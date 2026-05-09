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

# Brief: each chime ≤ 3.0 seconds.
MAX_DURATION_S = 3.0
# Brief: each chime ≤ 100 KB to keep the bundle small.
MAX_FILE_BYTES = 100 * 1024
# Brief: combined bundle ≤ 250 KB.
MAX_BUNDLE_BYTES = 250 * 1024


class TestBundledChimeConstants:
    """The three bundled chimes are advertised by name in const.py."""

    def test_static_path_format(self):
        assert STATIC_CHIMES_PATH == "/ticker_static/chimes"
        assert STATIC_CHIMES_PATH.startswith("/")
        assert not STATIC_CHIMES_PATH.endswith("/")

    def test_bundled_chimes_count(self):
        assert len(BUNDLED_CHIMES) == 3

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
