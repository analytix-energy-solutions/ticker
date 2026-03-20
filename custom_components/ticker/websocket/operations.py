"""Test notification and migration WebSocket commands."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..discovery import async_get_notify_services_for_person
from ..const import MAX_MIGRATION_TITLE_LENGTH, MAX_MIGRATION_MESSAGE_LENGTH
from .validation import (
    sanitize_for_storage,
    validate_category_id,
    validate_entity_id,
    MAX_CATEGORY_NAME_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Test notification command
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/test_notification",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_test_notification(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send a test notification to a specific person."""
    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return

    # Get person name
    person_state = hass.states.get(person_id)
    person_name = person_state.attributes.get("friendly_name", person_id) if person_state else person_id

    # Get notify services (now returns list of dicts)
    notify_services = await async_get_notify_services_for_person(hass, person_id)

    if not notify_services:
        connection.send_error(
            msg["id"],
            "no_notify_services",
            f"No notify services found for {person_name}",
        )
        return

    # Send test notification
    results = []
    for service_info in notify_services:
        service = service_info["service"]
        service_name_display = service_info.get("name", service)
        domain, service_name = service.split(".", 1)

        try:
            await hass.services.async_call(
                domain,
                service_name,
                {
                    "title": "Ticker Test",
                    "message": f"Test notification for {person_name}. If you see this, notifications are working!",
                },
                blocking=True,
            )
            results.append({"service": service, "name": service_name_display, "success": True})
            _LOGGER.info("Test notification sent to %s via %s", person_id, service)
        except Exception as err:
            results.append({"service": service, "name": service_name_display, "success": False, "error": str(err)})
            _LOGGER.error("Test notification failed for %s via %s: %s", person_id, service, err)

    connection.send_result(msg["id"], {"results": results})


# =============================================================================
# Migration commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/scan",
    }
)
@websocket_api.async_response
async def ws_migrate_scan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Scan automations and scripts for notification service calls."""
    from ..migrate import async_scan_for_notifications

    try:
        findings = await async_scan_for_notifications(hass)
        connection.send_result(msg["id"], {"findings": findings})
    except Exception as err:
        _LOGGER.error("Migration scan failed: %s", err)
        connection.send_error(
            msg["id"],
            "scan_failed",
            str(err),
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/convert",
        vol.Required("finding"): dict,
        vol.Required("category_id"): str,
        vol.Required("category_name"): str,
        vol.Required("apply_directly"): bool,
        vol.Optional("title"): str,
        vol.Optional("message"): str,
    }
)
@websocket_api.async_response
async def ws_migrate_convert(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Convert a notification to use ticker.notify."""
    from ..migrate import async_convert_notification

    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    # Sanitize category_name
    category_name = sanitize_for_storage(msg["category_name"], MAX_CATEGORY_NAME_LENGTH)
    if not category_name:
        connection.send_error(msg["id"], "invalid_category_name", "Category name is required")
        return

    # Sanitize title and message if provided
    title = sanitize_for_storage(msg.get("title"), MAX_MIGRATION_TITLE_LENGTH) if msg.get("title") else None
    message = sanitize_for_storage(msg.get("message"), MAX_MIGRATION_MESSAGE_LENGTH) if msg.get("message") else None

    try:
        result = await async_convert_notification(
            hass=hass,
            finding=msg["finding"],
            category_id=category_id,
            category_name=category_name,
            apply_directly=msg["apply_directly"],
            title=title,
            message=message,
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _LOGGER.error("Migration conversion failed: %s", err)
        connection.send_error(
            msg["id"],
            "convert_failed",
            str(err),
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/delete",
        vol.Required("finding"): dict,
    }
)
@websocket_api.async_response
async def ws_migrate_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a duplicate notification action."""
    from ..migrate import async_delete_notification

    try:
        result = await async_delete_notification(
            hass=hass,
            finding=msg["finding"],
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _LOGGER.error("Migration deletion failed: %s", err)
        connection.send_error(
            msg["id"],
            "delete_failed",
            str(err),
        )
