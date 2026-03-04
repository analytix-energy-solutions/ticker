"""WebSocket API for Ticker integration."""

from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, SUBSCRIPTION_MODES, MODE_CONDITIONAL, MODE_NEVER, SET_BY_USER, SET_BY_ADMIN, DEVICE_MODE_ALL, DEVICE_MODE_SELECTED
from .discovery import async_discover_notify_services

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Maximum lengths for user inputs
MAX_CATEGORY_ID_LENGTH = 64
MAX_CATEGORY_NAME_LENGTH = 100
MAX_ICON_LENGTH = 64
MAX_COLOR_LENGTH = 20

# Valid patterns
CATEGORY_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
ICON_PATTERN = re.compile(r"^[a-z0-9_\-:]+$", re.IGNORECASE)
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


# =============================================================================
# Input sanitization helpers
# =============================================================================

def _sanitize_string(value: str | None, max_length: int = 200) -> str | None:
    """Sanitize a string by removing/escaping dangerous characters.
    
    - Strips leading/trailing whitespace
    - Removes null bytes
    - Escapes HTML special characters
    - Truncates to max_length
    """
    if value is None:
        return None
    
    if not isinstance(value, str):
        value = str(value)
    
    # Strip whitespace and remove null bytes
    value = value.strip().replace("\x00", "")
    
    # Escape HTML special characters to prevent XSS
    value = (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
    
    # Truncate to max length
    if len(value) > max_length:
        value = value[:max_length]
    
    return value


def _validate_category_id(category_id: str) -> tuple[bool, str | None]:
    """Validate a category ID.
    
    Returns (is_valid, error_message).
    Valid IDs: lowercase alphanumeric and underscores only.
    """
    if not category_id:
        return False, "Category ID is required"
    
    if len(category_id) > MAX_CATEGORY_ID_LENGTH:
        return False, f"Category ID must be {MAX_CATEGORY_ID_LENGTH} characters or less"
    
    if not CATEGORY_ID_PATTERN.match(category_id):
        return False, "Category ID must contain only lowercase letters, numbers, and underscores"
    
    return True, None


def _validate_icon(icon: str | None) -> tuple[bool, str | None]:
    """Validate an icon string.
    
    Returns (is_valid, error_message).
    Valid icons: alphanumeric, underscores, hyphens, and colons (for mdi:icon format).
    """
    if icon is None:
        return True, None
    
    if len(icon) > MAX_ICON_LENGTH:
        return False, f"Icon must be {MAX_ICON_LENGTH} characters or less"
    
    if not ICON_PATTERN.match(icon):
        return False, "Icon must be in format 'mdi:icon-name'"
    
    return True, None


def _validate_color(color: str | None) -> tuple[bool, str | None]:
    """Validate a color string.
    
    Returns (is_valid, error_message).
    Valid colors: hex format #RRGGBB.
    """
    if color is None:
        return True, None
    
    if len(color) > MAX_COLOR_LENGTH:
        return False, f"Color must be {MAX_COLOR_LENGTH} characters or less"
    
    if not COLOR_PATTERN.match(color):
        return False, "Color must be in hex format (#RRGGBB)"
    
    return True, None


def _validate_entity_id(entity_id: str, domain: str) -> tuple[bool, str | None]:
    """Validate an entity ID.
    
    Returns (is_valid, error_message).
    """
    if not entity_id:
        return False, f"{domain} entity ID is required"
    
    if not entity_id.startswith(f"{domain}."):
        return False, f"Invalid {domain} entity ID format"
    
    # Basic format check: domain.object_id with safe characters
    if not re.match(r"^[a-z_]+\.[a-z0-9_]+$", entity_id):
        return False, f"Invalid {domain} entity ID format"
    
    return True, None


async def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Set up the Ticker WebSocket API."""
    websocket_api.async_register_command(hass, ws_get_categories)
    websocket_api.async_register_command(hass, ws_create_category)
    websocket_api.async_register_command(hass, ws_update_category)
    websocket_api.async_register_command(hass, ws_delete_category)
    websocket_api.async_register_command(hass, ws_get_users)
    websocket_api.async_register_command(hass, ws_set_user_enabled)
    websocket_api.async_register_command(hass, ws_get_subscriptions)
    websocket_api.async_register_command(hass, ws_set_subscription)
    websocket_api.async_register_command(hass, ws_get_zones)
    websocket_api.async_register_command(hass, ws_get_current_person)
    websocket_api.async_register_command(hass, ws_get_queue)
    websocket_api.async_register_command(hass, ws_clear_queue)
    websocket_api.async_register_command(hass, ws_remove_queue_entry)
    websocket_api.async_register_command(hass, ws_get_logs)
    websocket_api.async_register_command(hass, ws_get_log_stats)
    websocket_api.async_register_command(hass, ws_clear_logs)
    websocket_api.async_register_command(hass, ws_test_notification)
    websocket_api.async_register_command(hass, ws_migrate_scan)
    websocket_api.async_register_command(hass, ws_migrate_convert)
    websocket_api.async_register_command(hass, ws_migrate_delete)
    websocket_api.async_register_command(hass, ws_get_devices)
    websocket_api.async_register_command(hass, ws_set_device_preference)
    _LOGGER.info("Ticker WebSocket API registered")


def _get_store(hass: HomeAssistant) -> "TickerStore":
    """Get the Ticker store from the config entry runtime data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("Ticker integration not configured")
    entry = entries[0]
    if not hasattr(entry, 'runtime_data') or entry.runtime_data is None:
        raise ValueError("Ticker integration not loaded")
    return entry.runtime_data.store


# =============================================================================
# Category commands
# =============================================================================

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
    store = _get_store(hass)
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
    }
)
@websocket_api.async_response
async def ws_create_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new category."""
    store = _get_store(hass)
    
    # Validate and sanitize category_id
    category_id = msg["category_id"]
    is_valid, error = _validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return
    
    # Sanitize name
    name = _sanitize_string(msg["name"], MAX_CATEGORY_NAME_LENGTH)
    if not name:
        connection.send_error(msg["id"], "invalid_name", "Category name is required")
        return
    
    # Validate and sanitize icon
    icon = msg.get("icon")
    is_valid, error = _validate_icon(icon)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_icon", error)
        return
    
    # Validate color
    color = msg.get("color")
    is_valid, error = _validate_color(color)
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
    
    category = await store.async_create_category(
        category_id=category_id,
        name=name,
        icon=icon,
        color=color,
    )
    
    connection.send_result(msg["id"], {"category": category})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/category/update",
        vol.Required("category_id"): str,
        vol.Optional("name"): str,
        vol.Optional("icon"): str,
        vol.Optional("color"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_update_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an existing category."""
    store = _get_store(hass)
    
    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = _validate_category_id(category_id)
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
        name = _sanitize_string(msg["name"], MAX_CATEGORY_NAME_LENGTH)
        if not name:
            connection.send_error(msg["id"], "invalid_name", "Category name cannot be empty")
            return
    
    # Validate icon if provided
    icon = msg.get("icon")
    if icon is not None:
        is_valid, error = _validate_icon(icon)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_icon", error)
            return
    
    # Validate color if provided
    color = msg.get("color")
    if color is not None:
        is_valid, error = _validate_color(color)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_color", error)
            return
    
    category = await store.async_update_category(
        category_id=category_id,
        name=name,
        icon=icon,
        color=color,
    )
    
    # Update service schema if name changed
    if name:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries and hasattr(entries[0], 'runtime_data') and entries[0].runtime_data:
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
    store = _get_store(hass)
    
    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = _validate_category_id(category_id)
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


# =============================================================================
# User commands
# =============================================================================

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
    store = _get_store(hass)
    
    discovered_users = await async_discover_notify_services(hass)
    
    result = []
    for person_id, user_data in discovered_users.items():
        stored_user = store.get_user(person_id)
        
        merged = {
            **user_data,
            "enabled": stored_user.get("enabled", True) if stored_user else True,
            "notify_services_override": (
                stored_user.get("notify_services_override", []) 
                if stored_user else []
            ),
            "device_preference": (
                stored_user.get("device_preference", {"mode": DEVICE_MODE_ALL, "devices": []})
                if stored_user else {"mode": DEVICE_MODE_ALL, "devices": []}
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
    store = _get_store(hass)
    
    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = _validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return
    
    enabled = msg["enabled"]
    
    user = await store.async_set_user_enabled(person_id, enabled)
    
    connection.send_result(msg["id"], {"user": user})


# =============================================================================
# Subscription commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/subscriptions",
        vol.Optional("person_id"): str,
        vol.Optional("category_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_subscriptions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get subscriptions, optionally filtered by person or category."""
    store = _get_store(hass)
    
    person_id = msg.get("person_id")
    category_id = msg.get("category_id")
    
    # Validate person_id if provided
    if person_id:
        is_valid, error = _validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return
    
    # Validate category_id if provided
    if category_id:
        is_valid, error = _validate_category_id(category_id)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_category_id", error)
            return
    
    if person_id:
        subscriptions = store.get_subscriptions_for_person(person_id)
        result = list(subscriptions.values())
    elif category_id:
        result = store.get_subscriptions_for_category(category_id)
    else:
        all_categories = store.get_categories()
        result = []
        for cat_id in all_categories:
            result.extend(store.get_subscriptions_for_category(cat_id))
    
    connection.send_result(msg["id"], {"subscriptions": result})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/subscription/set",
        vol.Required("person_id"): str,
        vol.Required("category_id"): str,
        vol.Required("mode"): vol.In(SUBSCRIPTION_MODES),
        vol.Optional("conditions"): dict,
        vol.Optional("device_override"): dict,
    }
)
@websocket_api.async_response
async def ws_set_subscription(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set subscription mode for a person and category."""
    store = _get_store(hass)
    
    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = _validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return
    
    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = _validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return
    
    mode = msg["mode"]
    conditions = msg.get("conditions")
    device_override = msg.get("device_override")
    
    # Validate conditions if provided
    if conditions:
        zones = conditions.get("zones", {})
        for zone_id in zones.keys():
            is_valid, error = _validate_entity_id(zone_id, "zone")
            if not is_valid:
                connection.send_error(msg["id"], "invalid_zone", error)
                return
            
            # Check zone actually exists in Home Assistant
            if not hass.states.get(zone_id):
                connection.send_error(
                    msg["id"],
                    "zone_not_found",
                    f"Zone '{zone_id}' does not exist",
                )
                return
    
    # Validate device_override if provided
    if device_override:
        if mode == MODE_NEVER:
            # Device override not applicable for 'never' mode
            connection.send_error(
                msg["id"],
                "invalid_device_override",
                "Device override cannot be set for 'never' mode",
            )
            return
        
        devices = device_override.get("devices", [])
        if device_override.get("enabled") and devices:
            # Validate that devices exist in discovery
            discovered_users = await async_discover_notify_services(hass)
            person_data = discovered_users.get(person_id, {})
            discovered_services = {
                svc["service"] for svc in person_data.get("notify_services", [])
            }
            
            for device_service in devices:
                if device_service not in discovered_services:
                    connection.send_error(
                        msg["id"],
                        "invalid_device",
                        f"Device '{device_service}' not found for this person",
                    )
                    return
    
    if not store.category_exists(category_id):
        connection.send_error(
            msg["id"],
            "category_not_found",
            f"Category '{category_id}' not found",
        )
        return
    
    if mode == MODE_CONDITIONAL and not conditions:
        connection.send_error(
            msg["id"],
            "conditions_required",
            "Conditions are required for conditional mode",
        )
        return
    
    # Determine set_by: check if caller is modifying their own subscription
    # If the caller's HA user is linked to the target person, it's a user action
    # Otherwise, it's an admin action
    set_by = SET_BY_ADMIN  # Default to admin
    caller_user = connection.user
    if caller_user:
        # Get the user_id linked to the target person
        discovered_users = await async_discover_notify_services(hass)
        target_user_data = discovered_users.get(person_id, {})
        target_user_id = target_user_data.get("user_id")
        
        if target_user_id and target_user_id == caller_user.id:
            set_by = SET_BY_USER
    
    subscription = await store.async_set_subscription(
        person_id=person_id,
        category_id=category_id,
        mode=mode,
        conditions=conditions,
        set_by=set_by,
        device_override=device_override,
    )
    
    connection.send_result(msg["id"], {"subscription": subscription})


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
    }
)
@websocket_api.async_response
async def ws_set_device_preference(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set device preference for the current user."""
    store = _get_store(hass)
    
    user = connection.user
    if not user:
        connection.send_error(
            msg["id"],
            "no_user",
            "No user associated with this connection",
        )
        return
    
    user_id = user.id
    mode = msg["mode"]
    devices = msg.get("devices", [])
    
    # Validate: if mode is 'selected', devices cannot be empty
    if mode == DEVICE_MODE_SELECTED and not devices:
        connection.send_error(
            msg["id"],
            "empty_device_selection",
            "At least one device must be selected when using 'selected' mode",
        )
        return
    
    # Find the person for this user
    discovered_users = await async_discover_notify_services(hass)
    person_id = None
    discovered_services = set()
    
    for pid, user_data in discovered_users.items():
        if user_data.get("user_id") == user_id:
            person_id = pid
            discovered_services = {
                svc["service"] for svc in user_data.get("notify_services", [])
            }
            break
    
    if not person_id:
        connection.send_error(
            msg["id"],
            "no_person",
            "No person entity found for this user",
        )
        return
    
    # Validate that all selected devices exist in discovery
    if mode == DEVICE_MODE_SELECTED:
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
        person_id=person_id,
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
            store = _get_store(hass)
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
    store = _get_store(hass)
    
    person_id = msg.get("person_id")
    
    # Validate person_id if provided
    if person_id:
        is_valid, error = _validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return
    
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
    store = _get_store(hass)
    
    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = _validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
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
    store = _get_store(hass)
    
    # Validate queue_id (should be a UUID)
    queue_id = msg["queue_id"]
    if not queue_id or len(queue_id) > 50:
        connection.send_error(msg["id"], "invalid_queue_id", "Invalid queue ID")
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
        vol.Optional("limit", default=100): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=500)
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
    store = _get_store(hass)
    
    person_id = msg.get("person_id")
    category_id = msg.get("category_id")
    outcome = msg.get("outcome")
    
    # Validate person_id if provided
    if person_id:
        is_valid, error = _validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return
    
    # Validate category_id if provided
    if category_id:
        is_valid, error = _validate_category_id(category_id)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_category_id", error)
            return
    
    # Validate outcome if provided (simple alphanumeric check)
    if outcome and not re.match(r"^[a-z_]+$", outcome):
        connection.send_error(msg["id"], "invalid_outcome", "Invalid outcome filter")
        return
    
    logs = store.get_logs(
        limit=msg.get("limit", 100),
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
    store = _get_store(hass)
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
    store = _get_store(hass)
    count = await store.async_clear_logs()
    connection.send_result(msg["id"], {"cleared": count})


# =============================================================================
# Test notification command
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/test_notification",
        vol.Required("person_id"): str,
    }
)
@websocket_api.async_response
async def ws_test_notification(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send a test notification to a specific person."""
    from .discovery import async_get_notify_services_for_person
    
    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = _validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return
    
    # Get person name
    person_state = hass.states.get(person_id)
    person_name = person_state.attributes.get("friendly_name", person_id) if person_state else person_id
    
    # Get notify services (now returns list of dicts)
    notify_services = await async_get_notify_services_for_person(hass, person_id)
    
    if not notify_services:
        connection.send_error(
            msg["id"],
            "no_notify_services",
            f"No notify services found for {person_name}",
        )
        return
    
    # Send test notification
    results = []
    for service_info in notify_services:
        service = service_info["service"]
        service_name_display = service_info.get("name", service)
        domain, service_name = service.split(".", 1)
        
        try:
            await hass.services.async_call(
                domain,
                service_name,
                {
                    "title": "Ticker Test",
                    "message": f"Test notification for {person_name}. If you see this, notifications are working!",
                },
                blocking=True,
            )
            results.append({"service": service, "name": service_name_display, "success": True})
            _LOGGER.info("Test notification sent to %s via %s", person_id, service)
        except Exception as err:
            results.append({"service": service, "name": service_name_display, "success": False, "error": str(err)})
            _LOGGER.error("Test notification failed for %s via %s: %s", person_id, service, err)
    
    connection.send_result(msg["id"], {"results": results})


# =============================================================================
# Migration commands
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/scan",
    }
)
@websocket_api.async_response
async def ws_migrate_scan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Scan automations and scripts for notification service calls."""
    from .migrate import async_scan_for_notifications
    
    try:
        findings = await async_scan_for_notifications(hass)
        connection.send_result(msg["id"], {"findings": findings})
    except Exception as err:
        _LOGGER.error("Migration scan failed: %s", err)
        connection.send_error(
            msg["id"],
            "scan_failed",
            str(err),
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/convert",
        vol.Required("finding"): dict,
        vol.Required("category_id"): str,
        vol.Required("category_name"): str,
        vol.Required("apply_directly"): bool,
        vol.Optional("title"): str,
        vol.Optional("message"): str,
    }
)
@websocket_api.async_response
async def ws_migrate_convert(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Convert a notification to use ticker.notify."""
    from .migrate import async_convert_notification
    
    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = _validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return
    
    # Sanitize category_name
    category_name = _sanitize_string(msg["category_name"], MAX_CATEGORY_NAME_LENGTH)
    if not category_name:
        connection.send_error(msg["id"], "invalid_category_name", "Category name is required")
        return
    
    # Sanitize title and message if provided
    title = _sanitize_string(msg.get("title"), 200) if msg.get("title") else None
    message = _sanitize_string(msg.get("message"), 1000) if msg.get("message") else None
    
    try:
        result = await async_convert_notification(
            hass=hass,
            finding=msg["finding"],
            category_id=category_id,
            category_name=category_name,
            apply_directly=msg["apply_directly"],
            title=title,
            message=message,
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _LOGGER.error("Migration conversion failed: %s", err)
        connection.send_error(
            msg["id"],
            "convert_failed",
            str(err),
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/migrate/delete",
        vol.Required("finding"): dict,
    }
)
@websocket_api.async_response
async def ws_migrate_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a duplicate notification action."""
    from .migrate import async_delete_notification
    
    try:
        result = await async_delete_notification(
            hass=hass,
            finding=msg["finding"],
        )
        connection.send_result(msg["id"], result)
    except Exception as err:
        _LOGGER.error("Migration deletion failed: %s", err)
        connection.send_error(
            msg["id"],
            "delete_failed",
            str(err),
        )
