"""Tests for BUG-044: Disabled users should not receive notifications via
secondary delivery paths (condition re-evaluation and queue release).

Covers:
- condition_listeners.py: _async_reevaluate_subscriptions skips disabled users
- arrival.py: async_release_queue_for_conditions skips disabled users
- arrival.py: _handle_person_state_change skips disabled users
- Recipients (prefixed "recipient:") bypass the disabled-user guard
- Enabled users continue to work normally through both paths
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.condition_listeners import ConditionListenerManager
from custom_components.ticker.arrival import async_release_queue_for_conditions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass(states: dict[str, str] | None = None) -> MagicMock:
    """Build a mock hass with optional entity states."""
    hass = MagicMock()

    def _get(entity_id: str):
        if states and entity_id in states:
            s = MagicMock()
            s.state = states[entity_id]
            return s
        return None

    hass.states.get = _get
    return hass


def _make_store(
    subscriptions: dict | None = None,
    user_enabled: bool = True,
    queue: list[dict] | None = None,
) -> MagicMock:
    """Build a mock store with configurable user enabled state and queue."""
    store = MagicMock()
    store.get_all_subscriptions.return_value = subscriptions or {}
    store.get_subscriptions_for_person.return_value = {}
    store.is_user_enabled.return_value = user_enabled
    store.get_queue_for_person.return_value = queue or []
    store.async_remove_from_queue = AsyncMock()
    store.async_requeue_entries = AsyncMock(return_value=(0, 0))
    store.get_recipient.return_value = None
    return store


def _conditional_sub(person_id: str, category_id: str, rules: list) -> dict:
    """Build a conditional subscription dict."""
    return {
        "person_id": person_id,
        "category_id": category_id,
        "mode": "conditional",
        "conditions": {
            "rules": rules,
            "queue_until_met": True,
        },
    }


def _state_rule(entity_id: str, state: str) -> dict:
    return {"type": "state", "entity_id": entity_id, "state": state}


def _queued_entry(queue_id: str, category_id: str) -> dict:
    return {
        "queue_id": queue_id,
        "category_id": category_id,
        "title": "Test",
        "message": "Test message",
    }


# ---------------------------------------------------------------------------
# ConditionListenerManager._async_reevaluate_subscriptions
# ---------------------------------------------------------------------------

class TestReEvaluateSkipsDisabledUser:
    """Disabled users are skipped during condition re-evaluation."""

    @pytest.mark.asyncio
    async def test_disabled_user_skipped(self):
        """A disabled user's conditional subscription is not evaluated."""
        hass = _make_hass({"switch.light": "on"})
        store = _make_store(
            subscriptions={
                "person.alice:cat1": _conditional_sub(
                    "person.alice", "cat1",
                    [_state_rule("switch.light", "on")],
                ),
            },
            user_enabled=False,
            queue=[_queued_entry("q1", "cat1")],
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        await mgr._async_reevaluate_subscriptions(
            filter_type="state", filter_value="switch.light",
        )

        # Callback should NOT have been called because user is disabled
        callback.assert_not_awaited()
        # Queue should not have been checked
        store.get_queue_for_person.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_user_evaluated(self):
        """An enabled user's conditional subscription IS evaluated."""
        hass = _make_hass({
            "switch.light": "on",
            "person.alice": "home",
        })

        # Need person state for non-recipient evaluation
        alice_state = MagicMock()
        alice_state.state = "home"
        original_get = hass.states.get

        def _get_with_person(entity_id):
            if entity_id == "person.alice":
                return alice_state
            return original_get(entity_id)

        hass.states.get = _get_with_person

        store = _make_store(
            subscriptions={
                "person.alice:cat1": _conditional_sub(
                    "person.alice", "cat1",
                    [_state_rule("switch.light", "on")],
                ),
            },
            user_enabled=True,
            queue=[_queued_entry("q1", "cat1")],
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "state met")]),
        ):
            await mgr._async_reevaluate_subscriptions(
                filter_type="state", filter_value="switch.light",
            )

        # Callback SHOULD have been called because user is enabled
        callback.assert_awaited_once_with("person.alice", "cat1")

    @pytest.mark.asyncio
    async def test_recipient_bypasses_disabled_guard(self):
        """Recipient subscriptions are not affected by is_user_enabled."""
        hass = _make_hass({"switch.light": "on"})

        store = _make_store(
            subscriptions={
                "recipient:webhook123:cat1": _conditional_sub(
                    "recipient:webhook123", "cat1",
                    [_state_rule("switch.light", "on")],
                ),
            },
            user_enabled=False,  # would block a normal user
            queue=[_queued_entry("q1", "cat1")],
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "state met")]),
        ):
            await mgr._async_reevaluate_subscriptions(
                filter_type="state", filter_value="switch.light",
            )

        # Callback SHOULD fire -- recipients bypass the disabled check
        callback.assert_awaited_once_with("recipient:webhook123", "cat1")

    @pytest.mark.asyncio
    async def test_mixed_enabled_disabled_users(self):
        """Only enabled users get their conditions evaluated in a batch."""
        hass = _make_hass({"switch.light": "on"})

        alice_state = MagicMock()
        alice_state.state = "home"
        original_get = hass.states.get

        def _get_with_person(entity_id):
            if entity_id == "person.alice":
                return alice_state
            return original_get(entity_id)

        hass.states.get = _get_with_person

        subs = {
            "person.alice:cat1": _conditional_sub(
                "person.alice", "cat1",
                [_state_rule("switch.light", "on")],
            ),
            "person.bob:cat1": _conditional_sub(
                "person.bob", "cat1",
                [_state_rule("switch.light", "on")],
            ),
        }

        store = _make_store(
            subscriptions=subs,
            queue=[_queued_entry("q1", "cat1")],
        )
        # Alice enabled, Bob disabled
        store.is_user_enabled.side_effect = lambda pid: pid == "person.alice"

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "state met")]),
        ):
            await mgr._async_reevaluate_subscriptions(
                filter_type="state", filter_value="switch.light",
            )

        # Only Alice's callback should fire
        callback.assert_awaited_once_with("person.alice", "cat1")


# ---------------------------------------------------------------------------
# async_release_queue_for_conditions
# ---------------------------------------------------------------------------

class TestReleaseQueueSkipsDisabledUser:
    """Disabled users' queued notifications are not released."""

    @pytest.mark.asyncio
    async def test_disabled_user_queue_not_released(self):
        """Queue release is skipped for a disabled user."""
        hass = _make_hass()
        store = _make_store(
            user_enabled=False,
            queue=[_queued_entry("q1", "cat1")],
        )

        await async_release_queue_for_conditions(
            hass, store, "person.alice", "cat1",
        )

        # Queue should never be fetched because we return early
        store.get_queue_for_person.assert_not_called()
        store.async_remove_from_queue.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(
        "custom_components.ticker.arrival.async_send_bundled_notification",
        new_callable=AsyncMock,
        return_value=True,
    )
    async def test_enabled_user_queue_released(self, mock_send):
        """Queue release proceeds for an enabled user."""
        hass = _make_hass()
        store = _make_store(
            user_enabled=True,
            queue=[_queued_entry("q1", "cat1")],
        )

        await async_release_queue_for_conditions(
            hass, store, "person.alice", "cat1",
        )

        store.get_queue_for_person.assert_called_once_with("person.alice")
        store.async_remove_from_queue.assert_awaited_once_with("q1")
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recipient_bypasses_disabled_guard(self):
        """Recipient queue release is not blocked by disabled-user check."""
        hass = _make_hass()
        store = _make_store(
            user_enabled=False,  # would block a normal user
            queue=[_queued_entry("q1", "cat1")],
        )
        store.get_recipient.return_value = {
            "id": "webhook123",
            "name": "Slack",
            "type": "webhook",
        }

        with patch(
            "custom_components.ticker.arrival._async_deliver_recipient_queue",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await async_release_queue_for_conditions(
                hass, store, "recipient:webhook123", "cat1",
            )

        # Queue SHOULD be fetched for recipients regardless of user enabled
        store.get_queue_for_person.assert_called_once_with("recipient:webhook123")
        # is_user_enabled should NOT have been called with the recipient ID
        store.is_user_enabled.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_user_no_queue_entries_noop(self):
        """Disabled user with no queue entries is a clean no-op."""
        hass = _make_hass()
        store = _make_store(user_enabled=False, queue=[])

        await async_release_queue_for_conditions(
            hass, store, "person.alice", "cat1",
        )

        # Early return before queue fetch
        store.get_queue_for_person.assert_not_called()


# ---------------------------------------------------------------------------
# arrival.py: _handle_person_state_change (arrival listener)
# ---------------------------------------------------------------------------

class TestArrivalListenerSkipsDisabledUser:
    """The arrival state-change handler skips disabled users."""

    @pytest.mark.asyncio
    async def test_disabled_user_arrival_skipped(self):
        """Zone change for a disabled user does not trigger queue delivery."""
        hass = MagicMock()
        hass.states.async_all.return_value = [
            MagicMock(entity_id="person.alice"),
        ]

        store = _make_store(
            user_enabled=False,
            queue=[_queued_entry("q1", "cat1")],
        )

        entry_mock = MagicMock()
        entry_mock.runtime_data.store = store

        with patch(
            "custom_components.ticker.arrival.async_track_state_change_event"
        ) as mock_track:
            from custom_components.ticker.arrival import (
                async_setup_arrival_listener,
            )

            await async_setup_arrival_listener(hass, entry_mock)

            # Extract the registered callback
            assert mock_track.called
            state_change_cb = mock_track.call_args[0][2]

            # Simulate person.alice moving from not_home to home
            event = MagicMock()
            event.data = {
                "entity_id": "person.alice",
                "old_state": MagicMock(state="not_home"),
                "new_state": MagicMock(state="home"),
            }

            await state_change_cb(event)

        # Queue should not be fetched because user is disabled
        store.get_queue_for_person.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_user_arrival_processes(self):
        """Zone change for an enabled user does trigger queue check."""
        hass = MagicMock()
        hass.states.async_all.return_value = [
            MagicMock(entity_id="person.alice"),
        ]

        store = _make_store(
            user_enabled=True,
            queue=[],  # empty queue so it returns early after check
        )

        entry_mock = MagicMock()
        entry_mock.runtime_data.store = store

        with patch(
            "custom_components.ticker.arrival.async_track_state_change_event"
        ) as mock_track:
            from custom_components.ticker.arrival import (
                async_setup_arrival_listener,
            )

            await async_setup_arrival_listener(hass, entry_mock)

            state_change_cb = mock_track.call_args[0][2]

            event = MagicMock()
            event.data = {
                "entity_id": "person.alice",
                "old_state": MagicMock(state="not_home"),
                "new_state": MagicMock(state="home"),
            }

            await state_change_cb(event)

        # Queue should be checked because user is enabled
        store.get_queue_for_person.assert_called_once_with("person.alice")


# ---------------------------------------------------------------------------
# is_user_enabled edge cases
# ---------------------------------------------------------------------------

class TestIsUserEnabledEdgeCases:
    """Verify is_user_enabled behavior that the guards depend on."""

    def test_unknown_user_defaults_to_enabled(self):
        """A person_id not in the store defaults to enabled (True)."""
        from custom_components.ticker.store.users import UserMixin

        mixin = UserMixin()
        mixin._users = {}
        assert mixin.is_user_enabled("person.unknown") is True

    def test_user_with_no_enabled_key_defaults_true(self):
        """A user record missing 'enabled' key defaults to True."""
        from custom_components.ticker.store.users import UserMixin

        mixin = UserMixin()
        mixin._users = {"person.alice": {"person_id": "person.alice"}}
        assert mixin.is_user_enabled("person.alice") is True

    def test_explicitly_disabled_user(self):
        """A user with enabled=False returns False."""
        from custom_components.ticker.store.users import UserMixin

        mixin = UserMixin()
        mixin._users = {
            "person.alice": {"person_id": "person.alice", "enabled": False}
        }
        assert mixin.is_user_enabled("person.alice") is False

    def test_explicitly_enabled_user(self):
        """A user with enabled=True returns True."""
        from custom_components.ticker.store.users import UserMixin

        mixin = UserMixin()
        mixin._users = {
            "person.alice": {"person_id": "person.alice", "enabled": True}
        }
        assert mixin.is_user_enabled("person.alice") is True
