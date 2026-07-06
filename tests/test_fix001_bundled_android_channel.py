"""FIX-001 — per-category Android channel in bundled notifications.

``bundled_notify.async_send_bundled_notification`` injects the primary
category's ``android_channel`` as ``data.channel`` only for single-entry
(``count == 1``) bundles delivered in the rich (Android) format. It uses
``setdefault`` so an already-present channel (e.g. ``ticker_critical``) is
preserved.

Coverage:
- (a) single-entry rich bundle → data.channel == category android_channel
- (b) multi-entry bundle → no channel injected
- (c) plain/iOS format → no channel injected
- (d) existing channel (ticker_critical) preserved via setdefault
Mirrors the delivery-path style of test_bundled_notify.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.bundled_notify import (
    async_send_bundled_notification,
)
from custom_components.ticker.const import DEVICE_MODE_ALL


# ---------------------------------------------------------------------------
# Helpers (parallel to test_bundled_notify.py)
# ---------------------------------------------------------------------------

def _make_entry(
    category_id: str = "security",
    title: str = "Alarm",
    message: str = "Front door opened",
    data: dict | None = None,
) -> dict:
    entry = {
        "category_id": category_id,
        "title": title,
        "message": message,
    }
    if data is not None:
        entry["data"] = data
    return entry


def _make_store(category: dict | None = None) -> MagicMock:
    store = MagicMock()
    store.get_device_preference.return_value = {"mode": DEVICE_MODE_ALL}
    store.get_device_override.return_value = None
    store.get_category.return_value = category or {
        "name": "Security",
        "navigate_to": None,
        "smart_notification": None,
        "android_channel": "security_alerts",
    }
    store.async_add_log = AsyncMock()
    return store


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    person_state = MagicMock()
    person_state.attributes = {"friendly_name": "Hans"}
    hass.states.get.return_value = person_state
    return hass


def _one_android_service():
    return [{"service": "notify.mobile_app_pixel", "name": "Pixel", "device_id": "d1"}]


# ---------------------------------------------------------------------------
# (a) single-entry rich bundle injects the channel
# ---------------------------------------------------------------------------

class TestSingleEntryChannelInjected:

    @pytest.mark.asyncio
    async def test_single_entry_rich_gets_category_channel(self):
        hass = _make_hass()
        store = _make_store()  # android_channel="security_alerts"
        entry = _make_entry()

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=_one_android_service(),
        ), patch(
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=False,
        ):
            result = await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        assert result is True
        service_data = hass.services.async_call.call_args[0][2]
        assert service_data["data"]["channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_single_entry_no_channel_when_category_lacks_it(self):
        hass = _make_hass()
        store = _make_store(category={
            "name": "Security",
            "navigate_to": None,
            "smart_notification": None,
        })
        entry = _make_entry()

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=_one_android_service(),
        ), patch(
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=False,
        ):
            await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        service_data = hass.services.async_call.call_args[0][2]
        assert "channel" not in service_data.get("data", {})


# ---------------------------------------------------------------------------
# (b) multi-entry bundle → no channel (count != 1 gate)
# ---------------------------------------------------------------------------

class TestMultiEntryNoChannel:

    @pytest.mark.asyncio
    async def test_multi_entry_does_not_inject_channel(self):
        hass = _make_hass()
        # Even though every category resolves to one with an android_channel,
        # the count>1 gate must block injection (no single unambiguous channel).
        store = _make_store()  # get_category returns android_channel for all ids
        entries = [
            _make_entry(),
            _make_entry(
                category_id="traffic",
                title="Traffic Jam",
                message="Highway blocked",
            ),
        ]

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=_one_android_service(),
        ), patch(
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=False,
        ):
            await async_send_bundled_notification(
                hass, "person.hans", entries, store
            )

        service_data = hass.services.async_call.call_args[0][2]
        assert "channel" not in service_data.get("data", {})


# ---------------------------------------------------------------------------
# (c) plain / iOS format → no channel
# ---------------------------------------------------------------------------

class TestPlainFormatNoChannel:

    @pytest.mark.asyncio
    async def test_ios_plain_format_does_not_inject_channel(self):
        hass = _make_hass()
        store = _make_store()  # android_channel="security_alerts"
        entry = _make_entry()

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=_one_android_service(),
        ), patch(
            # iOS device → rich flips to plain, so channel must NOT be set.
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=True,
        ):
            await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        service_data = hass.services.async_call.call_args[0][2]
        assert "channel" not in service_data.get("data", {})


# ---------------------------------------------------------------------------
# (d) existing channel preserved via setdefault
# ---------------------------------------------------------------------------

class TestCriticalChannelPreserved:

    @pytest.mark.asyncio
    async def test_existing_ticker_critical_channel_is_preserved(self):
        hass = _make_hass()
        store = _make_store()  # category android_channel="security_alerts"
        # The queued entry already carries a critical channel.
        entry = _make_entry(data={"channel": "ticker_critical"})

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=_one_android_service(),
        ), patch(
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=False,
        ):
            await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        service_data = hass.services.async_call.call_args[0][2]
        # setdefault must not overwrite the pre-existing critical channel.
        assert service_data["data"]["channel"] == "ticker_critical"
