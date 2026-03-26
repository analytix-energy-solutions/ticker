"""Action and snooze WebSocket commands for Ticker integration (F-5)."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    ACTION_TYPES,
    ACTION_TYPE_SCRIPT,
    ACTION_TYPE_SNOOZE,
    MAX_ACTIONS_PER_SET,
    SNOOZE_DURATIONS_MINUTES,
)
from .validation import get_store

_LOGGER = logging.getLogger(__name__)

SCRIPT_ENTITY_PATTERN = re.compile(r"^script\.[a-z0-9_]+$")


def _validate_action_set(action_set: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate an action_set structure.

    Returns (is_valid, error_message).
    """
    actions = action_set.get("actions", [])
    if not isinstance(actions, list):
        return False, "actions must be a list"

    if len(actions) > MAX_ACTIONS_PER_SET:
        return False, f"Maximum {MAX_ACTIONS_PER_SET} actions allowed"

    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            return False, f"Action {i} must be an object"

        title = action.get("title", "").strip()
        if not title:
            return False, f"Action {i}: title is required"

        action_type = action.get("type")
        if action_type not in ACTION_TYPES:
            return False, f"Action {i}: invalid type '{action_type}'"

        if action_type == ACTION_TYPE_SCRIPT:
            script_entity = action.get("script_entity", "")
            if not SCRIPT_ENTITY_PATTERN.match(script_entity):
                return False, f"Action {i}: invalid script entity '{script_entity}'"

        if action_type == ACTION_TYPE_SNOOZE:
            snooze_minutes = action.get("snooze_minutes")
            if snooze_minutes not in SNOOZE_DURATIONS_MINUTES:
                return (
                    False,
                    f"Action {i}: snooze_minutes must be one of {SNOOZE_DURATIONS_MINUTES}",
                )

        # Ensure index is set
        if "index" not in action:
            action["index"] = i

    return True, None


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
    """Set or clear action_set on a category."""
    store = get_store(hass)
    category_id = msg["category_id"]

    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"], "not_found", f"Category '{category_id}' not found"
        )
        return

    action_set = msg.get("action_set")

    if action_set is not None:
        is_valid, error = _validate_action_set(action_set)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_action_set", error)
            return

    category = await store.async_update_category_action_set(category_id, action_set)

    if category is None:
        connection.send_error(
            msg["id"], "not_found", f"Category '{category_id}' not found"
        )
        return

    connection.send_result(msg["id"], {"category": category})


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
