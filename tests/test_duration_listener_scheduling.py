"""Tests for duration rule wakeup scheduling in ConditionListenerManager.

A "for_at_least" duration leaf becomes true at a fixed future timestamp
with no state-change event to trigger re-evaluation, so the manager must
schedule a one-shot timer for the earliest such threshold and reschedule
on every listener refresh. Covers:

- async_refresh_listeners schedules a wakeup when a pending for_at_least
  leaf is below its threshold
- no wakeup is scheduled once the threshold has already passed
- blank entity_id resolves to the subscription's person_id for scheduling
- a stale wakeup timer is cancelled when no duration leaves remain pending
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.condition_listeners import ConditionListenerManager


def _make_hass(states: dict[str, MagicMock] | None = None) -> MagicMock:
    hass = MagicMock()
    hass.is_running = True
    states = states or {}
    hass.states.get = lambda eid: states.get(eid)
    return hass


def _make_store(subscriptions: dict) -> MagicMock:
    store = MagicMock()
    store.get_all_subscriptions.return_value = subscriptions
    store.get_queue_for_person.return_value = []
    store.is_user_enabled.return_value = True
    return store


def _duration_sub(
    person_id: str,
    category_id: str,
    entity_id: str,
    minutes: int,
    comparison: str = "for_at_least",
) -> dict:
    return {
        "person_id": person_id,
        "category_id": category_id,
        "mode": "conditional",
        "conditions": {
            "queue_until_met": True,
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [{
                    "type": "duration",
                    "entity_id": entity_id,
                    "state": "home",
                    "comparison": comparison,
                    "minutes": minutes,
                }],
            },
        },
    }


def _person_state(entity_id: str, state: str, minutes_ago: float, now: datetime) -> MagicMock:
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.last_changed = now - timedelta(minutes=minutes_ago)
    return s


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_schedules_wakeup_for_pending_for_at_least_leaf():
    """Person home 5m, threshold 15m -> wakeup scheduled ~10m out."""
    person = _person_state("person.x", "home", minutes_ago=5, now=_NOW)
    hass = _make_hass({"person.x": person})
    store = _make_store({
        "person.x:cat1": _duration_sub("person.x", "cat1", "person.x", minutes=15),
    })
    mgr = ConditionListenerManager(hass, store)

    with patch(
        "custom_components.ticker.condition_listeners.dt_util.utcnow",
        return_value=_NOW,
    ), patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ) as mock_call_later:
        await mgr.async_refresh_listeners()

    assert mock_call_later.called
    _hass_arg, delay, _cb = mock_call_later.call_args[0]
    assert 590 <= delay <= 600  # ~10 minutes remaining


@pytest.mark.asyncio
async def test_no_wakeup_when_threshold_already_passed():
    """Person home 30m, threshold 15m -> already met, no future wakeup needed."""
    person = _person_state("person.x", "home", minutes_ago=30, now=_NOW)
    hass = _make_hass({"person.x": person})
    store = _make_store({
        "person.x:cat1": _duration_sub("person.x", "cat1", "person.x", minutes=15),
    })
    mgr = ConditionListenerManager(hass, store)

    with patch(
        "custom_components.ticker.condition_listeners.dt_util.utcnow",
        return_value=_NOW,
    ), patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ) as mock_call_later:
        await mgr.async_refresh_listeners()

    assert not mock_call_later.called


@pytest.mark.asyncio
async def test_blank_entity_id_resolves_to_person_id_for_scheduling():
    """Duration leaf with no entity_id defaults to the subscription's person."""
    person = _person_state("person.x", "home", minutes_ago=1, now=_NOW)
    hass = _make_hass({"person.x": person})
    store = _make_store({
        "person.x:cat1": _duration_sub("person.x", "cat1", "", minutes=10),
    })
    mgr = ConditionListenerManager(hass, store)

    with patch(
        "custom_components.ticker.condition_listeners.dt_util.utcnow",
        return_value=_NOW,
    ), patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ) as mock_call_later:
        await mgr.async_refresh_listeners()

    assert mock_call_later.called


@pytest.mark.asyncio
async def test_blank_entity_id_duration_leaf_registers_person_entity_listener():
    """Regression: the documented default (blank entity_id = subscriber's
    person) must get an entity-change listener, for both comparisons --
    otherwise the person transitioning state is never noticed at all."""
    person = _person_state("person.x", "not_home", minutes_ago=1, now=_NOW)
    hass = _make_hass({"person.x": person})
    store = _make_store({
        "person.x:cat1": _duration_sub(
            "person.x", "cat1", entity_id="", minutes=10, comparison="within",
        ),
    })
    mgr = ConditionListenerManager(hass, store)

    with patch(
        "custom_components.ticker.condition_listeners.dt_util.utcnow",
        return_value=_NOW,
    ), patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ):
        await mgr.async_refresh_listeners()

    assert "person.x" in mgr._tracked_entities


@pytest.mark.asyncio
async def test_entity_reevaluation_reschedules_duration_wakeup():
    """Regression: an entity transitioning into a duration leaf's target
    state must (re)compute the for_at_least wakeup immediately, not only
    on the next unrelated subscription-change refresh."""
    person = _person_state("person.x", "home", minutes_ago=0, now=_NOW)
    hass = _make_hass({"person.x": person})
    store = _make_store({
        "person.x:cat1": _duration_sub("person.x", "cat1", "person.x", minutes=15),
    })
    mgr = ConditionListenerManager(hass, store)

    with patch(
        "custom_components.ticker.condition_listeners.dt_util.utcnow",
        return_value=_NOW,
    ), patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ) as mock_call_later:
        await mgr._async_reevaluate_for_entity("person.x")

    assert mock_call_later.called


@pytest.mark.asyncio
async def test_stale_wakeup_cancelled_when_no_duration_leaves_pending():
    """A previously scheduled wakeup is cancelled once nothing needs it."""
    hass = _make_hass({})
    store = _make_store({})
    mgr = ConditionListenerManager(hass, store)

    stale_unsub = MagicMock()
    mgr._duration_wakeup_unsub = stale_unsub

    with patch(
        "custom_components.ticker.condition_listeners.async_call_later",
    ):
        await mgr.async_refresh_listeners()

    stale_unsub.assert_called_once()
    assert mgr._duration_wakeup_unsub is None
