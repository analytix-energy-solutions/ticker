"""Category mixin for TickerStore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.helpers.storage import Store

from ..const import CATEGORY_DEFAULT, CATEGORY_DEFAULT_NAME

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class CategoryMixin:
    """Mixin providing category functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _categories: dict[str, dict[str, Any]]
    - _categories_store: Store[dict[str, dict[str, Any]]]
    - _subscriptions: dict[str, dict[str, Any]]
    - _category_listeners: list[Callable[[], None]]
    - async_save_subscriptions: coroutine
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _categories: dict[str, dict[str, Any]]
    _categories_store: "Store[dict[str, dict[str, Any]]]"
    _subscriptions: dict[str, dict[str, Any]]
    _category_listeners: list[Callable[[], None]]

    async def async_save_subscriptions(self) -> None:
        """Save subscriptions to storage."""
        raise NotImplementedError

    async def async_save_categories(self) -> None:
        """Save categories to storage."""
        await self._categories_store.async_save(self._categories)
        self._notify_category_change()

    def _notify_category_change(self) -> None:
        """Notify listeners that categories have changed."""
        for callback in self._category_listeners:
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Error in category change callback: %s", err)

    def register_category_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback for category changes."""
        self._category_listeners.append(callback)

    def unregister_category_listener(self, callback: Callable[[], None]) -> None:
        """Unregister a callback for category changes."""
        if callback in self._category_listeners:
            self._category_listeners.remove(callback)

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
