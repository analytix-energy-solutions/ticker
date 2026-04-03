"""TTS notification delivery for Ticker recipients.

Handles sending TTS notifications to media_player entities. Extracted from
recipient_notify.py to enable future announce/restore functionality (F-19)
without bloating the push notification path.
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
    TTS_PLAYBACK_MAX_TIMEOUT,
    TTS_PLAYBACK_START_TIMEOUT,
    TTS_POLL_INTERVAL,
)
from .formatting import build_tts_payload

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


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


def _get_supported_features(hass: HomeAssistant, entity_id: str) -> int:
    """Read supported_features from a media_player entity state.

    Args:
        hass: Home Assistant instance.
        entity_id: The media_player entity ID.

    Returns:
        Integer bitmask of supported features, or 0 if unavailable.
    """
    state = hass.states.get(entity_id)
    if state is None:
        return 0
    return int(state.attributes.get("supported_features", 0))


async def _call_tts_service(
    hass: HomeAssistant,
    tts_service: str,
    payload: dict[str, Any],
) -> None:
    """Call the TTS service with a timeout.

    Args:
        hass: Home Assistant instance.
        tts_service: Service identifier (e.g., 'tts.speak').
        payload: Service call payload.

    Raises:
        asyncio.TimeoutError: If the call exceeds NOTIFY_SERVICE_TIMEOUT.
        HomeAssistantError: If the service call fails.
    """
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
    """Poll until entity reaches target_state or timeout expires.

    Args:
        hass: Home Assistant instance.
        entity_id: The entity to monitor.
        target_state: The state string to wait for.
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between polls.

    Returns:
        True if the target state was reached, False on timeout.
    """
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
    """Poll until entity exits exit_state or timeout expires.

    Args:
        hass: Home Assistant instance.
        entity_id: The entity to monitor.
        exit_state: The state string to wait to leave.
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between polls.

    Returns:
        True if the entity exited the state, False on timeout.
    """
    elapsed = 0.0
    while elapsed < timeout:
        state = hass.states.get(entity_id)
        if state and state.state != exit_state:
            return True
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    _LOGGER.debug("Timeout waiting for %s to exit '%s'", entity_id, exit_state)
    return False


async def _deliver_tts_announce(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
) -> str:
    """Deliver TTS via announce mode (platform handles pause/resume).

    Announce-capable media players automatically pause current media,
    play the TTS, and resume. No manual snapshot/restore needed.

    Args:
        hass: Home Assistant instance.
        entity_id: The media_player entity ID.
        tts_service: TTS service identifier.
        payload: TTS service payload.

    Returns:
        Delivery method label for logging.
    """
    _LOGGER.debug(
        "TTS announce delivery to %s via %s", entity_id, tts_service,
    )
    await _call_tts_service(hass, tts_service, payload)
    return "announce"


async def _deliver_tts_with_restore(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
) -> str:
    """Deliver TTS with manual snapshot/restore of media state.

    Before TTS: snapshots state, media_content_id, and media_content_type.
    After TTS: if the player was previously 'playing' and content info is
    available, calls media_player.play_media to resume. Streams resume
    live; local files restart from the beginning (known limitation).

    Restore failures log a warning but do not fail the notification.

    Args:
        hass: Home Assistant instance.
        entity_id: The media_player entity ID.
        tts_service: TTS service identifier.
        payload: TTS service payload.

    Returns:
        Delivery method label for logging.
    """
    # Snapshot current media state before TTS
    state_obj = hass.states.get(entity_id)
    prev_state = state_obj.state if state_obj else None
    prev_content_id = (
        state_obj.attributes.get("media_content_id") if state_obj else None
    )
    prev_content_type = (
        state_obj.attributes.get("media_content_type") if state_obj else None
    )

    _LOGGER.debug(
        "TTS restore delivery to %s (prev_state=%s, has_content=%s)",
        entity_id, prev_state, bool(prev_content_id),
    )

    # Deliver TTS (blocking — waits for TTS to be queued, not for playback to finish)
    await _call_tts_service(hass, tts_service, payload)

    # Wait for TTS playback to actually finish before restoring.
    # Note: if player transitions through 'playing' faster than poll_interval,
    # the 5s timeout acts as a minimum wait — still better than 0s.
    await _wait_for_state(hass, entity_id, "playing", timeout=TTS_PLAYBACK_START_TIMEOUT)
    await _wait_for_state_exit(hass, entity_id, "playing", timeout=TTS_PLAYBACK_MAX_TIMEOUT)

    # Attempt to restore previous media if it was playing
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

    return "restore"


async def _deliver_tts_plain(
    hass: HomeAssistant,
    entity_id: str,
    tts_service: str,
    payload: dict[str, Any],
) -> str:
    """Deliver TTS with no announce or restore — plain fire-and-forget.

    Args:
        hass: Home Assistant instance.
        entity_id: The media_player entity ID.
        tts_service: TTS service identifier.
        payload: TTS service payload.

    Returns:
        Delivery method label for logging.
    """
    _LOGGER.debug(
        "TTS plain delivery to %s via %s", entity_id, tts_service,
    )
    await _call_tts_service(hass, tts_service, payload)
    return "plain"


async def async_send_tts(
    hass: HomeAssistant,
    store: "TickerStore",
    recipient: dict[str, Any],
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
    notification_id: str | None = None,
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

    # Optional pre-playback delay for Chromecast/Cast devices
    buffer_delay = recipient.get("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT)
    if buffer_delay > 0:
        _LOGGER.debug(
            "TTS buffer delay: waiting %.1fs for %s", buffer_delay, entity_id,
        )
        await asyncio.sleep(buffer_delay)

    # Determine delivery method: announce > restore > plain
    features = _get_supported_features(hass, entity_id)
    supports_announce = bool(features & MEDIA_ANNOUNCE_FEATURE)
    resume = recipient.get("resume_after_tts", False)

    try:
        if supports_announce:
            method = await _deliver_tts_announce(
                hass, entity_id, tts_service, payload,
            )
        elif resume:
            method = await _deliver_tts_with_restore(
                hass, entity_id, tts_service, payload,
            )
        else:
            method = await _deliver_tts_plain(
                hass, entity_id, tts_service, payload,
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
