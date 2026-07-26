"""Integration coverage for ``bundle_on_release`` threading through the shared
category-field validator (``category_validation.py``).

PR #60 shipped the ``bundle_on_release`` feature tests (store sparse + WS
create/update + delivery split) in ``tests/test_bundle_on_release.py``. This
module closes the ONE remaining integration gap: both ``ws_create_category``
and the ``ticker.ensure_category`` service now route category fields through
``validate_and_sanitize_category_fields``, and ``bundle_on_release`` was
threaded through that shared helper. We assert only the helper's contract for
this key (returned kwargs shape) — the store's sparse-skip behavior itself is
already proven by #60.

Contract: the helper always returns ``bundle_on_release`` in its kwargs dict,
passing the caller's value straight through:
- ``False``  -> ``False`` (store persists it)
- ``True``   -> ``True``  (store omits it -> default True)
- absent     -> ``None``  (store sparse-skips it -> default True)
"""

from __future__ import annotations

import sys

import pytest
import voluptuous as vol

# The ensure_category schema references cv.string / cv.boolean, which the
# conftest stub leaves as bare MagicMocks (they let any value through and
# return MagicMock). To exercise the schema's field coercion/rejection we
# install real-ish validators into the stub module BEFORE building the schema,
# mirroring the established pattern in test_bugfix_104_action_set_id_param.py.
_cv = sys.modules["homeassistant.helpers.config_validation"]


def _cv_string(value):
    if isinstance(value, str):
        return value
    raise vol.Invalid("expected str")


def _cv_boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on", "enable"):
            return True
        if low in ("0", "false", "no", "off", "disable"):
            return False
        raise vol.Invalid("expected boolean")
    if isinstance(value, int):
        return bool(value)
    raise vol.Invalid("expected boolean")


_cv.string = _cv_string
_cv.boolean = _cv_boolean

from custom_components.ticker.category_validation import (  # noqa: E402
    validate_and_sanitize_category_fields,
)
from custom_components.ticker.service_schema import (  # noqa: E402
    _build_ensure_category_schema,
)


def _base_fields(**extra) -> dict:
    """Minimal valid create fields, plus any extra keys under test."""
    fields = {"category_id": "appliance_done", "name": "Appliance done"}
    fields.update(extra)
    return fields


class TestBundleOnReleasePassThrough:
    """The shared helper surfaces ``bundle_on_release`` verbatim in its kwargs."""

    def test_false_passed_through(self):
        kwargs = validate_and_sanitize_category_fields(
            _base_fields(bundle_on_release=False)
        )
        assert kwargs["bundle_on_release"] is False

    def test_true_passed_through(self):
        kwargs = validate_and_sanitize_category_fields(
            _base_fields(bundle_on_release=True)
        )
        assert kwargs["bundle_on_release"] is True

    def test_absent_is_none(self):
        """Key omitted -> None so the store sparse-skips it (default True)."""
        kwargs = validate_and_sanitize_category_fields(_base_fields())
        assert kwargs["bundle_on_release"] is None

    def test_key_always_present_in_kwargs(self):
        """The kwargs are splatted into async_create_category, so the key must
        exist on every path (even when the caller omits it)."""
        assert "bundle_on_release" in validate_and_sanitize_category_fields(
            _base_fields()
        )


class TestEnsureCategorySchemaBundleOnRelease:
    """The ``ticker.ensure_category`` voluptuous schema accepts the bool field.

    Confirms the schema wiring in ``_build_ensure_category_schema`` (§SPEC
    schema mirror of the WS create command) exposes ``bundle_on_release`` as an
    optional cv.boolean — the entry point the service handler validates against.
    """

    def test_schema_accepts_false(self):
        schema = _build_ensure_category_schema()
        out = schema(
            {
                "category_id": "appliance_done",
                "name": "Appliance done",
                "bundle_on_release": False,
            }
        )
        assert out["bundle_on_release"] is False

    def test_schema_accepts_true(self):
        schema = _build_ensure_category_schema()
        out = schema(
            {
                "category_id": "news",
                "name": "News",
                "bundle_on_release": True,
            }
        )
        assert out["bundle_on_release"] is True

    def test_schema_omits_when_absent(self):
        """Optional field — not injected into the validated output when omitted."""
        schema = _build_ensure_category_schema()
        out = schema({"category_id": "news", "name": "News"})
        assert "bundle_on_release" not in out

    def test_schema_rejects_non_boolean(self):
        """cv.boolean rejects a value that is not boolean-coercible."""
        schema = _build_ensure_category_schema()
        with pytest.raises(vol.Invalid):
            schema(
                {
                    "category_id": "news",
                    "name": "News",
                    "bundle_on_release": "not-a-bool",
                }
            )
