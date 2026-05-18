"""F-38 backend authorization — read-path cases (spec §8 a-g, s-v).

This file covers the read-side admin-or-self gates plus the
FIX-001/002/003 omit-the-filter substitution catch from the Chunk 1
reviewer pass. Write-side, admin-only-handler, and device-preference
cases live in ``test_f38_view_as_user_writes.py`` so each file stays
under the 500-line hard limit.

Cases (a)-(g) follow the case IDs in spec §8 verbatim. Cases (s)-(v)
verify that a non-admin caller who omits ``person_id`` is scoped to
their own data (not falling through to the household-wide branch),
while an admin omitting ``person_id`` retains the unscoped view.

Conftest fixtures ``admin_connection`` and ``non_admin_connection``
build mock WS connections with ``is_admin`` set appropriately.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.ticker.websocket.queue_log import (
    ws_get_logs,
    ws_get_queue,
)
from custom_components.ticker.websocket.subscriptions import (
    ws_get_subscriptions,
)

from ._f38_helpers import (
    discovered,
    make_store,
    patch_discovery,
    patch_store,
)


# ---------------------------------------------------------------------------
# Read gates — (a)-(g)
# ---------------------------------------------------------------------------


class TestF38ReadGates:

    # (a)
    @pytest.mark.asyncio
    async def test_ws_subscriptions_admin_can_read_any(self, admin_connection):
        store = make_store()
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 1,
            "type": "ticker/subscriptions",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[0]:
            await ws_get_subscriptions(MagicMock(), admin_connection, msg)

        admin_connection.send_result.assert_called_once()
        admin_connection.send_error.assert_not_called()
        store.get_subscriptions_for_person.assert_called_once_with(
            "person.other"
        )

    # (b)
    @pytest.mark.asyncio
    async def test_ws_subscriptions_non_admin_self_ok(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 2,
            "type": "ticker/subscriptions",
            "person_id": "person.caller",
        }
        with patch_discovery(disc), patch_store(store)[0]:
            await ws_get_subscriptions(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_result.assert_called_once()
        non_admin_connection.send_error.assert_not_called()

    # (c)
    @pytest.mark.asyncio
    async def test_ws_subscriptions_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 3,
            "type": "ticker/subscriptions",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[0]:
            await ws_get_subscriptions(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"
        store.get_subscriptions_for_person.assert_not_called()

    # (d)
    @pytest.mark.asyncio
    async def test_ws_queue_admin_can_read_any(self, admin_connection):
        store = make_store()
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 4,
            "type": "ticker/queue",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_queue(MagicMock(), admin_connection, msg)

        admin_connection.send_result.assert_called_once()
        store.get_queue_for_person.assert_called_once_with("person.other")

    # (e)
    @pytest.mark.asyncio
    async def test_ws_queue_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 5,
            "type": "ticker/queue",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_queue(MagicMock(), non_admin_connection, msg)

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"

    # (f)
    @pytest.mark.asyncio
    async def test_ws_logs_admin_can_read_any(self, admin_connection):
        store = make_store()
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 6,
            "type": "ticker/logs",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_logs(MagicMock(), admin_connection, msg)

        admin_connection.send_result.assert_called_once()
        kwargs = store.get_logs.call_args[1]
        assert kwargs["person_id"] == "person.other"

    # (g)
    @pytest.mark.asyncio
    async def test_ws_logs_non_admin_other_forbidden(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 7,
            "type": "ticker/logs",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_logs(MagicMock(), non_admin_connection, msg)

        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"


# ---------------------------------------------------------------------------
# Omit-person-id scope — (s)-(v)
# ---------------------------------------------------------------------------


class TestF38OmitPersonIdScope:
    """Reviewer Chunk 1 catch (FIX-001/002/003): a non-admin caller who
    omits ``person_id`` must NOT fall through to the household-wide
    branch. The handlers substitute the caller's own person_id. Admin
    omitting ``person_id`` retains the unscoped (all-household) view.
    """

    # (s)
    @pytest.mark.asyncio
    async def test_ws_subscriptions_non_admin_omits_person_id_scopes_to_self(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 19, "type": "ticker/subscriptions"}
        with patch_discovery(disc), patch_store(store)[0]:
            await ws_get_subscriptions(
                MagicMock(), non_admin_connection, msg
            )

        non_admin_connection.send_error.assert_not_called()
        store.get_subscriptions_for_person.assert_called_once_with(
            "person.caller"
        )
        # Must NOT have fallen through to the household-wide branch.
        store.get_categories.assert_not_called()

    # (t)
    @pytest.mark.asyncio
    async def test_ws_queue_non_admin_omits_person_id_scopes_to_self(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 20, "type": "ticker/queue"}
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_queue(MagicMock(), non_admin_connection, msg)

        non_admin_connection.send_error.assert_not_called()
        store.get_queue_for_person.assert_called_once_with("person.caller")
        store.get_queue.assert_not_called()

    # (u)
    @pytest.mark.asyncio
    async def test_ws_logs_non_admin_omits_person_id_scopes_to_self(
        self, non_admin_connection
    ):
        store = make_store()
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 21, "type": "ticker/logs"}
        with patch_discovery(disc), patch_store(store)[1]:
            await ws_get_logs(MagicMock(), non_admin_connection, msg)

        non_admin_connection.send_error.assert_not_called()
        kwargs = store.get_logs.call_args[1]
        assert kwargs["person_id"] == "person.caller"

    # (v)
    @pytest.mark.asyncio
    async def test_ws_subscriptions_admin_omits_person_id_returns_household(
        self, admin_connection
    ):
        """Admin omitting ``person_id`` retains the unscoped view across
        all categories (the pre-F-38 household-wide branch)."""
        store = make_store()
        store.get_categories.return_value = {"cat1": {}, "cat2": {}}
        disc = discovered("person.admin", "uid_admin")
        msg = {"id": 22, "type": "ticker/subscriptions"}
        with patch_discovery(disc), patch_store(store)[0]:
            await ws_get_subscriptions(MagicMock(), admin_connection, msg)

        admin_connection.send_error.assert_not_called()
        store.get_categories.assert_called_once()
        store.get_subscriptions_for_person.assert_not_called()
