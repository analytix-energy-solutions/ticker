# ticker

Smart notification management for Home Assistant.

Ticker replaces scattered `notify.mobile_app_*` calls with a single `ticker.notify` service. Your automations declare what happened, and Ticker routes notifications to the right people based on their subscription preferences, location, time of day, and device state.

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

## Quick start

Once installed, Ticker adds two sidebar panels: an admin panel for managing categories and users, and a user panel for subscriptions, queue, and notification history.

Create a category in the admin panel (e.g., "Security"), then replace your existing notify calls:

```yaml
# Before — one call per person, per device
- service: notify.mobile_app_johns_phone
  data:
    title: "Motion Detected"
    message: "Front door camera"
- service: notify.mobile_app_janes_phone
  data:
    title: "Motion Detected"
    message: "Front door camera"

# After — one call, Ticker handles routing
- service: ticker.notify
  data:
    category: security
    title: "Motion Detected"
    message: "Front door camera"
```

Each person controls how they receive each category — always, never, or conditionally based on zone, time, or entity state. The admin panel includes a migration wizard that scans your existing automations and helps convert them.

For the full feature guide, see [USER_GUIDE.md](custom_components/ticker/USER_GUIDE.md).

## Key features

- **Single service call** replaces all individual `notify.mobile_app_*` calls
- **Three subscription modes** — Always, Never, and Conditional with zone, time, and entity state rules
- **Smart queuing** — notifications queue when conditions aren't met and deliver automatically when they are
- **Notification actions** — configure action buttons per category (script, snooze, dismiss) with full lifecycle tracking *(v1.3.0)*
- **Per-user snooze** — suppress a category's notifications temporarily without touching any automation *(v1.3.0)*
- **Inline images in history** — camera snapshots and notification images displayed directly in the History tab *(v1.3.0)*
- **Device routing** — global device preference plus per-category overrides
- **Notification history** — grouped by notification call, with deep-link from phone notifications
- **Dashboard sensors** — `sensor.ticker_<category>` entities for Lovelace integration *(v1.2.0)*
- **Migration wizard** — scan and convert existing automations
- **Self-healing delivery** — failed deliveries retry automatically before falling back

## AI Disclosure

This integration is being developed with AI assistance. 

## Version history

### v1.3.0 (current)

- **Notification Actions & Workflows** — configure action buttons per category (script, snooze, dismiss). Ticker listens for button taps and routes them automatically — no second automation required.
- **Per-user snooze** — tapping a snooze button suppresses that category for the configured duration for that person only, without touching any automation.
- **Inline images in History** — notifications with a `data.image` field now show the image inline in the user History tab.
- Action taken recorded in admin logs and user history.
- Bug fixes: stray HTML entities in migration wizard output, disabled users counted as subscribers, improved Companion App notify service discovery.

### v1.2.1

- Hotfix for mobile_app Companion App notify service discovery — services were not found on fresh HA installs because legacy `notify.mobile_app_*` services are not registered in the entity registry.

### v1.2.0

- Advanced conditional rules: time windows and entity state conditions in addition to zones.
- Category sensor entities (`sensor.ticker_<category_id>`) for dashboard integration.
- Internal refactoring: store, websocket, and arrival handling split into smaller modules, all files under 500 lines.

### v1.1.0

- Notification grouping in History tab — entries from the same `ticker.notify` call grouped into a single card with device tags.
- History badge count reflects grouped notifications.

### v1.0.0

First public release with complete notification management: category routing, three subscription modes with advanced conditions, smart queuing with bundled delivery, self-healing retries, per-user device routing, notification history with phone deep-links, auto-discovery, admin and user panels, and migration wizard.

## Uninstalling

Update any automations using `ticker.notify` before removing. Then delete the integration from Settings → Devices & Services. Removing Ticker deletes all its data — categories, subscriptions, queue, and logs.

## License

GPL-3.0

## Support Ticker

If Ticker is useful to you, consider sponsoring development via GitHub Sponsors. It helps keep the project active and growing.
Join our Discord server to find out more and get support: https://discord.gg/NCcG4GpP
