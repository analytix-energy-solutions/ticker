"""Tests for F-35.1 Bundled Default Chimes — assets and constants.

Verifies the three bundled WAV files exist, parse cleanly, are within
the duration / size budget, and that the ``BUNDLED_CHIMES`` /
``STATIC_CHIMES_PATH`` constants are wired to them.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from custom_components.ticker.const import BUNDLED_CHIMES, STATIC_CHIMES_PATH


CHIMES_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "ticker"
    / "static"
    / "chimes"
)

# Caps relaxed (v1.7.0b20) to accommodate the BUG-110 ``chromecast_*``
# variants, which prepend leading silence to the original body. The
# padding was bumped from 1.5s to 2.5s in v1.7.0b22 to give Chromecast
# devices more time to wake before the chime body begins, pushing the
# largest cast variant (``chromecast_doorbell.wav``) to ~187 KB and the
# combined bundle to ~648 KB. Worst-case duration: doorbell ~1.75s body
# + 2.5s silence ≈ 4.25s; headroom kept for future tweaks.
MAX_DURATION_S = 5.0
# Each chime ≤ 200 KB (observed worst-case 187,466 B for the cast doorbell).
MAX_FILE_BYTES = 200 * 1024
# Combined bundle ≤ 720 KB (observed total 648,526 B across 3 originals + 3 cast variants).
MAX_BUNDLE_BYTES = 720 * 1024


class TestBundledChimeConstants:
    """The three bundled chimes are advertised by name in const.py."""

    def test_static_path_format(self):
        assert STATIC_CHIMES_PATH == "/ticker_static/chimes"
        assert STATIC_CHIMES_PATH.startswith("/")
        assert not STATIC_CHIMES_PATH.endswith("/")

    def test_bundled_chimes_count(self):
        # 3 original + 3 BUG-110 cast variants
        assert len(BUNDLED_CHIMES) == 6

    def test_bundled_chimes_have_required_keys(self):
        for entry in BUNDLED_CHIMES:
            assert "id" in entry
            assert "label" in entry
            assert "filename" in entry

    def test_bundled_chime_ids_unique(self):
        ids = [c["id"] for c in BUNDLED_CHIMES]
        assert len(ids) == len(set(ids))

    def test_bundled_chime_filenames_unique(self):
        names = [c["filename"] for c in BUNDLED_CHIMES]
        assert len(names) == len(set(names))


class TestBundledChimeAssets:
    """Each declared chime file exists, parses, and respects budget caps."""

    @pytest.mark.parametrize("entry", BUNDLED_CHIMES, ids=lambda e: e["id"])
    def test_chime_file_exists(self, entry):
        path = CHIMES_DIR / entry["filename"]
        assert path.is_file(), f"Missing bundled chime: {path}"

    @pytest.mark.parametrize("entry", BUNDLED_CHIMES, ids=lambda e: e["id"])
    def test_chime_file_under_size_cap(self, entry):
        path = CHIMES_DIR / entry["filename"]
        size = path.stat().st_size
        assert size <= MAX_FILE_BYTES, (
            f"{entry['filename']} is {size} bytes (cap {MAX_FILE_BYTES})"
        )

    @pytest.mark.parametrize("entry", BUNDLED_CHIMES, ids=lambda e: e["id"])
    def test_chime_parses_as_wav(self, entry):
        path = CHIMES_DIR / entry["filename"]
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
        assert channels == 1, f"{entry['filename']} should be mono"
        assert sampwidth == 2, f"{entry['filename']} should be 16-bit"
        assert framerate > 0
        assert nframes > 0

    @pytest.mark.parametrize("entry", BUNDLED_CHIMES, ids=lambda e: e["id"])
    def test_chime_duration_under_cap(self, entry):
        path = CHIMES_DIR / entry["filename"]
        with wave.open(str(path), "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        assert duration <= MAX_DURATION_S, (
            f"{entry['filename']} is {duration:.2f}s (cap {MAX_DURATION_S}s)"
        )

    def test_total_bundle_size_under_cap(self):
        total = sum(
            (CHIMES_DIR / e["filename"]).stat().st_size for e in BUNDLED_CHIMES
        )
        assert total <= MAX_BUNDLE_BYTES, (
            f"bundle is {total} bytes (cap {MAX_BUNDLE_BYTES})"
        )

    def test_licenses_file_present(self):
        """LICENSES.md must ship next to the WAVs to document the CC0 grant."""
        path = CHIMES_DIR / "LICENSES.md"
        assert path.is_file(), "LICENSES.md is missing"
        text = path.read_text(encoding="utf-8")
        assert "CC0" in text, "LICENSES.md should mention CC0"


# Pairs of (original_id, chromecast_variant_id) — BUG-110 workaround.
_CAST_PAIRS = [
    ("subtle", "chromecast_subtle"),
    ("alert", "chromecast_alert"),
    ("doorbell", "chromecast_doorbell"),
]


def _entry_by_id(chime_id: str) -> dict:
    """Resolve a BUNDLED_CHIMES entry by its ``id`` field."""
    for entry in BUNDLED_CHIMES:
        if entry["id"] == chime_id:
            return entry
    raise AssertionError(f"missing bundled chime entry: {chime_id}")


class TestChromecastSilencePaddedVariants:
    """BUG-110 workaround: ``chromecast_*`` variants prepend ~1.5s silence.

    Each pair must satisfy two invariants:

    * The cast variant is strictly LONGER in frames than its unpadded
      counterpart — silence really was prepended, not just renamed.
    * The first ~1.5s of the cast variant is zero-amplitude — the
      pad actually lands in the cast DMR swallow window rather than
      attenuating the audible body.
    """

    @pytest.mark.parametrize("original_id, cast_id", _CAST_PAIRS)
    def test_cast_variant_is_longer(self, original_id, cast_id):
        original_path = CHIMES_DIR / _entry_by_id(original_id)["filename"]
        cast_path = CHIMES_DIR / _entry_by_id(cast_id)["filename"]
        with wave.open(str(original_path), "rb") as wf:
            original_frames = wf.getnframes()
        with wave.open(str(cast_path), "rb") as wf:
            cast_frames = wf.getnframes()
        assert cast_frames > original_frames, (
            f"{cast_id} should be longer than {original_id} "
            f"({cast_frames} vs {original_frames} frames)"
        )

    @pytest.mark.parametrize("_original_id, cast_id", _CAST_PAIRS)
    def test_cast_variant_starts_with_zero_amplitude(self, _original_id, cast_id):
        """First ~1.5s of frames must be silence (all sample values == 0)."""
        cast_path = CHIMES_DIR / _entry_by_id(cast_id)["filename"]
        with wave.open(str(cast_path), "rb") as wf:
            framerate = wf.getframerate()
            sampwidth = wf.getsampwidth()
            channels = wf.getnchannels()
            # Read just the leading-silence region.
            silence_frames = int(1.5 * framerate)
            assert silence_frames <= wf.getnframes()
            raw = wf.readframes(silence_frames)
        bytes_per_frame = sampwidth * channels
        assert len(raw) == silence_frames * bytes_per_frame
        # 16-bit signed PCM zero is two 0x00 bytes per sample. A purely
        # silent region is therefore an all-zero byte string.
        assert raw == b"\x00" * len(raw), (
            f"{cast_id} leading 1.5s region is not pure silence"
        )
