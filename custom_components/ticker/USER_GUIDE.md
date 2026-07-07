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
6. [Device recipients](#device-recipients)
7. [Notification actions](#notification-actions)
8. [Notification history](#notification-history)
9. [Self-healing delivery](#self-healing-delivery)
10. [Admin panel](#admin-panel)
11. [Setting up Ticker for household members](#setting-up-ticker-for-household-members)
12. [User panel](#user-panel)
13. [Migration wizard](#migration-wizard)
14. [Dashboard sensors](#dashboard-sensors)
15. [Uninstalling](#uninstalling)
16. [Version history](#version-history)

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

### Targeting multiple categories *(v1.6.0)*

The `category` field also accepts a list of category IDs, so a single call can fan out to multiple categories at once:

```yaml
service: ticker.notify
data:
  category:
    - security
    - info
  title: "Motion Detected"
  message: "Front door camera"
```

Each listed category is processed independently: Ticker generates a fresh `notification_id` per category, applies that category's conditions and critical flag, fans out to the right subscribers, and writes a separate history entry per category. Duplicates in the list are ignored. If one category in the list does not exist, Ticker logs a warning and continues with the valid ones; if none of the categories resolve, the call fails with a validation error.

The admin Automations tab renders multi-category automations as read-only entries with a "N categories" badge. To edit them, modify the automation YAML directly.

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

Queued notifications expire after 48 hours by default. You can override this per call (in hours, minimum 1, maximum 48):

```yaml
service: ticker.notify
data:
  category: deliveries
  title: "Package Arriving"
  message: "Driver is 5 minutes away"
  expiration: 1
```

### Critical notifications *(v1.4.0)*

To send a critical alert that bypasses silent mode and DND on the recipient's device, add `critical: true` to the service call:

```yaml
service: ticker.notify
data:
  category: security
  title: "Alarm Triggered"
  message: "Motion detected at front door"
  critical: true
```

Ticker translates this automatically per platform:
- **iOS** — injects `push: { sound: { name: "default", critical: 1, volume: 1.0 } }`, which bypasses silent mode and DND.
- **Android** — sets `priority: high`, `ttl: 0`, and routes to the `ticker_critical` channel for high-priority FCM delivery.

You do not need to handle platform differences in your automation. The same call works for all devices.

Admins can also enable critical notifications at the category level from the category editor's General sub-tab. When a category has critical enabled, every notification sent to that category is treated as critical automatically — you do not need to include `critical: true` in the service call at all. If you do include `critical: true` or `critical: false` explicitly, that per-call value takes precedence over the category setting. This lets you send a non-critical test notification to an otherwise-critical category by passing `critical: false`, or force critical behavior for a specific call in a category that does not have it enabled by default.

### Navigation target *(v1.5.0)*

By default, tapping a notification from Ticker opens the Ticker history view (`/ticker#history`). You can override this per call with the `navigate_to` parameter:

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Front door camera"
  navigate_to: /lovelace/cameras
```

The value must be a relative HA path beginning with `/` (e.g., `/lovelace/0`, `/lovelace/cameras`). Absolute URLs (`https://…`), `javascript:` URIs, and protocol-relative `//host/path` values are rejected by the validator — see the Security note below.

Ticker injects the correct field per platform automatically — you do not need to set `clickAction` or `url` yourself:
- **Android** — injects `clickAction` into the notification data.
- **iOS** — injects `url` into the notification data.

If the per-call `navigate_to` is omitted, Ticker falls back to the category-level default. Admins can configure a category default in the category editor's General sub-tab using the Navigation Picker. If neither is set, notifications navigate to `/ticker#history`.

If your automation already sets `clickAction` or `url` explicitly in the `data` block, those values are preserved and `navigate_to` does not overwrite them.

> **Note:** Per-call `navigate_to` is not preserved when a notification is queued. Queued notifications use the category default or the global default when they are eventually delivered.

**Security (v1.6.0):** `navigate_to` is validated as a relative HA path. Values must begin with `/` and cannot contain `://` or `//` protocol-relative prefixes or control characters. Absolute URLs (`https://…`), `javascript:` URIs, and similar unsafe values are rejected. This applies at category create/update time, on the admin Automations tab, and at service-call time.

### Auto-clear triggers *(v1.6.0)*

Persistent notifications (the kind that the user cannot swipe away) normally require a second automation to call `ticker.clear_notification` when the triggering condition ends. The `clear_when` parameter lets you declare the clear trigger inline with the notification, so a single `ticker.notify` call is enough.

**Entity-state trigger** — dismisses the notification when a binary sensor returns to its off state:

```yaml
service: ticker.notify
data:
  category: alerts
  title: "Washer finished"
  message: "Unload when you have a moment"
  data:
    tag: washer_done
  clear_when:
    entity_id: binary_sensor.washer_running
    state: "off"
```

**Event trigger** — dismisses the notification when a custom event fires:

```yaml
service: ticker.notify
data:
  category: alerts
  title: "Door left open"
  message: "Back door still open"
  data:
    tag: back_door_open
  clear_when:
    event_type: back_door_closed
```

When the trigger fires, Ticker calls `ticker.clear_notification` automatically against the tag of the delivered notification. Listeners are one-shot and are torn down after the first fire.

> **Prerequisite:** auto-clear only takes effect when the target category has a tag mode (Category or Title) configured in the Smart sub-tab. Without a tag mode the underlying mobile_app notify service has no tag to target — Ticker registers the listener but the clear call is silently skipped (a warning is logged). Configure the category's tag mode before relying on `clear_when`.

> **State trigger fires on transition only:** the entity-state trigger registers a listener for state changes that match the target state. If the entity is **already** in the target state when the notification is delivered (e.g. the washer is already `off`), the listener will never fire and the notification stays until manually dismissed. Use a different trigger entity (or pre-check the entity state in the automation) when the clear condition could already be true at delivery time.

> **Important limitation:** auto-clear listeners do not survive a Home Assistant restart. If HA restarts between delivery and trigger fire, the listener is lost and the notification stays on the device until the user dismisses it manually or another call clears the tag. For notifications that must survive restarts, drive the clear from an HA automation triggered by the same condition.

Auto-clear is YAML-only in v1.6.0 — the HA service UI does not render a structured editor for this field.

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

The `actions` parameter accepts exactly two values: `category_default` (the default — use the category's configured action set if any) or `none` (suppress action button injection entirely). Omitting the parameter is equivalent to passing `category_default`.

If you want to inject your own custom buttons on a specific call, place them in the underlying notify service's payload via the `data` block (Ticker passes `data` through to the underlying mobile_app notify service):

```yaml
service: ticker.notify
data:
  category: alerts
  title: "Custom buttons"
  message: "Pick one"
  actions: none           # suppress Ticker's category buttons
  data:
    actions:              # consumed by the mobile_app notify service
      - action: SNOOZE_1H
        title: Snooze 1h
      - action: DISMISS
        title: Dismiss
```

### Per-call action set override *(v1.5.0)*

Action sets are now managed as a shared library. You can override which action set is used for a specific call with the `action_set_id` parameter:

```yaml
service: ticker.notify
data:
  category: security
  title: "Motion Detected"
  message: "Front door camera"
  action_set_id: confirm_alert
```

This overrides the category's default action set for this call only. If the ID does not match a known action set, a warning is logged and the category default (if any) is used. Omitting `action_set_id` uses the category's configured action set.

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

Rules support **AND and OR logic** — you control per group whether all rules must be satisfied (AND) or any one is sufficient (OR). The condition set has two toggles that apply to the top-level result:

- **Deliver when conditions met** — Send the notification immediately when the condition tree evaluates as true (respecting your AND/OR grouping and NOT inversions).
- **Queue until conditions met** — Hold the notification and release it automatically when the condition tree becomes true.

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

**Duration** — Evaluates how long an entity has held a given state. Leave the entity field blank to default to the subscriber's own person entity. Two comparisons are available:

- **Within N minutes** — the entity transitioned into the target state at most N minutes ago (e.g. "just arrived home", "just left").
- **For at least N minutes** — the entity has held the target state continuously for at least N minutes (e.g. "staying home", "staying away").

```
Rule: (this person) = home, within 10m       # just arrived
Rule: (this person) = not_home, for ≥ 15m    # been away a while
```

When "Queue until conditions met" is enabled, a "For at least" duration rule that is not yet met is automatically re-checked the moment its threshold is crossed, even with no underlying state change: no need to also add a Time rule to catch it. This re-check relies on the queue mechanism, so it does not apply to a "Deliver when conditions met"-only subscription with no queueing.

### Condition-level toggles

The "deliver when met" and "queue until met" toggles apply to the entire set of rules, not to individual rules. For example:

```
Rules (AND):
  1. Zone = Home
  2. Entity state: media_player.tv = off

☑ Deliver when conditions met
☑ Queue until conditions met
```

With both toggles enabled, this delivers notifications when the condition tree is true (here, both conditions because they share an AND group). When the tree evaluates false, notifications are queued and released automatically when the tree becomes true.

With only "deliver when conditions met" enabled, notifications are delivered when the tree is true but silently skipped when it isn't — no queuing.

With only "queue until conditions met" enabled, notifications are never delivered immediately but are queued and released when the tree becomes true.

### AND/OR condition grouping *(v1.5.0)*

The conditions builder supports mixed AND/OR logic. Click the operator pill between any two conditions to toggle between AND and OR. You can also group adjacent conditions into a sub-group with its own operator — up to two nesting levels deep.

For example:

```
Group (AND)
  Zone = Home
  Group (OR)
    Time = 08:00–22:00
    Entity state: binary_sensor.tv = off
```

This delivers when the person is home AND either the time is within the window OR the TV is off.

Existing flat-rules conditions from earlier versions migrate automatically to the new format. No manual action is required.

### Active condition listeners

Ticker doesn't just check conditions at send time — it actively monitors for changes. When a person enters a zone, a time window opens, or an entity changes state, Ticker re-evaluates all queued notifications and releases the ones whose conditions are now met. This means queued notifications are delivered as soon as possible, not just on the next `ticker.notify` call.

---

## Smart notification management

*Added in v1.5.0*

Admins can configure smart notification behaviour per category from the Smart sub-tab in the category editor. Settings are injected automatically at delivery time — no changes to automations required.

### Auto-grouping

When a group key is configured, Ticker injects it into the notification payload so the OS groups related notifications together on the device. Useful for categories that fire frequently (e.g., motion alerts).

### Auto-tagging

Tag mode controls whether Ticker injects a tag into each notification:

- **None** — no tag injected (default).
- **Category** — tag is set to the category ID. Repeated notifications for the same category replace the previous one on the device.
- **Title** — tag is derived from the notification title. Notifications with the same title replace each other.

### Sticky and persistent flags

- **Sticky** — the notification stays in the device tray after the user taps it (Android only).
- **Persistent** — the notification cannot be dismissed by the user (Android only).

### Clearing notifications programmatically

The `ticker.clear_notification` service dismisses active tagged notifications from all subscriber devices for a given category:

```yaml
service: ticker.clear_notification
data:
  category: security
```

This only has effect when the category has a tag mode other than None configured.

---

## How routing works

When `ticker.notify` is called, Ticker processes each person entity in Home Assistant:

1. **Enabled check** — Disabled users are skipped entirely (not logged as skipped, fully excluded).
2. **Snooze check** *(v1.3.0)* — If the person has an active snooze for this category, the notification is logged as "snoozed" and skipped.
3. **Mode check** — The person's subscription mode for the category is evaluated.
4. **Delivery decision** — Based on the mode:
   - **Always**: Send immediately to the person's target devices.
   - **Never**: Log as skipped, do nothing.
   - **Conditional**: Evaluate the condition tree (AND/OR groups with optional NOT inversions). If the tree is true and "deliver when conditions met" is enabled, send immediately. If "queue until conditions met" is enabled and the tree is false, queue the notification. Otherwise, skip.
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

## Device recipients

*Added in v1.4.0*

Device recipients are notification targets that are not tied to a person entity — shared household devices like a living room TV, a hallway speaker, or a wall-mounted tablet. Admins configure them centrally in the Devices tab; they receive notifications from the same `ticker.notify` call as household members, with their own subscription modes and conditions.

### Device types

Each recipient has a device type that determines how Ticker delivers the notification.

**Push** — Ticker calls one or more notify services, the same way it does for person devices. The delivery format (rich or plain) is auto-detected from the service identifier and can be overridden by the admin. Use this for TVs with the `nfandroidtv` integration, persistent notifications, or any notify-based target.

**TTS** — Ticker calls `tts.speak` targeting a media player entity. Use this for speakers or voice assistants. The admin selects the media player and optionally a TTS service from dropdowns populated from live HA data.

### TTS delivery

For TTS devices, Ticker uses a 3-step priority system at delivery time:

1. **Announce mode** — If the media player supports `MEDIA_ANNOUNCE` (HA 2024.1+), Ticker uses announce mode and HA handles pause/resume automatically.
2. **Snapshot/restore** — If announce is not supported and `resume_after_tts` is enabled, Ticker snapshots the current playback state, plays the TTS, then restores playback afterwards.
3. **Plain** — If neither applies, Ticker calls `tts.speak` with no resume behaviour.

The `supports_announce` status is shown as a badge on the recipient card so admins can see at a glance which delivery path will be used.

### Pre-TTS chime

*Added in v1.7.0 (F-35)*

Each TTS recipient can be paired with a chime — a short audio clip that plays through the same media_player just before the spoken announcement. This gives listeners in another room a moment to orient before the message starts. The chime is configured as an HA `media_content_id` (the same picker HA uses for its media browser).

Where it is configured:

- **Recipient dialog** (admin > Devices) — sets the device default. Empty means no chime for this device.
- **Category dialog** (admin > Categories > General) — optionally overrides the device default. Empty falls back to the device default; empty at both levels = no chime.

Both dialogs include a Test Chime button that plays the chime through the chosen media_player without going through the queue, sending TTS, or producing a History entry.

The chime is fail-soft: if the media_player is offline, the asset is missing, or playback fails for any reason, the failure is logged as a warning and the TTS announcement still delivers normally — the History entry is still marked as Sent. TTS proceeds no more than 10 seconds after the chime starts playing on platforms that expose the chime in `media_content_id`; on platforms that never expose it (or the chime can't be detected within ~1.5 s), TTS proceeds after a fixed 3-second gap. Either way, a stuck or silent chime will never block the announcement indefinitely.

**Caveat — Alexa double-chime:** Some TTS engines (notably Amazon Alexa via the Alexa Media Player integration) play their own "earcon" tone before speech. If Ticker also plays a chime, the listener hears two tones in a row. Ticker does not auto-detect this — leave the chime field empty for Alexa-based recipients to avoid the double-chime.

#### Bundled default chimes

*Added in v1.7.0 (F-35.1)*

Ticker ships three CC0-licensed chime assets out of the box so the feature is functional without sourcing a third-party file:

- **Subtle ding** — single soft tone (~0.6s)
- **Alert tone** — two-tone descending alert (~1.3s)
- **Doorbell** — classic ding-dong (~1.8s)

Both the recipient and category dialogs render preset chips above the chime URL field. Clicking a chip writes the chime's absolute URL into the field — bundled chimes use the same delivery path as user-supplied `media_content_id` values, so playback behaviour is identical.

**Chromecast targets — pick the `(Chromecast)` variant.** Three additional bundled chimes — labelled `(Chromecast) Subtle ding`, `(Chromecast) Alert tone`, and `(Chromecast) Doorbell` — are identical to the originals but with 2.5 seconds of leading silence prepended. The Cast Default Media Receiver swallows the first 1–2 seconds when loading a new media context, which makes short chimes inaudible on a plain Chromecast target (see BUGS.md BUG-110). The `(Chromecast)` variants feed silence into that swallow window so the audible body of the chime survives. Pick the matching `(Chromecast)` variant from the preset chips on the recipient or category dialog when the target is a Chromecast / Google Cast speaker that lacks `MEDIA_ANNOUNCE` support; Ticker does not auto-detect this.

**Caveat — host changes stale the URL:** The stored URL is composed from HA's **internal URL** (e.g. `http://homeassistant.local:8123/ticker_static/chimes/subtle.wav`). If you later change the HA internal URL or move to a different hostname, the stored URL becomes stale and the chime stops playing. Re-pick the chip to refresh — Ticker recomposes the URL from the current HA internal URL each time the dialog opens.

If Ticker cannot resolve any HA URL (`get_url` returns nothing), the bundled chip row is hidden — you can still paste a chime URL or `media-source://` value manually.

#### Volume override

*Added in v1.7.0 (F-35.2)*

Both the recipient (Devices) dialog and the category (General sub-tab) dialog include a **Volume Override** slider just above the Pre-TTS Chime block. The slider sets the media_player's volume for the chime + TTS pair, then restores the previous level after TTS finishes playing.

- **Range**: 0–100 % on the slider, mapped to HA's standard 0.0–1.0 `volume_level` scale.
- **Default**: leave the slider on **Default** (button shows "Set", value reads "Default") to inherit the media_player's current volume — current behavior, no `volume_set` is called.
- **Recipient default**: applied to every category that does not specify its own override.
- **Category override**: when set, beats the device default for notifications in that category.
- **Test Chime**: previews at the current slider value. Snapshot/restore happens server-side, so testing does not leave your media at the test volume — provided the device exposes a `volume_level` attribute (i.e. is on or playing). On cold devices that don't report `volume_level`, the override is silently skipped (fail-soft) and the device's volume is not touched.

The override is applied via Home Assistant's standard `media_player.volume_set` service. After setting the level, Ticker briefly waits before issuing the next service call so the platform can apply the new volume — Sonos in particular needs ~200 ms to apply a new volume on the cached connector before `play_media` starts. On Chromecast targets the trailing settle is skipped because `play_media` triggers a context switch that supersedes it. The previous volume is restored after TTS finishes — for snapshot/restore and plain delivery this is after the entity exits the `playing` state; for announce mode (where the platform handles pause/resume) it is restored right after the TTS service call returns.

**Fail-soft**: if `volume_set` fails (offline player, unsupported attribute, etc.), Ticker logs a warning and proceeds with chime + TTS at the device's current volume — the announcement is never blocked by a volume problem.

**Push devices**: the slider is hidden on Push-type recipients. Push notifications use the mobile_app's own volume settings; Ticker does not touch them.

### Subscriptions and conditions

Device recipients support the same subscription modes as users — Always, Never, and Conditional with time and entity state rules. Zone rules are not available for recipients (they have no location state).

Recipients also support queuing: if conditions are not met at send time, the notification is held and released when conditions are satisfied, the same as for person subscriptions.

### Admin log

Recipient deliveries appear in the admin Logs tab alongside person deliveries, identified by the recipient's display name. They do not appear in any user's History tab.

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

### Search and filters *(v1.6.0)*

The History tab has a filter bar at the top with:

- **Search box** — live full-text search against the title, message, and image URL of every entry. Case-insensitive, updates as you type.
- **Category dropdown** — filter to a specific category. Populated dynamically from categories present in your history.
- **Date range** — two date pickers for a from/to window (inclusive, local time).

Filters compose with AND logic and run client-side, so there is no round-trip to the backend. When filters reduce the list to zero matches, an inline "No matches. Clear filters to see all." message appears while the filter bar stays visible so you can adjust. Filters reset when you switch away from the History tab or close the panel.

### Delete and clear *(v1.6.0)*

Each history entry has a small × button in the corner. Clicking it prompts for confirmation and then deletes the entire notification group (all device-level rows sharing that `notification_id`). Entries from older versions without a `notification_id` do not show a delete button.

A **Clear History** button at the top of the tab wipes your own history after confirmation. This is scoped to the current user — other users' history is untouched. Admins can delete individual rows from the admin Logs tab (see below).

### Expired notifications *(v1.6.0)*

If a queued notification expires before its conditions are met, it now appears in the History tab as a faded entry with a muted "expired" badge. Previously expired notifications disappeared silently. This is driven by a periodic sweep that runs every 15 minutes plus once at integration startup.

### Inline images *(v1.3.0)*

Notifications with a `data.image` field (HTTP/HTTPS URLs or `/local/` paths) display the image directly in the history entry. This makes it easy to do a quick visual check when reviewing multiple camera or snapshot notifications without opening each one on your phone.

Images that fail to load are silently hidden. `media-source://` URIs show a placeholder icon.

### Deep-link from phone notifications

Every **push** notification Ticker sends includes `url` and `clickAction` fields pointing to `/ticker#history` (or to the per-call or category `navigate_to` if set). When you tap a notification on your phone, it opens directly to the configured target. TTS and persistent notification deliveries do not receive these fields — there is no UI to tap.

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

Only visible to users in the "Administrator" group. The admin panel has eight tabs: Categories, Users, Queue, Logs, Devices, Action Sets, Automations, and Migrate.

### Categories tab

Create, edit, and delete notification categories. Each category has a name (from which an ID is auto-generated), an icon, an optional color, and optional default subscription settings. The General sub-tab also includes a **Critical notifications** toggle — when enabled, all notifications sent to this category are treated as critical by default (individual service calls can still override this with an explicit `critical` value). The General sub-tab also includes a **Navigation Picker** for setting a category-level default navigation target (see Navigation target above).

The General sub-tab also includes an **Android Channel** field *(v1.8.0)*. Enter an Android notification channel ID (e.g. `security_alerts`) to route this category's push notifications through a specific Android OS-level channel. This controls the sound, vibration, and Do-Not-Disturb behavior that the Android Companion App assigns to the notification. Leave blank to use the app's default channel. Critical notifications always use the `ticker_critical` channel regardless of this setting. This field has no effect on iOS devices or TTS/persistent recipients.

The Smart sub-tab configures per-category smart notification delivery: auto-grouping, tag mode, sticky, and persistent flags (see Smart notification management above).

Each category also has an **Action Buttons** section where admins configure the category's default action set reference from the Action Sets library.

The "General" category is created automatically and cannot be deleted.

When you add or remove categories, the `ticker.notify` service schema in Developer Tools updates dynamically to reflect the current category list.

### Users tab

View all discovered person entities and their linked notify services (displayed with friendly names). Admins can enable or disable users and set subscriptions on their behalf. A "Test" button sends a test notification to verify delivery.

### Queue tab

Inspect all currently queued notifications across all users, grouped by person. Shows the title, message, category, queue time, and expiration time for each entry.

### Logs tab

View the notification log with outcome badges (sent, queued, skipped, snoozed, failed, expired) and summary statistics. Logs are retained for 7 days with a maximum of 500 entries. The admin log is an ungrouped audit trail showing every individual delivery attempt. Entries where a user tapped an action button show a pill with the action title and person name.

**Click-to-filter *(v1.6.0):*** the stat counters at the top of the Logs tab are clickable. Clicking Sent, Queued, Skipped, Failed, Snoozed, or Expired filters the log list to show only entries with that outcome; the counter card highlights to indicate the active filter. Clicking Total clears the filter. Counters always display unfiltered totals so you can see what clicking them would restore. The filter is client-side only and resets when the admin panel closes.

**Per-row delete *(v1.6.0):*** each log row has a small × button in its header. Clicking it deletes that single entry after confirmation. The existing **Clear All** button remains and wipes the entire log (global, across all users).

**Expired badge *(v1.6.0):*** notifications that aged out of the queue before delivery now carry a muted "expired" badge and contribute to the new Expired stat counter.

### Devices tab *(v1.4.0)*

Create, edit, and delete device recipients — shared notification targets not tied to any person entity. Each device has a name, icon, enabled toggle, device type (Push or TTS), and one or more assigned notify services or a media player entity. Subscriptions and conditions per category are configured in the same accordion layout as the Users tab.

#### Linking a device to a user *(v1.8.0)*

For shared devices that should follow a specific household member's notification preferences — e.g. a hallway tablet that should match Mom's subscriptions — link the device to that person instead of mirroring every category by hand.

**When to use it:** a device that lives in or near one person's space and should fire only when that person's own subscription rules say it would. Pairs well with F-21 device-level conditions: link mirrors **subscriptions**, device-conditions still gate the device globally.

**How to enable:**

1. Open the admin **Devices** tab. Device foldouts open expanded by default so the link controls are visible without clicking.
2. At the top of the foldout, set **Link mode** to **Linked to user**.
3. Pick a person from the user dropdown. Selecting a user fires the link immediately; switching back to **Standalone** clears it.

**What gets mirrored:** the **per-category subscription set** — every category's mode (Always / Never / Conditional) and the conditions blob on conditional rows. When linked, the per-category rows on the device card render read-only with a "Mirroring &lt;name&gt; — edit in user panel" notice. Changes to the linked user's subscriptions in the user panel take effect immediately on the linked device's delivery.

**What stays device-local:** the device-level conditions tab (F-21) remains editable in the device dialog and continues to act as a global gate — if the device-conditions are not met, the notification is skipped regardless of the linked user's mode. Volume override, chime, notify services, navigation target, icon, name, and enabled toggle are also device-local and unaffected by the link.

**Edge cases:**

- **User mode = Never:** the device is skipped, even if the device's own conditions are met. Never wins.
- **User mode = Always + device-conditions unmet:** the device is skipped on the device-condition gate. Linking does not bypass F-21.
- **Linked person is renamed in HA (entity ID unchanged):** no effect — the link stores the entity ID.
- **Linked person entity is deleted from HA:** the device automatically applies an orphan fallback — the person's then-current subscriptions are copied into the device's own subscription rows (tagged `set_by=orphan_fallback` in the audit), the link is cleared, and the device reverts to Standalone with its last-known subscription set frozen on disk. Delivery is never silently broken.

The user panel never exposes the link — household members can't see or change which devices mirror them. The link is an admin-only configuration.

### Action Sets tab *(v1.5.0)*

Create, edit, and delete reusable action button sets from a central library. Each action set has a name, a slug ID, and up to 3 action buttons (Script, Snooze, or Dismiss). The "Used by" column shows which categories reference each set. Action sets that are referenced by one or more categories cannot be deleted until all references are removed.

Categories reference a library entry by ID. Editing a library entry immediately affects all categories that reference it.

### Automations tab *(v1.5.0)*

Scans all automations and scripts for `ticker.notify` calls and displays them in a filterable list. Filter by category or source type (automation vs. script). Click any result to expand an inline edit form for category, title, message, image, navigate_to, actions, critical flag, and expiration — no need to open the automation editor. YAML-backed sources are backed up before any change is written.

### Migrate tab

Run the migration wizard (see Migration wizard section below).

---

## Setting up Ticker for household members

*Added in v1.7.0 (F-38)*

Configuring Ticker for a non-technical household member normally requires them to log in to Home Assistant themselves and navigate to the user panel. The **View-as** feature lets an admin do this setup on their behalf without needing the other person's credentials.

### How to use it

1. Open the Ticker **user panel** while logged in as an admin.
2. A **"Viewing as"** dropdown appears in the top-right corner of the panel header. It is only visible to admins — other users do not see it.
3. Select a household member from the dropdown. The panel immediately re-renders showing that person's subscriptions, queue, and history.
4. A persistent banner — "Viewing as: [Name]" — stays visible at the top of the panel so you always know whose view you are in.
5. Make whatever changes are needed: update subscription modes, configure conditions, adjust device preferences. All changes are attributed to admin in the audit log.
6. Click **Stop viewing** in the banner to return to your own view.

### Notes

- The dropdown only lists people with a linked HA person entity and discovered notify services. Service accounts and users without a person entity do not appear.
- If your own HA account is not linked to a person entity, the panel shows a message pointing you to the dropdown — you can still assist other household members even without a personal entity.
- Impersonation state is in-memory only. If you reload the page or navigate away, the panel returns to your own view automatically.
- Any subscription changes made while in impersonation mode are written with `set_by=ADMIN` in the audit trail, identical to admin edits made directly via the admin Users tab.

---

## User panel

Available to all users. The user panel has three tabs.

### Subscriptions tab

View and change your subscription preferences per category. For each category, choose Always, Never, or Conditional and configure rules. Categories disabled by an admin are hidden entirely.

This tab also shows your global device preference ("Send to all devices" or "Selected devices only") and lets you configure per-category device overrides.

**Admin-managed devices** *(v1.8.0)* — If your administrator has linked one or more shared device recipients to your account (for example, a hallway tablet or shared speaker), those devices appear in the My Devices section below your own devices, labeled `(admin-managed)`. They are shown as locked, checked rows: they always receive your notifications when your subscription mode and conditions allow delivery, and the user panel cannot disable them. To change which devices are linked to you, ask your administrator to edit the device in the admin Devices tab.

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

> **Note:** "Copy YAML" uses the browser Clipboard API where available. In the HA Companion App or non-HTTPS environments the YAML is shown in a dialog instead — select all and copy from there.

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

### v1.7.0 (current)

**Added:**
- **View-as-User** — admins can operate the user panel on another household member's behalf using a new "Viewing as" dropdown in the panel header. See [Setting up Ticker for household members](#setting-up-ticker-for-household-members).
- **NOT operator for conditions** — toggle a NOT pill on any condition row or group to invert its result (e.g., "NOT in zone home" = person is away, "NOT 08:00–22:00" = overnight window). Works for all rule types.
- **Pre-TTS chime** — TTS recipients can be paired with a short audio chime that plays immediately before each TTS announcement. Set at the device level in the admin Devices tab with an optional per-category override. Three bundled CC0 chime presets ship out of the box (subtle/alert/doorbell), plus matching `(Chromecast)` variants with leading silence to survive the Cast Default Media Receiver swallow window.
- **Volume override** — a slider in the device and category dialogs sets the media_player volume for the chime+TTS pair and restores the previous level after TTS finishes. Leave on Default to inherit the device's current volume.
- **Entity-state value suggestions** — the state field in entity-state condition rules suggests valid values for the selected entity's domain (input_select options, climate/lock/cover/media_player/alarm enums). Free-text still accepted for custom values.

**Fixed:**
- **BUG-104** — `action_set_id` parameter on `ticker.notify` (documented since v1.5.0) was rejected at the service schema layer. Now correctly accepted and forwarded to the action-set resolver. Unknown IDs log a warning and fall back to the category default.

**Security:**
- Cross-user WebSocket data disclosure (BUG-108): WebSocket handlers accepting `person_id` now enforce admin-or-self gating. A non-admin caller can no longer read another user's subscriptions, queue, or logs by supplying a foreign person_id. Existing HA access control (valid session required) was always enforced; this closes the within-session cross-user read path.

### v1.6.0

**Added:**
- **Notification history search** — the user History tab has a new filter bar with full-text search, category dropdown, and a date-range picker. Filters compose with AND logic and run entirely client-side. An inline "No matches" state appears when filters reduce the list to zero while keeping the filter bar visible.
- **Log Filter by Status** — the admin Logs tab stat counters (Total, Sent, Queued, Skipped, Failed, Snoozed, Expired) are now clickable. Clicking filters the log list to that outcome; clicking Total clears the filter. Counters always show unfiltered totals.
- **Expired notification visibility** — queued notifications that expire before delivery are now logged with the new "expired" outcome and shown as faded entries in user History and admin Logs. A periodic sweep runs every 15 minutes.
- **Multi-category fan-out** — `ticker.notify` `category` field accepts either a single category ID (string) or a list. Each category in the list is processed independently with its own `notification_id`, conditions, critical flag, and log entry. Duplicates are de-duplicated; invalid category IDs in a list are logged as warnings and skipped.
- **Auto-clear triggers** — new `clear_when` parameter on `ticker.notify` takes either an entity-state trigger (`entity_id` + `state`) or an event trigger (`event_type`). When the trigger fires, Ticker automatically calls `ticker.clear_notification` against the delivered tag. Listeners do not survive HA restarts.
- **History management** — per-entry × delete buttons on the admin Logs tab and per-group × delete on the user History tab. A user-scoped "Clear History" button wipes the current user's history without affecting others.
- **Blueprint-friendly device registration** — Ticker now registers itself as a Home Assistant device (`entry_type=service`) under manufacturer "Analytix Energy Solutions" and model "Ticker Notification Router". It appears in device pickers for blueprints and the HA Devices list. Blueprints still call `notify.ticker`; device-action platform support is deferred to a later release.
- **Per-category `expose_in_sensor` flag** — a new category setting (default on) controls whether raw notification title and body are copied into the `sensor.ticker_<category>` extra attributes. Turn off for sensitive categories such as 2FA codes, medical reminders, or authentication flows.
- **navigate_to validation** — `navigate_to` values are now validated as relative HA paths. Absolute URLs (`https://`), `javascript:` URIs, `//`-protocol-relative paths, and strings containing control characters are rejected at category create/update, automations edit, and service-call time.
- **Condition tree leaf validation** — subscription and device-conditions validation now recursively checks leaf node contents (entity IDs, zone IDs, HH:MM time format, weekday integers). Invalid leaves are rejected at save time rather than surfacing as runtime errors later.
- **Condition listener refresh on subscription CRUD** — creating, updating, or deleting a conditional subscription now refreshes the global condition listener registry via a debounced callback, so new state/time rules start firing without requiring an HA restart.
- **Audit log `set_by` correctness** — subscription changes now correctly record `set_by=USER` when a non-admin edits another user's subscription (previously tagged as ADMIN regardless of caller role).

**Fixed:**
- Conditional subscriptions migrated to the F-2b tree format (v1.5.0) were silently delivering as Always because the notify handler only checked the legacy `rules` key, which the tree migration removes. Added a shared `has_any_conditions()` helper and wired both user and recipient notify paths through it. (BUG-084, BUG-085)
- Zone rules and arrival release compared the zone friendly name returned by HA against the zone object-id slug, which only matched by coincidence. Added a `resolve_zone_name()` helper that reads the friendly name from the HA state machine. Also removed a hard-coded `new_zone == "home"` literal in the non-conditional fallback. (BUG-087, BUG-088)
- Queue retries reset the notification's `expires_at` to 48 hours from the retry time instead of preserving the remaining lifetime from the original call. Already-expired entries are now skipped instead of re-queued. (BUG-089)
- Snooze action tap resolved to an arbitrary category when an action set was shared across multiple categories. Now resolves the originating category via the notification log. (BUG-090)
- Bundled arrival notifications did not pass `notification_id` into the log entry, breaking history correlation and F-30 auto-clear resolution for bundled deliveries. Added `notification_id` propagation through the queue and bundled delivery path. (BUG-091)
- `_check_device_ios` returned False on the first non-matching device config entry instead of continuing, so devices with multiple integrations could be mis-classified. (BUG-092)
- `_check_device_ios` and related iOS fallback logic — see above. Related: discovery name-matching fallback removed because it was cross-linking notify services when one person's name was a substring of another. (BUG-094)
- Zone arrival and condition re-evaluation could release queued notifications for disabled users. The `is_user_enabled` guard that was already in the arrival handler has been extended to the condition listener re-evaluation and the async queue release paths. (BUG-044 extension)
- Condition rules with `after: HH:MM` and `before: HH:MM` only tracked the opening edge. The closing edge is now also tracked so deliver-when-met windows correctly close. (BUG-096)
- `conditions={}` on `ticker/create_recipient` and `ticker/update_recipient` was rejected; empty dict is now normalized to `None`. Malformed conditions dicts with unknown keys are still rejected. (BUG-093)
- The Persistent toggle on the category Smart sub-tab did not stay on when clicked and reset the replacement dropdown as a side effect. The in-flight Smart sub-tab state is now buffered in `_pendingSmart[categoryId]` before re-render, matching the existing `_pendingDefaultConditions` pattern. (BUG-083, GitHub #25, reported by kurdt1994)
- `ticker.clear_notification` was defined but never registered as a service. It is now wired into `async_setup` alongside `ticker.notify`.
- Admin Navigation Picker dashboard list was always empty because the loader called `lovelace/dashboards` instead of `lovelace/dashboards/list`.
- Notification titles were logged at INFO level; now at DEBUG. (BUG-101)
- **BUG-102**: Conditional subscriptions gated on `zone.home` (or any zone) never evaluated correctly. Zone matching compared the zone friendly name against `person.state`, which HA sets to the constant "home" (lowercase) — not the friendly name. Fix: zone evaluation now uses entity-ID membership in `zone.attributes["persons"]`, which is HA's authoritative list. Immune to zone renames, locale differences, and case sensitivity.
- **BUG-103**: Migration wizard dropped picture/image links from converted automations. The converter was wrapping the source `data:` block one level too many, producing `data.data.data.image` instead of `data.data.image`. At runtime `ticker.notify` reads `data.image` one level under the call, finds nothing, and the picture is silently dropped. Fix: the converter now reads `old_service_data["data"]` directly as the inner data block, matching the model used by the Automations tab editor. Top-level mobile_app keys other than `title`/`message`/`data` (e.g. `target:`) are dropped with a debug log entry. (GitHub #29, vordenken)
- **Note:** Automations that were already converted before v1.6.0 with image/picture fields are still broken on disk. Re-run the migration wizard against those automations, or edit the YAML/storage entry by hand to remove the extra `data:` wrapper.
- 21 bugs fixed in total. See BUGS.md and CHANGELOG.md for the complete list.

### v1.5.2

**Fixed:**
- **BUG-082**: Adding a new device recipient (TTS or Push) always failed with `expected dict for dictionary value @ data['conditions']. Got None` when the Conditions tab was left empty.

### v1.5.1

**Fixed:**
- **BUG-081**: "Copy YAML" in the Migration Wizard crashed in the HA Companion App and non-HTTPS contexts (`Cannot read properties of undefined (reading 'writeText')`). The Clipboard API call is now guarded; the fallback dialog is reachable in all environments.

### v1.5.0

**Added:**
- **AND/OR condition grouping** — the conditions builder now supports mixed AND/OR logic. Toggle the operator pill between conditions, or group conditions into a sub-group with its own operator. Up to two nesting levels. Existing conditions migrate automatically.
- **Automations Manager** — a new Automations tab in the admin panel surfaces every automation and script that uses `ticker.notify`, with inline editing of all notification fields without opening the automation editor.
- **Action Sets Library** — action sets are now a first-class resource managed from a dedicated library tab. Categories reference a shared action set by ID. A per-call `action_set_id` parameter allows automation-level overrides.
- **Smart notification management** — per-category auto-grouping, auto-tagging (none / category / title), sticky and persistent flags, and `ticker.clear_notification` service.
- **Notification navigation target** — `navigate_to` parameter on `ticker.notify` controls where notification taps navigate. Category-level default configurable via the Navigation Picker in the admin panel.

**Fixed:**
- iOS delivery incorrectly stripped `image`, `image_url`, and `attachment` data keys from notifications — regression introduced in v1.4.0 by the HTML stripping feature; filter removed.
- Queued single-entry notifications discarded all original data fields (image, url, custom keys) on delivery.

### v1.4.0

**Added:**
- **Device recipients** — admins configure shared devices (TVs, speakers, tablets) in a new Devices tab. Each recipient has its own subscriptions and conditions. Push and TTS delivery types supported; TTS uses announce mode, snapshot/restore, or plain fallback in priority order.
- **Critical notifications** — `critical: true` on `ticker.notify` injects platform-specific critical alert payloads. iOS bypasses silent/DND mode; Android uses high-priority FCM. No platform-specific logic required in automations.
- **Alarmo and blueprint compatibility** — Ticker registers as `notify.ticker`, discoverable by Alarmo, blueprints, and any integration scanning for `notify.*` services.
- **Configurable category default mode** — admins set the default subscription mode (Always / Never / Conditional) per category from the category create/edit dialog.

**Fixed:**
- Admin log timestamps truncated on mobile.
- Admin log list capped at 100 entries while stats showed 500.
- Discovery cache storing empty results on HA startup, causing delivery failures for up to 5 minutes.

### v1.3.0

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
