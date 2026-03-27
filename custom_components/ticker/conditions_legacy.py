"""Legacy condition format converters for Ticker.

Handles conversion from pre-F-2 zone-based condition formats to the
current rules-based format. Used by store migrations.
"""

from __future__ import annotations

import logging
from typing import Any

from .const import RULE_TYPE_ZONE

_LOGGER = logging.getLogger(__name__)


def convert_legacy_zones_to_rules(
    zones_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert legacy zones format to new conditions format.

    Legacy format:
        {
            "zone.home": {
                "deliver_while_here": True,
                "queue_until_arrival": True
            }
        }

    New conditions format:
        {
            "deliver_when_met": True,
            "queue_until_met": True,
            "rules": [
                {"type": "zone", "zone_id": "zone.home"}
            ]
        }

    Since legacy format only had zone conditions, the per-zone flags
    are promoted to conditions-level (1:1 conversion).

    Args:
        zones_config: Legacy zones dict

    Returns:
        Complete conditions dict with rules and top-level flags
    """
    rules: list[dict[str, Any]] = []
    has_deliver = False
    has_queue = False

    for zone_id, zone_config in zones_config.items():
        if zone_config.get("deliver_while_here", False):
            has_deliver = True
        if zone_config.get("queue_until_arrival", False):
            has_queue = True

        rule: dict[str, Any] = {
            "type": RULE_TYPE_ZONE,
            "zone_id": zone_id,
        }
        rules.append(rule)

    return {
        "deliver_when_met": has_deliver,
        "queue_until_met": has_queue,
        "rules": rules,
    }
