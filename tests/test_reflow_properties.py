"""Property-based whole-list invariants for reflow.py (A5).

Tasks 6/7 table-test merge_runts() and the forward steal in isolation; every live
defect this project has found was in their COMPOSITION -- merge -> time -> steal ->
cascade -> clamp. These tests generate adversarial episodes with a seeded
``random.Random`` (stdlib only -- no hypothesis) and assert five invariants over the
WHOLE output list, not over one step:

1. temporal validity   2. readability validity   3. conservation
4. causality           5. idempotence + purity

Built with help of Claude (Anthropic).
"""
import copy
import random

import pytest

import reflow

SEEDS = range(60)


# --- adversarial generation --------------------------------------------------

# short, long, and outright unwrappable tokens (>MAX_LINE, >MAX_CHARS with no
# interior boundary) so wrap_balance's fallback path is exercised.
_TOKENS = ["a", "I", "no", "yes", "wait", "hello", "there", "kind", "of", "really",
           "the", "unbelievable", "extraordinarily", "x",
           "supercalifragilisticexpialidocious",
           "pneumonoultramicroscopicsilicovolcanoconiosisandthensome"]
_DURS = [0.0, 0.0, 0.02, 0.08, 0.2, 0.35, 0.6, 1.4, 3.2, 6.9, 9.5]   # 9.5 > MAX_DUR
# 0.0 == back-to-back; 0.05/0.08 == successors closer than MIN_GAP (9 such pairs
# ship today); -0.04 == whisper handing us an overlapping pair; >0.5 == span break.
_GAPS = [0.0, 0.0, 0.001, 0.05, 0.08, 0.2, 0.49, 0.51, 1.3, 4.0, -0.04]


def _token(rng, punct_p):
    r = rng.random()
    if r < 0.03: return ""                      # blank word: must vanish, not crash
    if r < 0.05: return "   "
    t = rng.choice(_TOKENS)
    p = rng.random()
    if p < punct_p: return t + rng.choice(".?!")
    if p < punct_p + 0.12: return t + rng.choice(",;:")
    return t


def _random_words(rng, n, punct_p=0.12, seg_p=0.2):
    """Adversarial word timing: zero-length words, back-to-back words, successors
    closer than MIN_GAP, overlaps, missing timestamps and mid-utterance seg changes."""
    out, t, seg = [], round(rng.uniform(0.0, 3.0), 3), 0
    for _ in range(n):
        dur = rng.choice(_DURS)
        start, end = t, t + dur
        w = {"text": _token(rng, punct_p), "start": round(start, 3), "end": round(end, 3),
             "prob": rng.choice([0.0, 0.1, 0.5, 0.9, 1.0]), "seg": seg}
        if rng.random() < 0.03: w["start"] = None      # whisper drops these in the wild
        if rng.random() < 0.03: w["end"] = None
        out.append(w)
        t = max(end + rng.choice(_GAPS), 0.0)
        if rng.random() < seg_p: seg += 1
    return out


def _segments_for(rng, words):
    """Segment bounds that sometimes lie: too tight (forces _clamp_to_segments to
    pull words), too loose, unbounded, or missing entirely (seg index out of range)."""
    segs: dict[int, list[float]] = {}
    for w in words:
        s = w["seg"]
        lo = w["start"] if w["start"] is not None else 0.0
        hi = w["end"] if w["end"] is not None else lo
        cur = segs.setdefault(s, [lo, hi])
        cur[0], cur[1] = min(cur[0], lo), max(cur[1], hi)
    out = []
    for s in range(max(segs, default=-1) + 1):
        lo, hi = segs.get(s, [0.0, 0.0])
        mode = rng.random()
        if mode < 0.15:
            out.append({"no_speech_prob": rng.random()})                   # unbounded
            continue
        if mode < 0.35:                                                    # too tight
            span = hi - lo
            lo, hi = lo + span * 0.25, hi - span * 0.25
            if hi < lo: lo = hi
        elif mode < 0.5:
            lo, hi = lo - 0.4, hi + 0.4                                    # too loose
        out.append({"start": round(lo, 3), "end": round(hi, 3), "no_speech_prob": rng.random()})
    if out and rng.random() < 0.1: out.pop()          # words referencing a missing segment
    return out


def _random_episode(rng):
    mode = rng.choice(["mixed", "staccato", "dense", "sparse", "single", "empty", "mixed", "dense",
                       "staccato", "mixed", "sparse", "staccato"])
    if mode == "empty": return [], []
    if mode == "single":
        words = _random_words(rng, 1)
    elif mode == "staccato":            # runs of consecutive short groups ("Yes." "No.")
        words = _random_words(rng, rng.randint(8, 40), punct_p=0.55, seg_p=0.4)
    elif mode == "dense":               # long unbroken utterances -> overflow splitting
        words = _random_words(rng, rng.randint(30, 90), punct_p=0.02, seg_p=0.05)
    elif mode == "sparse":
        words = _random_words(rng, rng.randint(4, 20), punct_p=0.2, seg_p=0.6)
    else:
        words = _random_words(rng, rng.randint(10, 60))
    return words, _segments_for(rng, words)


# --- reference helpers (mirror reflow()'s own pre-timing pipeline) ------------

def _groups(words, segments):
    """The groups reflow() hands to merge_runts(): same five lines, so a card's
    original onset and last-word end can be named without new production fields."""
    prepped = reflow._dejitter(reflow._clamp_to_segments(reflow._normalize(words), segments))
    out = []
    for span in reflow.split_spans(prepped):
        for g in reflow.segment_span(span):
            if reflow._text(g).strip(): out.append(g)
    return out


def _timed_groups(words, segments):
    g, _ = reflow.merge_runts(_groups(words, segments))
    return g


def _tokens(texts):
    return " ".join(texts).split()


def _splittable(text):
    """True when SOME split into <=MAX_LINES lines keeps every line within MAX_LINE.
    ~1% of production cards are 82-84 chars with no boundary near the midpoint;
    wrap_balance falls through to an over-long fallback for exactly those."""
    ws = text.split()
    if len(ws) < 2: return len(text) <= reflow.MAX_LINE
    return any(len(" ".join(ws[:i])) <= reflow.MAX_LINE and len(" ".join(ws[i:])) <= reflow.MAX_LINE
               for i in range(1, len(ws)))


# --- 1-4: whole-list invariants over reflow() --------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_whole_list_invariants(seed):
    rng = random.Random(seed)
    words, segments = _random_episode(rng)
    pristine = copy.deepcopy(words)
    groups = _timed_groups(words, segments)
    try:
        cards = reflow.reflow(words, segments)
    except reflow.CascadeInfeasible:
        return                                   # explicit, allowed failure mode
    assert words == pristine, "reflow() mutated its input words"
    assert len(cards) == len(groups)

    # --- 1. temporal validity ---
    for i, (c, g) in enumerate(zip(cards, groups)):
        onset, last_end = g[0]["start"], g[-1]["end"]
        assert c["start"] < c["end"]
        # C6: the source window is the spoken span, whatever timing did to the display.
        assert (c["source_start"], c["source_end"]) == (onset, last_end)
        # A card may end before its own last word ONLY where the profile caps it: at
        # MAX_DUR past its onset, or MIN_GAP before the successor's spoken onset (which
        # is where time_cards() caps it, using the successor's PRE-shift onset).
        capped_by_next = (i + 1 < len(groups)
                          and c["end"] >= groups[i + 1][0]["start"] - reflow.MIN_GAP - reflow.EPS)
        assert c["end"] >= min(last_end, onset + reflow.MAX_DUR) - reflow.EPS or capped_by_next
    for a, b in zip(cards, cards[1:]):
        assert b["start"] > a["start"], "starts must be strictly ordered"
        assert b["start"] - a["end"] >= reflow.MIN_GAP - reflow.EPS

    # --- 2. readability validity ---
    for c in cards:
        dur = c["end"] - c["start"]
        assert not reflow.is_short(dur) or c["orphan"]
        assert dur <= reflow.MAX_DUR + reflow.EPS
        lines = c["text"].split("\n")
        assert len(lines) <= reflow.MAX_LINES
        for ln in lines:
            assert len(ln) <= reflow.MAX_LINE or not _splittable(c["text"].replace("\n", " "))

    # --- 2b. bounded hang: no card outlasts what its own text needs ---
    for c, g in zip(cards, groups):
        needed = max(reflow.MIN_DUR, len(reflow._text(g)) / reflow.MAX_CPS)
        assert (c["end"] - c["start"]) <= max(reflow.HANG_MIN_DUR,
                                              reflow.HANG_FACTOR * needed) + reflow.EPS

    # --- 3. conservation ---
    assert _tokens(c["text"].replace("\n", " ") for c in cards) == _tokens(w["text"] for w in words)

    # --- 4. causality: never reveal a line before it is spoken ---
    for c, g in zip(cards, groups):
        assert c["start"] >= g[0]["start"] - reflow.EPS


@pytest.mark.parametrize("seed", SEEDS)
def test_preprocessing_never_moves_a_word_earlier_than_spoken(seed):
    """Causality at the source: _normalize/_clamp_to_segments/_dejitter may only move
    a word LATER, the one exception being a word clamped back inside its segment."""
    rng = random.Random(seed)
    words, segments = _random_episode(rng)
    prepped = reflow._dejitter(reflow._clamp_to_segments(reflow._normalize(words), segments))
    for raw, out in zip(words, prepped):
        if raw["start"] is None: continue
        seg = segments[raw["seg"]] if raw["seg"] < len(segments) else {}
        hi = seg.get("end")
        clamped = hi is not None and seg.get("start") is not None and raw["start"] > hi
        assert out["start"] >= raw["start"] - reflow.EPS or clamped


# --- 5. idempotence and purity ----------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_merge_runts_is_a_fixed_point_and_pure(seed):
    rng = random.Random(seed)
    words, segments = _random_episode(rng)
    groups = _groups(words, segments)
    pristine = copy.deepcopy(groups)
    g1, m1 = reflow.merge_runts(groups)
    assert groups == pristine, "merge_runts() mutated its input groups"
    g2, m2 = reflow.merge_runts(g1)
    assert m2 == [], f"second pass merged again: {m2}"
    assert g2 == g1
    assert _tokens(reflow._text(g) for g in g1) == _tokens(reflow._text(g) for g in groups)
    assert len(m1) == len(groups) - len(g1)


# --- CascadeInfeasible accounting and the bounded-audio tail -----------------

@pytest.mark.parametrize("seed", SEEDS)
def test_bounded_audio_keeps_the_invariants_or_raises_with_full_accounting(seed):
    rng = random.Random(seed)
    words, segments = _random_episode(rng)
    groups = _timed_groups(words, segments)
    if not groups: return
    span_end = max(g[-1]["end"] for g in groups)
    audio = round(span_end * rng.uniform(0.4, 1.15), 3)
    try:
        times, records = reflow.time_cards(groups, audio_duration=audio)
    except reflow.CascadeInfeasible as e:
        # the one place the accounting is not a tautology: applied is what the cascade
        # already realized across the cards it hopped, residual is what would not fit.
        assert abs(e.requested - (e.applied + e.residual)) <= reflow.EPS
        assert e.residual > 0 and e.applied >= 0
        assert 0 <= e.index < len(groups)
        return
    for (s, en) in times:
        assert s < en
    for (s0, e0), (s1, _e1) in zip(times, times[1:]):
        assert s1 - e0 >= reflow.MIN_GAP - reflow.EPS
        assert s1 > s0
    # A hang trim rides the same record list but is not a shift: it moves ONE start later
    # and displaces nobody, so it is accounted for on its own terms. Every record is still
    # checked by exactly one of the two loops below -- the cascade population, and the
    # assertions made over it, are unchanged.
    hangs = [r for r in records if r.get("reason") == "hang_trim"]
    shifts = [r for r in records if r.get("reason") != "hang_trim"]
    assert len(hangs) + len(shifts) == len(records)
    for r in hangs:
        assert r["start_after"] > r["start_before"] + reflow.EPS      # starts only move LATER
        assert times[r["index"]][0] == pytest.approx(r["start_after"])
        assert r["needed_dur"] >= reflow.MIN_DUR - reflow.EPS
        assert r["hang_dur"] > r["needed_dur"]
    for i, (s, en) in enumerate(times):
        short = reflow.is_short(en - s)
        assert not short or any(r["index"] == i and r["unfixable"] for r in shifts)
        assert en - s <= reflow.MAX_DUR + reflow.EPS
    for r in shifts:
        assert r["requested_shift"] > reflow.EPS
        if r["unfixable"]:                       # the tail clamp: NONE of the ask was applied,
            assert r["applied_shift"] == 0.0     # so requested == applied + residual is a real
            assert abs(r["requested_shift"] - r["residual_shift"]) <= reflow.EPS   # statement
            assert r["hops"] == 0
        else:                                    # a SUCCESS record: _cascade returns its own
            assert r["hops"] >= 1                # request on every success path, so applied
            assert r["displaced"]                # == requested and residual == 0.0 ALWAYS. The
            assert "applied_shift" not in r      # identity was true by construction and would
            assert "residual_shift" not in r     # survive replacing both fields with literals.


# --- degenerate inputs -------------------------------------------------------

def test_empty_input_yields_no_cards():
    assert reflow.reflow([], []) == []
    assert reflow.time_cards([]) == ([], [])
    assert reflow.merge_runts([]) == ([], [])


def test_single_zero_length_word_still_yields_a_readable_card():
    words = [{"text": "Hi.", "start": 4.0, "end": 4.0, "prob": 0.9, "seg": 0}]
    cards = reflow.reflow(words, [{"start": 4.0, "end": 4.0, "no_speech_prob": 0.0}])
    assert len(cards) == 1
    assert cards[0]["start"] == 4.0
    assert cards[0]["end"] - cards[0]["start"] >= reflow.MIN_DUR - reflow.EPS
