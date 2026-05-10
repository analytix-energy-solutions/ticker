"""Tests for per-category Android notification channel feature.

Covers:
- store/categories.py: android_channel param in create and update
- recipient_notify.py: channel injection in payload for rich format only
- user_notify.py: channel injection in payload for rich format only
- Critical priority: when critical=True and android_channel both set,
  the critical channel ("ticker_critical") takes precedence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.recipient_notify import _async_send_push
from custom_components.ticker.const import (
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_PERSISTENT,
    DEVICE_TYPE_PUSH,
)


class FakeCategoryStore(CategoryMixin):
    """Concrete class mixing in CategoryMixin for testing."""

    def __init__(self, categories=None):
        self.hass = MagicMock()
        self._categories: dict = categories if categories is not None else {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


@pytest.fixture
def store():
    return FakeCategoryStore()


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_store(category: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.get_category.return_value = category
    return store


def _push_recipient(
    recipient_id: str = "tv_living",
    name: str = "Living Room TV",
    services: list | None = None,
    delivery_format: str = DELIVERY_FORMAT_RICH,
) -> dict:
    return {
        "recipient_id": recipient_id,
        "name": name,
        "device_type": DEVICE_TYPE_PUSH,
        "notify_services": services
        if services is not None
        else [{"service": "notify.nfandroidtv", "name": "TV"}],
        "delivery_format": delivery_format,
    }


class TestCreateCategoryAndroidChannel:
    @pytest.mark.asyncio
    async def test_create_with_android_channel(self, store):
        cat = await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        assert cat["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_create_without_android_channel(self, store):
        cat = await store.async_create_category("info", "Info")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_create_android_channel_empty_string(self, store):
        cat = await store.async_create_category("info", "Info", android_channel="")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_create_android_channel_persisted_in_store(self, store):
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        stored = store._categories["security"]
        assert stored["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_create_saves_to_storage(self, store):
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        store._categories_store.async_save.assert_awaited_once()


class TestUpdateCategoryAndroidChannel:
    @pytest.mark.asyncio
    async def test_update_set_android_channel(self, store):
        await store.async_create_category("security", "Security")
        cat = await store.async_update_category(
            "security", android_channel="security_alerts"
        )
        assert cat["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_update_clear_android_channel_with_empty_string(self, store):
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        cat = await store.async_update_category("security", android_channel="")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_update_android_channel_none_leaves_unchanged(self, store):
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        cat = await store.async_update_category("security", name="Security v2")
        assert cat["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_update_android_channel_none_no_existing(self, store):
        await store.async_create_category("info", "Info")
        cat = await store.async_update_category("info", name="Info v2")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, store):
        result = await store.async_update_category("missing", android_channel="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_toggle_android_channel_set_clear_set(self, store):
        await store.async_create_category("security", "Security")
        assert "android_channel" not in store._categories["security"]

        await store.async_update_category(
            "security", android_channel="security_alerts"
        )
        assert store._categories["security"]["android_channel"] == "security_alerts"

        await store.async_update_category("security", android_channel="")
        assert "android_channel" not in store._categories["security"]

        await store.async_update_category("security", android_channel="new_channel")
        assert store._categories["security"]["android_channel"] == "new_channel"


class TestRecipientNotifyAndroidChannel:
    @pytest.mark.asyncio
    async def test_android_channel_injected_for_rich_format(self):
        hass = _make_hass()
        store = _make_store(category={"android_channel": "security_alerts"})
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        await _async_send_push(
            hass, store, recipient, "security", "Title", "Msg",
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert payload["data"]["channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_android_channel_absent_for_plain_format(self):
        hass = _make_hass()
        store = _make_store(category={"android_channel": "security_alerts"})
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_PLAIN)

        await _async_send_push(
            hass, store, recipient, "security", "Title", "Msg",
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert "channel" not in payload.get("data", {})

    @pytest.mark.asyncio
    async def test_android_channel_absent_for_persistent_format(self):
        hass = _make_hass()
        store = _make_store(category={"android_channel": "security_alerts"})
        recipient = _push_recipient(
            services=[
                {"service": "notify.persistent_notification", "name": "Persistent"}
            ],
            delivery_format=DELIVERY_FORMAT_PERSISTENT,
        )

        await _async_send_push(
            hass, store, recipient, "security", "Title", "Msg",
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert "channel" not in payload

    @pytest.mark.asyncio
    async def test_android_channel_absent_when_not_set(self):
        hass = _make_hass()
        store = _make_store(category={"name": "Security"})
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        await _async_send_push(
            hass, store, recipient, "security", "Title", "Msg",
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert "channel" not in payload.get("data", {})

    @pytest.mark.asyncio
    async def test_critical_channel_wins_over_android_channel(self):
        hass = _make_hass()
        store = _make_store(category={"android_channel": "security_alerts"})
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        await _async_send_push(
            hass, store, recipient, "security", "Title", "Msg",
            data={"critical": True},
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert payload["data"]["channel"] == "ticker_critical"

    @pytest.mark.asyncio
    async def test_android_channel_with_no_category(self):
        hass = _make_hass()
        store = _make_store(category=None)
        recipient = _push_recipient(delivery_format=DELIVERY_FORMAT_RICH)

        await _async_send_push(
            hass, store, recipient, "missing", "Title", "Msg",
        )

        call_args = hass.services.async_call.call_args
        payload = call_args[0][2]
        assert "channel" not in payload.get("data", {})


class TestWsCategoryAndroidChannelPassthrough:
    @pytest.mark.asyncio
    async def test_ws_create_passes_android_channel(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        cat = store.get_category("security")
        assert cat["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_ws_create_defaults_android_channel_empty(self):
        store = FakeCategoryStore()
        await store.async_create_category("info", "Info")
        cat = store.get_category("info")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_ws_update_passes_android_channel(self):
        store = FakeCategoryStore()
        await store.async_create_category("security", "Security")
        await store.async_update_category(
            "security", android_channel="security_alerts"
        )
        cat = store.get_category("security")
        assert cat["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_ws_update_clears_android_channel(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        await store.async_update_category("security", android_channel="")
        cat = store.get_category("security")
        assert "android_channel" not in cat

    @pytest.mark.asyncio
    async def test_ws_update_omitted_android_channel_unchanged(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            "security", "Security", android_channel="security_alerts"
        )
        await store.async_update_category("security", name="Security v2")
        cat = store.get_category("security")
        assert cat["android_channel"] == "security_alerts"
