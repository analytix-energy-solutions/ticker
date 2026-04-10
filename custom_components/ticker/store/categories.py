"""Category mixin for TickerStore."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.helpers.storage import Store

from ..const import CATEGORY_DEFAULT, CATEGORY_DEFAULT_NAME, SMART_TAG_MODE_NONE

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _has_active_smart_config(config: dict) -> bool:
    """Check if smart_notification config has any non-default values.

    The default tag_mode is "none" which is truthy, so a naive
    ``any(config.values())`` check would incorrectly treat an
    all-default config as active. This helper inspects each field
    individually against its default.
    """
    if config.get("group"):
        return True
    if config.get("tag_mode", SMART_TAG_MODE_NONE) != SMART_TAG_MODE_NONE:
        return True
    if config.get("sticky"):
        return True
    if config.get("persistent"):
        return True
    return False


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
        default_mode: str | None = None,
        default_conditions: dict[str, Any] | None = None,
        critical: bool = False,
        smart_notification: dict[str, Any] | None = None,
        action_set_id: str | None = None,
        navigate_to: str | None = None,
        expose_in_sensor: bool | None = None,
    ) -> dict[str, Any]:
        """Create a new category.

        Args:
            category_id: Unique slug identifier for the category (e.g., "security").
            name: Human-readable display name shown in the admin panel and notifications.
            icon: MDI icon string (e.g., "mdi:shield"). Defaults to "mdi:bell".
            color: Optional hex color string for visual distinction in the admin UI.
            default_mode: Default subscription mode ("always", "never", or "conditional")
                applied to new subscribers. Omitted from the category dict when None,
                which causes the global default ("always") to be used instead.
            default_conditions: Default conditions dict applied alongside default_mode
                when mode is "conditional". Omitted from the category dict when None.
            critical: When True, every notification sent to this category is treated as
                critical by default. The category dict omits the "critical" key when
                False (sparse storage). Per-call overrides on ticker.notify always take
                precedence over this category-level default.
            smart_notification: Optional dict of smart notification settings (group,
                tag, sticky, persistent). Omitted when None or all-default (sparse).
            action_set_id: Optional reference to a library action set. Omitted when None
                (sparse storage). An empty string clears any existing reference.
            navigate_to: Optional URL or HA path for tap-to-navigate on notification
                click (e.g., "/lovelace/cameras"). Omitted when None (sparse storage);
                the global default is applied at send time by formatting.py.
            expose_in_sensor: If False, the category sensor will record counts and
                last_triggered but omit notification header/body content from its
                attributes (BUG-099). Sparse storage — only persisted when False;
                read-time default is True via category.get("expose_in_sensor", True).
        """
        category: dict[str, Any] = {
            "id": category_id,
            "name": name,
            "icon": icon or "mdi:bell",
            "color": color,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if default_mode:
            category["default_mode"] = default_mode
        if default_conditions:
            category["default_conditions"] = default_conditions
        if critical:
            category["critical"] = True
        if smart_notification and _has_active_smart_config(smart_notification):
            category["smart_notification"] = smart_notification
        if action_set_id:
            category["action_set_id"] = action_set_id
        if navigate_to:
            category["navigate_to"] = navigate_to
        # Sparse storage: only persist expose_in_sensor when explicitly False
        # (matches critical/smart_notification pattern). Default at read time
        # is True via category.get("expose_in_sensor", True).
        if expose_in_sensor is False:
            category["expose_in_sensor"] = False
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
        default_mode: str | None = None,
        default_conditions: dict[str, Any] | None = None,
        clear_defaults: bool = False,
        critical: bool | None = None,
        smart_notification: dict[str, Any] | None = None,
        clear_smart_notification: bool = False,
        action_set_id: str | None = None,
        navigate_to: str | None = None,
        expose_in_sensor: bool | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing category.

        Args:
            clear_defaults: If True, remove default_mode and default_conditions.
            critical: If provided, set the critical flag on the category.
            smart_notification: If provided, set or clear smart notification config.
                A non-empty dict with truthy values is stored; an empty or all-default
                dict removes the key (sparse storage).
            clear_smart_notification: If True, explicitly remove smart_notification
                from the category dict. Takes precedence over smart_notification arg.
            navigate_to: If provided, set the tap-to-navigate URL on the category.
                A non-empty string is stored; an empty string clears the key (sparse).
            expose_in_sensor: If provided, control whether the category sensor
                exposes notification header/body (BUG-099). None leaves the current
                value unchanged. True removes the key (default behavior, sparse).
                False persists the key so the sensor blanks content.
        """
        if category_id not in self._categories:
            return None

        category = self._categories[category_id]

        if name is not None:
            category["name"] = name
        if icon is not None:
            category["icon"] = icon
        if color is not None:
            category["color"] = color
        if critical is not None:
            if critical:
                category["critical"] = True
            else:
                category.pop("critical", None)

        if clear_smart_notification:
            category.pop("smart_notification", None)
        elif smart_notification is not None:
            if smart_notification and _has_active_smart_config(smart_notification):
                category["smart_notification"] = smart_notification
            else:
                category.pop("smart_notification", None)

        # action_set_id: non-empty string sets, empty string clears (sparse)
        if action_set_id is not None:
            if action_set_id:
                category["action_set_id"] = action_set_id
            else:
                category.pop("action_set_id", None)

        # navigate_to: non-empty string sets, empty string clears (sparse)
        if navigate_to is not None:
            if navigate_to:
                category["navigate_to"] = navigate_to
            else:
                category.pop("navigate_to", None)

        # expose_in_sensor: sparse — store key only when False (BUG-099)
        if expose_in_sensor is not None:
            if expose_in_sensor is False:
                category["expose_in_sensor"] = False
            else:
                category.pop("expose_in_sensor", None)

        if clear_defaults:
            category.pop("default_mode", None)
            category.pop("default_conditions", None)
        else:
            if default_mode is not None:
                category["default_mode"] = default_mode
            if default_conditions is not None:
                category["default_conditions"] = default_conditions

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
            # Fire once after the cascade so condition listeners refresh
            # a single time instead of per-key (BUG-086).
            self._notify_subscription_change()  # type: ignore[attr-defined]

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
