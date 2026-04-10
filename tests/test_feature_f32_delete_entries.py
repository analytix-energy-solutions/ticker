"""Tests for F-32: Delete / clear log entry store methods.

Covers the new store_log.py helpers that back the user-facing delete
and clear-all actions:

- async_remove_log_entry(log_id): remove a single entry by log_id
- async_remove_log_group(notification_id, person_id): remove every row
  belonging to one logical notification (a single dispatch can log
  multiple rows, one per device)
- async_clear_logs_for_person(person_id): wipe a person's history

Each method saves immediately (bypassing the debounce) and returns the
number of entries removed (or a bool for single-entry deletion).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store_log import LogMixin


def _make_store() -> LogMixin:
    mixin = LogMixin()
    mixin.hass = MagicMock()
    mixin._logs = []
    mixin._logs_store = MagicMock()
    mixin._logs_store.async_save = AsyncMock()
    mixin._logs_dirty = False
    mixin._logs_save_unsub = None
    mixin._logs_first_dirty_time = None
    return mixin


def _seed(mixin: LogMixin, entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        entry.setdefault("timestamp", now)
        entry.setdefault("outcome", "sent")
    mixin._logs.extend(entries)


# ---------------------------------------------------------------------------
# async_remove_log_entry
# ---------------------------------------------------------------------------

class TestRemoveLogEntry:
    @pytest.mark.asyncio
    async def test_removes_matching_entry(self):
        store = _make_store()
        _seed(store, [
            {"log_id": "a", "person_id": "person.alice"},
            {"log_id": "b", "person_id": "person.alice"},
        ])

        ok = await store.async_remove_log_entry("a")

        assert ok is True
        assert [e["log_id"] for e in store._logs] == ["b"]
        store._logs_store.async_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        store = _make_store()
        _seed(store, [{"log_id": "a"}])

        ok = await store.async_remove_log_entry("missing")

        assert ok is False
        assert len(store._logs) == 1
        store._logs_store.async_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_for_empty_log_id(self):
        store = _make_store()
        _seed(store, [{"log_id": "a"}])

        ok = await store.async_remove_log_entry("")

        assert ok is False
        assert len(store._logs) == 1


# ---------------------------------------------------------------------------
# async_remove_log_group
# ---------------------------------------------------------------------------

class TestRemoveLogGroup:
    @pytest.mark.asyncio
    async def test_removes_all_rows_for_notification_and_person(self):
        """A single notification may span multiple device rows."""
        store = _make_store()
        _seed(store, [
            {"log_id": "a", "notification_id": "nid1", "person_id": "person.alice"},
            {"log_id": "b", "notification_id": "nid1", "person_id": "person.alice"},
            {"log_id": "c", "notification_id": "nid1", "person_id": "person.bob"},
            {"log_id": "d", "notification_id": "nid2", "person_id": "person.alice"},
        ])

        removed = await store.async_remove_log_group("nid1", "person.alice")

        assert removed == 2
        remaining = {e["log_id"] for e in store._logs}
        assert remaining == {"c", "d"}
        store._logs_store.async_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_match(self):
        store = _make_store()
        _seed(store, [
            {"log_id": "a", "notification_id": "nid1", "person_id": "person.alice"},
        ])

        removed = await store.async_remove_log_group("nid_ghost", "person.alice")

        assert removed == 0
        assert len(store._logs) == 1

    @pytest.mark.asyncio
    async def test_returns_zero_for_blank_inputs(self):
        store = _make_store()
        _seed(store, [
            {"log_id": "a", "notification_id": "nid1", "person_id": "person.alice"},
        ])

        assert await store.async_remove_log_group("", "person.alice") == 0
        assert await store.async_remove_log_group("nid1", "") == 0
        assert len(store._logs) == 1


# ---------------------------------------------------------------------------
# async_clear_logs_for_person
# ---------------------------------------------------------------------------

class TestClearLogsForPerson:
    @pytest.mark.asyncio
    async def test_removes_all_entries_for_person(self):
        store = _make_store()
        _seed(store, [
            {"log_id": "a", "person_id": "person.alice"},
            {"log_id": "b", "person_id": "person.alice"},
            {"log_id": "c", "person_id": "person.bob"},
        ])

        removed = await store.async_clear_logs_for_person("person.alice")

        assert removed == 2
        assert [e["log_id"] for e in store._logs] == ["c"]
        store._logs_store.async_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_person_has_no_logs(self):
        store = _make_store()
        _seed(store, [{"log_id": "a", "person_id": "person.alice"}])

        removed = await store.async_clear_logs_for_person("person.ghost")

        assert removed == 0
        assert len(store._logs) == 1

    @pytest.mark.asyncio
    async def test_returns_zero_for_blank_person_id(self):
        store = _make_store()
        _seed(store, [{"log_id": "a", "person_id": "person.alice"}])

        removed = await store.async_clear_logs_for_person("")

        assert removed == 0
        assert len(store._logs) == 1

    @pytest.mark.asyncio
    async def test_cancels_pending_debounced_save(self):
        """If a debounced save was scheduled, it must be cancelled first."""
        store = _make_store()
        _seed(store, [{"log_id": "a", "person_id": "person.alice"}])
        fake_unsub = MagicMock()
        store._logs_save_unsub = fake_unsub

        await store.async_clear_logs_for_person("person.alice")

        fake_unsub.assert_called_once()
        assert store._logs_save_unsub is None
