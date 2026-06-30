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

# --- Netflix readability profile (the acceptance criteria, in code) ----------
MAX_LINE = 42            # chars per line
MAX_LINES = 2
MAX_CHARS = MAX_LINE * MAX_LINES   # 84 — a single card's text ceiling
MAX_CPS = 17.0           # reading speed (visible chars / display seconds)
MIN_DUR = 0.83           # seconds
MAX_DUR = 7.0            # seconds
MIN_GAP = 0.083          # ~2 frames @ 24 fps — minimum gap between cards
GAP_MAX = 0.5            # hard span break: never glue words across a pause this long
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
    raise NotImplementedError


def time_cards(groups: list[list[dict]]) -> list[tuple[float, float]]:
    """Assign (start, end) to each group in global order. start = first word
    onset (pinned); end extended into trailing silence to satisfy MIN_DUR/MAX_CPS,
    capped at MAX_DUR and at MIN_GAP before the next group's start."""
    raise NotImplementedError


def card_confidence(words: list[dict], segments: list[dict]) -> tuple[float, float]:
    """Per-card confidence: avg_logprob = mean ln(max(prob, PROB_FLOOR)) over the
    card's words; no_speech_prob = max over the segments the words came from."""
    raise NotImplementedError


def reflow(words: list[dict], segments: list[dict]) -> list[dict]:
    """Turn whisper word/segment data into finished Cards (see module docstring)."""
    raise NotImplementedError
