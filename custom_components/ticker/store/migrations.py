"""Migration mixin for TickerStore."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..const import (
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    DEFAULT_CONDITION_ZONE,
    LEGACY_MODE_ALWAYS,
    LEGACY_MODE_NEVER,
    LEGACY_MODE_WHEN_IN_ZONE,
    LEGACY_MODE_ON_ARRIVAL,
    DEVICE_MODE_ALL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class MigrationMixin:
    """Mixin providing migration functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _subscriptions: dict[str, dict[str, Any]]
    - _users: dict[str, dict[str, Any]]
    - async_save_subscriptions: coroutine
    - async_save_users: coroutine
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _subscriptions: dict[str, dict[str, Any]]
    _users: dict[str, dict[str, Any]]

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

    async def _async_migrate_rule_flags_to_conditions(self) -> int:
        """Migrate deliver/queue flags from per-rule to conditions level.

        Previously, each rule had its own deliver_when_met/queue_until_met.
        Now these flags live at the conditions level (apply to the entire
        ruleset). This migrates already-converted rules data.

        Returns count of migrated subscriptions.
        """
        migrated_count = 0

        for key, sub in self._subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])
            if not rules:
                continue

            # Skip if conditions-level flags already exist
            if "deliver_when_met" in conditions:
                continue

            # Promote per-rule flags to conditions level
            has_deliver = any(
                rule.get("deliver_when_met", False) for rule in rules
            )
            has_queue = any(
                rule.get("queue_until_met", False) for rule in rules
            )
            conditions["deliver_when_met"] = has_deliver
            conditions["queue_until_met"] = has_queue

            # Strip per-rule flags
            for rule in rules:
                rule.pop("deliver_when_met", None)
                rule.pop("queue_until_met", None)

            migrated_count += 1
            _LOGGER.debug(
                "Migrated subscription %s flags to conditions level",
                key,
            )

        if migrated_count > 0:
            await self.async_save_subscriptions()

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
                    {type: "zone", zone_id: "zone.home", ...}
                ]
            }

        Returns count of migrated subscriptions.
        """
        from ..conditions import convert_legacy_zones_to_rules

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

            # Convert to new conditions format with top-level flags
            sub["conditions"] = convert_legacy_zones_to_rules(zones)
            migrated_count += 1

            _LOGGER.debug(
                "Migrated subscription %s from zones to rules format",
                key,
            )

        if migrated_count > 0:
            await self.async_save_subscriptions()

        return migrated_count
