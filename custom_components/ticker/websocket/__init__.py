"""WebSocket API for Ticker integration."""

from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .categories import (
    ws_get_categories,
    ws_create_category,
    ws_update_category,
    ws_delete_category,
)
from .users import (
    ws_get_users,
    ws_set_user_enabled,
)
from .subscriptions import (
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
from .logs_delete import (
    ws_remove_log_entry,
    ws_remove_log_group,
    ws_clear_logs_for_person,
)
from .operations import (
    ws_test_notification,
    ws_migrate_scan,
    ws_migrate_convert,
    ws_migrate_delete,
)
from .actions import (
    ws_set_action_set,
    ws_get_snoozes,
    ws_clear_snooze,
)
from .action_sets import (
    ws_action_sets_list,
    ws_action_set_create,
    ws_action_set_update,
    ws_action_set_delete,
)
from .recipients import (
    ws_get_recipients,
    ws_create_recipient,
    ws_update_recipient,
    ws_delete_recipient,
    ws_set_recipient_subscription,
)
from .recipient_helpers import (
    ws_get_available_notify_services,
    ws_get_tts_options,
    ws_test_recipient,
)
from .automations import (
    ws_automations_scan,
    ws_automations_update,
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

    # Log deletion commands (F-32)
    websocket_api.async_register_command(hass, ws_remove_log_entry)
    websocket_api.async_register_command(hass, ws_remove_log_group)
    websocket_api.async_register_command(hass, ws_clear_logs_for_person)

    # Test and migration commands
    websocket_api.async_register_command(hass, ws_test_notification)
    websocket_api.async_register_command(hass, ws_migrate_scan)
    websocket_api.async_register_command(hass, ws_migrate_convert)
    websocket_api.async_register_command(hass, ws_migrate_delete)

    # Action and snooze commands (F-5)
    websocket_api.async_register_command(hass, ws_set_action_set)
    websocket_api.async_register_command(hass, ws_get_snoozes)
    websocket_api.async_register_command(hass, ws_clear_snooze)

    # Action Sets Library commands (F-5b)
    websocket_api.async_register_command(hass, ws_action_sets_list)
    websocket_api.async_register_command(hass, ws_action_set_create)
    websocket_api.async_register_command(hass, ws_action_set_update)
    websocket_api.async_register_command(hass, ws_action_set_delete)

    # Recipient commands (F-18)
    websocket_api.async_register_command(hass, ws_get_recipients)
    websocket_api.async_register_command(hass, ws_create_recipient)
    websocket_api.async_register_command(hass, ws_update_recipient)
    websocket_api.async_register_command(hass, ws_delete_recipient)
    websocket_api.async_register_command(hass, ws_set_recipient_subscription)
    websocket_api.async_register_command(hass, ws_get_available_notify_services)
    websocket_api.async_register_command(hass, ws_get_tts_options)
    websocket_api.async_register_command(hass, ws_test_recipient)

    # Automations Manager commands (F-3)
    websocket_api.async_register_command(hass, ws_automations_scan)
    websocket_api.async_register_command(hass, ws_automations_update)

    _LOGGER.info("Ticker WebSocket API registered")
