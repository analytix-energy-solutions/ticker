"""Condition evaluation engine for Ticker F-2/F-2b Advanced Conditions.

Supports zone, time, and state rules with AND/OR grouping (condition_tree).
Legacy flat rules[] format is supported as fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONDITION_NODE_GROUP,
    RULE_TYPE_ZONE,
    RULE_TYPE_TIME,
    RULE_TYPE_STATE,
)

if TYPE_CHECKING:
    from homeassistant.core import State

_LOGGER = logging.getLogger(__name__)


def evaluate_zone_rule(
    rule: dict[str, Any],
    person_state: "State",
) -> tuple[bool, str]:
    """Evaluate a zone rule. Returns (is_met, reason)."""
    zone_id = rule.get("zone_id", "")
    if not zone_id:
        return False, "No zone_id specified"

    # Extract zone name from zone_id (e.g., "zone.home" -> "home")
    zone_name = zone_id.replace("zone.", "")
    person_zone = person_state.state

    is_met = person_zone == zone_name
    if is_met:
        return True, f"In zone {zone_name}"
    return False, f"Not in zone {zone_name} (currently in {person_zone})"


def evaluate_time_rule(
    rule: dict[str, Any],
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Evaluate a time rule. Supports overnight windows. Returns (is_met, reason)."""
    if now is None:
        now = dt_util.now()

    after_str = rule.get("after", "")
    before_str = rule.get("before", "")
    days = rule.get("days", [])  # List of day numbers 1-7 (Mon-Sun)

    if not after_str or not before_str:
        return False, "Time rule missing 'after' or 'before'"

    try:
        after_parts = after_str.split(":")
        before_parts = before_str.split(":")
        after_time = time(int(after_parts[0]), int(after_parts[1]))
        before_time = time(int(before_parts[0]), int(before_parts[1]))
    except (ValueError, IndexError):
        return False, f"Invalid time format: {after_str} - {before_str}"

    current_time = now.time()
    current_day = now.isoweekday()  # 1=Monday, 7=Sunday

    # Check day constraint if specified
    if days and current_day not in days:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        current_day_name = day_names[current_day - 1]
        return False, f"Day {current_day_name} not in allowed days"

    # Handle overnight windows (e.g., 22:00 to 06:00)
    if after_time <= before_time:
        # Normal window (e.g., 08:00 to 22:00)
        is_in_window = after_time <= current_time <= before_time
    else:
        # Overnight window (e.g., 22:00 to 06:00)
        is_in_window = current_time >= after_time or current_time <= before_time

    if is_in_window:
        return True, f"Time {current_time.strftime('%H:%M')} is within {after_str}-{before_str}"
    return False, f"Time {current_time.strftime('%H:%M')} outside {after_str}-{before_str}"


def evaluate_state_rule(
    hass: HomeAssistant,
    rule: dict[str, Any],
) -> tuple[bool, str]:
    """Evaluate an entity state rule. Returns (is_met, reason)."""
    entity_id = rule.get("entity_id", "")
    expected_state = rule.get("state", "")

    if not entity_id:
        return False, "No entity_id specified"
    if not expected_state:
        return False, "No expected state specified"

    state = hass.states.get(entity_id)
    if state is None:
        return False, f"Entity {entity_id} not found"

    # Case-insensitive comparison
    actual_state = state.state.lower()
    expected_lower = expected_state.lower()

    if actual_state == expected_lower:
        return True, f"{entity_id} is {state.state}"
    return False, f"{entity_id} is {state.state}, not {expected_state}"


def evaluate_rule(
    hass: HomeAssistant,
    rule: dict[str, Any],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Evaluate a single rule.

    Args:
        hass: Home Assistant instance
        rule: Rule configuration dict
        person_state: Person entity state, or None for recipients
        now: Current datetime (for time rules)

    Returns:
        Tuple of (is_met, reason_string)
    """
    rule_type = rule.get("type", "")

    if rule_type == RULE_TYPE_ZONE:
        if person_state is None:
            # Recipients have no location; skip zone rules (treat as met)
            return True, "Zone rule skipped (no person state)"
        return evaluate_zone_rule(rule, person_state)
    elif rule_type == RULE_TYPE_TIME:
        return evaluate_time_rule(rule, now)
    elif rule_type == RULE_TYPE_STATE:
        return evaluate_state_rule(hass, rule)
    else:
        _LOGGER.debug("Unknown rule type '%s', treating as unmet", rule_type)
        return False, f"Unknown rule type: {rule_type}"


def evaluate_rules(
    hass: HomeAssistant,
    rules: list[dict[str, Any]],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, list[tuple[bool, str]]]:
    """Evaluate all rules with AND logic.

    All rules must be met for the overall condition to be true.

    Args:
        hass: Home Assistant instance
        rules: List of rule dicts
        person_state: Person entity state, or None for recipients
        now: Current datetime (for time rules)

    Returns:
        Tuple of (all_met, list_of_per_rule_results) where each result
        is (is_met, reason_string).
    """
    if not rules:
        return True, [(True, "No rules configured")]

    all_met = True
    results: list[tuple[bool, str]] = []

    for rule in rules:
        is_met, reason = evaluate_rule(hass, rule, person_state, now)
        results.append((is_met, reason))
        if not is_met:
            all_met = False
            # Continue checking to collect all results

    return all_met, results


def evaluate_group(
    hass: HomeAssistant,
    group: dict[str, Any],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, list[tuple[bool, str]]]:
    """Evaluate a condition group node (AND or OR).

    Recursively evaluates children. AND: all must be met.
    OR: at least one must be met.

    Args:
        hass: Home Assistant instance
        group: Group node dict with 'operator' and 'children'
        person_state: Person entity state, or None for recipients
        now: Current datetime (for time rules)

    Returns:
        Tuple of (is_met, per_child_results).
    """
    operator = group.get("operator", "AND").upper()
    children = group.get("children", [])

    if not children:
        return True, [(True, "Empty group")]

    results: list[tuple[bool, str]] = []
    for child in children:
        if child.get("type") == CONDITION_NODE_GROUP:
            child_met, _child_results = evaluate_group(
                hass, child, person_state, now,
            )
            child_op = child.get("operator", "AND")
            results.append((
                child_met,
                f"Group ({child_op}): {'met' if child_met else 'not met'}",
            ))
        else:
            child_met, child_reason = evaluate_rule(
                hass, child, person_state, now,
            )
            results.append((child_met, child_reason))

    if operator == "OR":
        all_met = any(r[0] for r in results)
    else:  # AND
        all_met = all(r[0] for r in results)

    return all_met, results


def evaluate_condition_tree(
    hass: HomeAssistant,
    conditions: dict[str, Any],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, list[tuple[bool, str]]]:
    """Evaluate conditions using condition_tree (new format) or rules[] (legacy).

    Falls back to flat rules[] evaluation if condition_tree is absent.

    Args:
        hass: Home Assistant instance
        conditions: Conditions dict with 'condition_tree' or 'rules'
        person_state: Person entity state, or None for recipients
        now: Current datetime (for time rules)

    Returns:
        Tuple of (all_met, per_node_results).
    """
    tree = conditions.get("condition_tree")
    if tree:
        return evaluate_group(hass, tree, person_state, now)

    # Legacy flat rules[] — evaluate with AND
    rules = conditions.get("rules", [])
    return evaluate_rules(hass, rules, person_state, now)


def should_deliver_now(
    hass: HomeAssistant,
    conditions: dict[str, Any],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Check if notification should be delivered now.

    Evaluates all rules with AND logic. Only delivers if:
    1. All rules are met, AND
    2. deliver_when_met is True (at conditions level or in any rule)

    Args:
        hass: Home Assistant instance
        conditions: Conditions dict with 'rules' and optional 'deliver_when_met'
        person_state: Person entity state, or None for recipients
        now: Current datetime

    Returns:
        Tuple of (should_deliver, reason_string)
    """
    rules = conditions.get("rules", [])
    if not rules:
        # No rules = always deliver (fallback behavior)
        return True, "No conditions configured"

    # Check for deliver_when_met at conditions level
    has_deliver = conditions.get("deliver_when_met", False)

    if not has_deliver:
        return False, "Delivery not enabled for these conditions"

    # Evaluate all conditions (tree or flat rules)
    all_met, rule_results = evaluate_condition_tree(
        hass, conditions, person_state, now,
    )

    if all_met:
        return True, "All conditions met"

    # Find first unmet reason from already-evaluated results
    for is_met, reason in rule_results:
        if not is_met:
            return False, reason
    return False, "Conditions not met"


def should_queue(
    hass: HomeAssistant,
    conditions: dict[str, Any],
    person_state: "State | None",
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Check if notification should be queued for later.

    Queues if:
    1. queue_until_met is True (at conditions level or in any rule), AND
    2. Not all rules are currently met

    Args:
        hass: Home Assistant instance
        conditions: Conditions dict with 'rules' and optional 'queue_until_met'
        person_state: Person entity state, or None for recipients
        now: Current datetime

    Returns:
        Tuple of (should_queue, reason_string)
    """
    rules = conditions.get("rules", [])
    if not rules:
        return False, "No conditions configured"

    # Check for queue_until_met at conditions level
    has_queue = conditions.get("queue_until_met", False)

    if not has_queue:
        return False, "Queueing not enabled for these conditions"

    # Evaluate all conditions (tree or flat rules)
    all_met, _rule_results = evaluate_condition_tree(
        hass, conditions, person_state, now,
    )

    if all_met:
        # Already met - deliver now, don't queue
        return False, "All conditions already met"

    return True, "Waiting for conditions to be met"


def _collect_triggers_from_node(
    node: dict[str, Any],
    triggers: dict[str, Any],
) -> None:
    """Recursively collect trigger data from a condition tree node.

    Walks both group nodes (recursing into children) and leaf nodes
    (extracting zone/state/time trigger data).

    Args:
        node: A condition tree node (group or leaf)
        triggers: Mutable dict with 'zones' (set), 'entities' (set),
            'time_windows' (list) to populate
    """
    if node.get("type") == CONDITION_NODE_GROUP:
        for child in node.get("children", []):
            _collect_triggers_from_node(child, triggers)
    elif node.get("type") == RULE_TYPE_ZONE:
        zone_id = node.get("zone_id", "")
        if zone_id:
            triggers["zones"].add(zone_id)
    elif node.get("type") == RULE_TYPE_STATE:
        entity_id = node.get("entity_id", "")
        if entity_id:
            triggers["entities"].add(entity_id)
    elif node.get("type") == RULE_TYPE_TIME:
        after = node.get("after", "")
        if after:
            triggers["time_windows"].append({
                "after": after,
                "before": node.get("before", ""),
                "days": node.get("days", []),
            })


def get_queue_triggers(
    conditions: dict[str, Any],
) -> dict[str, Any]:
    """Extract triggers needed for queue release monitoring.

    Only returns triggers if queue_until_met is enabled at conditions level.
    Supports both condition_tree (new format) and flat rules[] (legacy).

    Args:
        conditions: Conditions dict with 'condition_tree' or 'rules'
            and 'queue_until_met'

    Returns:
        Dict with 'zones', 'entities', 'time_windows' keys
    """
    triggers: dict[str, Any] = {
        "zones": set(),
        "entities": set(),
        "time_windows": [],
    }

    # Only collect triggers if queueing is enabled
    if not conditions.get("queue_until_met", False):
        triggers["zones"] = []
        triggers["entities"] = []
        return triggers

    # Try condition_tree first, then fall back to flat rules[]
    tree = conditions.get("condition_tree")
    if tree:
        _collect_triggers_from_node(tree, triggers)
    else:
        rules = conditions.get("rules", [])
        for rule in rules:
            _collect_triggers_from_node(rule, triggers)

    # Convert sets to lists for JSON serialization
    triggers["zones"] = list(triggers["zones"])
    triggers["entities"] = list(triggers["entities"])

    return triggers


def convert_legacy_zones_to_rules(
    zones_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert legacy zones format to new conditions format.

    Legacy format:
        {
            "zone.home": {
                "deliver_while_here": True,
                "queue_until_arrival": True
            }
        }

    New conditions format:
        {
            "deliver_when_met": True,
            "queue_until_met": True,
            "rules": [
                {"type": "zone", "zone_id": "zone.home"}
            ]
        }

    Since legacy format only had zone conditions, the per-zone flags
    are promoted to conditions-level (1:1 conversion).

    Args:
        zones_config: Legacy zones dict

    Returns:
        Complete conditions dict with rules and top-level flags
    """
    rules = []
    has_deliver = False
    has_queue = False

    for zone_id, zone_config in zones_config.items():
        if zone_config.get("deliver_while_here", False):
            has_deliver = True
        if zone_config.get("queue_until_arrival", False):
            has_queue = True

        rule = {
            "type": RULE_TYPE_ZONE,
            "zone_id": zone_id,
        }
        rules.append(rule)

    return {
        "deliver_when_met": has_deliver,
        "queue_until_met": has_queue,
        "rules": rules,
    }


def has_valid_rules(conditions: dict[str, Any] | None) -> bool:
    """Check if conditions have at least one effective delivery path.

    Supports condition_tree (F-2b), flat rules[], and legacy zones format.

    Args:
        conditions: Conditions dict with 'condition_tree', 'rules', or 'zones'

    Returns:
        True if rules/tree exist and deliver_when_met or queue_until_met is
        enabled at conditions level.
    """
    if not conditions:
        return False

    # Check condition_tree (F-2b format)
    tree = conditions.get("condition_tree")
    if tree and tree.get("children"):
        return bool(
            conditions.get("deliver_when_met")
            or conditions.get("queue_until_met")
        )

    rules = conditions.get("rules", [])
    if not rules:
        # Check legacy zones format (pre-migration data)
        zones = conditions.get("zones", {})
        if zones:
            for zone_config in zones.values():
                if zone_config.get("deliver_while_here") or zone_config.get("queue_until_arrival"):
                    return True
        return False

    # Conditions-level flags (current format)
    return bool(
        conditions.get("deliver_when_met")
        or conditions.get("queue_until_met")
    )
