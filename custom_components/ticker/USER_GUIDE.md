# Ticker User Guide

Complete reference for the Ticker notification management integration for Home Assistant.

For installation and a quick overview, see the [README](../../README.md).

---

## Table of contents

1. [Service call](#service-call)
2. [Subscription modes](#subscription-modes)
3. [Conditional rules](#conditional-rules)
4. [How routing works](#how-routing-works)
5. [Device routing](#device-routing)
6. [Notification actions](#notification-actions)
7. [Notification history](#notification-history)
8. [Self-healing delivery](#self-healing-delivery)
9. [Admin panel](#admin-panel)
10. [User panel](#user-panel)
11. [Migration wizard](#migration-wizard)
12. [Dashboard sensors](#dashboard-sensors)
13. [Uninstalling](#uninstalling)
14. [Version history](#version-history)

---

## Service call

The core of Ticker is the `ticker.notify` service. Call it from any automation or script:

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Camera: Front Door"
```

The `category` field accepts either the category display name (e.g., "Security Alerts") or its generated ID (e.g., `security_alerts`).

### Passing data through

Any additional data you include is forwarded to the underlying mobile app notify service. This means all standard HA companion app notification properties work — images, sounds, channels, and more:

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Camera: Front Door"
  data:
    image: /local/snapshots/front_door.jpg
    channel: security
    importance: high
```

### Queue expiration

Queued notifications expire after 48 hours by default. You can override this per call (in hours, maximum 48):

```yaml
service: ticker.notify
data:
  category: deliveries
  title: "Package Arriving"
  message: "Driver is 5 minutes away"
  expiration: 1
```

### Controlling action button injection *(v1.3.0)*

If a category has action buttons configured, Ticker injects them automatically into every outgoing notification. You can control this per call with the optional `actions` parameter:

```yaml
# Suppress action button injection for this call
service: ticker.notify
data:
  category: security
  title: "System test"
  message: "No buttons wanted"
  actions: none
```

Omitting the `actions` parameter (the default) uses the category's configured action set if one exists.

---

## Subscription modes

Each person has a subscription mode per category that controls how they receive notifications.

**Always** — Delivered immediately regardless of conditions. This is the default for all categories unless an admin sets a different category default.

**Never** — Silently skipped. The notification is logged as "skipped" but never sent. Useful for opting out of categories that aren't relevant to you.

**Conditional** — Delivery depends on rules you define. See the next section for details.

### Category defaults

Admins can set a default subscription mode and conditions per category. When a user has no explicit subscription for a category, the category default applies. For example, setting the "Security" category default to Conditional with a zone rule means all users start with that configuration. Users can freely change their subscription afterwards — the default is just a starting point.

### Admin vs. user subscriptions

Admins control *who* receives notifications per category. Users control *when* they receive them. When an admin disables a category for a user, that category is hidden from the user panel entirely. Subscriptions set by an admin are tracked separately from user-set subscriptions.

---

## Conditional rules

When a subscription is set to Conditional, you define one or more rules that determine when notifications are delivered or queued.

All rules use **AND logic** — every rule must be satisfied for the overall condition to be met. The condition set has two toggles that apply to the rules as a whole:

- **Deliver when all conditions met** — Send the notification immediately when every rule is satisfied.
- **Queue until all conditions met** — Hold the notification and release it automatically when every rule becomes satisfied.

Both toggles can be enabled at the same time. If no valid rules are configured, the subscription falls back to Always.

### Rule types

**Zone** — Evaluates whether the person is in a specific zone.

```
Rule: Zone = Home
```

**Time** — Evaluates whether the current time is within a window. Supports day-of-week filtering and overnight spans (e.g., 22:00–06:00).

```
Rule: Time = 08:00–22:00, Mon–Fri
```

**Entity state** — Evaluates whether a Home Assistant entity is in a specific state.

```
Rule: binary_sensor.tv_power = off
```

### Condition-level toggles

The "deliver when met" and "queue until met" toggles apply to the entire set of rules, not to individual rules. For example:

```
Rules:
  1. Zone = Home
  2. Entity state: media_player.tv = off

☑ Deliver when all conditions met
☑ Queue until all conditions met
```

With both toggles enabled, this delivers notifications when the person is home AND the TV is off. If either condition isn't met, notifications are queued and released automatically when both are satisfied simultaneously.

With only "deliver when met" enabled, notifications are delivered when conditions are met but silently skipped when they aren't — no queuing.

With only "queue until met" enabled, notifications are never delivered immediately but are queued and released when conditions are met.

### Active condition listeners

Ticker doesn't just check conditions at send time — it actively monitors for changes. When a person enters a zone, a time window opens, or an entity changes state, Ticker re-evaluates all queued notifications and releases the ones whose conditions are now met. This means queued notifications are delivered as soon as possible, not just on the next `ticker.notify` call.

---

## How routing works

When `ticker.notify` is called, Ticker processes each person entity in Home Assistant:

1. **Enabled check** — Disabled users are skipped entirely (not logged as skipped, fully excluded).
2. **Snooze check** *(v1.3.0)* — If the person has an active snooze for this category, the notification is logged as "snoozed" and skipped.
3. **Mode check** — The person's subscription mode for the category is evaluated.
4. **Delivery decision** — Based on the mode:
   - **Always**: Send immediately to the person's target devices.
   - **Never**: Log as skipped, do nothing.
   - **Conditional**: Evaluate all rules. If all are met and "deliver when met" is enabled, send immediately. If "queue until met" is enabled and not all rules are met, queue the notification. Otherwise, skip.
5. **Action injection** *(v1.3.0)* — If the category has action buttons configured and the automation has not supplied its own `data.actions`, Ticker injects the action buttons automatically.
6. **Device selection** — The person's global device preference and any per-category overrides determine which notify services receive the notification (see Device routing below).
7. **Sensor update** — The category sensor entity is updated with the delivery results.

Ticker discovers notify services automatically by tracing person entities → device trackers → mobile app devices → notify services. Discovery results are cached for 5 minutes and refreshed on integration reload.

---

## Device routing

*Added in v1.0.0*

Users can control which of their devices receive notifications at two levels.

### Global device preference

In the user panel, each person can choose between "Send to all devices" (default) and "Selected devices only" with a specific device list. This applies to all categories as a baseline.

If a person selects specific devices but all selected devices later become unavailable (e.g., removed from HA), Ticker falls back to sending to all devices rather than silently failing.

### Per-category device override

For any category, a person can optionally enable "Also send to additional devices" and select extra devices. This is **additive** — the selected override devices are unioned with the global preference.

For example, if your global preference is "phone only" and you add your tablet as an override for Security, then security alerts go to both phone and tablet. All other categories go to phone only.

Per-category overrides are only available when the subscription mode is Always or Conditional (not Never), and only when the person has two or more discovered devices.

### Friendly device names

Device names are displayed using friendly names from the HA device registry (e.g., "John's iPhone" instead of `notify.mobile_app_johns_iphone`).

---

## Notification actions

*Added in v1.3.0*

Ticker solves the "two-automation problem" in Home Assistant. Normally, sending actionable notifications and handling the user's response requires two disconnected automations with manually-matched string identifiers. Ticker handles both sides centrally.

### How it works

Admins configure action buttons per category in the admin panel. When Ticker sends a notification for that category, the buttons are automatically included. When a user taps a button, Ticker receives the response and handles it — no second automation required.

### Action button types

**Script** — Calls a Home Assistant script when tapped. The admin selects the script from a dropdown. Any logic that would normally go in a second automation goes into that script instead.

**Snooze** — Suppresses notifications for this category for a configured duration (15 min, 30 min, 1 h, 2 h, or 4 h). The snooze applies only to the person who tapped it and only for the snoozed category — other household members continue receiving notifications as normal. The snooze expires automatically.

**Dismiss** — Acknowledges the notification. No action is taken, but the tap is logged.

### Configuring action buttons

In the admin panel, open any category and expand the "Action Buttons" section. Up to 3 buttons can be configured per category. Each button has a title (what the user sees on the button) and a type with type-specific settings.

### Action tracking

Every button tap is recorded. The admin Logs tab shows which action was taken and by whom. The user History tab shows "You tapped: X" on the relevant history entry.

### Automation override

If your automation already sets `data.actions` on the `ticker.notify` call, those buttons take precedence over the category's configured action set. You can also pass `actions: none` to suppress injection entirely for that call.

### Snooze behaviour

While snoozed, notifications for that category are logged with a "snoozed" outcome rather than being sent. Queued notifications that are released during a snooze period are also suppressed. Once the snooze expires, all future notifications for that category are delivered normally.

---

## Notification history

*Added in v1.0.0, grouping added in v1.1.0, inline images added in v1.3.0*

The user panel includes a History tab showing all notifications that were successfully sent to you. Entries are grouped by date with timestamps.

### Notification grouping *(v1.1.0)*

Each `ticker.notify` call generates a unique `notification_id`. In the History tab, all log entries sharing the same `notification_id` are grouped into a single card. This means a notification sent to three devices appears as one entry showing all three devices and their delivery outcomes, rather than three separate entries.

The History tab badge count reflects grouped notifications, not raw log entries.

### Inline images *(v1.3.0)*

Notifications with a `data.image` field (HTTP/HTTPS URLs or `/local/` paths) display the image directly in the history entry. This makes it easy to do a quick visual check when reviewing multiple camera or snapshot notifications without opening each one on your phone.

Images that fail to load are silently hidden. `media-source://` URIs show a placeholder icon.

### Deep-link from phone notifications

Every notification Ticker sends includes `url` and `clickAction` fields pointing to `/ticker#history`. When you tap a notification on your phone, it opens directly to the History tab in the Ticker user panel.

This is especially useful on iOS where quickly tapping a notification group can dismiss them before you read them. Ticker preserves the full history so nothing is lost.

These fields are only injected if your automation hasn't already set custom `url` or `clickAction` values in the `data` dict.

### Admin log vs. user history

The admin panel Logs tab shows an ungrouped audit log of every individual delivery attempt across all users — including sent, queued, skipped, snoozed, and failed outcomes. The user panel History tab shows only "sent" outcomes for the current user, grouped by notification call.

---

## Self-healing delivery

*Added in v1.0.0*

When Ticker delivers queued notifications as a bundled summary (e.g., on zone arrival), it's possible that all notify services fail — for example, if a phone is temporarily offline or a service is unavailable.

Rather than losing the notifications, Ticker re-queues them with an incremented retry counter. It retries up to 3 times. After the maximum retries, entries are discarded and a warning is written to the Home Assistant system log.

Additionally, if a conditional subscription references a zone that has been deleted from Home Assistant, Ticker detects this at notification time, automatically resets the subscription to "Always" mode, and delivers the notification immediately. This prevents silently broken subscriptions from accumulating.

---

## Admin panel

Only visible to users in the "Administrator" group. The admin panel has five tabs.

### Categories tab

Create, edit, and delete notification categories. Each category has a name (from which an ID is auto-generated), an icon, an optional color, and optional default subscription settings.

Each category also has an **Action Buttons** section where admins configure up to 3 action buttons (Script, Snooze, or Dismiss) that are automatically included in notifications for that category.

The "General" category is created automatically and cannot be deleted.

When you add or remove categories, the `ticker.notify` service schema in Developer Tools updates dynamically to reflect the current category list.

### Users tab

View all discovered person entities and their linked notify services (displayed with friendly names). Admins can enable or disable users and set subscriptions on their behalf. A "Test" button sends a test notification to verify delivery.

### Queue tab

Inspect all currently queued notifications across all users, grouped by person. Shows the title, message, category, queue time, and expiration time for each entry.

### Logs tab

View the notification log with outcome badges (sent, queued, skipped, snoozed, failed) and summary statistics. Logs are retained for 7 days with a maximum of 500 entries. The admin log is an ungrouped audit trail showing every individual delivery attempt. Entries where a user tapped an action button show a pill with the action title and person name.

### Migrate tab

Run the migration wizard (see Migration wizard section below).

---

## User panel

Available to all users. The user panel has three tabs.

### Subscriptions tab

View and change your subscription preferences per category. For each category, choose Always, Never, or Conditional and configure rules. Categories disabled by an admin are hidden entirely.

This tab also shows your global device preference ("Send to all devices" or "Selected devices only") and lets you configure per-category device overrides.

### Queue tab

View your personal notification queue — notifications waiting for conditions to be met before delivery. Shows the category, title, message, and expiration time for each entry.

### History tab

Browse your notification history, grouped by date. Entries from the same `ticker.notify` call are displayed as a single card showing all target devices. Notifications with images show the image inline. Entries where you tapped an action button show which action you took.

---

## Migration wizard

The admin panel includes a migration wizard that scans your automations and scripts for existing `notify.*` and `persistent_notification.*` service calls. It supports both the `action:` (legacy) and `actions:` (current) YAML keys.

The wizard walks you through each found notification call and offers two conversion paths:

- **Apply Directly** — For UI-created automations. Ticker modifies the automation in place, replacing the notify call with a `ticker.notify` call using a category you select or create inline.
- **Copy YAML** — For YAML-based automations. Ticker generates the replacement YAML for you to paste into your configuration.

The wizard also detects duplicate notification calls across automations, showing a side-by-side comparison so you can decide which to keep.

---

## Dashboard sensors

*Added in v1.2.0*

Ticker creates a sensor entity for each category, making notification data available for Lovelace dashboard cards.

Each sensor:
- **Entity ID**: `sensor.ticker_<category_id>` (e.g., `sensor.ticker_security`)
- **State**: Count of notifications currently stored (0–10)
- **Attributes**: `notifications` (list of the last 10 notifications), `category_id`, `category_name`, `last_triggered`

Sensors are created and removed dynamically as categories are added or deleted.

Each notification in the list includes: `header`, `body`, `delivered` (list of service IDs), `queued` (list of descriptions), `dropped` (list of descriptions), `priority`, and `timestamp`.

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

**Note:** Sensor data is in-memory only and clears on HA restart. For persistent history, use the Ticker panel.

---

## Uninstalling

Update any automations using `ticker.notify` before removing. Then delete the integration from Settings → Devices & Services.

Removing Ticker deletes all its persistent data: categories, subscriptions, user preferences, queue, and logs. This cleanup happens automatically via `async_remove_entry`.

---

## Version history

### v1.3.0 (current)

**Added:**
- **Notification Actions & Workflows** — configure up to 3 action buttons per category (Script, Snooze, Dismiss). Ticker listens for button taps and routes them centrally — no second automation required.
- **Per-user snooze** — a Snooze action button suppresses notifications for that person and category for a configurable duration (15 min–4 h). Applies to that person only; other household members are unaffected. Expires automatically.
- **Inline images in History** — notifications with `data.image` (HTTP/HTTPS or `/local/` paths) display the image inline in the user History tab.
- **Action tracking** — admin Logs tab shows action taken pills; user History tab shows "You tapped: X".
- `actions` parameter on `ticker.notify` — pass `actions: none` to suppress action button injection for a specific call.
- Snoozed outcome in admin logs.

**Fixed:**
- **BUG-046**: Migration wizard produced stray HTML entities in Jinja2 templates.
- **BUG-048**: Disabled users incorrectly counted as subscribers in the admin Categories tab.
- **B-1 / BUG-043**: Rewrote Companion App notify service discovery — device-registry-based lookup eliminates cross-linking when device names are substrings of each other.

### v1.2.1

**Fixed:**
- **BUG-043**: Hotfix for mobile_app Companion App notify service discovery — legacy `notify.mobile_app_*` services were not found on fresh HA installs because they are not registered as notify entities in the entity registry.

### v1.2.0

**Added:**
- **Advanced conditional rules** — time windows (with day-of-week filtering and overnight span support) and entity state conditions, in addition to zone rules. All rule types use AND logic.
- **Category sensor entities** — `sensor.ticker_<category_id>` entities exposing the last 10 notifications as structured attributes for Lovelace dashboard integration.

**Fixed:**
- **BUG-042**: Sensor entity attributes not visible in HA state due to deprecated property pattern.
- **BUG-041**: Integration failed to load on startup due to incorrect argument type in condition listeners.
- **BUG-040**: Frontend panels re-rendered entire DOM on every state change, causing scroll position loss.

**Changed:**
- Store refactored into `store/` package with mixins; all Python files under 500 lines.

### v1.1.0

**Added:**
- Notification grouping in user panel History tab — entries from the same `ticker.notify` call are grouped into a single card showing all target devices and delivery outcomes.
- `notification_id` field in log entries to correlate deliveries from the same service call.
- Device tags shown per history entry in user panel.

**Changed:**
- History tab badge count reflects grouped notifications instead of raw log entries.

**Fixed:**
- **BUG-027**: Notify services displayed as `[object Object]` instead of friendly names on the Users tab.

### v1.0.0

First public release. Complete notification management including:

- Core `ticker.notify` service with category-based routing.
- Three subscription modes: Always, Never, and Conditional.
- Conditional mode with zone, time, and entity state rules using AND logic. Condition-level "deliver when met" and "queue until met" toggles.
- Automatic queuing with 48-hour expiration and bundled delivery when conditions are met.
- Active condition listeners for zone arrival, time window changes, and entity state changes.
- Self-healing delivery: retry up to 3 times on bundled notification failure, auto-reset broken subscriptions.
- Per-user global device preference (all devices vs. selected) with per-category additive overrides.
- Notification history in user panel with date grouping and deep-link from phone notifications.
- Auto-discovery of person entities and linked notify services with friendly names.
- Admin panel with five tabs: Categories, Users, Queue, Logs, and Migrate.
- User panel with three tabs: Subscriptions, Queue, and History.
- Migration wizard with "Apply Directly" and "Copy YAML" workflows and duplicate detection.
- Category defaults for pre-populating new user subscriptions.
- Admin vs. user role separation with admin-disabled categories hidden from users.
- Storage cleanup on integration removal.
- GPL-3.0 license.
