"""Log management mixin for TickerStore."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import (
    MAX_LOG_ENTRIES,
    LOG_RETENTION_DAYS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

# Debounce configuration for log saves
LOG_SAVE_DEBOUNCE_SECONDS = 30  # Wait 30 seconds after last log before saving
LOG_SAVE_MAX_DELAY_SECONDS = 60  # Force save after 60 seconds regardless


class LogMixin:
    """Mixin providing log functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _logs: list[dict[str, Any]]
    - _logs_store: Store[list[dict[str, Any]]]
    - _logs_dirty: bool
    - _logs_save_unsub: Callable[[], None] | None
    - _logs_first_dirty_time: datetime | None
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _logs: list[dict[str, Any]]
    _logs_store: "Store[list[dict[str, Any]]]"
    _logs_dirty: bool
    _logs_save_unsub: Callable[[], None] | None
    _logs_first_dirty_time: datetime | None

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
        limit: int = MAX_LOG_ENTRIES,
        person_id: str | None = None,
        category_id: str | None = None,
        outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get log entries with optional filters."""
        filtered = self._logs

        if person_id:
            filtered = [entry for entry in filtered if entry.get("person_id") == person_id]

        if category_id:
            filtered = [entry for entry in filtered if entry.get("category_id") == category_id]

        if outcome:
            filtered = [entry for entry in filtered if entry.get("outcome") == outcome]

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

    async def async_update_log_action_taken(
        self,
        notification_id_short: str,
        person_id: str,
        action_taken: dict[str, Any],
    ) -> bool:
        """Update log entries with action_taken for matching notification and person.

        Matches by notification_id prefix (first 8 chars) and person_id.
        Only updates entries with outcome 'sent'.

        Returns True if any entries were updated.
        """
        updated = False
        for log in self._logs:
            nid = log.get("notification_id", "")
            if (
                nid
                and nid[:8] == notification_id_short
                and log.get("person_id") == person_id
                and log.get("outcome") == "sent"
            ):
                log["action_taken"] = action_taken
                updated = True

        if updated:
            await self.async_save_logs()
            _LOGGER.debug(
                "Updated action_taken for notification %s / %s",
                notification_id_short, person_id,
            )

        return updated

    def find_log_category_by_nid(
        self, nid_short: str, person_id: str
    ) -> str | None:
        """Find the category_id of the most recent log entry matching a notification.

        Matches by notification_id prefix (first 8 chars) and person_id, iterating
        logs in reverse (most-recent first). Used by action handling to resolve the
        correct category when an action set is shared across multiple categories
        (BUG-090).

        Returns the matching log entry's category_id, or None if no match.
        """
        for log in reversed(self._logs):
            nid = log.get("notification_id", "")
            if (
                nid
                and nid[:8] == nid_short
                and log.get("person_id") == person_id
            ):
                return log.get("category_id")
        return None

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
