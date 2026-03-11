"""User mixin for TickerStore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ..const import DEVICE_MODE_ALL, DEVICE_MODE_SELECTED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class UserMixin:
    """Mixin providing user functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _users: dict[str, dict[str, Any]]
    - _users_store: Store[dict[str, dict[str, Any]]]
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _users: dict[str, dict[str, Any]]
    _users_store: "Store[dict[str, dict[str, Any]]]"

    async def async_save_users(self) -> None:
        """Save users to storage."""
        await self._users_store.async_save(self._users)

    def get_users(self) -> dict[str, dict[str, Any]]:
        """Get all stored users."""
        return self._users.copy()

    def get_user(self, person_id: str) -> dict[str, Any] | None:
        """Get a single user by person ID."""
        return self._users.get(person_id)

    def is_user_enabled(self, person_id: str) -> bool:
        """Check if a user is enabled for notifications. Default is True."""
        user = self._users.get(person_id)
        if user is None:
            return True
        return user.get("enabled", True)

    def _create_default_user(self, person_id: str) -> dict[str, Any]:
        """Create a default user object."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "person_id": person_id,
            "enabled": True,
            "notify_services_override": [],  # Legacy field, kept for compatibility
            "device_preference": {
                "mode": DEVICE_MODE_ALL,
                "devices": [],
            },
            "created_at": now,
            "updated_at": now,
        }

    async def async_get_or_create_user(self, person_id: str) -> dict[str, Any]:
        """Get user or create with defaults if not exists."""
        if person_id not in self._users:
            self._users[person_id] = self._create_default_user(person_id)
            await self.async_save_users()
            _LOGGER.debug("Created user record for: %s", person_id)
        return self._users[person_id]

    async def async_set_user_enabled(
        self, person_id: str, enabled: bool
    ) -> dict[str, Any]:
        """Enable or disable a user for notifications."""
        if person_id not in self._users:
            self._users[person_id] = self._create_default_user(person_id)

        self._users[person_id]["enabled"] = enabled
        self._users[person_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save_users()

        status = "enabled" if enabled else "disabled"
        _LOGGER.info("User %s notifications %s", person_id, status)
        return self._users[person_id]

    async def async_update_user(
        self, person_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Update user properties."""
        if person_id not in self._users:
            self._users[person_id] = self._create_default_user(person_id)

        for key, value in kwargs.items():
            if key in ("enabled", "notify_services_override", "device_preference"):
                self._users[person_id][key] = value

        self._users[person_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save_users()
        return self._users[person_id]

    def get_device_preference(self, person_id: str) -> dict[str, Any]:
        """Get device preference for a person.

        Returns:
            Dict with 'mode' ('all' or 'selected') and 'devices' (list of service IDs)
        """
        user = self._users.get(person_id)
        if user and "device_preference" in user:
            return user["device_preference"]
        return {"mode": DEVICE_MODE_ALL, "devices": []}

    async def async_set_device_preference(
        self,
        person_id: str,
        mode: str,
        devices: list[str] | None = None,
    ) -> dict[str, Any]:
        """Set device preference for a person.

        Args:
            person_id: The person entity ID
            mode: 'all' or 'selected'
            devices: List of notify service IDs (required if mode='selected')
        """
        if person_id not in self._users:
            self._users[person_id] = self._create_default_user(person_id)

        self._users[person_id]["device_preference"] = {
            "mode": mode,
            "devices": devices or [],
        }
        self._users[person_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save_users()

        _LOGGER.debug(
            "Set device preference for %s: mode=%s, devices=%s",
            person_id,
            mode,
            devices or [],
        )
        return self._users[person_id]
