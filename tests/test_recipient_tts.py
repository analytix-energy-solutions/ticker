"""Tests for custom_components.ticker.recipient_tts module.

Covers the TTS delivery pipeline: announce, restore, plain modes,
the async_send_tts orchestrator, and supporting helpers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.ticker.recipient_tts import (
    _get_supported_features,
    _call_tts_service,
    _deliver_tts_announce,
    _deliver_tts_plain,
    _deliver_tts_with_restore,
    async_send_tts,
    log_delivery_failure,
)
from custom_components.ticker.const import (
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_SENT,
    MEDIA_ANNOUNCE_FEATURE,
    NOTIFY_SERVICE_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass(
    entity_id: str | None = None,
    state: str = "idle",
    features: int = 0,
    content_id: str | None = None,
    content_type: str | None = None,
) -> MagicMock:
    """Create a mock hass with a media_player state."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    if entity_id:
        attrs = {"supported_features": features}
        if content_id is not None:
            attrs["media_content_id"] = content_id
        if content_type is not None:
            attrs["media_content_type"] = content_type
        state_obj = SimpleNamespace(
            entity_id=entity_id,
            state=state,
            attributes=attrs,
        )
        hass.states.get = MagicMock(return_value=state_obj)
    else:
        hass.states.get = MagicMock(return_value=None)

    return hass


def _make_store() -> MagicMock:
    """Create a mock TickerStore."""
    store = MagicMock()
    store.async_add_log = AsyncMock()
    return store


def _make_recipient(
    recipient_id: str = "speaker_kitchen",
    name: str = "Kitchen Speaker",
    entity_id: str = "media_player.kitchen",
    tts_service: str | None = None,
    resume: bool = False,
) -> dict:
    """Create a recipient dict matching the store schema."""
    r = {
        "recipient_id": recipient_id,
        "name": name,
        "media_player_entity_id": entity_id,
        "resume_after_tts": resume,
    }
    if tts_service:
        r["tts_service"] = tts_service
    return r


# ---------------------------------------------------------------------------
# _get_supported_features
# ---------------------------------------------------------------------------

class TestGetSupportedFeatures:
    """Tests for _get_supported_features()."""

    def test_returns_features_from_state(self, mock_hass):
        state_obj = SimpleNamespace(
            attributes={"supported_features": 524288},
        )
        mock_hass.states.get = MagicMock(return_value=state_obj)
        assert _get_supported_features(mock_hass, "media_player.x") == 524288

    def test_returns_zero_when_entity_missing(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        assert _get_supported_features(mock_hass, "media_player.gone") == 0

    def test_returns_zero_when_attribute_missing(self, mock_hass):
        state_obj = SimpleNamespace(attributes={})
        mock_hass.states.get = MagicMock(return_value=state_obj)
        assert _get_supported_features(mock_hass, "media_player.x") == 0

    def test_casts_string_to_int(self, mock_hass):
        state_obj = SimpleNamespace(attributes={"supported_features": "1024"})
        mock_hass.states.get = MagicMock(return_value=state_obj)
        assert _get_supported_features(mock_hass, "media_player.x") == 1024

    def test_combined_bitmask(self, mock_hass):
        """Features bitmask with announce (524288) + other bits."""
        features = MEDIA_ANNOUNCE_FEATURE | 64 | 128
        state_obj = SimpleNamespace(attributes={"supported_features": features})
        mock_hass.states.get = MagicMock(return_value=state_obj)
        result = _get_supported_features(mock_hass, "media_player.x")
        assert result & MEDIA_ANNOUNCE_FEATURE


# ---------------------------------------------------------------------------
# _call_tts_service
# ---------------------------------------------------------------------------

class TestCallTtsService:
    """Tests for _call_tts_service()."""

    @pytest.mark.asyncio
    async def test_calls_correct_domain_and_service(self):
        hass = _make_hass()
        payload = {"entity_id": "media_player.kitchen", "message": "hello"}
        await _call_tts_service(hass, "tts.google_translate_say", payload)
        hass.services.async_call.assert_awaited_once_with(
            "tts", "google_translate_say", payload, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_calls_tts_speak(self):
        hass = _make_hass()
        payload = {"entity_id": "media_player.kitchen", "message": "hi"}
        await _call_tts_service(hass, "tts.speak", payload)
        hass.services.async_call.assert_awaited_once_with(
            "tts", "speak", payload, blocking=True,
        )

    @pytest.mark.asyncio
    async def test_timeout_propagates(self):
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)
        with pytest.raises(asyncio.TimeoutError):
            await _call_tts_service(hass, "tts.speak", {})


# ---------------------------------------------------------------------------
# _deliver_tts_announce
# ---------------------------------------------------------------------------

class TestDeliverTtsAnnounce:
    """Tests for _deliver_tts_announce()."""

    @pytest.mark.asyncio
    async def test_returns_announce_label(self):
        hass = _make_hass()
        result = await _deliver_tts_announce(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "announce"

    @pytest.mark.asyncio
    async def test_calls_tts_service(self):
        hass = _make_hass()
        payload = {"entity_id": "media_player.kitchen", "message": "test"}
        await _deliver_tts_announce(hass, "media_player.kitchen", "tts.speak", payload)
        hass.services.async_call.assert_awaited_once()


# ---------------------------------------------------------------------------
# _deliver_tts_plain
# ---------------------------------------------------------------------------

class TestDeliverTtsPlain:
    """Tests for _deliver_tts_plain()."""

    @pytest.mark.asyncio
    async def test_returns_plain_label(self):
        hass = _make_hass()
        result = await _deliver_tts_plain(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "plain"

    @pytest.mark.asyncio
    async def test_calls_tts_service(self):
        hass = _make_hass()
        payload = {"message": "test"}
        await _deliver_tts_plain(hass, "media_player.kitchen", "tts.speak", payload)
        hass.services.async_call.assert_awaited_once()


# ---------------------------------------------------------------------------
# _deliver_tts_with_restore
# ---------------------------------------------------------------------------

@patch("custom_components.ticker.recipient_tts._wait_for_state_exit", new_callable=AsyncMock, return_value=True)
@patch("custom_components.ticker.recipient_tts._wait_for_state", new_callable=AsyncMock, return_value=True)
class TestDeliverTtsWithRestore:
    """Tests for _deliver_tts_with_restore()."""

    @pytest.mark.asyncio
    async def test_returns_restore_label(self, _mock_wait, _mock_wait_exit):
        hass = _make_hass(entity_id="media_player.kitchen")
        result = await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "restore"

    @pytest.mark.asyncio
    async def test_restores_when_was_playing_with_content(self, _mock_wait, _mock_wait_exit):
        """If media was playing with content, play_media is called to restore."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            content_id="http://stream.example.com/live",
            content_type="music",
        )
        await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        # Two service calls: tts.speak + media_player.play_media
        assert hass.services.async_call.await_count == 2
        restore_call = hass.services.async_call.call_args_list[1]
        assert restore_call[0][0] == "media_player"
        assert restore_call[0][1] == "play_media"
        assert restore_call[0][2]["media_content_id"] == "http://stream.example.com/live"
        assert restore_call[0][2]["media_content_type"] == "music"

    @pytest.mark.asyncio
    async def test_no_restore_when_idle(self, _mock_wait, _mock_wait_exit):
        """If media was idle, no restore call."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="idle",
            content_id="http://stream.example.com/live",
        )
        await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert hass.services.async_call.await_count == 1

    @pytest.mark.asyncio
    async def test_no_restore_when_no_content_id(self, _mock_wait, _mock_wait_exit):
        """If media was playing but no content_id, skip restore."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
        )
        await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert hass.services.async_call.await_count == 1

    @pytest.mark.asyncio
    async def test_defaults_content_type_to_music(self, _mock_wait, _mock_wait_exit):
        """If no media_content_type was present, defaults to 'music'."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            content_id="http://stream.example.com",
        )
        await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        restore_call = hass.services.async_call.call_args_list[1]
        assert restore_call[0][2]["media_content_type"] == "music"

    @pytest.mark.asyncio
    async def test_restore_timeout_logs_warning_not_failure(self, _mock_wait, _mock_wait_exit):
        """Restore timeout should log warning but still return 'restore'."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            content_id="http://stream.example.com",
        )
        # First call (TTS) succeeds, second call (restore) times out
        hass.services.async_call = AsyncMock(
            side_effect=[None, asyncio.TimeoutError()],
        )
        result = await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "restore"

    @pytest.mark.asyncio
    async def test_restore_exception_logs_warning_not_failure(self, _mock_wait, _mock_wait_exit):
        """Restore error should log warning but still return 'restore'."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            content_id="http://stream.example.com",
        )
        hass.services.async_call = AsyncMock(
            side_effect=[None, RuntimeError("connection reset")],
        )
        result = await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "restore"

    @pytest.mark.asyncio
    async def test_entity_gone_still_delivers(self, _mock_wait, _mock_wait_exit):
        """If entity disappeared before delivery, snapshot is None-safe."""
        hass = _make_hass()  # No entity
        result = await _deliver_tts_with_restore(
            hass, "media_player.kitchen", "tts.speak", {"message": "hi"},
        )
        assert result == "restore"
        # Only the TTS call, no restore attempt
        assert hass.services.async_call.await_count == 1


# ---------------------------------------------------------------------------
# log_delivery_failure
# ---------------------------------------------------------------------------

class TestLogDeliveryFailure:
    """Tests for log_delivery_failure()."""

    @pytest.mark.asyncio
    async def test_logs_with_correct_outcome(self):
        store = _make_store()
        await log_delivery_failure(
            store, "cat1", "person:r1", "Kitchen", "Title", "Msg",
            "tts.speak", "Timeout after 30s", "notif-123", None,
        )
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_FAILED
        assert kw["reason"] == "Timeout after 30s"
        assert kw["category_id"] == "cat1"
        assert kw["notification_id"] == "notif-123"


# ---------------------------------------------------------------------------
# async_send_tts — orchestrator
# ---------------------------------------------------------------------------

class TestAsyncSendTts:
    """Tests for async_send_tts() orchestrator."""

    @pytest.mark.asyncio
    async def test_announce_path_when_feature_supported(self):
        """When media player has MEDIA_ANNOUNCE_FEATURE, use announce."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
        )
        store = _make_store()
        recipient = _make_recipient()

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["delivered"]) == 1
        assert "[announce]" in result["delivered"][0]
        assert result["queued"] == []
        assert result["dropped"] == []

    @pytest.mark.asyncio
    async def test_restore_path_when_resume_true(self):
        """When resume_after_tts=True and no announce, use restore."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient(resume=True)

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["delivered"]) == 1
        assert "[restore]" in result["delivered"][0]

    @pytest.mark.asyncio
    async def test_plain_path_default(self):
        """When no announce support and resume=False, use plain."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient(resume=False)

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["delivered"]) == 1
        assert "[plain]" in result["delivered"][0]

    @pytest.mark.asyncio
    async def test_announce_overrides_resume(self):
        """Announce takes priority over resume_after_tts=True."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
        )
        store = _make_store()
        recipient = _make_recipient(resume=True)

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert "[announce]" in result["delivered"][0]

    @pytest.mark.asyncio
    async def test_missing_entity_id_drops(self):
        """Recipient without media_player_entity_id is dropped."""
        hass = _make_hass()
        store = _make_store()
        recipient = _make_recipient()
        del recipient["media_player_entity_id"]

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["dropped"]) == 1
        assert "No media player" in result["dropped"][0]
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_FAILED

    @pytest.mark.asyncio
    async def test_empty_entity_id_drops(self):
        """Recipient with empty media_player_entity_id is dropped."""
        hass = _make_hass()
        store = _make_store()
        recipient = _make_recipient()
        recipient["media_player_entity_id"] = ""

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["dropped"]) == 1

    @pytest.mark.asyncio
    async def test_timeout_error_drops_with_log(self):
        """Timeout during TTS delivery results in drop + log."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)
        store = _make_store()
        recipient = _make_recipient()

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["dropped"]) == 1
        assert "Timeout" in result["dropped"][0]
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_FAILED

    @pytest.mark.asyncio
    async def test_ha_error_drops_with_log(self):
        """HomeAssistantError during TTS delivery results in drop + log."""
        from homeassistant.exceptions import HomeAssistantError

        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("service not found"),
        )
        store = _make_store()
        recipient = _make_recipient()

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["dropped"]) == 1
        assert "service not found" in result["dropped"][0]

    @pytest.mark.asyncio
    async def test_unexpected_error_drops_with_log(self):
        """Unexpected exception results in drop + log."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        hass.services.async_call = AsyncMock(
            side_effect=RuntimeError("network down"),
        )
        store = _make_store()
        recipient = _make_recipient()

        result = await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["dropped"]) == 1
        assert "network down" in result["dropped"][0]

    @pytest.mark.asyncio
    async def test_default_tts_service_is_tts_speak(self):
        """When recipient has no tts_service, defaults to tts.speak."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient()  # No tts_service key

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        call_args = hass.services.async_call.call_args
        assert call_args[0][0] == "tts"
        assert call_args[0][1] == "speak"

    @pytest.mark.asyncio
    async def test_custom_tts_service(self):
        """Recipient with explicit tts_service uses that service."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient(tts_service="tts.google_translate_say")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        call_args = hass.services.async_call.call_args
        assert call_args[0][0] == "tts"
        assert call_args[0][1] == "google_translate_say"

    @pytest.mark.asyncio
    async def test_success_logs_sent_outcome(self):
        """Successful delivery logs with LOG_OUTCOME_SENT."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient()

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
            notification_id="notif-42",
        )

        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SENT
        assert kw["notification_id"] == "notif-42"
        assert kw["category_id"] == "cat1"

    @pytest.mark.asyncio
    async def test_person_id_format(self):
        """person_id should be 'recipient:{recipient_id}'."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient(recipient_id="speaker_kitchen")

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        kw = store.async_add_log.call_args[1]
        assert kw["person_id"] == "recipient:speaker_kitchen"

    @pytest.mark.asyncio
    async def test_image_url_from_data(self):
        """image_url is extracted from data dict."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient()

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
            data={"image": "http://img.png"},
        )

        kw = store.async_add_log.call_args[1]
        assert kw["image_url"] == "http://img.png"

    @pytest.mark.asyncio
    async def test_none_data_no_image(self):
        """When data is None, image_url should be None."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient()

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
            data=None,
        )

        kw = store.async_add_log.call_args[1]
        assert kw["image_url"] is None

    @pytest.mark.asyncio
    async def test_recipient_name_fallback(self):
        """When name is missing, falls back to recipient_id."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_store()
        recipient = _make_recipient()
        del recipient["name"]

        await async_send_tts(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        kw = store.async_add_log.call_args[1]
        assert kw["person_name"] == "speaker_kitchen"
