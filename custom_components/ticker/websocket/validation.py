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
    RULE_TYPES,
    SNOOZE_DURATIONS_MINUTES,
)

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
    """Sanitize a string for safe storage without HTML escaping.

    Performs safe cleanup suitable for values persisted to HA storage,
    passed to service calls, or written to YAML. Does NOT escape HTML
    entities -- the frontend handles display-escaping via its own
    esc() and escAttr() utilities.

    Steps (in order):
      1. Coerce non-string values to str
      2. Strip leading/trailing whitespace
      3. Remove null bytes
      4. Truncate to max_length

    Args:
        value: The input string (or None).
        max_length: Maximum allowed length after cleaning. Defaults to 200.

    Returns:
        The cleaned string, or None if the input was None.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    # Strip whitespace and remove null bytes
    value = value.strip().replace("\x00", "")

    # Truncate to max length
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


def validate_condition_tree(
    tree: dict,
    depth: int = 0,
) -> str | None:
    """Validate a condition_tree structure recursively.

    Checks node types, operator values, and depth limits.

    Args:
        tree: A condition tree node (group or leaf).
        depth: Current nesting depth (0 = root).

    Returns:
        Error message string if invalid, None if valid.
    """
    if not isinstance(tree, dict):
        return "Condition tree node must be a dict"

    node_type = tree.get("type")
    if not node_type:
        return "Condition tree node missing 'type'"

    if node_type == CONDITION_NODE_GROUP:
        operator = tree.get("operator", "").upper()
        if operator not in CONDITION_OPERATORS:
            return f"Invalid group operator '{operator}', must be AND or OR"

        children = tree.get("children")
        if not isinstance(children, list):
            return "Group node 'children' must be a list"

        if depth >= CONDITION_MAX_DEPTH:
            return (
                f"Condition tree exceeds max depth of {CONDITION_MAX_DEPTH}"
            )

        for idx, child in enumerate(children):
            error = validate_condition_tree(child, depth + 1)
            if error:
                return f"children[{idx}]: {error}"

        return None

    # Leaf node — must be a known rule type
    if node_type not in RULE_TYPES:
        return f"Unknown node type '{node_type}'"

    return None


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
