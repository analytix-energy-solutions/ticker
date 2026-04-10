"""Tests for BUG-090: find_log_category_by_nid resolves category by nid prefix.

When an action set is shared across multiple categories, action
handling needs to resolve the correct category for the actual
notification that fired. The fix iterates logs in reverse (most recent
first) and matches by the 8-char notification_id prefix + person_id.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ticker.store_log import LogMixin


def _make_mixin() -> LogMixin:
    mixin = LogMixin()
    mixin.hass = MagicMock()
    mixin._logs = []
    return mixin


def _log(nid: str, category_id: str, person_id: str = "person.alice") -> dict:
    return {
        "log_id": nid + "_log",
        "timestamp": "2026-04-10T10:00:00+00:00",
        "category_id": category_id,
        "person_id": person_id,
        "outcome": "sent",
        "notification_id": nid,
    }


class TestBug090FindLogCategoryByNid:

    def test_returns_category_for_matching_nid(self):
        mixin = _make_mixin()
        mixin._logs = [
            _log("abcd1234aaaaaaaa", "cat_alpha"),
            _log("wxyz5678bbbbbbbb", "cat_beta"),
        ]

        result = mixin.find_log_category_by_nid("abcd1234", "person.alice")
        assert result == "cat_alpha"

        result2 = mixin.find_log_category_by_nid("wxyz5678", "person.alice")
        assert result2 == "cat_beta"

    def test_returns_none_when_no_match(self):
        mixin = _make_mixin()
        mixin._logs = [_log("abcd1234xxxx", "cat_alpha")]
        assert mixin.find_log_category_by_nid("nonexist", "person.alice") is None

    def test_returns_none_when_person_mismatch(self):
        mixin = _make_mixin()
        mixin._logs = [_log("abcd1234xxxx", "cat_alpha", person_id="person.alice")]
        assert (
            mixin.find_log_category_by_nid("abcd1234", "person.bob") is None
        )

    def test_most_recent_match_wins(self):
        """With duplicate nids, the most-recent log entry wins (reverse scan)."""
        mixin = _make_mixin()
        mixin._logs = [
            _log("abcd1234oldest", "cat_old"),
            _log("abcd1234newest", "cat_new"),
        ]
        # Both share the first 8 chars "abcd1234"
        result = mixin.find_log_category_by_nid("abcd1234", "person.alice")
        # Reverse iteration means the newest (last in list) wins
        assert result == "cat_new"

    def test_empty_logs_returns_none(self):
        mixin = _make_mixin()
        assert mixin.find_log_category_by_nid("abcd1234", "person.alice") is None

    def test_log_without_nid_is_skipped(self):
        mixin = _make_mixin()
        log_no_nid = _log("", "cat_alpha")
        log_no_nid["notification_id"] = ""
        mixin._logs = [log_no_nid]
        assert mixin.find_log_category_by_nid("abcd1234", "person.alice") is None
