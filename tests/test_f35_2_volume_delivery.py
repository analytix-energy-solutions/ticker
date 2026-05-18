"""Tests for F-35.2 Volume Override — backend delivery (chunk 2).

Covers:
- _resolve_volume: recipient default, category override, none, in/out of range.
- _is_valid_volume edge cases.
- _set_volume: success path, fail-soft, settle delay.
- async_send_tts plain/restore/announce branches: snapshot before chime,
  override applied, restored after TTS exits playing.
- Caller-supplied volume= kwarg overrides resolved value (test-chime path).
- BUG-109 iteration 2: ``_is_cast_target`` helper unit coverage
  (TestCastDetection).

All non-cast integration tests default ``_is_cast_target`` to ``False``
so they exercise the simpler pre-set pattern (single ``volume_set`` per
side, no jiggle). Cast-branch coverage lives in
``test_f35_2_volume_delivery_jiggle.py``.
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
from custom_components.ticker.recipient_tts_delivery import (
    _is_cast_target,
    _is_valid_volume,
)
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
# BUG-109 iteration 2: _is_cast_target detection helper
# ---------------------------------------------------------------------------


class TestCastDetection:
    """Coverage for ``_is_cast_target``.

    BUG-109 iteration 2: cast scoping. The helper detects cast targets
    via the entity registry ``platform`` field. Cast targets get the
    deferred-apply jiggle pipeline; non-cast targets get the simpler
    pre-BUG-109 single-set flow.
    """

    @pytest.mark.asyncio
    async def test_cast_platform_returns_true(self):
        hass = MagicMock()
        entry = SimpleNamespace(platform="cast")
        registry = MagicMock()
        registry.async_get = MagicMock(return_value=entry)
        with patch(
            "custom_components.ticker.recipient_tts_chime.er.async_get",
            return_value=registry,
        ):
            assert (
                await _is_cast_target(hass, "media_player.kitchen")
            ) is True

    @pytest.mark.asyncio
    async def test_non_cast_platform_returns_false(self):
        hass = MagicMock()
        entry = SimpleNamespace(platform="sonos")
        registry = MagicMock()
        registry.async_get = MagicMock(return_value=entry)
        with patch(
            "custom_components.ticker.recipient_tts_chime.er.async_get",
            return_value=registry,
        ):
            assert (
                await _is_cast_target(hass, "media_player.living_room")
            ) is False

    @pytest.mark.asyncio
    async def test_missing_entry_returns_false(self):
        hass = MagicMock()
        registry = MagicMock()
        registry.async_get = MagicMock(return_value=None)
        with patch(
            "custom_components.ticker.recipient_tts_chime.er.async_get",
            return_value=registry,
        ):
            assert (
                await _is_cast_target(hass, "media_player.unknown")
            ) is False

    @pytest.mark.asyncio
    async def test_registry_exception_returns_false(self):
        """Any registry-lookup failure (mock states, hass not ready)
        defaults to non-cast so the simpler path is used."""
        hass = MagicMock()
        with patch(
            "custom_components.ticker.recipient_tts_chime.er.async_get",
            side_effect=RuntimeError("hass not ready"),
        ):
            assert (
                await _is_cast_target(hass, "media_player.kitchen")
            ) is False


# ---------------------------------------------------------------------------
# async_send_tts integration — non-cast simple flow
# ---------------------------------------------------------------------------


class TestPlainBranchVolume:
    """Plain delivery (non-cast): snapshot vol, single set override,
    chime+TTS, single set restore. BUG-109 iteration 2 reverts non-cast
    targets to the pre-BUG-109 simple flow."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_set_before_chime_and_restored_after(
        self, _w, _we, _cast,
    ):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0,
            volume_level=0.3,  # current device volume
        )
        # Patch the settle-delay sleep to keep the test fast. Also patch
        # _is_cast_target inside the chime module since _play_chime
        # makes its own cast-check.
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=False,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.8,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        # BUG-109 iteration 2 — non-cast simple flow:
        # 0) volume_set(0.8)             ← single set, no jiggle
        # 1) play_media(chime)
        # 2) tts.speak
        # 3) volume_set(0.3)             ← single restore, no jiggle
        assert calls[0][0][1] == "volume_set"
        assert calls[0][0][2]["volume_level"] == 0.8
        assert calls[1][0][1] == "play_media"
        assert calls[2][0][0] == "tts"
        assert calls[3][0][1] == "volume_set"
        assert calls[3][0][2]["volume_level"] == 0.3
        # Only 2 volume_set calls total (no jiggle on non-cast)
        vol_set_count = sum(1 for c in calls if c[0][1] == "volume_set")
        assert vol_set_count == 2

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_no_volume_override_no_volume_calls(self, _we, _cast):
        """Without an override, no volume_set calls are made."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")  # no volume

        with patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=False,
        ):
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        for call in hass.services.async_call.call_args_list:
            # No call should be volume_set
            assert call[0][1] != "volume_set"


class TestRestoreBranchVolume:
    """Restore delivery (non-cast): snapshot vol with media snapshot,
    single set override, single set restore."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_snapshot_with_media_snapshot(
        self, _w, _we, _cast,
    ):
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
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=False,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        # BUG-109 iteration 2 — non-cast simple flow:
        # 0) volume_set(0.9)               ← single set override
        # 1) play_media(chime)
        # 2) tts.speak
        # 3) play_media(restore stream)
        # 4) volume_set(0.4)               ← single restore
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
        # Only 2 volume_set calls (no jiggle on non-cast)
        vol_set_count = sum(1 for c in calls if c[0][1] == "volume_set")
        assert vol_set_count == 2


class TestAnnounceBranchVolume:
    """Announce delivery: volume override applied, restored after TTS.

    BUG-109 iteration 2: Cast devices don't expose MEDIA_ANNOUNCE, so
    the announce branch reverts to the pre-BUG-109 simple flow (single
    set, no jiggle, no extra waits).
    """

    @pytest.mark.asyncio
    async def test_announce_volume_set_and_restore(self):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
            volume_level=0.5,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=False,
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
        # BUG-109 iteration 2 — announce simple flow:
        # 0) volume_set(0.7)             ← single set override
        # 1) play_media (announce)
        # 2) tts.speak
        # 3) volume_set(0.5)             ← single restore
        assert names[0] == ("media_player", "volume_set")
        assert calls[0][0][2]["volume_level"] == 0.7
        assert names[1] == ("media_player", "play_media")
        assert calls[1][0][2]["announce"] is True
        assert names[2] == ("tts", "speak")
        assert names[-1] == ("media_player", "volume_set")
        assert calls[-1][0][2]["volume_level"] == 0.5
        # Only 2 volume_set calls — announce branch is simple flow.
        vol_set_count = sum(1 for c in calls if c[0][1] == "volume_set")
        assert vol_set_count == 2


class TestVolumeFailSoft:
    """Fail-soft: volume_set failure does not abort chime+TTS."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._is_cast_target",
        new_callable=AsyncMock, return_value=False,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_volume_set_failure_continues_to_chime_and_tts(
        self, _w, _we, _cast, caplog,
    ):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0,
            volume_level=0.3,
        )
        # BUG-109 iteration 2 — non-cast simple flow:
        # 1) volume_set (override) RAISES
        # 2) play_media (chime) OK
        # 3) tts.speak OK
        # 4) volume_set (restore) OK
        hass.services.async_call = AsyncMock(
            side_effect=[
                HomeAssistantError("offline"),  # override (fail)
                None,  # play_media (chime)
                None,  # tts.speak
                None,  # restore
            ],
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=False,
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


# NOTE: TestExplicitVolumeKwarg and TestCategoryOverridesVolume live in
# ``test_f35_2_volume_delivery_jiggle.py`` (cast-branch coverage).
