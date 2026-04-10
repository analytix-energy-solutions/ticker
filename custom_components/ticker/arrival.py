"""Arrival listener for Ticker integration.

Handles person state changes to deliver queued notifications when users
arrive at configured zones.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    EventEntityRegistryUpdatedData,
)

from .const import MODE_CONDITIONAL
from .conditions import evaluate_condition_tree, resolve_zone_name
from .bundled_notify import async_send_bundled_notification
from .recipient_notify import async_send_to_recipient

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_arrival_listener(
    hass: HomeAssistant,
    entry: "TickerConfigEntry",
) -> Callable[[], None]:
    """Set up listener for person state changes to handle ON_ARRIVAL notifications.

    This function sets up two listeners:
    1. A state change listener for all current person entities
    2. An entity registry listener to dynamically add new person entities

    Returns a function that unsubscribes from both listeners.
    """
    store = entry.runtime_data.store

    # Container to hold current state listener unsubscribe (allows updates)
    state_unsub_container: dict[str, Callable[[], None] | None] = {"unsub": None}

    # Track which person entities we're currently listening to
    tracked_persons: set[str] = set()

    async def _handle_person_state_change(event: Event) -> None:
        """Handle person state changes for queue_until_arrival delivery.

        Supports F-2 Advanced Conditions with:
        - Zone, time, and entity state rules
        - AND logic (all rules must be met for delivery)
        """
        from homeassistant.util import dt as dt_util

        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("person."):
            return

        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        if not old_state or not new_state:
            return

        old_zone = old_state.state
        new_zone = new_state.state

        # Only process if zone changed
        if old_zone == new_zone:
            return

        person_id = entity_id

        # Check if user is enabled - disabled users don't receive queued notifications
        if not store.is_user_enabled(person_id):
            _LOGGER.debug(
                "Skipping arrival processing for %s (user disabled)",
                person_id,
            )
            return

        _LOGGER.debug(
            "Person %s moved from %s to %s",
            person_id,
            old_zone,
            new_zone,
        )

        # Check if user has queued notifications
        queued = store.get_queue_for_person(person_id)
        if not queued:
            return

        # Group queued notifications by category
        queued_by_category: dict[str, list[dict]] = {}
        for entry in queued:
            cat_id = entry.get("category_id")
            if cat_id not in queued_by_category:
                queued_by_category[cat_id] = []
            queued_by_category[cat_id].append(entry)

        # Check each category's conditions to see which are now met
        subscriptions = store.get_subscriptions_for_person(person_id)
        entries_to_deliver: list[dict] = []
        entries_to_keep_queued: list[dict] = []

        for cat_id, cat_entries in queued_by_category.items():
            sub = subscriptions.get(cat_id, {})

            if sub.get("mode") != MODE_CONDITIONAL:
                # Non-conditional: legacy queued entries are delivered on any
                # zone change. The previous implementation hard-coded
                # ``new_zone == "home"``, which never matched because
                # ``person.state`` holds a zone's friendly_name (e.g. "Home")
                # rather than a slug. Non-conditional subscriptions do not
                # queue under modern logic, so flush any legacy entries on
                # the next zone transition.
                entries_to_deliver.extend(cat_entries)
                continue

            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])
            tree = conditions.get("condition_tree")

            if not rules and not tree:
                # Check legacy zones format
                zones = conditions.get("zones", {})
                if zones:
                    # Legacy: check if arrived at any queue_until_arrival zone.
                    # person.state holds the zone's friendly_name, so resolve
                    # zone_id -> friendly_name before comparing.
                    arrived = False
                    for zone_id, zone_config in zones.items():
                        if zone_config.get("queue_until_arrival"):
                            zone_name = resolve_zone_name(hass, zone_id)
                            if new_zone == zone_name:
                                arrived = True
                                break

                    if arrived:
                        entries_to_deliver.extend(cat_entries)
                    else:
                        entries_to_keep_queued.extend(cat_entries)
                else:
                    # No rules, tree, or zones configured — flush any legacy
                    # queued entries on the next zone transition.
                    entries_to_deliver.extend(cat_entries)
                continue

            # F-2/F-2b: Evaluate conditions (tree or flat rules)
            all_met, rule_results = evaluate_condition_tree(
                hass,
                conditions,
                new_state,
                dt_util.now(),
            )

            if all_met:
                _LOGGER.debug(
                    "All conditions met for %s/%s: %s",
                    person_id,
                    cat_id,
                    [reason for _, reason in rule_results],
                )
                entries_to_deliver.extend(cat_entries)
            else:
                _LOGGER.debug(
                    "Conditions not yet met for %s/%s: %s",
                    person_id,
                    cat_id,
                    [reason for _, reason in rule_results],
                )
                entries_to_keep_queued.extend(cat_entries)

        if not entries_to_deliver:
            _LOGGER.debug(
                "%s arrived at %s but no queued notifications ready for delivery",
                person_id,
                new_zone,
            )
            return

        _LOGGER.info(
            "%s arrived at %s - delivering %d of %d queued notifications",
            person_id,
            new_zone,
            len(entries_to_deliver),
            len(queued),
        )

        # Remove delivered entries from queue
        for entry in entries_to_deliver:
            await store.async_remove_from_queue(entry["queue_id"])

        # Send bundled notification for delivered entries
        success = await async_send_bundled_notification(
            hass, person_id, entries_to_deliver, store
        )

        # If sending failed completely, re-queue entries for retry
        if not success:
            requeued, discarded = await store.async_requeue_entries(entries_to_deliver)
            if requeued:
                _LOGGER.warning(
                    "Re-queued %d notifications for %s after delivery failure",
                    requeued,
                    person_id,
                )
            if discarded:
                _LOGGER.error(
                    "Discarded %d notifications for %s after max retries",
                    discarded,
                    person_id,
                )

    @callback
    def _update_state_listener() -> None:
        """Update the state change listener with current person entities."""
        # Unsubscribe from previous listener if exists
        if state_unsub_container["unsub"]:
            state_unsub_container["unsub"]()
            state_unsub_container["unsub"] = None

        # Get current person entity IDs
        person_ids = [state.entity_id for state in hass.states.async_all("person")]
        tracked_persons.clear()
        tracked_persons.update(person_ids)

        if person_ids:
            state_unsub_container["unsub"] = async_track_state_change_event(
                hass, person_ids, _handle_person_state_change
            )
            _LOGGER.debug(
                "Updated arrival listener for %d persons: %s",
                len(person_ids),
                person_ids,
            )
        else:
            _LOGGER.debug("No person entities to track for arrivals")

    @callback
    def _handle_entity_registry_update(event: Event) -> None:
        """Handle entity registry updates to track new person entities."""
        data: EventEntityRegistryUpdatedData = event.data
        action = data["action"]
        entity_id = data["entity_id"]

        # Only care about person entities
        if not entity_id.startswith("person."):
            return

        if action == "create":
            _LOGGER.info(
                "New person entity detected: %s - updating arrival listener",
                entity_id,
            )
            _update_state_listener()
        elif action == "remove":
            _LOGGER.info(
                "Person entity removed: %s - updating arrival listener",
                entity_id,
            )
            _update_state_listener()
        # Note: "update" action doesn't require re-subscription

    # Set up initial state listener
    _update_state_listener()

    # Set up entity registry listener for dynamic updates
    # Use event bus directly to catch ALL registry changes (then filter in callback)
    unsub_registry = hass.bus.async_listen(
        EVENT_ENTITY_REGISTRY_UPDATED, _handle_entity_registry_update
    )

    @callback
    def _unsubscribe_all() -> None:
        """Unsubscribe from all listeners."""
        if state_unsub_container["unsub"]:
            state_unsub_container["unsub"]()
        unsub_registry()
        _LOGGER.debug("Unsubscribed from all arrival listeners")

    return _unsubscribe_all


async def async_release_queue_for_conditions(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    category_id: str,
) -> None:
    """Release queued notifications when conditions are met.

    Called by ConditionListenerManager when state or time conditions are satisfied.
    Handles both person-based and recipient-based queue entries. Recipients
    (person_id prefixed with "recipient:") use async_send_to_recipient instead
    of the bundled notification path.

    Args:
        hass: Home Assistant instance
        store: Ticker store instance
        person_id: Person entity ID or "recipient:{recipient_id}"
        category_id: Category ID
    """
    # Get queued entries for this person/category
    queued = store.get_queue_for_person(person_id)
    entries_to_deliver = [q for q in queued if q.get("category_id") == category_id]

    if not entries_to_deliver:
        _LOGGER.debug(
            "No queued notifications for %s/%s to release",
            person_id,
            category_id,
        )
        return

    _LOGGER.info(
        "Conditions met for %s/%s - releasing %d queued notifications",
        person_id,
        category_id,
        len(entries_to_deliver),
    )

    # Remove entries from queue
    for entry in entries_to_deliver:
        await store.async_remove_from_queue(entry["queue_id"])

    # Route to recipient or person delivery path
    is_recipient = person_id.startswith("recipient:")
    if is_recipient:
        success = await _async_deliver_recipient_queue(
            hass, store, person_id, category_id, entries_to_deliver,
        )
    else:
        # Send bundled notification for person-based entries
        success = await async_send_bundled_notification(
            hass, person_id, entries_to_deliver, store
        )

    # If sending failed, re-queue entries for retry
    if not success:
        requeued, discarded = await store.async_requeue_entries(entries_to_deliver)
        if requeued:
            _LOGGER.warning(
                "Re-queued %d notifications for %s after delivery failure",
                requeued,
                person_id,
            )
        if discarded:
            _LOGGER.error(
                "Discarded %d notifications for %s after max retries",
                discarded,
                person_id,
            )


async def _async_deliver_recipient_queue(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    category_id: str,
    entries: list[dict],
) -> bool:
    """Deliver queued entries to a recipient via async_send_to_recipient.

    Sends each queued entry individually since recipients use format-aware
    payload transformation that differs per notification.

    Args:
        hass: Home Assistant instance
        store: Ticker store instance
        person_id: "recipient:{recipient_id}" prefixed ID
        category_id: Category ID
        entries: List of queued notification entries

    Returns:
        True if at least one entry was delivered, False if all failed.
    """
    # Extract recipient_id from "recipient:{recipient_id}"
    recipient_id = person_id.split(":", 1)[1] if ":" in person_id else person_id
    recipient = store.get_recipient(recipient_id)

    if not recipient:
        _LOGGER.error(
            "Recipient %s not found, cannot deliver %d queued notifications",
            recipient_id,
            len(entries),
        )
        return False

    any_success = False
    for entry in entries:
        results = await async_send_to_recipient(
            hass,
            store,
            recipient,
            category_id,
            title=entry.get("title", ""),
            message=entry.get("message", ""),
            data=entry.get("data"),
            notification_id=entry.get("notification_id"),
        )
        if results.get("delivered"):
            any_success = True

    _LOGGER.info(
        "Delivered %d queued notifications to recipient %s (%s)",
        len(entries),
        recipient_id,
        "success" if any_success else "all failed",
    )
    return any_success
