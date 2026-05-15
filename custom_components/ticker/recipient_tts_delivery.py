"""TTS delivery sub-pipeline — per-mode delivery branches.

Extracted from ``recipient_tts.py`` (F-35.2) and further split (v1.7.0
preflight, alongside F-37) when the chime+volume helpers grew past
the 500-line limit. This module now owns:

* State-polling helpers (``_wait_for_state``, ``_wait_for_state_exit``)
  used by the three delivery branches to bracket the chime+TTS window.
* Low-level service helpers (``_get_supported_features``,
  ``_call_tts_service``).
* The three per-mode delivery functions
  (``_deliver_tts_announce``, ``_deliver_tts_with_restore``,
  ``_deliver_tts_plain``).

The chime and volume primitives (``_resolve_chime``, ``_play_chime``,
``_wait_for_chime_complete``, ``_is_valid_volume``, ``_resolve_volume``,
``_snapshot_volume``, ``_set_volume``) live in
``recipient_tts_chime.py``. They are re-exported below so that callers
and tests using ``recipient_tts_delivery.<helper>`` (including
``patch("…recipient_tts_delivery._play_chime")``) continue to work
unchanged.

State-polling helpers (`_wait_for_state`, `_wait_for_state_exit`)
must remain defined in this module because the delivery branches call
them as bare names and tests patch them at this module's path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    NOTIFY_SERVICE_TIMEOUT,
    TTS_PLAYBACK_MAX_TIMEOUT,
    TTS_PLAYBACK_START_TIMEOUT,
    TTS_POLL_INTERVAL,
)
from .recipient_tts_chime import (
    _is_valid_volume,
    _play_chime,
    _resolve_chime,
    _resolve_volume,
    _set_volume,
    _snapshot_volume,
    _wait_for_chime_complete,
)

_LOGGER = logging.getLogger(__name__)

# Re-export the chime+volume helpers so external imports through this
# module continue to resolve, and so test patches at
# ``recipient_tts_delivery.<helper>`` still intercept the call sites
# inside this file (which reference these names as locals).
__all__ = [
    "_call_tts_service",
    "_deliver_tts_announce",
    "_deliver_tts_plain",
    "_deliver_tts_with_restore",
    "_get_supported_features",
    "_is_valid_volume",
    "_play_chime",
    "_resolve_chime",
    "_resolve_volume",
    "_set_volume",
    "_snapshot_volume",
    "_wait_for_chime_complete",
    "_wait_for_state",
    "_wait_for_state_exit",
]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _get_supported_features(hass: HomeAssistant, entity_id: str) -> int:
    """Read supported_features from a media_player entity state."""
    state = hass.states.get(entity_id)
    if state is None:
        return 0
    return int(state.attributes.get("supported_features", 0))


async def _call_tts_service(
    hass: HomeAssistant,
    tts_service: str,
    payload: dict[str, Any],
) -> None:
    """Call the TTS service with a timeout."""
    domain, service_name = tts_service.split(".", 1)
    await asyncio.wait_for(
        hass.services.async_call(domain, service_name, payload, blocking=True),
        timeout=NOTIFY_SERVICE_TIMEOUT,
    )


async def _wait_for_state(
    hass: HomeAssistant,
    entity_id: str,
    target_state: str,
    timeout: float = TTS_PLAYBACK_START_TIMEOUT,
    poll_interval: float = TTS_POLL_INTERVAL,
) -> bool:
    """Poll until entity reaches target_state or timeout expires."""
    elapsed = 0.0
    while elapsed < timeout:
        state = hass.states.get(entity_id)
        if state and state.state == target_state:
            return True
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    _LOGGER.debug("Timeout waiting for %s to reach '%s'", entity_id, target_state)
    return False


async def _wait_for_state_exit(
    hass: HomeAssistant,
    entity_id: str,
    exit_state: str,
    timeout: float = TTS_PLAYBACK_MAX_TIMEOUT,
    poll_interval: float = TTS_POLL_INTERVAL,
) -> bool:
    """Poll until entity exits exit_state or timeout expires."""
    elapsed = 0.0
    while elapsed < timeout:
        state = hass.states.get(entity_id)
        if state and state.state != exit_state:
            return True
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    _LOGGER.debug("Timeout waiting for %s to exit '%s'", entity_id, exit_state)
    return False


# ---------------------------------------------------------------------------
# Delivery branches: announce / restore / plain
# ---------------------------------------------------------------------------


async def _deliver_tts_announce(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
    chime_id: str | None = None,
    volume_level: float | None = None,
) -> str:
    """Deliver TTS via announce mode (platform handles pause/resume).

    F-35.2: when ``volume_level`` is set, snapshot the device's current
    volume_level, set the override before the chime, deliver chime+TTS,
    then restore the previous volume after TTS exits playing. HA's
    announce protocol may itself adjust volume on some platforms; we
    apply the override anyway and rely on the post-TTS restore to put
    the device back where it started.
    """
    _LOGGER.debug(
        "TTS announce delivery to %s via %s (chime=%s, vol=%s)",
        entity_id, tts_service, bool(chime_id), volume_level,
    )
    # F-35.2 cold-device consistency (FIX-001 Option A): only apply the
    # override when we successfully captured a snapshot.
    snap_vol: float | None = None
    vol_target: float | None = None
    if volume_level is not None and _is_valid_volume(volume_level):
        snap_vol = _snapshot_volume(hass, entity_id)
        if snap_vol is not None:
            vol_target = float(volume_level)
            await _set_volume(hass, entity_id, vol_target)
        else:
            _LOGGER.debug(
                "Skipping volume override on %s — no volume_level "
                "attribute (likely cold device)",
                entity_id,
            )
    try:
        if chime_id:
            await _play_chime(hass, entity_id, chime_id, announce=True)
        await _call_tts_service(hass, tts_service, payload)
        # Wait for TTS to enter and exit 'playing' so we restore volume
        # only after the announcement has finished. Skip when there is
        # no volume override to keep current announce-mode behavior
        # (HA's announce protocol owns its own pause/resume window).
        if snap_vol is not None:
            await _wait_for_state(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_START_TIMEOUT,
            )
            await _wait_for_state_exit(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_MAX_TIMEOUT,
            )
    finally:
        if snap_vol is not None and vol_target is not None:
            await _set_volume(hass, entity_id, snap_vol)
    return "announce"


async def _deliver_tts_with_restore(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
    chime_id: str | None = None,
    volume_level: float | None = None,
) -> str:
    """Deliver TTS with manual snapshot/restore of media state.

    Snapshot covers media + (F-35.2) volume — captured BEFORE the chime
    so the entire chime+TTS window is wrapped. Volume restore runs
    regardless of whether ``prev_state == "playing"``: putting the user's
    chosen volume back is always safe even when no media resumes.
    """
    state_obj = hass.states.get(entity_id)
    prev_state = state_obj.state if state_obj else None
    prev_content_id = (
        state_obj.attributes.get("media_content_id") if state_obj else None
    )
    prev_content_type = (
        state_obj.attributes.get("media_content_type") if state_obj else None
    )
    # F-35.2: capture volume in the same snapshot window.
    # FIX-001 Option A: cold-device consistency — only apply the
    # override when we successfully captured a snapshot.
    snap_vol: float | None = None
    vol_target: float | None = None
    if volume_level is not None and _is_valid_volume(volume_level):
        snap_vol = _snapshot_volume(hass, entity_id)
        if snap_vol is not None:
            vol_target = float(volume_level)
        else:
            _LOGGER.debug(
                "Skipping volume override on %s — no volume_level "
                "attribute (likely cold device)",
                entity_id,
            )

    _LOGGER.debug(
        "TTS restore delivery to %s (prev_state=%s, has_content=%s, "
        "chime=%s, vol=%s)",
        entity_id, prev_state, bool(prev_content_id),
        bool(chime_id), volume_level,
    )

    # Apply override volume between snapshot and chime.
    if snap_vol is not None and vol_target is not None:
        await _set_volume(hass, entity_id, vol_target)

    if chime_id:
        await _play_chime(hass, entity_id, chime_id)

    await _call_tts_service(hass, tts_service, payload)

    # Wait for TTS to actually finish before restoring.
    await _wait_for_state(
        hass, entity_id, "playing", timeout=TTS_PLAYBACK_START_TIMEOUT,
    )
    await _wait_for_state_exit(
        hass, entity_id, "playing", timeout=TTS_PLAYBACK_MAX_TIMEOUT,
    )

    # Restore previous media if it was playing.
    if prev_state == "playing" and prev_content_id:
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
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout restoring media on %s after TTS (exceeded %ds)",
                entity_id, NOTIFY_SERVICE_TIMEOUT,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to restore media on %s after TTS: %s", entity_id, err,
            )

    # F-35.2: restore the snapshotted volume after the media-restore
    # branch — safe whether or not media resumed.
    if snap_vol is not None:
        await _set_volume(hass, entity_id, snap_vol)

    return "restore"


async def _deliver_tts_plain(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
    chime_id: str | None = None,
    volume_level: float | None = None,
) -> str:
    """Deliver TTS with no announce or restore — plain fire-and-forget.

    F-35.2: when ``volume_level`` is set, wraps chime+TTS in a
    snapshot/set/restore window so the user's volume returns to its
    previous level after TTS exits ``playing``.
    """
    _LOGGER.debug(
        "TTS plain delivery to %s via %s (chime=%s, vol=%s)",
        entity_id, tts_service, bool(chime_id), volume_level,
    )
    # F-35.2 cold-device consistency (FIX-001 Option A): only apply the
    # override when we successfully captured a snapshot.
    snap_vol: float | None = None
    vol_target: float | None = None
    if volume_level is not None and _is_valid_volume(volume_level):
        snap_vol = _snapshot_volume(hass, entity_id)
        if snap_vol is not None:
            vol_target = float(volume_level)
            await _set_volume(hass, entity_id, vol_target)
        else:
            _LOGGER.debug(
                "Skipping volume override on %s — no volume_level "
                "attribute (likely cold device)",
                entity_id,
            )
    try:
        if chime_id:
            await _play_chime(hass, entity_id, chime_id)
        await _call_tts_service(hass, tts_service, payload)
        if snap_vol is not None:
            # Wait for TTS to start + exit playing before restoring volume.
            await _wait_for_state(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_START_TIMEOUT,
            )
            await _wait_for_state_exit(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_MAX_TIMEOUT,
            )
    finally:
        if snap_vol is not None and vol_target is not None:
            await _set_volume(hass, entity_id, snap_vol)
    return "plain"
