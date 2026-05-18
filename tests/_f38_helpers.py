"""Shared fixtures and patch helpers for F-38 test files.

Imported by both ``test_f38_view_as_user.py`` (read-path + omit-scope
cases) and ``test_f38_view_as_user_writes.py`` (write-path + admin-only
+ device-preference cases). Kept under the 500-line limit by splitting
the spec §8 cases across two files; helpers live here to avoid
duplication.

Not prefixed with ``test_`` so pytest does not attempt collection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def discovered(
    caller_person: str | None,
    caller_user_id: str | None,
    other_person: str = "person.other",
    other_user_id: str = "uid_other",
) -> dict[str, dict[str, Any]]:
    """Return a discovery map with up to two persons.

    ``caller_person=None`` produces a map containing only the foreign
    person (used when the caller has no linked person entity).
    """
    out: dict[str, dict[str, Any]] = {}
    if caller_person is not None:
        out[caller_person] = {
            "person_id": caller_person,
            "name": "Caller",
            "user_id": caller_user_id,
            "notify_services": [{"service": "notify.caller_phone"}],
            "device_trackers": [],
        }
    out[other_person] = {
        "person_id": other_person,
        "name": "Other",
        "user_id": other_user_id,
        "notify_services": [{"service": "notify.other_phone"}],
        "device_trackers": [],
    }
    return out


def patch_discovery(disc: dict[str, dict[str, Any]]):
    """Patch discovery at the validation helper's import site.

    ``_resolve_caller_person_id`` does a local import of
    ``async_discover_notify_services`` from ``..discovery`` each call
    (see validation.py). Patching the source module intercepts every
    binding established by such local imports.
    """
    return patch(
        "custom_components.ticker.discovery.async_discover_notify_services",
        new=AsyncMock(return_value=disc),
    )


def patch_discovery_subscriptions(disc):
    """Patch discovery at the subscriptions module's import site."""
    return patch(
        "custom_components.ticker.websocket.subscriptions."
        "async_discover_notify_services",
        new=AsyncMock(return_value=disc),
    )


def patch_discovery_queue_log(disc):
    """Patch discovery at the queue_log module's import site."""
    return patch(
        "custom_components.ticker.websocket.queue_log."
        "async_discover_notify_services",
        new=AsyncMock(return_value=disc),
    )


def patch_discovery_users(disc):
    """Patch discovery at the users module's import site."""
    return patch(
        "custom_components.ticker.websocket.users."
        "async_discover_notify_services",
        new=AsyncMock(return_value=disc),
    )


def make_store() -> MagicMock:
    """Return a MagicMock store with the methods these tests touch."""
    store = MagicMock()
    store.category_exists.return_value = True
    store.async_set_subscription = AsyncMock(return_value={"ok": True})
    store.async_clear_queue_for_person = AsyncMock(return_value=0)
    store.async_remove_from_queue = AsyncMock(return_value=True)
    store.async_set_device_preference = AsyncMock(
        return_value={"device_preference": {"mode": "all", "devices": []}}
    )
    store.get_subscriptions_for_person.return_value = {}
    store.get_subscriptions_for_category.return_value = []
    store.get_categories.return_value = {}
    store.get_queue_for_person.return_value = []
    store.get_queue.return_value = {}
    store.get_logs.return_value = []
    store.get_user.return_value = None
    return store


def patch_store(store: MagicMock):
    """Return a list of context managers patching get_store at all three
    handler module bindings. Index 0 = subscriptions, 1 = queue_log,
    2 = users.
    """
    return [
        patch(
            "custom_components.ticker.websocket.subscriptions.get_store",
            return_value=store,
        ),
        patch(
            "custom_components.ticker.websocket.queue_log.get_store",
            return_value=store,
        ),
        patch(
            "custom_components.ticker.websocket.users.get_store",
            return_value=store,
        ),
    ]
