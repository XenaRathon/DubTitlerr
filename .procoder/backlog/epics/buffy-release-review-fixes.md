# buffy-release-review-fixes

Status: open
Created: 2026-09-24
Source Review: `docs/Adversarial Reviews/BUFFY-2026-09-24-v0-2-0-release-review.md`
Reviewed Commit: `6f6f0731ca55bde03c89d4a90d90a921e715ffa9` (main HEAD, reviewed tree)
Reviewed Tag: `v0.2.0` (annotated) → `81494f2bc1748cbd74ec1a52812d541ea8149ac2`

> This is an **untracked planning artifact** living in the canonical review checkout (the
> `fix/published-episode-titles` worktree, where the labeled reconstruction now lives). The
> reviewed `main` worktree is a _separate_ worktree and does **not** contain the original
> review or this reconstruction, so the epic is intentionally kept here. It is not committed
> unless a later decision moves it into the repo. Do not publish, tag, or commit this file as
> part of the epic's work.
> **Recovery note (2026-09-24):** This epic file was restored byte-for-byte from the prior write payload (SHA-256: `840fa2895c96495f31efee848e9911a520fe6a47f6321c0ef5eaa074646346dc`). The source review document (`docs/Adversarial Reviews/BUFFY-2026-09-24-v0-2-0-release-review.md`) is currently missing and was not fabricated. A clearly-labeled derivative reconstruction built only from this epic plus handoff context now exists at `docs/Adversarial Reviews/BUFFY-2026-09-24-v0-2-0-release-review-RECONSTRUCTED.md` — it is **not** Buffy's original text and the missing original path must not be overwritten. The verified implementation is isolated in `/home/xenarathon/claude/DubTitlerr-remediation` on local branch `fix/buffy-release-review-remediation` based on main `6f6f073`.

## Why

Buffy's adversarial review of DubTitlerr v0.2.0 (reviewed tree `6f6f073`, the `v0.2.0` tag at
`81494f2`) landed with a verdict of **HOLD: fix or retag before publication**. The review found
the `v0.2.0` tag points at an older commit whose CI failed, release workflows pushed container
images (`:v0.2.0` and `:latest`) prior to review approval, and two medium-severity reliability
defects (`mux.py` soft failures writing no stage records, and shell-quote-broken crash
classification in `merge_pass.sh`) directly contradict the project's fail-closed claims.

This epic plans the remediation of all actionable findings from Buffy's review, establishing
stable remediation IDs, clear execution boundaries, dependency orders, verification commands,
and a strict definition of done. It is a plan, not a completion report: no work is asserted as
already done.

## Scope

- **[R-1] Release Integrity & Workflow Gates (B1, B2)**
  - Address the commit delta between tag `v0.2.0` (`81494f2`) and main HEAD (`6f6f073`).
  - Add a CI-status gate so `release.yml` cannot build or publish images from a failed or
    unverified tag run. (`release.yml` is a **separate workflow** from `ci.yml`; there is no
    cross-workflow `needs: ci` — see R-1 actions.)
  - Formulate owner options for `v0.2.1` vs retargeting/force-moving `v0.2.0`.
- **[F-1] Fail-Closed Reporting & Robustness (B4, B5)**
  - Ensure `mux.py` writes a stage record on every failure exit path using an **outcome present
    in `common.STAGE_OUTCOMES`** — never `verify-*`, `failed`, or any other non-enumerated
    value — so `failed_stage()` correctly identifies mux failures.
  - Replace unsafe inline `'$stem'` Python interpolation in `merge_pass.sh` crash-classification
    invocations (lines 56, 61, 69) with env/argv passing.
  - Add regression tests covering verify-failed mux stages and apostrophe-containing filenames.
- **[R-2] Representative-Media Evidence (B3)**
  - Enforce the representative-media checklist with an explicit host guard, treating any prior
    "verification" as evidence to **revalidate** (section D of the review is unverified live-host
    evidence, not completed fact).
  - Record sanitized evidence and add a verification section to release notes.
- **[H-1] Hygiene & Documentation (B6, B7, B9)**
  - Refresh `uv.lock` to match `pyproject.toml` version `0.2.0`.
  - Close carried story tracking OSV scanning citing `azrtydxb/procoder#301`.
  - Add a dated sprint-015 correction to backlog bookkeeping.
  - Fix stale test docstrings (`tests/test_merge_pass.py`) and obsolete sentences (`CHANGELOG.md`).
- **[H-2] Deployment Alignment (B8)**
  - Verify live image pin/version and align deploy units (`deploy/dubtitlerr-publish.service`)
    with shippable image naming — but treat the "builder is `0.1.3`" claim as unverified
    (review section D item 8).

## Out of Scope

- **No Locking:** Preserving the existing no-locking doctrine (no `flock`/`fcntl`/`O_EXCL` changes).
- **No Secondary Backend:** No new model or repair backends introduced.
- **No Production Sweep:** No live container restarts or pipeline runs executed as part of epic planning.
- **No Force-Move of Public `v0.2.0` Tag:** Automated or forced public tag movement without owner consent.
- **No GHCR / Release Publication:** No pushing to GitHub Container Registry or publishing draft releases from this branch/epic.
- **No Secrets Access:** No reading `.env`, credentials, tokens, or private keys.
- **No Reopening Settled Findings:** Positive checks (raw-ASR protection, review server auth, `words.json` schema v2) and unrelated hardening work are left untouched.

## Stable Remediation IDs & Task Breakdown

### Task H-1: Repository Hygiene & Dependency Lock Sync

- **ID:** `H-1`
- **Severity / Source:** Low (B6, B7, B9)
- **Actions:**
  1. Run `uv lock` (or `uv sync`) to update `uv.lock` to match `pyproject.toml` version `0.2.0`.
  2. Mark the carried story for the OSV scanner gap as closed, referencing `azrtydxb/procoder#301`.
  3. Add a dated correction to the sprint-015 retro (the retro's "no issue exists" claim is now disproven by B7).
  4. Fix stale test docstrings in `tests/test_merge_pass.py` and obsolete sentences in `CHANGELOG.md`.
- **Verification Commands:**
  - `git diff uv.lock` (verify only version/metadata sync changes)
  - `pytest tests/test_merge_pass.py`

### Task F-1: Fail-Closed Stage Recording & Shell-Safe Crash Classification

- **ID:** `F-1`
- **Severity / Source:** Medium (B4, B5)
- **Actions:**
  1. In `mux.py`'s `process()`, write a stage record on every failure exit path **using an
     outcome from `common.STAGE_OUTCOMES`** (the enumerable failure set is: `llm-empty`,
     `backend-unreachable`, `extract-error`, `build-error`, `no-video`, `timeout`,
     `crashed`, `unwritable`). Prescribe the following mapping:
     - **Mux verification failures** (`return "verify-" + res`, currently `mux.py:488`):
       map to `build-error` with a sanitized `detail` such as `verify:<reason>` (e.g.
       `verify:duration-mismatch`). Do **not** write `verify-*` or `failed` — those are not
       in `STAGE_OUTCOMES` and `write_stage` would raise `ValueError`.
     - **Unexpected exceptions** (currently `return "error"`, `mux.py:528`): map to
       `crashed` with a **sanitized** detail (no full stack/traceback, no file paths that
       could leak library layout). The bare `"error"` string is not a valid stage outcome.
     - **Signs-regression refusal** (`return "signs-regression-refused"`, `mux.py:463`):
       record using an allowed failure outcome (e.g. `build-error` with detail
       `signs-regression-refused`) so the refusal is visible to `failed_stage()`.
  2. Refactor `merge_pass.sh` crash-classification Python one-liners (`merge_pass.sh:56,61,69`)
     to receive `$stem` via environment variable (`STEM="$stem" python3 -c '...'`) instead of
     direct string interpolation, removing the `SyntaxError`/injection surface for
     apostrophe-containing filenames.
  3. Add robust unit/integration tests for:
     - A verify-failed mux recording is correctly captured by `failed_stage()` (assert
       `failed_stage(stem)` returns non-`None`; assert no `ValueError` is raised by
       `write_stage`).
     - Apostrophe-containing filenames (`JoJo's Bizarre Adventure - S01E01`) handled without
       `SyntaxError` and without writing a bogus record.
- **Acceptance Criterion:** `process()` never raises `ValueError` from `write_stage` (every
  failure path uses a real `STAGE_OUTCOMES` value), and `failed_stage(stem)` returns non-`None`
  for a verify-failed mux. The shell fallback writes no record for an apostrophe stem.
- **Verification Commands:**
  - `pytest tests/test_mux.py tests/test_merge_pass.py`
  - `bash -n merge_pass.sh`

### Task R-1: Release Integrity & Workflow CI Gate

- **ID:** `R-1`
- **Severity / Source:** Blocker / High (B1, B2)
- **Actions:**
  1. Add a CI-status gate to `release.yml` so image build/push cannot occur from a failed or
     unverified tag run. **Critical correction:** `release.yml` is a _separate workflow_ from
     `ci.yml`; GitHub Actions does **not** support a cross-workflow `needs: ci` dependency, so
     the draft's `needs: ci` prescription is invalid. Instead require an explicit, **tested**
     mechanism that proves image push cannot follow failed CI, leaving the exact mechanism as
     an implementation decision. Candidate mechanisms (pick one, and cover it with a test or
     a documented run):
     - A **reusable workflow** called by `release.yml` that re-runs the CI matrix (or a
       `workflow_call`-exposed test job) and fails the caller on any failure.
     - A **`workflow_run`** gate: a third workflow triggered on `workflow_run` of `ci` with
       `types: [completed]` that, only on `conclusion: success`, dispatches/approves the
       publish — or `release.yml` waits on a `workflow_run` check before pushing.
     - Equivalent proven approach (e.g. a required status check + a step that queries the CI
       run conclusion via the GitHub API and exits non-zero on red). The chosen mechanism must
       be demonstrated to block push on a red CI run before this task is done.
  2. Document owner options regarding public release tagging (`v0.2.1` vs retargeting).
- **Verification Commands:**
  - `actionlint .github/workflows/release.yml` (if available) or YAML syntax validation; plus
    a demonstration/run proving the gate blocks push on a failed CI conclusion.

### Task R-2 & H-2: Representative-Media Evidence & Deployment Alignment

- **ID:** `R-2`, `H-2`
- **Severity / Source:** Medium / Low (B3, B8)
- **Actions:**
  1. Run/verify the representative-media checklist with an explicit host guard (`hostname`
     matches expected host or test mock). **Treat the review's Section D claims (T12 outputs on
     vm102, VAD backend, the `0.1.3` builder pin, etc.) as unverified evidence to revalidate,
     not as completed facts** — SSH to the live host was refused during review, so all live-host
     claims are unconfirmed.
  2. Append sanitized verification evidence to release notes.
  3. Align `deploy/dubtitlerr-publish.service` image pin with current release tagging
     nomenclature; record the pair in the vault note, verifying the live pin rather than
     assuming the "builder `0.1.3`" claim.
- **Verification Commands:**
  - `pytest` (project test command; runs the suite per `pyproject.toml` `testpaths = ["tests"]`)
  - Host-guard / representative-media checklist output captured to release artifacts.

## Execution Dependency Graph

```
[H-1: Hygiene & uv.lock]
        ↓
[F-1: Fail-closed mux & shell-safe crash classification]
        ↓
[R-1: Workflow CI Gate & Release Integrity]
        ↓
[R-2 & H-2: Representative-Media Evidence & Deploy Alignment]
        ↓
[Owner Release Decision & Execution]
```

## Safety & Approval Boundaries

- **Safe in Fix Branch:** Code edits (`mux.py`, `merge_pass.sh`), test additions, `uv.lock`
  updates, doc/changelog corrections, and workflow gate hardening.
- **Owner / Live / Release Approval Required:**
  - Retagging or cutting `v0.2.1`.
  - Pushing tags or triggering production GHCR image publishes.
  - Updating live deployment services on vm102.
  - Moving `:latest` tag on public registries.

## Open Decisions

1. **v0.2.1 vs Retag:** Whether to cut `v0.2.1` incorporating the hardening fixes (recommended
   to preserve public commit history and avoid force-moving public tags) or to delete/retag
   `v0.2.0`. Left as an owner decision.
2. **CI Gate Mechanism:** Which tested cross-workflow gate (reusable workflow, `workflow_run`
   gate, or equivalent) `release.yml` adopts to prove image push cannot follow failed CI.
3. **`:latest` Timing:** Whether the release workflow should move `:latest` only after
   successful CI verification on the release tag.
4. **WatchState Credentials:** How to supply WatchState credentials for dry-run verification
   without reading secrets (using mock fixtures/env injection).
5. **Live Image Pin/Version:** Final pin version in `deploy/dubtitlerr-publish.service`,
   verified against the live host rather than assumed.

## Definition of Done

- All CI jobs (test on 3.11 + 3.13, lint, osv-scan) pass cleanly on the release branch/commit.
- `release.yml` proves, via a tested gate mechanism, that image push cannot occur after failed CI.
- New regression tests (verify-failed mux recording captured by `failed_stage()`, apostrophe
  filename safety) pass successfully; no `write_stage` `ValueError` on any failure path.
- Lockfile (`uv.lock`), documentation (`CHANGELOG.md`), and backlog bookkeeping are fully consistent.
- Representative-media evidence (checklist) is recorded in release artifacts, with Section D
  live-host claims revalidated rather than assumed.
- Tag and release strategy is explicitly approved and executed by the owner.
- Final CI and release container state audited and verified.

## Review Finding Coverage (B1–B9)

| ID  | Severity | Epic task | Note                                                                     |
| --- | -------- | --------- | ------------------------------------------------------------------------ |
| B1  | blocker  | R-1       | Tag/tree delta; retag or cut v0.2.1 (owner decision)                     |
| B2  | high     | R-1       | CI gate on `release.yml`; no unsafe cross-workflow `needs`               |
| B3  | medium   | R-2       | Representative-media evidence; Section D claims revalidated              |
| B4  | medium   | F-1       | mux writes a valid `STAGE_OUTCOMES` failure record on every failure path |
| B5  | medium   | F-1       | `merge_pass.sh` stem passed via env/argv, not `'$stem'`                  |
| B6  | low      | H-1       | `uv.lock` resynced to 0.2.0                                              |
| B7  | low      | H-1       | Carried story closed citing `azrtydxb/procoder#301`; retro corrected     |
| B8  | low      | H-2       | Deploy unit pin aligned + verified against live host                     |
| B9  | low      | H-1       | Stale docstrings / CHANGELOG sentences fixed                             |

> **Unverified-evidence note:** Section D of the source review lists ten live-host claims that
> the reviewer could not verify (SSH refused). This epic treats them as evidence to revalidate,
> not as completed facts — see R-2 and H-2 actions.
