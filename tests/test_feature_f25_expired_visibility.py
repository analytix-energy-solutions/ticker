"""Tests for F-25: Expired notification visibility.

When the queue cleanup job deletes an expired notification, it must first
write a log entry with outcome "expired" so operators and end-users can
see that a queued notification was never delivered. The log row must
carry the notification_id, person_id, category_id, and image_url from
the original queue entry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.const import LOG_OUTCOME_EXPIRED
from custom_components.ticker.store_queue import QueueMixin


def _make_mixin() -> QueueMixin:
    """Build a QueueMixin with just enough state for cleanup tests."""
    mixin = QueueMixin()
    mixin.hass = MagicMock()
    mixin._queue = {}
    mixin._queue_store = MagicMock()
    mixin._queue_store.async_save = AsyncMock()
    # F-25 calls get_user() and async_add_log() on the same store instance.
    mixin.get_user = MagicMock(return_value={"name": "Alice"})
    mixin.async_add_log = AsyncMock()
    return mixin


def _expired_entry(
    *,
    queue_id: str = "q-expired",
    notification_id: str = "nid-123",
    person_id: str = "person.alice",
    category_id: str = "cat_alerts",
    title: str = "Door left open",
    message: str = "Front door has been open for 5 min",
    image_url: str | None = "https://example.com/door.jpg",
) -> dict:
    """Build a queue entry whose expires_at is 1h in the past."""
    now = datetime.now(timezone.utc)
    return {
        "queue_id": queue_id,
        "person_id": person_id,
        "category_id": category_id,
        "title": title,
        "message": message,
        "data": {"image": image_url} if image_url else {},
        "created_at": (now - timedelta(hours=2)).isoformat(),
        "expires_at": (now - timedelta(hours=1)).isoformat(),
        "retry_count": 0,
        "notification_id": notification_id,
    }


class TestF25ExpiredVisibility:
    @pytest.mark.asyncio
    async def test_expired_entry_writes_log_with_expired_outcome(self):
        """Cleanup must write a log row with outcome=='expired'."""
        mixin = _make_mixin()
        entry = _expired_entry()
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        mixin.async_add_log.assert_awaited_once()
        kwargs = mixin.async_add_log.call_args.kwargs
        assert kwargs["outcome"] == LOG_OUTCOME_EXPIRED

    @pytest.mark.asyncio
    async def test_expired_log_preserves_notification_metadata(self):
        """Log row must carry notification_id / person_id / category_id / image."""
        mixin = _make_mixin()
        entry = _expired_entry(
            notification_id="nid-xyz",
            person_id="person.bob",
            category_id="cat_security",
            image_url="https://example.com/cam.jpg",
        )
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        kwargs = mixin.async_add_log.call_args.kwargs
        assert kwargs["notification_id"] == "nid-xyz"
        assert kwargs["person_id"] == "person.bob"
        assert kwargs["category_id"] == "cat_security"
        assert kwargs["image_url"] == "https://example.com/cam.jpg"
        assert kwargs["title"] == "Door left open"
        assert kwargs["message"] == "Front door has been open for 5 min"

    @pytest.mark.asyncio
    async def test_expired_entry_is_removed_from_queue(self):
        """After cleanup the queue entry must be gone."""
        mixin = _make_mixin()
        entry = _expired_entry()
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        assert entry["queue_id"] not in mixin._queue
        mixin._queue_store.async_save.assert_awaited()

    @pytest.mark.asyncio
    async def test_not_yet_expired_entry_is_left_alone(self):
        """Entries with a future expires_at are untouched."""
        mixin = _make_mixin()
        now = datetime.now(timezone.utc)
        entry = _expired_entry()
        entry["expires_at"] = (now + timedelta(hours=1)).isoformat()
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        assert entry["queue_id"] in mixin._queue
        mixin.async_add_log.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expired_log_uses_person_name_from_user_lookup(self):
        """The log row should prefer the user's name over the raw person_id."""
        mixin = _make_mixin()
        mixin.get_user = MagicMock(return_value={"name": "Alice Smith"})
        entry = _expired_entry(person_id="person.alice")
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        kwargs = mixin.async_add_log.call_args.kwargs
        assert kwargs["person_name"] == "Alice Smith"

    @pytest.mark.asyncio
    async def test_expired_log_falls_back_to_person_id_if_no_user(self):
        """When get_user returns None we fall back to person_id as the name."""
        mixin = _make_mixin()
        mixin.get_user = MagicMock(return_value=None)
        entry = _expired_entry(person_id="person.ghost")
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        kwargs = mixin.async_add_log.call_args.kwargs
        assert kwargs["person_name"] == "person.ghost"

    @pytest.mark.asyncio
    async def test_log_failure_does_not_block_queue_deletion(self):
        """If logging raises, the queue entry is still removed."""
        mixin = _make_mixin()
        mixin.async_add_log = AsyncMock(side_effect=RuntimeError("boom"))
        entry = _expired_entry()
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        assert entry["queue_id"] not in mixin._queue

    @pytest.mark.asyncio
    async def test_expired_log_reason_mentions_expiration(self):
        """The log reason should explain why the notification is in the log."""
        mixin = _make_mixin()
        entry = _expired_entry()
        mixin._queue[entry["queue_id"]] = entry

        await mixin._async_cleanup_expired_queue()

        kwargs = mixin.async_add_log.call_args.kwargs
        assert "expire" in kwargs["reason"].lower()
