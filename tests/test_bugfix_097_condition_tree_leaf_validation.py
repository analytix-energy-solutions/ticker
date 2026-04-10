"""Tests for BUG-097: validate_condition_tree performs leaf semantic checks.

Leaf nodes now validate:
- zone: zone_id exists in HA state machine (when hass provided)
- time: after/before are HH:MM format
- state: entity_id exists in HA state machine (when hass provided)

When hass=None, only structural validation runs so tests that don't
need HA state can call without it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ticker.websocket.validation import validate_condition_tree


def _group(*children, operator="AND") -> dict:
    return {"type": "group", "operator": operator, "children": list(children)}


def _hass_with_states(states: dict) -> MagicMock:
    hass = MagicMock()

    def _get(eid):
        return states.get(eid)

    hass.states.get = _get
    return hass


class TestBug097LeafValidation:

    def test_state_leaf_entity_not_found(self):
        hass = _hass_with_states({})
        tree = _group({
            "type": "state",
            "entity_id": "switch.does_not_exist",
            "state": "on",
        })
        error = validate_condition_tree(tree, hass)
        assert error is not None
        code, _msg = error
        assert code == "entity_not_found"

    def test_state_leaf_entity_exists_passes(self):
        hass = _hass_with_states({"switch.light": MagicMock()})
        tree = _group({
            "type": "state",
            "entity_id": "switch.light",
            "state": "on",
        })
        assert validate_condition_tree(tree, hass) is None

    def test_time_leaf_malformed_after(self):
        tree = _group({
            "type": "time",
            "after": "not-a-time",
            "before": "22:00",
        })
        error = validate_condition_tree(tree, hass=None)
        assert error is not None
        code, _msg = error
        assert code == "invalid_time_format"

    def test_time_leaf_malformed_before(self):
        tree = _group({
            "type": "time",
            "after": "08:00",
            "before": "25:99",
        })
        error = validate_condition_tree(tree, hass=None)
        assert error is not None
        assert error[0] == "invalid_time_format"

    def test_time_leaf_valid_passes_without_hass(self):
        tree = _group({
            "type": "time",
            "after": "08:00",
            "before": "22:00",
        })
        assert validate_condition_tree(tree, hass=None) is None

    def test_zone_leaf_zone_not_found(self):
        hass = _hass_with_states({})
        tree = _group({
            "type": "zone",
            "zone_id": "zone.nowhere",
        })
        error = validate_condition_tree(tree, hass)
        assert error is not None
        code, _msg = error
        assert code == "zone_not_found"

    def test_zone_leaf_invalid_format(self):
        tree = _group({
            "type": "zone",
            "zone_id": "not_a_zone",
        })
        error = validate_condition_tree(tree, hass=None)
        assert error is not None
        assert error[0] == "invalid_zone"

    def test_zone_leaf_existing_zone_passes(self):
        hass = _hass_with_states({"zone.home": MagicMock()})
        tree = _group({
            "type": "zone",
            "zone_id": "zone.home",
        })
        assert validate_condition_tree(tree, hass) is None

    def test_structural_only_with_hass_none(self):
        """hass=None skips entity/zone existence checks but still
        performs structural validation."""
        tree = _group({
            "type": "state",
            "entity_id": "switch.anything",
            "state": "on",
        })
        # Should pass structural validation without needing hass
        assert validate_condition_tree(tree, hass=None) is None

    def test_nested_group_propagates_child_error(self):
        hass = _hass_with_states({})
        tree = _group(
            _group({
                "type": "state",
                "entity_id": "switch.missing",
                "state": "on",
            }),
        )
        error = validate_condition_tree(tree, hass)
        assert error is not None
        assert error[0] == "entity_not_found"
