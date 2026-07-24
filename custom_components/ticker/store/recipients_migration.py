"""Recipient data migration.

Extracted from ``store/recipients.py`` to keep that file under the 500-line
limit (PR #61 added the ``tts_engine_entity_id`` sparse field + migration
default, pushing it over). Pure function — no store/self state; the
``RecipientMixin`` re-exposes it as a ``staticmethod`` so existing callers
(``RecipientMixin.migrate_recipient_data(recipients)``) are unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from ..const import (
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    TTS_BUFFER_DELAY_DEFAULT,
)

_LOGGER = logging.getLogger(__name__)


def migrate_recipient_data(recipients: dict[str, dict[str, Any]]) -> int:
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
