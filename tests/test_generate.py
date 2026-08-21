"""Unit tests for generate.py's needs_work() pre-filter (T18) and process()'s skip
guards. No CUDA/model needed -- the faster_whisper import is stubbed so generate.py can
be imported without the CUDA stack that only exists in the subgen runtime image it's
meant to run in (see generate.py's module docstring).

DIVERGENCE from specs/v1-polish/tasks.md T18 / spec.md Phase 4, case 7 ("ffprobe says
a Dubtitles track present but no stamp -> False (backstop)"): that backstop no longer
exists. needs_work() is a *stat-only* pre-filter -- its own comment in generate.py says
so explicitly ("Cheap pre-filter (stat only, no ffprobe/model)") -- and never called
ffprobe; the ffprobe "already muxed" check that lived one level down in process() was
REMOVED by the strip-at-mux change (see
docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-design.md), because
mux.py now REPLACES the old Dubtitles track instead of refusing to touch the file.
Cases 1-6 below are tested against the real needs_work(); case 7 is inverted into
test_process_no_longer_skips_on_an_embedded_dubtitles_track.
"""
import json
import os
import sys
import types

import pytest

import common
import glossary
import qc
import reflow


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


def _ffprobe_reports_a_dubtitles_track(monkeypatch):
    """Make any ffprobe subprocess call answer "this file has a Dubtitles subtitle track"
    -- i.e. exactly the condition the retired SKIP_IF_MUXED backstop keyed on."""
    import types as _types

    def run(cmd, **kw):
        return _types.SimpleNamespace(
            stdout=json.dumps({"streams": [{"index": 2, "tags": {"title": "Dubtitles"}}]}),
            returncode=0)

    monkeypatch.setattr(generate.subprocess, "run", run)


def test_process_no_longer_skips_on_an_embedded_dubtitles_track(monkeypatch, tmp_path):
    """Case 7 from T18/spec.md, RETIRED. The SKIP_IF_MUXED ffprobe backstop is gone: an
    embedded Dubtitles track no longer means "done", because mux now replaces that track
    rather than duplicating it. Without this, a PIPELINE_VERSION regeneration would
    silently no-op on every already-dubbed episode. process() must run past the muxed
    check (it stops at the next gate -- no English audio -- proving it got there)."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    _ffprobe_reports_a_dubtitles_track(monkeypatch)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "no-eng-dub"


def test_process_ffprobe_muxed_helper_is_gone():
    """generate.has_dubtitles_track() had exactly one caller (the retired guard); leaving
    it behind would invite a future re-introduction of the same false-positive skip.
    mux.has_dubtitles_track(info) is the surviving one -- it verifies, it does not skip."""
    assert not hasattr(generate, "has_dubtitles_track")


def test_process_skips_on_a_current_version_stamp(monkeypatch, tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    common.write_stamp(str(tmp_path / ("ep" + generate.STAMP_SUFFIX)), str(v))
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "already-muxed"


def test_process_retranscribes_a_file_whose_stamp_is_from_an_older_pipeline_version(
        monkeypatch, tmp_path):
    """The version-aware stamp is now the sole skip guard, so it is also the sole
    regeneration trigger: bump PIPELINE_VERSION and the v1-stamped file transcribes again."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    common.write_stamp(str(tmp_path / ("ep" + generate.STAMP_SUFFIX)), str(v))
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.PIPELINE_VERSION + 1)
    _ffprobe_reports_a_dubtitles_track(monkeypatch)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "no-eng-dub"


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


def test_card_word_probs_joins_on_source_not_display_timing():
    """C6: the forward steal moves DISPLAY timing; the audio a card describes never
    moves. Joining on the display window hands the LLM the NEIGHBOUR's word confidences
    -- a false positive on the runt that stole the time and a false negative on the card
    that actually holds the mis-heard word. Task 9 repointed overlap_ref(); this is the
    other evidence consumer."""
    words = [{"text": " Huh.", "start": 10.0, "end": 10.05, "prob": 0.9, "seg": 0},
             {"text": " friend,", "start": 10.2, "end": 10.5, "prob": 0.05, "seg": 0}]
    runt = {"start": 10.0, "end": 10.83, "source_start": 10.0, "source_end": 10.05}
    displaced = {"start": 10.913, "end": 11.743, "source_start": 10.2, "source_end": 10.5}
    assert generate._card_word_probs(runt, words) == [0.9]
    assert generate._card_word_probs(displaced, words) == [0.05]


def test_card_word_probs_falls_back_to_display_timing():
    """Back-compat, matching overlap_ref(): a card without the C6 source window (a
    pre-C6 sidecar) still joins on its display window rather than raising."""
    words = [{"text": " x", "start": 0.0, "end": 0.5, "prob": 0.4, "seg": 0}]
    assert generate._card_word_probs({"start": 0.0, "end": 1.0}, words) == [0.4]


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


def test_word_probs_stay_with_their_own_card_across_a_forward_steal(monkeypatch, tmp_path):
    """End-to-end: a runt steals time from its successor, so the successor's DISPLAY
    window no longer contains its own audio. Each card's word_probs must still describe
    ITS text -- one probability per word, and the 0.05 on the card that actually
    contains the mis-heard word (repair.has_low_prob_word reads exactly this list)."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    words = [_FakeWord(" Huh.", 10.0, 10.05, 0.9),
             _FakeWord(" Hello", 10.2, 10.25, 0.9), _FakeWord(" there", 10.3, 10.35, 0.9),
             _FakeWord(" friend,", 10.36, 10.42, 0.05), _FakeWord(" okay?", 10.43, 10.5, 0.9)]
    seg = _FakeSegment(10.0, 10.5, 0.05, words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg]))

    assert generate.process(str(v)) == "ok"
    conf = json.loads((tmp_path / "ep.dubtitles.conf.json").read_text())
    assert len(conf) == 2
    assert conf[1]["start"] > conf[1]["source_start"]          # the steal really displaced it
    for row in conf:
        assert len(row.get("word_probs", [])) == len(row["text"].split())
    assert 0.05 not in conf[0]["word_probs"]                   # the runt is not credited with it
    assert 0.05 in conf[1]["word_probs"]                       # the card that said it is


# --- V2 A8: WHISPER_AUDIO_FILTER in extract_wav() -----------------------------

def test_extract_wav_appends_audio_filter_by_default(monkeypatch, tmp_path):
    """The default WHISPER_AUDIO_FILTER (highpass+compand) is appended as -af to the
    ffmpeg command, right before the output path."""
    calls = []
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 2000)   # extract_wav's success check is stat-only; run() is faked
    assert generate.extract_wav("ep.mkv", 1, str(wav)) is True
    cmd = calls[0]
    assert cmd[-1] == str(wav)
    assert cmd[-3:-1] == ["-af", generate.AUDIO_FILTER]
    assert generate.AUDIO_FILTER.startswith("highpass=f=80")  # matches the spec's Data contracts default


def test_process_logs_chown_failure_instead_of_swallowing(monkeypatch, tmp_path, capsys):
    """V2 C10: a chown failure (e.g. not running as root) is logged, not silently
    swallowed, and must not abort the episode."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    words = [_FakeWord(" Hello", 0.0, 0.3, 0.95)]
    seg = _FakeSegment(0.0, 0.3, 0.05, words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg]))

    def _boom(*a, **kw):
        raise OSError("Operation not permitted")
    monkeypatch.setattr(generate.os, "chown", _boom)

    assert generate.process(str(v)) == "ok"
    out = capsys.readouterr().out
    assert out.count("chown failed for") == 2  # srt + confp


def test_extract_wav_no_filter_when_empty(monkeypatch, tmp_path):
    """Empty WHISPER_AUDIO_FILTER ("" -- the pre-A8 opt-out) must NOT add -af at all,
    reproducing the exact pre-A8 ffmpeg command."""
    calls = []
    monkeypatch.setattr(generate, "AUDIO_FILTER", "")
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 2000)
    generate.extract_wav("ep.mkv", 1, str(wav))
    assert "-af" not in calls[0]


# --- V2 C1: glossaries/<show>.lastrun.json ------------------------------------

def test_lastrun_json_written_after_show(monkeypatch, tmp_path):
    """End-to-end through main(): after processing every episode in a --root-less,
    explicit-file run (one file = "a show" here), main() writes GLOSS_DIR's
    <show>.lastrun.json with the run's totals. GLOSS_DIR is redirected to tmp_path
    (module-level constant, not re-read from env at call time -- monkeypatch the
    attribute, same as AUDIO_FILTER above)."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setenv("SHOW_NAME", "Test Show")
    monkeypatch.setattr(generate, "GLOSS_DIR", str(tmp_path))

    words = [_FakeWord(" Hello", 0.0, 0.3, 0.95), _FakeWord(" there.", 0.3, 0.9, 0.10)]
    seg = _FakeSegment(0.0, 0.9, 0.05, words)
    monkeypatch.setattr(generate, "WhisperModel", lambda *a, **kw: _FakeModel([seg]))
    monkeypatch.setattr(sys, "argv", ["generate.py", str(v)])

    generate.main()

    lr = json.loads((tmp_path / "Test Show.lastrun.json").read_text())
    assert lr["show"] == "Test Show"
    assert lr["episodes_total"] == 1 and lr["episodes_transcribed"] == 1
    assert lr["cards_written"] == 1
    assert lr["dropped_hallucination"] == 0
    assert lr["collapsed_runs"] == 0
    assert lr["flagged"] == 1  # the low-prob "there." word drags avg_logprob into flag_reason()
    assert lr["model"] == generate.MODEL
    assert lr["elapsed_s"] >= 0
    assert "model_version" in lr and "glossary_version" in lr


def test_lastrun_json_show_falls_back_when_unset(monkeypatch, tmp_path):
    """No SHOW_NAME env and no glossary 'show' field -> falls back to a safe filename
    instead of writing a leading-dot ".lastrun.json" hidden file."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.delenv("SHOW_NAME", raising=False)
    monkeypatch.setattr(generate, "GLOSS_DIR", str(tmp_path))

    words = [_FakeWord(" Hello", 0.0, 0.3, 0.95)]
    seg = _FakeSegment(0.0, 0.3, 0.05, words)
    monkeypatch.setattr(generate, "WhisperModel", lambda *a, **kw: _FakeModel([seg]))
    monkeypatch.setattr(sys, "argv", ["generate.py", str(v)])

    generate.main()

    assert not (tmp_path / ".lastrun.json").exists()
    lr = json.loads((tmp_path / "unknown_show.lastrun.json").read_text())
    assert lr["show"] == "unknown_show"


# --- V2 C15: CUDA error gating uses exception TYPE, not a "cuda" substring match -------

def _fail_marker(video):
    return os.path.splitext(video)[0] + ".dubtitles.fail"


def test_runtimeerror_poisons_episode_and_exits(monkeypatch, tmp_path):
    """A RuntimeError (what faster-whisper/ctranslate2 actually raise for a real GPU
    error) must exit(3) and leave the .fail marker in place -- the episode stays
    poisoned so the loop relauncher's fresh-GPU-context restart skips it, matching the
    pre-C15 behavior for a genuine CUDA/OOM failure."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "WhisperModel", lambda *a, **kw: object())

    def _boom(video):
        open(_fail_marker(video), "w").close()   # simulate process()'s in-flight marker
        raise RuntimeError("CUDA error: out of memory")

    monkeypatch.setattr(generate, "process", _boom)
    monkeypatch.setattr(sys, "argv", ["generate.py", str(v)])

    with pytest.raises(SystemExit) as ei:
        generate.main()
    assert ei.value.code == 3
    assert os.path.exists(_fail_marker(str(v)))  # NOT removed -- stays poisoned


def test_non_runtimeerror_mentioning_cuda_does_not_poison(monkeypatch, tmp_path):
    """The OLD substring-match gate (`"cuda" in str(e).lower()`) would have falsely
    poisoned/exited on this: a ValueError that merely mentions "cuda" in its message,
    with nothing to do with the GPU context. The new isinstance(e, RuntimeError) gate
    must NOT exit, must clear the .fail marker so the episode retries next sweep, and
    must persist a JSON crash record."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "WhisperModel", lambda *a, **kw: object())
    monkeypatch.setattr(generate, "GLOSS_DIR", str(tmp_path))  # let main() finish (C1 write)

    def _boom(video):
        open(_fail_marker(video), "w").close()
        raise ValueError("bad value near a cuda-adjacent buffer index")

    monkeypatch.setattr(generate, "process", _boom)
    monkeypatch.setattr(sys, "argv", ["generate.py", str(v)])

    generate.main()  # must NOT sys.exit

    assert not os.path.exists(_fail_marker(str(v)))  # cleared -- retries next sweep
    crash = json.loads((tmp_path / "ep.dubtitles.crash.json").read_text())
    assert crash["exc_type"] == "ValueError"
    assert crash["path"] == str(v)
    assert "cuda" in crash["msg"].lower()


# --- a version bump must not be defeated by a leftover sidecar ----------------
#
# mux removes sidecars only AFTER stamping, so a crash/kill in that window (or a
# skip-no-room mux) leaves a stale stamp beside a stale .ass/.srt. The sidecar-existence
# skips below are not version-aware on their own: without the clear-out, generate would
# return "already-ass" forever while mux re-embedded that OLD subtitle and stamped it
# CURRENT -- the episode would read as regenerated while still containing v1 content.

def _stale_stamped(tmp_path, monkeypatch, leftovers=(), fresh=()):
    """A file stamped by a superseded pipeline version, with `leftovers` (sidecars from
    that same old run, so OLDER than the stamp) and/or `fresh` sidecars (this
    regeneration's own work, written after the stamp)."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    stamp = tmp_path / ("ep" + generate.STAMP_SUFFIX)
    common.write_stamp(str(stamp), str(v))
    stamp_mtime = stamp.stat().st_mtime
    for name in leftovers:
        p = tmp_path / name
        p.write_text("output from the previous pipeline version")
        os.utime(p, (stamp_mtime - 60, stamp_mtime - 60))   # written before the stamp
    for name in fresh:
        p = tmp_path / name
        p.write_text("freshly transcribed, awaiting mux")
        os.utime(p, (stamp_mtime + 60, stamp_mtime + 60))   # written after the stamp
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.PIPELINE_VERSION + 1)
    return v


def test_stale_version_file_discards_its_leftover_ass_sidecar(monkeypatch, tmp_path):
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.eng.dubtitles.ass"])
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "no-eng-dub"      # NOT "already-ass"
    assert not (tmp_path / "ep.eng.dubtitles.ass").exists()


def test_stale_version_file_discards_its_leftover_srt_and_conf(monkeypatch, tmp_path):
    v = _stale_stamped(tmp_path, monkeypatch,
                       leftovers=["ep.eng.dubtitles.srt", "ep.dubtitles.conf.json"])
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "no-eng-dub"      # NOT "already-srt"
    assert not (tmp_path / "ep.eng.dubtitles.srt").exists()
    assert not (tmp_path / "ep.dubtitles.conf.json").exists()


def test_current_version_file_keeps_its_sidecars(monkeypatch, tmp_path):
    """Only a STALE-version stamp condemns the sidecars. A file awaiting its first mux
    (current version, sidecar present) must still skip and keep its work."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    (tmp_path / "ep.eng.dubtitles.ass").write_text("fresh, awaiting mux")
    assert generate.process(str(v)) == "already-ass"
    assert (tmp_path / "ep.eng.dubtitles.ass").exists()


def test_needs_work_true_for_a_stale_version_file_with_a_sidecar(monkeypatch, tmp_path):
    """The stat-only pre-filter has to agree, or process() is never reached and the
    clear-out above never runs."""
    needs_work = _real_needs_work()
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.eng.dubtitles.ass"])
    assert needs_work(str(v)) is True


def test_stale_version_file_keeps_a_sidecar_newer_than_its_stamp(monkeypatch, tmp_path):
    """The stamp only advances when mux succeeds, so between "generate re-transcribed" and
    "mux stamped" a FRESH sidecar sits beside a STALE stamp -- for at least MERGE_INTERVAL,
    and indefinitely if the mux keeps failing (skip-no-room, verify-*). Discarding it there
    would re-run Whisper on every resume pass; worse, gen_loop.sh's stall detector counts
    .srt files, so the deletions read as "no progress" and it abandons the show
    mid-regeneration. A sidecar newer than the stamp is this run's own work: keep it."""
    v = _stale_stamped(tmp_path, monkeypatch, fresh=["ep.eng.dubtitles.srt",
                                                     "ep.dubtitles.conf.json"])
    assert generate.process(str(v)) == "already-srt"
    assert (tmp_path / "ep.eng.dubtitles.srt").exists()
    assert (tmp_path / "ep.dubtitles.conf.json").exists()


def test_stale_version_file_discards_only_the_leftovers_not_the_fresh_work(monkeypatch, tmp_path):
    """Mid-regeneration state: the old .ass is still lying around from the interrupted
    previous mux, while the .srt is what this run just transcribed. The old assembly must
    go (or mux would embed it) and the new transcription must stay -- so the episode ends
    up correctly waiting on assemble, not re-transcribing."""
    v = _stale_stamped(tmp_path, monkeypatch,
                       leftovers=["ep.eng.dubtitles.ass"], fresh=["ep.eng.dubtitles.srt"])
    assert generate.process(str(v)) == "already-srt"
    assert not (tmp_path / "ep.eng.dubtitles.ass").exists()   # last version's assembly
    assert (tmp_path / "ep.eng.dubtitles.srt").exists()       # this run's transcription


def test_poison_marked_stale_file_keeps_its_sidecars(monkeypatch, tmp_path):
    """A .dubtitles.fail file is never transcribed, so discarding its sidecars would be
    pure destruction -- it would leave mux with nothing to embed until an operator
    manually removes the marker."""
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.eng.dubtitles.ass"])
    (tmp_path / "ep.dubtitles.fail").write_text("")
    assert generate.process(str(v)) == "already-ass"     # skipped, and nothing destroyed
    assert (tmp_path / "ep.eng.dubtitles.ass").exists()


def test_stale_version_file_parks_its_leftover_qc_sidecar(monkeypatch, tmp_path):
    """A superseded qc.json is last version's MEASUREMENT: left at its own path it
    aggregates as this version's, and it was not in the suffix list at all."""
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.dubtitles.qc.json"])
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: None)
    assert generate.process(str(v)) == "no-eng-dub"
    assert not (tmp_path / "ep.dubtitles.qc.json").exists()
    assert (tmp_path / "ep.dubtitles.qc.json.stale").exists()


def _infeasible_model(monkeypatch, generate_mod):
    monkeypatch.setattr(generate_mod, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate_mod, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate_mod, "media_duration", lambda path: 0.5)
    monkeypatch.setattr(generate_mod, "WMODEL", _displaced_pair_model())


def test_a_version_bump_that_ends_infeasible_leaves_the_prior_output_recoverable(monkeypatch, tmp_path):
    """F5. The stale-version clear-out runs BEFORE the already-srt guard, so under the
    DEFAULT SKIP_IF_SRT=1 a version bump destroyed the previous srt and conf and only
    THEN hit CascadeInfeasible -- ending with no srt, no conf and a permanent .fail
    marker that retires the episode until an operator deletes it by hand. The prior
    output must survive its own replacement failing."""
    v = _stale_stamped(tmp_path, monkeypatch,
                       leftovers=["ep.eng.dubtitles.srt", "ep.dubtitles.conf.json"])
    _infeasible_model(monkeypatch, generate)
    assert generate.process(str(v)) == "cascade-infeasible"
    assert (tmp_path / "ep.dubtitles.fail").exists()
    assert not (tmp_path / "ep.eng.dubtitles.srt").exists()        # still not muxable...
    assert (tmp_path / "ep.eng.dubtitles.srt.stale").exists()      # ...but not destroyed
    assert (tmp_path / "ep.dubtitles.conf.json.stale").exists()


def test_the_infeasible_sidecar_records_what_survived(monkeypatch, tmp_path, capsys):
    """"Recoverable" is only true if someone can find out. The sidecar names the parked
    files and the log line says how to get them back."""
    v = _stale_stamped(tmp_path, monkeypatch,
                       leftovers=["ep.eng.dubtitles.srt", "ep.dubtitles.conf.json"])
    _infeasible_model(monkeypatch, generate)
    generate.process(str(v))
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    ev = [e for e in doc["events"] if e.get("reason") == "cascade_infeasible"][0]
    assert ev["retained_prior_output"] == ["ep.dubtitles.conf.json.stale",
                                           "ep.eng.dubtitles.srt.stale"]
    assert "recover" in capsys.readouterr().out


def test_a_successful_regeneration_drops_the_parked_sidecars(monkeypatch, tmp_path):
    """The parked copies are insurance against a failed replacement, not litter: once
    this run has written its own srt and conf they go."""
    v = _stale_stamped(tmp_path, monkeypatch,
                       leftovers=["ep.eng.dubtitles.ass", "ep.eng.dubtitles.srt",
                                  "ep.dubtitles.conf.json", "ep.dubtitles.qc.json"])
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setattr(generate, "WMODEL", _short_card_model())
    assert generate.process(str(v)) == "ok"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".stale")] == []
    assert (tmp_path / "ep.eng.dubtitles.srt").exists()
    assert (tmp_path / "ep.dubtitles.conf.json").exists()


def test_needs_work_false_for_a_poison_marked_stale_file(monkeypatch, tmp_path):
    """needs_work must agree with process(): a poisoned file is not work, so it must not
    drag the ~40s model load into a sweep that has nothing else to do."""
    needs_work = _real_needs_work()
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.eng.dubtitles.ass"])
    (tmp_path / "ep.dubtitles.fail").write_text("")
    assert needs_work(str(v)) is False


# --- QC: MIN_DUR floor in the violation counter, and the sidecar write -------

def _qc_card(start, end, text, **kw):
    d = {"start": start, "end": end, "text": text}
    d.update(kw)
    return d


def test_violation_counter_now_has_a_min_dur_floor(tmp_path):
    rec = qc.Recorder()
    generate._record_qc(rec, [_qc_card(0.0, 0.02, "Cool!")])          # 0.02s, 294 cps
    c = rec.build(show="S", episode="E", stem="x")["counters"]
    assert c["ordinary_under_min_dur_after"] == 1
    assert c["violations"] == 1                   # floor breach IS a violation


def test_exact_min_dur_card_is_not_a_violation():
    rec = qc.Recorder()
    generate._record_qc(rec, [_qc_card(11.51, round(11.51 + reflow.MIN_DUR, 3), "ok")])
    assert rec.build(show="S", episode="E", stem="x")["counters"]["violations"] == 0


def test_a_quarantined_orphan_is_not_counted_as_an_ordinary_short_card():
    """B1/v4: the split exists so a quarantined orphan cannot break the acceptance
    assertion it was exempted from. _record_qc saw (start, end, text) tuples with the
    orphan flag already discarded, so EVERY short card landed in the ordinary counter
    and orphan_under_min_dur_after could never be non-zero."""
    rec = qc.Recorder()
    generate._record_qc(rec, [_qc_card(0.0, 0.40, "Huh.", orphan=True)])
    c = rec.build(show="S", episode="E", stem="x")["counters"]
    assert c["orphan_under_min_dur_after"] == 1
    assert c["ordinary_under_min_dur_after"] == 0   # must stay 0 at acceptance
    assert c["violations"] == 1                     # still a violation, just an exempt one
    assert c["orphan_candidates_fixed"] == 0        # quarantine is not a fix


def test_required_extension_is_observed_per_card():
    """B1: `chars / MAX_CPS - duration` -- the quantity the deferred cps-stealing
    decision consumes, and which a bare over_cps COUNT cannot supply. Negative on a
    card with reading slack, so the quantiles describe the whole population."""
    rec = qc.Recorder()
    generate._record_qc(rec, [_qc_card(0.0, 1.0, "a" * 34), _qc_card(2.0, 4.0, "ok"),
                              _qc_card(5.0, 7.0, "fine"), _qc_card(8.0, 10.0, "also fine")])
    q = rec.build(show="S", episode="E", stem="x")["quantiles"]["required_extension"]
    assert q["max"] == pytest.approx(34 / reflow.MAX_CPS - 1.0)      # 1.0s short
    assert q["p50"] < 0                                              # the cards with slack


def test_card_faults_is_the_single_profile_definition():
    """B2/C4a: ONE predicate behind both the sidecar's `violations` counter and the
    console line's `violations=`. Layout comes from reflow.layout_faults (the single
    definition); the duration floor and ceiling are timing, not layout, so they are
    added here rather than duplicated into reflow's layout profile."""
    assert generate._card_faults("Fine.", 2.0) == []
    assert generate._card_faults("Cool!", 0.40) == ["under_min_dur"]
    assert generate._card_faults("Fine.", reflow.MAX_DUR + 1.0) == ["over_max_dur"]
    for text, dur in (("a" * 43, 5.0), ("a\nb\nc", 5.0), ("a " * 43, 9.0), ("a" * 40, 1.0)):
        layout = reflow.layout_faults(text, dur)
        assert layout                                     # fixture really is invalid
        assert generate._card_faults(text, dur)[:len(layout)] == layout


def test_card_at_exactly_max_cps_is_not_a_fault():
    """Every threshold comparison carries EPS -- the log line's hand-rolled cps test
    did not, so a card could be counted by the console and not by the sidecar."""
    assert generate._card_faults("a" * 17, 1.0) == []


def _short_card_model():
    """One card the timing pass cannot lift to MIN_DUR: the audio ends where it does
    (A6's end-of-episode clamp), so it ships short -- the defect this branch exists for."""
    return _FakeModel([_FakeSegment(0.0, 0.40, 0.05, [_FakeWord(" Cool!", 0.0, 0.40, 0.95)])])


def test_log_line_violation_count_agrees_with_the_sidecar(monkeypatch, tmp_path, capsys):
    """B2: the console counter validated every ceiling and no floor, so the operator-facing
    number said 0 on the exact episodes the sidecar scored as violating."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: 0.40)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _short_card_model())

    assert generate.process(str(v)) == "ok"
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    assert doc["counters"]["violations"] == 1              # the sidecar sees the floor breach
    line = [ln for ln in capsys.readouterr().out.splitlines() if " cards=" in ln][0]
    assert f"violations={doc['counters']['violations']}" in line
    assert f"over_cps={doc['counters']['over_cps']}" in line


def test_over_chars_is_counted_not_only_evented():
    """F4: over_chars is a layout_faults dimension no counter tracked. Two LEGAL 42-char
    lines totalling 85 visible chars pass every per-line check, so the card emitted a
    layout_exception event whose reason no counter could answer for -- and, being
    pre-existing rather than correction-introduced, it goes in the evictable ordinary
    event list. It was the one fault class that could be lost entirely."""
    rec = qc.Recorder()
    generate._record_qc(rec, [_qc_card(0.0, 6.0, "a" * 42 + "\n" + "b" * 42)])
    c = rec.build(show="S", episode="E", stem="x")["counters"]
    assert c["over_chars"] == 1
    assert c["violations"] == 1
    assert (c["over_line_len"], c["over_cps"]) == (0, 0)     # legal on every OTHER dimension


def test_qc_sidecar_is_written_next_to_conf(monkeypatch, tmp_path):
    """Drives generate's real write path (process()), mirroring
    test_word_probs_written_to_conf_json's fake-model setup, and asserts the QC
    sidecar lands next to conf.json with cards_after populated."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    words = [_FakeWord(" Hello", 0.0, 0.3, 0.95), _FakeWord(" there.", 0.3, 0.9, 0.10)]
    seg = _FakeSegment(0.0, 0.9, 0.05, words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg]))

    assert generate.process(str(v)) == "ok"
    qc_path = tmp_path / "ep.dubtitles.qc.json"
    assert qc_path.exists()
    doc = json.loads(qc_path.read_text())
    assert doc["counters"]["cards_after"] == 1
    assert doc["stem"] == str(tmp_path / "ep")


def test_qc_records_the_before_half_of_the_pair(monkeypatch, tmp_path):
    """cards_before and ordinary_under_min_dur_before were declared and never written,
    so "before vs after" was unanswerable and a retired episode's sidecar was
    indistinguishable from a flawless one on every counter but cascade_infeasible.
    The fixture is one runt ("Monster.") absorbed backward into its predecessor."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    words = [_FakeWord(" Fine.", 0.0, 1.0, 0.95), _FakeWord(" Monster.", 1.08, 1.38, 0.95)]
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([_FakeSegment(0.0, 1.38, 0.05, words)]))

    assert generate.process(str(v)) == "ok"
    c = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())["counters"]
    assert c["cards_before"] == 2                      # the timing layer saw two groups
    assert c["cards_after"] == 1
    assert c["ordinary_under_min_dur_before"] == 1     # one runt arrived...
    assert c["ordinary_under_min_dur_after"] == 0      # ...and none shipped


def test_qc_counts_flagged_and_low_conf(monkeypatch, tmp_path, capsys):
    """flagged and low_conf were computed in process() and thrown away -- the log line
    reported them, the persisted sidecar always said 0."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    words = [_FakeWord(" Huh.", 10.0, 10.05, 0.9), _FakeWord(" Hello", 10.2, 10.25, 0.9),
             _FakeWord(" there", 10.3, 10.35, 0.9), _FakeWord(" friend,", 10.36, 10.42, 0.05),
             _FakeWord(" okay?", 10.43, 10.5, 0.9)]
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([_FakeSegment(10.0, 10.5, 0.05, words)]))

    assert generate.process(str(v)) == "ok"
    c = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())["counters"]
    line = [ln for ln in capsys.readouterr().out.splitlines() if " cards=" in ln][0]
    assert c["low_conf"] > 0
    assert f"low-conf={c['low_conf']} " in line          # sidecar and log agree
    assert f"flagged={c['flagged']} " in line


# --- QC: orphan_candidates / merged_backward (deferred scope from Task 5) ----

def test_qc_counts_orphan_candidates_but_never_marks_them_fixed(monkeypatch, tmp_path):
    """reflow.reflow() flags a stranded fragment as "orphan"; process() must count it
    into orphan_candidates. Quarantining an orphan is not a fix -- orphan_candidates_fixed
    must stay 0 here, since nothing in this pipeline claims to have fixed it."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    # seg0: "Hello there." (finished sentence) then a stray "Wait" -- an orphan:
    # its true utterance "for me." starts in seg1 after a real (>GAP_MAX) pause.
    seg0_words = [_FakeWord(" Hello", 0.0, 0.3, 0.95), _FakeWord(" there.", 0.4, 0.7, 0.95),
                  _FakeWord(" Wait", 0.8, 1.0, 0.95)]
    seg1_words = [_FakeWord(" for", 1.6, 1.9, 0.95), _FakeWord(" me.", 2.0, 2.3, 0.95)]
    seg0 = _FakeSegment(0.0, 1.0, 0.05, seg0_words)
    seg1 = _FakeSegment(1.6, 2.3, 0.05, seg1_words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg0, seg1]))

    assert generate.process(str(v)) == "ok"
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    c = doc["counters"]
    assert c["orphan_candidates"] == 1
    assert c["orphan_candidates_fixed"] == 0
    assert c["merged_backward"] == 0


def test_qc_counts_a_genuine_backward_merge(monkeypatch, tmp_path):
    """A sentence tail split into its own too-short card ("Monster.") merges backward
    into its predecessor -- process() must count that absorption into merged_backward."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")

    words = [_FakeWord(" Fine.", 0.0, 1.0, 0.95), _FakeWord(" Monster.", 1.08, 1.38, 0.95)]
    seg = _FakeSegment(0.0, 1.38, 0.05, words)
    monkeypatch.setattr(generate, "WMODEL", _FakeModel([seg]))

    assert generate.process(str(v)) == "ok"
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    c = doc["counters"]
    assert c["merged_backward"] == 1
    assert c["cards_after"] == 1


# --- C6 + Task 7 loose end: source timing in conf.json, audio duration to reflow ---

class _FakeRun:
    def __init__(self, stdout):
        self.stdout = stdout


def test_media_duration_parses_ffprobe_format_duration(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _FakeRun(json.dumps({"format": {"duration": "1421.376000"}}))
    monkeypatch.setattr(generate.subprocess, "run", fake_run)
    assert generate.media_duration("ep.wav") == pytest.approx(1421.376)
    assert "format=duration" in calls[0]


def test_media_duration_is_none_when_ffprobe_fails(monkeypatch):
    def boom(cmd, **kw):
        raise OSError("no ffprobe")
    monkeypatch.setattr(generate.subprocess, "run", boom)
    assert generate.media_duration("ep.wav") is None


def test_media_duration_is_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: _FakeRun("N/A"))
    assert generate.media_duration("ep.wav") is None


def _displaced_pair_model():
    """A runt followed by a surplus card: the second card's DISPLAY start is stolen
    forward, its spoken onset is not."""
    words = [_FakeWord(" Oh.", 0.0, 0.10, 0.9),
             _FakeWord(" A much longer line here.", 0.15, 3.0, 0.9)]
    return _FakeModel([_FakeSegment(0.0, 3.0, 0.05, words)])


def test_conf_json_carries_source_and_display_timing(monkeypatch, tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _displaced_pair_model())

    assert generate.process(str(v)) == "ok"
    conf = json.loads((tmp_path / "ep.dubtitles.conf.json").read_text())
    assert len(conf) == 2
    assert (conf[0]["source_start"], conf[0]["source_end"]) == (0.0, 0.1)
    assert (conf[1]["source_start"], conf[1]["source_end"]) == (0.15, 3.0)
    assert conf[1]["start"] > conf[1]["source_start"]      # display displaced by the steal
    assert all(round(c[k], 3) == c[k] for c in conf for k in ("source_start", "source_end"))


def test_process_passes_the_media_duration_into_reflow(monkeypatch, tmp_path):
    """reflow.time_cards()'s end-of-audio guard is only live if generate.py measures
    the audio and hands the value over."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: 3.0)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _displaced_pair_model())

    seen = {}
    real = generate.reflow.reflow

    def spy(words, segments, **kw):
        seen.update(kw)
        return real(words, segments, **kw)
    monkeypatch.setattr(generate.reflow, "reflow", spy)

    assert generate.process(str(v)) == "ok"
    assert seen["audio_duration"] == 3.0


def test_media_duration_failure_never_fails_the_episode(monkeypatch, tmp_path):
    """An ffprobe failure means "unbounded", not a dead episode."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _displaced_pair_model())

    assert generate.process(str(v)) == "ok"


# --- QC: cascade telemetry, and the A2b infeasible-cascade contract ----------

def test_qc_counts_what_the_timing_cascade_did(monkeypatch, tmp_path):
    """time_cards()'s cascade records were dropped on the floor, so the sidecar could
    never say what the timing pass actually did. A runt stealing from a surplus
    successor is one steal, one displaced card, one shortened card, depth 1."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _displaced_pair_model())

    assert generate.process(str(v)) == "ok"
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    c = doc["counters"]
    assert c["stolen"] == 1
    assert c["displaced"] == 1
    assert c["shortened_by_neighbour"] == 1
    assert c["unfixable_runts"] == 0
    assert c["cascade_infeasible"] == 0
    assert doc["quantiles"]["cascade_depth"]["max"] == 1.0
    assert doc["quantiles"]["displacement"]["max"] > 0.0


def _infeasible_setup(monkeypatch, tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: 0.5)   # shorter than the steal needs
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", _displaced_pair_model())
    return v


def test_cascade_infeasible_writes_no_subtitle_and_poisons_the_episode(monkeypatch, tmp_path):
    """A2b, strict: a card list that cannot satisfy the temporal invariants is
    structurally unfixable. Nothing is written for muxing, and the .dubtitles.fail
    poison marker retires the episode instead of letting every sweep re-fail it."""
    v = _infeasible_setup(monkeypatch, tmp_path)
    assert generate.process(str(v)) == "cascade-infeasible"
    assert (tmp_path / "ep.dubtitles.fail").exists()
    assert not (tmp_path / "ep.eng.dubtitles.srt").exists()
    assert not (tmp_path / "ep.dubtitles.conf.json").exists()
    assert not (tmp_path / "ep.eng.dubtitles.ass").exists()
    assert generate.process(str(v)) == "skip-prior-crash"    # the next sweep moves on


def test_cascade_infeasible_never_reaches_main_and_never_clears_the_marker(monkeypatch, tmp_path):
    """main() treats a non-RuntimeError as "not the episode's fault" and REMOVES the
    marker, so a leaked CascadeInfeasible would re-fail forever. process() must swallow it."""
    v = _infeasible_setup(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(generate, "log", lambda *a: seen.append(" ".join(str(x) for x in a)))
    generate.process(str(v))
    assert (tmp_path / "ep.dubtitles.fail").exists()
    assert not (tmp_path / "ep.dubtitles.crash.json").exists()
    assert any("cascade" in m.lower() for m in seen)


def test_cascade_infeasible_still_writes_the_qc_sidecar(monkeypatch, tmp_path):
    """A failed episode is exactly when the evidence matters most: the sidecar records
    the counter plus the shift accounting, with requested == applied + residual."""
    v = _infeasible_setup(monkeypatch, tmp_path)
    generate.process(str(v))
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    assert doc["counters"]["cascade_infeasible"] == 1
    ev = [e for e in doc["events"] if e.get("reason") == "cascade_infeasible"]
    assert len(ev) == 1
    e = ev[0]
    assert e["residual_shift"] > 0
    assert e["requested_shift"] == pytest.approx(e["applied_shift"] + e["residual_shift"], abs=reflow.EPS)


# --- C7 (task 10): post-glossary re-wrap and validate -------------------------
#
# Layout is decided by reflow() BEFORE glossary.correct() rewrites the text, so a
# correction can invalidate a layout nothing re-checks. The pass re-wraps through the
# SAME wrapping function and validates the whole profile on the RESULT -- measured
# invalidity, never a growth proxy, because wrapping feasibility depends on where word
# boundaries fall, not on total length.

# 84 chars, word boundaries at 20/41/62 -> a legal 42/41 split exists.
_WRAPPABLE_84 = " ".join(("a" * 20, "b" * 20, "c" * 20, "d" * 21))
# 84 chars again -- length-NEUTRAL, boundaries moved to 20/45/62 -> no split fits 2x42.
_UNWRAPPABLE_84 = " ".join(("a" * 20, "b" * 24, "c" * 16, "d" * 21))


def _card(text, start=0.0, end=6.0, before=None):
    return {"start": start, "end": end, "text": text,
            "pre_correction_text": text if before is None else before}


def _layout_events(rec):
    """Read through build() rather than rec.events: correction-introduced exceptions are
    recorded as PRIORITY events so a flood of pre-existing ones cannot evict them, and
    build() is what merges the two lists into the sidecar's single `events` array."""
    doc = rec.build(show="S", episode="E", stem="x")
    return [e for e in doc["events"] if e.get("reason") == "layout_exception"]


def test_length_neutral_correction_that_breaks_wrapping_is_detected():
    """Same total length, different word boundaries -> no legal 2x42 split. The
    correction is KEPT (the right name beats the layout profile) and the card is
    recorded as a layout exception."""
    assert len(_WRAPPABLE_84) == len(_UNWRAPPABLE_84) == reflow.MAX_CHARS
    rec = qc.Recorder()
    cards = [_card(_UNWRAPPABLE_84, before=_WRAPPABLE_84)]
    generate._revalidate_after_correction(rec, cards)
    assert rec.counters["layout_exceptions"] == 1
    assert cards[0]["text"].replace("\n", " ") == _UNWRAPPABLE_84   # kept, not reverted
    e = _layout_events(rec)[0]
    assert e["layout_exception_reason"] == ["over_line_len"]
    assert e["caused_by_correction"] is True
    assert max(e["line_lengths"]) > reflow.MAX_LINE
    assert e["cps"] == pytest.approx(reflow.MAX_CHARS / 6.0, abs=0.01)
    assert e["start"] == 0.0 and e["end"] == 6.0


def test_two_char_growth_on_a_short_card_records_over_cps():
    """+2 characters on a MIN_DUR card adds ~2.4 cps -- enough to cross 17 cps on its
    own, with the line length never in question."""
    before, after = "Meet the shojo", "Meet the Shoujou"
    dur = reflow.MIN_DUR
    assert reflow.card_cps(before, dur) <= reflow.MAX_CPS + reflow.EPS
    assert reflow.card_cps(after, dur) > reflow.MAX_CPS + reflow.EPS
    rec = qc.Recorder()
    cards = [_card(after, start=1.0, end=1.0 + dur, before=before)]
    generate._revalidate_after_correction(rec, cards)
    assert rec.counters["layout_exceptions"] == 1
    assert cards[0]["text"] == after
    e = _layout_events(rec)[0]
    assert e["layout_exception_reason"] == ["over_cps"]
    assert e["caused_by_correction"] is True
    assert e["cps"] > reflow.MAX_CPS


def test_a_card_already_unwrappable_before_correction_is_not_blamed_on_the_glossary():
    """~1% of cards have no word boundary near the midpoint and wrap_balance falls
    through to its over-long fallback with no glossary involved. Those are reported,
    but they must not bump the counter C7's revisit trigger reads."""
    rec = qc.Recorder()
    cards = [_card(_UNWRAPPABLE_84)]                       # correction changed nothing
    generate._revalidate_after_correction(rec, cards)
    assert rec.counters["layout_exceptions"] == 0
    e = _layout_events(rec)[0]
    assert e["caused_by_correction"] is False
    assert e["pre_existing_reason"] == ["over_line_len"]


def test_a_valid_corrected_card_is_rewrapped_and_records_nothing():
    rec = qc.Recorder()
    cards = [_card("x" * 41 + " " + "y" * 42)]             # 84 chars, splits 41/42
    generate._revalidate_after_correction(rec, cards)
    assert cards[0]["text"] == "x" * 41 + "\n" + "y" * 42
    assert rec.counters["layout_exceptions"] == 0
    assert _layout_events(rec) == []


def test_rewrap_uses_the_one_wrapping_algorithm_not_the_per_line_correction():
    """Correcting per line preserves the OLD break. Re-wrapping the joined text through
    reflow.wrap_balance is what makes generation have exactly one wrapping algorithm."""
    joined = "the quickquick brown fox jumps over lazy dogs and zzz runs away fast today"
    per_line = "the quickquick brown fox jumps over lazy\ndogs and zzz runs away fast today"
    rec = qc.Recorder()
    cards = [_card(per_line, end=8.0)]
    generate._revalidate_after_correction(rec, cards)
    assert cards[0]["text"] == reflow.wrap_balance(joined)
    assert cards[0]["text"] != per_line


def _one_card_model(tokens, step=0.35):
    words, t = [], 0.0
    for w in tokens:
        words.append(_FakeWord(" " + w, t, t + step, 0.95)); t += step
    return _FakeModel([_FakeSegment(0.0, t, 0.05, words)])


def test_the_text_validated_is_the_text_written(monkeypatch, tmp_path):
    """End to end: the srt and conf.json carry the re-wrapped corrected text, and the
    qc sidecar's exception (if any) describes that same text."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "GLOSS",
                        glossary.load_dict({"hard_fixes": {"quick": "quickquick"}}))
    toks = "the quick brown fox jumps over lazy dogs and zzz runs away fast today".split()
    monkeypatch.setattr(generate, "WMODEL", _one_card_model(toks))

    assert generate.process(str(v)) == "ok"
    srt = (tmp_path / "ep.eng.dubtitles.srt").read_text()
    body = srt.split("\n", 2)[2].strip()                   # index + timestamps stripped
    assert "quickquick" in body
    assert body == reflow.wrap_balance(body.replace("\n", " "))   # canonical wrap
    conf = json.loads((tmp_path / "ep.dubtitles.conf.json").read_text())
    assert conf[0]["text"] == body.replace("\n", " ")
    assert "pre_correction_text" not in conf[0]        # C7 bookkeeping stays out of the sidecar
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    for e in doc["events"]:
        if e.get("reason") == "layout_exception":
            assert e["text"] == body.replace("\n", " ")


def test_generate_and_repair_share_one_profile_definition():
    """Two copies of the layout profile is the 'two algorithms that can disagree' hazard
    C7 warns about -- repair.fits_card and generate._layout_faults must both resolve to
    reflow.layout_faults, so a repair cannot be accepted against one set of rules and
    then judged by another."""
    for text, dur in [("ok", 3.0), ("x" * 90, 1.0), ("a\nb\nc", 2.0), ("y" * 50, 0.9)]:
        assert generate._layout_faults(text, dur) == reflow.layout_faults(text, dur)


# --- H1: the srt and conf writes are atomic -----------------------------------
#
# process() clears the in-flight .dubtitles.fail marker the moment transcription
# finishes -- BEFORE either write. A plain open(path, "w") truncates immediately, so a
# crash in that window leaves a TRUNCATED srt with no marker on disk, and the default
# SKIP_IF_SRT=1 already-srt guard reads that as a finished episode on the next sweep:
# mux then embeds a cut-off subtitle. Same rule the stale-sidecar parking fix follows --
# never drop known-good output before the replacement exists.


def _two_card_model():
    return _FakeModel([_FakeSegment(0.0, 5.0, 0.05,
                                    [_FakeWord(" Hello there friend.", 0.0, 2.0, 0.9),
                                     _FakeWord(" And here is a second line.", 3.0, 5.0, 0.9)])])


def _generation_setup(monkeypatch, tmp_path, model):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 1000)
    monkeypatch.setattr(generate, "eng_audio_index", lambda video: 1)
    monkeypatch.setattr(generate, "extract_wav", lambda video, idx, wav: True)
    monkeypatch.setattr(generate, "media_duration", lambda path: None)
    monkeypatch.setenv("SKIP_IF_SRT", "0")
    monkeypatch.setattr(generate, "WMODEL", model)
    return v


def _leftover_temps(tmp_path):
    return sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp"))


def test_a_crash_midway_through_the_srt_write_leaves_no_truncated_srt(monkeypatch, tmp_path):
    v = _generation_setup(monkeypatch, tmp_path, _two_card_model())
    real, calls = generate.ts_srt, []

    def boom(t):
        calls.append(t)
        if len(calls) > 3: raise RuntimeError("disk full")   # card 1 written, card 2 half-written
        return real(t)

    monkeypatch.setattr(generate, "ts_srt", boom)
    with pytest.raises(RuntimeError):
        generate.process(str(v))
    assert len(calls) == 4, "the write did not reach the second card -- test no longer reproduces"
    assert not (tmp_path / "ep.eng.dubtitles.srt").exists()
    assert _leftover_temps(tmp_path) == []


def test_a_crash_midway_through_the_conf_write_leaves_no_truncated_conf(monkeypatch, tmp_path):
    """json.dump is patched rather than fed unserialisable data because the C encoder
    can emit the whole document in one chunk -- which would leave no partial file and so
    would not reproduce the defect at all."""
    v = _generation_setup(monkeypatch, tmp_path, _two_card_model())

    def half_dump(obj, f, **kw):
        f.write(json.dumps(obj)[:20]); raise RuntimeError("disk full")

    monkeypatch.setattr(generate.json, "dump", half_dump)
    with pytest.raises(RuntimeError):
        generate.process(str(v))
    assert (tmp_path / "ep.eng.dubtitles.srt").exists()      # the srt got all the way through
    assert not (tmp_path / "ep.dubtitles.conf.json").exists()
    assert _leftover_temps(tmp_path) == []


def test_a_failed_regeneration_does_not_destroy_the_previous_srt(monkeypatch, tmp_path):
    """The atomicity that matters in the sweep: replacing an episode's output must not
    leave it with less than it had. os.replace swaps or does nothing."""
    v = _generation_setup(monkeypatch, tmp_path, _two_card_model())
    prior = tmp_path / "ep.eng.dubtitles.srt"
    prior.write_text("1\n00:00:00,000 --> 00:00:02,000\nprevious good output\n\n")
    monkeypatch.setattr(generate, "ts_srt", lambda t: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        generate.process(str(v))
    assert prior.read_text() == "1\n00:00:00,000 --> 00:00:02,000\nprevious good output\n\n"
    assert _leftover_temps(tmp_path) == []


def test_both_writes_still_chown_and_land_on_the_happy_path(monkeypatch, tmp_path):
    """The replace must not cost the files their ownership fix-up, and the chown must
    address the FINAL path, not the temp one."""
    v = _generation_setup(monkeypatch, tmp_path, _two_card_model())
    chowned = []
    monkeypatch.setattr(generate.os, "chown", lambda p, u, g: chowned.append(p))
    assert generate.process(str(v)) == "ok"
    srt, confp = str(tmp_path / "ep.eng.dubtitles.srt"), str(tmp_path / "ep.dubtitles.conf.json")
    qcp = str(tmp_path / "ep.dubtitles.qc.json")
    # the qc sidecar is chowned too, in _write_qc after it exists -- it is read
    # library-wide by an aggregator that is not root
    assert chowned == [srt, confp, qcp]
    assert os.path.exists(srt) and os.path.exists(confp)
    assert json.loads(open(confp).read())
    assert open(srt).read().startswith("1\n")
    assert _leftover_temps(tmp_path) == []


# --- H2: per-card timing events -- the sidecar must answer "which ones" -------
#
# B1: "counters answer how many; quantiles answer how bad; events answer which ones."
# The counters and quantiles shipped; the events did not. _record_cascades held the
# displaced/shortened index lists and folded them into counters and quantiles only, so a
# sidecar recorded that 431 cards moved and how far but never WHICH.


def _cascade_cards(n, disp):
    """n cards, card i displaced by disp(i) seconds from its spoken onset."""
    return [{"start": i * 10.0 + disp(i), "end": i * 10.0 + disp(i) + 2.0,
             "source_start": i * 10.0, "source_end": i * 10.0 + 1.5} for i in range(n)]


def test_every_displaced_card_that_matters_gets_an_event(monkeypatch, tmp_path):
    """End-to-end: a runt steals from its successor, and the sidecar names the successor
    rather than only counting it."""
    v = _generation_setup(monkeypatch, tmp_path, _displaced_pair_model())
    assert generate.process(str(v)) == "ok"
    doc = json.loads((tmp_path / "ep.dubtitles.qc.json").read_text())
    evs = [e for e in doc["events"] if e.get("reason") == "cascade_shift"]
    assert len(evs) == 1
    e = evs[0]
    assert e["card_index"] == 1
    assert sorted(e["effects"]) == ["displaced", "shortened"]   # ONE event, both effects
    assert e["start"] > e["source_start"]
    assert e["displacement"] == pytest.approx(e["start"] - e["source_start"], abs=1e-3)
    assert e["dur_before"] > e["dur_after"]                     # the neighbour really lost time
    assert e["dur_after"] == pytest.approx(e["end"] - e["start"], abs=1e-3)
    assert e["hops"] >= 1
    assert doc["counters"]["displaced"] == 1 and doc["counters"]["shortened_by_neighbour"] == 1


def test_a_card_that_is_both_displaced_and_shortened_gets_one_event_not_two():
    rec = qc.Recorder()
    cards = _cascade_cards(4, lambda i: 0.5 if i else 0.0)
    generate._record_cascades(rec, cards, [{"unfixable": False, "index": 0, "hops": 3,
                                            "displaced": [1, 2, 3], "shortened": [2],
                                            "dur_before": {1: 2.5, 2: 4.0, 3: 2.5}}])
    evs = [e for e in rec.build("s", "e", "st")["events"] if e["reason"] == "cascade_shift"]
    assert [e["card_index"] for e in evs] == [1, 2, 3]
    both = next(e for e in evs if e["card_index"] == 2)
    assert sorted(both["effects"]) == ["displaced", "shortened"]
    assert sorted(evs[0]["effects"]) == ["displaced"]
    assert both["dur_before"] == 4.0
    assert rec.counters["displaced"] == 3 and rec.counters["shortened_by_neighbour"] == 1


def test_cascade_events_are_capped_at_the_worst_offenders():
    """qc.MAX_EVENTS is 500 and Recorder.event() keeps the FIRST N, so one event per
    moved card (431 on a real episode) crowds out the rare classes that exist in no
    counter at all. Only the worst N by displacement are emitted; the quantiles still
    carry the whole distribution."""
    n = 120
    rec = qc.Recorder()
    cards = _cascade_cards(n, lambda i: i * 0.01)
    generate._record_cascades(rec, cards, [{"unfixable": False, "index": 0, "hops": 2,
                                            "displaced": list(range(1, n)), "shortened": [],
                                            "dur_before": dict.fromkeys(range(1, n), 2.5)}])
    doc = rec.build("s", "e", "st")
    evs = [e for e in doc["events"] if e["reason"] == "cascade_shift"]
    assert len(evs) == generate.MAX_CASCADE_EVENTS < n - 1
    assert [e["card_index"] for e in evs] == list(range(n - 1, n - 1 - len(evs), -1))
    assert rec.priority_events == []            # that tier is reserved for layout exceptions
    assert rec.counters["displaced"] == n - 1   # counters and quantiles stay complete
    assert doc["quantiles"]["displacement"]["max"] == pytest.approx((n - 1) * 0.01, abs=1e-6)


def test_punctuation_is_restored_before_reflow_splits_the_words():
    """The load-bearing ordering of the punctuation pass (spec 2026-08-20). Restoring
    after reflow() -- repair.py's natural home for it -- would leave every boundary
    exactly as wrong as before, so the call site, not just the code, is the feature."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "generate.py")).read()
    assert "punctuation.restore(words, segments" in src
    assert src.index("punctuation.restore(") < src.index("reflow.reflow(")
