"""Tests for BUG-105: discovery dedup and stale-service filtering.

`discovery.py` runs two parallel discovery passes (Path 1: entity-registry,
Path 2: mobile_app config-entry fallback added in BUG-043). When the iOS
Companion App is updated or a phone is replaced, both paths can emit
valid-looking entries with different `service` strings for the same
device. The frontend renders chips by display name, so users saw two
identical-looking chips, one of which silently failed to dispatch.

These tests cover the six cases from SPEC_BUG-105_v1.6.1.md §8:

- a:  cross-path dedup keeps Path 1 (entity-registry-authoritative).
- b:  Path 1 stale slug filtered at emission.
- b2: Path 2 stale slug filtered at emission (regression guard).
- c:  Issue #5 rename case — Path 1 stale, Path 2 live; Path 2 survives.
- d:  Cold-start empty notify domain → empty result, not cached.
- e:  Single-path emission — dedup is a no-op.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.discovery import (
    _dedup_device_services,
    _discovery_cache,
    async_discover_notify_services,
    invalidate_discovery_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _person_state(entity_id: str, friendly: str, trackers=None, user_id=None):
    state = MagicMock()
    state.entity_id = entity_id
    state.attributes = {
        "friendly_name": friendly,
        "device_trackers": trackers or [],
        "user_id": user_id,
    }
    return state


def _make_entity(domain: str, entity_id: str, device_id: str, platform: str = ""):
    """Build a fake entity-registry entry."""
    e = MagicMock()
    e.domain = domain
    e.entity_id = entity_id
    e.device_id = device_id
    e.platform = platform
    return e


def _real_slugify(value: str) -> str:
    """Minimal slugify stand-in matching HA's behavior for these inputs."""
    return (
        value.strip()
        .lower()
        .replace("'", "")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _patch_discovery_environment(
    *,
    entities,
    services_map,
    devices_by_id,
    config_entries,
    persons,
):
    """Build the patch context shared by every async_discover test."""
    fake_entity_reg = MagicMock()
    fake_entity_reg.entities = MagicMock()
    fake_entity_reg.entities.values = MagicMock(return_value=entities)

    # tracker entity → linked device_id resolution for the per-person walk
    by_id = {e.entity_id: e for e in entities}
    fake_entity_reg.async_get = MagicMock(side_effect=by_id.get)

    fake_device_reg = MagicMock()
    fake_device_reg.async_get = MagicMock(side_effect=devices_by_id.get)

    hass = MagicMock()
    hass.services.async_services.return_value = {"notify": services_map}
    hass.states.async_all = MagicMock(return_value=persons)
    hass.config_entries.async_get_entry = MagicMock(
        side_effect=config_entries.get
    )

    return hass, fake_entity_reg, fake_device_reg


# ---------------------------------------------------------------------------
# Helper-level tests (don't need full discovery wiring)
# ---------------------------------------------------------------------------


class TestDedupDeviceServicesHelper:
    """Direct unit tests for _dedup_device_services."""

    def test_empty_input_returns_empty(self):
        assert _dedup_device_services([], {}) == []

    def test_single_entry_returns_unchanged(self):
        entries = [{"service": "notify.x", "name": "X", "device_id": "d1"}]
        assert _dedup_device_services(entries, {"x": MagicMock()}) == entries

    def test_two_distinct_names_both_survive(self):
        entries = [
            {"service": "notify.a", "name": "Phone A", "device_id": "d"},
            {"service": "notify.b", "name": "Phone B", "device_id": "d"},
        ]
        result = _dedup_device_services(
            entries, {"a": MagicMock(), "b": MagicMock()}
        )
        assert len(result) == 2

    def test_same_name_prefers_live_slug(self):
        entries = [
            # Path 1 emitted first but slug is stale
            {"service": "notify.stale", "name": "Hans Phone", "device_id": "d"},
            # Path 2 emitted second with the live slug
            {"service": "notify.live", "name": "Hans Phone", "device_id": "d"},
        ]
        notify_map = {"live": MagicMock()}
        result = _dedup_device_services(entries, notify_map)
        assert len(result) == 1
        assert result[0]["service"] == "notify.live"

    def test_same_name_first_wins_when_both_live(self):
        # When both slugs exist in notify_services_map, Path 1 wins (first emitted).
        entries = [
            {"service": "notify.path1", "name": "Hans Phone", "device_id": "d"},
            {"service": "notify.path2", "name": "Hans Phone", "device_id": "d"},
        ]
        notify_map = {"path1": MagicMock(), "path2": MagicMock()}
        result = _dedup_device_services(entries, notify_map)
        assert len(result) == 1
        assert result[0]["service"] == "notify.path1"

    def test_name_grouping_is_case_and_whitespace_insensitive(self):
        entries = [
            {"service": "notify.a", "name": "  Hans Phone  ", "device_id": "d"},
            {"service": "notify.b", "name": "hans phone", "device_id": "d"},
        ]
        result = _dedup_device_services(entries, {"a": MagicMock()})
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration tests against async_discover_notify_services
# ---------------------------------------------------------------------------


class TestBug105Discovery:
    """End-to-end tests for the full discovery flow."""

    @pytest.mark.asyncio
    async def test_dedup_cross_path_same_device_same_name(self):
        """Case a: Path 1 and Path 2 emit different slugs for the same
        device with the same display name; both resolve in hass.services.
        Survivor is Path 1 (entity-registry-authoritative)."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"

        # Path 1: entity-registry yields a notify entity for device.
        notify_entity = _make_entity(
            "notify", "notify.mobile_app_iphone_van_hans", device_id
        )
        # Path 2: same device shows up as a mobile_app device_tracker too.
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="mobile_app",
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = ["entry_1"]

        config_entry = MagicMock()
        config_entry.domain = "mobile_app"
        # device_name slugifies to a *different* slug from the entity_id
        config_entry.data = {"device_name": "iPhone van Hans 2"}

        # BOTH slugs live in hass.services notify map
        services_map = {
            "mobile_app_iphone_van_hans": MagicMock(),
            "mobile_app_iphone_van_hans_2": MagicMock(),
        }

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[notify_entity, tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={"entry_1": config_entry},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        services = result["person.hans"]["notify_services"]
        assert len(services) == 1, (
            f"expected exactly one notify service after dedup, got {services}"
        )
        # Path 1's slug wins (entity-registry-authoritative).
        assert services[0]["service"] == "notify.mobile_app_iphone_van_hans"

    @pytest.mark.asyncio
    async def test_path1_stale_service_dropped(self):
        """Case b: Path 1 emits a slug not present in hass.services.notify;
        the entry is dropped at emission."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"
        notify_entity = _make_entity(
            "notify", "notify.mobile_app_iphone_van_hans_stale", device_id
        )
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="mobile_app",
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = []  # no mobile_app config entry → Path 2 silent

        services_map = {}  # nothing live — Path 1's slug is stale

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[notify_entity, tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        assert result["person.hans"]["notify_services"] == [], (
            "stale Path 1 entry must be filtered out"
        )

    @pytest.mark.asyncio
    async def test_path2_stale_service_dropped(self):
        """Case b2: Regression guard — Path 2 reconstructs a slug that is
        not in hass.services.notify; existing line 148 behavior must not
        regress after the dedup helper is added."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"
        # No Path 1 notify entity — only mobile_app device_tracker for Path 2
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="mobile_app",
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = ["entry_1"]

        config_entry = MagicMock()
        config_entry.domain = "mobile_app"
        config_entry.data = {"device_name": "iPhone van Hans"}

        # Empty notify_services_map: reconstructed slug not live
        services_map = {}

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={"entry_1": config_entry},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        assert result["person.hans"]["notify_services"] == [], (
            "Path 2 stale-filter regression — reconstructed slug should be skipped"
        )

    @pytest.mark.asyncio
    async def test_issue_5_rename_case_path2_fallback(self):
        """Case c: Issue #5 — phone renamed; Path 1's slug is now stale,
        but Path 2's reconstructed slug is current. Path 2 must survive.
        This proves the BUG-105 fix did not regress BUG-043 / issue #5."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"

        # Path 1: stale entity_id slug
        notify_entity = _make_entity(
            "notify", "notify.mobile_app_iphone_van_hans", device_id
        )
        # Path 2: current device_name slug differs
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="mobile_app",
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = ["entry_1"]

        config_entry = MagicMock()
        config_entry.domain = "mobile_app"
        config_entry.data = {"device_name": "iPhone van Hans 2"}

        # Only the renamed slug is live
        services_map = {"mobile_app_iphone_van_hans_2": MagicMock()}

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[notify_entity, tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={"entry_1": config_entry},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        services = result["person.hans"]["notify_services"]
        assert len(services) == 1, (
            "issue #5 protection — Path 2 fallback must survive when Path 1 is stale"
        )
        assert services[0]["service"] == "notify.mobile_app_iphone_van_hans_2"

    @pytest.mark.asyncio
    async def test_cold_start_empty_notify_domain(self):
        """Case d: hass.services.async_services() returns {} for notify
        (HA still loading, mobile_app not yet registered). All entries
        are filtered → result effectively empty → _should_cache_result
        returns False → cache NOT updated. No exception."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"
        notify_entity = _make_entity(
            "notify", "notify.mobile_app_iphone_van_hans", device_id
        )
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="mobile_app",
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = ["entry_1"]

        config_entry = MagicMock()
        config_entry.domain = "mobile_app"
        config_entry.data = {"device_name": "iPhone van Hans"}

        # The cold-start signal: notify domain not yet populated.
        services_map = {}

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[notify_entity, tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={"entry_1": config_entry},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        # Person exists but has no notify services
        assert result["person.hans"]["notify_services"] == []
        # Importantly, cache must NOT be locked in (BUG-060 guard still active)
        # _discovery_cache is module-level; verify it stays empty after this call.
        from custom_components.ticker import discovery as _disc
        assert _disc._discovery_cache == {}, (
            "cold-start empty result must not be cached (BUG-060 guard)"
        )

    @pytest.mark.asyncio
    async def test_no_duplicates_when_only_one_path_emits(self):
        """Case e: only Path 1 finds a service; Path 2 silent. Single
        entry survives; dedup helper is effectively a no-op."""
        invalidate_discovery_cache()

        device_id = "dev_hans_phone"

        # Path 1 only: notify entity present, no mobile_app device_tracker.
        notify_entity = _make_entity(
            "notify", "notify.mobile_app_iphone_van_hans", device_id
        )
        tracker_entity = _make_entity(
            "device_tracker",
            "device_tracker.iphone_van_hans",
            device_id,
            platform="",  # not mobile_app — Path 2 will skip
        )

        device = MagicMock()
        device.name_by_user = "Hans Phone"
        device.name = "Hans Phone"
        device.config_entries = []

        services_map = {"mobile_app_iphone_van_hans": MagicMock()}

        hass, ereg, dreg = _patch_discovery_environment(
            entities=[notify_entity, tracker_entity],
            services_map=services_map,
            devices_by_id={device_id: device},
            config_entries={},
            persons=[
                _person_state(
                    "person.hans",
                    "Hans",
                    trackers=["device_tracker.iphone_van_hans"],
                )
            ],
        )

        with patch(
            "custom_components.ticker.discovery.er.async_get", return_value=ereg
        ), patch(
            "custom_components.ticker.discovery.dr.async_get", return_value=dreg
        ), patch(
            "custom_components.ticker.discovery.slugify", side_effect=_real_slugify
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        services = result["person.hans"]["notify_services"]
        assert len(services) == 1
        assert services[0]["service"] == "notify.mobile_app_iphone_van_hans"
