#!/usr/bin/env python3
"""Hallucination confidence-gate for dubtitle cards (B1).

Whisper occasionally invents text over music/silence, loops an n-gram within a line, or
repeats a whole line across many cards. This module classifies reflow cards (post A1 + C1)
into DROP (near-certain garbage) vs FLAG (kept, but suspect) and collapses runaway repeat
runs. Conservative by design: a single weak signal only flags — it never deletes a line.

Pure stdlib, deterministic, runs in the subgen image. Card dicts are
{start, end, text, avg_logprob, no_speech_prob}.  Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import re
from collections import Counter

import reflow

# The two no_speech_prob-gated rules that used to live here -- `music`
# (nsp > 0.95 AND avg_logprob < -2.0 -> drop) and `maybe_silence` (nsp > 0.5 -> flag) --
# were DELETED on 2026-08-24, not tuned. `music` caught 0 of 353,879 cards, and stays at 0
# even on large-v3, whose nsp is live: none of its segments clearing 0.95 also has a
# logprob below -2.0. The conjunction does not occur in this material, so no model change
# revives it, and every reachable relaxation destroys more real dialogue than it saves.
# The full measurement -- including the precision table that forced the 2026-08-21 revert
# -- is preserved in .procoder/adr/0002-the-nsp-gated-rules-are-deleted-not-tuned.md.
# Do not re-add either rule from intuition: the ~20% precision ceiling is the thing to
# beat, not the threshold.
# FLAG thresholds (a single weaker signal -> keep but mark suspect)
LP_FLAG = -0.6
# repetition
REPEAT_MIN_TOKENS = 6  # below this a card is too short to call a loop (protects emphasis)
REPEAT_COVERAGE = 0.6  # a repeated word/1-3-gram covering >= this fraction of the card
RUN_COLLAPSE = 4  # collapse a run of >= this many near-identical consecutive cards

# Known whisper hallucination phrases (music/credits/UGC boilerplate). Conservative —
# only phrases that are never real dub dialogue. V2 C8: sourced from
# data/hallucination_blocklist.txt (one regex alternative per line, # comments allowed)
# so it can be tuned without a code change; falls back to this exact inline pattern if
# the file is missing/unreadable (backward-compatible, e.g. a dev checkout without data/).
_BLOCKLIST_PATTERN_FALLBACK = (
    r"amara\.org|thank you for watching|thanks for watching|thanks for your support|"
    r"please subscribe|subscribe to (the|our|my) channel|like and subscribe|"
    r"see you (in the )?next (video|time)|subtitles by|captions? by|transcri(bed|ption) by|"
    r"translated by|copyright|www\.|http|to be continued|we.?ll be right back"
)


def _load_blocklist(path: str = "data/hallucination_blocklist.txt") -> re.Pattern:
    try:
        with open(path, encoding="utf-8") as f:
            alts = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        alts = []
    return re.compile("|".join(alts) if alts else _BLOCKLIST_PATTERN_FALLBACK, re.I)


BLOCKLIST = _load_blocklist()


def is_repetition(text: str) -> bool:
    """True if the card is dominated by a repeated word or short n-gram (a within-line loop)."""
    toks = re.findall(r"[a-z0-9']+", text.lower())
    n = len(toks)
    if n < REPEAT_MIN_TOKENS:
        return False
    if Counter(toks).most_common(1)[0][1] / n >= REPEAT_COVERAGE:  # one word dominates
        return True
    for k in (3, 2):  # a 2-3-gram loops
        grams = [tuple(toks[i : i + k]) for i in range(n - k + 1)]
        top = Counter(grams).most_common(1)[0][1]
        if top >= 3 and top * k / n >= REPEAT_COVERAGE:
            return True
    return False


def _tick(rec, rule: str, activated: bool) -> None:
    """Record that ``rule`` was EVALUATED, and separately whether it FIRED.

    `evaluated > 0` with `activated == 0` across a season is the dead-rule signal this
    codebase did not have: `music` sat inert through 353,879 cards and every episode still
    reported success, because zero activation is not an error. `rec` is optional so tools/
    and tests can call these bare.

    Short-circuiting is deliberate and meaningful: a rule that returns early leaves the
    later rules UN-evaluated, and the counters should say so rather than implying they ran
    and declined."""
    if rec is None:
        return
    rec.count(f"rule_{rule}_evaluated")
    # ALWAYS create the activated counter, incrementing by 0 when it did not fire. A missing
    # key is indistinguishable from "never reached", which is the exact ambiguity this
    # function exists to remove -- an absent counter would rebuild the invisibility one
    # level down.
    rec.count(f"rule_{rule}_activated", 1 if activated else 0)


# A card of at most this many words whose SOURCE window is longer than reflow.MAX_DUR
# carries a word timestamp whisper got wrong. Scoped deliberately: a long span across
# several words is ordinary dialogue.
BAD_WINDOW_MAX_WORDS = 2


def bad_source_window(card: dict, rec=None) -> bool:
    """True when this card's ``source_*`` window is a whisper timestamp already proven
    implausible -- a one- or two-word card whose source span exceeds reflow.MAX_DUR.

    Measured in the VAD hang-trim investigation: single function words pinned at the 7s
    ceiling ('disobeys', 'it'), and 20 of 401 gated cards carrying MORE word
    probabilities than they have words, because a 7-second window swallows the
    neighbours'. The window is not merely a display problem: two stages select evidence
    with it, and both were trusting a value known to be wrong.

    Returns False when either ``source_*`` key is ABSENT rather than defaulting to the
    display window. The VAD design records two of its own measurements invalidated by
    exactly that -- a ``.get(..., card["start"])`` fallback guaranteeing the answer it
    was asked to test. No window means no evidence that the window is bad.

    This is observability, not recovery: the counters are the point. A caller that finds
    a bad window should use NOTHING, not a substitute."""
    ss, se = card.get("source_start"), card.get("source_end")
    hit = (
        ss is not None
        and se is not None
        and len(card.get("text", "").split()) <= BAD_WINDOW_MAX_WORDS
        and (se - ss) > reflow.MAX_DUR
    )
    _tick(rec, "source_window", hit)
    return hit


def drop_reason(card: dict, rec=None) -> str | None:
    """'blocklist' | 'repetition' | None — near-certain garbage only. The nsp-gated
    'music' rule was deleted 2026-08-24 -- see ADR 0002."""
    text = card.get("text", "")
    hit = bool(BLOCKLIST.search(text))
    _tick(rec, "blocklist", hit)
    if hit:
        return "blocklist"
    hit = is_repetition(text)
    _tick(rec, "repetition", hit)
    if hit:
        return "repetition"
    return None


def flag_reason(card: dict, rec=None) -> str | None:
    """A weaker single-signal suspicion for a KEPT card ('low_conf' | None). The
    nsp-gated 'maybe_silence' was deleted 2026-08-24 -- see ADR 0002."""
    hit = card.get("avg_logprob", 0.0) < LP_FLAG
    _tick(rec, "low_conf", hit)
    if hit:
        return "low_conf"
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def collapse_runs(cards: list[dict]) -> list[dict]:
    """Collapse runs of >= RUN_COLLAPSE near-identical consecutive cards into one (first
    start, last end). Shorter repeats are left untouched."""
    out: list[dict] = []
    i = 0
    while i < len(cards):
        j = i + 1
        key = _norm(cards[i]["text"])
        while j < len(cards) and _norm(cards[j]["text"]) == key:
            j += 1
        run = cards[i:j]
        if len(run) >= RUN_COLLAPSE:
            merged = dict(run[0])
            merged["end"] = run[-1]["end"]
            out.append(merged)
        else:
            out.extend(run)
        i = j
    return out
