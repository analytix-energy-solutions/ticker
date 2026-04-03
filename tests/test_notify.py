"""Tests for custom_components.ticker.notify (TickerNotifyEntity).

Verifies entity instantiation, unique_id generation, and service delegation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.notify import TickerNotifyEntity, async_setup_entry
from custom_components.ticker.const import CATEGORY_DEFAULT, DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_entry(entry_id: str = "test_entry_123") -> MagicMock:
    """Create a minimal mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


# ---------------------------------------------------------------------------
# TickerNotifyEntity instantiation
# ---------------------------------------------------------------------------

class TestTickerNotifyEntityInit:
    def test_unique_id(self):
        entry = _make_config_entry("abc123")
        entity = TickerNotifyEntity(entry)
        assert entity._attr_unique_id == "abc123_notify"

    def test_name(self):
        entity = TickerNotifyEntity(_make_config_entry())
        assert entity._attr_name == "Ticker"

    def test_has_entity_name(self):
        entity = TickerNotifyEntity(_make_config_entry())
        assert entity._attr_has_entity_name is True


# ---------------------------------------------------------------------------
# async_send_message
# ---------------------------------------------------------------------------

class TestAsyncSendMessage:
    @pytest.mark.asyncio
    async def test_delegates_to_ticker_notify(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message("Hello world", title="Test")

        entity.hass.services.async_call.assert_awaited_once()
        call_args = entity.hass.services.async_call.call_args
        assert call_args[0][0] == DOMAIN
        assert call_args[0][1] == "notify"
        service_data = call_args[0][2]
        assert service_data["message"] == "Hello world"
        assert service_data["title"] == "Test"
        assert service_data["category"] == CATEGORY_DEFAULT

    @pytest.mark.asyncio
    async def test_uses_category_from_data(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message(
            "Alert", title="Security", data={"category": "security"}
        )

        service_data = entity.hass.services.async_call.call_args[0][2]
        assert service_data["category"] == "security"
        # category should be popped from data, not passed through
        assert "category" not in service_data.get("data", {})

    @pytest.mark.asyncio
    async def test_no_title_defaults_to_notification(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message("Hello")

        service_data = entity.hass.services.async_call.call_args[0][2]
        assert service_data["title"] == "Notification"

    @pytest.mark.asyncio
    async def test_extra_data_passed_through(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message(
            "msg", data={"image": "http://img.png", "priority": "high"}
        )

        service_data = entity.hass.services.async_call.call_args[0][2]
        assert service_data["data"]["image"] == "http://img.png"
        assert service_data["data"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_no_data_key_when_empty(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message("msg")

        service_data = entity.hass.services.async_call.call_args[0][2]
        assert "data" not in service_data

    @pytest.mark.asyncio
    async def test_does_not_mutate_caller_data(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        caller_data = {"category": "alerts", "extra": "val"}
        await entity.async_send_message("msg", data=caller_data)

        # Original dict should still have category
        assert "category" in caller_data

    @pytest.mark.asyncio
    async def test_blocking_true(self):
        entity = TickerNotifyEntity(_make_config_entry())
        entity.hass = MagicMock()
        entity.hass.services.async_call = AsyncMock()

        await entity.async_send_message("msg")

        call_kwargs = entity.hass.services.async_call.call_args[1]
        assert call_kwargs.get("blocking") is True


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------

class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_adds_entity(self):
        hass = MagicMock()
        entry = _make_config_entry()
        add_entities = MagicMock()

        await async_setup_entry(hass, entry, add_entities)

        add_entities.assert_called_once()
        entities = add_entities.call_args[0][0]
        assert len(entities) == 1
        assert isinstance(entities[0], TickerNotifyEntity)
