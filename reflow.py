#!/usr/bin/env python3
"""Reflow whisper word-level output into clean, well-timed subtitle cards.

Pure stdlib, deterministic, no CUDA/whisper imports — so the segmentation/timing
rules are fully unit-testable in isolation. ``generate.py`` adapts faster-whisper
objects into the plain dicts below and calls :func:`reflow`.

Data shapes
-----------
word    : {"text": str, "start": float|None, "end": float|None,
           "prob": float, "seg": int}   # seg = index into ``segments``
segment : {"start": float, "end": float, "no_speech_prob": float}
Card    : {"start": float, "end": float, "text": str,   # text may hold one '\\n'
           "avg_logprob": float, "no_speech_prob": float}

The cards satisfy the A1 spec: Netflix readability profile, start pinned to the
spoken onset, never gluing across a >0.5 s pause, end extended into trailing
silence for readability. See specs/a1-reflow-timing/spec.md.
Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import math

# --- Netflix readability profile (the acceptance criteria, in code) ----------
MAX_LINE = 42            # chars per line
MAX_LINES = 2
MAX_CHARS = MAX_LINE * MAX_LINES   # 84 — a single card's text ceiling
MAX_CPS = 17.0           # reading speed (visible chars / display seconds)
MIN_DUR = 0.83           # seconds
MAX_DUR = 7.0            # seconds
MIN_GAP = 0.083          # ~2 frames @ 24 fps — minimum gap between cards
GAP_MAX = 0.5            # hard span break: never glue words across a pause this long
# Within a whisper segment the words are one continuous utterance, so any gap is an
# alignment artifact, not silence — close it (== GAP_MAX so the only real splits left
# are at segment boundaries, where genuine pauses land). Prevents leading-word orphans.
DEJITTER_GAP = GAP_MAX
SENT_END = ".!?…"
CLAUSE = ",;:"
PROB_FLOOR = 1e-4        # clamp before ln() so prob==0 doesn't give -inf


def split_spans(words: list[dict]) -> list[list[dict]]:
    """Split the ordered word list into spans, breaking wherever the gap between
    one word's end and the next word's start exceeds :data:`GAP_MAX`."""
    spans: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] > GAP_MAX:
            spans.append(cur)
            cur = []
        cur.append(w)
    if cur:
        spans.append(cur)
    return spans


def _text(words: list[dict]) -> str:
    return " ".join(w["text"].strip() for w in words)


def _dur(words: list[dict]) -> float:
    return words[-1]["end"] - words[0]["start"]


def _fits(words: list[dict]) -> bool:
    return len(_text(words)) <= MAX_CHARS and _dur(words) <= MAX_DUR


def _split_sentences(span: list[dict]) -> list[list[dict]]:
    """Close a piece after any word whose text ends in sentence-final punctuation."""
    pieces: list[list[dict]] = []
    cur: list[dict] = []
    for w in span:
        cur.append(w)
        if w["text"].rstrip().endswith(tuple(SENT_END)):
            pieces.append(cur)
            cur = []
    if cur:
        pieces.append(cur)
    return pieces


def _best_split_index(piece: list[dict]) -> int:
    """Interior index (1..n-1) at which to cut an overflowing piece, honoring
    the tier order: largest pause -> clause delimiter -> char midpoint."""
    n = len(piece)
    mid = n / 2
    # tier 1: largest inter-word pause (tie -> nearest the midpoint)
    gap, _, idx = max(
        (piece[i]["start"] - piece[i - 1]["end"], -abs(i - mid), i) for i in range(1, n)
    )
    if gap > 0:
        return idx
    # tier 2: clause delimiter, nearest the midpoint
    clause = [i for i in range(1, n) if piece[i - 1]["text"].rstrip().endswith(tuple(CLAUSE))]
    if clause:
        return min(clause, key=lambda i: (abs(i - mid), i))
    # tier 3: word boundary nearest the character midpoint
    half = len(_text(piece)) / 2
    run = 0
    best_i, best_d = 1, None
    for i in range(1, n):
        run += len(piece[i - 1]["text"].strip()) + 1
        d = abs(run - half)
        if best_d is None or d < best_d:
            best_d, best_i = d, i
    return best_i


def _split_overflow(piece: list[dict]) -> list[list[dict]]:
    if len(piece) == 1 or _fits(piece):
        return [piece]
    i = _best_split_index(piece)
    return _split_overflow(piece[:i]) + _split_overflow(piece[i:])


def segment_span(span: list[dict]) -> list[list[dict]]:
    """Segment one span's words into card-sized word groups: sentence-final
    punctuation first; an overflowing piece (>MAX_CHARS or >MAX_DUR) is cut by
    largest internal pause -> clause delimiter near the midpoint -> word-wrap."""
    groups: list[list[dict]] = []
    for piece in _split_sentences(span):
        groups.extend(_split_overflow(piece))
    return groups


def wrap_balance(text: str) -> str:
    """Wrap ``text`` to <=MAX_LINES lines of <=MAX_LINE chars, balanced. Returns
    the text with at most one embedded newline."""
    text = text.strip()
    if len(text) <= MAX_LINE:
        return text
    words = text.split()
    best = None          # split where both lines fit, most balanced
    fallback = None      # otherwise minimize the longer line
    for i in range(1, len(words)):
        l1, l2 = " ".join(words[:i]), " ".join(words[i:])
        if max(len(l1), len(l2)) < (fallback[0] if fallback else float("inf")):
            fallback = (max(len(l1), len(l2)), l1 + "\n" + l2)
        if len(l1) <= MAX_LINE and len(l2) <= MAX_LINE:
            score = abs(len(l1) - len(l2))
            if best is None or score < best[0]:
                best = (score, l1 + "\n" + l2)
    if best:
        return best[1]
    return fallback[1] if fallback else text


def time_cards(groups: list[list[dict]]) -> list[tuple[float, float]]:
    """Assign (start, end) to each group in global order. start = first word
    onset (pinned); end extended into trailing silence to satisfy MIN_DUR/MAX_CPS,
    capped at MAX_DUR and at MIN_GAP before the next group's start."""
    out: list[tuple[float, float]] = []
    n = len(groups)
    for j, g in enumerate(groups):
        start = g[0]["start"]
        natural_end = g[-1]["end"]
        chars = len(_text(g))
        # extend (never shrink below the spoken span) to satisfy min duration + reading speed
        target = max(natural_end, start + MIN_DUR, start + chars / MAX_CPS)
        cap = start + MAX_DUR
        if j + 1 < n:                       # never overlap the next card; keep a 2-frame gap
            cap = min(cap, groups[j + 1][0]["start"] - MIN_GAP)
        end = min(target, cap)
        if end <= start:                    # degenerate (next card starts almost immediately)
            end = start + MIN_GAP
        out.append((start, end))
    return out


def card_confidence(words: list[dict], segments: list[dict]) -> tuple[float, float]:
    """Per-card confidence: avg_logprob = mean ln(max(prob, PROB_FLOOR)) over the
    card's words; no_speech_prob = max over the segments the words came from."""
    logs = [math.log(max(w.get("prob", PROB_FLOOR), PROB_FLOOR)) for w in words]
    avg = sum(logs) / len(logs) if logs else math.log(PROB_FLOOR)
    segs = {w.get("seg", 0) for w in words}
    nsp = max((segments[s].get("no_speech_prob", 0.0) for s in segs if s < len(segments)),
              default=0.0)
    return avg, nsp


def _normalize(words: list[dict]) -> list[dict]:
    """Fill missing timestamps by carrying forward, so downstream timing never
    sees None. Mutates copies; preserves text/prob/seg."""
    out: list[dict] = []
    t = 0.0
    for w in words:
        start = w["start"] if w.get("start") is not None else t
        end = w["end"] if w.get("end") is not None else start
        if end < start:
            end = start
        out.append({**w, "start": float(start), "end": float(end)})
        t = end
    return out


def _clamp_to_segments(words: list[dict], segments: list[dict]) -> list[dict]:
    """Pull each word's timestamps inside its source segment's [start, end].
    Whisper's word DTW occasionally times a segment's leading word far before the
    segment itself; left alone, the >0.5s gap split would strand it as an orphan
    card shown long before its line. Segments without bounds are left untouched."""
    out = []
    for w in words:
        seg = segments[w["seg"]] if w.get("seg", 0) < len(segments) else {}
        lo, hi = seg.get("start"), seg.get("end")
        start, end = w["start"], w["end"]
        if lo is not None and hi is not None and hi >= lo:
            start = min(max(start, lo), hi)
            end = max(min(max(end, lo), hi), start)
        out.append({**w, "start": start, "end": end})
    return out


def _dejitter(words: list[dict]) -> list[dict]:
    """Close implausibly large gaps WITHIN a whisper segment. Whisper sometimes pins a
    segment's leading word(s) to the segment's (too-early) start while the real speech
    is seconds later; the gap between is an alignment artifact, not silence. For each
    such gap (> DEJITTER_GAP) the earlier words are shifted forward to meet the body,
    so they aren't stranded as an early card. Observed leading-orphan pattern only."""
    i = 0
    while i < len(words):
        j = i
        while j < len(words) and words[j]["seg"] == words[i]["seg"]:
            j += 1
        for k in range(i, j - 1):
            gap = words[k + 1]["start"] - words[k]["end"]
            if gap > DEJITTER_GAP:
                for m in range(i, k + 1):     # shift the early cluster forward to close it
                    words[m]["start"] += gap
                    words[m]["end"] += gap
        i = j
    return words


def reflow(words: list[dict], segments: list[dict]) -> list[dict]:
    """Turn whisper word/segment data into finished Cards (see module docstring)."""
    groups: list[list[dict]] = []
    for span in split_spans(_dejitter(_clamp_to_segments(_normalize(words), segments))):
        for g in segment_span(span):
            if _text(g).strip():           # drop blank cards
                groups.append(g)
    if not groups:
        return []
    cards = []
    for (start, end), g in zip(time_cards(groups), groups):
        avg, nsp = card_confidence(g, segments)
        cards.append({
            "start": start, "end": end, "text": wrap_balance(_text(g)),
            "avg_logprob": avg, "no_speech_prob": nsp,
        })
    return cards
