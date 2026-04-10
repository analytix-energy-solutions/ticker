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


def resolve_action_set(
    store: Any,
    category: dict[str, Any] | None,
    per_call_action_set_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve the action set to use for a notification.

    Resolution priority (highest to lowest):
    1. per_call_action_set_id -- look up from library
    2. category.action_set_id -- category's library reference
    3. category.action_set -- legacy inline (pre-migration fallback)
    4. None -- no actions

    Returns:
        Tuple of (action_set_dict, action_set_id) or (None, None).
    """
    # Priority 1: per-call override
    if per_call_action_set_id:
        action_set = store.get_action_set(per_call_action_set_id)
        if action_set:
            return action_set, per_call_action_set_id
        _LOGGER.warning(
            "Action set '%s' not found in library",
            per_call_action_set_id,
        )

    # Priority 2: category's library reference
    if category:
        cat_action_set_id = category.get("action_set_id")
        if cat_action_set_id:
            action_set = store.get_action_set(cat_action_set_id)
            if action_set:
                return action_set, cat_action_set_id
            _LOGGER.warning(
                "Category action_set_id '%s' not found in library",
                cat_action_set_id,
            )

        # Priority 3: legacy inline fallback
        inline = category.get("action_set")
        if inline:
            return inline, category.get("id", "unknown")

    return None, None


def build_action_payload(
    action_set: dict[str, Any],
    action_set_id: str,
    notification_id: str,
) -> list[dict[str, str]]:
    """Build data.actions list for a notification from a resolved action set.

    Action ID format: TICKER_{action_set_id}_{action_index}_{notification_id_short}
    """
    actions = action_set.get("actions", [])
    if not actions:
        return []

    nid_short = notification_id[:8]
    result: list[dict[str, str]] = []

    for action_def in actions:
        idx = action_def.get("index", 0)
        action_id = f"{ACTION_ID_PREFIX}{action_set_id}_{idx}_{nid_short}"
        result.append({
            "action": action_id,
            "title": action_def.get("title", "Action"),
        })

    return result


def _parse_action_id(action_id: str) -> tuple[str, int, str] | None:
    """Parse a Ticker action ID into (segment, action_index, nid_short).

    The segment is an action_set_id (post-migration) or a legacy category_id.
    Parses right-to-left since the segment can contain underscores.
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

    segment, action_index, nid_short = parsed

    # Resolve person: try device_id first, fall back to log lookup
    device_id = event.data.get("device_id")
    person_id = resolve_person_from_device(hass, device_id) if device_id else None
    if not person_id:
        person_id = _resolve_person_from_logs(store, nid_short)
    person_label = person_id or "unknown"

    _LOGGER.info(
        "Action event: %s (segment=%s, index=%d, person=%s)",
        action_id, segment, action_index, person_label,
    )

    # Resolve the action set and the actual category_id.
    # Post-migration, segment is an action_set_id; pre-migration it's a category_id.
    resolved_cat_id: str | None = None
    action_set_dict = store.get_action_set(segment)
    if action_set_dict:
        # segment is a library action_set_id — resolve real category.
        # When the same action set is shared across multiple categories, we
        # must look up which category this specific notification belonged to
        # via the log (BUG-090). Fall back to the first user only if the log
        # lookup fails (e.g. bundled notifications or expired log entries).
        if person_id:
            resolved_cat_id = store.find_log_category_by_nid(nid_short, person_id)
        if not resolved_cat_id:
            using = store.is_action_set_in_use(segment)
            if using:
                resolved_cat_id = using[0]
                _LOGGER.debug(
                    "BUG-090 fallback: log lookup for nid=%s person=%s failed; "
                    "using first category %s from action set %s users",
                    nid_short, person_label, resolved_cat_id, segment,
                )
    else:
        # segment might be a legacy category_id
        category = store.get_category(segment)
        if not category:
            _LOGGER.warning(
                "Action segment '%s' not found as action set or category",
                segment,
            )
            return
        resolved_cat_id = segment
        # Try category's library reference
        cat_ref = category.get("action_set_id")
        if cat_ref:
            action_set_dict = store.get_action_set(cat_ref)
        # Fallback to legacy inline
        if not action_set_dict:
            action_set_dict = category.get("action_set", {})

    actions = action_set_dict.get("actions", []) if action_set_dict else []

    action_def = None
    for a in actions:
        if a.get("index") == action_index:
            action_def = a
            break

    if not action_def:
        _LOGGER.warning(
            "Action index %d not found in segment %s", action_index, segment
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
            except Exception as err:  # noqa: BLE001 — script failure must not abort delivery
                _LOGGER.error("Failed to execute script %s: %s", script_entity, err)

    elif action_type == ACTION_TYPE_SNOOZE:
        snooze_minutes = action_def.get("snooze_minutes", 30)
        if person_id:
            if resolved_cat_id:
                await store.async_set_snooze(person_id, resolved_cat_id, snooze_minutes)
            else:
                _LOGGER.warning("Cannot snooze: category unresolved for segment %s", segment)
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
