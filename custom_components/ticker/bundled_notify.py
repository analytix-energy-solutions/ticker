"""Bundled notification sender for Ticker integration.

Handles sending bundled notifications when queued notifications are
released (e.g., on zone arrival or when conditions are met).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .const import (
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
    LOG_OUTCOME_SENT,
)
from .discovery import async_get_notify_services_for_person

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Timeout for notify service calls (in seconds)
NOTIFY_SERVICE_TIMEOUT = 30


async def async_send_bundled_notification(
    hass: HomeAssistant,
    person_id: str,
    entries: list[dict[str, Any]],
    store: "TickerStore",
) -> bool:
    """Send a bundled notification summarizing queued notifications.

    Respects device preferences:
    - Uses global device preference as base
    - Unions device overrides from all categories in the bundle

    Args:
        hass: Home Assistant instance
        person_id: The person entity ID
        entries: List of queued notification entries to bundle
        store: TickerStore instance for device preferences and logging

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
        by_category: dict[str, list[dict[str, Any]]] = {}
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

        service_data: dict[str, Any] = {
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
        person_name = (
            person_state.attributes.get("friendly_name", person_id)
            if person_state
            else person_id
        )
        services_str = ", ".join(final_devices)
        for entry in entries:
            entry_data = entry.get("data") or {}
            entry_image_url = entry_data.get("image")
            await store.async_add_log(
                category_id=entry["category_id"],
                person_id=person_id,
                person_name=person_name,
                title=entry["title"],
                message=entry["message"],
                outcome=LOG_OUTCOME_SENT,
                notify_service=services_str,
                reason="Delivered on arrival (bundled)",
                image_url=entry_image_url,
            )

    return any_success
