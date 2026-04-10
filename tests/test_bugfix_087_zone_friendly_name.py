"""Tests for BUG-087: zone rule must compare against friendly_name.

``person.state`` in Home Assistant is the zone's ``friendly_name``
(e.g. "Main House"), not the zone entity's object_id slug
(e.g. "main_house"). The previous logic compared the stored zone_id's
slug against person.state directly, so a zone with a distinct friendly
name never matched. BUG-087 introduces ``resolve_zone_name`` which
looks up the friendly name from the zone entity state and falls back
to the slug if the zone is gone.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ticker.conditions import (
    evaluate_zone_rule,
    resolve_zone_name,
)


def _zone_state(friendly_name: str | None):
    """Build a mock zone state with an optional friendly_name attribute."""
    state = MagicMock()
    state.attributes = {"friendly_name": friendly_name} if friendly_name else {}
    return state


def _hass_with_zone(zone_id: str, friendly: str | None):
    hass = MagicMock()

    def _get(entity_id):
        if entity_id == zone_id:
            return _zone_state(friendly)
        return None

    hass.states.get = _get
    return hass


def _person_state(state_value: str) -> MagicMock:
    ps = MagicMock()
    ps.state = state_value
    return ps


# ---------------------------------------------------------------------------
# resolve_zone_name
# ---------------------------------------------------------------------------

class TestResolveZoneName:
    """resolve_zone_name returns friendly_name, falls back to slug."""

    def test_returns_friendly_name_when_present(self):
        hass = _hass_with_zone("zone.main_house", "Main House")
        assert resolve_zone_name(hass, "zone.main_house") == "Main House"

    def test_falls_back_to_slug_when_no_friendly_name(self):
        hass = _hass_with_zone("zone.main_house", None)
        assert resolve_zone_name(hass, "zone.main_house") == "main_house"

    def test_falls_back_to_slug_when_state_missing(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        assert resolve_zone_name(hass, "zone.main_house") == "main_house"

    def test_strips_zone_prefix_on_fallback(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        assert resolve_zone_name(hass, "zone.work") == "work"


# ---------------------------------------------------------------------------
# evaluate_zone_rule
# ---------------------------------------------------------------------------

class TestEvaluateZoneRule:
    """evaluate_zone_rule compares against friendly_name, not slug."""

    def test_matches_on_friendly_name(self):
        """Zone with friendly_name "Main House" matches person.state
        "Main House" even though slug is "main_house"."""
        hass = _hass_with_zone("zone.main_house", "Main House")
        rule = {"type": "zone", "zone_id": "zone.main_house"}
        person_state = _person_state("Main House")

        is_met, reason = evaluate_zone_rule(hass, rule, person_state)
        assert is_met is True
        assert "Main House" in reason

    def test_does_not_match_on_slug_when_friendly_differs(self):
        """Regression: comparing against the slug 'main_house' must
        NOT be the path that produces the match — the fix uses the
        friendly_name."""
        hass = _hass_with_zone("zone.main_house", "Main House")
        rule = {"type": "zone", "zone_id": "zone.main_house"}
        # Person state is the slug — pre-fix code would have matched
        # this; post-fix it should not because friendly_name wins.
        person_state = _person_state("main_house")

        is_met, _reason = evaluate_zone_rule(hass, rule, person_state)
        assert is_met is False

    def test_no_zone_id_returns_unmet(self):
        hass = MagicMock()
        rule = {"type": "zone"}
        person_state = _person_state("home")
        is_met, reason = evaluate_zone_rule(hass, rule, person_state)
        assert is_met is False
        assert "No zone_id" in reason

    def test_fallback_slug_still_matches(self):
        """If the zone is deleted, fall back to slug comparison so
        legacy subscriptions still work."""
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        rule = {"type": "zone", "zone_id": "zone.home"}
        person_state = _person_state("home")

        is_met, _reason = evaluate_zone_rule(hass, rule, person_state)
        assert is_met is True
