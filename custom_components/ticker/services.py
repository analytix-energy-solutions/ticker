"""Service handlers for Ticker integration.

NOTE (v1.8.2): This file intentionally exceeds the 500-line project limit.
The overage is an accepted waiver to land the merged community perf PR #50
(asyncio.gather fan-out of the person/recipient dispatch loops) without forcing
a hot-path refactor in the same change. Extracting the dispatch logic into a
dedicated dispatch.py module is the proper decongestion path (tracked as a
follow-up); do not squeeze this file under 500 by trimming working logic.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_set_service_schema

from homeassistant.util import dt as dt_util

from .category_validation import (
    CategoryFieldError,
    validate_and_sanitize_category_fields,
)
from .const import (
    DOMAIN,
    SERVICE_NOTIFY,
    SERVICE_ENSURE_CATEGORY,
    ATTR_CATEGORY,
    ATTR_TITLE,
    ATTR_MESSAGE,
    ATTR_EXPIRATION,
    ATTR_DATA,
    ATTR_ACTIONS,
    ATTR_ACTION_SET_ID,
    ATTR_CRITICAL,
    ATTR_NAVIGATE_TO,
    ATTR_CLEAR_WHEN,
    DEFAULT_EXPIRATION_HOURS,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    LOG_OUTCOME_SKIPPED,
    SMART_TAG_MODE_NONE,
)
from .service_schema import (
    _build_ensure_category_schema,
    _build_service_schema,
    _build_service_description,
)
from .websocket.validation import get_store
from .conditions import evaluate_condition_tree
from .formatting import build_smart_tag
from .user_notify import async_handle_conditional_notification, async_send_notification
from .recipient_notify import (
    async_send_to_recipient,
    async_handle_conditional_recipient,
    resolve_effective_subscription_pid,
)
from .sensor import get_category_sensor

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


def _get_loaded_entry(hass: HomeAssistant) -> "TickerConfigEntry":
    """Get a loaded Ticker config entry or raise ServiceValidationError."""
    entries = hass.config_entries.async_entries(DOMAIN)

    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_config_entry",
        )

    entry = entries[0]

    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
        )

    return entry


def _resolve_category_id(category_name: str, store: "TickerStore") -> str:
    """Resolve category name to category ID or raise ServiceValidationError."""
    # Check if it's already a valid category ID
    if store.category_exists(category_name):
        return category_name

    # Try to find by name
    categories = store.get_categories()
    for cat_id, cat_data in categories.items():
        if cat_data.get("name") == category_name:
            return cat_id

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_category",
        translation_placeholders={"category": category_name},
    )


def _get_person_name(hass: HomeAssistant, person_id: str) -> str:
    """Get friendly name for a person entity."""
    state = hass.states.get(person_id)
    if state:
        return state.attributes.get("friendly_name", person_id)
    return person_id


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Ticker services.

    Per IQS action-setup rule, services are registered in async_setup
    and check for loaded config entries at runtime.
    """

    async def async_handle_notify(call: ServiceCall) -> None:
        """Handle the ticker.notify service call.

        F-27: accepts a single category (string) or a list of categories.
        When a list is provided, the notification is fanned out to each
        category in turn, with a fresh notification_id per category so
        history correlation and action callbacks stay independent.
        """
        # Get loaded entry (raises ServiceValidationError if not available)
        entry = _get_loaded_entry(hass)
        store = entry.runtime_data.store

        category_input = call.data[ATTR_CATEGORY]
        title = call.data[ATTR_TITLE]
        message = call.data[ATTR_MESSAGE]
        expiration = call.data.get(ATTR_EXPIRATION, DEFAULT_EXPIRATION_HOURS)
        base_data = dict(call.data.get(ATTR_DATA, {}))
        actions_param = call.data.get(ATTR_ACTIONS)
        suppress_actions = actions_param == "none"
        # BUG-104: empty/whitespace -> None so the category default is used.
        action_set_id = (call.data.get(ATTR_ACTION_SET_ID) or "").strip() or None
        navigate_to = call.data.get(ATTR_NAVIGATE_TO)
        critical_override_present = ATTR_CRITICAL in call.data
        critical_override_value = call.data.get(ATTR_CRITICAL)
        # F-30: optional auto-clear trigger descriptor.
        clear_when = call.data.get(ATTR_CLEAR_WHEN)
        auto_clear_registry = getattr(entry.runtime_data, "auto_clear", None)

        # F-27: normalize category input to a de-duplicated list, preserving order.
        if isinstance(category_input, str):
            cats_input: list[str] = [category_input]
        else:
            cats_input = list(dict.fromkeys(category_input))

        if not cats_input:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_category",
                translation_placeholders={"category": ""},
            )

        # Hoist person discovery and recipient fetch above the per-category loop.
        persons = hass.states.async_all("person")
        recipients = store.get_recipients()

        processed_count = 0
        last_resolve_error: ServiceValidationError | None = None

        for cat_input in cats_input:
            # Resolve each category independently; on miss, log a warning
            # and continue to the next so a single bad ID does not abort the
            # entire fan-out.
            try:
                category_id = _resolve_category_id(cat_input, store)
            except ServiceValidationError as err:
                _LOGGER.warning(
                    "ticker.notify: skipping unknown category %r", cat_input
                )
                last_resolve_error = err
                continue

            # Per-category data copy so cross-category mutation (notably the
            # critical flag) cannot leak between iterations.
            data_for_cat = dict(base_data)

            # Resolve critical flag INSIDE the loop: per-call override wins,
            # otherwise fall back to this category's default.
            category = store.get_category(category_id)
            if critical_override_present:
                resolved_critical = critical_override_value
            else:
                resolved_critical = (category or {}).get("critical", False)
            if resolved_critical:
                data_for_cat["critical"] = True
            else:
                data_for_cat.pop("critical", None)

            # Fresh notification_id per category so history correlation and
            # action callbacks remain independent.
            notification_id = str(uuid.uuid4())

            _LOGGER.debug(
                "Processing notification for category '%s': %s "
                "(notification_id: %s)",
                category_id,
                title,
                notification_id,
            )

            dispatch_result = await _dispatch_to_category(
                hass=hass,
                store=store,
                category=category,
                category_id=category_id,
                title=title,
                message=message,
                data=data_for_cat,
                expiration=expiration,
                notification_id=notification_id,
                suppress_actions=suppress_actions,
                action_set_id=action_set_id,
                navigate_to=navigate_to,
                persons=persons,
                recipients=recipients,
            )
            processed_count += 1

            # F-30: auto-clear registration — one per category (each category
            # owns its own notification_id, delivered_services, and tag).
            if clear_when and auto_clear_registry and dispatch_result["delivered_services"]:
                await auto_clear_registry.register(
                    notification_id=dispatch_result["notification_id"],
                    clear_when=clear_when,
                    delivered_services=dispatch_result["delivered_services"],
                    tag=dispatch_result["tag"],
                )

        # F-27: if no category in the list resolved, surface the last error so
        # automations see a failure rather than a silent no-op.
        if processed_count == 0:
            if last_resolve_error is not None:
                raise last_resolve_error
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_category",
                translation_placeholders={"category": ""},
            )

    async def _dispatch_to_category(
        *,
        hass: HomeAssistant,
        store: "TickerStore",
        category: dict | None,
        category_id: str,
        title: str,
        message: str,
        data: dict,
        expiration: int,
        notification_id: str,
        suppress_actions: bool,
        action_set_id: str | None,
        navigate_to: str | None,
        persons: list,
        recipients: dict,
    ) -> dict:
        """Dispatch a single notification to one category's subscribers.

        Runs person loop, recipient loop, and category sensor update for one
        resolved category_id. Returns a dict with notification_id,
        delivered_services (flat notify.* list), and tag (smart-notif tag or
        None) — consumed by the F-30 auto-clear registration in the caller.
        """
        # Accumulate delivery results for sensor update
        delivery_results: dict[str, list[str]] = {
            "delivered": [],
            "queued": [],
            "dropped": [],
        }

        async def _process_person(person_state) -> None:
            person_id = person_state.entity_id
            person_name = person_state.attributes.get("friendly_name", person_id)

            # Check if user is enabled for notifications
            if not store.is_user_enabled(person_id):
                _LOGGER.debug("Skipping %s (user disabled)", person_id)
                return

            mode = store.get_subscription_mode(person_id, category_id)

            _LOGGER.debug(
                "Person %s subscription mode for %s: %s",
                person_id,
                category_id,
                mode,
            )

            if mode == MODE_NEVER:
                _LOGGER.debug("Skipping %s (mode: never)", person_id)
                await store.async_add_log(
                    category_id=category_id,
                    person_id=person_id,
                    person_name=person_name,
                    title=title,
                    message=message,
                    outcome=LOG_OUTCOME_SKIPPED,
                    reason="Subscription mode: never",
                    notification_id=notification_id,
                )
                delivery_results["dropped"].append(f"{person_id}: mode never")
                return

            if mode == MODE_ALWAYS:
                results = await async_send_notification(
                    hass, store, person_id, person_name, category_id, title, message,
                    data, notification_id=notification_id,
                    suppress_actions=suppress_actions,
                    action_set_id=action_set_id,
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

            elif mode == MODE_CONDITIONAL:
                results = await async_handle_conditional_notification(
                    hass=hass,
                    store=store,
                    person_id=person_id,
                    person_name=person_name,
                    person_state=person_state,
                    category_id=category_id,
                    title=title,
                    message=message,
                    data=data,
                    expiration=expiration,
                    notification_id=notification_id,
                    suppress_actions=suppress_actions,
                    action_set_id=action_set_id,
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

        # --- Recipient loop (F-18) ---
        # NOTE: `recipients` is passed in from the caller so the fetch is
        # hoisted above the F-27 per-category fan-out loop.
        async def _process_recipient(r_id, r_data) -> None:
            if not r_data.get("enabled", True):
                _LOGGER.debug("Skipping recipient %s (disabled)", r_id)
                return

            r_person_id = f"recipient:{r_id}"
            # F-21: Device-level condition gate (before subscription mode)
            device_conditions = r_data.get("conditions")
            if device_conditions and (
                device_conditions.get("rules")
                or device_conditions.get("condition_tree")
            ):
                # person_state=None: recipients have no location
                all_met, rule_results = evaluate_condition_tree(
                    hass, device_conditions, None,
                )
                if not all_met:
                    gate_reason = next(
                        (r for ok, r in rule_results if not ok),
                        "Conditions not met",
                    )
                    _LOGGER.debug(
                        "Skipping recipient %s (device conditions not met: %s)",
                        r_id,
                        gate_reason,
                    )
                    await store.async_add_log(
                        category_id=category_id,
                        person_id=r_person_id,
                        person_name=r_data.get("name", r_id),
                        title=title,
                        message=message,
                        outcome=LOG_OUTCOME_SKIPPED,
                        reason=f"Device conditions: {gate_reason}",
                        notification_id=notification_id,
                    )
                    delivery_results["dropped"].append(
                        f"{r_person_id}: device conditions not met"
                    )
                    return

            # F-39: swap effective person_id when user_link is set; logging
            # and queueing still use r_person_id (recipient attribution).
            sub_pid = resolve_effective_subscription_pid(r_data)
            r_mode = store.get_subscription_mode(sub_pid, category_id)
            _LOGGER.debug(
                "Recipient %s mode for %s: %s (effective_pid=%s)",
                r_id, category_id, r_mode, sub_pid,
            )
            if r_mode == MODE_NEVER:
                _LOGGER.debug("Skipping recipient %s (mode: never)", r_id)
                await store.async_add_log(
                    category_id=category_id,
                    person_id=r_person_id,
                    person_name=r_data.get("name", r_id),
                    title=title,
                    message=message,
                    outcome=LOG_OUTCOME_SKIPPED,
                    reason="Subscription mode: never",
                    notification_id=notification_id,
                )
                delivery_results["dropped"].append(f"{r_person_id}: mode never")
                return

            if r_mode == MODE_ALWAYS:
                results = await async_send_to_recipient(
                    hass, store, r_data, category_id, title, message, data,
                    notification_id=notification_id,
                    suppress_actions=suppress_actions,
                    action_set_id=action_set_id,
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

            elif r_mode == MODE_CONDITIONAL:
                results = await async_handle_conditional_recipient(
                    hass, store, r_data, category_id, title, message, data,
                    expiration,
                    notification_id=notification_id,
                    suppress_actions=suppress_actions,
                    action_set_id=action_set_id,
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

        # Fan out to all persons and recipients concurrently instead of
        # awaiting each sequentially. Each coroutine mutates the shared
        # delivery_results dict; asyncio is single-threaded so the list
        # extends are safe. return_exceptions=True keeps a failure in one
        # subscriber from aborting the rest of the fan-out.
        dispatch_tasks = [_process_person(ps) for ps in persons]
        dispatch_tasks += [
            _process_recipient(r_id, r_data)
            for r_id, r_data in recipients.items()
        ]
        for outcome in await asyncio.gather(
            *dispatch_tasks, return_exceptions=True
        ):
            if isinstance(outcome, Exception):
                _LOGGER.error("Notification dispatch task failed: %s", outcome)

        # Update category sensor with notification data
        sensor = get_category_sensor(hass, category_id)
        if sensor:
            # BUG-099: honor per-category expose_in_sensor flag. When False the
            # sensor still tracks count + last_triggered but blanks header/body
            # so recorder/history consumers cannot read raw notification content.
            expose_content = (category or {}).get("expose_in_sensor", True)
            sensor.async_add_notification(
                header=title,
                body=message,
                delivered=delivery_results["delivered"],
                queued=delivery_results["queued"],
                dropped=delivery_results["dropped"],
                priority="normal",
                timestamp=dt_util.utcnow().isoformat(),
                expose_content=expose_content,
            )

        # F-30: mirror formatting.inject_smart_notification's tag resolution
        # so the caller can register the auto-clear listener against the same
        # tag the device received. delivery_results["delivered"] holds raw
        # notify.* ids (see results["delivered"].append in user_notify /
        # recipient_notify) — we pass them through unmodified.
        smart_cfg = (category or {}).get("smart_notification") or {}
        tag_mode = smart_cfg.get("tag_mode", SMART_TAG_MODE_NONE)
        return {
            "notification_id": notification_id,
            "delivered_services": list(delivery_results["delivered"]),
            "tag": build_smart_tag(category_id, title, tag_mode),
        }

    async def async_handle_ensure_category(call: ServiceCall) -> dict:
        """Handle the ticker.ensure_category service call.

        Idempotent create-if-absent of a notification category so any
        integration/automation can declare categories declaratively. Validates
        identity first, fails soft before Ticker's entry loads, and never
        overwrites an existing category (create-only). Returns
        ``{"created": bool, "category_id": str}``.
        """
        # AC3: validate identity/fields first — bad input surfaces cleanly.
        try:
            kwargs = validate_and_sanitize_category_fields(call.data)
        except CategoryFieldError as err:
            raise ServiceValidationError(err.message) from err

        # AC4: fail-soft if Ticker's config entry has not loaded yet. Use
        # get_store (returns store or raises ValueError) rather than
        # _get_loaded_entry, which raises a user-facing ServiceValidationError.
        try:
            store = get_store(hass)
        except ValueError:
            _LOGGER.warning(
                "ticker.ensure_category called before Ticker is configured; "
                "ignoring"
            )
            return {"created": False, "category_id": kwargs["category_id"]}

        # AC2/AC6: no-op if it already exists — never overwrite or delete.
        if store.category_exists(kwargs["category_id"]):
            return {"created": False, "category_id": kwargs["category_id"]}

        # AC1: create with supplied attributes. async_create_category notifies
        # category listeners (update_service_schema), so the ticker.notify
        # dropdown refreshes automatically.
        await store.async_create_category(**kwargs)
        return {"created": True, "category_id": kwargs["category_id"]}

    hass.services.async_register(
        DOMAIN,
        SERVICE_NOTIFY,
        async_handle_notify,
        schema=_build_service_schema(),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ENSURE_CATEGORY,
        async_handle_ensure_category,
        schema=_build_ensure_category_schema(),
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Set initial service description (without store, uses defaults)
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_NOTIFY,
        _build_service_description(None),
    )

    _LOGGER.info("Ticker services registered")


def register_schema_updater(hass: HomeAssistant, entry: "TickerConfigEntry") -> None:
    """Register callback to update service schema when categories change.

    Called from async_setup_entry after store is initialized.
    """
    store = entry.runtime_data.store

    @callback
    def update_service_schema() -> None:
        """Update service schema when categories change."""
        async_set_service_schema(
            hass,
            DOMAIN,
            SERVICE_NOTIFY,
            _build_service_description(store, hass=hass),
        )
        _LOGGER.debug("Updated ticker.notify service schema with new categories")

    # Store the updater in runtime_data
    entry.runtime_data.update_service_schema = update_service_schema

    # Update schema now with current categories
    update_service_schema()

    # NOTE: Services are intentionally NOT unloaded when a config entry is
    # unloaded (per IQS action-setup rule). They remain registered and will
    # raise ServiceValidationError if called without a loaded entry.
