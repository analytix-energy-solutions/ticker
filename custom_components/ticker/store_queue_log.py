"""Queue and log management mixin for TickerStore."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import (
    DEFAULT_EXPIRATION_HOURS,
    MAX_LOG_ENTRIES,
    LOG_RETENTION_DAYS,
    MAX_QUEUE_RETRIES,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# Debounce configuration for log saves
LOG_SAVE_DEBOUNCE_SECONDS = 30  # Wait 30 seconds after last log before saving
LOG_SAVE_MAX_DELAY_SECONDS = 60  # Force save after 60 seconds regardless


class QueueLogMixin:
    """Mixin providing queue and log functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _queue: dict[str, dict[str, Any]]
    - _queue_store: Store[dict[str, dict[str, Any]]]
    - _logs: list[dict[str, Any]]
    - _logs_store: Store[list[dict[str, Any]]]
    - _logs_dirty: bool
    - _logs_save_unsub: Callable[[], None] | None
    - _logs_first_dirty_time: datetime | None
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _queue: dict[str, dict[str, Any]]
    _queue_store: "Store[dict[str, dict[str, Any]]]"
    _logs: list[dict[str, Any]]
    _logs_store: "Store[list[dict[str, Any]]]"
    _logs_dirty: bool
    _logs_save_unsub: Callable[[], None] | None
    _logs_first_dirty_time: datetime | None

    # =========================================================================
    # Queue methods
    # =========================================================================

    async def async_save_queue(self) -> None:
        """Save queue to storage."""
        await self._queue_store.async_save(self._queue)

    async def _async_cleanup_expired_queue(self) -> None:
        """Remove expired queue entries."""
        now = datetime.now(timezone.utc)
        expired_ids = []

        for queue_id, entry in self._queue.items():
            expires_at = datetime.fromisoformat(entry["expires_at"])
            if now > expires_at:
                expired_ids.append(queue_id)

        if expired_ids:
            for queue_id in expired_ids:
                del self._queue[queue_id]
            await self.async_save_queue()
            _LOGGER.info("Cleaned up %d expired queue entries", len(expired_ids))

    def get_queue(self) -> dict[str, dict[str, Any]]:
        """Get all queued notifications."""
        return self._queue.copy()

    def get_queue_for_person(self, person_id: str) -> list[dict[str, Any]]:
        """Get queued notifications for a specific person."""
        return [
            entry for entry in self._queue.values()
            if entry["person_id"] == person_id
        ]

    def get_queue_count_for_person(self, person_id: str) -> int:
        """Get count of queued notifications for a person."""
        return len(self.get_queue_for_person(person_id))

    async def async_add_to_queue(
        self,
        person_id: str,
        category_id: str,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        expiration_hours: int = DEFAULT_EXPIRATION_HOURS,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """Add a notification to the queue."""
        now = datetime.now(timezone.utc)
        queue_id = str(uuid.uuid4())

        entry = {
            "queue_id": queue_id,
            "person_id": person_id,
            "category_id": category_id,
            "title": title,
            "message": message,
            "data": data or {},
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=expiration_hours)).isoformat(),
            "retry_count": retry_count,
        }

        self._queue[queue_id] = entry
        await self.async_save_queue()

        _LOGGER.debug(
            "Queued notification for %s: %s (expires in %dh, retry %d)",
            person_id,
            title,
            expiration_hours,
            retry_count,
        )
        return entry

    async def async_remove_from_queue(self, queue_id: str) -> bool:
        """Remove a single entry from the queue."""
        if queue_id not in self._queue:
            return False

        del self._queue[queue_id]
        await self.async_save_queue()
        return True

    async def async_clear_queue_for_person(self, person_id: str) -> int:
        """Clear all queued notifications for a person. Returns count removed."""
        to_remove = [
            queue_id for queue_id, entry in self._queue.items()
            if entry["person_id"] == person_id
        ]

        for queue_id in to_remove:
            del self._queue[queue_id]

        if to_remove:
            await self.async_save_queue()
            _LOGGER.info("Cleared %d queued notifications for %s", len(to_remove), person_id)

        return len(to_remove)

    async def async_get_and_clear_queue_for_person(
        self, person_id: str
    ) -> list[dict[str, Any]]:
        """Get and remove all queued notifications for a person."""
        entries = self.get_queue_for_person(person_id)

        if entries:
            for entry in entries:
                del self._queue[entry["queue_id"]]
            await self.async_save_queue()

        return entries

    async def async_requeue_entries(
        self, entries: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Re-queue entries with incremented retry count.

        Entries that exceed MAX_QUEUE_RETRIES are discarded.

        Returns:
            Tuple of (requeued_count, discarded_count)
        """
        requeued = 0
        discarded = 0

        for entry in entries:
            retry_count = entry.get("retry_count", 0) + 1

            if retry_count >= MAX_QUEUE_RETRIES:
                _LOGGER.warning(
                    "Discarding queued notification for %s after %d failed attempts: %s",
                    entry["person_id"],
                    retry_count,
                    entry["title"],
                )
                discarded += 1
                continue

            # Re-queue with incremented retry count, preserving original expiration
            await self.async_add_to_queue(
                person_id=entry["person_id"],
                category_id=entry["category_id"],
                title=entry["title"],
                message=entry["message"],
                data=entry.get("data"),
                expiration_hours=DEFAULT_EXPIRATION_HOURS,  # Reset expiration on retry
                retry_count=retry_count,
            )
            requeued += 1
            _LOGGER.debug(
                "Re-queued notification for %s (retry %d): %s",
                entry["person_id"],
                retry_count,
                entry["title"],
            )

        return requeued, discarded

    # =========================================================================
    # Log methods (with debounced saving)
    # =========================================================================

    async def _async_save_logs_immediate(self) -> None:
        """Save logs to storage immediately."""
        await self._logs_store.async_save(self._logs)
        self._logs_dirty = False
        self._logs_first_dirty_time = None
        _LOGGER.debug("Logs saved to storage")

    def _schedule_logs_save(self) -> None:
        """Schedule a debounced save of logs."""
        now = datetime.now(timezone.utc)

        # Track when logs first became dirty
        if self._logs_first_dirty_time is None:
            self._logs_first_dirty_time = now

        # Check if we've exceeded max delay
        time_since_first_dirty = (now - self._logs_first_dirty_time).total_seconds()
        if time_since_first_dirty >= LOG_SAVE_MAX_DELAY_SECONDS:
            # Force immediate save
            _LOGGER.debug("Max log save delay reached, forcing save")
            self.hass.async_create_task(self._async_save_logs_immediate())
            if self._logs_save_unsub:
                self._logs_save_unsub()
                self._logs_save_unsub = None
            return

        # Cancel existing scheduled save
        if self._logs_save_unsub:
            self._logs_save_unsub()
            self._logs_save_unsub = None

        # Schedule new debounced save
        @callback
        def _async_save_logs_callback(_now) -> None:
            """Callback to save logs after debounce delay."""
            self._logs_save_unsub = None
            self.hass.async_create_task(self._async_save_logs_immediate())

        self._logs_save_unsub = async_call_later(
            self.hass, LOG_SAVE_DEBOUNCE_SECONDS, _async_save_logs_callback
        )

    async def async_save_logs(self) -> None:
        """Save logs to storage (debounced).

        This method schedules a save after a delay to batch multiple writes.
        Use _async_save_logs_immediate() for immediate saves.
        """
        self._logs_dirty = True
        self._schedule_logs_save()

    async def _async_cleanup_old_logs(self) -> None:
        """Remove old log entries based on retention policy."""
        if not self._logs:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
        original_count = len(self._logs)

        self._logs = [
            log for log in self._logs
            if datetime.fromisoformat(log["timestamp"]) > cutoff
        ]

        # Also enforce max entries
        if len(self._logs) > MAX_LOG_ENTRIES:
            self._logs = self._logs[-MAX_LOG_ENTRIES:]

        removed = original_count - len(self._logs)
        if removed > 0:
            await self._async_save_logs_immediate()
            _LOGGER.info("Cleaned up %d old log entries", removed)

    def get_logs(
        self,
        limit: int = 100,
        person_id: str | None = None,
        category_id: str | None = None,
        outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get log entries with optional filters."""
        filtered = self._logs

        if person_id:
            filtered = [l for l in filtered if l.get("person_id") == person_id]

        if category_id:
            filtered = [l for l in filtered if l.get("category_id") == category_id]

        if outcome:
            filtered = [l for l in filtered if l.get("outcome") == outcome]

        # Return newest first, limited
        return list(reversed(filtered[-limit:]))

    def get_log_stats(self) -> dict[str, Any]:
        """Get summary statistics for logs."""
        if not self._logs:
            return {
                "total": 0,
                "by_outcome": {},
                "by_category": {},
            }

        by_outcome: dict[str, int] = {}
        by_category: dict[str, int] = {}

        for log in self._logs:
            outcome = log.get("outcome", "unknown")
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1

            category = log.get("category_id", "unknown")
            by_category[category] = by_category.get(category, 0) + 1

        return {
            "total": len(self._logs),
            "by_outcome": by_outcome,
            "by_category": by_category,
        }

    async def async_add_log(
        self,
        category_id: str,
        person_id: str,
        person_name: str,
        title: str,
        message: str,
        outcome: str,
        notify_service: str | None = None,
        reason: str | None = None,
        notification_id: str | None = None,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        """Add a log entry (with debounced save)."""
        log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        entry = {
            "log_id": log_id,
            "timestamp": now.isoformat(),
            "category_id": category_id,
            "person_id": person_id,
            "person_name": person_name,
            "title": title,
            "message": message,
            "outcome": outcome,
        }

        if notify_service:
            entry["notify_service"] = notify_service

        if reason:
            entry["reason"] = reason

        if notification_id:
            entry["notification_id"] = notification_id

        if image_url:
            entry["image_url"] = image_url

        self._logs.append(entry)

        # Enforce max entries
        if len(self._logs) > MAX_LOG_ENTRIES:
            self._logs = self._logs[-MAX_LOG_ENTRIES:]

        # Schedule debounced save
        await self.async_save_logs()
        return entry

    async def async_clear_logs(self) -> int:
        """Clear all logs. Returns count removed."""
        count = len(self._logs)
        self._logs = []

        # Cancel any pending debounced save
        if self._logs_save_unsub:
            self._logs_save_unsub()
            self._logs_save_unsub = None

        # Save immediately since this is a user action
        await self._async_save_logs_immediate()
        _LOGGER.info("Cleared %d log entries", count)
        return count
