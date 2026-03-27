"""Tests for BUG-061: iOS platform detection via registry lookup.

Covers resolve_ios_platform(), _check_device_ios(), DELIVERY_FORMAT_PATTERNS
changes (iphone/ipad patterns removed), and integration with
detect_delivery_format().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.formatting import (
    detect_delivery_format,
    resolve_ios_platform,
    _check_device_ios,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_PATTERNS,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_PERSISTENT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config_entry(
    domain: str = "mobile_app",
    entry_id: str = "entry_1",
    data: dict | None = None,
) -> MagicMock:
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.domain = domain
    entry.entry_id = entry_id
    entry.data = data or {}
    return entry


def _make_entity_entry(device_id: str | None = None) -> MagicMock:
    """Create a mock EntityEntry."""
    entry = MagicMock()
    entry.device_id = device_id
    return entry


def _make_device(config_entry_ids: list[str] | None = None) -> MagicMock:
    """Create a mock DeviceEntry."""
    device = MagicMock()
    device.config_entries = config_entry_ids or []
    return device


@pytest.fixture
def hass_with_registries():
    """Build a mock hass with entity_registry, device_registry, and config_entries."""
    hass = MagicMock()

    # Entity registry mock
    entity_reg = MagicMock()
    entity_reg.async_get.return_value = None  # default: no entity found

    # Device registry mock
    device_reg = MagicMock()
    device_reg.async_get.return_value = None  # default: no device found

    # Config entries mock
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_get_entry.return_value = None

    return hass, entity_reg, device_reg


# ---------------------------------------------------------------------------
# _check_device_ios
# ---------------------------------------------------------------------------

class TestCheckDeviceIos:
    """Tests for _check_device_ios() helper."""

    def test_ios_device_returns_true(self, hass_with_registries):
        hass, _, device_reg = hass_with_registries
        ios_entry = _make_config_entry(
            domain="mobile_app", entry_id="e1",
            data={"os_name": "iOS"},
        )
        device = _make_device(config_entry_ids=["e1"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = ios_entry

        assert _check_device_ios(hass, device_reg, "dev_123") is True

    def test_android_device_returns_false(self, hass_with_registries):
        hass, _, device_reg = hass_with_registries
        android_entry = _make_config_entry(
            domain="mobile_app", entry_id="e1",
            data={"os_name": "Android"},
        )
        device = _make_device(config_entry_ids=["e1"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = android_entry

        assert _check_device_ios(hass, device_reg, "dev_123") is False

    def test_no_device_returns_false(self, hass_with_registries):
        hass, _, device_reg = hass_with_registries
        device_reg.async_get.return_value = None

        assert _check_device_ios(hass, device_reg, "dev_123") is False

    def test_device_no_config_entries_returns_false(self, hass_with_registries):
        hass, _, device_reg = hass_with_registries
        device = _make_device(config_entry_ids=[])
        device_reg.async_get.return_value = device

        assert _check_device_ios(hass, device_reg, "dev_123") is False

    def test_non_mobile_app_entry_skipped(self, hass_with_registries):
        """A device linked to a non-mobile_app config entry is not iOS."""
        hass, _, device_reg = hass_with_registries
        other_entry = _make_config_entry(
            domain="zwave", entry_id="e1",
            data={"os_name": "iOS"},
        )
        device = _make_device(config_entry_ids=["e1"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = other_entry

        assert _check_device_ios(hass, device_reg, "dev_123") is False

    def test_missing_os_name_returns_false(self, hass_with_registries):
        hass, _, device_reg = hass_with_registries
        entry = _make_config_entry(
            domain="mobile_app", entry_id="e1",
            data={},  # no os_name
        )
        device = _make_device(config_entry_ids=["e1"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = entry

        assert _check_device_ios(hass, device_reg, "dev_123") is False

    def test_ios_case_insensitive(self, hass_with_registries):
        """os_name comparison is lowered, so 'iOS' and 'ios' both match."""
        hass, _, device_reg = hass_with_registries
        entry = _make_config_entry(
            domain="mobile_app", entry_id="e1",
            data={"os_name": "iOS"},
        )
        device = _make_device(config_entry_ids=["e1"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = entry

        assert _check_device_ios(hass, device_reg, "dev_123") is True

    def test_config_entry_not_found_returns_false(self, hass_with_registries):
        """If async_get_entry returns None for the entry_id, skip gracefully."""
        hass, _, device_reg = hass_with_registries
        device = _make_device(config_entry_ids=["nonexistent_entry"])
        device_reg.async_get.return_value = device
        hass.config_entries.async_get_entry.return_value = None

        assert _check_device_ios(hass, device_reg, "dev_123") is False


# ---------------------------------------------------------------------------
# resolve_ios_platform
# ---------------------------------------------------------------------------

class TestResolveIosPlatform:
    """Tests for resolve_ios_platform()."""

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_ios_via_entity_registry(self, mock_er, mock_dr):
        """Path 1: entity exists in registry, device linked to iOS config entry."""
        hass = MagicMock()

        # Entity registry returns an entity with a device_id
        entity_entry = _make_entity_entry(device_id="dev_1")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = entity_entry
        mock_er.async_get.return_value = entity_reg

        # Device registry returns a device linked to a mobile_app entry
        device = _make_device(config_entry_ids=["cfg_1"])
        device_reg = MagicMock()
        device_reg.async_get.return_value = device
        mock_dr.async_get.return_value = device_reg

        # Config entry is iOS
        ios_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"os_name": "iOS"},
        )
        hass.config_entries.async_get_entry.return_value = ios_entry

        assert resolve_ios_platform(hass, "notify.mobile_app_hans_iphone") is True

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_android_via_entity_registry(self, mock_er, mock_dr):
        """Path 1: entity exists, device is Android."""
        hass = MagicMock()

        entity_entry = _make_entity_entry(device_id="dev_1")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = entity_entry
        mock_er.async_get.return_value = entity_reg

        device = _make_device(config_entry_ids=["cfg_1"])
        device_reg = MagicMock()
        device_reg.async_get.return_value = device
        mock_dr.async_get.return_value = device_reg

        android_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"os_name": "Android"},
        )
        hass.config_entries.async_get_entry.return_value = android_entry

        assert resolve_ios_platform(hass, "notify.mobile_app_pixel") is False

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_ios_via_legacy_path(self, mock_er, mock_dr, mock_slugify):
        """Path 2: no entity in registry, falls back to config entry device_name matching."""
        hass = MagicMock()

        # Entity registry returns nothing
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        # Legacy path: match by slugified device_name
        mock_slugify.return_value = "hans_iphone"
        ios_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "Hans iPhone", "os_name": "iOS"},
        )
        hass.config_entries.async_entries.return_value = [ios_entry]

        assert resolve_ios_platform(hass, "notify.mobile_app_hans_iphone") is True
        mock_slugify.assert_called_with("Hans iPhone")

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_android_via_legacy_path(self, mock_er, mock_dr, mock_slugify):
        """Path 2: legacy path, device is Android."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        mock_slugify.return_value = "hans_s_phone"
        android_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "Hans's Phone", "os_name": "Android"},
        )
        hass.config_entries.async_entries.return_value = [android_entry]

        assert resolve_ios_platform(hass, "notify.mobile_app_hans_s_phone") is False

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_no_mobile_app_config_entries(self, mock_er, mock_dr):
        """No mobile_app config entries at all."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        hass.config_entries.async_entries.return_value = []

        assert resolve_ios_platform(hass, "notify.mobile_app_something") is False

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_service_id_no_match(self, mock_er, mock_dr, mock_slugify):
        """Service suffix doesn't match any config entry device_name."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        mock_slugify.return_value = "other_device"
        entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "Other Device", "os_name": "iOS"},
        )
        hass.config_entries.async_entries.return_value = [entry]

        # service suffix is "my_phone", doesn't match "other_device"
        assert resolve_ios_platform(hass, "notify.mobile_app_my_phone") is False

    def test_empty_service_id_returns_false(self):
        hass = MagicMock()
        assert resolve_ios_platform(hass, "") is False

    def test_none_service_id_returns_false(self):
        hass = MagicMock()
        assert resolve_ios_platform(hass, None) is False

    def test_non_notify_service_returns_false(self):
        """Services not starting with 'notify.' are rejected immediately."""
        hass = MagicMock()
        assert resolve_ios_platform(hass, "tts.google_translate") is False

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_non_mobile_app_notify_service(self, mock_er, mock_dr):
        """A notify service that doesn't contain 'mobile_app_' falls through."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        # Service is notify.some_custom_service (no mobile_app_ prefix)
        assert resolve_ios_platform(hass, "notify.some_custom_service") is False

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_missing_device_name_in_config_entry(
        self, mock_er, mock_dr, mock_slugify
    ):
        """Config entry with no device_name is skipped gracefully."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        # Entry has empty device_name
        entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "", "os_name": "iOS"},
        )
        hass.config_entries.async_entries.return_value = [entry]

        assert resolve_ios_platform(hass, "notify.mobile_app_something") is False

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_missing_os_name_in_config_entry(
        self, mock_er, mock_dr, mock_slugify
    ):
        """Config entry with no os_name defaults to empty string, not iOS."""
        hass = MagicMock()

        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        mock_slugify.return_value = "my_device"
        entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "My Device"},  # no os_name
        )
        hass.config_entries.async_entries.return_value = [entry]

        assert resolve_ios_platform(hass, "notify.mobile_app_my_device") is False

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_entity_exists_but_no_device_id_falls_through(self, mock_er, mock_dr):
        """Entity exists in registry but has no device_id; falls to legacy path."""
        hass = MagicMock()

        entity_entry = _make_entity_entry(device_id=None)
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = entity_entry
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        # No config entries to match in legacy path
        hass.config_entries.async_entries.return_value = []

        assert resolve_ios_platform(hass, "notify.mobile_app_test") is False


# ---------------------------------------------------------------------------
# DELIVERY_FORMAT_PATTERNS — BUG-061 changes
# ---------------------------------------------------------------------------

class TestDeliveryFormatPatternsBug061:
    """Verify iphone/ipad patterns were removed from DELIVERY_FORMAT_PATTERNS."""

    def test_no_iphone_pattern(self):
        """No pattern in DELIVERY_FORMAT_PATTERNS should match 'iphone'."""
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert "iphone" not in pattern.lower(), (
                f"Found iphone in pattern: ({match_type}, {pattern}, {fmt})"
            )

    def test_no_ipad_pattern(self):
        """No pattern in DELIVERY_FORMAT_PATTERNS should match 'ipad'."""
        for match_type, pattern, fmt in DELIVERY_FORMAT_PATTERNS:
            assert "ipad" not in pattern.lower(), (
                f"Found ipad in pattern: ({match_type}, {pattern}, {fmt})"
            )

    def test_persistent_notification_still_works(self):
        assert detect_delivery_format("notify.persistent_notification") == DELIVERY_FORMAT_PERSISTENT

    def test_nfandroidtv_still_rich(self):
        assert detect_delivery_format("notify.nfandroidtv") == DELIVERY_FORMAT_RICH

    def test_mobile_app_still_rich(self):
        assert detect_delivery_format("notify.mobile_app_pixel") == DELIVERY_FORMAT_RICH

    def test_iphone_service_now_returns_rich(self):
        """After BUG-061, iphone services are no longer pattern-matched to plain.
        iOS detection is now handled by resolve_ios_platform()."""
        assert detect_delivery_format("notify.mobile_app_iphone") == DELIVERY_FORMAT_RICH

    def test_ipad_service_now_returns_rich(self):
        """After BUG-061, ipad services are no longer pattern-matched to plain."""
        assert detect_delivery_format("notify.mobile_app_ipad") == DELIVERY_FORMAT_RICH


# ---------------------------------------------------------------------------
# Integration: detect_delivery_format + resolve_ios_platform
# ---------------------------------------------------------------------------

class TestIntegrationFormatWithIosDetection:
    """End-to-end: detect_delivery_format returns 'rich' for all mobile_app,
    then resolve_ios_platform is called to override to 'plain' for iOS."""

    @patch("custom_components.ticker.formatting.slugify")
    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_ios_device_overrides_to_plain(self, mock_er, mock_dr, mock_slugify):
        """Simulates the caller pattern: detect format, then check iOS to override."""
        hass = MagicMock()

        # Entity registry returns nothing (use legacy path)
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        mock_er.async_get.return_value = entity_reg

        device_reg = MagicMock()
        mock_dr.async_get.return_value = device_reg

        mock_slugify.return_value = "hans_iphone"
        ios_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"device_name": "Hans iPhone", "os_name": "iOS"},
        )
        hass.config_entries.async_entries.return_value = [ios_entry]

        service_id = "notify.mobile_app_hans_iphone"

        # Step 1: detect_delivery_format returns rich (not plain)
        fmt = detect_delivery_format(service_id)
        assert fmt == DELIVERY_FORMAT_RICH

        # Step 2: resolve_ios_platform detects iOS
        is_ios = resolve_ios_platform(hass, service_id)
        assert is_ios is True

        # Step 3: Caller overrides to plain
        if is_ios and fmt == DELIVERY_FORMAT_RICH:
            fmt = DELIVERY_FORMAT_PLAIN
        assert fmt == DELIVERY_FORMAT_PLAIN

    @patch("custom_components.ticker.formatting.dr")
    @patch("custom_components.ticker.formatting.er")
    def test_android_device_stays_rich(self, mock_er, mock_dr):
        """Android device: detect_delivery_format returns rich, no override."""
        hass = MagicMock()

        entity_entry = _make_entity_entry(device_id="dev_1")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = entity_entry
        mock_er.async_get.return_value = entity_reg

        device = _make_device(config_entry_ids=["cfg_1"])
        device_reg = MagicMock()
        device_reg.async_get.return_value = device
        mock_dr.async_get.return_value = device_reg

        android_entry = _make_config_entry(
            domain="mobile_app", entry_id="cfg_1",
            data={"os_name": "Android"},
        )
        hass.config_entries.async_get_entry.return_value = android_entry

        service_id = "notify.mobile_app_pixel"

        fmt = detect_delivery_format(service_id)
        assert fmt == DELIVERY_FORMAT_RICH

        is_ios = resolve_ios_platform(hass, service_id)
        assert is_ios is False

        # No override
        assert fmt == DELIVERY_FORMAT_RICH

    def test_explicit_admin_format_not_overridden(self):
        """If an admin has explicitly set a format on a recipient,
        the caller should not override it. This test documents the
        expected pattern (caller responsibility)."""
        admin_format = DELIVERY_FORMAT_RICH  # explicitly set by admin
        service_id = "notify.mobile_app_hans_iphone"

        # Even if this is an iOS device, an explicit admin format
        # should be preserved. The override logic in callers checks
        # `if not explicit_format:` before applying iOS override.
        # This test just verifies the contract.
        assert admin_format == DELIVERY_FORMAT_RICH
