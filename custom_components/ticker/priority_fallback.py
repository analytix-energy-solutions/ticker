"""Category-level priority fallback.

Split out of services.py to keep that file under the project's ~500-line
convention (mirrors the frontend admin panel's tab.js/handlers.js split).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .const import (
    DEFAULT_PRIORITY_FALLBACK_WINDOW_MINUTES,
    PRIORITY_FALLBACK_JUST_LEFT_THEN_AWAY,
    PRIORITY_FALLBACK_ONLY_HOME_THEN_AWAY,
)


def resolve_priority_group(
    persons: list,
    priority_fallback: dict[str, Any],
    now,
) -> list:
    """Resolve which persons a priority-fallback category should notify.

    The only_home_then_away / just_left_then_away modes try a primary
    group first, and fall back to everyone away only when the primary
    group is empty.

    - "only_home_then_away": primary = persons currently home.
    - "just_left_then_away": primary = persons away who transitioned away
      within window_minutes.

    In both cases the fallback group is everyone away, since the primary
    group being empty means (by construction) no one who is home would be
    in the fallback anyway.

    Persons whose presence is not actually known ("unknown"/"unavailable",
    e.g. a device tracker offline or not yet reported in after HA restart)
    are excluded from both groups: we cannot classify them as home or away,
    so they are never selected by this fallback either way.

    Args:
        persons: All person State objects for the category's notify call.
        priority_fallback: {"mode": ..., "window_minutes": ...}.
        now: Current time (tz-aware), for the just_left window comparison.

    Returns:
        The subset of `persons` that should be notified. Returns `persons`
        unchanged if `mode` is not recognized, or if `window_minutes` is
        malformed for "just_left_then_away" (defensive: this reads a raw
        stored dict, not one freshly validated by the store layer).
    """
    mode = priority_fallback.get("mode")
    # Matches HA's person entity state literally; not imported from
    # homeassistant.const to stay consistent with the rest of this codebase
    # (see conditions.py's zone-matching notes on person.state comparisons).
    home_state = "home"
    unresolved_states = ("unknown", "unavailable")
    known = [p for p in persons if p.state not in unresolved_states]

    if mode == PRIORITY_FALLBACK_ONLY_HOME_THEN_AWAY:
        home = [p for p in known if p.state == home_state]
        if home:
            return home
        return [p for p in known if p.state != home_state]

    if mode == PRIORITY_FALLBACK_JUST_LEFT_THEN_AWAY:
        window_minutes = priority_fallback.get(
            "window_minutes", DEFAULT_PRIORITY_FALLBACK_WINDOW_MINUTES,
        )
        if not isinstance(window_minutes, (int, float)) or isinstance(window_minutes, bool):
            window_minutes = DEFAULT_PRIORITY_FALLBACK_WINDOW_MINUTES
        away = [p for p in known if p.state != home_state]
        threshold = timedelta(minutes=window_minutes)
        just_left = [p for p in away if now - p.last_changed <= threshold]
        return just_left if just_left else away

    return persons
