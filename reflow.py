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


EPS = 1e-6               # float slack for every threshold comparison. conf.json stores
                         # 3-decimal values, so a duration re-derived from them lands a
                         # hair either side of the constant it was set to.


def is_short(dur: float) -> bool:
    """True when a card is genuinely below MIN_DUR (not merely a rounding artifact)."""
    return dur < MIN_DUR - EPS


def card_cps(text: str, dur: float) -> float:
    """Visible characters per second. A line break displays as a break, not a char,
    but counts as the space it replaces."""
    return len(text.replace("\n", " ")) / max(dur, EPS)


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
    best = None                # split where both lines fit, most balanced
    best_max_len = None        # fallback: minimize the longer line (V2 C13: named,
    fallback_text = None       # not embedded as a tuple's first element)
    for i in range(1, len(words)):
        l1, l2 = " ".join(words[:i]), " ".join(words[i:])
        cur_max_len = max(len(l1), len(l2))
        if best_max_len is None or cur_max_len < best_max_len:
            best_max_len = cur_max_len
            fallback_text = l1 + "\n" + l2
        if len(l1) <= MAX_LINE and len(l2) <= MAX_LINE:
            score = abs(len(l1) - len(l2))
            if best is None or score < best[0]:
                best = (score, l1 + "\n" + l2)
    if best:
        return best[1]
    return fallback_text if fallback_text is not None else text


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


ORPHAN_MAX_WORDS = 2      # observed morphology is 1-2 words; widening needs measurement first


def is_orphan_group(group: list[dict], nxt: list[dict] | None, prev: list[dict] | None = None) -> bool:
    """A short group stranded ALONE IN ITS OWN SPAN while the utterance it belongs to
    starts in the next segment. _dejitter() cannot reach these because it only closes
    gaps within a segment (`words[j]["seg"] == words[i]["seg"]`).

    The discriminator is whether this group could be a CONTINUATION of its predecessor.
    Timing alone cannot tell: "Wait" may sit 0.1s after "Hello there." and still belong
    to "for me." two seconds later. But "Hello there." is a finished sentence, so
    nothing can continue it -- whereas a fragment trailing an unfinished clause
    plausibly completes that clause and must stay mergeable.

    So: a fragment (few words, no terminal punctuation) separated from the next
    utterance by a real pause AND a segment change, which cannot belong to what
    precedes it. ``prev=None`` means no predecessor to belong to.

    Conservative by design: a false positive merely declines a merge, a false negative
    cements a word into the sentence it does not belong to."""
    if not nxt or len(group) > ORPHAN_MAX_WORDS:
        return False
    if group[-1].get("seg") == nxt[0].get("seg"):
        return False                                  # same utterance, not stranded
    if _text(group).rstrip().endswith(tuple(SENT_END)):
        return False                                  # a complete utterance ("Yes.")
    if nxt[0]["start"] - group[-1]["end"] <= GAP_MAX:
        return False                                  # no real pause before the next line
    if prev is None:
        return True
    return (_text(prev).rstrip().endswith(tuple(SENT_END))          # prev is finished...
            or group[0]["start"] - prev[-1]["end"] > GAP_MAX)       # ...or a pause splits them


def merge_runts(groups: list[list[dict]]) -> tuple[list[list[dict]], list[dict]]:
    """Absorb a too-short group into its predecessor when the merged card would satisfy
    the whole profile. Runs at GROUP level, before time_cards(), so timings are
    re-derived rather than hand-patched. Left-to-right, single pass, fixed point: a
    predecessor that already absorbed a runt is a legal target for the next, with all
    four constraints re-evaluated on the merged form. An orphan (Task 5) never merges
    backward. A merged group still below MIN_DUR is not a failure -- it falls through
    to the forward-steal task. Sentence-final punctuation on the predecessor is NOT a
    gate here -- only a preference downstream can weigh it; this function must still
    merge "Done." + "Next." when the profile fits."""
    out: list[list[dict]] = []
    merges: list[dict] = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if out and is_short(_dur(g)) and not is_orphan_group(g, nxt, out[-1]):
            p = out[-1]
            merged_text = _text(p) + " " + _text(g)
            span = g[-1]["end"] - p[0]["start"]
            if (g[0]["start"] - p[-1]["end"] <= GAP_MAX + EPS
                    and len(merged_text) <= MAX_CHARS
                    and span <= MAX_DUR + EPS
                    and card_cps(merged_text, span) <= MAX_CPS + EPS):
                merges.append({"reason": "runt_backward_merge",
                               "into": len(out) - 1,      # index, not id(): CPython
                               "absorbed": _text(g)})     # reuses ids after GC
                out[-1] = p + g
                continue
        out.append(g)
    return out, merges


def reflow(words: list[dict], segments: list[dict], merge_log: list[dict] | None = None) -> list[dict]:
    """Turn whisper word/segment data into finished Cards (see module docstring).
    ``merge_log``, if given, is extended with merge_runts()'s per-merge records (so a
    caller like generate.py can count them for the QC sidecar without reflow() itself
    growing a wider return type)."""
    groups: list[list[dict]] = []
    for span in split_spans(_dejitter(_clamp_to_segments(_normalize(words), segments))):
        for g in segment_span(span):
            if _text(g).strip():           # drop blank cards
                groups.append(g)
    if not groups:
        return []
    groups, merges = merge_runts(groups)
    if merge_log is not None:
        merge_log.extend(merges)
    cards = []
    nxts = groups[1:] + [None]
    prevs = [None] + groups[:-1]
    for (start, end), g, nxt, prv in zip(time_cards(groups), groups, nxts, prevs):
        avg, nsp = card_confidence(g, segments)
        cards.append({
            "start": start, "end": end, "text": wrap_balance(_text(g)),
            "avg_logprob": avg, "no_speech_prob": nsp,
            "orphan": is_orphan_group(g, nxt, prv),
        })
    return cards
