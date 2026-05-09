"""Tests for F-35.2 Volume Override — schema + storage layer (chunk 1).

Covers:
- const.py: ATTR_VOLUME_OVERRIDE, VOLUME_OVERRIDE_MIN/MAX,
  VOLUME_SET_SETTLE_DELAY constants
- store/recipients.py: volume_override round-trip via store
  (sparse on TTS; silently dropped on push; out-of-range dropped)
- store/categories.py: volume_override round-trip (sparse;
  clear_volume_override flag honored)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store.recipients import RecipientMixin
from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.const import (
    ATTR_VOLUME_OVERRIDE,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
    VOLUME_SET_SETTLE_DELAY,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestVolumeOverrideConstants:
    def test_attr_value(self):
        assert ATTR_VOLUME_OVERRIDE == "volume_override"

    def test_min_max_values(self):
        assert VOLUME_OVERRIDE_MIN == 0.0
        assert VOLUME_OVERRIDE_MAX == 1.0

    def test_settle_delay(self):
        # 200ms is the locked decision in the brief
        assert VOLUME_SET_SETTLE_DELAY == 0.2


# ---------------------------------------------------------------------------
# Recipient store round-trip
# ---------------------------------------------------------------------------


class FakeRecipientStore(RecipientMixin):
    def __init__(self):
        self.hass = MagicMock()
        self._recipients: dict = {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self.async_save_subscriptions = AsyncMock()
        self._subscription_listeners: list = []

    def _notify_subscription_change(self) -> None:
        pass


class TestRecipientVolumeStorage:
    @pytest.mark.asyncio
    async def test_create_tts_with_volume_persists(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=0.6,
        )
        assert rec["volume_override"] == 0.6

    @pytest.mark.asyncio
    async def test_create_tts_without_volume_omits_key(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        assert "volume_override" not in rec

    @pytest.mark.asyncio
    async def test_create_tts_with_none_volume_omits_key(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=None,
        )
        assert "volume_override" not in rec

    @pytest.mark.asyncio
    async def test_create_tts_out_of_range_drops_key(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=1.5,
        )
        assert "volume_override" not in rec

    @pytest.mark.asyncio
    async def test_create_tts_zero_is_valid(self):
        """Zero volume is a valid in-range value (silent)."""
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=0.0,
        )
        assert rec["volume_override"] == 0.0

    @pytest.mark.asyncio
    async def test_create_tts_one_is_valid(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=1.0,
        )
        assert rec["volume_override"] == 1.0

    @pytest.mark.asyncio
    async def test_create_push_drops_volume_silently(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="phone",
            name="Phone",
            device_type=DEVICE_TYPE_PUSH,
            notify_services=[{"service": "notify.x", "name": "X"}],
            volume_override=0.5,
        )
        assert "volume_override" not in rec

    @pytest.mark.asyncio
    async def test_update_sets_volume(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        rec = await store.async_update_recipient(
            "kitchen", volume_override=0.4,
        )
        assert rec["volume_override"] == 0.4

    @pytest.mark.asyncio
    async def test_update_with_none_clears_volume(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=0.7,
        )
        rec = await store.async_update_recipient(
            "kitchen", volume_override=None,
        )
        assert "volume_override" not in rec

    @pytest.mark.asyncio
    async def test_update_with_out_of_range_clears_volume(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            volume_override=0.7,
        )
        rec = await store.async_update_recipient(
            "kitchen", volume_override=2.0,
        )
        assert "volume_override" not in rec


# ---------------------------------------------------------------------------
# Category store round-trip
# ---------------------------------------------------------------------------


class FakeCategoryStore(CategoryMixin):
    def __init__(self):
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


class TestCategoryVolumeStorage:
    @pytest.mark.asyncio
    async def test_create_with_volume_persists(self):
        store = FakeCategoryStore()
        cat = await store.async_create_category(
            category_id="security",
            name="Security",
            volume_override=0.8,
        )
        assert cat["volume_override"] == 0.8

    @pytest.mark.asyncio
    async def test_create_without_volume_omits_key(self):
        store = FakeCategoryStore()
        cat = await store.async_create_category(
            category_id="security", name="Security",
        )
        assert "volume_override" not in cat

    @pytest.mark.asyncio
    async def test_create_out_of_range_drops(self):
        store = FakeCategoryStore()
        cat = await store.async_create_category(
            category_id="security",
            name="Security",
            volume_override=1.5,
        )
        assert "volume_override" not in cat

    @pytest.mark.asyncio
    async def test_update_sets_volume(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security", name="Security",
        )
        cat = await store.async_update_category(
            category_id="security",
            volume_override=0.3,
        )
        assert cat["volume_override"] == 0.3

    @pytest.mark.asyncio
    async def test_update_clear_flag_removes_volume(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security",
            name="Security",
            volume_override=0.7,
        )
        cat = await store.async_update_category(
            category_id="security",
            clear_volume_override=True,
        )
        assert "volume_override" not in cat

    @pytest.mark.asyncio
    async def test_update_out_of_range_clears(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security",
            name="Security",
            volume_override=0.7,
        )
        cat = await store.async_update_category(
            category_id="security",
            volume_override=99.0,
        )
        assert "volume_override" not in cat
