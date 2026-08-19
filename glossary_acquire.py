#!/usr/bin/env python3
"""Acquire proper nouns for a show whose releases carry no mineable subtitle track.

mine_glossary.py can only learn names from an embedded fansub track. Where a release
ships none, the glossary for that stretch of the show stays empty and every name is left
to Whisper's guessing. This module fills that gap from the opposite direction: the show's
wiki owns the candidate list AND every canonical spelling, and the show's own transcripts
only decide which wiki entities are worth asking about. Our errors can raise a question;
they can never become an answer.

See docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md.
Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import json
import math
import os
import re

import jellyfish

import mine_glossary

_DISAMBIG_RE = re.compile(r"\s*\([^)]*\)\s*$")
_REDUCE_RE = re.compile("[\\s" + chr(0x27) + chr(0x2019) + "-]")


def normalize_title(title: str) -> str:
    """A wiki article title reduced to the name itself.

    Fandom titles carry disambiguators and subpages -- 'Misty (anime)',
    'Ash Ketchum/Sun & Moon'. Both are part of the TITLE, not the name, and emitting one
    as a hard_fix canonical would rewrite dialogue to include it."""
    return _DISAMBIG_RE.sub("", str(title).split("/")[0]).strip()


def reduce_form(s: str) -> str:
    """The form both sides are compared on: lowercase, no spaces/apostrophes/hyphens.

    This is what lets the ASR token 'Vanderdecken' match the title 'Van der Decken'.
    The class is built with chr() rather than written literally: the curly apostrophe
    U+2019 gets silently normalised to U+0027 by editors in this toolchain, which
    silently disables curly-apostrophe stripping and passes a literal-looking review."""
    return _REDUCE_RE.sub("", str(s).lower())


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound on k/n at ~95% confidence.

    Used instead of a bare ratio because a ratio cannot tell 5-vs-1 from 56-vs-2 -- both
    look lopsided, but only one is evidence. Wilson discounts the small sample for us."""
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


EXPANSION_RATIO = 1.35


def is_expansion(variant: str, canonical: str) -> bool:
    """True if 'correcting' variant->canonical would GROW a word into a longer name.

    A canonical that merely CONTAINS the variant is not a match: the transcript says
    'Warlords', the wiki title is 'Seven Warlords of the Sea', and substituting one for the
    other rewrites the line into nonsense. Length ratio catches the rest ('Ace' ->
    'Portgas D. Ace'), while a true respelling stays about the same length."""
    v, c = reduce_form(variant), reduce_form(canonical)
    if not v or not c:
        return True
    if v == c:
        return False
    if v in c and len(c) > len(v):
        return True
    return len(c) > len(v) * EXPANSION_RATIO


MIN_SIM = float(os.environ.get("ACQUIRE_MIN_SIM", "0.72"))


def similarity(a: str, b: str) -> float:
    """Jaro-Winkler on the reduced forms, nudged when a phonetic key agrees.

    RECALL, not safety. Measured on real data the true and false pairs overlap completely
    (Syrahose/Shirahoshi 0.755 sits BELOW Warlords/Warlord 0.975), so no threshold here can
    separate them and none is asked to -- R2 and R3 do the rejecting. The phonetic key is a
    bonus signal only: exact metaphone bucketing was tried and split Shirahoshi/Syrahose
    into XRHX/SRHS, dropping the case this module exists for."""
    ra, rb = reduce_form(a), reduce_form(b)
    if not ra or not rb:
        return 0.0
    score = jellyfish.jaro_winkler_similarity(ra, rb)
    if jellyfish.metaphone(ra) == jellyfish.metaphone(rb) or jellyfish.soundex(ra) == jellyfish.soundex(rb):
        score = min(1.0, score + 0.02)
    return score


def best_title(token: str, titles: list) -> tuple[str, float]:
    """(normalised title, score) of the closest title above MIN_SIM, else ('', 0.0)."""
    best, best_score = "", 0.0
    for t in titles:
        norm = normalize_title(t)
        if not norm:
            continue
        s = similarity(token, norm)
        if s > best_score:
            best, best_score = norm, s
    return (best, best_score) if best_score >= MIN_SIM else ("", 0.0)


CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def _conf_text(path: str) -> str:
    """All dialogue text from one conf.json, newline-joined, or '' if unreadable."""
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(rows, list):
        return ""
    return "\n".join(str(r.get("text", "")) for r in rows if isinstance(r, dict))


def _srt_text(path: str) -> str:
    """Dialogue lines from an SRT: drop indices and timecodes, keep the rest."""
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        out.append(s)
    return "\n".join(out)


def harvest(show_dir: str) -> tuple[dict, set, int]:
    """(counts, midsentence, n_files) of capitalised tokens across the show's own output.

    conf.json is preferred; the SRT is the fallback for episodes whose conf is gone (104 of
    696 stamped episodes at time of writing). One source per episode stem, never both."""
    counter: dict = {}
    mid: set = set()
    stems_done, files = set(), 0
    for dp, _dns, fs in os.walk(show_dir):
        for fn in sorted(fs):
            if fn.endswith(CONF_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(CONF_SUFFIX)]), _conf_text(os.path.join(dp, fn))
            elif fn.endswith(SRT_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(SRT_SUFFIX)]), _srt_text(os.path.join(dp, fn))
            else:
                continue
            if stem in stems_done or not text:
                continue
            stems_done.add(stem); files += 1
            mine_glossary.mine_text(text, counter, mid)
    return counter, mid, files
