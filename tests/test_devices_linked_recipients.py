"""F-39 chunk 5 — ``ticker/devices`` linked_recipients surface (v1.8.0b3).

Verifies:
- Response payload includes ``linked_recipients`` (default []).
- Recipients with ``user_link`` matching the target person are returned
  in name-sorted order.
- Recipients without a ``user_link`` (Standalone) are not returned.
- Admin can pass ``person_id`` to query another person's linked devices.
- Non-admin caller supplying a foreign ``person_id`` gets ``forbidden``.
- Backward compat: the ``devices`` field is still populated from
  discovery for the resolved target person.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.const import ATTR_USER_LINK
from custom_components.ticker.websocket.queue_log import ws_get_devices
from custom_components.ticker.websocket.recipient_helpers import (
    _collect_linked_recipients,
)

from ._f38_helpers import (
    discovered,
    patch_discovery,
    patch_discovery_queue_log,
)


def _make_store(recipients: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.get_recipients.return_value = recipients or {}
    return store


def _patch_store(store: MagicMock):
    return patch(
        "custom_components.ticker.websocket.queue_log.get_store",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestCollectLinkedRecipients:
    def test_empty_when_no_recipients(self):
        store = _make_store({})
        assert _collect_linked_recipients(store, "person.alice") == []

    def test_empty_when_no_recipients_match(self):
        store = _make_store({
            "tablet": {
                "recipient_id": "tablet", "name": "Hallway",
                ATTR_USER_LINK: "person.bob",
            },
            "speaker": {"recipient_id": "speaker", "name": "Kitchen"},
        })
        assert _collect_linked_recipients(store, "person.alice") == []

    def test_returns_only_matching_linked_recipients(self):
        store = _make_store({
            "a": {"recipient_id": "a", "name": "Zebra",
                  ATTR_USER_LINK: "person.alice"},
            "b": {"recipient_id": "b", "name": "Apple",
                  ATTR_USER_LINK: "person.alice"},
            "c": {"recipient_id": "c", "name": "Mango",
                  ATTR_USER_LINK: "person.bob"},
            "d": {"recipient_id": "d", "name": "Standalone"},
        })
        result = _collect_linked_recipients(store, "person.alice")
        # Name-sorted, ascending, case-insensitive.
        assert [r["name"] for r in result] == ["Apple", "Zebra"]
        assert [r["recipient_id"] for r in result] == ["b", "a"]

    def test_sort_is_case_insensitive(self):
        store = _make_store({
            "a": {"recipient_id": "a", "name": "bravo",
                  ATTR_USER_LINK: "person.x"},
            "b": {"recipient_id": "b", "name": "Alpha",
                  ATTR_USER_LINK: "person.x"},
            "c": {"recipient_id": "c", "name": "charlie",
                  ATTR_USER_LINK: "person.x"},
        })
        result = _collect_linked_recipients(store, "person.x")
        assert [r["name"] for r in result] == ["Alpha", "bravo", "charlie"]

    def test_tolerates_none_store(self):
        assert _collect_linked_recipients(None, "person.x") == []


# ---------------------------------------------------------------------------
# ws_get_devices behavior
# ---------------------------------------------------------------------------


class TestWsGetDevicesLinkedRecipients:

    @pytest.mark.asyncio
    async def test_response_includes_linked_recipients_field(
        self, non_admin_connection
    ):
        """Backward-compat: ``devices`` field stays populated AND new
        ``linked_recipients`` key is always present in the payload."""
        store = _make_store({})
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 1, "type": "ticker/devices"}
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), non_admin_connection, msg)
        non_admin_connection.send_result.assert_called_once()
        payload = non_admin_connection.send_result.call_args[0][1]
        assert "devices" in payload
        assert "linked_recipients" in payload
        assert payload["linked_recipients"] == []
        # Discovery's notify_services for the caller bubbles through unchanged.
        assert payload["devices"] == [{"service": "notify.caller_phone"}]

    @pytest.mark.asyncio
    async def test_empty_when_no_recipients_link_to_caller(
        self, non_admin_connection
    ):
        store = _make_store({
            "speaker": {"recipient_id": "speaker", "name": "Kitchen",
                        ATTR_USER_LINK: "person.other"},
            "standalone": {"recipient_id": "standalone", "name": "Office"},
        })
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 2, "type": "ticker/devices"}
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), non_admin_connection, msg)
        payload = non_admin_connection.send_result.call_args[0][1]
        assert payload["linked_recipients"] == []

    @pytest.mark.asyncio
    async def test_includes_linked_recipients_sorted_by_name(
        self, non_admin_connection
    ):
        store = _make_store({
            "z": {"recipient_id": "z", "name": "Zulu",
                  ATTR_USER_LINK: "person.caller"},
            "a": {"recipient_id": "a", "name": "alpha",
                  ATTR_USER_LINK: "person.caller"},
            "m": {"recipient_id": "m", "name": "Mike",
                  ATTR_USER_LINK: "person.caller"},
            "x": {"recipient_id": "x", "name": "Xray",
                  ATTR_USER_LINK: "person.other"},
        })
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 3, "type": "ticker/devices"}
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), non_admin_connection, msg)
        payload = non_admin_connection.send_result.call_args[0][1]
        names = [r["name"] for r in payload["linked_recipients"]]
        # Sorted case-insensitive ascending; "Xray" excluded (other person).
        assert names == ["alpha", "Mike", "Zulu"]

    @pytest.mark.asyncio
    async def test_admin_can_query_other_persons_linked_devices(
        self, admin_connection
    ):
        """Admin supplies ``person_id`` to surface another household
        member's linked recipients (view-as parity)."""
        store = _make_store({
            "tablet": {"recipient_id": "tablet", "name": "Hallway",
                       ATTR_USER_LINK: "person.other"},
            "self": {"recipient_id": "self", "name": "AdminThing",
                     ATTR_USER_LINK: "person.admin"},
        })
        disc = discovered("person.admin", "uid_admin")
        msg = {
            "id": 4,
            "type": "ticker/devices",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), admin_connection, msg)
        admin_connection.send_result.assert_called_once()
        admin_connection.send_error.assert_not_called()
        payload = admin_connection.send_result.call_args[0][1]
        assert [r["recipient_id"] for r in payload["linked_recipients"]] \
            == ["tablet"]

    @pytest.mark.asyncio
    async def test_non_admin_foreign_person_id_forbidden(
        self, non_admin_connection
    ):
        store = _make_store({
            "tablet": {"recipient_id": "tablet", "name": "Hallway",
                       ATTR_USER_LINK: "person.other"},
        })
        disc = discovered("person.caller", "uid_regular")
        msg = {
            "id": 5,
            "type": "ticker/devices",
            "person_id": "person.other",
        }
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), non_admin_connection, msg)
        non_admin_connection.send_error.assert_called_once()
        assert non_admin_connection.send_error.call_args[0][1] == "forbidden"
        non_admin_connection.send_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_backward_compat_devices_field_unchanged_shape(
        self, non_admin_connection
    ):
        """Existing consumers reading ``result.devices`` continue to work:
        the shape of each device entry is whatever discovery returned,
        unchanged by F-39 chunk 5."""
        store = _make_store({})
        disc = discovered("person.caller", "uid_regular")
        msg = {"id": 6, "type": "ticker/devices"}
        with patch_discovery(disc), patch_discovery_queue_log(disc), \
                _patch_store(store):
            await ws_get_devices(MagicMock(), non_admin_connection, msg)
        payload = non_admin_connection.send_result.call_args[0][1]
        assert isinstance(payload["devices"], list)
        # Discovery fixture returns ``[{"service": "notify.caller_phone"}]``.
        for d in payload["devices"]:
            assert "service" in d
