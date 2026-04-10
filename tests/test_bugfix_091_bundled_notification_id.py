"""Tests for BUG-091: bundled notification log entries carry notification_id.

When queued notifications are released and sent as a bundle, each log
entry written must include the original queue entry's
``notification_id`` so action handling can correlate taps back to the
source notification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.bundled_notify import (
    async_send_bundled_notification,
)


def _make_store() -> MagicMock:
    store = MagicMock()
    store.get_device_preference.return_value = {"mode": "all", "devices": []}
    store.get_device_override.return_value = None
    store.get_category.return_value = {"name": "Cat 1"}
    store.async_add_log = AsyncMock()
    return store


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    person_state = MagicMock()
    person_state.attributes = {"friendly_name": "Alice"}
    hass.states.get = MagicMock(return_value=person_state)
    return hass


class TestBug091BundledLogsCarryNid:

    @pytest.mark.asyncio
    async def test_single_entry_log_has_notification_id(self):
        """Single-entry bundle delivers the original notification_id."""
        hass = _make_hass()
        store = _make_store()

        entry = {
            "queue_id": "q1",
            "category_id": "cat1",
            "title": "T",
            "message": "M",
            "data": {},
            "notification_id": "nid_abc123",
        }

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            new_callable=AsyncMock,
            return_value=[{"service": "notify.alice_phone", "name": "Phone"}],
        ):
            ok = await async_send_bundled_notification(
                hass, "person.alice", [entry], store,
            )

        assert ok is True
        store.async_add_log.assert_awaited_once()
        log_kwargs = store.async_add_log.call_args[1]
        assert log_kwargs.get("notification_id") == "nid_abc123"

    @pytest.mark.asyncio
    async def test_multi_entry_each_log_has_own_nid(self):
        """Multi-entry bundle writes a log per entry with that entry's nid."""
        hass = _make_hass()
        store = _make_store()

        entries = [
            {
                "queue_id": "q1",
                "category_id": "cat1",
                "title": "T1",
                "message": "M1",
                "data": {},
                "notification_id": "nid_one",
            },
            {
                "queue_id": "q2",
                "category_id": "cat2",
                "title": "T2",
                "message": "M2",
                "data": {},
                "notification_id": "nid_two",
            },
        ]

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            new_callable=AsyncMock,
            return_value=[{"service": "notify.alice_phone", "name": "Phone"}],
        ):
            ok = await async_send_bundled_notification(
                hass, "person.alice", entries, store,
            )

        assert ok is True
        assert store.async_add_log.await_count == 2
        logged_nids = {
            call.kwargs.get("notification_id")
            for call in store.async_add_log.await_args_list
        }
        assert logged_nids == {"nid_one", "nid_two"}

    @pytest.mark.asyncio
    async def test_entry_without_nid_logs_none(self):
        """An entry with no notification_id logs None, not a crash."""
        hass = _make_hass()
        store = _make_store()

        entry = {
            "queue_id": "q1",
            "category_id": "cat1",
            "title": "T",
            "message": "M",
            "data": {},
            # no notification_id key
        }

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            new_callable=AsyncMock,
            return_value=[{"service": "notify.alice_phone", "name": "Phone"}],
        ):
            ok = await async_send_bundled_notification(
                hass, "person.alice", [entry], store,
            )

        assert ok is True
        log_kwargs = store.async_add_log.call_args[1]
        assert log_kwargs.get("notification_id") is None
