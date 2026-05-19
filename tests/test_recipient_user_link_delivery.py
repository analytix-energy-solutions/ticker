"""F-39 chunk 2 — User-link resolver in the delivery path.

These tests cover the resolver helper itself (pure function, no I/O) and
the end-to-end delivery semantics for linked recipients. The contract:

* When ``user_link`` is set on a recipient, subscription mode and
  conditions are looked up under the linked person entity id.
* When ``user_link`` is absent, the recipient's own
  ``recipient:{recipient_id}`` rows are used — behavior must be
  byte-identical to chunk 1 (anchor: ``test_recipient_notify.py``).
* The upstream F-21 device-condition gate in ``services.py`` is the
  sole device-condition enforcement site. The resolver does NOT
  re-evaluate device conditions; if the F-21 gate skips a recipient,
  the resolver never runs.
* Queueing and logging stay attributed to the recipient, not the
  linked user, even when the conditions were the user's.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ticker.const import (
    ATTR_USER_LINK,
    DEVICE_TYPE_PUSH,
    LOG_OUTCOME_QUEUED,
    LOG_OUTCOME_SKIPPED,
)
from custom_components.ticker.recipient_notify import (
    async_handle_conditional_recipient,
    async_send_to_recipient,
    resolve_effective_subscription_pid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_store(
    category: dict | None = None,
    conditions: dict | None = None,
) -> MagicMock:
    store = MagicMock()
    store.async_add_log = AsyncMock()
    store.async_add_to_queue = AsyncMock()
    store.get_category.return_value = category
    store.get_subscription_conditions.return_value = conditions
    return store


def _recipient(
    recipient_id: str = "tv_living",
    name: str = "Living Room TV",
    user_link: str | None = None,
) -> dict:
    r: dict = {
        "recipient_id": recipient_id,
        "name": name,
        "device_type": DEVICE_TYPE_PUSH,
        "notify_services": [{"service": "notify.tv_living", "name": "TV"}],
        "delivery_format": "auto",
    }
    if user_link is not None:
        r[ATTR_USER_LINK] = user_link
    return r


# ---------------------------------------------------------------------------
# resolve_effective_subscription_pid — pure function
# ---------------------------------------------------------------------------

class TestResolveEffectiveSubscriptionPid:
    """Resolver returns the linked person id when set, else recipient key."""

    def test_no_user_link_returns_recipient_key(self):
        r = _recipient(recipient_id="tv1")
        assert resolve_effective_subscription_pid(r) == "recipient:tv1"

    def test_user_link_returns_person_id(self):
        r = _recipient(recipient_id="tv1", user_link="person.alice")
        assert resolve_effective_subscription_pid(r) == "person.alice"

    def test_empty_string_user_link_falls_back(self):
        """Empty string is falsy — must NOT be treated as a real link."""
        r = _recipient(recipient_id="tv1", user_link="")
        assert resolve_effective_subscription_pid(r) == "recipient:tv1"

    def test_none_user_link_falls_back(self):
        r = _recipient(recipient_id="tv1")
        r[ATTR_USER_LINK] = None
        assert resolve_effective_subscription_pid(r) == "recipient:tv1"

    def test_standalone_byte_identical_to_legacy_format(self):
        """Anchor: legacy code built `f'recipient:{recipient_id}'` inline.
        Resolver must produce exactly that string for unlinked recipients."""
        r = _recipient(recipient_id="kitchen_speaker")
        legacy = f"recipient:{r['recipient_id']}"
        assert resolve_effective_subscription_pid(r) == legacy


# ---------------------------------------------------------------------------
# async_handle_conditional_recipient — user_link semantics
# ---------------------------------------------------------------------------

class TestConditionalRecipientWithUserLink:
    """When user_link is set, conditions lookup uses the linked person id.

    Logging and queueing remain attributed to the recipient.
    """

    @pytest.mark.asyncio
    async def test_conditions_looked_up_under_linked_user(self):
        """Linked recipient queries store.get_subscription_conditions with
        the linked person id, NOT the recipient key."""
        hass = _make_hass()
        store = _make_store(conditions=None)  # falls back to no-conditions branch
        recipient = _recipient(user_link="person.alice")

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ):
            await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "T", "M",
            )

        # Verify conditions were fetched under the linked person id.
        store.get_subscription_conditions.assert_called_once_with(
            "person.alice", "cat1",
        )

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_user_conditional_met_delivers(self, mock_deliver):
        """User in conditional mode, user conditions met -> delivers."""
        mock_deliver.return_value = (True, "all met")
        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _recipient(user_link="person.alice")

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            result = await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "T", "M",
            )

        mock_send.assert_awaited_once()
        assert result["delivered"] == ["svc"]

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_user_conditional_unmet_queues_under_recipient(
        self, mock_deliver, mock_queue,
    ):
        """User conditions UNMET + queue-until-met -> queued under the
        recipient key (not the linked user). The user's conditions
        gated delivery, but ownership of the queue row stays with the
        recipient so admins can clear it from the device row."""
        mock_deliver.return_value = (False, "time not met")
        mock_queue.return_value = (True, "queue until time met")
        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _recipient(recipient_id="tv1", user_link="person.alice")

        result = await async_handle_conditional_recipient(
            hass, store, recipient, "cat1", "T", "M",
        )

        store.async_add_to_queue.assert_awaited_once()
        queue_kw = store.async_add_to_queue.call_args[1]
        assert queue_kw["person_id"] == "recipient:tv1"
        store.async_add_log.assert_awaited_once()
        log_kw = store.async_add_log.call_args[1]
        assert log_kw["outcome"] == LOG_OUTCOME_QUEUED
        assert log_kw["person_id"] == "recipient:tv1"
        assert len(result["queued"]) == 1

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_user_conditional_unmet_no_queue_skips(
        self, mock_deliver, mock_queue,
    ):
        """User conditions UNMET + queue NOT enabled -> skipped, logged
        under the recipient."""
        mock_deliver.return_value = (False, "time not met")
        mock_queue.return_value = (False, "no queue")
        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _recipient(recipient_id="tv1", user_link="person.alice")

        result = await async_handle_conditional_recipient(
            hass, store, recipient, "cat1", "T", "M",
        )

        store.async_add_to_queue.assert_not_called()
        store.async_add_log.assert_awaited_once()
        log_kw = store.async_add_log.call_args[1]
        assert log_kw["outcome"] == LOG_OUTCOME_SKIPPED
        assert log_kw["person_id"] == "recipient:tv1"
        assert len(result["dropped"]) == 1

    @pytest.mark.asyncio
    async def test_no_conditions_falls_back_to_category_default(self):
        """When the linked user has no subscription row for this category,
        get_subscription_conditions returns None (per the store's existing
        category-default fallback). Helper sends immediately."""
        hass = _make_hass()
        store = _make_store(conditions=None)
        recipient = _recipient(user_link="person.alice")

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ) as mock_send:
            await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "T", "M",
            )

        mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# async_handle_conditional_recipient — standalone regression
# ---------------------------------------------------------------------------

class TestConditionalRecipientStandaloneRegression:
    """A recipient with no user_link must behave byte-identical to
    chunk 1 (see test_recipient_notify.py::TestAsyncHandleConditionalRecipient
    for the parallel anchors)."""

    @pytest.mark.asyncio
    async def test_conditions_looked_up_under_recipient_key(self):
        hass = _make_hass()
        store = _make_store(conditions=None)
        recipient = _recipient(recipient_id="tv1")  # no user_link

        with patch(
            "custom_components.ticker.recipient_notify.async_send_to_recipient",
            new_callable=AsyncMock,
            return_value={"delivered": ["svc"], "queued": [], "dropped": []},
        ):
            await async_handle_conditional_recipient(
                hass, store, recipient, "cat1", "T", "M",
            )

        store.get_subscription_conditions.assert_called_once_with(
            "recipient:tv1", "cat1",
        )

    @pytest.mark.asyncio
    @patch("custom_components.ticker.conditions.should_queue")
    @patch("custom_components.ticker.conditions.should_deliver_now")
    async def test_standalone_queue_keyed_to_recipient(
        self, mock_deliver, mock_queue,
    ):
        mock_deliver.return_value = (False, "time not met")
        mock_queue.return_value = (True, "queue")
        hass = _make_hass()
        store = _make_store(conditions={"rules": [{"type": "time"}]})
        recipient = _recipient(recipient_id="tv1")

        await async_handle_conditional_recipient(
            hass, store, recipient, "cat1", "T", "M",
        )

        store.async_add_to_queue.assert_awaited_once()
        queue_kw = store.async_add_to_queue.call_args[1]
        assert queue_kw["person_id"] == "recipient:tv1"


# ---------------------------------------------------------------------------
# async_send_to_recipient — push path is unaffected by user_link
# ---------------------------------------------------------------------------

class TestSendUnaffectedByUserLink:
    """The push delivery path itself is independent of user_link — the
    resolver only swaps the subscription lookup key. Once the recipient
    loop has decided to deliver, the payload, services, and log
    attribution come from the recipient.
    """

    @pytest.mark.asyncio
    async def test_push_log_attributed_to_recipient_even_when_linked(self):
        hass = _make_hass()
        store = _make_store()
        recipient = _recipient(recipient_id="tv1", user_link="person.alice")

        result = await async_send_to_recipient(
            hass, store, recipient, "cat1", "Title", "Msg",
        )

        assert result["delivered"] == ["notify.tv_living"]
        log_kw = store.async_add_log.call_args[1]
        # Log should be under the recipient, never the linked user.
        assert log_kw["person_id"] == "recipient:tv1"


# ---------------------------------------------------------------------------
# F-21 device-condition gate documentation
# ---------------------------------------------------------------------------

# The architect brief calls out two cases where the F-21 device-condition
# gate stops delivery before the resolver runs:
#
#   * User in `always` mode + device conditions FAIL -> skipped at F-21
#   * User in `conditional` mode, user conditions met + device conditions
#     FAIL -> skipped at F-21
#
# Those cases live in services.py and are covered by the existing F-21
# integration tests (see test_f21_device_conditions.py for the device-
# condition-gate paths). Re-asserting them here would duplicate that
# coverage and re-wire the entire `_dispatch_to_category` harness. The
# resolver contract is: "when the F-21 gate stops the flow, the resolver
# is never reached." That is verified by inspection of services.py
# (sub_pid is computed AFTER the gate `continue`).
