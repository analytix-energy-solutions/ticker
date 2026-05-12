"""Tests for F-35.2 Volume Override — backend delivery (chunk 2).

Covers:
- _resolve_volume: recipient default, category override, none, in/out of range.
- _is_valid_volume edge cases.
- _set_volume: success path, fail-soft, settle delay.
- async_send_tts plain/restore/announce branches: snapshot before chime,
  override applied, restored after TTS exits playing.
- Caller-supplied volume= kwarg overrides resolved value (test-chime path).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.ticker.recipient_tts import (
    _resolve_volume,
    _set_volume,
    _snapshot_volume,
    async_send_tts,
)
from custom_components.ticker.recipient_tts_delivery import _is_valid_volume
from custom_components.ticker.const import (
    MEDIA_ANNOUNCE_FEATURE,
    VOLUME_SET_SETTLE_DELAY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass(
    entity_id: str | None = None,
    state: str = "idle",
    features: int = 0,
    volume_level: float | None = None,
    content_id: str | None = None,
    content_type: str | None = None,
) -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    if entity_id:
        attrs: dict = {"supported_features": features}
        if volume_level is not None:
            attrs["volume_level"] = volume_level
        if content_id is not None:
            attrs["media_content_id"] = content_id
        if content_type is not None:
            attrs["media_content_type"] = content_type
        state_obj = SimpleNamespace(
            entity_id=entity_id, state=state, attributes=attrs,
        )
        hass.states.get = MagicMock(return_value=state_obj)
    else:
        hass.states.get = MagicMock(return_value=None)
    return hass


def _make_store(category: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.get_category = MagicMock(return_value=category)
    return store


def _make_recipient(
    chime: str | None = None,
    resume: bool = False,
    entity_id: str = "media_player.kitchen",
    volume_override: float | None = None,
) -> dict:
    r = {
        "recipient_id": "kitchen",
        "name": "Kitchen",
        "media_player_entity_id": entity_id,
        "resume_after_tts": resume,
    }
    if chime is not None:
        r["chime_media_content_id"] = chime
    if volume_override is not None:
        r["volume_override"] = volume_override
    return r


# ---------------------------------------------------------------------------
# _is_valid_volume
# ---------------------------------------------------------------------------


class TestIsValidVolume:
    def test_in_range_floats_valid(self):
        assert _is_valid_volume(0.0)
        assert _is_valid_volume(0.5)
        assert _is_valid_volume(1.0)

    def test_in_range_ints_valid(self):
        assert _is_valid_volume(0)
        assert _is_valid_volume(1)

    def test_out_of_range_invalid(self):
        assert not _is_valid_volume(-0.1)
        assert not _is_valid_volume(1.1)
        assert not _is_valid_volume(2.0)

    def test_none_invalid(self):
        assert not _is_valid_volume(None)

    def test_string_invalid(self):
        assert not _is_valid_volume("0.5")

    def test_bool_invalid(self):
        # True == 1 numerically but is not a volume value
        assert not _is_valid_volume(True)
        assert not _is_valid_volume(False)


# ---------------------------------------------------------------------------
# _resolve_volume
# ---------------------------------------------------------------------------


class TestResolveVolume:
    def test_device_only(self):
        rec = {"volume_override": 0.4}
        assert _resolve_volume(rec, None) == 0.4

    def test_category_overrides_device(self):
        rec = {"volume_override": 0.4}
        cat = {"volume_override": 0.8}
        assert _resolve_volume(rec, cat) == 0.8

    def test_neither_returns_none(self):
        assert _resolve_volume({}, {}) is None
        assert _resolve_volume({}, None) is None

    def test_category_invalid_falls_back_to_device(self):
        """An out-of-range or non-numeric category override falls
        through to the recipient's default."""
        rec = {"volume_override": 0.4}
        cat = {"volume_override": 1.5}  # out of range
        assert _resolve_volume(rec, cat) == 0.4

    def test_returns_float_not_int(self):
        rec = {"volume_override": 1}
        result = _resolve_volume(rec, None)
        assert result == 1.0
        assert isinstance(result, float)

    def test_zero_is_returned(self):
        rec = {"volume_override": 0.0}
        assert _resolve_volume(rec, None) == 0.0


# ---------------------------------------------------------------------------
# _snapshot_volume
# ---------------------------------------------------------------------------


class TestSnapshotVolume:
    def test_returns_attribute_when_present(self):
        hass = _make_hass(entity_id="media_player.kitchen", volume_level=0.7)
        assert _snapshot_volume(hass, "media_player.kitchen") == 0.7

    def test_none_when_state_missing(self):
        hass = _make_hass(entity_id=None)
        assert _snapshot_volume(hass, "media_player.kitchen") is None

    def test_none_when_attribute_missing(self):
        hass = _make_hass(entity_id="media_player.kitchen")  # no volume
        assert _snapshot_volume(hass, "media_player.kitchen") is None


# ---------------------------------------------------------------------------
# _set_volume
# ---------------------------------------------------------------------------


class TestSetVolume:
    @pytest.mark.asyncio
    async def test_success_calls_volume_set_and_sleeps(self):
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            ok = await _set_volume(hass, "media_player.kitchen", 0.6)
        assert ok is True
        # service called with volume_set, blocking, payload
        call = hass.services.async_call.call_args
        assert call[0][0] == "media_player"
        assert call[0][1] == "volume_set"
        assert call[0][2] == {
            "entity_id": "media_player.kitchen",
            "volume_level": 0.6,
        }
        # settle delay applied
        mock_sleep.assert_awaited_once_with(VOLUME_SET_SETTLE_DELAY)

    @pytest.mark.asyncio
    async def test_failure_logs_and_returns_false(self, caplog):
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("offline"),
        )
        with caplog.at_level("WARNING"):
            ok = await _set_volume(hass, "media_player.kitchen", 0.6)
        assert ok is False
        assert any(
            "Volume override set failed" in rec.message for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_timeout_swallowed(self, caplog):
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)
        with caplog.at_level("WARNING"):
            ok = await _set_volume(hass, "media_player.kitchen", 0.6)
        assert ok is False


# ---------------------------------------------------------------------------
# async_send_tts integration — volume snapshot/set/restore
# ---------------------------------------------------------------------------


class TestPlainBranchVolume:
    """Plain delivery: snapshot vol, set override, chime+TTS, restore vol."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_set_before_chime_and_restored_after(self, _w, _we):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0,
            volume_level=0.3,  # current device volume
        )
        # Patch the settle-delay sleep to keep the test fast.
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.8,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        # Order: volume_set(0.8), play_media(chime), tts.speak,
        #        volume_set(restore=0.3)
        assert calls[0][0][0] == "media_player"
        assert calls[0][0][1] == "volume_set"
        assert calls[0][0][2]["volume_level"] == 0.8
        assert calls[1][0][0] == "media_player"
        assert calls[1][0][1] == "play_media"
        assert calls[2][0][0] == "tts"
        assert calls[3][0][0] == "media_player"
        assert calls[3][0][1] == "volume_set"
        assert calls[3][0][2]["volume_level"] == 0.3

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_no_volume_override_no_volume_calls(self, _we):
        """Without an override, no volume_set calls are made."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")  # no volume

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        for call in hass.services.async_call.call_args_list:
            # No call should be volume_set
            assert call[0][1] != "volume_set"


class TestRestoreBranchVolume:
    """Restore delivery: snapshot vol with media snapshot, restore both."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_snapshot_with_media_snapshot(self, _w, _we):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
            content_id="http://stream/live",
            content_type="music",
            features=0,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        # Expected order:
        # 1) volume_set(0.9), 2) play_media(chime), 3) tts.speak,
        # 4) play_media(restore stream), 5) volume_set(0.4)
        names = [(c[0][0], c[0][1]) for c in calls]
        assert names[0] == ("media_player", "volume_set")
        assert calls[0][0][2]["volume_level"] == 0.9
        assert names[1] == ("media_player", "play_media")
        assert calls[1][0][2]["media_content_id"] == "media-source://x"
        assert names[2] == ("tts", "speak")
        assert names[3] == ("media_player", "play_media")
        assert calls[3][0][2]["media_content_id"] == "http://stream/live"
        assert names[4] == ("media_player", "volume_set")
        assert calls[4][0][2]["volume_level"] == 0.4


class TestAnnounceBranchVolume:
    """Announce delivery: volume override applied, restored after TTS."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_announce_volume_set_and_restore(self, _w, _we):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
            volume_level=0.5,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.7,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        names = [(c[0][0], c[0][1]) for c in calls]
        # volume_set, play_media (announce), tts.speak, volume_set (restore)
        assert names[0] == ("media_player", "volume_set")
        assert calls[0][0][2]["volume_level"] == 0.7
        assert names[1] == ("media_player", "play_media")
        assert calls[1][0][2]["announce"] is True
        assert names[2] == ("tts", "speak")
        assert names[-1] == ("media_player", "volume_set")
        assert calls[-1][0][2]["volume_level"] == 0.5


class TestVolumeFailSoft:
    """Fail-soft: volume_set failure does not abort chime+TTS."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_set_failure_continues_to_chime_and_tts(
        self, _w, _we, caplog,
    ):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0,
            volume_level=0.3,
        )
        # First call (volume_set) raises, rest succeed
        hass.services.async_call = AsyncMock(
            side_effect=[
                HomeAssistantError("offline"),  # initial volume_set
                None,  # play_media (chime)
                None,  # tts.speak
                None,  # restore volume_set
            ],
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.8,
            )
            with caplog.at_level("WARNING"):
                result = await async_send_tts(
                    hass, store, recipient, "cat1", "Title", "Hello",
                )

        assert any(
            "Volume override set failed" in rec.message
            for rec in caplog.records
        )
        # TTS still delivered
        assert len(result["delivered"]) == 1
        assert result["dropped"] == []


class TestExplicitVolumeKwarg:
    """volume= kwarg overrides resolved value (test-chime path)."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_explicit_volume_wins_over_recipient(self, _w, _we):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0, volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.2,  # ignored
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
                volume=0.95,
            )

        # First service call should be volume_set with 0.95, not 0.2.
        first = hass.services.async_call.call_args_list[0]
        assert first[0][1] == "volume_set"
        assert first[0][2]["volume_level"] == 0.95


class TestCategoryOverridesVolume:
    """End-to-end: category volume_override beats recipient default."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_category_volume_wins(self, _we):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0, volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.ticker.recipient_tts_delivery._wait_for_state",
                new_callable=AsyncMock, return_value=True,
            ):
                store = _make_store(
                    category={"volume_override": 0.9},
                )
                recipient = _make_recipient(
                    chime="media-source://x", volume_override=0.2,
                )
                await async_send_tts(
                    hass, store, recipient, "cat1", "Title", "Hello",
                )

        first = hass.services.async_call.call_args_list[0]
        assert first[0][1] == "volume_set"
        assert first[0][2]["volume_level"] == 0.9
