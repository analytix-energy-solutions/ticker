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
``recipient_tts_chime.py``. ``_restore_previous_media`` lives in
``recipient_tts_cast.py``. They are re-exported below so that callers
and tests using ``recipient_tts_delivery.<helper>`` (including
``patch("…recipient_tts_delivery._play_chime")``) continue to work
unchanged.

State-polling helpers (`_wait_for_state`, `_wait_for_state_exit`)
must remain defined in this module because the delivery branches call
them as bare names and tests patch them at this module's path.

BUG-109 iteration 3 (v1.7.0b17): cast branches use a **hybrid**
pre-set + deferred re-apply pattern. The earlier deferred-only
pattern (b16) left brief audible gaps on cast because the chime/
resumed-media app loaded at the cast receiver's then-current volume
before our subsequent ``volume_set`` landed. The hybrid pre-sets
BEFORE ``play_media`` (so the new app context loads at the desired
volume) AND keeps the deferred re-apply on TTS (defensive — confirmed
working at b16). See DESIGN_DECISIONS.md #49 iteration 3.
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
from .recipient_tts_cast import _restore_previous_media
from .recipient_tts_chime import (
    _is_cast_target,
    _is_valid_volume,
    _play_chime,
    _resolve_chime,
    _resolve_volume,
    _set_volume,
    _set_volume_with_jiggle,
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
    "_is_cast_target",
    "_is_valid_volume",
    "_play_chime",
    "_resolve_chime",
    "_resolve_volume",
    "_restore_previous_media",
    "_set_volume",
    "_set_volume_with_jiggle",
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
    then restore the previous volume after TTS exits playing.

    BUG-109 iteration 2: Cast devices do not advertise MEDIA_ANNOUNCE
    support, so they never enter this branch. Non-cast announce-capable
    platforms (HA Voice, Sonos) manage their own per-app volume context
    internally and do not need the cast-specific jiggle/timing
    workarounds. This branch therefore uses the simpler pre-BUG-109
    single-set pattern.
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

    BUG-109 iteration 3 (cast hybrid). Non-cast: unchanged simple flow.
    Cast: pre-set BEFORE every ``play_media`` (chime + resume) AND
    deferred re-apply after TTS state=playing (defensive — see
    DESIGN_DECISIONS.md #49 iteration 3). Resume path additionally
    re-applies the snapshot volume after the resumed media reaches
    state=playing so cast's per-app context lands on the correct gain.
    """
    state_obj = hass.states.get(entity_id)
    prev_state = state_obj.state if state_obj else None
    prev_content_id = (
        state_obj.attributes.get("media_content_id") if state_obj else None
    )
    prev_content_type = (
        state_obj.attributes.get("media_content_type") if state_obj else None
    )
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

    is_cast = await _is_cast_target(hass, entity_id)

    _LOGGER.debug(
        "TTS restore delivery to %s (prev_state=%s, has_content=%s, "
        "chime=%s, vol=%s, cast=%s)",
        entity_id, prev_state, bool(prev_content_id),
        bool(chime_id), volume_level, is_cast,
    )

    # CHIME pre-set: cast uses jiggle so the chime app loads at the
    # override volume; non-cast uses the simple single set. BUG-110
    # b21 (Issue 1): drop trailing settle on cast — play_media's
    # context switch supersedes it and we shrink the audible
    # pre-chime override window on the prior media by ~200ms.
    # BUG-110 b23 (Issue 1 follow-up): pause the still-playing prior
    # media before the jiggle so no audible window at the override
    # gain remains; play_media(chime) resumes audio at the new gain.
    if snap_vol is not None and vol_target is not None:
        if is_cast:
            await _set_volume_with_jiggle(
                hass, entity_id, vol_target,
                skip_final_settle=True,
                pause_before_jiggle=True,
            )
        else:
            await _set_volume(hass, entity_id, vol_target)

    if chime_id:
        await _play_chime(hass, entity_id, chime_id)

    await _call_tts_service(hass, tts_service, payload)

    # Wait for TTS to actually start playing.
    await _wait_for_state(
        hass, entity_id, "playing", timeout=TTS_PLAYBACK_START_TIMEOUT,
    )

    # Cast TTS deferred re-apply — TTS may load a new app context that
    # would otherwise reset cast's per-app volume.
    if snap_vol is not None and vol_target is not None and is_cast:
        await _set_volume_with_jiggle(hass, entity_id, vol_target)

    # Wait for TTS to exit playing.
    await _wait_for_state_exit(
        hass, entity_id, "playing", timeout=TTS_PLAYBACK_MAX_TIMEOUT,
    )

    # Restore previous media if it was playing.
    resumed = False
    if prev_state == "playing" and prev_content_id:
        # RESUME pre-set (cast): set snapshot volume BEFORE play_media
        # so the resumed media app loads at the right gain (eliminates
        # the brief loud "blip" observed in iteration 2 testing).
        # BUG-110 b21 (Issue 1): skip trailing settle — play_media
        # for the resume context switch supersedes it.
        if snap_vol is not None and is_cast:
            await _set_volume_with_jiggle(
                hass, entity_id, snap_vol, skip_final_settle=True,
            )

        resumed = await _restore_previous_media(
            hass, entity_id, prev_content_id, prev_content_type,
        )
        if resumed:
            # BUG-109: wait for the resumed media to actually start
            # playing before sending the defensive volume re-apply.
            await _wait_for_state(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_START_TIMEOUT,
            )
            # Cast: defensive re-apply on the freshly-loaded resume app.
            if snap_vol is not None and is_cast:
                await _set_volume_with_jiggle(hass, entity_id, snap_vol)

    # Final restore: cast covered above when resumed; non-cast (and
    # cast no-resume) needs a final set so the user's volume is back
    # to snapshot.
    if snap_vol is not None and not (is_cast and resumed):
        if is_cast:
            await _set_volume_with_jiggle(hass, entity_id, snap_vol)
        else:
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

    BUG-109 iteration 3 (cast hybrid). Non-cast: unchanged simple flow
    (single pre-set + single restore). Cast: pre-set BEFORE
    ``play_media(chime)`` AND deferred re-apply after TTS state=playing.
    No resume step on this path; only the final restore at the end.
    """
    _LOGGER.debug(
        "TTS plain delivery to %s via %s (chime=%s, vol=%s)",
        entity_id, tts_service, bool(chime_id), volume_level,
    )
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

    is_cast = await _is_cast_target(hass, entity_id)

    # CHIME pre-set: cast uses jiggle (skip_final_settle so play_media
    # for the chime context switch supersedes the settle, shrinking the
    # audible override window on the prior media by ~200ms — BUG-110
    # b21 Issue 1). BUG-110 b23 (Issue 1 follow-up): also pause the
    # still-playing prior media before the jiggle so no audible
    # override-volume window remains; play_media(chime) resumes audio
    # at the new gain. Non-cast: simple single set with default settle.
    if snap_vol is not None and vol_target is not None:
        if is_cast:
            await _set_volume_with_jiggle(
                hass, entity_id, vol_target,
                skip_final_settle=True,
                pause_before_jiggle=True,
            )
        else:
            await _set_volume(hass, entity_id, vol_target)

    try:
        if chime_id:
            await _play_chime(hass, entity_id, chime_id)
        await _call_tts_service(hass, tts_service, payload)
        if snap_vol is not None:
            # Wait for TTS to start playing.
            await _wait_for_state(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_START_TIMEOUT,
            )
            # Cast TTS deferred re-apply on the freshly-loaded TTS app.
            if vol_target is not None and is_cast:
                await _set_volume_with_jiggle(hass, entity_id, vol_target)
            # Wait for TTS to exit playing before restoring.
            await _wait_for_state_exit(
                hass, entity_id, "playing",
                timeout=TTS_PLAYBACK_MAX_TIMEOUT,
            )
    finally:
        if snap_vol is not None and vol_target is not None:
            if is_cast:
                await _set_volume_with_jiggle(hass, entity_id, snap_vol)
            else:
                await _set_volume(hass, entity_id, snap_vol)
    return "plain"
