"""Storage management for Ticker integration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
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
    DEFAULT_EXPIRATION_HOURS,
    MAX_LOG_ENTRIES,
    LOG_RETENTION_DAYS,
    MAX_QUEUE_RETRIES,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    DEFAULT_CONDITION_ZONE,
    LEGACY_MODE_ALWAYS,
    LEGACY_MODE_NEVER,
    LEGACY_MODE_WHEN_IN_ZONE,
    LEGACY_MODE_ON_ARRIVAL,
    SET_BY_USER,
    SET_BY_ADMIN,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
)

_LOGGER = logging.getLogger(__name__)

# Debounce configuration for log saves
LOG_SAVE_DEBOUNCE_SECONDS = 30  # Wait 30 seconds after last log before saving
LOG_SAVE_MAX_DELAY_SECONDS = 60  # Force save after 60 seconds regardless


class TickerStore:
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
        
        # Debounced log saving state
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

        # Clean up expired queue entries
        await self._async_cleanup_expired_queue()

        # Clean up old log entries
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
        if not conditions:
            return False
        
        zones = conditions.get("zones", {})
        for zone_id, zone_config in zones.items():
            if zone_config.get("deliver_while_here") or zone_config.get("queue_until_arrival"):
                return True
        
        # Future: check time, presence conditions here
        return False

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
