"""Tests for BUG-092: _check_device_ios must scan ALL config entries.

A device can be linked to multiple config entries (e.g. mobile_app
plus another integration). The previous logic short-circuited on the
first non-mobile_app entry or the first non-iOS mobile_app entry,
missing iOS devices that weren't the first entry listed. The fix
iterates all entries and returns True on the first iOS match.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ticker.formatting import _check_device_ios


def _config_entry(domain: str, os_name: str = "") -> MagicMock:
    entry = MagicMock()
    entry.domain = domain
    entry.data = {"os_name": os_name} if os_name else {}
    return entry


def _hass_with_entries(entries_by_id: dict[str, MagicMock]) -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(
        side_effect=lambda eid: entries_by_id.get(eid)
    )
    return hass


def _device_reg_with_device(device_id: str, config_entry_ids: list[str]) -> MagicMock:
    device = MagicMock()
    device.config_entries = config_entry_ids
    reg = MagicMock()
    reg.async_get = MagicMock(
        side_effect=lambda did: device if did == device_id else None
    )
    return reg


class TestBug092CheckDeviceIos:

    def test_non_mobile_app_then_ios_returns_true(self):
        """First entry is NOT mobile_app, second IS mobile_app iOS."""
        entries = {
            "entry_a": _config_entry("some_other_integration"),
            "entry_b": _config_entry("mobile_app", os_name="iOS"),
        }
        hass = _hass_with_entries(entries)
        device_reg = _device_reg_with_device("dev1", ["entry_a", "entry_b"])

        assert _check_device_ios(hass, device_reg, "dev1") is True

    def test_android_mobile_app_then_ios_returns_true(self):
        """First entry is mobile_app Android, second is mobile_app iOS."""
        entries = {
            "entry_a": _config_entry("mobile_app", os_name="Android"),
            "entry_b": _config_entry("mobile_app", os_name="iOS"),
        }
        hass = _hass_with_entries(entries)
        device_reg = _device_reg_with_device("dev1", ["entry_a", "entry_b"])

        assert _check_device_ios(hass, device_reg, "dev1") is True

    def test_only_android_returns_false(self):
        entries = {
            "entry_a": _config_entry("mobile_app", os_name="Android"),
        }
        hass = _hass_with_entries(entries)
        device_reg = _device_reg_with_device("dev1", ["entry_a"])

        assert _check_device_ios(hass, device_reg, "dev1") is False

    def test_device_not_found_returns_false(self):
        hass = MagicMock()
        device_reg = MagicMock()
        device_reg.async_get = MagicMock(return_value=None)

        assert _check_device_ios(hass, device_reg, "missing") is False

    def test_ios_case_insensitive(self):
        """os_name comparison is lowercase, so 'IOS' or 'ios' also matches."""
        entries = {
            "entry_a": _config_entry("mobile_app", os_name="iOS"),
        }
        hass = _hass_with_entries(entries)
        device_reg = _device_reg_with_device("dev1", ["entry_a"])

        assert _check_device_ios(hass, device_reg, "dev1") is True
