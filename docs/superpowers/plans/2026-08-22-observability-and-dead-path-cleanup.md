# Observability and Dead-Path Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a pipeline rule that stops firing, or a stage that silently fails, visible —
and delete the dead paths already confirmed.

**Architecture:** Four independent changes. Three add observability to infrastructure that
already exists (the `qc` sidecar, the `.dubtitles.done` stamp); one deletes code. No new
services, no new dependencies, no manifest.

**Tech Stack:** Python 3.10 stdlib, existing `qc.Recorder`, `argparse`. Tests with pytest,
run inside the container image (`pysubs2` is absent on the laptop).

**Spec:** `docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md` (§6 records the
successor item, deferred). Origin: adversarial reviews by GPT-5.6 Luna and GLM-5.2,
2026-08-21, in `docs/Adversarial Reviews/`.

## Global Constraints

- **The pattern being fixed is "handled failure with no observation."** Every bug that
  motivated this plan was a _correct_ fallback that nothing reported taking. A change that
  adds a fallback without adding its counter re-creates the problem.
- **Zero activation must be distinguishable from never-evaluated.** `evaluated == 0` and
  `activated == 0` mean different things and must be separately visible.
- **No second source of truth.** A declared manifest of what the pipeline does was explicitly
  rejected in review: it rots, and a stale check that reports "verified" is the same failure
  class. Everything here is measured at runtime, not declared.
- **Never delete known-good output before its replacement exists.** Writes stay temp-file +
  `os.replace`. Sidecars are parked (`.stale`), not removed.
- **Sidecars are group-writable** (`common.SIDECAR_MODE = 0o664`, `umask 002`). Any new
  sidecar follows this or a non-root writer cannot rewrite it.
- **Run the suite in the container:** `docker run --rm -v "$PWD":/src -w /src --entrypoint sh
dubtitle-builder:latest -c "pip install -q pytest; python3 -m pytest --ignore=tests/test_boxxo_voice_extract.py"`
  Baseline is **1045 passing**.
- **Do not touch** `AGENTS.md`, `boxxo_voice_extract.py`, `tests/test_boxxo_voice_extract.py` —
  another workstream owns them.

---

### Task 1: Delete confirmed dead code

Fastest win, no dependencies, and it proves the audit was real. Each item below was verified
by source search during the 2026-08-21 review; re-verify before deleting.

**Files:**

- Modify: `common.py` (remove `dialogue_event_count`), `tests/test_common.py:114-127`
- Modify: `mux.py:50` (remove `DELETE_BROKEN`), `mux.py:171-194` (remove `partners`)
- Delete: `all_seasons.sh`, `anime_library.sh`, `merge_watcher.sh`, `post_season.sh`,
  `post_show.sh`, `run-dub-merge.sh`
- Modify: `IMPROVEMENTS.md:199-210,240` (remove `REPAIR_BACKEND_SECONDARY`)

**Interfaces:**

- Consumes: nothing.
- Produces: nothing. This task only removes.

- [ ] **Step 1: Re-verify each item has no caller**

```bash
grep -rn "dialogue_event_count" --include='*.py' .        # expect: def + tests only
grep -rn "partners(" --include='*.py' . | grep -v "def partners"   # expect: tests only
grep -rn "DELETE_BROKEN" --include='*.py' .               # expect: mux.py:50 + docstring
for f in all_seasons anime_library merge_watcher post_season post_show run-dub-merge; do
  echo "$f: $(grep -rl "$f.sh" --include='*.sh' --include='*.py' --include='Dockerfile*' . | grep -v "/$f.sh$" | wc -l) referrer(s)"
done
```

Expected: `dialogue_event_count` and `partners` have no production caller. `anime_library.sh`
DOES reference `post_show.sh` — delete them together or not at all. If any count is non-zero
for a reason not listed here, STOP and report rather than deleting.

- [ ] **Step 2: Write the failing test for the destructive knob**

`DELETE_BROKEN_HARDLINKS` currently advertises a destructive safety control that does nothing.
Deleting the variable is the fix; this test pins that it is gone, so it cannot be reintroduced
without wiring.

```python
def test_delete_broken_hardlinks_is_not_a_silent_noop():
    """The env var was read into mux.DELETE_BROKEN and never consumed: an operator could set
    DELETE_BROKEN_HARDLINKS=1, see no error, and believe broken seeding hardlinks were being
    reaped. Removed 2026-08-22. If it is ever reintroduced it must be WIRED, not just read."""
    import mux
    assert not hasattr(mux, "DELETE_BROKEN"), "dead destructive knob reintroduced unwired"
    assert not hasattr(mux, "partners"), "partners() has no caller; wire it or leave it out"
```

- [ ] **Step 3: Run it, confirm it FAILS**

Run: `python3 -m pytest tests/test_mux.py::test_delete_broken_hardlinks_is_not_a_silent_noop -v`
Expected: FAIL — `mux.DELETE_BROKEN` currently exists.

- [ ] **Step 4: Delete the code**

Remove `mux.py:50` (`DELETE_BROKEN = ...`), `mux.py:171-194` (`partners`), the
`DELETE_BROKEN_HARDLINKS` mention in `mux.py`'s module docstring (line 27), and
`common.dialogue_event_count` plus its tests. Delete the six shell scripts. Remove
`REPAIR_BACKEND_SECONDARY` from `IMPROVEMENTS.md` (`REVIEW.md:1015` already records that it
was never implemented — leave that note, it is the history).

- [ ] **Step 5: Run the full suite**

Run the container command from Global Constraints.
Expected: PASS. Count will drop below 1045 because `dialogue_event_count`'s tests are gone;
record the new number in the commit message.

- [ ] **Step 6: Commit**

```bash
git add common.py mux.py tests/test_common.py tests/test_mux.py IMPROVEMENTS.md
git rm all_seasons.sh anime_library.sh merge_watcher.sh post_season.sh post_show.sh run-dub-merge.sh
git commit -m "chore: delete confirmed dead paths found by the 2026-08-21 review

DELETE_BROKEN_HARDLINKS advertised a destructive safety control that did
nothing: read into mux.DELETE_BROKEN, never consumed. partners() had no
caller. dialogue_event_count() had no runtime caller (timing_compare uses
dialogue_density_score). Six shell scripts predate the container and are not
COPY'd into the image; run-dub-merge.sh was referenced by nothing at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Liveness counters on every gated rule

The dead-path detector. A rule with `evaluated > 0` and `activated == 0` across N episodes is
dead. This replaces the contract-manifest proposal, which was rejected in review for creating
a second source of truth that rots.

**Files:**

- Modify: `qc.py` (bump `SCHEMA_VERSION` 3 → 4)
- Modify: `hallucination.py` (`drop_reason`, `flag_reason` — accept an optional recorder)
- Modify: `generate.py` (pass the recorder at the call sites)
- Test: `tests/test_hallucination.py`, `tests/test_qc.py`, `tests/test_generate.py`

**Interfaces:**

- Consumes: `qc.Recorder.count(name, n=1)` — the existing counter API (`qc.py:51`).
- Produces: counters named `rule_<name>_evaluated` and `rule_<name>_activated` in the qc
  sidecar, for `blocklist`, `repetition`, `music`, `low_conf`, `maybe_silence`.

- [ ] **Step 1: Write the failing test**

```python
def test_drop_reason_records_evaluated_and_activated(tmp_path):
    """A rule that never fires must be distinguishable from a rule never reached.
    hallucination.music fired 0 times in 353,879 cards and nothing noticed."""
    import hallucination as h, qc
    rec = qc.Recorder()
    speech = {"text": "Hello there.", "no_speech_prob": 0.1, "avg_logprob": -0.2}
    h.drop_reason(speech, rec=rec)
    assert rec.counters["rule_music_evaluated"] == 1
    assert rec.counters["rule_music_activated"] == 0
    assert rec.counters["rule_blocklist_evaluated"] == 1
    assert rec.counters["rule_blocklist_activated"] == 0

    h.drop_reason({"text": "To be continued...", "no_speech_prob": 0.1,
                   "avg_logprob": -0.2}, rec=rec)
    assert rec.counters["rule_blocklist_activated"] == 1


def test_drop_reason_without_recorder_is_unchanged():
    """rec is optional: tools/ and tests call drop_reason bare."""
    import hallucination as h
    assert h.drop_reason({"text": "To be continued...", "no_speech_prob": 0.1,
                          "avg_logprob": -0.2}) == "blocklist"
```

- [ ] **Step 2: Run it, confirm it FAILS**

Run: `python3 -m pytest tests/test_hallucination.py -k evaluated -v`
Expected: FAIL — `drop_reason()` takes no `rec` argument.

- [ ] **Step 3: Implement**

```python
def _tick(rec, rule, activated):
    """Record that `rule` was evaluated, and whether it fired. `evaluated > 0` with
    `activated == 0` across a season is the dead-rule signal -- the one this codebase
    lacked when hallucination.music sat inert through 353,879 cards."""
    if rec is None:
        return
    rec.count(f"rule_{rule}_evaluated")
    if activated:
        rec.count(f"rule_{rule}_activated")


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
```

Apply the same shape to `flag_reason` for `low_conf` and `maybe_silence`. Note `flag_reason`
returns on the first match, so `maybe_silence` is only _evaluated_ when `low_conf` did not
fire — that is correct and the counter should reflect it.

- [ ] **Step 4: Wire the call sites in generate.py**

`generate.py:626-640` calls `hallucination.drop_reason(c)` and `flag_reason(c)` inside the
card loop. The recorder `rec` is already in scope (created at `generate.py:621`). Pass it.

- [ ] **Step 5: Bump the schema**

`qc.py:15`: `SCHEMA_VERSION = 4   # v4: rule_*_evaluated / rule_*_activated liveness counters`

- [ ] **Step 6: Run the full suite**

Expected: PASS. `tests/test_generate.py` asserts sidecar contents — update any that pin
`schema_version == 3`.

- [ ] **Step 7: Commit**

```bash
git add qc.py hallucination.py generate.py tests/
git commit -m "feat(qc): liveness counters so a dead rule is visible

hallucination.music fired 0 times across 353,879 cards and nothing reported
it. evaluated/activated per rule makes 'ran and found nothing' distinct from
'never reached'. Rides the existing qc sidecar; no manifest, which would be a
second source of truth that rots.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Per-stage `unresolved` queue

**The highest-value item.** The architecture principle says a human sees what the model cannot
settle. `glossary_acquire.py` implements that (`review_items` at `:685`, `record_decision` at
`:712`, `--review` at `:859`). The subtitle path does not: model refusals, transport failures,
no-anchor cases and guard rejections all become counters and vanish.

Per-stage, not one flat queue — triage differs by stage (a repair rejection needs a fansub
check; a punctuation rejection needs a read; a hallucination flag needs an audio listen).

**Files:**

- Create: `unresolved.py`
- Create: `tests/test_unresolved.py`
- Modify: `repair.py` (at `skipped_no_ref` `:400`, `rejected` `:451`)
- Modify: `punctuation.py` (at `restore_empty`, `restore_rejected_guard`)
- Modify: `Dockerfile.builder` COPY list (a module missing from it ImportErrors at container
  start and no test catches it — see `tests/test_dockerfile_copy.py`)

**Interfaces:**

- Produces: `record(stem, stage, reason, **fields)` appending to
  `<stem>.dubtitles.unresolved.json`; `items(path)` reading them back; `--review` CLI.
- Entry shape: `{stage, reason, original_text, proposed_text, source_start, source_end,
avg_logprob, model, backend, ts}`.

- [ ] **Step 1: Write the failing test**

```python
def test_records_per_stage_and_survives_reread(tmp_path):
    import unresolved
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="Gum -gum!",
                      source_start=1.0, source_end=1.4, avg_logprob=-0.79)
    unresolved.record(stem, "punctuation", "llm_empty", original_text="who are you")
    got = unresolved.items(stem)
    assert [e["stage"] for e in got] == ["repair", "punctuation"]
    assert got[0]["reason"] == "no_reference"
    assert got[0]["original_text"] == "Gum -gum!"


def test_append_never_raises_and_never_blocks(tmp_path):
    """Same contract as qc.write: this is observability. It must not fail an episode
    that otherwise generated correctly."""
    import unresolved
    assert unresolved.record("/nonexistent/dir/ep", "repair", "no_reference") is False


def test_sidecar_is_group_writable(tmp_path):
    import stat, unresolved, common
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference")
    mode = stat.S_IMODE(os.stat(stem + ".dubtitles.unresolved.json").st_mode)
    assert mode == common.SIDECAR_MODE
```

- [ ] **Step 2: Run it, confirm it FAILS**

Run: `python3 -m pytest tests/test_unresolved.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'unresolved'`

- [ ] **Step 3: Implement `unresolved.py`**

Mirror `qc.write`'s discipline exactly: temp file + `os.replace`, `os.chmod` to
`common.SIDECAR_MODE`, and **never raise** — return `True`/`False`. Read-modify-append rather
than open-in-append, so a partial write can never corrupt the JSON array.

- [ ] **Step 4: Wire repair.py**

At `repair.py:400` (`skipped_no_ref += 1`) record `reason="no_reference"` with the card's
text and source window. At `:451` (`rejected += 1`) record `reason="rejected_guard"` with both
the original and the model's proposal — that proposal is currently discarded entirely.

- [ ] **Step 5: Wire punctuation.py**

At the `restore_empty` site record `reason="llm_empty"` (this is the case where a dead endpoint
looks like a clean run — `common.llm_chat()` returns `""` on every transport failure). At
`restore_rejected_guard` record `reason="rejected_guard"`.

- [ ] **Step 6: Add the `--review` CLI**

Mirror `glossary_acquire.py:859-888`. Walk all stages in one pass but keep entries stage-keyed;
show the evidence each stage's triage needs. Resolution is recorded back into the file.

- [ ] **Step 7: Add to the Dockerfile COPY list**

`Dockerfile.builder:58` — add `unresolved.py`. `tests/test_dockerfile_copy.py` checks
local-import closure; confirm it passes.

- [ ] **Step 8: Run the full suite, then commit**

```bash
git add unresolved.py tests/test_unresolved.py repair.py punctuation.py Dockerfile.builder
git commit -m "feat: per-stage unresolved queue - the missing human rung

The ladder was rules -> bounded LLM -> keep old text / increment a counter.
Model refusals, transport failures and no-anchor cases vanished: llm_chat()
returns '' on every transport error, so a dead endpoint looked like a clean
run. Per-stage because triage differs by stage.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Stage-execution record in the stamp

`.dubtitles.done` says an episode is done. It does not say what "done" means — an episode where
repair never ran is today indistinguishable from one where it ran and found nothing.
`merge_pass.sh` has no `set -e` and checks no exit status; `MERGE_PASS_DONE` prints regardless.

**Files:**

- Modify: `common.py` (`write_stamp`), `mux.py` (`write_stamp` call at `:329`)
- Test: `tests/test_common.py`, `tests/test_mux.py`

**Interfaces:**

- Consumes: existing stamp dict `{size, mtime, muxed, version}`.
- Produces: adds `stages: {repair: bool, signs_merge: bool, punctuation: bool}`.
  `stamp_valid()` must IGNORE the new key — an old stamp without it stays valid.

- [ ] **Step 1: Write the failing test**

```python
def test_stamp_records_which_stages_ran(tmp_path):
    import common, json
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 10)
    p = str(tmp_path / "ep.dubtitles.done")
    common.write_stamp(p, str(v), stages={"repair": False, "signs_merge": True,
                                          "punctuation": True})
    d = json.load(open(p))
    assert d["stages"]["repair"] is False


def test_old_stamp_without_stages_is_still_valid(tmp_path):
    """A stamp written before this change must not trigger library-wide re-transcription."""
    import common, json, os
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 10)
    st = os.stat(v)
    old = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True,
           "version": common.PIPELINE_VERSION}
    assert common.stamp_valid(old, str(v)) is True
```

- [ ] **Step 2: Run it, confirm it FAILS**

Expected: FAIL on the first test — `write_stamp()` takes no `stages`.
The second should already PASS; if it does not, STOP — backward compatibility is the
constraint that keeps this from re-transcribing the library.

- [ ] **Step 3: Implement**

`stages` is optional and defaults to `None` (key omitted). `stamp_valid()` is untouched.

- [ ] **Step 4: Run the full suite, then commit**

```bash
git add common.py mux.py tests/
git commit -m "feat(stamp): record which stages actually ran

An episode where repair never ran was indistinguishable from one where it ran
and found nothing. merge_pass.sh has no set -e and checks no exit status.
Additive and optional: stamp_valid ignores it, so no re-transcription.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Not in this plan

- **VAD hang trim** — dropped, see the spec. Do not reopen without reading §3.
- **The `source_*` plausibility guard** (spec §5 + §6) — its own item, deferred deliberately;
  both parts touch the same handling and should be done together.
- **`DUB_SUFFIX`** — read as an env var in `dub_signs_merge.py:40`, hardcoded in `generate.py`
  (×3), `mux.py:55`, `merge_pass.sh`. Either remove the variable or make all sites read it.
  Not urgent (nobody changes the suffix) but it is a live inconsistency.
- **`webrtcvad` install** — `Dockerfile.builder` wraps it in `|| echo`, it silently failed,
  and the module is absent so `tools/vad.py` returns `None` for every probe.
  `webrtcvad-wheels` fixes it (verified 2026-08-21). Analytics-only; no pipeline impact.
- **`REQUIRE_ENG`** hardcoded at `gen_loop.sh:54`, making the compose value decorative.
- **`MERGE_ROOTS` scoping** — operational, not code.

---

## Follow-up item: attack/technique names are unreachable by the current verifier

Raised 2026-08-21 after `'Gum-Gum Pistol'` was transcribed as `'Gum-Gum Hit-Off'` by turbo.
The glossary contains characters, places and organisations but **not one attack name**, and
nothing in `initial_prompt` names any, so the decoder has never been told the phrases exist.
That is the likely root of the whole `dum dum` / `kuma kuma` / `gum flake gum` cluster: one
attack prefix, misheard four different ways.

**Two separate reasons the existing tooling cannot fill the gap.** Both were measured.

**1. Structural — techniques are wiki SUBPAGES, not articles.**
`glossary_verify.fetch_titles()` returned 8,109 One Piece titles. Not one attack among them:

    'Gomu Gomu'  -> 8 hits, all of the form  Gomu Gomu no Mi/Gear 2 Techniques
    'Pistol'     -> 0 hits

Individual techniques live in tables inside `.../Gear N Techniques` subpages, and
`glossary_verify` normalises `/Subpage` paths away by design. So every technique in the
franchise is invisible to it. This shape is franchise-independent: Jujutsu Kaisen's cursed
techniques, Fire Force's ignition abilities and Naruto's jutsu are organised the same way.

**2. Semantic — the wiki is the WRONG AUTHORITY for a dub pipeline here.**
The wiki records the Japanese-derived canon; the dub says something else, and not as a spelling
variant but as different words in a different order:

    wiki: Gear Second          dub: Second Gear
    wiki: Gomu Gomu no Pistol  dub: Gum-Gum Pistol

For characters and places the two agree (`Luffy`, `Enies Lobby`), which is why verification
works there. For techniques, verifying against the wiki would confirm a string this pipeline
must never emit. `glossary_acquire`'s spec already calls for "dub-preference" in adjudication,
but for techniques there may be no dub-name field on the wiki to prefer.

**Do NOT fill this from model memory.** Eleven candidate attack names were written from model
recall on 2026-08-21 and reverted the same hour: it breaks the project's own rule that the wiki
owns every canonical string and a model only decides which entities to ask about. Only
`Gum-Gum Pistol` remains, and only because a human confirmed it. `initial_prompt` is the
highest-leverage place to be wrong — a bad name there biases _every_ transcription.

**Possible approaches, none evaluated:**

- Fetch the technique subpages and parse their tables, taking the dub column where one exists.
- Mine dub names from the shows' own fansub tracks, where a release has one — the transcript
  is then proposing candidates, which is the sanctioned direction, and the fansub carries the
  dub wording rather than the wiki's.
- Treat it as a human-curated list per show, entered through the `--review` CLI, on the grounds
  that a franchise has tens of techniques, not thousands.

**Why it matters:** turbo is measurably weaker on proper nouns than large-v3 (14 vs 10
name-fixes on the same episode, plus the `Kuma Kuma` fabrication), and the production model is
now turbo. The deterministic layer has to carry more of the load than it did, and attack names
are the category it currently does not cover at all.
