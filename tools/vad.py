#!/usr/bin/env python3
"""VAD probe (Timing Compare U3, T7-T8): independent acoustic check of the dub audio at
each in-gap card, so tools/timing_compare.py can split "kept, in a subtitle gap" into a
confident hallucination (silence) vs a real dub-only line the subs omit (speech). See
specs/timing-compare/spec-v3.md's "[v3] VAD probe of in-gap cards" acceptance criterion.

Two backends, selected by `vad_probe(..., backend=...)`:
  - "webrtcvad" (default): frames a 16 kHz mono PCM window into 10/20/30 ms chunks and
    runs Google's WebRTC voice-activity detector per frame, then decides speech-present
    from the fraction of voiced frames (voiced_ratio_to_verdict). Targets *voiced speech*
    specifically, so it's the better discriminator against loud music/SFX.
  - "ffmpeg-silencedetect" (dep-free fallback): runs ffmpeg's `silencedetect` audio filter
    over the window and decides speech-present from how much of the window it reports as
    silent. Energy-based, NOT a speech classifier -- cruder, and can mistake quiet speech
    for silence or loud music/SFX for speech (documented limitation, spec-v3.md).

Every public entry point (`vad_probe` and both backend functions) returns `bool | None`:
True = speech present, False = no voiced speech, **None = could not determine** (missing
window, backend unavailable, subprocess/parse failure) -- callers map None to
`in_gap_vad_error`, never guess a silent True/False. The VAD path only ADDS information to
an already-kept in-gap card; it must never raise (a broad except is the last line of
defense in `vad_probe` itself, on top of each backend's own guards) and never change
tools/timing_compare.py's on-cue/in-gap classification (T6).

*** ENVIRONMENT REALITY (do not remove this note without re-verifying) ***
`webrtcvad` does NOT install in this repo's py3.14 dev venv (no prebuilt wheel for 3.14;
the sdist's setup.py also pulls in `pkg_resources`/`pip`'s vendored `pkg_resources`, which
py3.14 no longer ships). The import is guarded (`try/except ImportError` below) so this
module always imports cleanly and `_vad_probe_webrtcvad`/`vad_probe(backend="webrtcvad")`
degrade to `None` (`in_gap_vad_error`) rather than crashing. Real webrtcvad decisions on
real audio are PENDING manual verification on the server (where the container's Debian
Python has a prebuilt wheel) -- see tests/test_vad.py's docstring and the U3 report for
what IS and is NOT covered by unit tests here.

Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import re
import subprocess
import sys
import wave

try:
    import webrtcvad
except ImportError:                     # pragma: no cover -- exercised for real in this dev venv
    webrtcvad = None

sys.path.insert(0, ".")
import common  # noqa: E402

log = common.log

# --- Tunables ---

SAMPLE_RATE = 16000                     # extract_audio_window() (timing_compare.py) always
SAMPLE_WIDTH = 2                        # produces 16k mono pcm_s16le, matching generate.py's
                                         # extract_wav() convention.
VALID_FRAME_MS = (10, 20, 30)           # the only frame durations webrtcvad accepts
DEFAULT_FRAME_MS = 30

# Fraction of frames a window needs flagged "voiced" (webrtcvad) -- or fraction of the
# window NOT reported "silent" (ffmpeg-silencedetect) -- to call the window speech-present.
# Deliberately low: this is a presence detector, not a density scorer -- an in-gap window is
# typically only 1-3s and even a short real utterance shouldn't be shrugged off as
# hallucination-adjacent noise. PENDING calibration against the by_nsp cross-tab on the
# first real run (spec-v3.md open question: "VAD aggressiveness + music-masked speech").
VAD_MIN_VOICED_RATIO_DEFAULT = 0.3

SILENCEDETECT_NOISE_DB = -30            # ffmpeg silencedetect noise floor
SILENCEDETECT_MIN_DURATION_S = 0.3      # shortest gap silencedetect will report


# ============================================================================
# Pure decision core -- the ONLY part of this module unit-testable without webrtcvad or
# ffmpeg in this dev venv. No I/O, no subprocess, no C-extension.
# ============================================================================

def voiced_ratio_to_verdict(voiced_frames: list, min_voiced_ratio: float = VAD_MIN_VOICED_RATIO_DEFAULT):
    """Pure decision: speech present (True) if the fraction of `voiced_frames` (one bool
    per audio frame, True = that frame was flagged voiced) that are True is
    >= min_voiced_ratio; False if there are frames but too few/none are voiced.

    Returns None (never a guessed False) for an empty frame list -- e.g. a zero-length or
    unframeable window -- so callers route it to `in_gap_vad_error` rather than silently
    reporting a confident "silent" verdict for a window that was never actually examined.
    This is the one deliberate deviation from the brief's `-> bool` signature; the return
    type is `bool | None` for that reason."""
    if not voiced_frames:
        return None
    return (sum(1 for v in voiced_frames if v) / len(voiced_frames)) >= min_voiced_ratio


def frame_pcm(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE, frame_ms: int = DEFAULT_FRAME_MS,
              sample_width: int = SAMPLE_WIDTH) -> list:
    """Pure byte-slicer: split raw little-endian 16-bit PCM audio into fixed-size frames
    (webrtcvad requires exactly 10/20/30 ms frames at a supported sample rate -- it raises
    on any other buffer length). Drops a trailing partial frame (at most `frame_ms`
    milliseconds -- negligible against a multi-second in-gap window) rather than padding
    it, since a padded frame would be a fabricated sample, not real audio. No file I/O;
    exercised in tests/test_vad.py with synthetic bytes."""
    frame_bytes = int(sample_rate * (frame_ms / 1000.0) * sample_width)
    if frame_bytes <= 0 or not pcm_bytes:
        return []
    return [pcm_bytes[i:i + frame_bytes] for i in range(0, len(pcm_bytes) - frame_bytes + 1, frame_bytes)]


def read_wav_pcm(wav_path: str, expected_rate: int = SAMPLE_RATE, expected_width: int = SAMPLE_WIDTH):
    """Read a mono PCM wav's raw sample bytes via the stdlib `wave` module -- no ffmpeg, no
    webrtcvad needed for this step, so it's fully exercisable in this dev venv with a
    synthetic wav built by the same stdlib module. Returns None (never raises) if the file
    is missing/unreadable, not a valid wav, or not in the expected format --
    extract_audio_window() (tools/timing_compare.py) always produces 16k mono pcm_s16le via
    ffmpeg, so a format mismatch here means upstream extraction produced something
    unexpected; route to in_gap_vad_error rather than guessing at the format."""
    try:
        with wave.open(wav_path, "rb") as wf:
            if wf.getnchannels() != 1 or wf.getframerate() != expected_rate or wf.getsampwidth() != expected_width:
                return None
            return wf.readframes(wf.getnframes())
    except (OSError, wave.Error, EOFError):
        return None


def wav_duration_s(wav_path: str):
    """Duration in seconds of a wav file via stdlib `wave` (frames / framerate). None
    (never raises) if the file is missing/unreadable or not a valid wav."""
    try:
        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            if not rate:
                return None
            return wf.getnframes() / rate
    except (OSError, wave.Error, EOFError):
        return None


_SILENCE_DURATION_RE = re.compile(r"silence_duration:\s*(-?[\d.]+)")


def parse_silencedetect_output(stderr_text: str) -> float:
    """Pure text parser: sum every `silence_duration: <seconds>` value ffmpeg's
    `silencedetect` audio filter prints to stderr (one per detected silence interval that
    fully completed within the analyzed window). No subprocess, no I/O -- unit-testable
    with a synthetic string shaped like real ffmpeg stderr output. Returns 0.0 (not None)
    for text with no matches -- "no reported silence" is a real, valid parse result (the
    whole window was voiced/loud), distinct from "couldn't determine" which the caller
    signals by never reaching this parser (subprocess failure short-circuits first)."""
    return sum(float(m) for m in _SILENCE_DURATION_RE.findall(stderr_text))


# ============================================================================
# Backend implementations -- real I/O (wav read via stdlib `wave`; webrtcvad C-extension;
# ffmpeg subprocess). PENDING manual verification on the server: webrtcvad is unavailable
# in this dev venv (see module docstring) and there is no real in-gap-card audio window
# available here to run either backend against for real. tests/test_vad.py exercises the
# webrtcvad code PATH (frame count, is_speech call shape, aggregation) against a stub
# module standing in for webrtcvad -- same pattern test_generate.py uses to stub
# faster_whisper -- which is NOT the same as having run real webrtcvad.
# ============================================================================

def _vad_probe_webrtcvad(wav_path: str, aggressiveness: int = 2, frame_ms: int = DEFAULT_FRAME_MS,
                          min_voiced_ratio: float = VAD_MIN_VOICED_RATIO_DEFAULT):
    if webrtcvad is None:
        return None                     # guarded: module unavailable -> in_gap_vad_error, no crash
    pcm = read_wav_pcm(wav_path)
    if pcm is None:
        return None
    frames = frame_pcm(pcm, frame_ms=frame_ms)
    if not frames:
        return None
    try:
        vad = webrtcvad.Vad(aggressiveness)
        voiced = [bool(vad.is_speech(f, SAMPLE_RATE)) for f in frames]
    except Exception as e:
        log("webrtcvad probe failed:", wav_path, e)
        return None
    return voiced_ratio_to_verdict(voiced, min_voiced_ratio)


def _vad_probe_ffmpeg_silencedetect(wav_path: str, noise_db: int = SILENCEDETECT_NOISE_DB,
                                     min_silence_s: float = SILENCEDETECT_MIN_DURATION_S,
                                     min_voiced_ratio: float = VAD_MIN_VOICED_RATIO_DEFAULT):
    duration = wav_duration_s(wav_path)
    if not duration or duration <= 0:
        return None
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "info", "-i", wav_path,
             "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}", "-f", "null", "-"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except Exception as e:
        log("ffmpeg silencedetect failed:", wav_path, e)
        return None
    if r.returncode != 0:
        log("ffmpeg silencedetect nonzero exit:", wav_path, r.returncode)
        return None
    silent_s = parse_silencedetect_output(r.stderr)
    voiced_ratio = max(0.0, 1.0 - silent_s / duration)
    return voiced_ratio >= min_voiced_ratio


# ============================================================================
# Public entry point
# ============================================================================

def vad_probe(wav_path: str, aggressiveness: int = 2, backend: str = "webrtcvad",
              min_voiced_ratio: float = VAD_MIN_VOICED_RATIO_DEFAULT):
    """Run a VAD backend over a 16 kHz mono wav window and return True (speech present),
    False (no voiced speech / effectively silent), or None (could not determine -- no wav,
    backend unavailable, subprocess/parse failure). Never raises: this is the seam
    tools/timing_compare.py calls per in-gap card, and per spec-v3.md a VAD failure must
    degrade to `in_gap_vad_error` and let the run continue, never abort it.

    `backend`: "webrtcvad" (default) or "ffmpeg-silencedetect". An unrecognized backend
    string also returns None (logged) rather than raising, for the same reason."""
    try:
        if backend == "webrtcvad":
            return _vad_probe_webrtcvad(wav_path, aggressiveness, min_voiced_ratio=min_voiced_ratio)
        if backend == "ffmpeg-silencedetect":
            return _vad_probe_ffmpeg_silencedetect(wav_path, min_voiced_ratio=min_voiced_ratio)
        log("vad_probe: unknown backend", backend)
        return None
    except Exception as e:   # belt-and-suspenders: VAD must never crash the run (spec-v3.md)
        log("vad_probe failed:", wav_path, backend, e)
        return None
