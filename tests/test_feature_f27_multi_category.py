"""Tests for F-27: Multi-category fan-out in ticker.notify.

The service handler accepts either a single category string (backwards
compat) or a list of categories. For lists, the handler must:

- Loop once per category (deduplicated, preserving order).
- Generate a fresh notification_id per category.
- Make a per-category copy of the base data dict so the critical flag on
  one category cannot leak into the next.
- Skip categories that do not resolve but log a warning and continue.
- Raise ServiceValidationError when the list is empty or when NO category
  in the list resolves.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ServiceValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.async_register = MagicMock()
    hass.states = MagicMock()
    hass.states.async_all.return_value = []  # no persons to keep loops quiet
    return hass


def _make_store(known_categories: list[str], critical_map: dict[str, bool] | None = None):
    """Mock store that recognizes the given category ids."""
    critical_map = critical_map or {}
    store = MagicMock()
    store.get_recipients.return_value = {}
    store.category_exists.side_effect = lambda cid: cid in known_categories
    store.get_categories.return_value = {cid: {"name": cid} for cid in known_categories}

    def _get_category(cid):
        if cid not in known_categories:
            return None
        return {"name": cid, "critical": critical_map.get(cid, False)}

    store.get_category.side_effect = _get_category
    store.is_user_enabled.return_value = True
    store.get_subscription_mode.return_value = "always"
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    return store


async def _get_handler(hass):
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    return hass.services.async_register.call_args_list[0][0][2]


def _make_call(category, *, title="T", message="M", extra_data=None, critical=None):
    call = MagicMock()
    call.data = {
        "category": category,
        "title": title,
        "message": message,
    }
    if extra_data is not None:
        call.data["data"] = extra_data
    if critical is not None:
        call.data["critical"] = critical
    return call


def _patch_entry(store):
    entry = MagicMock()
    entry.runtime_data.store = store
    entry.runtime_data.auto_clear = None
    return patch(
        "custom_components.ticker.services._get_loaded_entry",
        return_value=entry,
    )


# ---------------------------------------------------------------------------
# Fan-out behavior
# ---------------------------------------------------------------------------

class TestF27MultiCategoryFanOut:
    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_list_of_two_categories_dispatches_twice(self, _sensor):
        """category=['cat_a','cat_b'] should dispatch once per category."""
        hass = _make_hass()
        store = _make_store(["cat_a", "cat_b"])
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            await handler(_make_call(["cat_a", "cat_b"]))

        # get_category called at least once per category in the fan-out loop
        called_cats = {c.args[0] for c in store.get_category.call_args_list}
        assert {"cat_a", "cat_b"}.issubset(called_cats)

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_each_category_gets_unique_notification_id(self, _sensor):
        """Fan-out must mint a fresh uuid4 per category."""
        hass = _make_hass()
        store = _make_store(["cat_a", "cat_b"])
        # A single person so the sensor path is exercised with data per loop.
        person = MagicMock()
        person.entity_id = "person.alice"
        person.attributes = {"friendly_name": "Alice"}
        hass.states.async_all.return_value = [person]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call(["cat_a", "cat_b"]))

        nids = [c.kwargs["notification_id"] for c in mock_send.call_args_list]
        assert len(nids) == 2
        assert nids[0] != nids[1]

    @pytest.mark.asyncio
    async def test_empty_list_raises_service_validation_error(self):
        """An empty list must fail fast with ServiceValidationError."""
        hass = _make_hass()
        store = _make_store(["cat_a"])
        handler = await _get_handler(hass)

        with _patch_entry(store):
            with pytest.raises(ServiceValidationError):
                await handler(_make_call([]))

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_duplicate_categories_processed_once(self, _sensor):
        """['cat_a','cat_a'] should only dispatch one notification."""
        hass = _make_hass()
        store = _make_store(["cat_a"])
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            await handler(_make_call(["cat_a", "cat_a"]))

        # get_category for the cat_a key should be called exactly once from
        # the fan-out loop. category_exists is what the loop resolves first,
        # so we assert de-dup by counting resolve calls.
        assert store.category_exists.call_count == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_invalid_category_logged_valid_categories_continue(self, _sensor):
        """An unknown id in the list must not abort the whole fan-out."""
        hass = _make_hass()
        store = _make_store(["cat_a"])  # cat_bad does NOT exist
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            # Should not raise — cat_a is valid
            await handler(_make_call(["cat_bad", "cat_a"]))

        # get_category was called for the resolved category at least once
        called_cats = {c.args[0] for c in store.get_category.call_args_list}
        assert "cat_a" in called_cats

    @pytest.mark.asyncio
    async def test_all_invalid_list_raises_service_validation_error(self):
        """If every category in the list is invalid, raise the last error."""
        hass = _make_hass()
        store = _make_store(["cat_real"])  # list below has none of these
        handler = await _get_handler(hass)

        with _patch_entry(store):
            with pytest.raises(ServiceValidationError):
                await handler(_make_call(["nope1", "nope2"]))

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_single_string_still_works_backward_compat(self, _sensor):
        """category='cat_a' (not a list) still dispatches a single notification."""
        hass = _make_hass()
        store = _make_store(["cat_a"])
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            await handler(_make_call("cat_a"))

        called_cats = {c.args[0] for c in store.get_category.call_args_list}
        assert "cat_a" in called_cats

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_critical_flag_does_not_leak_between_categories(self, _sensor):
        """
        Category cat_a is critical, cat_b is not. The data dict passed to the
        second category's dispatch must NOT carry critical=True inherited from
        the first category iteration. This is the per-loop `dict(base_data)`
        copy guard.
        """
        hass = _make_hass()
        store = _make_store(
            ["cat_a", "cat_b"],
            critical_map={"cat_a": True, "cat_b": False},
        )
        person = MagicMock()
        person.entity_id = "person.alice"
        person.attributes = {"friendly_name": "Alice"}
        hass.states.async_all.return_value = [person]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call(["cat_a", "cat_b"]))

        # Two dispatch calls, one per category.
        assert mock_send.await_count == 2
        # Resolve by matching category_id kwarg.
        by_cat = {c.kwargs["category_id"]: c.kwargs["data"] for c in mock_send.call_args_list}
        assert by_cat["cat_a"].get("critical") is True
        assert "critical" not in by_cat["cat_b"], (
            "F-27 regression: critical flag leaked from cat_a into cat_b. "
            "The per-category `data_for_cat = dict(base_data)` copy is the "
            "guard that should prevent this."
        )
