"""Tests for conditions.py person_state=None handling (F-18 recipient support).

When person_state is None (recipients have no location), zone rules should
be skipped (treated as met). Time and state rules should still evaluate normally.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from custom_components.ticker.conditions import (
    evaluate_rule,
    evaluate_rules,
    should_deliver_now,
    should_queue,
)
from custom_components.ticker.const import (
    RULE_TYPE_ZONE,
    RULE_TYPE_TIME,
    RULE_TYPE_STATE,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.states = MagicMock()
    return hass


# ---------------------------------------------------------------------------
# evaluate_rule with person_state=None
# ---------------------------------------------------------------------------

class TestEvaluateRuleNoPerson:
    """Zone rules skip when person_state is None; others still evaluate."""

    def test_zone_rule_skipped(self, mock_hass):
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None)
        assert is_met is True
        assert "skipped" in reason.lower()

    def test_time_rule_still_evaluated(self, mock_hass):
        rule = {"type": RULE_TYPE_TIME, "after": "08:00", "before": "22:00"}
        now = datetime(2026, 3, 22, 12, 0)  # noon, within window
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None, now=now)
        assert is_met is True

    def test_time_rule_outside_window(self, mock_hass):
        rule = {"type": RULE_TYPE_TIME, "after": "08:00", "before": "10:00"}
        now = datetime(2026, 3, 22, 23, 0)
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None, now=now)
        assert is_met is False

    def test_state_rule_still_evaluated(self, mock_hass):
        state_obj = MagicMock()
        state_obj.state = "on"
        mock_hass.states.get.return_value = state_obj

        rule = {"type": RULE_TYPE_STATE, "entity_id": "switch.alarm", "state": "on"}
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None)
        assert is_met is True

    def test_state_rule_not_met(self, mock_hass):
        state_obj = MagicMock()
        state_obj.state = "off"
        mock_hass.states.get.return_value = state_obj

        rule = {"type": RULE_TYPE_STATE, "entity_id": "switch.alarm", "state": "on"}
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None)
        assert is_met is False

    def test_unknown_rule_type(self, mock_hass):
        rule = {"type": "unknown"}
        is_met, reason = evaluate_rule(mock_hass, rule, person_state=None)
        assert is_met is False
        assert "unknown" in reason.lower()


# ---------------------------------------------------------------------------
# evaluate_rule with person_state (existing behavior, regression)
# ---------------------------------------------------------------------------

class TestEvaluateRuleWithPerson:
    def test_zone_rule_met(self, mock_hass, fake_state):
        person = fake_state("person.alice", "home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}
        is_met, _ = evaluate_rule(mock_hass, rule, person_state=person)
        assert is_met is True

    def test_zone_rule_not_met(self, mock_hass, fake_state):
        person = fake_state("person.alice", "not_home")
        rule = {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}
        is_met, _ = evaluate_rule(mock_hass, rule, person_state=person)
        assert is_met is False


# ---------------------------------------------------------------------------
# evaluate_rules with person_state=None
# ---------------------------------------------------------------------------

class TestEvaluateRulesNoPerson:
    def test_empty_rules_returns_true(self, mock_hass):
        all_met, reasons = evaluate_rules(mock_hass, [], person_state=None)
        assert all_met is True

    def test_zone_only_all_met(self, mock_hass):
        rules = [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}]
        all_met, reasons = evaluate_rules(mock_hass, rules, person_state=None)
        assert all_met is True

    def test_mixed_zone_and_time_met(self, mock_hass):
        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "00:00", "before": "23:59"},
        ]
        now = datetime(2026, 3, 22, 12, 0)
        all_met, reasons = evaluate_rules(mock_hass, rules, person_state=None, now=now)
        assert all_met is True
        assert len(reasons) == 2

    def test_mixed_zone_and_time_not_met(self, mock_hass):
        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "08:00", "before": "10:00"},
        ]
        now = datetime(2026, 3, 22, 23, 0)
        all_met, reasons = evaluate_rules(mock_hass, rules, person_state=None, now=now)
        assert all_met is False

    def test_mixed_zone_time_state_all_met(self, mock_hass):
        state_obj = MagicMock()
        state_obj.state = "on"
        mock_hass.states.get.return_value = state_obj

        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "00:00", "before": "23:59"},
            {"type": RULE_TYPE_STATE, "entity_id": "switch.x", "state": "on"},
        ]
        now = datetime(2026, 3, 22, 12, 0)
        all_met, reasons = evaluate_rules(mock_hass, rules, person_state=None, now=now)
        assert all_met is True
        assert len(reasons) == 3


# ---------------------------------------------------------------------------
# should_deliver_now / should_queue with person_state=None
# ---------------------------------------------------------------------------

class TestShouldDeliverNoPerson:
    def test_deliver_with_zone_rule_met(self, mock_hass):
        conditions = {
            "deliver_when_met": True,
            "rules": [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}],
        }
        deliver, reason = should_deliver_now(mock_hass, conditions, person_state=None)
        assert deliver is True

    def test_no_deliver_when_time_not_met(self, mock_hass):
        conditions = {
            "deliver_when_met": True,
            "rules": [
                {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
                {"type": RULE_TYPE_TIME, "after": "08:00", "before": "10:00"},
            ],
        }
        now = datetime(2026, 3, 22, 23, 0)
        deliver, reason = should_deliver_now(
            mock_hass, conditions, person_state=None, now=now
        )
        assert deliver is False


class TestShouldQueueNoPerson:
    def test_queue_when_time_not_met(self, mock_hass):
        conditions = {
            "deliver_when_met": True,
            "queue_until_met": True,
            "rules": [
                {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
                {"type": RULE_TYPE_TIME, "after": "08:00", "before": "10:00"},
            ],
        }
        now = datetime(2026, 3, 22, 23, 0)
        should_q, reason = should_queue(
            mock_hass, conditions, person_state=None, now=now
        )
        assert should_q is True

    def test_no_queue_when_all_met(self, mock_hass):
        conditions = {
            "deliver_when_met": True,
            "queue_until_met": True,
            "rules": [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}],
        }
        should_q, reason = should_queue(mock_hass, conditions, person_state=None)
        assert should_q is False
