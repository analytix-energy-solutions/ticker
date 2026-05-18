"""Tests for BUG-104: `action_set_id` parameter on `ticker.notify`.

The internal plumbing (`actions.resolve_action_set` plus the four
delivery functions in `user_notify` / `recipient_notify`) has accepted
`action_set_id` since v1.5.0, but the service entry point itself never
wired it. Four gap sites were fixed:

1. service_schema._build_service_schema: vol.Optional(ATTR_ACTION_SET_ID): cv.string
2. service_schema._build_service_description: text-selector field exposed
3. services.async_handle_notify: extract from call.data (empty/whitespace -> None)
4. services._dispatch_to_category: kwarg + forward to all four downstream
   delivery functions.

`resolve_action_set` already handles unknown IDs fail-soft (logs a warning,
falls back to the category default), so the schema does not validate
existence.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol


# --- conftest cv stub: make cv.string an identity-with-type-check ---------
# The shared conftest stubs `homeassistant.helpers.config_validation` as a
# MagicMock, which lets any value through. To exercise the schema's
# rejection of non-string action_set_id values we install a real-ish
# `cv.string` validator into the stub module BEFORE importing the schema.
_cv = sys.modules["homeassistant.helpers.config_validation"]


def _cv_string(value):
    if isinstance(value, str):
        return value
    raise vol.Invalid("expected str")


_cv.string = _cv_string
# vol.Length expects a length-checkable; keep it permissive.
_cv.entity_id = lambda v: v
_cv.boolean = lambda v: bool(v) if isinstance(v, (bool, int, str)) else v


from custom_components.ticker.const import ATTR_ACTION_SET_ID  # noqa: E402
from custom_components.ticker.service_schema import (  # noqa: E402
    _build_service_description,
    _build_service_schema,
)


# ---------------------------------------------------------------------------
# Schema tests (gap 1)
# ---------------------------------------------------------------------------


class TestSchemaAcceptsActionSetId:
    """`_build_service_schema()` must accept `action_set_id` as optional str."""

    def test_schema_accepts_action_set_id(self):
        schema = _build_service_schema()
        out = schema(
            {
                "category": "alerts",
                "title": "t",
                "message": "m",
                "action_set_id": "confirm_alert",
            }
        )
        assert out["action_set_id"] == "confirm_alert"

    def test_schema_omits_action_set_id_cleanly(self):
        """Omitting `action_set_id` is valid and the key is absent from output."""
        schema = _build_service_schema()
        out = schema({"category": "alerts", "title": "t", "message": "m"})
        assert "action_set_id" not in out

    def test_schema_rejects_non_string_action_set_id(self):
        """Voluptuous must reject ints/lists/dicts; cv.string demands str."""
        schema = _build_service_schema()
        with pytest.raises(vol.Invalid):
            schema(
                {
                    "category": "alerts",
                    "title": "t",
                    "message": "m",
                    "action_set_id": 12345,
                }
            )


# ---------------------------------------------------------------------------
# Description tests (gap 2)
# ---------------------------------------------------------------------------


class TestDescriptionExposesActionSetIdField:
    """`_build_service_description()` must expose action_set_id as a text field."""

    def test_description_has_action_set_id_field(self):
        desc = _build_service_description(store=None, hass=None)
        assert ATTR_ACTION_SET_ID in desc["fields"]

    def test_action_set_id_field_uses_text_selector(self):
        desc = _build_service_description(store=None, hass=None)
        field = desc["fields"][ATTR_ACTION_SET_ID]
        assert field["selector"] == {"text": {}}
        assert field["required"] is False


# ---------------------------------------------------------------------------
# Handler extraction + dispatcher forwarding (gaps 3 + 4)
# ---------------------------------------------------------------------------


def _make_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.async_register = MagicMock()
    hass.states = MagicMock()
    hass.states.async_all.return_value = []
    return hass


def _make_store(known_categories: list[str]):
    store = MagicMock()
    store.get_recipients.return_value = {}
    store.category_exists.side_effect = lambda cid: cid in known_categories
    store.get_categories.return_value = {
        cid: {"name": cid} for cid in known_categories
    }
    store.get_category.side_effect = (
        lambda cid: {"name": cid} if cid in known_categories else None
    )
    store.is_user_enabled.return_value = True
    store.get_subscription_mode.return_value = "always"
    store.async_add_log = AsyncMock()
    return store


async def _get_handler(hass):
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    return hass.services.async_register.call_args_list[0][0][2]


def _make_call(category, *, action_set_id=None, omit_key=False):
    call = MagicMock()
    call.data = {"category": category, "title": "T", "message": "M"}
    if not omit_key:
        call.data["action_set_id"] = action_set_id
    return call


def _patch_entry(store):
    entry = MagicMock()
    entry.runtime_data.store = store
    entry.runtime_data.auto_clear = None
    return patch(
        "custom_components.ticker.services._get_loaded_entry",
        return_value=entry,
    )


def _make_person(entity_id="person.alice", name="Alice"):
    person = MagicMock()
    person.entity_id = entity_id
    person.attributes = {"friendly_name": name}
    return person


class TestHandlerExtractsActionSetId:
    """`async_handle_notify` must extract `action_set_id` from `call.data`
    and coerce empty/whitespace to None."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_handler_extracts_value_and_forwards(self, _sensor):
        """A real id flows through to the downstream delivery call."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="confirm_alert"))

        assert mock_send.await_count == 1
        assert mock_send.call_args.kwargs["action_set_id"] == "confirm_alert"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_handler_coerces_empty_string_to_none(self, _sensor):
        """`action_set_id: ""` becomes None so the category default is used."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id=""))

        assert mock_send.call_args.kwargs["action_set_id"] is None

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_handler_coerces_whitespace_to_none(self, _sensor):
        """Whitespace-only value coerces to None as well."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="   "))

        assert mock_send.call_args.kwargs["action_set_id"] is None

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_handler_omitted_key_is_none(self, _sensor):
        """No `action_set_id` key at all -> forwarded as None (category default)."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", omit_key=True))

        assert mock_send.call_args.kwargs["action_set_id"] is None


class TestDispatchForwardsToFourDownstreams:
    """`_dispatch_to_category` must forward `action_set_id` to all four
    delivery functions: async_send_notification, async_handle_conditional_notification,
    async_send_to_recipient, async_handle_conditional_recipient."""

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_forwards_to_async_send_notification(self, _sensor):
        """MODE_ALWAYS person -> async_send_notification."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        store.get_subscription_mode.return_value = "always"
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="my_set"))

        assert mock_send.call_args.kwargs["action_set_id"] == "my_set"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_forwards_to_async_handle_conditional_notification(self, _sensor):
        """MODE_CONDITIONAL person -> async_handle_conditional_notification."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        store.get_subscription_mode.return_value = "conditional"
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_handle_conditional_notification",
            new_callable=AsyncMock,
        ) as mock_cond, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_cond.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="my_set"))

        assert mock_cond.call_args.kwargs["action_set_id"] == "my_set"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_forwards_to_async_send_to_recipient(self, _sensor):
        """MODE_ALWAYS recipient -> async_send_to_recipient."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        store.get_recipients.return_value = {
            "phone": {"enabled": True, "name": "Phone"}
        }
        store.get_subscription_mode.return_value = "always"
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_to_recipient",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="my_set"))

        assert mock_send.call_args.kwargs["action_set_id"] == "my_set"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_forwards_to_async_handle_conditional_recipient(self, _sensor):
        """MODE_CONDITIONAL recipient -> async_handle_conditional_recipient."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        store.get_recipients.return_value = {
            "phone": {"enabled": True, "name": "Phone"}
        }
        store.get_subscription_mode.return_value = "conditional"
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_handle_conditional_recipient",
            new_callable=AsyncMock,
        ) as mock_cond, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_cond.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="my_set"))

        assert mock_cond.call_args.kwargs["action_set_id"] == "my_set"


class TestIntegrationOverrideAndFallback:
    """End-to-end behavior expectations:
    - per-call override flows through unchanged
    - omitted action_set_id forwards as None so the category default is used
    - unknown id is not pre-validated (fail-soft contract)
    """

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_per_call_overrides_category_default(self, _sensor):
        """A per-call id is what the dispatcher forwards regardless of any
        category-stored default — resolve_action_set decides priority
        downstream, not the dispatcher."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        # Category has its own default action_set_id; the dispatcher must
        # NOT substitute it for the per-call override.
        store.get_category.side_effect = lambda cid: (
            {"name": cid, "action_set_id": "category_default_set"}
            if cid == "alerts"
            else None
        )
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", action_set_id="per_call_set"))

        # The per-call value is what the dispatcher forwards.
        assert mock_send.call_args.kwargs["action_set_id"] == "per_call_set"

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_omitted_action_set_id_uses_category_default(self, _sensor):
        """When the caller omits action_set_id, the dispatcher passes None
        and resolve_action_set (downstream) falls back to the category
        default. No regression for callers that never set the param."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        store.get_category.side_effect = lambda cid: (
            {"name": cid, "action_set_id": "category_default_set"}
            if cid == "alerts"
            else None
        )
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            await handler(_make_call("alerts", omit_key=True))

        assert mock_send.call_args.kwargs["action_set_id"] is None

    @pytest.mark.asyncio
    @patch("custom_components.ticker.services.get_category_sensor", return_value=None)
    async def test_unknown_action_set_id_passes_through(self, _sensor):
        """Schema must not reject unknown IDs — fail-soft is enforced
        downstream by resolve_action_set (warns + category default)."""
        hass = _make_hass()
        store = _make_store(["alerts"])
        hass.states.async_all.return_value = [_make_person()]
        handler = await _get_handler(hass)

        with _patch_entry(store), patch(
            "custom_components.ticker.services.async_send_notification",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "custom_components.ticker.services.build_smart_tag",
            return_value=None,
        ):
            mock_send.return_value = {"delivered": [], "queued": [], "dropped": []}
            # Schema accepts this unknown id, handler forwards it,
            # dispatch forwards it — without raising.
            await handler(_make_call("alerts", action_set_id="does_not_exist"))

        assert mock_send.call_args.kwargs["action_set_id"] == "does_not_exist"
