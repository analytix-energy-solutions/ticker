"""Tests for Issue #69: duplicate notifications when persons share a device.

A ``device_tracker`` may belong to more than one ``person`` -- two people
sharing a household tablet, or a second "service" person used by automations.
Home Assistant allows it, and each person previously resolved that device
independently, so one ``ticker.notify`` call reached the device once per
person.

Covers the deduplication at both levels:

- ``async_send_notification`` honouring the shared ``claimed_devices`` set
- ``services._dispatch_to_category`` actually creating and threading that set,
  so the unit-level fix is verifiably wired up
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.user_notify import (
    async_handle_conditional_notification,
    async_send_notification,
)
from custom_components.ticker.const import (
    DELIVERY_FORMAT_RICH,
    DEVICE_MODE_ALL,
    LOG_OUTCOME_SKIPPED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHARED = "notify.mobile_app_shared_tablet"
ALICE_ONLY = "notify.mobile_app_alice_phone"


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_store() -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    store.is_snoozed.return_value = False
    store.get_device_preference.return_value = {"mode": DEVICE_MODE_ALL}
    store.get_device_override.return_value = None
    store.get_category.return_value = None
    store.get_subscription_conditions.return_value = None
    return store


def _services_list(service_ids: list[str]) -> list[dict]:
    return [
        {"service": s, "name": s, "device_id": f"dev_{i}"}
        for i, s in enumerate(service_ids)
    ]


def _called_services(hass: MagicMock) -> list[str]:
    """Reconstruct the notify services actually dispatched."""
    return [
        f"{c.args[0]}.{c.args[1]}"
        for c in hass.services.async_call.await_args_list
    ]


# ---------------------------------------------------------------------------
# async_send_notification: the shared claim set
# ---------------------------------------------------------------------------

@patch("custom_components.ticker.user_notify.resolve_ios_platform", return_value=False)
@patch(
    "custom_components.ticker.user_notify.detect_delivery_format",
    return_value=DELIVERY_FORMAT_RICH,
)
@patch(
    "custom_components.ticker.user_notify.async_get_notify_services_for_person",
    new_callable=AsyncMock,
)
class TestClaimedDevices:
    """async_send_notification must skip devices already claimed."""

    @pytest.mark.asyncio
    async def test_second_person_does_not_resend_to_shared_device(
        self, mock_discover, _detect, _ios,
    ):
        """The core regression: one device, two persons, one notification."""
        mock_discover.return_value = _services_list([SHARED])
        hass = _make_hass()
        store = _make_store()
        claimed: set[str] = set()

        first = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )
        second = await async_send_notification(
            hass, store, "person.copilot", "Copilot", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        assert first["delivered"] == [SHARED]
        assert second["delivered"] == []
        assert _called_services(hass) == [SHARED]

    @pytest.mark.asyncio
    async def test_unshared_devices_still_delivered(
        self, mock_discover, _detect, _ios,
    ):
        """Only the overlapping device is dropped, never the whole person."""
        hass = _make_hass()
        store = _make_store()
        claimed: set[str] = set()

        mock_discover.return_value = _services_list([SHARED])
        await async_send_notification(
            hass, store, "person.bob", "Bob", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        # Alice shares the tablet with Bob but also has her own phone.
        mock_discover.return_value = _services_list([SHARED, ALICE_ONLY])
        result = await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        assert result["delivered"] == [ALICE_ONLY]
        assert sorted(_called_services(hass)) == sorted([SHARED, ALICE_ONLY])

    @pytest.mark.asyncio
    async def test_claim_set_accumulates_every_sent_device(
        self, mock_discover, _detect, _ios,
    ):
        mock_discover.return_value = _services_list([SHARED, ALICE_ONLY])
        claimed: set[str] = set()

        await async_send_notification(
            _make_hass(), _make_store(), "person.alice", "Alice", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        assert claimed == {SHARED, ALICE_ONLY}

    @pytest.mark.asyncio
    async def test_suppressed_person_is_logged_as_skipped_not_failed(
        self, mock_discover, _detect, _ios,
    ):
        """A duplicate is not a delivery failure and must not read as one."""
        mock_discover.return_value = _services_list([SHARED])
        store = _make_store()
        claimed = {SHARED}

        result = await async_send_notification(
            _make_hass(), store, "person.copilot", "Copilot", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        store.async_add_log.assert_awaited_once()
        kw = store.async_add_log.call_args[1]
        assert kw["outcome"] == LOG_OUTCOME_SKIPPED
        assert SHARED in kw["reason"]
        assert result["dropped"] == [
            "person.copilot: shared device(s) already notified"
        ]

    @pytest.mark.asyncio
    async def test_no_claim_set_means_no_deduplication(
        self, mock_discover, _detect, _ios,
    ):
        """Standalone sends -- queue replay, arrival -- keep old behaviour."""
        mock_discover.return_value = _services_list([SHARED])
        hass = _make_hass()
        store = _make_store()

        for person in ("person.alice", "person.copilot"):
            await async_send_notification(
                hass, store, person, person, "cat1", "T", "M", data={},
            )

        assert _called_services(hass) == [SHARED, SHARED]

    @pytest.mark.asyncio
    async def test_snoozed_person_does_not_claim_the_device(
        self, mock_discover, _detect, _ios,
    ):
        """Trap: a subscriber who never sends must not claim a device away.

        Alice is snoozed, so the tablet must still be claimable by Copilot --
        otherwise snoozing one person silences a device for everyone.
        """
        mock_discover.return_value = _services_list([SHARED])
        hass = _make_hass()
        store = _make_store()
        claimed: set[str] = set()

        store.is_snoozed.return_value = True
        await async_send_notification(
            hass, store, "person.alice", "Alice", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )
        assert claimed == set()

        store.is_snoozed.return_value = False
        result = await async_send_notification(
            hass, store, "person.copilot", "Copilot", "cat1", "T", "M",
            data={}, claimed_devices=claimed,
        )

        assert result["delivered"] == [SHARED]
        assert _called_services(hass) == [SHARED]

    @pytest.mark.asyncio
    async def test_conditional_path_threads_the_claim_set(
        self, mock_discover, _detect, _ios,
    ):
        """MODE_CONDITIONAL reaches the same send and must dedupe too."""
        mock_discover.return_value = _services_list([SHARED])
        hass = _make_hass()
        store = _make_store()
        # No conditions configured -> falls through to an immediate send.
        store.get_subscription_conditions.return_value = None
        claimed = {SHARED}

        result = await async_handle_conditional_notification(
            hass=hass, store=store, person_id="person.copilot",
            person_name="Copilot", person_state=MagicMock(),
            category_id="cat1", title="T", message="M", data={},
            expiration=24, claimed_devices=claimed,
        )

        assert result["delivered"] == []
        hass.services.async_call.assert_not_awaited()


# ---------------------------------------------------------------------------
# services._dispatch_to_category: the wiring
# ---------------------------------------------------------------------------

def _person(entity_id: str, name: str) -> MagicMock:
    state = MagicMock()
    state.entity_id = entity_id
    state.attributes = {"friendly_name": name}
    return state


def _dispatch_hass(persons: list[MagicMock]) -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.async_register = MagicMock()
    hass.states = MagicMock()
    hass.states.async_all.return_value = persons
    return hass


def _dispatch_store() -> MagicMock:
    store = MagicMock()
    store.get_recipients.return_value = {}
    store.category_exists.side_effect = lambda cid: cid == "cat1"
    store.get_categories.return_value = {"cat1": {"name": "cat1"}}
    store.get_category.side_effect = (
        lambda cid: {"name": "cat1", "critical": False} if cid == "cat1" else None
    )
    store.is_user_enabled.return_value = True
    store.get_subscription_mode.return_value = "always"
    store.get_device_preference.return_value = {"mode": DEVICE_MODE_ALL}
    store.get_device_override.return_value = None
    store.is_snoozed.return_value = False
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    return store


async def _notify_handler(hass: MagicMock):
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    return hass.services.async_register.call_args_list[0][0][2]


@pytest.mark.asyncio
@patch("custom_components.ticker.user_notify.resolve_ios_platform", return_value=False)
@patch(
    "custom_components.ticker.user_notify.detect_delivery_format",
    return_value=DELIVERY_FORMAT_RICH,
)
@patch(
    "custom_components.ticker.user_notify.async_get_notify_services_for_person",
    new_callable=AsyncMock,
)
@patch("custom_components.ticker.services.get_category_sensor", return_value=None)
async def test_dispatch_sends_once_to_a_device_two_persons_share(
    _sensor, mock_discover, _detect, _ios,
):
    """End-to-end through the real ticker.notify handler.

    Proves the claim set is actually created and threaded in services.py --
    the unit tests above would still pass if the wiring were missing.
    """
    mock_discover.return_value = _services_list([SHARED])
    hass = _dispatch_hass([
        _person("person.dan", "Dan"),
        _person("person.copilot", "Copilot"),
    ])
    store = _dispatch_store()
    handler = await _notify_handler(hass)

    entry = MagicMock()
    entry.runtime_data.store = store
    entry.runtime_data.auto_clear = None

    call = MagicMock()
    call.data = {"category": "cat1", "title": "T", "message": "M"}

    with patch(
        "custom_components.ticker.services._get_loaded_entry", return_value=entry,
    ), patch(
        "custom_components.ticker.services.build_smart_tag", return_value=None,
    ):
        await handler(call)

    assert _called_services(hass) == [SHARED]
