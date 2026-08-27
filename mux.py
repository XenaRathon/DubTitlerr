#!/usr/bin/env python3
"""MUX stage — embed the merged dubtitle .ass into the mkv as a default
"Dubtitles" subtitle track, set the English audio + Dubtitles track as the
defaults, and (the whole point of muxing) carry the embedded fonts so signs
render in their correct typeface.

Per video that has a sibling dubtitle sidecar (``.eng.dubtitles.ass`` for an mkv with
signs/songs, else ``.eng.dubtitles.srt`` for an mp4 dialogue-only episode):
  * SKIP if already muxed — a valid, current-in-both-tiers ``.dubtitles.done``
    stamp (stat-only). This is the ONLY skip guard: the old "embedded Dubtitles track"
    ffprobe backstop is gone, because a re-mux now REPLACES the old track rather than
    duplicating it, so re-running is idempotent and self-healing,
  * SKIP if the pool lacks room for a full-size temp (free-space pre-check; never ENOSPC),
  * mkvmerge remux (stream copy, no re-encode) to an **mkv**: drop any OLD "Dubtitles"
    track and add the sidecar as track-name "Dubtitles" / default in the same pass (so a
    regeneration replaces in place — no separate pre-strip); set eng audio default,
    original-language audio not; keep eng/orig/mul/signs-songs subs (drop other-language
    dialogue subs); keep all fonts,
  * VERIFY (a/v + the Dubtitles track + duration within tolerance) before touching the original,
  * finalize the muxed mkv (atomic, with a cross-branch fallback), preserving ownership;
    for an mp4 source, remove the OLD ``.mp4`` library link (the seeding download hardlink
    partner is left alone — the orphan-reaper owns it per seed-until-orphan),
  * write the ``.dubtitles.done`` stamp, then remove the sidecar.

DRY-RUN by default (prints the plan); pass --apply to do it. Run as root.
Env: MUX_ROOTS (colon list), KEEP_LANGS, MIN_FREE_GB (skip threshold, default 5),
DUR_TOL (seconds, default 2), MEDIA_UID/GID.
  REVIEW_GATE_SHOWS      colon list of show DIRECTORY names (e.g. "Cowboy Bebop (1998)
                         {tvdb-76885}", not "Cowboy Bebop" -- the same identity the
                         decision store uses). EMPTY by default. [S-6]: an episode of a listed show
                         is held back from the mux while it still has pending
                         `repair_applied` entries -- repairs accept_repair admitted with
                         nothing checking their meaning. Unlisted shows are unaffected.
  REVIEW_GATE_STALE_DAYS default 7. A hold older than this is reported LOUDLY and is still
                         held. It buys a log line, never a release: auto-releasing
                         unreviewed repairs is the failure the review loop exists to
                         prevent.
Requires mkvtoolnix (mkvmerge) + ffprobe.  Built with help of Claude (Anthropic).
"""

import argparse
import errno
import json
import os
import re
import shutil
import subprocess
import time

import unresolved
from common import MEDIA_GID, MEDIA_UID, STAMP_SUFFIX, TRACK_NAME, is_our_track, log, read_stamp, stamp_valid, write_stamp

# Imported as a NAME so "which show is this path in" has exactly one definition, shared
# with the decision store. A second answer here would gate one show while storing verdicts
# under another, and the two would only disagree for the shows an operator actually listed.
from decisions import decisions_for, lookup, show_for

ROOTS = os.environ.get("MUX_ROOTS", "/data/Media/Anime Library").split(":")
# [S-6] Shows whose episodes wait for a human before they are released. Colon list, the
# MUX_ROOTS idiom. EMPTY BY DEFAULT: every install that has not opted in behaves exactly as
# it did before this existed.
REVIEW_GATE_SHOWS = [s.strip() for s in os.environ.get("REVIEW_GATE_SHOWS", "").split(":") if s.strip()]
# How long a hold may sit before it is reported. This buys a LOG LINE and nothing else --
# see held_for_review for why it must never buy a release.
REVIEW_GATE_STALE_DAYS = float(os.environ.get("REVIEW_GATE_STALE_DAYS", "7"))
# Shows already warned about, so a misconfigured season prints one line per sweep rather
# than one per episode. A warning nobody can read is the same as no warning.
_warned_unresolved: set = set()
# Every show name actually resolved during this run, so main() can report a listed name
# that matched nothing. See the REVIEW_GATE_SHOWS note in the module docstring.
_shows_seen: set = set()
# Base audio/subtitle languages to KEEP. The title's ORIGINAL language is detected
# per-file (the default audio track's language — Japanese for anime, but whatever it
# actually is for other content) and added to this set. Everything else (fre, spa,
# ger, …) is dropped. Video + the new Dubtitles track + all font attachments always kept.
KEEP_LANGS = set(os.environ.get("KEEP_LANGS", "eng,en,dut,nld,nl,und,").split(","))
_val = os.environ.get("HARDLINK_ROOTS")
HL_ROOTS = _val.split(":") if _val else ROOTS
DUR_TOL = float(os.environ.get("DUR_TOL", "2"))
MIN_FREE_GB = float(os.environ.get("MIN_FREE_GB", "5"))  # skip a remux if the pool is this low
SIZE_FACTOR = 1.1  # temp ~ source size (+headroom)
ASS_SUFFIX = ".eng.dubtitles.ass"
SRT_SUFFIX = ".eng.dubtitles.srt"
# subtitle track names that mark a signs/songs track worth keeping regardless of language
SIGNS_RE = re.compile(r"sign|song|karaoke|lyric|caption|title|credit|insert", re.I)


def has_room(free_bytes: float, src_size: int) -> bool:
    """True if there's room for a full-size temp plus the MIN_FREE_GB safety margin."""
    return free_bytes >= src_size * SIZE_FACTOR + MIN_FREE_GB * (1 << 30)


def keep_sub(track: dict, keep_langs: set) -> bool:
    """Keep an mkvmerge subtitle track if its language is wanted, it's multi-language ('mul'),
    or its name reads as signs/songs (so weird JoJo signs tracks survive).

    Our OWN previously-muxed dubtitle (track_name == TRACK_NAME) is always dropped, and
    that check comes FIRST: the track is language=eng, so every rule below would keep it
    and the remux would end up carrying two Dubtitles tracks. Dropping it here is what
    makes a re-mux a REPLACE (build_cmd re-adds the new one in the same pass) instead of
    a duplicate — and what retired the separate pre-strip pass."""
    props = track.get("properties") or {}
    if is_our_track(props.get("track_name")):
        return False
    lang = (props.get("language") or "").lower()
    if lang in keep_langs or lang == "mul":
        return True
    return bool(SIGNS_RE.search(props.get("track_name") or ""))


_IDENTIFY_CACHE: dict = {}


def identify(path):
    """mkvmerge -J, cached per path — build_cmd() and verify() both identify files;
    caching avoids the duplicate subprocess call."""
    if path not in _IDENTIFY_CACHE:
        r = subprocess.run(["mkvmerge", "-J", path], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        _IDENTIFY_CACHE[path] = json.loads(r.stdout)
    return _IDENTIFY_CACHE[path]


def has_dubtitles_track(info):
    """True if an mkvmerge -J dict carries a subtitle track named TRACK_NAME. Used only
    by verify(), to confirm the NEW track landed before the atomic replace (it is no
    longer a skip guard — see process())."""
    for t in info.get("tracks", []):
        if t.get("type") == "subtitles" and is_our_track((t.get("properties") or {}).get("track_name")):
            return True
    return False


def duration(path):
    """Container duration. NOTE: in Matroska this is the LONGEST track, so it is NOT a
    safe truncation signal for a remux that drops tracks -- use video_duration() for that.
    Kept because it is still the right number for "how long is this file"."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def _parse_duration(v):
    """Matroska's DURATION tag ("00:23:54.849708333") -> seconds; None if unparseable."""
    if not v or not isinstance(v, str):
        return None
    parts = v.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    except ValueError:
        return None


def _ffprobe_video(path):
    """First video stream's duration field + tags (split out so tests can stub the I/O)."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration:stream_tags=DURATION",
                "-of",
                "json",
                path,
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        streams = json.loads(r.stdout).get("streams", [])
        return streams[0] if streams else {}
    except Exception:
        return {}


def video_duration(path):
    """Duration of the VIDEO track -- the only thing a truncated remux would shorten.

    Container duration is unusable here: Matroska reports the longest track, and releases
    commonly ship a foreign subtitle running past the end of the video (JUJUTSU KAISEN
    S02E04 has a Polish fansub ending 19s after the picture does). Dropping such a track,
    which is exactly what this stage is for, shortens the container by ~19s and made the
    old container-vs-container check reject a perfectly good remux forever.

    Matroska usually leaves stream=duration as N/A and carries a DURATION tag instead, so
    try the field, then the tag, then fall back to the container figure."""
    st = _ffprobe_video(path)
    try:
        d = float(st.get("duration"))
        if d > 0:
            return d
    except (TypeError, ValueError):
        pass
    tagged = _parse_duration((st.get("tags") or {}).get("DURATION"))
    return tagged if tagged is not None else duration(path)


_partners_cache: dict[tuple[int, int], list[str]] = {}


def original_langs(info):
    """Original-language audio = the default audio track's language (fallback: first
    audio track). Anime -> jpn, but adapts to whatever the content actually is."""
    auds = [t for t in info.get("tracks", []) if t["type"] == "audio"]
    defs = [t for t in auds if (t.get("properties") or {}).get("default_track")]
    src = defs or auds[:1]
    return {((t.get("properties") or {}).get("language") or "").lower() for t in src} - {""}


def _stages_ran(stem: str, src: str) -> dict:
    """Which pipeline stages demonstrably ran, read from the sidecars still on disk.

    mux stamps AFTER repair / signs-merge / generate and BEFORE their sidecars are removed,
    so this is the one moment the pipeline can record what "done" actually meant. Without it
    an episode where repair never ran is indistinguishable from one where it ran and found
    nothing -- merge_pass.sh has no `set -e` and checks no exit status, so a stage that died
    still reached here and still stamped.

    A stage whose evidence is UNKNOWABLE is omitted, never reported False. "Did not run" and
    "cannot tell" are different claims; tools/vad.py makes the same distinction by returning
    None rather than a confident wrong answer."""
    st = {
        # repair writes its summary unconditionally, even when every card was skipped
        "repair": os.path.exists(stem + ".dubtitles.repair-summary.json"),
        # an .ass source means the signs/songs track was merged in; a bare .srt means it was not
        "signs_merge": src.endswith(ASS_SUFFIX),
    }
    try:
        with open(stem + ".dubtitles.qc.json", encoding="utf-8") as f:
            counters = json.load(f).get("counters") or {}
        st["punctuation"] = counters.get("restore_runs_sent", 0) > 0
    except (OSError, ValueError):
        pass  # no qc sidecar (pre-QC episode) -> cannot tell, so say nothing
    return st


def build_cmd(info, orig, ass, out):
    """Returns (mkvmerge cmd, [dropped track descriptions]). Keeps eng/dut + the original
    language audio, and eng/orig/mul/signs-songs subs; sets eng audio + Dubtitles default;
    keeps video + all attachments. ``info`` is an ``mkvmerge -J`` dict (passed for testability)."""
    keep = KEEP_LANGS | original_langs(info)
    audio_keep, sub_keep, dropped = [], [], []
    for t in info.get("tracks", []):
        tid = t["id"]
        lang = ((t.get("properties") or {}).get("language") or "").lower()
        if t["type"] == "audio":
            (audio_keep if lang in keep else dropped).append(str(tid) if lang in keep else f"audio:{lang or 'und'}")
        elif t["type"] == "subtitles":
            if keep_sub(t, keep):
                sub_keep.append(str(tid))
            elif is_our_track((t.get("properties") or {}).get("track_name")):
                dropped.append(f"sub:{TRACK_NAME}(old)")  # labelled so the mux log shows the strip
            else:
                dropped.append(f"sub:{lang or 'und'}")
    cmd = ["mkvmerge", "-o", out]
    if audio_keep:
        cmd += ["-a", ",".join(audio_keep)]  # else: keep all audio (safety)
    # -s is a WHITELIST and mkvmerge's default is copy-every-subtitle-track, so an empty
    # keep list must become an explicit -S ("no source subs") — omitting the flag would
    # copy back the very tracks `dropped` claims were removed. That is the mp4-origin /
    # only-sub-is-our-old-dubtitle case: without -S the file ends up with TWO Dubtitles
    # tracks, and verify() (presence-only) would pass it and stamp it.
    cmd += ["-s", ",".join(sub_keep)] if sub_keep else ["-S"]
    for t in info.get("tracks", []):
        tid = t["id"]
        lang = ((t.get("properties") or {}).get("language") or "").lower()
        if t["type"] == "audio" and str(tid) in audio_keep:
            cmd += ["--default-track-flag", f"{tid}:{'yes' if lang in ('eng', 'en') else 'no'}"]
        elif t["type"] == "subtitles" and str(tid) in sub_keep:
            cmd += ["--default-track-flag", f"{tid}:no"]
    cmd += [
        orig,
        "--track-name",
        f"0:{TRACK_NAME}",
        "--language",
        "0:eng",
        "--default-track-flag",
        "0:yes",
        "--sub-charset",
        "0:UTF-8",
        ass,
    ]
    return cmd, dropped


def verify(orig, out):
    """The half-size heuristic (C16) is gone -- it false-positived on compact muxes where
    mkvmerge shrinks the CUES or drops a large embedded .ass. The duration-tolerance check
    below is the real truncation canary: it runs unconditionally on the only path to "ok"."""
    info = identify(out)
    types = {t["type"] for t in info.get("tracks", [])}
    if "video" not in types or "audio" not in types:
        return "missing-av"
    if not has_dubtitles_track(info):
        return "no-dubtitles-track"
    if abs(video_duration(out) - video_duration(orig)) > DUR_TOL:
        return "duration-mismatch"
    # D2: font-attachment audit -- mkvmerge -J reports attachments as a top-level
    # "attachments" array (sibling of "tracks"), NOT as track entries; .get(..., [])
    # treats a fontless file (key absent) as 0, so equal-zero still returns "ok".
    src_fonts = identify(orig).get("attachments", [])
    out_fonts = info.get("attachments", [])
    if len(src_fonts) != len(out_fonts):
        return "font-count-mismatch"
    for f in out_fonts:
        if f.get("content_type") == "application/octet-stream":
            log(f"  font attachment '{f.get('file_name')}' has generic MIME type — may not be a valid font")
    return "ok"


def held_for_review(stem):
    """Whether this episode is waiting on a human. False for every unlisted show.

    Only `repair_applied` entries hold. A repair the guard REFUSED left the ASR text in
    place -- the safe outcome, and not something a viewer sees that nobody sanctioned. The
    admitted repair is the unchecked one: `accept_repair`'s own docstring states the bar and
    says nothing below it enforces meaning, and `factory -> needle` passes every gate. That
    is the class of change worth stopping a release for.

    A hold is NEVER released by this function on the strength of time. An episode past
    REVIEW_GATE_STALE_DAYS is reported loudly and stays held: auto-releasing unreviewed
    repairs is the exact failure this spec exists to prevent, and an alert that becomes a
    release is worse than no alert, because it reads as supervision."""
    if not REVIEW_GATE_SHOWS:
        return False
    show = show_for(stem)
    if not show:
        # The operator opted IN and we cannot tell which show this is, so the gate silently
        # does not apply: "" never matches a listed name, the episode muxes, and they
        # believe unreviewed repairs are being held while every one of them ships. Silence
        # is the failure here, not the miss.
        d = os.path.dirname(stem)
        if d not in _warned_unresolved:
            _warned_unresolved.add(d)
            log(f"  WARNING: review gate is on but cannot resolve a show for {d} — check GLOSSARY_DIR; NOT gated")
        return False
    _shows_seen.add(show)
    if show not in REVIEW_GATE_SHOWS:
        return False
    pend = [e for e in unresolved.pending(stem) if e.get("stage") == "repair_applied"]
    if not pend:
        return False
    # A line with a stored VERDICT is settled, whatever its queue flag says. resolve() and
    # decisions.record() are independent write paths: the verdict is what stops repair.py
    # re-queueing the line, the flag is only what the --review CLI sets. Trusting the flag
    # alone would hold an episode forever on a line the pipeline already considers decided
    # -- a verdict written by hand, by a future sync, or by a server whose resolve() write
    # failed. Resolved here rather than at the call site so the queue file is only read for
    # episodes that are actually candidates for a hold.
    store, _ = decisions_for(stem)
    if store:
        pend = [e for e in pend if not lookup(store, e.get("original_text", ""), e.get("proposed_text", ""))]
        if not pend:
            return False
    # Entries carry no timestamp, so the sidecar's mtime is the only staleness signal
    # available -- a deliberate approximation, and it moves whenever repair appends, which
    # makes it "time since the queue last changed" rather than "time since the oldest
    # entry". Good enough to surface a backlog; not a clock anything branches on.
    try:
        age_days = (time.time() - os.path.getmtime(unresolved.path_for(stem))) / 86400.0
    except OSError:
        age_days = 0.0
    if age_days > REVIEW_GATE_STALE_DAYS:
        log(
            f"  STALLED: {os.path.basename(stem)} held for review {age_days:.0f}d "
            f"(> {REVIEW_GATE_STALE_DAYS:g}d), {len(pend)} pending — NOT released; run the review"
        )
    return True


def sub_source(stem):
    """The subtitle sidecar to embed: the merged .ass (mkv w/ signs) else the terminal
    .srt (mp4, dialogue only). None if neither exists yet."""
    for suff in (ASS_SUFFIX, SRT_SUFFIX):
        if os.path.exists(stem + suff):
            return stem + suff
    return None


def _free_bytes(path):
    try:
        s = os.statvfs(os.path.dirname(path) or ".")
        return s.f_bavail * s.f_frsize
    except OSError:
        return float("inf")


def _finalize(tmp, dst):
    """Move tmp -> dst atomically; fall back to a cross-branch copy on mergerfs EXDEV."""
    try:
        os.replace(tmp, dst)
    except OSError as e:
        if getattr(e, "errno", None) == errno.EXDEV:
            shutil.move(tmp, dst)
        else:
            raise


def process(orig, apply):
    stem, ext = os.path.splitext(orig)
    stamp = stem + STAMP_SUFFIX
    src = sub_source(stem)
    if src is None:
        return "no-sub"
    if stamp_valid(read_stamp(stamp), orig):
        return "already-muxed"  # stat-only, version-aware stamp is the ONLY guard
    # AFTER the stamp check, not before it (the plan sketched the reverse). An episode that
    # already shipped cannot be held back -- reporting a hold for it would inflate the
    # backlog count with episodes no review can affect, and hide "already-muxed" behind a
    # status the operator is meant to act on.
    if held_for_review(stem):
        return "held-for-review"
    if not has_room(_free_bytes(orig), os.path.getsize(orig)):
        log("  skip (low disk):", os.path.basename(orig))
        return "skip-no-room"
    out = stem + ".muxtmp.mkv"
    final = stem + ".mkv"  # every episode ends as an mkv
    cmd, dropped = build_cmd(identify(orig), orig, src, out)
    if not apply:
        log(f"  PLAN mux {os.path.basename(orig)} ({ext}->mkv)  drop-tracks={dropped}")
        return "plan"
    try:
        st = os.stat(orig)
        subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800, check=False)
        res = verify(orig, out)
        if res != "ok":
            if os.path.exists(out):
                os.remove(out)
            return "verify-" + res
        os.chown(out, st.st_uid or MEDIA_UID, st.st_gid or MEDIA_GID)
        _finalize(out, final)  # write the muxed mkv
        if os.path.abspath(orig) != os.path.abspath(final) and os.path.exists(orig):
            os.remove(orig)  # mp4->mkv: drop the OLD library link (partner survives)
        try:
            write_stamp(stamp, final, stages=_stages_ran(stem, src))
            # stamp BEFORE removing sidecars (crash-safe skip)
        except OSError as e:
            # The remux already landed, but the stamp is now the ONLY record that this
            # file is done (the ffprobe backstop is gone). Without a stamp the next sweep
            # redoes the whole multi-GB mkvmerge — every sweep, forever. Keep the sidecars
            # so a retry can still succeed, and surface it as its own status rather than
            # letting it read as a normal "muxed" line.
            log(
                f"  ERROR: muxed OK but stamp write FAILED ({e}) — {os.path.basename(final)} "
                f"will be re-muxed every sweep until the stamp can be written"
            )
            return "stamp-write-failed"
        for suff in (ASS_SUFFIX, SRT_SUFFIX):
            try:
                os.remove(stem + suff)
            except OSError:
                pass
        with open(stem + ".dubtitles.mux.log", "w") as f:
            f.write(f"muxed {os.path.basename(orig)} -> mkv; eng audio + Dubtitles default\n")
            f.write("dropped non-keep tracks: " + ", ".join(dropped) + "\n")
        log(f"  muxed ({ext}->mkv); dropped {len(dropped)} foreign track(s)")
        return "muxed"
    except Exception as e:
        if os.path.exists(out):
            os.remove(out)
        log("  mux error:", e)
        return "error"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("paths", nargs="*", help="explicit video paths; else walk MUX_ROOTS")
    a = ap.parse_args(argv)
    if a.apply and os.geteuid() != 0:
        log("WARNING: not root — atomic replace may fail (mergerfs perms).")
    vids = list(a.paths)
    if not vids:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                vids += [os.path.join(dp, f) for f in files if f.lower().endswith((".mkv", ".mp4", ".m4v"))]
    counts = {}
    for v in vids:
        res = process(v, a.apply)
        counts[res] = counts.get(res, 0) + 1
        if res not in ("no-sub", "already-muxed"):
            log(f"{res}: {os.path.basename(v)}")
    # A listed name that matched nothing is almost always the display name where the
    # DIRECTORY BASENAME was wanted ("Cowboy Bebop" vs "Cowboy Bebop (1998) {tvdb-76885}").
    # show_for returns a non-empty string in that case, so the unresolved-show warning above
    # never fires: the gate is simply off, and silence is indistinguishable from success.
    for name in REVIEW_GATE_SHOWS:
        if name not in _shows_seen:
            log(
                f"  WARNING: REVIEW_GATE_SHOWS entry {name!r} never matched a show this sweep — "
                f"it must be the show's DIRECTORY name. Saw: {sorted(_shows_seen) or 'none'}"
            )
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
