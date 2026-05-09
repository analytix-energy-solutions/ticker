"""Tests for ConditionListenerManager.

Currently scoped to BUG-106: post-startup queue sweep that re-evaluates
all conditional subscriptions once after HA finishes starting. Catches
the race where ``ticker.notify`` dispatches before zone entity attributes
or other condition-relevant state finish settling at startup, leaving
entries queued under ``queue_until_met=true`` even though conditions
resolve as met moments later.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.condition_listeners import ConditionListenerManager


# ---------------------------------------------------------------------------
# BUG-106: async_sweep_for_startup
# ---------------------------------------------------------------------------
#
# The manager records `_was_starting_at_register = not hass.is_running` at
# construction time. After HA fires its "started" event, ticker awaits
# `async_sweep_for_startup`, which:
#   - early-returns if `_startup_swept` is already True (one-shot guard)
#   - early-returns (after flipping the flag) if HA was already running
#     when the manager was constructed (config-entry reload path)
#   - otherwise re-evaluates every conditional subscription with no filter,
#     releasing any queued entries whose conditions are now met
# ---------------------------------------------------------------------------


def _make_hass(
    is_running: bool,
    states: dict[str, MagicMock] | None = None,
) -> MagicMock:
    """Build a mock hass.

    Args:
        is_running: Value for ``hass.is_running``. False simulates cold
            boot (manager constructed during HA startup); True simulates a
            config-entry reload after HA is already up.
        states: Optional mapping of entity_id -> mock state. Anything not
            in the map returns None from ``hass.states.get``.
    """
    hass = MagicMock()
    hass.is_running = is_running

    states = states or {}

    def _get(entity_id: str):
        return states.get(entity_id)

    hass.states.get = _get
    return hass


def _zone_state(
    zone_id: str, friendly_name: str, persons: list[str] | None = None,
) -> MagicMock:
    """Build a mock zone entity state.

    persons attribute is included for forward-compatibility with BUG-102's
    persons-membership matching, even though the current branch's zone
    rule evaluator compares friendly_name against person.state.
    """
    s = MagicMock()
    s.entity_id = zone_id
    s.state = "0"
    s.attributes = {
        "friendly_name": friendly_name,
        "persons": list(persons or []),
    }
    return s


def _person_state(person_id: str, state: str) -> MagicMock:
    s = MagicMock()
    s.entity_id = person_id
    s.state = state
    return s


def _make_store(
    subscriptions: dict | None = None,
    queue: list[dict] | None = None,
    user_enabled: bool = True,
) -> MagicMock:
    store = MagicMock()
    store.get_all_subscriptions.return_value = subscriptions or {}
    store.get_queue_for_person.return_value = queue or []
    store.is_user_enabled.return_value = user_enabled
    return store


def _conditional_sub(
    person_id: str,
    category_id: str,
    rules: list[dict],
    queue_until_met: bool = True,
    mode: str = "conditional",
) -> dict:
    return {
        "person_id": person_id,
        "category_id": category_id,
        "mode": mode,
        "conditions": {
            "rules": rules,
            "queue_until_met": queue_until_met,
        },
    }


def _zone_rule(zone_id: str) -> dict:
    return {"type": "zone", "zone_id": zone_id}


def _state_rule(entity_id: str, state: str) -> dict:
    return {"type": "state", "entity_id": entity_id, "state": state}


def _queued_entry(queue_id: str, category_id: str) -> dict:
    return {
        "queue_id": queue_id,
        "category_id": category_id,
        "title": "T",
        "message": "M",
    }


# ---------------------------------------------------------------------------
# Construction-time state capture
# ---------------------------------------------------------------------------


class TestSweepFlagCapture:
    """The manager captures hass.is_running at __init__, not at sweep time."""

    def test_was_starting_true_when_hass_not_running(self):
        hass = _make_hass(is_running=False)
        store = _make_store()
        mgr = ConditionListenerManager(hass, store)
        assert mgr._was_starting_at_register is True
        assert mgr._startup_swept is False

    def test_was_starting_false_when_hass_already_running(self):
        hass = _make_hass(is_running=True)
        store = _make_store()
        mgr = ConditionListenerManager(hass, store)
        assert mgr._was_starting_at_register is False
        assert mgr._startup_swept is False

    def test_late_change_to_is_running_does_not_affect_flag(self):
        """The flag is captured at construction; later flips are ignored."""
        hass = _make_hass(is_running=False)
        store = _make_store()
        mgr = ConditionListenerManager(hass, store)
        # HA "starts" after the manager registers
        hass.is_running = True
        # Manager still remembers it was starting at register time
        assert mgr._was_starting_at_register is True


# ---------------------------------------------------------------------------
# Sweep behavior
# ---------------------------------------------------------------------------


class TestSweepReleasesStuckNotifications:
    """Cold-boot sweep releases entries whose conditions are now met."""

    @pytest.mark.asyncio
    async def test_sweep_releases_zone_only_subscription_when_conditions_met(
        self,
    ):
        """Cold boot, single zone-rule, person home, queued entry -> release."""
        zone = _zone_state(
            "zone.home", "home", persons=["person.x"],
        )
        person = _person_state("person.x", "home")
        hass = _make_hass(
            is_running=False,
            states={"zone.home": zone, "person.x": person},
        )

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1", [_zone_rule("zone.home")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        # Patch the evaluator so the test does not hinge on whichever
        # zone-matching strategy the current branch uses (friendly_name
        # vs zone.persons membership). The point of this test is that
        # *when* conditions are met, the sweep releases.
        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "in zone home")]),
        ):
            await mgr.async_sweep_for_startup()

        callback.assert_awaited_once_with("person.x", "cat1")
        assert mgr._startup_swept is True

    @pytest.mark.asyncio
    async def test_sweep_skips_when_conditions_not_met(self):
        """Cold boot, person not in zone -> queue stays put."""
        zone = _zone_state("zone.home", "home", persons=[])
        person = _person_state("person.x", "not_home")
        hass = _make_hass(
            is_running=False,
            states={"zone.home": zone, "person.x": person},
        )

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1", [_zone_rule("zone.home")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(False, [(False, "not in zone home")]),
        ):
            await mgr.async_sweep_for_startup()

        callback.assert_not_awaited()
        # Flag still flips so a second sweep is also a no-op.
        assert mgr._startup_swept is True

    @pytest.mark.asyncio
    async def test_sweep_runs_only_once_per_manager_instance(self):
        """Calling async_sweep_for_startup twice fires callback at most once."""
        zone = _zone_state("zone.home", "home", persons=["person.x"])
        person = _person_state("person.x", "home")
        hass = _make_hass(
            is_running=False,
            states={"zone.home": zone, "person.x": person},
        )

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1", [_zone_rule("zone.home")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "met")]),
        ):
            await mgr.async_sweep_for_startup()
            await mgr.async_sweep_for_startup()

        # Exactly one release despite two sweep invocations.
        callback.assert_awaited_once_with("person.x", "cat1")
        assert mgr._startup_swept is True

    @pytest.mark.asyncio
    async def test_sweep_skipped_when_ha_already_running_at_construction(
        self,
    ):
        """Reload path: HA already up at construction -> sweep is a no-op."""
        zone = _zone_state("zone.home", "home", persons=["person.x"])
        person = _person_state("person.x", "home")
        hass = _make_hass(
            is_running=True,  # config-entry reload after HA started
            states={"zone.home": zone, "person.x": person},
        )

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1", [_zone_rule("zone.home")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "met")]),
        ) as mock_eval:
            await mgr.async_sweep_for_startup()

        # No release: the reload-skip path returned before evaluation.
        callback.assert_not_awaited()
        # Subscriptions should not even have been walked for evaluation.
        mock_eval.assert_not_called()
        # Flag flipped so any subsequent calls are also no-ops.
        assert mgr._startup_swept is True

        # Second call also a no-op (covers the _startup_swept early return
        # branch on the reload path).
        await mgr.async_sweep_for_startup()
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_skips_non_conditional_subscriptions(self):
        """Subs with mode != conditional are ignored even with stray queue."""
        person = _person_state("person.x", "home")
        hass = _make_hass(
            is_running=False, states={"person.x": person},
        )

        # Mode is 'always' — defensive: should never enter the eval path.
        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1",
                    [_state_rule("switch.x", "on")],
                    mode="always",
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "met")]),
        ) as mock_eval:
            await mgr.async_sweep_for_startup()

        callback.assert_not_awaited()
        # Eval must not have been reached for non-conditional subs.
        mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_skips_never_mode_subscriptions(self):
        """Defensive: mode=never with stray queue still does not release."""
        hass = _make_hass(is_running=False)

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1",
                    [_state_rule("switch.x", "on")],
                    mode="never",
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "met")]),
        ) as mock_eval:
            await mgr.async_sweep_for_startup()

        callback.assert_not_awaited()
        mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_covers_recipient_state_only_subscription(self):
        """Recipient sub with state rule fires callback when met."""
        switch = MagicMock()
        switch.state = "on"
        hass = _make_hass(
            is_running=False, states={"switch.x": switch},
        )

        store = _make_store(
            subscriptions={
                "recipient:phone1:cat1": _conditional_sub(
                    "recipient:phone1", "cat1",
                    [_state_rule("switch.x", "on")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "switch on")]),
        ):
            await mgr.async_sweep_for_startup()

        callback.assert_awaited_once_with("recipient:phone1", "cat1")
        # Recipients bypass the user-enabled gate entirely.
        store.is_user_enabled.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_skips_disabled_user(self):
        """BUG-044 gating: disabled users are not released by the sweep."""
        zone = _zone_state("zone.home", "home", persons=["person.x"])
        person = _person_state("person.x", "home")
        hass = _make_hass(
            is_running=False,
            states={"zone.home": zone, "person.x": person},
        )

        store = _make_store(
            subscriptions={
                "person.x:cat1": _conditional_sub(
                    "person.x", "cat1", [_zone_rule("zone.home")],
                ),
            },
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=False,  # disabled
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        with patch(
            "custom_components.ticker.condition_listeners.evaluate_condition_tree",
            return_value=(True, [(True, "met")]),
        ) as mock_eval:
            await mgr.async_sweep_for_startup()

        callback.assert_not_awaited()
        # Disabled-user guard short-circuits before we reach the queue
        # lookup or condition evaluation.
        store.get_queue_for_person.assert_not_called()
        mock_eval.assert_not_called()
