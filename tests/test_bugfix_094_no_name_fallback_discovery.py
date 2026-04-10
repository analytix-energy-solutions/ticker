"""Tests for BUG-094: discovery no longer substring-matches by name.

The previous fallback path added ANY notify service whose name
contained the normalized person name as a substring. This cross-linked
persons whose names were substrings of other names (e.g. "John"
matching notify.mobile_app_johnnys_phone). The fix removes the
name-matching fallback — only registry-authoritative paths remain.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.ticker.discovery import (
    async_discover_notify_services,
    invalidate_discovery_cache,
)


def _person_state(entity_id: str, friendly: str, trackers=None, user_id=None):
    state = MagicMock()
    state.entity_id = entity_id
    state.attributes = {
        "friendly_name": friendly,
        "device_trackers": trackers or [],
        "user_id": user_id,
    }
    return state


class TestBug094NoNameFallback:

    @pytest.mark.asyncio
    async def test_person_with_no_trackers_has_no_services(self):
        """A person with no device_trackers and no registry-linked
        devices must get an empty notify_services list — the old name
        fallback would have incorrectly added notify.mobile_app_john
        just because the slug contains 'john'."""
        invalidate_discovery_cache()

        hass = MagicMock()
        # Person "John" with no trackers at all
        hass.states.async_all = MagicMock(return_value=[
            _person_state("person.john", "John", trackers=[]),
        ])
        hass.services.async_services.return_value = {"notify": {}}

        # Entity registry has no matching entities for this person
        fake_entity_reg = MagicMock()
        fake_entity_reg.entities = MagicMock()
        fake_entity_reg.entities.values = MagicMock(return_value=[])
        fake_entity_reg.async_get = MagicMock(return_value=None)

        fake_device_reg = MagicMock()

        with patch(
            "custom_components.ticker.discovery.er.async_get",
            return_value=fake_entity_reg,
        ), patch(
            "custom_components.ticker.discovery.dr.async_get",
            return_value=fake_device_reg,
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        assert "person.john" in result
        services = result["person.john"]["notify_services"]
        assert services == [], (
            "BUG-094 regression: person with no registry-linked tracker "
            "must NOT receive substring-matched notify services"
        )

    @pytest.mark.asyncio
    async def test_substring_name_collision_not_cross_linked(self):
        """Person 'John' must not pick up notify.mobile_app_johnnys_phone
        simply because 'john' is a substring of 'johnnys_phone'."""
        invalidate_discovery_cache()

        hass = MagicMock()
        hass.states.async_all = MagicMock(return_value=[
            _person_state("person.john", "John", trackers=[]),
        ])
        # Even though a notify service exists for someone else, no
        # name-matching should cross-link it.
        hass.services.async_services.return_value = {
            "notify": {"mobile_app_johnnys_phone": MagicMock()},
        }

        fake_entity_reg = MagicMock()
        fake_entity_reg.entities = MagicMock()
        fake_entity_reg.entities.values = MagicMock(return_value=[])
        fake_entity_reg.async_get = MagicMock(return_value=None)

        fake_device_reg = MagicMock()

        with patch(
            "custom_components.ticker.discovery.er.async_get",
            return_value=fake_entity_reg,
        ), patch(
            "custom_components.ticker.discovery.dr.async_get",
            return_value=fake_device_reg,
        ):
            result = await async_discover_notify_services(hass, use_cache=False)

        services = result["person.john"]["notify_services"]
        assert not any(
            "johnnys_phone" in svc.get("service", "")
            for svc in services
        ), "Cross-linking via name substring must be gone"
