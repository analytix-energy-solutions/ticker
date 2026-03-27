"""Tests for _wait_for_state and _wait_for_state_exit in recipient_tts.py.

Covers polling behavior, timeout, and state transitions.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.recipient_tts import (
    _wait_for_state,
    _wait_for_state_exit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass_with_state_sequence(states: list[str | None]) -> MagicMock:
    """Create hass mock that cycles through states on each .get() call.

    Args:
        states: List of state strings. None means entity not found.
    """
    hass = MagicMock()
    call_count = {"n": 0}

    def get_state(entity_id):
        idx = min(call_count["n"], len(states) - 1)
        call_count["n"] += 1
        s = states[idx]
        if s is None:
            return None
        return SimpleNamespace(entity_id=entity_id, state=s, attributes={})

    hass.states.get = MagicMock(side_effect=get_state)
    return hass


# ---------------------------------------------------------------------------
# _wait_for_state
# ---------------------------------------------------------------------------

class TestWaitForState:
    """Tests for _wait_for_state() polling."""

    @pytest.mark.asyncio
    async def test_already_in_target_returns_true(self):
        hass = _make_hass_with_state_sequence(["playing"])
        result = await _wait_for_state(
            hass, "media_player.x", "playing", timeout=1.0, poll_interval=0.05,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_transitions_to_target_returns_true(self):
        hass = _make_hass_with_state_sequence(["idle", "idle", "playing"])
        result = await _wait_for_state(
            hass, "media_player.x", "playing", timeout=2.0, poll_interval=0.05,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        hass = _make_hass_with_state_sequence(["idle"])
        result = await _wait_for_state(
            hass, "media_player.x", "playing", timeout=0.15, poll_interval=0.05,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_entity_missing_returns_false(self):
        hass = _make_hass_with_state_sequence([None])
        result = await _wait_for_state(
            hass, "media_player.gone", "playing", timeout=0.15, poll_interval=0.05,
        )
        assert result is False


# ---------------------------------------------------------------------------
# _wait_for_state_exit
# ---------------------------------------------------------------------------

class TestWaitForStateExit:
    """Tests for _wait_for_state_exit() polling."""

    @pytest.mark.asyncio
    async def test_already_exited_returns_true(self):
        hass = _make_hass_with_state_sequence(["idle"])
        result = await _wait_for_state_exit(
            hass, "media_player.x", "playing", timeout=1.0, poll_interval=0.05,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_exits_after_playing_returns_true(self):
        hass = _make_hass_with_state_sequence(["playing", "playing", "idle"])
        result = await _wait_for_state_exit(
            hass, "media_player.x", "playing", timeout=2.0, poll_interval=0.05,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_timeout_while_still_playing_returns_false(self):
        hass = _make_hass_with_state_sequence(["playing"])
        result = await _wait_for_state_exit(
            hass, "media_player.x", "playing", timeout=0.15, poll_interval=0.05,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_entity_missing_returns_false(self):
        hass = _make_hass_with_state_sequence([None])
        result = await _wait_for_state_exit(
            hass, "media_player.gone", "playing", timeout=0.15, poll_interval=0.05,
        )
        assert result is False
