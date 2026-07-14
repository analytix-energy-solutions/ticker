"""Constants for Ticker integration."""

DOMAIN = "ticker"
VERSION = "1.8.2"

# Storage keys
STORAGE_VERSION = 1
STORAGE_KEY_CATEGORIES = f"{DOMAIN}_categories"
STORAGE_KEY_SUBSCRIPTIONS = f"{DOMAIN}_subscriptions"
STORAGE_KEY_USERS = f"{DOMAIN}_users"
STORAGE_KEY_QUEUE = f"{DOMAIN}_queue"
STORAGE_KEY_LOGS = f"{DOMAIN}_logs"

# Subscription modes (v2 - lowercase)
MODE_ALWAYS = "always"
MODE_NEVER = "never"
MODE_CONDITIONAL = "conditional"

SUBSCRIPTION_MODES = [MODE_ALWAYS, MODE_NEVER, MODE_CONDITIONAL]

# Default subscription mode for new category subscriptions
DEFAULT_SUBSCRIPTION_MODE = MODE_ALWAYS

# Subscription set_by values (tracks who set the subscription)
SET_BY_USER = "user"
SET_BY_ADMIN = "admin"
# F-39: tag for subscriptions seeded into a recipient row when its linked
# person entity is removed (orphan fallback). The recipient reverts to
# Standalone with its last-known subs preserved.
SET_BY_ORPHAN_FALLBACK = "orphan_fallback"

# Device preference modes
DEVICE_MODE_ALL = "all"
DEVICE_MODE_SELECTED = "selected"

# Default zone for conditional mode
DEFAULT_CONDITION_ZONE = "zone.home"

# Rule types for F-2 Advanced Conditions
RULE_TYPE_ZONE = "zone"
RULE_TYPE_TIME = "time"
RULE_TYPE_STATE = "state"
RULE_TYPES = [RULE_TYPE_ZONE, RULE_TYPE_TIME, RULE_TYPE_STATE]

# Condition tree (F-2b AND/OR grouping)
CONDITION_NODE_GROUP = "group"
CONDITION_OPERATOR_AND = "AND"
CONDITION_OPERATOR_OR = "OR"
CONDITION_OPERATORS = [CONDITION_OPERATOR_AND, CONDITION_OPERATOR_OR]
CONDITION_MAX_DEPTH = 2

# Days of week (1=Monday, 7=Sunday per ISO 8601)
WEEKDAYS = list(range(1, 8))

# Legacy modes (for migration from v1)
LEGACY_MODE_ALWAYS = "ALWAYS"
LEGACY_MODE_NEVER = "NEVER"
LEGACY_MODE_WHEN_IN_ZONE = "WHEN_IN_ZONE"
LEGACY_MODE_ON_ARRIVAL = "ON_ARRIVAL"

# Default category (non-deletable)
CATEGORY_DEFAULT = "general"
CATEGORY_DEFAULT_NAME = "General"

# Service constants
SERVICE_NOTIFY = "notify"
NOTIFY_SERVICE_TIMEOUT = 30  # Timeout for notify/TTS service calls (seconds)
ATTR_CATEGORY = "category"
ATTR_TITLE = "title"
ATTR_MESSAGE = "message"
ATTR_EXPIRATION = "expiration"
ATTR_DATA = "data"

# Queue defaults
DEFAULT_EXPIRATION_HOURS = 48
MAX_EXPIRATION_HOURS = 48
MAX_QUEUE_RETRIES = 3  # Max retry attempts before discarding queued notification

# Log settings
MAX_LOG_ENTRIES = 500
LOG_RETENTION_DAYS = 7

# Sensor settings
MAX_SENSOR_NOTIFICATIONS = 10

# Log outcomes
LOG_OUTCOME_SENT = "sent"
LOG_OUTCOME_QUEUED = "queued"
LOG_OUTCOME_SKIPPED = "skipped"
LOG_OUTCOME_FAILED = "failed"
LOG_OUTCOME_SNOOZED = "snoozed"
LOG_OUTCOME_EXPIRED = "expired"

# F-25: Expired queue sweep interval (seconds)
EXPIRED_QUEUE_SWEEP_INTERVAL = 15 * 60  # 15 minutes

# F-5: Notification Actions
ACTION_TYPE_SCRIPT = "script"
ACTION_TYPE_SNOOZE = "snooze"
ACTION_TYPE_DISMISS = "dismiss"
ACTION_TYPES = [ACTION_TYPE_SCRIPT, ACTION_TYPE_SNOOZE, ACTION_TYPE_DISMISS]
ACTION_ID_PREFIX = "TICKER_"
MAX_ACTIONS_PER_SET = 3
SNOOZE_DURATIONS_MINUTES = [15, 30, 60, 120, 240]
STORAGE_KEY_SNOOZES = f"{DOMAIN}_snoozes"
ATTR_ACTIONS = "actions"
ATTR_CRITICAL = "critical"
ATTR_NAVIGATE_TO = "navigate_to"
MAX_NAVIGATE_TO_LENGTH = 500
DEFAULT_NAVIGATE_TO = "/ticker#history"

# F-18: Non-User Recipient Support
STORAGE_KEY_RECIPIENTS = f"{DOMAIN}_recipients"
MAX_RECIPIENT_ID_LENGTH = 64
MAX_RECIPIENT_NAME_LENGTH = 100
MAX_NOTIFY_SERVICES = 10

# F-39: Device-User Subscription Link
# A recipient (device) may optionally be linked to a person entity. When
# linked, the User-link resolver (chunk 2) swaps the effective person_id
# during subscription lookup so the recipient mirrors that user's subs +
# modes (read-only on the admin device side). The upstream device-condition
# gate (F-21) remains the sole device-condition enforcement site. Storage
# is sparse: the key is absent when not linked (Standalone behavior).
ATTR_USER_LINK = "user_link"

# Device type constants (F-18 device type discriminator)
DEVICE_TYPE_PUSH = "push"
DEVICE_TYPE_TTS = "tts"
DEVICE_TYPES = [DEVICE_TYPE_PUSH, DEVICE_TYPE_TTS]

# TTS polling timeouts (seconds)
TTS_PLAYBACK_START_TIMEOUT = 5.0
TTS_PLAYBACK_MAX_TIMEOUT = 60.0
TTS_POLL_INTERVAL = 0.5

# TTS buffer delay (seconds) — pre-playback pause for Chromecast/Cast devices
TTS_BUFFER_DELAY_MIN = 0.0
TTS_BUFFER_DELAY_MAX = 10.0
TTS_BUFFER_DELAY_DEFAULT = 0.0

# MediaPlayerEntityFeature.MEDIA_ANNOUNCE (HA 2024.1+)
MEDIA_ANNOUNCE_FEATURE = 524288

# F-35: Pre-TTS Chime
# Hard cap (seconds) for waiting on the chime media to finish playing
# before kicking off the TTS service call. Most chime assets are
# 0.5–3 seconds; 10s tolerates a slow Chromecast buffer + 3s jingle.
CHIME_WAIT_TIMEOUT = 10.0
# Fixed delay (seconds) between the chime play_media call and the TTS
# service call. State polling (`_wait_for_state_exit`) was unreliable
# across platforms — HA Voice in particular keeps the entity in
# "playing" through the chime/TTS swap, while other platforms briefly
# transition to "paused". A fixed delay covers all three bundled chimes
# (max 1.7s) plus a buffer before TTS audio starts on the device.
# 3.0s gives ~1.3s of silence between the longest bundled chime and the
# TTS audio (which starts ~0.2-0.5s after tts.cloud_say is invoked on
# warm Nabu connections). Chime assets longer than this gap will
# overlap with TTS — documented limitation.
CHIME_TTS_GAP = 3.0
ATTR_CHIME_MEDIA_CONTENT_ID = "chime_media_content_id"
MAX_CHIME_MEDIA_CONTENT_ID_LENGTH = 500

# SEC-002: per-category Android notification channel — bound + sanitized on
# storage like navigate_to / chime. Android channel IDs are short slugs.
MAX_ANDROID_CHANNEL_LENGTH = 100

# F-35.2: Volume Override
# Admin-configurable volume for the chime+TTS pair. Range mirrors HA's
# media_player.volume_set service: 0.0–1.0. Two-level config (recipient
# default + category override) using the same resolver shape as chime.
# Sparse storage — omitted when None/empty so existing recipients and
# categories load with no volume override (current behavior preserved).
ATTR_VOLUME_OVERRIDE = "volume_override"
VOLUME_OVERRIDE_MIN = 0.0
VOLUME_OVERRIDE_MAX = 1.0
# Settle delay (seconds) after media_player.volume_set before issuing the
# next service call. Sonos in particular needs ~150-250ms for the new
# volume to take effect on the cached connector before play_media starts;
# without it the chime can play at the previous volume level.
VOLUME_SET_SETTLE_DELAY = 0.2

# F-35.1: Bundled Default Chimes
# Three CC0 / synthesized chime assets shipped in-tree so the Pre-TTS
# Chime feature is functional out-of-box. Files live under
# custom_components/ticker/static/chimes/ and are served via a static
# HTTP path registered in __init__.py. The picker writes the absolute
# URL composed from HA's external/internal URL into chime_media_content_id —
# bundled chimes use the same delivery path as user-supplied assets.
STATIC_CHIMES_PATH = "/ticker_static/chimes"
BUNDLED_CHIMES = [
    {"id": "subtle", "label": "Subtle ding", "filename": "subtle.wav"},
    {"id": "alert", "label": "Alert tone", "filename": "alert.wav"},
    {"id": "doorbell", "label": "Doorbell", "filename": "doorbell.wav"},
    # BUG-110 workaround variants: 2.5s of leading silence prepended so
    # Cast Default Media Receiver's swallow window consumes the silence
    # instead of the audible chime body (bumped from 1.5s in v1.7.0b22
    # after in-room verification on prod kitchen_chromecast still showed
    # clipping at the start). Manual user selection — Ticker does not
    # auto-route by device platform.
    {
        "id": "chromecast_subtle",
        "label": "(Chromecast) Subtle ding",
        "filename": "chromecast_subtle.wav",
    },
    {
        "id": "chromecast_alert",
        "label": "(Chromecast) Alert tone",
        "filename": "chromecast_alert.wav",
    },
    {
        "id": "chromecast_doorbell",
        "label": "(Chromecast) Doorbell",
        "filename": "chromecast_doorbell.wav",
    },
]

# Delivery format constants
DELIVERY_FORMAT_RICH = "rich"
DELIVERY_FORMAT_PLAIN = "plain"
DELIVERY_FORMAT_TTS = "tts"
DELIVERY_FORMAT_PERSISTENT = "persistent"

# Full set of delivery formats (used internally by formatting.py)
DELIVERY_FORMATS = [
    DELIVERY_FORMAT_RICH,
    DELIVERY_FORMAT_PLAIN,
    DELIVERY_FORMAT_TTS,
    DELIVERY_FORMAT_PERSISTENT,
]

# Subset valid for push-type recipients (TTS is a device type, not a format)
RECIPIENT_DELIVERY_FORMATS = [DELIVERY_FORMAT_RICH, DELIVERY_FORMAT_PLAIN]

# Auto-detection patterns for delivery format (push devices only)
# TTS entries removed — TTS is now a device type, not a format.
# Each tuple: (match_type, pattern, delivery_format)
# match_type: "startswith", "contains", "equals"
DELIVERY_FORMAT_PATTERNS = [
    ("equals", "notify.persistent_notification", DELIVERY_FORMAT_PERSISTENT),
    ("contains", "nfandroidtv", DELIVERY_FORMAT_RICH),
    ("contains", "mobile_app", DELIVERY_FORMAT_RICH),
]

# Panel configuration
PANEL_ADMIN_URL = "/ticker-admin"
PANEL_ADMIN_NAME = "ticker-admin"
PANEL_ADMIN_TITLE = "Ticker Admin"
PANEL_ADMIN_ICON = "mdi:bell-cog"

PANEL_USER_URL = "/ticker"
PANEL_USER_NAME = "ticker"
PANEL_USER_TITLE = "Ticker"
PANEL_USER_ICON = "mdi:bell"

# Brand colors (from branding/README.md)
COLOR_PRIMARY = "#06b6d4"  # Ticker 500
COLOR_ACCENT = "#22d3ee"   # Ticker 400
COLOR_SUBTLE = "#0e7490"   # Ticker 700

# Migration wizard
MIGRATE_SOURCE_AUTOMATION = "automation"
MIGRATE_SOURCE_SCRIPT = "script"
MIGRATE_SERVICES = ["notify", "persistent_notification"]
MAX_MIGRATION_TITLE_LENGTH = 200
MAX_MIGRATION_MESSAGE_LENGTH = 1000
MAX_IMAGE_URL_LENGTH = 500

# F-6: Smart Notification Management
SERVICE_CLEAR_NOTIFICATION = "clear_notification"

SMART_TAG_MODE_NONE = "none"
SMART_TAG_MODE_CATEGORY = "category"
SMART_TAG_MODE_TITLE = "title"
SMART_TAG_MODES = [SMART_TAG_MODE_NONE, SMART_TAG_MODE_CATEGORY, SMART_TAG_MODE_TITLE]

# F-5b: Action Sets Library
STORAGE_KEY_ACTION_SETS = f"{DOMAIN}_action_sets"
ATTR_ACTION_SET_ID = "action_set_id"
MAX_ACTION_SET_ID_LENGTH = 64
MAX_ACTION_SET_NAME_LENGTH = 100
MAX_ACTION_SET_DESCRIPTION_LENGTH = 200

# F-30: Auto-Clear Triggers
# ticker.notify accepts a `clear_when` parameter describing a state or event
# trigger that will auto-dismiss the just-sent notification when it fires.
ATTR_CLEAR_WHEN = "clear_when"
CLEAR_WHEN_TYPE_STATE = "state"
CLEAR_WHEN_TYPE_EVENT = "event"

# F-31: Blueprint-Friendly HA Device Registration (Phase 1 — visibility only)
# Ticker registers a single virtual device in HA's device registry so it
# appears in device pickers and is discoverable to community blueprints.
DEVICE_MANUFACTURER = "Analytix Energy Solutions"
DEVICE_MODEL = "Ticker Notification Router"
DEVICE_NAME = "Ticker"
DEVICE_IDENTIFIER = "ticker"
