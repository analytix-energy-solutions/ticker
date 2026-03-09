"""Arrival listener for Ticker integration.

Handles person state changes to deliver queued notifications when users
arrive at configured zones.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    EventEntityRegistryUpdatedData,
)

from .const import (
    MODE_CONDITIONAL,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
    RULE_TYPE_ZONE,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_FAILED,
)
from .discovery import async_get_notify_services_for_person
from .conditions import evaluate_rules, get_queue_triggers

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Timeout for notify service calls (in seconds)
NOTIFY_SERVICE_TIMEOUT = 30


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
                # Non-conditional: deliver on any zone change (legacy behavior)
                if new_zone == "home":
                    entries_to_deliver.extend(cat_entries)
                else:
                    entries_to_keep_queued.extend(cat_entries)
                continue

            conditions = sub.get("conditions", {})
            rules = conditions.get("rules", [])

            if not rules:
                # Check legacy zones format
                zones = conditions.get("zones", {})
                if zones:
                    # Legacy: check if arrived at any queue_until_arrival zone
                    arrived = False
                    for zone_id, zone_config in zones.items():
                        if zone_config.get("queue_until_arrival"):
                            zone_name = zone_id.replace("zone.", "")
                            if new_zone == zone_name:
                                arrived = True
                                break

                    if arrived:
                        entries_to_deliver.extend(cat_entries)
                    else:
                        entries_to_keep_queued.extend(cat_entries)
                else:
                    # No rules or zones - deliver on home arrival
                    if new_zone == "home":
                        entries_to_deliver.extend(cat_entries)
                    else:
                        entries_to_keep_queued.extend(cat_entries)
                continue

            # F-2: Evaluate all rules with AND logic
            all_met, reasons = evaluate_rules(
                hass,
                rules,
                new_state,
                dt_util.now(),
            )

            if all_met:
                _LOGGER.debug(
                    "All conditions met for %s/%s: %s",
                    person_id,
                    cat_id,
                    reasons,
                )
                entries_to_deliver.extend(cat_entries)
            else:
                _LOGGER.debug(
                    "Conditions not yet met for %s/%s: %s",
                    person_id,
                    cat_id,
                    reasons,
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
        success = await _async_send_bundled_notification(
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


async def _async_send_bundled_notification(
    hass: HomeAssistant,
    person_id: str,
    entries: list[dict],
    store: "TickerStore",
) -> bool:
    """Send a bundled notification summarizing queued notifications.

    Respects device preferences:
    - Uses global device preference as base
    - Unions device overrides from all categories in the bundle

    Returns:
        True if at least one service succeeded, False if all failed.
    """
    if not entries:
        return True  # Nothing to send is considered success

    # Get notify services for person (list of dicts with service/name/device_id)
    all_services = await async_get_notify_services_for_person(hass, person_id)

    if not all_services:
        _LOGGER.warning(
            "No notify services found for %s, cannot send bundled notification",
            person_id,
        )
        return False  # No services = failure, should retry

    # Build lookup and get all service IDs
    service_lookup = {svc["service"]: svc for svc in all_services}
    all_service_ids = set(service_lookup.keys())

    # Get user's global device preference
    device_pref = store.get_device_preference(person_id)
    pref_mode = device_pref.get("mode", DEVICE_MODE_ALL)
    pref_devices = set(device_pref.get("devices", []))

    # Determine base device set from global preference
    if pref_mode == DEVICE_MODE_ALL:
        base_devices = all_service_ids
    else:  # DEVICE_MODE_SELECTED
        base_devices = pref_devices & all_service_ids
        if not base_devices:
            _LOGGER.warning(
                "User %s has 'selected' device mode but no valid devices, "
                "falling back to all devices",
                person_id,
            )
            base_devices = all_service_ids

    # Collect all category IDs from queued entries
    category_ids = {entry["category_id"] for entry in entries}

    # Union all device overrides from categories in the bundle
    final_devices = set(base_devices)
    for category_id in category_ids:
        device_override = store.get_device_override(person_id, category_id)
        if device_override and device_override.get("enabled"):
            override_devices = set(device_override.get("devices", []))
            valid_override = override_devices & all_service_ids
            if valid_override:
                final_devices |= valid_override
                _LOGGER.debug(
                    "Bundled notification: adding override devices for category %s: %s",
                    category_id,
                    valid_override,
                )

    if not final_devices:
        _LOGGER.warning(
            "No target devices for bundled notification to %s",
            person_id,
        )
        return False

    _LOGGER.debug(
        "Sending bundled notification to %s via %d device(s): %s",
        person_id,
        len(final_devices),
        final_devices,
    )

    # Build summary
    count = len(entries)

    if count == 1:
        # Single notification - just send it directly
        entry = entries[0]
        title = entry["title"]
        message = entry["message"]
    else:
        # Multiple notifications - build summary
        # Group by category
        by_category: dict[str, list] = {}
        for entry in entries:
            cat_id = entry["category_id"]
            cat = store.get_category(cat_id)
            cat_name = cat["name"] if cat else cat_id
            if cat_name not in by_category:
                by_category[cat_name] = []
            by_category[cat_name].append(entry)

        title = f"You have {count} notifications"

        # Build message with category breakdown
        summary_parts = []
        for cat_name, cat_entries in by_category.items():
            if len(cat_entries) == 1:
                summary_parts.append(f"{cat_name}: {cat_entries[0]['title']}")
            else:
                summary_parts.append(f"{cat_name} ({len(cat_entries)})")

        message = "\n".join(summary_parts)

    # Send to all target devices, track success
    any_success = False

    for service_id in final_devices:
        service_info = service_lookup.get(service_id, {})
        service_name_display = service_info.get("name", service_id)
        domain, service_name = service_id.split(".", 1)

        service_data = {
            "title": title,
            "message": message,
            "data": {
                "url": "/ticker#history",
                "clickAction": "/ticker#history",
            },
        }

        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    domain,
                    service_name,
                    service_data,
                    blocking=True,
                ),
                timeout=NOTIFY_SERVICE_TIMEOUT,
            )
            _LOGGER.info(
                "Sent bundled notification (%d items) to %s via %s (%s)",
                count,
                person_id,
                service_id,
                service_name_display,
            )
            any_success = True
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timeout sending bundled notification to %s via %s (exceeded %ds)",
                person_id,
                service_id,
                NOTIFY_SERVICE_TIMEOUT,
            )
        except Exception as err:
            _LOGGER.error(
                "Failed to send bundled notification to %s via %s: %s",
                person_id,
                service_id,
                err,
            )

    # Log delivery for each entry in the bundle (BUG-029 fix)
    if any_success:
        person_state = hass.states.get(person_id)
        person_name = person_state.attributes.get("friendly_name", person_id) if person_state else person_id
        services_str = ", ".join(final_devices)
        for entry in entries:
            await store.async_add_log(
                category_id=entry["category_id"],
                person_id=person_id,
                person_name=person_name,
                title=entry["title"],
                message=entry["message"],
                outcome=LOG_OUTCOME_SENT,
                notify_service=services_str,
                reason="Delivered on arrival (bundled)",
            )

    return any_success


async def async_release_queue_for_conditions(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    category_id: str,
) -> None:
    """Release queued notifications when conditions are met.

    Called by ConditionListenerManager when state or time conditions are satisfied.

    Args:
        hass: Home Assistant instance
        store: Ticker store instance
        person_id: Person entity ID
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

    # Send bundled notification
    success = await _async_send_bundled_notification(
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
