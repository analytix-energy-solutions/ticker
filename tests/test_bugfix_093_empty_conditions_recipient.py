"""Tests for BUG-093: empty conditions dict on recipient CRUD.

ws_create_recipient and ws_update_recipient must treat conditions={}
the same as conditions=None — an empty dict has no rules or
condition_tree, so it normalizes to None for storage. Previously the
handler ran validation on the empty dict and produced an error.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.websocket.recipients import (
    ws_create_recipient,
    ws_update_recipient,
)


def _base_create_msg(**overrides) -> dict:
    msg = {
        "id": 1,
        "type": "ticker/create_recipient",
        "recipient_id": "test_device",
        "name": "Test Device",
        "device_type": "push",
        "notify_services": [{"service": "notify.mobile", "name": "Phone"}],
        "delivery_format": "rich",
        "icon": "mdi:bell-ring",
        "enabled": True,
        "resume_after_tts": False,
        "tts_buffer_delay": 0.5,
    }
    msg.update(overrides)
    return msg


def _base_update_msg(**overrides) -> dict:
    msg = {
        "id": 2,
        "type": "ticker/update_recipient",
        "recipient_id": "test_device",
    }
    msg.update(overrides)
    return msg


def _make_mocks(existing_recipient: dict | None = None):
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.get_recipient.return_value = existing_recipient
    store.async_create_recipient = AsyncMock(
        return_value={"recipient_id": "test_device"}
    )
    store.async_update_recipient = AsyncMock(
        return_value={"recipient_id": "test_device"}
    )
    return hass, conn, store


@contextmanager
def _patches(store):
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
        return_value="Test Device",
    ):
        yield


class TestBug093CreateRecipientEmptyConditions:

    @pytest.mark.asyncio
    async def test_create_empty_conditions_succeeds_as_none(self):
        """conditions={} on create must succeed and normalize to None."""
        hass, conn, store = _make_mocks()

        with _patches(store):
            await ws_create_recipient(
                hass, conn, _base_create_msg(conditions={}),
            )

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        create_kwargs = store.async_create_recipient.call_args[1]
        assert create_kwargs["conditions"] is None


class TestBug093UpdateRecipientEmptyConditions:

    @pytest.mark.asyncio
    async def test_update_empty_conditions_succeeds_as_none(self):
        """conditions={} on update must succeed and normalize to None."""
        existing = {
            "recipient_id": "test_device",
            "device_type": "push",
            "name": "Test Device",
        }
        hass, conn, store = _make_mocks(existing_recipient=existing)

        with _patches(store):
            await ws_update_recipient(
                hass, conn, _base_update_msg(conditions={}),
            )

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        update_kwargs = store.async_update_recipient.call_args[1]
        assert update_kwargs["conditions"] is None

    @pytest.mark.asyncio
    async def test_update_null_conditions_also_succeeds_as_none(self):
        """conditions=None on update (sparse clear) succeeds."""
        existing = {
            "recipient_id": "test_device",
            "device_type": "push",
            "name": "Test Device",
        }
        hass, conn, store = _make_mocks(existing_recipient=existing)

        with _patches(store):
            await ws_update_recipient(
                hass, conn, _base_update_msg(conditions=None),
            )

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        update_kwargs = store.async_update_recipient.call_args[1]
        assert update_kwargs["conditions"] is None
