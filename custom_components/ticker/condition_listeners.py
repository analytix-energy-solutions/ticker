"""Condition listeners for Ticker F-2 Advanced Conditions.

Manages listeners for entity state changes and time triggers to re-evaluate
queued notifications and release them when conditions are met.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONDITION_NODE_GROUP,
    MODE_CONDITIONAL,
    RULE_TYPE_STATE,
    RULE_TYPE_TIME,
    RULE_TYPE_ZONE,
)
from .conditions import (
    evaluate_condition_tree,
    get_queue_triggers,
)

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


def _collect_leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively collect all leaf nodes from a condition tree.

    Args:
        node: A condition tree node (group or leaf).

    Returns:
        Flat list of all leaf (non-group) nodes.
    """
    if node.get("type") == CONDITION_NODE_GROUP:
        leaves: list[dict[str, Any]] = []
        for child in node.get("children", []):
            leaves.extend(_collect_leaves(child))
        return leaves
    return [node]


def _leaf_matches_filter(
    leaf: dict[str, Any],
    filter_type: str,
    filter_value: str | None,
) -> bool:
    """Check if a leaf node matches a filter type and value.

    Args:
        leaf: A leaf condition node.
        filter_type: Rule type to match (e.g. RULE_TYPE_STATE).
        filter_value: Value to match (entity_id or time string).

    Returns:
        True if the leaf matches the filter criteria.
    """
    if leaf.get("type") != filter_type:
        return False
    if filter_type == RULE_TYPE_STATE:
        return leaf.get("entity_id") == filter_value
    if filter_type == RULE_TYPE_TIME:
        # BUG-096: match either edge of the time window so `before`
        # triggers re-evaluate subscriptions too.
        return (
            leaf.get("after") == filter_value
            or leaf.get("before") == filter_value
        )
    return True


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

        # Debounced refresh state (BUG-086)
        self._pending_refresh_unsub: Callable[[], None] | None = None

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
        # This includes both person-based and recipient-based subscriptions.
        # Recipient subscriptions use keys prefixed with "recipient:".
        subscriptions = self.store.get_all_subscriptions()
        for key, sub in subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])
            tree = conditions.get("condition_tree")

            if not rules and not tree:
                continue

            # For recipient subscriptions, skip zone rules (recipients
            # have no location). Filter to time/state rules only.
            is_recipient = key.startswith("recipient:")
            if is_recipient and rules and not tree:
                effective_rules = [
                    r for r in rules
                    if r.get("type") != RULE_TYPE_ZONE
                ]
                if not effective_rules:
                    continue
                # Build trigger-extraction dict preserving queue_until_met flag
                trigger_conditions = dict(conditions)
                trigger_conditions["rules"] = effective_rules
            else:
                trigger_conditions = conditions

            triggers = get_queue_triggers(trigger_conditions)

            # Collect entity triggers
            for entity_id in triggers.get("entities", []):
                all_entities.add(entity_id)

            # Collect time triggers (BUG-096: track both edges of the
            # window so `before` fires listeners too). Empty strings
            # mean open-ended and are skipped.
            for time_window in triggers.get("time_windows", []):
                after = time_window.get("after", "")
                before = time_window.get("before", "")
                if after:
                    all_times.add(after)
                if before:
                    all_times.add(before)

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

        Handles both person-based and recipient-based subscriptions.
        Recipient subscriptions (key prefix "recipient:") skip zone rules
        and pass None for person_state since recipients have no location.

        Args:
            filter_type: Only check subscriptions with this rule type
            filter_value: Only check subscriptions with this value (entity_id or time)
        """
        subscriptions = self.store.get_all_subscriptions()

        for key, sub in subscriptions.items():
            if sub.get("mode") != MODE_CONDITIONAL:
                continue

            person_id = sub.get("person_id")
            category_id = sub.get("category_id")

            if not person_id or not category_id:
                continue

            is_recipient = key.startswith("recipient:")

            # BUG-044: disabled users must not have queued notifications
            # re-evaluated or released. Recipient subs are not user-gated.
            if not is_recipient and not self.store.is_user_enabled(person_id):
                continue

            # Check if this subscription has relevant conditions
            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])
            tree = conditions.get("condition_tree")

            if not rules and not tree:
                continue

            # Filter by rule type if specified (walk tree or flat rules)
            if filter_type:
                leaves = _collect_leaves(tree) if tree else list(rules)
                has_matching_rule = any(
                    _leaf_matches_filter(leaf, filter_type, filter_value)
                    for leaf in leaves
                )
                if not has_matching_rule:
                    continue

            # Check if person/recipient has queued notifications
            queued = self.store.get_queue_for_person(person_id)
            if not queued:
                continue

            # Filter to this category's queued notifications
            category_queued = [
                q for q in queued if q.get("category_id") == category_id
            ]
            if not category_queued:
                continue

            # Get person state (None for recipients — they have no location)
            person_state = None
            if not is_recipient:
                person_state = self.hass.states.get(person_id)
                if not person_state:
                    continue

            # Evaluate conditions (tree or flat rules)
            all_met, rule_results = evaluate_condition_tree(
                self.hass,
                conditions,
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
                    [reason for met, reason in rule_results if not met],
                )

    @callback
    def schedule_refresh(self) -> None:
        """Schedule a debounced refresh of condition listeners.

        Called from the store subscription listener whenever subscriptions
        change. Uses async_call_later with a 0.5s delay so cascaded deletes
        (e.g., removing a recipient with many subscriptions) coalesce into
        a single refresh instead of thrashing (BUG-086).
        """
        # Cancel any previously scheduled refresh so the timer resets
        if self._pending_refresh_unsub is not None:
            self._pending_refresh_unsub()
            self._pending_refresh_unsub = None

        async def _do_refresh(_now) -> None:
            self._pending_refresh_unsub = None
            try:
                await self.async_refresh_listeners()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Error refreshing condition listeners: %s", err
                )

        self._pending_refresh_unsub = async_call_later(
            self.hass, 0.5, _do_refresh
        )

    async def async_unload(self) -> None:
        """Clean up all listeners on unload."""
        # Cancel any pending debounced refresh so it does not fire
        # after teardown (BUG-086).
        if self._pending_refresh_unsub is not None:
            self._pending_refresh_unsub()
            self._pending_refresh_unsub = None

        self._cleanup_listeners()
        _LOGGER.debug("Condition listeners unloaded")
