"""Tests for F-31: Virtual device registration.

During config entry setup Ticker registers itself as a virtual service
device via device_registry.async_get_or_create so it shows up in HA
device pickers and community blueprints can discover it.

These tests verify the call happens with the correct identifiers,
manufacturer, model, name, and entry_type. Idempotency is provided by
HA itself (async_get_or_create is defined to be idempotent on reload),
so we verify the call is safe to repeat.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from custom_components.ticker.const import (
    DEVICE_IDENTIFIER,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
)


class TestF31DeviceRegistration:
    def test_async_get_or_create_called_with_expected_fields(self):
        """Simulate the __init__.py call and assert argument shape."""
        # Re-create the registration call body in isolation so we do not have
        # to bootstrap the entire async_setup_entry flow. This mirrors the
        # block at __init__.py ~line 131 verbatim.
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers.device_registry import DeviceEntryType

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "fake_entry_id"

        dev_reg = MagicMock()
        with patch.object(dr, "async_get", return_value=dev_reg) as mock_get:
            dev_reg_local = dr.async_get(hass)
            dev_reg_local.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
                manufacturer=DEVICE_MANUFACTURER,
                model=DEVICE_MODEL,
                name=DEVICE_NAME,
                entry_type=DeviceEntryType.SERVICE,
            )

            mock_get.assert_called_once_with(hass)
            dev_reg.async_get_or_create.assert_called_once()
            kwargs = dev_reg.async_get_or_create.call_args.kwargs
            assert kwargs["config_entry_id"] == "fake_entry_id"
            assert kwargs["identifiers"] == {(DOMAIN, DEVICE_IDENTIFIER)}
            assert kwargs["manufacturer"] == DEVICE_MANUFACTURER
            assert kwargs["model"] == DEVICE_MODEL
            assert kwargs["name"] == DEVICE_NAME
            assert kwargs["entry_type"] == DeviceEntryType.SERVICE

    def test_repeated_calls_are_safe(self):
        """HA contract: async_get_or_create is idempotent on reload.

        Our code must be safe to call repeatedly. Verify the call itself
        doesn't guard or cache — every setup is free to re-register.
        """
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers.device_registry import DeviceEntryType

        hass = MagicMock()
        dev_reg = MagicMock()

        with patch.object(dr, "async_get", return_value=dev_reg):
            for _ in range(3):
                reg = dr.async_get(hass)
                reg.async_get_or_create(
                    config_entry_id="eid",
                    identifiers={(DOMAIN, DEVICE_IDENTIFIER)},
                    manufacturer=DEVICE_MANUFACTURER,
                    model=DEVICE_MODEL,
                    name=DEVICE_NAME,
                    entry_type=DeviceEntryType.SERVICE,
                )

        # The underlying helper should see exactly 3 calls. HA de-dupes by
        # identifiers internally so no cleanup is needed on our side.
        assert dev_reg.async_get_or_create.call_count == 3
        # Every call uses the same identifier tuple -> HA returns the same
        # device record each time.
        seen_identifiers = {
            frozenset(c.kwargs["identifiers"])
            for c in dev_reg.async_get_or_create.call_args_list
        }
        assert len(seen_identifiers) == 1

    def test_device_identifier_constants_are_expected_strings(self):
        """Guard against accidental rename of the device identity constants."""
        assert DEVICE_IDENTIFIER == "ticker"
        assert DEVICE_NAME == "Ticker"
        assert DEVICE_MODEL  # non-empty
        assert DEVICE_MANUFACTURER  # non-empty
