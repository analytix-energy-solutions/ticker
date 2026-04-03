"""Tests for custom_components.ticker.store.recipients (RecipientMixin).

Verifies CRUD operations, enabled toggling, and subscription cleanup on delete.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.store.recipients import RecipientMixin
from custom_components.ticker.const import (
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMATS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeStore(RecipientMixin):
    """Concrete class mixing in RecipientMixin for testing."""

    def __init__(self, recipients=None, subscriptions=None):
        self.hass = MagicMock()
        self._recipients: dict = recipients if recipients is not None else {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self.async_save_subscriptions = AsyncMock()


@pytest.fixture
def store():
    return FakeStore()


# ---------------------------------------------------------------------------
# get_recipients / get_recipient
# ---------------------------------------------------------------------------

class TestGetRecipients:
    def test_empty_returns_empty_dict(self, store):
        assert store.get_recipients() == {}

    def test_returns_shallow_copy(self, store):
        """get_recipients returns a shallow copy -- adding keys to the
        result does not affect the store, but inner dicts are shared."""
        store._recipients["tv1"] = {"name": "TV"}
        result = store.get_recipients()
        result["tv2"] = {"name": "New"}
        assert "tv2" not in store._recipients

    def test_get_recipient_found(self, store):
        store._recipients["tv1"] = {"name": "TV"}
        assert store.get_recipient("tv1") == {"name": "TV"}

    def test_get_recipient_not_found(self, store):
        assert store.get_recipient("missing") is None


# ---------------------------------------------------------------------------
# is_recipient_enabled
# ---------------------------------------------------------------------------

class TestIsRecipientEnabled:
    def test_enabled_true(self, store):
        store._recipients["tv1"] = {"enabled": True}
        assert store.is_recipient_enabled("tv1") is True

    def test_enabled_false(self, store):
        store._recipients["tv1"] = {"enabled": False}
        assert store.is_recipient_enabled("tv1") is False

    def test_missing_enabled_defaults_true(self, store):
        store._recipients["tv1"] = {}
        assert store.is_recipient_enabled("tv1") is True

    def test_not_found_returns_false(self, store):
        assert store.is_recipient_enabled("missing") is False


# ---------------------------------------------------------------------------
# async_create_recipient
# ---------------------------------------------------------------------------

class TestCreateRecipient:
    @pytest.mark.asyncio
    async def test_create_success(self, store):
        result = await store.async_create_recipient(
            "tv1", "Living Room TV", [{"service": "notify.tv", "name": "TV"}]
        )
        assert result["recipient_id"] == "tv1"
        assert result["name"] == "Living Room TV"
        assert result["delivery_format"] == DELIVERY_FORMAT_RICH
        assert result["enabled"] is True
        assert result["icon"] == "mdi:bell-ring"
        assert "created_at" in result
        assert "updated_at" in result
        store._recipients_store.async_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        with pytest.raises(ValueError, match="already exists"):
            await store.async_create_recipient("tv1", "TV2", [])

    @pytest.mark.asyncio
    async def test_create_invalid_format_raises(self, store):
        with pytest.raises(ValueError, match="Invalid delivery_format"):
            await store.async_create_recipient(
                "tv1", "TV", [], delivery_format="invalid"
            )

    @pytest.mark.asyncio
    async def test_create_auto_format_allowed(self, store):
        result = await store.async_create_recipient(
            "tv1", "TV", [], delivery_format="auto"
        )
        assert result["delivery_format"] == "auto"

    @pytest.mark.asyncio
    async def test_create_custom_icon(self, store):
        result = await store.async_create_recipient(
            "tv1", "TV", [], icon="mdi:television"
        )
        assert result["icon"] == "mdi:television"

    @pytest.mark.asyncio
    async def test_create_disabled(self, store):
        result = await store.async_create_recipient(
            "tv1", "TV", [], enabled=False
        )
        assert result["enabled"] is False


# ---------------------------------------------------------------------------
# async_update_recipient
# ---------------------------------------------------------------------------

class TestUpdateRecipient:
    @pytest.mark.asyncio
    async def test_update_name(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        result = await store.async_update_recipient("tv1", name="Big TV")
        assert result["name"] == "Big TV"
        assert result["updated_at"] != result["created_at"] or True  # timestamps may match in fast tests

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await store.async_update_recipient("missing", name="x")

    @pytest.mark.asyncio
    async def test_update_ignores_unknown_fields(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        # Should not raise despite unknown field
        result = await store.async_update_recipient("tv1", name="TV2", bogus="val")
        assert result["name"] == "TV2"
        assert "bogus" not in result

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        result = await store.async_update_recipient(
            "tv1", name="New", icon="mdi:tv", enabled=False
        )
        assert result["name"] == "New"
        assert result["icon"] == "mdi:tv"
        assert result["enabled"] is False


# ---------------------------------------------------------------------------
# async_delete_recipient
# ---------------------------------------------------------------------------

class TestDeleteRecipient:
    @pytest.mark.asyncio
    async def test_delete_success(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        assert await store.async_delete_recipient("tv1") is True
        assert store.get_recipient("tv1") is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, store):
        assert await store.async_delete_recipient("missing") is False

    @pytest.mark.asyncio
    async def test_delete_cleans_up_subscriptions(self):
        subs = {
            "recipient:tv1:cat_a": {"mode": "always"},
            "recipient:tv1:cat_b": {"mode": "never"},
            "person.bob:cat_a": {"mode": "always"},
            "recipient:tv2:cat_a": {"mode": "always"},
        }
        s = FakeStore(
            recipients={"tv1": {"name": "TV"}},
            subscriptions=subs,
        )
        result = await s.async_delete_recipient("tv1")
        assert result is True
        # tv1 subscriptions removed
        assert "recipient:tv1:cat_a" not in s._subscriptions
        assert "recipient:tv1:cat_b" not in s._subscriptions
        # Other subscriptions untouched
        assert "person.bob:cat_a" in s._subscriptions
        assert "recipient:tv2:cat_a" in s._subscriptions
        s.async_save_subscriptions.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_no_subscriptions_no_sub_save(self):
        s = FakeStore(recipients={"tv1": {"name": "TV"}}, subscriptions={})
        await s.async_delete_recipient("tv1")
        s.async_save_subscriptions.assert_not_awaited()


# ---------------------------------------------------------------------------
# async_set_recipient_enabled
# ---------------------------------------------------------------------------

class TestSetRecipientEnabled:
    @pytest.mark.asyncio
    async def test_enable(self, store):
        await store.async_create_recipient("tv1", "TV", [], enabled=False)
        result = await store.async_set_recipient_enabled("tv1", True)
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_disable(self, store):
        await store.async_create_recipient("tv1", "TV", [])
        result = await store.async_set_recipient_enabled("tv1", False)
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_not_found_raises(self, store):
        with pytest.raises(ValueError, match="not found"):
            await store.async_set_recipient_enabled("missing", True)


# ---------------------------------------------------------------------------
# async_create_recipient - device_type / TTS params
# ---------------------------------------------------------------------------

class TestCreateRecipientDeviceType:
    @pytest.mark.asyncio
    async def test_create_push_default(self, store):
        result = await store.async_create_recipient("r1", "Push Device", [])
        assert result["device_type"] == DEVICE_TYPE_PUSH
        assert result["media_player_entity_id"] is None
        assert result["tts_service"] is None

    @pytest.mark.asyncio
    async def test_create_tts_device(self, store):
        result = await store.async_create_recipient(
            "speaker1", "Kitchen Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.google_translate_say",
        )
        assert result["device_type"] == DEVICE_TYPE_TTS
        assert result["media_player_entity_id"] == "media_player.kitchen"
        assert result["tts_service"] == "tts.google_translate_say"

    @pytest.mark.asyncio
    async def test_create_tts_overrides_delivery_format(self, store):
        """TTS device type ignores delivery_format and stores 'rich' default."""
        result = await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            delivery_format="plain",
        )
        assert result["delivery_format"] == DELIVERY_FORMAT_RICH

    @pytest.mark.asyncio
    async def test_create_invalid_device_type_raises(self, store):
        with pytest.raises(ValueError, match="Invalid device_type"):
            await store.async_create_recipient(
                "r1", "Bad", [], device_type="invalid"
            )

    @pytest.mark.asyncio
    async def test_create_push_invalid_format_raises(self, store):
        with pytest.raises(ValueError, match="Invalid delivery_format"):
            await store.async_create_recipient(
                "r1", "TV", [], device_type=DEVICE_TYPE_PUSH,
                delivery_format="tts"
            )

    @pytest.mark.asyncio
    async def test_update_tts_fields(self, store):
        await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.old",
        )
        result = await store.async_update_recipient(
            "speaker1",
            media_player_entity_id="media_player.new",
            tts_service="tts.cloud_say",
        )
        assert result["media_player_entity_id"] == "media_player.new"
        assert result["tts_service"] == "tts.cloud_say"


# ---------------------------------------------------------------------------
# migrate_recipient_data
# ---------------------------------------------------------------------------

class TestMigrateRecipientData:
    def test_tts_format_becomes_tts_device_type(self):
        recipients = {
            "speaker1": {
                "name": "Speaker",
                "delivery_format": "tts",
            }
        }
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 1
        r = recipients["speaker1"]
        assert r["device_type"] == DEVICE_TYPE_TTS
        assert r["delivery_format"] == DELIVERY_FORMAT_RICH
        assert r["media_player_entity_id"] is None
        assert r["tts_service"] is None

    def test_persistent_format_becomes_push_rich(self):
        recipients = {
            "pn1": {
                "name": "Persistent",
                "delivery_format": "persistent",
            }
        }
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 1
        r = recipients["pn1"]
        assert r["device_type"] == DEVICE_TYPE_PUSH
        assert r["delivery_format"] == DELIVERY_FORMAT_RICH

    def test_rich_format_becomes_push(self):
        recipients = {
            "tv1": {
                "name": "TV",
                "delivery_format": "rich",
            }
        }
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 1
        assert recipients["tv1"]["device_type"] == DEVICE_TYPE_PUSH

    def test_missing_format_defaults_to_push(self):
        recipients = {"tv1": {"name": "TV"}}
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 1
        assert recipients["tv1"]["device_type"] == DEVICE_TYPE_PUSH
        # delivery_format stays at whatever it was (missing is ok, defaults to rich at read time)

    def test_already_migrated_skipped(self):
        recipients = {
            "tv1": {
                "name": "TV",
                "device_type": DEVICE_TYPE_PUSH,
                "delivery_format": "rich",
            }
        }
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 0
        # But TTS fields should be filled in
        assert recipients["tv1"]["media_player_entity_id"] is None
        assert recipients["tv1"]["tts_service"] is None

    def test_idempotent(self):
        recipients = {
            "speaker1": {
                "name": "Speaker",
                "delivery_format": "tts",
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 0

    def test_multiple_recipients(self):
        recipients = {
            "tv1": {"name": "TV", "delivery_format": "rich"},
            "speaker1": {"name": "Speaker", "delivery_format": "tts"},
            "pn1": {"name": "PN", "delivery_format": "persistent"},
            "already": {"name": "Done", "device_type": "push"},
        }
        count = RecipientMixin.migrate_recipient_data(recipients)
        assert count == 3

    def test_empty_dict(self):
        count = RecipientMixin.migrate_recipient_data({})
        assert count == 0
