"""Tests for the per-category ``bundle_on_release`` toggle.

Covers:
- Store sparse persistence (create + update) mirroring expose_in_sensor.
- ``async_deliver_released_notifications`` delivery split: categories that
  opt out of bundling get one notification per entry; the rest keep the
  historical single-summary bundle.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.bundled_notify import (
    async_deliver_released_notifications,
)
from custom_components.ticker.store.categories import CategoryMixin
from custom_components.ticker.websocket.categories import (
    ws_create_category,
    ws_update_category,
)


class _FakeCategoryStore(CategoryMixin):
    """Concrete CategoryMixin host for store-level assertions."""

    def __init__(self):
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()


@pytest.fixture
def cat_store():
    return _FakeCategoryStore()


# ---------------------------------------------------------------------------
# Delivery split
# ---------------------------------------------------------------------------

def _entry(queue_id: str, category_id: str) -> dict:
    return {
        "queue_id": queue_id,
        "category_id": category_id,
        "title": f"T-{queue_id}",
        "message": f"M-{queue_id}",
    }


def _store(categories: dict[str, dict]) -> MagicMock:
    store = MagicMock()
    store.get_category.side_effect = lambda cid: categories.get(cid)
    return store


@pytest.mark.asyncio
async def test_default_categories_bundle_together():
    """With no opt-out, all released entries go out as one bundle call."""
    store = _store({"news": {"name": "News"}})  # no bundle_on_release key
    entries = [_entry("q1", "news"), _entry("q2", "news")]

    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", entries, store
        )

    assert failed == []
    # One bundled call carrying both entries.
    assert mock_send.await_count == 1
    assert mock_send.await_args.args[2] == entries


@pytest.mark.asyncio
async def test_opt_out_category_delivers_per_entry():
    """bundle_on_release=False -> one send call per entry."""
    store = _store({"appliance_done": {"bundle_on_release": False}})
    entries = [_entry("q1", "appliance_done"), _entry("q2", "appliance_done")]

    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", entries, store
        )

    assert failed == []
    assert mock_send.await_count == 2
    # Each call carries exactly one entry (full payload preserved by the
    # count==1 path in async_send_bundled_notification).
    sent = [call.args[2] for call in mock_send.await_args_list]
    assert [len(s) for s in sent] == [1, 1]
    assert {s[0]["queue_id"] for s in sent} == {"q1", "q2"}


@pytest.mark.asyncio
async def test_mixed_categories_split():
    """Opt-out entries go individually; the rest are bundled in one call."""
    store = _store(
        {
            "appliance_done": {"bundle_on_release": False},
            "news": {"name": "News"},
        }
    )
    entries = [
        _entry("q1", "appliance_done"),
        _entry("q2", "news"),
        _entry("q3", "appliance_done"),
        _entry("q4", "news"),
    ]

    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", entries, store
        )

    assert failed == []
    # 2 individual + 1 bundle = 3 calls.
    assert mock_send.await_count == 3
    sizes = sorted(len(call.args[2]) for call in mock_send.await_args_list)
    assert sizes == [1, 1, 2]


@pytest.mark.asyncio
async def test_failed_entries_returned_for_requeue():
    """A failed individual delivery is returned; successes are not."""
    store = _store({"appliance_done": {"bundle_on_release": False}})
    entries = [_entry("q1", "appliance_done"), _entry("q2", "appliance_done")]

    # First send succeeds, second fails.
    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(side_effect=[True, False]),
    ):
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", entries, store
        )

    assert [e["queue_id"] for e in failed] == ["q2"]


@pytest.mark.asyncio
async def test_empty_entries_short_circuit():
    store = _store({})
    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", [], store
        )
    assert failed == []
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_category_defaults_to_bundle():
    """A missing category (get_category -> None) keeps default bundling."""
    store = _store({})  # get_category returns None for any id
    entries = [_entry("q1", "ghost"), _entry("q2", "ghost")]

    with patch(
        "custom_components.ticker.bundled_notify.async_send_bundled_notification",
        new=AsyncMock(return_value=True),
    ) as mock_send:
        failed = await async_deliver_released_notifications(
            MagicMock(), "person.alice", entries, store
        )

    assert failed == []
    assert mock_send.await_count == 1
    assert len(mock_send.await_args.args[2]) == 2


# ---------------------------------------------------------------------------
# Store sparse persistence (default True, stored only when False)
# ---------------------------------------------------------------------------

class TestStorePersistence:
    @pytest.mark.asyncio
    async def test_create_false_persists_key(self, cat_store):
        cat = await cat_store.async_create_category(
            "appliance_done", "Appliance done", bundle_on_release=False
        )
        assert cat["bundle_on_release"] is False

    @pytest.mark.asyncio
    async def test_create_true_omits_key(self, cat_store):
        cat = await cat_store.async_create_category(
            "news", "News", bundle_on_release=True
        )
        assert "bundle_on_release" not in cat

    @pytest.mark.asyncio
    async def test_create_default_omits_key(self, cat_store):
        cat = await cat_store.async_create_category("news", "News")
        assert "bundle_on_release" not in cat

    @pytest.mark.asyncio
    async def test_update_set_false_persists(self, cat_store):
        await cat_store.async_create_category("appliance_done", "Appliance done")
        cat = await cat_store.async_update_category(
            "appliance_done", bundle_on_release=False
        )
        assert cat["bundle_on_release"] is False

    @pytest.mark.asyncio
    async def test_update_set_true_removes_key(self, cat_store):
        await cat_store.async_create_category(
            "appliance_done", "Appliance done", bundle_on_release=False
        )
        cat = await cat_store.async_update_category(
            "appliance_done", bundle_on_release=True
        )
        assert "bundle_on_release" not in cat

    @pytest.mark.asyncio
    async def test_update_none_leaves_unchanged(self, cat_store):
        await cat_store.async_create_category(
            "appliance_done", "Appliance done", bundle_on_release=False
        )
        cat = await cat_store.async_update_category(
            "appliance_done", name="Renamed"
        )
        assert cat["bundle_on_release"] is False


# ---------------------------------------------------------------------------
# WebSocket pass-through
# ---------------------------------------------------------------------------

def _ws_mocks(exists: bool = True):
    hass = MagicMock()
    conn = MagicMock()
    store = MagicMock()
    store.category_exists.return_value = exists
    store.async_create_category = AsyncMock(return_value={"id": "appliance_done"})
    store.async_update_category = AsyncMock(return_value={"id": "appliance_done"})
    hass.config_entries.async_entries.return_value = []
    return hass, conn, store


@contextmanager
def _ws_patches(store):
    with patch(
        "custom_components.ticker.websocket.categories.get_store",
        return_value=store,
    ), patch(
        "custom_components.ticker.websocket.categories.validate_category_id",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_icon",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_color",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.validate_navigate_to",
        return_value=(True, None),
    ), patch(
        "custom_components.ticker.websocket.categories.sanitize_for_storage",
        side_effect=lambda v, _: v,
    ):
        yield


class TestWebSocketPassThrough:
    @pytest.mark.asyncio
    async def test_create_forwards_bundle_on_release(self):
        hass, conn, store = _ws_mocks(exists=False)
        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "appliance_done",
            "name": "Appliance done",
            "bundle_on_release": False,
        }
        with _ws_patches(store):
            await ws_create_category(hass, conn, msg)
        assert store.async_create_category.await_args.kwargs["bundle_on_release"] is False

    @pytest.mark.asyncio
    async def test_create_omits_when_absent(self):
        hass, conn, store = _ws_mocks(exists=False)
        msg = {
            "id": 1,
            "type": "ticker/category/create",
            "category_id": "news",
            "name": "News",
        }
        with _ws_patches(store):
            await ws_create_category(hass, conn, msg)
        # Absent in msg -> None passed -> store keeps default (bundle).
        assert store.async_create_category.await_args.kwargs["bundle_on_release"] is None

    @pytest.mark.asyncio
    async def test_update_forwards_bundle_on_release(self):
        hass, conn, store = _ws_mocks(exists=True)
        msg = {
            "id": 2,
            "type": "ticker/category/update",
            "category_id": "appliance_done",
            "bundle_on_release": False,
        }
        with _ws_patches(store):
            await ws_update_category(hass, conn, msg)
        assert store.async_update_category.await_args.kwargs["bundle_on_release"] is False
