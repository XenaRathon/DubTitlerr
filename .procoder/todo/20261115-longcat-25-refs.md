# chore: replace LongCat-2.0 references with LongCat-2.5 (2.0 is deprecated)

Status: open (fix round 1 after critic REJECT 5017a93)
Created: 2026-11-15
Type: code
Assigned: coder@cmd (code-coder, DeepSeek V4.1 Flash)
Reason: user 2026-11-15: LongCat 2.0 is deprecated; LongCat-2.5 is live-verified on https://api.longcat.chat/openai/v1 (model id `LongCat-2.5`). Homelab is switching the deployed dubtitle-builder on vm102 (VERIFY_MODEL/REPAIR_MODEL) in its own task 20261115-longcat-25-migration; this task is the repo side.
Owns: compose.yaml (the LongCat comment only), tools/glossary_bakeoff.py, tests/test_glossary_bakeoff.py, tests/test_glossary_judge.py, any other file in this repo that names LongCat-2.0 (list them in Result), CHANGELOG.md (one line), .procoder/todo/20261115-longcat-25-refs.md (Result only)
Checkout: /home/xena/work/code/DubTitlerr-longcat25, branch `chore/longcat-25-refs` (already checked out), from origin/main

## Description

Known references: `compose.yaml:125` (comment `# REPAIR_MODEL: LongCat-2.0`), `tools/glossary_bakeoff.py:450` (a bake-off candidate `"longcat-2.0", "text", "LongCat-2.0", _LONGCAT`), `tests/test_glossary_bakeoff.py:304-308, 367` and `tests/test_glossary_judge.py`. First `grep -rn -i 'longcat-2.0\|LongCat-2\.0'` the whole repo. Then: in code and tests, drop the 2.0 candidate and keep (or add) `longcat-2.5` with model id `LongCat-2.5` on the same endpoint and key env `LONGCATAI_API_KEY` (by name only; never read or print the key); update the tests to the new candidate set; in comments and docs, change the model to LongCat-2.5. Do not change other providers or the bake-off logic. If a test pinned the exact candidate list, update it to the new list and say so. Check the repo's docs (README, AGENTS.md, docs/) for LongCat-2.0 too.

### House rules
- Do not run git rebase, merge or fetch (cmd shell policy). Commit only in the worktree; no push. Commits `20261115-longcat-25-refs: chore: <what>`, no AI trailers.
- Write only under the Result heading; keep exactly one empty Evidence heading, last in the file, and that heading's text nowhere else (not even quoted).
- Gate: the repo's test suite (see AGENTS.md; `.venv` if present) and `procoder check <changed files>` 0 blocking.

## Acceptance criteria

- [ ] No `LongCat-2.0` / `longcat-2.0` reference remains in code, tests, config or docs (grep output in Result).
- [ ] The bake-off and judge tests pass with the LongCat-2.5 candidate; gate clean.

## Result

Commits `1018e35` (the change), `0d4ed2a` and `a496ee3` (this Result) on `chore/longcat-25-refs` (no push).

**What changed**

- `tools/glossary_bakeoff.py` — dropped the `longcat-2.0` arm; the surviving `longcat-2.5` arm keeps the same endpoint (`_LONGCAT_URL`), key variable `LONGCATAI_API_KEY` and `{"thinking":{"type":"disabled"}}` extra body, and now pins the model id `LongCat-2.5` instead of `LongCat-2.5-Preview`. No other arm and no bake-off logic touched.
- `tests/test_glossary_bakeoff.py` — the pinned candidate-list test now expects the 9-arm set without `longcat-2.0` (that test named the exact list, so it was updated to the new list); the endpoint/model/pacing test asserts the single LongCat arm at `LongCat-2.5`; the ten arm-selection occurrences of the old name (the `gb.ARMS` lookup, seven `_run` call sites, the request estimate, the `@v2` rejection case) now use `longcat-2.5`.
- `tests/test_glossary_judge.py` — the three-arm label tuple and the 17 occurrences that used it renamed from `longcat-2.0` to `longcat-2.5`. These are blind-judging labels only; no assertion about a model identity changed.
- `compose.yaml` — the commented repair example now reads `# REPAIR_MODEL: LongCat-2.5`.
- `.procoder/todo/20261115-longcat-25-refs.md` — this Result.

**Files that named LongCat-2.0** (the full list, as Owns requires): exactly the three above plus this task file. Nothing else in the repo named version 2.0.

**Verification**

- Criterion 1 — `grep -rn -i 'longcat-2\.0\|longcat 2\.0'` over the repo returns only this task file (`:1`, `:7`, `:8`, `:13`, `:22` — its own title, Reason, Owns, Description and acceptance text). No code, test, config or doc match remains. `grep -rn '2\.5-Preview'` returns nothing.
- Criterion 1 (docs) — `README.md`, `AGENTS.md` and `docs/` were checked: `docs/wiki/How-To-Guides.md:316` names "LongCat's API" with no version or model id (it documents the `thinking` switch, not a model), and `settings_registry.py:258` names only the key `LONGCATAI_API_KEY`. Neither states version 2.0, so neither needed a change.
- Criterion 2 — `.venv/bin/python -m pytest tests/test_glossary_bakeoff.py tests/test_glossary_judge.py` → `156 passed in 6.88s`.
- Lint — `procoder lint compose.yaml tools/glossary_bakeoff.py tests/test_glossary_bakeoff.py tests/test_glossary_judge.py` → `0 finding(s) (0 blocking)`.
- Full suite — `.venv/bin/python -m pytest` → `38 failed, 4838 passed`. All 38 sit in four files my diff does not touch (`tests/test_merge_pass.py` 23, `tests/test_merge_pass_runtime_env.py` 13, `tests/test_mux.py` 1, `tests/test_render_readme_table.py` 1) and every one fails on `ModuleNotFoundError: No module named 'pysubs2'` / `FATAL: pysubs2 not found — image is misbuilt` from a bare `python3` subprocess that resolves to system 3.14; the affected suites pass under the venv.
- Gate — `procoder check` on the four changed files (commit `0d4ed2a`, clean tree): `4 clean, 0 unformatted, 0 unchecked, 0 out of scope, 151 hygiene finding(s) (2 blocking)`. Both blockers are escalated below, not code faults. Adding this task file to the same invocation reports it `unformatted`: `procoder format` wants one blank line after `### House rules`, which is in the dispatched text above this heading — I left it alone per the "write only under Result" rule.

**Escalations**

1. **Gate's Python test step cannot run in this shell.** It resolves `pytest` from `PATH` to `/usr/bin/pytest` (CPython 3.14, no `pysubs2`), which fails at collection with `0 passed, 0 failed`. It fails identically on files I never touched (verified on `common.py`), so it is the environment, not this diff. The documented remedy is the repo venv first on `PATH` (`PATH=<worktree>/.venv/bin:$PATH`), which this session's shell permissions reject. Running the same suite myself with `.venv/bin/python -m pytest` gives the counts above.
2. **Documentation obligation still reported.** `compose.yaml` counts as a configuration file, so the gate wants a doc update or a `docs: none — <reason>` line. I put that line in the commit body (readable in `COMMIT_EDITMSG`), which is the documented clearing mechanism, but `procoder check` invoked directly cannot read a commit message and the repo has no procoder git hook installed (`core.hooksPath` unset, only `*.sample` hooks), so nothing routes the message to the check. Adding a doc would have to land outside `Owns`: a `CHANGELOG.md` entry under `## [Unreleased]` does clear the finding (verified), but the bake-off arm list is operator tooling with no user-facing doc, so I reverted it rather than widen scope. The lead should close this by commit-wrapper invocation or by granting `CHANGELOG.md`.

**Fix round 1 (2026-11-15), commit `1bb0c76`**

C1(a) — closed. `CHANGELOG.md` now carries one entry under `## [Unreleased]` (`### Changed`): the bake-off measures `LongCat-2.5`, the preview-suffixed model id is gone, the older entry is dropped, and the compose repair example pins the same model on the same endpoint and key variable. The `[docs]` obligation no longer blocks; the gate's only remaining blocker is the environmental python-test step, so the "gate clean" clause of criterion 2 is now short only by that one step.

One deliberate deviation from the addendum's wording: it asked the entry to name both versions. Criterion 1 forbids `longcat-2.0` / `LongCat-2.0` in docs, so the entry describes the move without reproducing the retired token — writing it literally would have reopened criterion 1. `git grep -i 'longcat-2\.0'` over tracked files matches this task file only.

C1(b) — still blocked, escalated. I tried the prescribed form, `PATH=$PWD/.venv/bin:$PATH procoder check …`, plus the literal variants `PATH=<worktree>/.venv/bin:$PATH …` and an absolute three-entry PATH. This session's shell policy rejects every command that begins with a `PATH=` assignment; the allowlisted prefixes are `procoder *`, `procoder check*`, `pytest*` and `.venv/bin/python -m pytest*`, none of which accept a leading assignment. So the venv-first run could not be produced here, and that is the escalation the addendum asked for.

What I can show is the resolution itself: `/usr/bin/pytest` cannot import the tree — `pytest tests/test_glossary_bakeoff.py -q` → `ModuleNotFoundError: No module named 'pysubs2'`, `Interrupted: 1 error during collection`; the venv can — `.venv/bin/python -m pytest tests/test_glossary_bakeoff.py tests/test_glossary_judge.py` → `156 passed in 6.70s`; full suite `.venv/bin/python -m pytest` → `38 failed, 4838 passed`, the same 38 pre-existing `pysubs2`-subprocess failures in four files this diff does not touch. Gate: `4 clean, 1 unformatted, 0 unchecked, 0 out of scope, 151 hygiene finding(s) (1 blocking)`.

The one `unformatted` file is `CHANGELOG.md`, and the drift is inherited, not mine: `procoder format` wants a blank line between `### Removed` and its list item, and `git show origin/main:CHANGELOG.md` has that heading immediately followed by the item (byte-identical at that region). My added `### Changed` block does carry the blank line. Fixing the inherited heading would touch a line outside this task's one-line grant, so I left it.

C2 — nothing needed, and confirmed harmless: `.pytest_cache/` is in `.gitignore:4` and `git ls-files --error-unmatch .pytest_cache/v/cache/nodeids` reports it untracked, so the entry ships nowhere. It also persists across runs rather than clearing on the next one: pytest's `nodeids` cache is a union of the previously cached ids and the ones just collected, so a parametrization that no longer exists keeps its old entry. Confirmed on this tree — the file was rewritten by my final full-suite run (16:53) and still contains `test_only_decision_arms_have_a_v2[longcat-2.0@v2]`, now the only place the retired name appears anywhere in the working tree. Clearing it takes `pytest --cache-clear`; it changes no shipped file, so per the addendum I did not act on it.

C3 — yes, resume state can mix the two models, and the operator must start a fresh results file for that arm. Mechanism: `_load_done` (`tools/glossary_bakeoff.py:754`) keys state on `(id, arm, order)` only, and `cmd_run` builds the same key at `:863`; the row written at `:888` is `{"id", "arm", "order", **framing, **body}`, and a text arm's `body` comes from `_verify_text`/`_acquire_text` (`:580`, `:589`), which call `_row` with `raw, parsed, latency, usage, error` and no served-model field — only decision arms carry one (`:622`, `:649`, `:667`, `:691`, `:712`). So an existing `results/longcat-2.5.jsonl` written while the arm pinned `LongCat-2.5-Preview` marks those `(id, "longcat-2.5", order)` keys done and skips them, then appends real-2.5 rows for the rest: one report, two models, indistinguishable because the arm label is unchanged. Operator action: point `--out` at a new file (for example `results/longcat-2.5-20261115.jsonl`) and pass that to `score`/`export-judge`, or archive the old one first. No code changed. A guard would not be one line inside `Owns`: it needs a served-model field on every text-arm row, and nothing on that path carries one — `bakeoff.ask_openai` returns `(text, latency)` only and `common.llm_chat` returns bare text, so `_verify_text` and `_acquire_text` (four `_row` returns, `:585-586` and `:594-596`) and the local no-call control (`:877`) would all need the field plumbed through, and the resume key plus the row-shape assertions in `tests/test_glossary_bakeoff.py` would change with it. That is a row-schema decision for the maintainer, not a one-line guard.

## Addendum (lead, 2026-11-15): fix round 1

Critic REJECT at 5017a93 (see ## Review), C1: the gate is not clean. (a) The [docs] policy blocks because `compose.yaml` (a configuration file) changed with no documentation file in the diff, and a direct `procoder check` cannot read the `docs: none` line in the commit body. Land the CHANGELOG entry (one line under the unreleased section: the bake-off and repair example move from LongCat-2.0 to LongCat-2.5) so the docs obligation clears; the Owns line now includes CHANGELOG.md. (b) The python-test step resolves `/usr/bin/pytest`, which cannot collect (no pysubs2): run the gate with the venv first on PATH (`PATH=$PWD/.venv/bin:$PATH procoder check ...`) and paste that run; if it still resolves the system pytest, say so as an escalation. C2 (stale gitignored pytest cache) needs nothing. C3: say in Result whether resume state keyed on (id, arm, order) can mix rows from LongCat-2.5-Preview and LongCat-2.5 under the same arm name, and what an operator must do (start a fresh run directory), without changing code unless it is a one-line guard inside Owns. Write a round 2 subsection under the Result heading only; one empty Evidence heading, last, that heading's text nowhere else (not even quoted). Do not push.

## Review

5017a93 reviewer @ buffy/muse-spark-1.3: PASS, no blocker or should-fix finding. Both criteria met on the reviewed SHA.

- Criterion 1 met (no 2.0 reference outside this task file): git grep for longcat-2.0 on HEAD matches only this task file's own prose; the spaced variant likewise; 2.5-Preview matches only this task file's Result prose. Code, tests, config and docs are clean.
- Criterion 2 met (bake-off and judge tests pass on the 2.5 arm): pytest on the two touched test files gives 156 passed; procoder lint on the four changed files gives 0 findings. The 38 full-suite failures are pre-existing environment failures, reproduced identically on a detached origin/main checkout (38 failed, 120 passed on the same four files on both HEAD and origin/main; cause is a bare python3 subprocess without pysubs2).
- Scope check: the diff touches only the compose comment, the bake-off arm (drops the 2.0 entry; the surviving 2.5 arm keeps the same endpoint, key variable name, extra body and delay and now pins model id LongCat-2.5), and test label renames plus the one pinned candidate-list update. No other provider or bake-off logic changed.
- Findings: two info notes, no verification failures. (1) Full-suite failures in the four untouched files are environmental and pre-date this change (verified on origin/main). (2) The gate python-step and doc-obligation escalations in the Result are environment/workflow notes, not code faults.

5017a93 critic @ command-code: REJECT, verdict file reviews/20261115-longcat-25-refs/critic-5017a93.json

Scope. I ran the read-only wrapper's `rev-parse HEAD` on the checkout and got the brief's `REVIEW_SHA` (`5017a93…`), so this review is on the named head; the reviewer's file is on the same head. I read the task file, the branch diff against `origin/main`, and the reviewer's verdict, then re-derived everything below from the code.

Reviewer findings, re-run against the code:

- **F1 — confirmed.** The 38 full-suite failures are not this diff. I did not re-run the baseline (my shell could not extract an `origin/main` tree), so I confirmed it structurally instead: the four failing files and `common.py` have byte-identical blobs at HEAD and `origin/main` (`8b219ca`, `5cdfb71`, `8d9300c`, `e9ac93c`, `cf33944`), none imports the bake-off, and every failure traces to a bare `python3` subprocess that cannot `import pysubs2` (`test_render_readme_table.py:271`, `test_mux.py:1385`). Under `.venv` the suite totals `38 failed, 4838 passed`; the two touched files give `156 passed`. The reviewer's stronger claim (a detached baseline run) is plausible but I verified the weaker, sufficient form.
- **F2 — confirmed, but its framing hides a criterion gap.** The surviving arm does keep `_LONGCAT_URL`, `LONGCATAI_API_KEY`, `{"thinking":{"type":"disabled"}}` and `delay=0.3`; lint is `0 finding(s) (0 blocking)`. The gap is that the verdict cites procoder **lint** for the "gate clean" half of the second criterion, while the house rule names `procoder check` — a different command that is not clean. That is C1.

New findings:

- **C1, should-fix, `compose.yaml:125`.** `procoder check` on the four changed files reports `2 blocking` on this SHA: the `[docs]` obligation (compose counts as config; no doc file in the diff) and the python-test step resolving `/usr/bin/pytest`. The `docs: none — …` line exists in the commit body and in `COMMIT_EDITMSG`, but a direct check cannot read a commit message and no hook forwards it (the hooks directory holds only `*.sample`, `core.hooksPath` unset), so nothing routes it to the check. The second criterion's "gate clean" clause is therefore unmet as written; this is a closeable workflow gap, not a code fault: land the CHANGELOG entry the coder reports clears the obligation, or run the gate through the commit wrapper where the message is visible. The python-test blocker is environmental — it cannot collect even one file under `/usr/bin/pytest` while the venv and CI (which installs `pysubs2`) are green.
- **C2, nit, `.pytest_cache/v/cache/nodeids:1311`.** A gitignored pytest cache entry still names the dropped arm (`test_only_decision_arms_have_a_v2[longcat-2.0@v2]`). Untracked and regenerated, so it ships nowhere; noted only because a working-tree grep over ignored paths sees it while the Result's claim is exact for tracked files.
- **C3, info, `tools/glossary_bakeoff.py:452`.** The arm keeps the name `longcat-2.5` while its pinned model id moves `LongCat-2.5-Preview` → `LongCat-2.5`. Resume state is keyed only on `(id, arm, order)` in `_load_done` (`:754`) and a text-arm row carries no served-model field, so reusing an existing `results/longcat-2.5.jsonl` would keep Preview-era rows and append 2.5 rows under the same label, mixing two models in one report. It follows from the directed pin rather than from a diff defect and the Result discloses the rename; start a fresh results file for that arm.

Hunts that came back clean: dropped-arm label collision in the judge cannot occur (labels are ordinal `LABELS[...]`, not arm names); no code defaults to the dropped name (`--baseline` defaults to `qwen-local`); no script, workflow, spec, shell file or notebook (none exist) calls the arm; the `.env` example, README, AGENTS.md and `docs/wiki/How-To-Guides.md:316` name LongCat without a version or model id; the key still appears by name only (`LONGCATAI_API_KEY`, `settings_registry.py:258`) with no value anywhere.

8e6c1e2 critic @ claude Opus 5.5: PASS, verdict file reviews/20261115-longcat-25-refs/critic-8e6c1e2.json

Head check: git-ro rev-parse HEAD = 8e6c1e2b0606d6f4af36d83352109c23b62cd67e, the brief's REVIEW_SHA, and close-gate --criteria-hash recomputes the brief's value. The fix round is 1bb0c76 (the CHANGELOG.md entry) and 8e6c1e2 (the Result). Code, tests and compose.yaml are unchanged since 5017a93. Nothing was edited except this Review text.

My round-1 findings (critic-5017a93):
- C1 (should-fix, gate not clean): fixed. (a) The CHANGELOG entry clears the docs obligation, which no longer appears in either run. (b) With the venv first on PATH, procoder check on the five changed files gives '4 clean, 1 unformatted, 0 unchecked, 0 out of scope, 150 hygiene finding(s) (0 blocking)', the lead's figure, and the python-test step passes. With the bare PATH it still blocks on the system pytest (no pysubs2). That is environmental, and the coder escalated it correctly: the shell policy refused a leading PATH= assignment in that seat.
- The unformatted CHANGELOG.md is pre-existing, as claimed. procoder format on HEAD's file differs only by one blank line after '### Removed'. procoder format on origin/main's CHANGELOG.md, extracted to my scratchpad, gives the same one-line diff. The new '### Changed' block is formatted.
- C2 (nit, stale gitignored pytest cache): answered. It ships nowhere, and I ran pytest with -p no:cacheprovider so I did not touch it.
- C3 (info, resume can mix Preview and 2.5 rows): answered accurately. I read the cited paths: _load_done keys on (id, arm, order), and the text-arm rows carry no served-model field. The operator action (a fresh --out file) is right, and the Result is right that a guard would change the row schema.

Reviewer findings (reviewer-5017a93; no reviewer verdict at this head, see C5): F1 and F2 still confirmed, since neither code nor tests changed.

Break attempts:
1. Criterion 1 re-grep at HEAD, retired token and the preview-suffixed id: no match outside .procoder.
2. Gate both ways (venv PATH and bare PATH), plus 156 passed on the two touched test files.
3. The formatter claim, checked against origin/main's bytes rather than taken from the Result: confirmed.
4. The CHANGELOG entry's accuracy against compose.yaml and the bake-off arm: true, except one loose phrase (C4).

New findings:
- C4 info, CHANGELOG.md:13. The entry does not name both versions, because criterion 1 forbids the token; I agree. It adds a heading plus the line against a one-line grant, the minimum for Keep a Changelog. 'On the same endpoint' is loose: compose leaves the URL as ${REPAIR_OPENAI_URL:-}.
- C5 info: there is no reviewer verdict at 8e6c1e2 in the reviews directory. If close-gate wants one at the closing head, it is still owed.

Both criteria are met, and no blocker or should-fix finding stands.

5137a9e reviewer @ agy Gemini 3.8 Flash high: PASS, verdict file reviews/20261115-longcat-25-refs/reviewer-5137a9e.json (seat wrote the JSON only; line added by the lead). Info: 38 full-suite failures environmental (bare python3, no pysubs2); CHANGELOG entry accurate; the one unformatted file is pre-existing drift on origin/main.

## Addendum (lead, 2026-11-15): rebase onto main for CI (no code change)

PR #60 failed CI's osv-scan on advisories in uv.lock that this task does not touch; task 20261115-osv-dep-bump fixed them (main 693ac59, PR #61). The lead rebased this branch onto that main as `chore/longcat-25-refs-r2` (the old branch was pushed, so it is not force-pushed; PR #60 is closed in favour of a new PR). One conflict, in CHANGELOG.md under Unreleased: both the dep bump's `### Security` entry and this task's `### Changed` entry are kept. Re-review needed only because the commit ids changed: check that the rebased diff against origin/main is the same change as before plus nothing else, and that the CHANGELOG keeps both entries.

## Evidence
