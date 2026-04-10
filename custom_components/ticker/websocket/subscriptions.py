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
    _validate_leaf,
    get_store,
    validate_category_id,
    validate_condition_tree,
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
        # Check that either condition_tree, rules, or zones are provided
        tree = conditions.get("condition_tree")
        rules = conditions.get("rules", [])
        zones = conditions.get("zones", {})
        if not rules and not zones and not tree:
            connection.send_error(
                msg["id"],
                "conditions_required",
                "Either 'condition_tree', 'rules', or 'zones' must be "
                "provided for conditional mode",
            )
            return

        # Validate condition_tree structure + leaf semantics if present
        if tree:
            tree_error = validate_condition_tree(tree, hass)
            if tree_error:
                code, msg_text = tree_error
                connection.send_error(msg["id"], code, msg_text)
                return

    # Determine set_by: record ADMIN only when the caller actually has
    # admin rights. A non-admin HA user editing another user's subscription
    # must not be tagged as ADMIN — that is an audit-log correctness bug
    # (BUG-098). Self-edits are always tagged USER regardless of admin flag.
    set_by = SET_BY_ADMIN  # Default to admin (preserved when caller_user is None)
    caller_user = connection.user
    if caller_user:
        discovered_users = await async_discover_notify_services(hass)
        target_user_data = discovered_users.get(person_id, {})
        target_user_id = target_user_data.get("user_id")

        if target_user_id and target_user_id == caller_user.id:
            # Caller is editing their own subscription
            set_by = SET_BY_USER
        elif caller_user.is_admin:
            # Cross-user edit by an actual admin
            set_by = SET_BY_ADMIN
        else:
            # Cross-user edit by a non-admin caller — not an admin action;
            # fall back to USER rather than mislabeling the audit log.
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

        # Delegate to the shared leaf validator (see BUG-097). The shared
        # helper returns a (error_code, error_message) tuple; we prefix
        # the message with the rule index to preserve the WS contract.
        leaf_error = _validate_leaf(rule, hass)
        if leaf_error:
            error_code, error_msg = leaf_error
            return (msg_id, error_code, f"Rule {idx}: {error_msg}")

    # Validate conditions-level action flags (deliver/queue apply to the
    # entire ruleset, not individual rules)
    if rules:
        has_deliver = conditions.get("deliver_when_met", False)
        has_queue = conditions.get("queue_until_met", False)
        if not has_deliver and not has_queue:
            return (
                msg_id,
                "invalid_rule_actions",
                "At least one of 'deliver_when_met' or "
                "'queue_until_met' must be true",
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
