"""Tests for notify.-entity TTS recipients (e.g. Alexa via alexa_devices)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.formatting import build_tts_payload
from custom_components.ticker.recipient_tts_delivery import _call_tts_service


def test_payload_targets_notify_entity():
    """notify.-entity recipients target the notify entity, not the player."""
    payload = build_tts_payload(
        "<b>Hello</b>", "media_player.echo", tts_service="notify.echo_speak"
    )
    assert payload == {"entity_id": "notify.echo_speak", "message": "Hello"}


def test_payload_tts_service_unchanged():
    """Regular tts.* services keep targeting the media player."""
    payload = build_tts_payload("Hi", "media_player.x", tts_service="tts.cloud_say")
    assert payload["entity_id"] == "media_player.x"


@pytest.mark.asyncio
async def test_notify_entity_calls_send_message():
    """notify.<slug> is delivered via notify.send_message."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    payload = {"entity_id": "notify.echo_speak", "message": "Hi"}
    await _call_tts_service(hass, "notify.echo_speak", payload)
    hass.services.async_call.assert_awaited_once_with(
        "notify", "send_message", payload, blocking=True
    )


@pytest.mark.asyncio
async def test_tts_service_called_as_is():
    """Non-notify services are still called by their own name."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    await _call_tts_service(hass, "tts.cloud_say", {"message": "Hi"})
    hass.services.async_call.assert_awaited_once_with(
        "tts", "cloud_say", {"message": "Hi"}, blocking=True
    )
