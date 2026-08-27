# repair-review-and-decision-store — implementation plan

Status: draft
Spec: `.procoder/specs/repair-review-and-decision-store.md`

## Goal

Give the repair stage a human rung: queue every accepted repair and every gate rejection,
let a human settle them through a web UI, store the verdicts in a per-show artifact that
ships in git the way glossaries do, and apply them both to future runs and to episodes
already generated.

## Architecture

A new `decisions.py` owns a per-show JSON store keyed on the normalised
`(orig, proposed)` text pair; `repair.py` consults it at one point between
`glossary.correct()` and `accept_repair`, and records every accepted repair into the
existing `unresolved.py` queue. A new `review_apply.py` replays verdicts over an already
generated episode by rebuilding the srt from `conf.json` and invalidating the mux stamp,
and a new stdlib `review_server.py` is the disposable UI over both. All durable logic lives
in the modules; the server holds none.

## Constraints

Copied from the spec; every task inherits all of them.

- **No new runtime dependency.** `pyproject.toml` declares three (`pysubs2`,
  `faster-whisper`, `jellyfish`). The server is stdlib `http.server`.
- **Card timing is immutable in repair (C1).** `fits_card` still applies to a human's
  `correct` text and to a `force` verdict. The repair gives way, never the timing.
- **Never fail an episode.** The queue side inherits `unresolved.py`'s contract — it is
  observability and must never raise; every entry point returns a bool. The apply side is
  behavioural and fails CLOSED: an unreadable store means today's behaviour.
- **`orig` is the PRE-correction ASR text** — `c["text"]` before `glossary.correct()` runs.
  Never the post-correction proposal.
- **A miss is a no-op.** No match falls through to `accept_repair`. Never a partial apply.
- **TDD, no exceptions.** Every behaviour: write one test, RUN it, watch it fail for the
  right reason, then the simplest code that passes. RED command + failing output and GREEN
  command + passing output go in the task's `## Evidence` section — `todo close` asks.
- **`procoder check` clean and `procoder test` green** before any task closes.
- **`procoder format` prints nothing for an already-formatted file.** Never
  `format > out; cp out file` without a size guard — it has emptied a file here before.
- **Any new module imported by an entrypoint must be added to `Dockerfile.builder`'s COPY
  list**, and any new entrypoint to `tests/test_dockerfile_copy.py`'s `ENTRYPOINTS`.
  `qc.py` passed 987 tests and ImportError'd on container start across 33 commits.
- **`REPAIR_UNANCHORED` is NOT flipped by this plan.** It stays default-closed.
  `TEXT_VERSION` is NOT bumped: with an empty store the consult is a no-op.

## Task 1: the decision store

Files: `decisions.py` (new), `tests/test_decisions.py` (new)

Interfaces produced, consumed by tasks 2, 4, 5 and 7:

    DECISIONS_DIR = os.environ.get("DECISIONS_DIR", "/config/decisions")
    DECISIONS_APPLY = os.environ.get("DECISIONS_APPLY", "1") not in ("", "0")

    key(text) -> str                      # lowercase, collapse whitespace, KEEP punctuation
    load(show, dir=DECISIONS_DIR) -> dict # {} when absent, unreadable, or corrupt
    lookup(store, orig, proposed) -> dict | None
    record(store, orig, proposed, verdict, text="", note="", promoted=None) -> dict
    save(store, show, dir=DECISIONS_DIR) -> bool   # atomic mkstemp + os.replace
    decisions_for(path, dir=DECISIONS_DIR) -> tuple[dict, str]   # (store, show)

- [ ] RED: `test_key_normalises_case_and_whitespace_but_keeps_punctuation` — assert
      `key("  We're  Looking  For A Factory. ") == key("we're looking for a factory.")`
      and `key("CP-0.") != key("CP?")`. Run `python3 -m pytest tests/test_decisions.py -q`;
      expect collection to fail on the missing module. That is the right failure.
- [ ] GREEN: create `decisions.py` with a module docstring naming the ladder rung it serves
      and the `Env:` block for both variables, and implement `key()` as
      `" ".join(text.lower().split())`.
- [ ] RED: `test_lookup_matches_the_pair_and_only_the_pair` — a store holding one recorded
      verdict returns it for the same `(orig, proposed)` and `None` for a pair differing
      only in `proposed`.
- [ ] GREEN: implement `record()` (append to `store["decisions"]`) and `lookup()` (scan on
      the two normalised keys).
- [ ] RED: `test_record_refuses_empty_and_normalises_a_noop_correct` — `record()` with an
      empty `orig` or `proposed` returns without adding an entry; a `correct` whose `text`
      normalises equal to `orig` is stored as `verdict="reject"`.
- [ ] GREEN: add both guards at the top of `record()`.
- [ ] RED: `test_save_creates_the_file_then_appends_without_loss` — saving to a directory
      with no file for that show creates it; a second verdict round-trips both.
- [ ] GREEN: implement `save()` with `tempfile.mkstemp` in the target directory then
      `os.replace`, mirroring `unresolved._rewrite` (`unresolved.py:93`).
- [ ] RED: `test_a_corrupt_store_loads_empty_and_never_half_loads` — a file of invalid JSON
      makes `load()` return `{}`, not a partial dict.
- [ ] GREEN: wrap `load()` in `try/except (OSError, ValueError)` returning `{}`.
- [ ] RED: `test_decisions_for_walks_up_like_glossary_for` — an episode nested under a
      show directory resolves that show's store; a missing `DECISIONS_DIR` yields `({}, "")`.
- [ ] GREEN: implement `decisions_for()` as the same ancestor walk as
      `repair.glossary_for` (`repair.py:88`), taking show identity from the show DIRECTORY'S
      basename -- the name its glossary file is named for -- and NOT from `gloss["show"]`,
      which is a display name and would produce a store the glossary never agrees with.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 2: promotion into the show glossary

Files: `decisions.py` (extend), `tests/test_decisions.py` (extend)

Interfaces: `promote(gloss, promoted) -> dict` — returns a NEW glossary dict; never mutates
its argument, matching `glossary_acquire.apply_proposals` (`glossary_acquire.py:672`).

- [ ] RED: `test_promote_writes_a_hard_fix` — promoting the payload
      `{"hard_fix": {"Samadai": "Samurai"}}` returns a glossary mapping `Samadai` to
      `Samurai` in `hard_fixes`, and the input dict is unchanged.
- [ ] GREEN: deep-copy via `json.loads(json.dumps(gloss))`, set the key, return.
- [ ] RED: `test_promote_never_overwrites_a_curated_entry` — a glossary already mapping
      `Samadai` to something else keeps its value and the promotion is reported as refused.
- [ ] GREEN: skip and report when the key exists with a different value. A human's curated
      glossary outranks a promotion, the same way `glossary_acquire.revert` refuses to
      delete a `run == "review"` entry (`glossary_acquire.py:730`).
- [ ] RED: `test_a_promoted_verdict_records_what_it_promoted` — the stored decision carries
      the `promoted` payload verbatim so the audit trail survives.
- [ ] GREEN: pass `promoted` straight through `record()`.
- [ ] Docstring must state: `promoted` is set by the HUMAN at review time and is an audit
      trail, never an auto-classifier — auto-classification on a single-token difference
      would promote `factory -> needle` show-wide, the exact regression this store exists
      to catch.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 3: queue accepted repairs

Files: `unresolved.py`, `repair.py`, `tests/test_unresolved.py`, `tests/test_repair.py`

Interfaces: `unresolved.REASONS` gains a `"repair_applied": ("accepted",)` stage;
`unresolved.PRIMARY_STAGES` is new and names what the default review view shows.

- [ ] RED: `test_repair_applied_is_a_known_stage_with_its_own_evidence` — `REASONS`
      contains `repair_applied/accepted`, and `_EVIDENCE["accepted"]` lists
      `original_text`, `proposed_text`, `avg_logprob`.
- [ ] GREEN: add the stage to `REASONS` (`unresolved.py:47`) and the evidence template to
      `_EVIDENCE` (`unresolved.py:150`). Update the module docstring: the queue now covers
      both what could not be settled AND what was settled without checking meaning.
- [ ] RED: `test_primary_filter_excludes_no_reference_and_llm_empty` — over a queue holding
      all five reasons, the primary filter returns exactly the accepted repairs plus
      `rejected_guard` and `rejected_name_invented`, and `no_reference`/`llm_empty` are
      ABSENT. Assert on the absence: `pending()` (`unresolved.py:89`) applies no stage
      filter of its own, so a function returning everything would pass a presence-only test.
- [ ] GREEN: add `PRIMARY_STAGES` and a `pending(stem, primary_only=False)` parameter.
- [ ] RED: `test_an_accepted_repair_is_queued_with_the_right_evidence` — after
      `repair.process()` accepts one repair, the jsonl holds one `repair_applied/accepted`
      entry whose `original_text` equals the card's PRE-repair text and whose
      `proposed_text` equals the applied text. Assert the FIELDS, not the count — two empty
      strings would satisfy a count-only assertion.
- [ ] GREEN: add one `unresolved.record(...)` call on the success path in
      `repair.process()`, beside the existing `audit.append` (`repair.py:681`). Capture the
      pre-repair text into a local BEFORE `c["text"] = new` (`repair.py:683`) overwrites it.
- [ ] RED: `test_queue_entry_count_matches_the_repaired_summary` — the entry count equals
      the `repaired` field of `.dubtitles.repair-summary.json` for the same episode.
- [ ] GREEN: no new code expected; if this fails, the record call is on the wrong branch.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 4: consult the store inside repair

Files: `repair.py`, `tests/test_repair.py`

Interfaces consumed: everything from Task 1. Nothing new is exported.
The consult goes between `new = glossary.correct(new, gloss)[0]` (`repair.py:634`) and
`if not accept_repair(...)` (`repair.py:649`). `orig` for the lookup is `c["text"]`.

- [ ] RED: `test_a_reject_verdict_keeps_the_post_correction_asr_text` — with a `reject`
      stored, the card's text equals the post-`glossary.correct()` ASR text and no
      `repair_applied` entry is written. This pins the consult point: a consult placed
      BEFORE the correction leaves pre-correction text and fails.
- [ ] GREEN: add the lookup and the `reject` branch (`continue` without applying).
- [ ] RED: `test_a_correct_verdict_applies_the_humans_text`.
- [ ] GREEN: add the `correct` branch, assigning `new = d["text"]`.
- [ ] RED: `test_a_correct_that_does_not_fit_the_card_is_refused_and_recorded` — a `correct`
      whose text fails `fits_card` leaves the ASR text in place AND writes an unresolved
      entry naming the refusal. Timing is immutable; the human is told, not silently dropped.
- [ ] GREEN: run the `correct` text through `fits_card` before accepting it.
- [ ] RED: `test_a_force_verdict_admits_a_repair_the_gate_refused` — with `force` stored for
      a pair `accept_repair` refuses, the repair is applied; the same pair with no verdict is
      still refused.
- [ ] GREEN: add the `force` branch, bypassing `accept_repair` only.
- [ ] RED: `test_force_still_obeys_fits_card` — a forced repair that cannot be rendered is
      still refused and recorded. Force overrides judgement, never timing.
- [ ] GREEN: apply `fits_card` on the `force` path too.
- [ ] RED: `test_an_empty_store_is_byte_identical_and_still_consults` — output matches the
      pre-change code AND the lookup is observably called (counter or monkeypatched spy).
      Byte-identity alone is satisfied by a `return` that never reaches the consult.
- [ ] GREEN: no new code expected.
- [ ] RED: `test_decisions_apply_0_applies_nothing` — with `DECISIONS_APPLY=0` and a
      NON-empty store, output matches the empty-store case and no verdict is applied.
      Assert on the application, not the bytes: identical output proves the flag exists,
      not that it is read before the verdict takes effect.
- [ ] GREEN: gate the branch on `DECISIONS_APPLY`.
- [ ] Add `DECISIONS_DIR` and `DECISIONS_APPLY` to `repair.py`'s docstring `Env:` block.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 5: write-back for episodes already generated

Files: `review_apply.py` (new), `tests/test_review_apply.py` (new)

Interfaces:

    apply_episode(stem, store, gloss, apply=False) -> dict   # {"changed": n, "skipped": ...}
    main(argv=None)     # <stem> | --show <dir>, --apply (dry-run by default)

- [ ] RED: `test_a_reject_restores_the_asr_text_without_calling_the_llm` — on an episode
      with a stored `reject`, the srt is rewritten with the ASR text restored, the
      `.dubtitles.done` stamp is invalidated, and the LLM backend is NEVER called. Assert
      the backend is not called: `repair.process()` also rebuilds the srt from `conf.json`
      (`repair.py:689`), so a criterion that only checks the srt would be satisfied by
      re-running repair, which is not what this task is for.
- [ ] GREEN: read `conf.json`, apply verdicts to each row's text, rewrite the srt through
      `reflow.wrap_balance` exactly as `repair.py:689-693` does, then remove the stamp.
      Rebuild directly the way `recreate_srt.py` does; do not import `repair.process`.
- [ ] RED: `test_dry_run_writes_nothing` — without `--apply`, no file changes and the plan
      is printed. Matches the repo convention (`mux.py`, `glossary_acquire.py`).
- [ ] GREEN: guard every write on the flag.
- [ ] RED: `test_show_sweep_invalidates_only_episodes_that_change` — over a show of three
      episodes where one has a matching verdict, exactly one stamp is invalidated.
- [ ] GREEN: compute the changed set first, act only on it.
- [ ] RED: `test_a_missing_conf_json_is_refused_by_name_and_leaves_the_stamp` — refuses
      that episode, names it, and does not invalidate. Mirrors `repair.py`'s "skip" when
      the srt is absent (`repair.py:576`); a half-applied episode is the failure to avoid.
- [ ] GREEN: check for `conf.json` before touching anything.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 6: the pre-mux gate and its stall alert

Files: `mux.py`, `tests/test_mux.py`

Interfaces: `REVIEW_GATE_SHOWS` (colon list, `MUX_ROOTS` idiom), `REVIEW_GATE_STALE_DAYS`
(default 7). `mux.held_for_review(stem, show) -> bool`.

- [ ] RED: `test_a_gated_show_holds_an_episode_with_a_pending_entry` — listed show plus a
      pending `repair_applied` entry means the episode is skipped; resolve the entry and it
      muxes; with the list empty both mux.
- [ ] GREEN: add `held_for_review()` and one call in `mux.process()` before the existing
      stamp check. The pending entry is the only RELEASE condition.
- [ ] RED: `test_a_stale_hold_is_reported_loudly_and_still_not_muxed` — an entry older than
      `REVIEW_GATE_STALE_DAYS` produces a loud log line AND the episode is still held. The
      alert must never become a release: auto-releasing unreviewed repairs is the failure
      this whole spec exists to prevent.
- [ ] GREEN: compare the queue file's mtime against the threshold and log; do not branch on
      it. `unresolved` entries carry no timestamp, so the sidecar's mtime is the signal —
      note this in the docstring as the deliberate approximation it is.
- [ ] RED: `test_the_sweep_summary_carries_the_held_count` — the per-sweep summary reports
      how many episodes are held, so a backlog is visible rather than silent.
- [ ] GREEN: count holds and add the field.
- [ ] Add both variables to `mux.py`'s docstring `Env:` line.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 7: the review server

Files: `review_server.py` (new), `tests/test_review_server.py` (new)

Interfaces: `REVIEW_PORT` (8842), `REVIEW_TOKEN`. Handler functions are module-level and
take parsed arguments, so every test calls them directly — no socket is opened in tests.

    handle_index() -> dict
    handle_episode(stem, all_reasons=False) -> dict
    handle_decide(stem, index, verdict, text="", note="") -> dict
    handle_apply(stem) -> dict
    resolve_token(dir) -> str     # env, else read the persisted file, else generate one

- [ ] RED: `test_an_unset_token_is_generated_persisted_0600_and_required` — with
      `REVIEW_TOKEN` unset, `resolve_token()` creates a token, writes it mode 0600, and a
      write route WITHOUT it is refused. The unsafe default is the thing being tested away.
- [ ] GREEN: implement `resolve_token()` with `secrets.token_urlsafe(32)` and
      `os.chmod(path, 0o600)`; print it once at startup.
- [ ] RED: `test_an_explicitly_empty_token_disables_auth` — `REVIEW_TOKEN=""` set
      explicitly lets the same write through. Read routes are unaffected in both cases.
- [ ] GREEN: distinguish "unset" from "set empty" by `os.environ` membership, not falsiness.
- [ ] RED: `test_the_default_view_omits_non_primary_reasons` — `handle_episode(stem)`
      contains no `no_reference` or `llm_empty` entries; `all_reasons=True` includes them.
      Assert the ABSENCE.
- [ ] GREEN: delegate to Task 3's `pending(stem, primary_only=True)`.
- [ ] RED: `test_decide_persists_and_resolves` — `handle_decide` writes through
      `decisions.record`/`save` and marks the queue entry resolved via `unresolved.resolve`.
- [ ] GREEN: wire both calls. No storage logic in this module.
- [ ] RED: `test_the_verdict_offered_depends_on_the_entry_type` — an `accepted` entry offers
      `accept/reject/correct` and NOT `force`; a `rejected_guard` entry offers
      `force/reject/correct` and NOT `accept`. Without this, `accept` on a refused entry is
      a `force` with no distinct record, defeating the counting `force` exists for.
- [ ] GREEN: derive the offered set from the entry's stage and reason.
- [ ] RED: `test_forcing_an_unanchored_card_is_labelled_permanent` — the payload for a
      `force` action on an entry with no reference carries the warning that the result is
      unrecoverable on that card.
- [ ] GREEN: set the flag when the entry's `reference` is absent or empty.
- [ ] RED: `test_apply_invokes_write_back` — `handle_apply` calls Task 5's `apply_episode`.
- [ ] GREEN: wire it.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.

## Task 8: run it in the container

Files: `container_run.sh`, `Dockerfile.builder`, `tests/test_dockerfile_copy.py`

- [ ] RED: add `review_server.py` to `ENTRYPOINTS` in `tests/test_dockerfile_copy.py` and
      run the suite. It must fail on `decisions.py`, `review_apply.py` and
      `review_server.py` being absent from the COPY list. `qc.py` passed 987 tests and
      ImportError'd on container start for exactly this reason.
- [ ] GREEN: add all three modules to `Dockerfile.builder`'s COPY line.
- [ ] RED: `test_container_run_starts_the_server_as_a_background_loop` — parse
      `container_run.sh` and assert `review_server.py` is launched in a background subshell,
      not in the `exec` position. The generate loop is the container's foreground process
      and `[S-8]` must not be able to end it.
- [ ] GREEN: add a third background loop beside the existing merge loop, wrapped so its
      exit logs and retries rather than propagating. `set -e` is active in that script —
      the loop must not be able to take the entrypoint down.
- [ ] Document `REVIEW_PORT`, `REVIEW_TOKEN`, `DECISIONS_DIR`, `DECISIONS_APPLY`,
      `REVIEW_GATE_SHOWS` and `REVIEW_GATE_STALE_DAYS` in `container_run.sh`'s header.
- [ ] `procoder test` green, `procoder check` 0 blocking, evidence recorded.
