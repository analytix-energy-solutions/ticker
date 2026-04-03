"""Queue, log, zone, device, and current person WebSocket commands."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import DEVICE_MODE_ALL, DEVICE_MODE_SELECTED, MAX_LOG_ENTRIES
from ..discovery import async_discover_notify_services
from .validation import (
    get_store,
    validate_category_id,
    validate_entity_id,
)

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Zone commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/zones",
    }
)
@websocket_api.async_response
async def ws_get_zones(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all available zones."""
    zones = []

    for state in hass.states.async_all("zone"):
        zones.append({
            "zone_id": state.entity_id,
            "name": state.attributes.get("friendly_name", state.entity_id),
            "icon": state.attributes.get("icon", "mdi:map-marker"),
        })

    zones.sort(key=lambda z: (0 if z["zone_id"] == "zone.home" else 1, z["name"].lower()))

    connection.send_result(msg["id"], {"zones": zones})


# =============================================================================
# Device commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/devices",
    }
)
@websocket_api.async_response
async def ws_get_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get discovered devices with friendly names for the current user."""
    user = connection.user
    if not user:
        connection.send_error(
            msg["id"],
            "no_user",
            "No user associated with this connection",
        )
        return

    user_id = user.id

    discovered_users = await async_discover_notify_services(hass)

    # Find the person for this user
    for person_id, user_data in discovered_users.items():
        if user_data.get("user_id") == user_id:
            # Return the notify services with their friendly names
            devices = user_data.get("notify_services", [])
            connection.send_result(msg["id"], {"devices": devices})
            return

    # No person found for this user
    connection.send_result(msg["id"], {"devices": []})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/device_preference/set",
        vol.Required("mode"): vol.In([DEVICE_MODE_ALL, DEVICE_MODE_SELECTED]),
        vol.Optional("devices"): [str],
    }
)
@websocket_api.async_response
async def ws_set_device_preference(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set device preference for the current user."""
    store = get_store(hass)

    user = connection.user
    if not user:
        connection.send_error(
            msg["id"],
            "no_user",
            "No user associated with this connection",
        )
        return

    user_id = user.id
    mode = msg["mode"]
    devices = msg.get("devices", [])

    # Validate: if mode is 'selected', devices cannot be empty
    if mode == DEVICE_MODE_SELECTED and not devices:
        connection.send_error(
            msg["id"],
            "empty_device_selection",
            "At least one device must be selected when using 'selected' mode",
        )
        return

    # Find the person for this user
    discovered_users = await async_discover_notify_services(hass)
    person_id = None
    discovered_services = set()

    for pid, user_data in discovered_users.items():
        if user_data.get("user_id") == user_id:
            person_id = pid
            discovered_services = {
                svc["service"] for svc in user_data.get("notify_services", [])
            }
            break

    if not person_id:
        connection.send_error(
            msg["id"],
            "no_person",
            "No person entity found for this user",
        )
        return

    # Validate that all selected devices exist in discovery
    if mode == DEVICE_MODE_SELECTED:
        for device_service in devices:
            if device_service not in discovered_services:
                connection.send_error(
                    msg["id"],
                    "invalid_device",
                    f"Device '{device_service}' not found",
                )
                return

    # Save the preference
    updated_user = await store.async_set_device_preference(
        person_id=person_id,
        mode=mode,
        devices=devices if mode == DEVICE_MODE_SELECTED else [],
    )

    connection.send_result(msg["id"], {
        "device_preference": updated_user.get("device_preference", {})
    })


# =============================================================================
# Current person command (for user panel)
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/current_person",
    }
)
@websocket_api.async_response
async def ws_get_current_person(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the person entity for the current logged-in HA user."""
    user = connection.user
    if not user:
        connection.send_error(
            msg["id"],
            "no_user",
            "No user associated with this connection",
        )
        return

    user_id = user.id

    discovered_users = await async_discover_notify_services(hass)

    for person_id, user_data in discovered_users.items():
        if user_data.get("user_id") == user_id:
            store = get_store(hass)
            stored_user = store.get_user(person_id)

            result = {
                **user_data,
                "enabled": stored_user.get("enabled", True) if stored_user else True,
                "device_preference": (
                    stored_user.get("device_preference", {"mode": DEVICE_MODE_ALL, "devices": []})
                    if stored_user else {"mode": DEVICE_MODE_ALL, "devices": []}
                ),
            }
            connection.send_result(msg["id"], {"person": result})
            return

    connection.send_result(msg["id"], {"person": None})


# =============================================================================
# Queue commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/queue",
        vol.Optional("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_queue(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get queued notifications, optionally filtered by person."""
    store = get_store(hass)

    person_id = msg.get("person_id")

    # Validate person_id if provided
    if person_id:
        is_valid, error = validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return

    if person_id:
        queue = store.get_queue_for_person(person_id)
    else:
        queue = list(store.get_queue().values())

    queue.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    connection.send_result(msg["id"], {"queue": queue})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/queue/clear",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_clear_queue(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear all queued notifications for a person."""
    store = get_store(hass)

    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return

    count = await store.async_clear_queue_for_person(person_id)

    connection.send_result(msg["id"], {"cleared": count})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/queue/remove",
        vol.Required("queue_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_queue_entry(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a single entry from the queue."""
    store = get_store(hass)

    # Validate queue_id (should be a UUID)
    queue_id = msg["queue_id"]
    if not queue_id or len(queue_id) > 50:
        connection.send_error(msg["id"], "invalid_queue_id", "Invalid queue ID")
        return

    success = await store.async_remove_from_queue(queue_id)

    if not success:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Queue entry '{queue_id}' not found",
        )
        return

    connection.send_result(msg["id"], {"success": True})


# =============================================================================
# Log commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs",
        vol.Optional("limit", default=MAX_LOG_ENTRIES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LOG_ENTRIES)
        ),
        vol.Optional("person_id"): str,
        vol.Optional("category_id"): str,
        vol.Optional("outcome"): str,
    }
)
@websocket_api.async_response
async def ws_get_logs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get notification logs with optional filters."""
    store = get_store(hass)

    person_id = msg.get("person_id")
    category_id = msg.get("category_id")
    outcome = msg.get("outcome")

    # Validate person_id if provided
    if person_id:
        is_valid, error = validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return

    # Validate category_id if provided
    if category_id:
        is_valid, error = validate_category_id(category_id)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_category_id", error)
            return

    # Validate outcome if provided (simple alphanumeric check)
    if outcome and not re.match(r"^[a-z_]+$", outcome):
        connection.send_error(msg["id"], "invalid_outcome", "Invalid outcome filter")
        return

    logs = store.get_logs(
        limit=msg.get("limit", MAX_LOG_ENTRIES),
        person_id=person_id,
        category_id=category_id,
        outcome=outcome,
    )

    connection.send_result(msg["id"], {"logs": logs})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs/stats",
    }
)
@websocket_api.async_response
async def ws_get_log_stats(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get log statistics."""
    store = get_store(hass)
    stats = store.get_log_stats()
    connection.send_result(msg["id"], {"stats": stats})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs/clear",
    }
)
@websocket_api.async_response
async def ws_clear_logs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear all logs."""
    store = get_store(hass)
    count = await store.async_clear_logs()
    connection.send_result(msg["id"], {"cleared": count})
