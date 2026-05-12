"""TTS delivery sub-pipeline — chime, volume, snapshot/restore branches.

Extracted from ``recipient_tts.py`` to keep both files under the 500-line
limit while F-35.2 adds a snapshot/set/restore window for the volume
override (``media_player.volume_set`` before chime + restore after TTS).

The orchestrator ``async_send_tts`` lives in ``recipient_tts.py``; this
module owns the three per-mode delivery functions plus the chime/volume
helpers they share. ``recipient_tts.py`` re-exports the public-shape
helpers (``_resolve_chime``, ``_play_chime``, ``_deliver_tts_*``,
``_wait_for_state*``, ``_call_tts_service``, ``_get_supported_features``)
so existing imports continue to work unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CHIME_WAIT_TIMEOUT,
    CHIME_TTS_GAP,
    NOTIFY_SERVICE_TIMEOUT,
    TTS_PLAYBACK_MAX_TIMEOUT,
    TTS_PLAYBACK_START_TIMEOUT,
    TTS_POLL_INTERVAL,
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
    VOLUME_SET_SETTLE_DELAY,
)

_LOGGER = logging.getLogger(__name__)


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


async def _wait_for_chime_complete(
    hass: HomeAssistant,
    entity_id: str,
    chime_url: str,
    timeout: float = CHIME_WAIT_TIMEOUT,
    poll_interval: float = 0.2,
    detect_window: float = 1.5,
) -> None:
    """F-35: Wait for the chime to actually finish playing on entity_id.

    Polls the entity's ``media_content_id`` attribute. Phase 1: wait
    briefly for content_id to indicate the chime is playing (filename
    match handles platforms that normalize the URL). Phase 2: wait for
    content_id to change away (chime ended).

    Falls back to a fixed ``CHIME_TTS_GAP`` delay when the platform
    never exposes the chime in its content_id (e.g. tts engines that
    play through a non-media_player path, or platforms with stale
    state attribute updates). The fallback total dead-air budget
    matches ``CHIME_TTS_GAP`` so worst-case behavior is identical to
    the prior fixed-delay approach.

    The ``timeout`` cap prevents hanging when content_id sticks (e.g.
    a chime that loops). At timeout we fall through and let TTS start
    on top of any remaining chime audio.
    """
    chime_marker = chime_url.rsplit("/", 1)[-1] if "/" in chime_url else chime_url
    _LOGGER.debug(
        "Pre-TTS chime: waiting for chime '%s' to finish on %s "
        "(timeout=%.1fs, detect_window=%.1fs, poll=%.2fs)",
        chime_marker, entity_id, timeout, detect_window, poll_interval,
    )

    def _is_chime_now() -> bool:
        state = hass.states.get(entity_id)
        if not state:
            return False
        current = state.attributes.get("media_content_id") or ""
        return chime_marker in current or current == chime_url

    # Phase 1: wait briefly for the chime to register on the entity
    elapsed = 0.0
    started = False
    while elapsed < detect_window:
        if _is_chime_now():
            started = True
            _LOGGER.debug(
                "Pre-TTS chime: detected on %s after %.2fs",
                entity_id, elapsed,
            )
            break
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    if not started:
        # Platform doesn't expose chime in content_id — fall back to
        # the fixed gap so we still give the chime time to play.
        fallback = max(0.0, CHIME_TTS_GAP - elapsed)
        _LOGGER.debug(
            "Pre-TTS chime: not observed in content_id on %s within "
            "%.1fs; falling back to %.1fs fixed delay",
            entity_id, detect_window, fallback,
        )
        await asyncio.sleep(fallback)
        return

    # Phase 2: wait for chime to end (content_id changes away)
    while elapsed < timeout:
        if not _is_chime_now():
            _LOGGER.debug(
                "Pre-TTS chime: completed on %s after %.2fs total",
                entity_id, elapsed,
            )
            return
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    _LOGGER.debug(
        "Pre-TTS chime: timeout (%.1fs) on %s — yielding to TTS",
        timeout, entity_id,
    )


# ---------------------------------------------------------------------------
# F-35: chime resolution + playback
# ---------------------------------------------------------------------------


def _resolve_chime(
    recipient: dict[str, Any],
    category: dict[str, Any] | None,
) -> str | None:
    """F-35: Return the chime media_content_id to play, or None.

    Category override wins when non-empty; recipient default is used
    otherwise. Empty/missing at both levels returns None.
    """
    for src in (category, recipient):
        if not src:
            continue
        raw = src.get("chime_media_content_id") or ""
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


async def _play_chime(
    hass: HomeAssistant,
    entity_id: str,
    chime_id: str,
    announce: bool = False,
    volume_level: float | None = None,
) -> None:
    """F-35: Play a pre-TTS chime on entity_id, fail-soft.

    F-35.2: When ``volume_level`` is supplied (in [0.0, 1.0]) the call
    snapshots the entity's current ``volume_level`` attribute, sets the
    override volume, plays the chime, waits for it to finish, and
    restores the snapshotted volume — local to this helper so isolated
    callers (test chime path) don't leave the device's volume changed.
    """
    # F-35.2 cold-device consistency (FIX-001 Option A): only apply the
    # override when we successfully captured a snapshot. Cold devices
    # (no volume_level attribute, e.g. idle/off speakers) silently skip
    # the override so we never leave the device's volume permanently
    # changed. Mirrors `_deliver_tts_with_restore`.
    snapshot_volume: float | None = None
    if volume_level is not None and _is_valid_volume(volume_level):
        snapshot_volume = _snapshot_volume(hass, entity_id)
        if snapshot_volume is not None:
            await _set_volume(hass, entity_id, float(volume_level))
        else:
            _LOGGER.debug(
                "Skipping volume override on %s — no volume_level "
                "attribute (likely cold device)",
                entity_id,
            )

    try:
        _LOGGER.debug(
            "Pre-TTS chime: calling play_media on %s (chime=%s, announce=%s)",
            entity_id, chime_id, announce,
        )
        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    "media_player", "play_media",
                    {
                        "entity_id": entity_id,
                        "media_content_id": chime_id,
                        "media_content_type": "music",
                        "announce": announce,
                    },
                    blocking=True,
                ),
                timeout=NOTIFY_SERVICE_TIMEOUT,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Pre-TTS chime failed on %s: %s — proceeding with TTS",
                entity_id, err,
            )
            return

        # Wait for chime audio to actually finish before yielding to TTS.
        # Poll the entity's media_content_id attribute: when it matches
        # the chime URL the chime is playing, when it changes away the
        # chime is done. This is deterministic on platforms that update
        # content_id (HA Voice, most cast/Sonos integrations). For
        # platforms that never expose the chime in content_id we fall
        # back to a CHIME_TTS_GAP fixed delay.
        await _wait_for_chime_complete(hass, entity_id, chime_id)
    finally:
        if snapshot_volume is not None:
            await _set_volume(hass, entity_id, snapshot_volume)


# ---------------------------------------------------------------------------
# F-35.2: volume resolve + set/snapshot/restore
# ---------------------------------------------------------------------------


def _is_valid_volume(value: Any) -> bool:
    """Return True if ``value`` is a numeric volume in [0.0, 1.0]."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and VOLUME_OVERRIDE_MIN <= float(value) <= VOLUME_OVERRIDE_MAX
    )


def _resolve_volume(
    recipient: dict[str, Any],
    category: dict[str, Any] | None,
) -> float | None:
    """F-35.2: Return the override volume to apply, or None.

    Category override wins when present and in-range; recipient default
    is used otherwise. Out-of-range or missing at both levels returns
    None (no volume change — current behavior).
    """
    for src in (category, recipient):
        if not src:
            continue
        raw = src.get("volume_override")
        if _is_valid_volume(raw):
            return float(raw)
    return None


def _snapshot_volume(hass: HomeAssistant, entity_id: str) -> float | None:
    """Capture the entity's current volume_level attribute, or None."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    raw = state.attributes.get("volume_level")
    if _is_valid_volume(raw):
        return float(raw)
    return None


async def _set_volume(
    hass: HomeAssistant,
    entity_id: str,
    volume_level: float,
) -> bool:
    """F-35.2: Call ``media_player.volume_set`` fail-soft.

    Returns True if the call succeeded (and we slept for the settle
    delay), False if it raised. Failures log a warning but never
    propagate — callers continue with chime+TTS at the current volume.
    """
    try:
        await asyncio.wait_for(
            hass.services.async_call(
                "media_player", "volume_set",
                {"entity_id": entity_id, "volume_level": float(volume_level)},
                blocking=True,
            ),
            timeout=NOTIFY_SERVICE_TIMEOUT,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Volume override set failed on %s (volume=%.2f): %s — proceeding",
            entity_id, volume_level, err,
        )
        return False
    # Some platforms (Sonos) need a moment to apply the change before the
    # next service call sees the new volume.
    await asyncio.sleep(VOLUME_SET_SETTLE_DELAY)
    return True


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
