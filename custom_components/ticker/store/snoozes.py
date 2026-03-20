"""Snooze management mixin for TickerStore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class SnoozeMixin:
    """Mixin providing snooze functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _snoozes: dict[str, dict[str, Any]]
    - _snoozes_store: Store[dict[str, dict[str, Any]]]
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _snoozes: dict[str, dict[str, Any]]
    _snoozes_store: "Store[dict[str, dict[str, Any]]]"

    async def async_save_snoozes(self) -> None:
        """Save snoozes to storage."""
        await self._snoozes_store.async_save(self._snoozes)

    def get_snooze(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Return snooze record if active (not expired), else None."""
        key = f"{person_id}:{category_id}"
        record = self._snoozes.get(key)
        if record is None:
            return None

        expires_at = datetime.fromisoformat(record["expires_at"])
        if datetime.now(timezone.utc) >= expires_at:
            # Lazy-delete expired snooze
            del self._snoozes[key]
            self.hass.async_create_task(self.async_save_snoozes())
            return None

        return record

    def is_snoozed(self, person_id: str, category_id: str) -> bool:
        """Check if a person/category combination is currently snoozed."""
        return self.get_snooze(person_id, category_id) is not None

    async def async_set_snooze(
        self, person_id: str, category_id: str, minutes: int
    ) -> dict[str, Any]:
        """Create or overwrite a snooze record."""
        now = datetime.now(timezone.utc)
        key = f"{person_id}:{category_id}"

        record = {
            "person_id": person_id,
            "category_id": category_id,
            "snoozed_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=minutes)).isoformat(),
        }

        self._snoozes[key] = record
        await self.async_save_snoozes()

        _LOGGER.info(
            "Snoozed %s/%s for %d minutes", person_id, category_id, minutes
        )
        return record

    async def async_clear_snooze(
        self, person_id: str, category_id: str
    ) -> bool:
        """Delete a snooze record. Returns True if found."""
        key = f"{person_id}:{category_id}"
        if key not in self._snoozes:
            return False

        del self._snoozes[key]
        await self.async_save_snoozes()
        _LOGGER.info("Cleared snooze for %s/%s", person_id, category_id)
        return True

    def get_snoozes_for_person(
        self, person_id: str
    ) -> list[dict[str, Any]]:
        """Get all active snoozes for a person."""
        now = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        expired_keys: list[str] = []

        for key, record in self._snoozes.items():
            if record["person_id"] != person_id:
                continue
            expires_at = datetime.fromisoformat(record["expires_at"])
            if now >= expires_at:
                expired_keys.append(key)
            else:
                active.append(record)

        # Lazy-delete expired
        if expired_keys:
            for key in expired_keys:
                del self._snoozes[key]
            self.hass.async_create_task(self.async_save_snoozes())

        return active

    async def _async_cleanup_expired_snoozes(self) -> None:
        """Bulk remove expired snoozes. Called on load."""
        now = datetime.now(timezone.utc)
        expired_keys = [
            key
            for key, record in self._snoozes.items()
            if datetime.fromisoformat(record["expires_at"]) <= now
        ]

        if expired_keys:
            for key in expired_keys:
                del self._snoozes[key]
            await self.async_save_snoozes()
            _LOGGER.info("Cleaned up %d expired snoozes", len(expired_keys))
