# Glossary Name Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acquire proper nouns for shows whose releases ship no mineable fansub track, by proposing candidates from the show's own transcripts and letting the show's wiki own every canonical spelling.

**Architecture:** A new top-level module `glossary_acquire.py` harvests capitalised tokens from the show's existing `conf.json`/sidecar output, scores each against the cached Fandom title index, and writes `hard_fixes` only when four gates pass. Similarity is a *recall* device; the expansion guard (R2) and the dominance test (R3) carry all the safety. Every written entry is recorded in an `acquired` provenance map so a run can be reverted and so acquired names can be kept out of Whisper's `initial_prompt`.

**Tech Stack:** Python 3.11+, stdlib + `jellyfish` (already a dependency). Reuses `glossary_verify.{resolve_wiki,fetch_titles,adjudicate}` and `mine_glossary.mine_text`. `pytest` + `ruff`. No GPU, no network in tests.

**Spec:** `docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md`

## Global Constraints

- Python `>=3.11`; ruff `line-length = 130`, `select = ["E","F","I","W","UP","B"]`, `ignore = ["E701","E702"]`.
- Tests live in `tests/test_glossary_acquire.py`. `conftest.py` puts the repo root on `sys.path` — import modules directly (`import glossary_acquire`), never as a package.
- **No network and no LLM in any test.** Stub `fetch_titles`/`adjudicate` via monkeypatch.
- Any wiki or LLM failure must be a no-op that returns a report, never a raised exception. This matches `glossary_verify.verify()`'s existing contract.
- Defaults: `ACQUIRE_MIN_COUNT=3`, `ACQUIRE_MIN_SHARE=0.80`, `ACQUIRE_MIN_SIM=0.72`. All env-overridable.
- `--dry-run` is the default. Writing requires an explicit `--apply`.
- House style is terse one-liners (`if x: return`). Follow it; don't reformat neighbouring code.

---

### Task 1: Title normalisation and the comparison form

**Files:**
- Create: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_title(title: str) -> str`, `reduce_form(s: str) -> str`.

`glossary_verify._clean_title()` already exists but strips `(1999)` years and `{tvdb-…}` from *show* titles. Article titles need different treatment: `Misty (anime)` → `Misty`, `Ash Ketchum/Sun & Moon` → `Ash Ketchum`. Without this the tool would write a `hard_fix` mapping every mention of Misty to the literal string `Misty (anime)`.

`reduce_form` is the string both sides are compared on: lowercased with spaces, apostrophes and hyphens removed. This is what lets the token `Vanderdecken` match the title `Van der Decken` exactly.

- [ ] **Step 1: Write the failing test**

```python
import glossary_acquire as ga


def test_normalize_title_strips_disambiguator_and_subpage():
    assert ga.normalize_title("Misty (anime)") == "Misty"
    assert ga.normalize_title("Ash Ketchum/Sun & Moon") == "Ash Ketchum"
    assert ga.normalize_title("Satoshi (PMZ)") == "Satoshi"
    assert ga.normalize_title("Shirahoshi") == "Shirahoshi"


def test_reduce_form_drops_spacing_and_punctuation():
    assert ga.reduce_form("Van der Decken") == "vanderdecken"
    assert ga.reduce_form("Kin'emon") == "kinemon"
    assert ga.reduce_form("Portgas D. Ace") == "portgasd.ace"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'glossary_acquire'`

- [ ] **Step 3: Write the minimal implementation**

```python
#!/usr/bin/env python3
"""Acquire proper nouns for a show whose releases carry no mineable subtitle track.

mine_glossary.py can only learn names from an embedded fansub track. Where a release
ships none, the glossary for that stretch of the show stays empty and every name is left
to Whisper's guessing. This module fills that gap from the opposite direction: the show's
wiki owns the candidate list AND every canonical spelling, and the show's own transcripts
only decide which wiki entities are worth asking about. Our errors can raise a question;
they can never become an answer.

See docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md.
Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import re

_DISAMBIG_RE = re.compile(r"\s*\([^)]*\)\s*$")


def normalize_title(title: str) -> str:
    """A wiki article title reduced to the name itself.

    Fandom titles carry disambiguators and subpages -- 'Misty (anime)',
    'Ash Ketchum/Sun & Moon'. Both are part of the TITLE, not the name, and emitting one
    as a hard_fix canonical would rewrite dialogue to include it."""
    return _DISAMBIG_RE.sub("", str(title).split("/")[0]).strip()


def reduce_form(s: str) -> str:
    """The form both sides are compared on: lowercase, no spaces/apostrophes/hyphens.

    This is what lets the ASR token 'Vanderdecken' match the title 'Van der Decken'."""
    return re.sub(r"[\s'’-]", "", str(s).lower())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): wiki title normalisation and comparison form"
```

---

### Task 2: The dominance estimator

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `wilson_lower(k: int, n: int, z: float = 1.96) -> float`.

A bare ratio is the wrong estimator at small counts: 3-vs-0 and 60-vs-0 both read as infinity, and 5-vs-1 clears a 5:1 bar on almost no evidence. The Wilson score lower bound penalises small samples automatically.

- [ ] **Step 1: Write the failing test**

Note the exact expected values — they are the spec's acceptance numbers and must not drift.

```python
import pytest


@pytest.mark.parametrize("k,n,expected", [
    (56, 58, 0.883),   # Shirahoshi vs Syrahose -- applies
    (21, 37, 0.409),   # Smoker vs Smokey -- legitimate nickname, must NOT apply
    (8, 29, 0.147),    # Decken vs Deccan -- correct form is the minority, flagged
    (5, 6, 0.436),     # thin evidence clears 5:1 but must NOT apply
    (0, 12, 0.0),      # canonical never seen -- handled by the escape clause, not here
])
def test_wilson_lower_matches_spec_values(k, n, expected):
    assert ga.wilson_lower(k, n) == pytest.approx(expected, abs=0.001)


def test_wilson_lower_of_empty_cluster_is_zero():
    assert ga.wilson_lower(0, 0) == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k wilson -v`
Expected: FAIL — `AttributeError: module 'glossary_acquire' has no attribute 'wilson_lower'`

- [ ] **Step 3: Write the minimal implementation**

Add `import math` to the imports, then:

```python
def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound on k/n at ~95% confidence.

    Used instead of a bare ratio because a ratio cannot tell 5-vs-1 from 56-vs-2 -- both
    look lopsided, but only one is evidence. Wilson discounts the small sample for us."""
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k wilson -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): Wilson lower bound as the dominance estimator"
```

---

### Task 3: Harvest token counts from the show's own output

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `mine_glossary.mine_text(text, counter, midsentence)` — mutates `counter` (dict) and `midsentence` (set) in place.
- Produces: `harvest(show_dir: str) -> tuple[dict[str, int], set[str], int]` returning `(counts, midsentence, n_files)`.

This is the one place the stage reads our own output, and it is deliberate — see the spec. Prefer `<stem>.dubtitles.conf.json` (post-reflow, post-hallucination-gate text); fall back to `<stem>.eng.dubtitles.srt` where the conf is gone, since 104 of 696 stamped episodes have no conf.

- [ ] **Step 1: Write the failing test**

```python
import json


def _write_conf(tmp_path, name, texts):
    p = tmp_path / f"{name}.dubtitles.conf.json"
    p.write_text(json.dumps([{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]))
    return p


def test_harvest_counts_capitalised_tokens_and_tracks_midsentence(tmp_path):
    _write_conf(tmp_path, "Ep01", ["I saw Shirahoshi today.", "Shirahoshi ran away."])
    counts, mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts["Shirahoshi"] == 2
    assert "Shirahoshi" in mid          # mid-sentence in the first line


def test_harvest_falls_back_to_srt_when_conf_is_gone(tmp_path):
    (tmp_path / "Ep02.eng.dubtitles.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nWe fought Vergo here.\n\n")
    counts, mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts["Vergo"] == 1


def test_harvest_prefers_conf_over_srt_for_the_same_episode(tmp_path):
    _write_conf(tmp_path, "Ep03", ["Caesar laughed."])
    (tmp_path / "Ep03.eng.dubtitles.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMonet laughed.\n\n")
    counts, _mid, n = ga.harvest(str(tmp_path))
    assert n == 1
    assert counts.get("Caesar") == 1 and "Monet" not in counts
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k harvest -v`
Expected: FAIL — no attribute `harvest`

- [ ] **Step 3: Write the minimal implementation**

Add `import json`, `import os` and `import mine_glossary` to the imports, then:

```python
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def _conf_text(path: str) -> str:
    """All dialogue text from one conf.json, newline-joined, or '' if unreadable."""
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(rows, list):
        return ""
    return "\n".join(str(r.get("text", "")) for r in rows if isinstance(r, dict))


def _srt_text(path: str) -> str:
    """Dialogue lines from an SRT: drop indices and timecodes, keep the rest."""
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        out.append(s)
    return "\n".join(out)


def harvest(show_dir: str) -> tuple[dict, set, int]:
    """(counts, midsentence, n_files) of capitalised tokens across the show's own output.

    conf.json is preferred; the SRT is the fallback for episodes whose conf is gone (104 of
    696 stamped episodes at time of writing). One source per episode stem, never both."""
    counter: dict = {}
    mid: set = set()
    stems_done, files = set(), 0
    for dp, _dns, fs in os.walk(show_dir):
        for fn in sorted(fs):
            if fn.endswith(CONF_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(CONF_SUFFIX)]), _conf_text(os.path.join(dp, fn))
            elif fn.endswith(SRT_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(SRT_SUFFIX)]), _srt_text(os.path.join(dp, fn))
            else:
                continue
            if stem in stems_done or not text:
                continue
            stems_done.add(stem); files += 1
            mine_glossary.mine_text(text, counter, mid)
    return counter, mid, files
```

Note the `sorted(fs)` — `.dubtitles.conf.json` sorts before `.eng.dubtitles.srt` for the same stem, which is what makes conf win.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k harvest -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): harvest token counts from the show's own transcripts"
```

---

### Task 4: R2 — the expansion guard

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `reduce_form` (Task 1).
- Produces: `is_expansion(variant: str, canonical: str) -> bool`.

This is one of the two rules carrying the design's safety. The transcript says `Warlords` 10 times and the wiki title is `Seven Warlords of the Sea`; rewriting the word into the phrase corrupts dialogue. Same shape for `Vander` → `Vanderdecken`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("variant,canonical", [
    ("Warlords", "Seven Warlords of the Sea"),
    ("Vander", "Van der Decken"),
    ("Hoshi", "Shirahoshi"),
    ("Ace", "Portgas D. Ace"),
])
def test_is_expansion_rejects_growing_a_token_into_a_phrase(variant, canonical):
    assert ga.is_expansion(variant, canonical) is True


@pytest.mark.parametrize("variant,canonical", [
    ("Syrahose", "Shirahoshi"),
    ("Deccan", "Decken"),
    ("Brooke", "Brook"),
    ("Kinemon", "Kin'emon"),
    ("Vanderdecken", "Van der Decken"),
])
def test_is_expansion_allows_genuine_respellings(variant, canonical):
    assert ga.is_expansion(variant, canonical) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k expansion -v`
Expected: FAIL — no attribute `is_expansion`

- [ ] **Step 3: Write the minimal implementation**

```python
EXPANSION_RATIO = 1.35     # canonical this much longer than the variant is a phrase, not a respelling


def is_expansion(variant: str, canonical: str) -> bool:
    """True if 'correcting' variant->canonical would GROW a word into a longer name.

    A canonical that merely CONTAINS the variant is not a match: the transcript says
    'Warlords', the wiki title is 'Seven Warlords of the Sea', and substituting one for the
    other rewrites the line into nonsense. Length ratio catches the rest ('Ace' ->
    'Portgas D. Ace'), while a true respelling stays about the same length."""
    v, c = reduce_form(variant), reduce_form(canonical)
    if not v or not c:
        return True
    if v == c:
        return False
    if v in c and len(c) > len(v):
        return True
    return len(c) > len(v) * EXPANSION_RATIO
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k expansion -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): R2 expansion guard"
```

---

### Task 5: Scoring a token against the title index

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `normalize_title`, `reduce_form` (Task 1).
- Produces: `similarity(a: str, b: str) -> float`, `best_title(token: str, titles: list[str]) -> tuple[str, float]`.

**Read this before setting the threshold.** Measured Jaro-Winkler on every pair the design must match and every near-miss it must refuse:

| pair | JW | required |
|---|---|---|
| Syrahose / Shirahoshi | 0.755 | match |
| Deccan / Decken | 0.844 | match |
| Vander / Vanderdecken | 0.900 | reject |
| Smokey / Smoker | 0.933 | reject |
| Warlords / Warlord | 0.975 | reject |

The classes overlap completely — every true pair scores *lower* than every false one. So the threshold is a **recall floor at 0.72**, not a safety gate, and R2/R3 do the rejecting. An earlier draft used 0.88 and would have silently dropped both motivating cases.

- [ ] **Step 1: Write the failing test**

```python
def test_similarity_floor_admits_every_true_pair():
    for a, b in [("Syrahose", "Shirahoshi"), ("Deccan", "Decken"),
                 ("Hirohoshi", "Shirahoshi"), ("Brooke", "Brook"),
                 ("Kinemon", "Kin'emon"), ("Momonoske", "Momonosuke")]:
        assert ga.similarity(a, b) >= ga.MIN_SIM, f"{a}/{b} would be dropped"


def test_similarity_rejects_unrelated_names():
    assert ga.similarity("Robin", "Brook") < ga.MIN_SIM
    assert ga.similarity("Monet", "Momonosuke") < ga.MIN_SIM


def test_best_title_picks_the_closest_normalised_title():
    titles = ["Shirahoshi", "Hody Jones", "Neptune (character)", "Van der Decken"]
    name, score = ga.best_title("Syrahose", titles)
    assert name == "Shirahoshi" and score >= ga.MIN_SIM


def test_best_title_strips_the_disambiguator_from_what_it_returns():
    name, _score = ga.best_title("Neptune", ["Neptune (character)"])
    assert name == "Neptune"


def test_best_title_returns_empty_when_nothing_is_close():
    name, score = ga.best_title("Surrender", ["Shirahoshi", "Hody Jones"])
    assert name == "" and score == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "similarity or best_title" -v`
Expected: FAIL — no attribute `similarity`

- [ ] **Step 3: Write the minimal implementation**

Add `import jellyfish` to the imports, then:

```python
MIN_SIM = float(os.environ.get("ACQUIRE_MIN_SIM", "0.72"))


def similarity(a: str, b: str) -> float:
    """Jaro-Winkler on the reduced forms, nudged when a phonetic key agrees.

    RECALL, not safety. Measured on real data the true and false pairs overlap completely
    (Syrahose/Shirahoshi 0.755 sits BELOW Warlords/Warlord 0.975), so no threshold here can
    separate them and none is asked to -- R2 and R3 do the rejecting. The phonetic key is a
    bonus signal only: exact metaphone bucketing was tried and split Shirahoshi/Syrahose
    into XRHX/SRHS, dropping the case this module exists for."""
    ra, rb = reduce_form(a), reduce_form(b)
    if not ra or not rb:
        return 0.0
    score = jellyfish.jaro_winkler_similarity(ra, rb)
    if jellyfish.metaphone(ra) == jellyfish.metaphone(rb) or jellyfish.soundex(ra) == jellyfish.soundex(rb):
        score = min(1.0, score + 0.02)
    return score


def best_title(token: str, titles: list) -> tuple[str, float]:
    """(normalised title, score) of the closest title above MIN_SIM, else ('', 0.0)."""
    best, best_score = "", 0.0
    for t in titles:
        norm = normalize_title(t)
        if not norm:
            continue
        s = similarity(token, norm)
        if s > best_score:
            best, best_score = norm, s
    return (best, best_score) if best_score >= MIN_SIM else ("", 0.0)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "similarity or best_title" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): title scoring with a measured recall floor"
```

---

### Task 6: The decision — all four gates

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `wilson_lower` (Task 2), `is_expansion` (Task 4).
- Produces: `decide(variant, variant_count, canonical, canonical_count, score, midsentence: bool) -> dict` returning `{"verdict": "apply"|"flag", "reason": str, "bound": float}`.

**The escape clause carries the real cases.** Whisper produced `Kinemon` 12 times and `Kin'emon` zero, so the Wilson bound is 0.000 — it applies only because the canonical never appears at all. An implementation that checks `wilson > MIN_SHARE` alone fails the acceptance test.

- [ ] **Step 1: Write the failing test**

```python
def test_decide_applies_a_lopsided_mishearing():
    d = ga.decide("Syrahose", 2, "Shirahoshi", 56, 0.755, True)
    assert d["verdict"] == "apply" and d["bound"] == pytest.approx(0.883, abs=0.001)


def test_decide_applies_when_the_canonical_never_appears():
    # Whisper said 'Kinemon' 12x and 'Kin'emon' never. Wilson is 0.0; the escape clause carries it.
    d = ga.decide("Kinemon", 12, "Kin'emon", 0, 0.90, True)
    assert d["verdict"] == "apply" and d["reason"] == "canonical-unseen"


def test_decide_flags_a_legitimate_nickname():
    d = ga.decide("Smokey", 16, "Smoker", 21, 0.933, True)
    assert d["verdict"] == "flag" and d["reason"] == "share-too-close"


def test_decide_flags_when_the_correct_form_is_the_minority():
    # Deccan 21 vs Decken 8 -- motivates the spec but is NOT auto-fixable; same shape as Smokey.
    d = ga.decide("Deccan", 21, "Decken", 8, 0.844, True)
    assert d["verdict"] == "flag" and d["reason"] == "share-too-close"


def test_decide_flags_an_expansion():
    d = ga.decide("Warlords", 10, "Seven Warlords of the Sea", 0, 0.80, True)
    assert d["verdict"] == "flag" and d["reason"] == "would-expand"


def test_decide_flags_below_the_frequency_floor():
    d = ga.decide("Vergo", 2, "Vergo", 0, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "below-floor"


def test_decide_flags_a_token_never_seen_mid_sentence():
    d = ga.decide("Surrender", 22, "Surrender", 0, 1.0, False)
    assert d["verdict"] == "flag" and d["reason"] == "sentence-initial-only"


def test_decide_is_a_noop_when_variant_already_equals_canonical():
    d = ga.decide("Shirahoshi", 56, "Shirahoshi", 56, 1.0, True)
    assert d["verdict"] == "flag" and d["reason"] == "already-canonical"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k decide -v`
Expected: FAIL — no attribute `decide`

- [ ] **Step 3: Write the minimal implementation**

```python
MIN_COUNT = int(os.environ.get("ACQUIRE_MIN_COUNT", "3"))
MIN_SHARE = float(os.environ.get("ACQUIRE_MIN_SHARE", "0.80"))


def decide(variant: str, variant_count: int, canonical: str, canonical_count: int,
           score: float, midsentence: bool) -> dict:
    """Run the four gates over one variant->canonical proposal.

    Order matters: the cheap structural rejections come first so the report's reason is the
    most specific true one. R2 (expansion) and R3 (dominance) are the only gates carrying
    real safety -- `score` is a recall floor that has already been applied upstream."""
    if reduce_form(variant) == reduce_form(canonical):
        return {"verdict": "flag", "reason": "already-canonical", "bound": 0.0}
    if variant_count < MIN_COUNT:
        return {"verdict": "flag", "reason": "below-floor", "bound": 0.0}
    if not midsentence:
        return {"verdict": "flag", "reason": "sentence-initial-only", "bound": 0.0}
    if is_expansion(variant, canonical):
        return {"verdict": "flag", "reason": "would-expand", "bound": 0.0}
    if canonical_count == 0:
        # Nothing competes with it: Whisper never once produced the right spelling, so there
        # is no rival reading to be wrong about. This branch carries most real fixes.
        return {"verdict": "apply", "reason": "canonical-unseen", "bound": 0.0}
    bound = wilson_lower(canonical_count, canonical_count + variant_count)
    if bound > MIN_SHARE:
        return {"verdict": "apply", "reason": "dominant", "bound": bound}
    return {"verdict": "flag", "reason": "share-too-close", "bound": bound}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k decide -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): the four safety gates"
```

---

### Task 7: Proposing fixes for a whole show

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `best_title` (Task 5), `decide` (Task 6).
- Produces: `propose(counts: dict, midsentence: set, titles: list) -> list[dict]`, each proposal `{"variant","canonical","variant_count","canonical_count","score","verdict","reason","bound"}`.

Clusters are not built up front — they *emerge* as the set of tokens resolving to the same title. The canonical's own count is how often that exact spelling appears in the transcripts, which is the input R3 needs.

- [ ] **Step 1: Write the failing test**

```python
def test_propose_emits_one_proposal_per_variant_with_the_canonical_count(monkeypatch):
    titles = ["Shirahoshi", "Hody Jones"]
    counts = {"Shirahoshi": 56, "Syrahose": 2, "Hirohoshi": 1, "Hody": 9}
    mid = {"Shirahoshi", "Syrahose", "Hirohoshi", "Hody"}
    props = ga.propose(counts, mid, titles)
    by_variant = {p["variant"]: p for p in props}
    assert by_variant["Syrahose"]["canonical"] == "Shirahoshi"
    assert by_variant["Syrahose"]["canonical_count"] == 56
    assert by_variant["Syrahose"]["verdict"] == "apply"
    # Hirohoshi is real but appears once -- under the floor, so flagged not applied.
    assert by_variant["Hirohoshi"]["verdict"] == "flag"
    assert by_variant["Hirohoshi"]["reason"] == "below-floor"


def test_propose_ignores_tokens_that_match_no_title():
    props = ga.propose({"Surrender": 22, "Maybe": 20}, {"Surrender", "Maybe"}, ["Shirahoshi"])
    assert props == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k propose -v`
Expected: FAIL — no attribute `propose`

- [ ] **Step 3: Write the minimal implementation**

```python
def propose(counts: dict, midsentence: set, titles: list) -> list:
    """One proposal per harvested token that resolves to a wiki title.

    A token matching no title yields nothing here -- it is the tier-B queue's business
    (see acquire()), not a silent drop."""
    resolved = {}
    for tok in counts:
        name, score = best_title(tok, titles)
        if name:
            resolved[tok] = (name, score)
    out = []
    for tok, (canon, score) in sorted(resolved.items()):
        canon_count = counts.get(canon, 0)
        d = decide(tok, counts[tok], canon, canon_count, score, tok in midsentence)
        if d["reason"] == "already-canonical":
            continue
        out.append({"variant": tok, "canonical": canon, "variant_count": counts[tok],
                    "canonical_count": canon_count, "score": round(score, 3), **d})
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k propose -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): per-show proposal pass"
```

---

### Task 8: Applying proposals with provenance

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `propose` output (Task 7).
- Produces: `apply_proposals(gloss: dict, proposals: list, run_id: str) -> dict` — pure, deep-copies like `glossary_verify.apply_results` does.

Provenance is what makes `--revert` possible and what keeps acquired names out of `initial_prompt`. Both are required mitigations for the self-read loop: a wrong entry that reached `initial_prompt` would bias Whisper toward emitting it, raising its count and strengthening the very dominance test that admitted it.

- [ ] **Step 1: Write the failing test**

```python
def test_apply_proposals_writes_hard_fixes_and_provenance():
    gloss = {"show": "One Pace", "names": ["Luffy"], "hard_fixes": {"zolo": "Zoro"}}
    props = [{"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2,
              "canonical_count": 56, "score": 0.755, "verdict": "apply",
              "reason": "dominant", "bound": 0.883}]
    g = ga.apply_proposals(gloss, props, run_id="run1")
    assert g["hard_fixes"]["Syrahose"] == "Shirahoshi"
    assert g["hard_fixes"]["zolo"] == "Zoro"          # curated entries preserved
    assert g["acquired"]["Syrahose"]["canonical"] == "Shirahoshi"
    assert g["acquired"]["Syrahose"]["run"] == "run1"
    assert gloss.get("acquired") is None               # input not mutated


def test_apply_proposals_records_flagged_with_its_reason():
    props = [{"variant": "Smokey", "canonical": "Smoker", "variant_count": 16,
              "canonical_count": 21, "score": 0.933, "verdict": "flag",
              "reason": "share-too-close", "bound": 0.409}]
    g = ga.apply_proposals({"show": "One Pace"}, props, run_id="run1")
    assert "Smokey" not in g.get("hard_fixes", {})
    assert g["flagged"]["Smokey"] == "share-too-close"


def test_apply_proposals_never_adds_acquired_names_to_the_initial_prompt():
    gloss = {"show": "One Pace", "names": ["Luffy"], "initial_prompt": "Spell names correctly: Luffy."}
    props = [{"variant": "Syrahose", "canonical": "Shirahoshi", "variant_count": 2,
              "canonical_count": 56, "score": 0.755, "verdict": "apply",
              "reason": "dominant", "bound": 0.883}]
    g = ga.apply_proposals(gloss, props, run_id="run1")
    assert "Shirahoshi" not in g["initial_prompt"]
    assert "Shirahoshi" not in g["names"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k apply_proposals -v`
Expected: FAIL — no attribute `apply_proposals`

- [ ] **Step 3: Write the minimal implementation**

```python
def apply_proposals(gloss: dict, proposals: list, run_id: str) -> dict:
    """Write applied proposals into hard_fixes + acquired; record the rest in flagged.

    Pure: deep-copies its input the way glossary_verify.apply_results does, so curated
    hard_fixes, names and initial_prompt survive untouched.

    Acquired canonicals deliberately do NOT join `names`, and therefore never reach the
    regenerated initial_prompt. That is the cut that keeps a wrong entry from biasing the
    next transcription into producing more of the same spelling -- which would raise its
    count and reinforce the dominance test that let it in."""
    g = json.loads(json.dumps(gloss))
    fixes = g.setdefault("hard_fixes", {})
    acquired = g.setdefault("acquired", {})
    flagged = g.setdefault("flagged", {})
    for p in proposals:
        if p["verdict"] != "apply":
            flagged[p["variant"]] = p["reason"]
            continue
        fixes[p["variant"]] = p["canonical"]
        acquired[p["variant"]] = {"canonical": p["canonical"], "count": p["variant_count"],
                                  "canonical_count": p["canonical_count"],
                                  "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                                  "reason": p["reason"], "run": run_id}
    if not flagged:
        g.pop("flagged", None)
    return g
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k apply_proposals -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): apply with provenance, excluded from initial_prompt"
```

---

### Task 9: Revert

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: the `acquired` map written by Task 8.
- Produces: `revert(gloss: dict, run_id: str | None = None) -> dict`.

Without a way back out, a bad run is permanent — the glossary is additive and nothing prunes it.

- [ ] **Step 1: Write the failing test**

```python
def test_revert_removes_only_acquired_entries():
    gloss = {"hard_fixes": {"zolo": "Zoro", "Syrahose": "Shirahoshi"},
             "acquired": {"Syrahose": {"canonical": "Shirahoshi", "run": "run1"}}}
    g = ga.revert(gloss)
    assert g["hard_fixes"] == {"zolo": "Zoro"}
    assert g.get("acquired", {}) == {}


def test_revert_can_target_a_single_run():
    gloss = {"hard_fixes": {"a": "A", "b": "B"},
             "acquired": {"a": {"canonical": "A", "run": "run1"},
                          "b": {"canonical": "B", "run": "run2"}}}
    g = ga.revert(gloss, run_id="run1")
    assert g["hard_fixes"] == {"b": "B"}
    assert list(g["acquired"]) == ["b"]


def test_revert_leaves_a_hard_fix_a_human_has_since_changed():
    gloss = {"hard_fixes": {"Syrahose": "SomethingElse"},
             "acquired": {"Syrahose": {"canonical": "Shirahoshi", "run": "run1"}}}
    g = ga.revert(gloss)
    assert g["hard_fixes"]["Syrahose"] == "SomethingElse"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k revert -v`
Expected: FAIL — no attribute `revert`

- [ ] **Step 3: Write the minimal implementation**

```python
def revert(gloss: dict, run_id: str | None = None) -> dict:
    """Remove hard_fixes this module wrote, restoring the pre-acquisition glossary.

    A fix whose current value no longer matches what we recorded has been edited by hand
    since; leave it alone and drop only our provenance for it."""
    g = json.loads(json.dumps(gloss))
    fixes, acquired = g.get("hard_fixes", {}), g.get("acquired", {})
    for variant, meta in list(acquired.items()):
        if run_id is not None and meta.get("run") != run_id:
            continue
        if fixes.get(variant) == meta.get("canonical"):
            fixes.pop(variant, None)
        acquired.pop(variant, None)
    return g
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k revert -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): --revert path via acquired provenance"
```

---

### Task 10: Orchestration, tier B, and the CLI

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `glossary_verify.resolve_wiki(title, override) -> str | None`, `glossary_verify.fetch_titles(wiki_api, show_key) -> list[str]`, `glossary_verify.adjudicate(term, cands, show) -> {"canonical","confidence","dub_note"}`, `glossary.load(path) -> dict`, and Tasks 3/7/8.
- Produces: `acquire(gloss_path: str, show_dir: str, apply: bool = False, override: str | None = None) -> dict`, and `main()`.

**Tier B is not an appeal court.** The LLM fallback runs only for a frequent token that matched *no* title. A token that matched a title and then failed R2 or R3 is flagged — escalating it would make a model the override for the only two rules carrying the design's safety.

- [ ] **Step 1: Write the failing test**

```python
def test_acquire_is_a_noop_when_the_wiki_cannot_be_resolved(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: None)
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["note"] == "wiki unresolved"
    assert json.loads(gp.read_text()) == {"show": "One Pace"}


def test_acquire_dry_run_does_not_write(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["I fear Syrahose.", "Syrahose again.", "Syrahose thrice.",
                                   "Shirahoshi is safe."] * 20)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["applied"] == 1
    assert json.loads(gp.read_text()) == {"show": "One Pace"}   # untouched


def test_acquire_never_escalates_a_gate_failure_to_the_llm(tmp_path, monkeypatch):
    calls = []
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["Hey Smokey.", "Smokey again.", "Smokey thrice.",
                                   "Smoker is here.", "Smoker again.", "Smoker thrice.",
                                   "Smoker once more."] * 6)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Smoker"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: calls.append(a) or {"canonical": "", "confidence": "none", "dub_note": ""})
    rep = ga.acquire(str(gp), str(tmp_path), apply=True)
    assert rep["applied"] == 0
    assert calls == []      # matched a title then failed R3 -> flagged, never adjudicated
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k acquire -v`
Expected: FAIL — no attribute `acquire`

- [ ] **Step 3: Write the minimal implementation**

Add `import argparse`, `import glossary`, `import glossary_verify` and `from common import log` to the imports, then:

```python
def acquire(gloss_path: str, show_dir: str, apply: bool = False, override: str | None = None) -> dict:
    """Harvest -> score -> gate -> (optionally) write. Returns a report; never raises.

    Resilient by the same contract as glossary_verify.verify(): any wiki, LLM or IO failure
    leaves the glossary untouched and is reported, not raised."""
    try:
        gloss = json.load(open(gloss_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"note": f"load-failed: {e}"}
    show = gloss.get("show") or os.path.basename(gloss_path)[:-5]
    counts, mid, files = harvest(show_dir)
    if not counts:
        return {"show": show, "note": "nothing harvested", "files": files}
    api = glossary_verify.resolve_wiki(show, override or gloss.get("wiki"))
    if not api:
        return {"show": show, "note": "wiki unresolved", "files": files}
    titles = glossary_verify.fetch_titles(api, show)
    if not titles:
        return {"show": show, "wiki": api, "note": "no titles fetched", "files": files}
    proposals = propose(counts, mid, titles)
    applied = [p for p in proposals if p["verdict"] == "apply"]
    run_id = f"{show}:{len(titles)}:{files}"
    if apply and proposals:
        try:
            json.dump(apply_proposals(gloss, proposals, run_id), open(gloss_path, "w"),
                      indent=2, ensure_ascii=False)
        except OSError as e:
            return {"show": show, "wiki": api, "note": f"write-failed: {e}"}
    return {"show": show, "wiki": api, "files": files, "titles": len(titles),
            "proposed": len(proposals), "applied": len(applied),
            "flagged": len(proposals) - len(applied), "dry_run": not apply,
            "proposals": proposals}


def main():
    ap = argparse.ArgumentParser(description="Acquire proper nouns from a show's own output + its wiki.")
    ap.add_argument("glossary", help="path to <show>.json")
    ap.add_argument("show_dir", help="the show's media directory")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--wiki", default=None, help="override the wiki API base")
    ap.add_argument("--revert", action="store_true", help="undo previously acquired fixes and exit")
    a = ap.parse_args()
    if a.revert:
        g = json.load(open(a.glossary, encoding="utf-8"))
        out = revert(g)
        if a.apply:
            json.dump(out, open(a.glossary, "w"), indent=2, ensure_ascii=False)
        log(json.dumps({"reverted": len(g.get("acquired", {})), "written": a.apply}))
        return
    rep = acquire(a.glossary, a.show_dir, apply=a.apply, override=a.wiki)
    for p in rep.get("proposals", []):
        log(f"{p['verdict']:5} {p['variant']:18} -> {p['canonical']:22} "
            f"seen {p['variant_count']:4}/{p['canonical_count']:<4} sim {p['score']:.3f} "
            f"bound {p.get('bound', 0.0):.3f}  {p['reason']}")
    log(json.dumps({k: v for k, v in rep.items() if k != "proposals"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

Tier B is intentionally *not* wired in this task — `propose()` drops no-title tokens, and `acquire()` reports them only via `proposed` counts. Wiring the `list=search` fallback is Task 11.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k acquire -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): orchestration + CLI, dry-run by default"
```

---

### Task 11: Tier B — the unmatched-cluster queue

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `glossary_verify.adjudicate` (signature above), `glossary_verify.candidates(term, titles, k) -> list[str]`.
- Produces: `unmatched(counts: dict, midsentence: set, titles: list) -> list[str]`, and `acquire()` gains a `tier_b` report key.

A frequent token matching no title is the dub-only-name case (`Ash` on a romaji-titled wiki). It goes to the LLM *and* into `flagged` as `no-wiki-match` regardless of outcome, so a human still sees it.

- [ ] **Step 1: Write the failing test**

```python
def test_unmatched_lists_frequent_tokens_with_no_title_match():
    counts = {"Shirahoshi": 56, "Zunesha": 7, "Maybe": 20}
    mid = {"Shirahoshi", "Zunesha", "Maybe"}
    out = ga.unmatched(counts, mid, ["Shirahoshi", "Maybe"])
    assert out == ["Zunesha"]


def test_unmatched_respects_the_frequency_floor():
    assert ga.unmatched({"Zunesha": 2}, {"Zunesha"}, ["Shirahoshi"]) == []


def test_acquire_reports_tier_b_adjudications(tmp_path, monkeypatch):
    gp = tmp_path / "One Pace.json"
    gp.write_text(json.dumps({"show": "One Pace"}))
    _write_conf(tmp_path, "Ep01", ["Zunesha walks.", "Zunesha again.", "Zunesha thrice."] * 3)
    monkeypatch.setattr(ga.glossary_verify, "resolve_wiki", lambda *a, **k: "https://x/api.php")
    monkeypatch.setattr(ga.glossary_verify, "fetch_titles", lambda *a, **k: ["Shirahoshi"])
    monkeypatch.setattr(ga.glossary_verify, "adjudicate",
                        lambda *a, **k: {"canonical": "Zunisha", "confidence": "high", "dub_note": "dub"})
    rep = ga.acquire(str(gp), str(tmp_path), apply=False)
    assert rep["tier_b"] == {"Zunesha": "Zunisha"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "unmatched or tier_b" -v`
Expected: FAIL — no attribute `unmatched`

- [ ] **Step 3: Write the minimal implementation**

```python
def unmatched(counts: dict, midsentence: set, titles: list) -> list:
    """Frequent, mid-sentence tokens that resolved to no wiki title at all.

    This is the dub-only-name queue: a character the dub renamed outright ('Ash' where the
    wiki is titled in romaji) matches nothing phonetically, which is a MISS, never a
    corruption. Tier B asks the wiki's full-text search about these."""
    return sorted(t for t, c in counts.items()
                  if c >= MIN_COUNT and t in midsentence and not best_title(t, titles)[0])
```

In `acquire()`, after computing `proposals` and before the `apply` block, insert:

```python
    tier_b = {}
    for term in unmatched(counts, mid, titles):
        try:
            adj = glossary_verify.adjudicate(term, glossary_verify.candidates(term, titles), show)
        except Exception as e:
            log("acquire: adjudicate failed:", term, e); continue
        if adj.get("confidence") == "high" and adj.get("canonical"):
            tier_b[term] = adj["canonical"]
```

and add `"tier_b": tier_b` to the returned report dict.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: PASS (whole file)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): tier-B queue for tokens matching no wiki title"
```

---

### Task 12: Pin the substitution semantics this design depends on

**Files:**
- Modify: `tests/test_glossary.py`

**Interfaces:**
- Consumes: `glossary.correct(text, gloss) -> tuple[str, int]`, `glossary.load_dict(cfg) -> dict`.
- Produces: nothing — a regression guard.

`correct()` splits on whitespace and fixes per token, so a `hard_fix` for `Hoshi` cannot fire inside `Shirahoshi`. Nothing currently pins that. If a future refactor made it a substring replace, this module would start corrupting dialogue library-wide and every test here would still pass.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_glossary.py`:

```python
def test_hard_fix_never_fires_inside_a_longer_token():
    """glossary_acquire writes short variants as hard_fixes; token-level substitution is
    what keeps 'Hoshi' from rewriting the middle of 'Shirahoshi'."""
    g = glossary.load_dict({"names": [], "hard_fixes": {"hoshi": "Hoshi"}})
    out, n = glossary.correct("Shirahoshi met Hoshi", g)
    assert out == "Shirahoshi met Hoshi"
    assert "ShiraHoshi" not in out
```

- [ ] **Step 2: Run the test to verify it passes for the right reason**

Run: `.venv/bin/python -m pytest tests/test_glossary.py -k longer_token -v`
Expected: PASS. This one guards existing behaviour, so confirm it fails when broken: temporarily change `correct()`'s token loop to `text.replace(key, val)`, re-run, see it FAIL, then revert.

- [ ] **Step 3: Commit**

```bash
git add tests/test_glossary.py
git commit -m "test(glossary): pin token-boundary substitution acquire relies on"
```

---

### Task 13: Tier 0 — an expansion match is a KNOWN short form, not a failure

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `decide` (Task 6), `apply_proposals` (Task 8).
- Produces: `decide` gains verdict `"known"`; `apply_proposals` writes a `known` list.

Forty terms sit unread in the live `flagged` queues and nearly all are correct: `Yuji`,
`Megumi`, `Gojo`, `Izuku`, `Deku`, `Loid`, `Anya`, `Shinra`. They are `no-match` only
because the wiki titles characters by full name. `Yuji` ⊂ `Yuji Itadori` is structurally
the same relationship as `Warlords` ⊂ `Seven Warlords of the Sea`, and in both cases the
correct action is identical — leave the text alone. So every expansion match is recorded as
**known**: not fixed, and never flagged again.

- [ ] **Step 1: Write the failing test**

```python
def test_decide_marks_a_short_form_of_a_title_as_known():
    d = ga.decide("Yuji", 40, "Yuji Itadori", 0, 0.80, True)
    assert d["verdict"] == "known" and d["reason"] == "short-form"


def test_decide_marks_a_phrase_component_as_known_too():
    # Same relationship as Yuji/Yuji Itadori -- leave the dialogue alone either way.
    d = ga.decide("Warlords", 10, "Seven Warlords of the Sea", 0, 0.80, True)
    assert d["verdict"] == "known" and d["reason"] == "short-form"


def test_apply_proposals_records_known_and_never_flags_it():
    props = [{"variant": "Yuji", "canonical": "Yuji Itadori", "variant_count": 40,
              "canonical_count": 0, "score": 0.8, "verdict": "known",
              "reason": "short-form", "bound": 0.0}]
    g = ga.apply_proposals({"show": "JJK"}, props, run_id="run1")
    assert g["known"] == ["Yuji"]
    assert "Yuji" not in g.get("flagged", {})
    assert "Yuji" not in g.get("hard_fixes", {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "known or short_form" -v`
Expected: FAIL — `decide` returns `{"verdict": "flag", "reason": "would-expand"}`

- [ ] **Step 3: Change the expansion branch in `decide()`**

Replace the `is_expansion` branch:

```python
    if is_expansion(variant, canonical):
        return {"verdict": "known", "reason": "short-form", "bound": 0.0}
```

and in `apply_proposals()`, before the `if p["verdict"] != "apply"` check:

```python
        if p["verdict"] == "known":
            known.add(p["variant"]); continue
```

declaring `known = set(g.get("known", []))` beside the other setdefaults, and writing
`g["known"] = sorted(known)` before the return (dropping the key when empty).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: PASS (whole file — the old `would-expand` assertion in Task 6 must be updated to
expect `known`/`short-form`; that is the intended change, not a regression)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): tier 0 - expansion matches are known short forms"
```

---

### Task 14: Sample real context lines

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `harvest`'s file walk (Task 3).
- Produces: `context_lines(show_dir: str, tokens: list, limit: int = CONTEXT_LINES) -> dict[str, list[str]]`.

Both the LLM tier and the human tier need the same thing: the actual lines a spelling
appears in. `"Hey Smokey."` next to `"Smoker is here."` decides the case that frequency
cannot.

- [ ] **Step 1: Write the failing test**

```python
def test_context_lines_returns_real_lines_per_token(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Hey Smokey.", "Smoker is here.", "Nothing relevant."])
    ctx = ga.context_lines(str(tmp_path), ["Smokey", "Smoker"])
    assert ctx["Smokey"] == ["Hey Smokey."]
    assert ctx["Smoker"] == ["Smoker is here."]


def test_context_lines_caps_at_the_limit(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Smokey one.", "Smokey two.", "Smokey three."])
    ctx = ga.context_lines(str(tmp_path), ["Smokey"], limit=2)
    assert len(ctx["Smokey"]) == 2


def test_context_lines_matches_whole_words_only(tmp_path):
    _write_conf(tmp_path, "Ep01", ["Shirahoshi waited."])
    ctx = ga.context_lines(str(tmp_path), ["Hoshi"])
    assert ctx["Hoshi"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k context -v`
Expected: FAIL — no attribute `context_lines`

- [ ] **Step 3: Write the minimal implementation**

```python
CONTEXT_LINES = int(os.environ.get("ACQUIRE_CONTEXT_LINES", "4"))


def context_lines(show_dir: str, tokens: list, limit: int = CONTEXT_LINES) -> dict:
    """Up to `limit` real transcript lines containing each token, whole-word matched.

    Whole-word is required: 'Hoshi' must not match inside 'Shirahoshi', or the evidence
    shown to the model (and to the human) would be about a different name."""
    pats = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in tokens}
    out: dict = {t: [] for t in tokens}
    stems_done = set()
    for dp, _dns, fs in os.walk(show_dir):
        for fn in sorted(fs):
            if fn.endswith(CONF_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(CONF_SUFFIX)]), _conf_text(os.path.join(dp, fn))
            elif fn.endswith(SRT_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(SRT_SUFFIX)]), _srt_text(os.path.join(dp, fn))
            else:
                continue
            if stem in stems_done or not text:
                continue
            stems_done.add(stem)
            for ln in text.splitlines():
                for t, pat in pats.items():
                    if len(out[t]) < limit and pat.search(ln):
                        out[t].append(ln.strip())
            if all(len(v) >= limit for v in out.values()):
                return out
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k context -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): sample real context lines per token"
```

---

### Task 15: Tier C — contextual adjudication

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `context_lines` (Task 14), `common.llm_chat` (same kwargs `glossary_verify.adjudicate` uses).
- Produces: `build_merge_prompt(variant, canonical, ctx_v, ctx_c, show) -> str`, `adjudicate_merge(...) -> dict` returning `{"same_entity": bool, "confidence": "high"|"low"|"none"}`.

R3 cannot separate a consistent mishearing (`Deccan`/`Decken`, bound 0.147) from a name the
dub says two ways (`Smokey`/`Smoker`, 0.409). The surrounding lines can.

**Escalation rule — enforce it in code, not by convention:** only a `share-too-close`
verdict reaches this tier. `would-expand` never does, because expansion is structurally
wrong and no evidence redeems it.

- [ ] **Step 1: Write the failing test**

```python
def test_build_merge_prompt_quotes_both_sets_of_lines():
    pr = ga.build_merge_prompt("Deccan", "Decken", ["after Deccan."], ["Van Der Decken is coming."], "One Pace")
    assert "after Deccan." in pr and "Van Der Decken is coming." in pr
    assert "One Pace" in pr


def test_adjudicate_merge_parses_a_merge_verdict(monkeypatch):
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: '{"same_entity": true, "confidence": "high"}')
    out = ga.adjudicate_merge("Deccan", "Decken", ["x"], ["y"], "One Pace")
    assert out == {"same_entity": True, "confidence": "high"}


def test_adjudicate_merge_is_a_noop_when_the_llm_is_down(monkeypatch):
    monkeypatch.setattr(ga, "llm_chat", lambda *a, **k: "")
    assert ga.adjudicate_merge("a", "b", ["x"], ["y"], "S") == {"same_entity": False, "confidence": "none"}


def test_tier_c_runs_only_for_share_too_close(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ga, "adjudicate_merge",
                        lambda v, c, cv, cc, s: seen.append(v) or {"same_entity": True, "confidence": "high"})
    props = [{"variant": "Deccan", "canonical": "Decken", "variant_count": 21, "canonical_count": 8,
              "score": 0.844, "verdict": "flag", "reason": "share-too-close", "bound": 0.147},
             {"variant": "Warlords", "canonical": "Seven Warlords of the Sea", "variant_count": 10,
              "canonical_count": 0, "score": 0.8, "verdict": "known", "reason": "short-form", "bound": 0.0}]
    out = ga.escalate(props, {"Deccan": ["after Deccan."], "Decken": ["Van Der Decken."]}, "One Pace")
    assert seen == ["Deccan"]                       # the short-form case never escalates
    assert out[0]["verdict"] == "apply" and out[0]["reason"] == "context-merged"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "merge or tier_c" -v`
Expected: FAIL — no attribute `build_merge_prompt`

- [ ] **Step 3: Write the minimal implementation**

Change the import to `from common import llm_chat, log` (so the test can monkeypatch
`ga.llm_chat`), then:

```python
def build_merge_prompt(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> str:
    """Ask whether two spellings are one entity mis-transcribed or two legitimate forms.

    The model never supplies a spelling -- it answers yes/no about merging. The canonical
    string is already fixed by the wiki, which is what keeps R1 intact at this tier."""
    lines_v = "\n".join(f"  - {ln}" for ln in ctx_v) or "  (none)"
    lines_c = "\n".join(f"  - {ln}" for ln in ctx_c) or "  (none)"
    return (
        f"Two spellings appear in the English dub of {show}. Decide whether they are the SAME "
        f"name mis-transcribed, or two DIFFERENT legitimate forms (a nickname, a title, or a "
        f"separate character).\n\n"
        f'Spelling A: "{variant}"\n{lines_v}\n\n'
        f'Spelling B: "{canonical}"\n{lines_c}\n\n'
        f"A nickname the characters actually use is NOT a mis-transcription.\n"
        f'Answer with JSON only: {{"same_entity": true|false, "confidence": "high"|"low"}}\n')


def adjudicate_merge(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> dict:
    """LLM merge decision -> {'same_entity': bool, 'confidence': 'high'|'low'|'none'}."""
    none = {"same_entity": False, "confidence": "none"}
    try:
        out = llm_chat(build_merge_prompt(variant, canonical, ctx_v, ctx_c, show),
                       backend=glossary_verify.VERIFY_BACKEND, ollama_url=glossary_verify.OLLAMA,
                       llamacpp_url=glossary_verify.VERIFY_LLAMACPP_URL,
                       model=glossary_verify.VERIFY_MODEL,
                       max_tokens=glossary_verify.VERIFY_MAX_TOKENS, first_line=False)
    except Exception as e:
        log("acquire: merge adjudication failed:", variant, e); return none
    if not out:
        return none
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return none
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return none
    conf = str(d.get("confidence", "none")).lower()
    return {"same_entity": bool(d.get("same_entity")),
            "confidence": conf if conf in ("high", "low", "none") else "low"}


def escalate(proposals: list, ctx: dict, show: str) -> list:
    """Re-decide share-too-close proposals with context. Other verdicts pass through.

    ONLY share-too-close escalates. would-expand/short-form never does: expansion is
    structurally wrong and no amount of evidence makes it right."""
    out = []
    for p in proposals:
        if p.get("reason") != "share-too-close":
            out.append(p); continue
        adj = adjudicate_merge(p["variant"], p["canonical"],
                               ctx.get(p["variant"], []), ctx.get(p["canonical"], []), show)
        if adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "apply", "reason": "context-merged"})
        elif not adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "known", "reason": "context-distinct"})
        else:
            out.append(p)
    return out
```

Then wire it into `acquire()`: after `proposals = propose(...)`, insert

```python
    close = [p for p in proposals if p.get("reason") == "share-too-close"]
    if close:
        toks = sorted({p["variant"] for p in close} | {p["canonical"] for p in close})
        proposals = escalate(proposals, context_lines(show_dir, toks), show)
```

and recompute `applied` from the escalated list.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: PASS (whole file)

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): tier C - contextual merge adjudication"
```

---

### Task 16: `--review` — the human tier

**Files:**
- Modify: `glossary_acquire.py`
- Test: `tests/test_glossary_acquire.py`

**Interfaces:**
- Consumes: `context_lines` (Task 14), the `flagged` object form.
- Produces: `review_items(gloss: dict) -> list[dict]`, `record_decision(gloss, term, accept: bool) -> dict`, and a `--review` branch in `main()`.

`flagged` entries become objects carrying everything a decision needs, so the roadmap's Web
UI editor can render the same queue without re-deriving anything. Bare-string entries
written by `glossary_verify` still load.

- [ ] **Step 1: Write the failing test**

```python
def test_review_items_normalises_legacy_string_entries():
    gloss = {"flagged": {"Yuji": "no-match",
                         "Deccan": {"reason": "share-too-close", "canonical": "Decken",
                                    "context": ["after Deccan."]}}}
    items = {i["term"]: i for i in ga.review_items(gloss)}
    assert items["Yuji"]["reason"] == "no-match" and items["Yuji"]["context"] == []
    assert items["Deccan"]["canonical"] == "Decken"


def test_record_decision_accept_writes_the_fix_and_clears_the_flag():
    gloss = {"flagged": {"Deccan": {"reason": "share-too-close", "canonical": "Decken"}}}
    g = ga.record_decision(gloss, "Deccan", accept=True)
    assert g["hard_fixes"]["Deccan"] == "Decken"
    assert "Deccan" not in g.get("flagged", {})
    assert g["acquired"]["Deccan"]["reason"] == "human-approved"


def test_record_decision_reject_marks_it_known_so_it_is_never_asked_again():
    gloss = {"flagged": {"Smokey": {"reason": "share-too-close", "canonical": "Smoker"}}}
    g = ga.record_decision(gloss, "Smokey", accept=False)
    assert g["known"] == ["Smokey"]
    assert "Smokey" not in g.get("flagged", {})
    assert "Smokey" not in g.get("hard_fixes", {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -k "review_items or record_decision" -v`
Expected: FAIL — no attribute `review_items`

- [ ] **Step 3: Write the minimal implementation**

```python
def review_items(gloss: dict) -> list:
    """The pending review queue, normalised.

    glossary_verify writes bare strings; this module writes objects. Both load, so the
    queue that has been accumulating unread since the verifier shipped is reviewable too."""
    out = []
    for term, meta in sorted((gloss.get("flagged") or {}).items()):
        if isinstance(meta, str):
            meta = {"reason": meta}
        out.append({"term": term, "reason": meta.get("reason", ""),
                    "canonical": meta.get("canonical", ""),
                    "variant_count": meta.get("variant_count", 0),
                    "canonical_count": meta.get("canonical_count", 0),
                    "bound": meta.get("bound", 0.0), "context": meta.get("context", [])})
    return out


def record_decision(gloss: dict, term: str, accept: bool) -> dict:
    """Apply one human decision and drop the term from the queue for good."""
    g = json.loads(json.dumps(gloss))
    meta = (g.get("flagged") or {}).get(term)
    if isinstance(meta, str):
        meta = {"reason": meta}
    meta = meta or {}
    canon = meta.get("canonical", "")
    if accept and canon:
        g.setdefault("hard_fixes", {})[term] = canon
        g.setdefault("acquired", {})[term] = {"canonical": canon, "count": meta.get("variant_count", 0),
                                              "canonical_count": meta.get("canonical_count", 0),
                                              "score": meta.get("score", 0.0), "bound": meta.get("bound", 0.0),
                                              "reason": "human-approved", "run": "review"}
    else:
        g["known"] = sorted(set(g.get("known", [])) | {term})
    g.get("flagged", {}).pop(term, None)
    if not g.get("flagged"):
        g.pop("flagged", None)
    return g
```

Add a `--review` branch to `main()`, before the `--revert` branch:

```python
    if a.review:
        g = json.load(open(a.glossary, encoding="utf-8"))
        for item in review_items(g):
            log(f"\n{item['term']}  ->  {item['canonical'] or '(no canonical)'}   [{item['reason']}]")
            log(f"  seen {item['variant_count']}x vs canonical {item['canonical_count']}x, bound {item['bound']:.3f}")
            for ln in item["context"]:
                log(f"    | {ln}")
            ans = input("  accept this fix? [y/N/q] ").strip().lower()
            if ans == "q":
                break
            g = record_decision(g, item["term"], accept=(ans == "y"))
        if a.apply:
            json.dump(g, open(a.glossary, "w"), indent=2, ensure_ascii=False)
        log(json.dumps({"reviewed": True, "written": a.apply, "pending": len(g.get("flagged", {}))}))
        return
```

and register the flag: `ap.add_argument("--review", action="store_true", help="walk the pending queue interactively")`.

Finally, in `apply_proposals()`, write the object form so the queue carries its evidence:

```python
        flagged[p["variant"]] = {"reason": p["reason"], "canonical": p["canonical"],
                                 "variant_count": p["variant_count"],
                                 "canonical_count": p["canonical_count"],
                                 "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                                 "context": p.get("context", [])}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_glossary_acquire.py -v`
Expected: PASS (whole file). Update the Task 8 assertion
`g["flagged"]["Smokey"] == "share-too-close"` to
`g["flagged"]["Smokey"]["reason"] == "share-too-close"` — that is the intended contract
change, not a regression.

- [ ] **Step 5: Commit**

```bash
git add glossary_acquire.py tests/test_glossary_acquire.py
git commit -m "feat(acquire): --review, and flagged entries that carry their evidence"
```

---

### Task 17: Ship it — lint, image, and the pipeline hook

**Files:**
- Modify: `Dockerfile.builder` (the `COPY` list)
- Modify: `gen_loop.sh:24-31`
- Modify: `pyproject.toml` if `glossary_acquire.py` is not already in ruff's scope

**Interfaces:**
- Consumes: `glossary_acquire.main()` (Task 10).
- Produces: nothing downstream.

`common.py` was once missing from the image's `COPY` list and every import failed at container start; the same trap applies here.

- [ ] **Step 1: Add the module to the image**

Add `glossary_acquire.py` to `Dockerfile.builder`'s `COPY` list alongside `glossary_verify.py`.

- [ ] **Step 2: Verify ruff passes**

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Hook it into the sweep, after mine and before verify**

In `gen_loop.sh`, after the `mine_glossary.py` line (currently line 24) and before the `GLOSS=` assignment, add:

```sh
    # Acquire names the miner cannot reach: releases with no embedded fansub track leave the
    # glossary empty for that stretch of the show. Wiki-owned canonicals only; dry-run unless
    # ACQUIRE_APPLY=1, and failure-swallowed so it can never stall a sweep.
    if [ -n "${ACQUIRE_APPLY:-}" ] && [ -f "$GLOSS_DIR/$show.json" ]; then
        echo "#### ACQUIRE $show $(date)"
        timeout 600 python3 /app/glossary_acquire.py "$GLOSS_DIR/$show.json" "$ANIME/$show" \
            --apply </dev/null 2>&1 || echo "  acquire skipped (continuing)"
    fi
```

Gating on `ACQUIRE_APPLY` keeps the sweep's behaviour unchanged until Punk Hazard verification passes.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: all tests pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.builder gen_loop.sh
git commit -m "build(acquire): ship the module and hook it behind ACQUIRE_APPLY"
```

---

## Verification (run after Task 13, before enabling `ACQUIRE_APPLY`)

Dry-run against the real arc. `conf.json` files live beside the episodes on R520 at
`/export/media/Anime Library/One Pace/Season 30`.

```bash
python3 glossary_acquire.py "glossaries/One Pace.json" "/path/to/One Pace/Season 30"
```

Acceptance — from the spec's verification plan:

| Cluster | Counts | Required |
|---|---|---|
| `Kinemon` | 12, canonical unseen | `apply`, reason `canonical-unseen` |
| `Brooke` | 9, canonical unseen | `apply`, reason `canonical-unseen` |
| `Smokey` / `Smoker` | 16 / 21 | escalates to tier C; expected `known`/`context-distinct` (it is a nickname) |
| `Deccan` / `Decken` | 21 / 8 | escalates to tier C; `apply`/`context-merged` if the model merges them, else stays flagged |
| `Warlords` | 10 | `known`, reason `short-form` (tier 0) |
| `Surrender`, `Maybe`, `Hurry`, `Listen` | 10–22 | absent from proposals entirely |

If `Kinemon` or `Brooke` come back `flag`, the escape clause in `decide()` is wrong — that is
the failure mode this plan most expects, because both score a Wilson bound of 0.000.
