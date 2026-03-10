# ticker

Smart notification management for Home Assistant.

Ticker replaces scattered `notify.mobile_app_*` calls with a single `ticker.notify` service. Your automations declare what happened, and Ticker routes notifications to the right people based on their subscription preferences and location.

## Installation

### HACS

1. Open HACS, go to Integrations
2. Three dots menu → Custom repositories
3. Add this repository URL, select Integration
4. Search for "Ticker" and install
5. Restart Home Assistant
6. Settings → Devices & Services → Add Integration → Ticker

### Manual

1. Copy the `ticker` folder into `custom_components/`
2. Restart Home Assistant
3. Settings → Devices & Services → Add Integration → Ticker

## Usage

Once installed, Ticker adds two sidebar panels: an admin panel for managing categories and users, and a user panel where individuals manage their own subscriptions.

### Service call

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Camera: Front Door"
```

You can pass through additional data to the underlying notify service:

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Camera: Front Door"
  data:
    image: /local/snapshots/front_door.jpg
```

Queued notifications expire after 48 hours by default. You can override this per call:

```yaml
service: ticker.notify
data:
  category: deliveries
  title: "Package Arriving"
  message: "Driver is 5 minutes away"
  expiration: 1
```

### Subscription modes

**Always** — Delivered immediately regardless of location. This is the default.

**Never** — Silently skipped. Useful for opting out of categories that aren't relevant to you.

**Conditional** — Delivery depends on rules you define. Rules use AND logic — all must be met for immediate delivery. Three rule types are available:

- **Zone** — Deliver while in a specific zone, queue until arrival, or both.
- **Time** — Deliver during a time window (e.g., 09:00–17:00). Supports day-of-week filtering and overnight spans.
- **Entity state** — Deliver when a Home Assistant entity is in a specific state (e.g., `binary_sensor.tv_power` is `off`).

Each rule has independent "deliver when met" and "queue until met" toggles. If no valid rules are configured, falls back to Always.

### How routing works

Ticker automatically discovers notification services linked to each person entity. When `ticker.notify` is called, it checks each person's subscription for that category and either sends immediately, queues for later, or skips — depending on their mode and location.

Queued notifications are bundled and delivered as a summary when the person arrives at the configured zone.

## Admin panel

Only visible to users in the "Administrator" group. Manage categories, view users and their linked notify services, set subscriptions, inspect the notification queue, view logs, and run the migration wizard to convert existing automations.

### Category defaults

Admins can set a default subscription mode and conditions per category. When a user has no explicit subscription for a category, the category default is used. For example, setting the "Security" category default to Conditional with a zone rule means all users start with that configuration pre-populated. Users can freely change their subscription afterwards — the default is just a starting point.

## User panel

View and change your own subscription preferences per category, and manage your personal notification queue.

## Migration

The admin panel includes a migration wizard that scans your automations and scripts for existing `notify.*` and `persistent_notification.*` calls. It walks you through each one, letting you convert to `ticker.notify` with a category of your choice.

## Dashboard sensors

Ticker creates sensor entities for each category, exposing the last 10 notifications as attributes. Use these to display notification feeds on your HA dashboards.

Each sensor:
- **State**: Count of notifications (0-10)
- **Attributes**: `notifications` (list), `category_id`, `category_name`, `last_triggered`
- **Entity ID**: `sensor.ticker_<category_id>`

### Markdown card example

```yaml
type: markdown
title: "Security Notifications"
content: >
  {% set notifs = state_attr('sensor.ticker_security', 'notifications') %}
  {% if notifs %}
  {% for n in notifs | reverse %}
  **{{ n.header }}** — {{ n.timestamp | as_timestamp | timestamp_custom('%H:%M') }}
  {{ n.body }}
  _Delivered: {{ n.delivered | join(', ') }}_
  {% if n.queued %}_Queued: {{ n.queued | join(', ') }}_{% endif %}
  ---
  {% endfor %}
  {% else %}
  No recent notifications.
  {% endif %}
```

**Note:** Sensor data is in-memory only and clears on HA restart. For full history, use the Ticker panel.

## Uninstalling

Update any automations using `ticker.notify` before removing. Then delete the integration from Settings → Devices & Services. Removing Ticker deletes all its data — categories, subscriptions, queue, and logs.

## License

GPL-3.0

## Support Ticker

If Ticker is useful to you, consider sponsoring development via GitHub Sponsors. It helps keep the project active and growing.
Join our Discord server to find out more and get support: https://discord.gg/NCcG4GpP
