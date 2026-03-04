"""Ticker - Smart notifications for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    EventEntityRegistryUpdatedData,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    STORAGE_KEY_CATEGORIES,
    STORAGE_KEY_SUBSCRIPTIONS,
    STORAGE_KEY_USERS,
    STORAGE_KEY_QUEUE,
    STORAGE_KEY_LOGS,
    PANEL_ADMIN_NAME,
    PANEL_ADMIN_TITLE,
    PANEL_USER_NAME,
    PANEL_USER_TITLE,
    MODE_CONDITIONAL,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
)
from .store import TickerStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
from .services import async_setup_services, async_unload_services, register_schema_updater
from .websocket_api import async_setup_websocket_api
from .discovery import async_get_notify_services_for_person

if TYPE_CHECKING:
    from homeassistant.core import ServiceCall

_LOGGER = logging.getLogger(__name__)

# URL path for serving static files
FRONTEND_URL_BASE = f"/{DOMAIN}_frontend"

# Timeout for notify service calls (in seconds)
NOTIFY_SERVICE_TIMEOUT = 30

# No entity platforms for this integration
PLATFORMS: list[Platform] = []


@dataclass
class TickerData:
    """Runtime data for the Ticker integration."""

    store: TickerStore
    category_listener: Callable[[], None] | None = None
    unsub_arrival: Callable[[], None] | None = None
    update_service_schema: Callable[[], None] | None = None


type TickerConfigEntry = ConfigEntry[TickerData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Ticker integration.
    
    This registers the ticker.notify service which is available
    even before a config entry is loaded.
    """
    # Register services in async_setup per IQS action-setup rule
    await async_setup_services(hass)
    
    # Set up WebSocket API
    await async_setup_websocket_api(hass)
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TickerConfigEntry) -> bool:
    """Set up Ticker from a config entry."""
    _LOGGER.info("Setting up Ticker integration")

    # Initialize storage
    store = TickerStore(hass)
    await store.async_load()

    # Create runtime data
    runtime_data = TickerData(store=store)
    entry.runtime_data = runtime_data

    # Register static path for frontend files
    await _async_register_static_paths(hass)

    # Register custom iconset
    add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/ticker-icons.js")

    # Register panels
    await _async_register_panels(hass)

    # Register schema updater for service descriptions
    register_schema_updater(hass, entry)

    # Register category change listener to update service schema
    @callback
    def on_category_change() -> None:
        """Handle category changes by updating service schema."""
        if runtime_data.update_service_schema:
            runtime_data.update_service_schema()

    store.register_category_listener(on_category_change)
    runtime_data.category_listener = on_category_change

    # Set up person state listener for ON_ARRIVAL mode
    unsub_arrival = await _async_setup_arrival_listener(hass, entry)
    runtime_data.unsub_arrival = unsub_arrival
    
    # Register cleanup via async_on_unload
    entry.async_on_unload(
        lambda: _cleanup_entry(hass, entry)
    )

    _LOGGER.info("Ticker integration setup complete")
    return True


def _cleanup_entry(hass: HomeAssistant, entry: TickerConfigEntry) -> None:
    """Clean up when config entry is unloaded."""
    runtime_data = entry.runtime_data
    
    # Unregister category listener
    if runtime_data.category_listener:
        runtime_data.store.unregister_category_listener(runtime_data.category_listener)
    
    # Unregister arrival listener
    if runtime_data.unsub_arrival:
        runtime_data.unsub_arrival()


async def async_unload_entry(hass: HomeAssistant, entry: TickerConfigEntry) -> bool:
    """Unload a Ticker config entry."""
    _LOGGER.info("Unloading Ticker integration")

    # Unload store (saves any pending debounced data)
    await entry.runtime_data.store.async_unload()

    # Remove panels
    _async_unregister_panels(hass)

    _LOGGER.info("Ticker integration unloaded")
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of a Ticker config entry.

    Cleans up all persistent storage files created by the integration.
    Called by Home Assistant after the config entry has been removed.
    """
    _LOGGER.info("Removing Ticker integration data")

    storage_keys = [
        STORAGE_KEY_CATEGORIES,
        STORAGE_KEY_SUBSCRIPTIONS,
        STORAGE_KEY_USERS,
        STORAGE_KEY_QUEUE,
        STORAGE_KEY_LOGS,
    ]

    for key in storage_keys:
        store = Store(hass, STORAGE_VERSION, key)
        await store.async_remove()
        _LOGGER.debug("Removed storage: %s", key)

    _LOGGER.info(
        "Ticker integration data removed (%d storage files cleaned up)",
        len(storage_keys),
    )


def get_entry(hass: HomeAssistant) -> TickerConfigEntry | None:
    """Get the Ticker config entry if loaded."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        entry = entries[0]
        if hasattr(entry, 'runtime_data') and entry.runtime_data is not None:
            return entry
    return None


async def _async_register_static_paths(hass: HomeAssistant) -> None:
    """Register static paths for frontend files."""
    frontend_path = Path(__file__).parent / "frontend"
    
    # Register the frontend directory as a static path
    await hass.http.async_register_static_paths(
        [
            frontend.StaticPathConfig(
                FRONTEND_URL_BASE,
                str(frontend_path),
                cache_headers=False,  # Disable caching during development
            )
        ]
    )
    _LOGGER.debug("Registered static path %s -> %s", FRONTEND_URL_BASE, frontend_path)


async def _async_register_panels(hass: HomeAssistant) -> None:
    """Register the Ticker panels."""
    # Register admin panel
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ticker-admin-panel",
        frontend_url_path=PANEL_ADMIN_NAME,
        sidebar_title=PANEL_ADMIN_TITLE,
        sidebar_icon="ticker:logo",
        module_url=f"{FRONTEND_URL_BASE}/ticker-admin-panel.js",
        require_admin=True,
        config={"name": PANEL_ADMIN_TITLE},
    )
    _LOGGER.debug("Registered admin panel: %s", PANEL_ADMIN_NAME)

    # Register user panel
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ticker-panel",
        frontend_url_path=PANEL_USER_NAME,
        sidebar_title=PANEL_USER_TITLE,
        sidebar_icon="ticker:logo",
        module_url=f"{FRONTEND_URL_BASE}/ticker-panel.js",
        require_admin=False,
        config={"name": PANEL_USER_TITLE},
    )
    _LOGGER.debug("Registered user panel: %s", PANEL_USER_NAME)


def _async_unregister_panels(hass: HomeAssistant) -> None:
    """Unregister the Ticker panels."""
    frontend.async_remove_panel(hass, PANEL_ADMIN_NAME)
    frontend.async_remove_panel(hass, PANEL_USER_NAME)
    _LOGGER.debug("Unregistered Ticker panels")


async def _async_setup_arrival_listener(
    hass: HomeAssistant, 
    entry: TickerConfigEntry,
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
        """Handle person state changes for queue_until_arrival delivery."""
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
        
        # Check subscriptions to see which zones trigger delivery
        # Get all conditional subscriptions with queue_until_arrival for this person
        subscriptions = store.get_subscriptions_for_person(person_id)
        arrival_zones: set[str] = set()
        
        for cat_id, sub in subscriptions.items():
            if sub.get("mode") == MODE_CONDITIONAL:
                conditions = sub.get("conditions", {})
                zones = conditions.get("zones", {})
                for zone_id, zone_config in zones.items():
                    if zone_config.get("queue_until_arrival"):
                        zone_name = zone_id.replace("zone.", "")
                        arrival_zones.add(zone_name)
        
        # Also include home as default arrival zone for users with no explicit config
        # This ensures backwards compatibility and sensible defaults
        arrival_zones.add("home")
        
        # Check if person arrived at any of their arrival zones
        if new_zone not in arrival_zones:
            _LOGGER.debug(
                "%s arrived at %s but no queue_until_arrival configured for that zone",
                person_id,
                new_zone,
            )
            return
        
        _LOGGER.info(
            "%s arrived at %s - delivering %d queued notifications",
            person_id,
            new_zone,
            len(queued),
        )
        
        # Get and clear queued notifications
        entries = await store.async_get_and_clear_queue_for_person(person_id)
        
        if not entries:
            return
        
        # Send bundled notification
        success = await _async_send_bundled_notification(hass, person_id, entries, store)
        
        # If sending failed completely, re-queue entries for retry
        if not success:
            requeued, discarded = await store.async_requeue_entries(entries)
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
    store: TickerStore,
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
    
    return any_success
