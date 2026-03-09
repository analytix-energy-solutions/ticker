"""Subscription WebSocket commands for Ticker integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    SUBSCRIPTION_MODES,
    MODE_CONDITIONAL,
    MODE_NEVER,
    SET_BY_USER,
    SET_BY_ADMIN,
)
from ..discovery import async_discover_notify_services
from .validation import (
    get_store,
    validate_category_id,
    validate_entity_id,
)

_LOGGER = logging.getLogger(__name__)


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
        validation_error = _validate_conditions(hass, conditions, msg["id"])
        if validation_error:
            connection.send_error(*validation_error)
            return

    # Validate device_override if provided
    if device_override:
        validation_error = await _validate_device_override(
            hass, device_override, person_id, mode, msg["id"]
        )
        if validation_error:
            connection.send_error(*validation_error)
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
    set_by = SET_BY_ADMIN  # Default to admin
    caller_user = connection.user
    if caller_user:
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


def _validate_conditions(
    hass: HomeAssistant,
    conditions: dict[str, Any],
    msg_id: int,
) -> tuple[int, str, str] | None:
    """Validate conditions structure.

    Returns None if valid, or (msg_id, error_code, error_message) tuple if invalid.
    """
    # Support both legacy zones format and new rules format
    rules = conditions.get("rules", [])
    zones = conditions.get("zones", {})

    # Validate legacy zones format
    for zone_id in zones.keys():
        is_valid, error = validate_entity_id(zone_id, "zone")
        if not is_valid:
            return (msg_id, "invalid_zone", error)

        # Check zone actually exists in Home Assistant
        if not hass.states.get(zone_id):
            return (msg_id, "zone_not_found", f"Zone '{zone_id}' does not exist")

    # Validate new rules format (F-2 Advanced Conditions)
    valid_rule_types = ["zone", "time", "state"]
    for idx, rule in enumerate(rules):
        rule_type = rule.get("type")

        if rule_type not in valid_rule_types:
            return (
                msg_id,
                "invalid_rule_type",
                f"Rule {idx}: invalid type '{rule_type}'",
            )

        if rule_type == "zone":
            zone_id = rule.get("zone_id", "")
            is_valid, error = validate_entity_id(zone_id, "zone")
            if not is_valid:
                return (msg_id, "invalid_zone", f"Rule {idx}: {error}")
            if not hass.states.get(zone_id):
                return (
                    msg_id,
                    "zone_not_found",
                    f"Rule {idx}: Zone '{zone_id}' does not exist",
                )

        elif rule_type == "time":
            validation_error = _validate_time_rule(rule, idx, msg_id)
            if validation_error:
                return validation_error

        elif rule_type == "state":
            validation_error = _validate_state_rule(hass, rule, idx, msg_id)
            if validation_error:
                return validation_error

        # Ensure at least one action is set per rule
        if not rule.get("deliver_when_met") and not rule.get("queue_until_met"):
            return (
                msg_id,
                "invalid_rule_actions",
                f"Rule {idx}: At least one of 'deliver_when_met' or "
                "'queue_until_met' must be true",
            )

    return None


def _validate_time_rule(
    rule: dict[str, Any],
    idx: int,
    msg_id: int,
) -> tuple[int, str, str] | None:
    """Validate a time rule."""
    after = rule.get("after", "")
    before = rule.get("before", "")
    if not after or not before:
        return (
            msg_id,
            "invalid_time_rule",
            f"Rule {idx}: 'after' and 'before' are required for time rules",
        )
    # Validate time format HH:MM
    for time_val, name in [(after, "after"), (before, "before")]:
        try:
            parts = time_val.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time values")
        except (ValueError, IndexError):
            return (
                msg_id,
                "invalid_time_format",
                f"Rule {idx}: '{name}' must be in HH:MM format",
            )
    # Validate days if provided
    days = rule.get("days", [])
    if days:
        for day in days:
            if not isinstance(day, int) or not (1 <= day <= 7):
                return (
                    msg_id,
                    "invalid_day",
                    f"Rule {idx}: days must be integers 1-7 (Mon-Sun)",
                )
    return None


def _validate_state_rule(
    hass: HomeAssistant,
    rule: dict[str, Any],
    idx: int,
    msg_id: int,
) -> tuple[int, str, str] | None:
    """Validate a state rule."""
    entity_id = rule.get("entity_id", "")
    state_val = rule.get("state", "")
    if not entity_id:
        return (
            msg_id,
            "invalid_state_rule",
            f"Rule {idx}: 'entity_id' is required for state rules",
        )
    if not state_val:
        return (
            msg_id,
            "invalid_state_rule",
            f"Rule {idx}: 'state' is required for state rules",
        )
    # Check entity exists
    if not hass.states.get(entity_id):
        return (
            msg_id,
            "entity_not_found",
            f"Rule {idx}: Entity '{entity_id}' does not exist",
        )
    return None


async def _validate_device_override(
    hass: HomeAssistant,
    device_override: dict[str, Any],
    person_id: str,
    mode: str,
    msg_id: int,
) -> tuple[int, str, str] | None:
    """Validate device override structure.

    Returns None if valid, or (msg_id, error_code, error_message) tuple if invalid.
    """
    if mode == MODE_NEVER:
        return (
            msg_id,
            "invalid_device_override",
            "Device override cannot be set for 'never' mode",
        )

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
                return (
                    msg_id,
                    "invalid_device",
                    f"Device '{device_service}' not found for this person",
                )

    return None
