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


def test_needs_work_false_for_a_poison_marked_stale_file(monkeypatch, tmp_path):
    """needs_work must agree with process(): a poisoned file is not work, so it must not
    drag the ~40s model load into a sweep that has nothing else to do."""
    needs_work = _real_needs_work()
    v = _stale_stamped(tmp_path, monkeypatch, leftovers=["ep.eng.dubtitles.ass"])
    (tmp_path / "ep.dubtitles.fail").write_text("")
    assert needs_work(str(v)) is False
