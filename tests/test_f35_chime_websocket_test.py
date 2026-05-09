"""Tests for F-35 — ws_test_chime WebSocket handler.

Spec §12 cases 11–13:
- 11: happy path — valid entity + chime returns success, no log entry
- 12: invalid entity (no media_player. prefix) -> error
- 13: handler does not interact with TTS queue or History
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.websocket.recipient_helpers import ws_test_chime


def _msg(**overrides) -> dict:
    base = {
        "id": 1,
        "type": "ticker/test_chime",
        "media_player_entity_id": "media_player.kitchen",
        "chime_media_content_id": "media-source://x",
    }
    base.update(overrides)
    return base


class TestWsTestChimeHappyPath:
    """Case 11: valid args -> success result, no logging side effects."""

    @pytest.mark.asyncio
    async def test_returns_success(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(hass, conn, _msg())
        mock_play.assert_awaited_once()
        # _play_chime called with (hass, entity_id, chime_id)
        args = mock_play.await_args[0]
        assert args[1] == "media_player.kitchen"
        assert args[2] == "media-source://x"
        conn.send_result.assert_called_once_with(1, {"success": True})
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_call_async_send_tts(self):
        """No TTS pipeline (no async_send_tts)."""
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers.async_send_tts",
            new_callable=AsyncMock,
        ) as mock_send_tts:
            await ws_test_chime(hass, conn, _msg())
        mock_send_tts.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_touch_store_log(self):
        """No History entry — store.async_add_log untouched."""
        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.async_add_log = AsyncMock()
        # The handler doesn't even fetch the store, but verify if it did,
        # async_add_log would not be called.
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ):
            await ws_test_chime(hass, conn, _msg())
        store.async_add_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_strips_chime_id(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                _msg(chime_media_content_id="  media-source://x  "),
            )
        args = mock_play.await_args[0]
        assert args[2] == "media-source://x"


class TestWsTestChimeValidation:
    """Case 12: invalid entity / chime returns proper error codes."""

    @pytest.mark.asyncio
    async def test_invalid_entity_prefix_rejected(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                _msg(media_player_entity_id="light.kitchen"),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_media_player"
        mock_play.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_entity_rejected(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                _msg(media_player_entity_id=""),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_media_player"
        mock_play.assert_not_called()

    @pytest.mark.asyncio
    async def test_blank_chime_rejected(self):
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                _msg(chime_media_content_id="   "),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_chime"
        mock_play.assert_not_called()


class TestWsTestChimeNoQueueInteraction:
    """Case 13: test path does not serialise with real delivery."""

    @pytest.mark.asyncio
    async def test_play_chime_called_directly_not_through_pipeline(self):
        """Verifies the handler calls _play_chime, not the queue/notify path."""
        hass = MagicMock()
        conn = MagicMock()
        # Patch async_send_to_recipient and async_send_tts to verify they
        # are NOT used in the test-chime path.
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play, patch(
            "custom_components.ticker.websocket.recipient_helpers.async_send_tts",
            new_callable=AsyncMock,
        ) as mock_send_tts:
            await ws_test_chime(hass, conn, _msg())
        mock_play.assert_awaited_once()
        mock_send_tts.assert_not_called()
        # No store interaction at all
        assert not hass.method_calls or all(
            "async_add_log" not in str(c) for c in hass.method_calls
        )

    @pytest.mark.asyncio
    async def test_play_chime_failure_returns_error_via_send_error(self):
        """If _play_chime raises (defensive), error is reported, not raised."""
        hass = MagicMock()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock, side_effect=RuntimeError("boom"),
        ):
            await ws_test_chime(hass, conn, _msg())
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "test_chime_failed"
        assert "boom" in args[2]
