"""SEC-003 / SEC-004 / SEC-006 / SEC-007 — admin gates on privileged WS handlers.

v1.8.2 added ``@websocket_api.require_admin`` to the following handlers that
were previously reachable by any authenticated (non-admin) user:

* SEC-003 / SEC-004 — migration & test-notification operations
  (``websocket/operations.py``):
  ``ws_test_notification``, ``ws_migrate_scan``, ``ws_migrate_convert``,
  ``ws_migrate_delete``.
* SEC-006 — automations manager (``websocket/automations.py``):
  ``ws_automations_scan``, ``ws_automations_update``.
* SEC-007 — action-set / snooze management (``websocket/actions.py``):
  ``ws_set_action_set``, ``ws_get_snoozes``, ``ws_clear_snooze``.

This mirrors ``test_sec001_category_admin_gate.py``. The conftest
``require_admin`` stub tags every decorated function with the
``_ticker_require_admin`` marker; the HA framework enforces the gate at the
framework boundary, so at unit-test import time the marker is the durable,
inspectable proof that the decorator is present.

The introspection guard below FAILS the moment ``@require_admin`` is removed
from ANY of these handlers — the exact regression these fixes defend against.
"""

from __future__ import annotations

import pytest

from custom_components.ticker.websocket.operations import (
    ws_migrate_convert,
    ws_migrate_delete,
    ws_migrate_scan,
    ws_test_notification,
)
from custom_components.ticker.websocket.automations import (
    ws_automations_scan,
    ws_automations_update,
)
from custom_components.ticker.websocket.actions import (
    ws_clear_snooze,
    ws_get_snoozes,
    ws_set_action_set,
)


# Every handler that MUST be admin-gated in v1.8.2, grouped by fix id so a
# failure names the finding it protects.
ADMIN_GATED_HANDLERS = [
    # SEC-003 / SEC-004 — websocket/operations.py
    ("SEC-003/004", ws_test_notification),
    ("SEC-003/004", ws_migrate_scan),
    ("SEC-003/004", ws_migrate_convert),
    ("SEC-003/004", ws_migrate_delete),
    # SEC-006 — websocket/automations.py
    ("SEC-006", ws_automations_scan),
    ("SEC-006", ws_automations_update),
    # SEC-007 — websocket/actions.py
    ("SEC-007", ws_set_action_set),
    ("SEC-007", ws_get_snoozes),
    ("SEC-007", ws_clear_snooze),
]


class TestRequireAdminMarkers:
    """The ``@require_admin`` decorator must gate every privileged handler."""

    @pytest.mark.parametrize(
        "finding_id,handler",
        ADMIN_GATED_HANDLERS,
        ids=lambda v: v if isinstance(v, str) else v.__name__,
    )
    def test_handler_is_admin_gated(self, finding_id, handler):
        """Regression guard: FAILS if ``require_admin`` is dropped."""
        assert getattr(handler, "_ticker_require_admin", False), (
            f"[{finding_id}] {handler.__name__} must be decorated with "
            "@websocket_api.require_admin — removing it re-opens the "
            "privileged handler to non-admin WebSocket callers"
        )

    def test_all_nine_handlers_covered(self):
        """Pin the count so a handler cannot be quietly dropped from the guard."""
        assert len(ADMIN_GATED_HANDLERS) == 9
        # And every entry is a distinct callable.
        handlers = [h for _, h in ADMIN_GATED_HANDLERS]
        assert len(set(handlers)) == 9
