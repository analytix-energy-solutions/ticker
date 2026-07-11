"""Recipient mixin for TickerStore."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

from ..const import (
    ATTR_USER_LINK,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    DEVICE_TYPES,
    RECIPIENT_DELIVERY_FORMATS,
    SET_BY_ORPHAN_FALLBACK,
    TTS_BUFFER_DELAY_DEFAULT,
)

_LOGGER = logging.getLogger(__name__)


class RecipientMixin:
    """Mixin providing recipient (non-user device) functionality for TickerStore.

    Recipients are admin-managed notification targets not tied to a person
    entity (e.g., TVs, TTS speakers, wall tablets). They use the same
    subscription model as users but with a 'recipient:' key prefix.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _recipients: dict[str, dict[str, Any]]
    - _recipients_store: Store[dict[str, dict[str, Any]]]
    - _subscriptions: dict[str, dict[str, Any]] (from SubscriptionMixin)
    - async_save_subscriptions: coroutine (from SubscriptionMixin)
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _recipients: dict[str, dict[str, Any]]
    _recipients_store: "Store[dict[str, dict[str, Any]]]"
    _subscriptions: dict[str, dict[str, Any]]

    async def async_save_recipients(self) -> None:
        """Save recipients to storage."""
        await self._recipients_store.async_save(self._recipients)

    def get_recipients(self) -> dict[str, dict[str, Any]]:
        """Get all stored recipients."""
        return self._recipients.copy()

    def get_recipient(self, recipient_id: str) -> dict[str, Any] | None:
        """Get a single recipient by ID."""
        return self._recipients.get(recipient_id)

    def is_recipient_enabled(self, recipient_id: str) -> bool:
        """Check if a recipient is enabled for notifications.

        Returns False if the recipient is not found.
        """
        recipient = self._recipients.get(recipient_id)
        if recipient is None:
            return False
        return recipient.get("enabled", True)

    async def async_create_recipient(
        self,
        recipient_id: str,
        name: str,
        notify_services: list[dict[str, str]] | None = None,
        delivery_format: str = DELIVERY_FORMAT_RICH,
        icon: str = "mdi:bell-ring",
        enabled: bool = True,
        device_type: str = DEVICE_TYPE_PUSH,
        media_player_entity_id: str | None = None,
        tts_service: str | None = None,
        tts_engine_entity_id: str | None = None,
        resume_after_tts: bool = False,
        tts_buffer_delay: float = TTS_BUFFER_DELAY_DEFAULT,
        conditions: dict[str, Any] | None = None,
        chime_media_content_id: str | None = None,
        volume_override: float | None = None,
    ) -> dict[str, Any]:
        """Create a new recipient.

        Args:
            recipient_id: Unique slug identifier ([a-z0-9_]+).
            name: Display name for the recipient.
            notify_services: List of dicts with 'service' and 'name' keys
                (push type only).
            delivery_format: One of RECIPIENT_DELIVERY_FORMATS (push type).
                Ignored for TTS device type.
            icon: MDI icon string.
            enabled: Whether the recipient is active.
            device_type: 'push' or 'tts'.
            media_player_entity_id: Media player entity for TTS devices.
            tts_service: TTS service (e.g., 'tts.google_translate_say').
            tts_engine_entity_id: TTS engine entity (e.g., 'tts.google_translate')
                for services like tts.speak that support it.
            resume_after_tts: Whether to resume media after TTS playback.
            tts_buffer_delay: Seconds to wait before TTS playback (Chromecast).
            conditions: Device-level conditions dict (time/state rules).
                Evaluated before subscription mode. None means no gate.
            chime_media_content_id: F-35 — optional HA media_content_id played
                before TTS on this device. Sparse storage: only persisted when
                non-empty and only meaningful for TTS-type recipients (push
                recipients silently drop the field).
            volume_override: F-35.2 — optional float in [0.0, 1.0] applied via
                ``media_player.volume_set`` before chime+TTS, then restored
                afterwards. Sparse storage: only persisted on TTS recipients
                with a value in range; push recipients silently drop. None or
                out-of-range values are dropped.

        Returns:
            The created recipient dict.

        Raises:
            ValueError: If recipient_id already exists or invalid params.
        """
        if recipient_id in self._recipients:
            raise ValueError(f"Recipient '{recipient_id}' already exists")

        if device_type not in DEVICE_TYPES:
            raise ValueError(f"Invalid device_type: {device_type}")

        if device_type == DEVICE_TYPE_PUSH:
            if (
                delivery_format != "auto"
                and delivery_format not in RECIPIENT_DELIVERY_FORMATS
            ):
                raise ValueError(
                    f"Invalid delivery_format for push: {delivery_format}"
                )
        else:
            # TTS device type ignores delivery_format
            delivery_format = DELIVERY_FORMAT_RICH  # stored default, unused

        now = datetime.now(timezone.utc).isoformat()
        recipient: dict[str, Any] = {
            "recipient_id": recipient_id,
            "name": name,
            "icon": icon,
            "device_type": device_type,
            "notify_services": notify_services or [],
            "delivery_format": delivery_format,
            "media_player_entity_id": media_player_entity_id,
            "tts_service": tts_service,
            "tts_engine_entity_id": tts_engine_entity_id,
            "resume_after_tts": resume_after_tts,
            "tts_buffer_delay": tts_buffer_delay,
            "enabled": enabled,
            "created_at": now,
            "updated_at": now,
        }

        # Sparse storage: only persist conditions when set
        if conditions is not None:
            recipient["conditions"] = conditions

        # F-35: Sparse storage for chime — only persist on TTS devices
        # when a non-empty value was supplied. Push devices silently drop
        # the field per spec §6.1.
        if (
            device_type == DEVICE_TYPE_TTS
            and chime_media_content_id
            and chime_media_content_id.strip()
        ):
            recipient["chime_media_content_id"] = chime_media_content_id.strip()
        elif device_type != DEVICE_TYPE_TTS and chime_media_content_id:
            _LOGGER.debug(
                "Dropping chime_media_content_id on non-TTS recipient %s",
                recipient_id,
            )

        # Sparse storage for tts_engine_entity_id — only persist on TTS devices
        # when a non-empty value was supplied. Push devices silently drop.
        if (
            device_type == DEVICE_TYPE_TTS
            and tts_engine_entity_id
            and tts_engine_entity_id.strip()
        ):
            recipient["tts_engine_entity_id"] = tts_engine_entity_id.strip()
        elif device_type != DEVICE_TYPE_TTS and tts_engine_entity_id:
            _LOGGER.debug(
                "Dropping tts_engine_entity_id on non-TTS recipient %s",
                recipient_id,
            )

        # F-35.2: Sparse storage for volume_override — TTS-only,
        # in-range float. Push devices silently drop.
        if (
            device_type == DEVICE_TYPE_TTS
            and isinstance(volume_override, (int, float))
            and 0.0 <= float(volume_override) <= 1.0
        ):
            recipient["volume_override"] = float(volume_override)
        elif (
            device_type != DEVICE_TYPE_TTS
            and volume_override is not None
        ):
            _LOGGER.debug(
                "Dropping volume_override on non-TTS recipient %s",
                recipient_id,
            )

        self._recipients[recipient_id] = recipient
        await self.async_save_recipients()
        _LOGGER.info("Created recipient: %s (%s, type=%s)", recipient_id, name, device_type)
        return recipient

    async def async_update_recipient(
        self, recipient_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Update recipient properties.

        Args:
            recipient_id: The recipient to update.
            **kwargs: Fields to update (name, icon, notify_services,
                      delivery_format, enabled).

        Returns:
            The updated recipient dict.

        Raises:
            ValueError: If recipient_id does not exist.
        """
        if recipient_id not in self._recipients:
            raise ValueError(f"Recipient '{recipient_id}' not found")

        allowed_fields = {
            "name", "icon", "notify_services", "delivery_format", "enabled",
            "device_type", "media_player_entity_id", "tts_service",
            "tts_engine_entity_id", "resume_after_tts", "tts_buffer_delay", "conditions",
            "chime_media_content_id", "volume_override",
        }
        unknown = set(kwargs) - allowed_fields
        if unknown:
            _LOGGER.debug(
                "Ignoring unknown fields for recipient %s: %s",
                recipient_id,
                unknown,
            )
        for key, value in kwargs.items():
            if key in allowed_fields:
                if key == "conditions" and value is None:
                    # Sparse storage: remove conditions key when cleared
                    self._recipients[recipient_id].pop("conditions", None)
                elif key == "chime_media_content_id":
                    # F-35: sparse storage — strip + remove key when blank
                    cleaned = (value or "").strip() if isinstance(value, str) else ""
                    if cleaned:
                        self._recipients[recipient_id]["chime_media_content_id"] = cleaned
                    else:
                        self._recipients[recipient_id].pop(
                            "chime_media_content_id", None,
                        )
                elif key == "volume_override":
                    # F-35.2: sparse storage — None/out-of-range removes key,
                    # in-range float [0.0, 1.0] sets it.
                    if (
                        isinstance(value, (int, float))
                        and 0.0 <= float(value) <= 1.0
                    ):
                        self._recipients[recipient_id]["volume_override"] = (
                            float(value)
                        )
                    else:
                        self._recipients[recipient_id].pop(
                            "volume_override", None,
                        )
                elif key == "tts_engine_entity_id":
                    # Sparse storage — strip + remove key when blank
                    cleaned = (value or "").strip() if isinstance(value, str) else ""
                    if cleaned:
                        self._recipients[recipient_id]["tts_engine_entity_id"] = cleaned
                    else:
                        self._recipients[recipient_id].pop(
                            "tts_engine_entity_id", None,
                        )
                else:
                    self._recipients[recipient_id][key] = value

        self._recipients[recipient_id]["updated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        await self.async_save_recipients()
        _LOGGER.debug("Updated recipient: %s", recipient_id)
        return self._recipients[recipient_id]

    async def async_delete_recipient(self, recipient_id: str) -> bool:
        """Delete a recipient and all its subscriptions.

        Removes the recipient record and any subscription keys matching
        the 'recipient:{recipient_id}:' prefix.

        Args:
            recipient_id: The recipient to delete.

        Returns:
            True if deleted, False if not found.
        """
        if recipient_id not in self._recipients:
            return False

        del self._recipients[recipient_id]
        await self.async_save_recipients()

        # Clean up subscriptions with recipient: prefix
        prefix = f"recipient:{recipient_id}:"
        sub_keys_to_remove = [
            key for key in self._subscriptions if key.startswith(prefix)
        ]
        if sub_keys_to_remove:
            for key in sub_keys_to_remove:
                del self._subscriptions[key]
            await self.async_save_subscriptions()  # type: ignore[attr-defined]
            # Fire once after the cascade so condition listeners refresh
            # a single time instead of per-key (BUG-086).
            self._notify_subscription_change()  # type: ignore[attr-defined]
            _LOGGER.debug(
                "Removed %d subscriptions for deleted recipient %s",
                len(sub_keys_to_remove),
                recipient_id,
            )

        _LOGGER.info("Deleted recipient: %s", recipient_id)
        return True

    async def async_set_recipient_enabled(
        self, recipient_id: str, enabled: bool
    ) -> dict[str, Any]:
        """Toggle a recipient's enabled state.

        Args:
            recipient_id: The recipient to toggle.
            enabled: New enabled state.

        Returns:
            The updated recipient dict.

        Raises:
            ValueError: If recipient_id does not exist.
        """
        if recipient_id not in self._recipients:
            raise ValueError(f"Recipient '{recipient_id}' not found")

        self._recipients[recipient_id]["enabled"] = enabled
        self._recipients[recipient_id]["updated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        await self.async_save_recipients()

        status = "enabled" if enabled else "disabled"
        _LOGGER.info("Recipient %s %s", recipient_id, status)
        return self._recipients[recipient_id]

    async def async_set_recipient_user_link(
        self, recipient_id: str, person_id: str | None
    ) -> dict[str, Any]:
        """Set or clear the user_link on a recipient (F-39).

        Sparse storage: writes ``recipient[ATTR_USER_LINK] = person_id``
        when given, pops the key when None (Standalone). Updates
        ``updated_at`` and persists. The chunk-2 resolver uses this field
        to swap the effective person_id for subscription lookup; the F-21
        device-condition gate remains the sole device-condition site.

        Raises ValueError if recipient_id is unknown.
        """
        if recipient_id not in self._recipients:
            raise ValueError(f"Recipient '{recipient_id}' not found")

        recipient = self._recipients[recipient_id]
        if person_id is None:
            recipient.pop(ATTR_USER_LINK, None)
        else:
            recipient[ATTR_USER_LINK] = person_id

        recipient["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.async_save_recipients()
        _LOGGER.info(
            "Recipient %s user_link %s",
            recipient_id,
            f"set to {person_id}" if person_id else "cleared",
        )
        return recipient

    async def async_handle_person_removed(self, person_id: str) -> int:
        """Orphan-fallback for F-39 when a linked person is removed.

        For each recipient linked to ``person_id``: copy the person's
        current subscriptions into the recipient's own rows tagged
        ``set_by=SET_BY_ORPHAN_FALLBACK`` (conditions deep-copied), then
        clear ``user_link`` so the recipient reverts to Standalone with
        last-known subs. Logs a WARNING per recipient. Returns count.
        """
        affected_recipient_ids = [
            rid
            for rid, recipient in self._recipients.items()
            if recipient.get(ATTR_USER_LINK) == person_id
        ]
        if not affected_recipient_ids:
            return 0

        # Snapshot the user's subscriptions once for all affected recipients.
        # get_subscriptions_for_person returns {cat_id: subscription_dict}.
        source_subs = self.get_subscriptions_for_person(  # type: ignore[attr-defined]
            person_id
        )

        for rid in affected_recipient_ids:
            for cat_id, sub in source_subs.items():
                # Deep-copy conditions so the recipient's stored row owns
                # an independent snapshot — mutations of source_subs must
                # not leak into the recipient's data, and vice versa.
                conditions = sub.get("conditions")
                if conditions is not None:
                    conditions = copy.deepcopy(conditions)
                await self.async_set_subscription(  # type: ignore[attr-defined]
                    person_id=f"recipient:{rid}",
                    category_id=cat_id,
                    mode=sub.get("mode"),
                    conditions=conditions,
                    set_by=SET_BY_ORPHAN_FALLBACK,
                )

            # Clear user_link — recipient reverts to Standalone with the
            # subs we just seeded.
            self._recipients[rid].pop(ATTR_USER_LINK, None)
            self._recipients[rid]["updated_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            _LOGGER.warning(
                "F-39 orphan fallback: recipient %s was linked to %s "
                "(removed) — copied %d subscription(s) into recipient "
                "rows and cleared user_link",
                rid,
                person_id,
                len(source_subs),
            )

        await self.async_save_recipients()
        return len(affected_recipient_ids)

    @staticmethod
    def migrate_recipient_data(
        recipients: dict[str, dict[str, Any]],
    ) -> int:
        """Migrate recipients to include device_type and TTS fields.

        Handles pre-device-type data where delivery_format was the sole
        discriminator. Idempotent: skips recipients that already have
        device_type set.

        Migration rules:
        - delivery_format='tts' -> device_type='tts', media_player_entity_id=None
        - delivery_format='persistent' -> device_type='push', delivery_format='rich'
        - Otherwise -> device_type='push'
        - Adds missing media_player_entity_id/tts_service with None defaults.

        Args:
            recipients: Recipients dict (mutated in-place).

        Returns:
            Number of recipients migrated.
        """
        migrated = 0
        for rid, recipient in recipients.items():
            if "device_type" in recipient:
                # Ensure TTS fields exist even on already-migrated data
                recipient.setdefault("media_player_entity_id", None)
                recipient.setdefault("tts_service", None)
                recipient.setdefault("resume_after_tts", False)
                recipient.setdefault("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT)
                continue

            old_format = recipient.get("delivery_format", DELIVERY_FORMAT_RICH)

            if old_format == DELIVERY_FORMAT_TTS:
                recipient["device_type"] = DEVICE_TYPE_TTS
                recipient["delivery_format"] = DELIVERY_FORMAT_RICH
            elif old_format == "persistent":
                recipient["device_type"] = DEVICE_TYPE_PUSH
                recipient["delivery_format"] = DELIVERY_FORMAT_RICH
            else:
                recipient["device_type"] = DEVICE_TYPE_PUSH

            recipient.setdefault("media_player_entity_id", None)
            recipient.setdefault("tts_service", None)
            recipient.setdefault("tts_engine_entity_id", None)
            recipient.setdefault("resume_after_tts", False)
            recipient.setdefault("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT)
            migrated += 1
            _LOGGER.info(
                "Migrated recipient %s: device_type=%s (was format=%s)",
                rid,
                recipient["device_type"],
                old_format,
            )

        return migrated
