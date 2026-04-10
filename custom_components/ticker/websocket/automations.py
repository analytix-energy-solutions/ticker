"""Automations Manager WebSocket commands (F-3).

Provides scan and update commands for inspecting and editing
ticker.notify calls across automations and scripts.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import (
    DOMAIN,
    MAX_IMAGE_URL_LENGTH,
    MAX_MIGRATION_MESSAGE_LENGTH,
    MAX_MIGRATION_TITLE_LENGTH,
    MAX_NAVIGATE_TO_LENGTH,
    MIGRATE_SOURCE_AUTOMATION,
)
from .validation import (
    MAX_CATEGORY_NAME_LENGTH,
    sanitize_for_storage,
    validate_navigate_to,
)

_LOGGER = logging.getLogger(__name__)

# Services that indicate a ticker.notify call
_TICKER_SERVICES = {f"{DOMAIN}.notify", f"{DOMAIN}/notify"}


def _is_ticker_call(finding: dict[str, Any]) -> bool:
    """Check whether a scanner finding is a ticker.notify call."""
    service = finding.get("service", "")
    return service in _TICKER_SERVICES


# =============================================================================
# Scan: list all ticker.notify calls
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/automations/scan",
    }
)
@websocket_api.async_response
async def ws_automations_scan(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Scan automations and scripts for ticker.notify calls."""
    from ..migrate import async_scan_for_notifications

    try:
        all_findings = await async_scan_for_notifications(hass, services=[DOMAIN])
        ticker_findings = [f for f in all_findings if _is_ticker_call(f)]
        _LOGGER.debug(
            "Automations scan: %d ticker.notify calls found (of %d total)",
            len(ticker_findings),
            len(all_findings),
        )
        connection.send_result(msg["id"], {"findings": ticker_findings})
    except HomeAssistantError as err:
        _LOGGER.error("Automations scan failed: %s", err)
        connection.send_error(msg["id"], "scan_failed", str(err))
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Automations scan failed unexpectedly: %s", err)
        connection.send_error(msg["id"], "scan_failed", str(err))


# =============================================================================
# Update: modify a single ticker.notify call in-place
# =============================================================================

@websocket_api.websocket_command(
    {
        vol.Required("type"): "ticker/automations/update",
        vol.Required("finding"): vol.Schema(
            {
                vol.Required("source_type"): str,
                vol.Required("source_id"): str,
                vol.Required("source_file"): str,
                vol.Required("action_path"): str,
                vol.Required("action_index"): int,
                vol.Required("service"): str,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Required("category"): str,
        vol.Required("title"): str,
        vol.Required("message"): str,
        vol.Optional("data"): dict,
        vol.Optional("navigate_to"): vol.Any(
            None, vol.All(str, vol.Length(min=1, max=MAX_NAVIGATE_TO_LENGTH))
        ),
    }
)
@websocket_api.async_response
async def ws_automations_update(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a ticker.notify call in its source automation or script."""
    finding = msg["finding"]

    # Validate the finding looks like a ticker call
    if not _is_ticker_call(finding):
        connection.send_error(
            msg["id"],
            "not_ticker_call",
            "Finding is not a ticker.notify service call",
        )
        return

    # Validate source_type
    source_type = finding.get("source_type")
    if source_type not in (MIGRATE_SOURCE_AUTOMATION, "script"):
        connection.send_error(
            msg["id"],
            "invalid_finding",
            f"Invalid or missing source_type: {source_type!r}",
        )
        return

    # Sanitize inputs
    category = sanitize_for_storage(msg["category"], MAX_CATEGORY_NAME_LENGTH)
    if not category:
        connection.send_error(msg["id"], "invalid_category", "Category is required")
        return

    title = sanitize_for_storage(msg["title"], MAX_MIGRATION_TITLE_LENGTH) or ""
    message = sanitize_for_storage(msg["message"], MAX_MIGRATION_MESSAGE_LENGTH) or ""

    # Build the replacement action dict.
    # Use a sentinel to distinguish "navigate_to absent" from "navigate_to: null".
    _NAV_ABSENT = object()
    nav_value = msg.get("navigate_to", _NAV_ABSENT)
    # BUG-100: enforce relative HA path on any explicitly provided value.
    if nav_value is not _NAV_ABSENT:
        is_valid, error = validate_navigate_to(nav_value)
        if not is_valid:
            connection.send_error(msg["id"], "invalid_navigate_to", error)
            return
    new_action = _build_updated_action(
        finding, category, title, message, msg.get("data"), nav_value
    )

    # Apply to source file
    try:
        from ..migrate.converter import apply_to_automation, apply_to_script

        if source_type == MIGRATE_SOURCE_AUTOMATION:
            await apply_to_automation(hass, finding, new_action)
        else:
            await apply_to_script(hass, finding, new_action)

        _LOGGER.info(
            "Updated ticker.notify in %s (category: %s)",
            finding.get("source_id", "unknown"),
            category,
        )
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Automations update failed: %s", err)
        connection.send_error(msg["id"], "update_failed", str(err))


def _build_updated_action(
    finding: dict[str, Any],
    category: str,
    title: str,
    message: str,
    extra_data: dict[str, Any] | None,
    navigate_to: Any = None,
) -> dict[str, Any]:
    """Build a replacement action dict for an updated ticker.notify call.

    Preserves the action alias if one exists. Merges the image field
    from extra_data while keeping any other existing data keys intact.

    Args:
        finding: The original scanner finding.
        category: New category name.
        title: New title.
        message: New message.
        extra_data: Optional dict with keys like 'image' from the frontend.
        navigate_to: Tap-to-navigate URL. A non-string sentinel means the
            key was absent (preserve old value). None or empty string means
            clear. A non-empty string sets the value after sanitization.

    Returns:
        Complete action dict ready to write back.
    """
    service_data: dict[str, Any] = {
        "category": category,
        "title": title,
        "message": message,
    }

    # Preserve existing data sub-keys that the UI does not expose
    old_data = finding.get("service_data", {}).get("data", {})
    if isinstance(old_data, dict):
        merged_data = dict(old_data)
    else:
        merged_data = {}

    # Apply frontend-provided data
    if extra_data and isinstance(extra_data, dict):
        # Image lives under data.image
        image = extra_data.get("image")
        if image and isinstance(image, str):
            sanitized = sanitize_for_storage(image, MAX_IMAGE_URL_LENGTH)
            if sanitized:
                merged_data["image"] = sanitized
            else:
                merged_data.pop("image", None)
        elif "image" in extra_data and not image:
            merged_data.pop("image", None)

        # Actions is a top-level service_data key
        actions = extra_data.get("actions")
        if actions and isinstance(actions, str) and actions in (
            "category_default", "none"
        ):
            service_data["actions"] = actions

        # Critical is a top-level service_data key
        critical = extra_data.get("critical")
        if critical is True:
            service_data["critical"] = True
        elif critical is False:
            service_data["critical"] = False

        # Expiration is a top-level service_data key (hours, 1-48)
        expiration = extra_data.get("expiration")
        if isinstance(expiration, int) and 1 <= expiration <= 48:
            service_data["expiration"] = expiration

    # navigate_to: top-level service_data key, handled outside extra_data.
    # When navigate_to is a string (including ""), the key was explicitly sent.
    # None also means explicitly sent (voluptuous passes null as None).
    # A non-string sentinel means the key was absent — preserve old value.
    if isinstance(navigate_to, str) or navigate_to is None:
        if isinstance(navigate_to, str) and navigate_to:
            sanitized_nav = sanitize_for_storage(navigate_to, MAX_NAVIGATE_TO_LENGTH)
            if sanitized_nav:
                service_data["navigate_to"] = sanitized_nav
            else:
                # Sanitization emptied it — clear
                service_data.pop("navigate_to", None)
        else:
            # Explicitly None or empty string — clear navigate_to
            service_data.pop("navigate_to", None)
    else:
        # Sentinel / absent — preserve old navigate_to if it existed
        old_nav = finding.get("service_data", {}).get("navigate_to")
        if old_nav:
            service_data["navigate_to"] = old_nav

    if merged_data:
        service_data["data"] = merged_data

    new_action: dict[str, Any] = {
        "service": f"{DOMAIN}.notify",
        "data": service_data,
    }

    # Preserve alias if present
    if finding.get("action_alias"):
        new_action["alias"] = finding["action_alias"]

    return new_action
