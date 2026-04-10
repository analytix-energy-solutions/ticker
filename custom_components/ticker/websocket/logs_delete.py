"""F-32 History Management — log entry deletion WebSocket commands.

Provides the delete endpoints for individual log entries, notification
groups, and per-person clears. Kept in a separate module so that
``queue_log.py`` stays under the 500-line file budget.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..discovery import async_discover_notify_services
from .validation import get_store, validate_entity_id

_LOGGER = logging.getLogger(__name__)


async def _resolve_caller_person_id(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection
) -> str | None:
    """Return the person_id owned by the WS caller, or None."""
    user = connection.user
    if not user:
        return None
    discovered = await async_discover_notify_services(hass)
    for pid, user_data in discovered.items():
        if user_data.get("user_id") == user.id:
            return pid
    return None


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs/remove",
        vol.Required("log_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_log_entry(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a single log entry by log_id (F-32, admin-only)."""
    store = get_store(hass)
    log_id = msg["log_id"]
    if not log_id or len(log_id) > 64:
        connection.send_error(msg["id"], "invalid_log_id", "Invalid log ID")
        return

    success = await store.async_remove_log_entry(log_id)
    if not success:
        connection.send_error(
            msg["id"], "not_found", f"Log entry '{log_id}' not found"
        )
        return
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs/remove_group",
        vol.Required("notification_id"): str,
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_log_group(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove all log entries for a notification_id/person_id pair (F-32).

    Admins may target any person; non-admin callers may only target their
    own person_id (resolved via notify discovery).
    """
    store = get_store(hass)
    notification_id = msg["notification_id"]
    person_id = msg["person_id"]

    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return
    if not notification_id or len(notification_id) > 64:
        connection.send_error(
            msg["id"], "invalid_notification_id", "Invalid notification ID"
        )
        return

    user = connection.user
    if not (user and user.is_admin):
        caller_person_id = await _resolve_caller_person_id(hass, connection)
        if caller_person_id != person_id:
            connection.send_error(
                msg["id"], "forbidden", "Cannot modify another user's history"
            )
            return

    removed = await store.async_remove_log_group(notification_id, person_id)
    connection.send_result(msg["id"], {"removed": removed})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/logs/clear_for_person",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_clear_logs_for_person(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear all log entries for a specific person (F-32).

    Admins may clear any person; non-admin callers may only clear their own.
    """
    store = get_store(hass)
    person_id = msg["person_id"]

    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return

    user = connection.user
    if not (user and user.is_admin):
        caller_person_id = await _resolve_caller_person_id(hass, connection)
        if caller_person_id != person_id:
            connection.send_error(
                msg["id"], "forbidden", "Cannot modify another user's history"
            )
            return

    removed = await store.async_clear_logs_for_person(person_id)
    connection.send_result(msg["id"], {"cleared": removed})
