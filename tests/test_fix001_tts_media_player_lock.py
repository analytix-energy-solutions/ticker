"""FIX-001 (v1.8.2) — per-media_player TTS delivery lock.

PRs #49/#50 fan recipients out concurrently. TTS delivery mutates shared
media_player state (volume snapshot -> set -> chime -> speak -> restore), so
two recipients targeting the SAME media_player must be serialized while
recipients on DIFFERENT players stay concurrent.

These tests exercise ``recipient_tts._get_media_player_lock`` (identity /
per-entity semantics) and the ``async with _get_media_player_lock(entity_id)``
wrapper inside ``async_send_tts`` (serialization vs. concurrency). The delivery
helper is monkeypatched with a fake that tracks how many deliveries are active
at once, so the assertions are timing-robust rather than sleep-order fragile.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.ticker.recipient_tts as tts_mod
from custom_components.ticker.recipient_tts import (
    _get_media_player_lock,
    async_send_tts,
)


# ---------------------------------------------------------------------------
# Helpers (mirrors test_recipient_tts.py)
# ---------------------------------------------------------------------------

def _make_hass(entity_id: str, features: int = 0) -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    state_obj = SimpleNamespace(
        entity_id=entity_id,
        state="idle",
        attributes={"supported_features": features},
    )
    hass.states.get = MagicMock(return_value=state_obj)
    return hass


def _make_store() -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.get_category.return_value = None
    return store


def _make_recipient(
    recipient_id: str,
    entity_id: str,
    resume: bool = False,
) -> dict:
    return {
        "recipient_id": recipient_id,
        "name": recipient_id,
        "media_player_entity_id": entity_id,
        "resume_after_tts": resume,
        "tts_buffer_delay": 0.0,
    }


@pytest.fixture(autouse=True)
def _clear_locks():
    """Isolate the module-level lock registry between tests.

    ``_MEDIA_PLAYER_LOCKS`` is process-global and its ``asyncio.Lock``
    objects bind to the event loop that first uses them. Clearing before
    (and after) each test prevents a lock created in one test's loop from
    leaking into another's.
    """
    tts_mod._MEDIA_PLAYER_LOCKS.clear()
    yield
    tts_mod._MEDIA_PLAYER_LOCKS.clear()


class _ConcurrencyProbe:
    """Async delivery stand-in that records peak concurrent deliveries."""

    def __init__(self, hold: float = 0.05):
        self.active = 0
        self.max_active = 0
        self.events: list[str] = []
        self._hold = hold

    async def __call__(self, hass, entity_id, tts_service, payload,
                        *, chime_id=None, volume_level=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.events.append(f"start:{entity_id}")
        await asyncio.sleep(self._hold)
        self.events.append(f"end:{entity_id}")
        self.active -= 1
        return "plain"


# ---------------------------------------------------------------------------
# _get_media_player_lock — helper identity / per-entity semantics
# ---------------------------------------------------------------------------

class TestGetMediaPlayerLock:
    """Tests for the lazy per-entity lock factory."""

    def test_same_entity_returns_same_lock(self):
        lock_a = _get_media_player_lock("media_player.kitchen")
        lock_b = _get_media_player_lock("media_player.kitchen")
        assert lock_a is lock_b

    def test_different_entities_get_different_locks(self):
        lock_kitchen = _get_media_player_lock("media_player.kitchen")
        lock_office = _get_media_player_lock("media_player.office")
        assert lock_kitchen is not lock_office

    def test_returns_asyncio_lock(self):
        lock = _get_media_player_lock("media_player.kitchen")
        assert isinstance(lock, asyncio.Lock)

    def test_lock_registered_in_module_registry(self):
        _get_media_player_lock("media_player.kitchen")
        assert "media_player.kitchen" in tts_mod._MEDIA_PLAYER_LOCKS


# ---------------------------------------------------------------------------
# async_send_tts — serialization vs. concurrency
# ---------------------------------------------------------------------------

class TestTtsDeliveryLock:
    """Tests for the ``async with _get_media_player_lock`` wrapper."""

    @pytest.mark.asyncio
    async def test_same_entity_deliveries_serialized(self):
        """Two recipients on the SAME player never overlap in delivery."""
        probe = _ConcurrencyProbe()
        entity = "media_player.kitchen"
        hass = _make_hass(entity)
        store = _make_store()
        rec_a = _make_recipient("spk_a", entity)
        rec_b = _make_recipient("spk_b", entity)

        with patch.object(tts_mod, "_deliver_tts_plain", probe):
            await asyncio.gather(
                async_send_tts(hass, store, rec_a, "cat1", "T", "A"),
                async_send_tts(hass, store, rec_b, "cat1", "T", "B"),
            )

        # Lock serialized delivery: only ever one active at a time.
        assert probe.max_active == 1
        # Event stream is fully nested per call: start,end,start,end — never
        # start,start (which would prove interleaving).
        assert probe.events == [
            f"start:{entity}", f"end:{entity}",
            f"start:{entity}", f"end:{entity}",
        ]

    @pytest.mark.asyncio
    async def test_different_entities_deliveries_concurrent(self):
        """Recipients on DIFFERENT players deliver concurrently (per-entity)."""
        probe = _ConcurrencyProbe()
        hass_a = _make_hass("media_player.kitchen")
        hass_b = _make_hass("media_player.office")
        store = _make_store()
        rec_a = _make_recipient("spk_a", "media_player.kitchen")
        rec_b = _make_recipient("spk_b", "media_player.office")

        with patch.object(tts_mod, "_deliver_tts_plain", probe):
            await asyncio.gather(
                async_send_tts(hass_a, store, rec_a, "cat1", "T", "A"),
                async_send_tts(hass_b, store, rec_b, "cat1", "T", "B"),
            )

        # Per-entity locks do NOT serialize distinct players: both were in
        # their delivery window at the same time.
        assert probe.max_active == 2
        # Both starts precede either end (overlap).
        assert probe.events[0].startswith("start:")
        assert probe.events[1].startswith("start:")

    @pytest.mark.asyncio
    async def test_restore_path_also_serialized(self):
        """The lock wraps the whole dispatch, incl. the restore mode."""
        probe = _ConcurrencyProbe()
        entity = "media_player.kitchen"
        hass = _make_hass(entity)
        store = _make_store()
        rec_a = _make_recipient("spk_a", entity, resume=True)
        rec_b = _make_recipient("spk_b", entity, resume=True)

        with patch.object(tts_mod, "_deliver_tts_with_restore", probe):
            await asyncio.gather(
                async_send_tts(hass, store, rec_a, "cat1", "T", "A"),
                async_send_tts(hass, store, rec_b, "cat1", "T", "B"),
            )

        assert probe.max_active == 1

    @pytest.mark.asyncio
    async def test_lock_released_after_delivery(self):
        """After a delivery completes the lock is free for the next call."""
        probe = _ConcurrencyProbe(hold=0.0)
        entity = "media_player.kitchen"
        hass = _make_hass(entity)
        store = _make_store()
        rec = _make_recipient("spk_a", entity)

        with patch.object(tts_mod, "_deliver_tts_plain", probe):
            await async_send_tts(hass, store, rec, "cat1", "T", "A")
            # Lock must not be held after the first call returns.
            assert not _get_media_player_lock(entity).locked()
            # A second call still succeeds (would deadlock if held).
            result = await async_send_tts(hass, store, rec, "cat1", "T", "B")

        assert len(result["delivered"]) == 1
        assert probe.max_active == 1
