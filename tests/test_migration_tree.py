"""Tests for F-2b Store Migration: flat rules to condition_tree.

Covers:
- _async_migrate_flat_rules_to_tree converts flat rules to tree
- _async_migrate_flat_rules_to_tree skips when tree already exists
- _async_migrate_flat_rules_to_tree skips when no rules present
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.store.migrations import MigrationMixin


# ---------------------------------------------------------------------------
# Concrete test class mixing in MigrationMixin
# ---------------------------------------------------------------------------

class FakeMigrationStore(MigrationMixin):
    """Concrete class for testing MigrationMixin."""

    def __init__(self, subscriptions: dict | None = None):
        self.hass = MagicMock()
        self._subscriptions = subscriptions if subscriptions is not None else {}
        self._users: dict = {}
        self.async_save_subscriptions = AsyncMock()
        self.async_save_users = AsyncMock()


# ---------------------------------------------------------------------------
# _async_migrate_flat_rules_to_tree
# ---------------------------------------------------------------------------

class TestMigrateFlatRulesToTree:
    """Test migration from flat rules[] to condition_tree."""

    @pytest.mark.asyncio
    async def test_converts_flat_rules(self):
        """Flat rules wrapped in root AND group node."""
        rules = [
            {"type": "zone", "zone_id": "zone.home"},
            {"type": "time", "after": "08:00", "before": "22:00"},
        ]
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "conditional",
                "conditions": {
                    "deliver_when_met": True,
                    "queue_until_met": False,
                    "rules": rules,
                },
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 1
        conds = store._subscriptions["p1:cat1"]["conditions"]
        assert "condition_tree" in conds
        assert "rules" not in conds
        tree = conds["condition_tree"]
        assert tree["type"] == "group"
        assert tree["operator"] == "AND"
        assert len(tree["children"]) == 2
        assert tree["children"][0]["type"] == "zone"
        assert tree["children"][1]["type"] == "time"
        store.async_save_subscriptions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_existing_tree(self):
        """Subscriptions with condition_tree already set are unchanged."""
        existing_tree = {
            "type": "group",
            "operator": "OR",
            "children": [{"type": "state", "entity_id": "switch.a", "state": "on"}],
        }
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "conditional",
                "conditions": {
                    "deliver_when_met": True,
                    "condition_tree": existing_tree,
                },
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 0
        # Tree unchanged
        tree = store._subscriptions["p1:cat1"]["conditions"]["condition_tree"]
        assert tree["operator"] == "OR"
        store.async_save_subscriptions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_no_rules(self):
        """Subscriptions with no rules are unchanged."""
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "conditional",
                "conditions": {
                    "deliver_when_met": True,
                },
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 0
        assert "condition_tree" not in store._subscriptions["p1:cat1"]["conditions"]
        store.async_save_subscriptions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_non_conditional_mode(self):
        """Subscriptions with mode != conditional are skipped."""
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "always",
                "conditions": {
                    "rules": [{"type": "zone", "zone_id": "zone.home"}],
                },
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 0
        store.async_save_subscriptions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_empty_rules_list(self):
        """Empty rules list is falsy and should not be migrated."""
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "conditional",
                "conditions": {
                    "deliver_when_met": True,
                    "rules": [],
                },
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 0
        store.async_save_subscriptions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_subscriptions(self):
        """Multiple eligible subscriptions are all migrated."""
        store = FakeMigrationStore({
            "p1:cat1": {
                "mode": "conditional",
                "conditions": {
                    "rules": [{"type": "zone", "zone_id": "zone.home"}],
                },
            },
            "p2:cat2": {
                "mode": "conditional",
                "conditions": {
                    "rules": [{"type": "state", "entity_id": "switch.a", "state": "on"}],
                },
            },
            "p3:cat3": {
                "mode": "always",
            },
        })

        count = await store._async_migrate_flat_rules_to_tree()

        assert count == 2
        assert "condition_tree" in store._subscriptions["p1:cat1"]["conditions"]
        assert "condition_tree" in store._subscriptions["p2:cat2"]["conditions"]
        store.async_save_subscriptions.assert_awaited_once()
