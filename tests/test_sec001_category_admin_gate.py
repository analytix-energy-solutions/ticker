"""SEC-001 — category mutations require admin.

``websocket/categories.py`` gates the three mutation handlers behind
``@websocket_api.require_admin`` while leaving the read handler
(``ws_get_categories``) open to non-admin users.

The conftest stub of ``websocket_command`` discards the voluptuous schema
and the ``require_admin`` stub cannot enforce the gate at import time, so
this suite verifies the contract two ways:

1. Introspection — the ``_ticker_require_admin`` marker attached by the
   conftest ``require_admin`` stub must be present on the three mutation
   handlers and absent on the read handler. This regression guard FAILS
   if someone removes ``require_admin`` from a mutation OR adds it to
   ``ws_get_categories``.
2. Behavioral — via the ``admin_gate_call`` fixture (mirrors the F-38
   admin-gate tests): non-admin callers are rejected with ``unauthorized``
   before the handler body runs; admin callers proceed; and the read
   handler serves non-admin callers.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.websocket.categories import (
    ws_create_category,
    ws_delete_category,
    ws_get_categories,
    ws_update_category,
)


MUTATION_HANDLERS = [ws_create_category, ws_update_category, ws_delete_category]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_category_mocks(exists: bool = True):
    hass = MagicMock()
    store = MagicMock()
    store.category_exists.return_value = exists
    store.is_default_category.return_value = False
    store.get_categories.return_value = {"general": {"id": "general", "name": "General"}}
    store.async_create_category = AsyncMock(return_value={"id": "security"})
    store.async_update_category = AsyncMock(return_value={"id": "security"})
    store.async_delete_category = AsyncMock(return_value=True)
    hass.config_entries.async_entries.return_value = []
    return hass, store


@contextmanager
def _category_patches(store):
    with patch(
        "custom_components.ticker.websocket.categories.get_store",
        return_value=store,
    ), patch(
        "custom_components.ticker.websocket.categories.validate_category_id",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_icon",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_color",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_navigate_to",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.sanitize_for_storage",
        side_effect=lambda v, _: v,
    ):
        yield


# ---------------------------------------------------------------------------
# 1. Introspection — regression guard on the decorator contract
# ---------------------------------------------------------------------------

class TestRequireAdminMarkers:
    """The @require_admin decorator must gate mutations, not the read."""

    @pytest.mark.parametrize(
        "handler",
        MUTATION_HANDLERS,
        ids=lambda h: h.__name__,
    )
    def test_mutation_handler_is_admin_gated(self, handler):
        assert getattr(handler, "_ticker_require_admin", False), (
            f"{handler.__name__} must be decorated with "
            "@websocket_api.require_admin"
        )

    def test_read_handler_is_not_admin_gated(self):
        """ws_get_categories must stay open for non-admin users."""
        assert not getattr(ws_get_categories, "_ticker_require_admin", False), (
            "ws_get_categories must NOT be admin-gated — non-admin users "
            "read categories to render their subscription panel"
        )


# ---------------------------------------------------------------------------
# 2. Behavioral — non-admin blocked, admin allowed, read open
# ---------------------------------------------------------------------------

class TestMutationGateBlocksNonAdmin:
    """Non-admin calls short-circuit with 'unauthorized' before the body."""

    @pytest.mark.asyncio
    async def test_create_non_admin_forbidden(
        self, non_admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=False)
        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_create_category, hass, non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "unauthorized"
        non_admin_connection.send_result.assert_not_called()
        store.async_create_category.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_non_admin_forbidden(
        self, non_admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=True)
        msg = {
            "id": 2,
            "type": "ticker/category/update",
            "category_id": "security",
            "name": "Renamed",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_update_category, hass, non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "unauthorized"
        store.async_update_category.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_non_admin_forbidden(
        self, non_admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=True)
        msg = {
            "id": 3,
            "type": "ticker/category/delete",
            "category_id": "security",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_delete_category, hass, non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "unauthorized"
        store.async_delete_category.assert_not_awaited()


class TestMutationGateAllowsAdmin:
    """Admin callers reach the handler body and mutate the store."""

    @pytest.mark.asyncio
    async def test_create_admin_allowed(
        self, admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=False)
        msg = {
            "id": 4,
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_create_category, hass, admin_connection, msg
            )

        admin_connection.send_error.assert_not_called()
        admin_connection.send_result.assert_called_once()
        store.async_create_category.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_admin_allowed(
        self, admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=True)
        msg = {
            "id": 5,
            "type": "ticker/category/update",
            "category_id": "security",
            "name": "Renamed",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_update_category, hass, admin_connection, msg
            )

        admin_connection.send_error.assert_not_called()
        admin_connection.send_result.assert_called_once()
        store.async_update_category.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_admin_allowed(
        self, admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=True)
        msg = {
            "id": 6,
            "type": "ticker/category/delete",
            "category_id": "security",
        }
        with _category_patches(store):
            await admin_gate_call(
                ws_delete_category, hass, admin_connection, msg
            )

        admin_connection.send_error.assert_not_called()
        admin_connection.send_result.assert_called_once()
        store.async_delete_category.assert_awaited_once()


class TestReadHandlerOpenToNonAdmin:
    """ws_get_categories serves non-admin callers (no gate)."""

    @pytest.mark.asyncio
    async def test_get_categories_non_admin_allowed(
        self, non_admin_connection, admin_gate_call
    ):
        hass, store = _make_category_mocks(exists=True)
        msg = {"id": 7, "type": "ticker/categories"}
        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await admin_gate_call(
                ws_get_categories, hass, non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_not_called()
        non_admin_connection.send_result.assert_called_once()
        payload = non_admin_connection.send_result.call_args[0][1]
        assert "categories" in payload
