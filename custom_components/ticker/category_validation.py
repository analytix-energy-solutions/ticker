"""Shared category-field validation for the WS create command and the
``ticker.ensure_category`` service.

Both callers feed the SAME raw string keys (``category_id``, ``name``,
``icon``, ...) through :func:`validate_and_sanitize_category_fields` so the
validation/sanitization rules cannot drift between the WebSocket and service
paths (see SPEC AC5). The helper is deliberately caller-agnostic: it raises a
neutral :class:`CategoryFieldError` on the first invalid field, which each
caller translates into its own error surface (WS ``send_error`` /
``ServiceValidationError``).

It does NOT perform the ``category_exists`` / already-exists check — that is
per-caller control flow — and it does NOT duplicate the store's sparse/normalize
logic. It returns a kwargs dict ready to splat into
``store.async_create_category(**kwargs)``.
"""

from __future__ import annotations

from typing import Any

from .const import (
    MAX_ANDROID_CHANNEL_LENGTH,
    MAX_CHIME_MEDIA_CONTENT_ID_LENGTH,
    MAX_NAVIGATE_TO_LENGTH,
)
from .websocket.validation import (
    MAX_CATEGORY_NAME_LENGTH,
    sanitize_for_storage,
    validate_category_id,
    validate_color,
    validate_icon,
    validate_navigate_to,
)


class CategoryFieldError(Exception):
    """Raised when a category field fails validation.

    Carries a neutral error ``code`` and human-readable ``message`` that each
    caller translates into its own error surface.
    """

    def __init__(self, code: str, message: str) -> None:
        """Store the error code and message and initialize the exception."""
        super().__init__(message)
        self.code = code
        self.message = message


def validate_and_sanitize_category_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize raw category-create fields.

    Args:
        fields: Raw field mapping using the WS-create string keys
            (``category_id``, ``name``, ``icon``, ``color``, ``default_mode``,
            ``default_conditions``, ``critical``, ``smart_notification``,
            ``action_set_id``, ``navigate_to``, ``expose_in_sensor``,
            ``android_channel``, ``chime_media_content_id``,
            ``volume_override``).

    Returns:
        A kwargs dict ready to splat into ``store.async_create_category``.

    Raises:
        CategoryFieldError: On the first invalid field, carrying the matching
            WS error ``code`` and ``message``.
    """
    category_id = fields["category_id"]
    is_valid, error = validate_category_id(category_id)
    if not is_valid:
        raise CategoryFieldError("invalid_category_id", error or "Invalid category id")

    name = sanitize_for_storage(fields["name"], MAX_CATEGORY_NAME_LENGTH)
    if not name:
        raise CategoryFieldError("invalid_name", "Category name is required")

    icon = fields.get("icon")
    is_valid, error = validate_icon(icon)
    if not is_valid:
        raise CategoryFieldError("invalid_icon", error or "Invalid icon")

    color = fields.get("color")
    is_valid, error = validate_color(color)
    if not is_valid:
        raise CategoryFieldError("invalid_color", error or "Invalid color")

    navigate_to = sanitize_for_storage(fields.get("navigate_to"), MAX_NAVIGATE_TO_LENGTH)
    # BUG-100: enforce relative HA path, block javascript: / https:// etc.
    is_valid, error = validate_navigate_to(navigate_to)
    if not is_valid:
        raise CategoryFieldError("invalid_navigate_to", error or "Invalid navigate_to")

    expose_in_sensor = fields.get("expose_in_sensor")
    android_channel = (
        sanitize_for_storage(fields.get("android_channel"), MAX_ANDROID_CHANNEL_LENGTH)
        if "android_channel" in fields
        else None
    )

    # F-35: validate chime_media_content_id length.
    chime_id = fields.get("chime_media_content_id")
    if (
        chime_id is not None
        and isinstance(chime_id, str)
        and len(chime_id) > MAX_CHIME_MEDIA_CONTENT_ID_LENGTH
    ):
        raise CategoryFieldError(
            "invalid_chime",
            f"chime_media_content_id exceeds "
            f"{MAX_CHIME_MEDIA_CONTENT_ID_LENGTH} characters",
        )

    return {
        "category_id": category_id,
        "name": name,
        "icon": icon,
        "color": color,
        "default_mode": fields.get("default_mode"),
        "default_conditions": fields.get("default_conditions"),
        "critical": fields.get("critical", False),
        "smart_notification": fields.get("smart_notification"),
        "action_set_id": fields.get("action_set_id"),
        "navigate_to": navigate_to,
        "expose_in_sensor": expose_in_sensor,
        "android_channel": android_channel,
        "chime_media_content_id": chime_id,
        "volume_override": fields.get("volume_override"),
    }
