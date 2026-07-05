"""Tests for F-39 orphan-fallback handler (chunk 1).

When a linked person entity is removed, ``async_handle_person_removed``
copies the user's current subscriptions into the recipient's own rows
(tagged ``set_by=orphan_fallback``) and clears ``user_link``.
"""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.const import (
    ATTR_USER_LINK,
    DEVICE_TYPE_PUSH,
    MODE_ALWAYS,
    MODE_CONDITIONAL,
    SET_BY_ORPHAN_FALLBACK,
)
from custom_components.ticker.store.recipients import RecipientMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeStore(RecipientMixin):
    """Concrete store with the minimal SubscriptionMixin surface.

    ``async_set_subscription`` writes into ``_subscriptions`` using the
    canonical ``{person_id}:{category_id}`` key so the orphan-fallback
    handler's recipient: prefix writes go to the right place.
    """

    def __init__(self, recipients=None, subscriptions=None):
        self.hass = MagicMock()
        self._recipients: dict = recipients if recipients is not None else {}
        self._recipients_store = MagicMock()
        self._recipients_store.async_save = AsyncMock()
        self._subscriptions: dict = subscriptions if subscriptions is not None else {}
        self._subscriptions_store = MagicMock()
        self._subscriptions_store.async_save = AsyncMock()
        self._subscription_listeners: list = []
        # Track every set call so tests can assert set_by + payload shape.
        self.set_subscription_calls: list[dict] = []

    def _notify_subscription_change(self) -> None:
        pass

    async def async_save_subscriptions(self) -> None:
        await self._subscriptions_store.async_save(self._subscriptions)

    async def async_set_subscription(
        self,
        person_id: str,
        category_id: str,
        mode: str,
        conditions=None,
        set_by: str | None = None,
    ) -> dict:
        """Minimal stand-in matching SubscriptionMixin's signature."""
        sub = {
            "person_id": person_id,
            "category_id": category_id,
            "mode": mode,
            "set_by": set_by,
        }
        if conditions is not None:
            sub["conditions"] = conditions
        key = f"{person_id}:{category_id}"
        self._subscriptions[key] = sub
        self.set_subscription_calls.append({
            "person_id": person_id,
            "category_id": category_id,
            "mode": mode,
            "conditions": conditions,
            "set_by": set_by,
        })
        return sub

    def get_subscriptions_for_person(self, person_id: str) -> dict:
        prefix = f"{person_id}:"
        return {
            key.split(":", 1)[1]: sub
            for key, sub in self._subscriptions.items()
            if key.startswith(prefix)
        }


def _make_recipient(rid: str, linked_to: str | None) -> dict:
    rec = {
        "recipient_id": rid,
        "name": rid.replace("_", " ").title(),
        "device_type": DEVICE_TYPE_PUSH,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    if linked_to is not None:
        rec[ATTR_USER_LINK] = linked_to
    return rec


@pytest.fixture
def store_with_link():
    store = FakeStore()
    store._recipients["tv_living"] = _make_recipient("tv_living", "person.alice")
    store._recipients["tv_kitchen"] = _make_recipient("tv_kitchen", None)
    # Alice has two subs: an always and a conditional.
    store._subscriptions["person.alice:alerts"] = {
        "person_id": "person.alice",
        "category_id": "alerts",
        "mode": MODE_ALWAYS,
        "set_by": "user",
    }
    store._subscriptions["person.alice:dinner"] = {
        "person_id": "person.alice",
        "category_id": "dinner",
        "mode": MODE_CONDITIONAL,
        "set_by": "user",
        "conditions": {
            "version": 1,
            "tree": {"type": "group", "operator": "AND", "children": []},
        },
    }
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrphanFallback:
    @pytest.mark.asyncio
    async def test_copies_subs_into_recipient_rows(self, store_with_link):
        count = await store_with_link.async_handle_person_removed("person.alice")
        assert count == 1
        # Recipient now has its own subscription rows under recipient:tv_living:*
        assert "recipient:tv_living:alerts" in store_with_link._subscriptions
        assert "recipient:tv_living:dinner" in store_with_link._subscriptions

    @pytest.mark.asyncio
    async def test_clears_user_link(self, store_with_link):
        await store_with_link.async_handle_person_removed("person.alice")
        assert ATTR_USER_LINK not in store_with_link._recipients["tv_living"]

    @pytest.mark.asyncio
    async def test_set_by_orphan_fallback_recorded(self, store_with_link):
        await store_with_link.async_handle_person_removed("person.alice")
        for call in store_with_link.set_subscription_calls:
            assert call["set_by"] == SET_BY_ORPHAN_FALLBACK

    @pytest.mark.asyncio
    async def test_recipient_save_called(self, store_with_link):
        await store_with_link.async_handle_person_removed("person.alice")
        store_with_link._recipients_store.async_save.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_op_when_no_linked_recipients(self):
        store = FakeStore()
        store._recipients["tv_living"] = _make_recipient("tv_living", None)
        # Even with subs for that person, no recipient links -> no copies.
        store._subscriptions["person.alice:alerts"] = {
            "person_id": "person.alice",
            "category_id": "alerts",
            "mode": MODE_ALWAYS,
        }
        count = await store.async_handle_person_removed("person.alice")
        assert count == 0
        assert store.set_subscription_calls == []
        # Recipients store should not be saved when nothing changes.
        store._recipients_store.async_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_recipients_affected(self):
        store = FakeStore()
        store._recipients["tv_living"] = _make_recipient(
            "tv_living", "person.alice",
        )
        store._recipients["tv_bedroom"] = _make_recipient(
            "tv_bedroom", "person.alice",
        )
        store._recipients["tv_kitchen"] = _make_recipient(
            "tv_kitchen", "person.bob",
        )
        store._subscriptions["person.alice:alerts"] = {
            "person_id": "person.alice",
            "category_id": "alerts",
            "mode": MODE_ALWAYS,
        }
        count = await store.async_handle_person_removed("person.alice")
        assert count == 2
        assert ATTR_USER_LINK not in store._recipients["tv_living"]
        assert ATTR_USER_LINK not in store._recipients["tv_bedroom"]
        # Unlinked recipient untouched.
        assert store._recipients["tv_kitchen"][ATTR_USER_LINK] == "person.bob"

    @pytest.mark.asyncio
    async def test_conditions_deep_copied(self, store_with_link):
        await store_with_link.async_handle_person_removed("person.alice")
        # Find the conditional copy that was written.
        recipient_sub = store_with_link._subscriptions[
            "recipient:tv_living:dinner"
        ]
        source_sub = store_with_link._subscriptions.get("person.alice:dinner")
        # Person's row may have been preserved (we don't delete it in chunk 1
        # — that responsibility is upstream / out of scope). Even if it had
        # been deleted, the recipient's conditions must own an independent
        # dict so future mutations don't cross-contaminate.
        if source_sub is not None:
            assert recipient_sub["conditions"] is not source_sub["conditions"]
            # Mutate source: recipient untouched.
            source_sub["conditions"]["mutated"] = True
            assert "mutated" not in recipient_sub["conditions"]

    @pytest.mark.asyncio
    async def test_recipient_updated_at_refreshed(self, store_with_link):
        before = store_with_link._recipients["tv_living"]["updated_at"]
        await store_with_link.async_handle_person_removed("person.alice")
        after = store_with_link._recipients["tv_living"]["updated_at"]
        assert before != after

    @pytest.mark.asyncio
    async def test_returns_zero_when_unknown_person(self):
        store = FakeStore()
        store._recipients["tv_living"] = _make_recipient("tv_living", None)
        count = await store.async_handle_person_removed("person.ghost")
        assert count == 0
