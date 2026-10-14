#!/usr/bin/env python3
"""Per-episode QC sidecar: what the timing/layout passes did, and how bad the
residue is. Written next to conf.json and, like it, surviving the mux -- so the
library can be aggregated later without re-transcribing anything.

Counters answer "how many"; quantiles answer "how bad"; events answer "which ones".
A threshold decision needs all three, which is why the v1 counters-only design could
not settle the deferred cps question. Pure stdlib, no I/O except write().
Built with help of Claude (Anthropic).
"""

import json
import os
import tempfile

SCHEMA_VERSION = 4  # v4: rule_*_evaluated / rule_*_activated liveness counters. v3: the
# restore_* counters added (punctuation restoration). Zero
# in a v2 sidecar means "not counted", not "no run was restored".
# v2: over_chars counter added; cards_before,
# ordinary_under_min_dur_before, flagged and low_conf went from
# permanently-zero to populated. An aggregator must not compare a
# v1 sidecar to a v2 one and read the difference as a change in the
# pipeline rather than in what was being counted.
MAX_EVENTS = 500  # bound the detail; quantiles stay complete regardless

# Duration detector thresholds
OVERLONG_DUR_FLOOR = 6.0  # seconds: a card must exceed this duration to be flagged
OVERLONG_BASE_DUR = 3.0  # seconds: baseline minimum duration for words-based check
OVERLONG_WORD_FACTOR = 0.6  # seconds per word

DRIP_MIN_CARDS = 3  # minimum consecutive cards for a drip chain
DRIP_MIN_WORDS = 1  # minimum words per card in a drip chain
DRIP_MAX_WORDS = 2  # maximum words per card in a drip chain
DRIP_MAX_GAP = 1.0  # seconds: maximum gap between cards in a drip chain
DRIP_MIN_SPAN = 6.0  # seconds: minimum total span for a drip chain

REASON_OVERLONG = "overlong"
REASON_DRIP_CHAIN = "drip_chain"

COUNTERS = (
    "cards_before",
    "cards_after",
    "ordinary_under_min_dur_before",
    "ordinary_under_min_dur_after",
    "orphan_under_min_dur_after",
    "orphan_candidates",
    "orphan_candidates_fixed",
    "over_cps",
    "over_line_len",
    "over_chars",
    "violations",
    "merged_backward",
    "stolen",
    "shortened_by_neighbour",
    "displaced",
    "unfixable_runts",
    "cascade_infeasible",
    "layout_exceptions",
    "flagged",
    "low_conf",
    # punctuation restoration (runs on the words, before reflow -- see punctuation.py)
    "restore_runs_seen",
    "restore_runs_sent",
    "restore_accepted",
    "restore_rejected_guard",
    "restore_empty",
    "restore_words_repunctuated",
)

METRICS = ("cps", "required_extension", "displacement", "cascade_depth")


def _q(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(int(p * len(s)), len(s) - 1)]


def detect_duration_flags(cards):
    """Report-only detector for overlong cards and drip chains.

    Rules:
    1. Flag a card when duration > 6.0 s AND duration > max(3.0, words * 0.6) s.
    2. Flag a drip chain when 3 or more consecutive cards each hold 1-2 words,
       the gaps between them are each under 1.0 s, and the chain spans more than 6.0 s.

    Returns a list of {start, end, duration, words, text, reason}.
    Does not mutate the input cards.
    """
    if not cards:
        return []

    flags = []

    # 1. Overlong cards
    for c in cards:
        dur = c["end"] - c["start"]
        words = len(c.get("text", "").split())
        if dur > OVERLONG_DUR_FLOOR and dur > max(OVERLONG_BASE_DUR, words * OVERLONG_WORD_FACTOR):
            flags.append(
                {
                    "start": round(c["start"], 3),
                    "end": round(c["end"], 3),
                    "duration": round(dur, 3),
                    "words": words,
                    "text": c.get("text", "").replace("\n", " ").strip(),
                    "reason": REASON_OVERLONG,
                }
            )

    # 2. Drip chains
    # Evaluate contiguous sequences in order of display timing
    ordered = sorted(cards, key=lambda c: (c["start"], c["end"]))
    i = 0
    n = len(ordered)
    while i < n:
        c = ordered[i]
        w = len(c.get("text", "").split())
        if DRIP_MIN_WORDS <= w <= DRIP_MAX_WORDS:
            chain = [c]
            j = i + 1
            while j < n:
                next_c = ordered[j]
                next_w = len(next_c.get("text", "").split())
                if not (DRIP_MIN_WORDS <= next_w <= DRIP_MAX_WORDS):
                    break
                gap = next_c["start"] - ordered[j - 1]["end"]
                if gap >= DRIP_MAX_GAP:
                    break
                chain.append(next_c)
                j += 1

            if len(chain) >= DRIP_MIN_CARDS:
                span = chain[-1]["end"] - chain[0]["start"]
                if span > DRIP_MIN_SPAN:
                    total_words = sum(len(x.get("text", "").split()) for x in chain)
                    joined_text = " ".join(x.get("text", "").replace("\n", " ").strip() for x in chain)
                    flags.append(
                        {
                            "start": round(chain[0]["start"], 3),
                            "end": round(chain[-1]["end"], 3),
                            "duration": round(span, 3),
                            "words": total_words,
                            "text": joined_text,
                            "reason": REASON_DRIP_CHAIN,
                        }
                    )
            i = j
        else:
            i += 1

    flags.sort(key=lambda f: (f["start"], f["end"]))
    return flags


class Recorder:
    def __init__(self):
        self.counters = dict.fromkeys(COUNTERS, 0)
        self.metrics = {m: [] for m in METRICS}
        self.events = []
        self.priority_events = []
        self.event_count_total = 0
        self.duration_flags = []

    def count(self, name, n=1):
        self.counters[name] = self.counters.get(name, 0) + n

    def observe(self, metric, value):
        self.metrics.setdefault(metric, []).append(float(value))

    def record_duration_flags(self, cards):
        self.duration_flags = detect_duration_flags(cards)

    def event(self, priority=False, **fields):
        """Record one event. ``priority=True`` events are never evicted by ordinary ones.

        The cap keeps the sidecar bounded, but it keeps the FIRST MAX_EVENTS -- so a
        common event class can crowd out a rare one that no counter can reconstruct.
        Measured: a real episode emits ~130 over_cps events (already counted losslessly
        by _record_qc and described by the cps quantiles) against a handful of
        correction-introduced layout exceptions, which exist nowhere else."""
        self.event_count_total += 1
        if priority:
            self.priority_events.append(fields)
        elif len(self.events) < MAX_EVENTS:
            self.events.append(fields)

    def build(self, show, episode, stem, **meta):
        import reflow

        return {
            "schema_version": SCHEMA_VERSION,
            "show": show,
            "episode": episode,
            "stem": stem,
            **meta,
            "profile": {
                "min_dur": reflow.MIN_DUR,
                "max_dur": reflow.MAX_DUR,
                "max_cps": reflow.MAX_CPS,
                "min_gap": reflow.MIN_GAP,
                "max_line": reflow.MAX_LINE,
                "max_chars": reflow.MAX_CHARS,
            },
            "counters": dict(self.counters),
            "quantiles": {
                m: {"p50": _q(v, 0.50), "p90": _q(v, 0.90), "p95": _q(v, 0.95), "p99": _q(v, 0.99), "max": max(v) if v else 0.0}
                for m, v in self.metrics.items()
            },
            "duration_flags": list(self.duration_flags),
            "event_count_total": self.event_count_total,
            "events_retained": len(self.priority_events) + len(self.events),
            "events_truncated": self.event_count_total > len(self.priority_events) + len(self.events),
            "events": self.priority_events + self.events,
        }


def write(path, doc):
    """Atomic write. Returns True on success, False on failure -- never raises.
    QC is observability: it must not fail an episode that generated correctly.
    A MISSING sidecar is not a clean episode; the aggregate reporter counts absences."""
    tmp = None  # bound before the try: if mkstemp itself raises,
    try:  # the cleanup below must not depend on a NameError
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1)
        # 0664, NOT 0644: mkstemp gives 0600, and this sidecar exists to be READ later,
        # library-wide, by whoever aggregates it -- and REWRITTEN by whoever regenerates
        # the episode, who may not be the uid that created it. Hardcoded rather than
        # imported because qc.py is deliberately standalone (observability must not take
        # a dependency on the pipeline); test_qc_mode_matches_common pins it to
        # common.SIDECAR_MODE so the two cannot drift.
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False
