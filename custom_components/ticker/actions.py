"""Notification action listener and execution for Ticker integration (F-5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers import entity_registry as er

from .const import (
    ACTION_ID_PREFIX,
    ACTION_TYPE_SCRIPT,
    ACTION_TYPE_SNOOZE,
    ACTION_TYPE_DISMISS,
)

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"


async def async_setup_action_listener(
    hass: HomeAssistant, store: "TickerStore"
) -> Callable[[], None]:
    """Register event listener for mobile_app notification actions.

    Returns an unsub callable to remove the listener.
    """

    async def _handle(event: Event) -> None:
        await _async_handle_action_event(hass, store, event)

    unsub = hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, _handle)
    _LOGGER.info("Ticker action listener registered")
    return unsub


def build_action_payload(
    category: dict[str, Any], notification_id: str
) -> list[dict[str, str]]:
    """Build data.actions list for a notification from a category's action_set.

    Action ID format: TICKER_{category_id}_{action_index}_{notification_id_short}
    """
    action_set = category.get("action_set")
    if not action_set:
        return []

    actions = action_set.get("actions", [])
    if not actions:
        return []

    category_id = category["id"]
    nid_short = notification_id[:8]
    result: list[dict[str, str]] = []

    for action_def in actions:
        idx = action_def.get("index", 0)
        action_id = f"{ACTION_ID_PREFIX}{category_id}_{idx}_{nid_short}"
        result.append({
            "action": action_id,
            "title": action_def.get("title", "Action"),
        })

    return result


def _parse_action_id(action_id: str) -> tuple[str, int, str] | None:
    """Parse a Ticker action ID into (category_id, action_index, nid_short).

    Parses right-to-left since category_id can contain underscores.
    Returns None if the format is invalid.
    """
    if not action_id.startswith(ACTION_ID_PREFIX):
        return None

    remainder = action_id[len(ACTION_ID_PREFIX):]
    parts = remainder.rsplit("_", 2)

    if len(parts) < 3:
        return None

    category_id = parts[0]
    try:
        action_index = int(parts[1])
    except ValueError:
        return None
    nid_short = parts[2]

    return category_id, action_index, nid_short


def resolve_person_from_device(hass: HomeAssistant, device_id: str) -> str | None:
    """Resolve a device_id to a person entity ID.

    Traces: device_id -> device_tracker entities -> person entity with matching tracker.
    """
    if not device_id:
        return None

    entity_reg = er.async_get(hass)

    # Find device_tracker entities belonging to this device
    tracker_ids: list[str] = []
    for entity in entity_reg.entities.values():
        if entity.domain == "device_tracker" and entity.device_id == device_id:
            tracker_ids.append(entity.entity_id)

    if not tracker_ids:
        return None

    # Find person entity that has one of these trackers
    for state in hass.states.async_all("person"):
        person_trackers = state.attributes.get("device_trackers", [])
        for tracker_id in tracker_ids:
            if tracker_id in person_trackers:
                return state.entity_id

    return None


def _resolve_person_from_logs(store: "TickerStore", nid_short: str) -> str | None:
    """Fallback: resolve person_id from log entries matching a notification_id prefix."""
    for log in reversed(store._logs):
        nid = log.get("notification_id", "")
        if nid and nid[:8] == nid_short and log.get("outcome") == "sent":
            return log.get("person_id")
    return None


async def _async_handle_action_event(
    hass: HomeAssistant, store: "TickerStore", event: Event
) -> None:
    """Handle a mobile_app_notification_action event."""
    action_id = event.data.get("action", "")

    if not action_id.startswith(ACTION_ID_PREFIX):
        return  # Not a Ticker action

    parsed = _parse_action_id(action_id)
    if not parsed:
        _LOGGER.warning("Could not parse Ticker action ID: %s", action_id)
        return

    category_id, action_index, nid_short = parsed

    # Resolve person: try device_id first, fall back to log lookup
    device_id = event.data.get("device_id")
    person_id = resolve_person_from_device(hass, device_id) if device_id else None
    if not person_id:
        person_id = _resolve_person_from_logs(store, nid_short)
    person_label = person_id or "unknown"

    _LOGGER.info(
        "Action event: %s (category=%s, index=%d, person=%s)",
        action_id, category_id, action_index, person_label,
    )

    # Look up the action definition from the category
    category = store.get_category(category_id)
    if not category:
        _LOGGER.warning("Action for unknown category: %s", category_id)
        return

    action_set = category.get("action_set", {})
    actions = action_set.get("actions", [])

    action_def = None
    for a in actions:
        if a.get("index") == action_index:
            action_def = a
            break

    if not action_def:
        _LOGGER.warning(
            "Action index %d not found in category %s", action_index, category_id
        )
        return

    action_type = action_def.get("type")
    action_title = action_def.get("title", "Unknown")
    action_taken = {"title": action_title, "type": action_type}

    # Execute based on type
    if action_type == ACTION_TYPE_SCRIPT:
        script_entity = action_def.get("script_entity")
        if script_entity:
            try:
                await hass.services.async_call(
                    "script", "turn_on",
                    {"entity_id": script_entity},
                    blocking=False,
                )
                _LOGGER.info("Executed script %s for %s", script_entity, person_label)
                action_taken["script_entity"] = script_entity
            except Exception as err:
                _LOGGER.error("Failed to execute script %s: %s", script_entity, err)

    elif action_type == ACTION_TYPE_SNOOZE:
        snooze_minutes = action_def.get("snooze_minutes", 30)
        if person_id:
            await store.async_set_snooze(person_id, category_id, snooze_minutes)
            action_taken["snooze_minutes"] = snooze_minutes
        else:
            _LOGGER.warning("Cannot snooze: person unresolved for device %s", device_id)

    elif action_type == ACTION_TYPE_DISMISS:
        pass  # Dismiss is a no-op beyond logging

    else:
        _LOGGER.warning("Unknown action type: %s", action_type)

    # Update log entries with action_taken
    if person_id:
        await store.async_update_log_action_taken(
            nid_short, person_id, action_taken
        )
