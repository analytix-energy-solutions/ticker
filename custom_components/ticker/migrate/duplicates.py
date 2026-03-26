"""Duplicate detection functions for migration scanner."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..const import DOMAIN, MIGRATE_SERVICES

# Services to check for duplicates (migration targets + ticker.notify)
DUPLICATE_CHECK_SERVICES = MIGRATE_SERVICES + [DOMAIN]

_LOGGER = logging.getLogger(__name__)


def _normalize_value(value: Any) -> Any:
    """Normalize a value for comparison.

    Treats None, empty string, and missing as equivalent.
    """
    if value is None or value == "":
        return None
    return value


def _normalize_data_for_comparison(data: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a data dict for comparison.

    Removes keys with None/empty values and normalizes remaining values.
    """
    if not data:
        return {}

    normalized = {}
    for key, value in data.items():
        norm_value = _normalize_value(value)
        if norm_value is not None:
            normalized[key] = norm_value
    return normalized


def _are_duplicates(finding1: dict[str, Any], finding2: dict[str, Any]) -> bool:
    """Check if two findings are duplicates.

    For notify.*/persistent_notification.* services:
        Compare title, message, and data fields (ignore service and target).

    For ticker.notify:
        Compare category, title, message, and data fields.

    Empty string, None, and missing field are treated as equal.
    """
    service1 = finding1.get("service", "")
    service2 = finding2.get("service", "")

    # Get service domains
    domain1 = service1.split(".")[0] if "." in service1 else service1
    domain2 = service2.split(".")[0] if "." in service2 else service2

    # Both must be notification-related services
    if domain1 not in DUPLICATE_CHECK_SERVICES or domain2 not in DUPLICATE_CHECK_SERVICES:
        return False

    data1 = finding1.get("service_data", {})
    data2 = finding2.get("service_data", {})

    # Compare title and message
    title1 = _normalize_value(data1.get("title"))
    title2 = _normalize_value(data2.get("title"))
    message1 = _normalize_value(data1.get("message"))
    message2 = _normalize_value(data2.get("message"))

    if title1 != title2 or message1 != message2:
        return False

    # For ticker.notify, also compare category
    is_ticker1 = domain1 == DOMAIN
    is_ticker2 = domain2 == DOMAIN

    if is_ticker1 and is_ticker2:
        cat1 = _normalize_value(data1.get("category"))
        cat2 = _normalize_value(data2.get("category"))
        if cat1 != cat2:
            return False

    # Compare data fields (excluding title, message, category)
    extra_keys = {"title", "message", "category"}
    extra_data1 = _normalize_data_for_comparison(
        {k: v for k, v in data1.items() if k not in extra_keys}
    )
    extra_data2 = _normalize_data_for_comparison(
        {k: v for k, v in data2.items() if k not in extra_keys}
    )

    return extra_data1 == extra_data2


def _mark_adjacent_duplicates(findings: list[dict[str, Any]]) -> None:
    """Mark findings that have adjacent duplicates.

    Modifies findings in-place to add duplicate metadata:
    - has_duplicate: bool
    - duplicate_finding_id: str (finding_id of the duplicate)
    - is_first_in_duplicate_pair: bool

    Only checks immediately adjacent findings within the same source and action path parent.
    """
    if len(findings) < 2:
        return

    # Group findings by source_id and parent path for adjacency check
    # Adjacent means same source and sequential action_index in same parent path
    for i in range(len(findings) - 1):
        current = findings[i]
        next_finding = findings[i + 1]

        # Skip if already marked as duplicate
        if current.get("has_duplicate") or next_finding.get("has_duplicate"):
            continue

        # Must be in same source (same automation/script)
        if current.get("source_id") != next_finding.get("source_id"):
            continue

        # Check if they're adjacent (sequential indices in same parent path)
        if not _are_adjacent(current, next_finding):
            continue

        # Check if they're duplicates
        if _are_duplicates(current, next_finding):
            current["has_duplicate"] = True
            current["duplicate_finding_id"] = next_finding["finding_id"]
            current["is_first_in_duplicate_pair"] = True

            next_finding["has_duplicate"] = True
            next_finding["duplicate_finding_id"] = current["finding_id"]
            next_finding["is_first_in_duplicate_pair"] = False

            _LOGGER.debug(
                "Found duplicate notifications in %s: indices %s and %s",
                current["source_id"],
                current["action_path"],
                next_finding["action_path"],
            )


def _are_adjacent(finding1: dict[str, Any], finding2: dict[str, Any]) -> bool:
    """Check if two findings are immediately adjacent in the action sequence.

    Adjacent means:
    - Same parent path (e.g., both in root actions, or both in same then: block)
    - Sequential action indices (e.g., [0] and [1], not [0] and [2])
    """
    path1 = finding1.get("action_path", "")
    path2 = finding2.get("action_path", "")

    # Extract parent path (everything before the last [index])
    # e.g., "[0].then[1]" -> parent is "[0].then", index is 1
    match1 = re.match(r"^(.*)\[(\d+)\]$", path1)
    match2 = re.match(r"^(.*)\[(\d+)\]$", path2)

    if not match1 or not match2:
        return False

    parent1, leaf_idx1 = match1.groups()
    parent2, leaf_idx2 = match2.groups()

    # Must have same parent path
    if parent1 != parent2:
        return False

    # Must be sequential (difference of 1)
    return abs(int(leaf_idx1) - int(leaf_idx2)) == 1
