"""F-35 / F-35.2 chime + volume helpers for the TTS delivery pipeline.

Extracted from ``recipient_tts_delivery.py`` to keep both files under
the 500-line limit. This module owns:

* Chime resolution and playback (``_resolve_chime``, ``_play_chime``,
  ``_wait_for_chime_complete``).
* Volume snapshot / set / restore primitives (``_is_valid_volume``,
  ``_resolve_volume``, ``_snapshot_volume``, ``_set_volume``).

The three per-mode delivery functions (`_deliver_tts_announce`,
`_deliver_tts_with_restore`, `_deliver_tts_plain`) remain in
``recipient_tts_delivery.py``; they import these helpers and continue
to call them as bare names, so existing test patches that target
``recipient_tts_delivery.<helper>`` continue to work via the re-export
shim in that module.

The state-polling helpers (`_wait_for_state`, `_wait_for_state_exit`)
also remain in ``recipient_tts_delivery.py`` because numerous tests
patch them at that module path.
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
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
    VOLUME_SET_SETTLE_DELAY,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# F-35: chime completion polling
# ---------------------------------------------------------------------------


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
