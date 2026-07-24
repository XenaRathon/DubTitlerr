"""Unit tests for generate.py's needs_work() pre-filter (T18) and the ffprobe-detected
muxed backstop in process(). No CUDA/model needed -- the faster_whisper import is
stubbed so generate.py can be imported without the CUDA stack that only exists in the
subgen runtime image it's meant to run in (see generate.py's module docstring).

DIVERGENCE from specs/v1-polish/tasks.md T18 / spec.md Phase 4, case 7 ("ffprobe says
a Dubtitles track present but no stamp -> False (backstop)"): needs_work() is a
*stat-only* pre-filter -- its own comment in generate.py says so explicitly ("Cheap
pre-filter (stat only, no ffprobe/model)") -- and never calls ffprobe. The ffprobe-based
"already muxed" backstop actually lives one level down, in process(), guarded by
SKIP_IF_MUXED. Cases 1-6 below are tested against the real needs_work(); case 7 is
retargeted to process() instead of being force-fit into needs_work().
"""
import json
import sys
import types

import common


def _stub_faster_whisper():
    """generate.py does `from faster_whisper import WhisperModel` at module scope --
    that package (~2GB with torch+ctranslate2) is intentionally not installed in this
    dev venv; it only exists in the CUDA subgen image. Stub it so the module can be
    imported to test its pure/stat-only logic. Raises if anything actually tries to
    instantiate a model, so an accidental hermeticity violation fails loudly."""
    if "faster_whisper" in sys.modules:
        return
    fake = types.ModuleType("faster_whisper")

    class _UnusedWhisperModel:
        def __init__(self, *a, **kw):
            raise AssertionError("WhisperModel must never be instantiated by these tests")

    fake.WhisperModel = _UnusedWhisperModel
    sys.modules["faster_whisper"] = fake


_stub_faster_whisper()
import generate  # noqa: E402  (must follow the faster_whisper stub above)


def _real_needs_work():
    """Pull the real nested needs_work() out of main() by its code object, instead of
    reimplementing its checks in the test (which would only test a copy, never the real
    function). This is safe because needs_work() closes over none of main()'s locals
    (asserted below via co_freevars) -- it only touches module globals -- so binding its
    code object to generate's module dict reproduces it byte-for-byte."""
    for const in generate.main.__code__.co_consts:
        if isinstance(const, type(generate.main.__code__)) and const.co_name == "needs_work":
            assert const.co_freevars == (), "needs_work now closes over main() locals; extraction is stale"
            return types.FunctionType(const, vars(generate))
    raise AssertionError("generate.main() no longer defines a nested needs_work()")


def test_needs_work_matrix(tmp_path, monkeypatch):
    needs_work = _real_needs_work()
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)

    # 1. muxed .dubtitles.done stamp present and valid (size/mtime match) -> no work needed
    stamp = tmp_path / ("ep" + generate.STAMP_SUFFIX)
    common.write_stamp(str(stamp), str(v))
    assert needs_work(str(v)) is False
    stamp.unlink()

    # 2. .ass sidecar present -> already assembled -> no work needed
    ass = tmp_path / "ep.eng.dubtitles.ass"
    ass.write_text("x")
    assert needs_work(str(v)) is False
    ass.unlink()

    # 3. .srt sidecar + SKIP_IF_SRT=1 (default) -> already generated, awaiting assemble
    monkeypatch.setenv("SKIP_IF_SRT", "1")
    srt = tmp_path / "ep.eng.dubtitles.srt"
    srt.write_text("x")
    assert needs_work(str(v)) is False
    srt.unlink()

    # 4. .dubtitles.fail poison marker present -> skip (a prior hard crash; needs manual rm)
    fail = tmp_path / "ep.dubtitles.fail"
    fail.write_text("")
    assert needs_work(str(v)) is False
    fail.unlink()

    # 5. no sidecar/stamp/marker at all -> needs work
    assert needs_work(str(v)) is True

    # 6. stamp present but STALE (video replaced -> size mismatch) -> needs re-work
    common.write_stamp(str(stamp), str(v))
    v.write_bytes(b"y" * 5000)  # "replaced" download, different size
    assert needs_work(str(v)) is True


def test_ffprobe_muxed_backstop_in_process(monkeypatch, tmp_path):
    """Case 7 from T18/spec.md, retargeted to its real home: process()'s SKIP_IF_MUXED
    check. No .dubtitles.done stamp exists; ffprobe alone (stubbed here -- no real
    ffprobe/video/network) reports the Dubtitles track, and process() must still bail
    out as "already-muxed" before touching wav extraction or the model."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setenv("SKIP_IF_MUXED", "1")
    monkeypatch.setattr(generate, "has_dubtitles_track", lambda video: True)
    assert generate.process(str(v)) == "already-muxed"


# --- V2 A6: word_probs field on dubtitles.conf.json --------------------------

def test_card_word_probs_selects_by_time_overlap():
    """_card_word_probs() joins a card's [start, end] window against the full
    per-episode word list by time overlap (reflow's Card doesn't retain which whisper
    words built it -- see the function's docstring). A word entirely outside the
    window is excluded; a word overlapping it is included, rounded to 3 places."""
    words = [
        {"text": "Hello", "start": 0.0, "end": 0.3, "prob": 0.9512, "seg": 0},
        {"text": "there.", "start": 0.3, "end": 0.8, "prob": 0.10004, "seg": 0},
        {"text": "Later.", "start": 5.0, "end": 5.4, "prob": 0.99, "seg": 1},
    ]
    card = {"start": 0.0, "end": 0.8}
    assert generate._card_word_probs(card, words) == [0.951, 0.1]


def test_card_word_probs_empty_when_no_overlap():
    words = [{"text": "x", "start": 10.0, "end": 10.5, "prob": 0.5, "seg": 0}]
    assert generate._card_word_probs({"start": 0.0, "end": 1.0}, words) == []


class _FakeWord:
    def __init__(self, text, start, end, prob):
        self.word, self.start, self.end, self.probability = text, start, end, prob


class _FakeSegment:
    def __init__(self, start, end, nsp, words):
        self.start, self.end, self.no_speech_prob, self.words = start, end, nsp, words
        self.avg_logprob = -0.1  # only used by the no-word-timestamps fallback (unused here)


class _FakeModel:
    def __init__(self, segs):
        self._segs = segs

    def transcribe(self, *a, **kw):
        return self._segs, object()


def test_word_probs_written_to_conf_json(monkeypatch, tmp_path):
    """End-to-end through process(): a low-probability word inside an otherwise
    fine-avg_logprob card still shows up in dubtitles.conf.json's word_probs list
    (the field repair.has_low_prob_word() -- A7 -- reads), matching the card's word
    count in this no-correction, no-collapse case."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "has_dubtitles_track", lambda video: False)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    words = [_FakeWord(" Hello", 0.0, 0.3, 0.95), _FakeWord(" there.", 0.3, 0.9, 0.10)]
    seg = _FakeSegment(0.0, 0.9, 0.05, words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg]))

    assert generate.process(str(v)) == "ok"
    conf = json.loads((tmp_path / "ep.dubtitles.conf.json").read_text())
    assert len(conf) == 1
    assert conf[0]["word_probs"] == [0.95, 0.1]
    assert len(conf[0]["word_probs"]) == len(conf[0]["text"].split())
