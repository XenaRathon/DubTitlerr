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
Card    : {"start": float, "end": float,               # DISPLAY timing (after timing)
           "source_start": float, "source_end": float, # SOURCE timing (spoken span)
           "text": str,                                # text may hold one '\\n'
           "avg_logprob": float, "no_speech_prob": float}

The cards satisfy the A1 spec: Netflix readability profile, start pinned to the
spoken onset, never gluing across a >0.5 s pause, end extended into trailing
silence for readability. See specs/a1-reflow-timing/spec.md.
Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import math

# --- Netflix readability profile (the acceptance criteria, in code) ----------
MAX_LINE = 42  # chars per line
MAX_LINES = 2
MAX_CHARS = MAX_LINE * MAX_LINES  # 84 — a single card's text ceiling
MAX_CPS = 17.0  # reading speed (visible chars / display seconds)
MIN_DUR = 0.83  # seconds
MAX_DUR = 7.0  # seconds
MIN_GAP = 0.083  # ~2 frames @ 24 fps — minimum gap between cards
GAP_MAX = 0.5  # hard span break: never glue words across a pause this long
# Within a whisper segment the words are one continuous utterance, so any gap is an
# alignment artifact, not silence — close it (== GAP_MAX so the only real splits left
# are at segment boundaries, where genuine pauses land). Prevents leading-word orphans.
DEJITTER_GAP = GAP_MAX
SENT_END = ".!?…"
CLAUSE = ",;:"
SPLIT_PAUSE_MIN = 0.2  # seconds: the absolute floor for "that was a pause, not
# alignment noise". In continuous speech EVERY inter-word gap is
# a few hundredths of a second, and ~0.2 s is about where a
# listener stops hearing a word boundary and starts hearing a
# break. Kept below GAP_MAX (0.5), above which the span is cut
# outright and this tier never sees the gap at all.
SPLIT_PAUSE_K = 3.0  # ...AND the gap must stand out from THIS piece's own gap
# distribution: >= 3x its median gap. A fixed floor alone
# misjudges both ends -- fast dialogue never reaches it, slow
# dialogue clears it at every single word, which is the same
# arbitrary cut in different clothes. Median, not mean, so one
# long gap cannot inflate the threshold it has to clear.
PROB_FLOOR = 1e-4  # clamp before ln() so prob==0 doesn't give -inf


EPS = 1e-6  # float slack for every threshold comparison. conf.json stores
# 3-decimal values, so a duration re-derived from them lands a
# hair either side of the constant it was set to.


def is_short(dur: float) -> bool:
    """True when a card is genuinely below MIN_DUR (not merely a rounding artifact)."""
    return dur < MIN_DUR - EPS


def layout_faults(text: str, dur: float) -> list[str]:
    """Which display-profile constraints ``text`` violates at ``dur`` seconds; an empty
    list means valid. THE single definition of the profile -- generate.py and repair.py
    both call it, so a repair cannot be accepted against one set of rules and then
    rejected by another. Line lengths are integer character counts, so only cps needs EPS."""
    lines = text.split("\n")
    out = []
    if len(lines) > MAX_LINES:
        out.append("over_lines")
    if any(len(ln) > MAX_LINE for ln in lines):
        out.append("over_line_len")
    if len(text.replace("\n", " ")) > MAX_CHARS:
        out.append("over_chars")
    if card_cps(text, dur) > MAX_CPS + EPS:
        out.append("over_cps")
    return out


def layout_metrics(text: str, dur: float) -> tuple:
    """(line count, longest line, visible chars, cps) -- comparable dimension by
    dimension, so "did this edit make the card worse?" is answerable."""
    lines = text.split("\n")
    flat = text.replace("\n", " ")
    return (len(lines), max((len(ln) for ln in lines), default=0), len(flat), card_cps(text, dur))


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
    """Join word records back into a line.

    A plain " ".join is wrong here. whisper's word_timestamps splits a hyphenated word
    into two word records -- "Gum-gum" arrives as (" Gum", "-gum") -- so joining on spaces
    welds them back as "Gum -gum", a space that was never in the audio. Measured on One
    Pace S30E09: 5 occurrences per episode ("Gas -Gas", "Gum -gum", "Com -com",
    "grown -ups", "no -no") against 0 for the same model/audio decoded with
    word_timestamps=False, so the artefact is ours, not whisper's.

    It is not cosmetic. glossary.correct() matches phrase fixes with
    re.compile(r"\\b" + re.escape(key) + r"\\b"), so a "gas gas" -> "Gas-Gas" fix cannot
    match "Gas -Gas" and the canon correction silently no-ops on exactly the terms most
    likely to need it (Gas-Gas Fruit, Gum-Gum).

    A token that is ONLY dashes ("-", "--", em-dash) is a real separator -- punctuation.py
    emits those deliberately -- and keeps its spaces.
    """
    out: list[str] = []
    for w in words:
        t = w["text"].strip()
        if not t:
            continue
        # "-gum" continues the previous token; "-" on its own separates two of them.
        if out and t.startswith("-") and t.strip("-—–"):
            out[-1] += t
        elif out and out[-1].endswith("-") and out[-1].strip("-—–"):
            out[-1] += t  # the split landed the other way ("Gum-", "gum")
        else:
            out.append(t)
    return " ".join(out)


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


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _best_split_index(piece: list[dict]) -> int:
    """Interior index (1..n-1) at which to cut an overflowing piece, honoring
    the tier order: largest pause -> clause delimiter -> char midpoint.

    Tier 1 wins only on a gap that is genuinely a PAUSE. A `gap > 0` gate fires on
    essentially every piece -- word timestamps always leave a few hundredths between
    words -- so it cut at the largest of a set of indistinguishable noise values, i.e.
    arbitrarily, mid-phrase and across speaker changes. It also made tier 2 unreachable:
    the clause tier needed EVERY gap to be exactly 0.0, which real timestamps never are,
    while 22% of cards with no sentence punctuation carry a comma it could have used."""
    n = len(piece)
    mid = n / 2
    # tier 1: largest inter-word pause (tie -> nearest the midpoint)
    gaps = [piece[i]["start"] - piece[i - 1]["end"] for i in range(1, n)]
    pause = max(SPLIT_PAUSE_MIN, SPLIT_PAUSE_K * _median(gaps))
    gap, _, idx = max((g, -abs(i - mid), i) for i, g in enumerate(gaps, 1))
    if gap >= pause - EPS:
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
    best = None  # split where both lines fit, most balanced
    best_max_len = None  # fallback: minimize the longer line (V2 C13: named,
    fallback_text = None  # not embedded as a tuple's first element)
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


class CascadeInfeasible(Exception):
    """A forward steal ran out of audio: absorbing the rest of the shift would put a
    card's start at or past the end of the media. Carries the accounting -- with
    ``requested == applied + residual`` -- so the caller can log exactly how much did
    not fit. Emitting a knowingly invalid card would be worse than skipping the
    episode, so time_cards() raises instead of truncating.

    The accounting is CUMULATIVE over the cascade: ``applied`` is the displacement it
    already realized across every card it hopped, ``residual`` is the push that would
    not fit at card ``index``, and ``requested`` is their sum. It is deliberately not
    ``original_ask - remaining``: a zero-surplus card needs a BIGGER push than it
    received (its end has to move too), so the leftover is not a slice of the original
    ask and that subtraction goes negative once the cascade hops."""

    def __init__(self, index: int, requested: float, applied: float, residual: float, audio_duration: float | None = None):
        super().__init__(
            f"card {index}: {residual:.3f}s of a {requested:.3f}s forward steal does not "
            f"fit before the end of the audio ({audio_duration}s)"
        )
        self.index, self.audio_duration = index, audio_duration
        self.requested, self.applied, self.residual = requested, applied, residual


def _cascade(
    st: list[float], en: list[float], k: int, shift: float, audio_duration: float | None
) -> tuple[list[int], list[int], dict[int, float]]:
    """Push card ``k`` -- and its successors in turn, if it cannot swallow the whole
    shift -- ``shift`` seconds later. Absorption order: the card's own SURPLUS above
    MIN_DUR first (it merely gets shorter, its END DOES NOT MOVE, and the cascade
    terminates), then the gap behind it, then the next card. Mutates ``st``/``en`` in
    place and returns (displaced, shortened, dur_before). It does NOT return the shift:
    every success path applies the whole request, so an "applied" result could only ever
    hand back the caller's own argument. What did not fit is reported by raising.

    ``displaced`` lists every card whose START moved; ``shortened`` the subset that also
    LOST duration. The two are separate QC counters (B1: "a card that lost duration is a
    different event from one that started later"), and neither is recoverable from the
    finished timings -- a hop whose end moved with its start is indistinguishable
    afterwards from one that was merely displaced -- so the cascade records them here.

    ``dur_before`` maps each touched card to its duration as this hop found it, which is
    likewise unrecoverable afterwards: a displaced card whose end had to move ends up at
    exactly MIN_DUR whatever it was before. B1's event schema names it."""
    applied = 0.0
    displaced: list[int] = []
    shortened: list[int] = []
    durs: dict[int, float] = {}
    while shift > EPS:
        if audio_duration is not None and st[k] + shift >= audio_duration - EPS:
            raise CascadeInfeasible(k, applied + shift, applied, shift, audio_duration)
        dur_before = en[k] - st[k]
        st[k] += shift
        applied += shift
        displaced.append(k)
        durs[k] = dur_before
        if en[k] - st[k] >= MIN_DUR - EPS:  # its own surplus covered it; end unmoved
            shortened.append(k)  # ...so the whole shift came out of its duration
            return displaced, shortened, durs
        en[k] = st[k] + MIN_DUR  # no surplus: its end has to move too
        if MIN_DUR < dur_before - EPS:  # a runt is LENGTHENED here, not shortened
            shortened.append(k)
        if k + 1 == len(st):  # last card: nothing left to push
            return displaced, shortened, durs
        shift = max(en[k] + MIN_GAP - st[k + 1], 0.0)  # what the gap behind it cannot absorb
        k += 1
    return displaced, shortened, durs


def time_cards(groups: list[list[dict]], audio_duration: float | None = None) -> tuple[list[tuple[float, float]], list[dict]]:
    """Assign (start, end) to each group in global order. start = first word onset
    (pinned); end extended into trailing silence to satisfy MIN_DUR/MAX_CPS, capped at
    MAX_DUR and at MIN_GAP before the next group's start.

    Where that cap leaves a card under MIN_DUR the time is STOLEN FORWARD: the
    successor is pushed later (see :func:`_cascade`) until the card fits. The shift is
    NOT the extension delta -- the pre-cap end can already run past the successor's
    start (9 such pairs ship today), so the required shift is measured from where the
    successor must END UP, ``end + MIN_GAP``, absorbing that pre-existing deficit too.
    Starts only ever move LATER: a caption revealed early spoils its own line.

    Returns the timings plus one record per cascade. Raises :class:`CascadeInfeasible`
    when a shift would push a start to or past ``audio_duration`` (None == unbounded)."""
    n = len(groups)
    st = [g[0]["start"] for g in groups]
    en: list[float] = []
    for j, g in enumerate(groups):
        want = max(g[-1]["end"], st[j] + MIN_DUR, st[j] + len(_text(g)) / MAX_CPS)
        end = min(want, st[j] + MAX_DUR)
        if j + 1 < n:  # never overlap the next card; keep a 2-frame gap
            end = min(end, st[j + 1] - MIN_GAP)
        if end < st[j] + MIN_GAP:  # degenerate (next card starts almost immediately)
            end = st[j] + MIN_GAP
        en.append(end)

    records: list[dict] = []
    for j in range(n):
        need = max(en[j], st[j] + MIN_DUR)  # ends only ever move later, too
        if j + 1 < n:
            shift = need + MIN_GAP - st[j + 1]  # covers deficit AND extension in one measure
            if shift > EPS:
                deficit = max(en[j] + MIN_GAP - st[j + 1], 0.0)
                displaced, shortened, durs = _cascade(st, en, j + 1, shift, audio_duration)
                # no applied_shift/residual_shift here: a success applies the whole
                # request, so they were requested and 0.0 on every record ever written --
                # a reporter reading them would conclude "steals always fully fit", which
                # is not something a constant can say. They live on CascadeInfeasible and
                # on the tail clamp below, where the two really do differ.
                records.append(
                    {
                        "reason": "forward_steal",
                        "index": j,
                        "requested_shift": shift,
                        "hops": len(displaced),
                        "displaced": displaced,
                        "shortened": shortened,
                        "dur_before": durs,
                        "preexisting_gap_deficit": deficit,
                        "unfixable": False,
                    }
                )
        en[j] = need
    # the tail has no successor to steal from -- only the media itself bounds it
    if n and audio_duration is not None and en[-1] > audio_duration + EPS and audio_duration > st[-1] + EPS:
        en[-1] = audio_duration
        if is_short(en[-1] - st[-1]):
            short_by = MIN_DUR - (en[-1] - st[-1])
            records.append(
                {
                    "reason": "audio_truncated_tail",
                    "index": n - 1,
                    "requested_shift": short_by,
                    "applied_shift": 0.0,
                    "residual_shift": short_by,
                    "hops": 0,
                    "displaced": [],
                    "shortened": [],
                    "dur_before": {},
                    "preexisting_gap_deficit": 0.0,
                    "unfixable": True,
                }
            )
    return list(zip(st, en)), records


def card_confidence(words: list[dict], segments: list[dict]) -> tuple[float, float]:
    """Per-card confidence: avg_logprob = mean ln(max(prob, PROB_FLOOR)) over the
    card's words; no_speech_prob = max over the segments the words came from."""
    logs = [math.log(max(w.get("prob", PROB_FLOOR), PROB_FLOOR)) for w in words]
    avg = sum(logs) / len(logs) if logs else math.log(PROB_FLOOR)
    segs = {w.get("seg", 0) for w in words}
    nsp = max((segments[s].get("no_speech_prob", 0.0) for s in segs if s < len(segments)), default=0.0)
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
                for m in range(i, k + 1):  # shift the early cluster forward to close it
                    words[m]["start"] += gap
                    words[m]["end"] += gap
        i = j
    return words


ORPHAN_MAX_WORDS = 2  # observed morphology is 1-2 words; widening needs measurement first


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
        return False  # same utterance, not stranded
    if _text(group).rstrip().endswith(tuple(SENT_END)):
        return False  # a complete utterance ("Yes.")
    if nxt[0]["start"] - group[-1]["end"] <= GAP_MAX:
        return False  # no real pause before the next line
    if prev is None:
        return True
    return (
        _text(prev).rstrip().endswith(tuple(SENT_END))  # prev is finished...
        or group[0]["start"] - prev[-1]["end"] > GAP_MAX
    )  # ...or a pause splits them


def _merge_fits(p: list[dict], g: list[dict]) -> bool:
    """True when ``g`` is a runt that ``p`` may absorb: the merged card must satisfy the
    whole profile (gap, chars, duration, reading speed) on its MERGED form."""
    if not is_short(_dur(g)):
        return False
    merged_text = _text(p) + " " + _text(g)
    span = g[-1]["end"] - p[0]["start"]
    return (
        g[0]["start"] - p[-1]["end"] <= GAP_MAX + EPS
        and len(merged_text) <= MAX_CHARS
        and span <= MAX_DUR + EPS
        and card_cps(merged_text, span) <= MAX_CPS + EPS
    )


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
    # The number of ORIGINAL short, non-orphan groups -- the population the acceptance
    # assertion (ordinary_under_min_dur_after == 0) is measured against. Counted ONCE
    # here because it is unrecoverable afterwards: a merged span covers both its parts,
    # and the settle loop can absorb a group that was itself a merge target, so deriving
    # it from the records double-counts. Carried on every record so no index is special.
    census = sum(
        1
        for i, g in enumerate(groups)
        if is_short(_dur(g))
        and not is_orphan_group(g, groups[i + 1] if i + 1 < len(groups) else None, groups[i - 1] if i else None)
    )
    out: list[list[dict]] = []
    merges: list[dict] = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if out and _merge_fits(out[-1], g) and not is_orphan_group(g, nxt, out[-1]):
            merges.append(
                {
                    "reason": "runt_backward_merge",
                    "into": len(out) - 1,  # index, not id(): CPython
                    "absorbed": _text(g),  # reuses ids after GC
                    "short_groups_before": census,
                }
            )
            out[-1] = out[-1] + g
            # Absorbing a runt can leave the TARGET still short while making it cheap
            # enough (cps falls as the span grows) to join ITS predecessor -- a pairing
            # the left-to-right pass already declined and would never revisit. Settle it
            # here, or a second merge_runts() would merge again and the fixed point the
            # docstring promises would be a lie.
            while len(out) > 1 and _merge_fits(out[-2], out[-1]) and not is_orphan_group(out[-1], nxt, out[-2]):
                absorbed = out.pop()
                merges.append(
                    {
                        "reason": "runt_backward_merge",
                        "into": len(out) - 1,
                        "absorbed": _text(absorbed),
                        "short_groups_before": census,
                    }
                )
                out[-1] = out[-1] + absorbed
            continue
        out.append(g)
    return out, merges


def reflow(
    words: list[dict],
    segments: list[dict],
    merge_log: list[dict] | None = None,
    audio_duration: float | None = None,
    cascade_log: list[dict] | None = None,
) -> list[dict]:
    """Turn whisper word/segment data into finished Cards (see module docstring).
    ``merge_log`` and ``cascade_log``, if given, are extended with merge_runts()'s
    per-merge records and time_cards()'s per-cascade records respectively (so a caller
    like generate.py can count them for the QC sidecar without reflow() itself growing a
    wider return type). ``audio_duration`` (None == unbounded) is handed to
    :func:`time_cards`, which raises :class:`CascadeInfeasible` when a forward steal
    would run past the end of the media."""
    groups: list[list[dict]] = []
    for span in split_spans(_dejitter(_clamp_to_segments(_normalize(words), segments))):
        for g in segment_span(span):
            if _text(g).strip():  # drop blank cards
                groups.append(g)
    if not groups:
        return []
    groups, merges = merge_runts(groups)
    if merge_log is not None:
        merge_log.extend(merges)
    cards = []
    nxts = groups[1:] + [None]
    prevs = [None] + groups[:-1]
    times, cascades = time_cards(groups, audio_duration)
    if cascade_log is not None:
        cascade_log.extend(cascades)
    for (start, end), g, nxt, prv in zip(times, groups, nxts, prevs):
        avg, nsp = card_confidence(g, segments)
        cards.append(
            {
                # SOURCE timing is the group's natural spoken span, taken before time_cards()
                # touches anything: DISPLAY start/end may be stolen forward or extended for
                # readability, but the audio a card describes never moves. Downstream evidence
                # lookups (repair's overlap_ref) must anchor on the source window, or a
                # displaced card selects its NEIGHBOUR's subtitle as the justification for a
                # repair. A merged card carries the union: merge_runts() concatenates word
                # lists, so g[0]/g[-1] are the first and last groups' outer words.
                "source_start": g[0]["start"],
                "source_end": g[-1]["end"],
                "start": start,
                "end": end,
                "text": wrap_balance(_text(g)),
                "avg_logprob": avg,
                "no_speech_prob": nsp,
                "orphan": is_orphan_group(g, nxt, prv),
            }
        )
    return cards
