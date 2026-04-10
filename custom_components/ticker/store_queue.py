"""Queue management mixin for TickerStore."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

from .const import (
    DEFAULT_EXPIRATION_HOURS,
    MAX_QUEUE_RETRIES,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class QueueMixin:
    """Mixin providing queue functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _queue: dict[str, dict[str, Any]]
    - _queue_store: Store[dict[str, dict[str, Any]]]
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _queue: dict[str, dict[str, Any]]
    _queue_store: "Store[dict[str, dict[str, Any]]]"

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
        expiration_hours: float = DEFAULT_EXPIRATION_HOURS,
        retry_count: int = 0,
        notification_id: str | None = None,
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
            "notification_id": notification_id,
        }

        self._queue[queue_id] = entry
        await self.async_save_queue()

        _LOGGER.debug(
            "Queued notification for %s: %s (expires in %.2fh, retry %d)",
            person_id,
            title,
            float(expiration_hours),
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
        now = datetime.now(timezone.utc)

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

            # Compute remaining hours from the original expires_at so that
            # persistently-failing notifications do not get a fresh 48h window
            # on every retry (BUG-089).
            expires_at_raw = entry.get("expires_at")
            if expires_at_raw is None:
                _LOGGER.warning(
                    "Queue entry for %s missing expires_at; falling back to "
                    "DEFAULT_EXPIRATION_HOURS: %s",
                    entry["person_id"],
                    entry.get("title"),
                )
                remaining_hours: float = float(DEFAULT_EXPIRATION_HOURS)
            else:
                try:
                    expires_at = datetime.fromisoformat(expires_at_raw)
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "Queue entry for %s has invalid expires_at %r; falling "
                        "back to DEFAULT_EXPIRATION_HOURS: %s",
                        entry["person_id"],
                        expires_at_raw,
                        entry.get("title"),
                    )
                    remaining_hours = float(DEFAULT_EXPIRATION_HOURS)
                else:
                    remaining_seconds = (expires_at - now).total_seconds()
                    if remaining_seconds <= 0:
                        _LOGGER.debug(
                            "Skipping re-queue for %s: entry already past "
                            "expires_at (%s): %s",
                            entry["person_id"],
                            expires_at_raw,
                            entry["title"],
                        )
                        discarded += 1
                        continue
                    remaining_hours = remaining_seconds / 3600.0

            # Re-queue with incremented retry count and the remaining lifetime
            # of the original expiration window.
            await self.async_add_to_queue(
                person_id=entry["person_id"],
                category_id=entry["category_id"],
                title=entry["title"],
                message=entry["message"],
                data=entry.get("data"),
                expiration_hours=remaining_hours,
                retry_count=retry_count,
                notification_id=entry.get("notification_id"),
            )
            requeued += 1
            _LOGGER.debug(
                "Re-queued notification for %s (retry %d, %.2fh remaining): %s",
                entry["person_id"],
                retry_count,
                remaining_hours,
                entry["title"],
            )

        return requeued, discarded
