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

SCHEMA_VERSION = 3   # v3: the restore_* counters added (punctuation restoration). Zero
                     # in a v2 sidecar means "not counted", not "no run was restored".
                     # v2: over_chars counter added; cards_before,
                     # ordinary_under_min_dur_before, flagged and low_conf went from
                     # permanently-zero to populated. An aggregator must not compare a
                     # v1 sidecar to a v2 one and read the difference as a change in the
                     # pipeline rather than in what was being counted.
MAX_EVENTS = 500          # bound the detail; quantiles stay complete regardless

COUNTERS = ("cards_before", "cards_after", "ordinary_under_min_dur_before",
            "ordinary_under_min_dur_after", "orphan_under_min_dur_after",
            "orphan_candidates", "orphan_candidates_fixed",
            "over_cps", "over_line_len", "over_chars", "violations", "merged_backward", "stolen",
            "shortened_by_neighbour", "displaced", "unfixable_runts",
            "cascade_infeasible", "layout_exceptions", "flagged", "low_conf",
            # punctuation restoration (runs on the words, before reflow -- see punctuation.py)
            "restore_runs_seen", "restore_runs_sent", "restore_accepted",
            "restore_rejected_guard", "restore_empty", "restore_words_repunctuated")

METRICS = ("cps", "required_extension", "displacement", "cascade_depth")


def _q(vals, p):
    if not vals: return 0.0
    s = sorted(vals)
    return s[min(int(p * len(s)), len(s) - 1)]


class Recorder:
    def __init__(self):
        self.counters = dict.fromkeys(COUNTERS, 0)
        self.metrics = {m: [] for m in METRICS}
        self.events = []
        self.priority_events = []
        self.event_count_total = 0

    def count(self, name, n=1):
        self.counters[name] = self.counters.get(name, 0) + n

    def observe(self, metric, value):
        self.metrics.setdefault(metric, []).append(float(value))

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
            "show": show, "episode": episode, "stem": stem,
            **meta,
            "profile": {"min_dur": reflow.MIN_DUR, "max_dur": reflow.MAX_DUR,
                        "max_cps": reflow.MAX_CPS, "min_gap": reflow.MIN_GAP,
                        "max_line": reflow.MAX_LINE, "max_chars": reflow.MAX_CHARS},
            "counters": dict(self.counters),
            "quantiles": {m: {"p50": _q(v, .50), "p90": _q(v, .90), "p95": _q(v, .95),
                              "p99": _q(v, .99), "max": max(v) if v else 0.0}
                          for m, v in self.metrics.items()},
            "event_count_total": self.event_count_total,
            "events_retained": len(self.priority_events) + len(self.events),
            "events_truncated": self.event_count_total > len(self.priority_events) + len(self.events),
            "events": self.priority_events + self.events,
        }


def write(path, doc):
    """Atomic write. Returns True on success, False on failure -- never raises.
    QC is observability: it must not fail an episode that generated correctly.
    A MISSING sidecar is not a clean episode; the aggregate reporter counts absences."""
    tmp = None                        # bound before the try: if mkstemp itself raises,
    try:                              # the cleanup below must not depend on a NameError
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1)
        os.chmod(tmp, 0o644)          # mkstemp gives 0600; this sidecar exists to be READ
        os.replace(tmp, path)         # later, library-wide, by whoever aggregates it
        return True
    except Exception:
        if tmp is not None:
            try: os.unlink(tmp)
            except OSError: pass
        return False
