"""Tests for BUG-089: async_requeue_entries must preserve remaining lifetime.

Previously, requeue always used DEFAULT_EXPIRATION_HOURS (48h), giving
persistently-failing notifications a fresh window on every retry. The
fix computes the remaining seconds from ``expires_at`` and passes that
as the new expiration. Already-expired entries are skipped entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store_queue_log import QueueLogMixin


def _make_mixin() -> QueueLogMixin:
    """Build a QueueLogMixin with just enough state to exercise requeue."""
    mixin = QueueLogMixin()
    mixin.hass = MagicMock()
    mixin._queue = {}
    mixin._queue_store = MagicMock()
    mixin._queue_store.async_save = AsyncMock()
    return mixin


def _entry(
    *,
    expires_at: datetime | None,
    retry_count: int = 0,
    person_id: str = "person.alice",
    title: str = "T",
) -> dict:
    return {
        "queue_id": "old",
        "person_id": person_id,
        "category_id": "cat1",
        "title": title,
        "message": "m",
        "data": {},
        "retry_count": retry_count,
        "notification_id": "nid1",
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


class TestBug089RequeuePreservesLifetime:

    @pytest.mark.asyncio
    async def test_requeue_uses_remaining_lifetime_not_default(self):
        """An entry with 1h remaining must be requeued with ~1h, not 48h."""
        mixin = _make_mixin()
        now = datetime.now(timezone.utc)
        entry = _entry(expires_at=now + timedelta(hours=1))

        requeued, discarded = await mixin.async_requeue_entries([entry])

        assert requeued == 1
        assert discarded == 0

        # One new entry added under a fresh queue_id
        assert len(mixin._queue) == 1
        new_entry = next(iter(mixin._queue.values()))
        new_expires = datetime.fromisoformat(new_entry["expires_at"])
        new_created = datetime.fromisoformat(new_entry["created_at"])
        remaining = (new_expires - new_created).total_seconds() / 3600.0

        # Should be ~1 hour, certainly not 48 hours
        assert 0.9 <= remaining <= 1.1, (
            f"Expected ~1h remaining, got {remaining:.2f}h — regression to "
            f"DEFAULT_EXPIRATION_HOURS (48h) would fail here"
        )
        assert new_entry["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_requeue_skips_already_expired_entry(self):
        """An already-expired entry must be discarded, not re-queued."""
        mixin = _make_mixin()
        now = datetime.now(timezone.utc)
        entry = _entry(expires_at=now - timedelta(minutes=5))

        requeued, discarded = await mixin.async_requeue_entries([entry])

        assert requeued == 0
        assert discarded == 1
        assert len(mixin._queue) == 0

    @pytest.mark.asyncio
    async def test_requeue_discards_after_max_retries(self):
        """Entries exceeding MAX_QUEUE_RETRIES are discarded regardless."""
        mixin = _make_mixin()
        now = datetime.now(timezone.utc)
        # MAX_QUEUE_RETRIES = 3; retry_count 2 -> becomes 3 -> discard
        entry = _entry(expires_at=now + timedelta(hours=1), retry_count=2)

        requeued, discarded = await mixin.async_requeue_entries([entry])

        assert requeued == 0
        assert discarded == 1

    @pytest.mark.asyncio
    async def test_requeue_missing_expires_at_falls_back_to_default(self):
        """Legacy entries without expires_at fall back to 48h default."""
        mixin = _make_mixin()
        entry = _entry(expires_at=None)

        requeued, discarded = await mixin.async_requeue_entries([entry])

        assert requeued == 1
        assert discarded == 0
        new_entry = next(iter(mixin._queue.values()))
        new_expires = datetime.fromisoformat(new_entry["expires_at"])
        new_created = datetime.fromisoformat(new_entry["created_at"])
        remaining = (new_expires - new_created).total_seconds() / 3600.0
        # Fallback is DEFAULT_EXPIRATION_HOURS (48)
        assert 47.5 <= remaining <= 48.5
