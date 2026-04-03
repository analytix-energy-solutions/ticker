"""Tests for F-22: Notification Navigation Target (navigate_to).

Covers:
- formatting.py: inject_navigate_to() — URL/clickAction injection logic
- store/categories.py: navigate_to param in create and update (sparse storage)
- const.py: ATTR_NAVIGATE_TO, MAX_NAVIGATE_TO_LENGTH, DEFAULT_NAVIGATE_TO
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.formatting import inject_navigate_to
from custom_components.ticker.const import (
    ATTR_NAVIGATE_TO,
    DEFAULT_NAVIGATE_TO,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_PERSISTENT,
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_TTS,
    MAX_NAVIGATE_TO_LENGTH,
)
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
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestNavigateToConstants:
    """Verify F-22 constants are defined correctly."""

    def test_attr_navigate_to_value(self):
        assert ATTR_NAVIGATE_TO == "navigate_to"

    def test_default_navigate_to_value(self):
        assert DEFAULT_NAVIGATE_TO == "/ticker#history"

    def test_max_navigate_to_length(self):
        assert MAX_NAVIGATE_TO_LENGTH == 500


# ---------------------------------------------------------------------------
# inject_navigate_to: happy path
# ---------------------------------------------------------------------------

class TestInjectNavigateToHappyPath:
    """Tests for inject_navigate_to() normal operation."""

    def test_rich_format_injects_both_keys(self):
        """Rich format injects both clickAction (Android) and url (iOS)."""
        data = {}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == "/lovelace/cameras"
        assert data["url"] == "/lovelace/cameras"

    def test_plain_format_injects_both_keys(self):
        """Plain format injects both clickAction and url."""
        data = {}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_PLAIN)
        assert data["clickAction"] == "/lovelace/cameras"
        assert data["url"] == "/lovelace/cameras"

    def test_custom_path_injected_correctly(self):
        """A custom HA path is used verbatim."""
        data = {}
        inject_navigate_to(data, "/lovelace/security", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == "/lovelace/security"
        assert data["url"] == "/lovelace/security"

    def test_external_url_injected(self):
        """An external URL is passed through without modification."""
        data = {}
        inject_navigate_to(data, "https://example.com/status", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == "https://example.com/status"
        assert data["url"] == "https://example.com/status"


# ---------------------------------------------------------------------------
# inject_navigate_to: default fallback
# ---------------------------------------------------------------------------

class TestInjectNavigateToDefault:
    """Tests for None navigate_to falling back to DEFAULT_NAVIGATE_TO."""

    def test_none_falls_back_to_default(self):
        data = {}
        inject_navigate_to(data, None, DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == DEFAULT_NAVIGATE_TO
        assert data["url"] == DEFAULT_NAVIGATE_TO

    def test_empty_string_falls_back_to_default(self):
        """Empty string is falsy, so it triggers the default."""
        data = {}
        inject_navigate_to(data, "", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == DEFAULT_NAVIGATE_TO
        assert data["url"] == DEFAULT_NAVIGATE_TO


# ---------------------------------------------------------------------------
# inject_navigate_to: skipped formats (TTS, persistent)
# ---------------------------------------------------------------------------

class TestInjectNavigateToSkippedFormats:
    """TTS and persistent formats have no tap navigation concept."""

    def test_tts_format_no_injection(self):
        data = {"existing": "value"}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_TTS)
        assert "clickAction" not in data
        assert "url" not in data
        assert data["existing"] == "value"

    def test_persistent_format_no_injection(self):
        data = {"existing": "value"}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_PERSISTENT)
        assert "clickAction" not in data
        assert "url" not in data
        assert data["existing"] == "value"

    def test_tts_with_none_navigate_to(self):
        """TTS skips even when navigate_to is None (no default injection)."""
        data = {}
        inject_navigate_to(data, None, DELIVERY_FORMAT_TTS)
        assert data == {}

    def test_persistent_with_none_navigate_to(self):
        data = {}
        inject_navigate_to(data, None, DELIVERY_FORMAT_PERSISTENT)
        assert data == {}


# ---------------------------------------------------------------------------
# inject_navigate_to: existing keys not overridden
# ---------------------------------------------------------------------------

class TestInjectNavigateToExistingKeys:
    """Automation-set values must never be overridden."""

    def test_existing_click_action_not_overridden(self):
        data = {"clickAction": "/custom/dashboard"}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == "/custom/dashboard"
        # url should still be injected since it was not present
        assert data["url"] == "/lovelace/cameras"

    def test_existing_url_not_overridden(self):
        data = {"url": "/custom/dashboard"}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_RICH)
        assert data["url"] == "/custom/dashboard"
        # clickAction should still be injected since it was not present
        assert data["clickAction"] == "/lovelace/cameras"

    def test_both_existing_keys_preserved(self):
        data = {"clickAction": "/android", "url": "/ios"}
        inject_navigate_to(data, "/lovelace/cameras", DELIVERY_FORMAT_RICH)
        assert data["clickAction"] == "/android"
        assert data["url"] == "/ios"

    def test_existing_keys_preserved_with_none_navigate_to(self):
        """Even with default fallback, existing keys must not be overridden."""
        data = {"clickAction": "/my-dashboard", "url": "/my-page"}
        inject_navigate_to(data, None, DELIVERY_FORMAT_PLAIN)
        assert data["clickAction"] == "/my-dashboard"
        assert data["url"] == "/my-page"


# ---------------------------------------------------------------------------
# inject_navigate_to: edge cases
# ---------------------------------------------------------------------------

class TestInjectNavigateToEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_data_dict(self):
        """Starting from an empty dict should work fine."""
        data = {}
        inject_navigate_to(data, "/test", DELIVERY_FORMAT_RICH)
        assert len(data) == 2
        assert data["clickAction"] == "/test"
        assert data["url"] == "/test"

    def test_data_with_other_keys_preserved(self):
        """Other keys in the data dict are not disturbed."""
        data = {"tag": "ticker_alerts", "group": "ticker_alerts"}
        inject_navigate_to(data, "/test", DELIVERY_FORMAT_RICH)
        assert data["tag"] == "ticker_alerts"
        assert data["group"] == "ticker_alerts"
        assert data["clickAction"] == "/test"
        assert data["url"] == "/test"

    def test_mutates_in_place(self):
        """Verify the function mutates the dict, not returns a new one."""
        data = {}
        result = inject_navigate_to(data, "/test", DELIVERY_FORMAT_RICH)
        assert result is None  # returns None (void)
        assert "clickAction" in data


# ---------------------------------------------------------------------------
# Store: async_create_category with navigate_to
# ---------------------------------------------------------------------------

class TestCreateCategoryNavigateTo:
    """Tests for navigate_to parameter in async_create_category."""

    @pytest.mark.asyncio
    async def test_create_with_navigate_to_stores_it(self, store):
        cat = await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        assert cat["navigate_to"] == "/lovelace/cameras"

    @pytest.mark.asyncio
    async def test_create_without_navigate_to_omits_key(self, store):
        """Sparse storage: navigate_to key absent when not provided."""
        cat = await store.async_create_category("general", "General")
        assert "navigate_to" not in cat

    @pytest.mark.asyncio
    async def test_create_with_none_navigate_to_omits_key(self, store):
        """Explicit None is treated as omission (falsy check)."""
        cat = await store.async_create_category(
            "info", "Info", navigate_to=None
        )
        assert "navigate_to" not in cat

    @pytest.mark.asyncio
    async def test_create_with_empty_string_omits_key(self, store):
        """Empty string is falsy, so navigate_to is omitted."""
        cat = await store.async_create_category(
            "info", "Info", navigate_to=""
        )
        assert "navigate_to" not in cat

    @pytest.mark.asyncio
    async def test_create_persisted_in_store_dict(self, store):
        await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        stored = store._categories["cameras"]
        assert stored["navigate_to"] == "/lovelace/cameras"

    @pytest.mark.asyncio
    async def test_create_saves_to_storage(self, store):
        await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        store._categories_store.async_save.assert_awaited()


# ---------------------------------------------------------------------------
# Store: async_update_category with navigate_to
# ---------------------------------------------------------------------------

class TestUpdateCategoryNavigateTo:
    """Tests for navigate_to parameter in async_update_category."""

    @pytest.mark.asyncio
    async def test_update_sets_navigate_to(self, store):
        await store.async_create_category("cameras", "Cameras")
        cat = await store.async_update_category(
            "cameras", navigate_to="/lovelace/cameras"
        )
        assert cat["navigate_to"] == "/lovelace/cameras"

    @pytest.mark.asyncio
    async def test_update_changes_navigate_to(self, store):
        await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        cat = await store.async_update_category(
            "cameras", navigate_to="/lovelace/security"
        )
        assert cat["navigate_to"] == "/lovelace/security"

    @pytest.mark.asyncio
    async def test_update_empty_string_clears_navigate_to(self, store):
        """Empty string clears the key (sparse storage)."""
        await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        cat = await store.async_update_category("cameras", navigate_to="")
        assert "navigate_to" not in cat

    @pytest.mark.asyncio
    async def test_update_none_leaves_existing_untouched(self, store):
        """None means 'don't touch' -- existing navigate_to persists."""
        await store.async_create_category(
            "cameras", "Cameras", navigate_to="/lovelace/cameras"
        )
        cat = await store.async_update_category("cameras", name="Cameras v2")
        assert cat["navigate_to"] == "/lovelace/cameras"

    @pytest.mark.asyncio
    async def test_update_none_no_key_stays_absent(self, store):
        """When navigate_to was never set and None is passed, key stays absent."""
        await store.async_create_category("info", "Info")
        cat = await store.async_update_category("info", name="Info v2")
        assert "navigate_to" not in cat

    @pytest.mark.asyncio
    async def test_update_nonexistent_category_returns_none(self, store):
        result = await store.async_update_category(
            "missing", navigate_to="/lovelace/cameras"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_round_trip_set_clear_set(self, store):
        """Set -> clear -> set round-trip."""
        await store.async_create_category("cameras", "Cameras")

        # Set
        await store.async_update_category(
            "cameras", navigate_to="/lovelace/cameras"
        )
        assert store._categories["cameras"]["navigate_to"] == "/lovelace/cameras"

        # Clear
        await store.async_update_category("cameras", navigate_to="")
        assert "navigate_to" not in store._categories["cameras"]

        # Set again
        await store.async_update_category(
            "cameras", navigate_to="/lovelace/security"
        )
        assert store._categories["cameras"]["navigate_to"] == "/lovelace/security"
