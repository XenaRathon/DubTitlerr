#!/usr/bin/env python3
"""ASSEMBLE stage of the gold dubtitle builder.

Take the Whisper dub-dialogue sidecar (``<stem>.eng.dubtitles.srt``, produced by
generate.py) and merge it with the **signs, songs and credits** from the video's
own embedded English subtitle tracks into ONE ``.ass`` — so a single subtitle
track shows English-dub dialogue at the bottom *and* the positioned signs / song
karaoke / staff credits, all at once.

The classification is per-EVENT (by ASS style + positioning), not per-stream title:
many releases (e.g. One Pace) ship one *full* track mixing dialogue+signs+songs
plus a credits track, with no stream literally titled "Signs and Songs".

  KEEP  : events with \\k (song karaoke) or \\pos/\\move (positioned sign), and
          styles matching sign/song/caption/title/credit/translation/lyric/romaji
  DROP  : dialogue styles (main/flashback/thought/secondary/monologue/narration)
          and player-support "warning" notices — Whisper covers the dialogue

For every ``…eng.dubtitles.srt`` it:
  1. finds the matching video,
  2. extracts each English ASS subtitle stream, keeps only sign/song/credit events,
  3. appends the dub dialogue under a clean bottom "Dubtitles" style,
  4. writes ``…eng.dubtitles.ass`` and removes the redundant ``.srt``.

Idempotent. Env: MERGE_ROOTS (colon list), DUB_SUFFIX, MEDIA_UID/GID, SUB_LANGS
(comma list of accepted subtitle languages, default eng,und).
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""
import json, os, re, subprocess, sys, tempfile
import pysubs2

# OUTPUT_ROOT: write the .ass to this branch path (disk with space) instead of next to the
# mkv; mergerfs unifies branches so it still shows in the pool view. Reads use mergerfs path.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")
def out_for(p):
    if OUTPUT_ROOT and p.startswith(MEDIA_ROOT):
        q = OUTPUT_ROOT + p[len(MEDIA_ROOT):]
        os.makedirs(os.path.dirname(q), exist_ok=True)
        return q
    return p

ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
SUFFIX = os.environ.get("DUB_SUFFIX", ".eng.dubtitles.srt")
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))
MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

KARAOKE = re.compile(r"\\[kK][fo]?\d")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
# KEEP the Japanese romaji karaoke (top) + signs/credits. DROP the fansub English song
# TRANSLATION — it's replaced by whisper's transcribed English-dub lyrics (bottom Dubtitles).
KEEP_STYLE = re.compile(r"karaoke|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)
DROP_STYLE = re.compile(r"main|dialog|default|flashback|thought|secondary|monolog|narrat|warning|italics|translat|^alt", re.I)


def log(*a): print(*a, flush=True)


def find_video(stem):
    for ext in VIDEO_EXTS:
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def eng_sub_streams(video):
    """Indices of ASS/SSA subtitle streams in an accepted language."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index,codec_name:stream_tags=language",
             "-of", "json", video], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e); return []
    out = []
    for st in streams:
        if st.get("codec_name") not in ("ass", "ssa"):
            continue
        lang = ((st.get("tags") or {}).get("language", "") or "").lower()
        if lang in SUB_LANGS:
            out.append(st["index"])
    return out


def keep_event(ev):
    """True if this is a sign / song-romaji / caption / credit (not dialogue, and not the
    fansub English song translation — that's replaced by the transcribed Dubtitles)."""
    if ev.is_comment:
        return False
    if not ev.plaintext.strip():
        return False
    style = ev.style or ""
    if DROP_STYLE.search(style):          # dialogue / warning / song-translation -> drop FIRST
        return False                      # (checked before positioning so Translation drops too)
    t = ev.text
    if KARAOKE.search(t):                  # Japanese romaji karaoke (top) -> keep
        return True
    if POSITIONED.search(t):              # positioned sign -> keep
        return True
    if KEEP_STYLE.search(style):
        return True
    return False  # unknown plain event -> assume dialogue, Whisper has it


def extract(video, idx, out_ass):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}",
                    "-c:s", "copy", out_ass], capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    if not (os.path.exists(out_ass) and os.path.getsize(out_ass) > 0):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}", out_ass],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    return os.path.exists(out_ass) and os.path.getsize(out_ass) > 0


def build(video, dub_srt, out_ass):
    base = None         # the merged ScriptInfo/styles canvas
    kept = []           # (event, source_style_name)
    seen = set()
    for n, idx in enumerate(eng_sub_streams(video)):
        with tempfile.TemporaryDirectory() as td:
            ex = os.path.join(td, "s.ass")
            if not extract(video, idx, ex):
                continue
            try:
                subs = pysubs2.load(ex)
            except Exception as e:
                log("  load fail", idx, e); continue
        src_events = list(subs.events)   # snapshot BEFORE any clearing (base may alias subs)
        if base is None:
            base = subs
            base.events = []
        else:
            for sname, sty in subs.styles.items():   # carry styles from later tracks
                base.styles.setdefault(sname, sty)
        for ev in src_events:
            if not keep_event(ev):
                continue
            key = (int(ev.start), int(ev.end), ev.style, ev.plaintext.strip())
            if key in seen:
                continue
            seen.add(key); base.events.append(ev)
            kept.append(ev)
    if base is None:
        return "no-signs", 0, 0
    # bottom dub dialogue style
    play_y = 0
    try: play_y = int(base.info.get("PlayResY") or 0)
    except Exception: pass
    play_y = play_y or 720
    fs = max(32, round(play_y / 17))
    st = pysubs2.SSAStyle()
    st.fontname = "Arial"; st.fontsize = fs; st.bold = True
    st.primarycolor = pysubs2.Color(255, 255, 255); st.outlinecolor = pysubs2.Color(0, 0, 0)
    st.outline = max(1.5, fs / 22); st.shadow = 1.0
    st.alignment = pysubs2.Alignment.BOTTOM_CENTER; st.marginv = max(10, round(play_y / 22))
    base.styles["Dubtitles"] = st
    dub = pysubs2.load(dub_srt)
    added = 0
    for ev in dub:
        if ev.is_comment:
            continue
        ev.style = "Dubtitles"; base.events.append(ev); added += 1
    base.sort()
    base.save(out_ass)
    ok = os.path.exists(out_ass) and os.path.getsize(out_ass) > 0
    return ("ok" if ok else "save-fail"), len(kept), added


def process_one(srt):
    stem = srt[:-len(SUFFIX)]
    out_ass = out_for(stem + ".eng.dubtitles.ass")
    video = find_video(stem)
    if not video:
        return "no-video"
    try:
        res, signs, dub = build(video, srt, out_ass)
    except Exception as e:
        log("build error:", srt, e); return "build-error"
    if res != "ok" or dub == 0:
        return res if res != "ok" else "empty"
    try: os.chown(out_ass, MEDIA_UID, MEDIA_GID)
    except OSError: pass
    try: os.remove(srt)
    except OSError: pass
    log(f"  signs/songs/credits kept={signs}  dub lines={dub}")
    return "merged"


def main():
    args = sys.argv[1:]
    srts = list(args) if args else []      # explicit .srt paths, else walk roots
    if not srts:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for f in files:
                    if f.endswith(SUFFIX):
                        srts.append(os.path.join(dp, f))
    counts = {}
    for s in sorted(srts):
        res = process_one(s)
        counts[res] = counts.get(res, 0) + 1
        log(f"{res}: {os.path.basename(s)}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
