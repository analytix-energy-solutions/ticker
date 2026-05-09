"""Tests for F-35.1 — ws_get_bundled_chimes WebSocket handler.

Verifies:
- happy path returns 3 entries with absolute URLs composed from HA's
  external/internal URL + STATIC_CHIMES_PATH + filename;
- empty list when get_url raises NoURLAvailableError;
- empty list when get_url returns falsy;
- URL format ``<base>/ticker_static/chimes/<filename>`` (no double slash).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.const import BUNDLED_CHIMES, STATIC_CHIMES_PATH
from custom_components.ticker.websocket.recipient_helpers import (
    ws_get_bundled_chimes,
)


def _msg() -> dict:
    return {"id": 7, "type": "ticker/get_bundled_chimes"}


class TestWsGetBundledChimesHappyPath:
    @pytest.mark.asyncio
    async def test_returns_three_entries_with_urls(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "homeassistant.helpers.network.get_url",
            return_value="http://homeassistant.local:8123",
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        conn.send_result.assert_called_once()
        args = conn.send_result.call_args[0]
        assert args[0] == 7
        result = args[1]
        assert "chimes" in result
        chimes = result["chimes"]
        assert len(chimes) == 3
        for c in chimes:
            assert "id" in c and "label" in c and "url" in c
            assert c["url"].startswith("http://homeassistant.local:8123")
            assert STATIC_CHIMES_PATH in c["url"]
            assert c["url"].endswith(".wav")

    @pytest.mark.asyncio
    async def test_url_format_no_double_slash(self):
        hass = MagicMock()
        conn = MagicMock()
        # Trailing slash on the base URL must be normalised so we don't
        # get ``...:8123//ticker_static``.
        with patch(
            "homeassistant.helpers.network.get_url",
            return_value="http://example.com/",
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        chimes = conn.send_result.call_args[0][1]["chimes"]
        for c in chimes:
            assert "//" not in c["url"].split("://", 1)[1]

    @pytest.mark.asyncio
    async def test_ids_match_const_table(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "homeassistant.helpers.network.get_url",
            return_value="https://ha.local",
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        chimes = conn.send_result.call_args[0][1]["chimes"]
        returned_ids = {c["id"] for c in chimes}
        expected_ids = {entry["id"] for entry in BUNDLED_CHIMES}
        assert returned_ids == expected_ids


class TestWsGetBundledChimesNoUrl:
    @pytest.mark.asyncio
    async def test_returns_empty_when_get_url_raises(self):
        """NoURLAvailableError -> empty list, no error sent."""
        from homeassistant.helpers.network import NoURLAvailableError

        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "homeassistant.helpers.network.get_url",
            side_effect=NoURLAvailableError("no url"),
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result == {"chimes": []}
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_get_url_returns_none(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "homeassistant.helpers.network.get_url",
            return_value=None,
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result == {"chimes": []}

    @pytest.mark.asyncio
    async def test_returns_empty_on_unexpected_error(self):
        """Defensive: any other exception from get_url falls through to []."""
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "homeassistant.helpers.network.get_url",
            side_effect=RuntimeError("upstream broke"),
        ):
            await ws_get_bundled_chimes(hass, conn, _msg())
        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result == {"chimes": []}
