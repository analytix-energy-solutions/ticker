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

**Conditional** — Delivery depends on zone-based rules. You can configure per zone whether to deliver while present, queue until arrival, or both. If no conditions are configured, falls back to Always.

### How routing works

Ticker automatically discovers notification services linked to each person entity. When `ticker.notify` is called, it checks each person's subscription for that category and either sends immediately, queues for later, or skips — depending on their mode and location.

Queued notifications are bundled and delivered as a summary when the person arrives at the configured zone.

## Admin panel

Only visible to users in the "Administrator" group. Manage categories, view users and their linked notify services, set subscriptions, inspect the notification queue, view logs, and run the migration wizard to convert existing automations.

## User panel

View and change your own subscription preferences per category, and manage your personal notification queue.

## Migration

The admin panel includes a migration wizard that scans your automations and scripts for existing `notify.*` and `persistent_notification.*` calls. It walks you through each one, letting you convert to `ticker.notify` with a category of your choice.

## Uninstalling

Update any automations using `ticker.notify` before removing. Then delete the integration from Settings → Devices & Services. Removing Ticker deletes all its data — categories, subscriptions, queue, and logs.

## License

GPL-3.0

## Support Ticker

If Ticker is useful to you, consider sponsoring development via GitHub Sponsors. It helps keep the project active and growing.