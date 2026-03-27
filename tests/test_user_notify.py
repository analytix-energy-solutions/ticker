"""Tests for custom_components.ticker.user_notify module.

Covers async_send_notification (format detection, iOS override, critical
injection, device preferences) and async_handle_conditional_notification
(deliver/queue/skip paths).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.user_notify import (
    async_handle_conditional_notification,
    async_send_notification,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_RICH,
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
    LOG_OUTCOME_FAILED,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SENT,
    LOG_OUTCOME_SKIPPED,
    LOG_OUTCOME_SNOOZED,
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
    snoozed: bool = False,
    device_pref: dict | None = None,
    device_override: dict | None = None,
    category: dict | None = None,
    conditions: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    store.is_snoozed.return_value = snoozed
    store.get_device_preference.return_value = device_pref or {"mode": DEVICE_MODE_ALL}
    store.get_device_override.return_value = device_override
    store.get_category.return_value = category
    store.get_subscription_conditions.return_value = conditions
    return store


def _services_list(service_ids: list[str]) -> list[dict]:
    return [{"service": s, "name": s, "device_id": f"dev_{i}"} for i, s in enumerate(service_ids)]


# ---------------------------------------------------------------------------
# async_send_notification
# ---------------------------------------------------------------------------

class TestAsyncSendNotification:
    """Tests for async_send_notification()."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_successful_delivery(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list(["notify.mobile_app_phone"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={}, notification_id="n1",
        )

        assert result["delivered"] == ["notify.mobile_app_phone"]
        hass.services.async_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snoozed_drops(self):
        hass = _make_hass()
        store = _make_store(snoozed=True)

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        assert len(result["dropped"]) == 1
        assert "Snoozed" in result["dropped"][0]
        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SNOOZED

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    async def test_no_services_fails(self, mock_discover):
        mock_discover.return_value = []

        hass = _make_hass()
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        assert len(result["dropped"]) == 1
        assert "No notify services" in result["dropped"][0]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_ios_overrides_to_plain(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list(["notify.mobile_app_iphone"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = True

        hass = _make_hass()
        store = _make_store()

        await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title",
            "<b>Hello</b>", data={},
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        # Plain format strips HTML
        assert "<b>" not in payload.get("message", "")

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_selected_devices_filters(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list([
            "notify.mobile_app_phone", "notify.mobile_app_tablet",
        ])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store(device_pref={
            "mode": DEVICE_MODE_SELECTED,
            "devices": ["notify.mobile_app_phone"],
        })

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        assert result["delivered"] == ["notify.mobile_app_phone"]
        assert hass.services.async_call.await_count == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_device_override_adds_devices(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list([
            "notify.mobile_app_phone", "notify.mobile_app_tablet",
        ])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store(
            device_pref={
                "mode": DEVICE_MODE_SELECTED,
                "devices": ["notify.mobile_app_phone"],
            },
            device_override={
                "enabled": True,
                "devices": ["notify.mobile_app_tablet"],
            },
        )

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        assert set(result["delivered"]) == {
            "notify.mobile_app_phone", "notify.mobile_app_tablet",
        }

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_timeout_error_logged(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list(["notify.svc"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=asyncio.TimeoutError)
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        assert len(result["dropped"]) == 1
        assert "Timeout" in result["dropped"][0]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_critical_injection(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list(["notify.svc"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={"critical": True},
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert payload["data"]["importance"] == "high"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_deep_link_injection(self, mock_ios, mock_detect, mock_discover):
        mock_discover.return_value = _services_list(["notify.svc"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert payload["data"]["url"] == "/ticker#history"
        assert payload["data"]["clickAction"] == "/ticker#history"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_no_target_devices_after_prefs(self, mock_ios, mock_detect, mock_discover):
        """Selected device mode with no valid devices falls back to all."""
        mock_discover.return_value = _services_list(["notify.mobile_app_phone"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store(device_pref={
            "mode": DEVICE_MODE_SELECTED,
            "devices": ["notify.nonexistent"],
        })

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={},
        )

        # Fallback to all devices
        assert result["delivered"] == ["notify.mobile_app_phone"]


# ---------------------------------------------------------------------------
# async_handle_conditional_notification
# ---------------------------------------------------------------------------

class TestAsyncHandleConditionalNotification:
    """Tests for conditional delivery of user notifications."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_send_notification", new_callable=AsyncMock)
    async def test_no_conditions_sends_immediately(self, mock_send):
        mock_send.return_value = {"delivered": ["svc"], "queued": [], "dropped": []}

        hass = _make_hass()
        store = _make_store(conditions=None)

        result = await async_handle_conditional_notification(
            hass, store, "person.alice", "Alice", "home", "cat1",
            "Title", "Msg", {}, 48,
        )

        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_conditions_met_delivers(self, mock_deliver):
        mock_deliver.return_value = (True, "All conditions met")

        hass = _make_hass()
        store = _make_store(conditions={
            "rules": [{"type": "zone", "zone_id": "zone.home"}],
        })

        with patch(
            "custom_components.ticker.user_notify.async_send_notification",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            result = await async_handle_conditional_notification(
                hass, store, "person.alice", "Alice", "home", "cat1",
                "Title", "Msg", {}, 48,
            )

        mock_send.assert_awaited_once()
        assert result["delivered"] == ["svc"]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_conditions_not_met_queues(self, mock_deliver, mock_queue):
        mock_deliver.return_value = (False, "Not home")
        mock_queue.return_value = (True, "Queue until home")

        hass = _make_hass()
        store = _make_store(conditions={
            "rules": [{"type": "zone", "zone_id": "zone.home"}],
        })

        result = await async_handle_conditional_notification(
            hass, store, "person.alice", "Alice", "not_home", "cat1",
            "Title", "Msg", {}, 48,
        )

        store.async_add_to_queue.assert_awaited_once()
        assert len(result["queued"]) == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_conditions_not_met_skips(self, mock_deliver, mock_queue):
        mock_deliver.return_value = (False, "Not home")
        mock_queue.return_value = (False, "No queue")

        hass = _make_hass()
        store = _make_store(conditions={
            "rules": [{"type": "zone", "zone_id": "zone.home"}],
        })

        result = await async_handle_conditional_notification(
            hass, store, "person.alice", "Alice", "not_home", "cat1",
            "Title", "Msg", {}, 48,
        )

        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SKIPPED
        assert len(result["dropped"]) == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_send_notification", new_callable=AsyncMock)
    async def test_empty_rules_no_zones_sends(self, mock_send):
        """No rules and no zones means fallback to always."""
        mock_send.return_value = {"delivered": ["svc"], "queued": [], "dropped": []}

        hass = _make_hass()
        store = _make_store(conditions={"rules": []})

        result = await async_handle_conditional_notification(
            hass, store, "person.alice", "Alice", "home", "cat1",
            "Title", "Msg", {}, 48,
        )

        mock_send.assert_awaited_once()
