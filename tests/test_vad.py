"""Unit tests for tools/vad.py (Timing Compare U3, T7-T8).

Coverage map (see the U3 report for the authoritative PENDING list):
  - Pure decision/parsing core (voiced_ratio_to_verdict, frame_pcm, parse_silencedetect_output)
    -- fully covered, no I/O, no C-extension, no subprocess.
  - wav I/O (read_wav_pcm, wav_duration_s) via the stdlib `wave` module against synthetic
    wavs built by that same module -- fully covered; no ffmpeg needed to construct a valid
    16 kHz mono pcm_s16le wav for these tests.
  - `_vad_probe_webrtcvad`'s framing/call-shape/aggregation logic -- covered against a
    STUB `webrtcvad` module (monkeypatched onto tools.vad.webrtcvad), the exact pattern
    tests/test_generate.py uses to stub faster_whisper. This validates OUR integration
    code (frame count, is_speech call arguments, aggressiveness passthrough, exception
    handling, ratio aggregation) -- it is NOT a test of real webrtcvad's actual voice
    classification, which this dev venv cannot install (py3.14, no prebuilt wheel; see
    tools/vad.py's module docstring). PENDING manual verification on the server.
  - `_vad_probe_ffmpeg_silencedetect`'s and `vad_probe`'s real subprocess.run(["ffmpeg", ...])
    call is NOT exercised here (matches the project convention of tests/test_mux.py /
    tests/test_timing_compare.py: real ffmpeg/ffprobe subprocess calls are PENDING manual
    verification, not unit-tested, regardless of whether ffmpeg happens to be on the dev
    machine's PATH) -- only reached via the `duration is None` early-return guard and the
    pure `parse_silencedetect_output` parser it feeds into.
"""
import types
import wave

import pytest

import tools.vad as vad


def _write_wav(path, pcm_bytes, rate=16000, channels=1, width=2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)


# ============================================================================
# voiced_ratio_to_verdict -- pure, no I/O
# ============================================================================

def test_voiced_ratio_to_verdict_empty_is_none():
    assert vad.voiced_ratio_to_verdict([]) is None


def test_voiced_ratio_to_verdict_all_silent_is_false():
    assert vad.voiced_ratio_to_verdict([False, False, False, False]) is False


def test_voiced_ratio_to_verdict_all_voiced_is_true():
    assert vad.voiced_ratio_to_verdict([True, True, True, True]) is True


def test_voiced_ratio_to_verdict_threshold_boundary_inclusive():
    # 3/10 == 0.3 exactly at the default min_voiced_ratio -> True (>=, not >)
    frames = [True, True, True] + [False] * 7
    assert vad.voiced_ratio_to_verdict(frames, min_voiced_ratio=0.3) is True


def test_voiced_ratio_to_verdict_just_below_threshold_is_false():
    # 2/10 == 0.2 < 0.3 -> False
    frames = [True, True] + [False] * 8
    assert vad.voiced_ratio_to_verdict(frames, min_voiced_ratio=0.3) is False


def test_voiced_ratio_to_verdict_custom_ratio():
    frames = [True, False, False, False]   # 0.25
    assert vad.voiced_ratio_to_verdict(frames, min_voiced_ratio=0.5) is False
    assert vad.voiced_ratio_to_verdict(frames, min_voiced_ratio=0.25) is True


# ============================================================================
# frame_pcm -- pure byte-slicer, no I/O
# ============================================================================

def test_frame_pcm_exact_multiple_no_remainder():
    frame_bytes = int(16000 * 0.03 * 2)   # 960 -- 30ms @ 16kHz/16-bit mono
    pcm = b"\x01" * (frame_bytes * 4)
    frames = vad.frame_pcm(pcm, sample_rate=16000, frame_ms=30, sample_width=2)
    assert len(frames) == 4
    assert all(len(f) == frame_bytes for f in frames)


def test_frame_pcm_drops_trailing_partial_frame():
    frame_bytes = int(16000 * 0.03 * 2)
    pcm = b"\x01" * (frame_bytes * 2 + 100)   # 100 leftover bytes, not a full frame
    frames = vad.frame_pcm(pcm, sample_rate=16000, frame_ms=30, sample_width=2)
    assert len(frames) == 2


def test_frame_pcm_empty_input_is_empty_list():
    assert vad.frame_pcm(b"", sample_rate=16000, frame_ms=30, sample_width=2) == []


def test_frame_pcm_shorter_than_one_frame_is_empty_list():
    frame_bytes = int(16000 * 0.03 * 2)
    pcm = b"\x01" * (frame_bytes - 1)
    assert vad.frame_pcm(pcm, sample_rate=16000, frame_ms=30, sample_width=2) == []


@pytest.mark.parametrize("frame_ms", [10, 20, 30])
def test_frame_pcm_all_valid_webrtcvad_durations(frame_ms):
    expected_bytes = int(16000 * (frame_ms / 1000.0) * 2)
    pcm = b"\x00" * (expected_bytes * 3)
    frames = vad.frame_pcm(pcm, sample_rate=16000, frame_ms=frame_ms, sample_width=2)
    assert len(frames) == 3
    assert all(len(f) == expected_bytes for f in frames)


# ============================================================================
# parse_silencedetect_output -- pure text parser, no subprocess
# ============================================================================

def test_parse_silencedetect_output_sums_completed_intervals():
    text = (
        "[silencedetect @ 0x1] silence_start: 0.0132\n"
        "[silencedetect @ 0x1] silence_end: 1.503 | silence_duration: 1.4898\n"
        "[silencedetect @ 0x1] silence_start: 2.1\n"
        "[silencedetect @ 0x1] silence_end: 2.6 | silence_duration: 0.5\n"
        "[silencedetect @ 0x1] silence_start: 4.9\n"    # still-open interval at EOF, no duration
    )
    assert vad.parse_silencedetect_output(text) == pytest.approx(1.9898)


def test_parse_silencedetect_output_no_matches_is_zero():
    assert vad.parse_silencedetect_output("nothing relevant here\n") == 0.0


def test_parse_silencedetect_output_empty_string_is_zero():
    assert vad.parse_silencedetect_output("") == 0.0


# ============================================================================
# read_wav_pcm / wav_duration_s -- stdlib `wave` I/O against a synthetic wav (no ffmpeg,
# no webrtcvad needed to build or read a valid 16k mono pcm_s16le wav).
# ============================================================================

def test_read_wav_pcm_roundtrips_matching_format(tmp_path):
    path = str(tmp_path / "gap.wav")
    pcm = b"\x11\x22" * 480   # 960 bytes -- one 30ms frame at 16k/16-bit mono
    _write_wav(path, pcm)
    assert vad.read_wav_pcm(path) == pcm


def test_read_wav_pcm_wrong_sample_rate_is_none(tmp_path):
    path = str(tmp_path / "gap.wav")
    _write_wav(path, b"\x00" * 960, rate=8000)
    assert vad.read_wav_pcm(path, expected_rate=16000) is None


def test_read_wav_pcm_wrong_channel_count_is_none(tmp_path):
    path = str(tmp_path / "gap.wav")
    _write_wav(path, b"\x00" * 960, channels=2)
    assert vad.read_wav_pcm(path) is None


def test_read_wav_pcm_missing_file_is_none(tmp_path):
    assert vad.read_wav_pcm(str(tmp_path / "does-not-exist.wav")) is None


def test_read_wav_pcm_not_a_wav_is_none(tmp_path):
    path = tmp_path / "gap.wav"
    path.write_bytes(b"this is not a wav file at all")
    assert vad.read_wav_pcm(str(path)) is None


def test_wav_duration_s_matches_frames_over_rate(tmp_path):
    path = str(tmp_path / "gap.wav")
    _write_wav(path, b"\x00" * (16000 * 2 * 2))   # 2 seconds @ 16k/16-bit mono
    assert vad.wav_duration_s(path) == pytest.approx(2.0)


def test_wav_duration_s_missing_file_is_none(tmp_path):
    assert vad.wav_duration_s(str(tmp_path / "nope.wav")) is None


# ============================================================================
# _vad_probe_webrtcvad -- integration-shaped test against a STUB webrtcvad module
# (monkeypatched onto tools.vad.webrtcvad). Validates OUR framing/call/aggregation code,
# NOT real webrtcvad classification -- see module docstring. Mirrors the
# tests/test_generate.py faster_whisper-stub pattern.
# ============================================================================

class _FakeVad:
    """Stand-in for webrtcvad.Vad: flags a frame 'voiced' iff it contains any non-zero
    byte, so the synthetic wav's actual silence/tone frame layout drives the verdict --
    same shape as a real VAD's frame-in/bool-out contract, without the real algorithm."""
    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    def is_speech(self, frame, sample_rate):
        self.calls.append((len(frame), sample_rate))
        return any(frame)


def _install_fake_webrtcvad(monkeypatch, vad_cls=_FakeVad):
    fake_module = types.ModuleType("webrtcvad")
    fake_module.Vad = vad_cls
    monkeypatch.setattr(vad, "webrtcvad", fake_module)
    return fake_module


def test_vad_probe_webrtcvad_unavailable_in_this_dev_venv():
    """Documents the real, current environment fact (not a mock): webrtcvad fails to
    import here (py3.14, no prebuilt wheel), so tools.vad.webrtcvad is None at import
    time, and the guard in _vad_probe_webrtcvad must degrade to None, not raise."""
    assert vad.webrtcvad is None


def test_vad_probe_webrtcvad_guard_returns_none_when_module_unavailable(monkeypatch):
    monkeypatch.setattr(vad, "webrtcvad", None)
    assert vad._vad_probe_webrtcvad("/does/not/matter.wav", aggressiveness=2) is None


def test_vad_probe_webrtcvad_stub_speech_present(tmp_path, monkeypatch):
    _install_fake_webrtcvad(monkeypatch)
    frame_bytes = int(16000 * 0.03 * 2)
    silence = b"\x00" * frame_bytes
    tone = b"\x10\x00" * (frame_bytes // 2)
    pcm = silence * 5 + tone * 5   # 10 frames, 5 voiced -> ratio 0.5 >= default 0.3
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, pcm)

    result = vad._vad_probe_webrtcvad(wav_path, aggressiveness=2)
    assert result is True


def test_vad_probe_webrtcvad_stub_speech_absent_below_threshold(tmp_path, monkeypatch):
    _install_fake_webrtcvad(monkeypatch)
    frame_bytes = int(16000 * 0.03 * 2)
    silence = b"\x00" * frame_bytes
    tone = b"\x10\x00" * (frame_bytes // 2)
    pcm = silence * 8 + tone * 2   # 10 frames, 2 voiced -> ratio 0.2 < default 0.3
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, pcm)

    result = vad._vad_probe_webrtcvad(wav_path, aggressiveness=2)
    assert result is False


def test_vad_probe_webrtcvad_stub_all_silent(tmp_path, monkeypatch):
    _install_fake_webrtcvad(monkeypatch)
    frame_bytes = int(16000 * 0.03 * 2)
    pcm = (b"\x00" * frame_bytes) * 10
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, pcm)

    assert vad._vad_probe_webrtcvad(wav_path, aggressiveness=1) is False


def test_vad_probe_webrtcvad_stub_frame_count_and_aggressiveness_passthrough(tmp_path, monkeypatch):
    captured = {}

    class RecordingFakeVad(_FakeVad):
        def __init__(self, mode):
            super().__init__(mode)
            captured["mode"] = mode
            captured["instance"] = self

    _install_fake_webrtcvad(monkeypatch, vad_cls=RecordingFakeVad)
    frame_bytes = int(16000 * 0.03 * 2)
    pcm = (b"\x00" * frame_bytes) * 7
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, pcm)

    vad._vad_probe_webrtcvad(wav_path, aggressiveness=3)
    assert captured["mode"] == 3
    assert len(captured["instance"].calls) == 7
    assert all(sr == 16000 for _len, sr in captured["instance"].calls)


def test_vad_probe_webrtcvad_stub_exception_is_none_not_raised(tmp_path, monkeypatch):
    class RaisingFakeVad:
        def __init__(self, mode):
            pass

        def is_speech(self, frame, sample_rate):
            raise RuntimeError("simulated webrtcvad C-extension failure")

    _install_fake_webrtcvad(monkeypatch, vad_cls=RaisingFakeVad)
    frame_bytes = int(16000 * 0.03 * 2)
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, b"\x00" * frame_bytes)

    assert vad._vad_probe_webrtcvad(wav_path, aggressiveness=2) is None


def test_vad_probe_webrtcvad_missing_wav_is_none(monkeypatch, tmp_path):
    _install_fake_webrtcvad(monkeypatch)
    assert vad._vad_probe_webrtcvad(str(tmp_path / "nope.wav"), aggressiveness=2) is None


def test_vad_probe_webrtcvad_unframeable_window_is_none(tmp_path, monkeypatch):
    """A window shorter than a single frame (e.g. an extraction that produced a near-empty
    wav) must not silently read as 'no voiced frames -> silent'; frame_pcm returns [] and
    voiced_ratio_to_verdict(([])) is None -> in_gap_vad_error, not a guessed False."""
    _install_fake_webrtcvad(monkeypatch)
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, b"\x00\x00")   # far shorter than one 960-byte frame
    assert vad._vad_probe_webrtcvad(wav_path, aggressiveness=2) is None


# ============================================================================
# vad_probe -- top-level dispatcher
# ============================================================================

def test_vad_probe_unknown_backend_is_none():
    assert vad.vad_probe("/x.wav", backend="not-a-real-backend") is None


def test_vad_probe_webrtcvad_backend_missing_file_is_none():
    # webrtcvad is genuinely unavailable in this dev venv -- guard fires either way, but
    # this also covers the "no wav" path if the guard were ever not the first check.
    assert vad.vad_probe("/definitely/not/a/real/path.wav", backend="webrtcvad") is None


def test_vad_probe_ffmpeg_silencedetect_missing_file_is_none():
    # wav_duration_s() fails fast on a missing file -> None, before any subprocess call.
    assert vad.vad_probe("/definitely/not/a/real/path.wav", backend="ffmpeg-silencedetect") is None


def test_vad_probe_dispatches_to_webrtcvad_stub(tmp_path, monkeypatch):
    _install_fake_webrtcvad(monkeypatch)
    frame_bytes = int(16000 * 0.03 * 2)
    pcm = (b"\x10\x00" * (frame_bytes // 2)) * 10   # all voiced
    wav_path = str(tmp_path / "gap.wav")
    _write_wav(wav_path, pcm)
    assert vad.vad_probe(wav_path, aggressiveness=2, backend="webrtcvad") is True


def test_vad_probe_never_raises_on_unexpected_backend_error(monkeypatch):
    """Belt-and-suspenders: even if a backend function itself raised (shouldn't, given its
    own internal guards), vad_probe's outer try/except must still degrade to None."""
    def boom(*a, **kw):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(vad, "_vad_probe_webrtcvad", boom)
    assert vad.vad_probe("/x.wav", backend="webrtcvad") is None
