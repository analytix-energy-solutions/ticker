"""SEC-002 — android_channel is length-bounded and sanitized.

``const.MAX_ANDROID_CHANNEL_LENGTH = 100`` bounds the field. Both the
create and update WebSocket schemas apply
``vol.Length(max=MAX_ANDROID_CHANNEL_LENGTH)`` and both handlers call
``sanitize_for_storage(msg.get("android_channel"), MAX_ANDROID_CHANNEL_LENGTH)``.

Coverage:
- (a) Schema rejects an over-length android_channel (>100 chars) and
      accepts a value at exactly the limit. Because the conftest stub of
      ``websocket_command`` discards the schema, the real voluptuous
      schema is re-captured by temporarily swapping in a capturing
      ``websocket_command`` and reloading the module (throwaway-decorator
      trick), then restoring the module to its normal state.
- (b) The handler strips whitespace and null bytes via sanitize_for_storage.
- (c) Sparse semantics on update: absent key leaves value untouched,
      empty string clears, non-empty sets — exercised through the real
      handler against a real CategoryMixin store.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.ticker.const import MAX_ANDROID_CHANNEL_LENGTH
from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.websocket import categories as _categories_mod
from custom_components.ticker.websocket.categories import (
    ws_create_category,
    ws_update_category,
)


# ---------------------------------------------------------------------------
# Schema capture (throwaway-decorator trick)
# ---------------------------------------------------------------------------

def _capture_category_schemas() -> dict[str, dict]:
    """Re-run the module decorators with a capturing websocket_command.

    Returns a mapping of handler ``__name__`` -> the voluptuous schema
    dict passed to ``@websocket_api.websocket_command``. The module is
    reloaded a second time with the original stub restored so global
    state is unchanged for the rest of the suite.
    """
    ws_api = sys.modules["homeassistant.components.websocket_api"]
    original_wc = ws_api.websocket_command
    captured: dict[str, dict] = {}

    def _capturing(schema):
        def _deco(fn):
            captured[fn.__name__] = schema
            return fn
        return _deco

    ws_api.websocket_command = _capturing
    try:
        importlib.reload(_categories_mod)
    finally:
        ws_api.websocket_command = original_wc
        importlib.reload(_categories_mod)
    return captured


@pytest.fixture(scope="module")
def category_schemas() -> dict[str, dict]:
    return _capture_category_schemas()


class TestAndroidChannelSchemaBound:
    """The voluptuous schema enforces MAX_ANDROID_CHANNEL_LENGTH."""

    def test_create_schema_rejects_over_length(self, category_schemas):
        schema = vol.Schema(category_schemas["ws_create_category"])
        base = {
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
        }
        with pytest.raises(vol.Invalid):
            schema({**base, "android_channel": "x" * (MAX_ANDROID_CHANNEL_LENGTH + 1)})

    def test_create_schema_accepts_at_limit(self, category_schemas):
        schema = vol.Schema(category_schemas["ws_create_category"])
        base = {
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
        }
        result = schema({**base, "android_channel": "x" * MAX_ANDROID_CHANNEL_LENGTH})
        assert result["android_channel"] == "x" * MAX_ANDROID_CHANNEL_LENGTH

    def test_create_schema_accepts_none(self, category_schemas):
        schema = vol.Schema(category_schemas["ws_create_category"])
        base = {
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
        }
        result = schema({**base, "android_channel": None})
        assert result["android_channel"] is None

    def test_update_schema_rejects_over_length(self, category_schemas):
        schema = vol.Schema(category_schemas["ws_update_category"])
        base = {"type": "ticker/category/update", "category_id": "security"}
        with pytest.raises(vol.Invalid):
            schema({**base, "android_channel": "x" * (MAX_ANDROID_CHANNEL_LENGTH + 1)})

    def test_update_schema_accepts_at_limit(self, category_schemas):
        schema = vol.Schema(category_schemas["ws_update_category"])
        base = {"type": "ticker/category/update", "category_id": "security"}
        result = schema({**base, "android_channel": "x" * MAX_ANDROID_CHANNEL_LENGTH})
        assert result["android_channel"] == "x" * MAX_ANDROID_CHANNEL_LENGTH

    def test_const_value_is_100(self):
        """Guard the bound itself so a silent widening is caught."""
        assert MAX_ANDROID_CHANNEL_LENGTH == 100


# ---------------------------------------------------------------------------
# Real store for handler-level tests
# ---------------------------------------------------------------------------

class FakeCategoryStore(CategoryMixin):
    """Concrete class mixing in CategoryMixin for testing."""

    def __init__(self):
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


# ---------------------------------------------------------------------------
# (b) sanitize_for_storage strips whitespace + null bytes in the handler
# ---------------------------------------------------------------------------

class TestAndroidChannelSanitizeInHandler:
    """The real handler runs sanitize_for_storage on android_channel."""

    @pytest.mark.asyncio
    async def test_create_strips_whitespace_and_null_bytes(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
            "android_channel": " foo\x00 ",
        }
        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_create_category(hass, MagicMock(), msg)

        assert store.get_category("security")["android_channel"] == "foo"

    @pytest.mark.asyncio
    async def test_update_strips_whitespace_and_null_bytes(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        await store.async_create_category("security", "Security")

        msg = {
            "id": 2,
            "type": "ticker/category/update",
            "category_id": "security",
            "android_channel": "  alerts\x00\x00 ",
        }
        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_update_category(hass, MagicMock(), msg)

        assert store.get_category("security")["android_channel"] == "alerts"


# ---------------------------------------------------------------------------
# (c) Sparse semantics through the real handler
# ---------------------------------------------------------------------------

class TestAndroidChannelSparseSemanticsViaHandler:
    """absent leaves untouched, empty clears, non-empty sets."""

    async def _create(self, store, hass, **extra):
        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "security",
            "name": "Security",
            **extra,
        }
        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_create_category(hass, MagicMock(), msg)

    async def _update(self, store, hass, **extra):
        msg = {
            "id": 2,
            "type": "ticker/category/update",
            "category_id": "security",
            **extra,
        }
        with patch(
            "custom_components.ticker.websocket.categories.get_store",
            return_value=store,
        ):
            await ws_update_category(hass, MagicMock(), msg)

    @pytest.mark.asyncio
    async def test_absent_key_leaves_value_untouched(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        await self._create(store, hass, android_channel="security_alerts")
        # Update something else, omit android_channel entirely.
        await self._update(store, hass, name="Security v2")
        assert store.get_category("security")["android_channel"] == "security_alerts"

    @pytest.mark.asyncio
    async def test_empty_string_clears_value(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        await self._create(store, hass, android_channel="security_alerts")
        await self._update(store, hass, android_channel="")
        assert "android_channel" not in store.get_category("security")

    @pytest.mark.asyncio
    async def test_non_empty_sets_value(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        await self._create(store, hass)
        assert "android_channel" not in store.get_category("security")
        await self._update(store, hass, android_channel="new_channel")
        assert store.get_category("security")["android_channel"] == "new_channel"

    @pytest.mark.asyncio
    async def test_create_empty_string_not_stored(self):
        store = FakeCategoryStore()
        hass = _make_hass()
        await self._create(store, hass, android_channel="")
        assert "android_channel" not in store.get_category("security")
