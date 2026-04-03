"""Action Sets Library WebSocket commands for Ticker integration (F-5b).

Provides CRUD endpoints for the reusable action sets library.
Categories reference library entries by action_set_id instead of
embedding inline action definitions.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    MAX_ACTION_SET_DESCRIPTION_LENGTH,
    MAX_ACTION_SET_ID_LENGTH,
    MAX_ACTION_SET_NAME_LENGTH,
)
from .validation import get_store, sanitize_for_storage, validate_action_set

_LOGGER = logging.getLogger(__name__)

ACTION_SET_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _validate_action_set_id(action_set_id: str) -> tuple[bool, str | None]:
    """Validate an action set ID slug.

    Returns:
        Tuple of (is_valid, error_message).
    """
    if not action_set_id:
        return False, "Action set ID is required"
    if len(action_set_id) > MAX_ACTION_SET_ID_LENGTH:
        return False, (
            f"Action set ID must be {MAX_ACTION_SET_ID_LENGTH} characters or less"
        )
    if not ACTION_SET_ID_PATTERN.match(action_set_id):
        return False, (
            "Action set ID must contain only lowercase letters, numbers, "
            "and underscores"
        )
    return True, None


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "ticker/action_sets/list"}
)
@websocket_api.async_response
async def ws_action_sets_list(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all action sets in the library."""
    store = get_store(hass)
    action_sets = store.get_action_sets()
    connection.send_result(
        msg["id"], {"action_sets": list(action_sets.values())}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/action_set/create",
        vol.Required("action_set_id"): str,
        vol.Required("name"): str,
        vol.Required("actions"): list,
        vol.Optional("description", default=""): str,
    }
)
@websocket_api.async_response
async def ws_action_set_create(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new action set in the library."""
    store = get_store(hass)

    action_set_id = msg["action_set_id"]
    is_valid, error = _validate_action_set_id(action_set_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_action_set_id", error)
        return

    name = sanitize_for_storage(msg["name"], MAX_ACTION_SET_NAME_LENGTH)
    if not name:
        connection.send_error(msg["id"], "invalid_name", "Name is required")
        return

    description = sanitize_for_storage(
        msg.get("description", ""), MAX_ACTION_SET_DESCRIPTION_LENGTH
    ) or ""

    # Validate actions structure
    is_valid, error = validate_action_set({"actions": msg["actions"]})
    if not is_valid:
        connection.send_error(msg["id"], "invalid_actions", error)
        return

    try:
        action_set = await store.async_create_action_set(
            action_set_id=action_set_id,
            name=name,
            actions=msg["actions"],
            description=description,
        )
    except ValueError as err:
        connection.send_error(msg["id"], "action_set_exists", str(err))
        return

    connection.send_result(msg["id"], {"action_set": action_set})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/action_set/update",
        vol.Required("action_set_id"): str,
        vol.Optional("name"): str,
        vol.Optional("actions"): list,
        vol.Optional("description"): str,
    }
)
@websocket_api.async_response
async def ws_action_set_update(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an existing action set."""
    store = get_store(hass)
    action_set_id = msg["action_set_id"]

    kwargs: dict[str, Any] = {}

    if "name" in msg:
        name = sanitize_for_storage(msg["name"], MAX_ACTION_SET_NAME_LENGTH)
        if not name:
            connection.send_error(
                msg["id"], "invalid_name", "Name is required"
            )
            return
        kwargs["name"] = name

    if "actions" in msg:
        is_valid, error = validate_action_set({"actions": msg["actions"]})
        if not is_valid:
            connection.send_error(msg["id"], "invalid_actions", error)
            return
        kwargs["actions"] = msg["actions"]

    if "description" in msg:
        kwargs["description"] = sanitize_for_storage(
            msg["description"], MAX_ACTION_SET_DESCRIPTION_LENGTH
        ) or ""

    if not kwargs:
        connection.send_error(
            msg["id"], "no_fields", "No fields to update"
        )
        return

    action_set = await store.async_update_action_set(action_set_id, **kwargs)
    if action_set is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Action set '{action_set_id}' not found",
        )
        return

    connection.send_result(msg["id"], {"action_set": action_set})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/action_set/delete",
        vol.Required("action_set_id"): str,
    }
)
@websocket_api.async_response
async def ws_action_set_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete an action set from the library."""
    store = get_store(hass)
    action_set_id = msg["action_set_id"]

    # Guard: refuse to delete if any category references this action set
    using_categories = store.is_action_set_in_use(action_set_id)
    if using_categories:
        connection.send_error(
            msg["id"],
            "action_set_in_use",
            f"Action set '{action_set_id}' is in use by categories: "
            f"{', '.join(using_categories)}",
        )
        return

    deleted = await store.async_delete_action_set(action_set_id)
    if not deleted:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Action set '{action_set_id}' not found",
        )
        return

    connection.send_result(msg["id"], {"success": True})
