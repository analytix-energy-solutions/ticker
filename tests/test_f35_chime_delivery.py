"""Tests for F-35 — backend chime delivery sequence (recipient_tts.py).

Covers spec §12 cases 1–10:
- _resolve_chime: cases 1–4 (resolution rules)
- async_send_tts delivery branches: cases 5–7 (plain/restore/announce
  ordering, snapshot pre-chime)
- Fail-soft modes: cases 8–10 (HA error, wait timeout, generic exception)
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.ticker.recipient_tts import (
    _resolve_chime,
    _play_chime,
    async_send_tts,
)
from custom_components.ticker.const import (
    CHIME_WAIT_TIMEOUT,
    LOG_OUTCOME_SENT,
    MEDIA_ANNOUNCE_FEATURE,
)


# ---------------------------------------------------------------------------
# Helpers (mirror test_recipient_tts.py shapes for consistency)
# ---------------------------------------------------------------------------

def _make_hass(
    entity_id: str | None = None,
    state: str = "idle",
    features: int = 0,
    content_id: str | None = None,
    content_type: str | None = None,
) -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    if entity_id:
        attrs = {"supported_features": features}
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
) -> dict:
    r = {
        "recipient_id": "kitchen",
        "name": "Kitchen",
        "media_player_entity_id": entity_id,
        "resume_after_tts": resume,
    }
    if chime is not None:
        r["chime_media_content_id"] = chime
    return r


# ---------------------------------------------------------------------------
# §12 Case 1–4: _resolve_chime
# ---------------------------------------------------------------------------

class TestResolveChime:

    def test_device_only_returns_device_default(self):
        """Case 1: recipient has chime, category has none -> recipient's."""
        rec = {"chime_media_content_id": "media-source://device"}
        result = _resolve_chime(rec, None)
        assert result == "media-source://device"

    def test_category_overrides_device(self):
        """Case 2: both set -> category wins."""
        rec = {"chime_media_content_id": "media-source://device"}
        cat = {"chime_media_content_id": "media-source://cat"}
        result = _resolve_chime(rec, cat)
        assert result == "media-source://cat"

    def test_neither_returns_none(self):
        """Case 3: both empty -> None."""
        assert _resolve_chime({}, {}) is None
        assert _resolve_chime({}, None) is None

    def test_empty_string_treated_as_unset(self):
        """Case 4: recipient has '' (legacy quirk) -> None."""
        rec = {"chime_media_content_id": ""}
        assert _resolve_chime(rec, None) is None

    def test_whitespace_only_treated_as_unset(self):
        rec = {"chime_media_content_id": "   "}
        assert _resolve_chime(rec, None) is None

    def test_category_empty_falls_back_to_recipient(self):
        rec = {"chime_media_content_id": "media-source://device"}
        cat = {"chime_media_content_id": ""}
        result = _resolve_chime(rec, cat)
        assert result == "media-source://device"

    def test_strips_whitespace_in_returned_value(self):
        rec = {"chime_media_content_id": "  media-source://x  "}
        assert _resolve_chime(rec, None) == "media-source://x"


# ---------------------------------------------------------------------------
# §12 Case 5–7: delivery sequence — chime before TTS
# ---------------------------------------------------------------------------

class TestPlainPathChimeBeforeTts:
    """Case 5: plain path plays chime exactly once BEFORE TTS."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_chime_called_before_tts(self, _mock_wait):
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        # Two service calls: media_player.play_media (chime), tts.speak
        assert hass.services.async_call.await_count == 2
        first = hass.services.async_call.call_args_list[0]
        second = hass.services.async_call.call_args_list[1]
        assert first[0][0] == "media_player"
        assert first[0][1] == "play_media"
        assert first[0][2]["media_content_id"] == "media-source://x"
        assert first[0][2]["announce"] is False
        assert second[0][0] == "tts"
        assert second[0][1] == "speak"

        assert len(result["delivered"]) == 1
        assert result["dropped"] == []

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_no_chime_when_resolver_returns_none(self, _mock_wait):
        """Without a chime, plain delivery makes a single TTS call."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient()  # no chime

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert hass.services.async_call.await_count == 1
        only = hass.services.async_call.call_args_list[0]
        assert only[0][0] == "tts"


class TestRestorePathSnapshotBeforeChime:
    """Case 6: restore path snapshots BEFORE chime."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_snapshot_taken_before_chime(self, _w, _we):
        """Snapshot's content_id matches pre-chime state."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            content_id="http://stream.example.com/live",
            content_type="music",
            features=0,
        )
        store = _make_store(category=None)
        recipient = _make_recipient(
            chime="media-source://chime", resume=True,
        )

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        # 3 calls: chime play_media, tts.speak, restore play_media
        assert hass.services.async_call.await_count == 3
        chime_call = hass.services.async_call.call_args_list[0]
        tts_call = hass.services.async_call.call_args_list[1]
        restore_call = hass.services.async_call.call_args_list[2]
        # chime first
        assert chime_call[0][0] == "media_player"
        assert chime_call[0][2]["media_content_id"] == "media-source://chime"
        # tts second
        assert tts_call[0][0] == "tts"
        # restore last with the original stream content id
        assert restore_call[0][0] == "media_player"
        assert restore_call[0][1] == "play_media"
        assert (
            restore_call[0][2]["media_content_id"]
            == "http://stream.example.com/live"
        )


class TestAnnouncePathChimeUsesAnnounceTrue:
    """Case 7: announce delivery uses announce=True for the chime."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_chime_announce_true_in_announce_path(self, _mock_wait):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
        )
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        chime_call = hass.services.async_call.call_args_list[0]
        assert chime_call[0][0] == "media_player"
        assert chime_call[0][1] == "play_media"
        assert chime_call[0][2]["announce"] is True


class TestCategoryOverridesDeviceInDelivery:
    """End-to-end: category chime overrides device chime at send time."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_category_chime_wins(self, _mock_wait):
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(
            category={"chime_media_content_id": "media-source://cat"},
        )
        recipient = _make_recipient(chime="media-source://device")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        chime_call = hass.services.async_call.call_args_list[0]
        assert chime_call[0][2]["media_content_id"] == "media-source://cat"


# ---------------------------------------------------------------------------
# §12 Case 8–10: fail-soft modes
# ---------------------------------------------------------------------------

class TestChimeFailSoft:

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_chime_ha_error_tts_still_delivers(
        self, _mock_wait, caplog,
    ):
        """Case 8: play_media raises HAError -> warn, TTS still runs."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        # First call (chime) raises, second call (tts) succeeds
        hass.services.async_call = AsyncMock(
            side_effect=[HomeAssistantError("offline"), None],
        )
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        with caplog.at_level("WARNING"):
            result = await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        # Both calls attempted (chime + TTS)
        assert hass.services.async_call.await_count == 2
        # TTS still logged as sent
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SENT
        assert len(result["delivered"]) == 1
        assert result["dropped"] == []
        assert any(
            "Pre-TTS chime failed" in rec.message for rec in caplog.records
        )

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_chime_gap_fallback_when_content_id_not_observed(
        self, mock_sleep,
    ):
        """Case 9: when the platform never exposes the chime in
        media_content_id (mock hass returns no content_id), the
        ``_wait_for_chime_complete`` helper falls back to a fixed
        delay totalling CHIME_TTS_GAP and TTS still runs.
        """
        from custom_components.ticker.const import CHIME_TTS_GAP
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        # Both chime and TTS attempted
        assert hass.services.async_call.await_count == 2
        # TTS still logged as sent
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SENT
        assert len(result["delivered"]) == 1
        # Total fallback wait approximates CHIME_TTS_GAP (Phase 1
        # detect_window of polls at 0.2s + remainder fallback sleep).
        sleep_durations = [c.args[0] for c in mock_sleep.await_args_list if c.args]
        total_wait = sum(sleep_durations)
        assert total_wait >= CHIME_TTS_GAP - 0.3  # tolerate poll boundary
        assert total_wait <= CHIME_TTS_GAP + 1.0

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_chime_unknown_exception_caught_and_warned(
        self, _mock_wait, caplog,
    ):
        """Case 10: generic Exception during chime -> caught, TTS proceeds."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        hass.services.async_call = AsyncMock(
            side_effect=[RuntimeError("network"), None],
        )
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        with caplog.at_level("WARNING"):
            result = await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        assert hass.services.async_call.await_count == 2
        assert len(result["delivered"]) == 1
        assert result["dropped"] == []

    @pytest.mark.asyncio
    async def test_play_chime_helper_swallows_timeout(self, caplog):
        """Direct test on _play_chime: timeout is logged + swallowed."""
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)

        with caplog.at_level("WARNING"):
            # Should NOT raise
            await _play_chime(
                hass, "media_player.kitchen", "media-source://x",
            )

        assert any(
            "Pre-TTS chime failed" in rec.message for rec in caplog.records
        )

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_play_chime_default_announce_false(self, _mock_wait):
        """Default announce=False on play_media call."""
        hass = _make_hass(entity_id="media_player.kitchen")
        await _play_chime(hass, "media_player.kitchen", "media-source://x")
        call = hass.services.async_call.call_args
        assert call[0][2]["announce"] is False

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_play_chime_announce_true(self, _mock_wait):
        hass = _make_hass(entity_id="media_player.kitchen")
        await _play_chime(
            hass, "media_player.kitchen", "media-source://x", announce=True,
        )
        call = hass.services.async_call.call_args
        assert call[0][2]["announce"] is True


# ---------------------------------------------------------------------------
# §12 Case 14: chime does not appear in History
# ---------------------------------------------------------------------------

class TestChimeNotInHistory:
    """Case 14: only the TTS row is logged; chime produces no History row."""

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_only_tts_logged_no_chime_row(self, _mock_wait):
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        # Exactly one log entry — the TTS delivery.
        assert store.async_add_log.await_count == 1
        kw = store.async_add_log.call_args[1]
        # The notify_service identifies a TTS service, not media_player.
        assert "tts" in (kw.get("notify_service") or "").lower()
        assert "play_media" not in (kw.get("notify_service") or "")

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_chime_failure_still_one_log_row(self, _mock_wait):
        """Chime fail-soft does not produce an additional FAILED row."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        hass.services.async_call = AsyncMock(
            side_effect=[HomeAssistantError("offline"), None],
        )
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        # One row only, marked sent — chime failure is silent in History.
        assert store.async_add_log.await_count == 1
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SENT


# ---------------------------------------------------------------------------
# §12 Case 15: volume_override applies to TTS only — no volume key on chime
# ---------------------------------------------------------------------------

class TestChimeNoVolumePayload:
    """Case 15: chime play_media call carries no volume / volume_level key.

    Spec §7.5 (locked decision §4 #5): there is no chime_volume. The chime
    inherits the device's current volume; explicitly forbids passing a
    volume on the play_media call.
    """

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_plain_chime_payload_has_no_volume(self, _mock_wait):
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        chime_payload = hass.services.async_call.call_args_list[0][0][2]
        assert "volume" not in chime_payload
        assert "volume_level" not in chime_payload
        # Sanity: the keys that SHOULD be present
        assert chime_payload["entity_id"] == "media_player.kitchen"
        assert chime_payload["media_content_id"] == "media-source://x"
        assert chime_payload["media_content_type"] == "music"

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_announce_chime_payload_has_no_volume(self, _mock_wait):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
        )
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        chime_payload = hass.services.async_call.call_args_list[0][0][2]
        assert "volume" not in chime_payload
        assert "volume_level" not in chime_payload

    @pytest.mark.asyncio
    async def test_play_chime_helper_payload_has_no_volume(self):
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ):
            await _play_chime(
                hass, "media_player.kitchen", "media-source://x",
            )
        payload = hass.services.async_call.call_args[0][2]
        # Keys allowed on the chime call, per §7.1
        assert set(payload.keys()) == {
            "entity_id", "media_content_id", "media_content_type", "announce",
        }


# ---------------------------------------------------------------------------
# §12 Case 16: queue serialisation across back-to-back notifies
# ---------------------------------------------------------------------------

class TestChimeQueueSerialisation:
    """Case 16: two back-to-back notifies serialise — chime invoked twice,
    second TTS waits for first chime+TTS to complete.

    Per spec §5.4, no extra primitive — async_send_tts already serialises
    chime then TTS as one awaited unit per call. We assert that property:
    sequential awaits run chime->tts->chime->tts in order.
    """

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
        new_callable=AsyncMock, return_value=True,
    )
    async def test_back_to_back_notifies_invoke_chime_each_time(
        self, _mock_wait,
    ):
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store(category=None)
        recipient = _make_recipient(chime="media-source://x")

        # Fire two notifies sequentially — same recipient.
        await async_send_tts(hass, store, recipient, "cat1", "T1", "M1")
        await async_send_tts(hass, store, recipient, "cat1", "T2", "M2")

        # Each notify invokes 1 chime + 1 tts, so 4 service calls in order.
        calls = hass.services.async_call.call_args_list
        assert len(calls) == 4
        # Order: chime, tts, chime, tts
        assert calls[0][0][0] == "media_player"
        assert calls[0][0][1] == "play_media"
        assert calls[1][0][0] == "tts"
        assert calls[2][0][0] == "media_player"
        assert calls[2][0][1] == "play_media"
        assert calls[3][0][0] == "tts"
        # Two log rows (one per notify), both Sent
        assert store.async_add_log.await_count == 2
        outcomes = [
            call.kwargs["outcome"]
            for call in store.async_add_log.await_args_list
        ]
        assert outcomes == [LOG_OUTCOME_SENT, LOG_OUTCOME_SENT]
