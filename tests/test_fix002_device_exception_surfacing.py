"""FIX-002 (v1.8.2) — surface escaped device-dispatch exceptions.

PRs #49/#50 fan the per-device notify sends out via ``asyncio.gather`` inside
``async_send_notification``. Each ``_send_to_device`` coroutine owns an inner
try/except around the actual ``notify.*`` service call — but the payload-build
block (format detection, transform, injection) runs BEFORE that try. An
exception there would escape the coroutine.

FIX-002 captures the ``gather(return_exceptions=True)`` results and, for any
coroutine that raised, logs an error and appends ``f"{service_id}: {outcome}"``
to ``results["dropped"]`` — and crucially the failure of one device does NOT
abort the fan-out to the others.

These tests raise from the pre-send payload-build step (``detect_delivery_format``)
for exactly one service_id and assert the surfaced-drop, the error log, and that
sibling devices still deliver.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.user_notify import async_send_notification
from custom_components.ticker.const import (
    DELIVERY_FORMAT_RICH,
    DEVICE_MODE_ALL,
)


# ---------------------------------------------------------------------------
# Helpers (mirrors test_user_notify.py)
# ---------------------------------------------------------------------------

def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_store() -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    store.is_snoozed.return_value = False
    store.get_device_preference.return_value = {"mode": DEVICE_MODE_ALL}
    store.get_device_override.return_value = None
    store.get_category.return_value = None
    return store


def _services_list(service_ids: list[str]) -> list[dict]:
    return [
        {"service": s, "name": s, "device_id": f"dev_{i}"}
        for i, s in enumerate(service_ids)
    ]


def _detect_raising_for(bad_service: str, boom: Exception):
    """Return a detect_delivery_format side-effect that raises for one svc."""
    def _side_effect(service_id: str):
        if service_id == bad_service:
            raise boom
        return DELIVERY_FORMAT_RICH
    return _side_effect


# ---------------------------------------------------------------------------
# FIX-002 — escaped device-exception surfacing
# ---------------------------------------------------------------------------

class TestDeviceExceptionSurfacing:
    """Tests for surfacing exceptions escaping a device coroutine."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_payload_build_exception_surfaced_in_dropped(
        self, mock_ios, mock_detect, mock_discover,
    ):
        """A raise in the pre-send block lands in results['dropped']."""
        mock_discover.return_value = _services_list(["notify.good", "notify.bad"])
        mock_detect.side_effect = _detect_raising_for(
            "notify.bad", RuntimeError("payload boom"),
        )
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={}, notification_id="n1",
        )

        dropped = result["dropped"]
        assert any(d.startswith("notify.bad:") for d in dropped)
        assert any("payload boom" in d for d in dropped)

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_other_devices_still_deliver(
        self, mock_ios, mock_detect, mock_discover,
    ):
        """One device's escaped exception must not abort the fan-out."""
        mock_discover.return_value = _services_list(["notify.good", "notify.bad"])
        mock_detect.side_effect = _detect_raising_for(
            "notify.bad", RuntimeError("payload boom"),
        )
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={}, notification_id="n1",
        )

        # Healthy sibling still went out.
        assert result["delivered"] == ["notify.good"]
        # The good device's notify service was actually called once.
        assert hass.services.async_call.await_count == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_escaped_exception_logged_at_error(
        self, mock_ios, mock_detect, mock_discover, caplog,
    ):
        """The escaped exception is logged at ERROR level."""
        mock_discover.return_value = _services_list(["notify.good", "notify.bad"])
        mock_detect.side_effect = _detect_raising_for(
            "notify.bad", RuntimeError("payload boom"),
        )
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        with caplog.at_level(logging.ERROR, logger="custom_components.ticker.user_notify"):
            await async_send_notification(
                hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
                data={}, notification_id="n1",
            )

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log for the escaped exception"
        assert any(
            "Device dispatch failed" in r.getMessage() and "notify.bad" in r.getMessage()
            for r in error_records
        )

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_single_device_exception_surfaced(
        self, mock_ios, mock_detect, mock_discover,
    ):
        """With a single failing device, dropped carries it and nothing delivers."""
        mock_discover.return_value = _services_list(["notify.bad"])
        mock_detect.side_effect = _detect_raising_for(
            "notify.bad", ValueError("bad transform"),
        )
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
            data={}, notification_id="n1",
        )

        assert result["delivered"] == []
        assert len(result["dropped"]) == 1
        assert result["dropped"][0].startswith("notify.bad:")
        assert "bad transform" in result["dropped"][0]
        # No notify service ever ran (raise happened before the send).
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("custom_components.ticker.user_notify.async_get_notify_services_for_person", new_callable=AsyncMock)
    @patch("custom_components.ticker.user_notify.detect_delivery_format")
    @patch("custom_components.ticker.user_notify.resolve_ios_platform")
    async def test_transform_exception_also_surfaced(
        self, mock_ios, mock_detect, mock_discover,
    ):
        """A raise from transform_payload_for_format is surfaced too."""
        mock_discover.return_value = _services_list(["notify.good", "notify.bad"])
        mock_detect.return_value = DELIVERY_FORMAT_RICH
        mock_ios.return_value = False

        hass = _make_hass()
        store = _make_store()

        # transform runs in every device's pre-send build block; failing it
        # for all services proves each escaped exception is surfaced and that
        # gather did not abort on the first raise.
        with patch(
            "custom_components.ticker.user_notify.transform_payload_for_format",
            side_effect=RuntimeError("transform boom"),
        ):
            result = await async_send_notification(
                hass, store, "person.alice", "Alice", "cat1", "Title", "Msg",
                data={}, notification_id="n1",
            )

        # Both devices raised in the build step; both surface as drops and
        # gather did not abort early (order preserved, two entries).
        assert len(result["dropped"]) == 2
        assert all("transform boom" in d for d in result["dropped"])
        assert result["delivered"] == []
