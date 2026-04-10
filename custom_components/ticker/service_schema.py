"""Service schema and description builders for Ticker integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CATEGORY,
    ATTR_TITLE,
    ATTR_MESSAGE,
    ATTR_EXPIRATION,
    ATTR_DATA,
    ATTR_ACTIONS,
    ATTR_CRITICAL,
    ATTR_NAVIGATE_TO,
    DEFAULT_EXPIRATION_HOURS,
    MAX_EXPIRATION_HOURS,
    MAX_NAVIGATE_TO_LENGTH,
    CATEGORY_DEFAULT_NAME,
)
from .websocket.validation import validate_navigate_to_vol

if TYPE_CHECKING:
    from .store import TickerStore


def _build_service_schema() -> vol.Schema:
    """Build basic service schema (categories validated at runtime)."""
    return vol.Schema(
        {
            # F-27: accept single category ID/name or list for fan-out.
            # The UI selector stays single-dropdown; multi only via YAML.
            vol.Required(ATTR_CATEGORY): vol.Any(cv.string, [cv.string]),
            vol.Required(ATTR_TITLE): cv.string,
            vol.Required(ATTR_MESSAGE): cv.string,
            vol.Optional(ATTR_EXPIRATION, default=DEFAULT_EXPIRATION_HOURS): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_EXPIRATION_HOURS)
            ),
            vol.Optional(ATTR_DATA, default={}): dict,
            vol.Optional(ATTR_ACTIONS): vol.In(["category_default", "none"]),
            vol.Optional(ATTR_CRITICAL): bool,
            # BUG-100: enforce relative HA path; blocks javascript:/http(s)://
            vol.Optional(ATTR_NAVIGATE_TO): vol.All(
                cv.string,
                vol.Length(max=MAX_NAVIGATE_TO_LENGTH),
                validate_navigate_to_vol,
            ),
        }
    )


def _build_service_description(
    store: "TickerStore | None", hass: HomeAssistant | None = None
) -> dict[str, Any]:
    """Build service description with current categories for UI."""
    if store:
        categories = store.get_categories()
        category_options = [cat["name"] for cat in categories.values()]
    else:
        category_options = [CATEGORY_DEFAULT_NAME]

    # Build navigate_to options
    _nav_opts: list[dict[str, str]] = [
        {"value": "/ticker#history", "label": "Notification History"},
        {"value": "/ticker-admin", "label": "Ticker Admin"},
    ]
    # Add category-level navigate_to defaults
    if store:
        categories = store.get_categories()
        for c in categories.values():
            if c.get("navigate_to"):
                _nav_opts.append(
                    {"value": c["navigate_to"], "label": f"{c['name']}: {c['navigate_to']}"}
                )

    # Add HA sidebar panels dynamically
    _excl = {"ticker", "ticker-admin", "config", "developer-tools"}
    if hass:
        for p in hass.data.get("frontend_panels", {}).values():
            title = getattr(p, "sidebar_title", None)
            url = getattr(p, "frontend_url_path", None)
            if title and url and url not in _excl:
                _nav_opts.append({"value": f"/{url}", "label": title})

    # Static system paths
    for path, label in [
        ("/lovelace", "Overview (Default Dashboard)"),
        ("/config/devices", "Devices"),
        ("/config/integrations", "Integrations"),
        ("/config/automation/dashboard", "Automations"),
        ("/config/script", "Scripts"),
        ("/config/scene", "Scenes"),
        ("/config/helpers", "Helpers"),
        ("/config/areas", "Areas"),
    ]:
        _nav_opts.append({"value": path, "label": label})

    return {
        "name": "Send notification",
        "description": "Send a notification through Ticker to subscribed users",
        "fields": {
            ATTR_CATEGORY: {
                "name": "Category",
                "description": "The notification category",
                "required": True,
                "example": CATEGORY_DEFAULT_NAME,
                "selector": {
                    "select": {
                        "options": category_options,
                        "mode": "dropdown",
                    }
                },
            },
            ATTR_TITLE: {
                "name": "Title",
                "description": "The notification title",
                "required": True,
                "example": "Motion Detected",
                "selector": {"text": {}},
            },
            ATTR_MESSAGE: {
                "name": "Message",
                "description": "The notification message body",
                "required": True,
                "example": "Motion detected at front door",
                "selector": {"text": {"multiline": True}},
            },
            ATTR_EXPIRATION: {
                "name": "Expiration",
                "description": "Hours until notification expires (for queued notifications)",
                "required": False,
                "default": DEFAULT_EXPIRATION_HOURS,
                "example": 24,
                "selector": {
                    "number": {
                        "min": 1,
                        "max": MAX_EXPIRATION_HOURS,
                        "unit_of_measurement": "hours",
                    }
                },
            },
            ATTR_DATA: {
                "name": "Data",
                "description": "Additional data to pass to the underlying notify service",
                "required": False,
                "example": '{"image": "/local/snapshot.jpg"}',
                "selector": {"object": {}},
            },
            ATTR_ACTIONS: {
                "name": "Actions",
                "description": "Action button behavior: category_default (use category action set) or none (suppress)",
                "required": False,
                "default": "category_default",
                "selector": {
                    "select": {
                        "options": ["category_default", "none"],
                        "mode": "dropdown",
                    }
                },
            },
            ATTR_CRITICAL: {
                "name": "Critical",
                "description": (
                    "Send as critical notification (bypasses Do Not "
                    "Disturb and silent mode). If omitted, inherits "
                    "from category setting."
                ),
                "required": False,
                "selector": {"boolean": {}},
            },
            ATTR_NAVIGATE_TO: {
                "name": "Navigate to",
                "description": (
                    "URL or path to open when the notification is tapped. "
                    "Overrides category default. Example: /lovelace/cameras"
                ),
                "required": False,
                "selector": {
                    "select": {
                        "options": _nav_opts,
                        "custom_value": True,
                        "mode": "dropdown",
                    }
                },
            },
        },
    }
