"""Tests for custom_components.ticker.recipient_notify module.

Covers async_send_to_recipient (push + TTS branching),
_async_send_push (format detection, critical injection, error handling),
and async_handle_conditional_recipient (deliver/queue/skip paths).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.recipient_notify import (
    async_handle_conditional_recipient,
    async_send_to_recipient,
    _async_send_push,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_RICH,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_SKIPPED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_store(
    category: dict | None = None,
    conditions: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    store.get_category.return_value = category
    store.get_subscription_conditions.return_value = conditions
    return store


def _push_recipient(
    recipient_id: str = "tv_living",
    name: str = "Living Room TV",
    services: list | None = None,
    delivery_format: str = "auto",
) -> dict:
    return {
        "recipient_id": recipient_id,
        "name": name,
        "device_type": DEVICE_TYPE_PUSH,
        "notify_services": services if services is not None else [{"service": "notify.tv_living", "name": "TV"}],
        "delivery_format": delivery_format,
    }


def _tts_recipient(
    recipient_id: str = "speaker_kitchen",
    name: str = "Kitchen Speaker",
) -> dict:
    return {
        "recipient_id": recipient_id,
        "name": name,
        "device_type": DEVICE_TYPE_TTS,
        "media_player_entity_id": "media_player.kitchen",
    }


# ---------------------------------------------------------------------------
# async_send_to_recipient — routing
# ---------------------------------------------------------------------------

class TestAsyncSendToRecipient:
    """Verify routing between push and TTS paths."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.recipient_notify.async_send_tts", new_callable=AsyncMock)
    async def test_routes_tts_to_async_send_tts(self, mock_tts):
        mock_tts.return_value = {"delivered": ["tts"], "queued": [], "dropped": []}
        hass = _make_hass()
        store = _make_store()
        recipient = _tts_recipient()

        result = await async_send_to_recipient(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        mock_tts.assert_awaited_once()
        assert result["delivered"] == ["tts"]

    @pytest.mark.asyncio
    async def test_routes_push_to_send_push(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient()

        result = await async_send_to_recipient(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        assert len(result["delivered"]) == 1
        hass.services.async_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_defaults_to_push_when_no_device_type(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient()
        del recipient["device_type"]  # missing key

        result = await async_send_to_recipient(
            hass, store, recipient, "cat1", "Title", "Hello",
        )

        hass.services.async_call.assert_awaited_once()
        assert len(result["delivered"]) == 1


# ---------------------------------------------------------------------------
# _async_send_push
# ---------------------------------------------------------------------------

class TestAsyncSendPush:
    """Tests for push notification delivery to recipients."""

    @pytest.mark.asyncio
    async def test_no_services_drops(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(services=[])

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert len(result["dropped"]) == 1
        assert "No notify services" in result["dropped"][0]
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_FAILED

    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Hello",
            notification_id="n1",
        )

        assert result["delivered"] == ["notify.tv_living"]
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SENT
        assert kw["notification_id"] == "n1"

    @pytest.mark.asyncio
    async def test_timeout_drops(self):
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)
        store = _make_store()
        recipient = _push_recipient()

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert len(result["dropped"]) == 1
        assert "Timeout" in result["dropped"][0]

    @pytest.mark.asyncio
    async def test_ha_error_drops(self):
        from homeassistant.exceptions import HomeAssistantError

        hass = _make_hass()
        hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("service gone"),
        )
        store = _make_store()
        recipient = _push_recipient()

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert len(result["dropped"]) == 1
        assert "service gone" in result["dropped"][0]

    @pytest.mark.asyncio
    async def test_unexpected_error_drops(self):
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
        store = _make_store()
        recipient = _push_recipient()

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert len(result["dropped"]) == 1
        assert "boom" in result["dropped"][0]

    @pytest.mark.asyncio
    async def test_person_id_format(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(recipient_id="tv1")

        await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        kw = store.async_add_log.call_args[1]
        assert kw["person_id"] == "recipient:tv1"

    @pytest.mark.asyncio
    async def test_skips_empty_service_id(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(
            services=[{"service": "", "name": "Empty"}, {"service": "notify.tv", "name": "TV"}],
        )

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        # Only the valid service should be called
        assert result["delivered"] == ["notify.tv"]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.recipient_notify.detect_delivery_format")
    @patch("custom_components.ticker.recipient_notify.resolve_ios_platform")
    async def test_auto_format_ios_overrides_to_plain(self, mock_ios, mock_detect):
        """Auto delivery_format with iOS device should override to plain."""
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = True

        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(delivery_format="auto")

        await _async_send_push(
            hass, store, recipient, "cat1", "Title", "<b>Hello</b>",
        )

        # Verify the payload had HTML stripped (plain format)
        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert "<b>" not in payload.get("message", "")

    @pytest.mark.asyncio
    async def test_critical_injection(self):
        """When data has critical=True, critical payload is injected."""
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
            data={"critical": True},
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert payload["data"]["importance"] == "high"

    @pytest.mark.asyncio
    async def test_multiple_services_all_delivered(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient(
            services=[
                {"service": "notify.svc1", "name": "S1"},
                {"service": "notify.svc2", "name": "S2"},
            ],
            delivery_format=DELIVERY_FORMAT_RICH,
        )

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert set(result["delivered"]) == {"notify.svc1", "notify.svc2"}
        assert hass.services.async_call.await_count == 2

    @pytest.mark.asyncio
    async def test_image_url_from_data(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient()

        await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
            data={"image": "http://img.png"},
        )

        kw = store.async_add_log.call_args[1]
        assert kw["image_url"] == "http://img.png"

    @pytest.mark.asyncio
    async def test_none_data_no_crash(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _push_recipient()

        result = await _async_send_push(
            hass, store, recipient, "cat1", "Title", "Msg",
            data=None,
        )

        assert len(result["delivered"]) == 1


# ---------------------------------------------------------------------------
# async_handle_conditional_recipient
# ---------------------------------------------------------------------------

class TestAsyncHandleConditionalRecipient:
    """Tests for conditional delivery logic for recipients."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_delivers_when_conditions_met(self, mock_deliver):
        mock_deliver.return_value = (True, "All met")

        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _push_recipient()

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            result = await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "Title", "Msg",
            )

        mock_send.assert_awaited_once()
        assert result["delivered"] == ["svc"]

    @pytest.mark.asyncio
    async def test_no_conditions_sends_immediately(self):
        hass = _make_hass()
        store = _make_store(conditions=None)
        recipient = _push_recipient()

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            result = await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "Title", "Msg",
            )

        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_rules_sends_immediately(self):
        hass = _make_hass()
        store = _make_store(conditions={"rules": []})
        recipient = _push_recipient()

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            result = await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "Title", "Msg",
            )

        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_queues_when_queue_flag_set(self, mock_deliver, mock_queue):
        mock_deliver.return_value = (False, "Time not met")
        mock_queue.return_value = (True, "Queue until time met")

        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _push_recipient()

        result = await async_handle_conditional_recipient(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        store.async_add_to_queue.assert_awaited_once()
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_QUEUED
        assert len(result["queued"]) == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_skips_when_no_delivery_path(self, mock_deliver, mock_queue):
        mock_deliver.return_value = (False, "Time not met")
        mock_queue.return_value = (False, "No queue flag")

        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _push_recipient()

        result = await async_handle_conditional_recipient(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SKIPPED
        assert len(result["dropped"]) == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_passes_none_person_state(self, mock_deliver):
        """Recipients pass person_state=None to skip zone rules."""
        mock_deliver.return_value = (True, "OK")

        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "zone"}]})
        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": [], "queued": [], "dropped": []},
        ):
            await async_handle_conditional_recipient(
                hass, store, _push_recipient(), "cat1", "T", "M",
            )

        # Verify person_state=None was passed
        call_args = mock_deliver.call_args
        assert call_args[0][2] is None  # third positional arg is person_state
