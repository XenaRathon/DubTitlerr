#!/usr/bin/env python3
"""Split a human correction across two cards when the one it is repairing is too
narrow to hold it, but a legal split exists.

.procoder/todo/20260829-split-a-card-so-a-human-correction-fits.md. `repair.fits_card`
refuses a correction that cannot be displayed on the card it is repairing -- correct for
a MACHINE proposal, but a reviewer has listened to the line and typed what they heard,
and a card one character too narrow throws that transcription away. Two live cases
(`over_line_len`, one character over `MAX_LINE`) split cleanly at a sentence boundary
with no loss; a third (`over_cps`, the card was already too fast BEFORE the human
touched it) does not, and stays out of scope -- splitting only ever relieves
`over_line_len`/`over_chars`, never `over_cps`, so a caller must not reach for this
module on that fault.

Scope, settled 2026-09-02: HUMAN `correct`/`force` verdicts only. A machine repair
proposal that does not fit is still refused outright by `fits_card` -- C1 stays
absolute for that path, which is where it earns its keep.

Derived at srt/ass-write time only, never written into conf.json: the split is a pure
function of the human's stored correction text and the card's own immutable timing,
neither of which ever changes, so it reproduces byte-identically every time it is
re-derived. One durable card, one index, forever -- no renumbering, no migration.
"""

from __future__ import annotations

import re

import reflow

# Ranked candidate cut points: a sentence end is the strongest signal that the two
# halves are independently readable, a clause end (comma/semicolon/colon) the next
# best, and a bare word boundary the fallback when the line has no punctuation at all.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:])\s+")
_WORD_BOUNDARY = re.compile(r"\s+")


def _candidates(text: str) -> list[int]:
    """Character offsets into `text` where the second half would start, ranked best
    first (sentence end, then clause end, then any word boundary), each offset
    appearing once even if more than one pattern matches it."""
    seen: set[int] = set()
    out: list[int] = []
    for pattern in (_SENTENCE_END, _CLAUSE_END, _WORD_BOUNDARY):
        for m in pattern.finditer(text):
            pos = m.end()
            if 0 < pos < len(text) and pos not in seen:
                seen.add(pos)
                out.append(pos)
    return out


def _duration_split(text1: str, text2: str, total_dur: float, words: list | None) -> tuple[float, float]:
    """(dur1, dur2) summing to ``total_dur - reflow.MIN_GAP`` -- the standard gap every
    other pair of adjacent cards in the library gets, taken out of the total rather than
    added on top of it.

    Word-aligned when ``words`` (the ORIGINAL card's own ASR words, in order) covers
    exactly as many words as ``text1``+``text2`` combined: the correction is then a 1:1
    substitution of the original, so real speech timing exists to cut at. Anything else --
    a different word count, no word data, or a word missing its own timing (punctuation
    restoration can insert one with neither) -- falls back to character share, the only
    thing always available for a freely-typed rewrite."""
    avail = total_dur - reflow.MIN_GAP
    n1 = len(text1.split())
    if words is not None and len(words) == n1 + len(text2.split()) and n1 > 0:
        try:
            w_start = words[0]["start"]
            w_cut = words[n1 - 1]["end"]
            w_end = words[-1]["end"]
            span = w_end - w_start
            if None not in (w_start, w_cut, w_end) and span > 0:
                dur1 = (w_cut - w_start) / span * avail
                return dur1, avail - dur1
        except (KeyError, TypeError, ZeroDivisionError):
            pass
    total_chars = len(text1) + len(text2)
    dur1 = avail * len(text1) / total_chars
    return dur1, avail - dur1


def find_legal_split(text: str, start: float, end: float, words: list | None = None):
    """The best-ranked way to show ``text`` as TWO cards spanning ``[start, end]`` instead
    of one, or ``None`` if none of the candidate cuts produces two individually legal
    halves. Tries `_candidates(text)` in rank order and returns the first that works --
    never the shortest, cheapest, or most-balanced split, since a later-but-worse-ranked
    candidate succeeding first would defeat the whole point of ranking them.

    A cut that leaves either side empty (an out-of-range or trailing position) is skipped,
    not accepted as a zero-length card."""
    dur = end - start
    for pos in _candidates(text):
        t1, t2 = text[:pos].strip(), text[pos:].strip()
        if not t1 or not t2:
            continue
        dur1, dur2 = _duration_split(t1, t2, dur, words)
        if dur1 < reflow.MIN_DUR - reflow.EPS or dur2 < reflow.MIN_DUR - reflow.EPS:
            continue
        if reflow.layout_faults(reflow.wrap_balance(t1), dur1):
            continue
        if reflow.layout_faults(reflow.wrap_balance(t2), dur2):
            continue
        mid = start + dur1
        return (
            {"start": start, "end": mid, "text": t1},
            {"start": mid + reflow.MIN_GAP, "end": end, "text": t2},
        )
    return None
