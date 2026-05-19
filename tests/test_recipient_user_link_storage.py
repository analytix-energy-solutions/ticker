"""Tests for F-39 user_link storage on RecipientMixin (chunk 1).

Covers ``async_set_recipient_user_link`` sparse storage semantics and
the idempotency of ``migrate_recipient_data`` over user_link-bearing
recipients (the field is forward-compatible — no migration needed).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.const import (
    ATTR_USER_LINK,
    DEVICE_TYPE_PUSH,
)
from custom_components.ticker.store.recipients import RecipientMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeStore(RecipientMixin):
    """Concrete class mixing in RecipientMixin for testing."""

    def __init__(self, recipients=None, subscriptions=None):
        self.hass = MagicMock()
        self._recipients: dict = recipients if recipients is not None else {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self.async_save_subscriptions = AsyncMock()
        self._subscription_listeners: list = []

    def _notify_subscription_change(self) -> None:
        pass

    # Stubs SubscriptionMixin would normally provide — orphan-fallback
    # tests live in a separate module; storage tests don't exercise these.
    async def async_set_subscription(self, **kwargs):
        return None

    def get_subscriptions_for_person(self, person_id):
        return {}


@pytest.fixture
def store():
    s = FakeStore()
    s._recipients["tv_living"] = {
        "recipient_id": "tv_living",
        "name": "Living Room TV",
        "device_type": DEVICE_TYPE_PUSH,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    return s


# ---------------------------------------------------------------------------
# async_set_recipient_user_link — sparse storage
# ---------------------------------------------------------------------------

class TestSetRecipientUserLinkSetClear:
    @pytest.mark.asyncio
    async def test_set_writes_field(self, store):
        result = await store.async_set_recipient_user_link(
            "tv_living", "person.alice",
        )
        assert result[ATTR_USER_LINK] == "person.alice"
        assert store._recipients["tv_living"][ATTR_USER_LINK] == "person.alice"

    @pytest.mark.asyncio
    async def test_set_updates_timestamp(self, store):
        before = store._recipients["tv_living"]["updated_at"]
        await store.async_set_recipient_user_link("tv_living", "person.alice")
        assert store._recipients["tv_living"]["updated_at"] != before

    @pytest.mark.asyncio
    async def test_set_calls_save(self, store):
        await store.async_set_recipient_user_link("tv_living", "person.alice")
        store._recipients_store.async_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_pops_field_sparse(self, store):
        store._recipients["tv_living"][ATTR_USER_LINK] = "person.alice"
        result = await store.async_set_recipient_user_link("tv_living", None)
        # Field must be absent (sparse), not None.
        assert ATTR_USER_LINK not in result
        assert ATTR_USER_LINK not in store._recipients["tv_living"]

    @pytest.mark.asyncio
    async def test_clear_when_already_absent_is_noop_safe(self, store):
        assert ATTR_USER_LINK not in store._recipients["tv_living"]
        result = await store.async_set_recipient_user_link("tv_living", None)
        assert ATTR_USER_LINK not in result

    @pytest.mark.asyncio
    async def test_set_then_clear_roundtrip(self, store):
        await store.async_set_recipient_user_link("tv_living", "person.alice")
        assert store._recipients["tv_living"][ATTR_USER_LINK] == "person.alice"
        await store.async_set_recipient_user_link("tv_living", None)
        assert ATTR_USER_LINK not in store._recipients["tv_living"]

    @pytest.mark.asyncio
    async def test_unknown_recipient_raises_value_error(self, store):
        with pytest.raises(ValueError):
            await store.async_set_recipient_user_link("ghost", "person.alice")

    @pytest.mark.asyncio
    async def test_returns_recipient_dict(self, store):
        result = await store.async_set_recipient_user_link(
            "tv_living", "person.alice",
        )
        # Same identity as the stored record.
        assert result is store._recipients["tv_living"]

    @pytest.mark.asyncio
    async def test_persisted_shape_only_one_key_added(self, store):
        keys_before = set(store._recipients["tv_living"].keys())
        await store.async_set_recipient_user_link("tv_living", "person.alice")
        keys_after = set(store._recipients["tv_living"].keys())
        # Only user_link is new; updated_at was pre-existing.
        assert keys_after - keys_before == {ATTR_USER_LINK}


# ---------------------------------------------------------------------------
# migrate_recipient_data — forward-compatible w/ user_link
# ---------------------------------------------------------------------------

class TestMigrateIdempotentWithUserLink:
    def test_migrate_preserves_existing_user_link(self):
        recipients = {
            "tv1": {
                "device_type": DEVICE_TYPE_PUSH,
                "delivery_format": "rich",
                ATTR_USER_LINK: "person.alice",
            },
        }
        RecipientMixin.migrate_recipient_data(recipients)
        # Idempotent — user_link untouched.
        assert recipients["tv1"][ATTR_USER_LINK] == "person.alice"

    def test_migrate_no_user_link_remains_absent(self):
        recipients = {
            "tv1": {
                "device_type": DEVICE_TYPE_PUSH,
                "delivery_format": "rich",
            },
        }
        RecipientMixin.migrate_recipient_data(recipients)
        assert ATTR_USER_LINK not in recipients["tv1"]
