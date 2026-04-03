"""Service handlers for Ticker integration."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_set_service_schema

from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SERVICE_NOTIFY,
    ATTR_CATEGORY,
    ATTR_TITLE,
    ATTR_MESSAGE,
    ATTR_EXPIRATION,
    ATTR_DATA,
    ATTR_ACTIONS,
    ATTR_CRITICAL,
    ATTR_NAVIGATE_TO,
    DEFAULT_EXPIRATION_HOURS,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    LOG_OUTCOME_SKIPPED,
)
from .service_schema import _build_service_schema, _build_service_description
from .conditions import evaluate_condition_tree
from .user_notify import async_handle_conditional_notification, async_send_notification
from .recipient_notify import (
    async_send_to_recipient,
    async_handle_conditional_recipient,
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
        """Handle the ticker.notify service call."""
        # Get loaded entry (raises ServiceValidationError if not available)
        entry = _get_loaded_entry(hass)
        store = entry.runtime_data.store

        category_input = call.data[ATTR_CATEGORY]
        title = call.data[ATTR_TITLE]
        message = call.data[ATTR_MESSAGE]
        expiration = call.data.get(ATTR_EXPIRATION, DEFAULT_EXPIRATION_HOURS)
        data = dict(call.data.get(ATTR_DATA, {}))
        actions_param = call.data.get(ATTR_ACTIONS)
        suppress_actions = actions_param == "none"
        navigate_to = call.data.get(ATTR_NAVIGATE_TO)

        # Resolve category (raises ServiceValidationError if invalid)
        category_id = _resolve_category_id(category_input, store)

        # Resolve critical flag: per-call wins if explicitly set,
        # otherwise fall back to category default
        category = store.get_category(category_id)
        if ATTR_CRITICAL in call.data:
            resolved_critical = call.data[ATTR_CRITICAL]
        else:
            resolved_critical = (category or {}).get("critical", False)
        if resolved_critical:
            data["critical"] = True
        else:
            data.pop("critical", None)

        # Generate a unique ID for this notification call to group log entries
        notification_id = str(uuid.uuid4())

        _LOGGER.info(
            "Processing notification for category '%s': %s (notification_id: %s)",
            category_id,
            title,
            notification_id,
        )

        persons = hass.states.async_all("person")

        # Accumulate delivery results for sensor update
        delivery_results: dict[str, list[str]] = {
            "delivered": [],
            "queued": [],
            "dropped": [],
        }

        for person_state in persons:
            person_id = person_state.entity_id
            person_name = person_state.attributes.get("friendly_name", person_id)

            # Check if user is enabled for notifications
            if not store.is_user_enabled(person_id):
                _LOGGER.debug("Skipping %s (user disabled)", person_id)
                continue

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
                continue

            if mode == MODE_ALWAYS:
                results = await async_send_notification(
                    hass, store, person_id, person_name, category_id, title, message,
                    data, notification_id=notification_id,
                    suppress_actions=suppress_actions,
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
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

        # --- Recipient loop (F-18) ---
        recipients = store.get_recipients()
        for r_id, r_data in recipients.items():
            if not r_data.get("enabled", True):
                _LOGGER.debug("Skipping recipient %s (disabled)", r_id)
                continue

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
                    continue

            r_mode = store.get_subscription_mode(r_person_id, category_id)

            _LOGGER.debug(
                "Recipient %s subscription mode for %s: %s",
                r_id, category_id, r_mode,
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
                continue

            if r_mode == MODE_ALWAYS:
                results = await async_send_to_recipient(
                    hass, store, r_data, category_id, title, message, data,
                    notification_id=notification_id,
                    suppress_actions=suppress_actions,
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
                    navigate_to=navigate_to,
                )
                delivery_results["delivered"].extend(results["delivered"])
                delivery_results["queued"].extend(results["queued"])
                delivery_results["dropped"].extend(results["dropped"])

        # Update category sensor with notification data
        sensor = get_category_sensor(hass, category_id)
        if sensor:
            sensor.async_add_notification(
                header=title,
                body=message,
                delivered=delivery_results["delivered"],
                queued=delivery_results["queued"],
                dropped=delivery_results["dropped"],
                priority="normal",
                timestamp=dt_util.utcnow().isoformat(),
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_NOTIFY,
        async_handle_notify,
        schema=_build_service_schema(),
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
