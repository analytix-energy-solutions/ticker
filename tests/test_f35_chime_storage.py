"""Tests for F-35 Pre-TTS Chime — schema + storage layer.

Covers:
- const.py: CHIME_WAIT_TIMEOUT, ATTR_CHIME_MEDIA_CONTENT_ID,
  MAX_CHIME_MEDIA_CONTENT_ID_LENGTH constants
- store/recipients.py: chime_media_content_id round-trip via store
  (sparse on TTS; silently dropped on push)
- store/categories.py: chime_media_content_id round-trip (sparse)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store.recipients import RecipientMixin
from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.const import (
    ATTR_CHIME_MEDIA_CONTENT_ID,
    CHIME_WAIT_TIMEOUT,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    MAX_CHIME_MEDIA_CONTENT_ID_LENGTH,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestChimeConstants:
    """Verify F-35 constants are defined correctly."""

    def test_attr_chime_media_content_id_value(self):
        assert ATTR_CHIME_MEDIA_CONTENT_ID == "chime_media_content_id"

    def test_chime_wait_timeout_value(self):
        assert CHIME_WAIT_TIMEOUT == 10.0

    def test_max_length_value(self):
        assert MAX_CHIME_MEDIA_CONTENT_ID_LENGTH == 500


# ---------------------------------------------------------------------------
# Recipient store round-trip
# ---------------------------------------------------------------------------

class FakeRecipientStore(RecipientMixin):
    def __init__(self, recipients=None, subscriptions=None):
        self.hass = MagicMock()
        self._recipients: dict = recipients if recipients is not None else {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self.async_save_subscriptions = AsyncMock()
        self._subscription_listeners: list = []

    def _notify_subscription_change(self) -> None:
        pass


class TestRecipientChimeStorage:
    """Sparse-storage round-trip for chime_media_content_id on recipients."""

    @pytest.mark.asyncio
    async def test_create_tts_with_chime_persists_value(self):
        store = FakeRecipientStore()
        chime = "media-source://media_source/local/chimes/ding.mp3"
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            chime_media_content_id=chime,
        )
        assert rec["chime_media_content_id"] == chime

    @pytest.mark.asyncio
    async def test_create_tts_without_chime_omits_key(self):
        """Sparse storage: missing chime means missing key, not None."""
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        assert "chime_media_content_id" not in rec

    @pytest.mark.asyncio
    async def test_create_tts_with_empty_chime_omits_key(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            chime_media_content_id="",
        )
        assert "chime_media_content_id" not in rec

    @pytest.mark.asyncio
    async def test_create_tts_chime_is_stripped(self):
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            chime_media_content_id="  media-source://x  ",
        )
        assert rec["chime_media_content_id"] == "media-source://x"

    @pytest.mark.asyncio
    async def test_create_push_drops_chime_silently(self):
        """Push-type recipients silently drop chime per spec §6.1."""
        store = FakeRecipientStore()
        rec = await store.async_create_recipient(
            recipient_id="phone",
            name="Phone",
            device_type=DEVICE_TYPE_PUSH,
            notify_services=[{"service": "notify.mobile_app_x", "name": "X"}],
            chime_media_content_id="media-source://x",
        )
        assert "chime_media_content_id" not in rec

    @pytest.mark.asyncio
    async def test_update_sets_chime(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        rec = await store.async_update_recipient(
            "kitchen",
            chime_media_content_id="media-source://new",
        )
        assert rec["chime_media_content_id"] == "media-source://new"

    @pytest.mark.asyncio
    async def test_update_with_empty_clears_chime(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            chime_media_content_id="media-source://x",
        )
        rec = await store.async_update_recipient(
            "kitchen", chime_media_content_id="",
        )
        assert "chime_media_content_id" not in rec

    @pytest.mark.asyncio
    async def test_update_with_none_clears_chime(self):
        store = FakeRecipientStore()
        await store.async_create_recipient(
            recipient_id="kitchen",
            name="Kitchen",
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            chime_media_content_id="media-source://x",
        )
        rec = await store.async_update_recipient(
            "kitchen", chime_media_content_id=None,
        )
        assert "chime_media_content_id" not in rec


# ---------------------------------------------------------------------------
# Category store round-trip
# ---------------------------------------------------------------------------

class FakeCategoryStore(CategoryMixin):
    def __init__(self, categories=None):
        self.hass = MagicMock()
        self._categories: dict = categories if categories is not None else {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


class TestCategoryChimeStorage:
    """Sparse-storage round-trip for chime_media_content_id on categories."""

    @pytest.mark.asyncio
    async def test_create_with_chime_persists_value(self):
        store = FakeCategoryStore()
        chime = "media-source://media_source/local/chimes/alarm.mp3"
        cat = await store.async_create_category(
            category_id="security",
            name="Security",
            chime_media_content_id=chime,
        )
        assert cat["chime_media_content_id"] == chime

    @pytest.mark.asyncio
    async def test_create_without_chime_omits_key(self):
        store = FakeCategoryStore()
        cat = await store.async_create_category(
            category_id="security",
            name="Security",
        )
        assert "chime_media_content_id" not in cat

    @pytest.mark.asyncio
    async def test_create_with_empty_chime_omits_key(self):
        store = FakeCategoryStore()
        cat = await store.async_create_category(
            category_id="security",
            name="Security",
            chime_media_content_id="",
        )
        assert "chime_media_content_id" not in cat

    @pytest.mark.asyncio
    async def test_update_sets_chime(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security", name="Security",
        )
        cat = await store.async_update_category(
            category_id="security",
            chime_media_content_id="media-source://x",
        )
        assert cat["chime_media_content_id"] == "media-source://x"

    @pytest.mark.asyncio
    async def test_update_with_empty_clears_chime(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security",
            name="Security",
            chime_media_content_id="media-source://x",
        )
        cat = await store.async_update_category(
            category_id="security",
            chime_media_content_id="",
        )
        assert "chime_media_content_id" not in cat

    @pytest.mark.asyncio
    async def test_update_strips_whitespace(self):
        store = FakeCategoryStore()
        await store.async_create_category(
            category_id="security", name="Security",
        )
        cat = await store.async_update_category(
            category_id="security",
            chime_media_content_id="  media-source://x  ",
        )
        assert cat["chime_media_content_id"] == "media-source://x"
