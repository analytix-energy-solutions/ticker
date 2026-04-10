"""Ticker - Smart notifications for Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    VERSION,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DEVICE_IDENTIFIER,
    STORAGE_VERSION,
    STORAGE_KEY_CATEGORIES,
    STORAGE_KEY_SUBSCRIPTIONS,
    STORAGE_KEY_USERS,
    STORAGE_KEY_QUEUE,
    STORAGE_KEY_LOGS,
    STORAGE_KEY_SNOOZES,
    STORAGE_KEY_RECIPIENTS,
    STORAGE_KEY_ACTION_SETS,
    EXPIRED_QUEUE_SWEEP_INTERVAL,
    PANEL_ADMIN_NAME,
    PANEL_ADMIN_TITLE,
    PANEL_USER_NAME,
    PANEL_USER_TITLE,
)
from .store import TickerStore
from .actions import async_setup_action_listener
from .arrival import async_setup_arrival_listener, async_release_queue_for_conditions
from .auto_clear import AutoClearRegistry
from .condition_listeners import ConditionListenerManager
from .discovery import async_discover_notify_services, invalidate_discovery_cache
from .services import async_setup_services, register_schema_updater
from .websocket import async_setup_websocket_api

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

# URL path for serving static files
FRONTEND_URL_BASE = f"/{DOMAIN}_frontend"

# Entity platforms for this integration
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NOTIFY]


@dataclass
class TickerData:
    """Runtime data for the Ticker integration."""

    store: TickerStore
    category_listener: Callable[[], None] | None = None
    action_set_listener: Callable[[], None] | None = None
    subscription_listener: Callable[[], None] | None = None
    unsub_arrival: Callable[[], None] | None = None
    unsub_actions: Callable[[], None] | None = None
    unsub_expired_sweep: Callable[[], None] | None = None
    update_service_schema: Callable[[], None] | None = None
    condition_listener_manager: ConditionListenerManager | None = None
    # F-30: auto-clear trigger registry (in-memory, does not survive restart).
    auto_clear: AutoClearRegistry | None = None


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

    # Invalidate discovery cache to ensure fresh data after reload (BUG-036)
    invalidate_discovery_cache()

    # Initialize storage
    store = TickerStore(hass)
    await store.async_load()

    # Pre-warm discovery cache once HA signals startup is complete (BUG-060)
    async def _prewarm_discovery(hass_ref: HomeAssistant) -> None:
        """Pre-warm discovery cache after HA startup."""
        await async_discover_notify_services(hass_ref, use_cache=False)

    async_at_start(hass, _prewarm_discovery)

    # Create runtime data
    runtime_data = TickerData(store=store)
    # F-30: instantiate the auto-clear registry before services fire so the
    # ticker.notify handler can always resolve it via runtime_data.
    runtime_data.auto_clear = AutoClearRegistry(hass)
    entry.runtime_data = runtime_data

    # F-31: Register Ticker as a virtual device so it shows up in HA device
    # pickers and is discoverable to community blueprints. Phase 1 is
    # visibility only — device actions for ticker.notify are deferred.
    # async_get_or_create is idempotent on reload; HA prunes devices linked
    # to removed config entries automatically, so no explicit cleanup.
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        name=DEVICE_NAME,
        entry_type=DeviceEntryType.SERVICE,
    )

    # Initialize hass.data for sensor storage
    hass.data.setdefault(DOMAIN, {})

    # Forward setup to entity platforms (sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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

    # Refresh service schema when action sets change (F-5b)
    store.register_action_set_listener(on_category_change)
    runtime_data.action_set_listener = on_category_change

    # Set up person state listener for ON_ARRIVAL mode
    unsub_arrival = await async_setup_arrival_listener(hass, entry)
    runtime_data.unsub_arrival = unsub_arrival

    # Set up condition listener manager for state/time-based queue release
    async def on_conditions_met(person_id: str, category_id: str) -> None:
        """Handle conditions being met by releasing queued notifications."""
        await async_release_queue_for_conditions(hass, store, person_id, category_id)

    condition_manager = ConditionListenerManager(hass, store, on_conditions_met)
    await condition_manager.async_setup()
    runtime_data.condition_listener_manager = condition_manager

    # Refresh condition listeners whenever subscriptions change so newly
    # created conditional subscriptions receive their state/time listeners
    # without requiring an HA restart (BUG-086). Register AFTER async_setup
    # so the initial load is not duplicated.
    store.register_subscription_listener(condition_manager.schedule_refresh)
    runtime_data.subscription_listener = condition_manager.schedule_refresh

    # Set up notification action listener (F-5)
    unsub_actions = await async_setup_action_listener(hass, store)
    runtime_data.unsub_actions = unsub_actions

    # F-25: Periodic sweep of expired queue entries so they surface in logs
    # even when no new notification traffic triggers lazy cleanup.
    async def _sweep_expired(_now) -> None:
        """Run expired queue cleanup on a fixed interval."""
        try:
            await store._async_cleanup_expired_queue()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Expired queue sweep failed")

    runtime_data.unsub_expired_sweep = async_track_time_interval(
        hass,
        _sweep_expired,
        timedelta(seconds=EXPIRED_QUEUE_SWEEP_INTERVAL),
    )

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

    # Unregister action set listener
    if runtime_data.action_set_listener:
        runtime_data.store.unregister_action_set_listener(runtime_data.action_set_listener)

    # Unregister subscription listener (BUG-086)
    if runtime_data.subscription_listener:
        runtime_data.store.unregister_subscription_listener(
            runtime_data.subscription_listener
        )

    # Unregister arrival listener
    if runtime_data.unsub_arrival:
        runtime_data.unsub_arrival()

    # Unregister action listener
    if runtime_data.unsub_actions:
        runtime_data.unsub_actions()

    # F-25: Cancel expired queue sweep interval
    if runtime_data.unsub_expired_sweep:
        runtime_data.unsub_expired_sweep()
        runtime_data.unsub_expired_sweep = None

    # F-30: tear down any still-pending auto-clear listeners.
    if runtime_data.auto_clear is not None:
        runtime_data.auto_clear.unregister_all()

    # Note: condition_listener_manager cleanup is handled by
    # async_unload() in async_unload_entry — no sync cleanup here.


async def async_unload_entry(hass: HomeAssistant, entry: TickerConfigEntry) -> bool:
    """Unload a Ticker config entry."""
    _LOGGER.info("Unloading Ticker integration")

    # Tear down condition listeners before unloading platforms (BUG-068)
    if entry.runtime_data.condition_listener_manager:
        await entry.runtime_data.condition_listener_manager.async_unload()

    # Unload entity platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Unload store (saves any pending debounced data)
    await entry.runtime_data.store.async_unload()

    # Remove panels
    _async_unregister_panels(hass)

    # Clean up hass.data
    if DOMAIN in hass.data:
        hass.data.pop(DOMAIN)

    _LOGGER.info("Ticker integration unloaded")
    return unload_ok


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
        STORAGE_KEY_SNOOZES,
        STORAGE_KEY_RECIPIENTS,
        STORAGE_KEY_ACTION_SETS,
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
        module_url=f"{FRONTEND_URL_BASE}/ticker-admin-panel.js?v={VERSION}",
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
        module_url=f"{FRONTEND_URL_BASE}/ticker-panel.js?v={VERSION}",
        require_admin=False,
        config={"name": PANEL_USER_TITLE},
    )
    _LOGGER.debug("Registered user panel: %s", PANEL_USER_NAME)


def _async_unregister_panels(hass: HomeAssistant) -> None:
    """Unregister the Ticker panels."""
    frontend.async_remove_panel(hass, PANEL_ADMIN_NAME)
    frontend.async_remove_panel(hass, PANEL_USER_NAME)
    _LOGGER.debug("Unregistered Ticker panels")
