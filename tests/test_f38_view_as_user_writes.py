"""F-38 backend authorization — write-path + admin-only handler cases
(spec §8 h-r).

Companion to ``test_f38_view_as_user.py`` (read-path + omit-scope
cases). Split to keep each file under the 500-line limit.

Covers:
- Cross-user write gates: queue/clear, queue/remove, subscription/set
  (cases h, i, j, k)
- Admin-only handlers: ticker/users, ticker/get_person (cases l, m, n, o)
- ``ticker/device_preference/set`` with optional admin-only ``person_id``
  (cases p, q, r)

The ``admin_gate_call`` fixture wraps a handler invocation so that
``@websocket_api.require_admin``-decorated handlers reject non-admins
in tests (the conftest stub of ``require_admin`` cannot enforce the
gate at import time; the helper enforces it at call time using the
``_ticker_require_admin`` marker attached by the stub).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.ticker.const import (
    DEVICE_MODE_ALL,
    DEVICE_MODE_SELECTED,
    SET_BY_ADMIN,
)
from custom_components.ticker.websocket.queue_log import (
    ws_clear_queue,
    ws_remove_queue_entry,
    ws_set_device_preference,
)
from custom_components.ticker.websocket.subscriptions import (
    ws_set_subscription,
)
from custom_components.ticker.websocket.users import (
    ws_get_person,
    ws_get_users,
)

from ._f38_helpers import (
    discovered,
    make_store,
    patch_discovery,
    patch_discovery_queue_log,
    patch_discovery_subscriptions,
    patch_discovery_users,
    patch_store,
)


# ---------------------------------------------------------------------------
# Cross-user write gates — (h)-(k)
# ---------------------------------------------------------------------------


class TestF38WriteGates:

    # (h)
    @pytest.mark.asyncio
    async def test_ws_queue_clear_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 8,
            "type": "ticker/queue/clear",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_clear_queue(MagicMock(), non_admin_connection, msg)

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"
        store.async_clear_queue_for_person.assert_not_awaited()

    # (i)
    @pytest.mark.asyncio
    async def test_ws_queue_remove_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        """FIX-004: cross-user remove returns ``not_found`` (info leak
        collapsed) rather than ``forbidden`` when the entry belongs to
        someone else, so the caller cannot enumerate the other user's
        queue entries.
        """
        store = make_store()
        store.get_queue.return_value = {
            "queue_abc": {
                "queue_id": "queue_abc",
                "person_id": "person.other",
            }
        }
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 9,
            "type": "ticker/queue/remove",
            "queue_id": "queue_abc",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_remove_queue_entry(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "not_found"
        store.async_remove_from_queue.assert_not_awaited()

    # (j)
    @pytest.mark.asyncio
    async def test_ws_subscription_set_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 10,
            "type": "ticker/subscription/set",
            "person_id": "person.other",
            "category_id": "cat1",
            "mode": "always",
        }
        with patch_discovery(disc), patch_discovery_subscriptions(
            disc
        ), patch_store(store)[0]:
            await ws_set_subscription(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"
        store.async_set_subscription.assert_not_awaited()

    # (k)
    @pytest.mark.asyncio
    async def test_ws_subscription_set_admin_sets_set_by_admin(
        self, admin_connection
    ):
        """Regression on BUG-098: admin editing another user's
        subscription persists ``set_by=ADMIN``."""
        store = make_store()
        # Admin's user_id is uid_admin; target (person.other) is owned
        # by a different HA user — the cross-user admin path.
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 11,
            "type": "ticker/subscription/set",
            "person_id": "person.other",
            "category_id": "cat1",
            "mode": "always",
        }
        with patch_discovery(disc), patch_discovery_subscriptions(
            disc
        ), patch_store(store)[0]:
            await ws_set_subscription(MagicMock(), admin_connection, msg)

        admin_connection.send_error.assert_not_called()
        store.async_set_subscription.assert_awaited_once()
        set_by = store.async_set_subscription.call_args[1]["set_by"]
        assert set_by == SET_BY_ADMIN


# ---------------------------------------------------------------------------
# Admin-only handlers — (l)-(o)
# ---------------------------------------------------------------------------


class TestF38AdminOnlyHandlers:

    # (l)
    @pytest.mark.asyncio
    async def test_ws_users_non_admin_forbidden(
        self, non_admin_connection, admin_gate_call
    ):
        """Non-admin call to ``ticker/users`` is rejected by the
        ``@require_admin`` gate before reaching the handler body."""
        assert getattr(ws_get_users, "_ticker_require_admin", False), (
            "ws_get_users must be decorated with @websocket_api.require_admin"
        )

        store = make_store()
        msg = {"id": 12, "type": "ticker/users"}
        with patch_discovery_users({}), patch_store(store)[2]:
            await admin_gate_call(
                ws_get_users, MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert (
            non_admin_connection.send_error.call_args[0][1] == "unauthorized"
        )
        non_admin_connection.send_result.assert_not_called()

    # (m)
    @pytest.mark.asyncio
    async def test_ws_get_person_admin_returns_person(
        self, admin_connection, admin_gate_call
    ):
        assert getattr(ws_get_person, "_ticker_require_admin", False), (
            "ws_get_person must be decorated with @websocket_api.require_admin"
        )

        store = make_store()
        store.get_user.return_value = {
            "enabled": True,
            "device_preference": {
                "mode": DEVICE_MODE_SELECTED,
                "devices": ["notify.x"],
            },
        }
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 13,
            "type": "ticker/get_person",
            "person_id": "person.other",
        }
        with patch_discovery_users(disc), patch_store(store)[2]:
            await admin_gate_call(
                ws_get_person, MagicMock(), admin_connection, msg
            )

        admin_connection.send_error.assert_not_called()
        admin_connection.send_result.assert_called_once()
        payload = admin_connection.send_result.call_args[0][1]
        assert payload["person"]["person_id"] == "person.other"
        assert payload["person"]["enabled"] is True
        assert (
            payload["person"]["device_preference"]["mode"]
            == DEVICE_MODE_SELECTED
        )

    # (n)
    @pytest.mark.asyncio
    async def test_ws_get_person_admin_returns_none_for_missing(
        self, admin_connection, admin_gate_call
    ):
        store = make_store()
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 14,
            "type": "ticker/get_person",
            "person_id": "person.does_not_exist",
        }
        with patch_discovery_users(disc), patch_store(store)[2]:
            await admin_gate_call(
                ws_get_person, MagicMock(), admin_connection, msg
            )

        admin_connection.send_result.assert_called_once()
        payload = admin_connection.send_result.call_args[0][1]
        assert payload == {"person": None}

    # (o)
    @pytest.mark.asyncio
    async def test_ws_get_person_non_admin_forbidden(
        self, non_admin_connection, admin_gate_call
    ):
        store = make_store()
        msg = {
            "id": 15,
            "type": "ticker/get_person",
            "person_id": "person.other",
        }
        with patch_discovery_users({}), patch_store(store)[2]:
            await admin_gate_call(
                ws_get_person, MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert (
            non_admin_connection.send_error.call_args[0][1] == "unauthorized"
        )


# ---------------------------------------------------------------------------
# device_preference/set with optional person_id — (p)-(r)
# ---------------------------------------------------------------------------


class TestF38DevicePreferenceAdmin:

    # (p)
    @pytest.mark.asyncio
    async def test_ws_device_preference_admin_targets_other_person(
        self, admin_connection
    ):
        store = make_store()
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 16,
            "type": "ticker/device_preference/set",
            "mode": DEVICE_MODE_ALL,
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_discovery_queue_log(
            disc
        ), patch_store(store)[1]:
            await ws_set_device_preference(
                MagicMock(), admin_connection, msg
            )

        admin_connection.send_error.assert_not_called()
        store.async_set_device_preference.assert_awaited_once()
        kwargs = store.async_set_device_preference.call_args[1]
        assert kwargs["person_id"] == "person.other"
        assert kwargs["mode"] == DEVICE_MODE_ALL

    # (q)
    @pytest.mark.asyncio
    async def test_ws_device_preference_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 17,
            "type": "ticker/device_preference/set",
            "mode": DEVICE_MODE_ALL,
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_discovery_queue_log(
            disc
        ), patch_store(store)[1]:
            await ws_set_device_preference(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert (
            non_admin_connection.send_error.call_args[0][1] == "forbidden"
        )
        store.async_set_device_preference.assert_not_awaited()

    # (r)
    @pytest.mark.asyncio
    async def test_ws_device_preference_caller_default_unchanged(
        self, non_admin_connection
    ):
        """No ``person_id`` provided — handler must derive target from
        the caller's own HA user (pre-F-38 behavior preserved)."""
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 18,
            "type": "ticker/device_preference/set",
            "mode": DEVICE_MODE_ALL,
        }
        with patch_discovery(disc), patch_discovery_queue_log(
            disc
        ), patch_store(store)[1]:
            await ws_set_device_preference(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_not_called()
        store.async_set_device_preference.assert_awaited_once()
        kwargs = store.async_set_device_preference.call_args[1]
        assert kwargs["person_id"] == "person.caller"
