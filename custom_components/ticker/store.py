"""Storage management for Ticker integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    STORAGE_KEY_CATEGORIES,
    STORAGE_KEY_SUBSCRIPTIONS,
    STORAGE_KEY_USERS,
    STORAGE_KEY_QUEUE,
    STORAGE_KEY_LOGS,
    DEFAULT_SUBSCRIPTION_MODE,
    CATEGORY_DEFAULT,
    CATEGORY_DEFAULT_NAME,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    DEFAULT_CONDITION_ZONE,
    LEGACY_MODE_ALWAYS,
    LEGACY_MODE_NEVER,
    LEGACY_MODE_WHEN_IN_ZONE,
    LEGACY_MODE_ON_ARRIVAL,
    SET_BY_USER,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
)
from .store_queue_log import QueueLogMixin

_LOGGER = logging.getLogger(__name__)


class TickerStore(QueueLogMixin):
    """Manage Ticker data storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self.hass = hass

        # Typed Store definitions per HA best practices
        self._categories_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_CATEGORIES
        )
        self._subscriptions_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_SUBSCRIPTIONS
        )
        self._users_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_USERS
        )
        self._queue_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_QUEUE
        )
        self._logs_store: Store[list[dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_LOGS
        )

        # In-memory data
        self._categories: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._users: dict[str, dict[str, Any]] = {}
        self._queue: dict[str, dict[str, Any]] = {}
        self._logs: list[dict[str, Any]] = []
        self._category_listeners: list[Callable[[], None]] = []

        # Debounced log saving state (used by QueueLogMixin)
        self._logs_dirty: bool = False
        self._logs_save_unsub: Callable[[], None] | None = None
        self._logs_first_dirty_time: datetime | None = None

    async def async_load(self) -> None:
        """Load data from storage."""
        categories_data = await self._categories_store.async_load()
        self._categories = categories_data if categories_data else {}

        subscriptions_data = await self._subscriptions_store.async_load()
        self._subscriptions = subscriptions_data if subscriptions_data else {}

        # Migrate subscriptions if needed
        if self._subscriptions:
            migrated = await self._async_migrate_subscriptions()
            if migrated:
                _LOGGER.info("Migrated %d subscriptions to v2 format", migrated)

            # Migrate zones format to rules format (F-2)
            migrated_rules = await self._async_migrate_conditions_to_rules()
            if migrated_rules:
                _LOGGER.info("Migrated %d subscriptions to rules format", migrated_rules)

        users_data = await self._users_store.async_load()
        self._users = users_data if users_data else {}

        # Migrate users to add device_preference if needed
        if self._users:
            migrated_users = await self._async_migrate_users()
            if migrated_users:
                _LOGGER.info("Migrated %d users to include device_preference", migrated_users)

        queue_data = await self._queue_store.async_load()
        self._queue = queue_data if queue_data else {}

        logs_data = await self._logs_store.async_load()
        self._logs = logs_data if logs_data else []

        # Ensure default category exists
        await self._async_ensure_default_category()

        # Clean up expired queue entries (from mixin)
        await self._async_cleanup_expired_queue()

        # Clean up old log entries (from mixin)
        await self._async_cleanup_old_logs()

        _LOGGER.debug(
            "Loaded %d categories, %d subscriptions, %d users, %d queued, %d logs",
            len(self._categories),
            len(self._subscriptions),
            len(self._users),
            len(self._queue),
            len(self._logs),
        )

    async def async_unload(self) -> None:
        """Unload store and save any pending data."""
        # Cancel any pending debounced save
        if self._logs_save_unsub:
            self._logs_save_unsub()
            self._logs_save_unsub = None

        # Save dirty logs immediately
        if self._logs_dirty:
            await self._async_save_logs_immediate()

        _LOGGER.debug("Store unloaded, pending logs saved")

    async def _async_ensure_default_category(self) -> None:
        """Ensure the default 'General' category exists."""
        if CATEGORY_DEFAULT not in self._categories:
            self._categories[CATEGORY_DEFAULT] = {
                "id": CATEGORY_DEFAULT,
                "name": CATEGORY_DEFAULT_NAME,
                "icon": "mdi:bell",
                "color": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "is_default": True,
            }
            await self._categories_store.async_save(self._categories)
            _LOGGER.info("Created default category: %s", CATEGORY_DEFAULT_NAME)

    async def _async_migrate_subscriptions(self) -> int:
        """Migrate subscriptions from v1 to v2 format.

        v1 format: mode = ALWAYS|NEVER|WHEN_IN_ZONE|ON_ARRIVAL, zone = str
        v2 format: mode = always|never|conditional, conditions = {zones: {...}}

        Returns count of migrated subscriptions.
        """
        migrated_count = 0

        for key, sub in self._subscriptions.items():
            old_mode = sub.get("mode", "")

            # Skip if already in v2 format (lowercase modes)
            if old_mode in (MODE_ALWAYS, MODE_NEVER, MODE_CONDITIONAL):
                continue

            # Migrate from v1 uppercase modes
            if old_mode == LEGACY_MODE_ALWAYS:
                sub["mode"] = MODE_ALWAYS
                sub.pop("zone", None)  # Remove legacy zone field
                migrated_count += 1

            elif old_mode == LEGACY_MODE_NEVER:
                sub["mode"] = MODE_NEVER
                sub.pop("zone", None)
                migrated_count += 1

            elif old_mode == LEGACY_MODE_WHEN_IN_ZONE:
                zone = sub.pop("zone", DEFAULT_CONDITION_ZONE)
                sub["mode"] = MODE_CONDITIONAL
                sub["conditions"] = {
                    "zones": {
                        zone: {
                            "deliver_while_here": True,
                            "queue_until_arrival": False,
                        }
                    }
                }
                migrated_count += 1

            elif old_mode == LEGACY_MODE_ON_ARRIVAL:
                zone = sub.pop("zone", DEFAULT_CONDITION_ZONE)
                sub["mode"] = MODE_CONDITIONAL
                sub["conditions"] = {
                    "zones": {
                        zone: {
                            "deliver_while_here": False,
                            "queue_until_arrival": True,
                        }
                    }
                }
                migrated_count += 1

        if migrated_count > 0:
            await self.async_save_subscriptions()

        return migrated_count

    async def _async_migrate_users(self) -> int:
        """Migrate users to add device_preference field.

        Returns count of migrated users.
        """
        migrated_count = 0

        for person_id, user in self._users.items():
            # Skip if already has device_preference
            if "device_preference" in user:
                continue

            # Add default device_preference
            user["device_preference"] = {
                "mode": DEVICE_MODE_ALL,
                "devices": [],
            }
            migrated_count += 1

        if migrated_count > 0:
            await self.async_save_users()

        return migrated_count

    async def _async_migrate_conditions_to_rules(self) -> int:
        """Migrate conditions from zones format to rules format (F-2).

        Legacy format:
            conditions: {
                zones: {
                    "zone.home": {deliver_while_here: True, queue_until_arrival: True}
                }
            }

        New rules format:
            conditions: {
                rules: [
                    {type: "zone", zone_id: "zone.home", deliver_when_met: True, queue_until_met: True}
                ]
            }

        Returns count of migrated subscriptions.
        """
        from .conditions import convert_legacy_zones_to_rules

        migrated_count = 0

        for key, sub in self._subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            conditions = sub.get("conditions", {})

            # Skip if already has rules format
            if "rules" in conditions:
                continue

            # Check for legacy zones format
            zones = conditions.get("zones", {})
            if not zones:
                continue

            # Convert to rules format
            rules = convert_legacy_zones_to_rules(zones)
            sub["conditions"] = {"rules": rules}
            migrated_count += 1

            _LOGGER.debug(
                "Migrated subscription %s from zones to rules format",
                key,
            )

        if migrated_count > 0:
            await self.async_save_subscriptions()

        return migrated_count

    async def async_save_categories(self) -> None:
        """Save categories to storage."""
        await self._categories_store.async_save(self._categories)
        self._notify_category_change()

    async def async_save_subscriptions(self) -> None:
        """Save subscriptions to storage."""
        await self._subscriptions_store.async_save(self._subscriptions)

    async def async_save_users(self) -> None:
        """Save users to storage."""
        await self._users_store.async_save(self._users)

    def _notify_category_change(self) -> None:
        """Notify listeners that categories have changed."""
        for callback in self._category_listeners:
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Error in category change callback: %s", err)

    def register_category_listener(self, callback) -> None:
        """Register a callback for category changes."""
        self._category_listeners.append(callback)

    def unregister_category_listener(self, callback) -> None:
        """Unregister a callback for category changes."""
        if callback in self._category_listeners:
            self._category_listeners.remove(callback)

    # =========================================================================
    # Category methods
    # =========================================================================

    def get_categories(self) -> dict[str, dict[str, Any]]:
        """Get all categories."""
        return self._categories.copy()

    def get_category(self, category_id: str) -> dict[str, Any] | None:
        """Get a single category by ID."""
        return self._categories.get(category_id)

    def category_exists(self, category_id: str) -> bool:
        """Check if a category exists."""
        return category_id in self._categories

    async def async_create_category(
        self,
        category_id: str,
        name: str,
        icon: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Create a new category."""
        category = {
            "id": category_id,
            "name": name,
            "icon": icon or "mdi:bell",
            "color": color,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._categories[category_id] = category
        await self.async_save_categories()
        _LOGGER.info("Created category: %s", category_id)
        return category

    async def async_update_category(
        self,
        category_id: str,
        name: str | None = None,
        icon: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing category."""
        if category_id not in self._categories:
            return None

        category = self._categories[category_id]

        if name is not None:
            category["name"] = name
        if icon is not None:
            category["icon"] = icon
        if color is not None:
            category["color"] = color

        category["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self.async_save_categories()
        _LOGGER.info("Updated category: %s", category_id)
        return category

    def is_default_category(self, category_id: str) -> bool:
        """Check if a category is the default (non-deletable) category."""
        return category_id == CATEGORY_DEFAULT

    async def async_delete_category(self, category_id: str) -> bool:
        """Delete a category and its subscriptions."""
        if category_id not in self._categories:
            return False

        # Prevent deletion of default category
        if self.is_default_category(category_id):
            _LOGGER.warning("Cannot delete default category: %s", category_id)
            return False

        del self._categories[category_id]
        await self.async_save_categories()

        # Remove subscriptions for this category
        keys_to_remove = [
            key for key in self._subscriptions
            if key.endswith(f":{category_id}")
        ]
        for key in keys_to_remove:
            del self._subscriptions[key]

        if keys_to_remove:
            await self.async_save_subscriptions()

        _LOGGER.info("Deleted category: %s", category_id)
        return True

    # =========================================================================
    # User methods
    # =========================================================================

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

    async def async_set_user_enabled(self, person_id: str, enabled: bool) -> dict[str, Any]:
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
        self, person_id: str, **kwargs
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

    # =========================================================================
    # Subscription methods
    # =========================================================================

    def _subscription_key(self, person_id: str, category_id: str) -> str:
        """Generate subscription key."""
        return f"{person_id}:{category_id}"

    def get_subscription(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get subscription for a person and category."""
        key = self._subscription_key(person_id, category_id)
        return self._subscriptions.get(key)

    def get_subscriptions_for_person(
        self, person_id: str
    ) -> dict[str, dict[str, Any]]:
        """Get all subscriptions for a person."""
        prefix = f"{person_id}:"
        return {
            key.split(":")[1]: sub
            for key, sub in self._subscriptions.items()
            if key.startswith(prefix)
        }

    def get_subscriptions_for_category(
        self, category_id: str
    ) -> list[dict[str, Any]]:
        """Get all subscriptions for a category."""
        suffix = f":{category_id}"
        return [
            sub for key, sub in self._subscriptions.items()
            if key.endswith(suffix)
        ]

    def get_subscription_mode(
        self, person_id: str, category_id: str
    ) -> str:
        """Get subscription mode, defaulting to always if not set."""
        sub = self.get_subscription(person_id, category_id)
        if sub:
            return sub.get("mode", DEFAULT_SUBSCRIPTION_MODE)
        return DEFAULT_SUBSCRIPTION_MODE

    def get_subscription_conditions(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get subscription conditions for conditional mode."""
        sub = self.get_subscription(person_id, category_id)
        if sub and sub.get("mode") == MODE_CONDITIONAL:
            return sub.get("conditions", {})
        return None

    def get_device_override(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get device override for a subscription.

        Returns:
            Dict with 'enabled' (bool) and 'devices' (list) if override exists,
            None otherwise.
        """
        sub = self.get_subscription(person_id, category_id)
        if sub:
            return sub.get("device_override")
        return None

    def _has_valid_conditions(self, conditions: dict[str, Any] | None) -> bool:
        """Check if conditions have at least one effective delivery path."""
        from .conditions import has_valid_rules
        return has_valid_rules(conditions)

    async def async_set_subscription(
        self,
        person_id: str,
        category_id: str,
        mode: str,
        conditions: dict[str, Any] | None = None,
        set_by: str | None = None,
        device_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set subscription for a person and category.

        Args:
            person_id: The person entity ID
            category_id: The category ID
            mode: One of 'always', 'never', 'conditional'
            conditions: For conditional mode, dict with zones config:
                {
                    "zones": {
                        "zone.home": {
                            "deliver_while_here": True,
                            "queue_until_arrival": True
                        }
                    }
                }
            set_by: Who set this subscription ('user' or 'admin')
            device_override: Optional device override for this category:
                {
                    "enabled": True,
                    "devices": ["notify.mobile_app_tablet"]
                }
        """
        key = self._subscription_key(person_id, category_id)

        subscription = {
            "person_id": person_id,
            "category_id": category_id,
            "mode": mode,
            "set_by": set_by or SET_BY_USER,
        }

        if mode == MODE_CONDITIONAL:
            if conditions and self._has_valid_conditions(conditions):
                subscription["conditions"] = conditions
            else:
                # No valid conditions - fallback to always
                _LOGGER.warning(
                    "Conditional mode for %s/%s has no valid conditions, falling back to always",
                    person_id,
                    category_id,
                )
                subscription["mode"] = MODE_ALWAYS

        # Device override only applies to always/conditional modes
        if device_override and mode in (MODE_ALWAYS, MODE_CONDITIONAL):
            subscription["device_override"] = device_override
        elif mode == MODE_NEVER:
            # Clear device override for 'never' mode
            subscription.pop("device_override", None)

        self._subscriptions[key] = subscription
        await self.async_save_subscriptions()
        _LOGGER.debug(
            "Set subscription: %s -> %s = %s (set_by: %s, device_override: %s)",
            person_id, category_id, subscription["mode"], subscription["set_by"],
            "enabled" if subscription.get("device_override", {}).get("enabled") else "disabled"
        )
        return subscription

    async def async_delete_subscription(
        self, person_id: str, category_id: str
    ) -> bool:
        """Delete a subscription."""
        key = self._subscription_key(person_id, category_id)
        if key not in self._subscriptions:
            return False

        del self._subscriptions[key]
        await self.async_save_subscriptions()
        return True
