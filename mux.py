#!/usr/bin/env python3
"""MUX stage — embed the merged dubtitle .ass into the mkv as a default
"Dubtitles" subtitle track, set the English audio + Dubtitles track as the
defaults, and (the whole point of muxing) carry the embedded fonts so signs
render in their correct typeface.

Per video that has a sibling ``<stem>.eng.dubtitles.ass``:
  * SKIP if the mkv already contains a subtitle track titled "Dubtitles"
    (idempotency gate — survives sidecar cleanup, makes re-runs safe),
  * mkvmerge remux (stream copy, no re-encode): add the .ass as track-name
    "Dubtitles" / default; set eng audio default, jpn audio not; clear default
    on the other subtitle tracks,
  * VERIFY the output (all original track types present + the Dubtitles track +
    duration within tolerance) before touching the original,
  * atomically replace the original, preserving ownership,
  * delete the redundant .ass sidecar,
  * HARDLINK CLEANUP: if the original had st_nlink>1, the remux gives the library
    path a fresh inode while the old inode lives on via its other hardlinks
    (e.g. the download). Those are now an orphaned, un-muxed duplicate, so delete
    them (records each to .dubtitles.mux.log). Caveat: if a partner is still being
    seeded in a torrent client, that torrent will go missing.

DRY-RUN by default (prints the plan); pass --apply to do it. Run as root.
Env: MUX_ROOTS (colon list), HARDLINK_ROOTS (colon list of dirs to search for
partner hardlinks, default = same as MUX_ROOTS), DELETE_BROKEN_HARDLINKS (1/0,
default 1), DUR_TOL (seconds, default 2), MEDIA_UID/GID.
Requires mkvtoolnix (mkvmerge) + ffprobe.  Built with help of Claude (Anthropic).
"""
import argparse, json, os, shutil, subprocess, sys
import importlib.util

ROOTS = os.environ.get("MUX_ROOTS", "/data/Media/Anime Library").split(":")
# Base audio/subtitle languages to KEEP. The title's ORIGINAL language is detected
# per-file (the default audio track's language — Japanese for anime, but whatever it
# actually is for other content) and added to this set. Everything else (fre, spa,
# ger, …) is dropped. Video + the new Dubtitles track + all font attachments always kept.
KEEP_LANGS = set(os.environ.get("KEEP_LANGS", "eng,en,dut,nld,nl,und,").split(","))
HL_ROOTS = os.environ.get("HARDLINK_ROOTS", "").split(":") if os.environ.get("HARDLINK_ROOTS") else ROOTS
DELETE_BROKEN = os.environ.get("DELETE_BROKEN_HARDLINKS", "1") == "1"
DUR_TOL = float(os.environ.get("DUR_TOL", "2"))
MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))
ASS_SUFFIX = ".eng.dubtitles.ass"
TRACK_NAME = "Dubtitles"


def log(*a): print(*a, flush=True)


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


def build_cmd(orig, ass, out):
    """Returns (mkvmerge cmd, [dropped track descriptions]). Keeps eng/dut + the
    original language audio/subs; sets eng audio + Dubtitles default; keeps video + all attachments."""
    info = identify(orig)
    keep = KEEP_LANGS | original_langs(info)
    audio_keep, sub_keep, dropped = [], [], []
    for t in info.get("tracks", []):
        tid = t["id"]; lang = (t.get("properties", {}).get("language", "") or "").lower()
        if t["type"] == "audio":
            (audio_keep if lang in keep else dropped).append(str(tid) if lang in keep else f"audio:{lang or 'und'}")
        elif t["type"] == "subtitles":
            (sub_keep if lang in keep else dropped).append(str(tid) if lang in keep else f"sub:{lang or 'und'}")
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


def process(orig, apply):
    stem = os.path.splitext(orig)[0]
    ass = stem + ASS_SUFFIX
    if not os.path.exists(ass):
        return "no-ass"
    if has_dubtitles_track(identify(orig)):
        return "already-muxed"
    plist = partners(orig) if DELETE_BROKEN else []
    out = stem + ".muxtmp.mkv"
    cmd, dropped = build_cmd(orig, ass, out)
    if not apply:
        log(f"  PLAN mux {os.path.basename(orig)}  drop-tracks={dropped}  "
            f"hardlink-partners-to-delete={len(plist)}")
        for p in plist:
            log("        would delete:", p)
        return "plan"
    try:
        st = os.stat(orig)
        subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800, check=False)
        res = verify(orig, out)
        if res != "ok":
            if os.path.exists(out):
                os.remove(out)
            return "verify-" + res
        os.chown(out, st.st_uid if st.st_uid else MEDIA_UID, st.st_gid if st.st_gid else MEDIA_GID)
        os.replace(out, orig)                      # library path -> new inode
        deleted = []
        for p in plist:                            # old inode's other links = orphan duplicate
            try:
                os.remove(p); deleted.append(p)
            except OSError as e:
                log("  partner del fail:", p, e)
        try:
            os.remove(ass)
        except OSError:
            pass
        with open(stem + ".dubtitles.mux.log", "w") as f:
            f.write("muxed Dubtitles track; eng audio + Dubtitles set default\n")
            f.write("dropped non-keep-language tracks: " + ", ".join(dropped) + "\n")
            for p in deleted:
                f.write("deleted broken hardlink: " + p + "\n")
        log(f"  muxed; dropped {len(dropped)} foreign track(s); deleted {len(deleted)} orphaned hardlink(s)")
        return "muxed"
    except Exception as e:
        if os.path.exists(out):
            os.remove(out)
        log("  mux error:", e)
        return "error"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply and os.geteuid() != 0:
        log("WARNING: not root — atomic replace / partner deletion may fail (mergerfs perms).")
    counts = {}
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".mkv",)):
                    res = process(os.path.join(dp, f), a.apply)
                    counts[res] = counts.get(res, 0) + 1
                    if res not in ("no-ass", "already-muxed"):
                        log(f"{res}: {f}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
