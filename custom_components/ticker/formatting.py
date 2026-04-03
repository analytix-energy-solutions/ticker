"""Delivery format detection and payload transformation for Ticker.

Handles auto-detection of delivery formats based on notify service names
and transforms notification payloads for different target types (rich,
plain, TTS, persistent notification).

Used by F-18 (Non-User Recipient Support) and shared with F-16
(Platform-Aware HTML Stripping).
"""

from __future__ import annotations

import re
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import (
    DEFAULT_NAVIGATE_TO,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_PATTERNS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    SMART_TAG_MODE_NONE,
    SMART_TAG_MODE_CATEGORY,
    SMART_TAG_MODE_TITLE,
)

_LOGGER = logging.getLogger(__name__)

# Compiled regex for stripping HTML tags
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Remove HTML tags from text.

    Args:
        text: Input string potentially containing HTML tags.

    Returns:
        Text with all HTML tags removed.
    """
    if not text:
        return text
    return _HTML_TAG_PATTERN.sub("", text)


def detect_device_type(service_id: str) -> str:
    """Determine device type from a service identifier.

    Pattern-matches the service name to decide whether it is a TTS
    target or a push (notify) target.

    Args:
        service_id: The full service identifier (e.g., 'tts.google_home',
                     'notify.mobile_app_hans_iphone').

    Returns:
        DEVICE_TYPE_TTS for TTS services, DEVICE_TYPE_PUSH for everything else.
    """
    if not service_id:
        return DEVICE_TYPE_PUSH

    service_lower = service_id.lower()

    if service_lower.startswith("tts."):
        return DEVICE_TYPE_TTS
    if "alexa_media" in service_lower:
        return DEVICE_TYPE_TTS

    return DEVICE_TYPE_PUSH


def build_tts_payload(
    message: str,
    entity_id: str,
    tts_service: str | None = None,
) -> dict[str, Any]:
    """Build a payload for TTS delivery.

    Strips HTML from the message and returns a dict suitable for
    calling the configured TTS service.

    Supports two TTS calling patterns:
    - **Modern (tts.speak):** entity_id is intentionally omitted because
      Ticker stores only the media player entity, not the TTS engine
      entity (e.g., tts.google_translate). HA will use the default
      TTS engine. media_player_entity_id is the speaker target.
    - **Legacy (tts.google_translate_say, etc.):** entity_id is the
      media_player directly. This is the default since most users
      use legacy TTS services.

    Args:
        message: The notification message (may contain HTML).
        entity_id: The media_player entity ID to speak on.
        tts_service: TTS service (e.g., 'tts.google_translate_say').
            Determines which payload pattern to use.

    Returns:
        Payload dict ready for hass.services.async_call.
    """
    clean_message = strip_html(message or "")

    # Modern tts.speak uses media_player_entity_id as the speaker target
    # and entity_id as the TTS engine entity (e.g., tts.google_translate).
    # Ticker only stores the media player, not the TTS engine entity, so
    # entity_id is omitted — HA will use the default TTS engine.
    if tts_service and tts_service.lower() == "tts.speak":
        return {
            "media_player_entity_id": entity_id,
            "message": clean_message,
        }

    # Legacy pattern (default): entity_id IS the media_player.
    # Services like tts.google_translate_say, tts.cloud_say, etc.
    return {
        "entity_id": entity_id,
        "message": clean_message,
    }


def detect_delivery_format(service_id: str) -> str:
    """Infer delivery format from a notify service identifier.

    Evaluates patterns from DELIVERY_FORMAT_PATTERNS in order.
    First match wins. Falls back to 'rich' if no pattern matches.

    Args:
        service_id: The full service identifier (e.g., 'notify.nfandroidtv',
                     'tts.google_home').

    Returns:
        One of the DELIVERY_FORMATS constants ('rich', 'plain', 'tts',
        'persistent').
    """
    if not service_id:
        return DELIVERY_FORMAT_RICH

    service_lower = service_id.lower()

    for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
        if match_type == "startswith" and service_lower.startswith(pattern):
            return fmt
        if match_type == "contains" and pattern in service_lower:
            return fmt
        if match_type == "equals" and service_lower == pattern:
            return fmt

    return DELIVERY_FORMAT_RICH


def transform_payload_for_format(
    title: str,
    message: str,
    format_type: str,
    category_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transform a notification payload for a specific delivery format.

    Args:
        title: Notification title.
        message: Notification message (may contain HTML).
        format_type: Target delivery format (rich, plain, tts, persistent).
        category_id: Category ID, used for persistent notification tags.
        data: Optional additional data dict to include.

    Returns:
        Transformed payload dict ready for the service call.
    """
    title = title or ""
    message = message or ""

    if format_type == DELIVERY_FORMAT_PLAIN:
        payload: dict[str, Any] = {
            "title": strip_html(title),
            "message": strip_html(message),
        }
        if data:
            payload["data"] = dict(data)
        return payload

    if format_type == DELIVERY_FORMAT_TTS:
        return {"message": strip_html(message)}

    if format_type == DELIVERY_FORMAT_PERSISTENT:
        payload = {
            "title": title,
            "message": message,
        }
        if category_id:
            payload["notification_id"] = f"ticker_{category_id}"
        return payload

    # DELIVERY_FORMAT_RICH (default): pass-through
    payload = {
        "title": title,
        "message": message,
    }
    if data:
        payload["data"] = dict(data)
    return payload


def inject_critical_payload(service_data: dict[str, Any], format_type: str) -> None:
    """Inject platform-specific critical notification payload.

    Modifies service_data in-place based on detected delivery format:
    - plain (iOS): push.sound.critical, push.sound.name, push.sound.volume,
      push.interruption-level
    - rich (Android): importance, channel, priority

    Other formats (tts, persistent) are no-ops since they have no
    concept of critical priority.

    Args:
        service_data: The payload dict to mutate. Must already contain a
            'data' key for injection to occur.
        format_type: Delivery format string (rich, plain, tts, persistent).
    """
    if format_type == DELIVERY_FORMAT_PLAIN:
        data = service_data.setdefault("data", {})
        push = data.setdefault("push", {})
        push["sound"] = {"critical": 1, "name": "default", "volume": 1.0}
        push["interruption-level"] = "critical"
    elif format_type == DELIVERY_FORMAT_RICH:
        data = service_data.setdefault("data", {})
        data["importance"] = "high"
        data["channel"] = "ticker_critical"
        data["priority"] = "high"


def build_smart_tag(
    category_id: str, title: str | None, tag_mode: str
) -> str | None:
    """Build a tag string based on the smart tag mode.

    Args:
        category_id: The category slug identifier.
        title: Notification title (used for title-based tags).
        tag_mode: One of SMART_TAG_MODE_NONE, SMART_TAG_MODE_CATEGORY,
            or SMART_TAG_MODE_TITLE.

    Returns:
        A tag string, or None if tag_mode is 'none'.
    """
    if tag_mode == SMART_TAG_MODE_NONE:
        return None
    if tag_mode == SMART_TAG_MODE_CATEGORY:
        return f"ticker_{category_id}"
    if tag_mode == SMART_TAG_MODE_TITLE:
        return f"ticker_{category_id}_{slugify(title or 'untitled')}"
    return None


def inject_smart_notification(
    enriched_data: dict[str, Any],
    category_id: str,
    title: str | None,
    smart_config: dict[str, Any],
    delivery_format: str,
) -> None:
    """Inject smart notification fields into the data payload.

    Mutates enriched_data in-place. Only injects fields that the automation
    has not already set (automation values always take precedence). Skips
    entirely for TTS delivery format since TTS has no concept of grouping,
    tags, or sticky notifications.

    Args:
        enriched_data: The notification data dict to mutate.
        category_id: The category slug identifier.
        title: Notification title.
        smart_config: Smart notification config dict from the category.
        delivery_format: The resolved delivery format string.
    """
    if delivery_format in (DELIVERY_FORMAT_TTS, DELIVERY_FORMAT_PERSISTENT):
        return

    # Group: collapse notifications by category
    if smart_config.get("group") and "group" not in enriched_data:
        enriched_data["group"] = f"ticker_{category_id}"

    # Tag: replace previous notification (mode-dependent)
    tag_mode = smart_config.get("tag_mode", SMART_TAG_MODE_NONE)
    tag = build_smart_tag(category_id, title, tag_mode)
    if tag and "tag" not in enriched_data:
        enriched_data["tag"] = tag

    # Sticky: notification persists until user dismisses it
    if (
        smart_config.get("sticky") or smart_config.get("persistent")
    ) and "sticky" not in enriched_data:
        enriched_data["sticky"] = "true"

    # Persistent: notification survives app restart
    if smart_config.get("persistent") and "persistent" not in enriched_data:
        enriched_data["persistent"] = "true"


def inject_navigate_to(
    enriched_data: dict[str, Any],
    navigate_to: str | None,
    delivery_format: str,
) -> None:
    """Inject a clickAction/url into the data payload for tap-to-navigate.

    Mutates enriched_data in-place. Only applies to push formats (rich and
    plain) since TTS and persistent notifications have no concept of tap
    navigation. Respects existing values — if the automation already set a
    clickAction or url, this is a no-op.

    The value comes from (in priority order):
    1. Per-call ``navigate_to`` on ``ticker.notify``
    2. Category-level ``navigate_to`` field
    3. Global default ``DEFAULT_NAVIGATE_TO``

    Args:
        enriched_data: The notification data dict to mutate.
        navigate_to: The resolved navigation URL/path, or None to use the
            global default.
        delivery_format: The resolved delivery format string.
    """
    if delivery_format in (DELIVERY_FORMAT_TTS, DELIVERY_FORMAT_PERSISTENT):
        return

    url = navigate_to or DEFAULT_NAVIGATE_TO

    # Android (rich): clickAction
    if "clickAction" not in enriched_data:
        enriched_data["clickAction"] = url

    # iOS (plain): url
    if "url" not in enriched_data:
        enriched_data["url"] = url


def resolve_ios_platform(hass: HomeAssistant, service_id: str) -> bool:
    """Check whether a notify service belongs to an iOS device.

    Resolves the service to its parent device via the entity registry,
    then checks the linked mobile_app config entry for os_name == 'iOS'.
    This is authoritative and does not depend on the user-chosen device
    name (which is the flaw BUG-061 fixes).

    Args:
        hass: Home Assistant instance.
        service_id: Full notify service ID (e.g., 'notify.mobile_app_hans_s_phone').

    Returns:
        True if the service is confirmed to be an iOS mobile_app device.
    """
    if not service_id or not service_id.startswith("notify."):
        return False

    # Service ID and entity ID share the same format: notify.{suffix}
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    # Path 1: Direct entity lookup (modern notify entities)
    entity_entry = entity_reg.async_get(service_id)
    if entity_entry and entity_entry.device_id:
        if _check_device_ios(hass, device_reg, entity_entry.device_id):
            return True

    # Path 2: Legacy mobile_app — match by slugified device_name
    svc_suffix = service_id.split(".", 1)[1]
    if not svc_suffix.startswith("mobile_app_"):
        return False

    for entry in hass.config_entries.async_entries("mobile_app"):
        device_name = entry.data.get("device_name", "")
        if not device_name:
            continue
        if f"mobile_app_{slugify(device_name)}" == svc_suffix:
            os_name = entry.data.get("os_name", "")
            return os_name.lower() == "ios"

    return False


def _check_device_ios(
    hass: HomeAssistant,
    device_reg: dr.DeviceRegistry,
    device_id: str,
) -> bool:
    """Check if a device belongs to an iOS mobile_app config entry.

    Args:
        hass: Home Assistant instance.
        device_reg: Device registry.
        device_id: Device registry ID.

    Returns:
        True if any linked mobile_app config entry has os_name 'iOS'.
    """
    device = device_reg.async_get(device_id)
    if not device:
        return False
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == "mobile_app":
            os_name = entry.data.get("os_name", "")
            return os_name.lower() == "ios"
    return False
