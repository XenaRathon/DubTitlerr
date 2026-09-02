#!/usr/bin/env python3
"""Derive the generate queue from what is actually being watched.

`gen_loop.sh` reads its show order from a flat file and re-reads it every sweep, so this
module only has to regenerate that file. It answers exactly one question -- **is this show
live?** -- and never narrows within a show: once queued, the whole series regenerates,
because the value of a subtitle track is in the episodes ahead of the viewer, not behind.

TWO SOURCES, NEITHER OPTIONAL. Measured 2026-08-21:

  WatchState only   One Pace after 2026-07-11. Playback is on Jellyfin; WatchState syncs
                    the watched flag into Plex WITHOUT bumping Plex's show-level
                    `lastViewedAt`, which sat exactly 40.0 days stale.
  Plex only         SPY x FAMILY, Serial Experiments Lain, Mashle, SK8 the Infinity.
                    WatchState is configured for ONE Plex user (account 1) plus the
                    household Jellyfin; other Plex users are invisible to it.

Each source alone returns a confident, correctly-sorted, incomplete list. Neither is a
superset, so the queue is their union.

TRI-STATE, after tools/vad.py: reachable-with-data / reachable-empty / unreachable. An empty
answer and an unreachable source are different facts, and only one of them is evidence. If
either source cannot be read, the order file is left ALONE -- a stale queue is safe; a queue
silently narrowed by an outage is not.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request

WATCHSTATE_URL = os.environ.get("WATCHSTATE_URL", "")
WATCHSTATE_API_KEY = os.environ.get("WATCHSTATE_API_KEY", "")
PLEX_URL = os.environ.get("PLEX_URL", "")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
PLEX_SECTION = os.environ.get("PLEX_SECTION", "7")
ANIME_ROOT = os.environ.get("ANIME_ROOT", "/media/Anime Library")
TIMEOUT = int(os.environ.get("WATCH_QUEUE_TIMEOUT", "30"))
PER_PAGE = 1000
MAX_PAGES = 100  # backstop; 20k items is 21 pages today


class Unreachable(Exception):
    """A source could not be read. NOT the same as a source with nothing to say."""


def _get(url: str, headers: dict | None = None) -> bytes:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
        raise Unreachable(f"{url.split('?')[0]}: {e}") from e


def clean_title(title: str) -> str:
    """Strip the `(YYYY)` and `{tvdb-NNNN}` suffixes a library directory carries.

    Same normalisation as glossary_verify._clean_title; duplicated rather than imported
    because that module pulls in the wiki/LLM stack this one has no use for."""
    return re.sub(r"\s*\(\d{4}\)|\s*\{[^}]*\}", "", title).strip()


def from_watchstate(since: int) -> dict:
    """{show title -> last watched unix ts} from WatchState. Raises Unreachable.

    `watched=1` is not optional: over the 30 days to 2026-08-21 the state table held 804
    episode rows with watched=0 whose `updated` fell inside the window -- rows that were
    touched by a sync, not watched by a person. Counting them inflates the queue with shows
    nobody has seen."""
    if not (WATCHSTATE_URL and WATCHSTATE_API_KEY):
        raise Unreachable("WATCHSTATE_URL/WATCHSTATE_API_KEY not set")
    out: dict[str, int] = {}
    base = WATCHSTATE_URL.rstrip("/")
    page, pages = 1, 1
    # EVERY page. The rows are NOT ordered by recency -- page 1 of 21 opens on a 2009
    # timestamp -- so stopping early silently reads a near-random slice of the library and
    # calls it "recently watched".
    while page <= pages and page <= MAX_PAGES:
        body = _get(f"{base}/v1/api/history?perpage={PER_PAGE}&page={page}", {"X-apikey": WATCHSTATE_API_KEY})
        try:
            doc = json.loads(body)
        except ValueError as e:
            raise Unreachable(f"watchstate: bad JSON on page {page}: {e}") from e
        # the payload key is `history`; `items` would read empty and look like "nothing
        # watched", which this module is specifically built not to confuse with an outage
        rows = doc.get("history")
        if rows is None:
            raise Unreachable("watchstate: no `history` key in response")
        pages = int((doc.get("paging") or {}).get("last_page") or 1)
        for it in rows:
            if it.get("type") != "episode" or not it.get("watched"):
                continue  # watched=0 rows carry an air date in `updated`, not a play time
            ts = int(it.get("updated") or 0)
            title = (it.get("title") or "").strip()
            if title and ts >= since:
                out[title] = max(out.get(title, 0), ts)
        page += 1
    return out


def from_plex(since: int) -> dict:
    """{show title -> last viewed unix ts} across ALL Plex accounts. Raises Unreachable.

    Filtered CLIENT-SIDE. Plex's `viewedAt>>=` query parameter is silently ignored: a
    60-day request on 2026-08-21 returned rows back to 2025-08-29, well-formed, with no
    indication the filter had not applied."""
    if not (PLEX_URL and PLEX_TOKEN):
        raise Unreachable("PLEX_URL/PLEX_TOKEN not set")
    url = f"{PLEX_URL.rstrip('/')}/status/sessions/history/all?librarySectionID={PLEX_SECTION}&X-Plex-Token={PLEX_TOKEN}"
    xml = _get(url).decode("utf-8", "replace")
    out: dict[str, int] = {}
    for row in re.findall(r"<Video\b[^>]*>", xml):
        g = re.search(r'grandparentTitle="([^"]*)"', row)
        v = re.search(r'viewedAt="(\d+)"', row)
        if not (g and v):
            continue
        ts = int(v.group(1))
        if ts >= since:
            t = html.unescape(g.group(1))
            out[t] = max(out.get(t, 0), ts)
    return out


def library_dirs(root: str) -> list:
    try:
        return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    except OSError as e:
        raise Unreachable(f"anime root {root}: {e}") from e


def fold(title: str) -> str:
    """Aggressive match key: case-folded, stripped of everything but letters and digits.

    Media-server titles and directory names disagree in ways that are invisible at a glance
    and each of these is a REAL case from this library on 2026-08-21:

        Plex "Trigun Stampede"                  dir "TRIGUN STAMPEDE (2023) {tvdb-421378}"
        Plex "I'm in Love with the Villainess"  dir "I'm in Love With the Villainess (2023)…"
        Plex "Marriage Toxin"                   dir "MARRIAGETOXIN (2026) {tvdb-468734}"

    Case, one capitalised preposition, and a missing space. All three would have been
    silently dropped from the queue by exact matching."""
    return re.sub(r"[^a-z0-9]+", "", clean_title(title).casefold())


def match_dirs(titles: dict, dirs: list) -> tuple[list, list]:
    """(ordered directory names, unmatched titles). Three tiers: exact, then the
    `(YYYY)`/`{tvdb-}` normalisation, then `fold()`. Unmatched titles are RETURNED, never
    dropped quietly -- a library rename would otherwise shrink the queue invisibly."""
    by_exact = {d: d for d in dirs}
    by_clean, by_fold, fold_dupes = {}, {}, set()
    for d in dirs:
        by_clean.setdefault(clean_title(d), d)
        k = fold(d)
        if k in by_fold:
            fold_dupes.add(k)  # ambiguous: two directories fold together
        else:
            by_fold[k] = d
    hits, misses = {}, []
    for t, ts in titles.items():
        k = fold(t)
        d = by_exact.get(t) or by_clean.get(clean_title(t)) or (None if k in fold_dupes else by_fold.get(k))
        if d:
            hits[d] = max(hits.get(d, 0), ts)
        else:
            misses.append(t)  # includes anything ambiguous -- report, never guess
    order = [d for d, _ in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))]
    return order, sorted(misses)


def build(since: int, root: str, pins: list | None = None) -> tuple[list, dict]:
    """Union both sources. Raises Unreachable if EITHER cannot be read."""
    ws = from_watchstate(since)
    px = from_plex(since)
    if not ws and not px:
        raise Unreachable("both sources reachable but empty -- cannot tell, refusing to write")
    merged: dict[str, int] = dict(ws)
    for t, ts in px.items():
        merged[t] = max(merged.get(t, 0), ts)
    order, misses = match_dirs(merged, library_dirs(root))
    for p in reversed(pins or []):  # pinned shows lead, in the order given
        if p in order:
            order.remove(p)
        order.insert(0, p)
    return order, {"watchstate": len(ws), "plex": len(px), "union": len(merged), "matched": len(order), "unmatched": misses}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--out", default=os.environ.get("ANIME_ORDER", "/config/anime_order.txt"))
    ap.add_argument("--root", default=ANIME_ROOT)
    ap.add_argument("--pin", action="append", default=[], help="always queue this show, however long since it was watched")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    import time

    since = int(time.time()) - a.window_days * 86400
    try:
        order, rep = build(since, a.root, a.pin)
    except Unreachable as e:
        print(f"watch_queue: REFUSING TO WRITE -- {e}", file=sys.stderr)
        return 2
    print(
        f"watch_queue: watchstate={rep['watchstate']} plex={rep['plex']} "
        f"union={rep['union']} matched={rep['matched']} window={a.window_days}d"
    )
    if rep["unmatched"]:
        print(
            f"  no library directory for {len(rep['unmatched'])}: "
            f"{', '.join(rep['unmatched'][:10])}" + (" …" if len(rep["unmatched"]) > 10 else "")
        )
    for i, d in enumerate(order, 1):
        print(f"  {i:>2} {d}")
    if a.dry_run:
        print("  (dry run -- nothing written)")
        return 0
    if not order:
        # `build()` only reaches here when at least one source had real entries (both-empty
        # raises Unreachable above), so a zero-hit match is a rename or config problem, never
        # a legitimately empty library. Refusing leaves the PREVIOUS order file in place --
        # gen_loop.sh keeps sweeping what it already had rather than going silent for
        # RESCAN_INTERVAL on an order file that parses to zero shows.
        print("watch_queue: REFUSING TO WRITE -- 0 shows matched a library directory (see unmatched above)", file=sys.stderr)
        return 2
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(a.out) or ".", prefix=os.path.basename(a.out) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(order) + "\n")
        os.replace(tmp, a.out)
    except OSError as e:
        print(f"watch_queue: REFUSING TO WRITE -- {e}", file=sys.stderr)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return 2
    print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
