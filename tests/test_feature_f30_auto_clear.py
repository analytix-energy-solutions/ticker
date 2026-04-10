"""Tests for F-30: Auto-clear trigger registry.

The AutoClearRegistry wires one-shot state-change or event listeners that
dispatch a clear_notification against the originally-delivered notify
services when the trigger fires. This module verifies:

- Happy-path state and event registration + firing
- Non-matching state does not fire
- State removed (new_state is None) unregisters cleanly
- Missing entity skipped with warning, no listener registered
- Tag-less registration is rejected
- Duplicate notification_id tears down the prior entry
- unregister_by_tag, unregister_all wiring
- async_dispatch_clear wrapper adapts a flat list to the dict form
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.auto_clear import AutoClearRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass_with_entity(entity_id: str | None = "binary_sensor.door"):
    """Build a mocked hass with an optional existing state."""
    hass = MagicMock()
    # Capture event listeners so tests can fire them.
    hass._event_listeners = {}

    def _listen(event_type, callback):
        hass._event_listeners.setdefault(event_type, []).append(callback)
        return MagicMock(name=f"unsub_event_{event_type}")

    hass.bus = MagicMock()
    hass.bus.async_listen.side_effect = _listen

    state = MagicMock() if entity_id else None
    hass.states = MagicMock()
    hass.states.get = MagicMock(return_value=state)

    # Close any coroutine handed to async_create_task so the test does not
    # leak an unawaited coroutine warning.
    def _consume_coro(coro, *_a, **_kw):
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock(name="task")

    hass.async_create_task = MagicMock(side_effect=_consume_coro)
    return hass


@pytest.fixture
def hass():
    return _make_hass_with_entity()


@pytest.fixture
def registry(hass):
    return AutoClearRegistry(hass)


class TestStateTriggerRegistration:
    @pytest.mark.asyncio
    async def test_state_trigger_registers_listener(self, registry, hass):
        """Registering a state trigger subscribes via async_track_state_change_event."""
        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            return_value=MagicMock(name="unsub"),
        ) as mock_track:
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="ticker_alerts",
            )

            mock_track.assert_called_once()
            # Entity list is the 2nd positional arg.
            assert mock_track.call_args.args[1] == ["binary_sensor.door"]
        assert "nid1" in registry._entries
        assert registry._tags["nid1"] == "ticker_alerts"

    @pytest.mark.asyncio
    async def test_state_trigger_fires_on_match(self, registry, hass):
        """The state callback must call _dispatch_clear when the target state is reached."""
        captured_cb = {}

        def _capture(_hass, _ents, cb):
            captured_cb["cb"] = cb
            return MagicMock(name="unsub")

        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            side_effect=_capture,
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="t1",
            )

        # Fire a state event: new_state.state == "off" -> should dispatch
        new_state = MagicMock()
        new_state.state = "off"
        event = MagicMock()
        event.data = {"new_state": new_state}
        captured_cb["cb"](event)

        # _fire schedules dispatch via async_create_task.
        hass.async_create_task.assert_called_once()
        # Entry was popped as part of one-shot teardown.
        assert "nid1" not in registry._entries

    @pytest.mark.asyncio
    async def test_state_trigger_ignores_non_matching_state(self, registry, hass):
        """A state change to a different value must NOT dispatch clear."""
        captured_cb = {}

        def _capture(_hass, _ents, cb):
            captured_cb["cb"] = cb
            return MagicMock(name="unsub")

        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            side_effect=_capture,
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="t1",
            )

        new_state = MagicMock()
        new_state.state = "on"  # not the target
        event = MagicMock()
        event.data = {"new_state": new_state}
        captured_cb["cb"](event)

        hass.async_create_task.assert_not_called()
        assert "nid1" in registry._entries  # still armed

    @pytest.mark.asyncio
    async def test_state_trigger_entity_removed_unregisters(self, registry, hass):
        """new_state is None (entity removed) must unregister cleanly, no clear."""
        captured_cb = {}

        def _capture(_hass, _ents, cb):
            captured_cb["cb"] = cb
            return MagicMock(name="unsub")

        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            side_effect=_capture,
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="t1",
            )

        event = MagicMock()
        event.data = {"new_state": None}
        captured_cb["cb"](event)

        assert "nid1" not in registry._entries
        hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_trigger_missing_entity_skipped(self):
        """If hass.states.get returns None, registration is skipped with a warning."""
        hass = _make_hass_with_entity(entity_id=None)
        registry = AutoClearRegistry(hass)

        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
        ) as mock_track:
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "sensor.ghost", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="t1",
            )

            mock_track.assert_not_called()
        assert "nid1" not in registry._entries


class TestEventTriggerRegistration:
    @pytest.mark.asyncio
    async def test_event_trigger_registers_listener(self, registry, hass):
        """Registering an event trigger subscribes via hass.bus.async_listen."""
        await registry.register(
            notification_id="nid1",
            clear_when={"event_type": "my_event"},
            delivered_services=["notify.mobile_app_phone"],
            tag="t1",
        )

        hass.bus.async_listen.assert_called_once()
        assert hass.bus.async_listen.call_args.args[0] == "my_event"
        assert "nid1" in registry._entries

    @pytest.mark.asyncio
    async def test_event_trigger_fires_on_event(self, registry, hass):
        """Firing the matching event dispatches clear and tears down the entry."""
        await registry.register(
            notification_id="nid1",
            clear_when={"event_type": "my_event"},
            delivered_services=["notify.mobile_app_phone"],
            tag="t1",
        )

        # Fire the captured callback.
        callbacks = hass._event_listeners["my_event"]
        assert len(callbacks) == 1
        callbacks[0](MagicMock())

        hass.async_create_task.assert_called_once()
        assert "nid1" not in registry._entries


class TestRegistrationGuards:
    @pytest.mark.asyncio
    async def test_missing_tag_skips_registration(self, registry, hass):
        """Tag-less registration must be refused with a warning."""
        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
        ) as mock_track:
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag=None,
            )
            mock_track.assert_not_called()
        assert "nid1" not in registry._entries

    @pytest.mark.asyncio
    async def test_empty_delivered_services_skipped(self, registry, hass):
        """No delivered services -> nothing to clear, no registration."""
        await registry.register(
            notification_id="nid1",
            clear_when={"entity_id": "binary_sensor.door", "state": "off"},
            delivered_services=[],
            tag="t1",
        )
        assert "nid1" not in registry._entries

    @pytest.mark.asyncio
    async def test_invalid_clear_when_shape_skipped(self, registry, hass):
        """An unrecognized clear_when dict is ignored."""
        await registry.register(
            notification_id="nid1",
            clear_when={"something_random": 1},
            delivered_services=["notify.mobile_app_phone"],
            tag="t1",
        )
        assert "nid1" not in registry._entries

    @pytest.mark.asyncio
    async def test_duplicate_notification_id_unregisters_prior(self, registry, hass):
        """Re-registering the same id tears down the prior entry first."""
        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            return_value=MagicMock(name="unsub_a"),
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="tag_a",
            )

        first_unsubs = registry._entries["nid1"]

        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            return_value=MagicMock(name="unsub_b"),
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.mobile_app_phone"],
                tag="tag_b",
            )

        # The prior unsubs were invoked (teardown) and the entry now holds
        # the new unsubs.
        for unsub in first_unsubs:
            unsub.assert_called()
        assert registry._tags["nid1"] == "tag_b"


class TestUnregister:
    @pytest.mark.asyncio
    async def test_unregister_by_tag(self, registry, hass):
        """unregister_by_tag removes any entries matching the tag."""
        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            return_value=MagicMock(),
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.a"],
                tag="shared_tag",
            )
            await registry.register(
                notification_id="nid2",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.b"],
                tag="shared_tag",
            )
            await registry.register(
                notification_id="nid3",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.c"],
                tag="other_tag",
            )

        removed = registry.unregister_by_tag("shared_tag")
        assert removed == 2
        assert "nid1" not in registry._entries
        assert "nid2" not in registry._entries
        assert "nid3" in registry._entries

    @pytest.mark.asyncio
    async def test_unregister_all_clears_everything(self, registry, hass):
        """unregister_all tears down every entry."""
        with patch(
            "custom_components.ticker.auto_clear.async_track_state_change_event",
            return_value=MagicMock(),
        ):
            await registry.register(
                notification_id="nid1",
                clear_when={"entity_id": "binary_sensor.door", "state": "off"},
                delivered_services=["notify.a"],
                tag="t1",
            )
            await registry.register(
                notification_id="nid2",
                clear_when={"event_type": "evt"},
                delivered_services=["notify.b"],
                tag="t2",
            )

        registry.unregister_all()
        assert registry._entries == {}
        assert registry._tags == {}


class TestDispatchClearWrapper:
    @pytest.mark.asyncio
    async def test_async_dispatch_clear_adapts_flat_list_to_dict_shape(self):
        """async_dispatch_clear must wrap flat strings into {'service': ...} dicts."""
        from custom_components.ticker import clear_notification as cn

        hass = MagicMock()
        with patch.object(
            cn, "_async_send_clear_to_services", new_callable=AsyncMock,
        ) as mock_send:
            mock_send.return_value = ["notify.mobile_app_phone"]
            await cn.async_dispatch_clear(
                hass,
                ["notify.mobile_app_phone", "notify.mobile_app_tablet"],
                "my_tag",
                "ctx-nid",
            )

            mock_send.assert_awaited_once()
            services_arg = mock_send.call_args.args[1]
            assert services_arg == [
                {"service": "notify.mobile_app_phone"},
                {"service": "notify.mobile_app_tablet"},
            ]
            # Tag and label passed through unchanged.
            assert mock_send.call_args.args[2] == "my_tag"
            assert mock_send.call_args.args[3] == "ctx-nid"
