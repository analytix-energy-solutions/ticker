"""Regression tests for BUG-102 — zone matching by persons membership.

BUG-102: Conditional subscriptions gated on a zone rule failed to deliver
when the zone's friendly_name differed in case (or text) from the person's
state. Home Assistant lowercases zone-derived person states ("home"), so
comparing person.state against zone.friendly_name ("Home") silently failed.

Fix: ``evaluate_zone_rule`` and the legacy-zones path in ``arrival.py`` now
use the zone entity's ``persons`` attribute (a list of person entity IDs
currently inside the zone) for membership matching. ``resolve_zone_name`` is
retained as a display-only helper for log/reason strings.

This file pins that contract directly so any future regression is caught
immediately.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.conditions import (
    evaluate_condition_tree,
    evaluate_rule,
    evaluate_zone_rule,
)
from custom_components.ticker.const import (
    MODE_CONDITIONAL,
    RULE_TYPE_ZONE,
)


# ---------------------------------------------------------------------------
# evaluate_zone_rule — direct contract tests
# ---------------------------------------------------------------------------


class TestEvaluateZoneRulePersonsMembership:
    """``evaluate_zone_rule`` matches via the zone's ``persons`` attribute."""

    def test_zone_home_matches_via_persons_attribute(self, mock_hass, fake_state):
        """Person listed in zone.persons -> rule met with 'In <friendly>'."""
        mock_hass.register_zone("zone.home", "Home", ["person.alice"])
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is True
        assert reason == "In Home"

    def test_zone_home_does_not_match_when_person_absent(
        self, mock_hass, fake_state,
    ):
        """Person not in persons list -> rule unmet with 'Not in <friendly>'."""
        mock_hass.register_zone("zone.home", "Home", ["person.bob"])
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is False
        assert reason == "Not in Home"

    def test_renamed_zone_still_matches(self, mock_hass, fake_state):
        """KEY resilience test — renaming friendly_name does not break match.

        This is the whole point of BUG-102: matching is independent of the
        zone's display name.
        """
        mock_hass.register_zone("zone.home", "Thuis", ["person.alice"])
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is True
        assert reason == "In Thuis"

    def test_nested_zones_both_match(self, mock_hass, fake_state):
        """Two independently registered zones both evaluate True."""
        mock_hass.register_zone("zone.home", "Home", ["person.alice"])
        mock_hass.register_zone(
            "zone.living_room", "Living Room", ["person.alice"],
        )
        person = fake_state("person.alice", "home")

        home_met, home_reason = evaluate_zone_rule(
            mock_hass,
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            person,
        )
        living_met, living_reason = evaluate_zone_rule(
            mock_hass,
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.living_room"},
            person,
        )

        assert home_met is True
        assert home_reason == "In Home"
        assert living_met is True
        assert living_reason == "In Living Room"

    def test_zone_not_found_returns_false(self, mock_hass, fake_state):
        """Missing zone entity -> False with 'Zone <zone_id> not found'."""
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.gone"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is False
        assert reason == "Zone zone.gone not found"

    def test_zone_with_empty_persons_attribute(self, mock_hass, fake_state):
        """persons=[] -> nobody in zone -> False with 'Not in <friendly>'."""
        mock_hass.register_zone("zone.home", "Home", [])
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is False
        assert reason == "Not in Home"

    def test_zone_with_missing_persons_attribute(self, mock_hass, fake_state):
        """Zone with no 'persons' key at all -> defensive .get('persons', [])."""
        # Bypass register_zone helper to simulate a zone whose attributes
        # dict has no 'persons' key (e.g. corrupt or unusual HA state).
        zone_state = MagicMock()
        zone_state.entity_id = "zone.home"
        zone_state.attributes = {"friendly_name": "Home"}
        mock_hass._zone_store["zone.home"] = zone_state

        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_zone_rule(mock_hass, rule, person)

        assert is_met is False
        assert reason == "Not in Home"

    def test_recipient_skips_zone_rule_unchanged(self, mock_hass):
        """evaluate_rule with person_state=None on a zone rule -> skipped/met."""
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}

        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None)

        assert is_met is True
        assert reason == "Zone rule skipped (no person state)"


# ---------------------------------------------------------------------------
# E2E mirror of Hans's exact production scenario
# ---------------------------------------------------------------------------


class TestBug102ProductionScenario:
    """End-to-end mirror of the exact production failure from BUG-102."""

    def test_bug_102_zone_home_delivers_when_person_is_home(
        self, mock_hass, fake_state,
    ):
        """Hans's prod bug — conditional sub gated on zone.home delivers.

        Subscription:
          mode=conditional
          condition_tree: {group AND, children=[{type:zone, zone_id:zone.home}]}
          deliver_when_met=True
          queue_until_met=True

        State:
          zone.home friendly_name="Home" persons=["person.hans_dekker"]
          person.hans_dekker.state="home"  (lowercase, as real HA emits)

        Expected: condition tree evaluates met=True so the notification is
        delivered immediately rather than queued.
        """
        mock_hass.register_zone(
            "zone.home", "Home", ["person.hans_dekker"],
        )
        person = fake_state("person.hans_dekker", "home")

        conditions: dict[str, Any] = {
            "deliver_when_met": True,
            "queue_until_met": True,
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [
                    {"type": "zone", "zone_id": "zone.home"},
                ],
            },
        }

        all_met, results = evaluate_condition_tree(
            mock_hass, conditions, person,
        )

        assert all_met is True, (
            f"BUG-102 regression: zone.home should match for person.hans_dekker "
            f"via persons membership. Got results={results}"
        )
        assert len(results) == 1
        assert results[0][0] is True
        assert results[0][1] == "In Home"


# ---------------------------------------------------------------------------
# Arrival listener regression tests (Option B — same file)
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine to completion in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_arrival_event(
    fake_state_factory,
    entity_id: str,
    old_state_value: str,
    new_state_value: str,
):
    """Build a state-change event with old/new State objects."""
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "old_state": fake_state_factory(entity_id, old_state_value),
        "new_state": fake_state_factory(entity_id, new_state_value),
    }
    return event


def _setup_arrival_with_store(mock_hass, store) -> Any:
    """Run async_setup_arrival_listener and return the captured callback.

    Captures the ``_handle_person_state_change`` closure registered via
    the mocked ``async_track_state_change_event`` so tests can drive
    arrival logic directly. Note: ``arrival.py`` imports the tracker at
    module load (``from ... import async_track_state_change_event``) so
    we must patch the symbol on the ``arrival`` module itself, not on
    the helpers module.
    """
    from custom_components.ticker import arrival as arrival_mod

    tracker = MagicMock(return_value=lambda: None)

    # Provide a person entity so _update_state_listener registers a handler
    person_entity = MagicMock()
    person_entity.entity_id = "person.alice"
    mock_hass.states.async_all = MagicMock(return_value=[person_entity])
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_listen = MagicMock(return_value=lambda: None)

    entry = MagicMock()
    entry.runtime_data.store = store

    with patch.object(
        arrival_mod, "async_track_state_change_event", tracker,
    ):
        _run(arrival_mod.async_setup_arrival_listener(mock_hass, entry))

    assert tracker.called, (
        "expected arrival listener to register a state change handler"
    )
    args, _kwargs = tracker.call_args
    # Signature: (hass, entity_ids, callback)
    return args[2]


class TestArrivalReleasesQueue:
    """BUG-102 fix in arrival.py legacy-zones path uses persons membership."""

    def test_arrival_releases_queue_when_persons_changes(
        self, mock_hass, fake_state,
    ):
        """Person added to zone.persons -> queued entry is delivered."""
        # Queue starts gated; we'll flip the zone before invoking the callback
        mock_hass.register_zone("zone.home", "Home", [])

        store = MagicMock()
        store.is_user_enabled.return_value = True
        store.get_queue_for_person.return_value = [
            {
                "queue_id": "q1",
                "category_id": "cat1",
                "title": "t",
                "message": "m",
            },
        ]
        # Conditional subscription with a single zone rule
        store.get_subscriptions_for_person.return_value = {
            "cat1": {
                "mode": MODE_CONDITIONAL,
                "conditions": {
                    "deliver_when_met": True,
                    "queue_until_met": True,
                    "condition_tree": {
                        "type": "group",
                        "operator": "AND",
                        "children": [
                            {"type": "zone", "zone_id": "zone.home"},
                        ],
                    },
                },
            },
        }
        store.async_remove_from_queue = AsyncMock()
        store.async_requeue_entries = AsyncMock(return_value=(0, 0))

        callback = _setup_arrival_with_store(mock_hass, store)

        # Now flip the zone: alice is now home
        mock_hass.register_zone("zone.home", "Home", ["person.alice"])

        event = _make_arrival_event(
            fake_state, "person.alice", "not_home", "home",
        )

        with patch(
            "custom_components.ticker.arrival.async_send_bundled_notification",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            _run(callback(event))

        assert mock_send.await_count == 1, (
            "expected bundled notification to be sent on arrival"
        )
        sent_entries = mock_send.await_args.args[2]
        assert len(sent_entries) == 1
        assert sent_entries[0]["queue_id"] == "q1"
        store.async_remove_from_queue.assert_awaited_with("q1")

    def test_departure_keeps_queue_intact(self, mock_hass, fake_state):
        """Person leaves zone -> queued entry stays queued, no delivery."""
        mock_hass.register_zone("zone.home", "Home", [])  # alice not present

        store = MagicMock()
        store.is_user_enabled.return_value = True
        store.get_queue_for_person.return_value = [
            {
                "queue_id": "q1",
                "category_id": "cat1",
                "title": "t",
                "message": "m",
            },
        ]
        store.get_subscriptions_for_person.return_value = {
            "cat1": {
                "mode": MODE_CONDITIONAL,
                "conditions": {
                    "deliver_when_met": True,
                    "queue_until_met": True,
                    "condition_tree": {
                        "type": "group",
                        "operator": "AND",
                        "children": [
                            {"type": "zone", "zone_id": "zone.home"},
                        ],
                    },
                },
            },
        }
        store.async_remove_from_queue = AsyncMock()
        store.async_requeue_entries = AsyncMock(return_value=(0, 0))

        callback = _setup_arrival_with_store(mock_hass, store)

        # Departure: state changed away from home, persons still []
        event = _make_arrival_event(
            fake_state, "person.alice", "home", "not_home",
        )

        with patch(
            "custom_components.ticker.arrival.async_send_bundled_notification",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            _run(callback(event))

        assert mock_send.await_count == 0, (
            "expected no delivery on departure"
        )
        store.async_remove_from_queue.assert_not_awaited()

    def test_legacy_zones_path_uses_persons_not_friendly_name(
        self, mock_hass, fake_state,
    ):
        """Legacy ``zones`` shape: arrival match uses persons membership.

        Renames the zone friendly_name to "Thuis" to prove the legacy
        path no longer compares person.state against friendly_name.
        Fixes the BUG-102 codepath at arrival.py:140.
        """
        # Renamed zone, alice is now inside via persons
        mock_hass.register_zone("zone.home", "Thuis", ["person.alice"])

        store = MagicMock()
        store.is_user_enabled.return_value = True
        store.get_queue_for_person.return_value = [
            {
                "queue_id": "q1",
                "category_id": "cat1",
                "title": "t",
                "message": "m",
            },
        ]
        # Legacy conditions shape: no rules, no condition_tree, only zones dict
        store.get_subscriptions_for_person.return_value = {
            "cat1": {
                "mode": MODE_CONDITIONAL,
                "conditions": {
                    "zones": {
                        "zone.home": {"queue_until_arrival": True},
                    },
                },
            },
        }
        store.async_remove_from_queue = AsyncMock()
        store.async_requeue_entries = AsyncMock(return_value=(0, 0))

        callback = _setup_arrival_with_store(mock_hass, store)

        event = _make_arrival_event(
            fake_state, "person.alice", "not_home", "home",
        )

        with patch(
            "custom_components.ticker.arrival.async_send_bundled_notification",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            _run(callback(event))

        assert mock_send.await_count == 1, (
            "BUG-102 regression: legacy zones path must use persons "
            "membership, not friendly_name comparison"
        )
        sent_entries = mock_send.await_args.args[2]
        assert len(sent_entries) == 1
        assert sent_entries[0]["queue_id"] == "q1"
        store.async_remove_from_queue.assert_awaited_with("q1")
