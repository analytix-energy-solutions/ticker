"""Tests for F-33 NOT operator (negate flag) on condition tree nodes.

Covers, per docs/SPEC_F-33_v1.7.0.md §11.2:
- Group A: implicit vs explicit negate=false (missing-reads-as-false).
- Group B: single negated leaf per type (zone, state, time).
- Group C: negated groups (leaf x group composition).
- Group D: nested groups, mixed-depth (double negation identity, 3-level).
- Group E: WebSocket validator round-trip.
- Group F: round-trip through the categories store (sparse normalization).
- Listener regression test lives in tests/test_condition_listeners.py.

Local helpers re-implemented (not imported from test_conditions_tree.py) to
keep this file independently loadable. Existing fixtures elsewhere stay
literally untouched per spec §11.1.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.conditions import (
    _apply_negate,
    evaluate_condition_tree,
    evaluate_group,
    should_deliver_now,
)
from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.websocket.validation import (
    validate_condition_tree,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hass_states(states: dict[str, str]) -> MagicMock:
    hass = MagicMock()

    def _get(entity_id: str):
        if entity_id in states:
            s = MagicMock()
            s.state = states[entity_id]
            return s
        return None

    hass.states.get = _get
    return hass


def _hass_zone(
    zone_id: str,
    persons: list[str],
    extra: dict[str, str] | None = None,
) -> MagicMock:
    hass = MagicMock()
    extras = extra or {}

    def _get(entity_id: str):
        if entity_id == zone_id:
            z = MagicMock()
            z.attributes = {"friendly_name": "Home", "persons": list(persons)}
            return z
        if entity_id in extras:
            s = MagicMock()
            s.state = extras[entity_id]
            return s
        return None

    hass.states.get = _get
    return hass


def _person(eid: str) -> MagicMock:
    p = MagicMock()
    p.entity_id = eid
    return p


def _zone(zone_id: str) -> dict:
    return {"type": "zone", "zone_id": zone_id}


def _state(entity_id: str, state: str) -> dict:
    return {"type": "state", "entity_id": entity_id, "state": state}


def _time(after: str, before: str) -> dict:
    return {"type": "time", "after": after, "before": before}


def _grp(op: str, children: list, negate: bool | None = None) -> dict:
    g: dict = {"type": "group", "operator": op, "children": children}
    if negate is not None:
        g["negate"] = negate
    return g


def _neg(node: dict, value: bool = True) -> dict:
    node["negate"] = bool(value)
    return node


class _FakeCategoryStore(CategoryMixin):
    """Concrete CategoryMixin subclass for unit-testing storage paths."""

    def __init__(self) -> None:
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


# ===========================================================================
# Group A — implicit vs explicit negate=false (missing-reads-as-false rule)
# ===========================================================================

class TestImplicitVsExplicitNegateFalse:
    """Absent ``negate`` key MUST behave identically to ``negate=false``."""

    def test_leaf_missing_negate_equals_explicit_false(self):
        hass = _hass_states({"switch.a": "on"})
        implicit = _grp("AND", [_state("switch.a", "on")])
        explicit = _grp("AND", [_neg(_state("switch.a", "on"), False)])
        r1, _ = evaluate_group(hass, implicit, None)
        r2, _ = evaluate_group(hass, explicit, None)
        assert r1 is True and r2 is True

    def test_group_missing_negate_equals_explicit_false(self):
        hass = _hass_states({"switch.a": "on"})
        implicit = _grp("AND", [_state("switch.a", "on")])
        explicit = _grp("AND", [_state("switch.a", "on")], negate=False)
        r1, _ = evaluate_group(hass, implicit, None)
        r2, _ = evaluate_group(hass, explicit, None)
        assert r1 is True and r2 is True

    def test_explicit_negate_false_round_trips_via_should_deliver_now(self):
        hass = _hass_states({"switch.a": "on"})
        implicit = {
            "condition_tree": _grp("AND", [_state("switch.a", "on")]),
            "deliver_when_met": True,
        }
        explicit = {
            "condition_tree": _grp(
                "AND",
                [_neg(_state("switch.a", "on"), False)],
                negate=False,
            ),
            "deliver_when_met": True,
        }
        r1, _ = should_deliver_now(hass, implicit, None)
        r2, _ = should_deliver_now(hass, explicit, None)
        assert r1 is True and r2 is True

    def test_apply_negate_helper_no_key_is_passthrough(self):
        is_met, reason = _apply_negate({"type": "state"}, True, "ok")
        assert (is_met, reason) == (True, "ok")
        is_met2, reason2 = _apply_negate(
            {"type": "state", "negate": False}, True, "ok",
        )
        assert (is_met2, reason2) == (True, "ok")


# ===========================================================================
# Group B — single negated leaf per type
# ===========================================================================

class TestSingleNegatedLeaf:
    """Negation of each leaf type inverts the leaf's raw boolean."""

    def test_negated_zone_leaf_when_inside_zone_is_false(self):
        hass = _hass_zone("zone.home", persons=["person.alice"])
        tree = _grp("AND", [_neg(_zone("zone.home"))])
        result, details = evaluate_group(hass, tree, _person("person.alice"))
        assert result is False
        assert "NOT" in details[0][1]

    def test_negated_zone_leaf_when_outside_zone_is_true(self):
        hass = _hass_zone("zone.home", persons=[])
        tree = _grp("AND", [_neg(_zone("zone.home"))])
        result, _ = evaluate_group(hass, tree, _person("person.alice"))
        assert result is True

    def test_negated_state_leaf_when_state_differs_is_true(self):
        # TV is on; NOT (TV == off) => True
        hass = _hass_states({"binary_sensor.tv": "on"})
        tree = _grp("AND", [_neg(_state("binary_sensor.tv", "off"))])
        result, _ = evaluate_group(hass, tree, None)
        assert result is True

    def test_negated_state_leaf_when_state_matches_is_false(self):
        # TV is on; NOT (TV == on) => False
        hass = _hass_states({"binary_sensor.tv": "on"})
        tree = _grp("AND", [_neg(_state("binary_sensor.tv", "on"))])
        result, _ = evaluate_group(hass, tree, None)
        assert result is False

    def test_negated_time_leaf_inside_window_is_false(self):
        # 12:00 inside 08:00-22:00; NOT(in window) => False
        hass = MagicMock()
        tree = _grp("AND", [_neg(_time("08:00", "22:00"))])
        result, _ = evaluate_group(
            hass, tree, None, now=datetime(2026, 5, 11, 12, 0, 0),
        )
        assert result is False

    def test_negated_time_leaf_outside_window_is_true(self):
        # 23:00 outside 08:00-22:00; NOT(out of window) => True
        hass = MagicMock()
        tree = _grp("AND", [_neg(_time("08:00", "22:00"))])
        result, _ = evaluate_group(
            hass, tree, None, now=datetime(2026, 5, 11, 23, 0, 0),
        )
        assert result is True


# ===========================================================================
# Group C — negated groups (leaf x group composition)
# ===========================================================================

class TestNegatedGroups:
    """Group-level negate applies AFTER the AND/OR fold."""

    def test_negated_and_group_with_negated_child(self):
        """NOT (zone IN home AND NOT state(TV==off)) — alice home, TV on."""
        # leaf 1: in zone -> True; leaf 2: NOT (TV==off) where TV=on -> True
        # AND fold: True; group NOT: False.
        hass = _hass_zone(
            "zone.home", persons=["person.alice"],
            extra={"binary_sensor.tv": "on"},
        )
        tree = _grp(
            "AND",
            [_zone("zone.home"), _neg(_state("binary_sensor.tv", "off"))],
            negate=True,
        )
        result, _ = evaluate_group(hass, tree, _person("person.alice"))
        assert result is False

    def test_negated_or_group_with_mixed_negation(self):
        """NOT (NOT zone(home) OR state(TV==off)) — alice OUT, TV on."""
        # leaf 1: NOT (not in zone) -> NOT False -> True
        # leaf 2: TV == off -> False
        # OR fold: True; group NOT: False.
        hass = _hass_zone(
            "zone.home", persons=[],
            extra={"binary_sensor.tv": "on"},
        )
        tree = _grp(
            "OR",
            [_neg(_zone("zone.home")), _state("binary_sensor.tv", "off")],
            negate=True,
        )
        result, _ = evaluate_group(hass, tree, _person("person.alice"))
        assert result is False


# ===========================================================================
# Group D — nested groups, mixed depth (composition / identity)
# ===========================================================================

class TestNestedMixedNegation:
    """Composition: NOT-group(NOT-leaf) === group(positive-leaf)."""

    def test_double_negation_is_identity_inside_zone(self):
        hass = _hass_zone("zone.home", persons=["person.alice"])
        positive = _grp("AND", [_zone("zone.home")])
        double_neg = _grp("AND", [_neg(_zone("zone.home"))], negate=True)
        r1, _ = evaluate_group(hass, positive, _person("person.alice"))
        r2, _ = evaluate_group(hass, double_neg, _person("person.alice"))
        assert r1 == r2 == True  # noqa: E712

    def test_double_negation_is_identity_outside_zone(self):
        hass = _hass_zone("zone.home", persons=[])
        positive = _grp("AND", [_zone("zone.home")])
        double_neg = _grp("AND", [_neg(_zone("zone.home"))], negate=True)
        r1, _ = evaluate_group(hass, positive, _person("person.alice"))
        r2, _ = evaluate_group(hass, double_neg, _person("person.alice"))
        assert r1 == r2 == False  # noqa: E712

    def test_three_level_nested_mixed_negation(self):
        """NOT-AND(OR(A=on, B=on), NOT state(C=on)) across two state sets."""
        tree = _grp(
            "AND",
            [
                _grp("OR", [
                    _state("switch.a", "on"),
                    _state("switch.b", "on"),
                ]),
                _neg(_state("switch.c", "on")),
            ],
            negate=True,
        )
        # State 1: A=off, B=on, C=off
        #   OR: F or T = T; NOT C(on)=NOT F=T; AND: T; root NOT: F.
        hass1 = _hass_states({
            "switch.a": "off", "switch.b": "on", "switch.c": "off",
        })
        r1, _ = evaluate_group(hass1, tree, None)
        assert r1 is False
        # State 2: A=off, B=off, C=on
        #   OR: F; NOT C(on)=NOT T=F; AND: F and F = F; root NOT: T.
        hass2 = _hass_states({
            "switch.a": "off", "switch.b": "off", "switch.c": "on",
        })
        r2, _ = evaluate_group(hass2, tree, None)
        assert r2 is True

    def test_empty_negated_group_is_false(self):
        """An empty group inverts True -> False per spec §4.3."""
        hass = MagicMock()
        result, details = evaluate_group(
            hass, _grp("AND", [], negate=True), None,
        )
        assert result is False
        assert details[0][0] is False


# ===========================================================================
# Group E — WebSocket validator round-trip
# ===========================================================================

class TestValidatorNegate:
    """validate_condition_tree accepts bool negate, rejects non-bool."""

    def test_accepts_negate_true_on_leaf(self):
        tree = _grp("AND", [_neg(_state("switch.a", "on"))])
        assert validate_condition_tree(tree) is None

    def test_accepts_negate_true_on_group(self):
        tree = _grp("AND", [_state("switch.a", "on")], negate=True)
        assert validate_condition_tree(tree) is None

    def test_accepts_explicit_negate_false(self):
        tree = _grp(
            "AND",
            [_neg(_state("switch.a", "on"), False)],
            negate=False,
        )
        assert validate_condition_tree(tree) is None

    def test_accepts_negate_absent(self):
        tree = _grp("AND", [_state("switch.a", "on")])
        assert validate_condition_tree(tree) is None

    def test_rejects_non_bool_negate(self):
        # String, int, and None — none are bool.
        for bad_value in ("true", 1, None):
            tree = _grp("AND", [_state("switch.a", "on")])
            tree["negate"] = bad_value
            err = validate_condition_tree(tree)
            assert err is not None, f"expected rejection for {bad_value!r}"
            code, msg = err
            assert code == "invalid_tree"
            assert "negate" in msg.lower() or "boolean" in msg.lower()


# ===========================================================================
# Group F — Round-trip through the categories store (sparse normalization)
# ===========================================================================

class TestStoreSparseNormalization:
    """``negate: false`` is stripped before persistence; ``negate: true`` kept."""

    @pytest.mark.asyncio
    async def test_create_strips_negate_false(self):
        store = _FakeCategoryStore()
        conds = {
            "condition_tree": _grp(
                "AND",
                [
                    _neg(_state("switch.a", "on"), False),
                    _neg(_state("switch.b", "off"), True),
                ],
                negate=False,
            ),
            "deliver_when_met": True,
        }
        await store.async_create_category(
            "alerts", "Alerts", default_conditions=conds,
        )
        tree = store._categories["alerts"]["default_conditions"]["condition_tree"]
        assert "negate" not in tree                     # group false stripped
        assert "negate" not in tree["children"][0]      # leaf false stripped
        assert tree["children"][1]["negate"] is True    # leaf true preserved

    @pytest.mark.asyncio
    async def test_update_strips_negate_false(self):
        store = _FakeCategoryStore()
        await store.async_create_category("alerts", "Alerts")
        conds = {
            "condition_tree": _grp(
                "OR",
                [
                    _neg(_zone("zone.home"), True),
                    _neg(_state("switch.c", "on"), False),
                ],
                negate=False,
            ),
            "deliver_when_met": True,
        }
        await store.async_update_category(
            "alerts", default_conditions=conds,
        )
        tree = store._categories["alerts"]["default_conditions"]["condition_tree"]
        assert "negate" not in tree
        assert tree["children"][0]["negate"] is True
        assert "negate" not in tree["children"][1]

    @pytest.mark.asyncio
    async def test_round_trip_evaluation_unchanged_after_strip(self):
        """Pre- and post-strip trees evaluate identically (missing == false)."""
        store = _FakeCategoryStore()
        conds = {
            "condition_tree": _grp(
                "AND",
                [
                    _neg(_state("switch.a", "on"), False),
                    _neg(_state("switch.b", "off"), True),
                ],
                negate=False,
            ),
            "deliver_when_met": True,
        }
        hass = _hass_states({"switch.a": "on", "switch.b": "on"})
        pre, _ = evaluate_condition_tree(hass, conds, None)
        await store.async_create_category(
            "alerts", "Alerts", default_conditions=conds,
        )
        stored = store._categories["alerts"]["default_conditions"]
        post, _ = evaluate_condition_tree(hass, stored, None)
        assert pre is True and post is True

    @pytest.mark.asyncio
    async def test_strip_recurses_into_nested_groups(self):
        store = _FakeCategoryStore()
        conds = {
            "condition_tree": _grp(
                "AND",
                [
                    _grp(
                        "OR",
                        [_neg(_state("switch.a", "on"), False)],
                        negate=False,
                    ),
                    _neg(_state("switch.b", "off"), True),
                ],
                negate=False,
            ),
        }
        await store.async_create_category(
            "alerts", "Alerts", default_conditions=conds,
        )
        tree = store._categories["alerts"]["default_conditions"]["condition_tree"]
        assert "negate" not in tree
        inner = tree["children"][0]
        assert "negate" not in inner
        assert "negate" not in inner["children"][0]
        assert tree["children"][1]["negate"] is True
