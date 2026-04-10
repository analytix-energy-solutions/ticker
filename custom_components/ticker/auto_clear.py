"""F-30 Auto-Clear Triggers — registry of one-shot clear listeners.

Accepts a `clear_when` descriptor on ticker.notify and, after the notification
is delivered, registers either a state-change listener or an event bus
listener. When the trigger fires, the registry dispatches a clear_notification
to the list of notify services that originally received the notification, then
unregisters itself (one-shot).

IMPORTANT — HA RESTART LIMITATION:
  Registered listeners live entirely in memory on the running HA instance.
  They do NOT persist across Home Assistant restarts. If HA restarts after a
  notification is delivered but before its clear_when trigger fires, the
  notification will remain on the device until it is manually dismissed or
  another clear_notification call targets the same tag. Documenting this is
  a deliberate tradeoff to keep the feature lightweight; persisting these
  entries would require storage, rehydration, and a resubscription dance on
  every startup that is not justified for the current Reddit-requested use.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CLEAR_WHEN_TYPE_EVENT, CLEAR_WHEN_TYPE_STATE

_LOGGER = logging.getLogger(__name__)


def _classify_clear_when(clear_when: dict[str, Any]) -> str | None:
    """Return the clear_when trigger type, or None if the shape is invalid."""
    if not isinstance(clear_when, dict):
        return None
    if "entity_id" in clear_when and "state" in clear_when:
        return CLEAR_WHEN_TYPE_STATE
    if "event_type" in clear_when:
        return CLEAR_WHEN_TYPE_EVENT
    return None


class AutoClearRegistry:
    """In-memory registry of auto-clear listeners keyed by notification_id.

    Each entry owns one or more unsub callbacks. On trigger, the registry
    fires the clear dispatch helper and unregisters the entry (one-shot).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registry."""
        self._hass = hass
        self._entries: dict[str, list[Callable[[], None]]] = {}
        # Parallel id→tag map so unregister_by_tag (called on manual clear)
        # can find entries without scanning callable closures.
        self._tags: dict[str, str] = {}

    async def register(
        self,
        notification_id: str,
        clear_when: dict[str, Any],
        delivered_services: list[str],
        tag: str | None,
    ) -> None:
        """Register a one-shot auto-clear listener for a delivered notification.

        Args:
            notification_id: Unique notification id (uuid4 from services.py).
            clear_when: Validated trigger descriptor (state or event shape).
            delivered_services: notify.* service ids that received the
                notification and should receive the subsequent clear.
            tag: The smart-notification tag that was applied to the outgoing
                payload. If None, the category has no tag mode configured and
                auto-clear cannot target a specific notification — we log a
                warning and skip registration (the HA Companion App keys clear
                operations on tag, so a tag-less clear would nuke unrelated
                notifications).
        """
        if not delivered_services:
            _LOGGER.debug(
                "auto_clear: skip %s (no delivered services)", notification_id
            )
            return

        if not tag:
            _LOGGER.warning(
                "auto_clear: notification %s has no smart-notification tag; "
                "clear_when is ignored (category needs tag_mode configured)",
                notification_id,
            )
            return

        trigger_type = _classify_clear_when(clear_when)
        if trigger_type is None:
            _LOGGER.warning(
                "auto_clear: invalid clear_when shape for %s: %r",
                notification_id,
                clear_when,
            )
            return

        # Idempotency: if something re-registers the same id, tear down the
        # prior entry first. uuid4 collision is not expected but belt-and-
        # braces keeps us from leaking listeners.
        if notification_id in self._entries:
            _LOGGER.debug(
                "auto_clear: re-register collision for %s; unregistering prior",
                notification_id,
            )
            self.unregister(notification_id)

        if trigger_type == CLEAR_WHEN_TYPE_STATE:
            unsubs = self._register_state(
                notification_id, clear_when, delivered_services, tag
            )
        else:
            unsubs = self._register_event(
                notification_id, clear_when, delivered_services, tag
            )

        if unsubs:
            self._entries[notification_id] = unsubs
            self._tags[notification_id] = tag
            _LOGGER.debug(
                "auto_clear: registered %s trigger for %s (tag=%s, services=%d)",
                trigger_type,
                notification_id,
                tag,
                len(delivered_services),
            )

    def _register_state(
        self,
        notification_id: str,
        clear_when: dict[str, Any],
        delivered_services: list[str],
        tag: str,
    ) -> list[Callable[[], None]]:
        """Wire an async_track_state_change_event listener."""
        entity_id: str = clear_when["entity_id"]
        target_state: str = clear_when["state"]

        # Fail-soft if the entity does not exist yet. We do NOT register a
        # listener on a ghost entity — this matches the brief's guidance.
        if self._hass.states.get(entity_id) is None:
            _LOGGER.warning(
                "auto_clear: entity %s does not exist; clear_when for %s "
                "will not be active",
                entity_id,
                notification_id,
            )
            return []

        @callback
        def _state_callback(event: Event) -> None:
            """Handle state change; fire clear when target state is reached."""
            new_state = event.data.get("new_state")
            if new_state is None:
                # Entity was removed after registration. Drop the listener so
                # we stop leaking; nothing can match anymore.
                _LOGGER.debug(
                    "auto_clear: entity %s removed; dropping %s",
                    entity_id,
                    notification_id,
                )
                self.unregister(notification_id)
                return
            if new_state.state != target_state:
                return
            self._fire(notification_id, delivered_services, tag)

        unsub = async_track_state_change_event(
            self._hass, [entity_id], _state_callback
        )
        return [unsub]

    def _register_event(
        self,
        notification_id: str,
        clear_when: dict[str, Any],
        delivered_services: list[str],
        tag: str,
    ) -> list[Callable[[], None]]:
        """Wire a hass.bus.async_listen listener for a one-shot event."""
        event_type: str = clear_when["event_type"]

        @callback
        def _event_callback(_event: Event) -> None:
            """Handle event fire; dispatch clear and unregister."""
            self._fire(notification_id, delivered_services, tag)

        unsub = self._hass.bus.async_listen(event_type, _event_callback)
        return [unsub]

    @callback
    def _fire(
        self,
        notification_id: str,
        delivered_services: list[str],
        tag: str,
    ) -> None:
        """Fire the clear and tear down the entry (one-shot discipline)."""
        # Pop FIRST so re-entrancy (e.g., a state callback landing on the
        # same tick as another event) can't double-dispatch.
        entry = self._entries.pop(notification_id, None)
        self._tags.pop(notification_id, None)
        if entry is None:
            return
        for unsub in entry:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "auto_clear: unsub failed for %s",
                    notification_id,
                    exc_info=True,
                )

        # Schedule the dispatch on the event loop so callbacks stay sync.
        self._hass.async_create_task(
            self._dispatch_clear(notification_id, delivered_services, tag)
        )

    async def _dispatch_clear(
        self,
        notification_id: str,
        delivered_services: list[str],
        tag: str,
    ) -> None:
        """Call the public clear dispatch helper."""
        # Local import to avoid a module-level cycle with clear_notification.
        from .clear_notification import async_dispatch_clear

        _LOGGER.info(
            "auto_clear: firing clear for %s (tag=%s, services=%d)",
            notification_id,
            tag,
            len(delivered_services),
        )
        try:
            await async_dispatch_clear(
                self._hass, delivered_services, tag, notification_id
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "auto_clear: dispatch_clear failed for %s", notification_id
            )

    def unregister(self, notification_id: str) -> None:
        """Tear down a registered entry by id (idempotent)."""
        entry = self._entries.pop(notification_id, None)
        self._tags.pop(notification_id, None)
        if not entry:
            return
        for unsub in entry:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "auto_clear: unsub failed for %s",
                    notification_id,
                    exc_info=True,
                )

    def unregister_all(self) -> None:
        """Tear down every entry (called on unload)."""
        for notification_id in list(self._entries.keys()):
            self.unregister(notification_id)
        self._entries.clear()
        self._tags.clear()

    def unregister_by_tag(self, tag: str) -> int:
        """Tear down any entries matching a given notification tag.

        Used by the manual clear_notification service handler: when a tag is
        cleared by hand, we drop any pending auto-clear listeners that would
        later fire against an already-dismissed notification. Linear scan
        over _tags is fine because the registry is expected to hold at most
        a handful of live entries at any time.

        Returns the number of entries unregistered.
        """
        matched = [nid for nid, t in list(self._tags.items()) if t == tag]
        for nid in matched:
            self.unregister(nid)
        return len(matched)
