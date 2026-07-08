"""Tests for per-call routing modes (F-fork, drop-in parity with iq_notify).

Covers mode_routing.resolve_mode_group across the full iq_notify mode set,
including presence classification, recency windows, unresolved-state
exclusion, and delegation to resolve_priority_group for the two "then_away"
modes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.ticker.mode_routing import resolve_mode_group


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Person:
    """Minimal person State stand-in (entity_id, state, last_changed)."""

    def __init__(self, entity_id: str, state: str, minutes_ago: float = 60) -> None:
        self.entity_id = entity_id
        self.state = state
        self.last_changed = _NOW - timedelta(minutes=minutes_ago)
        self.attributes = {"friendly_name": entity_id}


def _ids(persons) -> set:
    return {p.entity_id for p in persons}


# ---------------------------------------------------------------------------
# passthrough / unknown modes
# ---------------------------------------------------------------------------

class TestPassthrough:
    def test_none_returns_all(self):
        ps = [_Person("person.a", "home"), _Person("person.b", "not_home")]
        assert resolve_mode_group(ps, None, None, _NOW) is ps

    def test_all_returns_all(self):
        ps = [_Person("person.a", "home"), _Person("person.b", "not_home")]
        assert resolve_mode_group(ps, "all", None, _NOW) is ps

    def test_unknown_mode_fails_open_to_all(self):
        ps = [_Person("person.a", "home")]
        assert resolve_mode_group(ps, "sideways", None, _NOW) == ps


# ---------------------------------------------------------------------------
# static presence modes
# ---------------------------------------------------------------------------

class TestStaticPresence:
    def _fixture(self):
        return [
            _Person("person.home", "home"),
            _Person("person.away", "not_home"),
            _Person("person.unknown", "unknown"),
            _Person("person.unavail", "unavailable"),
        ]

    def test_only_home(self):
        assert _ids(resolve_mode_group(self._fixture(), "only_home", None, _NOW)) == {
            "person.home"
        }

    def test_only_away_excludes_unresolved(self):
        # not_home counts as away; unknown/unavailable are never classified.
        assert _ids(resolve_mode_group(self._fixture(), "only_away", None, _NOW)) == {
            "person.away"
        }

    def test_nobody_home_suppresses_when_someone_home(self):
        assert resolve_mode_group(self._fixture(), "nobody_home", None, _NOW) == []

    def test_nobody_home_notifies_known_when_no_one_home(self):
        ps = [
            _Person("person.away", "not_home"),
            _Person("person.work", "work"),
            _Person("person.unknown", "unknown"),
        ]
        assert _ids(resolve_mode_group(ps, "nobody_home", None, _NOW)) == {
            "person.away",
            "person.work",
        }


# ---------------------------------------------------------------------------
# recency-window modes
# ---------------------------------------------------------------------------

class TestRecencyWindows:
    def _fixture(self):
        return [
            _Person("person.home_recent", "home", minutes_ago=1),
            _Person("person.home_old", "home", minutes_ago=30),
            _Person("person.away_recent", "not_home", minutes_ago=1),
            _Person("person.away_old", "not_home", minutes_ago=30),
        ]

    def test_just_arrived(self):
        assert _ids(resolve_mode_group(self._fixture(), "just_arrived", 2, _NOW)) == {
            "person.home_recent"
        }

    def test_just_left(self):
        assert _ids(resolve_mode_group(self._fixture(), "just_left", 2, _NOW)) == {
            "person.away_recent"
        }

    def test_staying_home(self):
        assert _ids(resolve_mode_group(self._fixture(), "staying_home", 2, _NOW)) == {
            "person.home_old"
        }

    def test_staying_away(self):
        assert _ids(resolve_mode_group(self._fixture(), "staying_away", 2, _NOW)) == {
            "person.away_old"
        }

    def test_window_defaults_on_garbage(self):
        # None window falls back to default (2 min); home_recent (1m) is in,
        # home_old (30m) is out.
        assert _ids(resolve_mode_group(self._fixture(), "just_arrived", None, _NOW)) == {
            "person.home_recent"
        }


# ---------------------------------------------------------------------------
# then_away delegation
# ---------------------------------------------------------------------------

class TestThenAwayDelegation:
    def test_only_home_then_away_prefers_home(self):
        ps = [_Person("person.a", "home"), _Person("person.b", "not_home")]
        assert _ids(
            resolve_mode_group(ps, "only_home_then_away", None, _NOW)
        ) == {"person.a"}

    def test_only_home_then_away_falls_back_to_away(self):
        ps = [_Person("person.a", "not_home"), _Person("person.b", "work")]
        assert _ids(
            resolve_mode_group(ps, "only_home_then_away", None, _NOW)
        ) == {"person.a", "person.b"}

    def test_just_left_then_away_prefers_recent_leavers(self):
        ps = [
            _Person("person.recent", "not_home", minutes_ago=1),
            _Person("person.old", "not_home", minutes_ago=30),
        ]
        assert _ids(
            resolve_mode_group(ps, "just_left_then_away", 2, _NOW)
        ) == {"person.recent"}
