"""Tests for F-35.2 — Test Chime path applies the volume override (chunk 3).

Covers:
- _play_chime with volume_level: snapshot vol, set override, play, restore.
- _play_chime without volume_level: behavior unchanged from F-35.1.
- ws_test_chime accepts volume_override and passes it to _play_chime.
- ws_test_chime without volume_override: behavior unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.recipient_tts_delivery import _play_chime
from custom_components.ticker.websocket.recipient_helpers import ws_test_chime


def _make_hass(volume_level: float | None = 0.4) -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    attrs: dict = {"supported_features": 0}
    if volume_level is not None:
        attrs["volume_level"] = volume_level
    state_obj = SimpleNamespace(
        entity_id="media_player.kitchen", state="idle", attributes=attrs,
    )
    hass.states.get = MagicMock(return_value=state_obj)
    return hass


# ---------------------------------------------------------------------------
# _play_chime with volume_level
# ---------------------------------------------------------------------------


class TestPlayChimeVolumeLevel:
    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_with_volume_level_snapshots_sets_restores(self, _we):
        hass = _make_hass(volume_level=0.4)
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _play_chime(
                hass, "media_player.kitchen",
                "media-source://x",
                volume_level=0.85,
            )

        calls = hass.services.async_call.call_args_list
        # Order: volume_set(0.85), play_media(chime), volume_set(0.4)
        assert calls[0][0][1] == "volume_set"
        assert calls[0][0][2]["volume_level"] == 0.85
        assert calls[1][0][1] == "play_media"
        assert calls[1][0][2]["media_content_id"] == "media-source://x"
        assert calls[2][0][1] == "volume_set"
        assert calls[2][0][2]["volume_level"] == 0.4

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_without_volume_level_no_volume_calls(self, _we):
        hass = _make_hass(volume_level=0.4)
        await _play_chime(hass, "media_player.kitchen", "media-source://x")
        calls = hass.services.async_call.call_args_list
        # Only one call — play_media. No volume_set.
        assert len(calls) == 1
        assert calls[0][0][1] == "play_media"

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_level_out_of_range_no_volume_calls(self, _we):
        """Out-of-range volume_level is treated as None — no volume_set."""
        hass = _make_hass(volume_level=0.4)
        await _play_chime(
            hass, "media_player.kitchen", "media-source://x",
            volume_level=1.5,  # invalid
        )
        calls = hass.services.async_call.call_args_list
        assert len(calls) == 1
        assert calls[0][0][1] == "play_media"

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_no_snapshot_when_attribute_missing(self, _we):
        """FIX-001 Option A: cold-device behavior — if the entity has
        no volume_level attribute, the override is silently skipped
        (no apply, no restore) so we never permanently change the
        device's volume. Only play_media is called."""
        hass = _make_hass(volume_level=None)  # no volume_level attr
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _play_chime(
                hass, "media_player.kitchen", "media-source://x",
                volume_level=0.85,
            )
        calls = hass.services.async_call.call_args_list
        names = [c[0][1] for c in calls]
        # Cold-device: no volume_set at all, only the chime play_media.
        assert names == ["play_media"]


# ---------------------------------------------------------------------------
# ws_test_chime — schema accepts volume_override
# ---------------------------------------------------------------------------


class TestWsTestChimeVolume:

    def _make_conn(self):
        conn = MagicMock()
        conn.send_result = MagicMock()
        conn.send_error = MagicMock()
        return conn

    @pytest.mark.asyncio
    async def test_with_volume_override_passes_to_play_chime(self):
        hass = MagicMock()
        conn = self._make_conn()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                {
                    "id": 1,
                    "type": "ticker/test_chime",
                    "media_player_entity_id": "media_player.kitchen",
                    "chime_media_content_id": "media-source://x",
                    "volume_override": 0.6,
                },
            )

        mock_play.assert_awaited_once()
        call = mock_play.await_args
        # positional: (hass, entity_id, chime_id, ...)
        assert call.args[0] is hass
        assert call.args[1] == "media_player.kitchen"
        assert call.args[2] == "media-source://x"
        # kwargs: announce + volume_level
        assert call.kwargs["announce"] is True
        assert call.kwargs["volume_level"] == 0.6
        conn.send_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_volume_override_passes_none(self):
        hass = MagicMock()
        conn = self._make_conn()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                {
                    "id": 1,
                    "type": "ticker/test_chime",
                    "media_player_entity_id": "media_player.kitchen",
                    "chime_media_content_id": "media-source://x",
                },
            )
        call = mock_play.await_args
        assert call.kwargs["volume_level"] is None
        conn.send_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_entity_returns_error_even_with_volume(self):
        hass = MagicMock()
        conn = self._make_conn()
        await ws_test_chime(
            hass, conn,
            {
                "id": 1,
                "type": "ticker/test_chime",
                "media_player_entity_id": "switch.bad",
                "chime_media_content_id": "media-source://x",
                "volume_override": 0.5,
            },
        )
        conn.send_error.assert_called_once()
        code = conn.send_error.call_args[0][1]
        assert code == "invalid_media_player"

    @pytest.mark.asyncio
    async def test_explicit_none_volume_passes_none(self):
        hass = MagicMock()
        conn = self._make_conn()
        with patch(
            "custom_components.ticker.websocket.recipient_helpers._play_chime",
            new_callable=AsyncMock,
        ) as mock_play:
            await ws_test_chime(
                hass, conn,
                {
                    "id": 1,
                    "type": "ticker/test_chime",
                    "media_player_entity_id": "media_player.kitchen",
                    "chime_media_content_id": "media-source://x",
                    "volume_override": None,
                },
            )
        call = mock_play.await_args
        assert call.kwargs["volume_level"] is None
