"""Discover notify services for persons in Home Assistant."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

# Cache configuration
CACHE_TTL_SECONDS = 300  # 5 minutes

# Module-level cache storage
_discovery_cache: dict[str, dict[str, Any]] = {}
_cache_timestamp: float = 0.0


def _is_cache_valid() -> bool:
    """Check if the cache is still valid based on TTL."""
    global _cache_timestamp
    if not _discovery_cache:
        return False
    return (time.monotonic() - _cache_timestamp) < CACHE_TTL_SECONDS


def invalidate_discovery_cache() -> None:
    """Invalidate the discovery cache.
    
    Call this when devices/entities change and a refresh is needed.
    """
    global _discovery_cache, _cache_timestamp
    _discovery_cache = {}
    _cache_timestamp = 0.0
    _LOGGER.debug("Discovery cache invalidated")


def _dedup_device_services(
    services: list[dict[str, str]],
    notify_services_map: dict[str, Any],
) -> list[dict[str, str]]:
    """Collapse duplicate notify-service entries within a single device bucket.

    Path 1 (entity-registry) and Path 2 (device-registry mobile_app fallback)
    can both emit valid services for the same logical device but with
    different `service` slugs (e.g. after a Companion App update where the
    entity_id-derived slug and the config-entry-derived slug diverge). The
    frontend renders chips by `name`, so users see what looks like two
    duplicate entries — but only one slug actually resolves on HA, so
    dispatched notifications via the stale slug fail silently. (BUG-105)

    Strategy: group entries by lowercased+stripped `name`. For groups with
    more than one entry, prefer the entry whose service slug exists in
    `notify_services_map`. If multiple match (or none match), keep the first
    emitted — Path 1 runs before Path 2, so entity-registry-authoritative
    wins on ties. Drop the others and DEBUG-log what was dropped.

    Args:
        services: List of service dicts for a single device_id.
        notify_services_map: Current `notify` domain services from
            `hass.services.async_services()`. Used to identify the
            live/preferred slug when multiple compete.

    Returns:
        Deduplicated list preserving original order of survivors.
    """
    if len(services) <= 1:
        return services

    groups: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for entry in services:
        key = (entry.get("name") or "").strip().lower()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)

    survivors: list[dict[str, str]] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            survivors.append(group[0])
            continue
        # Prefer first entry whose slug is live in notify_services_map.
        chosen = None
        for entry in group:
            slug = entry.get("service", "").split(".", 1)[-1]
            if slug in notify_services_map:
                chosen = entry
                break
        if chosen is None:
            chosen = group[0]
        dropped = [e for e in group if e is not chosen]
        if dropped:
            _LOGGER.debug(
                "Dedup: kept notify entry %s; dropped duplicates %s "
                "(grouped by display name %r)",
                chosen.get("service"),
                [e.get("service") for e in dropped],
                chosen.get("name"),
            )
        survivors.append(chosen)

    return survivors


def _should_cache_result(result: dict[str, dict[str, Any]]) -> bool:
    """Check whether a discovery result is worth caching.

    Returns False if the result is empty or every person has an empty
    notify_services list — this typically means HA registries were still
    loading when discovery ran, and caching would lock in bad data for
    the full TTL window.
    """
    if not result:
        return False
    return any(
        person.get("notify_services")
        for person in result.values()
    )


async def async_discover_notify_services(
    hass: HomeAssistant,
    use_cache: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    Discover notify services for each person entity.
    
    Traces: person → device_tracker → parent device → notify service
    
    Args:
        hass: Home Assistant instance
        use_cache: If True, return cached results if valid. Default True.
    
    Returns dict keyed by person entity_id with structure:
    {
        "person.john": {
            "person_id": "person.john",
            "name": "John",
            "notify_services": [
                {"service": "notify.mobile_app_johns_iphone", "name": "John's iPhone"}
            ],
            "device_trackers": ["device_tracker.johns_iphone"]
        }
    }
    """
    global _discovery_cache, _cache_timestamp
    
    # Return cached results if valid and caching is enabled
    if use_cache and _is_cache_valid():
        _LOGGER.debug("Returning cached discovery results (%d persons)", len(_discovery_cache))
        return _discovery_cache
    
    _LOGGER.debug("Performing fresh discovery of notify services")
    
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    
    def _get_device_name(device_id: str) -> str | None:
        """Get friendly name for a device (name_by_user if set, else name)."""
        device = device_reg.async_get(device_id)
        if device:
            return device.name_by_user or device.name
        return None
    
    # Build device_id → notify services mapping (with names)
    # Structure: {device_id: [{"service": "...", "name": "...", "device_id": "..."}]}
    device_notify_services: dict[str, list[dict[str, str]]] = {}

    # Hoisted above Path 1 (BUG-105) so both discovery paths share the same
    # stale-service filter. Empty dict during cold-start; in that case both
    # paths skip everything and `_should_cache_result` (BUG-060) refuses to
    # cache the empty result so the next caller retries.
    notify_services_map = hass.services.async_services().get("notify", {})

    for entity in entity_reg.entities.values():
        if entity.domain == "notify" and entity.device_id:
            # Use the service name format: notify.{entity_id without domain}
            service_name = f"notify.{entity.entity_id.split('.', 1)[1]}"
            # BUG-105: drop entries whose slug no longer resolves on HA. Mirrors
            # the existing Path 2 check at the same step. Without this, stale
            # entity-registry slugs (e.g. after Companion App update / device
            # replace) leak through and dispatch silently fails.
            if service_name.split(".", 1)[1] not in notify_services_map:
                continue
            if entity.device_id not in device_notify_services:
                device_notify_services[entity.device_id] = []
            device_name = _get_device_name(entity.device_id) or service_name
            service_entry = {
                "service": service_name,
                "name": device_name,
                "device_id": entity.device_id,
            }
            # Avoid duplicates
            if not any(s["service"] == service_name for s in device_notify_services[entity.device_id]):
                device_notify_services[entity.device_id].append(service_entry)

    # Path 2: Legacy mobile_app services via device registry + config entries
    for entity in entity_reg.entities.values():
        if (
            entity.platform == "mobile_app"
            and entity.domain == "device_tracker"
            and entity.device_id
        ):
            device = device_reg.async_get(entity.device_id)
            if not device:
                continue
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if not entry or entry.domain != "mobile_app":
                    continue
                device_name = entry.data.get("device_name")
                if not device_name:
                    _LOGGER.warning(
                        "mobile_app config entry %s has no device_name, skipping",
                        entry_id,
                    )
                    continue
                slug = slugify(device_name)
                full_service = f"notify.mobile_app_{slug}"
                # Verify service actually exists
                if f"mobile_app_{slug}" not in notify_services_map:
                    continue
                if entity.device_id not in device_notify_services:
                    device_notify_services[entity.device_id] = []
                friendly = _get_device_name(entity.device_id) or full_service
                if not any(
                    s["service"] == full_service
                    for s in device_notify_services[entity.device_id]
                ):
                    device_notify_services[entity.device_id].append({
                        "service": full_service,
                        "name": friendly,
                        "device_id": entity.device_id,
                    })

    # BUG-105: collapse cross-path duplicates within each device bucket so
    # frontend chips and dispatched notifications use the single live slug.
    for _device_id, _entries in list(device_notify_services.items()):
        device_notify_services[_device_id] = _dedup_device_services(
            _entries, notify_services_map
        )

    # Build device_id → device_tracker mapping
    device_trackers: dict[str, list[str]] = {}
    
    for entity in entity_reg.entities.values():
        if entity.domain == "device_tracker" and entity.device_id:
            if entity.device_id not in device_trackers:
                device_trackers[entity.device_id] = []
            device_trackers[entity.device_id].append(entity.entity_id)

    # Get all person entities and their device_trackers
    result: dict[str, dict[str, Any]] = {}
    
    for state in hass.states.async_all("person"):
        person_id = state.entity_id
        person_name = state.attributes.get("friendly_name", person_id)
        person_trackers = state.attributes.get("device_trackers", [])
        # user_id links person to HA user account (for panel identification)
        user_id = state.attributes.get("user_id")
        
        notify_services: list[dict[str, str]] = []
        
        for tracker_id in person_trackers:
            # Find the entity to get device_id
            tracker_entity = entity_reg.async_get(tracker_id)
            if tracker_entity and tracker_entity.device_id:
                device_id = tracker_entity.device_id
                # Get notify services for this device
                if device_id in device_notify_services:
                    for service_entry in device_notify_services[device_id]:
                        # Avoid duplicates by checking service name
                        if not any(s["service"] == service_entry["service"] for s in notify_services):
                            notify_services.append(service_entry)
        
        # Note: A name-matching fallback previously existed here but was removed
        # in BUG-094. It used substring containment (`normalized_name in service_name`)
        # which cross-linked persons whose names were substrings of other names
        # (e.g. "John" matching notify.mobile_app_johnnys_phone). The registry-based
        # paths above (entity platform + legacy mobile_app via config entries,
        # added in BUG-043) are authoritative.

        result[person_id] = {
            "person_id": person_id,
            "name": person_name,
            "user_id": user_id,  # HA user account ID (may be None)
            "notify_services": notify_services,
            "device_trackers": list(person_trackers),
        }
        
        _LOGGER.debug(
            "Discovered for %s: %d notify services, %d trackers",
            person_id,
            len(notify_services),
            len(person_trackers),
        )
    
    # Update cache only if result contains useful data (BUG-060)
    if _should_cache_result(result):
        _discovery_cache = result
        _cache_timestamp = time.monotonic()
        _LOGGER.debug("Discovery cache updated with %d persons", len(result))
    else:
        _LOGGER.warning(
            "Discovery returned no notify services — result not cached, will retry on next call"
        )
    
    return result


async def async_get_notify_services_for_person(
    hass: HomeAssistant, 
    person_id: str,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Get notify services for a specific person.
    
    Args:
        hass: Home Assistant instance
        person_id: The person entity ID (e.g., "person.john")
        use_cache: If True, use cached results if valid. Default True.
    
    Returns:
        List of notify service dicts:
        [{"service": "notify.mobile_app_johns_iphone", "name": "John's iPhone", "device_id": "..."}]
    """
    all_users = await async_discover_notify_services(hass, use_cache=use_cache)
    if person_id in all_users:
        return all_users[person_id].get("notify_services", [])
    return []
