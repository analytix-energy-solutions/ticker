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


class TestPlayChimeVolumeLevelNonCast:
    """_play_chime volume override on non-cast targets: simple
    pre-set/restore pattern (BUG-109 iteration 2 reverts non-cast to
    the pre-BUG-109 single-set flow)."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_chime._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_with_volume_level_snapshots_sets_restores(self, _we, _cast):
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
        # BUG-109 iteration 2 — non-cast simple flow:
        # 0) volume_set(0.85)           ← single set, no jiggle
        # 1) play_media(chime)
        # 2) volume_set(0.4)            ← single restore
        assert calls[0][0][1] == "volume_set"
        assert calls[0][0][2]["volume_level"] == 0.85
        assert calls[1][0][1] == "play_media"
        assert calls[1][0][2]["media_content_id"] == "media-source://x"
        assert calls[2][0][1] == "volume_set"
        assert calls[2][0][2]["volume_level"] == 0.4
        assert len(calls) == 3

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_chime._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_without_volume_level_no_volume_calls(self, _we, _cast):
        hass = _make_hass(volume_level=0.4)
        await _play_chime(hass, "media_player.kitchen", "media-source://x")
        calls = hass.services.async_call.call_args_list
        # Only one call — play_media. No volume_set.
        assert len(calls) == 1
        assert calls[0][0][1] == "play_media"

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_chime._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_level_out_of_range_no_volume_calls(self, _we, _cast):
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
        "custom_components.ticker.recipient_tts_chime._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_no_snapshot_when_attribute_missing(self, _we, _cast):
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


class TestPlayChimeVolumeLevelCast:
    """_play_chime volume override on cast targets: pre-set + jiggle +
    play_media + wait_complete + restore (BUG-109 iteration 3 hybrid,
    v1.7.0b17). The iteration-2 deferred-only pattern was reverted on
    the chime path because the chime app was loading at the pre-test
    volume before the deferred apply landed — devastating for short
    chime audio. Pre-set hits the cast receiver before the chime app
    spins up so the app loads at the override gain.

    BUG-110 (WONTFIX, v1.7.0b20): cast play_media for the chime is
    bit-identical to non-cast — music + caller-passed announce flag,
    no `extra` parameter. Two experimental cast-only fixes (b18:
    audio/wav + announce=True; b19: extra.stream_type=LIVE) were
    tested in-room and either had no effect or caused cross-context
    regressions. The cast DMR ~1-2s swallow window is upstream — not
    workaroundable via play_media params. See BUGS.md BUG-110.
    """

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_chime._is_cast_target",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_cast_pre_sets_override_before_chime_play_media(
        self, _we, _w, _cast,
    ):
        hass = _make_hass(volume_level=0.4)
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _play_chime(
                hass, "media_player.kitchen",
                "media-source://x",
                volume_level=0.85,
            )

        calls = hass.services.async_call.call_args_list
        names = [c[0][1] for c in calls]
        # Cast hybrid (iteration 3): pre-set volume_set (jiggle + target)
        # MUST come BEFORE play_media(chime) so the chime app loads at
        # the override gain. Then play_media + wait_complete. Then
        # restore (jiggle 0.15 + target 0.4).
        first_play_idx = names.index("play_media")
        first_vol_idx = names.index("volume_set")
        assert first_vol_idx < first_play_idx, (
            "Cast hybrid: pre-set volume_set should precede "
            f"play_media; got {names}"
        )
        # Verify jiggle target sequence — 0.85 and 0.4 must both be
        # present as targets.
        vol_levels = [
            c[0][2]["volume_level"] for c in calls
            if c[0][1] == "volume_set"
        ]
        assert 0.85 in vol_levels
        assert 0.4 in vol_levels
        assert pytest.approx(0.60) in vol_levels  # override jiggle
        assert pytest.approx(0.15) in vol_levels  # restore jiggle
        # Hybrid call shape: 4 volume_set + 1 play_media = 5 calls.
        assert len(calls) == 5
        assert names == [
            "volume_set", "volume_set",  # pre-set jiggle + target
            "play_media",                  # chime
            "volume_set", "volume_set",  # restore jiggle + snapshot
        ]
        # BUG-110 WONTFIX (v1.7.0b20): cast play_media is bit-identical
        # to non-cast — music + caller-passed announce flag, no `extra`.
        play_call = calls[first_play_idx]
        play_data = play_call[0][2]
        assert play_data["media_content_type"] == "music"
        assert play_data["announce"] is False
        assert "extra" not in play_data


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
