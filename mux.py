#!/usr/bin/env python3
"""MUX stage — embed the merged dubtitle .ass into the mkv as a default
"Dubtitles" subtitle track, set the English audio + Dubtitles track as the
defaults, and (the whole point of muxing) carry the embedded fonts so signs
render in their correct typeface.

Per video that has a sibling dubtitle sidecar (``.eng.dubtitles.ass`` for an mkv with
signs/songs, else ``.eng.dubtitles.srt`` for an mp4 dialogue-only episode):
  * SKIP if already muxed — a valid ``.dubtitles.done`` stamp (stat-only) or an embedded
    "Dubtitles" track (ffprobe backstop); survives sidecar cleanup, makes re-runs safe,
  * SKIP if the pool lacks room for a full-size temp (free-space pre-check; never ENOSPC),
  * mkvmerge remux (stream copy, no re-encode) to an **mkv**: add the sidecar as track-name
    "Dubtitles" / default; set eng audio default, original-language audio not; keep
    eng/orig/mul/signs-songs subs (drop other-language dialogue subs); keep all fonts,
  * VERIFY (a/v + the Dubtitles track + duration within tolerance) before touching the original,
  * finalize the muxed mkv (atomic, with a cross-branch fallback), preserving ownership;
    for an mp4 source, remove the OLD ``.mp4`` library link (the seeding download hardlink
    partner is left alone — the orphan-reaper owns it per seed-until-orphan),
  * write the ``.dubtitles.done`` stamp, then remove the sidecar.

DRY-RUN by default (prints the plan); pass --apply to do it. Run as root.
Env: MUX_ROOTS (colon list), KEEP_LANGS, MIN_FREE_GB (skip threshold, default 5),
DUR_TOL (seconds, default 2), MEDIA_UID/GID, DELETE_BROKEN_HARDLINKS (default 0 = off).
Requires mkvtoolnix (mkvmerge) + ffprobe.  Built with help of Claude (Anthropic).
"""
import argparse
import errno
import json
import os
import re
import shutil
import subprocess

ROOTS = os.environ.get("MUX_ROOTS", "/data/Media/Anime Library").split(":")
# Base audio/subtitle languages to KEEP. The title's ORIGINAL language is detected
# per-file (the default audio track's language — Japanese for anime, but whatever it
# actually is for other content) and added to this set. Everything else (fre, spa,
# ger, …) is dropped. Video + the new Dubtitles track + all font attachments always kept.
KEEP_LANGS = set(os.environ.get("KEEP_LANGS", "eng,en,dut,nld,nl,und,").split(","))
HL_ROOTS = os.environ.get("HARDLINK_ROOTS", "").split(":") if os.environ.get("HARDLINK_ROOTS") else ROOTS
# D1: default OFF — never delete a seeding download hardlink; the orphan-reaper owns that
# (seed-until-orphan policy). Muxing only replaces the library's own file.
DELETE_BROKEN = os.environ.get("DELETE_BROKEN_HARDLINKS", "0") == "1"
DUR_TOL = float(os.environ.get("DUR_TOL", "2"))
MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))
MIN_FREE_GB = float(os.environ.get("MIN_FREE_GB", "5"))   # skip a remux if the pool is this low
SIZE_FACTOR = 1.1                                         # temp ~ source size (+headroom)
ASS_SUFFIX = ".eng.dubtitles.ass"
SRT_SUFFIX = ".eng.dubtitles.srt"
STAMP_SUFFIX = ".dubtitles.done"
TRACK_NAME = "Dubtitles"
# subtitle track names that mark a signs/songs track worth keeping regardless of language
SIGNS_RE = re.compile(r"sign|song|karaoke|lyric|caption|title|credit|insert", re.I)


def log(*a): print(*a, flush=True)


def has_room(free_bytes: float, src_size: int) -> bool:
    """True if there's room for a full-size temp plus the MIN_FREE_GB safety margin."""
    return free_bytes >= src_size * SIZE_FACTOR + MIN_FREE_GB * (1 << 30)


def write_stamp(path: str, video: str) -> None:
    """Write the .dubtitles.done idempotency stamp recording the muxed file's size+mtime."""
    st = os.stat(video)
    with open(path, "w") as f:
        json.dump({"size": st.st_size, "mtime": st.st_mtime, "muxed": True}, f)


def read_stamp(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def stamp_valid(stamp: dict | None, video: str) -> bool:
    """True if the stamp matches the current file (size+mtime) — i.e. still muxed, not replaced."""
    if not stamp or not stamp.get("muxed"):
        return False
    try:
        st = os.stat(video)
    except OSError:
        return False
    return stamp.get("size") == st.st_size and abs(stamp.get("mtime", 0) - st.st_mtime) < 1.0


def keep_sub(track: dict, keep_langs: set) -> bool:
    """Keep an mkvmerge subtitle track if its language is wanted, it's multi-language ('mul'),
    or its name reads as signs/songs (so weird JoJo signs tracks survive)."""
    props = track.get("properties", {})
    lang = (props.get("language") or "").lower()
    if lang in keep_langs or lang == "mul":
        return True
    return bool(SIGNS_RE.search(props.get("track_name") or ""))


def identify(path):
    r = subprocess.run(["mkvmerge", "-J", path], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
    return json.loads(r.stdout)


def has_dubtitles_track(info):
    for t in info.get("tracks", []):
        if t.get("type") == "subtitles" and (t.get("properties", {}).get("track_name", "") == TRACK_NAME):
            return True
    return False


def duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def partners(orig):
    """Other paths hardlinked to orig (same inode), searched within HL_ROOTS."""
    st = os.stat(orig)
    if st.st_nlink <= 1:
        return []
    found = []
    for root in HL_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dp, f)
                if p == orig:
                    continue
                try:
                    s2 = os.stat(p)
                except OSError:
                    continue
                if s2.st_ino == st.st_ino and s2.st_dev == st.st_dev and s2.st_size == st.st_size:
                    if os.path.samefile(p, orig):
                        found.append(p)
    return found


def original_langs(info):
    """Original-language audio = the default audio track's language (fallback: first
    audio track). Anime -> jpn, but adapts to whatever the content actually is."""
    auds = [t for t in info.get("tracks", []) if t["type"] == "audio"]
    defs = [t for t in auds if t.get("properties", {}).get("default_track")]
    src = defs or auds[:1]
    return {(t.get("properties", {}).get("language", "") or "").lower() for t in src} - {""}


def build_cmd(info, orig, ass, out):
    """Returns (mkvmerge cmd, [dropped track descriptions]). Keeps eng/dut + the original
    language audio, and eng/orig/mul/signs-songs subs; sets eng audio + Dubtitles default;
    keeps video + all attachments. ``info`` is an ``mkvmerge -J`` dict (passed for testability)."""
    keep = KEEP_LANGS | original_langs(info)
    audio_keep, sub_keep, dropped = [], [], []
    for t in info.get("tracks", []):
        tid = t["id"]; lang = (t.get("properties", {}).get("language", "") or "").lower()
        if t["type"] == "audio":
            (audio_keep if lang in keep else dropped).append(str(tid) if lang in keep else f"audio:{lang or 'und'}")
        elif t["type"] == "subtitles":
            (sub_keep if keep_sub(t, keep) else dropped).append(
                str(tid) if keep_sub(t, keep) else f"sub:{lang or 'und'}")
    cmd = ["mkvmerge", "-o", out]
    if audio_keep: cmd += ["-a", ",".join(audio_keep)]      # else: keep all audio (safety)
    if sub_keep: cmd += ["-s", ",".join(sub_keep)]
    for t in info.get("tracks", []):
        tid = t["id"]; lang = (t.get("properties", {}).get("language", "") or "").lower()
        if t["type"] == "audio" and str(tid) in audio_keep:
            cmd += ["--default-track-flag", f"{tid}:{'yes' if lang in ('eng', 'en') else 'no'}"]
        elif t["type"] == "subtitles" and str(tid) in sub_keep:
            cmd += ["--default-track-flag", f"{tid}:no"]
    cmd += [orig,
            "--track-name", f"0:{TRACK_NAME}", "--language", "0:eng",
            "--default-track-flag", "0:yes", "--sub-charset", "0:UTF-8", ass]
    return cmd, dropped


def verify(orig, out):
    if not (os.path.exists(out) and os.path.getsize(out) > os.path.getsize(orig) * 0.5):
        return "too-small"
    info = identify(out)
    types = {t["type"] for t in info.get("tracks", [])}
    if "video" not in types or "audio" not in types:
        return "missing-av"
    if not has_dubtitles_track(info):
        return "no-dubtitles-track"
    if abs(duration(out) - duration(orig)) > DUR_TOL:
        return "duration-mismatch"
    return "ok"


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
    if stamp_valid(read_stamp(stamp), orig) or has_dubtitles_track(identify(orig)):
        return "already-muxed"                     # stat-only stamp first, ffprobe backstop
    if not has_room(_free_bytes(orig), os.path.getsize(orig)):
        log("  skip (low disk):", os.path.basename(orig))
        return "skip-no-room"
    out = stem + ".muxtmp.mkv"
    final = stem + ".mkv"                           # every episode ends as an mkv
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
        _finalize(out, final)                       # write the muxed mkv
        if os.path.abspath(orig) != os.path.abspath(final) and os.path.exists(orig):
            os.remove(orig)                         # mp4->mkv: drop the OLD library link (partner survives)
        write_stamp(stamp, final)                   # stamp BEFORE removing sidecars (crash-safe skip)
        for suff in (ASS_SUFFIX, SRT_SUFFIX):
            try: os.remove(stem + suff)
            except OSError: pass
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("paths", nargs="*", help="explicit video paths; else walk MUX_ROOTS")
    a = ap.parse_args()
    if a.apply and os.geteuid() != 0:
        log("WARNING: not root — atomic replace may fail (mergerfs perms).")
    vids = list(a.paths)
    if not vids:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                vids += [os.path.join(dp, f) for f in files
                         if f.lower().endswith((".mkv", ".mp4", ".m4v"))]
    counts = {}
    for v in vids:
        res = process(v, a.apply)
        counts[res] = counts.get(res, 0) + 1
        if res not in ("no-sub", "already-muxed"):
            log(f"{res}: {os.path.basename(v)}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
