"""Tests for BUG-098: ws_set_subscription correctly tags set_by.

The audit trail (set_by) must reflect:
- SET_BY_USER when a caller edits their own subscription
- SET_BY_ADMIN when a real admin edits someone else's subscription
- SET_BY_USER when a non-admin caller edits someone else's subscription
  (falls back to USER rather than mislabeling as admin)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.const import SET_BY_ADMIN, SET_BY_USER
from custom_components.ticker.websocket.subscriptions import ws_set_subscription


def _make_conn(user_id: str, is_admin: bool) -> MagicMock:
    conn = MagicMock()
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    conn.user = user
    return conn


def _base_msg(**overrides) -> dict:
    msg = {
        "id": 1,
        "type": "ticker/subscription/set",
        "person_id": "person.target",
        "category_id": "cat1",
        "mode": "always",
    }
    msg.update(overrides)
    return msg


def _make_store() -> MagicMock:
    store = MagicMock()
    store.category_exists.return_value = True
    store.async_set_subscription = AsyncMock(return_value={"ok": True})
    return store


def _discovered_for(target_person: str, target_user_id: str | None) -> dict:
    return {
        target_person: {
            "person_id": target_person,
            "name": "Target",
            "user_id": target_user_id,
            "notify_services": [],
            "device_trackers": [],
        }
    }


class TestBug098SetByAudit:

    @pytest.mark.asyncio
    async def test_self_edit_tagged_user_even_if_admin(self):
        """Self-edit is always SET_BY_USER regardless of admin flag."""
        hass = MagicMock()
        store = _make_store()
        conn = _make_conn(user_id="uid_admin", is_admin=True)

        with patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.subscriptions.async_discover_notify_services",
            new_callable=AsyncMock,
            return_value=_discovered_for("person.target", "uid_admin"),
        ):
            await ws_set_subscription(hass, conn, _base_msg())

        store.async_set_subscription.assert_awaited_once()
        set_by = store.async_set_subscription.call_args[1]["set_by"]
        assert set_by == SET_BY_USER

    @pytest.mark.asyncio
    async def test_admin_cross_user_edit_tagged_admin(self):
        """Real admin editing another user's sub is SET_BY_ADMIN."""
        hass = MagicMock()
        store = _make_store()
        conn = _make_conn(user_id="uid_admin", is_admin=True)

        with patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.subscriptions.async_discover_notify_services",
            new_callable=AsyncMock,
            return_value=_discovered_for("person.target", "uid_someone_else"),
        ):
            await ws_set_subscription(hass, conn, _base_msg())

        set_by = store.async_set_subscription.call_args[1]["set_by"]
        assert set_by == SET_BY_ADMIN

    @pytest.mark.asyncio
    async def test_non_admin_cross_user_edit_tagged_user(self):
        """Non-admin caller editing another user's sub is SET_BY_USER
        (must not be mislabeled as ADMIN)."""
        hass = MagicMock()
        store = _make_store()
        conn = _make_conn(user_id="uid_regular", is_admin=False)

        with patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.subscriptions.async_discover_notify_services",
            new_callable=AsyncMock,
            return_value=_discovered_for("person.target", "uid_someone_else"),
        ):
            await ws_set_subscription(hass, conn, _base_msg())

        set_by = store.async_set_subscription.call_args[1]["set_by"]
        assert set_by == SET_BY_USER, (
            "BUG-098: non-admin cross-user edits must fall back to "
            "SET_BY_USER, not be mislabeled as admin"
        )
