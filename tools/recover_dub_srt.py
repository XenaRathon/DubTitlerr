#!/usr/bin/env python3
"""Rebuild ``<stem>.eng.dubtitles.srt`` from the episode's ALREADY-MUXED Dubtitles track.

Companion to recreate_srt.py, for the harder half of a PIPELINE_VERSION regeneration.
recreate_srt.py rebuilds the sidecar from ``<stem>.dubtitles.conf.json``; this one is for
the episodes whose conf.json is long gone, where the only surviving copy of the dub
dialogue is the muxed track itself.

Our muxed track holds two kinds of event: the dialogue, all carrying the "Dubtitles"
style, and the signs/songs lifted from the release. The dialogue is finished work —
transcribed, glossary-corrected and LLM-repaired. The signs are precisely what a rebuild
replaces. So lifting out the Dubtitles-styled events alone reconstructs the sidecar
exactly, and a full-library rebuild costs hours of remuxing instead of days of Whisper
on a 6 GB 1060.

This is the one place the pipeline deliberately reads its own output. It is not the
context leak that common.eng_sub_streams() exists to prevent: nothing here is treated as
a fansub reference, the lines go straight back out as dialogue, and repair.py skips an
episode with no conf.json, so already-repaired text is never re-repaired.

Usage:  python3 tools/recover_dub_srt.py [--apply] <video.mkv> [...]
Without --apply it only reports what it would recover.  Built with help of Claude.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pysubs2  # noqa: E402

from common import TRACK_NAME, extract_sub, log, stream_title, ts_srt  # noqa: E402
from common import subprocess as _sp  # noqa: E402


def dub_events(ass_path, srt_origin=False):
    """The dialogue events from a muxed Dubtitles track, in order.

    From an .ass track, only the "Dubtitles"-styled events: the sign/song events beside
    them are last version's output, re-derived from the release during the rebuild.

    ``srt_origin`` is for the tracks that were muxed straight from the .srt, because the
    release shipped no embedded signs for the merge to find (mux embeds the srt when
    dub_signs_merge returns "no-signs"). pysubs2 gives every event of an SRT the style
    "Default", so the style filter discarded those episodes wholesale. Such a track holds
    nothing but our dialogue -- there are no signs in it to confuse with it -- so every
    event counts."""
    try:
        subs = pysubs2.load(ass_path)
    except Exception as e:
        log("  load fail", ass_path, e)
        return []
    out = []
    for ev in subs.events:
        if ev.is_comment:
            continue
        if not srt_origin and ev.style != TRACK_NAME:
            continue
        if not ev.plaintext.strip():
            continue
        out.append(ev)
    return out


def write_srt(events, out_path):
    """Write the recovered dialogue as an SRT. Returns the number of lines written.

    Refuses an empty sidecar: merge_pass discovers work BY the sidecar's existence, so a
    zero-line .srt would assemble an empty .ass and mux a dubtitle track with no dialogue
    in it — quietly destroying the episode's dubtitles instead of rebuilding them."""
    if not events:
        raise ValueError(f"refusing to write an empty dubtitle sidecar: {out_path}")
    with open(out_path, "w", encoding="utf-8") as f:
        for i, ev in enumerate(events, 1):
            f.write(f"{i}\n{ts_srt(ev.start / 1000.0)} --> {ts_srt(ev.end / 1000.0)}\n"
                    f"{ev.plaintext.strip()}\n\n")
    return len(events)


def our_track_index(video):
    """``(index, codec_name)`` of our own muxed Dubtitles track, or ``(None, None)``.
    Deliberately the inverse of common.eng_sub_streams()'s exclusion — here it is the
    track we WANT. The codec comes back too because an extracted SRT and a style-less ASS
    are indistinguishable once pysubs2 has parsed them (see dub_events)."""
    import json
    try:
        r = _sp.run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                     "stream=index,codec_name:stream_tags=language,title", "-of", "json",
                     video], capture_output=True, text=True, stdin=_sp.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e)
        return (None, None)
    for st in streams:
        if stream_title(st).strip() == TRACK_NAME:
            return (st["index"], st.get("codec_name"))
    return (None, None)


def recover(source, out_path):
    """``source`` is either a video (the track is extracted) or an .ass/.srt already on
    disk. Returns a short status string."""
    if os.path.exists(out_path):
        return "exists"                     # fresher work already there — never clobber it
    if source.lower().endswith((".ass", ".ssa", ".srt")):
        evs = dub_events(source, srt_origin=source.lower().endswith(".srt"))
    else:
        idx, codec = our_track_index(source)
        if idx is None:
            return "no-dubtitles-track"
        srt_origin = codec in ("subrip", "srt", "text")
        with tempfile.TemporaryDirectory() as td:
            ex = os.path.join(td, "d.srt" if srt_origin else "d.ass")
            if not extract_sub(source, idx, ex):
                return "extract-failed"
            evs = dub_events(ex, srt_origin=srt_origin)
    if not evs:
        return "no-dialogue"
    write_srt(evs, out_path)
    return "recovered"


def main():
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv[1:]
    counts = {}
    for video in args:
        stem = os.path.splitext(video)[0]
        out = stem + ".eng.dubtitles.srt"
        if not apply:
            res = "exists" if os.path.exists(out) else ("would-recover"
                  if our_track_index(video)[0] is not None else "no-dubtitles-track")
        else:
            res = recover(video, out)
        counts[res] = counts.get(res, 0) + 1
        log(f"{res}: {os.path.basename(video)}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
