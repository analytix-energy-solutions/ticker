"""WebSocket API for Ticker integration."""

from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .category_user import (
    ws_get_categories,
    ws_create_category,
    ws_update_category,
    ws_delete_category,
    ws_get_users,
    ws_set_user_enabled,
    ws_get_subscriptions,
    ws_set_subscription,
)
from .queue_log import (
    ws_get_zones,
    ws_get_devices,
    ws_set_device_preference,
    ws_get_current_person,
    ws_get_queue,
    ws_clear_queue,
    ws_remove_queue_entry,
    ws_get_logs,
    ws_get_log_stats,
    ws_clear_logs,
)
from .operations import (
    ws_test_notification,
    ws_migrate_scan,
    ws_migrate_convert,
    ws_migrate_delete,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Set up the Ticker WebSocket API."""
    # Category commands
    websocket_api.async_register_command(hass, ws_get_categories)
    websocket_api.async_register_command(hass, ws_create_category)
    websocket_api.async_register_command(hass, ws_update_category)
    websocket_api.async_register_command(hass, ws_delete_category)

    # User commands
    websocket_api.async_register_command(hass, ws_get_users)
    websocket_api.async_register_command(hass, ws_set_user_enabled)

    # Subscription commands
    websocket_api.async_register_command(hass, ws_get_subscriptions)
    websocket_api.async_register_command(hass, ws_set_subscription)

    # Zone and device commands
    websocket_api.async_register_command(hass, ws_get_zones)
    websocket_api.async_register_command(hass, ws_get_current_person)
    websocket_api.async_register_command(hass, ws_get_devices)
    websocket_api.async_register_command(hass, ws_set_device_preference)

    # Queue commands
    websocket_api.async_register_command(hass, ws_get_queue)
    websocket_api.async_register_command(hass, ws_clear_queue)
    websocket_api.async_register_command(hass, ws_remove_queue_entry)

    # Log commands
    websocket_api.async_register_command(hass, ws_get_logs)
    websocket_api.async_register_command(hass, ws_get_log_stats)
    websocket_api.async_register_command(hass, ws_clear_logs)

    # Test and migration commands
    websocket_api.async_register_command(hass, ws_test_notification)
    websocket_api.async_register_command(hass, ws_migrate_scan)
    websocket_api.async_register_command(hass, ws_migrate_convert)
    websocket_api.async_register_command(hass, ws_migrate_delete)

    _LOGGER.info("Ticker WebSocket API registered")
