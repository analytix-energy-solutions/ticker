"""Sensor platform for Ticker integration.

Provides category sensor entities that expose the last 10 notifications
per category for dashboard integration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_SENSOR_NOTIFICATIONS

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ticker sensor entities from a config entry."""
    store: TickerStore = entry.runtime_data.store

    # Initialize sensors storage in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["sensors"] = {}

    # Create sensors for existing categories
    categories = store.get_categories()
    entities = []
    for category_id, category_data in categories.items():
        sensor = TickerCategorySensor(
            entry=entry,
            category_id=category_id,
            category_name=category_data.get("name", category_id),
            icon=category_data.get("icon", "mdi:bell"),
        )
        entities.append(sensor)
        hass.data[DOMAIN]["sensors"][category_id] = sensor

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Created %d category sensor entities", len(entities))

    # Register category change listener for dynamic add/remove
    @callback
    def on_category_change() -> None:
        """Handle category changes by adding/removing sensors."""
        hass.async_create_task(
            _async_update_sensors_for_categories(
                hass, entry, store, async_add_entities
            )
        )

    store.register_category_listener(on_category_change)

    # Store listener reference for cleanup
    entry.async_on_unload(
        lambda: store.unregister_category_listener(on_category_change)
    )


async def _async_update_sensors_for_categories(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: "TickerStore",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Update sensors when categories change."""
    sensors: dict[str, TickerCategorySensor] = hass.data[DOMAIN]["sensors"]
    categories = store.get_categories()

    current_category_ids = set(categories.keys())
    existing_sensor_ids = set(sensors.keys())

    # Add sensors for new categories
    new_category_ids = current_category_ids - existing_sensor_ids
    new_entities = []
    for category_id in new_category_ids:
        category_data = categories[category_id]
        sensor = TickerCategorySensor(
            entry=entry,
            category_id=category_id,
            category_name=category_data.get("name", category_id),
            icon=category_data.get("icon", "mdi:bell"),
        )
        new_entities.append(sensor)
        sensors[category_id] = sensor
        _LOGGER.info("Created sensor for new category: %s", category_id)

    if new_entities:
        async_add_entities(new_entities)

    # Remove sensors for deleted categories
    removed_category_ids = existing_sensor_ids - current_category_ids
    for category_id in removed_category_ids:
        sensor = sensors.pop(category_id, None)
        if sensor:
            await sensor.async_remove()
            _LOGGER.info("Removed sensor for deleted category: %s", category_id)


class TickerCategorySensor(SensorEntity):
    """Sensor entity representing a Ticker notification category.

    State: Count of notifications in the list (0-10)
    Attributes: notifications list, category_id, category_name, last_triggered
    """

    has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        category_id: str,
        category_name: str,
        icon: str,
    ) -> None:
        """Initialize the category sensor."""
        self._entry = entry
        self._category_id = category_id
        self._category_name = category_name
        self._attr_icon = icon
        self._attr_name = f"Ticker - {category_name}"
        self._attr_unique_id = f"ticker_{entry.entry_id}_{category_id}"

        # In-memory notification storage
        self._notifications: list[dict[str, Any]] = []
        self._last_triggered: str | None = None

        # Set initial attributes via _attr_ convention (HA 2024.1+ uses
        # @cached_property for extra_state_attributes; @property overrides
        # are silently bypassed during state serialization)
        self._attr_extra_state_attributes: dict[str, Any] = {
            "notifications": self._notifications,
            "category_id": self._category_id,
            "category_name": self._category_name,
            "last_triggered": self._last_triggered,
        }

    @property
    def native_value(self) -> int:
        """Return the count of notifications."""
        return len(self._notifications)

    @callback
    def async_add_notification(
        self,
        header: str,
        body: str,
        delivered: list[str],
        queued: list[str],
        dropped: list[str],
        priority: str,
        timestamp: str,
        expose_content: bool = True,
    ) -> None:
        """Add a notification to the sensor.

        Args:
            header: Notification title
            body: Notification message
            delivered: List of service IDs where delivery succeeded
            queued: List of descriptions for queued deliveries
            dropped: List of descriptions for dropped/skipped deliveries
            priority: Priority level (default "normal")
            timestamp: ISO 8601 timestamp of the notification
            expose_content: If False, header and body are blanked in the stored
                notification dict (BUG-099). Count and last_triggered still
                update so dashboards can observe activity without leaking
                raw notification text through entity attributes. Default True
                preserves backward compatibility for any other caller.
        """
        notification = {
            "header": header if expose_content else "",
            "body": body if expose_content else "",
            "delivered": delivered,
            "queued": queued,
            "dropped": dropped,
            "priority": priority,
            "timestamp": timestamp,
        }

        self._notifications.append(notification)

        # Trim to max entries (oldest rolls off)
        if len(self._notifications) > MAX_SENSOR_NOTIFICATIONS:
            self._notifications = self._notifications[-MAX_SENSOR_NOTIFICATIONS:]

        # Update last_triggered
        self._last_triggered = timestamp

        # Refresh attributes dict (HA reads _attr_extra_state_attributes)
        self._attr_extra_state_attributes = {
            "notifications": self._notifications,
            "category_id": self._category_id,
            "category_name": self._category_name,
            "last_triggered": self._last_triggered,
        }

        # Trigger state update
        self.async_write_ha_state()

        _LOGGER.debug(
            "Added notification to sensor %s: %s (total: %d)",
            self._category_id,
            header,
            len(self._notifications),
        )


def get_category_sensor(
    hass: HomeAssistant,
    category_id: str,
) -> TickerCategorySensor | None:
    """Get the sensor entity for a category.

    Args:
        hass: Home Assistant instance
        category_id: The category ID to look up

    Returns:
        TickerCategorySensor if found, None otherwise
    """
    sensors = hass.data.get(DOMAIN, {}).get("sensors", {})
    return sensors.get(category_id)
