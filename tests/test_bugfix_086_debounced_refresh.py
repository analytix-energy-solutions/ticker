"""Tests for BUG-086: debounced condition listener refresh on sub changes.

When a subscription is created, updated, or deleted, the store fires
its subscription-change listeners. Ticker registers
``ConditionListenerManager.schedule_refresh`` as one of these listeners
so newly added conditional subscriptions get state/time triggers
without an HA restart. ``schedule_refresh`` debounces via
``async_call_later(0.5)`` to coalesce cascaded deletes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.condition_listeners import ConditionListenerManager
from custom_components.ticker.store.subscriptions import SubscriptionMixin


# ---------------------------------------------------------------------------
# schedule_refresh behavior
# ---------------------------------------------------------------------------

class TestBug086ScheduleRefresh:
    """ConditionListenerManager.schedule_refresh debounces refresh calls."""

    def test_schedule_refresh_uses_async_call_later_with_debounce(self):
        """schedule_refresh registers a debounced timer via async_call_later."""
        hass = MagicMock()
        store = MagicMock()
        store.get_all_subscriptions.return_value = {}

        mgr = ConditionListenerManager(hass, store)

        fake_unsub = MagicMock()
        with patch(
            "custom_components.ticker.condition_listeners.async_call_later",
            return_value=fake_unsub,
        ) as mock_later:
            mgr.schedule_refresh()

        mock_later.assert_called_once()
        args = mock_later.call_args[0]
        # args: (hass, delay_seconds, callback)
        assert args[0] is hass
        assert args[1] == 0.5
        # The pending unsub should be stored for cancellation
        assert mgr._pending_refresh_unsub is fake_unsub

    def test_schedule_refresh_cancels_previous_pending(self):
        """Calling schedule_refresh twice cancels the previous timer."""
        hass = MagicMock()
        store = MagicMock()
        store.get_all_subscriptions.return_value = {}

        mgr = ConditionListenerManager(hass, store)

        first_unsub = MagicMock()
        second_unsub = MagicMock()
        with patch(
            "custom_components.ticker.condition_listeners.async_call_later",
            side_effect=[first_unsub, second_unsub],
        ):
            mgr.schedule_refresh()
            mgr.schedule_refresh()

        # The first timer must have been cancelled
        first_unsub.assert_called_once()
        # The current pending should be the second one
        assert mgr._pending_refresh_unsub is second_unsub


# ---------------------------------------------------------------------------
# Store subscription listener wiring
# ---------------------------------------------------------------------------

class TestBug086StoreListenerFires:
    """Store's _notify_subscription_change fires all registered callbacks."""

    def test_subscription_change_fires_listener(self):
        """_notify_subscription_change triggers every registered callback."""
        mixin = SubscriptionMixin()
        mixin._subscription_listeners = []

        cb1 = MagicMock()
        cb2 = MagicMock()
        mixin.register_subscription_listener(cb1)
        mixin.register_subscription_listener(cb2)

        mixin._notify_subscription_change()

        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_unregister_subscription_listener_removes_callback(self):
        """unregister removes a callback so it is no longer invoked."""
        mixin = SubscriptionMixin()
        mixin._subscription_listeners = []

        cb = MagicMock()
        mixin.register_subscription_listener(cb)
        mixin.unregister_subscription_listener(cb)

        mixin._notify_subscription_change()
        cb.assert_not_called()

    def test_listener_exception_does_not_block_others(self):
        """One misbehaving callback must not prevent others from firing."""
        mixin = SubscriptionMixin()
        mixin._subscription_listeners = []

        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        good_cb = MagicMock()
        mixin.register_subscription_listener(bad_cb)
        mixin.register_subscription_listener(good_cb)

        # Should not raise
        mixin._notify_subscription_change()
        good_cb.assert_called_once()
