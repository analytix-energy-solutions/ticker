"""F-33 WebSocket round-trip integration tests (spec §11.3).

Exercises the full WS-handler path for category and subscription writes
that carry ``negate`` flags on condition-tree nodes. The store layer is
not mocked: a real :class:`CategoryMixin` / :class:`SubscriptionMixin`
instance is wired up so the sparse-storage normalization actually runs
and the persisted shape can be inspected.

The Ticker WS test pattern (see ``tests/test_f35_chime_websocket.py``)
uses a MagicMock connection plus targeted patches around discovery and
``get_store``; that same pattern is applied here so no new test harness
is introduced.

Coverage:

1. ``ticker/category/create`` with a negated tree round-trips to the
   stored shape with ``negate: true`` preserved and ``negate: false``
   stripped (sparse).
2. ``ticker/category/update`` rewrites the stored tree with the same
   normalization rules.
3. ``ticker/subscription/set`` with a negated tree persists the same
   normalized shape on the subscription record.
4. The WS validator rejects a non-bool ``negate`` field on a condition
   tree at the handler boundary (confirms the validator is wired in,
   not bypassed). Mirrors the unit-level coverage in
   ``tests/test_f33_negate.py`` but at handler integration level.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.store.subscriptions import SubscriptionMixin
from custom_components.ticker.websocket.categories import (
    ws_create_category,
    ws_update_category,
)
from custom_components.ticker.websocket.subscriptions import (
    ws_set_subscription,
)


# ---------------------------------------------------------------------------
# Real-mixin store harness (no MagicMock for the data path so the strip
# normalization actually runs).
# ---------------------------------------------------------------------------


class _RealStore(CategoryMixin, SubscriptionMixin):
    """Concrete CategoryMixin + SubscriptionMixin used for round-trip tests.

    Persistence is mocked at the HA-Store layer (``async_save`` is an
    AsyncMock) but every other code path — including
    :func:`normalize_conditions_negate` — runs unchanged.
    """

    def __init__(self) -> None:
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._subscriptions_store = MagicMock()
        self._subscriptions_store.async_save = AsyncMock()
        self._category_listeners: list = []
        self._subscription_listeners: list = []


def _make_hass_with_state(entity_id: str, state_value: str) -> MagicMock:
    """Hass that returns a state for one specific entity_id (used by
    state-leaf existence validation in the WS path)."""
    hass = MagicMock()

    def _get(eid: str):
        if eid == entity_id:
            s = MagicMock()
            s.state = state_value
            return s
        return None

    hass.states.get = _get
    hass.config_entries.async_entries.return_value = []
    return hass


def _make_conn() -> MagicMock:
    conn = MagicMock()
    conn.user = None  # set_by branch uses default
    return conn


def _state_leaf(entity_id: str, state: str, negate: bool | None = None) -> dict:
    leaf = {"type": "state", "entity_id": entity_id, "state": state}
    if negate is not None:
        leaf["negate"] = negate
    return leaf


def _group(operator: str, children: list, negate: bool | None = None) -> dict:
    g: dict = {"type": "group", "operator": operator, "children": children}
    if negate is not None:
        g["negate"] = negate
    return g


# ---------------------------------------------------------------------------
# 1. Category create — negated tree round-trip
# ---------------------------------------------------------------------------


class TestCategoryCreateNegateRoundTrip:

    @pytest.mark.asyncio
    async def test_create_preserves_negate_true_and_strips_false(self):
        store = _RealStore()
        hass = _make_hass_with_state("binary_sensor.tv", "on")
        conn = _make_conn()

        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "alerts",
            "name": "Alerts",
            "default_mode": "conditional",
            "default_conditions": {
                "condition_tree": _group(
                    "AND",
                    [
                        _state_leaf("binary_sensor.tv", "off", negate=True),
                        _state_leaf("binary_sensor.tv", "on", negate=False),
                    ],
                    negate=False,
                ),
                "deliver_when_met": True,
            },
        }

        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_create_category(hass, conn, msg)

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

        # Read the stored shape back via the same store API used by
        # ws_get_categories. negate=true preserved on the leaf, negate=false
        # stripped from group and the second leaf.
        cat = store.get_category("alerts")
        assert cat is not None
        tree = cat["default_conditions"]["condition_tree"]
        assert "negate" not in tree  # group false stripped
        assert tree["children"][0]["negate"] is True
        assert "negate" not in tree["children"][1]


# ---------------------------------------------------------------------------
# 2. Category update — negated tree rewrite
# ---------------------------------------------------------------------------


class TestCategoryUpdateNegateRoundTrip:

    @pytest.mark.asyncio
    async def test_update_rewrites_tree_with_same_normalization(self):
        store = _RealStore()
        hass = _make_hass_with_state("binary_sensor.tv", "on")
        conn = _make_conn()

        # Seed an existing category through the same WS create path.
        await store.async_create_category("alerts", "Alerts")

        update_msg = {
            "id": 2,
            "type": "ticker/category/update",
            "category_id": "alerts",
            "default_mode": "conditional",
            "default_conditions": {
                "condition_tree": _group(
                    "OR",
                    [
                        _state_leaf("binary_sensor.tv", "on", negate=False),
                        _state_leaf("binary_sensor.tv", "off", negate=True),
                    ],
                    negate=True,
                ),
                "deliver_when_met": True,
            },
        }

        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_update_category(hass, conn, update_msg)

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

        tree = store.get_category("alerts")["default_conditions"][
            "condition_tree"
        ]
        # Group negate=true is preserved (only `false` is stripped).
        assert tree["negate"] is True
        assert "negate" not in tree["children"][0]  # false stripped
        assert tree["children"][1]["negate"] is True


# ---------------------------------------------------------------------------
# 3. Subscription set — negated tree round-trip
# ---------------------------------------------------------------------------


class TestSubscriptionSetNegateRoundTrip:

    @pytest.mark.asyncio
    async def test_set_subscription_normalizes_negate(self):
        store = _RealStore()
        await store.async_create_category("alerts", "Alerts")
        hass = _make_hass_with_state("binary_sensor.tv", "on")
        conn = _make_conn()

        msg = {
            "id": 3,
            "type": "ticker/subscription/set",
            "person_id": "person.alice",
            "category_id": "alerts",
            "mode": "conditional",
            "conditions": {
                "condition_tree": _group(
                    "AND",
                    [
                        _state_leaf("binary_sensor.tv", "off", negate=True),
                        _state_leaf("binary_sensor.tv", "on", negate=False),
                    ],
                    negate=False,
                ),
                "deliver_when_met": True,
            },
        }

        with patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.subscriptions."
            "async_discover_notify_services",
            new=AsyncMock(return_value={}),
        ):
            await ws_set_subscription(hass, conn, msg)

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

        sub = store.get_subscription("person.alice", "alerts")
        assert sub is not None
        assert sub["mode"] == "conditional"
        tree = sub["conditions"]["condition_tree"]
        assert "negate" not in tree  # group false stripped
        assert tree["children"][0]["negate"] is True
        assert "negate" not in tree["children"][1]


# ---------------------------------------------------------------------------
# 4. Validator wired into WS path — non-bool negate is rejected end-to-end
# ---------------------------------------------------------------------------


class TestValidatorWiredIntoWsHandler:
    """Confirms ``validate_condition_tree`` is actually called from the
    subscription WS handler — not bypassed — by sending a tree with a
    non-bool ``negate`` and asserting the handler returns an error code
    instead of persisting.
    """

    @pytest.mark.asyncio
    async def test_set_subscription_rejects_non_bool_negate(self):
        store = _RealStore()
        await store.async_create_category("alerts", "Alerts")
        hass = _make_hass_with_state("binary_sensor.tv", "on")
        conn = _make_conn()

        bad_tree = _group(
            "AND", [_state_leaf("binary_sensor.tv", "off")],
        )
        bad_tree["negate"] = "true"  # string, not bool

        msg = {
            "id": 4,
            "type": "ticker/subscription/set",
            "person_id": "person.alice",
            "category_id": "alerts",
            "mode": "conditional",
            "conditions": {
                "condition_tree": bad_tree,
                "deliver_when_met": True,
            },
        }

        with patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.subscriptions."
            "async_discover_notify_services",
            new=AsyncMock(return_value={}),
        ):
            await ws_set_subscription(hass, conn, msg)

        # Handler must send_error (validator hit), and nothing should have
        # been persisted on the store.
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "invalid_tree"
        assert "negate" in args[2].lower() or "boolean" in args[2].lower()
        assert store.get_subscription("person.alice", "alerts") is None
