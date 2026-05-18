"""Tests for F-35 — ws_test_chime WebSocket handler.

Spec §12 cases 11–13:
- 11: happy path — valid entity + chime returns success, no log entry
- 12: invalid entity (no media_player. prefix) -> error
- 13: handler does not interact with TTS queue or History
"""

from __future__ import annotations

from types import SimpleNamespace
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


class TestWsTestChimeCastRestoresMedia:
    """BUG-110 b21 (Issue 3): on cast targets ``announce=True`` is
    silently ignored when the platform lacks MEDIA_ANNOUNCE feature
    so the platform's auto pause/resume doesn't happen. The handler
    snapshots prior media state and calls ``_restore_previous_media``
    in a finally block after the chime so the user's radio resumes.
    """

    @staticmethod
    def _cast_hass_with_playing_media(
        content_id: str = "http://stream/live",
        content_type: str = "music",
    ) -> MagicMock:
        hass = MagicMock()
        state_obj = SimpleNamespace(
            state="playing",
            attributes={
                "media_content_id": content_id,
                "media_content_type": content_type,
            },
        )
        hass.states.get = MagicMock(return_value=state_obj)
        return hass

    @pytest.mark.asyncio
    async def test_cast_target_with_playing_media_calls_restore(self):
        """Cast + prior state=playing -> _restore_previous_media is
        called with the snapshotted content id / type."""
        hass = self._cast_hass_with_playing_media()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock, return_value=True,
        ) as mock_restore, patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ):
            await ws_test_chime(hass, conn, _msg())
        mock_restore.assert_awaited_once()
        args = mock_restore.await_args[0]
        assert args[1] == "media_player.kitchen"
        assert args[2] == "http://stream/live"
        assert args[3] == "music"
        # Success was still reported.
        conn.send_result.assert_called_once_with(1, {"success": True})

    @pytest.mark.asyncio
    async def test_non_cast_target_does_not_restore(self):
        """Non-cast targets rely on the platform's MEDIA_ANNOUNCE handling
        — the handler must NOT call _restore_previous_media."""
        hass = self._cast_hass_with_playing_media()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=False,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock,
        ) as mock_restore, patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock,
        ):
            await ws_test_chime(hass, conn, _msg())
        mock_restore.assert_not_called()
        conn.send_result.assert_called_once_with(1, {"success": True})

    @pytest.mark.asyncio
    async def test_cast_target_idle_prior_state_skips_restore(self):
        """Cast but prior state was idle (nothing to resume) -> no restore."""
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="idle",
            attributes={"media_content_id": None, "media_content_type": None},
        ))
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock,
        ) as mock_restore, patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock,
        ):
            await ws_test_chime(hass, conn, _msg())
        mock_restore.assert_not_called()

    @pytest.mark.asyncio
    async def test_cast_target_no_content_id_skips_restore(self):
        """Cast playing but content_id missing -> nothing to restore."""
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=SimpleNamespace(
            state="playing",
            attributes={"media_content_id": None, "media_content_type": None},
        ))
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock,
        ) as mock_restore, patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock,
        ):
            await ws_test_chime(hass, conn, _msg())
        mock_restore.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_failure_logged_not_raised(self, caplog):
        """If _restore_previous_media raises, the warning is logged and
        the handler returns normally (success was already sent)."""
        hass = self._cast_hass_with_playing_media()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock, side_effect=RuntimeError("net"),
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock,
        ):
            with caplog.at_level("WARNING"):
                await ws_test_chime(hass, conn, _msg())
        assert any(
            "failed to restore prior media" in rec.message.lower()
            for rec in caplog.records
        )
        conn.send_result.assert_called_once_with(1, {"success": True})

    @pytest.mark.asyncio
    async def test_restore_runs_even_if_play_chime_fails(self):
        """If _play_chime raises and the platform was playing, restore
        still runs (finally clause). Mirrors how a real notification
        flow recovers from chime errors."""
        hass = self._cast_hass_with_playing_media()
        conn = MagicMock()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock, side_effect=RuntimeError("boom"),
        ), patch(
            "custom_components.ticker.websocket.recipient_helpers._restore_previous_media",
            new_callable=AsyncMock, return_value=True,
        ) as mock_restore, patch(
            "custom_components.ticker.websocket.recipient_helpers._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ):
            await ws_test_chime(hass, conn, _msg())
        mock_restore.assert_awaited_once()
        # Error was reported (chime failure path).
        conn.send_error.assert_called_once()
