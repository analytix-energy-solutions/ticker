"""Tests for F-39 WebSocket handlers (chunk 1).

Covers:
- ``ws_set_recipient_user_link``: admin gate, validation, set/clear paths.
- ``ws_get_recipients``: F-39 fields (user_link, linked_user_name,
  linked_user_subscriptions) appear correctly for linked and unlinked
  recipients.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.const import (
    ATTR_USER_LINK,
    MODE_ALWAYS,
    MODE_CONDITIONAL,
)
from custom_components.ticker.websocket.recipient_subscriptions import (
    ws_set_recipient_user_link,
)
from custom_components.ticker.websocket.recipients import ws_get_recipients
from tests.conftest import call_with_admin_gate


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_hass(person_states: dict[str, MagicMock] | None = None) -> MagicMock:
    """Build a hass mock whose ``states.get`` honours a fixed person map."""
    hass = MagicMock()
    state_map = person_states or {}
    hass.states = MagicMock()

    def _get(entity_id, *args, **kwargs):
        return state_map.get(entity_id)

    hass.states.get = _get
    return hass


def _make_person_state(friendly_name: str) -> MagicMock:
    state = MagicMock()
    state.attributes = {"friendly_name": friendly_name}
    return state


def _make_conn(is_admin: bool = True) -> MagicMock:
    conn = MagicMock()
    user = MagicMock()
    user.id = "uid_admin" if is_admin else "uid_user"
    user.is_admin = is_admin
    conn.user = user
    return conn


def _make_store(
    recipient: dict | None = None,
    updated_return: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.get_recipient.return_value = recipient
    store.async_set_recipient_user_link = AsyncMock(
        return_value=updated_return or recipient or {},
    )
    return store


# ---------------------------------------------------------------------------
# ws_set_recipient_user_link — admin gate
# ---------------------------------------------------------------------------

class TestSetUserLinkAdminGate:

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self):
        hass = _make_hass()
        conn = _make_conn(is_admin=False)
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "tv_living",
            "person_id": "person.alice",
        }
        await call_with_admin_gate(
            ws_set_recipient_user_link, hass, conn, msg,
        )
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "unauthorized"

    @pytest.mark.asyncio
    async def test_decorator_attribute_set(self):
        assert getattr(
            ws_set_recipient_user_link, "_ticker_require_admin", False,
        ) is True


# ---------------------------------------------------------------------------
# ws_set_recipient_user_link — validation
# ---------------------------------------------------------------------------

class TestSetUserLinkValidation:

    @pytest.mark.asyncio
    async def test_unknown_recipient(self):
        hass = _make_hass()
        conn = _make_conn()
        store = _make_store(recipient=None)
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "ghost",
            "person_id": "person.alice",
        }
        with patch(
            "custom_components.ticker.websocket.recipient_subscriptions.get_store",
            return_value=store,
        ):
            await ws_set_recipient_user_link(hass, conn, msg)
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "recipient_not_found"

    @pytest.mark.asyncio
    async def test_invalid_person_id_format(self):
        hass = _make_hass()
        conn = _make_conn()
        store = _make_store(recipient={"recipient_id": "tv_living"})
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "tv_living",
            "person_id": "alice",  # missing "person." prefix
        }
        with patch(
            "custom_components.ticker.websocket.recipient_subscriptions.get_store",
            return_value=store,
        ):
            await ws_set_recipient_user_link(hass, conn, msg)
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "invalid_person_id"

    @pytest.mark.asyncio
    async def test_invalid_person_id_no_state(self):
        # Prefix is correct but the entity isn't registered in hass.states.
        hass = _make_hass(person_states={})
        conn = _make_conn()
        store = _make_store(recipient={"recipient_id": "tv_living"})
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "tv_living",
            "person_id": "person.ghost",
        }
        with patch(
            "custom_components.ticker.websocket.recipient_subscriptions.get_store",
            return_value=store,
        ):
            await ws_set_recipient_user_link(hass, conn, msg)
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "invalid_person_id"


# ---------------------------------------------------------------------------
# ws_set_recipient_user_link — set + clear
# ---------------------------------------------------------------------------

class TestSetUserLinkHappyPath:

    @pytest.mark.asyncio
    async def test_none_unlinks(self):
        hass = _make_hass()
        conn = _make_conn()
        updated = {"recipient_id": "tv_living", "name": "Living TV"}
        store = _make_store(
            recipient={"recipient_id": "tv_living"},
            updated_return=updated,
        )
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "tv_living",
            "person_id": None,
        }
        with patch(
            "custom_components.ticker.websocket.recipient_subscriptions.get_store",
            return_value=store,
        ):
            await ws_set_recipient_user_link(hass, conn, msg)
        conn.send_error.assert_not_called()
        conn.send_result.assert_called_once()
        store.async_set_recipient_user_link.assert_awaited_once_with(
            "tv_living", None,
        )
        # Response shape
        result = conn.send_result.call_args[0][1]
        assert result == {"recipient": updated}

    @pytest.mark.asyncio
    async def test_valid_person_id_links(self):
        hass = _make_hass(
            person_states={"person.alice": _make_person_state("Alice")},
        )
        conn = _make_conn()
        updated = {
            "recipient_id": "tv_living",
            "name": "Living TV",
            ATTR_USER_LINK: "person.alice",
        }
        store = _make_store(
            recipient={"recipient_id": "tv_living"},
            updated_return=updated,
        )
        msg = {
            "id": 1,
            "type": "ticker/set_recipient_user_link",
            "recipient_id": "tv_living",
            "person_id": "person.alice",
        }
        with patch(
            "custom_components.ticker.websocket.recipient_subscriptions.get_store",
            return_value=store,
        ):
            await ws_set_recipient_user_link(hass, conn, msg)
        conn.send_error.assert_not_called()
        store.async_set_recipient_user_link.assert_awaited_once_with(
            "tv_living", "person.alice",
        )
        result = conn.send_result.call_args[0][1]
        assert result["recipient"][ATTR_USER_LINK] == "person.alice"


# ---------------------------------------------------------------------------
# ws_get_recipients — F-39 response fields
# ---------------------------------------------------------------------------

class TestGetRecipientsUserLinkFields:

    @pytest.mark.asyncio
    async def test_unlinked_recipient_has_null_fields(self):
        hass = _make_hass()
        conn = _make_conn()
        store = MagicMock()
        store.get_recipients.return_value = {
            "tv_living": {
                "recipient_id": "tv_living",
                "name": "Living TV",
                "device_type": "push",
            },
        }
        store.get_categories.return_value = {
            "alerts": {"default_mode": MODE_ALWAYS},
        }
        store.get_subscriptions_for_recipient.return_value = {}
        store.get_subscriptions_for_person.return_value = {}
        msg = {"id": 1, "type": "ticker/get_recipients"}
        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_get_recipients(hass, conn, msg)
        result = conn.send_result.call_args[0][1]["recipients"]
        assert len(result) == 1
        assert result[0]["user_link"] is None
        assert result[0]["linked_user_name"] is None
        assert result[0]["linked_user_subscriptions"] is None
        # Existing field still present.
        assert "subscriptions" in result[0]

    @pytest.mark.asyncio
    async def test_linked_recipient_includes_friendly_name_and_subs(self):
        hass = _make_hass(
            person_states={"person.alice": _make_person_state("Alice")},
        )
        conn = _make_conn()
        store = MagicMock()
        store.get_recipients.return_value = {
            "tv_living": {
                "recipient_id": "tv_living",
                "name": "Living TV",
                "device_type": "push",
                ATTR_USER_LINK: "person.alice",
            },
        }
        store.get_categories.return_value = {
            "alerts": {"default_mode": MODE_ALWAYS},
            "dinner": {"default_mode": MODE_CONDITIONAL},
        }
        # Recipient's own rows are empty (linked, so we mirror user).
        store.get_subscriptions_for_recipient.return_value = {}
        # Alice's user-side rows.
        store.get_subscriptions_for_person.return_value = {
            "alerts": {"mode": MODE_ALWAYS},
            "dinner": {
                "mode": MODE_CONDITIONAL,
                "conditions": {"version": 1},
            },
        }
        msg = {"id": 1, "type": "ticker/get_recipients"}
        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_get_recipients(hass, conn, msg)
        result = conn.send_result.call_args[0][1]["recipients"]
        assert result[0]["user_link"] == "person.alice"
        assert result[0]["linked_user_name"] == "Alice"
        lus = result[0]["linked_user_subscriptions"]
        assert lus["alerts"]["mode"] == MODE_ALWAYS
        assert lus["dinner"]["mode"] == MODE_CONDITIONAL
        assert lus["dinner"]["conditions"] == {"version": 1}

    @pytest.mark.asyncio
    async def test_linked_recipient_with_missing_person_state(self):
        """If the linked person has no current state (e.g. just removed but
        the orphan-fallback listener hasn't fired yet), friendly_name is
        None and the subscription map is still built from stored rows."""
        hass = _make_hass(person_states={})
        conn = _make_conn()
        store = MagicMock()
        store.get_recipients.return_value = {
            "tv_living": {
                "recipient_id": "tv_living",
                "name": "Living TV",
                ATTR_USER_LINK: "person.ghost",
            },
        }
        store.get_categories.return_value = {
            "alerts": {"default_mode": MODE_ALWAYS},
        }
        store.get_subscriptions_for_recipient.return_value = {}
        store.get_subscriptions_for_person.return_value = {}
        msg = {"id": 1, "type": "ticker/get_recipients"}
        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_get_recipients(hass, conn, msg)
        result = conn.send_result.call_args[0][1]["recipients"]
        assert result[0]["user_link"] == "person.ghost"
        assert result[0]["linked_user_name"] is None
        # Still a dict (just empty mapping over default category modes).
        assert result[0]["linked_user_subscriptions"] is not None
        assert result[0]["linked_user_subscriptions"]["alerts"]["mode"] == MODE_ALWAYS
