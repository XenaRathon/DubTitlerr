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
          (including a song's Kanji/Japanese/English siblings under an
          "Opening-"/"ED<N>-" style prefix, whatever language each one is in)
  DROP  : dialogue styles (main/flashback/thought/secondary/monologue/narration),
          player-support "warning" notices, and — inside a detected song span only
          — the whisper-transcribed dub cards, in favour of the fansub's own
          lyrics/translation kept above (see _song_spans; a dub re-sung in English
          would previously have replaced them, but nothing does on a Japanese OP)

For every ``…eng.dubtitles.srt`` it:
  1. finds the matching video,
  2. extracts each English ASS subtitle stream, keeps only sign/song/credit events,
  3. appends the dub dialogue under a clean bottom "Dubtitles" style,
  4. writes ``…eng.dubtitles.ass`` and removes the redundant ``.srt``.

Idempotent. Env: MERGE_ROOTS (colon list), DUB_SUFFIX, MEDIA_UID/GID, SUB_LANGS
(comma list of accepted subtitle languages, default eng,und).
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""

import os
import re
import sys
import tempfile

import pysubs2

from common import MEDIA_GID, MEDIA_UID, find_video, log, out_for, signs_sub_streams
from common import extract_sub as extract

ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
SUFFIX = os.environ.get("DUB_SUFFIX", ".eng.dubtitles.srt")
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))

KARAOKE = re.compile(r"\\[kK][fo]?\d")
HAS_DRAWING = re.compile(r"\\p\d|\\clip|\\iclip")
ANIMATED = re.compile(r"\\t\(|\\fade?\(|\\move\(")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
# KEEP the Japanese romaji karaoke (top) + signs/credits + the fansub's own English song
# TRANSLATION. Reversed 2026-09-02 (.procoder/todo/20260830-drop-transcribed-song-lyrics-
# restore-fansub-translation.md): the translation used to be dropped on the assumption that
# whisper's transcribed English-dub lyrics would replace it, which only holds if the dub
# re-sings the song in English. Measured on SAO S01E02 (opening sung in Japanese): whisper
# mangles the Japanese into pseudo-romaji and then invents English outright (avg_logprob
# -1.7 to -4.1 against -0.3/-0.7 for ordinary dialogue) -- nothing replaces the translation
# that was thrown away, and hallucination lands in its place. See _song_spans() below,
# which now drops those whisper cards from the dub track instead.
KEEP_STYLE = re.compile(r"karaoke|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)
# A song's per-language sibling styles don't all carry a common keyword -- SAO's own wiki
# names them "Opening-Romaji-L1", "Opening-Kanji-L1", "ED1-Romaji", "ED1-Japanese",
# "ED1-English": the Romaji one matches KEEP_STYLE's "romaji" already, but Kanji/Japanese/
# English siblings match nothing there and fell through to "assume dialogue, drop" -- half
# of each song's on-screen text was silently missing. The "Opening-"/"ED<N>-" prefix
# convention covers the whole family regardless of which language suffix a given release
# uses, without needing to enumerate every language name.
SONG_FAMILY_STYLE = re.compile(r"^(?:opening|ending)[\s_-]|^(?:op|ed)\d+[\s_-]", re.I)
# STRONG_DROP_STYLE: an unambiguous role, independent of the release's own style-naming
# quirks -- a "Warning" style is a player-support notice, never actual signs content, and
# wins even over a keep-signal tag.
STRONG_DROP_STYLE = re.compile(r"warning", re.I)
# WEAK_DROP_STYLE: a GUESS that a style name means plain dialogue. Real releases reuse
# "Default" for both a dialogue track AND a signs/songs track depending on the group's
# own convention (MARRIAGETOXIN S01E01: the signs/songs track's own style is "Default"),
# so this guess must yield to an unambiguous tag signal (\pos/\move/\k/\p) rather than
# overriding it -- see keep_event().
WEAK_DROP_STYLE = re.compile(r"main|dialog|default|flashback|thought|secondary|monolog|narrat|italics|^alt", re.I)


def keep_event(ev):
    """True if this is a sign / song-romaji / caption / credit (not dialogue, and not the
    fansub English song translation — that's replaced by the transcribed Dubtitles)."""
    if ev.is_comment:
        return False
    if not ev.plaintext.strip():
        return False
    style = ev.style or ""
    if STRONG_DROP_STYLE.search(style):
        return False
    if SONG_FAMILY_STYLE.search(style):  # Opening-/ED<N>- sibling, any language -> keep
        return True
    t = ev.text
    tagged = bool(KARAOKE.search(t) or HAS_DRAWING.search(t) or POSITIONED.search(t) or ANIMATED.search(t))
    if WEAK_DROP_STYLE.search(style) and not tagged:  # a style-name GUESS, only when nothing else says otherwise
        return False
    if KARAOKE.search(t):  # Japanese romaji karaoke (top) -> keep
        return True
    if HAS_DRAWING.search(t):  # vector-drawn sign (\p/\clip/\iclip) -> keep
        return True
    if POSITIONED.search(t) or ANIMATED.search(t):  # positioned/animated sign -> keep
        return True  # (ANIMATED's \move overlaps POSITIONED; merged into one check)
    if KEEP_STYLE.search(style):
        return True
    return False  # unknown plain event, no tag, no keep-style -> assume dialogue, Whisper has it


# Song events inside one OP/ED are timed syllable-by-syllable (SAO E02: 2,142 separate
# events for one opening) but still fall inside the one span that matters. Adjacent events
# this close together merge into the same span; the OP and ED themselves are minutes apart
# and stay separate spans, so ordinary dialogue between them is untouched.
SONG_SPAN_MERGE_GAP_MS = 2000


def _song_spans(kept_events):
    """Merged (start, end) ms intervals covered by song-family-styled kept events -- the
    OP/ED's own timespan(s), independent of how many per-syllable events make one up.

    Empty on a track whose signs stream carries no song-family styles, which is what makes
    the drop below a no-op there without a separate guard.

    MEASURED 2026-09-02, correcting this docstring's original claim that One Pace had "no
    chapters, no OP/ED at all": most One Pace seasons do produce no spans, but S17 and S27
    do. S27's signs track yields three spans covering 18.6-145.2s and drops 25-26 dub cards
    per episode; S17 yields two spans and drops 2-4. The dropped cards were inspected and
    are whisper's song output -- raw Japanese lyrics, bilingual mush ("So決めたこと悔いはない
    Oh I know what I'm supposed to do"), and invented English ("Let's start with the new
    world") -- so the drop is doing its job there. But "no-op on One Pace" was never true,
    and the library's largest show was carrying this behaviour unmeasured."""
    spans = sorted((ev.start, ev.end) for ev in kept_events if SONG_FAMILY_STYLE.search(ev.style or ""))
    merged: list = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + SONG_SPAN_MERGE_GAP_MS:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _overlaps_any(start, end, spans):
    return any(start < s_end and end > s_start for s_start, s_end in spans)


def build(video, dub_srt, out_ass):
    base = None  # the merged ScriptInfo/styles canvas
    kept = []  # (event, source_style_name)
    seen = set()
    base_ws = None  # D3: base track's WrapStyle, for cross-track comparison
    resolutions = []  # D5: (PlayResX, PlayResY) per source track, for mismatch warning
    for _n, idx in enumerate(signs_sub_streams(video, SUB_LANGS)):
        with tempfile.TemporaryDirectory() as td:
            ex = os.path.join(td, "s.ass")
            if not extract(video, idx, ex):
                continue
            try:
                subs = pysubs2.load(ex)
            except Exception as e:
                log("  load fail", idx, e)
                continue
        src_events = list(subs.events)  # snapshot BEFORE any clearing (base may alias subs)
        resolutions.append((subs.info.get("PlayResX"), subs.info.get("PlayResY")))  # D5
        if base is None:
            base = subs
            base.events = []
            base.info["ScaledBorderAndShadow"] = "yes"  # D4: consistent cross-player rendering
            base_ws = base.info.get("WrapStyle")  # D3
        else:
            track_ws = subs.info.get("WrapStyle")  # D3
            if track_ws != base_ws:
                log(f"WrapStyle differs: base={base_ws} track={track_ws} — using base")
            for sname, sty in subs.styles.items():  # carry styles from later tracks
                if sname in base.styles:
                    existing = base.styles[sname]  # D1: flag conflicting redefinitions
                    if existing.fontname != sty.fontname or existing.fontsize != sty.fontsize:
                        log(f"  style conflict: '{sname}' — font/size differ, using first definition")
                else:
                    base.styles[sname] = sty
        for ev in src_events:
            if not keep_event(ev):
                continue
            # Dedup on the FULL override text and the layer, not the plaintext: a
            # typeset sign is often several stacked events sharing \pos, style, timing
            # and plaintext, differing only in tags (a black backing copy supplying the
            # stroke, plus the visible copy that \t()s its fill to white). Keying on
            # plaintext collapsed those to the first — the black one — so credits and
            # captions rendered solid black. Byte-identical events (the same sign
            # carried by both the full track and the signs/songs track) still collapse.
            key = (int(ev.start), int(ev.end), ev.style, ev.layer, ev.text)
            if key in seen:
                continue
            seen.add(key)
            base.events.append(ev)
            kept.append(ev)
    if base is None:
        return "no-signs", 0, 0
    if len(set(resolutions)) > 1:  # D5: warn only — no coordinate transform (deferred to V3)
        log("WARNING: resolution mismatch between subtitle tracks — signs may be mispositioned")
    # bottom dub dialogue style
    play_y = 0
    try:
        play_y = int(base.info.get("PlayResY") or 0)
    except Exception:
        pass
    play_y = play_y or 720
    fs = max(32, round(play_y / 17))
    st = pysubs2.SSAStyle()
    st.fontname = "Arial"
    st.fontsize = fs
    st.bold = True
    st.primarycolor = pysubs2.Color(255, 255, 255)
    st.outlinecolor = pysubs2.Color(0, 0, 0)
    st.outline = max(1.5, fs / 22)
    st.shadow = 1.0
    st.alignment = pysubs2.Alignment.BOTTOM_CENTER
    st.marginv = max(10, round(play_y / 22))
    base.styles["Dubtitles"] = st
    dub = pysubs2.load(dub_srt)
    song_spans = _song_spans(kept)
    added = dropped_song = 0
    for ev in dub:
        if ev.is_comment:
            continue
        # debt: a card of real spoken dialogue over an opening/ending is dropped along with
        # the lyrics, since the whole song span is cut regardless of what's actually sung
        # under it. This HAS now fired on real content -- One Pace S17/S27, measured
        # 2026-09-02 -- correcting the original note here, which claimed SAO S01E02 was the
        # only measured case and that it had silence under the intro. Every dropped card
        # inspected so far is genuine whisper song output, but two were ambiguous ("If
        # you're in it, I'll protect you from the moment", S17E03 63.5s; "I'll see you /
        # next time.", S27E04 112.6s) and nothing distinguishes them from dialogue except
        # reading them. Revisit by gating on avg_logprob, which already separates sung
        # hallucination (-1.7 to -4.1) from ordinary dialogue (-0.3/-0.7), instead of
        # cutting a blanket span.
        if _overlaps_any(ev.start, ev.end, song_spans):
            dropped_song += 1
            continue
        ev.style = "Dubtitles"
        base.events.append(ev)
        added += 1
    if dropped_song:
        log(f"  song-span dropped {dropped_song} whisper dub card(s) (fansub translation kept instead)")
    # Dubtitles dialogue on the floor (layer 0); every sign/song event bumped one
    # layer up so it renders on top. Shift (not zero) keeps the relative z-order
    # among multi-layer sign compositions.
    for ev in base.events:
        if ev.style == "Dubtitles":
            ev.layer = 0
        else:
            ev.layer = ev.layer + 1
    base.sort()
    base.save(out_ass)
    ok = os.path.exists(out_ass) and os.path.getsize(out_ass) > 0
    return ("ok" if ok else "save-fail"), len(kept), added


def process_one(srt):
    stem = srt[: -len(SUFFIX)]
    out_ass = out_for(stem + ".eng.dubtitles.ass")
    video = find_video(stem)
    if not video:
        return "no-video"
    try:
        res, signs, dub = build(video, srt, out_ass)
    except Exception as e:
        log("build error:", srt, e)
        return "build-error"
    if res != "ok" or dub == 0:
        return res if res != "ok" else "empty"
    try:
        os.chown(out_ass, MEDIA_UID, MEDIA_GID)
    except OSError as e:
        log(f"chown failed for {out_ass}: {e}")
    try:
        os.remove(srt)
    except OSError:
        pass
    log(f"  signs/songs/credits kept={signs}  dub lines={dub}")
    return "merged"


def main():
    args = sys.argv[1:]
    srts = list(args) if args else []  # explicit .srt paths, else walk roots
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
