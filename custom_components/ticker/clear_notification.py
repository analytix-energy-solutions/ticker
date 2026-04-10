"""Clear notification service for Ticker (F-6).

Sends a clear_notification command to devices to dismiss previously sent
tagged notifications. Uses the same tag-building logic as the smart
notification system so that tags match between send and clear.

The HA Companion App convention: sending message "clear_notification"
with a matching tag removes that notification from the device.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema

import voluptuous as vol

from .const import (
    ATTR_CATEGORY,
    ATTR_TITLE,
    DOMAIN,
    MODE_NEVER,
    NOTIFY_SERVICE_TIMEOUT,
    SERVICE_CLEAR_NOTIFICATION,
    SMART_TAG_MODE_NONE,
    SMART_TAG_MODE_TITLE,
)
from .discovery import async_get_notify_services_for_person
from .formatting import build_smart_tag

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


def resolve_category_id(category_name: str, store: "TickerStore") -> str:
    """Resolve category name to category ID or raise ServiceValidationError.

    Checks if the input is already a valid category ID, then falls back
    to name-based lookup.

    Args:
        category_name: Category name or ID from the service call.
        store: Ticker data store.

    Returns:
        The resolved category ID.

    Raises:
        ServiceValidationError: If no matching category is found.
    """
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


def _build_clear_schema() -> vol.Schema:
    """Build the voluptuous schema for clear_notification."""
    return vol.Schema(
        {
            vol.Required(ATTR_CATEGORY): cv.string,
            vol.Optional(ATTR_TITLE): cv.string,
        }
    )


def _build_clear_description(store: "TickerStore | None") -> dict[str, Any]:
    """Build service description for clear_notification for the UI."""
    from .const import CATEGORY_DEFAULT_NAME

    if store:
        categories = store.get_categories()
        category_options = [cat["name"] for cat in categories.values()]
    else:
        category_options = [CATEGORY_DEFAULT_NAME]

    return {
        "name": "Clear notification",
        "description": (
            "Dismiss a previously sent tagged notification from all "
            "subscribed devices. Requires the category to have smart "
            "notification tag mode enabled."
        ),
        "fields": {
            ATTR_CATEGORY: {
                "name": "Category",
                "description": "The notification category to clear",
                "required": True,
                "selector": {
                    "select": {
                        "options": category_options,
                        "mode": "dropdown",
                    }
                },
            },
            ATTR_TITLE: {
                "name": "Title",
                "description": (
                    "The notification title. Required when the category "
                    "uses title-based tag mode so the correct tag can be "
                    "matched. Ignored for category-based tag mode."
                ),
                "required": False,
                "selector": {"text": {}},
            },
        },
    }


def _resolve_tag(
    category: dict[str, Any],
    category_id: str,
    title: str | None,
) -> str | None:
    """Resolve the tag to clear based on category smart_notification config.

    Args:
        category: Category dict from store.
        category_id: Category slug ID.
        title: Optional title for title-based tags.

    Returns:
        The tag string, or None if the category has no tag mode configured.
    """
    smart_config = category.get("smart_notification")
    if not smart_config:
        return None

    tag_mode = smart_config.get("tag_mode", SMART_TAG_MODE_NONE)
    return build_smart_tag(category_id, title, tag_mode)


async def _async_send_clear_to_services(
    hass: HomeAssistant,
    services: list[dict[str, Any]],
    tag: str,
    context_label: str,
) -> list[str]:
    """Send clear_notification to a list of notify services.

    Shared helper for both person-based and recipient-based clearing.

    Args:
        hass: Home Assistant instance.
        services: List of dicts with a 'service' key (e.g., 'notify.mobile_app_x').
        tag: The notification tag to clear.
        context_label: Human-readable label for log messages (e.g., person ID).

    Returns:
        List of service IDs that were successfully called.
    """
    cleared: list[str] = []

    for svc_entry in services:
        service_id = svc_entry.get("service", "")
        if not service_id or "." not in service_id:
            continue

        domain, service_name = service_id.split(".", 1)
        payload: dict[str, Any] = {
            "message": "clear_notification",
            "data": {"tag": tag},
        }

        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    domain, service_name, payload, blocking=True,
                ),
                timeout=NOTIFY_SERVICE_TIMEOUT,
            )
            cleared.append(service_id)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout clearing notification on %s for %s",
                service_id, context_label,
            )
        except Exception:
            _LOGGER.warning(
                "Failed to clear notification on %s for %s",
                service_id, context_label,
                exc_info=True,
            )

    return cleared


async def async_dispatch_clear(
    hass: HomeAssistant,
    services: list[str],
    tag: str,
    context_label: str,
) -> list[str]:
    """Public helper: dispatch a clear_notification to a flat list of services.

    F-30: Used by auto_clear.py to fire a clear against the exact notify
    services that received the original delivery. Wraps
    _async_send_clear_to_services which expects a list of dicts with a
    'service' key.

    Args:
        hass: Home Assistant instance.
        services: Flat list of notify service ids (e.g.,
            ['notify.mobile_app_phone']).
        tag: The notification tag to clear.
        context_label: Human-readable label for log messages.

    Returns:
        List of service ids successfully cleared.
    """
    svc_entries = [{"service": s} for s in services]
    return await _async_send_clear_to_services(hass, svc_entries, tag, context_label)


async def _async_clear_for_person(
    hass: HomeAssistant,
    person_id: str,
    tag: str,
) -> list[str]:
    """Send clear_notification to all notify services for a person.

    Args:
        hass: Home Assistant instance.
        person_id: Person entity ID.
        tag: The notification tag to clear.

    Returns:
        List of service IDs that were successfully called.
    """
    services = await async_get_notify_services_for_person(hass, person_id)
    return await _async_send_clear_to_services(hass, services, tag, person_id)


async def _async_clear_for_recipient(
    hass: HomeAssistant,
    recipient: dict[str, Any],
    tag: str,
) -> list[str]:
    """Send clear_notification to a push recipient's notify services.

    TTS and persistent recipients are skipped (no concept of clearing).

    Args:
        hass: Home Assistant instance.
        recipient: Recipient dict from store.
        tag: The notification tag to clear.

    Returns:
        List of service IDs that were successfully called.
    """
    from .const import DEVICE_TYPE_PUSH

    if recipient.get("device_type") != DEVICE_TYPE_PUSH:
        return []

    notify_services = recipient.get("notify_services", [])
    r_label = f"recipient:{recipient.get('recipient_id', 'unknown')}"
    return await _async_send_clear_to_services(hass, notify_services, tag, r_label)


async def async_handle_clear_notification(
    hass: HomeAssistant,
    store: TickerStore,
    call: ServiceCall,
) -> None:
    """Handle the ticker.clear_notification service call.

    Resolves the category and tag, then sends clear_notification to all
    subscribed persons and push recipients.

    Args:
        hass: Home Assistant instance.
        store: Ticker data store.
        call: The incoming service call.

    Raises:
        ServiceValidationError: If category is invalid or has no tag mode.
    """
    category_input = call.data[ATTR_CATEGORY]
    title = call.data.get(ATTR_TITLE)

    # Resolve category (raises ServiceValidationError if invalid)
    category_id = resolve_category_id(category_input, store)
    category = store.get_category(category_id)

    if not category:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_category",
            translation_placeholders={"category": category_input},
        )

    # Resolve the tag to clear
    tag = _resolve_tag(category, category_id, title)

    if not tag:
        _LOGGER.warning(
            "Category '%s' has no smart notification tag mode configured; "
            "clear_notification has no effect",
            category_id,
        )
        return

    # Title-based tag mode requires a title
    smart_config = category.get("smart_notification", {})
    if smart_config.get("tag_mode") == SMART_TAG_MODE_TITLE and not title:
        _LOGGER.warning(
            "Category '%s' uses title-based tag mode but no title was "
            "provided; clearing with partial tag",
            category_id,
        )

    _LOGGER.info(
        "Clearing notifications for category '%s' with tag '%s'",
        category_id, tag,
    )

    # F-30: drop any pending auto-clear listeners targeting this tag so they
    # cannot later fire against an already-dismissed notification.
    try:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries:
            runtime_data = getattr(entries[0], "runtime_data", None)
            registry = getattr(runtime_data, "auto_clear", None) if runtime_data else None
            if registry is not None:
                dropped = registry.unregister_by_tag(tag)
                if dropped:
                    _LOGGER.debug(
                        "auto_clear: dropped %d pending listener(s) for tag %s",
                        dropped, tag,
                    )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("auto_clear unregister_by_tag failed", exc_info=True)

    all_cleared: list[str] = []

    # Clear for all subscribed persons
    persons = hass.states.async_all("person")
    for person_state in persons:
        person_id = person_state.entity_id

        if not store.is_user_enabled(person_id):
            continue

        mode = store.get_subscription_mode(person_id, category_id)
        if mode == MODE_NEVER:
            continue

        cleared = await _async_clear_for_person(hass, person_id, tag)
        all_cleared.extend(cleared)

    # Clear for all subscribed push recipients
    recipients = store.get_recipients()
    for r_id, r_data in recipients.items():
        if not r_data.get("enabled", True):
            continue

        r_person_id = f"recipient:{r_id}"
        r_mode = store.get_subscription_mode(r_person_id, category_id)
        if r_mode == MODE_NEVER:
            continue

        cleared = await _async_clear_for_recipient(hass, r_data, tag)
        all_cleared.extend(cleared)

    _LOGGER.info(
        "Cleared notifications on %d service(s) for category '%s'",
        len(all_cleared), category_id,
    )


async def async_setup_clear_service(hass: HomeAssistant) -> None:
    """Register the ticker.clear_notification service.

    Encapsulates schema, description, and handler registration so that
    services.py can delegate with a single call.

    Args:
        hass: Home Assistant instance.
    """
    async def async_handle_clear(call: ServiceCall) -> None:
        """Handle the ticker.clear_notification service call."""
        from .services import _get_loaded_entry

        entry = _get_loaded_entry(hass)
        store = entry.runtime_data.store
        await async_handle_clear_notification(hass, store, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_NOTIFICATION,
        async_handle_clear,
        schema=_build_clear_schema(),
    )

    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CLEAR_NOTIFICATION,
        _build_clear_description(None),
    )


@callback
def register_clear_schema_updater(
    hass: HomeAssistant, store: "TickerStore",
) -> None:
    """Update the clear_notification service schema with current categories.

    Args:
        hass: Home Assistant instance.
        store: Ticker data store with current categories.
    """
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CLEAR_NOTIFICATION,
        _build_clear_description(store),
    )
