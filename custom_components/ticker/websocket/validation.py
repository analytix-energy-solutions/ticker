"""Input validation and sanitization for WebSocket API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

if TYPE_CHECKING:
    from ..store import TickerStore

# Maximum lengths for user inputs
MAX_CATEGORY_ID_LENGTH = 64
MAX_CATEGORY_NAME_LENGTH = 100
MAX_ICON_LENGTH = 64
MAX_COLOR_LENGTH = 20

# Valid patterns
CATEGORY_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
ICON_PATTERN = re.compile(r"^[a-z0-9_\-:]+$", re.IGNORECASE)
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def sanitize_string(value: str | None, max_length: int = 200) -> str | None:
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


def get_store(hass: HomeAssistant) -> "TickerStore":
    """Get the Ticker store from the config entry runtime data."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ValueError("Ticker integration not configured")
    entry = entries[0]
    if not hasattr(entry, 'runtime_data') or entry.runtime_data is None:
        raise ValueError("Ticker integration not loaded")
    return entry.runtime_data.store
