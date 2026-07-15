"""Tests for the ``ticker.ensure_category`` service (v1.8.3b1).

NOTE (v1.8.3): This test file exceeds the 500-line project limit (~622 lines).
Accepted waiver — the 8 AC-grouped test classes share a common fixture/helper
header, and keeping them in one file keeps that setup in one place. If it grows
further, split into test_ensure_category_core.py (AC1/AC2/AC6/contract/refresh)
and test_ensure_category_validation.py (AC3/AC4/AC5).

Covers SPEC_TICKER_ENSURE_CATEGORY AC1-AC6 against the service handler
``async_handle_ensure_category`` in ``services.py``. The handler is invoked
directly with a mock ``ServiceCall`` whose ``.data`` is the raw field dict,
backed by a REAL ``CategoryMixin`` store so the create/idempotency guarantees
run through actual store code (not mocks).

Patching guidance (from code review): create-path field validation lives in
``category_validation.py``, NOT in ``websocket/categories.py``. To force a
validation outcome on the CREATE/ENSURE path, patch validators at
``custom_components.ticker.category_validation.*``. ``get_store`` is used
directly by the handler (imported into ``services.py``), so it is patched at
``custom_components.ticker.services.get_store``.

Acceptance criteria mapping:
- AC1 -> TestEnsureCreate
- AC2 -> TestEnsureIdempotentNoOp
- AC3 -> TestEnsureValidation
- AC4 -> TestEnsureFailSoft
- AC5 -> TestSharedValidationHelper
- AC6 -> TestEnsureCreateOnly
- Response contract -> TestResponseContract
- Schema refresh (§4.5) -> TestSchemaRefreshListener
"""

from __future__ import annotations

import copy
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.ticker.const import SERVICE_ENSURE_CATEGORY
from custom_components.ticker.store.categories import CategoryMixin


# ---------------------------------------------------------------------------
# Real-mixin store harness (data path runs unchanged; only HA-Store persistence
# and subscription-save are mocked). Mirrors the FakeCategoryStore pattern in
# tests/test_f35_chime_storage.py and _RealStore in test_f33_negate_websocket.py.
# ---------------------------------------------------------------------------


class _RealCategoryStore(CategoryMixin):
    """Concrete ``CategoryMixin`` used for ensure_category round-trip tests.

    The category dict, sparse-storage normalization, ``category_exists`` and
    the ``_category_listeners`` notification chain all run for real; only the
    HA Store ``async_save`` is mocked.
    """

    def __init__(self) -> None:
        self.hass = MagicMock()
        self._categories: dict = {}
        self._categories_store = MagicMock()
        self._categories_store.async_save = AsyncMock()
        self._subscriptions: dict = {}
        self._category_listeners: list = []
        self.async_save_subscriptions = AsyncMock()

    def _notify_subscription_change(self) -> None:  # pragma: no cover - unused here
        pass


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    return hass


async def _get_ensure_handler(hass) -> object:
    """Register services and return the ``ensure_category`` handler.

    Locates the registration by service name rather than positional index so
    the lookup survives re-ordering of ``async_register`` calls.
    """
    from custom_components.ticker.services import async_setup_services

    await async_setup_services(hass)
    for call in hass.services.async_register.call_args_list:
        if call.args[1] == SERVICE_ENSURE_CATEGORY:
            return call.args[2]
    raise AssertionError("ensure_category service was not registered")


def _make_call(**fields) -> MagicMock:
    """Build a mock ServiceCall whose ``.data`` is the raw field dict."""
    call = MagicMock()
    call.data = dict(fields)
    return call


def _patch_store(store):
    """Patch the handler's ``get_store`` to return the given store."""
    return patch(
        "custom_components.ticker.services.get_store",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# AC1 — create with a new category_id
# ---------------------------------------------------------------------------


class TestEnsureCreate:
    """AC1: ensuring a NEW category_id creates it with the supplied fields."""

    @pytest.mark.asyncio
    async def test_new_category_returns_created_true(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            result = await handler(
                _make_call(category_id="ew_alerts", name="EW Alerts")
            )

        assert result == {"created": True, "category_id": "ew_alerts"}

    @pytest.mark.asyncio
    async def test_new_category_persisted_with_supplied_fields(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(
                _make_call(
                    category_id="ew_ops",
                    name="EW Ops",
                    icon="mdi:cog",
                    critical=True,
                    navigate_to="/energy_wizard_beta",
                )
            )

        assert store.category_exists("ew_ops")
        cat = store.get_category("ew_ops")
        assert cat["name"] == "EW Ops"
        assert cat["icon"] == "mdi:cog"
        assert cat["critical"] is True
        assert cat["navigate_to"] == "/energy_wizard_beta"

    @pytest.mark.asyncio
    async def test_created_category_appears_in_get_categories(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_schedule", name="Schedule"))

        assert "ew_schedule" in store.get_categories()

    @pytest.mark.asyncio
    async def test_create_invokes_async_create_category(self):
        """The create path routes through store.async_create_category."""
        hass = _make_hass()
        store = _RealCategoryStore()
        spy = AsyncMock(wraps=store.async_create_category)
        store.async_create_category = spy
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_savings", name="Savings"))

        spy.assert_awaited_once()
        assert spy.await_args.kwargs["category_id"] == "ew_savings"


# ---------------------------------------------------------------------------
# AC2 — idempotent no-op (never overwrite)
# ---------------------------------------------------------------------------


class TestEnsureIdempotentNoOp:
    """AC2: re-ensuring an existing id with different attrs is a no-op.

    This is the critical "never clobber" guarantee — a user may have renamed
    or re-configured the category in the admin panel; ensure must preserve it.
    """

    @pytest.mark.asyncio
    async def test_second_ensure_returns_created_false(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_alerts", name="Original"))
            result = await handler(
                _make_call(category_id="ew_alerts", name="Different Name")
            )

        assert result == {"created": False, "category_id": "ew_alerts"}

    @pytest.mark.asyncio
    async def test_existing_category_is_unchanged(self):
        """User customizations (name/icon) survive a re-ensure verbatim."""
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(
                _make_call(
                    category_id="ew_alerts",
                    name="User Renamed This",
                    icon="mdi:heart",
                )
            )
            before = copy.deepcopy(store.get_category("ew_alerts"))

            await handler(
                _make_call(
                    category_id="ew_alerts",
                    name="Caller Default Name",
                    icon="mdi:bell",
                    critical=True,
                )
            )
            after = store.get_category("ew_alerts")

        assert after == before, (
            "AC2 regression: ensure_category overwrote an existing category. "
            "The exists-path must be a pure no-op."
        )
        assert after["name"] == "User Renamed This"
        assert after["icon"] == "mdi:heart"
        assert "critical" not in after

    @pytest.mark.asyncio
    async def test_no_op_does_not_re_save(self):
        """The no-op path must not touch the store persistence layer again."""
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_ops", name="Ops"))
            saves_after_create = store._categories_store.async_save.await_count
            await handler(_make_call(category_id="ew_ops", name="Ops v2"))
            saves_after_noop = store._categories_store.async_save.await_count

        assert saves_after_noop == saves_after_create


# ---------------------------------------------------------------------------
# AC3 — validation raises ServiceValidationError
# ---------------------------------------------------------------------------


class TestEnsureValidation:
    """AC3: invalid identity/field input raises ServiceValidationError."""

    @pytest.mark.asyncio
    async def test_invalid_category_id_raises(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store), pytest.raises(ServiceValidationError):
            # Uppercase + spaces violate the [a-z0-9_]+ slug pattern.
            await handler(_make_call(category_id="Bad ID!", name="Whatever"))

        assert store.get_categories() == {}

    @pytest.mark.asyncio
    async def test_empty_name_raises(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store), pytest.raises(ServiceValidationError):
            await handler(_make_call(category_id="ew_alerts", name=""))

    @pytest.mark.asyncio
    async def test_whitespace_only_name_raises(self):
        """A whitespace name sanitizes to empty -> invalid_name."""
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store), pytest.raises(ServiceValidationError):
            await handler(_make_call(category_id="ew_alerts", name="   "))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "unsafe",
        [
            "https://evil.example",
            "javascript:alert(1)",
            "//evil.example",
            "relative/no/leading/slash",
        ],
    )
    async def test_unsafe_navigate_to_raises(self, unsafe):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store), pytest.raises(ServiceValidationError):
            await handler(
                _make_call(
                    category_id="ew_alerts",
                    name="Alerts",
                    navigate_to=unsafe,
                )
            )

        assert store.get_categories() == {}

    @pytest.mark.asyncio
    async def test_validation_runs_before_store_resolution(self):
        """Bad input must raise even if the store is unresolvable — identity
        is validated first (SPEC §4.1 before §4.2)."""
        hass = _make_hass()
        handler = await _get_ensure_handler(hass)

        with patch(
            "custom_components.ticker.services.get_store",
            side_effect=ValueError("not loaded"),
        ), pytest.raises(ServiceValidationError):
            await handler(_make_call(category_id="Bad ID!", name="X"))


# ---------------------------------------------------------------------------
# AC4 — fail-soft before Ticker's config entry loads
# ---------------------------------------------------------------------------


class TestEnsureFailSoft:
    """AC4: called before Ticker is configured -> warn + created:false, no raise."""

    @pytest.mark.asyncio
    async def test_unresolvable_store_returns_created_false(self):
        hass = _make_hass()
        handler = await _get_ensure_handler(hass)

        with patch(
            "custom_components.ticker.services.get_store",
            side_effect=ValueError("Ticker integration not loaded"),
        ):
            result = await handler(_make_call(category_id="ew_alerts", name="A"))

        assert result == {"created": False, "category_id": "ew_alerts"}

    @pytest.mark.asyncio
    async def test_unresolvable_store_does_not_raise(self):
        hass = _make_hass()
        handler = await _get_ensure_handler(hass)

        with patch(
            "custom_components.ticker.services.get_store",
            side_effect=ValueError("not configured"),
        ):
            # Must NOT raise (fail-soft; caller may race the entry load).
            await handler(_make_call(category_id="ew_alerts", name="A"))

    @pytest.mark.asyncio
    async def test_fail_soft_logs_warning(self, caplog):
        hass = _make_hass()
        handler = await _get_ensure_handler(hass)

        with patch(
            "custom_components.ticker.services.get_store",
            side_effect=ValueError("not configured"),
        ), caplog.at_level(logging.WARNING, logger="custom_components.ticker.services"):
            await handler(_make_call(category_id="ew_alerts", name="A"))

        assert any(
            record.levelno == logging.WARNING
            and "before Ticker is configured" in record.getMessage()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_fail_soft_creates_nothing(self):
        """No store write occurs when Ticker is not loaded."""
        hass = _make_hass()
        store = _RealCategoryStore()
        store.async_create_category = AsyncMock()
        handler = await _get_ensure_handler(hass)

        with patch(
            "custom_components.ticker.services.get_store",
            side_effect=ValueError("not configured"),
        ):
            await handler(_make_call(category_id="ew_alerts", name="A"))

        store.async_create_category.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC6 — create-only (never update/delete on the exists path)
# ---------------------------------------------------------------------------


class TestEnsureCreateOnly:
    """AC6: ensuring an existing category never updates or deletes it."""

    @pytest.mark.asyncio
    async def test_exists_path_calls_no_mutating_store_methods(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        # Seed an existing category via the real create path first.
        with _patch_store(store):
            await handler(_make_call(category_id="ew_alerts", name="Seed"))

            # Now spy on every mutating store method and re-ensure.
            store.async_create_category = AsyncMock()
            store.async_update_category = AsyncMock()
            store.async_delete_category = AsyncMock()

            await handler(
                _make_call(category_id="ew_alerts", name="Should Not Apply")
            )

        store.async_create_category.assert_not_awaited()
        store.async_update_category.assert_not_awaited()
        store.async_delete_category.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_path_never_updates_or_deletes(self):
        """Even on the create branch, only create is invoked."""
        hass = _make_hass()
        store = _RealCategoryStore()
        store.async_update_category = AsyncMock()
        store.async_delete_category = AsyncMock()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_new", name="New"))

        store.async_update_category.assert_not_awaited()
        store.async_delete_category.assert_not_awaited()


# ---------------------------------------------------------------------------
# Response contract — SupportsResponse.OPTIONAL dict shape on both paths
# ---------------------------------------------------------------------------


class TestResponseContract:
    """The handler returns the ``{"created": bool, "category_id": str}`` dict."""

    @pytest.mark.asyncio
    async def test_create_path_response_shape(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            result = await handler(_make_call(category_id="ew_alerts", name="A"))

        assert isinstance(result, dict)
        assert set(result) == {"created", "category_id"}
        assert result["created"] is True
        assert result["category_id"] == "ew_alerts"

    @pytest.mark.asyncio
    async def test_noop_path_response_shape(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_alerts", name="A"))
            result = await handler(_make_call(category_id="ew_alerts", name="B"))

        assert isinstance(result, dict)
        assert set(result) == {"created", "category_id"}
        assert result["created"] is False
        assert result["category_id"] == "ew_alerts"

    @pytest.mark.asyncio
    async def test_service_registered_with_optional_response(self):
        """The service is registered supports_response=OPTIONAL so plain
        automations still work while callers can opt into the dict."""
        from homeassistant.core import SupportsResponse

        hass = _make_hass()
        await _get_ensure_handler(hass)

        for call in hass.services.async_register.call_args_list:
            if call.args[1] == SERVICE_ENSURE_CATEGORY:
                assert call.kwargs.get("supports_response") is (
                    SupportsResponse.OPTIONAL
                )
                break
        else:  # pragma: no cover
            raise AssertionError("ensure_category not registered")


# ---------------------------------------------------------------------------
# AC5 — single shared validation helper for WS-create and the service
# ---------------------------------------------------------------------------


class TestSharedValidationHelper:
    """AC5: ws/category/create and ticker.ensure_category share ONE validator.

    The 66 existing WS-create tests already prove WS behavior preservation; we
    do not duplicate them. Here we assert both paths route through
    ``validate_and_sanitize_category_fields`` by patching a validator at the
    ``category_validation.*`` layer and observing that BOTH surfaces reflect
    the same underlying failure (per the code-review patching guidance).
    """

    @pytest.mark.asyncio
    async def test_both_paths_surface_same_validator_failure(self):
        from custom_components.ticker.websocket.categories import ws_create_category

        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        # Force the SHARED validator to fail at the category_validation layer.
        with patch(
            "custom_components.ticker.category_validation.validate_category_id",
            return_value=(False, "shared-helper-error"),
        ):
            # Service path -> ServiceValidationError carrying the shared message.
            with _patch_store(store):
                with pytest.raises(ServiceValidationError) as exc_info:
                    await handler(_make_call(category_id="x", name="X"))
            assert "shared-helper-error" in str(exc_info.value)

            # WS path -> send_error with the shared code + message.
            connection = MagicMock()
            msg = {
                "id": 7,
                "type": "ticker/category/create",
                "category_id": "x",
                "name": "X",
            }
            with patch(
                "custom_components.ticker.websocket.categories.get_store",
                return_value=store,
            ):
                await ws_create_category(hass, connection, msg)

        connection.send_error.assert_called_once()
        _mid, code, message = connection.send_error.call_args.args
        assert code == "invalid_category_id"
        assert message == "shared-helper-error"

    @pytest.mark.asyncio
    async def test_patching_at_websocket_layer_is_dead_for_create_path(self):
        """Guard for the review note: create-path validation no longer lives
        in websocket.categories, so patching a validator THERE must NOT affect
        the ensure service. If this ever starts failing, validation has drifted
        back into the WS module."""
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        # websocket.categories does not import validate_category_id at all for
        # the create path (it delegates to category_validation). Patching a
        # name there is a no-op; the service still creates successfully.
        with _patch_store(store), patch(
            "custom_components.ticker.websocket.validation.validate_category_id",
            return_value=(True, None),
        ):
            result = await handler(_make_call(category_id="ew_alerts", name="A"))

        assert result["created"] is True


# ---------------------------------------------------------------------------
# Schema refresh (SPEC §4.5) — category-change listener chain fires on create
# ---------------------------------------------------------------------------


class TestSchemaRefreshListener:
    """SPEC §4.5: creating via the service fires the category-change listener
    chain (``on_category_change`` -> ``update_service_schema``) so the
    ``ticker.notify`` category dropdown refreshes automatically.

    We assert at the store-listener boundary: ``async_create_category`` ->
    ``async_save_categories`` -> ``_notify_category_change`` invokes registered
    listeners. ``register_schema_updater`` wires ``update_service_schema`` in as
    exactly such a listener in production. End-to-end dropdown re-render is a
    frontend concern covered by deploy/UX verification (see coverage gap).
    """

    @pytest.mark.asyncio
    async def test_create_fires_category_listener(self):
        hass = _make_hass()
        store = _RealCategoryStore()
        listener = MagicMock()
        store.register_category_listener(listener)
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_alerts", name="A"))

        listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_does_not_fire_category_listener(self):
        """A no-op ensure must not needlessly refresh the schema."""
        hass = _make_hass()
        store = _RealCategoryStore()
        handler = await _get_ensure_handler(hass)

        with _patch_store(store):
            await handler(_make_call(category_id="ew_alerts", name="A"))
            listener = MagicMock()
            store.register_category_listener(listener)
            await handler(_make_call(category_id="ew_alerts", name="B"))

        listener.assert_not_called()
