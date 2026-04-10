"""Tests for const.py v1.4.0 changes.

Verifies new constants, removed patterns, and structural requirements.
"""

from __future__ import annotations


from custom_components.ticker.const import (
    DELIVERY_FORMAT_PATTERNS,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMATS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    DEVICE_TYPES,
    MEDIA_ANNOUNCE_FEATURE,
    RECIPIENT_DELIVERY_FORMATS,
    TTS_PLAYBACK_MAX_TIMEOUT,
    TTS_PLAYBACK_START_TIMEOUT,
    TTS_POLL_INTERVAL,
    VERSION,
)


class TestVersion:
    def test_version_is_valid_semver(self):
        """Version string is valid semver (X.Y.Z)."""
        parts = VERSION.split(".")
        assert len(parts) == 3, f"Expected X.Y.Z, got {VERSION}"
        for p in parts:
            assert p.isdigit(), f"Non-numeric version part: {p}"


class TestDeviceTypes:
    def test_push_and_tts_defined(self):
        assert DEVICE_TYPE_PUSH == "push"
        assert DEVICE_TYPE_TTS == "tts"

    def test_device_types_list(self):
        assert DEVICE_TYPE_PUSH in DEVICE_TYPES
        assert DEVICE_TYPE_TTS in DEVICE_TYPES


class TestDeliveryFormats:
    def test_all_formats_in_list(self):
        assert DELIVERY_FORMAT_RICH in DELIVERY_FORMATS
        assert DELIVERY_FORMAT_PLAIN in DELIVERY_FORMATS
        assert DELIVERY_FORMAT_TTS in DELIVERY_FORMATS
        assert DELIVERY_FORMAT_PERSISTENT in DELIVERY_FORMATS

    def test_recipient_formats_no_tts(self):
        """TTS is a device type, not a valid recipient delivery format."""
        assert DELIVERY_FORMAT_TTS not in RECIPIENT_DELIVERY_FORMATS
        assert DELIVERY_FORMAT_RICH in RECIPIENT_DELIVERY_FORMATS
        assert DELIVERY_FORMAT_PLAIN in RECIPIENT_DELIVERY_FORMATS

    def test_recipient_formats_no_persistent(self):
        """Persistent is handled via push device type, not a recipient format."""
        assert DELIVERY_FORMAT_PERSISTENT not in RECIPIENT_DELIVERY_FORMATS


class TestDeliveryFormatPatterns:
    def test_no_iphone_patterns(self):
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert "iphone" not in pattern.lower()

    def test_no_ipad_patterns(self):
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert "ipad" not in pattern.lower()

    def test_no_tts_patterns(self):
        """TTS is now a device type, patterns should not detect TTS format."""
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert fmt != DELIVERY_FORMAT_TTS

    def test_persistent_notification_pattern_exists(self):
        found = any(
            pattern == "notify.persistent_notification" and fmt == DELIVERY_FORMAT_PERSISTENT
            for _, pattern, fmt in DELIVERY_FORMAT_PATTERNS
        )
        assert found

    def test_pattern_tuples_are_valid(self):
        valid_match_types = {"startswith", "contains", "equals"}
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert match_type in valid_match_types, f"Invalid match_type: {match_type}"
            assert isinstance(pattern, str)
            assert fmt in DELIVERY_FORMATS


class TestTtsConstants:
    def test_playback_start_timeout(self):
        assert TTS_PLAYBACK_START_TIMEOUT == 5.0

    def test_playback_max_timeout(self):
        assert TTS_PLAYBACK_MAX_TIMEOUT == 60.0

    def test_poll_interval(self):
        assert TTS_POLL_INTERVAL == 0.5

    def test_media_announce_feature(self):
        assert MEDIA_ANNOUNCE_FEATURE == 524288
