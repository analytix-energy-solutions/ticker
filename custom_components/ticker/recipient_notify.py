"""Recipient notification delivery for Ticker F-18.

Handles sending notifications to non-user recipients (TVs, TTS speakers,
persistent notifications, etc.) with format-aware payload transformation.

This module is intentionally decoupled from notify.py to avoid cross-
dependency. It uses formatting.py directly for payload transformation.

TTS delivery logic lives in recipient_tts.py (extracted for F-19).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_EXPIRATION_HOURS,
    DEFAULT_NAVIGATE_TO,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_RICH,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_SKIPPED,
    NOTIFY_SERVICE_TIMEOUT,
)
from .formatting import (
    detect_delivery_format,
    inject_critical_payload,
    inject_navigate_to,
    inject_smart_notification,
    resolve_ios_platform,
    transform_payload_for_format,
)
from .recipient_tts import (
    async_send_tts,
    log_delivery_failure,
)

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)

# Formats that do not support action buttons (push device only)
_NO_ACTION_FORMATS = {DELIVERY_FORMAT_PERSISTENT}


async def async_send_to_recipient(
    hass: HomeAssistant,
    store: "TickerStore",
    recipient: dict[str, Any],
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
    notification_id: str | None = None,
    suppress_actions: bool = False,
    action_set_id: str | None = None,
    navigate_to: str | None = None,
) -> dict[str, list[str]]:
    """Send a notification to a recipient based on its device_type.

    Branches on device_type:
    - 'push': iterates notify_services, transforms payload per delivery_format
    - 'tts': builds TTS payload and calls tts.speak on media_player_entity_id

    Args:
        hass: Home Assistant instance.
        store: Ticker store.
        recipient: Recipient dict from store.
        category_id: Category being notified.
        title: Notification title.
        message: Notification message body.
        data: Optional extra data dict.
        notification_id: Unique notification call ID for log grouping.
        suppress_actions: Whether to suppress action buttons.
        action_set_id: Optional action set ID override.
        navigate_to: Optional URL/path override for tap-to-navigate.

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists.
    """
    device_type = recipient.get("device_type", DEVICE_TYPE_PUSH)

    if device_type == DEVICE_TYPE_TTS:
        return await async_send_tts(
            hass, store, recipient, category_id, title, message,
            data, notification_id,
        )

    return await _async_send_push(
        hass, store, recipient, category_id, title, message,
        data, notification_id, suppress_actions, action_set_id, navigate_to,
    )


async def _async_send_push(
    hass: HomeAssistant,
    store: "TickerStore",
    recipient: dict[str, Any],
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
    notification_id: str | None = None,
    suppress_actions: bool = False,
    action_set_id: str | None = None,
    navigate_to: str | None = None,
) -> dict[str, list[str]]:
    """Send a push notification to a recipient's notify services.

    Handles rich, plain, and persistent delivery formats. Persistent
    is treated as a push device whose service is
    notify.persistent_notification -- the standard push path handles it.

    Args:
        hass: Home Assistant instance.
        store: Ticker store.
        recipient: Recipient dict (device_type='push').
        category_id: Category being notified.
        title: Notification title.
        message: Notification message body.
        data: Optional extra data dict.
        notification_id: Unique notification call ID for log grouping.
        suppress_actions: Whether to suppress action buttons.
        action_set_id: Optional action set ID override.
        navigate_to: Optional URL/path override for tap-to-navigate.

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists.
    """
    results: dict[str, list[str]] = {"delivered": [], "queued": [], "dropped": []}
    recipient_id = recipient["recipient_id"]
    recipient_name = recipient.get("name", recipient_id)
    person_id = f"recipient:{recipient_id}"
    image_url = data.get("image") if data else None

    notify_services = recipient.get("notify_services", [])
    if not notify_services:
        _LOGGER.warning("Recipient %s has no notify services", recipient_id)
        await store.async_add_log(
            category_id=category_id, person_id=person_id,
            person_name=recipient_name, title=title, message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No notify services configured",
            notification_id=notification_id, image_url=image_url,
        )
        results["dropped"].append(f"{person_id}: No notify services")
        return results

    # Resolve delivery format.
    # Known limitation: auto-detection uses first service's format for all services.
    # If a recipient has mixed-platform services (e.g., iOS + Android), all get
    # the same format. Per-service detection could be added if needed.
    delivery_format = recipient.get("delivery_format", "auto")
    if delivery_format == "auto":
        first_service = notify_services[0].get("service", "")
        delivery_format = detect_delivery_format(first_service)
        # BUG-061: Override to plain for iOS devices (registry-based detection)
        if delivery_format == DELIVERY_FORMAT_RICH and resolve_ios_platform(hass, first_service):
            delivery_format = DELIVERY_FORMAT_PLAIN

    # Suppress actions for formats that don't support them
    effective_suppress = (
        suppress_actions or delivery_format in _NO_ACTION_FORMATS
    )

    for svc_entry in notify_services:
        service_id = svc_entry.get("service", "")
        service_display = svc_entry.get("name", service_id)
        if not service_id:
            continue

        payload = transform_payload_for_format(
            title=title, message=message, format_type=delivery_format,
            category_id=category_id, data=data,
        )

        # F-15: Inject critical notification payload if flagged
        if data and data.get("critical"):
            inject_critical_payload(payload, delivery_format)

        # Ensure data key exists for formats that support actions
        if delivery_format not in _NO_ACTION_FORMATS and "data" not in payload:
            payload["data"] = {}

        # F-5/F-5b: Inject action buttons via resolved action set
        category = store.get_category(category_id)
        if not effective_suppress and "data" in payload:
            if "actions" not in payload["data"] and notification_id:
                from .actions import build_action_payload, resolve_action_set

                action_set, resolved_id = resolve_action_set(
                    store, category, action_set_id,
                )
                if action_set and resolved_id:
                    payload["data"]["actions"] = build_action_payload(
                        action_set, resolved_id, notification_id
                    )

        # F-6: Inject smart notification fields (group, tag, sticky, persistent)
        smart_config = (category or {}).get("smart_notification")
        if smart_config and isinstance(payload.get("data"), dict):
            inject_smart_notification(
                payload["data"], category_id, title, smart_config, delivery_format
            )

        # F-22: Inject tap-to-navigate deep-link (per-call > category > default)
        if isinstance(payload.get("data"), dict):
            resolved_navigate_to = (
                navigate_to
                or (category or {}).get("navigate_to")
                or DEFAULT_NAVIGATE_TO
            )
            inject_navigate_to(payload["data"], resolved_navigate_to, delivery_format)

        # Android channel: per-category notification routing (Android only)
        android_channel = (category or {}).get("android_channel")
        if android_channel and delivery_format == DELIVERY_FORMAT_RICH:
            if "data" not in payload:
                payload["data"] = {}
            if "channel" not in payload["data"]:
                payload["data"]["channel"] = android_channel

        try:
            domain, service_name = service_id.split(".", 1)
            await asyncio.wait_for(
                hass.services.async_call(
                    domain, service_name, payload, blocking=True
                ),
                timeout=NOTIFY_SERVICE_TIMEOUT,
            )

            _LOGGER.info(
                "Sent recipient notification to %s via %s (%s)",
                recipient_id, service_id, service_display,
            )
            await store.async_add_log(
                category_id=category_id, person_id=person_id,
                person_name=recipient_name, title=title, message=message,
                outcome=LOG_OUTCOME_SENT,
                notify_service=f"{service_id} ({service_display})",
                notification_id=notification_id, image_url=image_url,
            )
            results["delivered"].append(service_id)

        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timeout sending to recipient %s via %s (exceeded %ds)",
                recipient_id, service_id, NOTIFY_SERVICE_TIMEOUT,
            )
            await log_delivery_failure(
                store, category_id, person_id, recipient_name, title,
                message, service_id,
                f"Timeout after {NOTIFY_SERVICE_TIMEOUT}s",
                notification_id, image_url,
            )
            results["dropped"].append(f"{service_id}: Timeout")

        except HomeAssistantError as err:
            _LOGGER.error(
                "Failed to send to recipient %s via %s: %s",
                recipient_id, service_id, err,
            )
            await log_delivery_failure(
                store, category_id, person_id, recipient_name, title,
                message, service_id, str(err), notification_id, image_url,
            )
            results["dropped"].append(f"{service_id}: {err}")

        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Unexpected error sending to recipient %s via %s: %s",
                recipient_id, service_id, err,
            )
            await log_delivery_failure(
                store, category_id, person_id, recipient_name, title,
                message, service_id, str(err), notification_id, image_url,
            )
            results["dropped"].append(f"{service_id}: {err}")

    return results


async def async_handle_conditional_recipient(
    hass: HomeAssistant,
    store: "TickerStore",
    recipient: dict[str, Any],
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
    expiration: int = DEFAULT_EXPIRATION_HOURS,
    notification_id: str | None = None,
    suppress_actions: bool = False,
    action_set_id: str | None = None,
    navigate_to: str | None = None,
) -> dict[str, list[str]]:
    """Handle conditional delivery for a recipient.

    Evaluates time/state conditions (zone rules are skipped since
    recipients have no person entity). Delivers immediately if conditions
    are met, queues if queue_until_met is set, or skips.

    Args:
        hass: Home Assistant instance.
        store: Ticker store.
        recipient: Recipient dict from store.
        category_id: Category being notified.
        title: Notification title.
        message: Notification message body.
        data: Optional extra data dict.
        expiration: Hours until queued notification expires.
        notification_id: Unique notification call ID for log grouping.
        suppress_actions: Whether to suppress action buttons.
        action_set_id: Optional action set ID override.
        navigate_to: Optional URL/path override for tap-to-navigate.

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists.
    """
    from .conditions import has_any_conditions, should_deliver_now, should_queue

    recipient_id = recipient["recipient_id"]
    recipient_name = recipient.get("name", recipient_id)
    person_id = f"recipient:{recipient_id}"
    image_url = data.get("image") if data else None

    conditions = store.get_subscription_conditions(person_id, category_id)

    # BUG-085: check both condition_tree and rules (F-2b migration
    # removes the legacy rules key in favor of condition_tree).
    if not has_any_conditions(conditions):
        _LOGGER.warning(
            "Conditional mode for recipient %s/%s has no conditions, "
            "sending immediately",
            recipient_id,
            category_id,
        )
        return await async_send_to_recipient(
            hass, store, recipient, category_id, title, message, data,
            notification_id=notification_id, suppress_actions=suppress_actions,
            action_set_id=action_set_id, navigate_to=navigate_to,
        )

    # person_state=None tells conditions.py to skip zone rules
    deliver, deliver_reason = should_deliver_now(hass, conditions, None)

    if deliver:
        _LOGGER.debug(
            "Delivering to recipient %s/%s: %s",
            recipient_id, category_id, deliver_reason,
        )
        return await async_send_to_recipient(
            hass, store, recipient, category_id, title, message, data,
            notification_id=notification_id, suppress_actions=suppress_actions,
            action_set_id=action_set_id, navigate_to=navigate_to,
        )

    do_queue, queue_reason = should_queue(hass, conditions, None)

    if do_queue:
        await store.async_add_to_queue(
            person_id=person_id,
            category_id=category_id,
            title=title,
            message=message,
            data=data,
            expiration_hours=expiration,
            notification_id=notification_id,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=recipient_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_QUEUED,
            reason=f"Conditional: {queue_reason}",
            notification_id=notification_id,
            image_url=image_url,
        )
        _LOGGER.debug(
            "Queued notification for recipient %s/%s: %s",
            recipient_id, category_id, queue_reason,
        )
        return {
            "delivered": [],
            "queued": [f"{person_id}: {queue_reason}"],
            "dropped": [],
        }

    # No delivery path
    _LOGGER.debug(
        "Skipping notification for recipient %s/%s: %s",
        recipient_id, category_id, deliver_reason,
    )
    await store.async_add_log(
        category_id=category_id,
        person_id=person_id,
        person_name=recipient_name,
        title=title,
        message=message,
        outcome=LOG_OUTCOME_SKIPPED,
        reason=f"Conditional: {deliver_reason}",
        notification_id=notification_id,
        image_url=image_url,
    )
    return {
        "delivered": [],
        "queued": [],
        "dropped": [f"{person_id}: {deliver_reason}"],
    }
