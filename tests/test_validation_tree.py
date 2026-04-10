"""Tests for F-2b Condition Tree Validation.

Covers:
- validate_condition_tree with valid tree
- validate_condition_tree with invalid operator
- validate_condition_tree with depth > max
- validate_condition_tree with non-group root
- validate_condition_tree with missing type
- validate_condition_tree with unknown leaf type

Note on hass parameter (BUG-097 refactor):
    validate_condition_tree now accepts an optional ``hass`` parameter.
    When hass is None (the default, used here in structural tests),
    semantic entity/zone existence checks are skipped. Production
    callers (subscriptions.py, recipients.py) pass a real hass so
    state existence is enforced at runtime.

    The validator now returns ``(error_code, error_message)`` tuples
    instead of prefix-encoded strings. Tests unpack via the
    ``_err_message`` helper below when they need to assert on message
    content.
"""

from __future__ import annotations


from custom_components.ticker.websocket.validation import validate_condition_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group(operator: str, children: list) -> dict:
    return {"type": "group", "operator": operator, "children": children}


def _state_leaf(entity_id: str = "switch.a", state: str = "on") -> dict:
    return {"type": "state", "entity_id": entity_id, "state": state}


def _zone_leaf(zone_id: str = "zone.home") -> dict:
    return {"type": "zone", "zone_id": zone_id}


def _time_leaf(after: str = "08:00", before: str = "22:00") -> dict:
    return {"type": "time", "after": after, "before": before}


def _err_message(error) -> str:
    """Extract the message portion of a validator error tuple.

    The validator returns (error_code, error_message) or None.
    Tests that assert against message content use this to remain
    agnostic to the specific error_code.
    """
    assert error is not None
    assert isinstance(error, tuple) and len(error) == 2
    return error[1]


# ---------------------------------------------------------------------------
# Valid trees
# ---------------------------------------------------------------------------

class TestValidConditionTree:
    """Tests for valid condition trees that should pass validation."""

    def test_simple_and_group(self):
        """Simple AND group with leaf children."""
        tree = _group("AND", [_state_leaf(), _zone_leaf()])
        assert validate_condition_tree(tree) is None

    def test_simple_or_group(self):
        """Simple OR group with leaf children."""
        tree = _group("OR", [_state_leaf(), _time_leaf()])
        assert validate_condition_tree(tree) is None

    def test_nested_groups_within_depth(self):
        """Nested group at depth 1 (max is 2) is valid."""
        tree = _group("AND", [
            _state_leaf(),
            _group("OR", [_zone_leaf(), _time_leaf()]),
        ])
        assert validate_condition_tree(tree) is None

    def test_empty_children_valid(self):
        """Group with empty children list is structurally valid."""
        tree = _group("AND", [])
        assert validate_condition_tree(tree) is None

    def test_lowercase_operator_accepted(self):
        """Operator comparison is case-insensitive (uppercased internally)."""
        tree = _group("and", [_state_leaf()])
        assert validate_condition_tree(tree) is None

    def test_all_leaf_types(self):
        """All three leaf types (zone, time, state) are accepted."""
        tree = _group("AND", [_zone_leaf(), _time_leaf(), _state_leaf()])
        assert validate_condition_tree(tree) is None


# ---------------------------------------------------------------------------
# Invalid operator
# ---------------------------------------------------------------------------

class TestInvalidOperator:
    """Tests for invalid group operators."""

    def test_xor_operator_rejected(self):
        """XOR is not a valid operator."""
        tree = _group("XOR", [_state_leaf()])
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "operator" in msg.lower() or "XOR" in msg

    def test_empty_operator_rejected(self):
        """Empty string operator is rejected."""
        tree = {"type": "group", "operator": "", "children": []}
        error = validate_condition_tree(tree)
        assert error is not None

    def test_not_operator_rejected(self):
        """NOT is not a valid operator."""
        tree = _group("NOT", [_state_leaf()])
        error = validate_condition_tree(tree)
        assert error is not None


# ---------------------------------------------------------------------------
# Depth exceeded
# ---------------------------------------------------------------------------

class TestDepthExceeded:
    """Tests for trees that exceed CONDITION_MAX_DEPTH (2)."""

    def test_depth_3_rejected(self):
        """Three levels of nesting exceeds max depth of 2."""
        # depth 0 -> depth 1 -> depth 2 -> depth 3 (exceeds)
        tree = _group("AND", [
            _group("OR", [
                _group("AND", [_state_leaf()]),
            ]),
        ])
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "depth" in msg.lower()

    def test_depth_2_accepted(self):
        """Two levels of nesting is within max depth."""
        tree = _group("AND", [
            _group("OR", [_state_leaf()]),
        ])
        assert validate_condition_tree(tree) is None


# ---------------------------------------------------------------------------
# Non-group root / missing type / unknown type
# ---------------------------------------------------------------------------

class TestInvalidNodeTypes:
    """Tests for invalid node types and structures."""

    def test_leaf_as_root_accepted(self):
        """A leaf node at root is valid (it is a known rule type)."""
        tree = _state_leaf()
        assert validate_condition_tree(tree) is None

    def test_unknown_type_rejected(self):
        """Unknown node type is rejected."""
        tree = {"type": "foobar"}
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "foobar" in msg

    def test_missing_type_rejected(self):
        """Node without type key is rejected."""
        tree = {"operator": "AND", "children": []}
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "type" in msg.lower()

    def test_non_dict_rejected(self):
        """Non-dict node is rejected."""
        error = validate_condition_tree("not a dict")
        msg = _err_message(error)
        assert "dict" in msg.lower()

    def test_children_not_list_rejected(self):
        """Group node where children is not a list is rejected."""
        tree = {"type": "group", "operator": "AND", "children": "not-a-list"}
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "list" in msg.lower()

    def test_invalid_child_propagates_error(self):
        """Error in a child node is returned with index prefix."""
        tree = _group("AND", [
            _state_leaf(),
            {"type": "unknown_leaf"},
        ])
        error = validate_condition_tree(tree)
        msg = _err_message(error)
        assert "children[1]" in msg
