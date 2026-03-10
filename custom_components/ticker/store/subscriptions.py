"""Subscription mixin for TickerStore."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ..const import (
    DEFAULT_SUBSCRIPTION_MODE,
    MODE_ALWAYS,
    MODE_NEVER,
    MODE_CONDITIONAL,
    SET_BY_USER,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class SubscriptionMixin:
    """Mixin providing subscription functionality for TickerStore.

    This mixin expects the following attributes on the class:
    - hass: HomeAssistant
    - _subscriptions: dict[str, dict[str, Any]]
    - _subscriptions_store: Store[dict[str, dict[str, Any]]]
    """

    # Type hints for mixin attributes (provided by main class)
    hass: "HomeAssistant"
    _subscriptions: dict[str, dict[str, Any]]
    _subscriptions_store: "Store[dict[str, dict[str, Any]]]"

    async def async_save_subscriptions(self) -> None:
        """Save subscriptions to storage."""
        await self._subscriptions_store.async_save(self._subscriptions)

    def _subscription_key(self, person_id: str, category_id: str) -> str:
        """Generate subscription key."""
        return f"{person_id}:{category_id}"

    def get_subscription(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get subscription for a person and category."""
        key = self._subscription_key(person_id, category_id)
        return self._subscriptions.get(key)

    def get_subscriptions_for_person(
        self, person_id: str
    ) -> dict[str, dict[str, Any]]:
        """Get all subscriptions for a person."""
        prefix = f"{person_id}:"
        return {
            key.split(":", 1)[1]: sub
            for key, sub in self._subscriptions.items()
            if key.startswith(prefix)
        }

    def get_subscriptions_for_category(
        self, category_id: str
    ) -> list[dict[str, Any]]:
        """Get all subscriptions for a category."""
        suffix = f":{category_id}"
        return [
            sub for key, sub in self._subscriptions.items()
            if key.endswith(suffix)
        ]

    def get_subscription_mode(
        self, person_id: str, category_id: str
    ) -> str:
        """Get subscription mode, falling back to category default."""
        sub = self.get_subscription(person_id, category_id)
        if sub:
            return sub.get("mode", DEFAULT_SUBSCRIPTION_MODE)

        # Fall back to category default mode
        category = self._categories.get(category_id)
        if category and "default_mode" in category:
            return category["default_mode"]

        return DEFAULT_SUBSCRIPTION_MODE

    def get_subscription_conditions(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get subscription conditions, falling back to category default."""
        sub = self.get_subscription(person_id, category_id)
        if sub and sub.get("mode") == MODE_CONDITIONAL:
            return sub.get("conditions", {})

        # Fall back to category default conditions
        if not sub:
            category = self._categories.get(category_id)
            if (category
                    and category.get("default_mode") == MODE_CONDITIONAL
                    and "default_conditions" in category):
                return category["default_conditions"]

        return None

    def get_device_override(
        self, person_id: str, category_id: str
    ) -> dict[str, Any] | None:
        """Get device override for a subscription.

        Returns:
            Dict with 'enabled' (bool) and 'devices' (list) if override exists,
            None otherwise.
        """
        sub = self.get_subscription(person_id, category_id)
        if sub:
            return sub.get("device_override")
        return None

    def _has_valid_conditions(self, conditions: dict[str, Any] | None) -> bool:
        """Check if conditions have at least one effective delivery path."""
        from ..conditions import has_valid_rules
        return has_valid_rules(conditions)

    async def async_set_subscription(
        self,
        person_id: str,
        category_id: str,
        mode: str,
        conditions: dict[str, Any] | None = None,
        set_by: str | None = None,
        device_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set subscription for a person and category.

        Args:
            person_id: The person entity ID
            category_id: The category ID
            mode: One of 'always', 'never', 'conditional'
            conditions: For conditional mode, dict with zones config:
                {
                    "zones": {
                        "zone.home": {
                            "deliver_while_here": True,
                            "queue_until_arrival": True
                        }
                    }
                }
            set_by: Who set this subscription ('user' or 'admin')
            device_override: Optional device override for this category:
                {
                    "enabled": True,
                    "devices": ["notify.mobile_app_tablet"]
                }
        """
        key = self._subscription_key(person_id, category_id)

        subscription = {
            "person_id": person_id,
            "category_id": category_id,
            "mode": mode,
            "set_by": set_by or SET_BY_USER,
        }

        if mode == MODE_CONDITIONAL:
            if conditions and self._has_valid_conditions(conditions):
                subscription["conditions"] = conditions
            else:
                # No valid conditions - fallback to always
                _LOGGER.warning(
                    "Conditional mode for %s/%s has no valid conditions, "
                    "falling back to always",
                    person_id,
                    category_id,
                )
                subscription["mode"] = MODE_ALWAYS

        # Device override only applies to always/conditional modes
        if device_override and mode in (MODE_ALWAYS, MODE_CONDITIONAL):
            subscription["device_override"] = device_override
        elif mode == MODE_NEVER:
            # Clear device override for 'never' mode
            subscription.pop("device_override", None)

        self._subscriptions[key] = subscription
        await self.async_save_subscriptions()
        _LOGGER.debug(
            "Set subscription: %s -> %s = %s (set_by: %s, device_override: %s)",
            person_id,
            category_id,
            subscription["mode"],
            subscription["set_by"],
            "enabled" if subscription.get("device_override", {}).get("enabled")
            else "disabled",
        )
        return subscription

    async def async_delete_subscription(
        self, person_id: str, category_id: str
    ) -> bool:
        """Delete a subscription."""
        key = self._subscription_key(person_id, category_id)
        if key not in self._subscriptions:
            return False

        del self._subscriptions[key]
        await self.async_save_subscriptions()
        return True
