"""Tests for PR #61 (TTS engine injection) + v1.8.3b2 save-time validation.

PR #61 shipped without tests. This module covers the three surfaces the
fix touches:

1. ``formatting.build_tts_payload`` — engine ``entity_id`` injection for
   the modern ``tts.speak`` calling pattern, plus byte-identical backward
   compatibility when no engine is supplied.
2. ``store.recipients`` — sparse round-trip of ``tts_engine_entity_id`` on
   create/update, and clean migration of legacy recipients that predate
   the field.
3. ``websocket.recipient_validation.validate_tts_engine`` + the
   ``ws_create_recipient`` / ``ws_update_recipient`` intake guards
   (v1.8.3b2) that reject a ``tts.speak`` recipient with no engine.

WS-layer helpers (``_base_recipient_create`` / ``_base_recipient_update`` /
``_recipient_patches`` / ``_make_recipient_mocks``) are reused from
``test_f35_chime_websocket`` — the F-35 module already carries the updated
``_base_recipient_create`` that includes ``tts_engine_entity_id``.
The store-layer ``FakeStore`` is reused from ``test_store_recipients``.
"""

from __future__ import annotations

import pytest

from custom_components.ticker.formatting import build_tts_payload
from custom_components.ticker.websocket.recipient_validation import (
    validate_tts_engine,
)
from custom_components.ticker.websocket.recipients import (
    ws_create_recipient,
    ws_update_recipient,
)
from custom_components.ticker.const import (
    DEVICE_TYPE_PUSH,
    DEVICE_TYPE_TTS,
    DELIVERY_FORMAT_RICH,
)

from tests.test_f35_chime_websocket import (
    _base_recipient_create,
    _base_recipient_update,
    _make_recipient_mocks,
    _recipient_patches,
)
from tests.test_store_recipients import FakeStore


# ---------------------------------------------------------------------------
# 1. build_tts_payload — engine injection (PR #61)
# ---------------------------------------------------------------------------

class TestBuildTtsPayloadEngineInjection:
    """PR #61: tts.speak may carry a TTS-engine entity_id."""

    def test_speak_with_engine_injects_entity_id(self):
        """entity_id is the TTS engine, media_player_entity_id is the speaker."""
        result = build_tts_payload(
            "Hello",
            "media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.google_translate",
        )
        assert result["entity_id"] == "tts.google_translate"
        assert result["media_player_entity_id"] == "media_player.kitchen"
        assert result["message"] == "Hello"

    def test_engine_entity_distinct_from_media_player(self):
        """The engine entity must not clobber the speaker target."""
        result = build_tts_payload(
            "Hi",
            "media_player.office",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.piper",
        )
        # Two separate keys — the delivery target survives.
        assert result["entity_id"] != result["media_player_entity_id"]
        assert result["entity_id"] == "tts.piper"
        assert result["media_player_entity_id"] == "media_player.office"

    def test_speak_without_engine_omits_entity_id(self):
        """Backward compat: no engine -> no entity_id key (pre-PR behavior)."""
        result = build_tts_payload(
            "Hello", "media_player.kitchen", tts_service="tts.speak",
        )
        assert "entity_id" not in result
        assert result == {
            "media_player_entity_id": "media_player.kitchen",
            "message": "Hello",
        }

    def test_speak_empty_engine_omits_entity_id(self):
        """Falsy engine ('') is treated the same as absent — no entity_id."""
        result = build_tts_payload(
            "Hi",
            "media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="",
        )
        assert "entity_id" not in result

    def test_legacy_service_ignores_engine(self):
        """Legacy pattern (non-speak) never emits media_player_entity_id and
        entity_id remains the media_player, even if an engine is passed."""
        result = build_tts_payload(
            "Hi",
            "media_player.kitchen",
            tts_service="tts.google_translate_say",
            tts_engine_entity_id="tts.google_translate",
        )
        assert result == {
            "entity_id": "media_player.kitchen",
            "message": "Hi",
        }
        assert "media_player_entity_id" not in result

    def test_engine_strips_html_from_message(self):
        result = build_tts_payload(
            "<b>Fire!</b>",
            "media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.piper",
        )
        assert result["message"] == "Fire!"


# ---------------------------------------------------------------------------
# 2. validate_tts_engine — truth table (v1.8.3b2)
# ---------------------------------------------------------------------------

class TestValidateTtsEngineUnit:
    """Direct unit coverage of the save-time guard truth table."""

    def test_tts_speak_no_engine_invalid(self):
        ok, code, msg = validate_tts_engine(DEVICE_TYPE_TTS, "tts.speak", None)
        assert ok is False
        assert code == "missing_tts_engine"
        assert msg  # a human-readable reason is provided

    def test_tts_speak_empty_engine_invalid(self):
        ok, code, _ = validate_tts_engine(DEVICE_TYPE_TTS, "tts.speak", "")
        assert ok is False
        assert code == "missing_tts_engine"

    def test_tts_unset_service_defaults_to_speak_invalid(self):
        """Unset service defaults to tts.speak, so no engine is still invalid."""
        ok, code, _ = validate_tts_engine(DEVICE_TYPE_TTS, None, None)
        assert ok is False
        assert code == "missing_tts_engine"

    def test_tts_speak_with_engine_valid(self):
        ok, code, msg = validate_tts_engine(
            DEVICE_TYPE_TTS, "tts.speak", "tts.google_translate",
        )
        assert ok is True
        assert code is None
        assert msg is None

    def test_tts_cloud_say_no_engine_valid(self):
        """Legacy TTS service needs no engine."""
        ok, code, _ = validate_tts_engine(
            DEVICE_TYPE_TTS, "tts.cloud_say", None,
        )
        assert ok is True
        assert code is None

    def test_push_is_noop_even_with_speak_and_no_engine(self):
        ok, code, _ = validate_tts_engine(DEVICE_TYPE_PUSH, "tts.speak", None)
        assert ok is True
        assert code is None

    def test_push_always_valid(self):
        ok, _, _ = validate_tts_engine(DEVICE_TYPE_PUSH, None, None)
        assert ok is True


# ---------------------------------------------------------------------------
# 3a. ws_create_recipient — save-time guard
# ---------------------------------------------------------------------------

class TestCreateRecipientTtsEngineGuard:

    @pytest.mark.asyncio
    async def test_create_speak_without_engine_rejected(self):
        hass, conn, store = _make_recipient_mocks()
        msg = _base_recipient_create(tts_service="tts.speak")
        del msg["tts_engine_entity_id"]
        with _recipient_patches(store):
            await ws_create_recipient(hass, conn, msg)
        conn.send_error.assert_called_once()
        args = conn.send_error.call_args[0]
        assert args[1] == "missing_tts_engine"
        store.async_create_recipient.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_unset_service_without_engine_rejected(self):
        """No tts_service defaults to tts.speak -> engine still required."""
        hass, conn, store = _make_recipient_mocks()
        msg = _base_recipient_create()  # no tts_service key
        del msg["tts_engine_entity_id"]
        with _recipient_patches(store):
            await ws_create_recipient(hass, conn, msg)
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "missing_tts_engine"
        store.async_create_recipient.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_speak_with_engine_succeeds(self):
        hass, conn, store = _make_recipient_mocks()
        with _recipient_patches(store):
            await ws_create_recipient(
                hass, conn, _base_recipient_create(tts_service="tts.speak"),
            )
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        kw = store.async_create_recipient.call_args[1]
        assert kw["tts_engine_entity_id"] == "tts.google_translate"

    @pytest.mark.asyncio
    async def test_create_cloud_say_without_engine_succeeds(self):
        """Legacy service needs no engine — guard is a no-op."""
        hass, conn, store = _make_recipient_mocks()
        msg = _base_recipient_create(tts_service="tts.cloud_say")
        del msg["tts_engine_entity_id"]
        with _recipient_patches(store):
            await ws_create_recipient(hass, conn, msg)
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_push_is_noop(self):
        """Push recipients bypass the TTS-engine guard entirely."""
        hass, conn, store = _make_recipient_mocks()
        msg = _base_recipient_create(
            device_type=DEVICE_TYPE_PUSH,
            delivery_format=DELIVERY_FORMAT_RICH,
            notify_services=[{"service": "notify.phone", "name": "Phone"}],
            tts_service="tts.speak",  # nonsensical for push, must be ignored
        )
        del msg["tts_engine_entity_id"]
        with _recipient_patches(store):
            await ws_create_recipient(hass, conn, msg)
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()


# ---------------------------------------------------------------------------
# 3b. ws_update_recipient — gated save-time guard
# ---------------------------------------------------------------------------

def _tts_existing(**overrides) -> dict:
    existing = {
        "recipient_id": "kitchen",
        "device_type": DEVICE_TYPE_TTS,
        "name": "Kitchen",
        "media_player_entity_id": "media_player.kitchen",
    }
    existing.update(overrides)
    return existing


class TestUpdateRecipientTtsEngineGuard:

    @pytest.mark.asyncio
    async def test_set_speak_without_stored_engine_rejected(self):
        """Switching to tts.speak with no stored engine and none in msg."""
        existing = _tts_existing(tts_service="tts.cloud_say")
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn, _base_recipient_update(tts_service="tts.speak"),
            )
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "missing_tts_engine"
        store.async_update_recipient.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_speak_with_engine_succeeds(self):
        existing = _tts_existing(tts_service="tts.cloud_say")
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                _base_recipient_update(
                    tts_service="tts.speak",
                    tts_engine_entity_id="tts.google_translate",
                ),
            )
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()
        kw = store.async_update_recipient.call_args[1]
        assert kw["tts_engine_entity_id"] == "tts.google_translate"

    @pytest.mark.asyncio
    async def test_set_speak_uses_stored_engine(self):
        """Effective merge: stored engine satisfies the guard."""
        existing = _tts_existing(
            tts_service="tts.cloud_say",
            tts_engine_entity_id="tts.piper",
        )
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn, _base_recipient_update(tts_service="tts.speak"),
            )
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrelated_update_on_legacy_no_engine_not_blocked(self):
        """The gate: name-only edit on a tts.speak-no-engine recipient passes."""
        existing = _tts_existing(tts_service="tts.speak")  # no engine stored
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn, _base_recipient_update(name="Kitchen Renamed"),
            )
        conn.send_result.assert_called_once()
        conn.send_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_clearing_engine_on_speak_recipient_rejected(self):
        """Blanking the engine on a tts.speak recipient is rejected."""
        existing = _tts_existing(
            tts_service="tts.speak",
            tts_engine_entity_id="tts.piper",
        )
        hass, conn, store = _make_recipient_mocks(existing=existing)
        with _recipient_patches(store):
            await ws_update_recipient(
                hass, conn,
                _base_recipient_update(tts_engine_entity_id=""),
            )
        conn.send_error.assert_called_once()
        assert conn.send_error.call_args[0][1] == "missing_tts_engine"
        store.async_update_recipient.assert_not_called()


# ---------------------------------------------------------------------------
# 4. store.recipients — tts_engine_entity_id sparse round-trip (PR #61)
# ---------------------------------------------------------------------------

class TestStoreEngineRoundTrip:

    @pytest.mark.asyncio
    async def test_create_tts_stores_engine(self):
        store = FakeStore()
        result = await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.google_translate",
        )
        assert result["tts_engine_entity_id"] == "tts.google_translate"

    @pytest.mark.asyncio
    async def test_create_tts_strips_engine_whitespace(self):
        store = FakeStore()
        result = await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="  tts.piper  ",
        )
        assert result["tts_engine_entity_id"] == "tts.piper"

    @pytest.mark.asyncio
    async def test_create_tts_no_engine_defaults_none(self):
        """Absent engine -> field present as None (unset, not a stray value)."""
        store = FakeStore()
        result = await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.cloud_say",
        )
        assert result["tts_engine_entity_id"] is None

    @pytest.mark.asyncio
    async def test_update_sets_engine(self):
        store = FakeStore()
        await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.cloud_say",
        )
        result = await store.async_update_recipient(
            "spk", tts_engine_entity_id="tts.piper",
        )
        assert result["tts_engine_entity_id"] == "tts.piper"

    @pytest.mark.asyncio
    async def test_update_clears_engine_sparse(self):
        """Blank engine on update pops the key (sparse, like volume_override)."""
        store = FakeStore()
        await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.piper",
        )
        result = await store.async_update_recipient(
            "spk", tts_engine_entity_id="",
        )
        assert "tts_engine_entity_id" not in result

    @pytest.mark.asyncio
    async def test_update_whitespace_engine_clears_sparse(self):
        store = FakeStore()
        await store.async_create_recipient(
            "spk", "Speaker", [],
            device_type=DEVICE_TYPE_TTS,
            media_player_entity_id="media_player.kitchen",
            tts_service="tts.speak",
            tts_engine_entity_id="tts.piper",
        )
        result = await store.async_update_recipient(
            "spk", tts_engine_entity_id="   ",
        )
        assert "tts_engine_entity_id" not in result


# ---------------------------------------------------------------------------
# 5. migration — legacy recipients without the engine field load cleanly
# ---------------------------------------------------------------------------

class TestEngineMigration:

    def test_legacy_recipient_gains_none_engine(self):
        """A pre-device-type recipient migrates to an explicit None engine."""
        recipients = {
            "spk": {"name": "Speaker", "delivery_format": "tts"},
        }
        FakeStore.migrate_recipient_data(recipients)
        assert recipients["spk"]["tts_engine_entity_id"] is None

    def test_already_migrated_without_engine_key_loads_cleanly(self):
        """Already-migrated recipients that predate the field aren't rewritten
        and don't crash migration."""
        recipients = {
            "spk": {
                "name": "Speaker",
                "device_type": DEVICE_TYPE_TTS,
                "delivery_format": "rich",
                "media_player_entity_id": "media_player.kitchen",
            }
        }
        count = FakeStore.migrate_recipient_data(recipients)
        assert count == 0
        # No crash; recipient still usable without an engine key.
        assert "tts_engine_entity_id" not in recipients["spk"]

    def test_migrated_recipient_with_engine_preserved(self):
        recipients = {
            "spk": {
                "name": "Speaker",
                "device_type": DEVICE_TYPE_TTS,
                "delivery_format": "rich",
                "tts_engine_entity_id": "tts.piper",
            }
        }
        FakeStore.migrate_recipient_data(recipients)
        assert recipients["spk"]["tts_engine_entity_id"] == "tts.piper"
