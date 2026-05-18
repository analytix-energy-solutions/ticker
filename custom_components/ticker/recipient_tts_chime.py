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
from homeassistant.helpers import entity_registry as er

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
# BUG-109 iteration 2: cast-platform detection
# ---------------------------------------------------------------------------


async def _is_cast_target(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True if entity_id is served by the cast platform.

    BUG-109: Chromecast/Google Cast devices have a per-media-app volume
    context that differs from the receiver-level volume. A volume_set
    issued before play_media is applied to the previous (now-leaving)
    app context and does not affect the freshly-loaded chime/TTS app.
    The cast-aware delivery path defers volume_set to AFTER each
    play_media + state=playing transition. Non-cast platforms use the
    original simpler pre-set pattern.

    Detection uses the entity registry — the authoritative source for
    which integration owns an entity. We import ``entity_registry`` at
    call time (rather than module top-level) only for the lookup itself;
    the import is at module top so we mirror the pattern used elsewhere
    in the codebase (discovery.py, formatting.py, actions.py).
    """
    try:
        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
        return entry is not None and entry.platform == "cast"
    except Exception:  # noqa: BLE001
        # Defensive: any registry lookup failure (mock states, test
        # harness without registry, hass not yet started) defaults to
        # non-cast so we use the simpler delivery path.
        return False


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
        # BUG-110 b21 (Issue 2): Chromecast keeps the chime URL in
        # ``media_content_id`` after audio ends — content_id alone made
        # this poll wait the full CHIME_WAIT_TIMEOUT (10s) ceiling on
        # cast, producing an ~8s silent gap between chime end and TTS
        # start. State is the reliable signal: if the entity is not
        # actively playing/buffering the chime is over, regardless of
        # what content_id still reports.
        if state.state not in ("playing", "buffering"):
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

    BUG-109 iteration 3 (v1.7.0b17): Cast targets now PRE-SET the
    override volume via the jiggle helper BEFORE ``play_media`` so the
    chime app loads at the override gain (iteration 2's deferred-only
    pattern left the chime's first ~0.5-1s at the wrong volume — a
    devastating regression for short chime audio). Non-cast platforms
    continue with the simpler single pre-set pattern.
    """
    # F-35.2 cold-device consistency (FIX-001 Option A): only apply the
    # override when we successfully captured a snapshot. Cold devices
    # (no volume_level attribute, e.g. idle/off speakers) silently skip
    # the override so we never leave the device's volume permanently
    # changed.
    snapshot_volume: float | None = None
    if volume_level is not None and _is_valid_volume(volume_level):
        snapshot_volume = _snapshot_volume(hass, entity_id)
        if snapshot_volume is None:
            _LOGGER.debug(
                "Skipping volume override on %s — no volume_level "
                "attribute (likely cold device)",
                entity_id,
            )

    is_cast = await _is_cast_target(hass, entity_id)

    # Pre-set override BEFORE play_media so the chime app loads at the
    # target volume. Cast uses the jiggle helper to defeat cast's
    # internal volume cache. BUG-110 b21 (Issue 1): drop the trailing
    # settle on the target volume_set — play_media's context switch
    # supersedes any settle, and skipping it shrinks the audible window
    # where the still-playing prior media is at the override volume by
    # ~200ms. Non-cast platforms don't have the per-app reset so use
    # the simple single set.
    if snapshot_volume is not None:
        if is_cast:
            # BUG-110 b23 (Issue 1 follow-up): pause the still-playing
            # prior media before the jiggle so no audible window exists
            # at the override gain. play_media below resumes audio at
            # the new gain. Gated to cast since pause+jiggle+play is a
            # cast-specific cure for cast's per-app-volume reset.
            await _set_volume_with_jiggle(
                hass, entity_id, float(volume_level),
                skip_final_settle=True,
                pause_before_jiggle=True,
            )
        else:
            await _set_volume(hass, entity_id, float(volume_level))

    try:
        _LOGGER.debug(
            "Pre-TTS chime: calling play_media on %s (chime=%s, announce=%s, "
            "cast=%s)",
            entity_id, chime_id, announce, is_cast,
        )
        # BUG-110 (WONTFIX, v1.7.0b20): Cast's Default Media Receiver has
        # a ~1-2s swallow window when loading a new media context. For a
        # ~1.5s chime on Cast targets that lack MEDIA_ANNOUNCE feature
        # the audible portion lands inside that window. Two experimental
        # workarounds (b18: audio/wav + announce=True; b19: extra.
        # stream_type=LIVE) were tested in-room and either had no effect
        # or caused regressions in TTS audibility. Reverted to baseline:
        # the cast branch is bit-identical to the non-cast branch for
        # play_media. The swallow is an upstream Cast platform limitation
        # — see BUGS.md BUG-110 for documented user-side workarounds.
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
            # Cast: use jiggle for restore (still needs the cache-busting
            # double-set pattern). Non-cast: simple single set.
            if is_cast:
                await _set_volume_with_jiggle(hass, entity_id, snapshot_volume)
            else:
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
    settle: bool = True,
) -> bool:
    """F-35.2: Call ``media_player.volume_set`` fail-soft.

    Returns True if the call succeeded, False if it raised. Failures
    log a warning but never propagate — callers continue with
    chime+TTS at the current volume.

    ``settle``: when True (default) sleep ``VOLUME_SET_SETTLE_DELAY``
    after the service call so platforms like Sonos see the new volume
    on the next call. When False, skip the trailing sleep — used by
    the BUG-110 b21 (Issue 1) "skip_final_settle" path on cast pre-set
    sites where the caller is about to invoke ``play_media``, which
    triggers its own context switch and renders the settle wasteful
    (the audible window where the still-playing prior media is at the
    override volume is shortened by ~200ms).
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
    if settle:
        await asyncio.sleep(VOLUME_SET_SETTLE_DELAY)
    return True


async def _set_volume_with_jiggle(
    hass: HomeAssistant,
    entity_id: str,
    volume_level: float,
    skip_final_settle: bool = False,
    pause_before_jiggle: bool = False,
) -> bool:
    """Set volume reliably across cast platforms via a two-step pattern.

    Cast devices (Chromecast, Google Home) cache their volume internally
    and may ignore ``volume_set`` calls when the requested value matches
    that internal cache — even when HA's ``volume_level`` attribute shows
    a different value, because HA's view can desync from the cast
    device's actual state.

    The fix Hans empirically validated in a prior automation: send a
    distinct intermediate value ("jiggle") first, then the real target.
    Cast sees two transitions and physically applies the second one.

    Jiggle magnitude per Hans's working pattern: ``target - 0.25`` (or
    ``target + 0.25`` when target is too small to subtract from). On
    non-cast platforms the extra service call is wasted but harmless;
    we accept the small inefficiency for cross-platform reliability.

    ``skip_final_settle`` (BUG-110 b21, Issue 1): when True the trailing
    settle sleep after the TARGET call is skipped. The mid-jiggle settle
    is preserved unconditionally — cast needs to register the distinct
    intermediate value or it collapses the pair into one transition.
    Callers should pass True only when about to invoke ``play_media``
    immediately after; play_media's context switch supersedes the
    settle and the saved ~200ms shrinks the audible window where the
    still-playing prior media plays at the override volume. Cast
    acknowledges ``volume_set`` within ~15ms (faster than play_media
    takes effect), so the target is applied before chime audio.

    ``pause_before_jiggle`` (BUG-110 b23, Issue 1 follow-up): when True
    AND the entity is currently in ``state="playing"`` (narrow match —
    NOT ``"buffering"``), issue ``media_player.media_pause`` before the
    jiggle so the still-playing prior media is muted before any volume
    transition becomes audible. Eliminates the residual ~200ms audible
    window left after b21 where the override volume was briefly audible
    on the prior media. The pause call is fail-soft (broad Exception
    catch, log warning, continue) matching the ``_set_volume`` envelope;
    a settle delay follows so cast quiesces before the jiggle's first
    volume_set hits. Subsequent ``play_media`` resumes audio at the
    new gain — hence the pattern name "pause-jiggle-play". Gating is
    at call sites; this helper stays platform-agnostic.

    Returns True if both calls succeeded; False if either raised.
    Both calls are attempted regardless of the first's outcome —
    fail-soft contract preserved across BUG-109 history.
    """
    # BUG-110 b23 (Issue 1 follow-up): optionally pause currently-playing
    # media before any volume transition so the audible-window-on-prior-
    # media problem disappears. Narrow state check ("playing" only —
    # NOT "buffering") avoids pausing transient mid-load states.
    if pause_before_jiggle:
        state = hass.states.get(entity_id)
        if state is not None and state.state == "playing":
            try:
                await asyncio.wait_for(
                    hass.services.async_call(
                        "media_player", "media_pause",
                        {"entity_id": entity_id},
                        blocking=True,
                    ),
                    timeout=NOTIFY_SERVICE_TIMEOUT,
                )
                # Let the cast app quiesce before the jiggle's first
                # volume_set so the pause has fully taken effect.
                await asyncio.sleep(VOLUME_SET_SETTLE_DELAY)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Pause-before-jiggle failed on %s: %s — proceeding "
                    "with jiggle anyway",
                    entity_id, err,
                )

    # Pick a jiggle value that's distinct from the target.
    if volume_level >= 0.25:
        jiggle = max(0.0, volume_level - 0.25)
    else:
        jiggle = min(1.0, volume_level + 0.25)

    # Mid-jiggle settle stays unconditionally — cast must register the
    # distinct intermediate value, otherwise it may collapse jiggle+target
    # into a single transition and the cache-busting effect is lost.
    ok1 = await _set_volume(hass, entity_id, jiggle)
    ok2 = await _set_volume(
        hass, entity_id, volume_level, settle=not skip_final_settle,
    )
    return ok1 and ok2
