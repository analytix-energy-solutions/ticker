"""Tests for BUG-099: sensor expose_content gate.

When ``expose_content=False``, the sensor entry's header and body
fields are blanked so dashboards don't leak notification text. The
notification count and last_triggered still update so observers can
see activity. Default expose_content=True preserves content for
existing callers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.ticker.sensor import TickerCategorySensor


def _make_sensor() -> TickerCategorySensor:
    entry = MagicMock()
    entry.entry_id = "entry1"
    return TickerCategorySensor(
        entry=entry,
        category_id="cat1",
        category_name="Alerts",
        icon="mdi:bell",
    )


class TestBug099ExposeContent:

    def test_default_preserves_content(self):
        sensor = _make_sensor()
        with patch.object(sensor, "async_write_ha_state", create=True):
            sensor.async_add_notification(
                header="Secret Title",
                body="Secret Body",
                delivered=["notify.phone"],
                queued=[],
                dropped=[],
                priority="normal",
                timestamp="2026-04-10T10:00:00+00:00",
            )

        assert sensor.native_value == 1
        attrs = sensor._attr_extra_state_attributes
        entry = attrs["notifications"][0]
        assert entry["header"] == "Secret Title"
        assert entry["body"] == "Secret Body"
        assert attrs["last_triggered"] == "2026-04-10T10:00:00+00:00"

    def test_expose_content_false_blanks_header_and_body(self):
        sensor = _make_sensor()
        with patch.object(sensor, "async_write_ha_state", create=True):
            sensor.async_add_notification(
                header="Secret Title",
                body="Secret Body",
                delivered=["notify.phone"],
                queued=[],
                dropped=[],
                priority="normal",
                timestamp="2026-04-10T10:00:00+00:00",
                expose_content=False,
            )

        # Count still updates
        assert sensor.native_value == 1
        attrs = sensor._attr_extra_state_attributes
        entry = attrs["notifications"][0]
        # Header and body blanked
        assert entry["header"] == ""
        assert entry["body"] == ""
        # Other fields preserved
        assert entry["delivered"] == ["notify.phone"]
        assert entry["timestamp"] == "2026-04-10T10:00:00+00:00"
        # last_triggered still updates
        assert attrs["last_triggered"] == "2026-04-10T10:00:00+00:00"

    def test_expose_content_false_does_not_break_trimming(self):
        """The 10-entry cap still applies with expose_content=False."""
        sensor = _make_sensor()
        with patch.object(sensor, "async_write_ha_state", create=True):
            for i in range(15):
                sensor.async_add_notification(
                    header=f"H{i}",
                    body=f"B{i}",
                    delivered=[],
                    queued=[],
                    dropped=[],
                    priority="normal",
                    timestamp=f"2026-04-10T10:{i:02d}:00+00:00",
                    expose_content=False,
                )

        # Max is MAX_SENSOR_NOTIFICATIONS (10)
        assert sensor.native_value == 10
        for entry in sensor._attr_extra_state_attributes["notifications"]:
            assert entry["header"] == ""
            assert entry["body"] == ""
