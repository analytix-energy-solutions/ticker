"""Recipient management WebSocket commands for Ticker integration (F-18).

Handles CRUD operations for non-user recipients (devices like TVs, TTS
speakers, tablets).

Test notification and notify service discovery commands are in
recipient_helpers.py (extracted to stay under the 500-line limit).
The set_recipient_subscription handler lives in recipient_subscriptions.py
(also extracted for the 500-line limit).
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
    MODE_ALWAYS,
    MODE_CONDITIONAL,
    TTS_BUFFER_DELAY_DEFAULT,
    TTS_BUFFER_DELAY_MAX,
    TTS_BUFFER_DELAY_MIN,
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
)
from .recipient_validation import (
    validate_by_device_type,
    validate_chime_length,
    validate_conditions_blob,
    validate_delivery_format,
    validate_notify_services,
)
from .validation import (
    get_store,
    validate_icon,
    validate_recipient_id,
    sanitize_for_storage,
)

_LOGGER = logging.getLogger(__name__)

# F-35.2: shared schema fragment for the volume_override field.
_VOLUME_SCHEMA = vol.Any(
    None,
    vol.All(
        vol.Coerce(float),
        vol.Range(min=VOLUME_OVERRIDE_MIN, max=VOLUME_OVERRIDE_MAX),
    ),
)


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
        vol.Optional("chime_media_content_id"): vol.Any(None, str),
        vol.Optional("volume_override"): _VOLUME_SCHEMA,
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
    is_valid, err_code, err_msg = validate_by_device_type(
        msg, device_type, require_notify_services=True,
    )
    if not is_valid:
        connection.send_error(msg["id"], err_code, err_msg)
        return

    # Validate delivery_format only for push devices
    if device_type == DEVICE_TYPE_PUSH:
        is_valid, error = validate_delivery_format(msg["delivery_format"])
        if not is_valid:
            connection.send_error(msg["id"], "invalid_delivery_format", error)
            return

    is_valid, error = validate_icon(msg["icon"])
    if not is_valid:
        connection.send_error(msg["id"], "invalid_icon", error)
        return

    # Validate conditions (BUG-093: empty dict normalizes to None).
    conditions, cond_err = validate_conditions_blob(msg.get("conditions"), hass)
    if cond_err:
        code, msg_text = cond_err
        connection.send_error(msg["id"], code, msg_text)
        return

    # F-35: validate chime_media_content_id length (if provided)
    chime_id = msg.get("chime_media_content_id")
    chime_err = validate_chime_length(chime_id)
    if chime_err:
        connection.send_error(msg["id"], chime_err[0], chime_err[1])
        return

    # F-35.2: volume_override — stored only on TTS recipients with an
    # in-range float. Push devices silently drop the field at the store
    # layer (mirrors chime_media_content_id behavior).
    volume_override = msg.get("volume_override")

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
            chime_media_content_id=chime_id,
            volume_override=volume_override,
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
        vol.Optional("chime_media_content_id"): vol.Any(None, str),
        vol.Optional("volume_override"): _VOLUME_SCHEMA,
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
            is_valid, error = validate_notify_services(msg["notify_services"])
            if not is_valid:
                connection.send_error(msg["id"], "invalid_notify_services", error)
                return
        kwargs["notify_services"] = msg["notify_services"]

    # Validate delivery_format only for push devices
    if "delivery_format" in msg:
        if device_type == DEVICE_TYPE_PUSH:
            is_valid, error = validate_delivery_format(msg["delivery_format"])
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
        cond_val, cond_err = validate_conditions_blob(msg["conditions"], hass)
        if cond_err:
            code, msg_text = cond_err
            connection.send_error(msg["id"], code, msg_text)
            return
        kwargs["conditions"] = cond_val

    # F-35: chime_media_content_id — present means update; None or "" clears.
    # Push-type recipients silently drop the value at the store layer.
    if "chime_media_content_id" in msg:
        chime_id = msg["chime_media_content_id"]
        chime_err = validate_chime_length(chime_id)
        if chime_err:
            connection.send_error(msg["id"], chime_err[0], chime_err[1])
            return
        if device_type == DEVICE_TYPE_TTS:
            kwargs["chime_media_content_id"] = chime_id
        else:
            _LOGGER.debug(
                "Dropping chime_media_content_id for non-TTS recipient %s",
                recipient_id,
            )

    # F-35.2: volume_override — present means update; None or out-of-range
    # clears via store. Push-type recipients silently drop the value at
    # the store layer.
    if "volume_override" in msg:
        vol_val = msg["volume_override"]
        if device_type == DEVICE_TYPE_TTS:
            kwargs["volume_override"] = vol_val
        else:
            _LOGGER.debug(
                "Dropping volume_override for non-TTS recipient %s",
                recipient_id,
            )

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
