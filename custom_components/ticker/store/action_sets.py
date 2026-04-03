"""Action Sets Library store mixin (F-5b).

Provides CRUD for a reusable library of action set definitions,
independent of any category. Categories reference library entries
by ID (action_set_id) instead of embedding inline action_set dicts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class ActionSetMixin:
    """Mixin providing CRUD for the reusable action sets library.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _action_sets: dict[str, dict[str, Any]]
    - _action_sets_store: Store[dict[str, dict[str, Any]]]
    - _categories: dict[str, dict[str, Any]]
    - _action_set_listeners: list[Callable[[], None]]
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _action_sets: dict[str, dict[str, Any]]
    _action_sets_store: "Store[dict[str, dict[str, Any]]]"
    _categories: dict[str, dict[str, Any]]
    _categories_store: "Store[dict[str, dict[str, Any]]]"
    _action_set_listeners: list[Callable[[], None]]

    def _notify_action_set_change(self) -> None:
        """Notify listeners that action sets have changed."""
        for cb in self._action_set_listeners:
            try:
                cb()
            except Exception as err:
                _LOGGER.error("Error in action set change callback: %s", err)

    def register_action_set_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback for action set changes."""
        self._action_set_listeners.append(callback)

    def unregister_action_set_listener(self, callback: Callable[[], None]) -> None:
        """Unregister a callback for action set changes."""
        if callback in self._action_set_listeners:
            self._action_set_listeners.remove(callback)

    def get_action_sets(self) -> dict[str, dict[str, Any]]:
        """Return all action sets in the library."""
        return dict(self._action_sets)

    def get_action_set(self, action_set_id: str) -> dict[str, Any] | None:
        """Return a single action set by ID, or None if not found."""
        return self._action_sets.get(action_set_id)

    async def async_create_action_set(
        self,
        action_set_id: str,
        name: str,
        actions: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new action set in the library.

        Args:
            action_set_id: Unique slug identifier.
            name: Display name.
            actions: List of action definitions.
            description: Optional description.

        Returns:
            The created action set dict.

        Raises:
            ValueError: If action_set_id already exists.
        """
        if action_set_id in self._action_sets:
            raise ValueError(f"Action set '{action_set_id}' already exists")
        now = datetime.now(timezone.utc).isoformat()
        entry: dict[str, Any] = {
            "id": action_set_id,
            "name": name,
            "description": description,
            "actions": actions,
            "created_at": now,
            "updated_at": now,
        }
        self._action_sets[action_set_id] = entry
        await self._async_save_action_sets()
        self._notify_action_set_change()
        _LOGGER.info("Created action set '%s'", action_set_id)
        return entry

    async def async_update_action_set(
        self,
        action_set_id: str,
        *,
        name: str | None = None,
        actions: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing action set.

        Only provided fields are updated; None values are skipped.

        Returns:
            The updated entry, or None if not found.
        """
        entry = self._action_sets.get(action_set_id)
        if entry is None:
            return None
        if name is not None:
            entry["name"] = name
        if actions is not None:
            entry["actions"] = actions
        if description is not None:
            entry["description"] = description
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._async_save_action_sets()
        self._notify_action_set_change()
        _LOGGER.debug("Updated action set '%s'", action_set_id)
        return entry

    async def async_delete_action_set(self, action_set_id: str) -> bool:
        """Delete an action set from the library.

        Returns:
            True if deleted, False if not found.
        """
        if action_set_id not in self._action_sets:
            return False
        del self._action_sets[action_set_id]
        await self._async_save_action_sets()
        self._notify_action_set_change()
        _LOGGER.info("Deleted action set '%s'", action_set_id)
        return True

    def is_action_set_in_use(self, action_set_id: str) -> list[str]:
        """Return list of category IDs that reference this action set.

        Used to guard against deleting an in-use action set.
        """
        using: list[str] = []
        for cat_id, cat in self._categories.items():
            if cat.get("action_set_id") == action_set_id:
                using.append(cat_id)
        return using

    async def _async_migrate_inline_action_sets(self) -> None:
        """Migrate inline category.action_set dicts to the action sets library.

        For each category with an inline action_set and no action_set_id:
        1. Create a library entry with id = "{category_id}_actions"
        2. Set category.action_set_id to the new library entry ID
        3. Remove the inline action_set key

        Idempotent -- safe to run on every load.
        """
        migrated = 0
        for cat_id, cat in self._categories.items():
            if "action_set" not in cat:
                continue
            if "action_set_id" in cat:
                # Already migrated -- clean up orphaned inline key
                cat.pop("action_set", None)
                migrated += 1
                continue

            inline = cat.pop("action_set")
            if not isinstance(inline, dict):
                _LOGGER.warning("Skipping invalid inline action_set for %s", cat_id)
                continue
            library_id = f"{cat_id}_actions"

            # Avoid ID collision
            if library_id in self._action_sets:
                library_id = f"{cat_id}_actions_migrated"

            now = datetime.now(timezone.utc).isoformat()
            self._action_sets[library_id] = {
                "id": library_id,
                "name": f"{cat.get('name', cat_id)} Actions",
                "description": f"Migrated from category {cat_id}",
                "actions": inline.get("actions", []),
                "created_at": now,
                "updated_at": now,
            }
            cat["action_set_id"] = library_id
            migrated += 1
            _LOGGER.info(
                "Migrated inline action_set from category '%s' to library entry '%s'",
                cat_id,
                library_id,
            )

        if migrated:
            await self._async_save_action_sets()
            # Categories also need saving since we modified them
            self._categories_store.async_delay_save(
                lambda: dict(self._categories), 1.0
            )

    async def _async_save_action_sets(self) -> None:
        """Persist action sets to storage."""
        self._action_sets_store.async_delay_save(
            lambda: dict(self._action_sets), 1.0
        )
