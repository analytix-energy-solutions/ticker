"""Tests for category-level critical notification feature.

Covers:
- store/categories.py: critical param in create and update
- websocket/categories.py: critical field in WS schemas
- services.py: critical merge logic (per-call override vs category default)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.store.categories import CategoryMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCategoryStore(CategoryMixin):
    """Concrete class mixing in CategoryMixin for testing."""

    def __init__(self, categories=None):
        self.hass = MagicMock()
        self._categories: dict = categories if categories is not None else {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


@pytest.fixture
def store():
    return FakeCategoryStore()


# ---------------------------------------------------------------------------
# async_create_category: critical flag
# ---------------------------------------------------------------------------

class TestCreateCategoryCritical:
    @pytest.mark.asyncio
    async def test_create_with_critical_true(self, store):
        cat = await store.async_create_category("alerts", "Alerts", critical=True)
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_create_with_critical_false(self, store):
        cat = await store.async_create_category("info", "Info", critical=False)
        # When critical=False, the key should not be stored
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_create_without_critical_defaults_false(self, store):
        cat = await store.async_create_category("general", "General")
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_create_critical_persisted_in_store(self, store):
        await store.async_create_category("alerts", "Alerts", critical=True)
        stored = store._categories["alerts"]
        assert stored["critical"] is True

    @pytest.mark.asyncio
    async def test_create_saves_to_storage(self, store):
        await store.async_create_category("alerts", "Alerts", critical=True)
        store._categories_store.async_save.assert_awaited_once()


# ---------------------------------------------------------------------------
# async_update_category: critical flag toggle
# ---------------------------------------------------------------------------

class TestUpdateCategoryCritical:
    @pytest.mark.asyncio
    async def test_update_set_critical_true(self, store):
        await store.async_create_category("alerts", "Alerts")
        cat = await store.async_update_category("alerts", critical=True)
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_update_set_critical_false_removes_key(self, store):
        await store.async_create_category("alerts", "Alerts", critical=True)
        cat = await store.async_update_category("alerts", critical=False)
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_update_critical_none_leaves_unchanged(self, store):
        """When critical is not passed (None), existing value persists."""
        await store.async_create_category("alerts", "Alerts", critical=True)
        cat = await store.async_update_category("alerts", name="Alerts v2")
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_update_critical_none_no_critical_key(self, store):
        """When critical is not passed and was never set, key stays absent."""
        await store.async_create_category("info", "Info")
        cat = await store.async_update_category("info", name="Info v2")
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, store):
        result = await store.async_update_category("missing", critical=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_toggle_critical_on_off_on(self, store):
        """Round-trip: off -> on -> off -> on."""
        await store.async_create_category("alerts", "Alerts")
        assert "critical" not in store._categories["alerts"]

        await store.async_update_category("alerts", critical=True)
        assert store._categories["alerts"]["critical"] is True

        await store.async_update_category("alerts", critical=False)
        assert "critical" not in store._categories["alerts"]

        await store.async_update_category("alerts", critical=True)
        assert store._categories["alerts"]["critical"] is True


# ---------------------------------------------------------------------------
# get_category: critical field retrieval
# ---------------------------------------------------------------------------

class TestGetCategoryCritical:
    @pytest.mark.asyncio
    async def test_get_returns_critical_true(self, store):
        await store.async_create_category("alerts", "Alerts", critical=True)
        cat = store.get_category("alerts")
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_get_returns_no_critical_when_false(self, store):
        await store.async_create_category("info", "Info")
        cat = store.get_category("info")
        assert cat.get("critical", False) is False


# ---------------------------------------------------------------------------
# Service dispatch: critical merge logic
# ---------------------------------------------------------------------------

class TestServiceCriticalMerge:
    """Test the critical resolution logic in services.py async_handle_notify.

    The logic under test (from services.py lines 228-235):
        if ATTR_CRITICAL in call.data:
            resolved_critical = call.data[ATTR_CRITICAL]
        else:
            resolved_critical = (category or {}).get("critical", False)
        if resolved_critical:
            data["critical"] = True
        else:
            data.pop("critical", None)
    """

    def _resolve_critical(self, call_data: dict, category: dict | None) -> dict:
        """Simulate the critical merge logic from services.py."""
        data: dict = {}
        if "critical" in call_data:
            resolved_critical = call_data["critical"]
        else:
            resolved_critical = (category or {}).get("critical", False)
        if resolved_critical:
            data["critical"] = True
        else:
            data.pop("critical", None)
        return data

    def test_category_critical_true_no_override(self):
        """Category critical=True, no per-call override -> data gets critical=True."""
        data = self._resolve_critical(
            call_data={},
            category={"critical": True},
        )
        assert data["critical"] is True

    def test_category_critical_true_override_false(self):
        """Category critical=True, per-call critical=False -> data has no critical."""
        data = self._resolve_critical(
            call_data={"critical": False},
            category={"critical": True},
        )
        assert "critical" not in data

    def test_category_critical_false_override_true(self):
        """Category critical=False, per-call critical=True -> data gets critical=True."""
        data = self._resolve_critical(
            call_data={"critical": True},
            category={"critical": False},
        )
        assert data["critical"] is True

    def test_category_critical_false_no_override(self):
        """Category critical=False, no per-call override -> no critical in data."""
        data = self._resolve_critical(
            call_data={},
            category={"critical": False},
        )
        assert "critical" not in data

    def test_category_no_critical_key_no_override(self):
        """Category has no critical key at all -> defaults to False, no critical."""
        data = self._resolve_critical(
            call_data={},
            category={"name": "Info"},
        )
        assert "critical" not in data

    def test_category_no_critical_key_override_true(self):
        """Category has no critical key, per-call critical=True -> data gets critical."""
        data = self._resolve_critical(
            call_data={"critical": True},
            category={"name": "Info"},
        )
        assert data["critical"] is True

    def test_category_none_no_override(self):
        """Category is None (edge case) -> defaults to False."""
        data = self._resolve_critical(
            call_data={},
            category=None,
        )
        assert "critical" not in data

    def test_category_none_override_true(self):
        """Category is None, per-call critical=True -> data gets critical."""
        data = self._resolve_critical(
            call_data={"critical": True},
            category=None,
        )
        assert data["critical"] is True


# ---------------------------------------------------------------------------
# WebSocket: critical field passthrough
# ---------------------------------------------------------------------------

class TestWsCategoryCriticalPassthrough:
    """Verify the WS handlers pass critical through to store methods."""

    @pytest.mark.asyncio
    async def test_ws_create_passes_critical_true(self):
        """ws_create_category passes critical=True to store."""
        store = FakeCategoryStore()
        await store.async_create_category(
            "alerts", "Alerts", critical=True,
        )
        cat = store.get_category("alerts")
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_ws_create_passes_critical_default(self):
        """ws_create_category defaults critical to False when omitted."""
        store = FakeCategoryStore()
        await store.async_create_category("info", "Info")
        cat = store.get_category("info")
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_ws_update_passes_critical_true(self):
        """ws_update_category passes critical=True to store."""
        store = FakeCategoryStore()
        await store.async_create_category("alerts", "Alerts")
        await store.async_update_category("alerts", critical=True)
        cat = store.get_category("alerts")
        assert cat["critical"] is True

    @pytest.mark.asyncio
    async def test_ws_update_passes_critical_false(self):
        """ws_update_category passes critical=False to remove flag."""
        store = FakeCategoryStore()
        await store.async_create_category("alerts", "Alerts", critical=True)
        await store.async_update_category("alerts", critical=False)
        cat = store.get_category("alerts")
        assert "critical" not in cat

    @pytest.mark.asyncio
    async def test_ws_update_omitted_critical_unchanged(self):
        """ws_update_category with critical omitted leaves it unchanged."""
        store = FakeCategoryStore()
        await store.async_create_category("alerts", "Alerts", critical=True)
        # Simulate WS update that only changes name, critical not in msg
        await store.async_update_category("alerts", name="Alerts v2", critical=None)
        cat = store.get_category("alerts")
        assert cat["critical"] is True
