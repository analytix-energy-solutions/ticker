"""Tests for the BUG-109 cast volume "jiggle" workaround.

Split from ``test_f35_2_volume_delivery.py`` to keep both test files
under the 500-line limit. This file covers:

- ``_set_volume_with_jiggle`` direct unit tests (two-call behavior,
  jiggle magnitude, edge cases at the low end of the [0, 1] range,
  success/failure propagation).
- The BUG-109 integration test verifying that the restore path uses
  the jiggle helper and that the helper issues a distinct intermediate
  ``volume_set`` before the target.
- BUG-109 iteration 2 cast-branch deferred-apply integration tests
  (override volume_set occurs AFTER chime play_media + state=playing,
  TTS triggers a re-apply, restore goes through jiggle).

Background: Chromecast devices have an internal volume cache that can
desync from HA's ``volume_level`` attribute. When ``volume_set`` is
called with a value that matches the cast's internal cache, the call
is silently ignored. Hans empirically validated in a prior
non-Ticker automation that sending a distinct intermediate value
("target - 0.25") before the real target forces the cast to
physically apply the change. The pattern is now wrapped in
``_set_volume_with_jiggle``.

BUG-109 iteration 2 added per-media-app context handling: cast resets
its per-app volume on every play_media, so the override volume_set
must be deferred to AFTER play_media + state=playing. The cast branch
also re-applies the override when TTS loads its own app context.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.ticker.recipient_tts import (
    _set_volume_with_jiggle,
    async_send_tts,
)

# Reuse the test helpers from the main F-35.2 volume delivery suite.
from tests.test_f35_2_volume_delivery import (
    _make_hass,
    _make_recipient,
    _make_store,
)


# ---------------------------------------------------------------------------
# _set_volume_with_jiggle — direct unit tests
# ---------------------------------------------------------------------------


class TestSetVolumeWithJiggle:
    """Direct unit coverage for the jiggle helper.

    Validates the two-call pattern, jiggle magnitude (target ± 0.25),
    and success/failure propagation rules.
    """

    @pytest.mark.asyncio
    async def test_calls_set_volume_twice(self):
        """The helper must issue exactly two volume_set service calls."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
            )
        assert ok is True
        assert hass.services.async_call.call_count == 2

    @pytest.mark.asyncio
    async def test_first_call_uses_distinct_jiggle_value(self):
        """The first call must use a value DIFFERENT from the target."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
            )
        calls = hass.services.async_call.call_args_list
        first_level = calls[0][0][2]["volume_level"]
        assert first_level != 0.8, (
            "Jiggle value must be distinct from the target to force cast "
            f"devices out of their internal cache; got {first_level}"
        )
        # Per Hans's working pattern, magnitude is 0.25 below target
        # when target >= 0.25.
        assert first_level == pytest.approx(0.55)

    @pytest.mark.asyncio
    async def test_second_call_uses_exact_target(self):
        """The second call must land on the exact target volume."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
            )
        calls = hass.services.async_call.call_args_list
        assert calls[1][0][2]["volume_level"] == 0.8

    @pytest.mark.asyncio
    async def test_low_target_jiggles_upward(self):
        """When target < 0.25 we cannot subtract — jiggle UP instead.

        Otherwise the jiggle would clamp to 0.0 and could equal the
        target in the edge case target == 0.0, defeating the purpose.
        """
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.1,
            )
        calls = hass.services.async_call.call_args_list
        first_level = calls[0][0][2]["volume_level"]
        second_level = calls[1][0][2]["volume_level"]
        # Jiggle = 0.1 + 0.25 = 0.35; target = 0.1
        assert first_level == pytest.approx(0.35)
        assert second_level == 0.1
        assert first_level != second_level

    @pytest.mark.asyncio
    async def test_target_zero_jiggle_distinct(self):
        """target=0.0 must still produce a distinct first call."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.0,
            )
        calls = hass.services.async_call.call_args_list
        assert calls[0][0][2]["volume_level"] != 0.0
        assert calls[1][0][2]["volume_level"] == 0.0

    @pytest.mark.asyncio
    async def test_target_one_jiggles_downward(self):
        """target=1.0 must subtract (target >= 0.25 branch)."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 1.0,
            )
        calls = hass.services.async_call.call_args_list
        assert calls[0][0][2]["volume_level"] == pytest.approx(0.75)
        assert calls[1][0][2]["volume_level"] == 1.0

    @pytest.mark.asyncio
    async def test_returns_true_when_both_succeed(self):
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.6,
            )
        assert ok is True

    @pytest.mark.asyncio
    async def test_returns_false_when_first_fails(self):
        """First call failing returns False even if second succeeds."""
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(
            side_effect=[HomeAssistantError("offline"), None],
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.6,
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_returns_false_when_second_fails(self):
        """Second call failing returns False."""
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(
            side_effect=[None, HomeAssistantError("offline")],
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.6,
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_both_calls_made_even_if_first_fails(self):
        """Failures are fail-soft inside _set_volume; the wrapper still
        proceeds to the target call so the device gets at least one
        attempt at the intended volume."""
        hass = _make_hass(entity_id="media_player.kitchen")
        hass.services.async_call = AsyncMock(
            side_effect=[HomeAssistantError("offline"), None],
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.6,
            )
        assert hass.services.async_call.call_count == 2


# ---------------------------------------------------------------------------
# BUG-110 b21 (Issue 1): skip_final_settle on _set_volume_with_jiggle
# ---------------------------------------------------------------------------


class TestSetVolumeWithJiggleSkipFinalSettle:
    """BUG-110 b21 (Issue 1): the cast pre-set sites that immediately
    follow with ``play_media`` can skip the trailing settle on the
    target volume_set — play_media's context switch supersedes it
    and the saved ~200ms shrinks the audible window where the still
    playing prior media is at the override volume.
    """

    @pytest.mark.asyncio
    async def test_default_settles_after_both_calls(self):
        """Default behavior (skip_final_settle=False): trailing settle
        applied after BOTH the jiggle and the target. Two sleeps
        observed on the recipient_tts_chime asyncio module."""
        from custom_components.ticker.recipient_tts_chime import (
            VOLUME_SET_SETTLE_DELAY,
        )
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
            )
        assert ok is True
        settle_sleeps = [
            c.args[0] for c in mock_sleep.await_args_list
            if c.args and c.args[0] == VOLUME_SET_SETTLE_DELAY
        ]
        assert len(settle_sleeps) == 2, (
            f"Expected two settle sleeps (jiggle + target); got "
            f"{len(settle_sleeps)} (all sleeps: "
            f"{[c.args[0] for c in mock_sleep.await_args_list if c.args]})"
        )

    @pytest.mark.asyncio
    async def test_skip_final_settle_drops_trailing_settle(self):
        """skip_final_settle=True: only the mid-jiggle settle runs;
        the target volume_set returns without sleeping."""
        from custom_components.ticker.recipient_tts_chime import (
            VOLUME_SET_SETTLE_DELAY,
        )
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                skip_final_settle=True,
            )
        assert ok is True
        settle_sleeps = [
            c.args[0] for c in mock_sleep.await_args_list
            if c.args and c.args[0] == VOLUME_SET_SETTLE_DELAY
        ]
        assert len(settle_sleeps) == 1, (
            f"Expected exactly one settle sleep (mid-jiggle only); "
            f"got {len(settle_sleeps)}"
        )

    @pytest.mark.asyncio
    async def test_skip_final_settle_still_calls_volume_set_twice(self):
        """skip_final_settle does not change call count — only sleep."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                skip_final_settle=True,
            )
        assert hass.services.async_call.call_count == 2

    @pytest.mark.asyncio
    async def test_skip_final_settle_target_value_preserved(self):
        """The TARGET volume value is still the requested level."""
        hass = _make_hass(entity_id="media_player.kitchen")
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                skip_final_settle=True,
            )
        calls = hass.services.async_call.call_args_list
        # First is jiggle (distinct), second is exact target.
        assert calls[1][0][2]["volume_level"] == 0.8


# ---------------------------------------------------------------------------
# BUG-110 b23 (Issue 1 follow-up): pause_before_jiggle on _set_volume_with_jiggle
# ---------------------------------------------------------------------------


class TestSetVolumeWithJigglePauseBeforeJiggle:
    """BUG-110 b23 (Issue 1 follow-up): cast pre-set sites that follow
    immediately with ``play_media`` can additionally pause the still-
    playing prior media BEFORE the jiggle. This eliminates the residual
    ~200ms audible window where the override volume was briefly audible
    on the prior media — pause silences audio so the volume transition
    becomes inaudible until ``play_media`` resumes at the new gain.

    Gating: pause_before_jiggle=True AND state=="playing" (narrow match
    — not "buffering"). All other states fall through unchanged. The
    pause call is fail-soft: if it raises, the jiggle still proceeds.
    """

    @pytest.mark.asyncio
    async def test_default_no_pause_issued(self):
        """Default behavior (pause_before_jiggle=False): no media_pause
        is issued regardless of entity state. Only two volume_set calls
        observed."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
            )
        assert ok is True
        services_called = [
            c[0][1] for c in hass.services.async_call.call_args_list
        ]
        assert "media_pause" not in services_called, (
            f"Default must NOT pause; got services={services_called}"
        )
        # Only the two jiggle volume_sets.
        assert services_called.count("volume_set") == 2

    @pytest.mark.asyncio
    async def test_pause_issued_when_playing(self):
        """pause_before_jiggle=True AND state=="playing": media_pause
        is called exactly once, then settle, then jiggle proceeds."""
        from custom_components.ticker.recipient_tts_chime import (
            VOLUME_SET_SETTLE_DELAY,
        )
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                pause_before_jiggle=True,
            )
        assert ok is True
        services_called = [
            c[0][1] for c in hass.services.async_call.call_args_list
        ]
        # Exactly one media_pause, before both volume_sets.
        assert services_called.count("media_pause") == 1, (
            f"Expected exactly one media_pause; got {services_called}"
        )
        assert services_called[0] == "media_pause", (
            f"media_pause must precede volume_set; got {services_called}"
        )
        # Settle sleep observed after the pause and before the jiggle.
        settle_sleeps = [
            c.args[0] for c in mock_sleep.await_args_list
            if c.args and c.args[0] == VOLUME_SET_SETTLE_DELAY
        ]
        # Three settles total: one post-pause + two from the jiggle pair.
        assert len(settle_sleeps) == 3, (
            f"Expected 3 settle sleeps (post-pause + 2 jiggle); "
            f"got {len(settle_sleeps)}"
        )
        # And the jiggle pair still issued — two volume_sets.
        assert services_called.count("volume_set") == 2

    @pytest.mark.asyncio
    async def test_no_pause_when_state_not_playing(self):
        """pause_before_jiggle=True but state in {"paused", "idle",
        "off"}: no media_pause issued; jiggle proceeds normally."""
        for non_playing_state in ("paused", "idle", "off"):
            hass = _make_hass(
                entity_id="media_player.kitchen",
                state=non_playing_state,
                volume_level=0.4,
            )
            with patch(
                "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                ok = await _set_volume_with_jiggle(
                    hass, "media_player.kitchen", 0.8,
                    pause_before_jiggle=True,
                )
            assert ok is True
            services_called = [
                c[0][1] for c in hass.services.async_call.call_args_list
            ]
            assert "media_pause" not in services_called, (
                f"state={non_playing_state} must NOT trigger pause; "
                f"got {services_called}"
            )
            # Jiggle pair still issued.
            assert services_called.count("volume_set") == 2

    @pytest.mark.asyncio
    async def test_no_pause_when_state_buffering(self):
        """pause_before_jiggle=True but state=="buffering": narrow
        match excludes buffering (treated as transient mid-load); no
        media_pause issued."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="buffering",
            volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                pause_before_jiggle=True,
            )
        assert ok is True
        services_called = [
            c[0][1] for c in hass.services.async_call.call_args_list
        ]
        assert "media_pause" not in services_called, (
            "state=buffering must NOT trigger pause (narrow match — "
            f"'playing' only); got {services_called}"
        )

    @pytest.mark.asyncio
    async def test_pause_failure_is_fail_soft(self):
        """If media_pause raises, the helper logs a warning, proceeds
        with the jiggle, and returns success based on the volume_set
        outcomes only."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
        )

        async def _flaky_call(domain, service, payload, blocking=True):
            if service == "media_pause":
                raise HomeAssistantError("pause failed")
            return None

        hass.services.async_call = AsyncMock(side_effect=_flaky_call)
        with patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            ok = await _set_volume_with_jiggle(
                hass, "media_player.kitchen", 0.8,
                pause_before_jiggle=True,
            )
        # Return value tracks the volume_set outcomes only — both
        # volume_sets succeed in the flaky stub, so result is True.
        assert ok is True
        services_called = [
            c[0][1] for c in hass.services.async_call.call_args_list
        ]
        # Pause was attempted but raised — jiggle still proceeded.
        assert services_called.count("media_pause") == 1
        assert services_called.count("volume_set") == 2


# ---------------------------------------------------------------------------
# Integration: BUG-109 iteration 2 cast-branch deferred-apply
# ---------------------------------------------------------------------------


class TestCastBranchHybridPattern:
    """BUG-109 iteration 3 (v1.7.0b17): cast targets use a HYBRID
    pre-set + deferred re-apply pattern. The override volume_set is
    issued BOTH before ``play_media(chime)`` (so the chime app loads
    at the target gain) AND after TTS reaches ``state=playing`` (so
    the TTS app context — which may differ from the chime app — also
    plays at the target).
    """

    @pytest.mark.asyncio
    async def test_restore_branch_cast_pre_sets_override_before_chime(self):
        """Cast restore branch: override volume_set is issued BEFORE
        play_media(chime) in the hybrid pattern (iteration 3). The
        first two service calls are jiggle + target volume_set, then
        play_media(chime)."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
            content_id="http://stream/live",
            content_type="music",
            features=0,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        names = [c[0][1] for c in calls]
        # BUG-109 iteration 3 hybrid: the chime PRE-SET (jiggle pair)
        # precedes play_media. BUG-110 b23 (Issue 1 follow-up): when
        # the entity is in state="playing" the pre-set is preceded by
        # a media_pause to silence the prior media before the volume
        # transition. Sequence: media_pause, volume_set, volume_set,
        # play_media.
        first_play_idx = names.index("play_media")
        first_vol_set_idx = names.index("volume_set")
        assert first_vol_set_idx < first_play_idx, (
            "Cast hybrid: chime pre-set volume_set must precede "
            f"play_media(chime); got names={names}"
        )
        assert names[0] == "media_pause", (
            "BUG-110 b23: pause-jiggle-play must start with media_pause "
            f"when prior media is playing; got names={names}"
        )
        assert names[1] == "volume_set"
        assert names[2] == "volume_set"
        assert names[3] == "play_media"

    @pytest.mark.asyncio
    async def test_restore_branch_cast_reapplies_override_after_tts(self):
        """Cast restore branch: override is re-applied after TTS starts
        (TTS loads a new app context which resets cast's per-app
        volume). The override target (0.9) should appear AT LEAST twice
        in the volume_set sequence (initial deferred-apply + TTS
        re-apply) via the jiggle helper."""
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.4,
            content_id="http://stream/live",
            content_type="music",
            features=0,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        # Count volume_set calls landing on the override target (0.9).
        # Cast branch uses jiggle for each apply, so each override apply
        # contributes one target-level call (plus one jiggle).
        target_calls = sum(
            1 for c in calls
            if c[0][1] == "volume_set"
            and c[0][2]["volume_level"] == 0.9
        )
        assert target_calls >= 2, (
            "Cast branch must re-apply override after TTS starts "
            f"(chime app -> TTS app context reset); got {target_calls} "
            f"volume_set calls at 0.9"
        )


class TestRestoreBranchWaitsForResumedMediaBeforeVolumeRestore:
    """BUG-109 (full integration, cast path): the volume restore must
    (a) wait for the resumed media to enter ``playing`` AND (b) go
    through the jiggle helper so cast devices physically apply it.

    Both fixes must be present and ordered correctly.
    """

    @pytest.mark.asyncio
    async def test_wait_for_state_called_between_resume_and_volume_restore(self):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.71,
            content_id="http://stream/live",
            content_type="music",
            features=0,
        )
        # Order tracker — capture every relevant call site by name so
        # we can assert the exact sequence around BUG-109.
        order: list[str] = []

        async def _tagged_wait_for_state(*_args, **_kwargs):
            order.append("wait_for_state")
            return True

        async def _tagged_wait_for_state_exit(*_args, **_kwargs):
            order.append("wait_for_state_exit")
            return True

        original_call = hass.services.async_call

        async def _tagged_async_call(domain, service, payload, blocking=True):
            # Tag resume play_media specifically (content_id matches
            # the snapshotted stream, not the chime media-source).
            if service == "play_media" and payload.get(
                "media_content_id"
            ) == "http://stream/live":
                order.append("resume_play_media")
            elif service == "volume_set":
                level = payload.get("volume_level")
                # Round to 2 decimals for FP-stable tagging
                # (target - 0.25 may yield 0.45999... rather than 0.46).
                order.append(f"volume_set:{round(float(level), 2)}")
            return await original_call(domain, service, payload, blocking=blocking)

        hass.services.async_call = AsyncMock(side_effect=_tagged_async_call)

        # Wrap _set_volume_with_jiggle to assert it was used for the
        # restore (and not bypassed by a bare _set_volume call).
        from custom_components.ticker import recipient_tts_chime as _chime_mod

        jiggle_calls: list[float] = []
        original_jiggle = _chime_mod._set_volume_with_jiggle

        async def _tagged_jiggle(
            hass_arg, entity_id, volume_level,
            skip_final_settle=False, pause_before_jiggle=False,
        ):
            jiggle_calls.append(volume_level)
            return await original_jiggle(
                hass_arg, entity_id, volume_level,
                skip_final_settle=skip_final_settle,
                pause_before_jiggle=pause_before_jiggle,
            )

        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new=AsyncMock(side_effect=_tagged_wait_for_state),
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new=AsyncMock(side_effect=_tagged_wait_for_state_exit),
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._set_volume_with_jiggle",
            side_effect=_tagged_jiggle,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        # Resume play_media must appear in the sequence.
        assert "resume_play_media" in order, (
            f"expected resume play_media in call sequence, got {order}"
        )
        resume_idx = order.index("resume_play_media")
        # BUG-109 iteration 3 hybrid: the snapshot volume (0.71) is
        # applied BOTH before resume_play_media (pre-set so the resumed
        # app loads at the right gain) AND after the resumed media
        # enters state=playing (defensive re-apply). Pick the LAST
        # 0.71 occurrence (the defensive re-apply) and assert it
        # follows resume.
        restore_indices = [
            i for i, tag in enumerate(order) if tag == "volume_set:0.71"
        ]
        assert len(restore_indices) >= 2, (
            "BUG-109 iteration 3 hybrid: cast restore must apply "
            f"snapshot volume both before and after resume_play_media; "
            f"got {order}"
        )
        defensive_idx = restore_indices[-1]
        assert defensive_idx > resume_idx, (
            "BUG-109 iteration 3 hybrid: defensive snapshot re-apply "
            f"must come after resume_play_media; got {order}"
        )
        # Timing fix: _wait_for_state must be between resume and the
        # defensive re-apply (cast waits for the resumed media to
        # actually be playing before re-applying).
        between = order[resume_idx + 1:defensive_idx]
        assert "wait_for_state" in between, (
            "BUG-109: _wait_for_state must be called between the resume "
            f"play_media and the defensive volume re-apply; got "
            f"between={between} (full order={order})"
        )
        # Jiggle fix: restore must go through _set_volume_with_jiggle.
        assert 0.71 in jiggle_calls, (
            "BUG-109: volume restore must use _set_volume_with_jiggle; "
            f"jiggle calls captured: {jiggle_calls}"
        )
        # Jiggle fix: an intermediate volume_set must precede each
        # snapshot target (target - 0.25 = 0.46 after rounding).
        assert "volume_set:0.46" in order, (
            "BUG-109: jiggle pattern must issue an intermediate "
            f"volume_set (target - 0.25 = 0.46) before the target; "
            f"got {order}"
        )
        # The intermediate that pairs with the defensive re-apply must
        # also precede it.
        jiggle_indices = [
            i for i, tag in enumerate(order) if tag == "volume_set:0.46"
        ]
        assert any(i < defensive_idx and i > resume_idx for i in jiggle_indices), (
            "BUG-109: jiggle intermediate must precede the defensive "
            f"target volume_set; got {order}"
        )


class TestRestoreBranchUsesJiggleForVolumeRestore:
    """BUG-109 (additional finding): the volume restore must go
    through ``_set_volume_with_jiggle`` so cast devices physically
    apply the restore even when their internal cache matches the
    target. Cast path only.
    """

    @pytest.mark.asyncio
    async def test_restore_uses_jiggle_wrapper_not_bare_set_volume(self):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            state="playing",
            volume_level=0.71,
            content_id="http://stream/live",
            content_type="music",
            features=0,
        )

        jiggle_targets: list[float] = []

        async def _capture_jiggle(
            _hass, _entity_id, volume_level,
            skip_final_settle=False, pause_before_jiggle=False,
        ):
            jiggle_targets.append(float(volume_level))
            return True

        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._set_volume_with_jiggle",
            new=AsyncMock(side_effect=_capture_jiggle),
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", resume=True, volume_override=0.9,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        # Multiple jiggle calls expected (cast iteration 2):
        # - 0.9 override after chime + state=playing
        # - 0.9 re-apply after TTS state=playing
        # - 0.71 restore after media resume
        assert 0.9 in jiggle_targets, (
            f"override should use jiggle helper; got {jiggle_targets}"
        )
        assert 0.71 in jiggle_targets, (
            f"restore should use jiggle helper; got {jiggle_targets}"
        )
        # Order: override before restore.
        assert jiggle_targets.index(0.9) < jiggle_targets.index(0.71)


# ---------------------------------------------------------------------------
# Integration tests for explicit kwarg / category override — cast path
# ---------------------------------------------------------------------------


class TestExplicitVolumeKwarg:
    """volume= kwarg overrides resolved value (test-chime path), cast
    branch with jiggle pattern."""

    @pytest.mark.asyncio
    async def test_explicit_volume_wins_over_recipient(self):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0, volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(category=None)
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.2,  # ignored
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
                volume=0.95,
            )

        # Cast branch with deferred-apply + jiggle. The target volume
        # 0.95 must appear in the volume_set sequence (alongside its
        # jiggle 0.70).
        calls = hass.services.async_call.call_args_list
        levels = [
            c[0][2]["volume_level"] for c in calls
            if c[0][1] == "volume_set"
        ]
        assert 0.95 in levels, f"target 0.95 missing from {levels}"
        assert pytest.approx(0.70) in levels, (
            f"jiggle 0.70 (0.95-0.25) missing from {levels}"
        )


class TestCategoryOverridesVolume:
    """End-to-end: category volume_override beats recipient default
    (cast branch)."""

    @pytest.mark.asyncio
    async def test_category_volume_wins(self):
        hass = _make_hass(
            entity_id="media_player.kitchen",
            features=0, volume_level=0.4,
        )
        with patch(
            "custom_components.ticker.recipient_tts_delivery._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_chime._is_cast_target",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery._wait_for_state_exit",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.ticker.recipient_tts_delivery.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "custom_components.ticker.recipient_tts_chime.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            store = _make_store(
                category={"volume_override": 0.9},
            )
            recipient = _make_recipient(
                chime="media-source://x", volume_override=0.2,
            )
            await async_send_tts(
                hass, store, recipient, "cat1", "Title", "Hello",
            )

        calls = hass.services.async_call.call_args_list
        levels = [
            c[0][2]["volume_level"] for c in calls
            if c[0][1] == "volume_set"
        ]
        # Category target 0.9 must appear (not recipient's 0.2).
        assert 0.9 in levels, f"category target 0.9 missing from {levels}"
        assert 0.2 not in levels, (
            f"recipient default 0.2 should not be applied; got {levels}"
        )
