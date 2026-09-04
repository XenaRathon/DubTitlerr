#!/usr/bin/env python3
"""Export completed-dubtitle subtitles for the "unreviewed, subject to improve" public drop.

export_reviewed.py's manifest gates on decision 11 (every queued line has a human verdict).
Measured 2026-08-31 against the real library: 255 One Pace episodes carry a review queue,
7,222 queued lines have no verdict, and ZERO episodes qualify -- Season 31, the set believed
reviewed, does not either (docs/superpowers/specs/2026-08-31-public-beta-design.md,
Workstream C). Shipping under that gate means shipping nothing.

This tool gates on completion instead: a valid `.dubtitles.done` stamp (common.stamp_valid)
that matches the episode's current video is the same claim mux.py itself relies on to skip
a re-mux -- "this episode's dubtitle track is the one actually in the file". Every episode
that passes is exported with `"status": "unreviewed"` in its manifest entry, and the
repository README says so up front. Decision 11 is untouched; export_reviewed.py's stricter
manifest remains the tool for a future reviewed release.

Per episode: the dialogue-only `.srt` (regenerated from `.dubtitles.conf.json`, since
mux.py deletes the loose srt/ass sidecars on a successful mux) and the merged `.ass`
(extracted from the muxed video's own "Dubtitles"-titled subtitle stream -- the sidecar
mux.py wrote INTO the file, not a copy that can drift from it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reflow
import unresolved
from common import STAMP_SUFFIX, TRACK_NAME, read_stamp, stamp_valid, ts_srt

CONF_SUFFIX = ".dubtitles.conf.json"
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")


def find_video(stem: str) -> str | None:
    for ext in VIDEO_EXTS:
        video = stem + ext
        if os.path.exists(video):
            return video
    return None


def show_for(stem: str) -> str:
    """Derive the display show from the episode's grandparent directory, matching
    export_reviewed.py's own show_for."""
    return os.path.basename(os.path.dirname(os.path.dirname(stem)))


def completed_episodes(show: str, media_root: str) -> list:
    """Every stem in `show` whose muxed video currently matches a valid `.dubtitles.done`
    stamp. ONE `os.walk` of media_root -- review_server measures this walk at 297s for 989
    episodes over a network mount, so a second pass would double a five-minute operation to
    produce nothing new (same reasoning as export_reviewed.py's own single-walk test)."""
    stems = []
    for root, _dirs, files in os.walk(media_root):
        for filename in files:
            if not filename.endswith(STAMP_SUFFIX):
                continue
            stem = os.path.join(root, filename[: -len(STAMP_SUFFIX)])
            if show_for(stem) != show:
                continue
            video = find_video(stem)
            if video is None:
                continue
            if not stamp_valid(read_stamp(stem + STAMP_SUFFIX), video):
                continue
            stems.append(stem)
    stems.sort()
    return stems


def dialogue_srt(stem: str) -> str | None:
    """The dialogue-only SRT rebuilt from `.dubtitles.conf.json`. None (never raises) when
    the file is missing or unparseable -- this runs inside a loop over hundreds of real
    episodes and one bad conf.json must not abort the batch."""
    try:
        with open(stem + CONF_SUFFIX, encoding="utf-8") as f:
            cards = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        blocks = [
            f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{reflow.wrap_balance(c['text'])}\n"
            for i, c in enumerate(cards, 1)
        ]
    except (KeyError, TypeError):
        return None
    return "\n".join(blocks)


def probe_duration_seconds(video: str, run=subprocess.run) -> float | None:
    try:
        result = run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        value = float(json.loads(result.stdout)["format"]["duration"])
        return value if value > 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def dubtitles_stream_index(video: str, run=subprocess.run) -> int | None:
    """The stream index of the muxed video's own TRACK_NAME-titled subtitle stream, or
    None when it isn't there (the episode's video predates a successful mux)."""
    try:
        result = run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index:stream_tags=title",
                "-select_streams",
                "s",
                "-of",
                "json",
                video,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        streams = json.loads(result.stdout).get("streams", [])
        for s in streams:
            if (s.get("tags") or {}).get("title") == TRACK_NAME:
                return s.get("index")
        return None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def extract_ass(video: str, stream_index: int, out_path: str, run=subprocess.run) -> bool:
    """Thin, fully mockable wrapper around the ffmpeg extraction call. Never raises."""
    try:
        result = run(
            ["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:{stream_index}", out_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# A TRAILING run of bracket blocks, optionally welded to a release group (`]-Trix`). Only
# the tail: a bracket mid-title is the show's own punctuation, not somebody's rip metadata.
RELEASE_TAG_TAIL = re.compile(r"(?:\s*\[[^\]]*\])+(?:-[^\s\[\]]+)?\s*$")


# Bare, unbracketed tags -- this library holds both shapes. Deliberately a CLOSED
# vocabulary of things no episode title ends with (resolutions, codecs, sources, channel
# counts, bit depths) rather than a general "looks technical" rule: `Opus`, `Proper` and
# `Multi` are release tags AND ordinary English, so they are omitted here and caught by
# RELEASE_TAG_TAIL when they appear bracketed, which is how this library writes them.
RELEASE_TOKEN = (
    r"(?:\d{3,4}p|x26[45]|h\.?26[45]|hevc|av1|\d+ch|\d+bit|web-?dl|webrip|bluray|bdrip"
    r"|hdtv|dvdrip|remux|aac(?:\d(?:\.\d)?)?|flac|dts(?:-hd)?|truehd|repack|hdr\d*)"
)
BARE_TAG_TAIL = re.compile(rf"(?:[\s._-]+{RELEASE_TOKEN})+\s*$", re.IGNORECASE)


def published_title(basename: str) -> str:
    """The episode's name as it appears in the public repository: `Show - SxxExx - Title`.

    The media filename carries the encode's provenance -- resolution, source, codec, group
    -- which is meaningful in a library and is noise to somebody downloading a subtitle.
    Stripping it here rather than at publish time keeps ONE name: the manifest's
    `episode_title`, its `entry_key`, and the `.ass`/`.srt` filenames are all this string,
    so they cannot drift apart.

    Idempotent by construction, which is load-bearing: `entry_key` is built from this, so a
    title that changed shape would present every already-published episode as new."""
    stripped = BARE_TAG_TAIL.sub("", RELEASE_TAG_TAIL.sub("", basename)).strip()
    # A name that is nothing BUT tags leaves the raw basename: visibly wrong beats a file
    # published with an empty name.
    return stripped or basename


def entry_key(show: str, season: str, episode_title: str) -> str:
    """Stable identity for one published episode, independent of where the media lives."""
    return f"{show}/{season}/{episode_title}"


def content_hash(ass_text: str | None, srt: str | None) -> str:
    """sha256 over exactly what gets published, and nothing else.

    This is the CHANGE-DETECTION AUTHORITY. A stamp being rewritten means the pipeline ran
    again, not that the subtitle differs -- and those are very different questions. The
    2026-09-02 TEXT_VERSION 8->9 bump re-derives and re-muxes every episode in the library
    while changing the actual output of only the 24 shows that carry Japanese song lyrics
    (1,240 cards of 395,671). An mtime rule would have republished the entire repository to
    ship that; this republishes the shows that changed."""
    h = hashlib.sha256()
    h.update((ass_text or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((srt or "").encode("utf-8"))
    return h.hexdigest()


def source_fingerprint(stem: str) -> str | None:
    """The muxed video's identity per its own stamp, as a cheap "might have changed" filter.

    Not authoritative -- see `content_hash`. Its only job is to let a periodic sweep skip
    the ffprobe+ffmpeg extraction for an episode whose video has not been re-muxed since the
    last publish, which is nearly all of them on nearly every run. Conservative by
    construction: a changed fingerprint means "re-extract and let the hash decide", never
    "republish"."""
    stamp = read_stamp(stem + STAMP_SUFFIX)
    if not isinstance(stamp, dict):
        return None
    size, mtime = stamp.get("size"), stamp.get("mtime")
    return None if size is None or mtime is None else f"{size}:{mtime}"


def manifest_entry(
    stem: str,
    show: str,
    season: str,
    episode_title: str,
    duration: float | None,
    *,
    status: str = "unreviewed",
    sha256: str = "",
    source: str | None = None,
) -> dict:
    return {
        "show": show,
        "season": season,
        "episode_title": episode_title,
        "duration_seconds": duration,
        "status": status,
        "sha256": sha256,
        "source": source,
    }


def export_episode(
    stem: str,
    out_root: str,
    *,
    probe=probe_duration_seconds,
    stream_finder=dubtitles_stream_index,
    extractor=extract_ass,
    status: str = "unreviewed",
) -> dict | None:
    """Export one episode's subtitles into `out_root/<show>/<season>/`. None when the
    video has no TRACK_NAME stream to extract -- despite a valid completion stamp, that
    means there is nothing here actually worth shipping.

    Writes the `.ass` and `.srt` and returns the manifest entry carrying their content hash.
    Deciding whether that hash is NEW is the caller's job (`plan_export`), because only the
    caller has the previous manifest."""
    video = find_video(stem)
    if video is None:
        return None
    show = show_for(stem)
    season = os.path.basename(os.path.dirname(stem))
    episode_title = published_title(os.path.basename(stem))

    index = stream_finder(video)
    if index is None:
        return None

    out_dir = os.path.join(out_root, show, season)
    os.makedirs(out_dir, exist_ok=True)
    ass_path = os.path.join(out_dir, episode_title + ".ass")
    if not extractor(video, index, ass_path):
        try:
            os.remove(ass_path)
        except OSError:
            pass
        return None
    try:
        with open(ass_path, encoding="utf-8", errors="replace") as f:
            ass_text = f.read()
    except OSError:
        # The extractor reported success, so the episode still exports -- the pre-existing
        # contract trusts it, and refusing here would newly drop episodes for a read error.
        # The hash then covers the srt alone, which is conservative in the right direction:
        # it can only ever say "changed" when it should not, never the reverse.
        ass_text = None

    srt = dialogue_srt(stem)
    if srt is not None:
        with open(os.path.join(out_dir, episode_title + ".srt"), "w", encoding="utf-8") as f:
            f.write(srt)

    return manifest_entry(
        stem,
        show,
        season,
        episode_title,
        probe(video),
        status=status,
        sha256=content_hash(ass_text, srt),
        source=source_fingerprint(stem),
    )


def read_manifest(path: str) -> dict:
    """The previous publish, keyed by `entry_key`. {} when there is no manifest yet or it
    cannot be parsed -- a first run and an unreadable manifest both mean "publish
    everything", which is the safe direction: it over-publishes rather than silently
    withholding an episode that changed."""
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(entries, list):
        return {}
    out = {}
    for e in entries:
        if isinstance(e, dict) and e.get("episode_title"):
            out[entry_key(e.get("show", ""), e.get("season", ""), e["episode_title"])] = e
    return out


def is_reviewed(stem: str, store: dict) -> bool:
    """Decision 11: this episode has a review queue and every queued line has a verdict.

    Imported semantics, not a second implementation -- `unresolved.undecided` is the same
    call `export_reviewed.qualifying_episodes` makes. Measured 2026-08-31: ZERO episodes in
    the library pass this today (255 One Pace episodes carry a queue, 7,222 queued lines
    have no verdict), which is why the completion gate exists and why this is a per-episode
    STATUS rather than a separate tool and a separate, empty repository."""
    queue = unresolved.items(stem)
    return bool(queue) and not unresolved.undecided(queue, store)


def _published_files_exist(out_root: str, entry: dict) -> bool:
    """True while the repository still carries either file for this manifest entry."""
    stem = os.path.join(out_root, entry.get("show", ""), entry.get("season", ""), entry.get("episode_title", ""))
    return os.path.exists(stem + ".srt") or os.path.exists(stem + ".ass")


def plan_export(stems: list, out_root: str, published: dict, *, store=None, **kw) -> tuple:
    """(entries, stats). Exports each stem and classifies it against the previous manifest.

    `unchanged` episodes are skipped BEFORE the ffprobe/ffmpeg extraction: their muxed video
    carries the same stamp fingerprint it did at the last publish, so the content cannot
    have moved. That is what makes a periodic sweep cheap on the ~99% of runs where nothing
    was re-muxed.

    `rederived` means the video WAS re-muxed but the published bytes came out identical --
    the case a TEXT_VERSION bump creates for every show it does not actually affect. Those
    keep their existing files and produce no repository churn."""
    entries, stats = (
        [],
        {
            "new": 0,
            "updated": 0,
            "rederived": 0,
            "unchanged": 0,
            "skipped": 0,
            "duplicate": 0,
            "retained": 0,
        },
    )
    published_once = set()
    # Sorted, because two encodes of one episode publish ONE name and the walk order must
    # not decide which: an alternating winner republishes the pair on every sweep forever.
    for stem in sorted(stems):
        key = entry_key(
            show_for(stem),
            os.path.basename(os.path.dirname(stem)),
            published_title(os.path.basename(stem)),
        )
        if key in published_once:
            # A second library file for an episode already published this run -- they differ
            # only in release tags, which is exactly what published_title drops. Measured
            # 2026-09-04: 19 such titles across 38 files, all `[JA+EN]` re-releases.
            stats["duplicate"] += 1
            continue
        prior = published.get(key)
        if prior and prior.get("source") and prior["source"] == source_fingerprint(stem):
            entries.append(prior)
            published_once.add(key)
            stats["unchanged"] += 1
            continue
        status = "reviewed" if (store is not None and is_reviewed(stem, store)) else "unreviewed"
        entry = export_episode(stem, out_root, status=status, **kw)
        if entry is None:
            # The key is deliberately NOT claimed: an episode this encode cannot export
            # leaves the other encode free to try.
            stats["skipped"] += 1
            continue
        published_once.add(key)
        if not prior:
            stats["new"] += 1
        elif prior.get("sha256") == entry["sha256"]:
            stats["rederived"] += 1
        else:
            stats["updated"] += 1
        entries.append(entry)

    # An episode this run could not export is not thereby unpublished. The manifest
    # describes what the REPOSITORY carries, and its files are still sitting there --
    # measured 2026-09-04, when a library gone stale against a TEXT_VERSION bump qualified
    # nothing and emptied a manifest covering 48 episodes whose 96 files were untouched.
    # An entry is dropped only once its files are actually gone.
    for key, prior in published.items():
        if key in published_once or not _published_files_exist(out_root, prior):
            continue
        entries.append(prior)
        stats["retained"] += 1
    return entries, stats


def write_manifest(path: str, entries: list) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", required=True)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--decisions-dir",
        default=os.environ.get("DECISIONS_DIR", "/config/decisions"),
        help="mark episodes whose every queued line has a verdict as status=reviewed",
    )
    args = parser.parse_args(argv)

    import decisions  # local: only the reviewed-status path needs the store

    stems = completed_episodes(args.show, args.media_root)
    published = read_manifest(args.manifest)
    store = decisions.load(args.show, args.decisions_dir)
    entries, stats = plan_export(stems, args.out, published, store=store)
    # A manifest file's EXISTENCE is the claim "this show is published". Creating one for a
    # show that exported nothing makes that claim falsely -- and the publish script runs
    # this over every directory in the library, which on 2026-09-04 was 95 shows with
    # nothing to ship. An existing manifest is still rewritten, so a set that shrinks to
    # zero is recorded rather than left stale.
    if entries or os.path.exists(args.manifest):
        write_manifest(args.manifest, entries)
    reviewed = sum(1 for e in entries if e.get("status") == "reviewed")
    print(
        f"exported {len(entries)} of {len(stems)} completed episodes ({reviewed} reviewed, {len(entries) - reviewed} unreviewed)"
    )
    print(
        "  new={new} updated={updated} rederived-identical={rederived} unchanged={unchanged}"
        " skipped={skipped} duplicate-encode={duplicate} retained={retained}".format(**stats)
    )
    # Only these two mean the repository content actually moved. A periodic sweep that
    # prints 0/0 here has nothing to commit, which is the normal case.
    print(f"  republish needed: {stats['new'] + stats['updated']} episode(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
