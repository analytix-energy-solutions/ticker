"""Tests for BUG-063 through BUG-068 review fix manifest.

Covers:
- BUG-063: convert_legacy_zones_to_rules return value merged via conditions.update()
- BUG-064: evaluate_rules returns tuple[bool, list[tuple[bool, str]]]
- BUG-065/066: Dead code removal verification (sanitize_for_html, async_unload_services)
- DELIVERY_FORMAT_PATTERNS regression
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from custom_components.ticker.conditions import (
    convert_legacy_zones_to_rules,
    evaluate_rule,
    evaluate_rules,
    should_deliver_now,
    should_queue,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_PATTERNS,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_RICH,
    RULE_TYPE_STATE,
    RULE_TYPE_TIME,
    RULE_TYPE_ZONE,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.states = MagicMock()
    # BUG-087: resolve_zone_name calls hass.states.get(zone_id). Default
    # MagicMock returns a truthy MagicMock with a MagicMock friendly_name,
    # which breaks slug fallback. Return None for zone.* lookups so the
    # helper falls back to the slug; tests that need a stored entity
    # state override via side_effect below.
    _state_store: dict[str, object] = {}

    def _states_get(entity_id: str):
        if entity_id in _state_store:
            return _state_store[entity_id]
        if entity_id.startswith("zone."):
            return None
        return None

    hass.states.get.side_effect = _states_get
    hass.states._test_store = _state_store  # type: ignore[attr-defined]
    return hass


# ---------------------------------------------------------------------------
# BUG-064: evaluate_rules return type
# ---------------------------------------------------------------------------

class TestEvaluateRulesReturnType:
    """evaluate_rules must return (bool, list[tuple[bool, str]])."""

    def test_empty_rules_returns_tuple_with_list(self, mock_hass):
        all_met, results = evaluate_rules(mock_hass, [], person_state=None)
        assert all_met is True
        assert isinstance(results, list)
        assert len(results) == 1
        is_met, reason = results[0]
        assert is_met is True
        assert isinstance(reason, str)

    def test_single_met_rule_returns_correct_shape(self, mock_hass, fake_state):
        person = fake_state("person.alice", "home")
        rules = [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}]

        all_met, results = evaluate_rules(mock_hass, rules, person_state=person)

        assert all_met is True
        assert len(results) == 1
        assert results[0][0] is True
        assert "home" in results[0][1].lower()

    def test_single_unmet_rule_returns_false(self, mock_hass, fake_state):
        person = fake_state("person.alice", "not_home")
        rules = [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}]

        all_met, results = evaluate_rules(mock_hass, rules, person_state=person)

        assert all_met is False
        assert len(results) == 1
        assert results[0][0] is False

    def test_mixed_rules_collects_all_results(self, mock_hass, fake_state):
        """Even when one rule fails, all rules are evaluated and returned."""
        person = fake_state("person.alice", "home")
        state_obj = MagicMock()
        state_obj.state = "off"
        mock_hass.states._test_store["switch.x"] = state_obj

        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "08:00", "before": "22:00"},
            {"type": RULE_TYPE_STATE, "entity_id": "switch.x", "state": "on"},
        ]
        now = datetime(2026, 3, 25, 12, 0)

        all_met, results = evaluate_rules(
            mock_hass, rules, person_state=person, now=now
        )

        assert all_met is False  # state rule not met
        assert len(results) == 3
        # Zone met, time met, state not met
        assert results[0][0] is True
        assert results[1][0] is True
        assert results[2][0] is False

    def test_per_rule_results_match_individual_evaluate_rule(self, mock_hass, fake_state):
        """Per-rule results from evaluate_rules match calling evaluate_rule individually."""
        person = fake_state("person.alice", "not_home")
        state_obj = MagicMock()
        state_obj.state = "on"
        mock_hass.states._test_store["switch.x"] = state_obj

        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_STATE, "entity_id": "switch.x", "state": "on"},
        ]
        now = datetime(2026, 3, 25, 12, 0)

        _, results = evaluate_rules(mock_hass, rules, person_state=person, now=now)

        for i, rule in enumerate(rules):
            individual_met, individual_reason = evaluate_rule(
                mock_hass, rule, person_state=person, now=now
            )
            assert results[i][0] == individual_met
            assert results[i][1] == individual_reason

    def test_all_met_true_when_all_rules_pass(self, mock_hass, fake_state):
        person = fake_state("person.alice", "home")
        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "00:00", "before": "23:59"},
        ]
        now = datetime(2026, 3, 25, 12, 0)

        all_met, results = evaluate_rules(
            mock_hass, rules, person_state=person, now=now
        )

        assert all_met is True
        assert all(r[0] for r in results)

    def test_all_met_false_when_any_rule_fails(self, mock_hass, fake_state):
        person = fake_state("person.alice", "not_home")
        rules = [
            {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
            {"type": RULE_TYPE_TIME, "after": "00:00", "before": "23:59"},
        ]
        now = datetime(2026, 3, 25, 12, 0)

        all_met, results = evaluate_rules(
            mock_hass, rules, person_state=person, now=now
        )

        assert all_met is False


# ---------------------------------------------------------------------------
# BUG-064: should_deliver_now uses evaluate_rules without re-evaluating
# ---------------------------------------------------------------------------

class TestShouldDeliverNowUsesRuleResults:
    """should_deliver_now returns first unmet reason from rule_results."""

    def test_deliver_when_all_met(self, mock_hass, fake_state):
        person = fake_state("person.alice", "home")
        conditions = {
            "deliver_when_met": True,
            "rules": [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}],
        }

        deliver, reason = should_deliver_now(mock_hass, conditions, person)
        assert deliver is True
        assert "met" in reason.lower()

    def test_no_deliver_returns_first_unmet_reason(self, mock_hass, fake_state):
        person = fake_state("person.alice", "not_home")
        conditions = {
            "deliver_when_met": True,
            "rules": [
                {"type": RULE_TYPE_ZONE, "zone_id": "zone.home"},
                {"type": RULE_TYPE_TIME, "after": "08:00", "before": "10:00"},
            ],
        }
        now = datetime(2026, 3, 25, 23, 0)

        deliver, reason = should_deliver_now(mock_hass, conditions, person, now=now)
        assert deliver is False
        # Should get the zone failure reason (first unmet)
        assert "home" in reason.lower()

    def test_no_delivery_without_deliver_when_met(self, mock_hass, fake_state):
        person = fake_state("person.alice", "home")
        conditions = {
            "deliver_when_met": False,
            "rules": [{"type": RULE_TYPE_ZONE, "zone_id": "zone.home"}],
        }

        deliver, reason = should_deliver_now(mock_hass, conditions, person)
        assert deliver is False
        assert "not enabled" in reason.lower()


# ---------------------------------------------------------------------------
# BUG-063: convert_legacy_zones_to_rules and conditions.update()
# ---------------------------------------------------------------------------

class TestConvertLegacyZonesToRules:
    """convert_legacy_zones_to_rules returns dict with all three keys."""

    def test_returns_deliver_when_met_key(self):
        zones = {"zone.home": {"deliver_while_here": True}}
        result = convert_legacy_zones_to_rules(zones)
        assert "deliver_when_met" in result
        assert result["deliver_when_met"] is True

    def test_returns_queue_until_met_key(self):
        zones = {"zone.home": {"queue_until_arrival": True}}
        result = convert_legacy_zones_to_rules(zones)
        assert "queue_until_met" in result
        assert result["queue_until_met"] is True

    def test_returns_rules_key(self):
        zones = {"zone.home": {"deliver_while_here": True}}
        result = convert_legacy_zones_to_rules(zones)
        assert "rules" in result
        assert len(result["rules"]) == 1
        assert result["rules"][0]["type"] == RULE_TYPE_ZONE
        assert result["rules"][0]["zone_id"] == "zone.home"

    def test_multiple_zones(self):
        zones = {
            "zone.home": {"deliver_while_here": True, "queue_until_arrival": True},
            "zone.work": {"deliver_while_here": False, "queue_until_arrival": False},
        }
        result = convert_legacy_zones_to_rules(zones)
        assert len(result["rules"]) == 2
        assert result["deliver_when_met"] is True
        assert result["queue_until_met"] is True

    def test_no_flags_set(self):
        zones = {"zone.home": {}}
        result = convert_legacy_zones_to_rules(zones)
        assert result["deliver_when_met"] is False
        assert result["queue_until_met"] is False

    def test_empty_zones(self):
        result = convert_legacy_zones_to_rules({})
        assert result["deliver_when_met"] is False
        assert result["queue_until_met"] is False
        assert result["rules"] == []


class TestConditionsUpdateMerge:
    """BUG-063: conditions.update(converted) merges all three keys correctly."""

    def test_update_merges_all_keys(self):
        """Simulates the fix in user_notify.py line 95: conditions.update(converted)."""
        # Start with legacy conditions (has zones but no rules)
        conditions = {
            "zones": {"zone.home": {"deliver_while_here": True, "queue_until_arrival": True}},
        }

        # Simulate the conversion
        converted = convert_legacy_zones_to_rules(conditions["zones"])
        conditions.update(converted)

        # After update, conditions must have all keys
        assert "deliver_when_met" in conditions
        assert conditions["deliver_when_met"] is True
        assert "queue_until_met" in conditions
        assert conditions["queue_until_met"] is True
        assert "rules" in conditions
        assert len(conditions["rules"]) == 1
        # Original zones key preserved (not removed by update)
        assert "zones" in conditions

    def test_update_overwrites_existing_keys(self):
        """If conditions already had partial keys, update replaces them."""
        conditions = {
            "deliver_when_met": False,
            "zones": {"zone.home": {"deliver_while_here": True}},
        }
        converted = convert_legacy_zones_to_rules(conditions["zones"])
        conditions.update(converted)
        assert conditions["deliver_when_met"] is True


# ---------------------------------------------------------------------------
# BUG-065/066: Dead code verification
# ---------------------------------------------------------------------------

class TestDeadCodeRemoval:
    """Verify dead code was removed as claimed."""

    def test_sanitize_for_html_does_not_exist_in_validation(self):
        from custom_components.ticker.websocket import validation
        assert not hasattr(validation, "sanitize_for_html"), (
            "sanitize_for_html should have been removed from validation module"
        )

    def test_async_unload_services_does_not_exist_in_services(self):
        from custom_components.ticker import services
        assert not hasattr(services, "async_unload_services"), (
            "async_unload_services should have been removed from services module"
        )

    def test_sanitize_for_storage_still_exists(self):
        """Verify sanitize_for_storage was NOT removed (it is still used)."""
        from custom_components.ticker.websocket.validation import sanitize_for_storage
        assert callable(sanitize_for_storage)


# ---------------------------------------------------------------------------
# DELIVERY_FORMAT_PATTERNS regression
# ---------------------------------------------------------------------------

class TestDeliveryFormatPatterns:
    """Verify DELIVERY_FORMAT_PATTERNS still work after all changes."""

    def test_patterns_is_a_list(self):
        assert isinstance(DELIVERY_FORMAT_PATTERNS, list)
        assert len(DELIVERY_FORMAT_PATTERNS) > 0

    def test_each_pattern_is_3_tuple(self):
        for pat in DELIVERY_FORMAT_PATTERNS:
            assert len(pat) == 3, f"Pattern {pat} is not a 3-tuple"
            match_type, pattern, fmt = pat
            assert match_type in ("startswith", "contains", "equals")
            assert isinstance(pattern, str)
            assert isinstance(fmt, str)

    def test_persistent_notification_pattern(self):
        found = False
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            if pattern == "notify.persistent_notification":
                assert match_type == "equals"
                assert fmt == DELIVERY_FORMAT_PERSISTENT
                found = True
        assert found, "persistent_notification pattern missing"

    def test_mobile_app_pattern(self):
        found = False
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            if pattern == "mobile_app":
                assert match_type == "contains"
                assert fmt == DELIVERY_FORMAT_RICH
                found = True
        assert found, "mobile_app pattern missing"

    def test_nfandroidtv_pattern(self):
        found = False
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            if pattern == "nfandroidtv":
                assert match_type == "contains"
                assert fmt == DELIVERY_FORMAT_RICH
                found = True
        assert found, "nfandroidtv pattern missing"
