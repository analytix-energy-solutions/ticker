"""Storage management for Ticker integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import (
    STORAGE_VERSION,
    STORAGE_KEY_CATEGORIES,
    STORAGE_KEY_SUBSCRIPTIONS,
    STORAGE_KEY_USERS,
    STORAGE_KEY_QUEUE,
    STORAGE_KEY_LOGS,
    STORAGE_KEY_SNOOZES,
    STORAGE_KEY_RECIPIENTS,
)
from ..store_queue_log import QueueLogMixin
from .categories import CategoryMixin
from .users import UserMixin
from .subscriptions import SubscriptionMixin
from .snoozes import SnoozeMixin
from .recipients import RecipientMixin
from .migrations import MigrationMixin

_LOGGER = logging.getLogger(__name__)

# Export TickerStore for backward-compatible imports
__all__ = ["TickerStore"]


class TickerStore(
    QueueLogMixin,
    CategoryMixin,
    UserMixin,
    SubscriptionMixin,
    SnoozeMixin,
    RecipientMixin,
    MigrationMixin,
):
    """Manage Ticker data storage.

    This class combines multiple mixins to provide complete storage functionality:
    - QueueLogMixin: Queue and log management
    - CategoryMixin: Category CRUD operations
    - UserMixin: User management and device preferences
    - SubscriptionMixin: Subscription management
    - RecipientMixin: Non-user recipient management (F-18)
    - MigrationMixin: Data migration utilities
    """

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
        self._snoozes_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_SNOOZES
        )
        self._recipients_store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_RECIPIENTS
        )

        # In-memory data
        self._categories: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._users: dict[str, dict[str, Any]] = {}
        self._queue: dict[str, dict[str, Any]] = {}
        self._logs: list[dict[str, Any]] = []
        self._snoozes: dict[str, dict[str, Any]] = {}
        self._recipients: dict[str, dict[str, Any]] = {}
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
                _LOGGER.info(
                    "Migrated %d subscriptions to rules format", migrated_rules
                )

            # Migrate per-rule flags to conditions level
            migrated_flags = await self._async_migrate_rule_flags_to_conditions()
            if migrated_flags:
                _LOGGER.info(
                    "Migrated %d subscriptions flags to conditions level",
                    migrated_flags,
                )

        users_data = await self._users_store.async_load()
        self._users = users_data if users_data else {}

        # Migrate users to add device_preference if needed
        if self._users:
            migrated_users = await self._async_migrate_users()
            if migrated_users:
                _LOGGER.info(
                    "Migrated %d users to include device_preference", migrated_users
                )

        # Load recipients and migrate to device_type model if needed
        recipients_data = await self._recipients_store.async_load()
        self._recipients = recipients_data or {}
        if self._recipients:
            migrated_recipients = RecipientMixin.migrate_recipient_data(
                self._recipients
            )
            if migrated_recipients:
                await self.async_save_recipients()
                _LOGGER.info(
                    "Migrated %d recipients to device_type model",
                    migrated_recipients,
                )

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

        # Load snoozes and clean up expired
        snoozes_data = await self._snoozes_store.async_load()
        self._snoozes = snoozes_data if snoozes_data else {}
        await self._async_cleanup_expired_snoozes()

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
