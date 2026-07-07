"""Tests for the duration rule type (F-fork: Duration Rule Type).

Covers:
- evaluate_duration_rule: within / for_at_least comparisons, entity
  default-to-person, missing fields, entity not found
- evaluate_rule dispatch to RULE_TYPE_DURATION
- _collect_triggers_from_node / get_queue_triggers collecting duration leaves
- validate_condition_tree accepting/rejecting duration leaves
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.ticker.conditions import (
    evaluate_duration_rule,
    evaluate_rule,
    get_queue_triggers,
)
from custom_components.ticker.websocket.validation import validate_condition_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    """A fixed reference 'now' for deterministic elapsed-time math."""
    from datetime import datetime, timezone

    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _state(entity_id: str, state: str, minutes_ago: float) -> MagicMock:
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.last_changed = _now() - timedelta(minutes=minutes_ago)
    return s


def _hass_with_state(state: MagicMock | None) -> MagicMock:
    hass = MagicMock()
    hass.states.get = lambda eid: state if state and eid == state.entity_id else None
    return hass


def _duration_leaf(**overrides) -> dict:
    leaf = {
        "type": "duration",
        "entity_id": "person.frank",
        "state": "home",
        "comparison": "within",
        "minutes": 10,
    }
    leaf.update(overrides)
    return leaf


# ---------------------------------------------------------------------------
# evaluate_duration_rule: "within" comparison (just_arrived / just_left)
# ---------------------------------------------------------------------------

class TestDurationWithin:
    def test_within_threshold_is_met(self):
        state = _state("person.frank", "home", minutes_ago=5)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="within", minutes=10)
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is True
        assert "person.frank" in reason

    def test_beyond_threshold_is_not_met(self):
        state = _state("person.frank", "home", minutes_ago=15)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="within", minutes=10)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False

    def test_exact_threshold_is_met_inclusive(self):
        state = _state("person.frank", "home", minutes_ago=10)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="within", minutes=10)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is True

    def test_wrong_state_is_not_met(self):
        state = _state("person.frank", "not_home", minutes_ago=1)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="within", minutes=10, state="home")
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False
        assert "not_home" in reason


# ---------------------------------------------------------------------------
# evaluate_duration_rule: "for_at_least" comparison (staying_home / staying_away)
# ---------------------------------------------------------------------------

class TestDurationForAtLeast:
    def test_long_enough_is_met(self):
        state = _state("person.frank", "home", minutes_ago=30)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="for_at_least", minutes=15)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is True

    def test_not_long_enough_is_not_met(self):
        state = _state("person.frank", "home", minutes_ago=5)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="for_at_least", minutes=15)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False

    def test_exact_threshold_is_met_inclusive(self):
        state = _state("person.frank", "home", minutes_ago=15)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="for_at_least", minutes=15)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is True


# ---------------------------------------------------------------------------
# entity_id defaulting to person_state, and missing-field handling
# ---------------------------------------------------------------------------

class TestDurationDefaultsAndErrors:
    def test_blank_entity_id_defaults_to_person_state(self):
        state = _state("person.kevin", "home", minutes_ago=2)
        hass = _hass_with_state(state)
        rule = _duration_leaf(entity_id="", comparison="within", minutes=10)
        is_met, reason = evaluate_duration_rule(hass, rule, state, now=_now())
        assert is_met is True
        assert "person.kevin" in reason

    def test_blank_entity_id_no_person_state_is_skipped_as_met(self):
        """Recipients have no person_state; a blank-entity duration leaf must
        not become permanently unmet with no way to fix it (mirrors the
        zone rule's "no person context" skip for recipients)."""
        hass = _hass_with_state(None)
        rule = _duration_leaf(entity_id="", comparison="within", minutes=10)
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is True
        assert "skipped" in reason

    def test_missing_state_field(self):
        hass = _hass_with_state(_state("person.frank", "home", 1))
        rule = _duration_leaf(state="")
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False
        assert "state" in reason

    def test_missing_minutes(self):
        hass = _hass_with_state(_state("person.frank", "home", 1))
        rule = _duration_leaf(minutes=None)
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False
        assert "minutes" in reason

    def test_negative_minutes(self):
        hass = _hass_with_state(_state("person.frank", "home", 1))
        rule = _duration_leaf(minutes=-5)
        is_met, _reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False

    def test_entity_not_found(self):
        hass = _hass_with_state(None)
        rule = _duration_leaf(entity_id="person.ghost")
        is_met, reason = evaluate_duration_rule(hass, rule, None, now=_now())
        assert is_met is False
        assert "not found" in reason


# ---------------------------------------------------------------------------
# evaluate_rule dispatch
# ---------------------------------------------------------------------------

class TestEvaluateRuleDispatchesDuration:
    def test_dispatches_to_duration_evaluator(self):
        state = _state("person.frank", "home", minutes_ago=5)
        hass = _hass_with_state(state)
        rule = _duration_leaf(comparison="within", minutes=10)
        is_met, _reason = evaluate_rule(hass, rule, None, now=_now())
        assert is_met is True


# ---------------------------------------------------------------------------
# Trigger collection for the condition-listener scheduler
# ---------------------------------------------------------------------------

class TestDurationTriggerCollection:
    def test_get_queue_triggers_collects_duration_entity_and_meta(self):
        conditions = {
            "queue_until_met": True,
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [_duration_leaf(entity_id="person.frank")],
            },
        }
        triggers = get_queue_triggers(conditions)
        assert "person.frank" in triggers["entities"]
        assert len(triggers["durations"]) == 1
        assert triggers["durations"][0]["entity_id"] == "person.frank"
        assert triggers["durations"][0]["comparison"] == "within"

    def test_get_queue_triggers_collects_blank_entity_duration(self):
        """Blank entity_id is still collected; caller resolves the person default."""
        conditions = {
            "queue_until_met": True,
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [_duration_leaf(entity_id="")],
            },
        }
        triggers = get_queue_triggers(conditions)
        assert triggers["entities"] == set() or "" not in triggers["entities"]
        assert len(triggers["durations"]) == 1
        assert triggers["durations"][0]["entity_id"] == ""

    def test_get_queue_triggers_empty_when_queue_not_enabled(self):
        conditions = {
            "queue_until_met": False,
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "children": [_duration_leaf()],
            },
        }
        triggers = get_queue_triggers(conditions)
        assert triggers["durations"] == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestDurationValidation:
    def _group(self, *children):
        return {"type": "group", "operator": "AND", "children": list(children)}

    def test_valid_duration_leaf_passes(self):
        tree = self._group(_duration_leaf())
        assert validate_condition_tree(tree) is None

    def test_blank_entity_id_is_valid_structurally(self):
        tree = self._group(_duration_leaf(entity_id=""))
        assert validate_condition_tree(tree) is None

    def test_invalid_entity_id_format_rejected(self):
        tree = self._group(_duration_leaf(entity_id="not-a-valid-id"))
        error = validate_condition_tree(tree)
        assert error is not None
        assert error[0] == "invalid_duration_rule"

    def test_entity_not_found_rejected_when_hass_provided(self):
        hass = _hass_with_state(None)
        tree = self._group(_duration_leaf(entity_id="person.ghost"))
        error = validate_condition_tree(tree, hass)
        assert error is not None
        assert error[0] == "entity_not_found"

    def test_missing_state_rejected(self):
        tree = self._group(_duration_leaf(state=""))
        error = validate_condition_tree(tree)
        assert error is not None
        assert error[0] == "invalid_duration_rule"

    def test_invalid_comparison_rejected(self):
        tree = self._group(_duration_leaf(comparison="sideways"))
        error = validate_condition_tree(tree)
        assert error is not None
        assert error[0] == "invalid_duration_rule"

    def test_zero_minutes_rejected(self):
        tree = self._group(_duration_leaf(minutes=0))
        error = validate_condition_tree(tree)
        assert error is not None

    def test_excessive_minutes_rejected(self):
        tree = self._group(_duration_leaf(minutes=99999))
        error = validate_condition_tree(tree)
        assert error is not None
        assert error[0] == "invalid_duration_rule"

    def test_non_numeric_minutes_rejected(self):
        tree = self._group(_duration_leaf(minutes="ten"))
        error = validate_condition_tree(tree)
        assert error is not None
