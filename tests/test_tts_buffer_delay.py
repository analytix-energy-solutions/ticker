"""Tests for F-20: TTS Buffer Delay feature.

Verifies that the tts_buffer_delay constant, store CRUD, migration, and
runtime behavior in async_send_tts all work correctly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.const import (
    DELIVERY_FORMAT_PATTERNS,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMATS,
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    TTS_BUFFER_DELAY_DEFAULT,
    TTS_BUFFER_DELAY_MAX,
    TTS_BUFFER_DELAY_MIN,
)
from custom_components.ticker.store.recipients import RecipientMixin
from custom_components.ticker.recipient_tts import async_send_tts


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


def _make_hass(
    entity_id: str | None = None,
    state: str = "idle",
    features: int = 0,
) -> MagicMock:
    """Create a mock hass with a media_player state."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    if entity_id:
        attrs = {"supported_features": features}
        state_obj = SimpleNamespace(
            entity_id=entity_id,
            state=state,
            attributes=attrs,
        )
        hass.states.get = MagicMock(return_value=state_obj)
    else:
        hass.states.get = MagicMock(return_value=None)

    return hass


def _make_mock_store() -> MagicMock:
    """Create a mock TickerStore for async_send_tts tests."""
    store = MagicMock()
    store.async_add_log = AsyncMock()
    return store


def _make_recipient(
    recipient_id: str = "speaker_kitchen",
    name: str = "Kitchen Speaker",
    entity_id: str = "media_player.kitchen",
    tts_service: str | None = None,
    resume: bool = False,
    buffer_delay: float | None = None,
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
    if buffer_delay is not None:
        r["tts_buffer_delay"] = buffer_delay
    return r


@pytest.fixture
def store():
    return FakeStore()


# ---------------------------------------------------------------------------
# 1. Constants exist with correct values
# ---------------------------------------------------------------------------

class TestTtsBufferDelayConstants:
    """Verify TTS buffer delay constants in const.py."""

    def test_tts_buffer_delay_min(self):
        assert TTS_BUFFER_DELAY_MIN == 0.0

    def test_tts_buffer_delay_max(self):
        assert TTS_BUFFER_DELAY_MAX == 10.0

    def test_tts_buffer_delay_default(self):
        assert TTS_BUFFER_DELAY_DEFAULT == 0.0

    def test_min_is_float(self):
        assert isinstance(TTS_BUFFER_DELAY_MIN, float)

    def test_max_is_float(self):
        assert isinstance(TTS_BUFFER_DELAY_MAX, float)

    def test_default_is_float(self):
        assert isinstance(TTS_BUFFER_DELAY_DEFAULT, float)

    def test_min_less_than_max(self):
        assert TTS_BUFFER_DELAY_MIN < TTS_BUFFER_DELAY_MAX

    def test_default_within_range(self):
        assert TTS_BUFFER_DELAY_MIN <= TTS_BUFFER_DELAY_DEFAULT <= TTS_BUFFER_DELAY_MAX


# ---------------------------------------------------------------------------
# 2. Store: create_recipient with tts_buffer_delay persists correctly
# ---------------------------------------------------------------------------

class TestCreateRecipientBufferDelay:
    """Verify tts_buffer_delay is stored on create."""

    @pytest.mark.asyncio
    async def test_create_with_explicit_buffer_delay(self, store):
        result = await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=2.5,
        )
        assert result["tts_buffer_delay"] == 2.5

    @pytest.mark.asyncio
    async def test_create_with_default_buffer_delay(self, store):
        result = await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        assert result["tts_buffer_delay"] == 0.0

    @pytest.mark.asyncio
    async def test_create_push_has_buffer_delay(self, store):
        """Even push recipients store tts_buffer_delay (unused but present)."""
        result = await store.async_create_recipient(
            "tv1", "TV", [{"service": "notify.tv", "name": "TV"}],
            device_type=DEVICE_TYPE_PUSH,
        )
        assert result["tts_buffer_delay"] == 0.0

    @pytest.mark.asyncio
    async def test_create_with_zero_buffer_delay(self, store):
        result = await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=0.0,
        )
        assert result["tts_buffer_delay"] == 0.0

    @pytest.mark.asyncio
    async def test_create_with_max_buffer_delay(self, store):
        result = await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=10.0,
        )
        assert result["tts_buffer_delay"] == 10.0


# ---------------------------------------------------------------------------
# 3. Store: update_recipient with tts_buffer_delay updates correctly
# ---------------------------------------------------------------------------

class TestUpdateRecipientBufferDelay:
    """Verify tts_buffer_delay can be updated."""

    @pytest.mark.asyncio
    async def test_update_buffer_delay(self, store):
        await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=0.0,
        )
        result = await store.async_update_recipient(
            "speaker1", tts_buffer_delay=3.0,
        )
        assert result["tts_buffer_delay"] == 3.0

    @pytest.mark.asyncio
    async def test_update_buffer_delay_to_zero(self, store):
        await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=5.0,
        )
        result = await store.async_update_recipient(
            "speaker1", tts_buffer_delay=0.0,
        )
        assert result["tts_buffer_delay"] == 0.0

    @pytest.mark.asyncio
    async def test_update_other_fields_preserves_buffer_delay(self, store):
        await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_buffer_delay=4.0,
        )
        result = await store.async_update_recipient(
            "speaker1", name="New Name",
        )
        assert result["tts_buffer_delay"] == 4.0
        assert result["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_tts_buffer_delay_in_allowed_fields(self, store):
        """tts_buffer_delay should be an allowed update field (not ignored)."""
        await store.async_create_recipient(
            "speaker1", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
        )
        result = await store.async_update_recipient(
            "speaker1", tts_buffer_delay=7.5,
        )
        # If tts_buffer_delay were not in allowed_fields, it would be ignored
        assert result["tts_buffer_delay"] == 7.5


# ---------------------------------------------------------------------------
# 4. Store: migrate_recipient_data adds tts_buffer_delay default
# ---------------------------------------------------------------------------

class TestMigrateRecipientBufferDelay:
    """Verify migration adds tts_buffer_delay to existing recipients."""

    def test_new_migration_adds_buffer_delay(self):
        """Recipients without device_type get tts_buffer_delay=0.0."""
        recipients = {
            "speaker1": {
                "name": "Speaker",
                "delivery_format": "tts",
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["speaker1"]["tts_buffer_delay"] == 0.0

    def test_already_migrated_gets_buffer_delay_default(self):
        """Recipients with device_type but missing tts_buffer_delay get default."""
        recipients = {
            "speaker1": {
                "name": "Speaker",
                "device_type": DEVICE_TYPE_TTS,
                "media_player_entity_id": "media_player.kitchen",
                "tts_service": "tts.speak",
                "resume_after_tts": False,
                # No tts_buffer_delay key
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["speaker1"]["tts_buffer_delay"] == 0.0

    def test_already_migrated_preserves_existing_buffer_delay(self):
        """Recipients that already have tts_buffer_delay keep their value."""
        recipients = {
            "speaker1": {
                "name": "Speaker",
                "device_type": DEVICE_TYPE_TTS,
                "media_player_entity_id": "media_player.kitchen",
                "tts_service": "tts.speak",
                "resume_after_tts": False,
                "tts_buffer_delay": 3.5,
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["speaker1"]["tts_buffer_delay"] == 3.5

    def test_push_device_gets_buffer_delay_on_migration(self):
        """Push recipients without device_type also get tts_buffer_delay."""
        recipients = {
            "tv1": {
                "name": "TV",
                "delivery_format": "rich",
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["tv1"]["tts_buffer_delay"] == 0.0

    def test_push_already_migrated_gets_buffer_delay(self):
        """Push recipients already migrated but missing buffer_delay get default."""
        recipients = {
            "tv1": {
                "name": "TV",
                "device_type": DEVICE_TYPE_PUSH,
            }
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["tv1"]["tts_buffer_delay"] == 0.0

    def test_multiple_recipients_all_get_buffer_delay(self):
        """All recipients get tts_buffer_delay after migration."""
        recipients = {
            "tv1": {"name": "TV", "delivery_format": "rich"},
            "speaker1": {"name": "Speaker", "delivery_format": "tts"},
            "already_done": {
                "name": "Done", "device_type": "push",
                "tts_buffer_delay": 1.0,
            },
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert recipients["tv1"]["tts_buffer_delay"] == 0.0
        assert recipients["speaker1"]["tts_buffer_delay"] == 0.0
        assert recipients["already_done"]["tts_buffer_delay"] == 1.0


# ---------------------------------------------------------------------------
# 5. Recipient without tts_buffer_delay key -> .get() returns 0.0
# ---------------------------------------------------------------------------

class TestRecipientGetBufferDelayDefault:
    """Verify .get('tts_buffer_delay', default) behavior at runtime."""

    def test_missing_key_returns_default(self):
        """A recipient dict without tts_buffer_delay returns TTS_BUFFER_DELAY_DEFAULT."""
        recipient = {"recipient_id": "speaker1", "name": "Speaker"}
        assert recipient.get("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT) == 0.0

    def test_explicit_zero_returns_zero(self):
        recipient = {"tts_buffer_delay": 0.0}
        assert recipient.get("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT) == 0.0

    def test_explicit_value_returns_value(self):
        recipient = {"tts_buffer_delay": 5.0}
        assert recipient.get("tts_buffer_delay", TTS_BUFFER_DELAY_DEFAULT) == 5.0


# ---------------------------------------------------------------------------
# 6. DELIVERY_FORMAT_PATTERNS regression check
# ---------------------------------------------------------------------------

class TestDeliveryFormatPatternsRegression:
    """Ensure DELIVERY_FORMAT_PATTERNS are still correct after F-20 changes."""

    def test_no_tts_format_in_patterns(self):
        """TTS is a device type, not a delivery format in patterns."""
        for _match_type, _pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert fmt != DELIVERY_FORMAT_TTS

    def test_persistent_notification_present(self):
        found = any(
            pattern == "notify.persistent_notification"
            and fmt == DELIVERY_FORMAT_PERSISTENT
            for _, pattern, fmt in DELIVERY_FORMAT_PATTERNS
        )
        assert found

    def test_patterns_are_valid_tuples(self):
        valid_match_types = {"startswith", "contains", "equals"}
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert match_type in valid_match_types
            assert isinstance(pattern, str)
            assert fmt in DELIVERY_FORMATS


# ---------------------------------------------------------------------------
# 7. async_send_tts buffer delay runtime behavior
# ---------------------------------------------------------------------------

class TestAsyncSendTtsBufferDelay:
    """Verify buffer delay is applied in async_send_tts."""

    @pytest.mark.asyncio
    async def test_no_sleep_when_buffer_delay_zero(self):
        """When tts_buffer_delay is 0.0, asyncio.sleep should not be called."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_mock_store()
        recipient = _make_recipient(buffer_delay=0.0)

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )
            mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_sleep_when_buffer_delay_missing(self):
        """When tts_buffer_delay key is absent, no sleep (default is 0.0)."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_mock_store()
        recipient = _make_recipient()  # No buffer_delay

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )
            mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sleep_called_with_positive_delay(self):
        """When tts_buffer_delay > 0, asyncio.sleep is called with that value."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_mock_store()
        recipient = _make_recipient(buffer_delay=2.5)

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )
            mock_sleep.assert_awaited_once_with(2.5)

    @pytest.mark.asyncio
    async def test_sleep_called_before_tts_delivery(self):
        """Buffer delay sleep happens before the TTS service call."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_mock_store()
        recipient = _make_recipient(buffer_delay=1.0)

        call_order = []

        async def track_sleep(seconds):
            call_order.append(("sleep", seconds))

        async def track_service_call(*args, **kwargs):
            call_order.append(("service_call",))

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", side_effect=track_sleep):
            hass.services.async_call = AsyncMock(side_effect=track_service_call)
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        assert len(call_order) >= 2
        assert call_order[0] == ("sleep", 1.0)
        assert call_order[1] == ("service_call",)

    @pytest.mark.asyncio
    async def test_delivery_succeeds_with_buffer_delay(self):
        """Full happy path: buffer delay + successful TTS delivery."""
        hass = _make_hass(entity_id="media_player.kitchen", features=0)
        store = _make_mock_store()
        recipient = _make_recipient(buffer_delay=3.0)

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", new_callable=AsyncMock):
            result = await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        assert len(result["delivered"]) == 1
        assert result["dropped"] == []
        assert result["queued"] == []

    @pytest.mark.asyncio
    async def test_buffer_delay_with_announce_mode(self):
        """Buffer delay applies even when using announce delivery mode."""
        from custom_components.ticker.const import MEDIA_ANNOUNCE_FEATURE

        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=MEDIA_ANNOUNCE_FEATURE,
        )
        store = _make_mock_store()
        recipient = _make_recipient(buffer_delay=1.5)

        with patch("custom_components.ticker.recipient_tts.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )
            mock_sleep.assert_awaited_once_with(1.5)
            assert "[announce]" in result["delivered"][0]
