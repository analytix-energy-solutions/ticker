"""Regression tests for BUG-103 / GitHub #29.

Migration wizard previously triple-nested the inner `data:` block
when converting mobile_app notifications, producing
``data.data.data.image`` instead of ``data.data.image``. At runtime
``ticker.notify`` reads ``data.image`` one level under the call so
the picture silently disappeared.

Each test below pins down one shape of the contract that
``async_convert_notification`` must hold after the fix:

1.  Android image is unwrapped (not double-wrapped).
2.  iOS attachment dict survives at the right depth.
3.  Jinja templates pass through verbatim.
4.  ``/local/...`` paths pass through verbatim.
5.  No inner ``data:`` block → no ``data`` key on output.
6.  Other mobile_app data keys (tag, channel, color) survive.
7.  Top-level ``target:`` is silently dropped.
8.  ``yaml.dump`` round-trips with ``data.image`` (not ``data.data.image``).
9.  Dropped-keys debug log fires with source id when ``target:`` is dropped.
10. Malformed inner ``data:`` (string / list) is silently ignored.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import yaml

from custom_components.ticker.migrate.converter import async_convert_notification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(service_data: dict) -> dict:
    """Build a scanner-shaped finding dict with the given service_data."""
    return {
        "source_type": "automation",
        "source_id": "automation.test_notify",
        "source_file": "config/automations.yaml",
        "action_path": "[0]",
        "action_index": 0,
        "service_data": service_data,
        "action_alias": None,
    }


async def _convert(service_data: dict) -> dict:
    """Run the converter and return the new_action dict."""
    finding = _make_finding(service_data)
    result = await async_convert_notification(
        hass=MagicMock(),
        finding=finding,
        category_id="alerts",
        category_name="Alerts",
        apply_directly=False,
    )
    assert result["success"] is True
    return result


# ---------------------------------------------------------------------------
# 1. Android image unwrapped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_android_image_unwrapped():
    """Nested data.image must end up at data.data.image, not data.data.data.image."""
    service_data = {
        "title": "Doorbell",
        "message": "Someone rang the doorbell",
        "data": {
            "image": "/local/doorbell_snapshot.jpg",
        },
    }
    result = await _convert(service_data)
    new_action = result["new_action"]

    # The outer wrapper is data: { category, title, message, data: {...} }
    assert new_action["data"]["title"] == "Doorbell"
    assert new_action["data"]["data"] == {"image": "/local/doorbell_snapshot.jpg"}

    # The triple-nested shape must NOT appear.
    inner = new_action["data"]["data"]
    assert "data" not in inner, (
        f"Expected data.data.image, got triple-nested: {new_action['data']}"
    )
    assert inner["image"] == "/local/doorbell_snapshot.jpg"


# ---------------------------------------------------------------------------
# 2. iOS attachment unwrapped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ios_attachment_unwrapped():
    """iOS-style data.attachment dict must survive at data.data.attachment."""
    attachment = {
        "url": "https://example.com/snap.jpg",
        "content-type": "jpeg",
        "hide-thumbnail": False,
    }
    service_data = {
        "title": "Camera",
        "message": "Motion detected",
        "data": {
            "attachment": attachment,
        },
    }
    result = await _convert(service_data)
    new_action = result["new_action"]

    inner = new_action["data"]["data"]
    assert inner == {"attachment": attachment}
    assert inner["attachment"]["url"] == "https://example.com/snap.jpg"
    # No accidental extra wrapping
    assert "data" not in inner


# ---------------------------------------------------------------------------
# 3. Image with template preserved verbatim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_image_with_template():
    """Jinja template strings must pass through unmolested."""
    template = '{{ states("sensor.snapshot") }}'
    service_data = {
        "title": "Snapshot",
        "message": "Latest snapshot",
        "data": {
            "image": template,
        },
    }
    result = await _convert(service_data)
    inner = result["new_action"]["data"]["data"]
    assert inner["image"] == template


# ---------------------------------------------------------------------------
# 4. Local path preserved exactly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_image_local_path_preserved():
    """Exact /local/... string must round-trip."""
    path = "/local/cameras/front_door/latest.jpg"
    service_data = {
        "title": "Front door",
        "message": "Motion",
        "data": {
            "image": path,
        },
    }
    result = await _convert(service_data)
    assert result["new_action"]["data"]["data"]["image"] == path


# ---------------------------------------------------------------------------
# 5. No image, no data block → no data key on output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_image_no_data_block():
    """When the source has no inner data block, output must not have one either."""
    service_data = {
        "title": "Plain",
        "message": "No image",
    }
    result = await _convert(service_data)
    out_data = result["new_action"]["data"]
    # The outer 'data' dict (category/title/message wrapper) exists, but the
    # inner 'data' key (mobile_app payload extras) should be absent.
    assert "data" not in out_data, (
        f"Expected no inner data block, got: {out_data}"
    )
    assert out_data["title"] == "Plain"
    assert out_data["message"] == "No image"


# ---------------------------------------------------------------------------
# 6. Other data keys preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_other_data_keys_preserved():
    """tag, channel, color and similar mobile_app fields must survive."""
    service_data = {
        "title": "Alert",
        "message": "Sensor triggered",
        "data": {
            "tag": "sensor-1",
            "channel": "alarms",
            "color": "#ff0000",
            "image": "/local/sensor.jpg",
        },
    }
    result = await _convert(service_data)
    inner = result["new_action"]["data"]["data"]
    assert inner["tag"] == "sensor-1"
    assert inner["channel"] == "alarms"
    assert inner["color"] == "#ff0000"
    assert inner["image"] == "/local/sensor.jpg"
    # Still single-nested, not triple
    assert "data" not in inner


# ---------------------------------------------------------------------------
# 7. Top-level target: dropped silently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_level_target_dropped():
    """Top-level target: has no schema mapping in ticker.notify and must be dropped."""
    service_data = {
        "title": "Targeted",
        "message": "Goes to phone",
        "target": "mobile_app_phone",
        "data": {
            "image": "/local/foo.jpg",
        },
    }
    result = await _convert(service_data)
    new_action = result["new_action"]

    # target must not appear anywhere in the output action
    assert "target" not in new_action
    assert "target" not in new_action["data"]
    assert "target" not in new_action["data"].get("data", {})

    # Image still survives at the correct depth
    assert new_action["data"]["data"]["image"] == "/local/foo.jpg"


# ---------------------------------------------------------------------------
# 8. yaml.dump round-trips with data.image (not data.data.image)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_yaml_output_shape():
    """The serialized YAML must round-trip to the correct nesting depth."""
    service_data = {
        "title": "Round trip",
        "message": "Check the YAML",
        "data": {
            "image": "/local/check.jpg",
        },
    }
    result = await _convert(service_data)

    yaml_str = result["yaml"]
    reparsed = yaml.safe_load(yaml_str)

    # Expected shape:
    # service: ticker.notify
    # data:
    #   category: Alerts
    #   title: ...
    #   message: ...
    #   data:
    #     image: /local/check.jpg
    assert reparsed["service"] == "ticker.notify"
    assert reparsed["data"]["category"] == "Alerts"
    assert reparsed["data"]["data"]["image"] == "/local/check.jpg"

    # Triple-nested shape must NOT appear in the YAML.
    assert "data" not in reparsed["data"]["data"], (
        f"YAML still triple-nested:\n{yaml_str}"
    )


# ---------------------------------------------------------------------------
# 9. Dropped-keys debug log fires with source id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dropped_keys_debug_log(caplog):
    """When top-level keys (e.g. target:) are dropped, a debug log must
    fire that names the source automation and the sorted dropped keys.

    This locks down the diagnostic contract — operators relying on the log
    to audit migrations would silently lose visibility if it regressed.
    """
    service_data = {
        "title": "Targeted",
        "message": "Goes to phone",
        "target": "mobile_app_phone",
        "data": {
            "image": "/local/foo.jpg",
        },
    }
    finding = _make_finding(service_data)
    finding["source_id"] = "automation.front_door_alert"

    # The converter logs at DEBUG via the module-scoped _LOGGER.
    with caplog.at_level(logging.DEBUG, logger="custom_components.ticker.migrate.converter"):
        result = await async_convert_notification(
            hass=MagicMock(),
            finding=finding,
            category_id="alerts",
            category_name="Alerts",
            apply_directly=False,
        )

    assert result["success"] is True

    # Find the dropped-keys debug record.
    dropped_records = [
        r for r in caplog.records
        if "Migrator dropped non-data top-level keys" in r.getMessage()
    ]
    assert dropped_records, (
        f"Expected dropped-keys debug log, got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )

    msg = dropped_records[0].getMessage()
    # Source automation id must appear so operators can correlate.
    assert "automation.front_door_alert" in msg
    # The dropped key must appear (sorted list rendering — single key here).
    assert "target" in msg


# ---------------------------------------------------------------------------
# 10. Malformed inner data: silently no-ops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_data",
    [
        "this is a string, not a dict",
        ["a", "list", "of", "strings"],
        42,
    ],
    ids=["string", "list", "int"],
)
async def test_malformed_inner_data_silently_ignored(malformed_data):
    """The defensive ``isinstance(inner_data, dict)`` branch must mean
    that a non-dict ``data:`` value never lands on the output.

    A malformed source automation (hand-written, partial YAML, etc.)
    must not crash the migrator and must not produce an inner data
    block that would later break ``ticker.notify``.
    """
    service_data = {
        "title": "Bad shape",
        "message": "Inner data is not a dict",
        "data": malformed_data,
    }
    result = await _convert(service_data)
    new_action = result["new_action"]

    # Outer wrapper still well-formed.
    assert new_action["service"].endswith(".notify")
    assert new_action["data"]["title"] == "Bad shape"
    assert new_action["data"]["message"] == "Inner data is not a dict"

    # Crucially: no inner data block on the output, regardless of the
    # malformed source value type.
    assert "data" not in new_action["data"], (
        f"Malformed inner data leaked through: {new_action['data']}"
    )
