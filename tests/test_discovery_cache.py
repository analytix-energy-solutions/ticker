"""Tests for discovery.py cache guard (_should_cache_result).

Verifies that empty or service-less discovery results are not cached,
preventing stale empty caches from locking in bad data during HA startup.
"""

from __future__ import annotations

import pytest

from custom_components.ticker.discovery import _should_cache_result


# ---------------------------------------------------------------------------
# _should_cache_result
# ---------------------------------------------------------------------------

class TestShouldCacheResult:
    """Tests for _should_cache_result() guard."""

    def test_empty_dict_not_cached(self):
        assert _should_cache_result({}) is False

    def test_all_persons_empty_services_not_cached(self):
        result = {
            "person.alice": {
                "person_id": "person.alice",
                "notify_services": [],
            },
            "person.bob": {
                "person_id": "person.bob",
                "notify_services": [],
            },
        }
        assert _should_cache_result(result) is False

    def test_one_person_with_services_cached(self):
        result = {
            "person.alice": {
                "person_id": "person.alice",
                "notify_services": [{"service": "notify.mobile_app_alice"}],
            },
            "person.bob": {
                "person_id": "person.bob",
                "notify_services": [],
            },
        }
        assert _should_cache_result(result) is True

    def test_all_persons_with_services_cached(self):
        result = {
            "person.alice": {
                "person_id": "person.alice",
                "notify_services": [{"service": "notify.mobile_app_alice"}],
            },
        }
        assert _should_cache_result(result) is True

    def test_missing_notify_services_key_not_cached(self):
        """If no person has a 'notify_services' key at all, not cacheable."""
        result = {
            "person.alice": {"person_id": "person.alice"},
        }
        assert _should_cache_result(result) is False

    def test_none_notify_services_not_cached(self):
        result = {
            "person.alice": {
                "person_id": "person.alice",
                "notify_services": None,
            },
        }
        assert _should_cache_result(result) is False
