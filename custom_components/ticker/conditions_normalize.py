"""Condition-tree shape normalizers shared across stores.

Houses small, store-agnostic helpers that mutate a condition tree into its
canonical persistence shape. Currently the only operation is the F-33
sparse-storage normalization for the ``negate`` flag: an explicit
``negate: false`` key is stripped before persistence so the wire shape
stays clean and matches the "missing reads as false" rule used at every
read site.

This module is the single source of truth for the strip behaviour;
``store/categories.py`` and ``store/subscriptions.py`` both import from
here so any future refinement (e.g. additional sparse fields) happens in
one place. It lives at the integration root (next to ``conditions.py`` and
``conditions_legacy.py``) rather than under ``store/`` because the tree
shape is owned by the conditions evaluator, not by any one store.
"""

from __future__ import annotations

from typing import Any


def strip_negate_false_from_node(node: Any) -> None:
    """Recursively strip ``negate: false`` from a condition-tree node (F-33).

    The frontend always sends explicit ``negate: false`` for cleanliness,
    but storage is sparse: an absent key reads as ``False``. This mirrors
    the sparse-storage pattern already used for ``critical`` (decision 26)
    and ``expose_in_sensor`` (decision 31). ``negate: true`` is preserved.

    Mutates in place. Non-dict values (including the empty dict) and
    malformed ``children`` lists are ignored — the WebSocket validator
    rejects malformed shapes before reaching this point, and any odd-shaped
    legacy data is left untouched so this helper cannot cause data loss.
    """
    if not isinstance(node, dict):
        return
    if node.get("negate") is False:
        node.pop("negate", None)
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            strip_negate_false_from_node(child)


def normalize_conditions_negate(
    conditions: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize ``negate: false`` to sparse inside a conditions dict.

    Walks the optional ``condition_tree`` inside the ``conditions`` dict
    (the shape used by both ``category.default_conditions`` and
    ``subscription.conditions``) and strips ``negate: false`` keys from
    every node. The original dict is returned (mutated) when present;
    ``None`` passes through unchanged.
    """
    if not conditions:
        return conditions
    tree = conditions.get("condition_tree")
    if isinstance(tree, dict):
        strip_negate_false_from_node(tree)
    return conditions
