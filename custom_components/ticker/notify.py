"""Ticker notify platform - exposes notify entities for HA service discovery.

Registers Ticker as a HA notify platform so that notify.ticker appears in
Home Assistant. This makes Ticker visible to Alarmo, blueprints, and any
integration scanning for notify.* services.

Two kinds of entity are created:

* ``notify.ticker`` — a single generic entity kept for backwards
  compatibility and for callers (Alarmo, blueprints) that expect one notify
  service. It routes to the default category unless a category is supplied
  via ``data`` (which the HA ``notify.send_message`` action does not pass,
  so in practice it lands in the default category).

* ``notify.ticker_<category_id>`` — one entity per Ticker category, created
  and removed dynamically as categories change. Each carries its own
  category, so callers that can only pass ``message``/``title`` (e.g. the
  hass-alert2 notifier, which forbids ``data`` on notify entities) can still
  route to a specific category simply by targeting the matching entity. No
  ``data`` payload is required.

All entities delegate to the ``ticker.notify`` service for actual delivery,
so the full routing pipeline (subscriptions, conditions, queue, actions,
critical flag, smart-notification injection) is reused unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CATEGORY_DEFAULT, DOMAIN

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Key under hass.data[DOMAIN] holding the per-category notify entities,
# mirroring the "sensors" registry used by sensor.py.
NOTIFY_ENTITIES_KEY = "notify_entities"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ticker notify platform."""
    store: TickerStore = entry.runtime_data.store

    hass.data.setdefault(DOMAIN, {})
    category_entities: dict[str, TickerCategoryNotifyEntity] = {}
    hass.data[DOMAIN][NOTIFY_ENTITIES_KEY] = category_entities

    # Generic entity (notify.ticker) — backwards compatible / Alarmo target.
    entities: list[NotifyEntity] = [TickerNotifyEntity(entry)]

    # One entity per existing category (notify.ticker_<category_id>).
    for category_id, category_data in store.get_categories().items():
        entity = TickerCategoryNotifyEntity(
            entry=entry,
            category_id=category_id,
            category_name=category_data.get("name", category_id),
            icon=category_data.get("icon", "mdi:bell"),
        )
        entities.append(entity)
        category_entities[category_id] = entity

    async_add_entities(entities)
    _LOGGER.debug(
        "Ticker notify entities registered (generic + %d categories)",
        len(category_entities),
    )

    # Dynamic add/remove as categories change, matching sensor.py.
    @callback
    def on_category_change() -> None:
        hass.async_create_task(
            _async_update_category_notify_entities(
                hass, entry, store, async_add_entities
            )
        )

    store.register_category_listener(on_category_change)
    entry.async_on_unload(
        lambda: store.unregister_category_listener(on_category_change)
    )


async def _async_update_category_notify_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: "TickerStore",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add/remove per-category notify entities when categories change."""
    entities: dict[str, TickerCategoryNotifyEntity] = hass.data[DOMAIN][
        NOTIFY_ENTITIES_KEY
    ]
    categories = store.get_categories()

    current_ids = set(categories.keys())
    existing_ids = set(entities.keys())

    # New categories -> new entities
    new_entities = []
    for category_id in current_ids - existing_ids:
        category_data = categories[category_id]
        entity = TickerCategoryNotifyEntity(
            entry=entry,
            category_id=category_id,
            category_name=category_data.get("name", category_id),
            icon=category_data.get("icon", "mdi:bell"),
        )
        new_entities.append(entity)
        entities[category_id] = entity
        _LOGGER.info("Created notify entity for new category: %s", category_id)

    if new_entities:
        async_add_entities(new_entities)

    # Deleted categories -> remove entities
    for category_id in existing_ids - current_ids:
        entity = entities.pop(category_id, None)
        if entity:
            await entity.async_remove()
            _LOGGER.info(
                "Removed notify entity for deleted category: %s", category_id
            )


class TickerNotifyEntity(NotifyEntity):
    """Generic Ticker notify entity - delegates to the ticker.notify service.

    Kept for discoverability by other integrations (Alarmo, blueprints) that
    scan for notify.* entities or services. Category may be supplied via
    kwargs['data']['category']; when absent (the usual case, since the HA
    notify.send_message action carries no data), CATEGORY_DEFAULT is used.
    """

    _attr_has_entity_name = True
    _attr_name = "Ticker"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the generic Ticker notify entity."""
        self._attr_unique_id = f"{config_entry.entry_id}_notify"
        self._config_entry = config_entry

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        """Send a notification via Ticker."""
        data = dict(kwargs.get("data") or {})
        category = data.pop("category", CATEGORY_DEFAULT)

        service_data: dict[str, object] = {
            "message": message,
            "category": category,
            "title": title or "Notification",
        }
        if data:
            service_data["data"] = data

        await self.hass.services.async_call(
            DOMAIN, "notify", service_data, blocking=True
        )


class TickerCategoryNotifyEntity(NotifyEntity):
    """Per-category Ticker notify entity - fixed category, no data required.

    Exposes notify.ticker_<category_id>. Because the category is baked into
    the entity, callers only need to pass message/title — which is exactly
    the constraint the HA notify-entity interface (and hass-alert2's notifier)
    imposes. This is what lets Alert2 route to a specific category without
    being able to send a data payload.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        category_id: str,
        category_name: str,
        icon: str,
    ) -> None:
        """Initialize a per-category notify entity."""
        self._entry = entry
        self._category_id = category_id
        self._attr_icon = icon
        # Naming mirrors the category sensor ("Ticker - <Name>") so the
        # resulting entity_id is notify.ticker_<category_id>.
        self._attr_name = f"Ticker - {category_name}"
        self._attr_unique_id = f"{entry.entry_id}_notify_{category_id}"

    async def async_send_message(
        self, message: str, title: str | None = None, **kwargs: Any
    ) -> None:
        """Send a notification to this entity's fixed category via Ticker."""
        # Any extra data (from callers that can supply it) is forwarded, but
        # the category is always this entity's own and cannot be overridden.
        data = dict(kwargs.get("data") or {})
        data.pop("category", None)

        service_data: dict[str, object] = {
            "message": message,
            "category": self._category_id,
            "title": title or "Notification",
        }
        if data:
            service_data["data"] = data

        await self.hass.services.async_call(
            DOMAIN, "notify", service_data, blocking=True
        )
