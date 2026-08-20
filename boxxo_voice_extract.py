#!/usr/bin/env python3
"""Extract Garret Storms's lines as Boxxo from the show's native Crunchyroll SDH
subtitle track — sourcing material for a Boxxo (the homelab AI persona) voice clone
and personality-reference corpus. Not part of the dubtitle generation pipeline; a
one-off tool that happens to reuse its ffprobe/ffmpeg/pysubs2 plumbing (common.py).

Why the SDH track, not our own generated dubtitle: every CR.WEB-DL release ships an
official Crunchyroll SDH closed-caption track (title containing "SDH") that speaker-tags
each line, e.g. ``[BOXXO]\\NHello there.`` or ``[PROTAGONIST] I had no idea...``. That
tagging is Crunchyroll's own, not something this pipeline generates — no diarization
needed, just read the bracketed name off each line.

Two speakers matter here (see TARGET_SPEAKERS): ``BOXXO`` is his handful of actual
spoken catchphrases; ``PROTAGONIST`` is his inner monologue (he's narrated under his
pre-reincarnation identity, since a vending machine can't literally speak sentences).

Voice actor changed hands mid-run: Storms voiced S1 and S3 in full, but S2 was split —
Austin Tindle did S2E1-7, then Storms returned starting S2E8 (the pre-season cast
announcement said Tindle for all of S2 and was simply wrong about that; Tindle's own
post after the fact confirms the actual E8 handback). STORMS_MIN_EPISODE encodes the
valid window; episodes outside it are skipped entirely, including at the file-walk
level, so Tindle's S2E1-7 never enters the corpus.

Usage:
  python3 boxxo_voice_extract.py "/media/.../Reborn as a Vending Machine... {tvdb-423121}" /out
  python3 boxxo_voice_extract.py <show_root> <out_dir> --cut-audio   # also cut per-line .wav clips

Output: <out_dir>/manifest.jsonl, one JSON object per extracted line (speaker, text,
show/season/episode, start/end seconds, audio_safe). With --cut-audio, audio_safe lines
also get a .wav cut to <out_dir>/clips/<catchphrase|monologue>/.

Runs inside the fasc/dubtitle-builder image (has ffmpeg/ffprobe/pysubs2 already):
  docker run --rm --entrypoint python3 \\
    -v "<show_root>":/in:ro -v <out_dir>:/out \\
    -v $(pwd)/boxxo_voice_extract.py:/app/boxxo_voice_extract.py \\
    -v $(pwd)/common.py:/app/common.py \\
    fasc/dubtitle-builder:latest /app/boxxo_voice_extract.py /in /out [--cut-audio]

Built with help of Claude (Anthropic).
"""
import argparse
import json
import os
import re
import subprocess
import tempfile

import pysubs2

import common

# BOXXO = his spoken catchphrases (small closed set). PROTAGONIST = his inner monologue,
# narrated under his human identity. Folder names for --cut-audio clip output.
CATEGORY = {"BOXXO": "catchphrase", "PROTAGONIST": "monologue"}
TARGET_SPEAKERS = set(CATEGORY)

# Matches an SDH speaker tag at the start of a line, tolerant of a missing opening
# bracket (seen in the wild, e.g. "PROTAGONIST] I just thought..." — a CR captioning
# typo, not a rendering artifact) by anchoring on the closing bracket instead of
# requiring a balanced pair. Requires an ALL-CAPS name so sound-effect cues like
# "[gasps]"/"[screams]" (lowercase) never match.
SPEAKER_RE = re.compile(r"^\[?([A-Z][A-Z0-9 '.\-]*)\]\s*(.*)$")

# "S01E05"-style season/episode from a filename (this library's Sonarr-style naming).
SE_RE = re.compile(r"S(\d{2})E(\d{2})", re.I)

# See module docstring: the pre-season cast announcement (Tindle for all of S2) did not
# match what aired. Add a season here only once its Storms/Tindle split (if any) is
# confirmed — an unlisted season is excluded, not assumed valid.
STORMS_MIN_EPISODE = {1: 1, 2: 8, 3: 1}


def parse_season_episode(filename: str) -> tuple[int, int] | None:
    m = SE_RE.search(filename)
    return (int(m.group(1)), int(m.group(2))) if m else None


def is_storms_episode(season: int, episode: int) -> bool:
    floor = STORMS_MIN_EPISODE.get(season)
    return floor is not None and episode >= floor


def parse_event_lines(plaintext: str) -> list[dict]:
    """One event's rendered text, split into per-line ``{dash, speaker, text}``.

    ``dash`` marks a line that opens with "-" — SDH's convention for two speakers
    sharing one two-line card (only the SECOND speaker's line carries a tag; the first
    is a continuation of dialogue whose tag was on a *previous* card, so ``speaker`` is
    often ``None`` for it — that's expected, not a parse failure). A card with no dash
    lines is single-speaker: the tag (usually on line 1) covers the whole event."""
    parsed = []
    for ln in plaintext.split("\n"):
        dash = ln.startswith("-")
        body = ln[1:].lstrip() if dash else ln
        m = SPEAKER_RE.match(body)
        if m:
            parsed.append({"dash": dash, "speaker": m.group(1).strip(), "text": m.group(2).strip()})
        else:
            parsed.append({"dash": dash, "speaker": None, "text": body.strip()})
    return parsed


def extract_speaker_segments(plaintext: str, start: float, end: float) -> list[dict]:
    """One SDH event -> zero or more ``{speaker, text, start, end, audio_safe}`` for our
    two target speakers only (everyone else's lines are dropped here).

    ``audio_safe`` is False for a shared (dashed) card: both speakers' lines sit inside
    the SAME start/end timespan with no sub-level boundary between them, so a clip cut
    to that range would contain the other speaker's voice too. Text is still kept and
    correctly attributed (it's not ambiguous, only the audio split is) — useful for the
    personality corpus even where it's unsafe for the voice clone."""
    lines = parse_event_lines(plaintext)
    if not any(ln["dash"] for ln in lines):
        speaker = next((ln["speaker"] for ln in lines if ln["speaker"]), None)
        if speaker not in TARGET_SPEAKERS:
            return []
        text = " ".join(ln["text"] for ln in lines if ln["text"]).strip()
        return [{"speaker": speaker, "text": text, "start": start, "end": end, "audio_safe": True}] if text else []
    return [{"speaker": ln["speaker"], "text": ln["text"], "start": start, "end": end, "audio_safe": False}
            for ln in lines if ln["dash"] and ln["speaker"] in TARGET_SPEAKERS and ln["text"]]


def sdh_track_index(video: str) -> int | None:
    """The episode's official Crunchyroll SDH stream index, or None if this release
    doesn't ship one (older/non-CR rips) — those episodes are skipped, not guessed at."""
    for idx, title in common.eng_sub_tracks(video, {"eng", "en"}):
        if "sdh" in (title or "").lower():
            return idx
    return None


def eng_audio_index(video: str) -> int | None:
    """Self-contained copy of generate.py's eng_audio_index — not imported from there,
    since generate.py pulls in faster_whisper (GPU deps) at module scope and this tool
    has no reason to carry that weight just to reuse an 8-line ffprobe call."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index:stream_tags=language", "-of", "json", video],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        common.log("  ffprobe audio failed:", video, e)
        return None
    eng = [s for s in streams if ((s.get("tags") or {}).get("language", "").lower() in ("eng", "en"))]
    return eng[0]["index"] if eng else (streams[0]["index"] if streams else None)


def cut_clip(video: str, audio_idx: int, start: float, end: float, out_wav: str, sample_rate: int) -> bool:
    """Cut one line's audio to a mono PCM wav. ``-ss`` before ``-i`` (fast seek) is
    plenty accurate here — the caller's pad already covers ordinary SDH timing slop."""
    start = max(0.0, start)
    dur = max(0.05, end - start)
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", video,
           "-map", f"0:{audio_idx}", "-t", f"{dur:.3f}",
           "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", out_wav]
    subprocess.run(cmd, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    return os.path.exists(out_wav) and os.path.getsize(out_wav) > 1000


def process_episode(video: str, season: int, episode: int, sdh_idx: int, audio_idx: int | None,
                     cut_audio: bool, out_dir: str, pad: float, sample_rate: int,
                     show: str, slug: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as td:
        ass_path = os.path.join(td, "sdh.ass")
        if not common.extract_sub(video, sdh_idx, ass_path):
            common.log("  SDH extract failed:", os.path.basename(video))
            return []
        try:
            events = pysubs2.load(ass_path).events
        except Exception as e:
            common.log("  SDH parse failed:", os.path.basename(video), e)
            return []

    segments = []
    for ev in events:
        if ev.is_comment:
            continue
        txt = ev.plaintext.strip()
        if not txt:
            continue
        segments += extract_speaker_segments(txt, ev.start / 1000.0, ev.end / 1000.0)

    for seg in segments:
        seg.update(show=show, season=season, episode=episode, source=os.path.basename(video))
        if cut_audio and seg["audio_safe"] and audio_idx is not None:
            clip_dir = os.path.join(out_dir, "clips", CATEGORY[seg["speaker"]])
            os.makedirs(clip_dir, exist_ok=True)
            clip_path = os.path.join(clip_dir, f"{slug}_S{season:02d}E{episode:02d}_{int(seg['start'] * 1000)}.wav")
            if cut_clip(video, audio_idx, seg["start"] - pad, seg["end"] + pad, clip_path, sample_rate):
                seg["clip"] = clip_path
    return segments


def main(args) -> None:
    os.makedirs(args.out_dir, exist_ok=True)
    show = os.path.basename(os.path.normpath(args.show_root))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", show).strip("-").lower()
    manifest_path = os.path.join(args.out_dir, "manifest.jsonl")

    n_lines = n_clips = n_episodes = 0
    with open(manifest_path, "w") as mf:
        for root, dirs, files in os.walk(args.show_root):
            dirs[:] = [d for d in dirs if d.lower() not in common.EXTRA_DIRS]
            for fn in sorted(files):
                if not fn.lower().endswith(common.VIDEO_EXTS):
                    continue
                se = parse_season_episode(fn)
                if not se or not is_storms_episode(*se):
                    continue                        # not S1/S2E8+/S3, or unrecognized name
                season, episode = se
                video = os.path.join(root, fn)

                sdh_idx = sdh_track_index(video)
                if sdh_idx is None:
                    common.log(f"  no SDH track: {fn}")
                    continue
                audio_idx = eng_audio_index(video) if args.cut_audio else None
                if args.cut_audio and audio_idx is None:
                    common.log(f"  no English audio, text-only for: {fn}")

                segs = process_episode(video, season, episode, sdh_idx, audio_idx, args.cut_audio,
                                        args.out_dir, args.pad, args.sample_rate, show, slug)
                for seg in segs:
                    mf.write(json.dumps(seg) + "\n")
                    n_lines += 1
                    n_clips += 1 if seg.get("clip") else 0
                n_episodes += 1
                common.log(f"  {fn}: {len(segs)} lines")

    mode = f", {n_clips} audio clips cut" if args.cut_audio else " (text-only — pass --cut-audio for clips)"
    common.log(f"done: {n_episodes} episodes, {n_lines} lines -> {manifest_path}{mode}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("show_root", help="Path to the show's library folder (contains Season NN subfolders)")
    ap.add_argument("out_dir", help="Output directory for manifest.jsonl and (with --cut-audio) clips/")
    ap.add_argument("--cut-audio", action="store_true", help="Also cut per-line .wav clips for audio_safe lines")
    ap.add_argument("--sample-rate", type=int, default=24000, help="Clip sample rate (default 24000, XTTS-friendly)")
    ap.add_argument("--pad", type=float, default=0.15, help="Seconds padded before/after each cut clip (default 0.15)")
    main(ap.parse_args())
