"""Tests for F-18 subscription query methods in SubscriptionMixin.

Focuses on the three new query methods added for recipient support:
- get_subscriptions_for_recipient()
- get_recipient_subscriptions_for_category()
- get_user_subscriptions_for_category()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store.subscriptions import SubscriptionMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeSubStore(SubscriptionMixin):
    """Concrete class mixing in SubscriptionMixin for testing."""

    def __init__(self, subscriptions=None):
        self.hass = MagicMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self._subscriptions_store = MagicMock()
        self._subscriptions_store.async_save = AsyncMock()
        self._categories: dict = {}


def _make_sub(person_id: str, category_id: str, mode: str = "always") -> dict:
    return {"person_id": person_id, "category_id": category_id, "mode": mode}


# Canonical test data: mix of person and recipient subscriptions
MIXED_SUBS = {
    "person.alice:weather": _make_sub("person.alice", "weather"),
    "person.bob:weather": _make_sub("person.bob", "weather"),
    "person.alice:security": _make_sub("person.alice", "security"),
    "recipient:tv1:weather": _make_sub("recipient:tv1", "weather"),
    "recipient:tv1:security": _make_sub("recipient:tv1", "security"),
    "recipient:speaker1:weather": _make_sub("recipient:speaker1", "weather"),
}


@pytest.fixture
def mixed_store():
    return FakeSubStore(dict(MIXED_SUBS))


# ---------------------------------------------------------------------------
# get_subscriptions_for_recipient
# ---------------------------------------------------------------------------

class TestGetSubscriptionsForRecipient:
    def test_returns_matching_subs(self, mixed_store):
        result = mixed_store.get_subscriptions_for_recipient("tv1")
        assert set(result.keys()) == {"weather", "security"}

    def test_returns_empty_for_unknown(self, mixed_store):
        assert mixed_store.get_subscriptions_for_recipient("missing") == {}

    def test_does_not_include_person_subs(self, mixed_store):
        result = mixed_store.get_subscriptions_for_recipient("tv1")
        for sub in result.values():
            assert sub["person_id"].startswith("recipient:")

    def test_key_parsing_with_colon_in_id(self):
        """Verify split(':', 2) handles the 'recipient:id:cat' format."""
        store = FakeSubStore({
            "recipient:my_device:cat1": _make_sub("recipient:my_device", "cat1"),
        })
        result = store.get_subscriptions_for_recipient("my_device")
        assert "cat1" in result

    def test_single_recipient(self, mixed_store):
        result = mixed_store.get_subscriptions_for_recipient("speaker1")
        assert set(result.keys()) == {"weather"}


# ---------------------------------------------------------------------------
# get_recipient_subscriptions_for_category
# ---------------------------------------------------------------------------

class TestGetRecipientSubscriptionsForCategory:
    def test_returns_only_recipient_subs(self, mixed_store):
        result = mixed_store.get_recipient_subscriptions_for_category("weather")
        # Should include tv1 and speaker1, not alice or bob
        person_ids = {s["person_id"] for s in result}
        assert person_ids == {"recipient:tv1", "recipient:speaker1"}

    def test_empty_for_no_recipients(self):
        store = FakeSubStore({
            "person.alice:weather": _make_sub("person.alice", "weather"),
        })
        assert store.get_recipient_subscriptions_for_category("weather") == []

    def test_empty_for_unknown_category(self, mixed_store):
        assert mixed_store.get_recipient_subscriptions_for_category("nonexistent") == []

    def test_security_category(self, mixed_store):
        result = mixed_store.get_recipient_subscriptions_for_category("security")
        assert len(result) == 1
        assert result[0]["person_id"] == "recipient:tv1"


# ---------------------------------------------------------------------------
# get_user_subscriptions_for_category
# ---------------------------------------------------------------------------

class TestGetUserSubscriptionsForCategory:
    def test_returns_only_person_subs(self, mixed_store):
        result = mixed_store.get_user_subscriptions_for_category("weather")
        person_ids = {s["person_id"] for s in result}
        assert person_ids == {"person.alice", "person.bob"}

    def test_excludes_recipient_subs(self, mixed_store):
        result = mixed_store.get_user_subscriptions_for_category("weather")
        for sub in result:
            assert not sub["person_id"].startswith("recipient:")

    def test_empty_for_no_users(self):
        store = FakeSubStore({
            "recipient:tv1:weather": _make_sub("recipient:tv1", "weather"),
        })
        assert store.get_user_subscriptions_for_category("weather") == []

    def test_empty_for_unknown_category(self, mixed_store):
        assert mixed_store.get_user_subscriptions_for_category("nonexistent") == []

    def test_security_category(self, mixed_store):
        result = mixed_store.get_user_subscriptions_for_category("security")
        assert len(result) == 1
        assert result[0]["person_id"] == "person.alice"


# ---------------------------------------------------------------------------
# Existing method: get_subscriptions_for_category (regression)
# ---------------------------------------------------------------------------

class TestGetSubscriptionsForCategory:
    """Verify existing method still returns both person AND recipient subs."""

    def test_returns_all_subs(self, mixed_store):
        result = mixed_store.get_subscriptions_for_category("weather")
        assert len(result) == 4  # alice, bob, tv1, speaker1

    def test_empty_category(self, mixed_store):
        assert mixed_store.get_subscriptions_for_category("nonexistent") == []
