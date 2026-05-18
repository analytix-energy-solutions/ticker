"""F-35.1 chime helper WebSocket commands.

Extracted from ``recipient_helpers.py`` (v1.7.0b21) to keep that file
under the 500-line limit after BUG-110 b21 (Issue 3) added the
cast-target snapshot/restore wrapper around ``ws_test_chime``.

Currently owns:

* ``ws_get_bundled_chimes`` — returns absolute URLs for the in-tree
  bundled chime assets so the picker chips on the recipient and
  category dialogs can write a real ``media_content_id`` value
  through the standard delivery path.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import BUNDLED_CHIMES, STATIC_CHIMES_PATH

_LOGGER = logging.getLogger(__name__)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "ticker/get_bundled_chimes"}
)
@websocket_api.async_response
async def ws_get_bundled_chimes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """F-35.1: Return absolute URLs for the in-tree bundled chime assets.

    The picker on the recipient and category dialogs writes the returned
    ``url`` verbatim into ``chime_media_content_id`` so bundled chimes
    flow through the same delivery path as user-supplied media_content_id
    values.

    URL is composed using HA's INTERNAL URL by preference (b7 fix). The
    bundled WAVs are served locally from /config/custom_components/ticker
    /static/chimes via Ticker's static-path registration, so the consumer
    (a media_player on the same LAN as HA — Sonos / Cast / HA Voice /
    ESPHome speaker) reaches them fastest over the internal hostname.

    Earlier (b6 and prior) this used ``prefer_external=True``, which on
    Nabu-Cloud-connected installs wrote a ``*.ui.nabu.casa`` URL into
    ``chime_media_content_id``. HA Voice and other LAN devices then
    fetched the chime over the internet (cold TLS handshake +
    Nabu→HA→Nabu round trip), regularly taking longer than ``tts.cloud_say``
    itself, so the chime arrived at the device AFTER the TTS audio.
    Switching to internal URL keeps the fetch on-LAN and gives the chime
    a clean head start.

    Existing recipients/categories with stored ``ui.nabu.casa`` chime URLs
    keep working but stay slow — re-pick the chip to refresh.

    Returns ``[]`` (no chips rendered) when no HA URL is resolvable.
    """
    # Resolve HA's externally-reachable base URL. We import lazily so that
    # absence of the helper in older HA versions only impacts F-35.1 and
    # not the rest of the integration.
    try:
        from homeassistant.helpers.network import (
            NoURLAvailableError,
            get_url,
        )
    except ImportError:  # pragma: no cover — defensive guard
        _LOGGER.warning(
            "homeassistant.helpers.network.get_url unavailable; "
            "bundled chimes disabled"
        )
        connection.send_result(msg["id"], {"chimes": []})
        return

    try:
        base_url = get_url(hass, prefer_external=False, allow_internal=True)
    except NoURLAvailableError as err:
        _LOGGER.warning(
            "No HA URL resolvable for bundled chimes: %s", err
        )
        connection.send_result(msg["id"], {"chimes": []})
        return
    except Exception as err:  # noqa: BLE001 — defensive against HA shape drift
        _LOGGER.warning(
            "Unexpected error resolving HA URL for bundled chimes: %s", err
        )
        connection.send_result(msg["id"], {"chimes": []})
        return

    if not base_url:
        connection.send_result(msg["id"], {"chimes": []})
        return

    base = base_url.rstrip("/")
    chimes = [
        {
            "id": entry["id"],
            "label": entry["label"],
            "url": f"{base}{STATIC_CHIMES_PATH}/{entry['filename']}",
        }
        for entry in BUNDLED_CHIMES
    ]
    connection.send_result(msg["id"], {"chimes": chimes})
