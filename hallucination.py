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

# DROP thresholds (the music/silence combo — both must hold). Deliberately strict so B1 does
# NOT cull music-masked REAL dialogue (e.g. a "Buster Call" line under loud action is nsp~0.86);
# VAD already blocks pure-music/silence, so only near-certain garbage is dropped here.
# NSP_DROP 0.95 IS DELIBERATE AND MEASURED. Do not "fix" it for being unreachable.
#
# It is unreachable: across 859 episodes with a live nsp signal (353,879 cards), 0.95 AND -2.0
# caught exactly ZERO. That looks like a bug, and on 2026-08-21 it was loosened to 0.90 on
# exactly that reasoning -- then reverted the same day once a LABELLED set existed to judge it.
#
# The labels: 207 certain hallucinations (blocklist-matching cards) vs 57,572 real cards from
# the same 136 episodes. nsp separates them well (0.796 vs 0.330, |AUC-0.5|+0.5 = 0.929), and
# avg_logprob too (-0.613 vs -0.164, 0.913) -- but the CONJUNCTION never yields usable
# precision at any operating point:
#
#     nsp>0.70 lp<-0.3 -> recall 82.6%, precision 18.5%, 5.54 false drops per episode
#     nsp>0.80 lp<-0.3 -> recall 54.6%, precision 19.8%, 3.37
#     nsp>0.90 lp<-2.0 -> recall  2.9%, precision 19.4%, 0.18   <- the 2026-08-21 setting
#     nsp>0.95 lp<-2.0 -> recall  0.0%, precision  0.0%, 0.00   <- this one
#
# Precision peaks near 20%: four of every five drops would be real dialogue. At 0.90 the rule
# deletes 25 real cards to catch 6 hallucinations across 136 episodes. Per 0ee667e, "a caption
# that never covers its line is lost content. That is the worse failure" -- so an inert rule is
# strictly better than any reachable setting measured so far. Raising recall requires a signal
# with better precision, not a lower threshold.
#
# Separately: this rule cannot fire AT ALL on large-v3-turbo, whose no_speech_prob is collapsed
# to ~1e-10 (identical across two independent CT2 conversions, so it is the distilled decoder,
# not the packaging). On turbo the BLOCKLIST and is_repetition are the only live defences.
# See docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md sections 4 and 5.
NSP_DROP = 0.95          # no_speech_prob above this AND...
LP_DROP = -2.0           # ...avg_logprob below this => invented text over music/silence
# FLAG thresholds (a single weaker signal -> keep but mark suspect)
NSP_FLAG = 0.5
LP_FLAG = -0.6
# repetition
REPEAT_MIN_TOKENS = 6    # below this a card is too short to call a loop (protects emphasis)
REPEAT_COVERAGE = 0.6    # a repeated word/1-3-gram covering >= this fraction of the card
RUN_COLLAPSE = 4         # collapse a run of >= this many near-identical consecutive cards

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
    if Counter(toks).most_common(1)[0][1] / n >= REPEAT_COVERAGE:   # one word dominates
        return True
    for k in (3, 2):                                                # a 2-3-gram loops
        grams = [tuple(toks[i:i + k]) for i in range(n - k + 1)]
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


def drop_reason(card: dict, rec=None) -> str | None:
    """'blocklist' | 'repetition' | 'music' | None — near-certain garbage only."""
    text = card.get("text", "")
    hit = bool(BLOCKLIST.search(text))
    _tick(rec, "blocklist", hit)
    if hit:
        return "blocklist"
    hit = is_repetition(text)
    _tick(rec, "repetition", hit)
    if hit:
        return "repetition"
    hit = (card.get("no_speech_prob", 0.0) > NSP_DROP
           and card.get("avg_logprob", 0.0) < LP_DROP)
    _tick(rec, "music", hit)
    if hit:
        return "music"
    return None


def flag_reason(card: dict, rec=None) -> str | None:
    """A weaker single-signal suspicion for a KEPT card ('low_conf' | 'maybe_silence' | None)."""
    hit = card.get("avg_logprob", 0.0) < LP_FLAG
    _tick(rec, "low_conf", hit)
    if hit:
        return "low_conf"
    hit = card.get("no_speech_prob", 0.0) > NSP_FLAG
    _tick(rec, "maybe_silence", hit)
    if hit:
        return "maybe_silence"
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
