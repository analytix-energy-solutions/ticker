"""Category WebSocket commands for Ticker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    DOMAIN,
    MAX_CHIME_MEDIA_CONTENT_ID_LENGTH,
    MAX_NAVIGATE_TO_LENGTH,
    SMART_TAG_MODES,
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
)
from .validation import (
    get_store,
    sanitize_for_storage,
    validate_category_id,
    validate_color,
    validate_icon,
    validate_navigate_to,
    MAX_CATEGORY_NAME_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/categories",
    }
)
@websocket_api.async_response
async def ws_get_categories(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all categories."""
    store = get_store(hass)
    categories = store.get_categories()

    connection.send_result(
        msg["id"],
        {"categories": list(categories.values())},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/category/create",
        vol.Required("category_id"): str,
        vol.Required("name"): str,
        vol.Optional("icon"): str,
        vol.Optional("color"): str,
        vol.Optional("default_mode"): vol.In(["always", "never", "conditional"]),
        vol.Optional("default_conditions"): dict,
        vol.Optional("critical"): bool,
        vol.Optional("smart_notification"): vol.Any(
            None,
            vol.Schema({
                vol.Optional("group"): bool,
                vol.Optional("tag_mode"): vol.In(SMART_TAG_MODES),
                vol.Optional("sticky"): bool,
                vol.Optional("persistent"): bool,
            }),
        ),
        vol.Optional("action_set_id"): vol.Any(None, str),
        vol.Optional("navigate_to"): vol.Any(
            None, vol.All(str, vol.Length(min=1, max=MAX_NAVIGATE_TO_LENGTH))
        ),
        vol.Optional("expose_in_sensor"): bool,
        vol.Optional("chime_media_content_id"): vol.Any(None, str),
        vol.Optional("volume_override"): vol.Any(
            None,
            vol.All(
                vol.Coerce(float),
                vol.Range(min=VOLUME_OVERRIDE_MIN, max=VOLUME_OVERRIDE_MAX),
            ),
        ),
    }
)
@websocket_api.async_response
async def ws_create_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new category."""
    store = get_store(hass)

    # Validate and sanitize category_id
    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    # Sanitize name
    name = sanitize_for_storage(msg["name"], MAX_CATEGORY_NAME_LENGTH)
    if not name:
        connection.send_error(msg["id"], "invalid_name", "Category name is required")
        return

    # Validate and sanitize icon
    icon = msg.get("icon")
    is_valid, error = validate_icon(icon)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_icon", error)
        return

    # Validate color
    color = msg.get("color")
    is_valid, error = validate_color(color)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_color", error)
        return

    if store.category_exists(category_id):
        connection.send_error(
            msg["id"],
            "already_exists",
            f"Category '{category_id}' already exists",
        )
        return

    default_mode = msg.get("default_mode")
    default_conditions = msg.get("default_conditions")
    critical = msg.get("critical", False)

    smart_notification = msg.get("smart_notification")
    action_set_id = msg.get("action_set_id")
    navigate_to = sanitize_for_storage(msg.get("navigate_to"), MAX_NAVIGATE_TO_LENGTH)
    # BUG-100: enforce relative HA path, block javascript: / https:// etc.
    is_valid, error = validate_navigate_to(navigate_to)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_navigate_to", error)
        return
    expose_in_sensor = msg.get("expose_in_sensor") if "expose_in_sensor" in msg else None

    # F-35: validate chime_media_content_id length
    chime_id = msg.get("chime_media_content_id")
    if chime_id is not None and isinstance(chime_id, str):
        if len(chime_id) > MAX_CHIME_MEDIA_CONTENT_ID_LENGTH:
            connection.send_error(
                msg["id"], "invalid_chime",
                f"chime_media_content_id exceeds "
                f"{MAX_CHIME_MEDIA_CONTENT_ID_LENGTH} characters",
            )
            return

    # F-35.2: volume_override — pass through to store. Voluptuous already
    # validated the range; store enforces sparse storage.
    volume_override = msg.get("volume_override")

    category = await store.async_create_category(
        category_id=category_id,
        name=name,
        icon=icon,
        color=color,
        default_mode=default_mode,
        default_conditions=default_conditions,
        critical=critical,
        smart_notification=smart_notification,
        action_set_id=action_set_id,
        navigate_to=navigate_to,
        expose_in_sensor=expose_in_sensor,
        chime_media_content_id=chime_id,
        volume_override=volume_override,
    )

    connection.send_result(msg["id"], {"category": category})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/category/update",
        vol.Required("category_id"): str,
        vol.Optional("name"): str,
        vol.Optional("icon"): str,
        vol.Optional("color"): vol.Any(str, None),
        vol.Optional("default_mode"): vol.Any(vol.In(["always", "never", "conditional"]), None),
        vol.Optional("default_conditions"): vol.Any(dict, None),
        vol.Optional("critical"): bool,
        vol.Optional("smart_notification"): vol.Any(
            None,
            vol.Schema({
                vol.Optional("group"): bool,
                vol.Optional("tag_mode"): vol.In(SMART_TAG_MODES),
                vol.Optional("sticky"): bool,
                vol.Optional("persistent"): bool,
            }),
        ),
        vol.Optional("action_set_id"): vol.Any(None, str),
        vol.Optional("navigate_to"): vol.Any(
            None, vol.All(str, vol.Length(max=MAX_NAVIGATE_TO_LENGTH))
        ),
        vol.Optional("expose_in_sensor"): bool,
        vol.Optional("chime_media_content_id"): vol.Any(None, str),
        vol.Optional("volume_override"): vol.Any(
            None,
            vol.All(
                vol.Coerce(float),
                vol.Range(min=VOLUME_OVERRIDE_MIN, max=VOLUME_OVERRIDE_MAX),
            ),
        ),
    }
)
@websocket_api.async_response
async def ws_update_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an existing category."""
    store = get_store(hass)

    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"],
            "not_found",
            f"Category '{category_id}' not found",
        )
        return

    # Sanitize name if provided
    name = None
    if "name" in msg and msg["name"] is not None:
        name = sanitize_for_storage(msg["name"], MAX_CATEGORY_NAME_LENGTH)
        if not name:
            connection.send_error(
                msg["id"], "invalid_name", "Category name cannot be empty"
            )
            return

    # Validate icon if provided
    icon = msg.get("icon")
    if icon is not None:
        is_valid, error = validate_icon(icon)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_icon", error)
            return

    # Validate color if provided
    color = msg.get("color")
    if color is not None:
        is_valid, error = validate_color(color)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_color", error)
            return

    default_mode = msg.get("default_mode")
    default_conditions = msg.get("default_conditions")
    # clear_defaults when default_mode is explicitly set to None
    clear_defaults = "default_mode" in msg and msg["default_mode"] is None
    critical = msg.get("critical") if "critical" in msg else None

    smart_notification = msg.get("smart_notification") if "smart_notification" in msg else None
    clear_smart_notification = (
        "smart_notification" in msg and msg["smart_notification"] is None
    )
    action_set_id = msg.get("action_set_id") if "action_set_id" in msg else None
    navigate_to = msg.get("navigate_to") if "navigate_to" in msg else None
    if navigate_to:
        navigate_to = sanitize_for_storage(navigate_to, MAX_NAVIGATE_TO_LENGTH)
    # BUG-100: validate (None / empty string pass through to clear field)
    if "navigate_to" in msg:
        is_valid, error = validate_navigate_to(navigate_to)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_navigate_to", error)
            return
    expose_in_sensor = msg.get("expose_in_sensor") if "expose_in_sensor" in msg else None

    # F-35: chime_media_content_id — only forwarded when key is present in msg.
    # None or "" clears the override; non-empty sets it. Length-validated here.
    chime_id_present = "chime_media_content_id" in msg
    chime_id = msg.get("chime_media_content_id") if chime_id_present else None
    if chime_id_present and chime_id is not None and isinstance(chime_id, str):
        if len(chime_id) > MAX_CHIME_MEDIA_CONTENT_ID_LENGTH:
            connection.send_error(
                msg["id"], "invalid_chime",
                f"chime_media_content_id exceeds "
                f"{MAX_CHIME_MEDIA_CONTENT_ID_LENGTH} characters",
            )
            return

    # F-35.2: volume_override — present with None clears the key, present
    # with a numeric value sets it. Voluptuous already enforced range.
    volume_present = "volume_override" in msg
    volume_value = msg.get("volume_override") if volume_present else None

    update_kwargs: dict[str, Any] = dict(
        category_id=category_id,
        name=name,
        icon=icon,
        color=color,
        default_mode=default_mode,
        default_conditions=default_conditions,
        clear_defaults=clear_defaults,
        critical=critical,
        smart_notification=smart_notification,
        clear_smart_notification=clear_smart_notification,
        action_set_id=action_set_id,
        navigate_to=navigate_to,
        expose_in_sensor=expose_in_sensor,
    )
    if chime_id_present:
        # Pass empty string to explicitly clear; non-empty to set
        update_kwargs["chime_media_content_id"] = chime_id if chime_id else ""
    if volume_present:
        if volume_value is None:
            update_kwargs["clear_volume_override"] = True
        else:
            update_kwargs["volume_override"] = volume_value

    category = await store.async_update_category(**update_kwargs)

    # Update service schema if name changed
    if name:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries and hasattr(entries[0], "runtime_data") and entries[0].runtime_data:
            update_fn = entries[0].runtime_data.update_service_schema
            if update_fn:
                update_fn()

    connection.send_result(msg["id"], {"category": category})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/category/delete",
        vol.Required("category_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a category."""
    store = get_store(hass)

    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"],
            "not_found",
            f"Category '{category_id}' not found",
        )
        return

    if store.is_default_category(category_id):
        connection.send_error(
            msg["id"],
            "cannot_delete_default",
            "Cannot delete the default 'General' category",
        )
        return

    await store.async_delete_category(category_id)

    connection.send_result(msg["id"], {"success": True})
