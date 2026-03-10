"""Condition listeners for Ticker F-2 Advanced Conditions.

Manages listeners for entity state changes and time triggers to re-evaluate
queued notifications and release them when conditions are met.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import (
    MODE_CONDITIONAL,
    RULE_TYPE_STATE,
    RULE_TYPE_TIME,
)
from .conditions import (
    evaluate_rules,
    get_queue_triggers,
)

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


class ConditionListenerManager:
    """Manages entity and time listeners for condition-based queue release.

    This class:
    1. Scans subscriptions for state and time rules
    2. Sets up appropriate listeners
    3. Re-evaluates conditions when triggers fire
    4. Releases queued notifications when all conditions are met
    """

    def __init__(
        self,
        hass: HomeAssistant,
        store: "TickerStore",
        on_conditions_met: Callable[[str, str], Any] | None = None,
    ) -> None:
        """Initialize the listener manager.

        Args:
            hass: Home Assistant instance
            store: Ticker store instance
            on_conditions_met: Callback when conditions are met (person_id, category_id)
        """
        self.hass = hass
        self.store = store
        self.on_conditions_met = on_conditions_met

        # Track listener unsubscribe functions
        self._entity_unsubs: list[Callable[[], None]] = []
        self._time_unsubs: list[Callable[[], None]] = []

        # Track which entities we're listening to
        self._tracked_entities: set[str] = set()
        self._tracked_times: set[str] = set()  # "HH:MM" format

    async def async_setup(self) -> None:
        """Set up initial listeners based on current subscriptions."""
        await self.async_refresh_listeners()

    async def async_refresh_listeners(self) -> None:
        """Refresh all listeners based on current subscriptions.

        Called when subscriptions change to update what we're tracking.
        """
        # Clean up existing listeners
        self._cleanup_listeners()

        # Collect all triggers from conditional subscriptions
        all_entities: set[str] = set()
        all_times: set[str] = set()

        # Scan all subscriptions for conditional rules
        subscriptions = self.store._subscriptions
        for key, sub in subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])

            if not rules:
                continue

            triggers = get_queue_triggers(conditions)

            # Collect entity triggers
            for entity_id in triggers.get("entities", []):
                all_entities.add(entity_id)

            # Collect time triggers
            for time_window in triggers.get("time_windows", []):
                after = time_window.get("after", "")
                if after:
                    all_times.add(after)

        # Set up entity listeners
        if all_entities:
            self._setup_entity_listeners(list(all_entities))

        # Set up time listeners
        if all_times:
            self._setup_time_listeners(list(all_times))

        _LOGGER.debug(
            "Refreshed condition listeners: %d entities, %d times",
            len(all_entities),
            len(all_times),
        )

    def _cleanup_listeners(self) -> None:
        """Clean up all existing listeners."""
        for unsub in self._entity_unsubs:
            unsub()
        self._entity_unsubs.clear()
        self._tracked_entities.clear()

        for unsub in self._time_unsubs:
            unsub()
        self._time_unsubs.clear()
        self._tracked_times.clear()

    def _setup_entity_listeners(self, entity_ids: list[str]) -> None:
        """Set up state change listeners for entities.

        Args:
            entity_ids: List of entity IDs to track
        """
        if not entity_ids:
            return

        self._tracked_entities = set(entity_ids)

        unsub = async_track_state_change_event(
            self.hass,
            entity_ids,
            self._handle_entity_state_change,
        )
        self._entity_unsubs.append(unsub)

        _LOGGER.debug(
            "Set up entity listeners for: %s",
            entity_ids,
        )

    def _setup_time_listeners(self, times: list[str]) -> None:
        """Set up time-based listeners.

        Args:
            times: List of time strings in "HH:MM" format
        """
        for time_str in times:
            if time_str in self._tracked_times:
                continue

            try:
                parts = time_str.split(":")
                hour = int(parts[0])
                minute = int(parts[1])

                unsub = async_track_time_change(
                    self.hass,
                    self._handle_time_trigger,
                    hour=hour,
                    minute=minute,
                    second=0,
                )
                self._time_unsubs.append(unsub)
                self._tracked_times.add(time_str)

                _LOGGER.debug("Set up time listener for: %s", time_str)

            except (ValueError, IndexError) as err:
                _LOGGER.warning(
                    "Invalid time format '%s': %s",
                    time_str,
                    err,
                )

    @callback
    def _handle_entity_state_change(self, event: Event) -> None:
        """Handle entity state change events.

        Re-evaluates affected subscriptions when a tracked entity changes.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state or not old_state:
            return

        # Skip if state didn't actually change
        if new_state.state == old_state.state:
            return

        _LOGGER.debug(
            "Entity %s changed: %s -> %s",
            entity_id,
            old_state.state,
            new_state.state,
        )

        # Schedule async re-evaluation
        self.hass.async_create_task(
            self._async_reevaluate_for_entity(entity_id)
        )

    @callback
    def _handle_time_trigger(self, now) -> None:
        """Handle time trigger events.

        Re-evaluates subscriptions with time rules at the specified time.
        """
        time_str = now.strftime("%H:%M")
        _LOGGER.debug("Time trigger fired: %s", time_str)

        # Schedule async re-evaluation
        self.hass.async_create_task(
            self._async_reevaluate_for_time(time_str)
        )

    async def _async_reevaluate_for_entity(self, entity_id: str) -> None:
        """Re-evaluate subscriptions affected by an entity change.

        Args:
            entity_id: The entity that changed
        """
        await self._async_reevaluate_subscriptions(
            filter_type=RULE_TYPE_STATE,
            filter_value=entity_id,
        )

    async def _async_reevaluate_for_time(self, time_str: str) -> None:
        """Re-evaluate subscriptions affected by a time trigger.

        Args:
            time_str: The time that triggered ("HH:MM")
        """
        await self._async_reevaluate_subscriptions(
            filter_type=RULE_TYPE_TIME,
            filter_value=time_str,
        )

    async def _async_reevaluate_subscriptions(
        self,
        filter_type: str | None = None,
        filter_value: str | None = None,
    ) -> None:
        """Re-evaluate conditional subscriptions and release queued notifications.

        Args:
            filter_type: Only check subscriptions with this rule type
            filter_value: Only check subscriptions with this value (entity_id or time)
        """
        subscriptions = self.store._subscriptions

        for key, sub in subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            person_id = sub.get("person_id")
            category_id = sub.get("category_id")

            if not person_id or not category_id:
                continue

            # Check if this subscription has relevant rules
            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])

            if not rules:
                continue

            # Filter by rule type if specified
            if filter_type:
                has_matching_rule = False
                for rule in rules:
                    if rule.get("type") != filter_type:
                        continue
                    if filter_type == RULE_TYPE_STATE:
                        if rule.get("entity_id") == filter_value:
                            has_matching_rule = True
                            break
                    elif filter_type == RULE_TYPE_TIME:
                        if rule.get("after") == filter_value:
                            has_matching_rule = True
                            break

                if not has_matching_rule:
                    continue

            # Check if user has queued notifications
            queued = self.store.get_queue_for_person(person_id)
            if not queued:
                continue

            # Filter to this category's queued notifications
            category_queued = [q for q in queued if q.get("category_id") == category_id]
            if not category_queued:
                continue

            # Get person state
            person_state = self.hass.states.get(person_id)
            if not person_state:
                continue

            # Evaluate all rules
            all_met, reasons = evaluate_rules(
                self.hass,
                rules,
                person_state,
                dt_util.now(),
            )

            if all_met:
                _LOGGER.info(
                    "Conditions met for %s/%s - triggering queue release",
                    person_id,
                    category_id,
                )

                # Trigger callback if registered
                if self.on_conditions_met:
                    await self.on_conditions_met(person_id, category_id)
            else:
                _LOGGER.debug(
                    "Conditions not yet met for %s/%s: %s",
                    person_id,
                    category_id,
                    reasons,
                )

    async def async_unload(self) -> None:
        """Clean up all listeners on unload."""
        self._cleanup_listeners()
        _LOGGER.debug("Condition listeners unloaded")
