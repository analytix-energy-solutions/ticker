"""Service handlers for Ticker integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema

from .const import (
    DOMAIN,
    SERVICE_NOTIFY,
    ATTR_CATEGORY,
    ATTR_TITLE,
    ATTR_MESSAGE,
    ATTR_EXPIRATION,
    ATTR_DATA,
    DEFAULT_EXPIRATION_HOURS,
    MAX_EXPIRATION_HOURS,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SKIPPED,
    LOG_OUTCOME_FAILED,
    CATEGORY_DEFAULT_NAME,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
)
from .discovery import async_get_notify_services_for_person

if TYPE_CHECKING:
    from . import TickerConfigEntry
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Timeout for notify service calls (in seconds)
NOTIFY_SERVICE_TIMEOUT = 30


def _build_service_schema() -> vol.Schema:
    """Build basic service schema (categories validated at runtime)."""
    return vol.Schema(
        {
            vol.Required(ATTR_CATEGORY): cv.string,
            vol.Required(ATTR_TITLE): cv.string,
            vol.Required(ATTR_MESSAGE): cv.string,
            vol.Optional(ATTR_EXPIRATION, default=DEFAULT_EXPIRATION_HOURS): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_EXPIRATION_HOURS)
            ),
            vol.Optional(ATTR_DATA, default={}): dict,
        }
    )


def _build_service_description(store: TickerStore | None) -> dict[str, Any]:
    """Build service description with current categories for UI."""
    if store:
        categories = store.get_categories()
        category_options = [cat["name"] for cat in categories.values()]
    else:
        category_options = [CATEGORY_DEFAULT_NAME]
    
    return {
        "name": "Send notification",
        "description": "Send a notification through Ticker to subscribed users",
        "fields": {
            ATTR_CATEGORY: {
                "name": "Category",
                "description": "The notification category",
                "required": True,
                "example": CATEGORY_DEFAULT_NAME,
                "selector": {
                    "select": {
                        "options": category_options,
                        "mode": "dropdown",
                    }
                },
            },
            ATTR_TITLE: {
                "name": "Title",
                "description": "The notification title",
                "required": True,
                "example": "Motion Detected",
                "selector": {"text": {}},
            },
            ATTR_MESSAGE: {
                "name": "Message",
                "description": "The notification message body",
                "required": True,
                "example": "Motion detected at front door",
                "selector": {"text": {"multiline": True}},
            },
            ATTR_EXPIRATION: {
                "name": "Expiration",
                "description": "Hours until notification expires (for queued notifications)",
                "required": False,
                "default": DEFAULT_EXPIRATION_HOURS,
                "example": 24,
                "selector": {
                    "number": {
                        "min": 1,
                        "max": MAX_EXPIRATION_HOURS,
                        "unit_of_measurement": "hours",
                    }
                },
            },
            ATTR_DATA: {
                "name": "Data",
                "description": "Additional data to pass to the underlying notify service",
                "required": False,
                "example": '{"image": "/local/snapshot.jpg"}',
                "selector": {"object": {}},
            },
        },
    }


def _get_loaded_entry(hass: HomeAssistant) -> "TickerConfigEntry":
    """Get a loaded Ticker config entry or raise ServiceValidationError."""
    entries = hass.config_entries.async_entries(DOMAIN)
    
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_config_entry",
        )
    
    entry = entries[0]
    
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
        )
    
    return entry


def _resolve_category_id(category_name: str, store: "TickerStore") -> str:
    """Resolve category name to category ID or raise ServiceValidationError."""
    # Check if it's already a valid category ID
    if store.category_exists(category_name):
        return category_name

    # Try to find by name
    categories = store.get_categories()
    for cat_id, cat_data in categories.items():
        if cat_data.get("name") == category_name:
            return cat_id

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_category",
        translation_placeholders={"category": category_name},
    )


def _get_person_name(hass: HomeAssistant, person_id: str) -> str:
    """Get friendly name for a person entity."""
    state = hass.states.get(person_id)
    if state:
        return state.attributes.get("friendly_name", person_id)
    return person_id


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up Ticker services.
    
    Per IQS action-setup rule, services are registered in async_setup
    and check for loaded config entries at runtime.
    """

    async def async_handle_notify(call: ServiceCall) -> None:
        """Handle the ticker.notify service call."""
        # Get loaded entry (raises ServiceValidationError if not available)
        entry = _get_loaded_entry(hass)
        store = entry.runtime_data.store
        
        category_input = call.data[ATTR_CATEGORY]
        title = call.data[ATTR_TITLE]
        message = call.data[ATTR_MESSAGE]
        expiration = call.data.get(ATTR_EXPIRATION, DEFAULT_EXPIRATION_HOURS)
        data = call.data.get(ATTR_DATA, {})

        # Resolve category (raises ServiceValidationError if invalid)
        category_id = _resolve_category_id(category_input, store)

        # Generate a unique ID for this notification call to group log entries
        notification_id = str(uuid.uuid4())

        _LOGGER.info(
            "Processing notification for category '%s': %s (notification_id: %s)",
            category_id,
            title,
            notification_id,
        )

        persons = hass.states.async_all("person")
        
        if not persons:
            _LOGGER.warning("No person entities found, notification not sent")
            return
        
        for person_state in persons:
            person_id = person_state.entity_id
            person_name = person_state.attributes.get("friendly_name", person_id)
            
            # Check if user is enabled for notifications
            if not store.is_user_enabled(person_id):
                _LOGGER.debug("Skipping %s (user disabled)", person_id)
                continue
            
            mode = store.get_subscription_mode(person_id, category_id)
            
            _LOGGER.debug(
                "Person %s subscription mode for %s: %s",
                person_id,
                category_id,
                mode,
            )

            if mode == MODE_NEVER:
                _LOGGER.debug("Skipping %s (mode: never)", person_id)
                await store.async_add_log(
                    category_id=category_id,
                    person_id=person_id,
                    person_name=person_name,
                    title=title,
                    message=message,
                    outcome=LOG_OUTCOME_SKIPPED,
                    reason="Subscription mode: never",
                    notification_id=notification_id,
                )
                continue

            if mode == MODE_ALWAYS:
                await _async_send_notification(
                    hass, store, person_id, person_name, category_id, title, message, data,
                    notification_id=notification_id,
                )
            
            elif mode == MODE_CONDITIONAL:
                await _async_handle_conditional_notification(
                    hass=hass,
                    store=store,
                    person_id=person_id,
                    person_name=person_name,
                    person_state=person_state,
                    category_id=category_id,
                    title=title,
                    message=message,
                    data=data,
                    expiration=expiration,
                    notification_id=notification_id,
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_NOTIFY,
        async_handle_notify,
        schema=_build_service_schema(),
    )
    
    # Set initial service description (without store, uses defaults)
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_NOTIFY,
        _build_service_description(None),
    )
    
    _LOGGER.info("Ticker services registered")


def register_schema_updater(hass: HomeAssistant, entry: "TickerConfigEntry") -> None:
    """Register callback to update service schema when categories change.
    
    Called from async_setup_entry after store is initialized.
    """
    store = entry.runtime_data.store
    
    @callback
    def update_service_schema() -> None:
        """Update service schema when categories change."""
        async_set_service_schema(
            hass,
            DOMAIN,
            SERVICE_NOTIFY,
            _build_service_description(store),
        )
        _LOGGER.debug("Updated ticker.notify service schema with new categories")

    # Store the updater in runtime_data
    entry.runtime_data.update_service_schema = update_service_schema
    
    # Update schema now with current categories
    update_service_schema()


async def _async_handle_conditional_notification(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    person_name: str,
    person_state: Any,
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any],
    expiration: int,
    notification_id: str | None = None,
) -> None:
    """Handle notification delivery for conditional mode.
    
    Evaluates zone conditions and determines whether to:
    - Send immediately (deliver_while_here)
    - Queue for later (queue_until_arrival)
    - Skip (no matching conditions)
    """
    conditions = store.get_subscription_conditions(person_id, category_id)
    
    if not conditions:
        # No conditions configured - fallback to always
        _LOGGER.warning(
            "Conditional mode for %s/%s has no conditions, sending immediately",
            person_id,
            category_id,
        )
        await _async_send_notification(
            hass, store, person_id, person_name, category_id, title, message, data,
            notification_id=notification_id,
        )
        return
    
    zones = conditions.get("zones", {})
    person_zone = person_state.state  # e.g., "home", "work", "not_home"
    
    # Track actions to take
    should_send_now = False
    should_queue = False
    queue_zones: list[str] = []  # Zones where we should queue for arrival
    
    # Check each configured zone
    for zone_id, zone_config in zones.items():
        # Check if zone still exists
        if not hass.states.get(zone_id):
            _LOGGER.warning(
                "Zone '%s' no longer exists for %s/%s - skipping",
                zone_id,
                person_id,
                category_id,
            )
            continue
        
        zone_name = zone_id.replace("zone.", "")
        is_in_zone = (person_zone == zone_name)
        
        deliver_while_here = zone_config.get("deliver_while_here", False)
        queue_until_arrival = zone_config.get("queue_until_arrival", False)
        
        if is_in_zone:
            # Person is currently in this zone
            if deliver_while_here:
                should_send_now = True
                _LOGGER.debug(
                    "%s is in zone %s with deliver_while_here=True, will send",
                    person_id,
                    zone_id,
                )
            if queue_until_arrival:
                # Already in zone, so "arrival" condition is met - send now
                should_send_now = True
                _LOGGER.debug(
                    "%s is in zone %s with queue_until_arrival=True, "
                    "will send (already there)",
                    person_id,
                    zone_id,
                )
        else:
            # Person is NOT in this zone
            if queue_until_arrival:
                should_queue = True
                queue_zones.append(zone_id)
                _LOGGER.debug(
                    "%s not in zone %s, will queue until arrival",
                    person_id,
                    zone_id,
                )
    
    # Execute actions
    if should_send_now:
        await _async_send_notification(
            hass, store, person_id, person_name, category_id, title, message, data,
            notification_id=notification_id,
        )
    elif should_queue:
        # Queue the notification
        await store.async_add_to_queue(
            person_id=person_id,
            category_id=category_id,
            title=title,
            message=message,
            data=data,
            expiration_hours=expiration,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_QUEUED,
            reason=f"Conditional: waiting for arrival at {', '.join(queue_zones)}",
            notification_id=notification_id,
        )
        _LOGGER.debug(
            "Queued notification for %s (conditional: waiting for %s)",
            person_id,
            queue_zones,
        )
    else:
        # No conditions matched - skip
        _LOGGER.debug(
            "Skipping %s (conditional: no matching zone conditions, currently in %s)",
            person_id,
            person_zone,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_SKIPPED,
            reason=f"Conditional: no matching conditions (currently in {person_zone})",
            notification_id=notification_id,
        )


async def _async_send_notification(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    person_name: str,
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any],
    notification_id: str | None = None,
) -> None:
    """Send notification to a person via their notify services.
    
    Respects device preferences:
    - Global device preference (all vs selected devices)
    - Per-category device override (additive)
    """
    # Get all discovered services for this person (list of dicts with service/name/device_id)
    all_services = await async_get_notify_services_for_person(hass, person_id)
    
    if not all_services:
        _LOGGER.warning(
            "No notify services found for %s, cannot send notification",
            person_id,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No notify services found",
            notification_id=notification_id,
        )
        return

    # Build a lookup of service ID to service info
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
        # Filter to only devices that still exist
        base_devices = pref_devices & all_service_ids
        if not base_devices:
            _LOGGER.warning(
                "User %s has 'selected' device mode but no valid devices, "
                "falling back to all devices",
                person_id,
            )
            base_devices = all_service_ids
    
    # Check for per-category device override (additive)
    device_override = store.get_device_override(person_id, category_id)
    if device_override and device_override.get("enabled"):
        override_devices = set(device_override.get("devices", []))
        # Filter to only devices that exist
        valid_override_devices = override_devices & all_service_ids
        if valid_override_devices:
            # Union: base + override
            final_devices = base_devices | valid_override_devices
            _LOGGER.debug(
                "Category override for %s/%s: adding %s to base devices",
                person_id,
                category_id,
                valid_override_devices,
            )
        else:
            final_devices = base_devices
    else:
        final_devices = base_devices
    
    if not final_devices:
        _LOGGER.warning(
            "No target devices for %s after applying preferences",
            person_id,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No target devices after applying preferences",
            notification_id=notification_id,
        )
        return
    
    _LOGGER.debug(
        "Sending notification to %s via %d device(s): %s",
        person_id,
        len(final_devices),
        final_devices,
    )

    for service_id in final_devices:
        service_info = service_lookup.get(service_id, {})
        service_name_display = service_info.get("name", service_id)
        domain, service_name = service_id.split(".", 1)
        
        service_data: dict[str, Any] = {
            "title": title,
            "message": message,
        }
        if data:
            service_data["data"] = dict(data)  # Copy to avoid mutating caller's dict
        else:
            service_data["data"] = {}
        
        # Inject deep-link to Ticker history tab (don't override user-set values)
        if "url" not in service_data["data"]:
            service_data["data"]["url"] = "/ticker#history"
        if "clickAction" not in service_data["data"]:
            service_data["data"]["clickAction"] = "/ticker#history"

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
                "Sent notification to %s via %s (%s)",
                person_id,
                service_id,
                service_name_display,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_SENT,
                notify_service=f"{service_id} ({service_name_display})",
                notification_id=notification_id,
            )
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timeout sending notification to %s via %s (exceeded %ds)",
                person_id,
                service_id,
                NOTIFY_SERVICE_TIMEOUT,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=f"Timeout after {NOTIFY_SERVICE_TIMEOUT}s",
                notification_id=notification_id,
            )
        except HomeAssistantError as err:
            _LOGGER.error(
                "Failed to send notification to %s via %s: %s",
                person_id,
                service_id,
                err,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=str(err),
                notification_id=notification_id,
            )
        except Exception as err:
            _LOGGER.error(
                "Unexpected error sending notification to %s via %s: %s",
                person_id,
                service_id,
                err,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=str(err),
                notification_id=notification_id,
            )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Ticker services.
    
    Note: Per IQS, services registered in async_setup should NOT be unloaded
    when a config entry is unloaded. They remain available but will raise
    ServiceValidationError if called without a loaded entry.
    """
    # Services are intentionally NOT removed here per IQS action-setup rule.
    # The service will raise ServiceValidationError if called without a loaded entry.
    _LOGGER.debug("Ticker config entry unloaded (services remain registered)")
