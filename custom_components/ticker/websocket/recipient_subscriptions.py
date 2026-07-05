"""Recipient subscription WebSocket commands for Ticker integration.

F-18: ``ws_set_recipient_subscription`` (per-category mode).
F-39: ``ws_set_recipient_user_link`` (link/unlink a recipient to a person).

Extracted from recipients.py to comply with the 500-line hard limit.
Mirrors how subscriptions.py exists alongside the user-side handlers.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    MODE_ALWAYS,
    MODE_CONDITIONAL,
    MODE_NEVER,
    SET_BY_ADMIN,
)
from .validation import get_store, validate_category_id

# F-39: person entity IDs must start with "person.".
_PERSON_ID_PATTERN = re.compile(r"^person\.[a-z0-9_]+$")

_LOGGER = logging.getLogger(__name__)

RECIPIENT_SUBSCRIPTION_MODES = [MODE_ALWAYS, MODE_NEVER, MODE_CONDITIONAL]


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/set_recipient_subscription",
        vol.Required("recipient_id"): str,
        vol.Required("category_id"): str,
        vol.Required("mode"): vol.In(RECIPIENT_SUBSCRIPTION_MODES),
        vol.Optional("conditions"): dict,
    }
)
@websocket_api.async_response
async def ws_set_recipient_subscription(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set subscription mode for a recipient and category."""
    store = get_store(hass)

    recipient_id = msg["recipient_id"]
    if store.get_recipient(recipient_id) is None:
        connection.send_error(
            msg["id"], "recipient_not_found",
            f"Recipient '{recipient_id}' not found",
        )
        return

    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"], "category_not_found",
            f"Category '{category_id}' not found",
        )
        return

    person_id = f"recipient:{recipient_id}"
    conditions = msg.get("conditions")
    subscription = await store.async_set_subscription(
        person_id=person_id,
        category_id=category_id,
        mode=msg["mode"],
        conditions=conditions,
        set_by=SET_BY_ADMIN,
    )
    connection.send_result(msg["id"], {"subscription": subscription})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/set_recipient_user_link",
        vol.Required("recipient_id"): str,
        vol.Required("person_id"): vol.Any(None, str),
    }
)
@websocket_api.async_response
async def ws_set_recipient_user_link(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set or clear the user_link on a recipient (F-39, admin-only).

    When ``person_id`` is a string, it must match ``^person\\.`` AND resolve
    to a non-None state in HA. ``None`` clears the link (recipient reverts
    to Standalone — subscription rows are NOT modified here; that path is
    only used during orphan fallback in ``async_handle_person_removed``).
    """
    store = get_store(hass)

    recipient_id = msg["recipient_id"]
    if store.get_recipient(recipient_id) is None:
        connection.send_error(
            msg["id"], "recipient_not_found",
            f"Recipient '{recipient_id}' not found",
        )
        return

    person_id = msg["person_id"]
    if person_id is not None:
        if not isinstance(person_id, str) or not _PERSON_ID_PATTERN.match(person_id):
            connection.send_error(
                msg["id"], "invalid_person_id",
                "person_id must be a 'person.*' entity ID",
            )
            return
        if hass.states.get(person_id) is None:
            connection.send_error(
                msg["id"], "invalid_person_id",
                f"Person entity '{person_id}' not found",
            )
            return

    try:
        recipient = await store.async_set_recipient_user_link(
            recipient_id, person_id,
        )
    except ValueError as err:
        # Defensive — recipient existence already verified above.
        connection.send_error(msg["id"], "recipient_not_found", str(err))
        return

    connection.send_result(msg["id"], {"recipient": recipient})
