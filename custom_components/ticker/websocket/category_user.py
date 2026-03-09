"""Category, user, and subscription WebSocket commands."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    DOMAIN,
    SUBSCRIPTION_MODES,
    MODE_CONDITIONAL,
    MODE_NEVER,
    SET_BY_USER,
    SET_BY_ADMIN,
    DEVICE_MODE_ALL,
)
from ..discovery import async_discover_notify_services
from .validation import (
    get_store,
    sanitize_string,
    validate_category_id,
    validate_color,
    validate_entity_id,
    validate_icon,
    MAX_CATEGORY_NAME_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


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
    name = sanitize_string(msg["name"], MAX_CATEGORY_NAME_LENGTH)
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
        name = sanitize_string(msg["name"], MAX_CATEGORY_NAME_LENGTH)
        if not name:
            connection.send_error(msg["id"], "invalid_name", "Category name cannot be empty")
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
    store = get_store(hass)

    person_id = msg.get("person_id")
    category_id = msg.get("category_id")

    # Validate person_id if provided
    if person_id:
        is_valid, error = validate_entity_id(person_id, "person")
        if not is_valid:
            connection.send_error(msg["id"], "invalid_person_id", error)
            return

    # Validate category_id if provided
    if category_id:
        is_valid, error = validate_category_id(category_id)
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
    store = get_store(hass)

    # Validate person_id
    person_id = msg["person_id"]
    is_valid, error = validate_entity_id(person_id, "person")
    if not is_valid:
        connection.send_error(msg["id"], "invalid_person_id", error)
        return

    # Validate category_id
    category_id = msg["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        connection.send_error(msg["id"], "invalid_category_id", error)
        return

    mode = msg["mode"]
    conditions = msg.get("conditions")
    device_override = msg.get("device_override")

    # Validate conditions if provided
    if conditions:
        # Support both legacy zones format and new rules format
        rules = conditions.get("rules", [])
        zones = conditions.get("zones", {})

        # Validate legacy zones format
        for zone_id in zones.keys():
            is_valid, error = validate_entity_id(zone_id, "zone")
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

        # Validate new rules format (F-2 Advanced Conditions)
        valid_rule_types = ["zone", "time", "state"]
        for idx, rule in enumerate(rules):
            rule_type = rule.get("type")

            if rule_type not in valid_rule_types:
                connection.send_error(
                    msg["id"],
                    "invalid_rule_type",
                    f"Rule {idx}: invalid type '{rule_type}'",
                )
                return

            if rule_type == "zone":
                zone_id = rule.get("zone_id", "")
                is_valid, error = validate_entity_id(zone_id, "zone")
                if not is_valid:
                    connection.send_error(msg["id"], "invalid_zone", f"Rule {idx}: {error}")
                    return
                if not hass.states.get(zone_id):
                    connection.send_error(
                        msg["id"],
                        "zone_not_found",
                        f"Rule {idx}: Zone '{zone_id}' does not exist",
                    )
                    return

            elif rule_type == "time":
                after = rule.get("after", "")
                before = rule.get("before", "")
                if not after or not before:
                    connection.send_error(
                        msg["id"],
                        "invalid_time_rule",
                        f"Rule {idx}: 'after' and 'before' are required for time rules",
                    )
                    return
                # Validate time format HH:MM
                for time_val, name in [(after, "after"), (before, "before")]:
                    try:
                        parts = time_val.split(":")
                        hour = int(parts[0])
                        minute = int(parts[1])
                        if not (0 <= hour <= 23 and 0 <= minute <= 59):
                            raise ValueError("Invalid time values")
                    except (ValueError, IndexError):
                        connection.send_error(
                            msg["id"],
                            "invalid_time_format",
                            f"Rule {idx}: '{name}' must be in HH:MM format",
                        )
                        return
                # Validate days if provided
                days = rule.get("days", [])
                if days:
                    for day in days:
                        if not isinstance(day, int) or not (1 <= day <= 7):
                            connection.send_error(
                                msg["id"],
                                "invalid_day",
                                f"Rule {idx}: days must be integers 1-7 (Mon-Sun)",
                            )
                            return

            elif rule_type == "state":
                entity_id = rule.get("entity_id", "")
                state_val = rule.get("state", "")
                if not entity_id:
                    connection.send_error(
                        msg["id"],
                        "invalid_state_rule",
                        f"Rule {idx}: 'entity_id' is required for state rules",
                    )
                    return
                if not state_val:
                    connection.send_error(
                        msg["id"],
                        "invalid_state_rule",
                        f"Rule {idx}: 'state' is required for state rules",
                    )
                    return
                # Check entity exists
                if not hass.states.get(entity_id):
                    connection.send_error(
                        msg["id"],
                        "entity_not_found",
                        f"Rule {idx}: Entity '{entity_id}' does not exist",
                    )
                    return

            # Ensure at least one action is set per rule
            if not rule.get("deliver_when_met") and not rule.get("queue_until_met"):
                connection.send_error(
                    msg["id"],
                    "invalid_rule_actions",
                    f"Rule {idx}: At least one of 'deliver_when_met' or 'queue_until_met' must be true",
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

    if mode == MODE_CONDITIONAL:
        if not conditions:
            connection.send_error(
                msg["id"],
                "conditions_required",
                "Conditions are required for conditional mode",
            )
            return
        # Check that either rules or zones are provided
        rules = conditions.get("rules", [])
        zones = conditions.get("zones", {})
        if not rules and not zones:
            connection.send_error(
                msg["id"],
                "conditions_required",
                "Either 'rules' or 'zones' must be provided for conditional mode",
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
