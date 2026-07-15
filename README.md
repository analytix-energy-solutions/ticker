# ticker

Smart notification management for Home Assistant.

Ticker replaces scattered `notify.mobile_app_*` calls with a single `ticker.notify` service. Your automations declare what happened, and Ticker routes notifications to the right people based on their subscription preferences, location, time of day, and device state.

## Installation

### HACS

1. Open HACS, go to Integrations
2. Three dots menu - Custom repositories
3. Add this repository URL, select Integration
4. Search for "Ticker" and install
5. Restart Home Assistant
6. Settings - Devices & Services - Add Integration - Ticker

### Manual

1. Copy the `ticker` folder into `custom_components/`
2. Restart Home Assistant
3. Settings - Devices & Services - Add Integration - Ticker

## Quick start

Once installed, Ticker adds two sidebar panels: an admin panel for managing categories and users, and a user panel for subscriptions, queue, and notification history.

Create a category in the admin panel (e.g., "Security"), then replace your existing notify calls:

```yaml
# Before - one call per person, per device
- service: notify.mobile_app_johns_phone
  data:
    title: "Motion Detected"
    message: "Front door camera"
- service: notify.mobile_app_janes_phone
  data:
    title: "Motion Detected"
    message: "Front door camera"

# After - one call, Ticker handles routing
- service: ticker.notify
  data:
    category: security
    title: "Motion Detected"
    message: "Front door camera"
```

Each person controls how they receive each category - always, never, or conditionally based on zone, time, or entity state. The admin panel includes a migration wizard that scans your existing automations and helps convert them.

For the full feature guide, see [USER_GUIDE.md](custom_components/ticker/USER_GUIDE.md).

## Key features

- **Single service call** replaces all individual `notify.mobile_app_*` calls
- **Three subscription modes** - Always, Never, and Conditional with zone, time, and entity state rules
- **Smart queuing** - notifications queue when conditions aren't met and deliver automatically when they are
- **Notification actions** - configure action buttons per category (script, snooze, dismiss) with full lifecycle tracking *(v1.3.0)*
- **Per-user snooze** - suppress a category's notifications temporarily without touching any automation *(v1.3.0)*
- **Inline images in history** - camera snapshots and notification images displayed directly in the History tab *(v1.3.0)*
- **Device recipients** - send notifications to shared devices (TVs, speakers, tablets) independently of household members, with TTS and push support *(v1.4.0)*
- **Critical notifications** - single `critical: true` flag translates to platform-specific critical alert payloads on both iOS and Android *(v1.4.0)*
- **Alarmo and blueprint compatibility** - Ticker registers as a standard `notify.ticker` service, discoverable by Alarmo and any integration scanning for notify services *(v1.4.0)*
- **AND/OR condition grouping** - Mix AND and OR logic in the conditions builder with up to two nesting levels. Existing conditions migrate automatically *(v1.5.0)*
- **NOT operator for conditions** - Toggle a NOT pill on any condition row or group to invert its result. Works for every rule type: "NOT in zone home" delivers when a person is outside the zone, "NOT 08:00–22:00" covers the overnight window, and NOT on a group inverts the entire AND/OR result. Conditions without the flag are unaffected *(v1.7.0)*
- **Automations Manager** - Admin tab that surfaces every automation and script using `ticker.notify` with inline editing, no automation editor required *(v1.5.0)*
- **Action Sets Library** - Reusable action button sets managed from a central library tab, referenced by ID from any category *(v1.5.0)*
- **Smart notification management** - Auto-grouping, auto-tagging, sticky/persistent flags, and `ticker.clear_notification` service injected automatically at delivery time *(v1.5.0)*
- **Notification navigation target** - `navigate_to` parameter on `ticker.notify` deep-links to any HA panel on notification tap, with a live navigation picker in the admin panel *(v1.5.0)*
- **Pre-TTS chime** - configure an audio chime that plays through the target media_player immediately before each TTS announcement, set per recipient with optional per-category override; ships three bundled CC0 chime presets (subtle/alert/doorbell) so the feature is functional out-of-box *(v1.7.0)*
- **Volume override** - 0–100 % slider on the device and category dialogs sets the media_player volume for the chime+TTS pair, then restores the previous level after TTS finishes playing. Leave on "Default" to inherit the device's current volume *(v1.7.0)*
- **Admin-assisted household setup** - admins can operate the user panel on another household member's behalf using a "Viewing as" dropdown in the panel header, making it easy to configure subscriptions and conditions for non-technical users without sharing credentials *(v1.7.0)*
- **Device-User Subscription Link** — link a device recipient to a household member so the device automatically mirrors that user's per-category subscription modes and conditions; device-level settings (volume, chime, conditions, notify services) remain device-local *(v1.8.0)*
- **Per-category Android notification channel** — set an Android OS notification channel per category for per-category sound and DND routing on Android Companion App devices; critical notifications always keep their own `ticker_critical` channel *(v1.8.0)*
- **`ticker.ensure_category` service** — integrations and automations can declare categories declaratively at setup time without coupling to Ticker internals; idempotent, create-only, never overwrites existing user customizations *(v1.8.3)*
- **Multi-category fan-out** - `category` field accepts a list of category IDs so a single `ticker.notify` call can target multiple categories at once *(v1.6.0)*
- **Auto-clear triggers** - `clear_when` parameter on `ticker.notify` auto-dismisses persistent notifications when an entity state or event trigger fires *(v1.6.0)*
- **History search and filters** - full-text search with category and date-range filters in the user History tab, plus clickable status filters on the admin Logs tab *(v1.6.0)*
- **Expired notification visibility** - queued notifications that expire before delivery now appear in History as faded entries so users know what they missed *(v1.6.0)*
- **History management** - delete individual entries or clear your own history from the user panel, per-row deletion for admins *(v1.6.0)*
- **Blueprint device target** - Ticker registers as a Home Assistant device so it shows up in blueprint device pickers *(v1.6.0)*
- **Device routing** - global device preference plus per-category overrides
- **Notification history** - grouped by notification call, with deep-link from phone notifications
- **Dashboard sensors** - `sensor.ticker_<category>` entities for Lovelace integration *(v1.2.0)*
- **Migration wizard** - scan and convert existing automations
- **Self-healing delivery** - failed deliveries retry automatically before falling back

## AI Disclosure

This integration is being developed with AI assistance. 

## Version history

### v1.8.3

- **`ticker.ensure_category` service** — a new public, idempotent service for integrations
  and automations that need to declare categories declaratively at setup time. Creates a
  category with the supplied attributes if it does not exist; if it already exists the
  call is a no-op and never overwrites user customizations. Returns
  `{"created": bool, "category_id": str}` via `SupportsResponse.OPTIONAL`. Fail-soft if
  Ticker's config entry has not loaded yet.

### v1.8.2

- **Security hardening** — admin-only gate added to all config-mutation WebSocket handlers
  (category create/update/delete, migration wizard, automations manager, action sets,
  test-notification, snooze diagnostics); `android_channel` is now length-capped and
  sanitized on write; the migration wizard's apply-to-file path is verified to stay within
  the HA config directory.
- **Bundled/queued notifications use the per-category Android channel** — single-category
  queue-release bundles now inject `data.channel` for Android (rich) delivery, matching
  the behaviour of immediate delivery.
- **Android Channel on the category create form** — the channel field is now available
  when creating a new category, not only when editing.
- **Parallelized notification dispatch** — the per-device fan-out and per-person/recipient
  loops now run concurrently via `asyncio.gather`, reducing delivery latency for
  multi-device households. A per-media_player lock serializes TTS delivery to the same
  speaker so concurrent calls cannot corrupt volume or overlap audio. Thanks to community
  contributor **@danswett** (#49, #50).

Community contributors: **@nalabelle** (#34), **@jesfer** (#55), **@danswett** (#52, #54, #49, #50). Feature credit: **@meyerluk** (#22).

### v1.8.1

- Hotfix: eliminated a cold-load `TypeError` in the user and admin panels — on a
  fresh load the panels could log `Cannot read properties of undefined (reading
  'SidebarToggle')` before their shared script finished loading. Harmless once
  loaded, but noisy in the console; now guarded.

### v1.8.0

- **Device-User Subscription Link** — admins can link a device recipient to a household member from the admin Devices tab; the linked device's per-category subscriptions then mirror that user's modes and conditions automatically. Device-level settings (conditions, volume, chime, notify services) stay device-local (F-39, closes GitHub #22, @meyerluk).
- **Per-category Android notification channel** — set an Android notification channel per category (admin Categories tab) for per-category sound and Do-Not-Disturb routing. The channel is injected into the Android (rich) push payload at delivery time; critical notifications keep their own channel. Thanks to community contributor **@nalabelle** (#34).
- **Editable categories fix** — categories could not be edited or saved after creation; the save failed silently because the `android_channel` field was rejected by the update schema (GitHub #46). Thanks to community contributor **@jesfer** (#55).
- **Mobile-portrait sidebar toggle** — the user and admin panels now render a hamburger (☰) button on mobile portrait so you can open the Home Assistant sidebar drawer; previously custom panels rendered no toggle and users could get trapped (GitHub #51). Thanks to community contributor **@danswett** (#52).
- **Notification History deep-link fix** — tapping a notification that targets the History tab (`#history`) now reliably opens History even when Home Assistant reuses the already-open panel, instead of falling back to Subscriptions (GitHub #53). Thanks to community contributor **@danswett** (#54).

### v1.7.0

- **View-as-User (admin assist)** — admins can operate the user panel on another household member's behalf. A "Viewing as" dropdown in the panel header lets the admin select any person; the panel re-renders as that user with a persistent "Viewing as: [Name]" banner and a one-tap "Stop viewing" exit.
- **NOT operator for conditions** — toggle a NOT pill on any condition row or group to invert its result. Works for all rule types and condition groups.
- **Pre-TTS chime** — each TTS recipient can be paired with a short audio chime that plays before TTS. Set per device with an optional per-category override. Three CC0 chime presets (subtle/alert/doorbell) ship out of the box.
- **Volume override** — a 0–100% slider on the device and category dialogs sets the media_player volume for the chime+TTS window, then restores it afterwards.
- **Entity-state value suggestions** — the state field in entity-state conditions now suggests valid values based on the selected entity's domain (input_select options, climate modes, lock/cover/media_player/alarm enums). Free-text still accepted for custom states.
- **Per-call `action_set_id`** — `ticker.notify` now accepts `action_set_id` to override the category default action set for a single call (closes BUG-104, where the documented parameter was rejected by the service schema).
- **Security** — WebSocket handlers accepting `person_id` now enforce admin-or-self gating (BUG-108), closing a within-session cross-user read path for subscriptions, queue, and logs.

### v1.6.0

- **Notification history search** — full-text search bar in the user History tab, plus category dropdown and date-range filters. Filter state resets on tab switch or panel close.
- **Log Filter by Status** — stat counters on the admin Logs tab (Total, Sent, Queued, Skipped, Failed, Snoozed, Expired) are now clickable and filter the log list to the selected outcome.
- **Expired notification visibility** — notifications that expire in the queue before delivery are logged with a dedicated "expired" outcome and shown as faded entries in user History and admin Logs. A periodic sweep checks for expired entries every 15 minutes.
- **Multi-category fan-out** — `ticker.notify` `category` field now accepts either a single category ID or a list. Each listed category gets its own notification_id and goes through the full per-category delivery pipeline.
- **Auto-clear triggers** — new `clear_when` parameter on `ticker.notify` accepts an entity-state or event trigger. Ticker registers a one-shot listener per delivered notification and calls `ticker.clear_notification` automatically when the trigger fires. (Listeners do not survive HA restart.)
- **History management** — per-entry delete buttons on the admin Logs tab and per-group delete on the user History tab, plus a user-scoped "Clear History" button. Legacy entries without a notification_id are gracefully skipped.
- **Blueprint-friendly device** — Ticker now registers itself as a Home Assistant device with `entry_type=service`, so it shows up in blueprint device pickers. Blueprints still call `notify.ticker` as the service; device-action support is deferred to a later release.
- **Per-category sensor privacy flag** — new `expose_in_sensor` category flag (default on) controls whether raw notification title and body are included in the category sensor's extra attributes. Turn off for sensitive categories such as 2FA codes or medical reminders.
- **Improved security** — `navigate_to` is now validated as a relative HA path (rejects `https://`, `javascript:`, `//`-protocol-relative, and paths containing control characters), condition trees validate leaf semantics against the HA state machine, and notification titles are no longer logged at INFO level.
- 21 bug fixes across conditional notification gating (post F-2b migration), zone rule evaluation, condition listener lifecycle, queue retry expiration, bundled log correlation, and the Persistent toggle in the category Smart sub-tab (GitHub #25). Includes BUG-102 (zone matching now uses entity-ID membership in `zone.attributes["persons"]` instead of fragile friendly-name string comparison) and BUG-103 (migration wizard now correctly preserves picture/image links from converted automations — re-run the wizard against any previously-converted automations that include images, GitHub #29).

### v1.5.2

- Fixed: adding a new device recipient (TTS or Push) always failed with
  `expected dict for dictionary value @ data['conditions']. Got None` when
  the Conditions tab was left empty. No device recipients could be created.

### v1.5.1

- Fixed: "Copy YAML" in the Migration Wizard crashed in the HA Companion App and
  non-HTTPS contexts (`Cannot read properties of undefined (reading 'writeText')`).
  The YAML fallback dialog now works correctly in all environments (GitHub #19).

### v1.5.0

- **AND/OR condition grouping** — the conditions builder now supports mixed AND/OR logic. Toggle the operator pill between conditions, or group adjacent conditions into a sub-group with its own operator. Up to two nesting levels. Existing flat conditions migrate automatically.
- **Automations Manager** — a new Automations tab in the admin panel surfaces every automation and script that uses `ticker.notify`, with inline editing of category, title, message, and more without opening the automation editor.
- **Action Sets Library** — action sets are now a first-class resource managed from a dedicated library tab rather than embedded inside individual categories. Any category can reference a shared action set by ID.
- **Smart notification management** — per-category auto-grouping, auto-tagging for replacement, `ticker.clear_notification` service, and persistent/sticky status notifications, all injected automatically at delivery time.
- **Notification navigation target** — a `navigate_to` parameter on `ticker.notify` deep-links to any HA panel when a notification is tapped. The admin panel includes a live navigation picker populated from the sidebar panel registry.
- Bug fixes: iOS delivery incorrectly stripped image data from notifications (regression in v1.4.0); queued single-entry notifications discarded all original data fields on delivery.

### v1.4.0

- **Device recipients** — send notifications to shared devices (TVs, speakers, wall tablets) independently of household members. Admins manage devices in a new Devices tab. Supports push (rich or plain) and TTS delivery with announce mode, snapshot/restore, and configurable resume behaviour.
- **Critical notifications** — pass `critical: true` on `ticker.notify` and Ticker injects the correct platform-specific critical alert payload automatically (iOS bypasses DND; Android uses high-priority FCM).
- **Alarmo and blueprint compatibility** — Ticker now registers as a standard `notify.ticker` service. Any integration or blueprint that scans for `notify.*` services can find and use Ticker directly.
- **Configurable category defaults** — admins can set the default subscription mode (Always / Never / Conditional) per category, so new users start with the right preference instead of always receiving everything.
- Bug fixes: admin log timestamps truncated on mobile, device cards losing controls on mobile with long names, log list capped at 100 entries while stats showed 500, discovery cache storing empty results on startup.

### v1.3.2

- Fixed: saving category from Default Mode or Actions sub-tab no longer fails with "Name required" (BUG-049)

### v1.3.1

- Added AI disclosure section to the README.

### v1.3.0

- **Notification Actions & Workflows** - configure action buttons per category (script, snooze, dismiss). Ticker listens for button taps and routes them automatically - no second automation required.
- **Per-user snooze** - tapping a snooze button suppresses that category for the configured duration for that person only, without touching any automation.
- **Inline images in History** - notifications with a `data.image` field now show the image inline in the user History tab.
- Action taken recorded in admin logs and user history.
- Bug fixes: stray HTML entities in migration wizard output, disabled users counted as subscribers, improved Companion App notify service discovery.

### v1.2.1

- Hotfix for mobile_app Companion App notify service discovery - services were not found on fresh HA installs because legacy `notify.mobile_app_*` services are not registered in the entity registry.

### v1.2.0

- Advanced conditional rules: time windows and entity state conditions in addition to zones.
- Category sensor entities (`sensor.ticker_<category_id>`) for dashboard integration.
- Internal refactoring: store, websocket, and arrival handling split into smaller modules, all files under 500 lines.

### v1.1.0

- Notification grouping in History tab - entries from the same `ticker.notify` call grouped into a single card with device tags.
- History badge count reflects grouped notifications.

### v1.0.0

First public release with complete notification management: category routing, three subscription modes with advanced conditions, smart queuing with bundled delivery, self-healing retries, per-user device routing, notification history with phone deep-links, auto-discovery, admin and user panels, and migration wizard.

## Uninstalling

Update any automations using `ticker.notify` before removing. Then delete the integration from Settings - Devices & Services. Removing Ticker deletes all its data - categories, subscriptions, queue, and logs.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Releases prior to v1.7.0 (v1.0.0 through v1.6.2) were licensed under GPL-3.0
and remain available under that license; the relicense applies to v1.7.0
and later.

## Support Ticker

If Ticker is useful to you, consider sponsoring development via GitHub Sponsors. It helps keep the project active and growing.
Join our Discord server to find out more and get support: https://discord.gg/NCcG4GpP
