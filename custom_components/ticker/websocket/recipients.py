"""Recipient management WebSocket commands for Ticker integration (F-18).

Handles CRUD operations for non-user recipients (devices like TVs, TTS
speakers, tablets) and recipient subscription management.

Test notification and notify service discovery commands are in
recipient_helpers.py (extracted to stay under the 500-line limit).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    DEVICE_TYPES,
    DELIVERY_FORMAT_RICH,
    MAX_RECIPIENT_NAME_LENGTH,
    MAX_NOTIFY_SERVICES,
    MODE_ALWAYS,
    MODE_CONDITIONAL,
    MODE_NEVER,
    RECIPIENT_DELIVERY_FORMATS,
    SET_BY_ADMIN,
    TTS_BUFFER_DELAY_DEFAULT,
    TTS_BUFFER_DELAY_MAX,
    TTS_BUFFER_DELAY_MIN,
)
from .validation import (
    get_store,
    validate_category_id,
    validate_condition_tree,
    validate_icon,
    validate_recipient_id,
    sanitize_for_storage,
)

_LOGGER = logging.getLogger(__name__)

RECIPIENT_SUBSCRIPTION_MODES = [MODE_ALWAYS, MODE_NEVER, MODE_CONDITIONAL]


def _validate_notify_services(
    notify_services: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Validate notify_services list. Each entry needs a 'service' key.

    Called only for push-type recipients; TTS recipients skip this.
    """
    if not notify_services:
        return False, "At least one notify service is required"
    if len(notify_services) > MAX_NOTIFY_SERVICES:
        return False, f"Maximum {MAX_NOTIFY_SERVICES} notify services allowed"
    for idx, entry in enumerate(notify_services):
        if not isinstance(entry, dict):
            return False, f"Notify service {idx} must be an object"
        service = entry.get("service", "")
        if not isinstance(service, str) or not service.startswith("notify."):
            return False, f"Notify service {idx}: 'service' must start with 'notify.'"
    return True, None


def _validate_delivery_format(fmt: str) -> tuple[bool, str | None]:
    """Validate delivery format value against recipient-valid formats."""
    if fmt not in RECIPIENT_DELIVERY_FORMATS:
        return False, (
            f"Delivery format must be one of: "
            f"{', '.join(RECIPIENT_DELIVERY_FORMATS)}"
        )
    return True, None


def _validate_by_device_type(
    msg: dict[str, Any],
    device_type: str,
    require_notify_services: bool = True,
) -> tuple[bool, str, str | None]:
    """Validate fields conditionally based on device_type.

    For push: requires notify_services (if require_notify_services=True).
    For tts: requires media_player_entity_id.

    Args:
        msg: WebSocket message dict.
        device_type: 'push' or 'tts'.
        require_notify_services: Whether to require non-empty notify_services
            for push devices (True for create, False for update).

    Returns:
        Tuple of (is_valid, error_code, error_message).
    """
    if device_type == DEVICE_TYPE_TTS:
        entity_id = msg.get("media_player_entity_id")
        if not entity_id or not isinstance(entity_id, str):
            return (
                False, "invalid_media_player",
                "media_player_entity_id is required for TTS recipients",
            )
        if not entity_id.startswith("media_player."):
            return (
                False, "invalid_media_player",
                "media_player_entity_id must start with 'media_player.'",
            )
    elif device_type == DEVICE_TYPE_PUSH and require_notify_services:
        notify_services = msg.get("notify_services")
        if notify_services is not None:
            is_valid, error = _validate_notify_services(notify_services)
            if not is_valid:
                return False, "invalid_notify_services", error
        elif require_notify_services:
            return (
                False, "invalid_notify_services",
                "notify_services is required for push recipients",
            )

    return True, "", None


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "ticker/get_recipients"}
)
@websocket_api.async_response
async def ws_get_recipients(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all recipients with their subscriptions merged in."""
    store = get_store(hass)
    recipients = store.get_recipients()
    categories = store.get_categories()

    result = []
    for recipient_id, recipient in recipients.items():
        subs = store.get_subscriptions_for_recipient(recipient_id)
        subscription_map: dict[str, dict[str, Any]] = {}
        for cat_id in categories:
            if cat_id in subs:
                sub = subs[cat_id]
                entry: dict[str, Any] = {
                    "mode": sub.get("mode", MODE_ALWAYS),
                }
                if sub.get("mode") == MODE_CONDITIONAL:
                    entry["conditions"] = sub.get("conditions", {})
                subscription_map[cat_id] = entry
            else:
                category = categories[cat_id]
                default_mode = category.get("default_mode", MODE_ALWAYS)
                entry = {"mode": default_mode}
                if (default_mode == MODE_CONDITIONAL
                        and "default_conditions" in category):
                    entry["conditions"] = category["default_conditions"]
                subscription_map[cat_id] = entry
        result.append({**recipient, "subscriptions": subscription_map})

    connection.send_result(msg["id"], {"recipients": result})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/create_recipient",
        vol.Required("recipient_id"): str,
        vol.Required("name"): str,
        vol.Optional("device_type", default=DEVICE_TYPE_PUSH): vol.In(DEVICE_TYPES),
        vol.Optional("notify_services"): list,
        vol.Optional("delivery_format", default=DELIVERY_FORMAT_RICH): str,
        vol.Optional("media_player_entity_id"): str,
        vol.Optional("tts_service"): str,
        vol.Optional("icon", default="mdi:bell-ring"): str,
        vol.Optional("enabled", default=True): bool,
        vol.Optional("resume_after_tts", default=False): bool,
        vol.Optional("tts_buffer_delay", default=TTS_BUFFER_DELAY_DEFAULT): vol.All(
            vol.Coerce(float), vol.Range(min=TTS_BUFFER_DELAY_MIN, max=TTS_BUFFER_DELAY_MAX),
        ),
        vol.Optional("conditions"): vol.Any(dict, None),
    }
)
@websocket_api.async_response
async def ws_create_recipient(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new recipient."""
    store = get_store(hass)

    recipient_id = msg["recipient_id"]
    is_valid, error = validate_recipient_id(recipient_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_recipient_id", error)
        return

    if store.get_recipient(recipient_id) is not None:
        connection.send_error(
            msg["id"], "recipient_exists",
            f"Recipient '{recipient_id}' already exists",
        )
        return

    name = sanitize_for_storage(msg["name"], MAX_RECIPIENT_NAME_LENGTH)
    if not name:
        connection.send_error(msg["id"], "invalid_name", "Name is required")
        return

    device_type = msg.get("device_type", DEVICE_TYPE_PUSH)

    # Conditional validation based on device_type
    is_valid, err_code, err_msg = _validate_by_device_type(
        msg, device_type, require_notify_services=True,
    )
    if not is_valid:
        connection.send_error(msg["id"], err_code, err_msg)
        return

    # Validate delivery_format only for push devices
    if device_type == DEVICE_TYPE_PUSH:
        is_valid, error = _validate_delivery_format(msg["delivery_format"])
        if not is_valid:
            connection.send_error(msg["id"], "invalid_delivery_format", error)
            return

    is_valid, error = validate_icon(msg["icon"])
    if not is_valid:
        connection.send_error(msg["id"], "invalid_icon", error)
        return

    # Validate conditions structure if provided (accepts condition_tree or rules).
    # BUG-093: treat conditions={} same as conditions=None — empty dict is a
    # natural "no conditions" value and must normalize to None for storage.
    conditions = msg.get("conditions")
    if conditions and (conditions.get("condition_tree") or conditions.get("rules") is not None):
        tree = conditions.get("condition_tree")
        rules = conditions.get("rules")
        if tree:
            tree_error = validate_condition_tree(tree, hass)
            if tree_error:
                code, msg_text = tree_error
                connection.send_error(msg["id"], code, msg_text)
                return
        elif not isinstance(rules, list):
            connection.send_error(
                msg["id"], "invalid_conditions",
                "Conditions must contain 'condition_tree' or 'rules'",
            )
            return
    else:
        # Empty dict or None — store as None
        conditions = None

    try:
        recipient = await store.async_create_recipient(
            recipient_id=recipient_id,
            name=name,
            device_type=device_type,
            notify_services=msg.get("notify_services"),
            delivery_format=msg["delivery_format"],
            media_player_entity_id=msg.get("media_player_entity_id"),
            tts_service=msg.get("tts_service"),
            icon=msg["icon"],
            enabled=msg["enabled"],
            resume_after_tts=msg["resume_after_tts"],
            tts_buffer_delay=msg["tts_buffer_delay"],
            conditions=conditions,
        )
    except ValueError as err:
        connection.send_error(msg["id"], "create_failed", str(err))
        return

    connection.send_result(msg["id"], {"recipient": recipient})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/update_recipient",
        vol.Required("recipient_id"): str,
        vol.Optional("name"): str,
        vol.Optional("device_type"): vol.In(DEVICE_TYPES),
        vol.Optional("notify_services"): list,
        vol.Optional("delivery_format"): str,
        vol.Optional("media_player_entity_id"): str,
        vol.Optional("tts_service"): str,
        vol.Optional("icon"): str,
        vol.Optional("enabled"): bool,
        vol.Optional("resume_after_tts"): bool,
        vol.Optional("tts_buffer_delay"): vol.All(
            vol.Coerce(float), vol.Range(min=TTS_BUFFER_DELAY_MIN, max=TTS_BUFFER_DELAY_MAX),
        ),
        vol.Optional("conditions"): vol.Any(dict, None),
    }
)
@websocket_api.async_response
async def ws_update_recipient(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update recipient properties."""
    store = get_store(hass)

    recipient_id = msg["recipient_id"]
    existing = store.get_recipient(recipient_id)
    if existing is None:
        connection.send_error(
            msg["id"], "recipient_not_found",
            f"Recipient '{recipient_id}' not found",
        )
        return

    kwargs: dict[str, Any] = {}

    # Resolve effective device_type (may be changing in this update)
    device_type = msg.get("device_type", existing.get("device_type", DEVICE_TYPE_PUSH))

    if "device_type" in msg:
        kwargs["device_type"] = msg["device_type"]

    if "name" in msg:
        name = sanitize_for_storage(msg["name"], MAX_RECIPIENT_NAME_LENGTH)
        if not name:
            connection.send_error(msg["id"], "invalid_name", "Name is required")
            return
        kwargs["name"] = name

    # Validate notify_services only for push devices
    if "notify_services" in msg:
        if device_type == DEVICE_TYPE_PUSH:
            is_valid, error = _validate_notify_services(msg["notify_services"])
            if not is_valid:
                connection.send_error(msg["id"], "invalid_notify_services", error)
                return
        kwargs["notify_services"] = msg["notify_services"]

    # Validate delivery_format only for push devices
    if "delivery_format" in msg:
        if device_type == DEVICE_TYPE_PUSH:
            is_valid, error = _validate_delivery_format(msg["delivery_format"])
            if not is_valid:
                connection.send_error(msg["id"], "invalid_delivery_format", error)
                return
        kwargs["delivery_format"] = msg["delivery_format"]

    # TTS fields
    if "media_player_entity_id" in msg:
        entity_id = msg["media_player_entity_id"]
        if device_type == DEVICE_TYPE_TTS:
            if not entity_id or not entity_id.startswith("media_player."):
                connection.send_error(
                    msg["id"], "invalid_media_player",
                    "media_player_entity_id must start with 'media_player.'",
                )
                return
        kwargs["media_player_entity_id"] = entity_id

    if "tts_service" in msg:
        kwargs["tts_service"] = msg["tts_service"]

    if "icon" in msg:
        is_valid, error = validate_icon(msg["icon"])
        if not is_valid:
            connection.send_error(msg["id"], "invalid_icon", error)
            return
        kwargs["icon"] = msg["icon"]

    if "enabled" in msg:
        kwargs["enabled"] = msg["enabled"]

    if "resume_after_tts" in msg:
        kwargs["resume_after_tts"] = msg["resume_after_tts"]

    if "tts_buffer_delay" in msg:
        kwargs["tts_buffer_delay"] = msg["tts_buffer_delay"]

    # F-21: Device-level conditions (None clears via sparse storage).
    # BUG-093: empty dict normalizes to None, same as explicit None.
    if "conditions" in msg:
        cond_val = msg["conditions"]
        if cond_val and (cond_val.get("condition_tree") or cond_val.get("rules") is not None):
            tree = cond_val.get("condition_tree")
            rules = cond_val.get("rules")
            if tree:
                tree_error = validate_condition_tree(tree, hass)
                if tree_error:
                    code, msg_text = tree_error
                    connection.send_error(msg["id"], code, msg_text)
                    return
            elif not isinstance(rules, list):
                connection.send_error(
                    msg["id"], "invalid_conditions",
                    "Conditions must contain 'condition_tree' or 'rules'",
                )
                return
        else:
            cond_val = None
        kwargs["conditions"] = cond_val

    if not kwargs:
        connection.send_error(msg["id"], "no_fields", "No fields to update")
        return

    try:
        recipient = await store.async_update_recipient(recipient_id, **kwargs)
    except ValueError as err:
        connection.send_error(msg["id"], "update_failed", str(err))
        return

    connection.send_result(msg["id"], {"recipient": recipient})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/delete_recipient",
        vol.Required("recipient_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_recipient(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a recipient and all its subscriptions."""
    store = get_store(hass)
    deleted = await store.async_delete_recipient(msg["recipient_id"])
    if not deleted:
        connection.send_error(
            msg["id"], "recipient_not_found",
            f"Recipient '{msg['recipient_id']}' not found",
        )
        return
    connection.send_result(msg["id"], {"success": True})


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
