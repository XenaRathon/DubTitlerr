#!/usr/bin/env python3
"""Watch-order season priority for the generate --root walk.

By default a library run transcribes a show's files in flat alphabetical order
(Season 01 -> Season 36). When a viewer is mid-show, that spends hours re-doing
already-watched early seasons before reaching the arc they're about to watch. This
module reorders so seasons >= a per-show "start season" go first (ascending, i.e.
the viewer's forward watch order), then the earlier seasons — without changing which
files get processed, only the sequence.

The start season is config-driven (no rebuild): a line "Show Name:NN" in
/config/season_priority.txt (SEASON_PRIORITY_FILE), with SEASON_START as an env
fallback. Absent config, order_files() is a plain sort — behaviour unchanged.

Pure stdlib, deterministic. Built with help of Claude (Anthropic)."""
from __future__ import annotations

import os
import re

NO_SEASON = 10**6         # sentinel: files with no SxxExx tag sort after all real seasons
_SE = re.compile(r"[Ss](\d+)[Ee](\d+)")
DEFAULT_PRIORITY_FILE = "/config/season_priority.txt"


def season_ep(path: str) -> tuple[int, int]:
    """(season, episode) parsed from an SxxExx tag in the filename; (NO_SEASON, 0) if absent."""
    m = _SE.search(os.path.basename(path))
    if not m:
        return (NO_SEASON, 0)
    return (int(m.group(1)), int(m.group(2)))


def order_files(files: list[str], start: int) -> list[str]:
    """Sort files for processing. start<=0 -> plain lexical (unchanged). start>0 -> seasons
    >= start first (ascending season, then episode), then seasons < start (also ascending);
    unmatched files always last. Path is the final tiebreak for determinism."""
    if start <= 0:
        return sorted(files)

    def key(p):
        s, e = season_ep(p)
        tier = 0 if s != NO_SEASON and s >= start else 1   # forward-watch seasons first
        return (tier, s, e, p)

    return sorted(files, key=key)


def read_start(show: str, path: str | None = None) -> int:
    """Start season for `show`: from the priority file ("Show:NN" lines, # comments allowed),
    else the SEASON_START env var, else 0 (disabled). File takes precedence over env."""
    path = path or os.environ.get("SEASON_PRIORITY_FILE", DEFAULT_PRIORITY_FILE)
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
                        return 0
    except OSError:
        pass
    try:
        return int(os.environ.get("SEASON_START", "0"))
    except ValueError:
        return 0
