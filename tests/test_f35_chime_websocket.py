"""Tests for F-35 — WebSocket schema validation for chime_media_content_id.

Covers:
- ws_create_recipient / ws_update_recipient: 500-char length validation,
  push-type silently drops the field
- ws_create_category / ws_update_category: 500-char length validation
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.const import MAX_CHIME_MEDIA_CONTENT_ID_LENGTH
from custom_components.ticker.websocket.recipients import (
    ws_create_recipient,
    ws_update_recipient,
)
from custom_components.ticker.websocket.categories import (
    ws_create_category,
    ws_update_category,
)


# ---------------------------------------------------------------------------
# Recipient WS tests
# ---------------------------------------------------------------------------

def _base_recipient_create(**overrides) -> dict:
    msg = {
        "id": 1,
        "type": "ticker/create_recipient",
        "recipient_id": "kitchen",
        "name": "Kitchen",
        "device_type": "tts",
        "delivery_format": "rich",
        "media_player_entity_id": "media_player.kitchen",
        "icon": "mdi:speaker",
        "enabled": True,
        "resume_after_tts": False,
        "tts_buffer_delay": 0.0,
    }
    msg.update(overrides)
    return msg


def _base_recipient_update(**overrides) -> dict:
    msg = {
        "id": 2,
        "type": "ticker/update_recipient",
        "recipient_id": "kitchen",
    }
    msg.update(overrides)
    return msg


def _make_recipient_mocks(existing: dict | None = None):
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.get_recipient.return_value = existing
    store.async_create_recipient = AsyncMock(
        return_value={"recipient_id": "kitchen"}
    )
    store.async_update_recipient = AsyncMock(
        return_value={"recipient_id": "kitchen"}
    )
    return hass, conn, store


@contextmanager
def _recipient_patches(store):
    with patch(
        "custom_components.ticker.websocket.recipients.get_store",
        return_value=store,
    ), patch(
        "custom_components.ticker.websocket.recipients.validate_recipient_id",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.recipients.validate_icon",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.recipients.sanitize_for_storage",
        return_value="Kitchen",
    ):
        yield


class TestRecipientChimeSchemaValidation:

    @pytest.mark.asyncio
    async def test_create_accepts_valid_chime(self):
        hass, conn, store = _make_recipient_mocks()
        with _recipient_patches(store):
            await ws_create_recipient(
                hass, conn,
                _base_recipient_create(
                    chime_media_content_id="media-source://ok",
                ),
            )
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        kw = store.async_create_recipient.call_args[1]
        assert kw["chime_media_content_id"] == "media-source://ok"

    @pytest.mark.asyncio
    async def test_create_rejects_chime_over_500_chars(self):
        hass, conn, store = _make_recipient_mocks()
        with _recipient_patches(store):
            await ws_create_recipient(
                hass, conn,
                _base_recipient_create(
                    chime_media_content_id="x" * (
                        MAX_CHIME_MEDIA_CONTENT_ID_LENGTH + 1
                    ),
                ),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_chime"
        store.async_create_recipient.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_accepts_chime_at_exactly_max_length(self):
        hass, conn, store = _make_recipient_mocks()
        with _recipient_patches(store):
            await ws_create_recipient(
                hass, conn,
                _base_recipient_create(
                    chime_media_content_id="x" * MAX_CHIME_MEDIA_CONTENT_ID_LENGTH,
                ),
            )
        conn.send_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_accepts_valid_chime(self):
        existing = {
            "recipient_id": "kitchen",
            "device_type": "tts",
            "name": "Kitchen",
        }
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                _base_recipient_update(
                    chime_media_content_id="media-source://x",
                ),
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_recipient.call_args[1]
        assert kw["chime_media_content_id"] == "media-source://x"

    @pytest.mark.asyncio
    async def test_update_rejects_chime_over_500_chars(self):
        existing = {
            "recipient_id": "kitchen",
            "device_type": "tts",
            "name": "Kitchen",
        }
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                _base_recipient_update(
                    chime_media_content_id="x" * 501,
                ),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_chime"

    @pytest.mark.asyncio
    async def test_update_push_recipient_drops_chime(self):
        """Push-type recipients silently drop chime field."""
        existing = {
            "recipient_id": "phone",
            "device_type": "push",
            "name": "Phone",
        }
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                {
                    "id": 3,
                    "type": "ticker/update_recipient",
                    "recipient_id": "phone",
                    "chime_media_content_id": "media-source://x",
                    "name": "Phone Updated",
                },
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_recipient.call_args[1]
        # chime should NOT be in kwargs sent to store
        assert "chime_media_content_id" not in kw

    @pytest.mark.asyncio
    async def test_update_clears_chime_with_empty_string(self):
        existing = {
            "recipient_id": "kitchen",
            "device_type": "tts",
            "name": "Kitchen",
        }
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                _base_recipient_update(chime_media_content_id=""),
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_recipient.call_args[1]
        assert kw["chime_media_content_id"] == ""


# ---------------------------------------------------------------------------
# Category WS tests
# ---------------------------------------------------------------------------

def _base_category_create(**overrides) -> dict:
    msg = {
        "id": 1,
        "type": "ticker/category/create",
        "category_id": "security",
        "name": "Security",
    }
    msg.update(overrides)
    return msg


def _base_category_update(**overrides) -> dict:
    msg = {
        "id": 2,
        "type": "ticker/category/update",
        "category_id": "security",
    }
    msg.update(overrides)
    return msg


def _make_category_mocks(exists: bool = True):
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.category_exists.return_value = exists
    store.async_create_category = AsyncMock(
        return_value={"id": "security"}
    )
    store.async_update_category = AsyncMock(
        return_value={"id": "security"}
    )
    # config entries for service-schema refresh path
    hass.config_entries.async_entries.return_value = []
    return hass, conn, store


@contextmanager
def _category_patches(store):
    with patch(
        "custom_components.ticker.websocket.categories.get_store",
        return_value=store,
    ), patch(
        "custom_components.ticker.websocket.categories.validate_category_id",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_icon",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_color",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_navigate_to",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.sanitize_for_storage",
        side_effect=lambda v, _: v,
    ):
        yield


class TestCategoryChimeSchemaValidation:

    @pytest.mark.asyncio
    async def test_create_accepts_valid_chime(self):
        hass, conn, store = _make_category_mocks(exists=False)
        with _category_patches(store):
            await ws_create_category(
                hass, conn,
                _base_category_create(
                    chime_media_content_id="media-source://x",
                ),
            )
        conn.send_result.assert_called_once()
        kw = store.async_create_category.call_args[1]
        assert kw["chime_media_content_id"] == "media-source://x"

    @pytest.mark.asyncio
    async def test_create_rejects_chime_over_500_chars(self):
        hass, conn, store = _make_category_mocks(exists=False)
        with _category_patches(store):
            await ws_create_category(
                hass, conn,
                _base_category_create(
                    chime_media_content_id="x" * 501,
                ),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_chime"
        store.async_create_category.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_accepts_valid_chime(self):
        hass, conn, store = _make_category_mocks(exists=True)
        with _category_patches(store):
            await ws_update_category(
                hass, conn,
                _base_category_update(
                    chime_media_content_id="media-source://x",
                ),
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_category.call_args[1]
        assert kw["chime_media_content_id"] == "media-source://x"

    @pytest.mark.asyncio
    async def test_update_clears_chime_with_empty_string(self):
        hass, conn, store = _make_category_mocks(exists=True)
        with _category_patches(store):
            await ws_update_category(
                hass, conn,
                _base_category_update(chime_media_content_id=""),
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_category.call_args[1]
        # empty string forwarded to clear in store
        assert kw["chime_media_content_id"] == ""

    @pytest.mark.asyncio
    async def test_update_rejects_chime_over_500_chars(self):
        hass, conn, store = _make_category_mocks(exists=True)
        with _category_patches(store):
            await ws_update_category(
                hass, conn,
                _base_category_update(
                    chime_media_content_id="x" * 501,
                ),
            )
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_chime"

    @pytest.mark.asyncio
    async def test_update_without_chime_key_does_not_pass_to_store(self):
        """Partial update without chime key shouldn't clobber."""
        hass, conn, store = _make_category_mocks(exists=True)
        with _category_patches(store):
            await ws_update_category(
                hass, conn,
                _base_category_update(name="Renamed"),
            )
        conn.send_result.assert_called_once()
        kw = store.async_update_category.call_args[1]
        assert "chime_media_content_id" not in kw
