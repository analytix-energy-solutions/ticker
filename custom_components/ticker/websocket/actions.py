"""Action and snooze WebSocket commands for Ticker integration (F-5)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .validation import get_store, validate_action_set

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/category/set_action_set",
        vol.Required("category_id"): str,
        vol.Optional("action_set"): vol.Any(dict, None),
    }
)
@websocket_api.async_response
async def ws_set_action_set(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Backward-compatible shim: stores action set in library and links category."""
    store = get_store(hass)
    category_id = msg["category_id"]

    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"], "not_found", f"Category '{category_id}' not found"
        )
        return

    action_set = msg.get("action_set")

    # Validate if provided
    if action_set is not None:
        is_valid, error = validate_action_set(action_set)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_action_set", error)
            return

    # Create or update library entry, then link category
    library_id = f"{category_id}_actions"
    if action_set is not None:
        existing = store.get_action_set(library_id)
        if existing:
            await store.async_update_action_set(
                library_id, actions=action_set.get("actions", [])
            )
        else:
            cat = store.get_category(category_id)
            await store.async_create_action_set(
                library_id,
                name=f"{(cat or {}).get('name', category_id)} Actions",
                actions=action_set.get("actions", []),
            )
        # Link category to library entry
        result = await store.async_update_category(
            category_id, action_set_id=library_id
        )
    else:
        # Clear: unlink category from library
        result = await store.async_update_category(category_id, action_set_id="")

    if result is None:
        connection.send_error(
            msg["id"], "not_found", f"Category '{category_id}' not found"
        )
        return

    connection.send_result(msg["id"], {"category": result})


# --- Snooze management/debug endpoints ---
# These handlers expose snooze state for diagnostics and manual clearing.
# They are not yet wired into the frontend; a snooze management UI is planned
# as part of future user-panel work. Do not remove.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/snooze/get",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_snoozes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get active snoozes for a person."""
    store = get_store(hass)
    snoozes = store.get_snoozes_for_person(msg["person_id"])
    connection.send_result(msg["id"], {"snoozes": snoozes})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/snooze/clear",
        vol.Required("person_id"): str,
        vol.Required("category_id"): str,
    }
)
@websocket_api.async_response
async def ws_clear_snooze(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear a snooze for a person/category."""
    store = get_store(hass)
    cleared = await store.async_clear_snooze(msg["person_id"], msg["category_id"])
    connection.send_result(msg["id"], {"success": cleared})
