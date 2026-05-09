"""TTS notification delivery for Ticker recipients (orchestrator).

The per-mode delivery functions, chime/volume helpers, and state-poll
helpers live in ``recipient_tts_delivery.py`` to keep both files under
the 500-line limit. This module owns the public ``async_send_tts``
orchestrator and the delivery-failure logger, and re-exports the
delivery helpers under their original names so existing imports
(``from .recipient_tts import _deliver_tts_announce`` etc.) continue
to work unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_SENT,
    MEDIA_ANNOUNCE_FEATURE,
    NOTIFY_SERVICE_TIMEOUT,
    TTS_BUFFER_DELAY_DEFAULT,
)
from .formatting import build_tts_payload
from .recipient_tts_delivery import (
    _call_tts_service,
    _deliver_tts_announce,
    _deliver_tts_plain,
    _deliver_tts_with_restore,
    _get_supported_features,
    _play_chime,
    _resolve_chime,
    _resolve_volume,
    _set_volume,
    _snapshot_volume,
    _wait_for_state,
    _wait_for_state_exit,
)

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Re-exports: tests and recipient_helpers import these names directly
# from this module. Keep the alias surface stable across the F-35.2
# split so no test-import churn is required.
__all__ = [
    "_call_tts_service",
    "_deliver_tts_announce",
    "_deliver_tts_plain",
    "_deliver_tts_with_restore",
    "_get_supported_features",
    "_play_chime",
    "_resolve_chime",
    "_resolve_volume",
    "_set_volume",
    "_snapshot_volume",
    "_wait_for_state",
    "_wait_for_state_exit",
    "async_send_tts",
    "log_delivery_failure",
]


async def log_delivery_failure(
    store: "TickerStore",
    category_id: str,
    person_id: str,
    person_name: str,
    title: str,
    message: str,
    notify_service: str,
    reason: str,
    notification_id: str | None,
    image_url: str | None,
) -> None:
    """Log a failed delivery attempt (shared by push and TTS paths)."""
    await store.async_add_log(
        category_id=category_id,
        person_id=person_id,
        person_name=person_name,
        title=title,
        message=message,
        outcome=LOG_OUTCOME_FAILED,
        notify_service=notify_service,
        reason=reason,
        notification_id=notification_id,
        image_url=image_url,
    )


async def async_send_tts(
    hass: HomeAssistant,
    store: "TickerStore",
    recipient: dict[str, Any],
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
    notification_id: str | None = None,
    volume: float | None = None,
) -> dict[str, list[str]]:
    """Send a TTS notification to a recipient's media player.

    Uses a 3-step priority system for delivery:
    1. Announce mode — if the media player supports MEDIA_ANNOUNCE, HA
       handles pause/resume automatically. resume_after_tts is ignored.
    2. Snapshot/restore — if resume_after_tts is True and no announce
       support, manually snapshots and restores the media state.
    3. Plain — simple tts.speak call with no resume behavior.

    Args:
        hass: Home Assistant instance.
        store: Ticker store.
        recipient: Recipient dict (device_type='tts').
        category_id: Category being notified.
        title: Notification title (not spoken).
        message: Message text to speak.
        data: Optional extra data dict.
        notification_id: Unique notification call ID for log grouping.
        volume: F-35.2 — explicit volume override (e.g. for the test
            chime path). When None, resolved from the recipient default
            and category override via ``_resolve_volume``.

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists.
    """
    results: dict[str, list[str]] = {"delivered": [], "queued": [], "dropped": []}
    recipient_id = recipient["recipient_id"]
    recipient_name = recipient.get("name", recipient_id)
    person_id = f"recipient:{recipient_id}"
    image_url = data.get("image") if data else None

    entity_id = recipient.get("media_player_entity_id")
    if not entity_id:
        _LOGGER.warning("TTS recipient %s has no media_player_entity_id", recipient_id)
        await store.async_add_log(
            category_id=category_id, person_id=person_id,
            person_name=recipient_name, title=title, message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No media_player_entity_id configured",
            notification_id=notification_id, image_url=image_url,
        )
        results["dropped"].append(f"{person_id}: No media player")
        return results

    tts_service = recipient.get("tts_service") or "tts.speak"
    payload = build_tts_payload(message, entity_id, tts_service)

    # F-35 §5.2: pre-playback delay (Chromecast). Runs BEFORE the chime.
    buffer_delay = recipient.get("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT)
    if buffer_delay > 0:
        _LOGGER.debug(
            "TTS buffer delay: waiting %.1fs for %s", buffer_delay, entity_id,
        )
        await asyncio.sleep(buffer_delay)

    # Best-effort category fetch — chime + volume both resolve from this.
    category: dict[str, Any] | None = None
    try:
        category = store.get_category(category_id)
    except Exception:  # noqa: BLE001
        category = None
    chime_id = _resolve_chime(recipient, category)

    # F-35.2: explicit caller-supplied volume wins (test-chime path);
    # otherwise resolve recipient default vs. category override.
    volume_level: float | None
    if volume is not None:
        volume_level = volume
    else:
        volume_level = _resolve_volume(recipient, category)

    features = _get_supported_features(hass, entity_id)
    supports_announce = bool(features & MEDIA_ANNOUNCE_FEATURE)
    resume = recipient.get("resume_after_tts", False)

    try:
        if supports_announce:
            method = await _deliver_tts_announce(
                hass, entity_id, tts_service, payload,
                chime_id=chime_id, volume_level=volume_level,
            )
        elif resume:
            method = await _deliver_tts_with_restore(
                hass, entity_id, tts_service, payload,
                chime_id=chime_id, volume_level=volume_level,
            )
        else:
            method = await _deliver_tts_plain(
                hass, entity_id, tts_service, payload,
                chime_id=chime_id, volume_level=volume_level,
            )

        svc_display = f"{tts_service} -> {entity_id} [{method}]"
        _LOGGER.info(
            "Sent TTS notification to %s via %s", recipient_id, svc_display,
        )
        await store.async_add_log(
            category_id=category_id, person_id=person_id,
            person_name=recipient_name, title=title, message=message,
            outcome=LOG_OUTCOME_SENT, notify_service=svc_display,
            notification_id=notification_id, image_url=image_url,
        )
        results["delivered"].append(svc_display)

    except asyncio.TimeoutError:
        _LOGGER.error(
            "Timeout sending TTS to %s (exceeded %ds)",
            recipient_id, NOTIFY_SERVICE_TIMEOUT,
        )
        await log_delivery_failure(
            store, category_id, person_id, recipient_name, title, message,
            tts_service, f"Timeout after {NOTIFY_SERVICE_TIMEOUT}s",
            notification_id, image_url,
        )
        results["dropped"].append(f"{tts_service}: Timeout")

    except HomeAssistantError as err:
        _LOGGER.error("Failed TTS to %s: %s", recipient_id, err)
        await log_delivery_failure(
            store, category_id, person_id, recipient_name, title, message,
            tts_service, str(err), notification_id, image_url,
        )
        results["dropped"].append(f"{tts_service}: {err}")

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Unexpected TTS error for %s: %s", recipient_id, err)
        await log_delivery_failure(
            store, category_id, person_id, recipient_name, title, message,
            tts_service, str(err), notification_id, image_url,
        )
        results["dropped"].append(f"{tts_service}: {err}")

    return results
