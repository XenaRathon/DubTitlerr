#!/usr/bin/env python3
"""Shared stdlib-only helpers for the DubTitlerr pipeline stages (generate.py, mux.py,
repair.py, dub_signs_merge.py, mine_glossary.py, recreate_srt.py).

Single source of truth for the helpers that used to be duplicated per-module (see
specs/v1-polish/spec.md, Phase 1 — Foundation). Stdlib + pysubs2: no imports from other
project modules, so any pipeline stage can import this without dragging in the rest
of the pipeline (and without risking a circular import).
"""

import http.client
import json
import os
import re
import subprocess
import tempfile
import urllib.parse

import pysubs2

MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))

# Sidecars must be GROUP-WRITABLE. 2026-08-21: every sidecar shipped 0644, so only the
# creating uid could ever overwrite one. That is invisible while the container runs as root
# (root bypasses the check) and breaks the moment any other member of the media group writes
# -- the 3200g node reaches the library over CIFS as r520smb (uid 1001, gid 100 users), hit
# "Permission denied" re-writing an existing .dubtitles.done, and re-muxed the same episode
# on every sweep because the stamp could never land. 8,701 sidecars library-wide were 0644.
#
# umask 002 covers the plain open(path, "w") sites (write_stamp, the .fail marker,
# crash/lastrun json, repair's srt + summary, mux.log). It is set at import because every
# pipeline module imports common, so there is exactly one place to get this right. Sites that
# chmod EXPLICITLY override umask and must use SIDECAR_MODE instead -- see _atomic_write in
# generate.py and qc.write (qc.py is deliberately standalone and hardcodes the same value;
# test_qc_mode_matches_common pins the two together).
SIDECAR_MODE = 0o664
os.umask(0o002)

# OUTPUT_ROOT: write sidecars/output files to this branch path instead of next to the
# source media, so writes land on a disk with space (mergerfs unifies branches, so the
# file still shows next to the source in the pool view). READS still use MEDIA_ROOT.
# Empty OUTPUT_ROOT = write in place.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")

VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

# SUB_LANGS: accepted embedded-sub languages for dialogue_intervals()'s default (all-stream)
# path -- same env var/default repair.py has always read (T1 hoist: single source of truth).
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))

# Dialogue-vs-sign/karaoke predicate (hoisted verbatim from repair.py's pre-refactor
# dialogue_intervals -- do not tweak without checking dub_signs_merge.py's classifier too,
# which uses a related but NOT identical KEEP_STYLE/DROP_STYLE pair for its own purpose).
KARAOKE = re.compile(r"\\[kK][fo]?\d")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
DROP_STYLE = re.compile(r"warning", re.I)  # junk, never a dialogue reference
DIALOGUE_EXCLUDE_STYLE = re.compile(r"karaoke|translat|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)


def load_extras(path="data/extras.txt"):
    """Load the EXTRA_DIRS set (Plex "local extras" subfolders + creditless/scene clips --
    never real episodes, often mismatched junk from the scraper -- pruned from library
    walks) from the single-source-of-truth data file (see specs/v2-models-ops/spec.md,
    "EXTRA_DIRS consolidation"). Falls back to the pre-consolidation hardcoded set if the
    file is missing/unreadable, so the pipeline still runs correctly without it (e.g. a
    dev checkout, or an image built before the data file existed)."""
    try:
        with open(path) as f:
            return {ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")}
    except OSError:
        return {
            "behind the scenes",
            "deleted scenes",
            "featurettes",
            "interviews",
            "scenes",
            "shorts",
            "trailers",
            "other",
            "extras",
        }


# Plex "local extras" subfolders + creditless/scene clips — never real episodes, often
# mismatched junk from the scraper. Pruned from library walks.
EXTRA_DIRS = load_extras()

STAMP_SUFFIX = ".dubtitles.done"

# TRACK_NAME: the mkv subtitle-track name mux.py stamps on our own generated dubtitle.
# It is self-authored and used nowhere else, so it doubles as the marker that keeps the
# pipeline from reading its OWN previous output as if it were the human fansub -- every
# context reader (eng_sub_streams below, mine_glossary.py's selector) excludes it, and
# mux.keep_sub() drops it so a re-mux replaces rather than duplicates it.
TRACK_NAME = "Dubtitles"

# The output versions recorded in each .dubtitles.done stamp. A file whose stamp is
# behind in either tier reads as STALE and is regenerated in place. Bumping either is a
# deliberate operator action -- the only thing that triggers a global regeneration.
# History below is the bump manual: every entry says what changed in the OUTPUT and why
# only a regeneration puts it into the files. Entries v2-v4 predate the tier split and
# were single-version bumps; read them as transcribe-tier bumps.
# v2 (2026-07-27): every v1 dubtitle has broken signs. The merge deduplicated events on
# their PLAINTEXT, which collapsed each stacked typeset composition to its black backing
# layer and threw away the white top layer, so credits/captions/titles rendered solid
# black; and it lifted signs from every English track at once, rendering them two or
# three times over. Both are fixed, and only a regeneration puts the corrected signs into
# the files.
# v3 (2026-08-20): three changes that alter the OUTPUT, so only a regeneration puts them
# into the files. (a) Cards below MIN_DUR are fixed -- 1,542 of them in one 22-episode
# season -- by merging a runt back into the sentence it was split from, or stealing time
# forward; 9 overlapping card pairs are repaired at the same time. (b) repair.py rewrites
# the srt from conf.json, which stores text FLATTENED, and never re-wrapped it: ZERO
# multi-line cues existed anywhere in the library and 25-32% of cues ran past 42
# characters. (c) Sentence punctuation is restored before cards are split -- Whisper
# decodes each segment cold (condition_on_previous_text=False, forced by both segment
# collapse and VRAM), so 27% of cards arrived with no terminal punctuation and
# _split_sentences had nothing to split on.
# v4 (2026-08-21): two output-changing fixes that must be applied universally, plus the
# observability work that makes a stale rule visible. (a) reflow._text() joined whisper's
# word tokens with spaces, so every hyphenated word shipped with a space in it -- "Gas -Gas"
# for Caesar's Devil Fruit, "Gum -gum" for Luffy's attack. Not merely cosmetic: glossary
# phrase fixes match on \b<escaped>\b, so the mangled form silently failed to correct, and
# the two bugs compounded into one wrong line. (b) The One Pace glossary gained 9 hard_fixes
# (Gum-Gum and its mishearings, Gas-Gas, Tashigi, guinea pigs) chosen from a 22-episode scan.
# The 183 episodes stamped v3 were produced BEFORE both and carry the artefacts, so v3 is not
# a state worth keeping -- hence a bump rather than a targeted stamp deletion.
# v5 (2026-08-24): the single version becomes TWO, because one number made a glossary
# fix cost the same as a decoder change -- a full re-transcribe of the library. See
# .procoder/adr/0001-idempotency-is-keyed-on-two-tiers-not-one-version.md.
# v6 (2026-08-26): repair.py gained the phonetic name guard -- it rejects an LLM repair
# that substitutes a proper noun found in neither the glossary nor the original
# (Syrahose -> Shyarros, Hirohoshi -> Hihohi). Text produced before it can carry names
# the guard would now refuse, so the whole text tier is stale.
#
# TRANSCRIBE_VERSION covers audio -> words. Bump it for ANY decoder-affecting change:
#   the whisper model, WHISPER_BEAM_SIZE, the compute type, whisper's own thresholds,
#   vad settings, or the initial_prompt (which the glossary feeds -- generate.py:112).
#   NOTHING DETECTS THESE MECHANICALLY. A change to any of them that does not carry a
#   bump leaves the library silently stale, and this comment is the only guard.
# TEXT_VERSION covers everything downstream of the word list: punctuation, reflow,
#   glossary correction, repair, the merge, the mux.
#
# Adoption is 4/6, NOT 6/6. The 576 stamps live at v4 were produced by the current
# decoder, so they are transcribe-fresh and only text-stale: they migrate at
# watch-gated pace instead of burning ~2 GPU-days to record a bookkeeping change.
TRANSCRIBE_VERSION = 4
TEXT_VERSION = 6
# GRANDFATHER_VERSION: fixed constant, never changes. The version assumed for a stamp
# written before versioning existed (no "version" key). At introduction it equalled
# the pipeline version, so that rollout regenerated nothing.
GRANDFATHER_VERSION = 1


def log(*a):
    print(*a, flush=True)


def out_for(p):
    """Redirect a write path onto OUTPUT_ROOT (if configured) so writes land on a disk
    with space; creates intermediate directories (safe superset of the non-creating
    variant — callers that write to an already-existing dir are unaffected)."""
    if OUTPUT_ROOT and p.startswith(MEDIA_ROOT):
        q = OUTPUT_ROOT + p[len(MEDIA_ROOT) :]
        os.makedirs(os.path.dirname(q), exist_ok=True)
        return q
    return p


def ts_srt(t):
    """Format a float number-of-seconds as an SRT timestamp (HH:MM:SS,mmm)."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


WORDS_SUFFIX = ".dubtitles.words.json"
WORDS_SCHEMA_VERSION = 1


def read_words(stem, rec=None):
    """The persisted word list, or None when it cannot be used -- never an exception.

    Every unusable state is COUNTED rather than swallowed, because the failure mode this
    guards is silent: a sidecar that is never found looks exactly like an episode that
    simply needs transcribing, and would re-transcribe forever while reporting healthy.
    Read through out_for() to match write_words -- following one convention on write and
    the other on read is precisely that silent miss."""
    path = out_for(stem + WORDS_SUFFIX)
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        if rec:
            rec.count("words_missing")
        return None
    try:
        version = int(doc.get("transcribe_version"))
    except (TypeError, ValueError):
        version = None
    if version is None or version != TRANSCRIBE_VERSION:
        # A crash between transcription and stamping leaves a sidecar from the previous
        # transcribe tier. Serving it would replay an older decoder's transcript.
        if rec:
            rec.count("words_version_mismatch")
        return None
    if not doc.get("words"):
        if rec:
            rec.count("words_missing")
        return None
    if rec:
        rec.count("words_reused")
    return doc


def write_stamp(path: str, video: str, stages: dict | None = None) -> None:
    """Write the .dubtitles.done idempotency stamp recording the muxed file's size+mtime
    and the tier versions that produced it (stamp_valid rejects a stamp behind either
    tier, so a version bump marks every prior-version file stale).

    ``stages`` optionally records WHICH stages actually ran, e.g.
    ``{"repair": False, "signs_merge": True, "punctuation": True}``. The stamp used to say
    an episode was done without saying what "done" meant: merge_pass.sh has no ``set -e``
    and checks no exit status, so a stage that died still reached mux and still stamped, and
    "repair never ran" was indistinguishable from "repair ran and found nothing".

    ADDITIVE AND OPTIONAL, and stamp_valid ignores it. That is the whole constraint: if an
    older stamp stopped validating, every episode in the library would read as unprocessed
    and be fully re-transcribed -- roughly 12 GPU-hours to add a bookkeeping field. Omitted
    entirely when the caller does not know, rather than guessed."""
    st = os.stat(video)
    doc = {
        "size": st.st_size,
        "mtime": st.st_mtime,
        "muxed": True,
        # "version" is written for backward compatibility ONLY: an older build of this
        # pipeline, and scripts/migrate_write_v1_stamps.py, read it. A stamp without it
        # reads to them as pre-versioning (GRANDFATHER_VERSION) and therefore stale,
        # which would re-transcribe the library. TEXT_VERSION is the right value: it is
        # the version of the OUTPUT, which is what those readers are asking about.
        "version": TEXT_VERSION,
        "transcribe_version": TRANSCRIBE_VERSION,
        "text_version": TEXT_VERSION,
    }
    if stages:
        doc["stages"] = stages
    with open(path, "w") as f:
        json.dump(doc, f)


def read_stamp(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def stamp_version(stamp: dict) -> int | None:
    """The stamp's pipeline version. A missing key predates versioning -> GRANDFATHER_VERSION.
    ``None`` for a value that can't be read as an integer (hand-edited/corrupt stamp) —
    callers treat that as "not valid", never as an exception: this runs outside mux's
    try/except, so a single bad sidecar must not abort a whole sweep."""
    try:
        return int(stamp.get("version", GRANDFATHER_VERSION))
    except (TypeError, ValueError):
        return None


def _tier_version(stamp: dict, key: str) -> int | None:
    """One tier's version out of a stamp, falling back to the legacy single "version"
    key for the 813 stamps written before tiers existed. ``None`` for a value that
    cannot be read as an integer -- callers treat that as stale, never as an exception,
    because this runs outside mux's try/except and one bad sidecar must not abort a
    whole sweep."""
    raw = stamp.get(key, stamp.get("version", GRANDFATHER_VERSION))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def stale_tiers(stamp: dict | None, video: str) -> set[str]:
    """Which of {"transcribe", "text"} this stamp is behind on, empty when it is current.

    A missing stamp, an unmuxed one, or one describing a DIFFERENT file (size+mtime)
    is stale in both tiers: there is nothing to reuse. Otherwise each tier is compared
    independently, so a TEXT_VERSION bump costs CPU minutes instead of GPU hours."""
    if not stamp or not stamp.get("muxed") or not _stamp_matches_file(stamp, video):
        return {"transcribe", "text"}
    stale = set()
    tv = _tier_version(stamp, "transcribe_version")
    if tv is None or tv < TRANSCRIBE_VERSION:
        stale.add("transcribe")
        stale.add("text")  # new words invalidate everything derived from them
    xv = _tier_version(stamp, "text_version")
    if xv is None or xv < TEXT_VERSION:
        stale.add("text")
    return stale


def _stamp_matches_file(stamp: dict, video: str) -> bool:
    """True if the stamp describes THIS exact file (size + mtime), ignoring version."""
    try:
        st = os.stat(video)
    except OSError:
        return False
    return stamp.get("size") == st.st_size and abs(stamp.get("mtime", 0) - st.st_mtime) < 1.0


def stamp_valid(stamp: dict | None, video: str) -> bool:
    """True if the stamp matches the current file (size+mtime) AND is current in BOTH
    tiers — i.e. still muxed, not replaced, and not stale output. Unchanged in meaning
    and signature, so no caller had to move when the single version became two."""
    return not stale_tiers(stamp, video)


def stale_version_stamp(stamp: dict | None, video: str) -> bool:
    """True if the stamp is OUR stamp for exactly this file (muxed, size+mtime match) but
    records an older version in either tier.

    That state means the video IS our own output from a superseded pipeline — and
    therefore that any ``.eng.dubtitles.*`` sidecar sitting next to it is that same old
    run's leftover (mux removes sidecars on success, so one surviving here means the mux
    was interrupted after stamping). Those sidecars must NOT be treated as new work: the
    sidecar-existence skips in generate.py would otherwise block the re-transcribe while
    mux happily re-embedded the OLD subtitle and stamped it current — a version bump that
    silently no-ops on exactly the files it was meant to fix."""
    if not stamp or not stamp.get("muxed") or not _stamp_matches_file(stamp, video):
        return False
    return bool(stale_tiers(stamp, video))


def find_video(stem):
    for e in VIDEO_EXTS:
        if os.path.exists(stem + e):
            return stem + e
    return None


def stream_title(st: dict) -> str:
    """An ffprobe stream's title tag, normalized (missing/null tags -> "")."""
    return ((st.get("tags") or {}).get("title", "") or "").strip()


def is_our_track(name: str | None) -> bool:
    """True if a track name marks it as OUR generated dubtitle. One predicate for both
    shapes the pipeline sees — ffprobe's ``tags.title`` (via stream_title) and mkvmerge's
    ``properties.track_name`` — so the "is this ours?" test can't drift between the stage
    that EXCLUDES the track from context and the stage that DROPS it at mux. A drift there
    is silent: exclude-but-keep yields a duplicate track, keep-but-drop loses the fansub."""
    return (name or "").strip() == TRACK_NAME


def eng_sub_streams(video, sub_langs):
    """Indices of ASS/SSA subtitle streams in an accepted language, EXCLUDING our own
    previously-muxed dubtitle (title == TRACK_NAME). ``sub_langs`` is a set of lowercased
    language codes (each consumer keeps its own SUB_LANGS env-derived set — not unified
    here, since the two current callers already read the same env var to the same default
    and there's no behavior change from passing it explicitly).

    The exclusion lives here because this is the single chokepoint for every stage that
    reads an embedded sub as CONTEXT (repair.py's semantic reference, timing_compare's
    timing reference, dub_signs_merge's signs/songs source) — our old dubtitle is
    codec=ass/language=eng and would otherwise be picked up as if it were the fansub,
    so a regeneration would repair/align/mine against last version's own mistakes.
    There is deliberately NO fallback: an episode whose only English sub is our old
    dubtitle yields [] and the pipeline runs reference-free."""
    return [idx for idx, _title in eng_sub_tracks(video, sub_langs)]


def eng_sub_tracks(video, sub_langs):
    """``(index, title)`` for each usable English ASS/SSA stream — the shared probe behind
    eng_sub_streams() and signs_sub_streams(). Only the latter needs the title, but both
    must apply the same is_our_track() exclusion, so the filtering lives in one place."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index,codec_name:stream_tags=language,title",
                "-of",
                "json",
                video,
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=90,
        )
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e)
        return []
    out = []
    for st in streams:
        if st.get("codec_name") not in ("ass", "ssa"):
            continue
        if is_our_track(stream_title(st)):  # our own old output — never context
            continue
        if ((st.get("tags") or {}).get("language", "") or "").lower() in sub_langs:
            out.append((st["index"], stream_title(st)))
    return out


# A track whose title says it carries the signs/songs. Covers the spellings actually
# present in the library: "Signs & Songs", "S&S", "Signs/Songs", "English[Signs]",
# "Songs + Signs", "Signs and Songs(Hydes)". "Forced" counts too — a forced track is
# signs plus foreign-dialogue captions, and releases that ship ['Forced', ''] mean it
# as the signs track. Deliberately NOT "karaoke": "Karaoke / English / ASS / FLE" is a
# single mixed dialogue+karaoke track, not a signs-only one.
SIGNS_TITLE = re.compile(r"\bs\s*&\s*s\b|sign|\bforced\b|songs?\b", re.I)


def signs_sub_streams(video, sub_langs):
    """Stream indices to lift signs/songs from.

    Releases routinely ship the SAME signs typeset into several English tracks — a full
    dialogue track, a signs/songs track, sometimes a CC track (39 of this library's 79
    releases have more than one). Merging all of them renders every sign two or three
    times, a few pixels apart. So when any track names itself as the signs track, that
    one is the release's own curated signs list and the only one we read; if several do
    (rival groups' typesetting of the same signs), the first wins.

    Releases that name nothing usefully fall back to the historic behaviour — every
    track, classified per event by keep_event() — which is how a single mixed
    dialogue+signs track has always been handled."""
    tracks = eng_sub_tracks(video, sub_langs)
    signs = [idx for idx, title in tracks if SIGNS_TITLE.search(title or "")]
    return [signs[0]] if signs else [idx for idx, _ in tracks]


def extract_sub(video, idx, out):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}", "-c:s", "copy", out],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=180,
    )
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}", out],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=180,
        )
    return os.path.exists(out) and os.path.getsize(out) > 0


def is_dialogue_event(ev: "pysubs2.SSAEvent", txt: str | None = None) -> bool:
    """True if a pysubs2 event is a *plain dialogue* line -- not a comment, not a
    positioned/animated sign, not karaoke, and not on an excluded (sign/song/karaoke/etc.)
    style -- and has non-empty rendered text. This is the exact predicate T1 hoisted out of
    repair.py's pre-refactor dialogue_intervals(); reused by dialogue_intervals(),
    and the pure dialogue_density_score() scorer below.

    ``txt``, if given, is the caller's already-computed ``ev.plaintext.strip()`` -- lets a
    caller that also needs the stripped text (dialogue_intervals) avoid recomputing it here.
    Default (None) computes it internally, so every other call site is unaffected."""
    if ev.is_comment:
        return False
    t = ev.text
    if KARAOKE.search(t) or POSITIONED.search(t):  # sign/song, not dialogue
        return False
    style = ev.style or ""
    if DIALOGUE_EXCLUDE_STYLE.search(style) or DROP_STYLE.search(style):
        return False
    return bool(txt if txt is not None else ev.plaintext.strip())


def _load_stream_events(video, idx):
    """Extract subtitle stream ``idx`` to a scratch .ass and return its pysubs2 events, or
    ``[]`` on any extraction/parse failure (never raises) -- matches the original
    repair.dialogue_intervals try/except-and-skip behavior exactly."""
    with tempfile.TemporaryDirectory() as td:
        ex = os.path.join(td, "s.ass")
        if not extract_sub(video, idx, ex):
            return []
        try:
            return pysubs2.load(ex).events
        except Exception:
            return []


def dialogue_intervals(video, stream_indices=None):
    """Embedded DIALOGUE lines (the translation track) as (start_s, end_s, text), sorted.

    ``stream_indices=None`` (default) reproduces the exact pre-hoist repair.py behavior:
    every English subtitle stream (``eng_sub_streams(video, SUB_LANGS)``) is scanned and
    the results merged/sorted together. Pass an explicit iterable of stream indices to
    score/scan just those streams (e.g. one candidate track at a time, for per-track
    density scoring) -- the byte-identical default path is what repair.py's live callers
    (``process``/``overlap_ref``) depend on."""
    indices = eng_sub_streams(video, SUB_LANGS) if stream_indices is None else stream_indices
    ivals = []
    for idx in indices:
        for ev in _load_stream_events(video, idx):
            txt = ev.plaintext.strip()
            if is_dialogue_event(ev, txt):
                ivals.append((ev.start / 1000.0, ev.end / 1000.0, txt))
    ivals.sort()
    return ivals


def dialogue_density_score(events: list) -> tuple:
    """Pure scorer over a pre-loaded list of pysubs2.SSAEvent (no I/O): returns
    ``(dialogue_cue_count, plain_event_share)`` where ``dialogue_cue_count`` is the number
    of plain-dialogue events (is_dialogue_event) and ``plain_event_share`` is that count
    divided by the number of non-comment events on the track -- i.e. how much of the track
    is dialogue versus signs/karaoke/songs. ``(0, 0.0)`` for an empty or all-comment track."""
    non_comment = [ev for ev in events if not ev.is_comment]
    if not non_comment:
        return (0, 0.0)
    dialogue_count = sum(1 for ev in non_comment if is_dialogue_event(ev))
    return (dialogue_count, dialogue_count / len(non_comment))


# --- shared LLM client --------------------------------------------------------
#
# The ollama/llamacpp dispatch used to live only in repair.py, so glossary_verify.py had
# no way to reach anything but Ollama and the pipeline could not be consolidated onto a
# single model. Both stages now call llm_chat().

LLM_TIMEOUT_CONNECT = float(os.environ.get("LLM_TIMEOUT_CONNECT", "10"))
LLM_TIMEOUT_READ = float(os.environ.get("LLM_TIMEOUT_READ", "120"))


def _post_json(url, body, timeout=None):
    """POST ``body`` as JSON with SEPARATE connect and read timeouts.

    urlopen() exposes one timeout covering connect plus every read, so a server that
    accepts the connection and then streams nothing is indistinguishable from an
    unreachable host. Going one layer lower via http.client lets the connect timeout stay
    short while a slow model still gets its full read budget."""
    parsed = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = cls(parsed.hostname, parsed.port, timeout=LLM_TIMEOUT_CONNECT)
    try:
        conn.connect()
        conn.sock.settimeout(timeout or LLM_TIMEOUT_READ)
        path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        conn.request("POST", path, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {data[:200]!r}")
        return json.loads(data)
    finally:
        conn.close()


def llm_chat(prompt, *, backend="ollama", ollama_url=None, llamacpp_url=None, model=None, max_tokens=80, first_line=True):
    """One prompt in, the model's text out. ``""`` means "no answer" — never raises, since
    a transport error must not abort a whole show mid-sweep.

    llamacpp posts to ``/v1/chat/completions``, NOT ``/completion``: the latter applies no
    chat template, and a templated instruct model answers it with nothing but newlines.
    ``chat_template_kwargs.enable_thinking=false`` is required by this fork — with the
    template applied but thinking still on, the model spends its entire budget on
    ``reasoning_content`` and returns an empty message. No model selector is sent; a
    llama.cpp server has exactly one model loaded.

    ``first_line`` suits a subtitle (one line, often quoted by the model). Adjudication
    returns a multi-line JSON object and must pass ``first_line=False`` or it is truncated
    to its opening brace — and ``max_tokens`` high enough that the JSON isn't cut short."""
    if backend == "llamacpp":
        url = llamacpp_url
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    else:
        url = ollama_url
        body = {"model": model, "prompt": prompt, "stream": False, "think": False, "options": {"temperature": 0}}
    try:
        data = _post_json(url, body)
        out = (data["choices"][0]["message"].get("content") if backend == "llamacpp" else data.get("response", "")) or ""
        out = out.strip()
    except Exception as e:
        log("  llm fail:", e)
        return ""
    if not out:
        return ""
    return out.splitlines()[0].strip().strip('"').strip() if first_line else out
