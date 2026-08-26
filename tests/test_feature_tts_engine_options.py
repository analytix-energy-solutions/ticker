"""Tests for modern TTS engine discovery in the recipient editor."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from custom_components.ticker.websocket.recipient_helpers import ws_get_tts_options
from custom_components.ticker.websocket.recipients import (
    _CHIME_TTS_GAP_SCHEMA,
    _CHIME_WAIT_TIMEOUT_SCHEMA,
)


@pytest.mark.asyncio
async def test_get_tts_options_returns_engine_entities():
    hass = MagicMock()
    hass.states.async_all.side_effect = lambda domain: {
        "media_player": [
            SimpleNamespace(
                entity_id="media_player.bedroom",
                attributes={"friendly_name": "Bedroom", "supported_features": 0},
            ),
        ],
        "tts": [
            SimpleNamespace(
                entity_id="tts.openai_tts",
                attributes={"friendly_name": "OpenAI TTS"},
            ),
            SimpleNamespace(
                entity_id="tts.home_assistant_cloud",
                attributes={"friendly_name": "Home Assistant Cloud"},
            ),
        ],
    }[domain]
    hass.services.async_services.return_value = {
        "tts": {"speak": object(), "cloud_say": object()},
    }
    connection = MagicMock()

    await ws_get_tts_options(
        hass, connection, {"id": 7, "type": "ticker/get_tts_options"},
    )

    result = connection.send_result.call_args.args[1]
    assert result["tts_entities"] == [
        {
            "entity_id": "tts.home_assistant_cloud",
            "friendly_name": "Home Assistant Cloud",
        },
        {"entity_id": "tts.openai_tts", "friendly_name": "OpenAI TTS"},
    ]
    assert {item["service_id"] for item in result["tts_services"]} == {
        "tts.cloud_say",
        "tts.speak",
    }


def test_chime_timing_schemas_accept_supported_values():
    assert _CHIME_WAIT_TIMEOUT_SCHEMA("3") == 3.0
    assert _CHIME_TTS_GAP_SCHEMA("1") == 1.0


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (_CHIME_WAIT_TIMEOUT_SCHEMA, 0.4),
        (_CHIME_WAIT_TIMEOUT_SCHEMA, 60.1),
        (_CHIME_TTS_GAP_SCHEMA, -0.1),
        (_CHIME_TTS_GAP_SCHEMA, 10.1),
    ],
)
def test_chime_timing_schemas_reject_out_of_range(schema, value):
    with pytest.raises(vol.Invalid):
        schema(value)
