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
  2. faster-whisper (large-v3, or turbo on small-VRAM cards -- see WHISPER_MODEL below),
     task=transcribe (English dub -> English text),
     word_timestamps + vad_filter + initial_prompt glossary,
  3. conservative name-correction sweep against the franchise glossary,
  4. write <stem>.eng.dubtitles.srt + <stem>.dubtitles.conf.json (segment
     confidences: start,end,avg_logprob,no_speech_prob) for the repair stage.

Usage:
  python3 generate.py /media/.../Episode.mkv [more.mkv ...]   # explicit files
  python3 generate.py --root "/media/Anime Library/One Pace/Season 15"  # walk dir

Env:
  WHISPER_MODEL   default large-v3  (in the container this is set FOR you by the image --
                  Dockerfile.builder bakes a model and exports its name as this var, so the
                  default below only applies to a bare checkout. See the MODEL comment.)
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
import qc
import reflow
from common import STAMP_SUFFIX, VIDEO_EXTS, load_extras, out_for, read_stamp, stale_version_stamp, stamp_valid, ts_srt

EXTRA_DIRS = load_extras()  # data/extras.txt is the source (see common.load_extras)
# V2 C1: where per-show run summaries (<show>.lastrun.json) live -- same GLOSSARY_DIR
# convention as mine_glossary.py/repair.py, not the per-run GLOSSARY_FILE.
GLOSS_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")

# V2 A9 resolved, and the answer is per-GPU rather than global -- so this is a fallback,
# not really "the" model. Dockerfile.builder's WHISPER_MODEL build-arg bakes one model and
# exports the same name as a container ENV, which wins over this default; the value here
# only decides what a bare checkout (or a container run with the ENV cleared) loads.
#
# large-v3 stays the fallback because it is what the 6GB 1060 runs, and it fits there at
# the default beam_size=7. On the 3500g node's 4GB 1050ti it does not: benched on a real
# episode it OOM'd at beam 7 and only fit forced down to greedy, where it came out WORSE
# (flagged=76, over_cps=111) than large-v3-turbo at the full beam (flagged=35, over_cps=98,
# peak 1405 MiB). Turbo is safe to reach for there because its known quality regression is
# on *translation*, and REQUIRE_ENG=1 means this pipeline only ever transcribes English
# audio to English text -- it never translates.
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


def media_duration(path):
    """Duration of ``path`` in seconds via ffprobe, or None when it cannot be measured.
    None means "unbounded" to reflow.time_cards(): a probe failure must never fail an
    episode, and unbounded is exactly the pre-existing behavior. Called on the EXTRACTED
    WAV, not the container -- whisper's timestamps live on the wav's timeline, and that
    is the timeline time_cards()'s end-of-audio guard has to compare against."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        dur = float(json.loads(r.stdout)["format"]["duration"])
    except Exception as e:
        log("ffprobe duration failed", path, e); return None
    return dur if dur > 0 else None


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


QC_SUFFIX = ".dubtitles.qc.json"


def _record_qc(rec, rows):
    """Fold the finished (start, end, text) rows into the QC recorder. Validates
    every FLOOR as well as every ceiling -- the omission that hid 730 short cards."""
    for a, b, t in rows:
        dur = b - a
        cps = reflow.card_cps(t, dur)
        rec.observe("cps", cps)
        lines = t.split("\n")
        short = reflow.is_short(dur)
        over_cps = cps > reflow.MAX_CPS + reflow.EPS
        over_line = any(len(ln) > reflow.MAX_LINE for ln in lines)
        if short: rec.count("ordinary_under_min_dur_after")
        if over_cps: rec.count("over_cps")
        if over_line: rec.count("over_line_len")
        if short or over_cps or over_line or dur > reflow.MAX_DUR + reflow.EPS or len(lines) > reflow.MAX_LINES:
            rec.count("violations")


def _layout_faults(text, dur):
    """Which profile constraints ``text`` violates at ``dur`` seconds; an empty list means valid.
    Line lengths are integer character counts, so only the cps comparison needs EPS."""
    lines = text.split("\n")
    reasons = []
    if len(lines) > reflow.MAX_LINES: reasons.append("over_lines")
    if any(len(ln) > reflow.MAX_LINE for ln in lines): reasons.append("over_line_len")
    if reflow.card_cps(text, dur) > reflow.MAX_CPS + reflow.EPS: reasons.append("over_cps")
    return reasons


def _revalidate_after_correction(rec, cards):
    """C7: re-wrap each card's corrected text through reflow.wrap_balance -- the SAME
    function reflow() already used, so generation has exactly one wrapping algorithm --
    then validate the whole profile (line count, line length, and cps at the card's
    actual duration) on the RESULT. Mutates cards in place.

    Order matters: this runs after collapse_runs (which moves a collapsed card's end,
    hence its cps) and before srt/conf are written, so the text validated is the text
    written. Correcting per line preserved the pre-correction break; nothing re-checked
    the profile afterwards.

    The trigger is MEASURED invalidity, never a growth proxy. Wrapping feasibility
    depends on where word boundaries fall, not on total length: a length-neutral
    substitution can redistribute characters until no split satisfies both lines (an
    84-char card whose boundaries land at 20/40/60 has none), and +2 characters on a
    0.83s card adds ~2.4 cps, enough to cross 17 cps by itself.

    An invalid card KEEPS its correction -- the right name beats the layout profile --
    and records a layout_exception event. No splitter is built: splitting needs
    re-timing, which would put layout downstream of timing and give two layout
    algorithms that can disagree.

    Roughly 1% of cards are unwrappable with no correction involved (82-84 chars with no
    word boundary near the midpoint, so wrap_balance falls through to its over-long
    fallback). Those are reported as events with caused_by_correction=False, and are
    already counted by _record_qc's over_line_len/over_cps; the layout_exceptions COUNTER
    is C7's revisit trigger (post_glossary_layout_invalid) and counts only what the
    correction broke."""
    for c in cards:
        dur = c["end"] - c["start"]
        c["text"] = text = reflow.wrap_balance(c["text"].replace("\n", " "))
        reasons = _layout_faults(text, dur)
        if not reasons: continue
        before = c.get("pre_correction_text", text)
        pre = _layout_faults(reflow.wrap_balance(before.replace("\n", " ")), dur)
        caused = bool(set(reasons) - set(pre))
        if caused: rec.count("layout_exceptions")
        lines = text.split("\n")
        flat = text.replace("\n", " ")
        rec.event(reason="layout_exception", start=round(c["start"], 3), end=round(c["end"], 3),
                  text=flat, layout_exception_reason=reasons, pre_existing_reason=pre,
                  caused_by_correction=caused, line_count=len(lines),
                  line_lengths=[len(ln) for ln in lines], max_line_length=max(len(ln) for ln in lines),
                  visible_chars=len(flat), cps=round(reflow.card_cps(text, dur), 2))


def _write_qc(rec, stem):
    """Build and write the sidecar. Observability only: a write failure is logged, never
    fatal (see qc.write's docstring), so this is safe on the failure path too."""
    show = os.environ.get("SHOW_NAME", "") or GLOSS.get("show", "") or "unknown_show"
    doc = rec.build(show=show, episode=os.path.basename(stem), stem=stem,
                    glossary_sha=_glossary_version(), pipeline_version=_model_version())
    qcp = out_for(stem + QC_SUFFIX)
    if not qc.write(qcp, doc):
        log(f"  qc sidecar write failed for {qcp}")


def _record_cascades(rec, cards, cascades):
    """Fold time_cards()'s per-cascade records into the recorder. The records are
    positional over the PRE-filter card list -- reflow() emits exactly one card per group
    -- so a displaced/shortened index there addresses cards[i] here. Counters count CARDS
    (B1), so overlapping cascades (one can reach into the next one's span) are unioned
    rather than summed; cascade_depth is per CASCADE, one observation each."""
    displaced, shortened = set(), set()
    for r in cascades:
        if r["unfixable"]:                      # the tail clamp: nothing left to steal from
            rec.count("unfixable_runts"); continue
        rec.count("stolen")                     # the runt at r["index"] took the time
        rec.observe("cascade_depth", r["hops"])
        displaced.update(r["displaced"]); shortened.update(r["shortened"])
    rec.count("displaced", len(displaced))
    rec.count("shortened_by_neighbour", len(shortened))
    for i in sorted(displaced):
        if i < len(cards):
            rec.observe("displacement", cards[i]["start"] - cards[i]["source_start"])


def _cascade_infeasible(stem, fail, exc):
    """A2b (strict): the card list cannot satisfy the A5 temporal invariants, so the
    episode is structurally unfixable. No srt/conf/ass is written and nothing is muxed.
    The poison marker goes back down -- process() already cleared the in-flight one after
    transcription -- so the skip-prior-crash path retires this episode instead of letting
    every sweep re-fail it; main() must never see the exception, because its
    non-RuntimeError branch REMOVES the marker and schedules exactly that retry loop.
    The QC sidecar is still written: a failed episode is when the evidence matters most."""
    try: open(fail, "w").close()
    except OSError: pass
    rec = qc.Recorder()
    rec.count("cascade_infeasible")
    rec.event(reason="cascade_infeasible", card_index=exc.index,
              requested_shift=exc.requested, applied_shift=exc.applied,
              residual_shift=exc.residual, audio_duration=exc.audio_duration)
    _write_qc(rec, stem)
    log(f"  cascade infeasible at card {exc.index}: {exc.residual:.3f}s of a {exc.requested:.3f}s "
        f"steal will not fit before {exc.audio_duration}s -- no subtitle written, episode poisoned")
    return "cascade-infeasible"


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
        audio_duration = media_duration(wav)     # measured while the wav still exists

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
    merge_log, cascade_log = [], []
    try:
        cards = reflow.reflow(words, segments, merge_log=merge_log, audio_duration=audio_duration,
                              cascade_log=cascade_log)
    except reflow.CascadeInfeasible as e:
        return _cascade_infeasible(stem, fail, e)
    kept, fixes, dropped = [], 0, 0
    for c in cards:
        if hallucination.drop_reason(c):          # blocklist / repetition / music -> drop
            dropped += 1; continue
        lines, n = [], 0
        for ln in c["text"].split("\n"):          # correct per line so the wrap is preserved
            fixed, k = glossary.correct(ln, GLOSS); lines.append(fixed); n += k
        fixes += n
        kc = dict(c); kc["text"] = "\n".join(lines)
        kc["pre_correction_text"] = c["text"]   # C7 tells a broken layout from an inherited one
        kc["flag"] = hallucination.flag_reason(c)  # weaker single signal -> kept but marked
        kc["word_probs"] = _card_word_probs(c, words)  # V2 A6: per-word confidence for repair
        kept.append(kc)
    collapsed = hallucination.collapse_runs(kept)
    # C7: layout was decided before the glossary rewrote the text -- re-wrap and
    # re-validate the corrected cards before anything is written.
    rec = qc.Recorder()
    _revalidate_after_correction(rec, collapsed)
    rows = [(c["start"], c["end"], c["text"]) for c in collapsed]
    conf = []
    for c in collapsed:
        row = {"start": round(c["start"], 3), "end": round(c["end"], 3),
               # C6: the audio evidence window, kept separate from the display timing a
               # forward steal may have moved. repair.py selects its fansub reference on
               # THIS pair; sidecars written before C6 simply lack it and fall back.
               "source_start": round(c["source_start"], 3),
               "source_end": round(c["source_end"], 3),
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
    # QC sidecar: observability only -- a write failure is logged, never fatal, since the
    # episode already generated correctly (see qc.write's docstring).
    _record_qc(rec, rows)
    rec.count("cards_after", len(rows))
    # Deferred from Task 5: orphan candidates are quarantined, not fixed -- count them
    # separately from merges, and never bump orphan_candidates_fixed (nothing here fixes
    # one). merged_backward comes from merge_runts()'s own records, not re-derived.
    rec.count("orphan_candidates", sum(1 for c in cards if c.get("orphan")))
    rec.count("merged_backward", len(merge_log))
    _record_cascades(rec, cards, cascade_log)
    _write_qc(rec, stem)
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
