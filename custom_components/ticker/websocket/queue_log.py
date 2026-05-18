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
    _resolve_caller_person_id,
    get_store,
    require_admin_for_cross_person,
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
        vol.Optional("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_device_preference(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set device preference for a person.

    F-38 Decision 15: optional admin-only ``person_id`` targets another
    user. When omitted, the caller's own person is used. Non-admin callers
    passing a foreign ``person_id`` receive ``forbidden``.
    """
    store = get_store(hass)

    mode = msg["mode"]
    devices = msg.get("devices", [])
    requested_pid = msg.get("person_id")

    # Validate: if mode is 'selected', devices cannot be empty
    if mode == DEVICE_MODE_SELECTED and not devices:
        connection.send_error(
            msg["id"],
            "empty_device_selection",
            "At least one device must be selected when using 'selected' mode",
        )
        return

    # F-38 §6.4: admin gate for cross-user writes.
    ok, caller_pid = await require_admin_for_cross_person(
        hass, connection, msg, requested_pid
    )
    if not ok:
        return
    target_person_id = requested_pid or caller_pid

    if not target_person_id:
        connection.send_error(
            msg["id"],
            "no_person",
            "No person entity found for this user",
        )
        return

    # Validate that all selected devices exist in discovery for target person
    if mode == DEVICE_MODE_SELECTED:
        discovered_users = await async_discover_notify_services(hass)
        target_data = discovered_users.get(target_person_id)
        discovered_services = {
            svc["service"]
            for svc in (target_data or {}).get("notify_services", [])
        }
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
        person_id=target_person_id,
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

    # BUG-108: gate cross-user read on admin-or-self. When a non-admin caller
    # omits person_id, substitute their own so the handler does not fall
    # through to the household-wide branch and leak other users' entries.
    ok, caller_pid = await require_admin_for_cross_person(
        hass, connection, msg, person_id
    )
    if not ok:
        return

    if not person_id and not connection.user.is_admin:
        if caller_pid is None:
            connection.send_error(
                msg["id"], "forbidden", "Caller has no linked person"
            )
            return
        person_id = caller_pid

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

    # BUG-108: gate cross-user write on admin-or-self
    ok, _ = await require_admin_for_cross_person(hass, connection, msg, person_id)
    if not ok:
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

    # BUG-108: look up the entry's owner and gate on admin-or-self.
    # The handler takes only queue_id, so we must resolve the target
    # person_id from the queue entry itself before deciding access.
    entry = store.get_queue().get(queue_id)
    if entry is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Queue entry '{queue_id}' not found",
        )
        return

    entry_person_id = entry.get("person_id")
    user = connection.user
    is_admin = bool(user and user.is_admin)
    if not is_admin:
        # Collapse the cross-user info leak: a non-admin caller cannot
        # distinguish "entry exists but owned by someone else" from
        # "entry doesn't exist". Both return not_found.
        caller_pid = await _resolve_caller_person_id(hass, connection)
        if entry_person_id != caller_pid:
            connection.send_error(
                msg["id"],
                "not_found",
                f"Queue entry '{queue_id}' not found",
            )
            return
    else:
        ok, _ = await require_admin_for_cross_person(
            hass, connection, msg, entry_person_id
        )
        if not ok:
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

    # BUG-108: gate cross-user read on admin-or-self. When a non-admin caller
    # omits person_id, substitute their own so the handler does not return
    # logs across the entire household (even when filtering by category).
    ok, caller_pid = await require_admin_for_cross_person(
        hass, connection, msg, person_id
    )
    if not ok:
        return

    if not person_id and not connection.user.is_admin:
        if caller_pid is None:
            connection.send_error(
                msg["id"], "forbidden", "Caller has no linked person"
            )
            return
        person_id = caller_pid

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
