"""Tests for BUG-084 and BUG-085: tree-only conditional subscriptions.

BUG-084 (user_notify.py) and BUG-085 (recipient_notify.py) both fell
through to unconditional delivery when a subscription had ONLY a
``condition_tree`` and no ``rules`` key, because the old gate checked
``rules[]`` exclusively. The fix uses ``has_any_conditions`` which
supports tree, flat rules, and legacy zones.

These tests verify that a tree-only subscription with
``queue_until_met=True`` and unmet conditions results in a QUEUED
outcome (not an immediate send).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.user_notify import (
    async_handle_conditional_notification,
)
from custom_components.ticker.recipient_notify import (
    async_handle_conditional_recipient,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_hass() -> MagicMock:
    hass = MagicMock()
    # No matching zone/entity states — conditions will be unmet
    hass.states.get = MagicMock(return_value=None)
    return hass


def _make_store(conditions: dict) -> MagicMock:
    store = MagicMock()
    store.get_subscription_conditions = MagicMock(return_value=conditions)
    store.async_add_to_queue = AsyncMock()
    store.async_add_log = AsyncMock()
    store.is_snoozed = MagicMock(return_value=False)
    return store


def _tree_only_conditions(queue_until_met: bool = True) -> dict:
    """Build a conditions dict with ONLY a condition_tree (no rules key)."""
    return {
        "condition_tree": {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "zone",
                    "zone_id": "zone.home",
                },
            ],
        },
        "queue_until_met": queue_until_met,
        "deliver_when_met": False,
    }


# ---------------------------------------------------------------------------
# BUG-084: user_notify.async_handle_conditional_notification
# ---------------------------------------------------------------------------

class TestBug084UserTreeOnly:
    """Tree-only conditions for a user must follow the gated path."""

    @pytest.mark.asyncio
    async def test_tree_only_unmet_queues_not_delivers(self):
        """A tree-only conditional sub + queue_until_met + unmet conditions
        must QUEUE the notification, not fall through to immediate send."""
        hass = _make_hass()
        # person.state not in zone "Home" (dummy state)
        person_state = MagicMock()
        person_state.state = "not_home"

        store = _make_store(_tree_only_conditions())

        with patch(
            "custom_components.ticker.user_notify.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await async_handle_conditional_notification(
                hass=hass,
                store=store,
                person_id="person.alice",
                person_name="Alice",
                person_state=person_state,
                category_id="cat1",
                title="Hello",
                message="Body",
                data={},
                expiration=48,
                notification_id="nid123",
            )

        # Immediate send MUST NOT have been called
        mock_send.assert_not_awaited()
        # Queue SHOULD have been written
        store.async_add_to_queue.assert_awaited_once()
        # Result reflects queued outcome
        assert result["delivered"] == []
        assert len(result["queued"]) == 1
        assert result["dropped"] == []

    @pytest.mark.asyncio
    async def test_tree_only_with_no_queue_flag_skips(self):
        """Tree-only with neither deliver_when_met nor queue_until_met
        results in the skip path (dropped), not unconditional send."""
        hass = _make_hass()
        person_state = MagicMock()
        person_state.state = "not_home"

        conditions = _tree_only_conditions(queue_until_met=False)
        # Neither flag set -> skip path
        store = _make_store(conditions)

        with patch(
            "custom_components.ticker.user_notify.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await async_handle_conditional_notification(
                hass=hass,
                store=store,
                person_id="person.alice",
                person_name="Alice",
                person_state=person_state,
                category_id="cat1",
                title="Hello",
                message="Body",
                data={},
                expiration=48,
            )

        mock_send.assert_not_awaited()
        store.async_add_to_queue.assert_not_awaited()
        assert result["delivered"] == []
        assert result["queued"] == []
        assert len(result["dropped"]) == 1


# ---------------------------------------------------------------------------
# BUG-085: recipient_notify.async_handle_conditional_recipient
# ---------------------------------------------------------------------------

class TestBug085RecipientTreeOnly:
    """Tree-only conditions for a recipient must follow the gated path."""

    @pytest.mark.asyncio
    async def test_recipient_tree_only_unmet_queues(self):
        """Tree-only recipient sub with queue_until_met + unmet conditions
        queues rather than falling through to immediate delivery."""
        hass = _make_hass()

        # Build a tree with a state rule (zones are skipped for recipients)
        conditions = {
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "state",
                        "entity_id": "switch.quiet_mode",
                        "state": "off",
                    },
                ],
            },
            "queue_until_met": True,
            "deliver_when_met": False,
        }
        # Entity exists but is in the wrong state -> unmet
        state_mock = MagicMock()
        state_mock.state = "on"
        hass.states.get = MagicMock(return_value=state_mock)

        store = _make_store(conditions)

        recipient = {
            "recipient_id": "living_room_tv",
            "name": "Living Room TV",
            "device_type": "push",
            "notify_services": [{"service": "notify.living_room_tv"}],
        }

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
        ) as mock_send:
            result = await async_handle_conditional_recipient(
                hass=hass,
                store=store,
                recipient=recipient,
                category_id="cat1",
                title="Hello",
                message="Body",
                data={},
                expiration=48,
                notification_id="nid456",
            )

        mock_send.assert_not_awaited()
        store.async_add_to_queue.assert_awaited_once()
        assert result["delivered"] == []
        assert len(result["queued"]) == 1
        assert result["dropped"] == []

    @pytest.mark.asyncio
    async def test_recipient_empty_conditions_sends_immediately(self):
        """Empty conditions dict falls through to immediate send (the
        path BUG-084/085 NO LONGER blocks when actual conditions exist)."""
        hass = _make_hass()
        store = _make_store({})  # No rules, no tree, no zones

        recipient = {
            "recipient_id": "living_room_tv",
            "name": "Living Room TV",
            "device_type": "push",
            "notify_services": [{"service": "notify.living_room_tv"}],
        }

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["notify.living_room_tv"], "queued": [], "dropped": []},
        ) as mock_send:
            await async_handle_conditional_recipient(
                hass=hass,
                store=store,
                recipient=recipient,
                category_id="cat1",
                title="Hello",
                message="Body",
                data={},
                expiration=48,
            )

        mock_send.assert_awaited_once()
        store.async_add_to_queue.assert_not_awaited()
