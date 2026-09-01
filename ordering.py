#!/usr/bin/env python3
"""Watch-order season priority for the generate --root walk.

By default a library run transcribes a show's files in flat alphabetical order
(Season 01 -> Season 36). When a viewer is mid-show, that spends hours re-doing
already-watched early seasons before reaching the arc they're about to watch. This
module reorders so seasons >= a per-show "start season" go first (ascending, i.e.
the viewer's forward watch order), then the earlier seasons — without changing which
files get processed, only the sequence.

The start season is config-driven (no rebuild): a line "Show Name:NN" in
SEASON_PRIORITY_FILE, with SEASON_START as a legitimate global env fallback when
no priority file is configured. Absent both, read_start() returns 0 and logs that
watch-order is disabled; order_files() then does a plain sort — behaviour unchanged.

Pure stdlib, deterministic. Built with help of Claude (Anthropic)."""

from __future__ import annotations

import os
import re

NO_SEASON = 10**6  # sentinel: files with no SxxExx tag sort after all real seasons
_SE = re.compile(r"[Ss](\d+)[Ee](\d+)")


def log(*a):
    print(*a, flush=True)


def season_ep(path: str) -> tuple[int, int]:
    """(season, episode) parsed from an SxxExx tag in the filename; (NO_SEASON, 0) if absent."""
    m = _SE.search(os.path.basename(path))
    if not m:
        return (NO_SEASON, 0)
    return (int(m.group(1)), int(m.group(2)))


def episode_key(path: str) -> str | None:
    """ "SxxExx" identity for an episode, or None with no SxxExx in the filename. One
    canonical stringification of season_ep(), shared by repair.py's per-episode
    prompt weighting and glossary_acquire.py's episode-tag writes so the two cannot
    disagree about a key's spelling."""
    s, e = season_ep(path)
    if s == NO_SEASON:
        return None
    return f"S{s:02d}E{e:02d}"


def order_files(files: list[str], start: int) -> list[str]:
    """Sort files for processing. start<=0 -> plain lexical (unchanged). start>0 -> seasons
    >= start first (ascending season, then episode), then seasons < start (also ascending);
    unmatched files always last. Path is the final tiebreak for determinism."""
    if start <= 0:
        return sorted(files)

    def key(p):
        s, e = season_ep(p)
        tier = 0 if s != NO_SEASON and s >= start else 1  # forward-watch seasons first
        return (tier, s, e, p)

    return sorted(files, key=key)


def read_start(show: str, path: str | None = None) -> int:
    """Start season for `show`: from the priority file ("Show:NN" lines, # comments allowed),
    else the SEASON_START env var, else 0 (disabled). File takes precedence over env, and
    SEASON_START is a legitimate global fallback in its own right -- not just a leftover of
    the disabled path.

    ``path`` resolves from SEASON_PRIORITY_FILE (no more hardcoded default file path). When
    neither a path nor a per-show file match is available, SEASON_START/0 is the result: a
    non-zero SEASON_START is honored (logged as such, since watch-order IS active), and only
    an unset/zero SEASON_START is logged as watch-order disabled (V2 C4). A non-integer value
    for the matched show logs a warning instead of silently returning 0, so a typo'd priority
    file doesn't fail invisibly."""
    path = path or os.environ.get("SEASON_PRIORITY_FILE")
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln or ln.startswith("#") or ":" not in ln:
                        continue
                    name, _, val = ln.rpartition(":")
                    if name.strip() == show:
                        try:
                            return int(val.strip())
                        except ValueError:
                            log(f"ordering: non-integer start for {show!r}: {val.strip()!r}")
                            return 0
        except OSError:
            pass
    try:
        start = int(os.environ.get("SEASON_START", "0"))
    except ValueError:
        start = 0
    if not path:
        if start:
            log(f"ordering: using SEASON_START={start} (no priority file)")
        else:
            log("ordering: SEASON_PRIORITY_FILE not set -- watch-order disabled")
    return start
