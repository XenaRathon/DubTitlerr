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
  2. faster-whisper (large-v3-turbo, or large-v3 on 6GB+ cards -- see WHISPER_MODEL below),
     task=transcribe (English dub -> English text),
     word_timestamps + vad_filter + initial_prompt glossary,
  3. conservative name-correction sweep against the franchise glossary,
  4. write <stem>.eng.dubtitles.srt + <stem>.dubtitles.conf.json (segment
     confidences: start,end,avg_logprob,no_speech_prob) for the repair stage.

Usage:
  python3 generate.py /media/.../Episode.mkv [more.mkv ...]   # explicit files
  python3 generate.py --root "/media/Anime Library/One Pace/Season 15"  # walk dir

Env:
  WHISPER_MODEL   default large-v3-turbo  (in the container this is set FOR you by the image --
                  Dockerfile.builder bakes a model and exports its name as this var, so the
                  default below only applies to a bare checkout. See the MODEL comment.)
  COMPUTE_TYPE    default int8  (Pascal-friendly, fits 6GB; try float16 for max quality)
  MODEL_DIR       default /subgen/models  (reuse subgen's downloaded model)
  WHISPER_AUDIO_FILTER  default highpass=f=80,compand=... (V2 A8; "" disables it, the
                  pre-A8 ffmpeg command)
  FFMPEG_TIMEOUT  default 600  (seconds; the wav decode in extract_wav. Raise it on a
                  slow NFS mount -- a timeout here fails the episode)
  FFPROBE_TIMEOUT default 60   (seconds; both ffprobe calls -- audio-stream pick and
                  duration. The stream pick reads the same remote file as the decode)
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
import punctuation
import qc
import reflow
from common import (
    SIDECAR_MODE,
    STAMP_SUFFIX,
    TRANSCRIBE_VERSION,
    VIDEO_EXTS,
    WORDS_SCHEMA_VERSION,
    WORDS_SUFFIX,
    load_extras,
    out_for,
    read_stamp,
    read_words,
    stale_tiers,
    stale_version_stamp,
    stamp_valid,
    ts_srt,
)

EXTRA_DIRS = load_extras()  # data/extras.txt is the source (see common.load_extras)
# V2 C1: where per-show run summaries (<show>.lastrun.json) live -- same GLOSSARY_DIR
# convention as mine_glossary.py/repair.py, not the per-run GLOSSARY_FILE.
GLOSS_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")

# V2 A9 resolved, and the answer is per-GPU rather than global -- so this is a fallback,
# not really "the" model. Dockerfile.builder's WHISPER_MODEL build-arg bakes one model and
# exports the same name as a container ENV, which wins over this default; the value here
# only decides what a bare checkout (or a container run with the ENV cleared) loads.
#
# large-v3-turbo is the fallback because it fits EVERY card this runs on at the default
# beam_size=7, and because it is what the production image has been built with since the
# 1050ti swap -- the default now names the artifact that actually ships. large-v3 does not
# fit the 3500g node's 4GB 1050ti: benched on a real episode it OOM'd at beam 7 and only
# fit forced down to greedy, where it came out WORSE (flagged=76, over_cps=111) than turbo
# at the full beam (flagged=35, over_cps=98, peak 1405 MiB). It still fits the 6GB 1060 at
# beam 7, which is what the build-arg is for. Turbo is safe to default to because its known
# quality regression is on *translation*, and REQUIRE_ENG=1 means this pipeline only ever
# transcribes English audio to English text -- it never translates.
#
# NOT a TRANSCRIBE_VERSION bump. common.py names the whisper model as decoder-affecting and
# says nothing detects it mechanically -- but the library's 576 v4 stamps were produced by
# THIS decoder (the image has been turbo-built since the swap), so they are transcribe-fresh
# already. Bumping would burn ~2 GPU-days to record a bookkeeping change, which is the exact
# trade common.py's 4/7 adoption note declines. A downstream install that built with the old
# large-v3 default and then rebuilds DOES change decoder without a bump; the drift test in
# tests/test_dockerfile_copy.py cannot see that, and it is recorded here as the known gap.
MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
COMPUTE = os.environ.get("COMPUTE_TYPE", "int8")
MODEL_DIR = os.environ.get("MODEL_DIR", "/subgen/models")
# V2 A8: optional pre-transcription audio cleanup (default highpass + dynamic-range
# compand, tuned for noisy/quiet anime dub tracks). Empty string ("") disables it
# entirely (the old, pre-A8 ffmpeg command) -- set WHISPER_AUDIO_FILTER="" to opt out.
AUDIO_FILTER = os.environ.get(
    "WHISPER_AUDIO_FILTER", "highpass=f=80,compand=attacks=0.001:decays=0.2:points=-80/-80|-30/-15|0/-3|20/-3"
)
# ffmpeg/ffprobe wall-clock limits. Both were literals until a full decode timed out
# on a slow NFS mount with no way to raise the ceiling short of editing this file. The
# probe budget is the tighter of the two and reads the SAME remote file the decode does,
# so it is overridable for the same reason.
FFMPEG_TIMEOUT = int(os.environ.get("FFMPEG_TIMEOUT", "600"))
FFPROBE_TIMEOUT = int(os.environ.get("FFPROBE_TIMEOUT", "60"))
AUDIO_START_THRESHOLD = 0.05  # ignore codec pre-skip and sub-frame timestamp noise
UID = int(os.environ.get("MEDIA_UID", "1000"))
GID = int(os.environ.get("MEDIA_GID", "100"))
SUFFIX = ".eng.dubtitles.srt"
WMODEL = None  # the WhisperModel, lazily loaded in main() once there's work to do

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
    # ONE derivation, in glossary.prompt_for: the text tier compares a stored prompt
    # against it to decide whether a glossary edit needs the GPU. A second copy here
    # would drift, and the drift would read as "the prompt changed" on every episode.
    INITIAL_PROMPT = glossary.prompt_for(GLOSS, show)
    print(
        f"glossary: show={show!r} names={len(GLOSS['names'])} "
        f"fixes={len(GLOSS['token_fixes']) + len(GLOSS['phrase_fixes'])} "
        f"prompt={'custom' if GLOSS['initial_prompt'] else 'neutral'}",
        flush=True,
    )


# Plex "local extras" subfolders + creditless/scene clips — never real episodes, often
# mismatched junk from the scraper, and a frequent source of malformed-clip crashes. The
# --root walk prunes these so a library run only ever transcribes actual episodes.
SKIP_FILE_RE = re.compile(r"\bNCED\b|\bNCOP\b|\bNCBD\b|-\s*scene\b|creditless", re.I)


def log(*a):
    print(*a, flush=True)


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
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index:stream_tags=language",
                "-of",
                "json",
                video,
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed", video, e)
        return None
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
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        dur = float(json.loads(r.stdout)["format"]["duration"])
    except Exception as e:
        log("ffprobe duration failed", path, e)
        return None
    return dur if dur > 0 else None


def audio_start_time(video, idx):
    """Start time of the selected audio stream in the container timeline, or None.

    ``idx`` is the global stream index returned by ``eng_audio_index``. Filtering the
    probe result by that index is important when a file contains multiple audio tracks:
    the stream that is probed must be the stream that ``extract_wav`` maps.
    """
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index,start_time",
                "-of",
                "json",
                video,
            ],
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        streams = json.loads(r.stdout).get("streams", [])
        stream = next((s for s in streams if s.get("index") == idx), None)
        if stream is None:
            return None
        return float(stream["start_time"])
    except Exception as e:
        log("ffprobe audio start failed", video, e)
        return None


def _apply_audio_start_offset(words, segments, audio_duration, offset):
    """Move Whisper's audio-relative timestamps onto the video timeline."""
    if offset is None or abs(offset) <= AUDIO_START_THRESHOLD:
        return audio_duration
    for item in words:
        item["start"] += offset
        item["end"] += offset
    for segment in segments:
        segment["start"] += offset
        segment["end"] += offset
    if audio_duration is not None:
        audio_duration += offset
    log(f"audio start offset: branch=corrected offset={offset:+.3f}s")
    return audio_duration


def extract_wav(video, idx, wav):
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-i",
        video,
        "-map",
        f"0:{idx}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
    ]
    if AUDIO_FILTER:  # V2 A8: empty WHISPER_AUDIO_FILTER = no filter (pre-A8 behavior)
        cmd += ["-af", AUDIO_FILTER]
    cmd.append(wav)
    subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT, stdin=subprocess.DEVNULL)
    return os.path.exists(wav) and os.path.getsize(wav) > 1000


def _card_word_probs(card, words, rec=None):
    """Per-word linear probabilities for one card (V2 A6), joined by time overlap
    against the full per-episode word list built in process()'s transcribe loop.
    reflow.Card doesn't retain which whisper words it was built from, so this
    re-derives the association here rather than threading it through reflow.py.

    Joined on the SOURCE window (C6), never the display one. A forward steal moves
    display timing -- starts later, ends past the old cap -- so a displaced card's
    display window can be entirely disjoint from its own audio while covering its
    neighbour's. Joining on display timing therefore hands repair.has_low_prob_word()
    the wrong card's confidences: a false negative on the card holding the mis-heard
    word and a false positive on the runt that stole the time. Same repoint, and the
    same pre-C6 fallback, as repair.overlap_ref(). The audio a card describes never moves.

    Must be called with the card's PRE-collapse boundaries (i.e. inside the per-card
    loop below, before hallucination.collapse_runs()): a later run-collapse keeps
    run[0]'s text verbatim, so computing word_probs against that same card's own
    source window -- rather than re-querying after the merge widens the window to
    cover the whole repeated run -- keeps the list aligned with the text it
    actually describes."""
    # S-6: a 1-2 word card whose source span exceeds MAX_DUR carries a whisper
    # timestamp already proven wrong, and a window that wide inherits the NEIGHBOURS'
    # probabilities -- measured at 20 of 401 gated cards, one of which would have been
    # flagged for repair purely on borrowed evidence. Return nothing rather than
    # substituting the display window: on 99% of gated cards display == source exactly,
    # so a fallback reproduces the window just declared implausible.
    if hallucination.bad_source_window(card, rec=rec):
        return []
    a = card.get("source_start", card["start"])
    b = card.get("source_end", card["end"])
    return [round(w["prob"], 3) for w in words if w["end"] > a and w["start"] < b]


QC_SUFFIX = ".dubtitles.qc.json"
STALE_SUFFIX = ".stale"  # parked, not deleted -- see park_stale_sidecars
# WORDS_SUFFIX is parked with the rest: a words.json left behind by a superseded
# pipeline would otherwise be READ by the cached text-tier path, replaying an older
# run's transcript into a current-version episode.
SIDECAR_SUFFIXES = (".eng.dubtitles.ass", ".eng.dubtitles.srt", ".dubtitles.conf.json", QC_SUFFIX, WORDS_SUFFIX)


def write_words(stem, words, segments, audio_duration, initial_prompt=""):
    """Persist the word list so a TEXT-tier change can re-run without the GPU.

    Written at exactly one point: AFTER punctuation.restore() has mutated word["text"]
    in place, and BEFORE reflow splits anything. That is what makes a replay free of the
    punctuation LLM call while still reproducing the same cards.

    ``segments`` is persisted alongside, and is NOT redundant: card_confidence() reads
    each card's no_speech_prob from the SEGMENT list (reflow.py), and that value exists
    nowhere on a word. A sidecar without it would replay every card at nsp 0.0, silently
    disabling the music drop rule and the maybe_silence flag on the cheap path.
    ``audio_duration`` likewise -- time_cards() clamps the tail against it and raises
    CascadeInfeasible from it; it is measured from the wav, which is long gone by replay.

    ``initial_prompt`` is stored as the STRING, not as a hash of the glossary file: the
    prompt is the only glossary-derived input the decoder ever sees, so comparing it is
    what distinguishes a glossary edit that needs the GPU from one that does not.

    The words are stored as generate holds them -- pre-reflow-transform. reflow's
    _normalize/_clamp_to_segments/_dejitter are pure and cost microseconds, and
    _card_word_probs() joins against this same untransformed list, so storing the
    post-transform words would make the replay diverge from the original run for no gain."""
    doc = {
        "schema_version": WORDS_SCHEMA_VERSION,
        "transcribe_version": TRANSCRIBE_VERSION,
        "model": os.environ.get("WHISPER_MODEL", ""),
        "initial_prompt": initial_prompt,
        "audio_duration": audio_duration,
        "segments": segments,
        "words": words,
    }
    _atomic_write(out_for(stem + WORDS_SUFFIX), lambda f: json.dump(doc, f))


def park_stale_sidecars(stem):
    """Move the sidecars LEFT BEHIND by a superseded pipeline version (see
    common.stale_version_stamp) out of the way. They are last version's output, not
    pending work: left in place they'd make the skips in process() return
    "already-ass"/"already-srt" forever while mux re-embedded that same old subtitle and
    stamped it as current -- and a leftover qc.json would aggregate as this version's
    measurement.

    They are RENAMED to <name>.stale, not deleted. This ran before the already-srt guard
    and before transcription, so on a version bump under the DEFAULT SKIP_IF_SRT=1 the
    previous srt and conf were destroyed and only THEN could reflow raise
    CascadeInfeasible -- leaving no srt, no conf and a permanent .fail marker that
    retires the episode until an operator clears it by hand. Deleting output before
    knowing a replacement exists is the destructive half of a swap done in the wrong
    order. Parked files are invisible to every consumer (mux, the assemble pass and the
    stall detector all match on exact suffixes), so nothing muxes last version's content
    while they sit there, and a failed replacement is one rename from being undone.
    drop_parked_sidecars() clears them once this run has written its own.

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
        return  # no stamp -> nothing is attributable to it
    for suff in SIDECAR_SUFFIXES:
        p = stem + suff
        try:
            if os.path.getmtime(p) > stamp_mtime:
                continue  # newer than the stamp -> this run's work
            os.replace(p, p + STALE_SUFFIX)
            log("  parked stale-version sidecar", os.path.basename(p))
        except OSError:
            pass


def parked_sidecars(stem):
    """Basenames of this episode's parked previous output, sorted. Empty when there is none."""
    return sorted(os.path.basename(stem + s + STALE_SUFFIX) for s in SIDECAR_SUFFIXES if os.path.exists(stem + s + STALE_SUFFIX))


def drop_parked_sidecars(stem):
    """Called once this run has written its own srt and conf: the parked copies were
    insurance against a failed replacement, and the replacement landed."""
    for suff in SIDECAR_SUFFIXES:
        try:
            os.remove(stem + suff + STALE_SUFFIX)
        except OSError:
            pass


def _card_faults(text, dur):
    """Every profile breach of one finished card, or [] when it is clean. B2 + C4a:
    THE single predicate behind both the sidecar's `violations` counter and the console
    line's `violations=` -- those were two independent implementations, and the console
    one (hardcoded 7.001/2/42, no floor, no EPS on cps) is the check that was supposed
    to catch 730 short cards and structurally could not.

    Layout comes from reflow.layout_faults, the single definition of the display
    profile. The duration floor and ceiling are TIMING, not layout, so they are added
    here rather than pushed into a profile that repair.py also consumes: repair may not
    change a card's duration, so a duration fault is not something it can be judged on."""
    faults = reflow.layout_faults(text, dur)
    if reflow.is_short(dur):
        faults.append("under_min_dur")
    if dur > reflow.MAX_DUR + reflow.EPS:
        faults.append("over_max_dur")
    return faults


def _record_before(rec, cards, merges):
    """The "before" half of the sidecar's before/after pairs, measured on reflow's
    output plus its merge log -- i.e. on the state the timing passes were handed.

    ``cards_before`` is the GROUP count the timing layer saw: every merge record absorbs
    exactly one group, so len(cards) + len(merges) reconstructs it. ``cards_after``
    counts what shipped, so the pair spans every pass that can change the card count --
    and a retired episode's sidecar is no longer indistinguishable from a flawless one.

    ``ordinary_under_min_dur_before`` counts the runts the timing layer had to fix, in
    three disjoint parts: every ABSORBED group (short by definition -- _merge_fits gates
    on is_short and an orphan never merges backward); every merge TARGET that was itself
    short before it grew (`target_was_short`, captured at merge time because a merged
    span covers both groups and nothing downstream can recover it); and every surviving
    card whose SOURCE span -- the spoken duration, which no display pass moves -- is
    still short. Omitting the middle term undercounted by ~10% and always downward,
    which flatters exactly the before/after comparison this metric exists to support."""
    rec.count("cards_before", len(cards) + len(merges))
    # merge_runts() counts the original short non-orphan groups at entry and stamps the
    # total on every record; with no merges nothing moved, so the survivors' SOURCE spans
    # (which no display pass touches) are the same population.
    rec.count(
        "ordinary_under_min_dur_before",
        merges[0]["short_groups_before"]
        if merges
        else sum(1 for c in cards if not c.get("orphan") and reflow.is_short(c["source_end"] - c["source_start"])),
    )


def _record_qc(rec, cards):
    """Fold the finished cards into the QC recorder. Validates every FLOOR as well as
    every ceiling -- the omission that hid 730 short cards.

    Takes the CARDS, not (start, end, text) rows: the rows discard the orphan flag, and
    a quarantined orphan that stays short must land in its own counter rather than
    breaking the ordinary_under_min_dur_after == 0 acceptance assertion it is exempt
    from. Muxing a short orphan is an explicit decision; muxing a short ordinary card
    is the defect."""
    for c in cards:
        a, b, t = c["start"], c["end"], c["text"]
        dur = b - a
        rec.observe("cps", reflow.card_cps(t, dur))
        # required_extension = how much longer this card would have to be displayed to
        # read at MAX_CPS. Signed and observed for EVERY card, so the quantiles describe
        # the whole population (negative == reading slack): this is the quantity the
        # deferred cps-stealing decision consumes, and a bare over_cps count cannot
        # supply it. Zero would be indistinguishable from "no card needed extension".
        rec.observe("required_extension", len(t.replace("\n", " ")) / reflow.MAX_CPS - dur)
        faults = _card_faults(t, dur)
        if "under_min_dur" in faults:
            rec.count("orphan_under_min_dur_after" if c.get("orphan") else "ordinary_under_min_dur_after")
        if "over_cps" in faults:
            rec.count("over_cps")
        if "over_line_len" in faults:
            rec.count("over_line_len")
        # over_chars: two LEGAL 42-char lines can still exceed MAX_CHARS, so this fault
        # passes every per-line check and had no counter behind its event at all.
        if "over_chars" in faults:
            rec.count("over_chars")

        if faults:
            rec.count("violations")


def _layout_faults(text, dur):
    """Which profile constraints ``text`` violates at ``dur`` seconds; an empty list means valid.
    Line lengths are integer character counts, so only the cps comparison needs EPS."""
    return reflow.layout_faults(text, dur)


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
        if not reasons:
            continue
        before = c.get("pre_correction_text", text)
        pre = _layout_faults(reflow.wrap_balance(before.replace("\n", " ")), dur)
        caused = bool(set(reasons) - set(pre))
        if caused:
            rec.count("layout_exceptions")
        lines = text.split("\n")
        flat = text.replace("\n", " ")
        # priority: a correction-introduced fault exists in no counter and cannot be
        # reconstructed, so it must survive the event cap. Pre-existing faults are
        # already counted losslessly by _record_qc and described by the cps quantiles.
        rec.event(
            priority=caused,
            reason="layout_exception",
            start=round(c["start"], 3),
            end=round(c["end"], 3),
            text=flat,
            layout_exception_reason=reasons,
            pre_existing_reason=pre,
            caused_by_correction=caused,
            line_count=len(lines),
            line_lengths=[len(ln) for ln in lines],
            max_line_length=max(len(ln) for ln in lines),
            visible_chars=len(flat),
            cps=round(reflow.card_cps(text, dur), 2),
        )


def _atomic_write(path, render, mode=SIDECAR_MODE):
    """Write ``path`` through a temp file in the same directory plus os.replace -- the
    discipline qc.write and glossary_acquire._write_json already follow.

    process() clears the in-flight .dubtitles.fail marker as soon as transcription
    finishes, BEFORE the srt and conf are written, so a plain open(path, "w") that dies
    mid-loop leaves a TRUNCATED file with no marker behind it: the default SKIP_IF_SRT=1
    already-srt guard reads that as a finished episode on the next sweep and mux embeds a
    cut-off subtitle. Same rule as the stale-sidecar parking fix one function away --
    never drop known-good output before the replacement exists. os.replace either swaps
    or does nothing, and a failure leaves neither a partial target nor a temp file.

    The exception is deliberately NOT swallowed (unlike qc.write's): the srt and conf are
    the episode's product, not observability, and a run that lost them must not report ok.

    ``mode`` defaults to common.SIDECAR_MODE (0664); mkstemp creates 0600, which would strip
    group/other read from every file we ship. It must stay GROUP-WRITABLE -- 0644 meant only
    the creating uid could ever overwrite a sidecar, which broke every non-root writer (see
    the SIDECAR_MODE comment in common.py)."""
    d = os.path.dirname(path) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            render(f)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _write_qc(rec, stem):
    """Build and write the sidecar. Observability only: a write failure is logged, never
    fatal (see qc.write's docstring), so this is safe on the failure path too."""
    show = os.environ.get("SHOW_NAME", "") or GLOSS.get("show", "") or "unknown_show"
    doc = rec.build(
        show=show, episode=os.path.basename(stem), stem=stem, glossary_sha=_glossary_version(), pipeline_version=_model_version()
    )
    qcp = out_for(stem + QC_SUFFIX)
    if not qc.write(qcp, doc):
        log(f"  qc sidecar write failed for {qcp}")
        return
    # Match every other sidecar's ownership. This one exists to be read library-wide
    # later; root-owned it is unreadable over the share by whoever aggregates it.
    try:
        os.chown(qcp, UID, GID)
    except OSError:
        pass


MAX_CASCADE_EVENTS = 25  # per episode: the worst displacements, not one per moved card


def _record_cascades(rec, cards, cascades):
    """Fold time_cards()'s per-cascade records into the recorder. The records are
    positional over the PRE-filter card list -- reflow() emits exactly one card per group
    -- so a displaced/shortened index there addresses cards[i] here. Counters count CARDS
    (B1), so overlapping cascades (one can reach into the next one's span) are unioned
    rather than summed; cascade_depth is per CASCADE, one observation each.

    B1 promises three answers: "counters answer how many; quantiles answer how bad;
    events answer which ones". The third one needs an event per affected card, because
    neither a count of 431 nor a p99 displacement can name a card anyone can go and look
    at. ONE event per card carrying an effect LIST, never one per effect: the counters
    keep displaced and shortened_by_neighbour deliberately separate, and the same cascade
    routinely does both to the same card."""
    displaced, shortened = set(), set()
    hops, dur_before = {}, {}
    for r in cascades:
        if r["unfixable"]:  # the tail clamp: nothing left to steal from
            rec.count("unfixable_runts")
            continue
        rec.count("stolen")  # the runt at r["index"] took the time
        rec.observe("cascade_depth", r["hops"])
        displaced.update(r["displaced"])
        shortened.update(r["shortened"])
        for i in r["displaced"]:  # first cascade to touch a card saw its true
            dur_before.setdefault(i, r["dur_before"].get(i))  # "before"; cascades run in order
            hops[i] = max(hops.get(i, 0), r["hops"])
    rec.count("displaced", len(displaced))
    rec.count("shortened_by_neighbour", len(shortened))
    moved = {i for i in displaced | shortened if i < len(cards)}
    disp = {i: cards[i]["start"] - cards[i]["source_start"] for i in moved}
    for i in sorted(displaced & moved):
        rec.observe("displacement", disp[i])
    # WORST N ONLY. qc.MAX_EVENTS is 500 and Recorder.event() keeps the FIRST ones, so an
    # event per moved card (431 on a measured episode) would evict the rare classes that
    # exist in no counter at all. The quantiles above already carry the whole
    # distribution; the events only have to name the offenders. Not priority=True either:
    # that tier is reserved for correction-introduced layout exceptions.
    for i in sorted(moved, key=lambda i: (-disp[i], i))[:MAX_CASCADE_EVENTS]:
        c, d0 = cards[i], dur_before.get(i)
        rec.event(
            reason="cascade_shift",
            card_index=i,
            effects=(["displaced"] if i in displaced else []) + (["shortened"] if i in shortened else []),
            start=round(c["start"], 3),
            end=round(c["end"], 3),
            # the audio window is the durable identity: card_index is positional
            # over the pre-filter list, and hallucination dropping renumbers it.
            source_start=round(c["source_start"], 3),
            source_end=round(c["source_end"], 3),
            displacement=round(disp[i], 3),
            hops=hops.get(i, 0),
            dur_before=None if d0 is None else round(d0, 3),
            dur_after=round(c["end"] - c["start"], 3),
        )


def _cascade_infeasible(stem, fail, exc):
    """A2b (strict): the card list cannot satisfy the A5 temporal invariants, so the
    episode is structurally unfixable. No srt/conf/ass is written and nothing is muxed.
    The poison marker goes back down -- process() already cleared the in-flight one after
    transcription -- so the skip-prior-crash path retires this episode instead of letting
    every sweep re-fail it; main() must never see the exception, because its
    non-RuntimeError branch REMOVES the marker and schedules exactly that retry loop.
    The QC sidecar is still written: a failed episode is when the evidence matters most."""
    try:
        open(fail, "w").close()
    except OSError:
        pass
    rec = qc.Recorder()
    rec.count("cascade_infeasible")
    # What survived: on a version bump this episode's previous srt/conf are parked
    # rather than deleted, so "poisoned" is recoverable rather than terminal. Recorded
    # here because the sidecar is the only durable account a retired episode gets.
    parked = parked_sidecars(stem)
    rec.event(
        reason="cascade_infeasible",
        card_index=exc.index,
        requested_shift=exc.requested,
        applied_shift=exc.applied,
        residual_shift=exc.residual,
        audio_duration=exc.audio_duration,
        retained_prior_output=parked,
    )
    _write_qc(rec, stem)
    log(
        f"  cascade infeasible at card {exc.index}: {exc.residual:.3f}s of a {exc.requested:.3f}s "
        f"steal will not fit before {exc.audio_duration}s -- no subtitle written, episode poisoned"
    )
    if parked:
        log(f"  previous output kept as {', '.join(parked)} -- drop the .stale suffix to recover it")
    return "cascade-infeasible"


def text_stages(stem, words, segments, audio_duration, rec, fail):
    """Everything downstream of the word list: reflow, glossary correction, the
    hallucination gate, layout re-validation, and the srt/conf write.

    Extracted so a CACHED re-run and a fresh transcription execute the SAME code. Two
    copies would drift, and the drift would be a replay that quietly produces different
    cards than the run it claims to reproduce -- undetectable without comparing two full
    runs of the same episode. Everything above this line is the transcribe tier; this is
    the text tier, and it costs CPU minutes."""
    # A1: reflow whisper's words into clean, well-timed cards. C1: name-correct each card.
    # B1: drop near-certain hallucinations, flag the suspect, collapse runaway repeat runs.
    merge_log, cascade_log = [], []
    try:
        cards = reflow.reflow(words, segments, merge_log=merge_log, audio_duration=audio_duration, cascade_log=cascade_log)
    except reflow.CascadeInfeasible as e:
        return _cascade_infeasible(stem, fail, e)
    kept, fixes, dropped = [], 0, 0
    for c in cards:
        if hallucination.drop_reason(c, rec=rec):  # blocklist / repetition / music -> drop
            dropped += 1
            continue
        lines, n = [], 0
        for ln in c["text"].split("\n"):  # correct per line so the wrap is preserved
            fixed, k = glossary.correct(ln, GLOSS)
            lines.append(fixed)
            n += k
        fixes += n
        kc = dict(c)
        kc["text"] = "\n".join(lines)
        kc["pre_correction_text"] = c["text"]  # C7 tells a broken layout from an inherited one
        kc["flag"] = hallucination.flag_reason(c, rec=rec)  # weaker single signal -> kept but marked
        kc["word_probs"] = _card_word_probs(c, words, rec=rec)  # V2 A6: per-word confidence for repair
        kept.append(kc)
    collapsed = hallucination.collapse_runs(kept)
    # C7: layout was decided before the glossary rewrote the text -- re-wrap and
    # re-validate the corrected cards before anything is written. (`rec` was opened before
    # the restoration pass so its counters land in this same sidecar.)
    _revalidate_after_correction(rec, collapsed)
    rows = [(c["start"], c["end"], c["text"]) for c in collapsed]
    conf = []
    for c in collapsed:
        row = {
            "start": round(c["start"], 3),
            "end": round(c["end"], 3),
            # C6: the audio evidence window, kept separate from the display timing a
            # forward steal may have moved. repair.py selects its fansub reference on
            # THIS pair; sidecars written before C6 simply lack it and fall back.
            "source_start": round(c["source_start"], 3),
            "source_end": round(c["source_end"], 3),
            "avg_logprob": round(c["avg_logprob"], 3),
            "no_speech_prob": round(c["no_speech_prob"], 3),
            "text": c["text"].replace("\n", " "),
        }
        if c.get("flag"):
            row["flag"] = c["flag"]
        if c.get("word_probs"):
            row["word_probs"] = c["word_probs"]  # optional/backward-compat (V2 A6/A7)
        conf.append(row)
    srt = out_for(stem + SUFFIX)
    confp = out_for(stem + ".dubtitles.conf.json")

    def _render_srt(f):
        for i, (a, b, t) in enumerate(rows, 1):
            f.write(f"{i}\n{ts_srt(a)} --> {ts_srt(b)}\n{t}\n\n")

    _atomic_write(srt, _render_srt)  # both atomic: the in-flight marker is
    _atomic_write(confp, lambda f: json.dump(conf, f))  # already gone by here (see helper)
    for p in (srt, confp):  # the qc sidecar is chowned in _write_qc, after it
        try:
            os.chown(p, UID, GID)  # exists
        except OSError as e:
            log(f"chown failed for {p}: {e}")
    # QC sidecar: observability only -- a write failure is logged, never fatal, since the
    # episode already generated correctly (see qc.write's docstring).
    _record_qc(rec, collapsed)
    rec.count("cards_after", len(rows))
    _record_before(rec, cards, merge_log)
    # Deferred from Task 5: orphan candidates are quarantined, not fixed -- count them
    # separately from merges, and never bump orphan_candidates_fixed (nothing here fixes
    # one). merged_backward comes from merge_runts()'s own records, not re-derived.
    rec.count("orphan_candidates", sum(1 for c in cards if c.get("orphan")))
    rec.count("merged_backward", len(merge_log))
    _record_cascades(rec, cards, cascade_log)
    low = sum(1 for c in conf if c["avg_logprob"] < -0.8 or c["no_speech_prob"] > 0.6)
    flagged = sum(1 for c in conf if c.get("flag"))
    rec.count("low_conf", low)
    rec.count("flagged", flagged)  # both were logged and
    _write_qc(rec, stem)  # then thrown away
    # Only now is the replacement COMPLETE -- srt, conf AND sidecar. Dropping the parked
    # copies before the sidecar exists would leave a window where neither generation's
    # qc.json is on disk.
    drop_parked_sidecars(stem)
    max_dur = max((b - a for a, b, _ in rows), default=0.0)
    faults = [_card_faults(t, b - a) for a, b, t in rows]  # B2: the SAME predicate the
    over_cps = sum(1 for f in faults if "over_cps" in f)  # sidecar counts, so the number
    bad = sum(1 for f in faults if f)  # an operator reads cannot differ
    collapsed_n = len(kept) - len(collapsed)
    log(
        f"  cards={len(rows)} name-fixes={fixes} dropped-hallucination={dropped} "
        f"collapsed={collapsed_n} flagged={flagged} low-conf={low} "
        f"max_dur={max_dur:.1f}s over_cps={over_cps} violations={bad} "
        f"meanlp={sum(c['avg_logprob'] for c in conf) / max(1, len(conf)):.2f}"
    )
    _LAST_STATS.clear()  # V2 C1: this episode's contribution to the show's lastrun.json
    _LAST_STATS.update(
        {"cards_written": len(rows), "dropped_hallucination": dropped, "collapsed_runs": collapsed_n, "flagged": flagged}
    )
    return "ok"


def partition_todo(files):
    """Split outstanding work by TIER: ``(transcribe_todo, text_todo)``.

    An episode whose transcript is current and whose words.json is usable needs only the
    text stages, which cost CPU minutes. Without this split a TEXT_VERSION bump sends
    every one of those episodes back through the decoder -- for the live library that is
    576 episodes and roughly two GPU-days, which is precisely the cost the tier split
    exists to remove.

    An episode that is text-stale but has NO usable words.json goes to the transcribe
    queue: it transcribes once and gains a sidecar. That is a migration, not a bump, and
    it is far better than being skipped forever for want of a cache."""
    transcribe_todo, text_todo = [], []
    for v in files:
        stem = os.path.splitext(v)[0]
        if os.path.exists(stem + ".dubtitles.fail"):
            continue  # poison marker wins, exactly as in needs_work()
        stale = stale_tiers(read_stamp(stem + STAMP_SUFFIX), v)
        if not stale:
            continue
        if "transcribe" in stale:
            transcribe_todo.append(v)
        elif read_words(stem) is not None:
            text_todo.append(v)
        else:
            transcribe_todo.append(v)
    return transcribe_todo, text_todo


def process_text(video):
    """Re-run the TEXT tier from the persisted word list -- no GPU, no punctuation LLM.

    Runs the identical text_stages() a fresh transcription runs, so a replay cannot
    quietly diverge from the run it claims to reproduce. Writes a new srt and conf;
    merge_pass then re-muxes the episode, because its stamp is text-stale."""
    stem = os.path.splitext(video)[0]
    rec = qc.Recorder()
    doc = read_words(stem, rec=rec)
    if doc is None:
        return "no-words"
    return text_stages(
        stem,
        doc["words"],
        doc.get("segments") or [],
        doc.get("audio_duration"),
        rec,
        stem + ".dubtitles.fail",
    )


def process(video):
    stem = os.path.splitext(video)[0]
    # The version-aware stamp (common.stamp_valid) is the ONLY "already muxed" guard.
    # The old SKIP_IF_MUXED ffprobe backstop is retired: an embedded Dubtitles track no
    # longer means "done", because mux.py now drops-and-replaces that track, so a
    # version bump must be able to regenerate an already-dubbed episode.
    stamp = read_stamp(stem + STAMP_SUFFIX)
    if stamp_valid(stamp, video):  # muxed, current version -> skip
        return "already-muxed"
    fail = stem + ".dubtitles.fail"
    # Our own superseded output -> its leftover sidecars are stale too. Skipped for a
    # poison-marked file: that one is never transcribed, so discarding its sidecars would
    # be pure destruction (mux would then have nothing to embed until the marker is
    # cleared by hand).
    if stale_version_stamp(stamp, video) and not os.path.exists(fail):
        park_stale_sidecars(stem)
    if os.path.exists(stem + ".eng.dubtitles.ass"):  # assembled already -> skip (idempotent)
        return "already-ass"
    if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"):
        return "already-srt"  # generated, awaiting (a retry of) assemble
    if os.path.exists(fail):  # a previous attempt hard-crashed on this
        return "skip-prior-crash"  # file -> skip it (rm the .fail to retry)
    idx = eng_audio_index(video)
    if idx is None:
        return "no-eng-dub"  # sub-only release (or no audio) -> skip
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        if not extract_wav(video, idx, wav):
            return "extract-failed"
        audio_duration = media_duration(wav)  # measured while the wav still exists

        try:
            open(fail, "w").close()  # mark in-flight (a segfault here leaves the
        except OSError:
            pass  # marker, so a resume skips this poison file)
        beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "7"))
        segs, _info = WMODEL.transcribe(
            wav,
            language="en",
            task="transcribe",
            beam_size=beam_size,
            best_of=beam_size,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.9,
            log_prob_threshold=-2.0,  # max coverage: VAD was removing
            initial_prompt=INITIAL_PROMPT,
        )  # music-masked dialogue (the 18-20min
        # Buster Call scene) before whisper saw it -> big gaps. VAD off + loose thresholds keep it;
        # B1 + the LLM repair clean the resulting silence/music hallucinations (tuning deferred).
        # condition_on_previous_text=False is now also FORCED BY VRAM, not only by the
        # collapse below. Measured 2026-08-20 on this box (1060, 6GB, large-v3, beam 7):
        # True OOMs -- "CUDA failed with error out of memory" -- in a fresh process with the
        # GPU otherwise idle at 121MiB. True grows the decoder prompt with the previous
        # segment's text, and there is no headroom for it here. Fitting it would mean
        # beam_size=1 or large-v3-turbo, both of which cost accuracy elsewhere.
        # Consequence: Whisper decodes each segment cold, so segments that begin mid-sentence
        # come back lowercase and unpunctuated -- 73% punctuated / 14% lowercase-start at the
        # segment level on S30E06. punctuation.restore() puts that back BEFORE reflow splits
        # the words (it sees the whole run in both directions -- more context than this flag
        # would have given whisper); repair.py is too late, the cards are cut by then.
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
                    words.append(
                        {"text": w.word, "start": w.start, "end": w.end, "prob": getattr(w, "probability", 1.0) or 1.0, "seg": si}
                    )
            else:  # no word timestamps -> whole segment as one "word"
                words.append(
                    {"text": s.text, "start": s.start, "end": s.end, "prob": min(1.0, math.exp(s.avg_logprob)), "seg": si}
                )
        audio_duration = _apply_audio_start_offset(words, segments, audio_duration, audio_start_time(video, idx))
    try:
        os.remove(fail)  # transcription finished -> clear in-flight mark
    except OSError:
        pass
    # A0: restore sentence punctuation to the WORD LIST before anything splits it. This has
    # to happen here and not in repair.py: repair edits card text, but by then the cards are
    # already split and timed, so the text would read better while the boundaries stayed
    # wrong (reflow has nothing to split on in an unpunctuated run and cuts on character
    # balance instead -- mid-phrase, across speaker changes). Any failure is a no-op; see
    # punctuation.restore's docstring.
    rec = qc.Recorder()
    punctuation.restore(words, segments, rec, stem=stem)
    # S-2: persist the word list HERE -- after restore() has mutated word["text"] in
    # place, before reflow splits anything -- so a text-tier re-run replays these exact
    # inputs with no GPU and no punctuation LLM call. Never fatal: the transcription
    # output is already committed by this point, so a failed sidecar write costs the
    # episode its cheap path, not its run. It is COUNTED, because an uncacheable episode
    # that says nothing looks identical to one that simply needed transcribing.
    try:
        write_words(stem, words, segments, audio_duration, initial_prompt=INITIAL_PROMPT)
    except Exception as e:
        rec.count("words_missing")
        log("words.json write failed (episode stays GPU-only):", stem, e)
    return text_stages(stem, words, segments, audio_duration, rec, fail)


def build_lastrun(show, elapsed_s, episodes_total, transcribed, totals, census):
    """The per-show run summary written to glossaries/<show>.lastrun.json.

    One builder rather than a dict literal plus a parallel list of field names: the
    per-tier staleness counts only earn their keep if something actually reports them,
    and two declarations of "what lastrun contains" would drift until one of them lied.
    Tests assert against this function, so the file and the assertion cannot disagree."""
    return {
        "show": show,
        "elapsed_s": elapsed_s,
        "episodes_total": episodes_total,
        "episodes_transcribed": transcribed,
        "cards_written": totals["cards_written"],
        "dropped_hallucination": totals["dropped_hallucination"],
        "collapsed_runs": totals["collapsed_runs"],
        "flagged": totals["flagged"],
        # GPU-hours vs CPU-minutes: reported separately or the split means nothing.
        "transcribe_stale": census["transcribe_stale"],
        "text_stale": census["text_stale"],
        "model": MODEL,
        "model_version": _model_version(),
        "glossary_version": _glossary_version(),
    }


def _staleness_census(files):
    """How many of ``files`` are behind in each tier, counted independently.

    Separate counts because the two costs are not comparable: transcribe-stale is
    GPU-hours, text-stale is CPU-minutes. A single combined "stale" number would hide
    exactly the distinction the tier split exists to expose. A transcribe-stale episode
    is text-stale too (new words invalidate everything derived from them), so text_stale
    is always >= transcribe_stale.

    Never raises: a corrupt or hand-edited stamp counts as fully stale, because this runs
    over a whole library and one bad sidecar must not abort the sweep."""
    census = {"transcribe_stale": 0, "text_stale": 0}
    for v in files:
        stem = os.path.splitext(v)[0]
        stale = stale_tiers(read_stamp(stem + STAMP_SUFFIX), v)
        if "transcribe" in stale:
            census["transcribe_stale"] += 1
        if "text" in stale:
            census["text_stale"] += 1
    return census


def main():
    args = sys.argv[1:]
    files = []
    if args and args[0] == "--root":
        for dp, dns, fs in os.walk(args[1]):
            dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]  # prune extras dirs
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
        if stamp_valid(stamp, v):
            return False  # muxed at the current version -> done
        if os.path.exists(stem + ".dubtitles.fail"):
            return False  # poison marker wins
        # Superseded output: its leftover sidecars are stale, so the checks below must not
        # read them as "done" -- process() discards them and re-transcribes.
        if stale_version_stamp(stamp, v):
            return True
        if os.path.exists(stem + ".eng.dubtitles.ass"):
            return False
        if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"):
            return False
        return True

    todo = [v for v in files if needs_work(v)]
    # Split what needs doing by TIER. needs_work() stays the gate (it also honours the
    # pending-sidecar and poison-marker skips); this only decides which queue the
    # survivors land in.
    transcribe_todo, text_todo = partition_todo(todo)
    # Counted over EVERY file, not just todo: the question this answers is "how far
    # behind is the part of the library I am not watching", and that is invisible if it
    # only counts what is already queued.
    census = _staleness_census(files)
    log(
        f"model={MODEL} compute={COMPUTE} require_eng={os.environ.get('REQUIRE_ENG', '1')} "
        f"files={len(files)} todo={len(todo)} "
        f"transcribe={len(transcribe_todo)} text={len(text_todo)} "
        f"transcribe_stale={census['transcribe_stale']} text_stale={census['text_stale']}"
    )
    if not todo:
        log("nothing to transcribe (all done) — skipping model load")
        return
    # The model is loaded ONLY when something actually needs the decoder. A text-only
    # sweep otherwise paid a ~40s GPU model load to perform zero transcription, which
    # would have made the cheap tier quietly not cheap.
    if transcribe_todo:
        globals()["WMODEL"] = WhisperModel(MODEL, device="cuda", compute_type=COMPUTE, download_root=MODEL_DIR)
    else:
        log("text-tier work only — skipping the model load")
    t0 = time.monotonic()  # V2 C1: per-show run summary
    transcribed = 0
    totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
    # Text tier first: it is CPU-minutes per episode, so the cheap wins land before the
    # GPU queue starts consuming the night.
    for v in text_todo:
        log("→", os.path.basename(v), "(text)")
        try:
            log("  ", process_text(v))
        except Exception as e:
            log("  ERROR", type(e).__name__, e)  # one bad sidecar must not abort the show
    for v in transcribe_todo:
        log("→", os.path.basename(v))
        try:
            status = process(v)  # one bad episode must not abort the show
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
                log("  CUDA/GPU error (RuntimeError) -> exiting to rebuild a clean GPU context (show resumes on restart)")
                sys.exit(3)
            # Non-RuntimeError: NOT a GPU error -> don't poison the episode. Clear the .fail
            # marker so the next sweep retries it, and persist a small JSON record of what
            # happened (V2 C15's retry log) for later triage.
            stem = os.path.splitext(v)[0]
            try:
                os.remove(stem + ".dubtitles.fail")
            except OSError:
                pass
            try:
                with open(out_for(stem + ".dubtitles.crash.json"), "w") as f:
                    json.dump({"path": v, "exc_type": type(e).__name__, "msg": str(e), "time": time.time()}, f)
            except OSError:
                pass
    # V2 C1: per-show run summary (glossaries/<show>.lastrun.json) -- one file per --root
    # invocation, since SHOW_NAME/GLOSSARY_FILE are per-run env (see load_glossary()).
    show = os.environ.get("SHOW_NAME", "") or GLOSS.get("show", "") or "unknown_show"
    lastrun = build_lastrun(show, round(time.monotonic() - t0, 1), len(todo), transcribed, totals, census)
    try:
        os.makedirs(GLOSS_DIR, exist_ok=True)
        with open(os.path.join(GLOSS_DIR, show + ".lastrun.json"), "w") as f:
            json.dump(lastrun, f, indent=2)
    except OSError as e:
        log("  lastrun.json write failed:", e)


if __name__ == "__main__":
    main()
