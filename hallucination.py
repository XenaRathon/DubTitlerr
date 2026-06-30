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

# DROP thresholds (the music/silence combo — both must hold)
NSP_DROP = 0.8           # no_speech_prob above this AND...
LP_DROP = -1.0           # ...avg_logprob below this => invented text over music/silence
# FLAG thresholds (a single weaker signal -> keep but mark suspect)
NSP_FLAG = 0.5
LP_FLAG = -0.6
# repetition
REPEAT_MIN_TOKENS = 6    # below this a card is too short to call a loop (protects emphasis)
REPEAT_COVERAGE = 0.6    # a repeated word/1-3-gram covering >= this fraction of the card
RUN_COLLAPSE = 4         # collapse a run of >= this many near-identical consecutive cards

# Known whisper hallucination phrases (music/credits/UGC boilerplate). Conservative —
# only phrases that are never real dub dialogue.
BLOCKLIST = re.compile(
    r"amara\.org|thank you for watching|thanks for watching|thanks for your support|"
    r"please subscribe|subscribe to (the|our|my) channel|like and subscribe|"
    r"see you (in the )?next (video|time)|subtitles by|captions? by|transcri(bed|ption) by|"
    r"translated by|copyright|www\.|http",
    re.I,
)


def is_repetition(text: str) -> bool:
    """True if the card is dominated by a repeated word or short n-gram (a within-line loop)."""
    toks = re.findall(r"[a-z0-9']+", text.lower())
    n = len(toks)
    if n < REPEAT_MIN_TOKENS:
        return False
    if Counter(toks).most_common(1)[0][1] / n >= REPEAT_COVERAGE:   # one word dominates
        return True
    for k in (3, 2):                                                # a 2-3-gram loops
        grams = [tuple(toks[i:i + k]) for i in range(n - k + 1)]
        top = Counter(grams).most_common(1)[0][1]
        if top >= 3 and top * k / n >= REPEAT_COVERAGE:
            return True
    return False


def drop_reason(card: dict) -> str | None:
    """'blocklist' | 'repetition' | 'music' | None — near-certain garbage only."""
    text = card.get("text", "")
    if BLOCKLIST.search(text):
        return "blocklist"
    if is_repetition(text):
        return "repetition"
    if card.get("no_speech_prob", 0.0) > NSP_DROP and card.get("avg_logprob", 0.0) < LP_DROP:
        return "music"
    return None


def flag_reason(card: dict) -> str | None:
    """A weaker single-signal suspicion for a KEPT card ('low_conf' | 'maybe_silence' | None)."""
    raise NotImplementedError


def collapse_runs(cards: list[dict]) -> list[dict]:
    """Collapse runs of >= RUN_COLLAPSE near-identical consecutive cards into one (first
    start, last end). Shorter repeats are left untouched."""
    raise NotImplementedError
