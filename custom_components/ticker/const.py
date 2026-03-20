"""Constants for Ticker integration."""

DOMAIN = "ticker"
VERSION = "1.3.2"

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
