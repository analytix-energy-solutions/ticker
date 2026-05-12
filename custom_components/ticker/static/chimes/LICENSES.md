# Bundled Chimes — Licensing

The three WAV files in this directory (`subtle.wav`, `alert.wav`,
`doorbell.wav`) ship with the Ticker integration as default Pre-TTS
chime assets (feature F-35.1).

## Origin

All three chimes are **synthesized in-house** from sine waves using only
Python's standard library (`math`, `struct`, `wave`). No third-party
audio assets, samples, or recordings are incorporated. The complete
synthesis script is committed at `scripts/generate_chimes.py` for
reproducibility — re-running it produces byte-identical output.

## License

These bundled audio files are dedicated to the public domain under the
[Creative Commons CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)
public-domain dedication. You may copy, modify, distribute, and
redistribute them — including commercially — without asking for
permission and without attribution.

This explicit grant is included so users who fork or repackage Ticker
(for example via HACS) can ship the chime assets without separate
licensing review.

## Format

* WAV, 22050 Hz, mono, 16-bit signed PCM
* Each file ≤ 3 seconds
* Total bundle size ~155 KB
