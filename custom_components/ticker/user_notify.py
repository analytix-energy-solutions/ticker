"""Notification sending handlers for Ticker integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_NAVIGATE_TO,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_RICH,
    DEVICE_MODE_ALL,
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_SKIPPED,
    LOG_OUTCOME_SNOOZED,
    NOTIFY_SERVICE_TIMEOUT,
)
from .actions import build_action_payload, resolve_action_set
from .discovery import async_get_notify_services_for_person
from .formatting import (
    detect_delivery_format,
    inject_critical_payload,
    inject_navigate_to,
    inject_smart_notification,
    resolve_ios_platform,
    transform_payload_for_format,
)

if TYPE_CHECKING:
    from .store import TickerStore

_LOGGER = logging.getLogger(__name__)


async def async_handle_conditional_notification(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    person_name: str,
    person_state: Any,
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any],
    expiration: int,
    notification_id: str | None = None,
    suppress_actions: bool = False,
    action_set_id: str | None = None,
    navigate_to: str | None = None,
) -> dict[str, list[str]]:
    """Handle notification delivery for conditional mode.

    Supports F-2 Advanced Conditions with:
    - Zone, time, and entity state rules
    - AND logic (all rules must be met)
    - deliver_when_met and queue_until_met per rule

    Evaluates conditions and determines whether to:
    - Send immediately (all rules met + deliver_when_met)
    - Queue for later (queue_until_met rules not met)
    - Skip (no matching delivery path)

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists of service IDs/descriptions.
    """
    from .conditions import (
        should_deliver_now,
        should_queue,
        convert_legacy_zones_to_rules,
        has_any_conditions,
    )

    image_url = data.get("image") if data else None

    conditions = store.get_subscription_conditions(person_id, category_id)

    if not conditions:
        # No conditions configured - fallback to always
        _LOGGER.warning(
            "Conditional mode for %s/%s has no conditions, sending immediately",
            person_id,
            category_id,
        )
        return await async_send_notification(
            hass, store, person_id, person_name, category_id, title, message, data,
            notification_id=notification_id, suppress_actions=suppress_actions,
            action_set_id=action_set_id, navigate_to=navigate_to,
        )

    # Self-heal legacy zones format: if only zones exist (no tree, no
    # rules), convert them in-place to the modern rules[] shape.
    if (
        not conditions.get("condition_tree")
        and not conditions.get("rules")
        and conditions.get("zones")
    ):
        converted = convert_legacy_zones_to_rules(conditions["zones"])
        conditions.update(converted)

    # Gate on any evaluable conditions (tree, flat rules, or zones).
    # BUG-084: previously this only checked rules[], so F-2b migrated
    # subscriptions (which have condition_tree and no rules) fell
    # through to unconditional delivery.
    if not has_any_conditions(conditions):
        _LOGGER.warning(
            "Conditional mode for %s/%s has no valid rules, sending immediately",
            person_id,
            category_id,
        )
        return await async_send_notification(
            hass, store, person_id, person_name, category_id, title, message, data,
            notification_id=notification_id, suppress_actions=suppress_actions,
            action_set_id=action_set_id, navigate_to=navigate_to,
        )

    # Check if we should deliver now (all conditions met + deliver_when_met)
    deliver, deliver_reason = should_deliver_now(hass, conditions, person_state)

    if deliver:
        _LOGGER.debug(
            "Delivering notification to %s/%s: %s",
            person_id,
            category_id,
            deliver_reason,
        )
        return await async_send_notification(
            hass, store, person_id, person_name, category_id, title, message, data,
            notification_id=notification_id, suppress_actions=suppress_actions,
            action_set_id=action_set_id, navigate_to=navigate_to,
        )

    # Check if we should queue (has queue_until_met flag and conditions not met)
    do_queue, queue_reason = should_queue(hass, conditions, person_state)

    if do_queue:
        # Queue the notification
        await store.async_add_to_queue(
            person_id=person_id,
            category_id=category_id,
            title=title,
            message=message,
            data=data,
            expiration_hours=expiration,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_QUEUED,
            reason=f"Conditional: {queue_reason}",
            notification_id=notification_id,
            image_url=image_url,
        )
        _LOGGER.debug(
            "Queued notification for %s/%s: %s",
            person_id,
            category_id,
            queue_reason,
        )
        return {"delivered": [], "queued": [f"{person_id}: {queue_reason}"], "dropped": []}

    # No delivery path - skip
    _LOGGER.debug(
        "Skipping notification for %s/%s: %s",
        person_id,
        category_id,
        deliver_reason,
    )
    await store.async_add_log(
        category_id=category_id,
        person_id=person_id,
        person_name=person_name,
        title=title,
        message=message,
        outcome=LOG_OUTCOME_SKIPPED,
        reason=f"Conditional: {deliver_reason}",
        notification_id=notification_id,
        image_url=image_url,
    )
    return {"delivered": [], "queued": [], "dropped": [f"{person_id}: {deliver_reason}"]}


async def async_send_notification(
    hass: HomeAssistant,
    store: "TickerStore",
    person_id: str,
    person_name: str,
    category_id: str,
    title: str,
    message: str,
    data: dict[str, Any],
    notification_id: str | None = None,
    suppress_actions: bool = False,
    action_set_id: str | None = None,
    navigate_to: str | None = None,
) -> dict[str, list[str]]:
    """Send notification to a person via their notify services.

    Respects device preferences:
    - Global device preference (all vs selected devices)
    - Per-category device override (additive)

    Returns:
        Dict with 'delivered', 'queued', 'dropped' lists of service IDs/descriptions.
    """
    image_url = data.get("image") if data else None
    results: dict[str, list[str]] = {"delivered": [], "queued": [], "dropped": []}

    # F-5: Snooze pre-check
    if store.is_snoozed(person_id, category_id):
        await store.async_add_log(
            category_id=category_id, person_id=person_id, person_name=person_name,
            title=title, message=message, outcome=LOG_OUTCOME_SNOOZED,
            reason="Snoozed by user", notification_id=notification_id,
            image_url=image_url,
        )
        results["dropped"].append(f"{person_id}: Snoozed")
        return results

    # Get all discovered services for this person (list of dicts with service/name/device_id)
    all_services = await async_get_notify_services_for_person(hass, person_id)

    if not all_services:
        _LOGGER.warning(
            "No notify services found for %s, cannot send notification",
            person_id,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No notify services found",
            notification_id=notification_id,
            image_url=image_url,
        )
        results["dropped"].append(f"{person_id}: No notify services found")
        return results

    # Build a lookup of service ID to service info
    service_lookup = {svc["service"]: svc for svc in all_services}
    all_service_ids = set(service_lookup.keys())

    # Get user's global device preference
    device_pref = store.get_device_preference(person_id)
    pref_mode = device_pref.get("mode", DEVICE_MODE_ALL)
    pref_devices = set(device_pref.get("devices", []))

    # Determine base device set from global preference
    if pref_mode == DEVICE_MODE_ALL:
        base_devices = all_service_ids
    else:  # DEVICE_MODE_SELECTED
        # Filter to only devices that still exist
        base_devices = pref_devices & all_service_ids
        if not base_devices:
            _LOGGER.warning(
                "User %s has 'selected' device mode but no valid devices, "
                "falling back to all devices",
                person_id,
            )
            base_devices = all_service_ids

    # Check for per-category device override (additive)
    device_override = store.get_device_override(person_id, category_id)
    if device_override and device_override.get("enabled"):
        override_devices = set(device_override.get("devices", []))
        # Filter to only devices that exist
        valid_override_devices = override_devices & all_service_ids
        if valid_override_devices:
            # Union: base + override
            final_devices = base_devices | valid_override_devices
            _LOGGER.debug(
                "Category override for %s/%s: adding %s to base devices",
                person_id,
                category_id,
                valid_override_devices,
            )
        else:
            final_devices = base_devices
    else:
        final_devices = base_devices

    if not final_devices:
        _LOGGER.warning(
            "No target devices for %s after applying preferences",
            person_id,
        )
        await store.async_add_log(
            category_id=category_id,
            person_id=person_id,
            person_name=person_name,
            title=title,
            message=message,
            outcome=LOG_OUTCOME_FAILED,
            reason="No target devices after applying preferences",
            notification_id=notification_id,
            image_url=image_url,
        )
        results["dropped"].append(f"{person_id}: No target devices")
        return results

    _LOGGER.debug(
        "Sending notification to %s via %d device(s): %s",
        person_id,
        len(final_devices),
        final_devices,
    )

    for service_id in final_devices:
        service_info = service_lookup.get(service_id, {})
        service_name_display = service_info.get("name", service_id)
        domain, service_name = service_id.split(".", 1)

        # F-16: Detect delivery format for this service
        delivery_format = detect_delivery_format(service_id)
        # BUG-061: Override to plain for iOS devices (registry-based detection)
        if delivery_format == DELIVERY_FORMAT_RICH and resolve_ios_platform(hass, service_id):
            delivery_format = DELIVERY_FORMAT_PLAIN
        _LOGGER.debug(
            "F-16: Service %s detected as format '%s'",
            service_id,
            delivery_format,
        )

        # Build enriched data dict before format transformation
        enriched_data: dict[str, Any] = dict(data) if data else {}

        # Fetch category once for action injection and smart notification
        category = store.get_category(category_id)

        # F-5/F-5b: Inject action buttons via resolved action set
        if not suppress_actions and "actions" not in enriched_data and notification_id:
            action_set, resolved_id = resolve_action_set(
                store, category, action_set_id,
            )
            if action_set and resolved_id:
                enriched_data["actions"] = build_action_payload(
                    action_set, resolved_id, notification_id
                )

        # F-6: Inject smart notification fields (group, tag, sticky, persistent)
        smart_config = (category or {}).get("smart_notification")
        if smart_config:
            inject_smart_notification(
                enriched_data, category_id, title, smart_config, delivery_format
            )

        # F-22: Inject tap-to-navigate deep-link (per-call > category > default)
        resolved_navigate_to = (
            navigate_to
            or (category or {}).get("navigate_to")
            or DEFAULT_NAVIGATE_TO
        )
        inject_navigate_to(enriched_data, resolved_navigate_to, delivery_format)

        # F-16: Transform payload for the target platform's delivery format
        service_data = transform_payload_for_format(
            title=title,
            message=message,
            format_type=delivery_format,
            category_id=category_id,
            data=enriched_data if enriched_data else None,
        )

        # F-15: Inject critical notification payload if flagged
        if data and data.get("critical"):
            inject_critical_payload(service_data, delivery_format)

        try:
            await asyncio.wait_for(
                hass.services.async_call(
                    domain,
                    service_name,
                    service_data,
                    blocking=True,
                ),
                timeout=NOTIFY_SERVICE_TIMEOUT,
            )
            _LOGGER.info(
                "Sent notification to %s via %s (%s)",
                person_id,
                service_id,
                service_name_display,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_SENT,
                notify_service=f"{service_id} ({service_name_display})",
                notification_id=notification_id,
                image_url=image_url,
            )
            results["delivered"].append(service_id)
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timeout sending notification to %s via %s (exceeded %ds)",
                person_id,
                service_id,
                NOTIFY_SERVICE_TIMEOUT,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=f"Timeout after {NOTIFY_SERVICE_TIMEOUT}s",
                notification_id=notification_id,
                image_url=image_url,
            )
            results["dropped"].append(f"{service_id}: Timeout")
        except HomeAssistantError as err:
            _LOGGER.error(
                "Failed to send notification to %s via %s: %s",
                person_id,
                service_id,
                err,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=str(err),
                notification_id=notification_id,
                image_url=image_url,
            )
            results["dropped"].append(f"{service_id}: {err}")
        except Exception as err:
            _LOGGER.error(
                "Unexpected error sending notification to %s via %s: %s",
                person_id,
                service_id,
                err,
            )
            await store.async_add_log(
                category_id=category_id,
                person_id=person_id,
                person_name=person_name,
                title=title,
                message=message,
                outcome=LOG_OUTCOME_FAILED,
                notify_service=service_id,
                reason=str(err),
                notification_id=notification_id,
                image_url=image_url,
            )
            results["dropped"].append(f"{service_id}: {err}")

    return results
