"""Tests for F-3 Automations Manager WebSocket commands.

Covers:
- ws_automations_scan returns filtered findings (ticker.notify only)
- ws_automations_update updates finding and returns success
- ws_automations_update handles invalid source_type gracefully
- _is_ticker_call filter logic
- _build_updated_action construction
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.websocket.automations import (
    ws_automations_scan,
    ws_automations_update,
    _is_ticker_call,
    _build_updated_action,
)


# ---------------------------------------------------------------------------
# _is_ticker_call
# ---------------------------------------------------------------------------

class TestIsTickerCall:
    """Test the ticker.notify service filter."""

    def test_ticker_dot_notify(self):
        assert _is_ticker_call({"service": "ticker.notify"}) is True

    def test_ticker_slash_notify(self):
        assert _is_ticker_call({"service": "ticker/notify"}) is True

    def test_other_service(self):
        assert _is_ticker_call({"service": "notify.mobile_app"}) is False

    def test_empty_service(self):
        assert _is_ticker_call({"service": ""}) is False

    def test_missing_service_key(self):
        assert _is_ticker_call({}) is False


# ---------------------------------------------------------------------------
# ws_automations_scan
# ---------------------------------------------------------------------------

class TestWsAutomationsScan:
    """Test scan WS handler."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.async_scan_for_notifications")
    async def test_returns_filtered_findings(self, mock_scan):
        """Only ticker.notify findings are returned."""
        mock_scan.return_value = [
            {"service": "ticker.notify", "source_id": "auto.1"},
            {"service": "notify.mobile_app", "source_id": "auto.2"},
            {"service": "ticker/notify", "source_id": "auto.3"},
        ]

        hass = MagicMock()
        conn = MagicMock()
        msg = {"id": 1, "type": "ticker/automations/scan"}

        await ws_automations_scan(hass, conn, msg)

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert len(result["findings"]) == 2
        services = [f["service"] for f in result["findings"]]
        assert "ticker.notify" in services
        assert "ticker/notify" in services
        assert "notify.mobile_app" not in services

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.async_scan_for_notifications")
    async def test_empty_scan_results(self, mock_scan):
        """No findings -> empty list returned."""
        mock_scan.return_value = []

        hass = MagicMock()
        conn = MagicMock()
        msg = {"id": 1, "type": "ticker/automations/scan"}

        await ws_automations_scan(hass, conn, msg)

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result["findings"] == []

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.async_scan_for_notifications")
    async def test_scan_error_sends_error(self, mock_scan):
        """Exception during scan sends error to connection."""
        from homeassistant.exceptions import HomeAssistantError
        mock_scan.side_effect = HomeAssistantError("Scan broke")

        hass = MagicMock()
        conn = MagicMock()
        msg = {"id": 1, "type": "ticker/automations/scan"}

        await ws_automations_scan(hass, conn, msg)

        conn.send_error.assert_called_once()
        error_args = conn.send_error.call_args[0]
        assert error_args[1] == "scan_failed"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.async_scan_for_notifications")
    async def test_scan_unexpected_error(self, mock_scan):
        """Unexpected exception is caught and sent as error."""
        mock_scan.side_effect = RuntimeError("unexpected")

        hass = MagicMock()
        conn = MagicMock()
        msg = {"id": 1, "type": "ticker/automations/scan"}

        await ws_automations_scan(hass, conn, msg)

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "scan_failed"


# ---------------------------------------------------------------------------
# ws_automations_update
# ---------------------------------------------------------------------------

class TestWsAutomationsUpdate:
    """Test update WS handler."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.converter.apply_to_automation", new_callable=AsyncMock, create=True)
    async def test_update_automation_success(self, mock_apply):
        """Valid update to an automation returns success."""
        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "automation",
                "source_id": "automation.test",
                "source_file": "automations.yaml",
                "action_path": "action.0",
                "action_index": 0,
                "service": "ticker.notify",
            },
            "category": "alerts",
            "title": "Test Alert",
            "message": "Something happened",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result["success"] is True
        mock_apply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_invalid_source_type(self):
        """Invalid source_type sends error."""
        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "invalid_type",
                "source_id": "test",
                "source_file": "test.yaml",
                "action_path": "action.0",
                "action_index": 0,
                "service": "ticker.notify",
            },
            "category": "alerts",
            "title": "Test",
            "message": "Hello",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_error.assert_called_once()
        error_args = conn.send_error.call_args[0]
        assert error_args[1] == "invalid_finding"

    @pytest.mark.asyncio
    async def test_update_not_ticker_call(self):
        """Finding with non-ticker service sends error."""
        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "automation",
                "source_id": "test",
                "source_file": "test.yaml",
                "action_path": "action.0",
                "action_index": 0,
                "service": "notify.mobile_app",
            },
            "category": "alerts",
            "title": "Test",
            "message": "Hello",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_error.assert_called_once()
        error_args = conn.send_error.call_args[0]
        assert error_args[1] == "not_ticker_call"

    @pytest.mark.asyncio
    async def test_update_empty_category_rejected(self):
        """Empty category after sanitization sends error."""
        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "automation",
                "source_id": "test",
                "source_file": "test.yaml",
                "action_path": "action.0",
                "action_index": 0,
                "service": "ticker.notify",
            },
            "category": "   ",  # whitespace only
            "title": "Test",
            "message": "Hello",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "invalid_category"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.converter.apply_to_script", new_callable=AsyncMock, create=True)
    async def test_update_script_source(self, mock_apply):
        """Script source_type dispatches to apply_to_script."""
        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "script",
                "source_id": "script.test",
                "source_file": "scripts.yaml",
                "action_path": "sequence.0",
                "action_index": 0,
                "service": "ticker.notify",
            },
            "category": "alerts",
            "title": "Test",
            "message": "Hello",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_result.assert_called_once()
        mock_apply.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.migrate.converter.apply_to_automation", new_callable=AsyncMock, create=True)
    async def test_update_apply_failure(self, mock_apply):
        """Exception during apply sends error."""
        mock_apply.side_effect = RuntimeError("write failed")

        hass = MagicMock()
        conn = MagicMock()
        msg = {
            "id": 1,
            "type": "ticker/automations/update",
            "finding": {
                "source_type": "automation",
                "source_id": "automation.test",
                "source_file": "automations.yaml",
                "action_path": "action.0",
                "action_index": 0,
                "service": "ticker.notify",
            },
            "category": "alerts",
            "title": "Test",
            "message": "Hello",
        }

        await ws_automations_update(hass, conn, msg)

        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "update_failed"


# ---------------------------------------------------------------------------
# _build_updated_action
# ---------------------------------------------------------------------------

class TestBuildUpdatedAction:
    """Test the action dict builder."""

    def test_basic_action(self):
        """Basic action with category, title, message."""
        finding = {
            "service": "ticker.notify",
            "service_data": {},
        }
        action = _build_updated_action(finding, "alerts", "Title", "Msg", None)
        assert action["service"] == "ticker.notify"
        assert action["data"]["category"] == "alerts"
        assert action["data"]["title"] == "Title"
        assert action["data"]["message"] == "Msg"
        assert "alias" not in action

    def test_preserves_alias(self):
        """Alias from finding is preserved in new action."""
        finding = {
            "service": "ticker.notify",
            "service_data": {},
            "action_alias": "Send alert",
        }
        action = _build_updated_action(finding, "alerts", "T", "M", None)
        assert action["alias"] == "Send alert"

    def test_merges_image_from_extra_data(self):
        """Image from extra_data is merged into action data."""
        finding = {"service": "ticker.notify", "service_data": {}}
        extra = {"image": "https://example.com/img.png"}
        action = _build_updated_action(finding, "cat", "T", "M", extra)
        assert action["data"]["data"]["image"] == "https://example.com/img.png"

    def test_clears_image_when_empty(self):
        """Empty image in extra_data removes image from merged data."""
        finding = {
            "service": "ticker.notify",
            "service_data": {"data": {"image": "old.png"}},
        }
        extra = {"image": ""}
        action = _build_updated_action(finding, "cat", "T", "M", extra)
        assert "image" not in action["data"].get("data", {})

    def test_preserves_existing_data_keys(self):
        """Existing data sub-keys not exposed by UI are preserved."""
        finding = {
            "service": "ticker.notify",
            "service_data": {"data": {"custom_key": "value"}},
        }
        action = _build_updated_action(finding, "cat", "T", "M", None)
        assert action["data"]["data"]["custom_key"] == "value"

    def test_no_data_key_when_empty(self):
        """No data sub-dict when merged data is empty."""
        finding = {"service": "ticker.notify", "service_data": {}}
        action = _build_updated_action(finding, "cat", "T", "M", None)
        assert "data" not in action["data"] or action["data"].get("data") is None
