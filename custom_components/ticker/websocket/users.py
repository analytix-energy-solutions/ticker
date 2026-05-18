"""User management WebSocket commands for Ticker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import DEVICE_MODE_ALL
from ..discovery import async_discover_notify_services
from .validation import get_store, validate_entity_id

_LOGGER = logging.getLogger(__name__)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/users",
    }
)
@websocket_api.async_response
async def ws_get_users(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all persons with their discovered notify services and settings."""
    store = get_store(hass)

    discovered_users = await async_discover_notify_services(hass)

    result = []
    for person_id, user_data in discovered_users.items():
        stored_user = store.get_user(person_id)

        merged = {
            **user_data,
            "enabled": stored_user.get("enabled", True) if stored_user else True,
            "notify_services_override": (
                stored_user.get("notify_services_override", [])
                if stored_user
                else []
            ),
            "device_preference": (
                stored_user.get(
                    "device_preference", {"mode": DEVICE_MODE_ALL, "devices": []}
                )
                if stored_user
                else {"mode": DEVICE_MODE_ALL, "devices": []}
            ),
        }
        result.append(merged)

    connection.send_result(msg["id"], {"users": result})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/user/set_enabled",
        vol.Required("person_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_user_enabled(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Enable or disable a user for notifications."""
    store = get_store(hass)

    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return

    enabled = msg["enabled"]

    user = await store.async_set_user_enabled(person_id, enabled)

    connection.send_result(msg["id"], {"user": user})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/get_person",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_person(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get a single person by id (admin-only, F-38 §6.5).

    Mirrors the merge shape of ``ticker/current_person`` but resolves the
    target via the explicit ``person_id`` rather than the caller's HA user.
    Returns ``{"person": None}`` when the id is not present in discovery.
    """
    person_id = msg["person_id"]

    discovered_users = await async_discover_notify_services(hass)
    user_data = discovered_users.get(person_id)
    if user_data is None:
        connection.send_result(msg["id"], {"person": None})
        return

    store = get_store(hass)
    stored_user = store.get_user(person_id)

    result = {
        **user_data,
        "enabled": stored_user.get("enabled", True) if stored_user else True,
        "device_preference": (
            stored_user.get(
                "device_preference", {"mode": DEVICE_MODE_ALL, "devices": []}
            )
            if stored_user
            else {"mode": DEVICE_MODE_ALL, "devices": []}
        ),
    }
    connection.send_result(msg["id"], {"person": result})
