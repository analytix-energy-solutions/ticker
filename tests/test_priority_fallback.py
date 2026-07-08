"""Tests for category-level priority fallback.

Covers:
- store/categories.py: sparse persist/normalize of priority_fallback
- services._resolve_priority_group: only_home_then_away / just_left_then_away
- services._dispatch_to_category: winning group is what actually gets
  notified, losing persons are logged as skipped
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.priority_fallback import resolve_priority_group as _resolve_priority_group
from custom_components.ticker.store.categories import _normalize_priority_fallback


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _person(entity_id: str, state: str, minutes_ago: float = 0) -> MagicMock:
    p = MagicMock()
    p.entity_id = entity_id
    p.state = state
    p.last_changed = _NOW - timedelta(minutes=minutes_ago)
    p.attributes = {"friendly_name": entity_id}
    return p


# ---------------------------------------------------------------------------
# store normalization
# ---------------------------------------------------------------------------

class TestNormalizePriorityFallback:
    def test_valid_mode_normalizes_with_default_window(self):
        result = _normalize_priority_fallback({"mode": "only_home_then_away"})
        assert result == {"mode": "only_home_then_away", "window_minutes": 2}

    def test_valid_mode_with_explicit_window(self):
        result = _normalize_priority_fallback({
            "mode": "just_left_then_away", "window_minutes": 10,
        })
        assert result == {"mode": "just_left_then_away", "window_minutes": 10}

    def test_unknown_mode_returns_none(self):
        assert _normalize_priority_fallback({"mode": "sideways"}) is None

    def test_none_returns_none(self):
        assert _normalize_priority_fallback(None) is None

    def test_empty_dict_returns_none(self):
        assert _normalize_priority_fallback({}) is None

    def test_invalid_window_falls_back_to_default(self):
        result = _normalize_priority_fallback({
            "mode": "only_home_then_away", "window_minutes": -5,
        })
        assert result["window_minutes"] == 2


# ---------------------------------------------------------------------------
# _resolve_priority_group: only_home_then_away
# ---------------------------------------------------------------------------

class TestOnlyHomeThenAway:
    def test_home_persons_win_when_present(self):
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home"),
        ]
        winners = _resolve_priority_group(
            persons, {"mode": "only_home_then_away"}, _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.frank"]

    def test_falls_back_to_everyone_away_when_nobody_home(self):
        persons = [
            _person("person.frank", "not_home"),
            _person("person.kevin", "not_home"),
        ]
        winners = _resolve_priority_group(
            persons, {"mode": "only_home_then_away"}, _NOW,
        )
        assert {p.entity_id for p in winners} == {"person.frank", "person.kevin"}

    def test_empty_persons_list(self):
        winners = _resolve_priority_group([], {"mode": "only_home_then_away"}, _NOW)
        assert winners == []


# ---------------------------------------------------------------------------
# _resolve_priority_group: just_left_then_away
# ---------------------------------------------------------------------------

class TestJustLeftThenAway:
    def test_recently_left_persons_win(self):
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home", minutes_ago=1),
            _person("person.caroline", "not_home", minutes_ago=30),
        ]
        winners = _resolve_priority_group(
            persons,
            {"mode": "just_left_then_away", "window_minutes": 5},
            _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.kevin"]

    def test_falls_back_to_everyone_away_when_nobody_just_left(self):
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home", minutes_ago=30),
        ]
        winners = _resolve_priority_group(
            persons,
            {"mode": "just_left_then_away", "window_minutes": 5},
            _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.kevin"]

    def test_home_persons_never_win(self):
        persons = [_person("person.frank", "home", minutes_ago=1)]
        winners = _resolve_priority_group(
            persons,
            {"mode": "just_left_then_away", "window_minutes": 5},
            _NOW,
        )
        assert winners == []

    def test_default_window_used_when_omitted(self):
        persons = [_person("person.kevin", "not_home", minutes_ago=1)]
        winners = _resolve_priority_group(
            persons, {"mode": "just_left_then_away"}, _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.kevin"]


class TestUnknownMode:
    def test_unknown_mode_returns_all_persons_unchanged(self):
        persons = [_person("person.frank", "home"), _person("person.kevin", "not_home")]
        winners = _resolve_priority_group(persons, {"mode": "sideways"}, _NOW)
        assert winners is persons


# ---------------------------------------------------------------------------
# Unresolved presence (unknown/unavailable) excluded from both groups
# ---------------------------------------------------------------------------

class TestUnresolvedPresenceExcluded:
    def test_unknown_state_excluded_from_only_home_then_away(self):
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "unknown"),
        ]
        winners = _resolve_priority_group(
            persons, {"mode": "only_home_then_away"}, _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.frank"]

    def test_unavailable_state_not_selected_as_away_fallback(self):
        """Nobody home and the only other person is unavailable: fallback
        must not guess that unavailable == away."""
        persons = [
            _person("person.frank", "not_home"),
            _person("person.kevin", "unavailable"),
        ]
        winners = _resolve_priority_group(
            persons, {"mode": "only_home_then_away"}, _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.frank"]

    def test_unknown_state_excluded_from_just_left_then_away(self):
        persons = [
            _person("person.kevin", "unknown", minutes_ago=1),
            _person("person.caroline", "not_home", minutes_ago=1),
        ]
        winners = _resolve_priority_group(
            persons,
            {"mode": "just_left_then_away", "window_minutes": 5},
            _NOW,
        )
        assert [p.entity_id for p in winners] == ["person.caroline"]


# ---------------------------------------------------------------------------
# Store-layer window_minutes guards (NaN, out-of-range)
# ---------------------------------------------------------------------------

class TestNormalizePriorityFallbackWindowGuards:
    def test_nan_window_falls_back_to_default(self):
        result = _normalize_priority_fallback({
            "mode": "only_home_then_away", "window_minutes": float("nan"),
        })
        assert result["window_minutes"] == 2

    def test_excessive_window_falls_back_to_default(self):
        result = _normalize_priority_fallback({
            "mode": "only_home_then_away", "window_minutes": 999999,
        })
        assert result["window_minutes"] == 2

    def test_max_window_is_accepted(self):
        result = _normalize_priority_fallback({
            "mode": "only_home_then_away", "window_minutes": 1440,
        })
        assert result["window_minutes"] == 1440


# ---------------------------------------------------------------------------
# Dispatch integration: winning group is notified, losers are logged skipped
# ---------------------------------------------------------------------------


def _make_hass(persons):
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.async_register = MagicMock()
    hass.states = MagicMock()
    hass.states.async_all.return_value = persons
    hass.states.get = lambda eid: next((p for p in persons if p.entity_id == eid), None)
    return hass


def _make_store(category: dict):
    store = MagicMock()
    store.get_recipients.return_value = {}
    store.category_exists.side_effect = lambda cid: cid == category["id"]
    store.get_categories.return_value = {category["id"]: category}
    store.get_category.side_effect = (
        lambda cid: category if cid == category["id"] else None
    )
    store.is_user_enabled.return_value = True
    store.get_subscription_mode.return_value = "always"
    store.async_add_log = AsyncMock()
    return store


def _patch_entry(store):
    entry = MagicMock()
    entry.runtime_data.store = store
    entry.runtime_data.auto_clear = None
    return patch(
        "custom_components.ticker.services._get_loaded_entry",
        return_value=entry,
    )


async def _get_handler(hass):
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    return hass.services.async_register.call_args_list[0][0][2]


def _make_call(category):
    call = MagicMock()
    call.data = {"category": category, "title": "T", "message": "M"}
    return call


class TestDispatchAppliesPriorityFallback:
    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_only_home_person_is_notified_other_is_skipped(self, _sensor):
        category = {
            "id": "alerts",
            "priority_fallback": {"mode": "only_home_then_away", "window_minutes": 2},
        }
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home"),
        ]
        hass = _make_hass(persons)
        store = _make_store(category)
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts"))

        assert mock_send.await_count == 1
        assert mock_send.call_args.args[2] == "person.frank"

        skipped_calls = [
            c for c in store.async_add_log.call_args_list
            if c.kwargs.get("person_id") == "person.kevin"
        ]
        assert len(skipped_calls) == 1
        assert "Priority fallback" in skipped_calls[0].kwargs["reason"]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_nobody_home_notifies_everyone_away(self, _sensor):
        category = {
            "id": "alerts",
            "priority_fallback": {"mode": "only_home_then_away", "window_minutes": 2},
        }
        persons = [
            _person("person.frank", "not_home"),
            _person("person.kevin", "not_home"),
        ]
        hass = _make_hass(persons)
        store = _make_store(category)
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts"))

        assert mock_send.await_count == 2

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_disabled_user_not_double_logged_as_priority_skip(self, _sensor):
        """Regression: a globally-disabled user losing the priority group
        must not get a misleading 'not in winning group' log entry on top
        of their existing silent is_user_enabled skip."""
        category = {
            "id": "alerts",
            "priority_fallback": {"mode": "only_home_then_away", "window_minutes": 2},
        }
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home"),
        ]
        hass = _make_hass(persons)
        store = _make_store(category)
        store.is_user_enabled.side_effect = lambda pid: pid != "person.kevin"
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts"))

        kevin_logs = [
            c for c in store.async_add_log.call_args_list
            if c.kwargs.get("person_id") == "person.kevin"
        ]
        assert kevin_logs == []

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_no_priority_fallback_notifies_everyone_as_before(self, _sensor):
        """Regression: categories without priority_fallback are unaffected."""
        category = {"id": "alerts"}
        persons = [
            _person("person.frank", "home"),
            _person("person.kevin", "not_home"),
        ]
        hass = _make_hass(persons)
        store = _make_store(category)
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts"))

        assert mock_send.await_count == 2
