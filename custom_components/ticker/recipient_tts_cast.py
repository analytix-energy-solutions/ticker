"""Cast-specific helpers for the TTS delivery pipeline (BUG-109).

Extracted from ``recipient_tts_delivery.py`` (v1.7.0b17) to keep that
file under the 500-line limit while the hybrid cast volume pattern
(pre-set + deferred re-apply) adds inline branches to both
``_deliver_tts_with_restore`` and ``_deliver_tts_plain``.

This module currently owns:

* ``_restore_previous_media`` — resume previously-playing media on the
  entity after TTS. Used by the cast and non-cast branches of
  ``_deliver_tts_with_restore``.

The cast detection helper (``_is_cast_target``) and the jiggle helper
(``_set_volume_with_jiggle``) still live in ``recipient_tts_chime.py``
because they're shared with the chime primitives. The hybrid
delivery sequence itself stays inline in the delivery branches so the
ordering (pre-set → play_media → wait → apply) is readable end-to-end.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant

from .const import NOTIFY_SERVICE_TIMEOUT

_LOGGER = logging.getLogger(__name__)


async def _restore_previous_media(
    hass: HomeAssistant,
    entity_id: str,
    prev_content_id: str,
    prev_content_type: str | None,
) -> bool:
    """Resume previously-playing media on the entity. Returns True on success.

    Extracted for reuse between the cast and non-cast branches of
    ``_deliver_tts_with_restore``. Fail-soft: any failure logs and
    returns False so the caller can decide whether to skip the post-
    resume volume re-apply.
    """
    try:
        await asyncio.wait_for(
            hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": entity_id,
                    "media_content_id": prev_content_id,
                    "media_content_type": prev_content_type or "music",
                },
                blocking=True,
            ),
            timeout=NOTIFY_SERVICE_TIMEOUT,
        )
        _LOGGER.debug("Restored media on %s after TTS", entity_id)
        return True
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Timeout restoring media on %s after TTS (exceeded %ds)",
            entity_id, NOTIFY_SERVICE_TIMEOUT,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Failed to restore media on %s after TTS: %s", entity_id, err,
        )
    return False
