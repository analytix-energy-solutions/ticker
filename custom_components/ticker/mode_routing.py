"""Per-call routing modes for ticker.notify.

Categories carry a *static* ``priority_fallback``. This module adds a
per-call ``mode`` that filters recipients by presence at send time, as a
per-call override evaluated against the person ``State`` list before
subscription/condition resolution.

The two "then_away" fallback modes delegate to
``priority_fallback.resolve_priority_group`` so the category-level and
per-call code paths share a single implementation.
"""

from __future__ import annotations

from datetime import timedelta

from .const import (
    DEFAULT_PRIORITY_FALLBACK_WINDOW_MINUTES,
    ROUTE_MODE_ALL,
    ROUTE_MODE_JUST_ARRIVED,
    ROUTE_MODE_JUST_LEFT,
    ROUTE_MODE_JUST_LEFT_THEN_AWAY,
    ROUTE_MODE_NOBODY_HOME,
    ROUTE_MODE_ONLY_AWAY,
    ROUTE_MODE_ONLY_HOME,
    ROUTE_MODE_ONLY_HOME_THEN_AWAY,
    ROUTE_MODE_STAYING_AWAY,
    ROUTE_MODE_STAYING_HOME,
)
from .priority_fallback import resolve_priority_group

# Matches HA's person entity state literally; kept consistent with
# priority_fallback.py rather than importing from homeassistant.const.
_HOME_STATE = "home"
_UNRESOLVED_STATES = ("unknown", "unavailable")

_THEN_AWAY_MODES = (
    ROUTE_MODE_ONLY_HOME_THEN_AWAY,
    ROUTE_MODE_JUST_LEFT_THEN_AWAY,
)


def _window(window_minutes) -> timedelta:
    """Coerce a raw window value to a timedelta, defaulting on garbage.

    Mirrors resolve_priority_group's defensiveness: this reads a value that
    originates from a service call, so a malformed ``window_minutes`` degrades
    to the default rather than raising.
    """
    if not isinstance(window_minutes, (int, float)) or isinstance(window_minutes, bool):
        window_minutes = DEFAULT_PRIORITY_FALLBACK_WINDOW_MINUTES
    return timedelta(minutes=window_minutes)


def resolve_mode_group(persons: list, mode: str, window_minutes, now) -> list:
    """Return the subset of ``persons`` a per-call routing ``mode`` should notify.

    Presence classification mirrors ``resolve_priority_group``: persons in an unknown/unavailable state are
    never classified as home or away, so presence-scoped modes never select
    them.

    An unrecognized mode returns ``persons`` unchanged (fail-open, same
    contract as ``resolve_priority_group``) so an unexpected value degrades to
    "notify everyone" rather than silently dropping the notification.

    Args:
        persons: All person ``State`` objects for this notify call.
        mode: One of ``const.ROUTE_MODES``.
        window_minutes: Recency window for the ``just_*`` / ``staying_*`` /
            ``just_left_then_away`` modes. Ignored by the others.
        now: Current tz-aware time, for the recency comparisons.

    Returns:
        The subset of ``persons`` to notify.
    """
    if mode in (None, ROUTE_MODE_ALL):
        return persons

    if mode in _THEN_AWAY_MODES:
        return resolve_priority_group(
            persons, {"mode": mode, "window_minutes": window_minutes}, now,
        )

    known = [p for p in persons if p.state not in _UNRESOLVED_STATES]
    home = [p for p in known if p.state == _HOME_STATE]
    away = [p for p in known if p.state != _HOME_STATE]

    if mode == ROUTE_MODE_ONLY_HOME:
        return home
    if mode == ROUTE_MODE_ONLY_AWAY:
        return away
    if mode == ROUTE_MODE_NOBODY_HOME:
        # Everyone (with known presence) is notified, but only when no one is
        # home at all; if anyone is home, no one is notified.
        return [] if home else known

    threshold = _window(window_minutes)

    if mode == ROUTE_MODE_JUST_ARRIVED:
        return [p for p in home if now - p.last_changed <= threshold]
    if mode == ROUTE_MODE_JUST_LEFT:
        return [p for p in away if now - p.last_changed <= threshold]
    if mode == ROUTE_MODE_STAYING_HOME:
        return [p for p in home if now - p.last_changed > threshold]
    if mode == ROUTE_MODE_STAYING_AWAY:
        return [p for p in away if now - p.last_changed > threshold]

    return persons
