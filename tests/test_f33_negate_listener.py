"""F-33 listener + supplemental regression tests.

Split out from ``tests/test_condition_listeners.py`` to keep that file
under the 500-line limit after the F-33 addition. Houses:

* The listener re-evaluation regression — the listener's re-evaluation
  pathway must honour the ``negate`` flag on leaves (and groups) without
  any extra code in the listener itself, because the rolled-up boolean
  returned by ``evaluate_condition_tree`` is already negate-applied
  (spec §4.5 / §5).
* Trigger-collection coverage from spec §4.6 — a negated leaf must still
  contribute its zone / entity / time-window trigger so the listener can
  fire and re-evaluate when the underlying state changes. The negation
  only flips the evaluator output, not the listener registration.
* Direct unit tests for the sparse-storage helper
  ``conditions_normalize.strip_negate_false_from_node`` /
  ``normalize_conditions_negate`` — these run transitively through the
  store tests but lack focused coverage of the documented edge cases
  (non-dict no-op, idempotency, deeply nested children, malformed
  ``children``, ``negate: true`` preservation).
* Validator reject-matrix fill-in for list/dict shapes that
  ``tests/test_f33_negate.py`` doesn't exercise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.condition_listeners import (
    ConditionListenerManager,
)
from custom_components.ticker.conditions import get_queue_triggers
from custom_components.ticker.conditions_normalize import (
    normalize_conditions_negate,
    strip_negate_false_from_node,
)
from custom_components.ticker.websocket.validation import (
    validate_condition_tree,
)


# ---------------------------------------------------------------------------
# Local fixtures — kept minimal and standalone so this file can run in
# isolation. Mirrors the shapes used by tests/test_condition_listeners.py
# but only includes what the F-33 regression below actually needs.
# ---------------------------------------------------------------------------


def _make_hass(
    is_running: bool,
    states: dict[str, MagicMock] | None = None,
) -> MagicMock:
    """Build a mock hass with ``is_running`` and ``states.get`` wired."""
    hass = MagicMock()
    hass.is_running = is_running

    states = states or {}

    def _get(entity_id: str):
        return states.get(entity_id)

    hass.states.get = _get
    return hass


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


def _queued_entry(queue_id: str, category_id: str) -> dict:
    return {
        "queue_id": queue_id,
        "category_id": category_id,
        "title": "T",
        "message": "M",
    }


# ---------------------------------------------------------------------------
# F-33: NOT operator regression — listener honours negate at re-evaluation
# ---------------------------------------------------------------------------


class TestF33NegatedConditionReevaluation:
    """The listener's re-evaluation path must inherit the negate semantics.

    Per spec §4.5 / §5, the rolled-up boolean returned by
    ``evaluate_condition_tree`` is already negate-applied. The listener
    consumes only that boolean, so a queued entry under a negated state
    rule should:
      - stay queued while the entity matches the (raw) state being negated
      - release when the entity flips to a state that satisfies the
        negated rule.
    """

    @pytest.mark.asyncio
    async def test_listener_reevaluates_negated_state_rule(self):
        """NOT (binary_sensor.tv = off) releases the queue when TV is on.

        This test uses the REAL evaluate_condition_tree (no patch) so the
        F-33 wrapper is exercised end-to-end through the listener's
        re-evaluation pathway.
        """
        # Build a hass with TV currently 'on'. The negated state rule
        # "NOT (binary_sensor.tv == off)" therefore resolves True.
        tv_on = MagicMock()
        tv_on.state = "on"

        # Recipient subscription used so we bypass person_state lookup
        # and the disabled-user gate — both orthogonal to F-33.
        hass = _make_hass(is_running=False, states={"binary_sensor.tv": tv_on})

        # Build a conditional sub with a condition_tree carrying negate=true
        # on the leaf. (The legacy "rules" list is empty so the tree is
        # the sole source of truth.)
        sub = {
            "person_id": "recipient:phone1",
            "category_id": "cat1",
            "mode": "conditional",
            "conditions": {
                "condition_tree": {
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "state",
                            "entity_id": "binary_sensor.tv",
                            "state": "off",
                            "negate": True,
                        },
                    ],
                },
                "queue_until_met": True,
            },
        }
        store = _make_store(
            subscriptions={"recipient:phone1:cat1": sub},
            queue=[_queued_entry("q1", "cat1")],
            user_enabled=True,
        )

        callback = AsyncMock()
        mgr = ConditionListenerManager(hass, store, on_conditions_met=callback)

        # Cold-boot sweep exercises the real evaluator. TV is on, the
        # negated rule "TV != off" resolves True, so the callback fires.
        await mgr.async_sweep_for_startup()

        callback.assert_awaited_once_with("recipient:phone1", "cat1")


# ---------------------------------------------------------------------------
# Spec §4.6 — get_queue_triggers / _collect_triggers_from_node must include
# triggers from negated leaves. A negated leaf still needs its listener so
# the queue can re-evaluate when the underlying state changes; negation only
# flips the evaluator output, not whether the listener fires.
# ---------------------------------------------------------------------------


def _conds_tree(tree: dict) -> dict:
    """Wrap a condition_tree with queue_until_met enabled (required for
    ``get_queue_triggers`` to collect anything)."""
    return {"condition_tree": tree, "queue_until_met": True}


class TestNegatedLeavesContributeTriggers:
    """Spec §4.6: negate is irrelevant to trigger collection."""

    def test_state_entity_collected_when_leaf_is_negated(self):
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "state",
                    "entity_id": "binary_sensor.tv",
                    "state": "off",
                    "negate": True,
                },
            ],
        }
        triggers = get_queue_triggers(_conds_tree(tree))
        assert "binary_sensor.tv" in triggers["entities"]

    def test_zone_collected_when_leaf_is_negated(self):
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {"type": "zone", "zone_id": "zone.home", "negate": True},
            ],
        }
        triggers = get_queue_triggers(_conds_tree(tree))
        assert "zone.home" in triggers["zones"]

    def test_time_window_collected_when_leaf_is_negated(self):
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "time",
                    "after": "08:00",
                    "before": "22:00",
                    "negate": True,
                },
            ],
        }
        triggers = get_queue_triggers(_conds_tree(tree))
        assert any(
            tw.get("after") == "08:00" and tw.get("before") == "22:00"
            for tw in triggers["time_windows"]
        )

    def test_triggers_collected_from_negated_group_children(self):
        """Group ``negate=True`` does not suppress trigger collection on its
        children. The group wrapper only flips the AND/OR result at eval
        time — listeners must still cover every leaf inside it.
        """
        tree = {
            "type": "group",
            "operator": "AND",
            "negate": True,
            "children": [
                {
                    "type": "state",
                    "entity_id": "binary_sensor.tv",
                    "state": "off",
                },
                {"type": "zone", "zone_id": "zone.home"},
            ],
        }
        triggers = get_queue_triggers(_conds_tree(tree))
        assert "binary_sensor.tv" in triggers["entities"]
        assert "zone.home" in triggers["zones"]

    def test_triggers_identical_for_negated_and_positive_leaves(self):
        """Sanity check: trigger lists are byte-for-byte identical whether
        the leaves are negated or not. Confirms the negate flag is invisible
        to ``_collect_triggers_from_node``.
        """
        positive_tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "state",
                    "entity_id": "binary_sensor.tv",
                    "state": "off",
                },
                {"type": "zone", "zone_id": "zone.home"},
            ],
        }
        negated_tree = {
            "type": "group",
            "operator": "AND",
            "negate": True,
            "children": [
                {
                    "type": "state",
                    "entity_id": "binary_sensor.tv",
                    "state": "off",
                    "negate": True,
                },
                {
                    "type": "zone",
                    "zone_id": "zone.home",
                    "negate": True,
                },
            ],
        }
        pos = get_queue_triggers(_conds_tree(positive_tree))
        neg = get_queue_triggers(_conds_tree(negated_tree))
        assert sorted(pos["entities"]) == sorted(neg["entities"])
        assert sorted(pos["zones"]) == sorted(neg["zones"])


# ---------------------------------------------------------------------------
# conditions_normalize unit tests — direct coverage of the sparse-storage
# helper. The store tests exercise it transitively, but its documented
# edge cases (non-dict, malformed children, idempotency) deserve focused
# assertions.
# ---------------------------------------------------------------------------


class TestStripNegateFalseHelper:

    def test_non_dict_input_is_no_op(self):
        # Should not raise on None, int, list, str.
        for value in (None, 1, "x", [1, 2, 3]):
            strip_negate_false_from_node(value)  # type: ignore[arg-type]

    def test_empty_dict_is_left_unchanged(self):
        node: dict = {}
        strip_negate_false_from_node(node)
        assert node == {}

    def test_negate_false_stripped_on_leaf(self):
        node = {"type": "state", "entity_id": "x", "negate": False}
        strip_negate_false_from_node(node)
        assert "negate" not in node

    def test_negate_true_preserved_on_leaf(self):
        node = {"type": "state", "entity_id": "x", "negate": True}
        strip_negate_false_from_node(node)
        assert node["negate"] is True

    def test_recurses_into_children_and_strips_at_every_level(self):
        node = {
            "type": "group",
            "operator": "AND",
            "negate": False,
            "children": [
                {
                    "type": "group",
                    "operator": "OR",
                    "negate": False,
                    "children": [
                        {"type": "state", "entity_id": "a", "negate": False},
                        {"type": "state", "entity_id": "b", "negate": True},
                    ],
                },
                {"type": "zone", "zone_id": "zone.home", "negate": False},
            ],
        }
        strip_negate_false_from_node(node)
        assert "negate" not in node
        inner = node["children"][0]
        assert "negate" not in inner
        assert "negate" not in inner["children"][0]
        assert inner["children"][1]["negate"] is True
        assert "negate" not in node["children"][1]

    def test_malformed_children_list_does_not_raise(self):
        # Validator rejects this before persistence, but the helper must
        # remain robust per its docstring contract.
        node = {"type": "group", "negate": False, "children": "oops"}
        strip_negate_false_from_node(node)
        assert "negate" not in node
        # Did not crash on the non-list `children`.

    def test_idempotent(self):
        node = {
            "type": "group",
            "negate": True,
            "children": [
                {"type": "state", "entity_id": "x", "negate": True},
            ],
        }
        strip_negate_false_from_node(node)
        first_pass = {**node, "children": [dict(c) for c in node["children"]]}
        strip_negate_false_from_node(node)
        assert node["negate"] is True
        assert node["children"][0]["negate"] is True
        assert node == first_pass


class TestNormalizeConditionsNegate:

    def test_none_passes_through(self):
        assert normalize_conditions_negate(None) is None

    def test_empty_conditions_pass_through(self):
        assert normalize_conditions_negate({}) == {}

    def test_conditions_without_tree_pass_through(self):
        conds = {"deliver_when_met": True, "rules": []}
        out = normalize_conditions_negate(conds)
        assert out == {"deliver_when_met": True, "rules": []}

    def test_strips_negate_false_from_nested_tree(self):
        conds = {
            "condition_tree": {
                "type": "group",
                "operator": "AND",
                "negate": False,
                "children": [
                    {"type": "state", "entity_id": "x", "negate": False},
                    {"type": "state", "entity_id": "y", "negate": True},
                ],
            },
            "deliver_when_met": True,
        }
        out = normalize_conditions_negate(conds)
        tree = out["condition_tree"]
        assert "negate" not in tree
        assert "negate" not in tree["children"][0]
        assert tree["children"][1]["negate"] is True


# ---------------------------------------------------------------------------
# Validator reject-matrix fill-in. tests/test_f33_negate.py covers str/int/
# None; this fills the remaining shapes (list, dict) called out in the
# audit prompt to lock the contract end-to-end.
# ---------------------------------------------------------------------------


class TestValidatorRejectMatrixExtras:

    @pytest.mark.parametrize(
        "bad_value",
        [[], [True], {}, {"x": 1}, 0.5],
    )
    def test_rejects_non_bool_negate_for_remaining_shapes(self, bad_value):
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {"type": "state", "entity_id": "x", "state": "on"},
            ],
            "negate": bad_value,
        }
        err = validate_condition_tree(tree)
        assert err is not None, f"expected rejection for {bad_value!r}"
        code, msg = err
        assert code == "invalid_tree"
        assert "negate" in msg.lower() or "boolean" in msg.lower()

    def test_rejects_non_bool_negate_on_leaf(self):
        # Mirrors the group test but locks down the leaf entry-point.
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "state",
                    "entity_id": "x",
                    "state": "on",
                    "negate": ["not-a-bool"],
                },
            ],
        }
        err = validate_condition_tree(tree)
        assert err is not None
        code, msg = err
        assert code == "invalid_tree"
        assert "negate" in msg.lower() or "boolean" in msg.lower()
