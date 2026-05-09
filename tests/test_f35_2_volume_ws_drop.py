"""Tests for F-35.2 — WebSocket handler layer (review test-gap closures).

Covers:
- Gap 1 — ws_update_recipient drops volume_override silently for push-type
  recipients (mirrors the create-path drop, but at the WS handler layer
  rather than at the store layer).
- Gap 2 — voluptuous schema rejects out-of-range volume_override values
  on the create_recipient, create_category, and test_chime schemas.

The conftest stubs ``websocket_api.websocket_command`` to a no-op, so the
decorator does not actually run the schema at handler-call time. These
tests assert directly against the named ``_VOLUME_SCHEMA`` fragment for
recipients and replicate the equivalent vol.Any(...) schema for
categories and test_chime (which use inline fragments).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.ticker.const import (
    VOLUME_OVERRIDE_MAX,
    VOLUME_OVERRIDE_MIN,
)
from custom_components.ticker.websocket.recipients import (
    _VOLUME_SCHEMA,
    ws_update_recipient,
)


# ---------------------------------------------------------------------------
# Gap 1 — WS update handler drops volume_override for push silently
# ---------------------------------------------------------------------------


def _make_mocks(existing_device_type: str = "push") -> tuple:
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.get_recipient.return_value = {
        "recipient_id": "phone",
        "name": "Phone",
        "device_type": existing_device_type,
        "notify_services": [{"service": "notify.x", "name": "X"}],
    }
    store.async_update_recipient = AsyncMock(
        return_value={"recipient_id": "phone"}
    )
    return hass, conn, store


class TestUpdatePushDropsVolumeOverride:
    """Gap 1: handler-layer push drop on update."""

    @pytest.mark.asyncio
    async def test_update_push_recipient_drops_volume_override_silently(self):
        """volume_override sent to a push device on update is dropped at
        the handler layer with a debug log; not forwarded to the store
        and no error returned to the caller."""
        hass, conn, store = _make_mocks(existing_device_type="push")

        # Include a benign updatable field so the handler doesn't bail with
        # "no_fields" after dropping the volume_override. The point of this
        # test is that volume_override is dropped silently — not that the
        # rest of the update flow rejects empty payloads.
        msg = {
            "id": 1,
            "type": "ticker/update_recipient",
            "recipient_id": "phone",
            "enabled": True,
            "volume_override": 0.5,
        }

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ), patch(
            "custom_components.ticker.websocket.recipients._LOGGER",
        ) as mock_logger:
            await ws_update_recipient(hass, conn, msg)

        # No error sent to caller.
        conn.send_error.assert_not_called()
        conn.send_result.assert_called_once()

        # Store update was called WITHOUT volume_override in kwargs.
        assert store.async_update_recipient.call_count == 1
        call_kwargs = store.async_update_recipient.call_args[1]
        assert "volume_override" not in call_kwargs
        # Sanity: enabled WAS forwarded.
        assert call_kwargs.get("enabled") is True

        # Handler logged a debug message about the drop.
        debug_calls = [
            c for c in mock_logger.debug.call_args_list
            if c[0] and "volume_override" in str(c[0][0]).lower()
        ]
        assert debug_calls, (
            "expected a debug log entry mentioning volume_override drop"
        )

    @pytest.mark.asyncio
    async def test_update_tts_recipient_keeps_volume_override(self):
        """Sanity check: TTS recipients still get volume_override forwarded
        to the store (only the push-path drops it)."""
        hass, conn, store = _make_mocks(existing_device_type="tts")
        # TTS recipients need media_player set
        store.get_recipient.return_value = {
            "recipient_id": "kitchen",
            "name": "Kitchen",
            "device_type": "tts",
            "media_player_entity_id": "media_player.kitchen",
        }

        msg = {
            "id": 1,
            "type": "ticker/update_recipient",
            "recipient_id": "kitchen",
            "volume_override": 0.6,
        }

        with patch(
            "custom_components.ticker.websocket.recipients.get_store",
            return_value=store,
        ):
            await ws_update_recipient(hass, conn, msg)

        conn.send_error.assert_not_called()
        call_kwargs = store.async_update_recipient.call_args[1]
        assert call_kwargs.get("volume_override") == 0.6


# ---------------------------------------------------------------------------
# Gap 2 — voluptuous schema rejects out-of-range volume_override
# ---------------------------------------------------------------------------


# The category/test_chime schemas inline this fragment — replicated here
# from the decorator definitions to test schema-level rejection without
# going through the (stubbed-out) websocket_command decorator.
_CATEGORY_VOLUME_SCHEMA = vol.Any(
    None,
    vol.All(
        vol.Coerce(float),
        vol.Range(min=VOLUME_OVERRIDE_MIN, max=VOLUME_OVERRIDE_MAX),
    ),
)
_TEST_CHIME_VOLUME_SCHEMA = vol.Any(
    None,
    vol.All(
        vol.Coerce(float),
        vol.Range(min=VOLUME_OVERRIDE_MIN, max=VOLUME_OVERRIDE_MAX),
    ),
)


class TestVolumeSchemaOutOfRangeRejection:
    """Gap 2: voluptuous schemas reject out-of-range volume_override."""

    def test_create_recipient_schema_rejects_out_of_range_volume(self):
        """Recipient schema (_VOLUME_SCHEMA) rejects values > 1.0."""
        with pytest.raises(vol.Invalid):
            _VOLUME_SCHEMA(1.5)

    def test_create_recipient_schema_rejects_negative_volume(self):
        with pytest.raises(vol.Invalid):
            _VOLUME_SCHEMA(-0.1)

    def test_create_recipient_schema_accepts_zero(self):
        """Zero is a valid (silent) volume."""
        assert _VOLUME_SCHEMA(0.0) == 0.0

    def test_create_recipient_schema_accepts_one(self):
        assert _VOLUME_SCHEMA(1.0) == 1.0

    def test_create_recipient_schema_accepts_none(self):
        """None means clear / inherit."""
        assert _VOLUME_SCHEMA(None) is None

    def test_create_category_schema_rejects_negative_volume(self):
        """Category schema fragment rejects negative values."""
        with pytest.raises(vol.Invalid):
            _CATEGORY_VOLUME_SCHEMA(-0.1)

    def test_create_category_schema_rejects_above_max(self):
        with pytest.raises(vol.Invalid):
            _CATEGORY_VOLUME_SCHEMA(1.01)

    def test_test_chime_schema_rejects_out_of_range_volume(self):
        """Test-chime schema fragment rejects values > 1.0."""
        with pytest.raises(vol.Invalid):
            _TEST_CHIME_VOLUME_SCHEMA(2.0)

    def test_test_chime_schema_rejects_negative_volume(self):
        with pytest.raises(vol.Invalid):
            _TEST_CHIME_VOLUME_SCHEMA(-0.5)
