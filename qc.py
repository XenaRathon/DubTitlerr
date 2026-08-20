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

SCHEMA_VERSION = 1
MAX_EVENTS = 500          # bound the detail; quantiles stay complete regardless

COUNTERS = ("cards_before", "cards_after", "ordinary_under_min_dur_before",
            "ordinary_under_min_dur_after", "orphan_under_min_dur_after",
            "orphan_candidates", "orphan_candidates_fixed",
            "over_cps", "over_line_len", "violations", "merged_backward", "stolen",
            "shortened_by_neighbour", "displaced", "unfixable_runts",
            "cascade_infeasible", "layout_exceptions", "flagged", "low_conf")

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
        self.event_count_total = 0

    def count(self, name, n=1):
        self.counters[name] = self.counters.get(name, 0) + n

    def observe(self, metric, value):
        self.metrics.setdefault(metric, []).append(float(value))

    def event(self, **fields):
        self.event_count_total += 1
        if len(self.events) < MAX_EVENTS:
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
            "events_retained": len(self.events),
            "events_truncated": self.event_count_total > len(self.events),
            "events": self.events,
        }


def write(path, doc):
    """Atomic write. Returns True on success, False on failure -- never raises.
    QC is observability: it must not fail an episode that generated correctly.
    A MISSING sidecar is not a clean episode; the aggregate reporter counts absences."""
    try:
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        try: os.unlink(tmp)
        except Exception: pass
        return False
