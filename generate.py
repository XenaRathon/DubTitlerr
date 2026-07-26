#!/usr/bin/env python3
"""Gold dubtitle GENERATION — transcribe an anime's English-dub audio into a
time-coded subtitle, biased toward correct franchise spellings and with per-segment
confidence captured for a downstream repair pass.

Runs in the subgen CUDA image (mccloud/subgen:2026.06.2) so it inherits the exact
faster-whisper 1.2.1 / ctranslate2 4.8.0 stack that already works on the 1060
(Pascal) + driver 550 — no new CUDA surface. Only extra dep is none (uses ffmpeg +
faster_whisper already present).

Per video:
  1. pick the English audio stream (by language tag) and extract 16k mono wav,
  2. faster-whisper large-v3, task=transcribe (English dub -> English text),
     word_timestamps + vad_filter + initial_prompt glossary,
  3. conservative name-correction sweep against the franchise glossary,
  4. write <stem>.eng.dubtitles.srt + <stem>.dubtitles.conf.json (segment
     confidences: start,end,avg_logprob,no_speech_prob) for the repair stage.

Usage:
  python3 generate.py /media/.../Episode.mkv [more.mkv ...]   # explicit files
  python3 generate.py --root "/media/Anime Library/One Pace/Season 15"  # walk dir

Env:
  WHISPER_MODEL   default large-v3  (V2 A9: large-v3-turbo not bench-tested in this
                  dev environment -- no GPU here -- PENDING manual test on the real
                  GTX 1060 6GB server; default stays large-v3 until that confirms it)
  COMPUTE_TYPE    default int8  (Pascal-friendly, fits 6GB; try float16 for max quality)
  MODEL_DIR       default /subgen/models  (reuse subgen's downloaded model)
  WHISPER_AUDIO_FILTER  default highpass=f=80,compand=... (V2 A8; "" disables it, the
                  pre-A8 ffmpeg command)
  MEDIA_UID/GID   default 1000/100
  GLOSSARY_DIR    default /config/glossaries  (V2 C1: where <show>.lastrun.json is written,
                  same dir mine_glossary.py/repair.py use for the show's glossary itself)
Built with help of Claude (Anthropic).
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

from faster_whisper import WhisperModel

import glossary
import hallucination
import ordering
import reflow
from common import STAMP_SUFFIX, VIDEO_EXTS, load_extras, out_for, read_stamp, stale_version_stamp, stamp_valid, ts_srt

EXTRA_DIRS = load_extras()  # data/extras.txt is the source (see common.load_extras)
# V2 C1: where per-show run summaries (<show>.lastrun.json) live -- same GLOSSARY_DIR
# convention as mine_glossary.py/repair.py, not the per-run GLOSSARY_FILE.
GLOSS_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")

# V2 A9: large-v3-turbo not bench-tested in this dev environment (no GPU here -- see
# extract_wav()'s WHISPER_AUDIO_FILTER note for the analogous CPU-only caveat elsewhere
# in this module) -- PENDING a manual test on the real GTX 1060 6GB server. Default
# stays large-v3 until that test confirms turbo doesn't OOM/regress accuracy on Pascal
# + int8. WHISPER_MODEL is already env-configurable (below), so switching to try turbo
# needs no code change -- just `WHISPER_MODEL=large-v3-turbo` on that box.
MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
COMPUTE = os.environ.get("COMPUTE_TYPE", "int8")
MODEL_DIR = os.environ.get("MODEL_DIR", "/subgen/models")
# V2 A8: optional pre-transcription audio cleanup (default highpass + dynamic-range
# compand, tuned for noisy/quiet anime dub tracks). Empty string ("") disables it
# entirely (the old, pre-A8 ffmpeg command) -- set WHISPER_AUDIO_FILTER="" to opt out.
AUDIO_FILTER = os.environ.get(
    "WHISPER_AUDIO_FILTER",
    "highpass=f=80,compand=attacks=0.001:decays=0.2:points=-80/-80|-30/-15|0/-3|20/-3")
UID = int(os.environ.get("MEDIA_UID", "1000")); GID = int(os.environ.get("MEDIA_GID", "100"))
SUFFIX = ".eng.dubtitles.srt"
WMODEL = None        # the WhisperModel, lazily loaded in main() once there's work to do

# --- Per-show glossary (optional) ---------------------------------------------------
# Name correction is OPT-IN per show (GLOSSARY_FILE), so One Piece's spellings can never
# leak onto another show. The tiered correction itself lives in glossary.py (C1). With no
# file, GLOSS is empty (correct() is a no-op) and the prompt is a neutral one from SHOW_NAME.
GLOSS = glossary.load("")
INITIAL_PROMPT = ""

def load_glossary():
    global GLOSS, INITIAL_PROMPT
    show = os.environ.get("SHOW_NAME", "")
    GLOSS = glossary.load(os.environ.get("GLOSSARY_FILE", ""))
    show = show or GLOSS.get("show", "")
    INITIAL_PROMPT = GLOSS["initial_prompt"] or (
        (f"This is {show}, a Japanese anime (English dub). Transcribe the spoken English "
         f"accurately, with natural punctuation.") if show else
        "Japanese anime, English dub. Transcribe the spoken English accurately, with natural punctuation.")
    print(f"glossary: show={show!r} names={len(GLOSS['names'])} "
          f"fixes={len(GLOSS['token_fixes']) + len(GLOSS['phrase_fixes'])} "
          f"prompt={'custom' if GLOSS['initial_prompt'] else 'neutral'}", flush=True)


# Plex "local extras" subfolders + creditless/scene clips — never real episodes, often
# mismatched junk from the scraper, and a frequent source of malformed-clip crashes. The
# --root walk prunes these so a library run only ever transcribes actual episodes.
SKIP_FILE_RE = re.compile(r"\bNCED\b|\bNCOP\b|\bNCBD\b|-\s*scene\b|creditless", re.I)


def log(*a): print(*a, flush=True)


# V2 C1: per-show run summary. process() updates this in place on its "ok" (success)
# path only; main() reads it right after each call to accumulate per-show totals for
# glossaries/<show>.lastrun.json. A module-level accumulator (rather than widening
# process()'s return type) keeps every existing "process() returns a status string"
# call site/test unchanged -- see WMODEL above for the same lazy-module-global pattern.
_LAST_STATS: dict = {}


def _model_version() -> str:
    """faster_whisper's package version, for the lastrun.json audit trail. Reads the
    already-imported module from sys.modules (real or the tests' stub) rather than
    importing it again, so this stays a no-op in the CPU-only dev/test environment."""
    fw = sys.modules.get("faster_whisper")
    return getattr(fw, "__version__", "unknown") if fw is not None else "unknown"


def _glossary_version() -> str:
    """Short content hash of the active GLOSSARY_FILE (so lastrun.json records exactly
    which glossary revision produced a run) -- 'none' if no glossary file is configured."""
    path = os.environ.get("GLOSSARY_FILE", "")
    if not path or not os.path.exists(path):
        return "none"
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except OSError:
        return "none"


def eng_audio_index(video):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index:stream_tags=language",
                            "-of", "json", video], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed", video, e); return None
    eng = [s for s in streams if ((s.get("tags") or {}).get("language", "").lower() in ("eng", "en"))]
    if eng:
        return eng[0]["index"]
    # No English-tagged audio. On a library-wide run this means a sub-only release —
    # do NOT fall back to stream 0 (that would transcribe the Japanese audio AS English
    # and produce garbage). Skip it. Set REQUIRE_ENG=0 only for pre-filtered single-audio
    # English collections (e.g. the One Pace mover already guarantees English audio).
    if os.environ.get("REQUIRE_ENG", "1") == "1":
        return None
    return streams[0]["index"] if streams else None


def extract_wav(video, idx, wav):
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}",
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    if AUDIO_FILTER:                    # V2 A8: empty WHISPER_AUDIO_FILTER = no filter (pre-A8 behavior)
        cmd += ["-af", AUDIO_FILTER]
    cmd.append(wav)
    subprocess.run(cmd, capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    return os.path.exists(wav) and os.path.getsize(wav) > 1000


def _card_word_probs(card, words):
    """Per-word linear probabilities for one card (V2 A6), joined by time overlap
    against the full per-episode word list built in process()'s transcribe loop.
    reflow.Card doesn't retain which whisper words it was built from, so this
    re-derives the association here rather than threading it through reflow.py.

    Must be called with the card's PRE-collapse boundaries (i.e. inside the per-card
    loop below, before hallucination.collapse_runs()): a later run-collapse keeps
    run[0]'s text verbatim, so computing word_probs against that same card's own
    [start, end] window -- rather than re-querying after the merge widens the window
    to cover the whole repeated run -- keeps the list aligned with the text it
    actually describes."""
    return [round(w["prob"], 3) for w in words if w["end"] > card["start"] and w["start"] < card["end"]]


def discard_stale_sidecars(stem):
    """Delete the sidecars LEFT BEHIND by a superseded pipeline version (see
    common.stale_version_stamp). They are last version's output, not pending work: left in
    place they'd make the skips in process() return "already-ass"/"already-srt" forever
    while mux re-embedded that same old subtitle and stamped it as current.

    A sidecar counts as a leftover only if it PREDATES the stamp. The run that wrote the
    stamp wrote its sidecars first and deleted them just after stamping, so anything older
    than the stamp belongs to that finished run. Anything NEWER is this regeneration's own
    fresh work: the stamp only advances when mux succeeds, so a re-transcribed sidecar sits
    beside a still-stale stamp for at least one MERGE_INTERVAL — and indefinitely if the
    mux keeps failing (skip-no-room, verify-*). Deleting that would re-run Whisper on every
    resume pass, and since gen_loop.sh's stall detector counts .srt files, the deletions
    would read as "no progress" and abandon the show mid-regeneration.

    (Raw paths, not out_for(): mux reads these same raw paths, so both already assume
    OUTPUT_ROOT resolves into the same mergerfs pool view.)"""
    try:
        stamp_mtime = os.path.getmtime(stem + STAMP_SUFFIX)
    except OSError:
        return                                    # no stamp -> nothing is attributable to it
    for suff in (".eng.dubtitles.ass", ".eng.dubtitles.srt", ".dubtitles.conf.json"):
        p = stem + suff
        try:
            if os.path.getmtime(p) > stamp_mtime:
                continue                          # newer than the stamp -> this run's work
            os.remove(p)
            log("  discarded stale-version sidecar", os.path.basename(p))
        except OSError:
            pass


def process(video):
    stem = os.path.splitext(video)[0]
    # The version-aware stamp (common.stamp_valid) is the ONLY "already muxed" guard.
    # The old SKIP_IF_MUXED ffprobe backstop is retired: an embedded Dubtitles track no
    # longer means "done", because mux.py now drops-and-replaces that track, so a
    # PIPELINE_VERSION bump must be able to regenerate an already-dubbed episode.
    stamp = read_stamp(stem + STAMP_SUFFIX)
    if stamp_valid(stamp, video):                       # muxed, current version -> skip
        return "already-muxed"
    fail = stem + ".dubtitles.fail"
    # Our own superseded output -> its leftover sidecars are stale too. Skipped for a
    # poison-marked file: that one is never transcribed, so discarding its sidecars would
    # be pure destruction (mux would then have nothing to embed until the marker is
    # cleared by hand).
    if stale_version_stamp(stamp, video) and not os.path.exists(fail):
        discard_stale_sidecars(stem)
    if os.path.exists(stem + ".eng.dubtitles.ass"):     # assembled already -> skip (idempotent)
        return "already-ass"
    if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"):
        return "already-srt"                            # generated, awaiting (a retry of) assemble
    if os.path.exists(fail):                      # a previous attempt hard-crashed on this
        return "skip-prior-crash"                 # file -> skip it (rm the .fail to retry)
    idx = eng_audio_index(video)
    if idx is None: return "no-eng-dub"          # sub-only release (or no audio) -> skip
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        if not extract_wav(video, idx, wav): return "extract-failed"
        try: open(fail, "w").close()             # mark in-flight (a segfault here leaves the
        except OSError: pass                     # marker, so a resume skips this poison file)
        beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "7"))
        segs, _info = WMODEL.transcribe(
            wav, language="en", task="transcribe", beam_size=beam_size, best_of=beam_size,
            word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
            no_speech_threshold=0.9, log_prob_threshold=-2.0,   # max coverage: VAD was removing
            initial_prompt=INITIAL_PROMPT)                       # music-masked dialogue (the 18-20min
        # Buster Call scene) before whisper saw it -> big gaps. VAD off + loose thresholds keep it;
        # B1 + the LLM repair clean the resulting silence/music hallucinations (tuning deferred).
        # condition_on_previous_text=False: with True, hard/music-masked stretches collapse into
        # one mega-segment (e.g. a 139s "segment" over the 18-20min mark of One Pace S19E16) that
        # reflow then renders as a long gap — real dialogue lost. False keeps segments discrete and
        # recovers that dialogue (faster-whisper's recommended anti-collapse setting). The glossary
        # initial_prompt still biases names; C1 correction + the LLM repair restore cross-line context.
        # (hallucination_silence_threshold also removed — it skipped real speech.)
        # Consume the (lazy) generator while the wav still exists, adapting whisper's
        # objects to the plain dicts reflow expects: one word dict per word (with its
        # source segment index), plus a per-segment record for no_speech_prob.
        words, segments = [], []
        for si, s in enumerate(segs):
            segments.append({"start": s.start, "end": s.end, "no_speech_prob": s.no_speech_prob})
            sw = s.words or []
            if sw:
                for w in sw:
                    words.append({"text": w.word, "start": w.start, "end": w.end,
                                  "prob": getattr(w, "probability", 1.0) or 1.0, "seg": si})
            else:                                # no word timestamps -> whole segment as one "word"
                words.append({"text": s.text, "start": s.start, "end": s.end,
                              "prob": min(1.0, math.exp(s.avg_logprob)), "seg": si})
    try: os.remove(fail)                          # transcription finished -> clear in-flight mark
    except OSError: pass
    # A1: reflow whisper's words into clean, well-timed cards. C1: name-correct each card.
    # B1: drop near-certain hallucinations, flag the suspect, collapse runaway repeat runs.
    cards = reflow.reflow(words, segments)
    kept, fixes, dropped = [], 0, 0
    for c in cards:
        if hallucination.drop_reason(c):          # blocklist / repetition / music -> drop
            dropped += 1; continue
        lines, n = [], 0
        for ln in c["text"].split("\n"):          # correct per line so the wrap is preserved
            fixed, k = glossary.correct(ln, GLOSS); lines.append(fixed); n += k
        fixes += n
        kc = dict(c); kc["text"] = "\n".join(lines)
        kc["flag"] = hallucination.flag_reason(c)  # weaker single signal -> kept but marked
        kc["word_probs"] = _card_word_probs(c, words)  # V2 A6: per-word confidence for repair
        kept.append(kc)
    collapsed = hallucination.collapse_runs(kept)
    rows = [(c["start"], c["end"], c["text"]) for c in collapsed]
    conf = []
    for c in collapsed:
        row = {"start": round(c["start"], 3), "end": round(c["end"], 3),
               "avg_logprob": round(c["avg_logprob"], 3),
               "no_speech_prob": round(c["no_speech_prob"], 3),
               "text": c["text"].replace("\n", " ")}
        if c.get("flag"):
            row["flag"] = c["flag"]
        if c.get("word_probs"):
            row["word_probs"] = c["word_probs"]  # optional/backward-compat (V2 A6/A7)
        conf.append(row)
    srt = out_for(stem + SUFFIX); confp = out_for(stem + ".dubtitles.conf.json")
    with open(srt, "w") as f:
        for i, (a, b, t) in enumerate(rows, 1):
            f.write(f"{i}\n{ts_srt(a)} --> {ts_srt(b)}\n{t}\n\n")
    with open(confp, "w") as f:
        json.dump(conf, f)
    for p in (srt, confp):
        try: os.chown(p, UID, GID)
        except OSError as e: log(f"chown failed for {p}: {e}")
    low = sum(1 for c in conf if c["avg_logprob"] < -0.8 or c["no_speech_prob"] > 0.6)
    max_dur = max((b - a for a, b, _ in rows), default=0.0)
    over_cps = sum(1 for a, b, t in rows
                   if len(t.replace("\n", " ")) / max(b - a, 1e-6) > reflow.MAX_CPS)
    bad = sum(1 for a, b, t in rows
              if b - a > 7.001 or len(t.split("\n")) > 2 or any(len(ln) > 42 for ln in t.split("\n")))
    collapsed_n = len(kept) - len(collapsed)
    flagged = sum(1 for c in conf if c.get("flag"))
    log(f"  cards={len(rows)} name-fixes={fixes} dropped-hallucination={dropped} "
        f"collapsed={collapsed_n} flagged={flagged} low-conf={low} "
        f"max_dur={max_dur:.1f}s over_cps={over_cps} violations={bad} "
        f"meanlp={sum(c['avg_logprob'] for c in conf)/max(1,len(conf)):.2f}")
    _LAST_STATS.clear()  # V2 C1: this episode's contribution to the show's lastrun.json
    _LAST_STATS.update({"cards_written": len(rows), "dropped_hallucination": dropped,
                         "collapsed_runs": collapsed_n, "flagged": flagged})
    return "ok"


def main():
    args = sys.argv[1:]
    files = []
    if args and args[0] == "--root":
        for dp, dns, fs in os.walk(args[1]):
            dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]   # prune extras dirs
            for fn in fs:
                if fn.lower().endswith(VIDEO_EXTS) and not SKIP_FILE_RE.search(fn):
                    files.append(os.path.join(dp, fn))
        # Watch-order priority: process seasons >= a per-show start season first (the arc
        # the viewer is about to watch), then earlier ones. Absent config -> plain sort.
        files = ordering.order_files(files, ordering.read_start(os.environ.get("SHOW_NAME", "")))
    else:
        files = args
    load_glossary()
    # Cheap pre-filter (stat only, no ffprobe/model): drop files already done so a perpetual
    # re-scan doesn't pay the ~40s model load when there's nothing new to transcribe.
    def needs_work(v):
        stem = os.path.splitext(v)[0]
        stamp = read_stamp(stem + STAMP_SUFFIX)
        if stamp_valid(stamp, v): return False        # muxed at the current version -> done
        if os.path.exists(stem + ".dubtitles.fail"): return False   # poison marker wins
        # Superseded output: its leftover sidecars are stale, so the checks below must not
        # read them as "done" -- process() discards them and re-transcribes.
        if stale_version_stamp(stamp, v): return True
        if os.path.exists(stem + ".eng.dubtitles.ass"): return False
        if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"): return False
        return True
    todo = [v for v in files if needs_work(v)]
    log(f"model={MODEL} compute={COMPUTE} require_eng={os.environ.get('REQUIRE_ENG','1')} files={len(files)} todo={len(todo)}")
    if not todo:
        log("nothing to transcribe (all done) — skipping model load"); return
    globals()["WMODEL"] = WhisperModel(MODEL, device="cuda", compute_type=COMPUTE, download_root=MODEL_DIR)
    t0 = time.monotonic()                                      # V2 C1: per-show run summary
    transcribed = 0
    totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
    for v in todo:
        log("→", os.path.basename(v))
        try:
            status = process(v)                 # one bad episode must not abort the show
            log("  ", status)
            if status == "ok":
                transcribed += 1
                for k in totals:
                    totals[k] += _LAST_STATS.get(k, 0)
        except Exception as e:
            log("  ERROR", type(e).__name__, e)
            # V2 C15: gate on the exception TYPE, not a substring match on "cuda" in the
            # message/stacktrace. faster-whisper/ctranslate2 raise RuntimeError for real
            # GPU errors (OOM, device ordinal, cuBLAS) -- the old `"cuda" in str(e).lower()`
            # check also fired on a plain ValueError/ZeroDivisionError that merely mentions
            # "cuda" somewhere in its text, which would falsely poison (and exit-3) on a bug
            # that has nothing to do with the GPU context.
            if isinstance(e, RuntimeError):
                # A CUDA OOM/device error poisons the context — every later file would also
                # fail and get falsely marked. Exit so the loop relauncher restarts with a
                # fresh context; the OOM'd file keeps its .fail (skipped on resume), the rest
                # transcribe cleanly. (Usually means another process grabbed the GPU.)
                log("  CUDA/GPU error (RuntimeError) -> exiting to rebuild a clean GPU context "
                    "(show resumes on restart)")
                sys.exit(3)
            # Non-RuntimeError: NOT a GPU error -> don't poison the episode. Clear the .fail
            # marker so the next sweep retries it, and persist a small JSON record of what
            # happened (V2 C15's retry log) for later triage.
            stem = os.path.splitext(v)[0]
            try: os.remove(stem + ".dubtitles.fail")
            except OSError: pass
            try:
                with open(out_for(stem + ".dubtitles.crash.json"), "w") as f:
                    json.dump({"path": v, "exc_type": type(e).__name__, "msg": str(e),
                               "time": time.time()}, f)
            except OSError:
                pass
    # V2 C1: per-show run summary (glossaries/<show>.lastrun.json) -- one file per --root
    # invocation, since SHOW_NAME/GLOSSARY_FILE are per-run env (see load_glossary()).
    show = os.environ.get("SHOW_NAME", "") or GLOSS.get("show", "") or "unknown_show"
    lastrun = {
        "show": show, "elapsed_s": round(time.monotonic() - t0, 1),
        "episodes_total": len(todo), "episodes_transcribed": transcribed,
        "cards_written": totals["cards_written"],
        "dropped_hallucination": totals["dropped_hallucination"],
        "collapsed_runs": totals["collapsed_runs"], "flagged": totals["flagged"],
        "model": MODEL, "model_version": _model_version(), "glossary_version": _glossary_version(),
    }
    try:
        os.makedirs(GLOSS_DIR, exist_ok=True)
        with open(os.path.join(GLOSS_DIR, show + ".lastrun.json"), "w") as f:
            json.dump(lastrun, f, indent=2)
    except OSError as e:
        log("  lastrun.json write failed:", e)


if __name__ == "__main__":
    main()
