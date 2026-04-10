"""Input validation and sanitization for WebSocket API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from ..const import (
    ACTION_TYPES,
    ACTION_TYPE_SCRIPT,
    ACTION_TYPE_SNOOZE,
    CONDITION_MAX_DEPTH,
    CONDITION_NODE_GROUP,
    CONDITION_OPERATORS,
    DOMAIN,
    MAX_ACTIONS_PER_SET,
    MAX_NAVIGATE_TO_LENGTH,
    RULE_TYPE_STATE,
    RULE_TYPE_TIME,
    RULE_TYPE_ZONE,
    RULE_TYPES,
    SNOOZE_DURATIONS_MINUTES,
)

TIME_HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

if TYPE_CHECKING:
    from ..store import TickerStore

SCRIPT_ENTITY_PATTERN = re.compile(r"^script\.[a-z0-9_]+$")

# Maximum lengths for user inputs
MAX_CATEGORY_ID_LENGTH = 64
MAX_CATEGORY_NAME_LENGTH = 100
MAX_ICON_LENGTH = 64
MAX_COLOR_LENGTH = 20

# Valid patterns
CATEGORY_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
ICON_PATTERN = re.compile(r"^[a-z0-9_\-:]+$", re.IGNORECASE)
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def sanitize_for_storage(value: str | None, max_length: int = 200) -> str | None:
    """Coerce to str, strip whitespace, remove null bytes, truncate. No HTML escaping."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip().replace("\x00", "")
    if len(value) > max_length:
        value = value[:max_length]
    return value


def validate_category_id(category_id: str) -> tuple[bool, str | None]:
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


def validate_recipient_id(recipient_id: str) -> tuple[bool, str | None]:
    """Validate a recipient ID slug ([a-z0-9_]+).

    Returns (is_valid, error_message).
    Reuses the same pattern as category IDs: lowercase alphanumeric and underscores.
    """
    from ..const import MAX_RECIPIENT_ID_LENGTH

    if not recipient_id:
        return False, "Recipient ID is required"
    if len(recipient_id) > MAX_RECIPIENT_ID_LENGTH:
        return False, f"Recipient ID must be {MAX_RECIPIENT_ID_LENGTH} chars or less"
    if not CATEGORY_ID_PATTERN.match(recipient_id):
        return False, (
            "Recipient ID must contain only lowercase letters, numbers, "
            "and underscores"
        )
    return True, None


def validate_icon(icon: str | None) -> tuple[bool, str | None]:
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


def validate_color(color: str | None) -> tuple[bool, str | None]:
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


_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f]")

NAVIGATE_TO_ERROR = "navigate_to must be a relative path starting with /"


def validate_navigate_to(value: Any) -> tuple[bool, str | None]:
    """Validate a navigate_to field (BUG-100): safe relative HA path or empty."""
    if value is None or value == "":
        return True, None
    if not isinstance(value, str):
        return False, NAVIGATE_TO_ERROR
    if len(value) > MAX_NAVIGATE_TO_LENGTH:
        return False, f"navigate_to must be {MAX_NAVIGATE_TO_LENGTH} characters or less"
    if _CONTROL_CHAR_PATTERN.search(value):
        return False, "navigate_to must not contain control characters"
    if not value.startswith("/"):
        return False, NAVIGATE_TO_ERROR
    # Reject protocol-relative URLs like "//evil.com" and embedded schemes.
    if value.startswith("//") or "://" in value:
        return False, NAVIGATE_TO_ERROR
    return True, None


def validate_navigate_to_vol(value: Any) -> str | None:
    """Voluptuous-compatible wrapper around :func:`validate_navigate_to`."""
    import voluptuous as vol

    is_valid, error = validate_navigate_to(value)
    if not is_valid:
        raise vol.Invalid(error or NAVIGATE_TO_ERROR)
    return value


def validate_entity_id(entity_id: str, domain: str) -> tuple[bool, str | None]:
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


# Condition-tree validator error codes (BUG-097):
#   Pre-BUG-097: invalid_zone, zone_not_found, invalid_time_format, entity_not_found
#   New:         invalid_time_rule, invalid_state_rule, invalid_leaf_type, invalid_tree


def _validate_zone_leaf(
    leaf: dict,
    hass: HomeAssistant | None,
) -> tuple[str, str] | None:
    """Validate a zone leaf node.

    Checks zone_id is present, starts with ``zone.``, and — when ``hass``
    is provided — that the zone actually exists as a state in HA. When
    ``hass`` is None (structural-only validation, e.g. unit tests), the
    existence check is skipped.

    Returns:
        (error_code, error_message) tuple if invalid, None if valid.
    """
    zone_id = leaf.get("zone_id", "")
    is_valid, error = validate_entity_id(zone_id, "zone")
    if not is_valid:
        return ("invalid_zone", error or "Invalid zone id")
    if hass is not None and not hass.states.get(zone_id):
        return ("zone_not_found", f"Zone '{zone_id}' does not exist")
    return None


def _validate_time_leaf(leaf: dict) -> tuple[str, str] | None:
    """Validate a time leaf node.

    Checks that ``after`` and ``before`` are present and formatted HH:MM,
    and that ``days`` (if present) is a list of integers 1-7 (Mon-Sun).

    Returns:
        (error_code, error_message) tuple if invalid, None if valid.
    """
    after = leaf.get("after", "")
    before = leaf.get("before", "")
    if not after or not before:
        return (
            "invalid_time_rule",
            "'after' and 'before' are required for time rules",
        )
    for time_val, name in ((after, "after"), (before, "before")):
        if not isinstance(time_val, str) or not TIME_HHMM_PATTERN.match(time_val):
            return (
                "invalid_time_format",
                f"'{name}' must be in HH:MM format",
            )
    days = leaf.get("days", [])
    if days:
        if not isinstance(days, list):
            return (
                "invalid_time_format",
                "days must be a list of integers 1-7 (Mon-Sun)",
            )
        for day in days:
            if not isinstance(day, int) or not (1 <= day <= 7):
                return (
                    "invalid_time_format",
                    "days must be integers 1-7 (Mon-Sun)",
                )
    return None


def _validate_state_leaf(
    leaf: dict,
    hass: HomeAssistant | None,
) -> tuple[str, str] | None:
    """Validate a state leaf node.

    Checks that ``entity_id`` is present, that ``state`` is a non-empty
    string, and — when ``hass`` is provided — that the entity exists in
    the HA state machine.

    Returns:
        (error_code, error_message) tuple if invalid, None if valid.
    """
    entity_id = leaf.get("entity_id", "")
    state_val = leaf.get("state", "")
    if not entity_id:
        return (
            "invalid_state_rule",
            "'entity_id' is required for state rules",
        )
    if not isinstance(state_val, str) or not state_val:
        return (
            "invalid_state_rule",
            "'state' is required for state rules",
        )
    if hass is not None and not hass.states.get(entity_id):
        return ("entity_not_found", f"Entity '{entity_id}' does not exist")
    return None


def _validate_leaf(
    leaf: dict,
    hass: HomeAssistant | None,
) -> tuple[str, str] | None:
    """Dispatch leaf validation based on ``leaf['type']``.

    Returns:
        (error_code, error_message) tuple if invalid, None if valid.
    """
    leaf_type = leaf.get("type")
    if leaf_type == RULE_TYPE_ZONE:
        return _validate_zone_leaf(leaf, hass)
    if leaf_type == RULE_TYPE_TIME:
        return _validate_time_leaf(leaf)
    if leaf_type == RULE_TYPE_STATE:
        return _validate_state_leaf(leaf, hass)
    return ("invalid_leaf_type", f"Unknown leaf type '{leaf_type}'")


def validate_condition_tree(
    tree: dict,
    hass: HomeAssistant | None = None,
    depth: int = 0,
) -> tuple[str, str] | None:
    """Validate a condition_tree structure recursively.

    Checks node types, operator values, depth limits, and — for leaf
    nodes — full semantic validity (zone existence, time format, entity
    existence). See BUG-097.

    ``hass`` is optional: when omitted (None), only structural validation
    runs and HA state-existence checks are skipped. Production callers
    (subscriptions.py, recipients.py) MUST pass ``hass`` so semantic
    validation runs. Tests that only exercise structural rules can call
    with a single argument.

    Args:
        tree: A condition tree node (group or leaf).
        hass: Home Assistant instance (for leaf existence checks). Pass
            None to skip semantic entity/zone checks.
        depth: Current nesting depth (0 = root).

    Returns:
        (error_code, error_message) tuple if invalid, None if valid.
    """
    if not isinstance(tree, dict):
        return ("invalid_tree", "Condition tree node must be a dict")

    node_type = tree.get("type")
    if not node_type:
        return ("invalid_tree", "Condition tree node missing 'type'")

    if node_type == CONDITION_NODE_GROUP:
        operator = tree.get("operator", "").upper()
        if operator not in CONDITION_OPERATORS:
            return (
                "invalid_tree",
                f"Invalid group operator '{operator}', must be AND or OR",
            )

        children = tree.get("children")
        if not isinstance(children, list):
            return ("invalid_tree", "Group node 'children' must be a list")

        if depth >= CONDITION_MAX_DEPTH:
            return (
                "invalid_tree",
                f"Condition tree exceeds max depth of {CONDITION_MAX_DEPTH}",
            )

        for idx, child in enumerate(children):
            error = validate_condition_tree(child, hass, depth + 1)
            if error:
                code, msg_text = error
                return (code, f"children[{idx}]: {msg_text}")

        return None

    # Leaf node — must be a known rule type
    if node_type not in RULE_TYPES:
        return ("invalid_tree", f"Unknown node type '{node_type}'")

    # Semantic validation of leaf contents (BUG-097)
    return _validate_leaf(tree, hass)


def validate_action_set(action_set: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate an action_set structure.

    Checks that actions is a list within size limits, each action has a
    title and valid type, and type-specific fields are correct.

    Returns:
        Tuple of (is_valid, error_message).
    """
    actions = action_set.get("actions", [])
    if not isinstance(actions, list):
        return False, "actions must be a list"

    if len(actions) > MAX_ACTIONS_PER_SET:
        return False, f"Maximum {MAX_ACTIONS_PER_SET} actions allowed"

    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            return False, f"Action {i} must be an object"

        title = action.get("title", "").strip()
        if not title:
            return False, f"Action {i}: title is required"

        action_type = action.get("type")
        if action_type not in ACTION_TYPES:
            return False, f"Action {i}: invalid type '{action_type}'"

        if action_type == ACTION_TYPE_SCRIPT:
            script_entity = action.get("script_entity", "")
            if not SCRIPT_ENTITY_PATTERN.match(script_entity):
                return False, f"Action {i}: invalid script entity '{script_entity}'"

        if action_type == ACTION_TYPE_SNOOZE:
            snooze_minutes = action.get("snooze_minutes")
            if snooze_minutes not in SNOOZE_DURATIONS_MINUTES:
                return (
                    False,
                    f"Action {i}: snooze_minutes must be one of {SNOOZE_DURATIONS_MINUTES}",
                )

        # Ensure index is set
        if "index" not in action:
            action["index"] = i

    return True, None


def get_store(hass: HomeAssistant) -> "TickerStore":
    """Get the Ticker store from the config entry runtime data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("Ticker integration not configured")
    entry = entries[0]
    if not hasattr(entry, 'runtime_data') or entry.runtime_data is None:
        raise ValueError("Ticker integration not loaded")
    return entry.runtime_data.store
