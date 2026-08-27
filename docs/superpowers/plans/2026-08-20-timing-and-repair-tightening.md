# Timing and Repair Tightening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three live defects in the DubTitlerr subtitle pipeline -- destroyed line wrapping, sub-minimum-duration cards, and overlapping cards -- add the QC sidecar that would have caught them, and let the glossary acquire names from our own transcripts.

**Architecture:** Deterministic changes to `reflow.py` (card merging and timing), a new `qc.py` observability module, guards in `repair.py` that constrain the LLM by the timing profile rather than letting it invalidate the profile, and a new candidate source for `glossary_acquire.py`. Every change is pure-stdlib and unit-testable without a model or GPU.

**Tech Stack:** Python 3.11+, pytest, stdlib only for the pipeline logic (`pysubs2`/`jellyfish` used elsewhere in the repo).

**Spec:** `docs/superpowers/specs/2026-08-20-timing-and-repair-tightening-design.md` (v4, FINAL -- reviewed over three adversarial rounds)

## Global Constraints

- **Run tests with `.venv/bin/python -m pytest`.** The system python lacks `pysubs2` and `jellyfish`; 14 test modules fail to collect under it. Baseline before this plan: **605 passed in ~19s**.
- **Every duration/threshold comparison carries an epsilon of `1e-6`**: `< X - EPS`, `> X + EPS`. Never bare `<` or `>`. This is the discipline whose absence made a naive count report 1,140 runts where there are 730.
- **Compute from full-precision floats; round only at JSON serialisation.** `conf.json` stores 3-decimal values; re-deriving a duration from them loses the epsilon.
- Netflix profile constants live in `reflow.py` and are imported, never re-declared: `MAX_LINE=42`, `MAX_LINES=2`, `MAX_CHARS=84`, `MAX_CPS=17.0`, `MIN_DUR=0.83`, `MAX_DUR=7.0`, `MIN_GAP=0.083`, `GAP_MAX=0.5`.
- **`reflow.py` stays pure stdlib and deterministic** -- no model, no I/O, no clock. That is what makes the timing rules testable.
- **No card ever moves earlier than its original onset.** A late caption is acceptable; an early one can spoil.
- Do not touch, commit, or run the untracked files `boxxo_voice_extract.py` / `tests/test_boxxo_voice_extract.py` / `AGENTS.md` -- they belong to another workstream.
- House style is deliberately terse one-liners (`if x: return`). Match it. `ruff` config allows `E701`/`E702`.
- Commit after each task with a conventional-commit message.

## File Structure

| File                  | Responsibility                                      | Tasks            |
| --------------------- | --------------------------------------------------- | ---------------- |
| `reflow.py`           | card grouping, merging, timing, wrapping (pure)     | 1, 5, 6, 7, 8, 9 |
| `qc.py` (new)         | QC sidecar schema, quantiles, bounded event list    | 2                |
| `generate.py`         | pipeline orchestration, conf/srt writing, QC wiring | 3, 9, 10         |
| `repair.py`           | LLM repair, acceptance guards, srt rewrite          | 4, 9, 11         |
| `recreate_srt.py`     | rebuild srt from conf                               | 4                |
| `mine_glossary.py`    | fansub name mining                                  | 12               |
| `glossary_acquire.py` | wiki-adjudicated acquisition                        | 13               |

---

### Task 1: Epsilon discipline and duration helpers

**Files:**

- Modify: `reflow.py` (constants block, ~line 26-40)
- Test: `tests/test_reflow.py`

**Interfaces:**

- Produces: `reflow.EPS`, `reflow.is_short(dur)`, `reflow.card_cps(text, dur)` -- used by every later task.

- [ ] **Step 1: Write the failing test**

```python
def test_eps_absorbs_json_round_trip_error():
    """A card set to exactly start+MIN_DUR, round-tripped through 3-decimal JSON,
    must NOT count as short. This is the bug that inflated the runt count by 56%."""
    start = round(11.51, 3)
    end = round(start + reflow.MIN_DUR, 3)
    assert end - start < reflow.MIN_DUR          # the float artifact is real
    assert not reflow.is_short(end - start)      # ...and is_short must ignore it


def test_is_short_still_catches_a_real_runt():
    assert reflow.is_short(0.02)
    assert reflow.is_short(reflow.MIN_DUR - 0.01)


def test_card_cps_uses_visible_chars():
    assert reflow.card_cps("ab\ncd", 1.0) == 5.0   # newline counts as one space
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_reflow.py -k "eps or is_short or card_cps" -v`
Expected: FAIL, `AttributeError: module 'reflow' has no attribute 'EPS'`

- [ ] **Step 3: Implement**

In `reflow.py`, after the constants block:

```python
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
```

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_reflow.py -q` -> PASS
Run: `.venv/bin/python -m pytest -q` -> 605 + 3 passed

- [ ] **Step 5: Commit**

```bash
git add reflow.py tests/test_reflow.py
git commit -m "feat(reflow): add EPS and duration helpers for threshold comparisons"
```

---

### Task 2: The QC sidecar module

**Files:**

- Create: `qc.py`
- Test: `tests/test_qc.py`

**Interfaces:**

- Produces: `qc.Recorder` with `.count(name, n=1)`, `.observe(metric, value)`, `.event(**fields)`, `.build(show, episode, stem, **meta) -> dict`, and `qc.write(path, doc) -> bool`.
- `MAX_EVENTS = 500`.

**Why a Recorder and not a dict:** the deferred cps-stealing decision needs quantiles over the whole card population while the event list is capped. Those two have different lifetimes, so accumulation is the module's job, not the caller's.

- [ ] **Step 1: Write the failing test**

```python
import qc

def test_quantiles_are_complete_even_when_events_truncate():
    r = qc.Recorder()
    for i in range(qc.MAX_EVENTS + 50):
        r.observe("displacement", i * 0.01)
        r.event(card_id=f"c{i}", effects=["displaced"], delta_start=i * 0.01)
    doc = r.build(show="S", episode="E1", stem="/x/E1")
    assert doc["events_truncated"] is True
    assert doc["events_retained"] == qc.MAX_EVENTS
    assert doc["event_count_total"] == qc.MAX_EVENTS + 50
    q = doc["quantiles"]["displacement"]
    assert q["max"] == pytest.approx(5.49)       # every observation counted
    assert q["p50"] < q["p90"] < q["p99"] <= q["max"]


def test_effects_is_a_list_not_an_enum():
    r = qc.Recorder()
    r.event(card_id="c0", effects=["shortened", "displaced"])
    ev = r.build(show="S", episode="E1", stem="/x/E1")["events"][0]
    assert ev["effects"] == ["shortened", "displaced"]


def test_counters_default_to_zero_and_increment():
    r = qc.Recorder()
    r.count("merged_backward", 3)
    c = r.build(show="S", episode="E1", stem="/x/E1")["counters"]
    assert c["merged_backward"] == 3
    assert c["stolen"] == 0                      # declared, not absent


def test_write_returns_false_on_failure_and_never_raises():
    assert qc.write("/nonexistent-dir/x.json", {"a": 1}) is False
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_qc.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'qc'`

- [ ] **Step 3: Implement `qc.py`**

```python
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
```

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_qc.py -q` -> PASS

- [ ] **Step 5: Commit**

```bash
git add qc.py tests/test_qc.py
git commit -m "feat(qc): per-episode sidecar with counters, quantiles and bounded events"
```

---

### Task 3: Wire QC into generate.py and add the MIN_DUR floor

**Files:**

- Modify: `generate.py` (~line 318-333, the stats block)
- Test: `tests/test_generate.py`

**Interfaces:**

- Consumes: `qc.Recorder`, `qc.write`, `reflow.is_short`, `reflow.card_cps`.
- Produces: `<stem>.dubtitles.qc.json` beside `<stem>.dubtitles.conf.json`.

**Context:** `generate.py:322`'s `bad` counter checks `dur > 7.001`, line count and line length -- every ceiling, no floor. That is structurally why a 0.02s card was never a violation. It is the check that was supposed to catch this.

- [ ] **Step 1: Write the failing test**

```python
def test_violation_counter_now_has_a_min_dur_floor(tmp_path):
    rows = [(0.0, 0.02, "Cool!")]                 # 0.02s, 294 cps
    rec = qc.Recorder()
    generate._record_qc(rec, rows)
    c = rec.build(show="S", episode="E", stem="x")["counters"]
    assert c["ordinary_under_min_dur_after"] == 1
    assert c["violations"] == 1                   # floor breach IS a violation


def test_exact_min_dur_card_is_not_a_violation():
    rows = [(11.51, round(11.51 + reflow.MIN_DUR, 3), "ok")]
    rec = qc.Recorder()
    generate._record_qc(rec, rows)
    assert rec.build(show="S", episode="E", stem="x")["counters"]["violations"] == 0


def test_qc_sidecar_is_written_next_to_conf(tmp_path):
    ...   # drive generate's write path; assert <stem>.dubtitles.qc.json exists
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_generate.py -k qc -v` -> FAIL, no `_record_qc`

- [ ] **Step 3: Implement**

Replace the discarded-stats block in `generate.py`:

```python
QC_SUFFIX = ".dubtitles.qc.json"


def _record_qc(rec, rows):
    """Fold the finished (start, end, text) rows into the QC recorder. Validates
    every FLOOR as well as every ceiling -- the omission that hid 730 short cards."""
    for a, b, t in rows:
        dur = b - a
        cps = reflow.card_cps(t, dur)
        rec.observe("cps", cps)
        lines = t.split("\n")
        short = reflow.is_short(dur)
        over_cps = cps > reflow.MAX_CPS + reflow.EPS
        over_line = any(len(ln) > reflow.MAX_LINE for ln in lines)
        if short: rec.count("ordinary_under_min_dur_after")
        if over_cps: rec.count("over_cps")
        if over_line: rec.count("over_line_len")
        if short or over_cps or over_line or dur > reflow.MAX_DUR + reflow.EPS or len(lines) > reflow.MAX_LINES:
            rec.count("violations")
```

and after writing `conf`, build and write the sidecar (failure logged, never fatal).

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest -q` -> all pass

- [ ] **Step 5: Commit**

```bash
git add generate.py tests/test_generate.py
git commit -m "fix(generate): validate the MIN_DUR floor and persist a QC sidecar"
```

---

### Task 4: Restore line wrapping in repair.py (LIVE DEFECT)

**Files:**

- Modify: `repair.py` (~line 386-390, the srt rewrite)
- Modify: `recreate_srt.py` (same defect, same fix)
- Test: `tests/test_repair.py`

**Interfaces:**

- Consumes: `reflow.wrap_balance` (already public).

**Context -- this is the highest-visibility item in the plan.** `generate.py:303` writes `conf.json` with `text.replace("\n", " ")`, flattening the wrap. `repair.py:388-390` then rewrites the srt from those conf rows and never re-wraps. Verified against shipped, muxed tracks: **zero multi-line cues exist anywhere in the library**; 25-32% of cues exceed 42 characters on one line (One Pace S30E01 165/520, Chainsaw Man 298/1123, BEASTARS 101/411). Every episode that passes through repair ships unwrapped -- whether or not repair changed a single word.

- [ ] **Step 1: Write the failing test**

```python
def test_repair_rewraps_even_when_it_changes_nothing(tmp_path):
    """A no-op repair must still write a wrapped srt. This is the live defect:
    conf.json holds flattened text and repair passed it straight through."""
    long_line = "Now everybody lift your hands up Sing about what you are dreaming"
    conf = [{"start": 0.0, "end": 5.0, "text": long_line}]
    ...   # drive repair.process with an empty reference so nothing is repaired
    cues = _parse_srt(srt_path)
    assert len(cues[0]["lines"]) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in cues[0]["lines"])


def test_repair_rewraps_a_repaired_line_too():
    ...   # same assertion on a line the LLM did change
```

- [ ] **Step 2: Run and watch it fail**

Run: `.venv/bin/python -m pytest tests/test_repair.py -k rewrap -v`
Expected: FAIL -- one line of 65 characters

- [ ] **Step 3: Implement**

In `repair.py`, the srt rewrite becomes:

```python
    # rewrite srt from (possibly repaired) conf rows. conf.json stores text FLATTENED
    # (generate.py replaces '\n' with ' '), so re-wrap here or every episode that
    # passes through repair ships as unwrapped single lines -- which is exactly what
    # the library did until this fix.
    with open(srt_out, "w") as f:
        for i, c in enumerate(conf, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n"
                    f"{reflow.wrap_balance(c['text'])}\n\n")
```

Apply the identical change in `recreate_srt.py`.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_repair.py tests/test_recover_dub_srt.py -q` -> PASS

- [ ] **Step 5: Commit**

```bash
git add repair.py recreate_srt.py tests/test_repair.py
git commit -m "fix(repair): re-wrap the srt on rewrite - every episode shipped unwrapped"
```

---

### Task 5: Orphan detection and quarantine (PREREQUISITE for Task 6)

**Files:**

- Modify: `reflow.py` (`segment_span` output / group provenance)
- Test: `tests/test_reflow.py`

**Interfaces:**

- Produces: `reflow.is_orphan_group(group) -> bool` and an `"orphan"` key on the card dict.

**Why this comes BEFORE merging.** `_dejitter()` (`reflow.py:217-234`) only closes gaps _within_ a whisper segment (`words[j]["seg"] == words[i]["seg"]`), so a word belonging to the next utterance but emitted in the previous segment survives as its own tiny card over silence. By duration alone that is indistinguishable from a sentence-tail runt -- so Task 6's backward merge would attach it to the sentence it does **not** belong to, while satisfying every invariant. Quarantine first, or Task 6 cements the defect.

**Quarantine is not a fix.** An orphan excluded from merging and extended by Task 6 is still the wrong word over the wrong audio. It is reported separately and never counted as fixed.

- [ ] **Step 1: Write the failing test**

```python
def test_single_word_group_from_a_previous_segment_is_an_orphan():
    g = [{"text": "Wait", "start": 10.0, "end": 10.2, "prob": .9, "seg": 0}]
    nxt = [{"text": "for", "start": 12.0, "end": 12.3, "prob": .9, "seg": 1}]
    assert reflow.is_orphan_group(g, nxt) is True


def test_a_legitimate_one_word_utterance_is_not_an_orphan():
    """'Yes.' spoken alone, in its own segment, with silence both sides."""
    g = [{"text": "Yes.", "start": 10.0, "end": 10.6, "prob": .9, "seg": 3}]
    nxt = [{"text": "I", "start": 14.0, "end": 14.2, "prob": .9, "seg": 4}]
    assert reflow.is_orphan_group(g, nxt) is False


def test_orphan_flag_reaches_the_card():
    cards = reflow.reflow(_orphan_words(), _orphan_segments())
    assert any(c.get("orphan") for c in cards)
```

- [ ] **Step 2: Run and watch it fail** -> `AttributeError: is_orphan_group`

- [ ] **Step 3: Implement**

```python
ORPHAN_MAX_WORDS = 2      # the observed morphology is 1-2 words; measure before widening


def is_orphan_group(group: list[dict], nxt: list[dict] | None) -> bool:
    """A short group stranded at the END of its segment while the utterance it belongs
    to starts in the NEXT segment. _dejitter() cannot reach these because it only
    closes gaps within a segment. Conservative by design: a false positive merely
    declines a merge, a false negative cements a word into the wrong sentence."""
    if not nxt or len(group) > ORPHAN_MAX_WORDS:
        return False
    if group[-1].get("seg") == nxt[0].get("seg"):
        return False                                  # same utterance, not stranded
    lead = nxt[0]["start"] - group[-1]["end"]
    trail = group[0]["start"] - 0.0
    return lead > GAP_MAX and trail > 0 and not _text(group).rstrip().endswith(tuple(SENT_END))
```

Thread the flag onto the card in `reflow()`; record `orphan_candidates` in QC.

- [ ] **Step 4: Verify green** -- run the whole suite, the flag must not change any existing card's timing.

- [ ] **Step 5: Commit**

```bash
git add reflow.py tests/test_reflow.py
git commit -m "feat(reflow): flag cross-segment orphan groups so merging can quarantine them"
```

---

### Task 6: Backward merge (A1/A4)

**Files:**

- Modify: `reflow.py` (new `merge_runts`, called from `reflow()` before `time_cards`)
- Test: `tests/test_reflow.py`

**Interfaces:**

- Produces: `reflow.merge_runts(groups) -> (groups, list[dict])` -- merged groups plus one record per merge (`{"reason", "into", "absorbed"}`).
- Consumes: `is_short`, `card_cps`, `is_orphan_group`.

**Measured on Punk Hazard:** 730 genuine runts; merge fixes 313 (43%).

**Determinism (A4) -- two implementations must agree:**

- single left-to-right pass to a fixed point; a runt merges only into its immediate predecessor
- a predecessor that already absorbed a runt is a legal target for the next, with all four constraints re-evaluated on the merged form
- a merged group still below `MIN_DUR` is not a failure; it falls through to Task 7
- an orphan group (Task 5) never merges backward

- [ ] **Step 1: Write the failing test**

```python
CASES = [   # (gap, pred_text, runt_text, pred_dur, runt_dur, should_merge, why)
    (0.08, "It's a", "monster.",  1.0, 0.30, True,  "ordinary sentence tail"),
    (0.60, "It's a", "monster.",  1.0, 0.30, False, "gap exceeds GAP_MAX"),
    (0.08, "x" * 70, "monster.",  1.0, 0.30, False, "merged text over MAX_CHARS"),
    (0.08, "It's a", "monster.",  6.9, 0.30, False, "merged span over MAX_DUR"),
    (0.08, "a" * 30, "b" * 20,    2.0, 0.30, False, "merged cps over MAX_CPS"),
    (0.08, "Done.",  "Next.",     1.0, 0.30, True,  "sentence-integrity is a PREFERENCE"),
]

@pytest.mark.parametrize("gap,pred,runt,pd,rd,expect,why", CASES)
def test_merge_legality(gap, pred, runt, pd, rd, expect, why):
    groups = _two_groups(gap, pred, runt, pd, rd)
    out, merges = reflow.merge_runts(groups)
    assert (len(out) == 1) is expect, why


def test_merge_is_idempotent():
    g = _corpus_like_groups()
    once, _ = reflow.merge_runts(g)
    twice, m2 = reflow.merge_runts(once)
    assert twice == once and m2 == []


def test_merge_preserves_every_word_in_order():
    g = _corpus_like_groups()
    out, _ = reflow.merge_runts(g)
    assert [w["text"] for grp in out for w in grp] == [w["text"] for grp in g for w in grp]


def test_orphan_is_never_merged_backward():
    groups = _orphan_then_utterance()
    out, merges = reflow.merge_runts(groups)
    assert len(out) == 2 and merges == []


def test_two_short_groups_may_merge_and_still_be_short():
    """Both parts 0.20s -> merged 0.40s, still under MIN_DUR. Not a failure:
    Task 7 handles it. (Rejected groq A1-E1 claimed this could not happen.)"""
    out, merges = reflow.merge_runts(_two_shorts(0.20, 0.20, gap=0.05))
    assert len(out) == 1
    assert reflow.is_short(out[0][-1]["end"] - out[0][0]["start"])
```

- [ ] **Step 2: Run and watch it fail** -> `AttributeError: merge_runts`

- [ ] **Step 3: Implement**

```python
def merge_runts(groups: list[list[dict]]) -> tuple[list[list[dict]], list[dict]]:
    """Absorb a too-short group into its predecessor when the merged card would satisfy
    the whole profile. Runs at GROUP level, before time_cards(), so timings are
    re-derived rather than hand-patched. Left-to-right, single pass, fixed point."""
    out: list[list[dict]] = []
    merges: list[dict] = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if out and is_short(_dur(g)) and not is_orphan_group(g, nxt):
            p = out[-1]
            merged_text = _text(p) + " " + _text(g)
            span = g[-1]["end"] - p[0]["start"]
            if (g[0]["start"] - p[-1]["end"] <= GAP_MAX + EPS
                    and len(merged_text) <= MAX_CHARS
                    and span <= MAX_DUR + EPS
                    and card_cps(merged_text, span) <= MAX_CPS + EPS):
                out[-1] = p + g
                merges.append({"reason": "runt_backward_merge",
                               "into": id(p), "absorbed": _text(g)})
                continue
        out.append(g)
    return out, merges
```

Call it from `reflow()` between grouping and `time_cards()`.

- [ ] **Step 4: Verify green** -- `.venv/bin/python -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add reflow.py tests/test_reflow.py
git commit -m "feat(reflow): merge runt groups backward when the merged card fits the profile"
```

---

### Task 7: Forward steal with cascade (A2/A2a/A2b/A6)

**Files:**

- Modify: `reflow.py` (`time_cards`)
- Test: `tests/test_reflow.py`

**Interfaces:**

- Produces: `reflow.time_cards(groups, audio_duration=None) -> (list[(start, end)], list[dict])` -- timings plus cascade records.
- Raises: `reflow.CascadeInfeasible` when the shift cannot fit before `audio_duration`.

**The shift is NOT the extension delta (A2a).** `time_cards`'s degenerate branch sets `end = start + MIN_GAP` without consulting the successor, so a card can already end AFTER its successor starts -- **9 such pairs exist in shipped Punk Hazard output**, e.g. `'Huh.'` overlapping `"Let's be honest."` by -0.083s. Shifting by the extension delta alone reproduces the overlap. Absorb the pre-existing deficit too:

```python
required_shift = max(extension_delta,
                     card_end + MIN_GAP - successor_start,
                     0.0)
```

**Absorption order:** the successor's own surplus above `MIN_DUR` first (it simply gets shorter, its end does not move, and the cascade terminates), then the gap after it, then propagate. Measured: 80% terminate in one hop, p90 2, max 7; 489 cards (5.0%) displaced, median 0.27s, p99 1.01s, max 1.36s, 5 over 1.0s.

**Infeasibility (A2b) is strict.** No card's start may reach `audio_duration`. If the required shift would do that, raise `CascadeInfeasible`; `generate.py` writes no srt, drops a `.dubtitles.fail` marker (the existing poison-file mechanism, so `gen_loop.sh` moves on rather than retrying forever) and still writes the QC sidecar. Emitting a known-invalid subtitle and calling it "observable" is worse than stalling one episode.

- [ ] **Step 1: Write the failing test**

```python
def test_steal_absorbs_a_preexisting_overlap_not_just_the_deficit():
    """The 9 live overlaps: predecessor ends AFTER successor starts."""
    groups = _overlapping_pair(pred_end=0.083, succ_start=0.050)
    times, _ = reflow.time_cards(groups)
    for (a, b), (c, _d) in zip(times, times[1:]):
        assert c - b >= reflow.MIN_GAP - reflow.EPS


def test_surplus_successor_terminates_the_cascade_in_one_hop():
    times, records = reflow.time_cards(_runt_then_long())
    assert records[0]["hops"] == 1
    assert times[1][1] == pytest.approx(_runt_then_long()[1][-1]["end"], abs=1e-6)  # end unmoved


def test_zero_surplus_successor_propagates():
    _, records = reflow.time_cards(_runt_then_tight_chain())
    assert records[0]["hops"] > 1


def test_last_card_runt_extends_but_never_past_the_audio():
    times, _ = reflow.time_cards(_single_short_group(), audio_duration=0.5)
    assert times[-1][1] <= 0.5 + reflow.EPS


def test_infeasible_cascade_raises_rather_than_emitting_junk():
    with pytest.raises(reflow.CascadeInfeasible) as e:
        reflow.time_cards(_dense_no_slack_chain(), audio_duration=3.0)
    assert e.value.requested == pytest.approx(e.value.applied + e.value.residual, abs=1e-6)
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement** -- rewrite `time_cards` to: derive the natural timings as today (keeping `MIN_DUR`/`MAX_CPS` as floors), then run the steal pass with `required_shift`, surplus-then-gap absorption, and the `audio_duration` feasibility check. Record `requested_shift`, `applied_shift`, `residual_shift`, `hops`, `preexisting_gap_deficit` per cascade.

- [ ] **Step 4: Verify green** -- full suite.

- [ ] **Step 5: Commit**

```bash
git add reflow.py tests/test_reflow.py
git commit -m "feat(reflow): steal forward to satisfy MIN_DUR, absorbing pre-existing gap deficits"
```

---

### Task 8: Property-based whole-list invariants (A5)

**Files:**

- Create: `tests/test_reflow_properties.py`

**Interfaces:**

- Consumes: everything from Tasks 5-7.

**Why:** Tasks 6 and 7 are each table-tested in isolation, but the failure surface is their COMPOSITION -- `merge -> time -> steal -> cascade -> clamp`. Both live defects found in review were composition bugs. Use a seeded `random.Random` (stdlib -- no new dependency); no hypothesis.

- [ ] **Step 1: Write the failing test**

```python
import random, reflow

def _random_words(rng, n):
    """Words with adversarial timing: zero-length, back-to-back, tight successors."""
    ...

@pytest.mark.parametrize("seed", range(50))
def test_whole_list_invariants(seed):
    rng = random.Random(seed)
    words, segments = _random_episode(rng)
    try:
        cards = reflow.reflow(words, segments)
    except reflow.CascadeInfeasible:
        return                              # explicit, allowed failure mode
    # 1. temporal validity
    for c in cards:
        assert c["start"] < c["end"]
        assert c["end"] >= c["natural_end"] - reflow.EPS or c.get("source_timestamp_overrun")
    for a, b in zip(cards, cards[1:]):
        assert b["start"] - a["end"] >= reflow.MIN_GAP - reflow.EPS
        assert b["start"] >= a["start"]
    # 2. readability validity
    for c in cards:
        assert not reflow.is_short(c["end"] - c["start"]) or c.get("orphan") or c.get("unfixable_runt")
        assert c["end"] - c["start"] <= reflow.MAX_DUR + reflow.EPS
        assert len(c["text"].split("\n")) <= reflow.MAX_LINES
    # 3. conservation
    assert _flatten(cards) == _expected_words(words)
    # 4. causality
    for c in cards:
        assert c["start"] >= c["original_onset"] - reflow.EPS
    # 5. idempotence
    g, _ = reflow.merge_runts(_groups(words, segments))
    g2, m2 = reflow.merge_runts(g)
    assert g2 == g and m2 == []
```

- [ ] **Step 2: Run.** Expect real failures -- that is the point of this task. Fix what it finds in `reflow.py`, not in the test.

- [ ] **Step 3: Iterate to green across all 50 seeds.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_reflow_properties.py reflow.py
git commit -m "test(reflow): property-based whole-list invariants over merge+steal composition"
```

---

### Task 9: Source timing vs display timing (C6)

**Files:**

- Modify: `reflow.py` (emit `source_start`/`source_end` on each card)
- Modify: `generate.py` (persist both into `conf.json`)
- Modify: `repair.py` (`overlap_ref` selects on the SOURCE window)
- Test: `tests/test_repair.py`, `tests/test_reflow.py`

**Interfaces:**

- Produces: `conf.json` rows gain `source_start` / `source_end`.
- Consumes: `overlap_ref(ivals, c.get("source_start", c["start"]), c.get("source_end", c["end"]))` -- the fallback keeps old sidecars working.

**Why this blocks shipping A before C.** Task 7 moves a card's DISPLAY start later. `overlap_ref()` then picks the fansub reference by that moved window. The dangerous case is not a missed reference (repair simply skips) -- it is a card displaced onto its NEIGHBOUR's cue and using it as the evidence justifying a repair. `accept_repair()`'s borrow and length guards check that a repair did not _copy_ the reference, not that the reference _describes the card's audio_. A merged card carries the union of its source groups' windows.

- [ ] **Step 1: Write the failing test**

```python
def test_overlap_ref_uses_the_source_window_not_the_displaced_one():
    card = {"start": 12.0, "end": 12.9, "source_start": 10.0, "source_end": 10.9}
    ivals = [(10.0, 10.9, "the right line"), (11.9, 13.0, "the neighbour's line")]
    assert repair.overlap_ref(ivals, card["source_start"], card["source_end"]) == "the right line"


def test_missing_source_window_falls_back_to_display(): ...
def test_merged_card_source_window_is_the_union(): ...
```

- [ ] **Step 2-5:** implement, verify, commit.

```bash
git commit -m "fix(repair): anchor reference selection to source timing, not displaced display timing"
```

---

### Task 10: Post-glossary re-wrap and validate (C7)

**Files:**

- Modify: `generate.py` (after `glossary.correct`, before `conf`/srt are written)
- Test: `tests/test_generate.py`

**Context:** `generate.py:283` reflows, `:290` corrects per line. A correction changes text AFTER wrapping and timing are fixed, and nothing re-checks the profile.

**The trigger is measured invalidity, not growth.** Capping canonical growth does not bound layout risk: wrapping depends on where word boundaries fall, not total length. A length-neutral substitution can leave an 84-char card whose boundaries land at cumulative 20/40/60 -- no split with both halves <= 42, and `wrap_balance` falls through to its over-long fallback. And +2 characters on a 0.83s card adds ~2.4 cps, enough to cross 17 cps alone.

Measured today: the largest lengthening `hard_fix` in the glossary is `shojo -> Shoujou` (+2); applying `glossary.correct()` across all 10,020 cards changes 101 and **zero change length**. So no splitter is built -- an unwrappable corrected card keeps its correction (the right name beats the layout profile) and records a `layout_exception`.

- [ ] **Step 1: Write the failing test**

```python
def test_length_neutral_correction_that_breaks_wrapping_is_detected():
    """Same total length, different word boundaries -> no legal 2x42 split."""
    gloss = _gloss_with_hard_fix("aaaaaaaaaaaaaaaaaaaa", "a" * 20)   # redistributes
    ...
    assert rec.counters["layout_exceptions"] == 1
    assert written_text == corrected_text        # correction kept, not reverted


def test_two_char_growth_on_a_short_card_records_over_cps(): ...
def test_the_text_validated_is_the_text_written(): ...
```

- [ ] **Step 2-5:** implement `_revalidate_after_correction()`, verify, commit.

```bash
git commit -m "feat(generate): re-wrap and validate cards after glossary correction"
```

---

### Task 11: Duration-aware and per-line repair acceptance (C2/C4/C5)

**Files:**

- Modify: `repair.py` (`accept_repair` signature and body; secondary-check path)
- Test: `tests/test_repair.py`

**Context:** `LEN_RATIO_MAX` is 1.5, so a repair may grow a line by 50% with nothing re-checking readability -- 40 chars at 3.0s (13 cps) becomes 58 chars (19.3 cps), unnoticed. A total-only check also passes text that is visually invalid, which is how the wrapping defect survived. The secondary-model output currently bypasses validation entirely.

- [ ] **Step 1: Write the failing test**

```python
def test_repair_that_would_exceed_cps_for_this_cards_duration_is_rejected():
    assert not repair.accept_repair("a" * 40, "b" * 58, ref="", dur=3.0)

def test_repair_valid_in_total_but_unwrappable_per_line_is_rejected(): ...
def test_secondary_model_output_goes_through_the_same_gate(): ...
def test_a_name_only_repair_still_passes():   # the case repair exists for
    assert repair.accept_repair("Hi Zorro", "Hi Zoro", ref="", dur=2.0)
```

- [ ] **Step 2-5:** implement, verify, commit.

```bash
git commit -m "fix(repair): reject repairs that break the readability profile for the card's duration"
```

---

### Task 12: Possessive folding with an independently qualifying bare lane (D5)

**Files:**

- Modify: `mine_glossary.py` (`mine_text`, admission in `main`)
- Test: `tests/test_mine_glossary.py`

**Interfaces:**

- Produces: `mine_text(text, bare, poss, mid)` -- separate bare and possessive counters.

**Context.** `mine_glossary.py:100` tests `^[A-Z][a-z]{3,}$` against a core that still carries `'s`, so `Brownbeard's`, `Vegapunk's`, `Hazzard's` match nothing and are counted as neither form -- evidence split across forms and discarded.

**Do NOT add an English-dictionary gate.** 13 of 81 glossary names ARE dictionary words, including `Brook`, `Robin` and `Chopper` -- three of the nine Straw Hats -- plus `Crocodile`, `Buggy`, `Smoker`, `Shanks`, `Marco`, `Roger`. A gate would make 16% of the cast permanently unmineable.

**Possessives reinforce; they never originate.** A bare count of ONE plus two possessives must not cross the floor unattended:

```
bare_count >= MINE_MIN_COUNT                          -> auto-append (today's behaviour)
bare_count <  MINE_MIN_COUNT
  and bare + possessive >= MINE_MIN_COUNT             -> review, "possessive_floor_crossing"
```

Measured on Punk Hazard: 89 terms auto-append on bare count alone; the crossing queue holds exactly **1** (`Traffy`, bare 2 / possessive 2).

- [ ] **Step 1: Write the failing test**

```python
def test_possessives_may_not_push_a_weak_candidate_over_the_floor():
    text = "I told the Boss to wait.\nBoss's men arrived.\nBoss's ship moved."
    added, queue = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Boss" not in added
    assert queue["Boss"] == {"reason": "possessive_floor_crossing", "bare": 1, "possessive": 2}


def test_possessives_reinforce_a_term_that_already_qualifies():
    text = "Brownbeard came.\nBrownbeard left.\nBrownbeard sang.\nBrownbeard's crew fled."
    added, _ = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Brownbeard" in added


def test_a_dictionary_word_name_is_still_mineable():
    """Brook, Robin, Chopper are Straw Hats AND English words. No dictionary gate."""
    text = "Brook played.\nBrook laughed.\nBrook sang."
    added, _ = mine_glossary.mine(text, min_count=3, common=set(), existing=set())
    assert "Brook" in added


def test_curly_apostrophe_possessive_folds_too():
    assert _fold("Brownbeard" + chr(0x2019) + "s") == "Brownbeard"
```

- [ ] **Step 2-5:** implement, verify, commit.

```bash
git commit -m "feat(mine): fold possessives as reinforcing evidence, never as origination"
```

---

### Task 13: Transcript-sourced candidates (D1/D2/D3/D3a/D3b/D4)

**Files:**

- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**

- Produces: a candidate record `{variant, source, raw_forms, normalized_forms, settled_target, occurrence_count, episode_count, contexts}`.

**Context.** The miner excludes our own dubtitle track to avoid reinforcing its errors, so a release with no fansub track mines nothing -- which is how `Hazzard`(4x), `Kinamon`(2x) and `Whitestrom`(2x) shipped. Feeding our `conf.json` in is safe here because a candidate is never trusted; it is adjudicated against the wiki, and the wiki breaks the loop.

**Signal is out-of-dictionary tokens, not flagged-card text.** 36.8% of cards carry a flag and the top recurring flagged texts are the OPENING THEME LYRICS. The existing filter chain cuts 350 raw candidates to 74.

**Source asymmetry (D3).** A fansub candidate was written by a human who knew the show; a transcript candidate is Whisper guessing at audio. So:

```
fansub                            -> existing miner policy
transcript + settled_target set   -> deterministic/wiki-approved auto-apply
transcript + settled_target None  -> review queue, regardless of tier, count,
                                     or LLM adjudication confidence
```

The last line is a hard prohibition in the APPLY rule, not the tier logic: `escalate()` can currently promote a confident context adjudication to an apply.

**Split floors (D4):** `>= 2` for near-misses of a settled term, `>= 3` for new terms. The distribution runs opposite to intuition -- high counts are correct names missing from the glossary (`Momonosuke` 21x, `Brownbeard` 16x), while the ERRORS live in the tail (`Kinamon` 2x, `Whitestrom` 2x, `Hazzard` 4x).

**Harvest scope (D3b):** record the episode set the counts were taken over, or the floors are not the floors that were measured.

**A D term that creates a layout exception (Task 10) may not auto-apply** -- it goes to review. Growth over +2 characters also goes to review.

- [ ] **Step 1: Write the failing test**

```python
def test_new_transcript_term_never_auto_applies_at_any_tier(): ...
def test_near_miss_of_a_settled_term_may_auto_apply():
    # Hazzard -> Hazard, anchored to a term acquired from an independent source
def test_split_floors(): ...
def test_harvest_scope_is_recorded_with_the_counts(): ...
def test_candidate_growth_over_two_chars_goes_to_review(): ...
```

- [ ] **Step 2-5:** implement, verify, commit.

```bash
git commit -m "feat(acquire): accept transcript candidates with source-aware apply rules"
```

---

## Acceptance

Re-run One Pace S30 (Punk Hazard, 22 episodes) and assert across all `qc.json`:

```
ordinary_under_min_dur_after == 0
orphan_candidates_fixed      == 0        # quarantine is not a fix
max_displacement             <= 2.0s
every cue: <= 2 lines, each <= 42 chars  # from the muxed track, not conf.json
no adjacent pair with gap < MIN_GAP - EPS
Hazzard / Kinamon / Whitestrom appear in the acquisition output
```

Verify wrapping against the **muxed** track (`ffmpeg -map 0:s:m:title:Dubtitles -f srt -`), never `conf.json` -- conf stores flattened text and will report a false pass.

## Deliberately out of scope

The full layout compiler (correct text before group sizing); repair on no-fansub episodes (skipped targets must still be RECORDED in QC with text/timestamp/reason, so the ladder does not end in a silent drop); LLM-chosen line breaks; library-wide rollout; the 3500g relocation; reference-cue ids when a merged source window spans several fansub cues.
