"""Tests for BUG-082: ws_create_recipient conditions=None rejection.

The frontend sends conditions=null when creating a recipient without
conditions. Before the fix, the voluptuous schema rejected null because
it only accepted dict. The fix changed to vol.Any(dict, None).

These tests verify the handler logic correctly handles:
1. conditions=None (explicit null) -- the bug scenario
2. conditions=<valid dict> -- existing behavior preserved
3. conditions omitted entirely -- existing behavior preserved
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.websocket.recipients import ws_create_recipient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_msg(**overrides) -> dict:
    """Build a minimal valid ws_create_recipient message dict.

    Push-type recipient with all required fields populated.
    """
    msg = {
        "id": 1,
        "type": "ticker/create_recipient",
        "recipient_id": "test_device",
        "name": "Test Device",
        "device_type": "push",
        "notify_services": [{"service": "notify.mobile", "name": "Phone"}],
        "delivery_format": "rich",
        "icon": "mdi:bell-ring",
        "enabled": True,
        "resume_after_tts": False,
        "tts_buffer_delay": 0.5,
    }
    msg.update(overrides)
    return msg


def _make_mocks():
    """Create hass, connection, and store mocks with standard stubs."""
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.get_recipient.return_value = None
    store.async_create_recipient = AsyncMock(
        return_value={"recipient_id": "test_device"}
    )
    return hass, conn, store


def _standard_patches(store):
    """Return a context-manager stack patching validation helpers."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
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
            return_value="Test Device",
        ):
            yield

    return _ctx()


# ---------------------------------------------------------------------------
# BUG-082: conditions=None must not raise or send error
# ---------------------------------------------------------------------------

class TestBug082ConditionsNull:
    """Regression tests for BUG-082: null conditions on create_recipient."""

    @pytest.mark.asyncio
    async def test_conditions_none_succeeds(self):
        """conditions=None (explicit null from frontend) must succeed.

        This is the exact scenario reported in BUG-082: the frontend
        sends {conditions: null} and the old schema rejected it.
        """
        hass, conn, store = _make_mocks()

        with _standard_patches(store):
            await ws_create_recipient(hass, conn, _base_msg(conditions=None))

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        # Verify conditions=None passed through to store
        create_kwargs = store.async_create_recipient.call_args[1]
        assert create_kwargs["conditions"] is None

    @pytest.mark.asyncio
    async def test_conditions_valid_dict_succeeds(self):
        """A valid conditions dict with rules list still works."""
        hass, conn, store = _make_mocks()
        conditions = {
            "rules": [{"type": "time", "after": "08:00", "before": "22:00"}],
        }

        with _standard_patches(store):
            await ws_create_recipient(hass, conn, _base_msg(conditions=conditions))

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        create_kwargs = store.async_create_recipient.call_args[1]
        assert create_kwargs["conditions"] == conditions

    @pytest.mark.asyncio
    async def test_conditions_omitted_succeeds(self):
        """Omitting conditions entirely must succeed (no key in msg)."""
        hass, conn, store = _make_mocks()

        with _standard_patches(store):
            await ws_create_recipient(hass, conn, _base_msg())

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        create_kwargs = store.async_create_recipient.call_args[1]
        assert create_kwargs["conditions"] is None

    @pytest.mark.asyncio
    async def test_conditions_none_does_not_call_get_on_none(self):
        """When conditions is None, the handler must not call .get() on it.

        This verifies the guard `if conditions is not None:` works.
        A regression would raise AttributeError: 'NoneType' has no
        attribute 'get'.
        """
        hass, conn, store = _make_mocks()

        with _standard_patches(store):
            # Should not raise AttributeError
            await ws_create_recipient(hass, conn, _base_msg(conditions=None))

        # If we got here without exception, the guard works
        conn.send_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_conditions_empty_dict_accepted(self):
        """BUG-093: empty dict {} normalizes to None (same as no conditions)."""
        hass, conn, store = _make_mocks()

        with _standard_patches(store):
            await ws_create_recipient(hass, conn, _base_msg(conditions={}))

        # Empty dict now accepted (normalized to None)
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_conditions_with_condition_tree_succeeds(self):
        """Conditions using condition_tree format also accepted."""
        hass, conn, store = _make_mocks()
        conditions = {
            "condition_tree": {
                "operator": "AND",
                "conditions": [
                    {"type": "time", "after": "09:00", "before": "17:00"},
                ],
            },
        }

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
            return_value="Test Device",
        ), patch(
            "custom_components.ticker.websocket.recipients.validate_condition_tree",
            return_value=None,  # None means valid
        ):
            await ws_create_recipient(hass, conn, _base_msg(conditions=conditions))

        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
