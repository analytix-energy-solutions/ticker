"""Validation helpers for recipient WebSocket handlers (F-18 / F-35).

Extracted from ``websocket/recipients.py`` so that file stays under the
500-line limit while F-35.2 adds the volume_override schema and field
plumbing. Pure validation only — no store access, no logging.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    MAX_CHIME_MEDIA_CONTENT_ID_LENGTH,
    MAX_NOTIFY_SERVICES,
    RECIPIENT_DELIVERY_FORMATS,
)
from .validation import validate_condition_tree


def validate_notify_services(
    notify_services: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Validate notify_services list. Each entry needs a 'service' key.

    Called only for push-type recipients; TTS recipients skip this.
    """
    if not notify_services:
        return False, "At least one notify service is required"
    if len(notify_services) > MAX_NOTIFY_SERVICES:
        return False, f"Maximum {MAX_NOTIFY_SERVICES} notify services allowed"
    for idx, entry in enumerate(notify_services):
        if not isinstance(entry, dict):
            return False, f"Notify service {idx} must be an object"
        service = entry.get("service", "")
        if not isinstance(service, str) or not service.startswith("notify."):
            return False, f"Notify service {idx}: 'service' must start with 'notify.'"
    return True, None


def validate_delivery_format(fmt: str) -> tuple[bool, str | None]:
    """Validate delivery format value against recipient-valid formats."""
    if fmt not in RECIPIENT_DELIVERY_FORMATS:
        return False, (
            f"Delivery format must be one of: "
            f"{', '.join(RECIPIENT_DELIVERY_FORMATS)}"
        )
    return True, None


def validate_by_device_type(
    msg: dict[str, Any],
    device_type: str,
    require_notify_services: bool = True,
) -> tuple[bool, str, str | None]:
    """Validate fields conditionally based on device_type.

    For push: requires notify_services (if require_notify_services=True).
    For tts: requires media_player_entity_id.

    Returns:
        Tuple of (is_valid, error_code, error_message).
    """
    if device_type == DEVICE_TYPE_TTS:
        entity_id = msg.get("media_player_entity_id")
        if not entity_id or not isinstance(entity_id, str):
            return (
                False, "invalid_media_player",
                "media_player_entity_id is required for TTS recipients",
            )
        if not entity_id.startswith("media_player."):
            return (
                False, "invalid_media_player",
                "media_player_entity_id must start with 'media_player.'",
            )
    elif device_type == DEVICE_TYPE_PUSH and require_notify_services:
        notify_services = msg.get("notify_services")
        if notify_services is not None:
            is_valid, error = validate_notify_services(notify_services)
            if not is_valid:
                return False, "invalid_notify_services", error
        elif require_notify_services:
            return (
                False, "invalid_notify_services",
                "notify_services is required for push recipients",
            )

    return True, "", None


def validate_chime_length(chime_id: Any) -> tuple[str, str] | None:
    """Return (code, msg) error tuple if chime exceeds the length cap."""
    if (
        chime_id is not None
        and isinstance(chime_id, str)
        and len(chime_id) > MAX_CHIME_MEDIA_CONTENT_ID_LENGTH
    ):
        return (
            "invalid_chime",
            f"chime_media_content_id exceeds "
            f"{MAX_CHIME_MEDIA_CONTENT_ID_LENGTH} characters",
        )
    return None


def validate_conditions_blob(
    raw: Any, hass: HomeAssistant,
) -> tuple[Any, tuple[str, str] | None]:
    """Normalize and validate a recipient conditions payload.

    Returns ``(conditions, error)`` where ``error`` is a ``(code, msg)``
    tuple on failure or ``None`` on success. Empty dict / None both
    normalize to ``None`` (BUG-093).
    """
    if not raw:
        return None, None
    if raw.get("condition_tree") or raw.get("rules") is not None:
        tree = raw.get("condition_tree")
        rules = raw.get("rules")
        if tree:
            tree_error = validate_condition_tree(tree, hass)
            if tree_error:
                return raw, tree_error
        elif not isinstance(rules, list):
            return raw, (
                "invalid_conditions",
                "Conditions must contain 'condition_tree' or 'rules'",
            )
        return raw, None
    return raw, (
        "invalid_conditions",
        "Conditions must contain 'condition_tree' or 'rules'",
    )
