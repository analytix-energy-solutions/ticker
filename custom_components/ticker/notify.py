"""Ticker notify platform - exposes a notify entity for HA service discovery.

Registers Ticker as a HA notify platform so that notify.ticker appears
in Home Assistant. This makes Ticker visible to Alarmo, blueprints, and
any integration scanning for notify.* services.

The entity delegates to the ticker.notify service for actual delivery.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CATEGORY_DEFAULT, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ticker notify platform."""
    async_add_entities([TickerNotifyEntity(config_entry)])
    _LOGGER.debug("Ticker notify entity registered")


class TickerNotifyEntity(NotifyEntity):
    """Ticker notification entity - delegates to ticker.notify service.

    This thin wrapper exists solely to make Ticker discoverable
    by other integrations (Alarmo, blueprints, etc.) that scan
    for notify.* entities or services.
    """

    _attr_has_entity_name = True
    _attr_name = "Ticker"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the Ticker notify entity."""
        self._attr_unique_id = f"{config_entry.entry_id}_notify"
        self._config_entry = config_entry

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        """Send a notification via Ticker.

        Maps the HA notify entity interface to ticker.notify service call.
        The category can be specified via kwargs['data']['category'].
        If no category is provided, defaults to CATEGORY_DEFAULT.
        """
        # Copy to avoid mutating the caller's dict
        data = dict(kwargs.get("data") or {})
        category = data.pop("category", CATEGORY_DEFAULT)

        service_data: dict[str, object] = {
            "message": message,
            "category": category,
        }
        if title:
            service_data["title"] = title
        else:
            service_data["title"] = "Notification"
        if data:
            service_data["data"] = data

        await self.hass.services.async_call(
            DOMAIN, "notify", service_data, blocking=True
        )
