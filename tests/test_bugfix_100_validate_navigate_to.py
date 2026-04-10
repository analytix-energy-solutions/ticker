"""Tests for BUG-100: validate_navigate_to rejects unsafe values.

navigate_to must be a relative path (e.g. /lovelace/0) and reject:
- absolute URLs with protocols
- javascript: schemes
- protocol-relative URLs (//evil.com)
- path traversal (../escape)
- control characters
- over-length strings

None and empty string pass through as "use default".
"""

from __future__ import annotations

import pytest

from custom_components.ticker.const import MAX_NAVIGATE_TO_LENGTH
from custom_components.ticker.websocket.validation import validate_navigate_to


class TestBug100ValidateNavigateTo:

    # ----- valid values -----

    def test_none_passes(self):
        is_valid, err = validate_navigate_to(None)
        assert is_valid is True
        assert err is None

    def test_empty_string_passes(self):
        is_valid, err = validate_navigate_to("")
        assert is_valid is True
        assert err is None

    def test_relative_lovelace_path_passes(self):
        is_valid, err = validate_navigate_to("/lovelace/0")
        assert is_valid is True
        assert err is None

    def test_relative_nested_path_passes(self):
        is_valid, _err = validate_navigate_to("/lovelace/home")
        assert is_valid is True

    # ----- rejected values -----

    @pytest.mark.parametrize(
        "value",
        [
            "https://evil.com",
            "http://example.com/path",
            "javascript:alert(1)",
            "//evil.com",
            "../escape",
            "lovelace/0",  # missing leading slash
        ],
    )
    def test_unsafe_values_rejected(self, value):
        is_valid, err = validate_navigate_to(value)
        assert is_valid is False
        assert err

    def test_control_characters_rejected(self):
        is_valid, err = validate_navigate_to("/lovelace\x00/0")
        assert is_valid is False
        assert err

    def test_control_character_tab_rejected(self):
        is_valid, _err = validate_navigate_to("/lovelace\t/0")
        assert is_valid is False

    def test_over_length_rejected(self):
        value = "/" + ("a" * (MAX_NAVIGATE_TO_LENGTH + 10))
        is_valid, err = validate_navigate_to(value)
        assert is_valid is False
        assert err

    def test_non_string_rejected(self):
        is_valid, err = validate_navigate_to(123)
        assert is_valid is False
        assert err

    def test_embedded_scheme_rejected(self):
        """A value that embeds '://' anywhere should be rejected."""
        is_valid, _err = validate_navigate_to("/foo://bar")
        assert is_valid is False
