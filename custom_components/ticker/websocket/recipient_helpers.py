"""Helper WebSocket commands for Ticker recipients (F-18).

Extracted from recipients.py to stay under the 500-line limit.
Contains test notification and notify service discovery commands.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from ..const import (
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_RICH,
    DEVICE_TYPE_TTS,
    MEDIA_ANNOUNCE_FEATURE,
)
from ..formatting import (
    detect_delivery_format,
    resolve_ios_platform,
    transform_payload_for_format,
)
from ..recipient_tts import async_send_tts
from .validation import get_store

_LOGGER = logging.getLogger(__name__)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "ticker/get_tts_options"}
)
@websocket_api.async_response
async def ws_get_tts_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return media_player entities and TTS services for dropdown population.

    Returns:
        media_players: list of {entity_id, friendly_name} for all media_player entities.
        tts_services: list of {service_id, name} for all tts.* services.
    """
    # Collect media_player entities
    media_players = []
    for state in hass.states.async_all("media_player"):
        friendly_name = state.attributes.get("friendly_name", state.entity_id)
        features = state.attributes.get("supported_features", 0)
        supports_announce = bool(features & MEDIA_ANNOUNCE_FEATURE)
        media_players.append({
            "entity_id": state.entity_id,
            "friendly_name": friendly_name,
            "supports_announce": supports_announce,
        })
    media_players.sort(key=lambda x: x["friendly_name"].lower())

    # Collect TTS services
    tts_services = []
    tts_service_map = hass.services.async_services().get("tts", {})
    for service_name in sorted(tts_service_map):
        service_id = f"tts.{service_name}"
        tts_services.append({
            "service_id": service_id,
            "name": service_name,
        })

    connection.send_result(msg["id"], {
        "media_players": media_players,
        "tts_services": tts_services,
    })


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/get_available_notify_services",
        vol.Optional("recipient_id"): str,
    }
)
@websocket_api.async_response
async def ws_get_available_notify_services(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List registered notify services, excluding already-assigned ones.

    Scans hass.services for the 'notify' domain and returns each service
    with its auto-detected delivery format. Filters out services already
    assigned to users or other recipients so each service is used once.

    Optional recipient_id: when editing a recipient, its own services
    are not excluded from the results.
    """
    store = get_store(hass)
    editing_id = msg.get("recipient_id")

    # Collect services already assigned to recipients
    excluded: set[str] = set()
    for rid, recipient in store.get_recipients().items():
        if rid == editing_id:
            continue
        for svc in recipient.get("notify_services") or []:
            if isinstance(svc, dict):
                excluded.add(svc.get("service", ""))
            elif isinstance(svc, str):
                excluded.add(svc)

    # Collect services already assigned to users
    for _pid, user in store.get_users().items():
        for svc in user.get("notify_services_override") or []:
            if isinstance(svc, dict):
                excluded.add(svc.get("service", ""))
            elif isinstance(svc, str):
                excluded.add(svc)

    notify_services_map = hass.services.async_services().get("notify", {})
    result = []
    for service_name in sorted(notify_services_map):
        service_id = f"notify.{service_name}"
        if service_id in excluded:
            continue
        detected = detect_delivery_format(service_id)
        # BUG-061: Override to plain for iOS devices (registry-based)
        if detected == DELIVERY_FORMAT_RICH and resolve_ios_platform(hass, service_id):
            detected = DELIVERY_FORMAT_PLAIN
        result.append({
            "service": service_id,
            "name": service_name,
            "detected_format": detected,
        })
    connection.send_result(msg["id"], {"services": result})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/test_recipient",
        vol.Required("recipient_id"): str,
    }
)
@websocket_api.async_response
async def ws_test_recipient(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send a test notification to a recipient.

    Handles both push and TTS device types:
    - push: iterates notify_services, transforms payload per delivery_format
    - tts: builds TTS payload and calls the configured tts_service
    """
    store = get_store(hass)

    recipient_id = msg["recipient_id"]
    recipient = store.get_recipient(recipient_id)
    if recipient is None:
        connection.send_error(
            msg["id"], "recipient_not_found",
            f"Recipient '{recipient_id}' not found",
        )
        return

    device_type = recipient.get("device_type", "push")
    recipient_name = recipient.get("name", recipient_id)

    if device_type == DEVICE_TYPE_TTS:
        result = await _test_tts_recipient(
            hass, store, recipient, recipient_name,
        )
        connection.send_result(msg["id"], {"results": [result]})
        return

    # Push device type
    results = await _test_push_recipient(
        hass, msg["id"], connection, recipient, recipient_name,
    )
    if results is not None:
        connection.send_result(msg["id"], {"results": results})


async def _test_tts_recipient(
    hass: HomeAssistant,
    store: Any,
    recipient: dict[str, Any],
    recipient_name: str,
) -> dict[str, Any]:
    """Test a TTS recipient by speaking a test message via async_send_tts.

    Delegates to the production TTS delivery pipeline so that announce mode,
    snapshot/restore, and plain fallback are all exercised by the test button.

    Args:
        hass: Home Assistant instance.
        store: TickerStore instance.
        recipient: Recipient dict from store.
        recipient_name: Display name for error messages.

    Returns:
        Result dict with service, name, success, and optional error.
    """
    entity_id = recipient.get("media_player_entity_id")
    if not entity_id:
        return {
            "service": "tts", "name": recipient_name,
            "success": False,
            "error": "No media_player_entity_id configured",
        }

    tts_service = recipient.get("tts_service") or "tts.speak"
    display_name = f"{tts_service} -> {entity_id}"

    result = await async_send_tts(
        hass,
        store,
        recipient,
        category_id="test",
        title="Ticker Test",
        message=(
            f"Ticker test for {recipient_name}. "
            "If you hear this, it works!"
        ),
    )
    # async_send_tts returns {delivered, queued, dropped} lists
    if result.get("delivered"):
        return {
            "service": tts_service, "name": display_name,
            "success": True,
        }
    # If nothing delivered, report the drop/queue reason
    error_detail = "TTS not delivered"
    if result.get("dropped"):
        error_detail = f"Dropped: {result['dropped']}"
    elif result.get("queued"):
        error_detail = f"Queued: {result['queued']}"
    return {
        "service": tts_service, "name": display_name,
        "success": False, "error": error_detail,
    }


async def _test_push_recipient(
    hass: HomeAssistant,
    msg_id: int,
    connection: websocket_api.ActiveConnection,
    recipient: dict[str, Any],
    recipient_name: str,
) -> list[dict[str, Any]] | None:
    """Test a push recipient by sending to each notify service.

    Args:
        hass: Home Assistant instance.
        msg_id: WebSocket message ID.
        connection: Active WebSocket connection.
        recipient: Recipient dict from store.
        recipient_name: Display name for error messages.

    Returns:
        List of result dicts, or None if an error was sent via connection.
    """
    notify_services = recipient.get("notify_services", [])
    if not notify_services:
        connection.send_error(
            msg_id, "no_notify_services",
            f"Recipient '{recipient_name}' has no services",
        )
        return None

    delivery_format = recipient.get("delivery_format", DELIVERY_FORMAT_RICH)

    payload = transform_payload_for_format(
        title="Ticker Test",
        message=f"Test for {recipient_name}. If you see this, it works!",
        format_type=delivery_format,
        category_id="test",
    )

    results = []
    for service_info in notify_services:
        service = service_info.get("service", "")
        service_display = service_info.get("name", service)

        if not service or "." not in service:
            results.append({
                "service": service, "name": service_display,
                "success": False, "error": "Invalid service format",
            })
            continue

        domain, svc_name = service.split(".", 1)

        if delivery_format == DELIVERY_FORMAT_PERSISTENT:
            call_domain = "persistent_notification"
            call_service = "create"
            call_data = {
                "title": payload.get("title", "Ticker Test"),
                "message": payload.get("message", ""),
                "notification_id": payload.get("notification_id"),
            }
        else:
            call_domain = domain
            call_service = svc_name
            call_data = payload

        try:
            await hass.services.async_call(
                call_domain, call_service, call_data, blocking=True,
            )
            results.append({
                "service": service, "name": service_display, "success": True,
            })
            _LOGGER.info(
                "Test sent to recipient %s via %s",
                recipient.get("recipient_id"), service,
            )
        except (HomeAssistantError, ServiceNotFound) as err:
            results.append({
                "service": service, "name": service_display,
                "success": False, "error": str(err),
            })
            _LOGGER.error(
                "Test failed for recipient %s via %s: %s",
                recipient.get("recipient_id"), service, err,
            )

    return results
