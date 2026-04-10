"""Tests for custom_components.ticker.bundled_notify module.

Covers BUG-080 fixes: single-entry data preservation, multi-entry no-data,
per-device data isolation, and injected field layering.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.bundled_notify import (
    async_send_bundled_notification,
)
from custom_components.ticker.const import (
    DEVICE_MODE_ALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    category_id: str = "weather",
    title: str = "Rain Alert",
    message: str = "It is raining",
    data: dict | None = None,
) -> dict:
    """Create a minimal queued notification entry."""
    entry = {
        "category_id": category_id,
        "title": title,
        "message": message,
    }
    if data is not None:
        entry["data"] = data
    return entry


def _make_store(
    category: dict | None = None,
    device_pref_mode: str = DEVICE_MODE_ALL,
) -> MagicMock:
    """Create a mock TickerStore."""
    store = MagicMock()
    store.get_device_preference.return_value = {"mode": device_pref_mode}
    store.get_device_override.return_value = None
    store.get_category.return_value = category or {
        "name": "Weather",
        "navigate_to": None,
        "smart_notification": None,
    }
    store.async_add_log = AsyncMock()
    return store


def _make_hass() -> MagicMock:
    """Create a minimal mocked HomeAssistant."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    person_state = MagicMock()
    person_state.attributes = {"friendly_name": "Hans"}
    hass.states.get.return_value = person_state
    return hass


def _one_android_service():
    """Return a single Android notify service list."""
    return [{"service": "notify.mobile_app_pixel", "name": "Pixel", "device_id": "d1"}]


# ---------------------------------------------------------------------------
# BUG-080: Single-entry data preservation
# ---------------------------------------------------------------------------

class TestSingleEntryDataPreservation:
    """BUG-080: When a bundled notification has one entry, original data fields
    like image, url, and custom keys must survive into the final payload."""

    @pytest.mark.asyncio
    async def test_single_entry_image_survives(self):
        """Image key from queued entry data flows into service call."""
        hass = _make_hass()
        store = _make_store()
        entry = _make_entry(data={"image": "http://img.png/photo.jpg"})

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
        call_args = hass.services.async_call.call_args
        service_data = call_args[0][2]
        assert service_data["data"]["image"] == "http://img.png/photo.jpg"

    @pytest.mark.asyncio
    async def test_single_entry_custom_keys_survive(self):
        """Arbitrary custom data keys from the queued entry survive."""
        hass = _make_hass()
        store = _make_store()
        entry = _make_entry(data={"custom_key": "custom_value", "priority": "high"})

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
        assert service_data["data"]["custom_key"] == "custom_value"
        assert service_data["data"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_single_entry_no_data_key(self):
        """Entry without data key does not crash (defaults to empty dict)."""
        hass = _make_hass()
        store = _make_store()
        entry = _make_entry(data=None)

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

    @pytest.mark.asyncio
    async def test_single_entry_data_none_value(self):
        """Entry with data=None seeds empty enriched_data, no KeyError."""
        hass = _make_hass()
        store = _make_store()
        entry = {"category_id": "weather", "title": "T", "message": "M", "data": None}

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


# ---------------------------------------------------------------------------
# BUG-080: Multi-entry bundle has no per-entry data
# ---------------------------------------------------------------------------

class TestMultiEntryNoData:
    """Multi-entry bundles generate a summary; no per-entry data is carried."""

    @pytest.mark.asyncio
    async def test_multi_entry_no_entry_data_in_payload(self):
        """Two-entry bundle should NOT carry per-entry data."""
        hass = _make_hass()
        store = _make_store()
        entries = [
            _make_entry(data={"image": "http://a.png"}),
            _make_entry(
                category_id="traffic",
                title="Traffic Jam",
                message="Highway blocked",
                data={"image": "http://b.png"},
            ),
        ]
        store.get_category.side_effect = lambda cid: {
            "weather": {"name": "Weather", "navigate_to": None, "smart_notification": None},
            "traffic": {"name": "Traffic", "navigate_to": None, "smart_notification": None},
        }.get(cid)

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
        # Multi-entry summary: data should NOT contain per-entry image keys
        data = service_data.get("data", {})
        assert "image" not in data

    @pytest.mark.asyncio
    async def test_multi_entry_summary_title(self):
        """Multi-entry bundle uses count-based summary title."""
        hass = _make_hass()
        store = _make_store()
        entries = [
            _make_entry(),
            _make_entry(title="Second"),
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
        assert service_data["title"] == "You have 2 notifications"


# ---------------------------------------------------------------------------
# BUG-080: Per-device data isolation (no cross-device mutation)
# ---------------------------------------------------------------------------

class TestPerDeviceDataIsolation:
    """Each device gets its own copy of enriched_data so inject_navigate_to
    and inject_smart_notification do not leak between devices."""

    @pytest.mark.asyncio
    async def test_two_devices_get_independent_data(self):
        """Navigate-to injection on device 1 must not affect device 2."""
        hass = _make_hass()
        store = _make_store()
        entry = _make_entry(data={"image": "http://img.png"})

        two_services = [
            {"service": "notify.mobile_app_pixel", "name": "Pixel", "device_id": "d1"},
            {"service": "notify.mobile_app_ipad", "name": "iPad", "device_id": "d2"},
        ]

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=two_services,
        ), patch(
            "custom_components.ticker.bundled_notify.resolve_ios_platform",
            return_value=False,
        ):
            await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        # Two calls, one per device
        assert hass.services.async_call.call_count == 2
        call1_data = hass.services.async_call.call_args_list[0][0][2].get("data", {})
        call2_data = hass.services.async_call.call_args_list[1][0][2].get("data", {})

        # Both should have the image from the original entry
        assert call1_data.get("image") == "http://img.png"
        assert call2_data.get("image") == "http://img.png"

        # Both should have navigate_to injected independently
        assert "clickAction" in call1_data
        assert "clickAction" in call2_data


# ---------------------------------------------------------------------------
# Injected fields layered on top of original data (single-entry)
# ---------------------------------------------------------------------------

class TestInjectedFieldsOnTopOfData:
    """Verify that navigate_to and smart_notification fields are added
    on top of preserved original data, not replacing it."""

    @pytest.mark.asyncio
    async def test_navigate_to_added_alongside_image(self):
        """Single entry with image data also gets clickAction injected."""
        hass = _make_hass()
        store = _make_store(category={
            "name": "Weather",
            "navigate_to": "/weather-dashboard",
            "smart_notification": None,
        })
        entry = _make_entry(data={"image": "http://img.png"})

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
        data = service_data["data"]
        # Original image preserved
        assert data["image"] == "http://img.png"
        # Navigate-to injected
        assert data["clickAction"] == "/weather-dashboard"

    @pytest.mark.asyncio
    async def test_smart_notification_added_alongside_data(self):
        """Single entry with data also gets smart notification fields."""
        hass = _make_hass()
        store = _make_store(category={
            "name": "Weather",
            "navigate_to": None,
            "smart_notification": {
                "group": True,
                "tag_mode": "category",
                "sticky": True,
            },
        })
        entry = _make_entry(data={"image": "http://img.png"})

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
        data = service_data["data"]
        # Original image preserved
        assert data["image"] == "http://img.png"
        # Smart notification fields injected
        assert data["group"] == "ticker_weather"
        assert data["sticky"] == "true"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestBundledEdgeCases:
    """Edge case coverage for bundled notification dispatch."""

    @pytest.mark.asyncio
    async def test_empty_entries_returns_true(self):
        """Empty entries list is a no-op success."""
        hass = _make_hass()
        store = _make_store()
        result = await async_send_bundled_notification(
            hass, "person.hans", [], store
        )
        assert result is True
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_services_returns_false(self):
        """No notify services for person returns failure."""
        hass = _make_hass()
        store = _make_store()
        entry = _make_entry()

        with patch(
            "custom_components.ticker.bundled_notify.async_get_notify_services_for_person",
            return_value=[],
        ):
            result = await async_send_bundled_notification(
                hass, "person.hans", [entry], store
            )

        assert result is False
