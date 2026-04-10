"""Tests for F-2b Condition Tree Evaluation.

Covers:
- evaluate_group with AND/OR operators
- evaluate_condition_tree with tree vs legacy rules vs empty
- Nested groups: (A AND (B OR C))
- _collect_triggers_from_node
- _tree_has_leaves (via has_valid_rules with condition_tree)
- has_valid_rules with condition_tree
"""

from __future__ import annotations

from unittest.mock import MagicMock


from custom_components.ticker.conditions import (
    evaluate_group,
    evaluate_condition_tree,
    has_valid_rules,
    _collect_triggers_from_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass_with_states(states: dict[str, str]) -> MagicMock:
    """Build a mock hass where hass.states.get(eid).state returns value."""
    hass = MagicMock()

    def _get(entity_id: str):
        if entity_id in states:
            s = MagicMock()
            s.state = states[entity_id]
            return s
        return None

    hass.states.get = _get
    return hass


def _zone_leaf(zone_id: str) -> dict:
    return {"type": "zone", "zone_id": zone_id}


def _time_leaf(after: str, before: str, days: list | None = None) -> dict:
    d: dict = {"type": "time", "after": after, "before": before}
    if days:
        d["days"] = days
    return d


def _state_leaf(entity_id: str, state: str) -> dict:
    return {"type": "state", "entity_id": entity_id, "state": state}


def _group(operator: str, children: list) -> dict:
    return {"type": "group", "operator": operator, "children": children}


# ---------------------------------------------------------------------------
# evaluate_group with AND operator
# ---------------------------------------------------------------------------

class TestEvaluateGroupAND:
    """AND group: all children must be True for group to be True."""

    def test_all_true(self):
        """All state leaves met -> group is True."""
        hass = _make_hass_with_states({"switch.a": "on", "switch.b": "on"})
        group = _group("AND", [
            _state_leaf("switch.a", "on"),
            _state_leaf("switch.b", "on"),
        ])
        result, details = evaluate_group(hass, group, None)
        assert result is True
        assert all(d[0] for d in details)

    def test_one_false(self):
        """One child unmet -> group is False."""
        hass = _make_hass_with_states({"switch.a": "on", "switch.b": "off"})
        group = _group("AND", [
            _state_leaf("switch.a", "on"),
            _state_leaf("switch.b", "on"),
        ])
        result, details = evaluate_group(hass, group, None)
        assert result is False

    def test_empty_children(self):
        """Empty children list -> True (vacuous truth)."""
        hass = MagicMock()
        group = _group("AND", [])
        result, details = evaluate_group(hass, group, None)
        assert result is True


# ---------------------------------------------------------------------------
# evaluate_group with OR operator
# ---------------------------------------------------------------------------

class TestEvaluateGroupOR:
    """OR group: at least one child True for group to be True."""

    def test_one_true(self):
        """One child met -> group is True."""
        hass = _make_hass_with_states({"switch.a": "off", "switch.b": "on"})
        group = _group("OR", [
            _state_leaf("switch.a", "on"),
            _state_leaf("switch.b", "on"),
        ])
        result, details = evaluate_group(hass, group, None)
        assert result is True

    def test_all_false(self):
        """All children unmet -> group is False."""
        hass = _make_hass_with_states({"switch.a": "off", "switch.b": "off"})
        group = _group("OR", [
            _state_leaf("switch.a", "on"),
            _state_leaf("switch.b", "on"),
        ])
        result, details = evaluate_group(hass, group, None)
        assert result is False

    def test_all_true(self):
        """All children met -> group is True."""
        hass = _make_hass_with_states({"switch.a": "on", "switch.b": "on"})
        group = _group("OR", [
            _state_leaf("switch.a", "on"),
            _state_leaf("switch.b", "on"),
        ])
        result, details = evaluate_group(hass, group, None)
        assert result is True


# ---------------------------------------------------------------------------
# evaluate_condition_tree
# ---------------------------------------------------------------------------

class TestEvaluateConditionTree:
    """Test evaluate_condition_tree dispatch to tree vs legacy vs empty."""

    def test_with_condition_tree(self):
        """condition_tree present -> delegates to evaluate_group."""
        hass = _make_hass_with_states({"switch.a": "on"})
        conditions = {
            "condition_tree": _group("AND", [
                _state_leaf("switch.a", "on"),
            ]),
        }
        result, details = evaluate_condition_tree(hass, conditions, None)
        assert result is True

    def test_with_legacy_rules(self):
        """No condition_tree, rules[] present -> delegates to evaluate_rules."""
        hass = _make_hass_with_states({"switch.a": "on"})
        conditions = {
            "rules": [_state_leaf("switch.a", "on")],
        }
        result, details = evaluate_condition_tree(hass, conditions, None)
        assert result is True

    def test_with_legacy_rules_unmet(self):
        """Legacy rules with unmet condition."""
        hass = _make_hass_with_states({"switch.a": "off"})
        conditions = {
            "rules": [_state_leaf("switch.a", "on")],
        }
        result, details = evaluate_condition_tree(hass, conditions, None)
        assert result is False

    def test_empty_conditions(self):
        """No tree, no rules -> returns (True, [...])."""
        hass = MagicMock()
        conditions = {}
        result, details = evaluate_condition_tree(hass, conditions, None)
        assert result is True

    def test_tree_takes_precedence_over_rules(self):
        """When both condition_tree and rules exist, tree wins."""
        hass = _make_hass_with_states({"switch.a": "on", "switch.b": "off"})
        conditions = {
            "condition_tree": _group("AND", [
                _state_leaf("switch.a", "on"),
            ]),
            "rules": [_state_leaf("switch.b", "on")],  # would fail
        }
        result, _ = evaluate_condition_tree(hass, conditions, None)
        assert result is True  # tree wins


# ---------------------------------------------------------------------------
# Nested groups: (A AND (B OR C))
# ---------------------------------------------------------------------------

class TestNestedGroups:
    """Test nested group evaluation."""

    def test_a_and_b_or_c_all_met(self):
        """A=met, B=met, C=unmet -> AND(A, OR(B,C)) = True."""
        hass = _make_hass_with_states({
            "switch.a": "on",
            "switch.b": "on",
            "switch.c": "off",
        })
        tree = _group("AND", [
            _state_leaf("switch.a", "on"),
            _group("OR", [
                _state_leaf("switch.b", "on"),
                _state_leaf("switch.c", "on"),
            ]),
        ])
        result, details = evaluate_group(hass, tree, None)
        assert result is True

    def test_a_and_b_or_c_inner_fails(self):
        """A=met, B=unmet, C=unmet -> AND(A, OR(B,C)) = False."""
        hass = _make_hass_with_states({
            "switch.a": "on",
            "switch.b": "off",
            "switch.c": "off",
        })
        tree = _group("AND", [
            _state_leaf("switch.a", "on"),
            _group("OR", [
                _state_leaf("switch.b", "on"),
                _state_leaf("switch.c", "on"),
            ]),
        ])
        result, details = evaluate_group(hass, tree, None)
        assert result is False

    def test_a_and_b_or_c_outer_fails(self):
        """A=unmet, B=met -> AND(A, OR(B,C)) = False."""
        hass = _make_hass_with_states({
            "switch.a": "off",
            "switch.b": "on",
            "switch.c": "off",
        })
        tree = _group("AND", [
            _state_leaf("switch.a", "on"),
            _group("OR", [
                _state_leaf("switch.b", "on"),
                _state_leaf("switch.c", "on"),
            ]),
        ])
        result, details = evaluate_group(hass, tree, None)
        assert result is False

    def test_or_with_nested_and(self):
        """OR(AND(A,B), C) where A+B unmet but C met -> True."""
        hass = _make_hass_with_states({
            "switch.a": "off",
            "switch.b": "off",
            "switch.c": "on",
        })
        tree = _group("OR", [
            _group("AND", [
                _state_leaf("switch.a", "on"),
                _state_leaf("switch.b", "on"),
            ]),
            _state_leaf("switch.c", "on"),
        ])
        result, _ = evaluate_group(hass, tree, None)
        assert result is True


# ---------------------------------------------------------------------------
# _collect_triggers_from_node
# ---------------------------------------------------------------------------

class TestCollectTriggersFromNode:
    """Test recursive trigger collection from condition tree nodes."""

    def test_collects_zones(self):
        """Zone leaves produce zone triggers."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        node = _group("AND", [
            _zone_leaf("zone.home"),
            _zone_leaf("zone.work"),
        ])
        _collect_triggers_from_node(node, triggers)
        assert triggers["zones"] == {"zone.home", "zone.work"}

    def test_collects_entities(self):
        """State leaves produce entity triggers."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        node = _group("OR", [
            _state_leaf("switch.a", "on"),
            _state_leaf("binary_sensor.door", "open"),
        ])
        _collect_triggers_from_node(node, triggers)
        assert triggers["entities"] == {"switch.a", "binary_sensor.door"}

    def test_collects_time_windows(self):
        """Time leaves produce time_window triggers."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        node = _time_leaf("08:00", "22:00", [1, 2, 3])
        _collect_triggers_from_node(node, triggers)
        assert len(triggers["time_windows"]) == 1
        assert triggers["time_windows"][0]["after"] == "08:00"
        assert triggers["time_windows"][0]["days"] == [1, 2, 3]

    def test_collects_from_nested_groups(self):
        """Triggers collected recursively through nested groups."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        node = _group("AND", [
            _zone_leaf("zone.home"),
            _group("OR", [
                _state_leaf("switch.a", "on"),
                _time_leaf("09:00", "17:00"),
            ]),
        ])
        _collect_triggers_from_node(node, triggers)
        assert triggers["zones"] == {"zone.home"}
        assert triggers["entities"] == {"switch.a"}
        assert len(triggers["time_windows"]) == 1

    def test_empty_zone_id_skipped(self):
        """Zone leaf with empty zone_id does not add to triggers."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        _collect_triggers_from_node({"type": "zone", "zone_id": ""}, triggers)
        assert triggers["zones"] == set()

    def test_empty_entity_id_skipped(self):
        """State leaf with empty entity_id does not add to triggers."""
        triggers = {"zones": set(), "entities": set(), "time_windows": []}
        _collect_triggers_from_node({"type": "state", "entity_id": ""}, triggers)
        assert triggers["entities"] == set()


# ---------------------------------------------------------------------------
# has_valid_rules with condition_tree
# ---------------------------------------------------------------------------

class TestHasValidRulesTree:
    """Test has_valid_rules recognizes condition_tree format."""

    def test_tree_with_children_and_deliver(self):
        """condition_tree with children + deliver_when_met -> True."""
        conditions = {
            "condition_tree": _group("AND", [_state_leaf("switch.a", "on")]),
            "deliver_when_met": True,
        }
        assert has_valid_rules(conditions) is True

    def test_tree_with_children_and_queue(self):
        """condition_tree with children + queue_until_met -> True."""
        conditions = {
            "condition_tree": _group("AND", [_state_leaf("switch.a", "on")]),
            "queue_until_met": True,
        }
        assert has_valid_rules(conditions) is True

    def test_tree_with_children_no_flags(self):
        """condition_tree with children but no delivery flags -> False."""
        conditions = {
            "condition_tree": _group("AND", [_state_leaf("switch.a", "on")]),
        }
        assert has_valid_rules(conditions) is False

    def test_tree_empty_children(self):
        """condition_tree with empty children -> falls through to rules check."""
        conditions = {
            "condition_tree": _group("AND", []),
            "deliver_when_met": True,
        }
        # Empty children means tree.get("children") is [], which is falsy
        assert has_valid_rules(conditions) is False

    def test_none_conditions(self):
        """None conditions -> False."""
        assert has_valid_rules(None) is False

    def test_empty_conditions(self):
        """Empty dict -> False."""
        assert has_valid_rules({}) is False
