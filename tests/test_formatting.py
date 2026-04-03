"""Tests for custom_components.ticker.formatting module.

Covers strip_html, detect_delivery_format, and transform_payload_for_format.
"""

from __future__ import annotations

import pytest

from custom_components.ticker.formatting import (
    build_tts_payload,
    detect_delivery_format,
    detect_device_type,
    inject_critical_payload,
    strip_html,
    transform_payload_for_format,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMAT_PERSISTENT,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
)


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    """Tests for strip_html()."""

    def test_removes_simple_tags(self):
        assert strip_html("<b>bold</b>") == "bold"

    def test_removes_nested_tags(self):
        assert strip_html("<div><p>hello</p></div>") == "hello"

    def test_removes_self_closing_tags(self):
        assert strip_html("line<br/>break") == "linebreak"

    def test_removes_tags_with_attributes(self):
        assert strip_html('<a href="http://example.com">link</a>') == "link"

    def test_preserves_plain_text(self):
        assert strip_html("no tags here") == "no tags here"

    def test_empty_string_returns_empty(self):
        assert strip_html("") == ""

    def test_none_returns_none(self):
        """strip_html returns falsy input as-is (guard: `if not text`)."""
        result = strip_html(None)
        assert result is None

    def test_only_tags_returns_empty(self):
        assert strip_html("<br><hr>") == ""

    def test_mixed_content(self):
        html = "<h1>Title</h1><p>Paragraph with <em>emphasis</em>.</p>"
        assert strip_html(html) == "TitleParagraph with emphasis."


# ---------------------------------------------------------------------------
# detect_delivery_format
# ---------------------------------------------------------------------------

class TestDetectDeliveryFormat:
    """Tests for detect_delivery_format()."""

    def test_empty_string_returns_rich(self):
        assert detect_delivery_format("") == DELIVERY_FORMAT_RICH

    def test_none_returns_rich(self):
        assert detect_delivery_format(None) == DELIVERY_FORMAT_RICH

    def test_tts_service_returns_rich(self):
        """TTS is now a device type, not a delivery format. tts.* falls through to rich."""
        assert detect_delivery_format("tts.google_home") == DELIVERY_FORMAT_RICH

    def test_tts_case_insensitive_returns_rich(self):
        assert detect_delivery_format("TTS.Google_Home") == DELIVERY_FORMAT_RICH

    def test_alexa_media_returns_rich(self):
        """alexa_media is now handled as device_type=tts, not delivery format."""
        assert detect_delivery_format("notify.alexa_media_echo") == DELIVERY_FORMAT_RICH

    def test_persistent_notification_exact(self):
        assert detect_delivery_format("notify.persistent_notification") == DELIVERY_FORMAT_PERSISTENT

    def test_persistent_notification_case_insensitive(self):
        assert detect_delivery_format("Notify.Persistent_Notification") == DELIVERY_FORMAT_PERSISTENT

    def test_nfandroidtv_contains(self):
        assert detect_delivery_format("notify.nfandroidtv") == DELIVERY_FORMAT_RICH

    def test_mobile_app_contains(self):
        assert detect_delivery_format("notify.mobile_app_pixel") == DELIVERY_FORMAT_RICH

    def test_unknown_service_falls_back_to_rich(self):
        assert detect_delivery_format("notify.some_unknown_service") == DELIVERY_FORMAT_RICH

    def test_iphone_returns_rich_after_bug061(self):
        """BUG-061: iPhone services no longer pattern-matched to plain.
        iOS detection moved to resolve_ios_platform() registry lookup."""
        assert detect_delivery_format("notify.mobile_app_iphone") == DELIVERY_FORMAT_RICH


# ---------------------------------------------------------------------------
# transform_payload_for_format
# ---------------------------------------------------------------------------

class TestTransformPayloadForFormat:
    """Tests for transform_payload_for_format()."""

    # -- Rich (default) --

    def test_rich_basic(self):
        result = transform_payload_for_format("Title", "Message", DELIVERY_FORMAT_RICH)
        assert result == {"title": "Title", "message": "Message"}

    def test_rich_with_data(self):
        data = {"image": "http://img.png", "priority": "high"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_RICH, data=data)
        assert result["data"] == {"image": "http://img.png", "priority": "high"}

    def test_rich_data_is_copied(self):
        data = {"key": "val"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_RICH, data=data)
        result["data"]["key"] = "changed"
        assert data["key"] == "val", "Original dict must not be mutated"

    def test_rich_no_data_key_when_none(self):
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_RICH)
        assert "data" not in result

    # -- Plain --

    def test_plain_strips_html(self):
        result = transform_payload_for_format("T", "<b>Bold</b>", DELIVERY_FORMAT_PLAIN)
        assert result["message"] == "Bold"

    def test_plain_preserves_image_in_data(self):
        """BUG-079: Plain format no longer strips image keys."""
        data = {"image": "http://img.png", "priority": "high"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["image"] == "http://img.png"
        assert result["data"]["priority"] == "high"

    def test_plain_preserves_image_only_data(self):
        """BUG-079: Plain format no longer strips image keys."""
        data = {"image": "http://img.png"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["image"] == "http://img.png"

    def test_plain_no_data(self):
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN)
        assert "data" not in result

    # -- TTS --

    def test_tts_only_message(self):
        result = transform_payload_for_format("Title", "<p>Speak this</p>", DELIVERY_FORMAT_TTS)
        assert result == {"message": "Speak this"}

    def test_tts_no_title(self):
        result = transform_payload_for_format("Title", "Hello", DELIVERY_FORMAT_TTS)
        assert "title" not in result

    def test_tts_no_data(self):
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_TTS, data={"k": "v"})
        assert "data" not in result

    # -- Persistent --

    def test_persistent_basic(self):
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PERSISTENT)
        assert result == {"title": "T", "message": "M"}

    def test_persistent_with_category_id(self):
        result = transform_payload_for_format(
            "T", "M", DELIVERY_FORMAT_PERSISTENT, category_id="weather_alert"
        )
        assert result["notification_id"] == "ticker_weather_alert"

    def test_persistent_no_category_no_notification_id(self):
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PERSISTENT)
        assert "notification_id" not in result

    def test_persistent_preserves_html(self):
        result = transform_payload_for_format("T", "<b>Bold</b>", DELIVERY_FORMAT_PERSISTENT)
        assert result["message"] == "<b>Bold</b>"

    # -- None / empty inputs --

    def test_none_title_becomes_empty(self):
        result = transform_payload_for_format(None, "M", DELIVERY_FORMAT_RICH)
        assert result["title"] == ""

    def test_none_message_becomes_empty(self):
        result = transform_payload_for_format("T", None, DELIVERY_FORMAT_RICH)
        assert result["message"] == ""

    # -- Plain title HTML stripping --

    def test_plain_strips_html_from_title(self):
        result = transform_payload_for_format(
            "<b>Alert</b>", "msg", DELIVERY_FORMAT_PLAIN
        )
        assert result["title"] == "Alert"

    def test_plain_preserves_image_url_in_data(self):
        """BUG-079: Plain format no longer strips image_url."""
        data = {"image_url": "http://img.png", "priority": "high"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["image_url"] == "http://img.png"
        assert result["data"]["priority"] == "high"

    def test_plain_preserves_attachment_in_data(self):
        """BUG-079: Plain format no longer strips attachment."""
        data = {"attachment": {"url": "http://img.png"}, "sound": "default"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["attachment"] == {"url": "http://img.png"}
        assert result["data"]["sound"] == "default"

    def test_plain_preserves_all_image_keys(self):
        """BUG-079: Plain format preserves all image-related keys."""
        data = {"image": "a", "image_url": "b", "attachment": "c"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["image"] == "a"
        assert result["data"]["image_url"] == "b"
        assert result["data"]["attachment"] == "c"

    def test_plain_data_is_copied(self):
        """BUG-079: Plain format copies data dict, does not mutate original."""
        data = {"image": "http://img.png", "key": "val"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        result["data"]["key"] = "changed"
        assert data["key"] == "val", "Original dict must not be mutated"

    def test_plain_with_rich_data_keys(self):
        """BUG-079: Plain format passes through clickAction and other rich keys."""
        data = {"clickAction": "/dashboard", "image": "http://img.png"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_PLAIN, data=data)
        assert result["data"]["clickAction"] == "/dashboard"
        assert result["data"]["image"] == "http://img.png"

    def test_rich_preserves_image_keys(self):
        """Regression: rich format still passes image keys through."""
        data = {"image": "a", "image_url": "b", "attachment": "c"}
        result = transform_payload_for_format("T", "M", DELIVERY_FORMAT_RICH, data=data)
        assert result["data"]["image"] == "a"
        assert result["data"]["image_url"] == "b"
        assert result["data"]["attachment"] == "c"


# ---------------------------------------------------------------------------
# detect_device_type
# ---------------------------------------------------------------------------

class TestDetectDeviceType:
    """Tests for detect_device_type()."""

    def test_tts_service_returns_tts(self):
        assert detect_device_type("tts.google_translate_say") == DEVICE_TYPE_TTS

    def test_tts_case_insensitive(self):
        assert detect_device_type("TTS.Cloud_Say") == DEVICE_TYPE_TTS

    def test_alexa_media_returns_tts(self):
        assert detect_device_type("notify.alexa_media_echo") == DEVICE_TYPE_TTS

    def test_mobile_app_returns_push(self):
        assert detect_device_type("notify.mobile_app_pixel") == DEVICE_TYPE_PUSH

    def test_empty_returns_push(self):
        assert detect_device_type("") == DEVICE_TYPE_PUSH

    def test_none_returns_push(self):
        assert detect_device_type(None) == DEVICE_TYPE_PUSH

    def test_generic_notify_returns_push(self):
        assert detect_device_type("notify.some_service") == DEVICE_TYPE_PUSH


# ---------------------------------------------------------------------------
# build_tts_payload
# ---------------------------------------------------------------------------

class TestBuildTtsPayload:
    """Tests for build_tts_payload()."""

    def test_legacy_basic(self):
        result = build_tts_payload("Hello world", "media_player.kitchen")
        assert result == {
            "entity_id": "media_player.kitchen",
            "message": "Hello world",
        }

    def test_legacy_strips_html(self):
        result = build_tts_payload("<b>Alert!</b> Fire", "media_player.living")
        assert result["message"] == "Alert! Fire"

    def test_legacy_with_explicit_service(self):
        result = build_tts_payload(
            "Test", "media_player.office", tts_service="tts.google_translate_say"
        )
        assert result == {
            "entity_id": "media_player.office",
            "message": "Test",
        }
        assert "media_player_entity_id" not in result

    def test_modern_tts_speak(self):
        """BUG-053: tts.speak omits entity_id, uses only media_player_entity_id."""
        result = build_tts_payload(
            "Hello", "media_player.kitchen", tts_service="tts.speak"
        )
        assert "entity_id" not in result
        assert result["media_player_entity_id"] == "media_player.kitchen"
        assert result["message"] == "Hello"

    def test_modern_tts_speak_case_insensitive(self):
        result = build_tts_payload(
            "Hello", "media_player.kitchen", tts_service="TTS.Speak"
        )
        assert "media_player_entity_id" in result

    def test_none_message_becomes_empty_string(self):
        result = build_tts_payload(None, "media_player.kitchen")
        assert result["message"] == ""

    def test_no_tts_service_uses_legacy(self):
        result = build_tts_payload("msg", "media_player.x", tts_service=None)
        assert "media_player_entity_id" not in result


# ---------------------------------------------------------------------------
# inject_critical_payload
# ---------------------------------------------------------------------------

class TestInjectCriticalPayload:
    """Tests for inject_critical_payload()."""

    def test_plain_ios_injection(self):
        sd = {"title": "T", "message": "M", "data": {}}
        inject_critical_payload(sd, DELIVERY_FORMAT_PLAIN)
        assert sd["data"]["push"]["sound"]["critical"] == 1
        assert sd["data"]["push"]["sound"]["name"] == "default"
        assert sd["data"]["push"]["sound"]["volume"] == 1.0
        assert sd["data"]["push"]["interruption-level"] == "critical"

    def test_plain_creates_data_if_missing(self):
        sd = {"title": "T", "message": "M"}
        inject_critical_payload(sd, DELIVERY_FORMAT_PLAIN)
        assert "push" in sd["data"]

    def test_rich_android_injection(self):
        sd = {"title": "T", "message": "M", "data": {}}
        inject_critical_payload(sd, DELIVERY_FORMAT_RICH)
        assert sd["data"]["importance"] == "high"
        assert sd["data"]["channel"] == "ticker_critical"
        assert sd["data"]["priority"] == "high"

    def test_rich_creates_data_if_missing(self):
        sd = {"title": "T", "message": "M"}
        inject_critical_payload(sd, DELIVERY_FORMAT_RICH)
        assert sd["data"]["importance"] == "high"

    def test_tts_is_noop(self):
        sd = {"message": "M"}
        inject_critical_payload(sd, DELIVERY_FORMAT_TTS)
        assert "data" not in sd

    def test_persistent_is_noop(self):
        sd = {"title": "T", "message": "M"}
        inject_critical_payload(sd, DELIVERY_FORMAT_PERSISTENT)
        assert "data" not in sd

    def test_rich_preserves_existing_data(self):
        sd = {"data": {"existing_key": "value"}}
        inject_critical_payload(sd, DELIVERY_FORMAT_RICH)
        assert sd["data"]["existing_key"] == "value"
        assert sd["data"]["importance"] == "high"

    def test_plain_preserves_existing_data(self):
        sd = {"data": {"existing_key": "value"}}
        inject_critical_payload(sd, DELIVERY_FORMAT_PLAIN)
        assert sd["data"]["existing_key"] == "value"
        assert "push" in sd["data"]
