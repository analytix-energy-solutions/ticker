"""Tests for F-21 Device-Level Conditions.

Covers:
- Store: create/update recipient with conditions, sparse storage
- Services: device-level condition gate in recipient delivery loop
- WebSocket: conditions validation in create/update handlers
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.store.recipients import RecipientMixin


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

class FakeStore(RecipientMixin):
    """Concrete class mixing in RecipientMixin for testing."""

    def __init__(self, recipients=None, subscriptions=None):
        self.hass = MagicMock()
        self._recipients: dict = recipients if recipients is not None else {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self.async_save_subscriptions = AsyncMock()


@pytest.fixture
def store():
    return FakeStore()


# ---------------------------------------------------------------------------
# Store: create recipient with/without conditions
# ---------------------------------------------------------------------------

class TestCreateRecipientConditions:
    """Verify conditions parameter in async_create_recipient."""

    @pytest.mark.asyncio
    async def test_create_without_conditions(self, store):
        """Existing behavior: no conditions param -> key absent (sparse)."""
        result = await store.async_create_recipient("r1", "Device", [])
        assert "conditions" not in result
        assert "conditions" not in store._recipients["r1"]

    @pytest.mark.asyncio
    async def test_create_with_none_conditions(self, store):
        """Explicit None -> key absent (sparse)."""
        result = await store.async_create_recipient(
            "r1", "Device", [], conditions=None,
        )
        assert "conditions" not in result

    @pytest.mark.asyncio
    async def test_create_with_conditions(self, store):
        """Conditions dict stored when provided."""
        conds = {"rules": [{"type": "time", "after": "08:00", "before": "22:00"}]}
        result = await store.async_create_recipient(
            "r1", "Device", [], conditions=conds,
        )
        assert result["conditions"] == conds
        assert store._recipients["r1"]["conditions"] == conds

    @pytest.mark.asyncio
    async def test_create_with_empty_rules(self, store):
        """Conditions with empty rules list is stored (valid structure)."""
        conds = {"rules": []}
        result = await store.async_create_recipient(
            "r1", "Device", [], conditions=conds,
        )
        assert result["conditions"] == conds

    @pytest.mark.asyncio
    async def test_create_persists(self, store):
        """Storage save called after create with conditions."""
        conds = {"rules": [{"type": "state", "entity_id": "switch.x", "state": "on"}]}
        await store.async_create_recipient("r1", "Dev", [], conditions=conds)
        store._recipients_store.async_save.assert_awaited_once()


# ---------------------------------------------------------------------------
# Store: update recipient conditions
# ---------------------------------------------------------------------------

class TestUpdateRecipientConditions:
    """Verify conditions in async_update_recipient (add, modify, clear)."""

    @pytest.mark.asyncio
    async def test_update_add_conditions(self, store):
        """Add conditions to a recipient that had none."""
        await store.async_create_recipient("r1", "Device", [])
        assert "conditions" not in store._recipients["r1"]

        conds = {"rules": [{"type": "time", "after": "09:00", "before": "17:00"}]}
        result = await store.async_update_recipient("r1", conditions=conds)
        assert result["conditions"] == conds

    @pytest.mark.asyncio
    async def test_update_modify_conditions(self, store):
        """Modify existing conditions."""
        old = {"rules": [{"type": "time", "after": "08:00", "before": "22:00"}]}
        await store.async_create_recipient("r1", "Dev", [], conditions=old)

        new = {"rules": [{"type": "state", "entity_id": "switch.x", "state": "on"}]}
        result = await store.async_update_recipient("r1", conditions=new)
        assert result["conditions"] == new

    @pytest.mark.asyncio
    async def test_update_clear_conditions_sparse(self, store):
        """Setting conditions to None pops the key (sparse cleanup)."""
        conds = {"rules": [{"type": "time", "after": "08:00", "before": "22:00"}]}
        await store.async_create_recipient("r1", "Dev", [], conditions=conds)
        assert "conditions" in store._recipients["r1"]

        result = await store.async_update_recipient("r1", conditions=None)
        assert "conditions" not in store._recipients["r1"]
        assert "conditions" not in result

    @pytest.mark.asyncio
    async def test_update_clear_when_no_conditions_no_error(self, store):
        """Clearing conditions that were never set does not raise."""
        await store.async_create_recipient("r1", "Dev", [])
        result = await store.async_update_recipient("r1", conditions=None)
        assert "conditions" not in result

    @pytest.mark.asyncio
    async def test_update_conditions_with_other_fields(self, store):
        """Conditions update alongside other fields."""
        await store.async_create_recipient("r1", "Dev", [])
        conds = {"rules": []}
        result = await store.async_update_recipient(
            "r1", name="New Name", conditions=conds,
        )
        assert result["name"] == "New Name"
        assert result["conditions"] == conds


# ---------------------------------------------------------------------------
# Services: device-level condition gate
# ---------------------------------------------------------------------------

def _make_hass_for_service():
    """Build a mock hass with states for the service handler."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    hass.states.async_all.return_value = []  # no persons
    return hass


def _make_store_for_service(recipients, sub_mode="always"):
    """Build a mock store for service handler tests."""
    store = MagicMock()
    store.get_recipients.return_value = recipients
    store.get_categories.return_value = {"cat1": {"name": "Test"}}
    store.get_category.return_value = {"name": "Test"}
    store.category_exists.return_value = True
    store.is_user_enabled.return_value = True
    store.get_subscription_mode.return_value = sub_mode
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    return store


class TestDeviceConditionGate:
    """Test F-21 condition gate in services.py recipient loop."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    @patch("custom_components.ticker.services.async_send_to_recipient", new_callable=AsyncMock)
    @patch("custom_components.ticker.services.evaluate_condition_tree")
    async def test_conditions_met_proceeds_to_delivery(
        self, mock_eval, mock_send, mock_sensor,
    ):
        """Recipient with met conditions proceeds to subscription check."""
        mock_eval.return_value = (True, [(True, "OK")])
        mock_send.return_value = {"delivered": ["svc"], "queued": [], "dropped": []}

        hass = _make_hass_for_service()
        recipients = {
            "r1": {
                "name": "Device",
                "enabled": True,
                "conditions": {
                    "rules": [{"type": "state", "entity_id": "switch.x", "state": "on"}],
                },
            },
        }
        store = _make_store_for_service(recipients)

        # Import and call the service handler internals
        from custom_components.ticker.services import async_setup_services

        # We need to extract the handler. Register then call it.
        await async_setup_services(hass)
        handler = hass.services.async_register.call_args_list[0][0][2]

        call = MagicMock()
        call.data = {
            "category": "cat1",
            "title": "Test",
            "message": "Hello",
        }

        # Mock config entry lookup
        entry = MagicMock()
        entry.state = MagicMock()
        entry.runtime_data.store = store
        with patch(
            "custom_components.ticker.services._get_loaded_entry",
            return_value=entry,
        ):
            await handler(call)

        mock_eval.assert_called_once()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    @patch("custom_components.ticker.services.async_send_to_recipient", new_callable=AsyncMock)
    @patch("custom_components.ticker.services.evaluate_condition_tree")
    async def test_conditions_not_met_skips_delivery(
        self, mock_eval, mock_send, mock_sensor,
    ):
        """Recipient with unmet conditions is skipped and logged."""
        mock_eval.return_value = (False, [(False, "State mismatch")])

        hass = _make_hass_for_service()
        recipients = {
            "r1": {
                "name": "Device",
                "enabled": True,
                "conditions": {
                    "rules": [{"type": "state", "entity_id": "switch.x", "state": "on"}],
                },
            },
        }
        store = _make_store_for_service(recipients)

        await _run_notify_handler(hass, store)

        mock_eval.assert_called_once()
        mock_send.assert_not_awaited()
        # Verify log was created with skipped outcome
        store.async_add_log.assert_awaited_once()
        log_kw = store.async_add_log.call_args[1]
        assert log_kw["outcome"] == "skipped"
        assert "Device conditions" in log_kw["reason"]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    @patch("custom_components.ticker.services.async_send_to_recipient", new_callable=AsyncMock)
    @patch("custom_components.ticker.services.evaluate_condition_tree")
    async def test_no_conditions_no_gate(
        self, mock_eval, mock_send, mock_sensor,
    ):
        """Recipient without conditions skips the gate entirely."""
        mock_send.return_value = {"delivered": ["svc"], "queued": [], "dropped": []}

        hass = _make_hass_for_service()
        recipients = {
            "r1": {
                "name": "Device",
                "enabled": True,
                # No "conditions" key at all
            },
        }
        store = _make_store_for_service(recipients)

        await _run_notify_handler(hass, store)

        mock_eval.assert_not_called()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    @patch("custom_components.ticker.services.async_send_to_recipient", new_callable=AsyncMock)
    @patch("custom_components.ticker.services.evaluate_condition_tree")
    async def test_empty_rules_no_gate(
        self, mock_eval, mock_send, mock_sensor,
    ):
        """Conditions with empty rules list does not trigger the gate."""
        mock_send.return_value = {"delivered": ["svc"], "queued": [], "dropped": []}

        hass = _make_hass_for_service()
        recipients = {
            "r1": {
                "name": "Device",
                "enabled": True,
                "conditions": {"rules": []},
            },
        }
        store = _make_store_for_service(recipients)

        await _run_notify_handler(hass, store)

        mock_eval.assert_not_called()
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    @patch("custom_components.ticker.services.async_send_to_recipient", new_callable=AsyncMock)
    @patch("custom_components.ticker.services.evaluate_condition_tree")
    async def test_dropped_added_when_conditions_not_met(
        self, mock_eval, mock_send, mock_sensor,
    ):
        """Skipped recipient is added to dropped results."""
        mock_eval.return_value = (False, [(False, "Not in time window")])

        hass = _make_hass_for_service()
        recipients = {
            "r1": {
                "name": "Device",
                "enabled": True,
                "conditions": {
                    "rules": [{"type": "time", "after": "08:00", "before": "10:00"}],
                },
            },
        }
        store = _make_store_for_service(recipients)

        await _run_notify_handler(hass, store)

        # The handler should have logged and continued
        store.async_add_log.assert_awaited_once()
        mock_send.assert_not_awaited()


async def _run_notify_handler(hass, store):
    """Helper: register services and invoke the notify handler."""
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    handler = hass.services.async_register.call_args_list[0][0][2]

    call = MagicMock()
    call.data = {
        "category": "cat1",
        "title": "Test",
        "message": "Hello",
    }

    entry = MagicMock()
    entry.runtime_data.store = store
    with patch(
        "custom_components.ticker.services._get_loaded_entry",
        return_value=entry,
    ):
        await handler(call)


# ---------------------------------------------------------------------------
# WebSocket: conditions validation
# ---------------------------------------------------------------------------

class TestWsCreateRecipientConditions:
    """Test conditions validation in ws_create_recipient."""

    @pytest.mark.asyncio
    async def test_create_with_valid_conditions(self):
        """Valid conditions dict accepted."""
        from custom_components.ticker.websocket.recipients import ws_create_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = None
        store.async_create_recipient = AsyncMock(return_value={"recipient_id": "r1"})

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_recipient_id",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_icon",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.sanitize_for_storage",
            return_value="Device",
        ):
            await ws_create_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/create_recipient",
                "recipient_id": "r1",
                "name": "Device",
                "device_type": "push",
                "notify_services": [{"service": "notify.tv", "name": "TV"}],
                "delivery_format": "rich",
                "icon": "mdi:bell-ring",
                "enabled": True,
                "resume_after_tts": False,
                "tts_buffer_delay": 0.5,
                "conditions": {
                    "rules": [{"type": "time", "after": "08:00", "before": "22:00"}],
                },
            })

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        # Verify conditions passed to store
        create_kw = store.async_create_recipient.call_args[1]
        assert create_kw["conditions"]["rules"][0]["type"] == "time"

    @pytest.mark.asyncio
    async def test_create_with_malformed_conditions_rejected(self):
        """Conditions without 'rules' list sends error."""
        from custom_components.ticker.websocket.recipients import ws_create_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = None

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_recipient_id",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.sanitize_for_storage",
            return_value="Device",
        ):
            await ws_create_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/create_recipient",
                "recipient_id": "r1",
                "name": "Device",
                "device_type": "push",
                "notify_services": [{"service": "notify.tv", "name": "TV"}],
                "delivery_format": "rich",
                "icon": "mdi:bell-ring",
                "enabled": True,
                "resume_after_tts": False,
                "tts_buffer_delay": 0.5,
                "conditions": {"bad_key": "no rules"},
            })

        conn.send_error.assert_called_once()
        error_args = conn.send_error.call_args[0]
        assert error_args[1] == "invalid_conditions"

    @pytest.mark.asyncio
    async def test_create_conditions_rules_not_list_rejected(self):
        """Conditions with rules as string (not list) rejected."""
        from custom_components.ticker.websocket.recipients import ws_create_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = None

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_recipient_id",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.sanitize_for_storage",
            return_value="Device",
        ):
            await ws_create_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/create_recipient",
                "recipient_id": "r1",
                "name": "Device",
                "device_type": "push",
                "notify_services": [{"service": "notify.tv", "name": "TV"}],
                "delivery_format": "rich",
                "icon": "mdi:bell-ring",
                "enabled": True,
                "resume_after_tts": False,
                "tts_buffer_delay": 0.5,
                "conditions": {"rules": "not-a-list"},
            })

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "invalid_conditions"

    @pytest.mark.asyncio
    async def test_create_without_conditions_no_error(self):
        """No conditions field is fine (existing behavior)."""
        from custom_components.ticker.websocket.recipients import ws_create_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = None
        store.async_create_recipient = AsyncMock(return_value={"recipient_id": "r1"})

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_recipient_id",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_icon",
            return_value=(True, None),
        ), patch(
            "custom_components.ticker.websocket.recipients.sanitize_for_storage",
            return_value="Device",
        ):
            await ws_create_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/create_recipient",
                "recipient_id": "r1",
                "name": "Device",
                "device_type": "push",
                "notify_services": [{"service": "notify.tv", "name": "TV"}],
                "delivery_format": "rich",
                "icon": "mdi:bell-ring",
                "enabled": True,
                "resume_after_tts": False,
                "tts_buffer_delay": 0.5,
            })

        conn.send_result.assert_called_once()
        create_kw = store.async_create_recipient.call_args[1]
        assert create_kw.get("conditions") is None


class TestWsUpdateRecipientConditions:
    """Test conditions validation in ws_update_recipient."""

    @pytest.mark.asyncio
    async def test_update_add_conditions(self):
        """Adding conditions via update."""
        from custom_components.ticker.websocket.recipients import ws_update_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = {"recipient_id": "r1", "device_type": "push"}
        store.async_update_recipient = AsyncMock(return_value={"recipient_id": "r1"})

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_update_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/update_recipient",
                "recipient_id": "r1",
                "conditions": {
                    "rules": [{"type": "state", "entity_id": "switch.x", "state": "on"}],
                },
            })

        conn.send_result.assert_called_once()
        update_kw = store.async_update_recipient.call_args[1]
        assert "conditions" in update_kw
        assert update_kw["conditions"]["rules"][0]["type"] == "state"

    @pytest.mark.asyncio
    async def test_update_clear_conditions_with_none(self):
        """Setting conditions to None clears them."""
        from custom_components.ticker.websocket.recipients import ws_update_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = {
            "recipient_id": "r1",
            "device_type": "push",
            "conditions": {"rules": []},
        }
        store.async_update_recipient = AsyncMock(return_value={"recipient_id": "r1"})

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_update_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/update_recipient",
                "recipient_id": "r1",
                "conditions": None,
            })

        conn.send_result.assert_called_once()
        update_kw = store.async_update_recipient.call_args[1]
        assert update_kw["conditions"] is None

    @pytest.mark.asyncio
    async def test_update_malformed_conditions_rejected(self):
        """Malformed conditions in update rejected."""
        from custom_components.ticker.websocket.recipients import ws_update_recipient

        hass = MagicMock()
        conn = MagicMock()
        store = MagicMock()
        store.get_recipient.return_value = {"recipient_id": "r1", "device_type": "push"}

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_update_recipient(hass, conn, {
                "id": 1,
                "type": "ticker/update_recipient",
                "recipient_id": "r1",
                "conditions": {"rules": "string-not-list"},
            })

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "invalid_conditions"
