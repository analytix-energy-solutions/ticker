"""Shared fixtures for Ticker tests.

Stubs out all homeassistant.* modules so Ticker code can be imported
without a real Home Assistant installation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Ensure custom_components is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))


class _FakeState:
    """Minimal State stand-in."""

    def __init__(self, entity_id: str, state: str):
        self.entity_id = entity_id
        self.state = state


class _StubModule(ModuleType):
    """Module that returns MagicMock for any missing attribute."""

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        mock = MagicMock()
        setattr(self, name, mock)
        return mock


def _make_module(name: str) -> _StubModule:
    """Create a real ModuleType with MagicMock attributes."""
    mod = _StubModule(name)
    mod.__dict__.setdefault("__all__", [])
    return mod


def _ensure_module(name: str) -> ModuleType:
    """Get or create a stub module."""
    if name not in sys.modules:
        sys.modules[name] = _make_module(name)
    return sys.modules[name]


# All homeassistant sub-modules referenced by ticker
_HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.const",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.loader",
    "homeassistant.helpers",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.typing",
    "homeassistant.helpers.event",
    "homeassistant.helpers.service",
    "homeassistant.helpers.start",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.components",
    "homeassistant.components.frontend",
    "homeassistant.components.panel_custom",
    "homeassistant.components.sensor",
    "homeassistant.components.persistent_notification",
    "homeassistant.components.websocket_api",
]

for _name in _HA_MODULES:
    _ensure_module(_name)

# Wire parent -> child references so `from homeassistant.X import Y` works
_ha = sys.modules["homeassistant"]
_ha.core = sys.modules["homeassistant.core"]
_ha.const = sys.modules["homeassistant.const"]
_ha.config_entries = sys.modules["homeassistant.config_entries"]
_ha.data_entry_flow = sys.modules["homeassistant.data_entry_flow"]
_ha.exceptions = sys.modules["homeassistant.exceptions"]
_ha.helpers = sys.modules["homeassistant.helpers"]
_ha.util = sys.modules["homeassistant.util"]
_ha.components = sys.modules["homeassistant.components"]

_helpers = sys.modules["homeassistant.helpers"]
_helpers.storage = sys.modules["homeassistant.helpers.storage"]
_helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]
_helpers.entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
_helpers.device_registry = sys.modules["homeassistant.helpers.device_registry"]
_helpers.config_validation = sys.modules["homeassistant.helpers.config_validation"]
_helpers.typing = sys.modules["homeassistant.helpers.typing"]
_helpers.event = sys.modules["homeassistant.helpers.event"]
_helpers.service = sys.modules["homeassistant.helpers.service"]
_helpers.start = sys.modules["homeassistant.helpers.start"]

_start = sys.modules["homeassistant.helpers.start"]
_start.async_at_start = MagicMock()

_util = sys.modules["homeassistant.util"]
_util.dt = sys.modules["homeassistant.util.dt"]
_util.slugify = MagicMock()

_comp = sys.modules["homeassistant.components"]
_comp.frontend = sys.modules["homeassistant.components.frontend"]
_comp.panel_custom = sys.modules["homeassistant.components.panel_custom"]
_comp.sensor = sys.modules["homeassistant.components.sensor"]
_comp.persistent_notification = sys.modules[
    "homeassistant.components.persistent_notification"
]
_comp.websocket_api = sys.modules["homeassistant.components.websocket_api"]

# Stub homeassistant.components.notify for notify platform tests
_ensure_module("homeassistant.components.notify")
_notify = sys.modules["homeassistant.components.notify"]
_notify.NotifyEntity = type("NotifyEntity", (), {
    "hass": None,
    "async_send_message": None,
})
_comp.notify = _notify

# Populate commonly used attributes on stub modules
_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = MagicMock
_core.State = _FakeState
_core.callback = lambda fn: fn  # passthrough decorator
_core.Event = MagicMock
_core.ServiceCall = MagicMock

_const = sys.modules["homeassistant.const"]
_const.Platform = MagicMock()

_config_entries = sys.modules["homeassistant.config_entries"]
_config_entries.ConfigEntry = MagicMock
_config_entries.ConfigFlow = MagicMock
_config_entries.ConfigEntryState = MagicMock()

_data_entry_flow = sys.modules["homeassistant.data_entry_flow"]
_data_entry_flow.FlowResult = MagicMock

_exceptions = sys.modules["homeassistant.exceptions"]

class _HAStubException(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        for k, v in kwargs.items():
            setattr(self, k, v)

_exceptions.HomeAssistantError = _HAStubException
_exceptions.ServiceValidationError = _HAStubException
_exceptions.ServiceNotFound = _HAStubException

_storage = sys.modules["homeassistant.helpers.storage"]
_storage.Store = MagicMock

_event = sys.modules["homeassistant.helpers.event"]
_event.async_call_later = MagicMock()
_event.async_track_state_change_event = MagicMock()
_event.async_track_time_interval = MagicMock()

_entity_platform = sys.modules["homeassistant.helpers.entity_platform"]
_entity_platform.AddEntitiesCallback = MagicMock

_entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
_entity_registry.async_get = MagicMock()
_entity_registry.EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"

_device_registry = sys.modules["homeassistant.helpers.device_registry"]
_device_registry.async_get = MagicMock()

_cv = sys.modules["homeassistant.helpers.config_validation"]
# cv is often used as `cv.string`, `cv.boolean` etc.

_service = sys.modules["homeassistant.helpers.service"]
_service.async_set_service_schema = MagicMock()

_frontend = sys.modules["homeassistant.components.frontend"]
_frontend.add_extra_js_url = MagicMock()

_sensor = sys.modules["homeassistant.components.sensor"]
_sensor.SensorEntity = type("SensorEntity", (), {})

_websocket_api = sys.modules["homeassistant.components.websocket_api"]
_websocket_api.async_register_command = MagicMock()
_websocket_api.websocket_command = lambda schema: (lambda fn: fn)
_websocket_api.async_response = lambda fn: fn
_websocket_api.require_admin = lambda fn: fn
_websocket_api.ActiveConnection = MagicMock


# -- Fixtures ---------------------------------------------------------------

@pytest.fixture
def fake_state():
    """Return factory for FakeState objects."""
    return _FakeState


@pytest.fixture
def mock_hass():
    """Return a minimal mocked HomeAssistant instance."""
    hass = MagicMock()
    hass.states = MagicMock()
    return hass
