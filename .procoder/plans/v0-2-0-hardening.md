# v0-2-0-hardening — implementation plan

Status: draft
Spec: `.procoder/specs/v0-2-0-hardening.md`

## Goal

Ship v0.2.0: a pipeline that cannot stamp a failed stage as done, a review server whose
documented posture matches its code, provenance that says which decoder produced an
episode, and a written go/no-go on timing-compare — with every live-host fact recorded
before any sweep runs.

## Architecture

`common.py` grows two small sidecar protocols (a per-episode stage-status file and a
process-level heartbeat file) that `repair.py`, `dub_signs_merge.py`, `mux.py`,
`merge_pass.sh` and `gen_loop.sh` write and that `mux.py` and `review_server.py`'s new
`/healthz` read. `mux.py` reorders its MP4 path so the stamp lands before the original is
removed. `generate.py` persists the full decoder identity in `words.json` and
`common.read_words()` compares it. `review_server.py` gates every data surface (API and
rendered page) on the token and treats an empty token as unset. Everything else in the
release is measurement, reconciliation of stale documents, and owner-run live checks
whose deliverable is a vault note.

## Sprints

Open each with `procoder sprint open "<goal>"`, pull the stories seeded from the spec's
criteria for the listed S-ids, close before opening the next. One active sprint at a time.

| Sprint | Goal                                                                                                                             | Tasks | Spec ids    |
| ------ | -------------------------------------------------------------------------------------------------------------------------------- | ----- | ----------- |
| 010    | Ground truth: CI green, Compose committed with a safe auth default, hygiene, production snapshot, scope frozen                   | 1–5   | S-1 … S-5   |
| 011    | Fail closed: stage status artifact, exit capture, signs transient vs signs-free, MP4 stamp-before-remove                         | 6–9   | S-6 … S-9   |
| 012    | Provenance and policy: decoder identity in words.json, unanchored-repair reconciliation, guard and secondary-backend closure     | 10–13 | S-10 … S-13 |
| 013    | Posture and liveness: token-gated GET and pages, REQUIRE_TOKEN, real-socket test, heartbeat + /healthz + HEALTHCHECK             | 14–17 | S-14 … S-16 |
| 014    | Measurement: timing-compare T12 on three shows, queue/publish and storage/host checklists, FFMPEG_TIMEOUT default, S&S prototype | 18–22 | S-17 … S-20 |
| 015    | Release: osv-scanner gap ledger, 0.2.0 release controller                                                                        | 23–24 | S-21 … S-22 |

Sprint 014's owner/live tasks (18, 20, 21) can run in parallel with 011–013 whenever the
owner is at a host; nothing in them depends on the code sprints.

## Opening each sprint

The backlog epic `v0-2-0-hardening` holds 58 stories seeded from the spec's criteria; each
story's description names its S-id, task and sprint. Open a sprint and pull its stories with
the block below (sprint numbers are assigned by `sprint open`; the next free one is 010).

Sprint 010:

```sh
procoder sprint open "Ground truth: CI green, Compose committed with a safe auth default, hygiene ledger cleared, production snapshot taken, v0.2.0 scope frozen"
procoder sprint pull \
  20260921-ruff-check-tests-test-gen-loop-set-e-py-prints-all-checks \
  20260921-git-merge-base-is-ancestor-github-main-head-succeeds-and \
  20260921-python3-m-pytest-tests-test-review-apply-py-q-passes \
  20260921-git-ls-files-compose-yaml-env-example-lists-both-currently \
  20260921-with-review-token-set-the-compose-default-shape-review \
  20260921-readme-md-s-review-server-section-and-security-md-both \
  20260921-git-status-porcelain-shows-no-untracked-entry-for-craftsman \
  20260921-a-vault-note-exists-homelab-projects-dubtitlerr-date \
  20260921-changelog-md-contains-a-0-2-0-unreleased-heading-listing
```

Sprint 011:

```sh
procoder sprint open "Fail closed: stage status artifact, merge_pass exit capture, signs transient vs signs-free, MP4 stamp-before-remove"
procoder sprint pull \
  20260921-common-write-stage-stem-repair-ok-then-common-read-stages \
  20260921-common-failed-stage-stem-returns-none-when-every-recorded \
  20260921-fixture-runs-of-repair-py-dub-signs-merge-py-and-mux-py \
  20260921-a-forced-llm-unreachable-path-in-repair-py-repair-py-853 \
  20260921-merge-pass-sh-captures-rc-immediately-after-each-of-the \
  20260921-with-two-fixture-episodes-one-forced-to-a-failed-stage-the \
  20260921-with-zero-failed-stages-the-script-prints-exactly-merge \
  20260921-given-a-prior-ass-sidecar-containing-at-least-one-non \
  20260921-a-genuinely-signs-free-episode-no-prior-ass-dub-signs-merge \
  20260921-for-an-mp4-m4v-source-with-a-monkeypatched-write-stamp-that \
  20260921-an-mkv-source-orig-final-never-calls-os-remove-on-the \
  20260921-readme-md-states-the-original-mp4-m4v-container-is-deleted \
  20260921-two-new-tests-pass-one-with-an-unwritable-stamp-path-one
```

Sprint 012:

```sh
procoder sprint open "Provenance and policy: decoder identity in words.json, unanchored-repair reconciliation, phonetic guard and secondary backend closed"
procoder sprint pull \
  20260921-common-words-schema-version-2-a-freshly-written-words-json \
  20260921-generate-decoder-identity-returns-model-model-initial \
  20260921-common-read-words-stem-expect-generate-decoder-identity \
  20260921-a-words-json-with-transcribe-version-greater-than-common \
  20260921-common-py-s-stamp-docstring-documents-same-size-same-mtime \
  20260921-decisions-load-for-the-relevant-one-pace-show-shows-all-45 \
  20260921-handoff-md-183-185-is-marked-superseded-in-place-dated \
  20260921-docs-wiki-how-to-guides-md-44-and-reference-md-106-no \
  20260921-issue-phonetic-name-guard-md-has-a-status-header-naming \
  20260921-improvements-md-5-architecture-two-backend-repair-is-absent
```

Sprint 013:

```sh
procoder sprint open "Posture and liveness: token-gated API and pages, REQUIRE_TOKEN, real-socket test, heartbeat + /healthz + HEALTHCHECK"
procoder sprint pull \
  20260921-review-server-authorised-get-none-returns-false-for-a-path \
  20260921-with-require-token-1-and-review-auth-off-both-set-review \
  20260921-the-token-box-js-sets-a-dubtitlerr-token-cookie-next-to-the \
  20260921-security-md-s-review-server-section-matches-the-new-get \
  20260921-a-test-starts-review-server-on-port-0-in-a-background \
  20260921-a-client-that-stalls-its-body-write-is-disconnected-at \
  20260921-opening-max-concurrent-1-simultaneous-connections-results \
  20260921-common-heartbeat-writes-common-heartbeat-path-atomically \
  20260921-get-healthz-returns-503-independently-for-each-of-a-stale \
  20260921-dockerfile-builder-contains-the-exact-healthcheck \
  20260921-the-autoheal-actuator-question-is-recorded-as-a-live-host
```

Sprint 014:

```sh
procoder sprint open "Measurement: timing-compare T12 on three shows, queue/publish and storage/host checklists, FFMPEG_TIMEOUT default, S&S prototype"
procoder sprint pull \
  20260921-tools-timing-compare-py-produces-docs-timing-compare-date \
  20260921-specs-timing-compare-tasks-md-shows-t1-t11-checked-and-no \
  20260921-a-vault-note-records-systemd-analyze-verify-output-the \
  20260921-a-vault-note-records-the-confirmed-single-active-worker \
  20260921-python3-c-import-generate-assert-generate-ffmpeg-timeout \
  20260921-tools-sns-extract-py-exists-imports-only-dub-signs-merge \
  20260921-programmatic-pysubs2-ssaevent-fixtures-covering-a-genuine \
  20260921-a-false-positive-inventory-file-exists-under-docs-beta
```

Sprint 015:

```sh
procoder sprint open "Release: osv-scanner gap ledger and the 0.2.0 release controller"
procoder sprint pull \
  20260921-a-tracked-issue-github-issue-or-procoder-backlog-entry \
  20260921-agents-md-documents-the-local-bin-osv-scanner-shim-as-host \
  20260921-pyproject-toml-s-version-field-reads-0-2-0 \
  20260921-changelog-md-s-0-2-0-section-carries-a-release-date-and-the \
  20260921-procoder-release-0-2-0-completes-clean-version-sync \
  20260921-the-release-note-records-verification-against \
  20260921-procoder-check-is-clean-and-the-full-suite-passes-on-the
```

## Owner decisions assumed by this plan

Each is written into the spec as a decision with a recommended default. Confirm or
overturn them when sprint 010 opens; an overturned one changes the task named.

1. **Review server bind stays `0.0.0.0`** (Task 14). Loopback inside a container makes the
   published port unreachable; the token, now required for every data surface, is the boundary.
2. **`REVIEW_AUTH=off` is the only way to disable auth; an empty `REVIEW_TOKEN` means
   "generate one"** (Task 2). Breaks any install that relied on an explicitly empty token to
   disable auth; the startup log names the change.
3. **`REPAIR_UNANCHORED=1` stays global** (Task 12). The v10 TEXT bump already paid for the
   library-wide re-derive; flipping it off would cost another. Recovery is a `reject` verdict
   plus `review_apply.py`, recorded in the vault note.
4. **Same-size/same-mtime media replacement is documented as the immutable-media
   assumption, not hashed** (Task 11).
5. **`REPAIR_BACKEND_SECONDARY` is retired, not built** (Task 13). Three prior reviews
   recommended retiring the doc section; `REPAIR_MODEL_SECONDARY` covers the two-pass check.
6. **`ISSUE-s32e02-timing.md` is committed** next to the other `ISSUE-*.md` files (Task 3).

## Constraints

Copied from the spec; every task inherits these.

- Tests: `python3 -m pytest` from the repo root (pyproject sets `-q` and `testpaths`).
  Baseline on this branch at `1e8eaaa`: **1,705 passed**. CI installs only
  `pytest pysubs2 jellyfish`; `faster_whisper` is stubbed in `tests/test_generate.py` and
  `webrtcvad` is monkeypatched in `tests/test_vad.py`. A new test may need nothing else.
- `ruff check .` must print `All checks passed!` (config in pyproject). `procoder check`
  blocks a commit on lint, a red suite, AI-attribution trailers, or an unanswered question
  in `.procoder/ask/QA.md`.
- Sidecar writes are temp file + `os.replace`, mode `common.SIDECAR_MODE`, path through
  `common.out_for()`; existence checks use the raw path. Stale sidecars are parked
  (`.stale`), never deleted.
- `TRANSCRIBE_VERSION = 4` and `TEXT_VERSION = 11` do not change in this release. A
  TRANSCRIBE bump re-transcribes 860 episodes on GPU.
- The production worker is never started to test; fixtures only. A diagnostic `docker run`
  against the pipeline image passes `--entrypoint` (`container_run.sh` ignores a trailing
  command). Verify the active worker host with `docker ps` before any live command; as of
  2026-09-08 it is vm102, and it has moved three times.
- No library-wide sweep until sprints 011 and 012 have shipped and Task 4's snapshot
  confirms a single worker.
- Live-host facts (IPs, hostnames, tokens) never enter the public repo; they go to the
  vault under `Homelab/Projects/DubTitlerr/`.
- Commit subjects are conventional `type(scope): subject`, present tense, ≤ 72 chars, no
  AI-attribution trailers.
- The three interface protocols below are fixed across tasks; a task that needs a
  different name updates this plan first.
  - Stage status: `common.STAGES_SUFFIX = ".dubtitles.stages.json"`,
    `common.STAGE_OUTCOMES`, `common.write_stage(stem, stage, outcome, detail="")`,
    `common.read_stages(stem)`, `common.failed_stage(stem)`.
  - Decoder identity: `common.WORDS_SCHEMA_VERSION = 2`, `generate.decoder_identity()`,
    `common.read_words(stem, rec=None, expect=None)`, counters `words_config_mismatch`
    and `words_config_unknown`.
  - Heartbeat: `common.HEARTBEAT_PATH`, `common.heartbeat(**fields)`,
    `common.read_heartbeat()`, `GET /healthz`.

## Task 1: Get CI green and confirm the review/apply regression

Sprint: 010 Scope: [S-1]

Files: `tests/test_gen_loop_set_e.py` (ruff formatting only, no logic change).

Interfaces: none new. Consumes the existing `github` and `origin` git remotes and the
existing `tests/test_review_apply.py` suite unchanged.

Correction to the stated facts: a fresh `git fetch origin main` plus `git fetch github main`
shows `origin/main` and `github/main` are identical, both at commit
`defe1519d721ed61f5a4fdb47a186a18feece0f8`, and that commit is already an ancestor of `HEAD`
(`1e8eaaa`) — the branch needs no merge or rebase to be even with the real, pushed `main` that
GitHub Actions builds against. The local `main` branch (`2f8ae8056ea67452f22d4cf1cbfc24ea4445503c`)
is one commit ahead of both remotes with an unrelated, never-pushed commit (subject
`docs(IMPROVEMENTS): note Jev-1.13 as a tier-C adjudicator candidate`, touches only
`IMPROVEMENTS.md`) — that commit is local-only housekeeping, not part of the real GitHub
`main`, and must not be pulled into this branch. `.procoder/state/handoff.md` already records
this precisely: `branch: fix/published-episode-titles — 2 ahead, 1 behind main` and
`head: 1e8eaaa` — the "1 behind" is against the stale local `main`, not the pushed one. The
remote branch `fix/published-episode-titles` (same SHA on both remotes) is currently at
`c157b5219754e7d70b0312623054036df0dd1602`, three commits behind local `HEAD` (`defe151`,
`7e3d106`, `1e8eaaa`) — pushing is a normal fast-forward, not a new branch.

- [ ] Confirm the ruff failure matches what's expected. Run `ruff check .` and expect this
      output:

  ```
  I001 [*] Import block is un-sorted or un-formatted
    --> tests/test_gen_loop_set_e.py:21:1
     |
  19 |   """
  20 |
  21 | / import re
  22 | | from pathlib import Path
     | |________________________^
  help: Organize imports
     |
  23 |
     -
  24 | GEN_LOOP = Path(__file__).resolve().parent.parent / "gen_loop.sh"
     |

  W292 [*] No newline at end of file
    --> tests/test_gen_loop_set_e.py:144:14
      |
  142 |                 f"them and reintroduce the silent-skip failure mode.\n"
  143 |                 f"Following lines:\n{following}"
  144 |             )
      |              ^
  help: Add trailing newline

  Found 2 errors.
  [*] 2 fixable with the --fix option.
  ```

- [ ] Fix it. Run `ruff check --fix tests/test_gen_loop_set_e.py`. This only reorders the
      existing `import re` / `from pathlib import Path` block and adds the missing trailing
      newline after line 144's closing parenthesis — no code line changes.

- [ ] Run `ruff check .` and expect exactly `All checks passed!` with exit code 0.

- [ ] Run `python3 -m pytest tests/test_gen_loop_set_e.py -q` and expect `3 passed` (the file
      still has 3 test functions — confirm with `grep -c "^def test_" tests/test_gen_loop_set_e.py`
      returning `3`), proving the reformat changed no behavior.

- [ ] Commit: `git commit -m "style(tests): fix import order and trailing newline"`.

- [ ] Regression check (note item 5, closed, verify-only — do not modify `review_apply.py` or
      `card_split.py`). Run `python3 -m pytest tests/test_review_apply.py -q` and expect
      `18 passed` (matches `grep -c "^def test_" tests/test_review_apply.py` returning `18`).
      This re-confirms `test_a_rejection_reopens_because_it_reverts_a_repair_that_already_shipped`
      and the shared card_split word-window contract still hold. If anything here fails, stop
      and open a new issue instead of touching `review_apply.py` in this task.

- [ ] Verify there is nothing to reconcile against the real PR base. Run:

  ```
  git fetch origin main
  git fetch github main
  git rev-parse origin/main github/main
  ```

  Expect both lines to print the same SHA (`defe1519d721ed61f5a4fdb47a186a18feece0f8` as of
  2026-09-21 — re-verify the literal value at execution time, since main may have advanced by
  then). Then run `git merge-base --is-ancestor origin/main HEAD && echo already even` and
  expect `already even`.

- [ ] Merge (not rebase) anyway, as the housekeeping step that makes the even-ness explicit in
      history rather than merely asserted:
      `git merge origin/main -m "merge: sync with the pushed main before opening the PR"`.
      Expect `Already up to date.` and no new commit, since the fast-forward relation already
      holds. Rebase is the wrong tool here regardless of outcome:
      `.procoder/state/handoff.md` records `head: 1e8eaaa` and
      `index: built at 1e8eaaa (104 files, 2737 symbols) — current` — a rebase changes
      `1e8eaaa`'s hash and immediately desyncs that recorded state from the real branch tip,
      for a repo where nothing needed reconciling anyway.

- [ ] Push: `git push github fix/published-episode-titles`. Expect a normal fast-forward
      update report showing the range from `c157b52` to the new tip, not a "new branch"
      report — the remote branch already exists at `c157b52` on both `origin` and `github`.

- [ ] Watch CI. Run `gh run list --repo XenaRathon/DubTitlerr --branch fix/published-episode-titles --limit 3`,
      then `gh run watch --repo XenaRathon/DubTitlerr <run-id>` using the newest run id from
      that list. Expect the `lint` job — the one that was red on `main` over the same
      `ruff check .` I001/W292 failures — to pass, along with the rest of the workflow.
      Record the concluded run's URL for the PR body.

- [ ] Open the PR. Run:

  ```
  gh pr create --repo XenaRathon/DubTitlerr \
    --base main --head fix/published-episode-titles \
    --title "fix: published episode titles, timeout verify fix, and review-auth hardening" \
    --body-file pr-body.md
  ```

  where `pr-body.md` contains:

  ```markdown
  ## Summary

  - Publish uses the show/season/episode title, not the raw media filename (see CHANGELOG).
  - gen_loop.sh's VERIFY_TIMEOUT no longer takes the container down under set -e.
  - Hotfix: 3.75x dialogue scale on PlayRes-mismatch.
  - review_server: an explicitly empty REVIEW_TOKEN is now treated as unset; only
    REVIEW_AUTH=off disables auth (see SECURITY.md).
  - compose.yaml and .env.example are committed for the first time.

  ## Test plan

  - [x] ruff check . -- All checks passed!
  - [x] python3 -m pytest tests/test_review_apply.py -q -- 18 passed
  - [x] python3 -m pytest tests/test_review_server.py -q -- 82 passed
  - [x] CI green on this branch (see linked run above)
  ```

  Open the PR only after Tasks 2 and 3 have been committed and pushed to the same branch
  (the body above describes their changes); the PR is opened for the owner to merge by
  hand — do not merge it from this task.

## Task 2: Fix the review server's auth default and commit the Compose example

Sprint: 010 Scope: [S-2]

Files: `review_server.py` (module docstring, `auth_required()`, and `announce_token()`'s
docstring and log text — behavior and wording only, no route changes), `tests/test_review_server.py`
(replace one now-wrong test, add two new ones, update two warning tests), `README.md` (lines
193-199 replaced), `SECURITY.md` (lines 16-25 replaced), `compose.yaml` (add one env line,
plus committing the file for the first time — it is currently untracked), `.env.example` (add
a commented block, plus the same first-commit), `docs/wiki/Reference.md` (one new table row
plus the Authentication table's third row corrected).

Interfaces: `review_server.auth_required(token_dir: str = "") -> bool` — new semantics:
returns `False` only when `os.environ.get("REVIEW_AUTH") == "off"`; an empty or unset
`REVIEW_TOKEN` no longer affects it. `token_dir` stays an unused parameter for call-site
compatibility (it was already unused in the current implementation). Sprint 013's
`authorised()` and `REQUIRE_TOKEN` work (Tasks 14-17) builds on this directly — do not change
`auth_required()`'s name or return type there.

First, close the real packaging gap. `compose.yaml` and `.env.example` exist in the working
tree (`git status --porcelain` shows `?? compose.yaml` and `?? .env.example`) but have zero
commit history on any branch, even though `README.md:127-128` tells a fresh cloner to use
them. Commit them as-is before editing them further, so the "these files never existed on any
branch" gap is closed independently of the auth fix below.

- [ ] `git add compose.yaml .env.example`

- [ ] Commit: `git commit -m "chore(deploy): commit the Compose example files"` (these were
      never committed before; this step alone fixes a real fresh-clone breakage).

Now the auth fix. Current code, `review_server.py:138-140`:

```python
def auth_required(token_dir: str = "") -> bool:
    """False ONLY when REVIEW_TOKEN is present in the environment and empty."""
    return not ("REVIEW_TOKEN" in os.environ and os.environ["REVIEW_TOKEN"] == "")
```

Running `docker compose config | grep REVIEW_` against the just-committed `compose.yaml`
prints exactly one line:

```
      REVIEW_TOKEN: ""
```

`compose.yaml`'s `REVIEW_TOKEN: ${REVIEW_TOKEN:-}` renders an unset host variable as an empty
string, and the current `auth_required()` treats that exact case as "disable auth" — so the
documented Compose install path (`cp .env.example .env && docker compose up`, no edits)
silently ships with auth off, while the plain `docker run` Quick Start (which never sets
`REVIEW_TOKEN` at all) hits the safe auto-generate branch instead. The two documented install
paths disagree on default security posture.

- [ ] Write the failing tests. In `tests/test_review_server.py`, delete the now-wrong test at
      lines 58-69, `test_an_explicitly_empty_token_disables_auth_but_unset_does_not` (it
      asserts the exact behavior being removed), and replace it with the two tests below.

  ```python
  def test_an_explicitly_empty_token_still_generates_one(tmp_path, monkeypatch):
      """An earlier version of this server treated REVIEW_TOKEN= as an opt-out of auth. Too
      many installs left it blank by accident -- a stray .env line, or Compose's
      ${REVIEW_TOKEN:-} rendering an unset variable as an empty string -- and got an
      unauthenticated root-owned endpoint without meaning to. An empty value is now treated
      exactly like an unset one: a token is still generated, and auth stays on."""
      monkeypatch.delenv("REVIEW_AUTH", raising=False)
      monkeypatch.setenv("REVIEW_TOKEN", "")
      tok = review_server.resolve_token(str(tmp_path))

      assert tok and len(tok) >= 32, "an empty REVIEW_TOKEN must still generate a real token"
      assert review_server.auth_required(str(tmp_path)) is True, "an empty REVIEW_TOKEN must not disable auth"


  def test_review_auth_off_is_the_only_way_to_disable_auth(tmp_path, monkeypatch):
      """REVIEW_TOKEN's value -- unset, empty, or set -- must never disable auth by itself.
      Only REVIEW_AUTH=off does, and it does so regardless of REVIEW_TOKEN."""
      monkeypatch.delenv("REVIEW_AUTH", raising=False)

      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      assert review_server.auth_required(str(tmp_path)) is True, "unset REVIEW_TOKEN must not disable auth"

      monkeypatch.setenv("REVIEW_TOKEN", "")
      assert review_server.auth_required(str(tmp_path)) is True, "empty REVIEW_TOKEN must not disable auth"

      monkeypatch.setenv("REVIEW_TOKEN", "hunter2")
      assert review_server.auth_required(str(tmp_path)) is True, "a real REVIEW_TOKEN must not disable auth"

      monkeypatch.setenv("REVIEW_AUTH", "off")
      assert review_server.auth_required(str(tmp_path)) is False, "REVIEW_AUTH=off is the only disable"
  ```

  Run `python3 -m pytest tests/test_review_server.py -k "still_generates_one or auth_off_is_the_only_way" -q`
  and expect `FAIL` with `AssertionError: an empty REVIEW_TOKEN must not disable auth` — both
  new tests fail against the unchanged `auth_required()`, which still returns `False` for an
  empty `REVIEW_TOKEN`.

- [ ] Also found during verification, beyond the two tests above: the existing tests at lines
      72-90, `test_a_disabled_token_on_the_wide_bind_gets_a_startup_warning` and
      `test_no_warning_when_the_bind_is_host_only_or_a_real_token_is_set`, set
      `REVIEW_TOKEN=""` to trigger `announce_token()`'s wide-bind warning — under the new
      semantics that no longer fires the warning, so these two would go red the moment
      `auth_required()` changes. Replace both with the two tests below.

  ```python
  def test_review_auth_off_on_the_wide_bind_gets_a_startup_warning(tmp_path, monkeypatch, capsys):
      """REVIEW_AUTH=off and the default 0.0.0.0 bind are each individually fine and
      documented; together they mean every write route is open to the network. That
      combination lived only in the module docstring -- an operator who finds the opt-out in
      a forum thread should see the risk in their own logs."""
      monkeypatch.setenv("REVIEW_AUTH", "off")
      review_server.announce_token(str(tmp_path), bind="0.0.0.0")
      out = capsys.readouterr().out
      assert "WARNING" in out and "0.0.0.0" in out


  def test_no_warning_when_the_bind_is_host_only_or_auth_is_on(tmp_path, monkeypatch, capsys):
      monkeypatch.setenv("REVIEW_AUTH", "off")
      review_server.announce_token(str(tmp_path), bind="127.0.0.1")
      assert "WARNING" not in capsys.readouterr().out

      monkeypatch.delenv("REVIEW_AUTH", raising=False)
      monkeypatch.setenv("REVIEW_TOKEN", "")
      review_server.announce_token(str(tmp_path), bind="0.0.0.0")
      assert "WARNING" not in capsys.readouterr().out, "an empty REVIEW_TOKEN alone must not warn -- only REVIEW_AUTH=off does"

      monkeypatch.setenv("REVIEW_TOKEN", "hunter2")
      review_server.announce_token(str(tmp_path), bind="0.0.0.0")
      assert "WARNING" not in capsys.readouterr().out
  ```

  Run `python3 -m pytest tests/test_review_server.py -k "startup_warning or auth_is_on" -q`
  and expect `FAIL` — `assert "WARNING" in out` fails because `REVIEW_AUTH=off` alone doesn't
  yet trigger the warning under the unchanged `announce_token`/`auth_required`.

- [ ] Implement minimally. Replace `review_server.py:138-140` with:

  ```python
  def auth_required(token_dir: str = "") -> bool:
      """False ONLY when REVIEW_AUTH=off. An empty REVIEW_TOKEN is treated as unset."""
      return os.environ.get("REVIEW_AUTH", "") != "off"
  ```

- [ ] Update the module docstring. Replace `review_server.py:16-24`, currently:

  ```
    REVIEW_TOKEN unset       -> a token is GENERATED, persisted 0600, and printed once.
    REVIEW_TOKEN= (empty)    -> auth disabled. Only an explicit empty value does this, and it
                                is the operator's decision about their own network.
    REVIEW_TOKEN=<value>     -> that token, and it wins over any persisted one.

  "Unset" and "set to empty" are distinguished by MEMBERSHIP in os.environ, never by
  falsiness: the entire posture rests on telling those two apart. Read routes are never gated
  ```

  with:

  ```
    REVIEW_TOKEN unset       -> a token is GENERATED, persisted 0600, and printed once.
    REVIEW_TOKEN= (empty)    -> treated exactly like unset: a token is still generated.
    REVIEW_TOKEN=<value>     -> that token, and it wins over any persisted one.
    REVIEW_AUTH=off          -> the ONLY way to disable auth. It is the operator's decision
                                about their own network, independent of REVIEW_TOKEN.

  Auth is gated on REVIEW_AUTH, never on REVIEW_TOKEN's value: a blank token left by
  accident (a stray REVIEW_TOKEN= line, or an unset Compose variable rendered empty) must
  not silently open a root-owned write endpoint. Read routes are never gated
  ```

  and replace line 7's closing sentence, currently "So an unset REVIEW_TOKEN generates one;
  only an explicitly empty REVIEW_TOKEN disables auth.", with: "So an unset OR empty
  REVIEW_TOKEN generates one; only REVIEW_AUTH=off disables auth."

- [ ] Update the startup-warning docstring. Replace `review_server.py:190-195`, currently:

  ```
      Also warns, loudly, on the one combination the module docstring calls "the operator's
      decision about their own network" but the README never mentions: an explicitly empty
      REVIEW_TOKEN (auth off) on the default 0.0.0.0 bind. The empty-token opt-out is one
      character away from the safe default, and an operator who finds it in a forum thread
      (the natural answer to "my token never arrived, I restarted before I saw it") should
      see the risk in their own logs, not only in source they may never read."""
  ```

  with:

  ```
      Also warns, loudly, on the one combination the module docstring calls "the operator's
      decision about their own network" but the README never mentions: REVIEW_AUTH=off on
      the default 0.0.0.0 bind. An empty REVIEW_TOKEN is no longer enough to trigger this --
      it is treated as unset -- so the only way an operator lands here is by setting
      REVIEW_AUTH=off on purpose, but they should still see the risk in their own logs, not
      only in source they may never read."""
  ```

- [ ] Update the startup-warning log text. Replace `review_server.py:198-203`, currently:

  ```python
          log(
              "review server: WARNING — REVIEW_TOKEN is explicitly empty (auth disabled) and "
              "REVIEW_BIND is 0.0.0.0: every write route is open to anything that can reach "
              "this port. Set REVIEW_TOKEN to a real value, or REVIEW_BIND to a host-only "
              "address, unless this network is one you fully trust."
          )
  ```

  with:

  ```python
          log(
              "review server: WARNING — REVIEW_AUTH=off (auth disabled) and REVIEW_BIND is "
              "0.0.0.0: every write route is open to anything that can reach this port. "
              "Unset REVIEW_AUTH, or set REVIEW_BIND to a host-only address, unless this "
              "network is one you fully trust."
          )
  ```

- [ ] Run `python3 -m pytest tests/test_review_server.py -q` and expect `82 passed` (81
      existing minus the 1 deleted test, plus the 2 new auth_required-focused tests, with the
      2 warning tests renamed in place: 81 - 1 + 2 = 82).

- [ ] Run `ruff check .` and expect `All checks passed!`.

- [ ] Update `README.md:193-199`. Replace this paragraph:

  ```
  The page is at `http://<host>:8842`. On first start the container logs a token; paste it
  into the box at the top once and the browser remembers it. `REVIEW_TOKEN` sets it
  explicitly; leaving it _unset_ generates one (the server runs as root and its write routes
  rewrite subtitles, so "unset" cannot mean "no auth"). Setting `REVIEW_TOKEN=` to an
  **explicitly empty** value disables auth entirely — only do this on a network you fully
  trust; the server logs a warning at startup if you do this while also bound to `0.0.0.0`
  (the default), since that combination means anything on the LAN can rewrite your subtitles.
  See [SECURITY.md](SECURITY.md) for the full auth model.
  ```

  with:

  ```
  The page is at `http://<host>:8842`. On first start the container logs a token; paste it
  into the box at the top once and the browser remembers it. `REVIEW_TOKEN` sets it
  explicitly; leaving it _unset_ generates one (the server runs as root and its write routes
  rewrite subtitles, so "unset" cannot mean "no auth"). An **explicitly empty**
  `REVIEW_TOKEN=` is treated exactly the same as unset — a token is still generated — because
  too many installs left it blank by accident. Auth is disabled only by setting
  `REVIEW_AUTH=off`; only do this on a network you fully trust, and the server logs a warning
  at startup if you do this while also bound to `0.0.0.0` (the default), since that
  combination means anything on the LAN can rewrite your subtitles. See
  [SECURITY.md](SECURITY.md) for the full auth model.
  ```

- [ ] Update `SECURITY.md:16-25`. Replace these bullets:

  ```
  - **`REVIEW_TOKEN` unset** — a token is generated, persisted `0600` beside `DECISIONS_DIR`
    (default `/config/review_token`, never inside `DECISIONS_DIR` itself, since that
    directory may later be published or synced), and printed once to the container's logs.
    Recover it later with `docker exec dubtitle-builder cat /config/review_token`. This is
    the default and requires no action.
  - **`REVIEW_TOKEN=<value>`** — use your own token instead of the generated one.
  - **`REVIEW_TOKEN=` (empty)** — disables auth entirely. This is a deliberate operator
    opt-out for a network you already trust completely, **not** something to set if you plan
    to expose the port beyond your LAN (a reverse proxy, a port-forward, a VPN with other
    members). If you do that, put your own auth in front of it instead.
  ```

  with:

  ```
  - **`REVIEW_TOKEN` unset** — a token is generated, persisted `0600` beside `DECISIONS_DIR`
    (default `/config/review_token`, never inside `DECISIONS_DIR` itself, since that
    directory may later be published or synced), and printed once to the container's logs.
    Recover it later with `docker exec dubtitle-builder cat /config/review_token`. This is
    the default and requires no action.
  - **`REVIEW_TOKEN=<value>`** — use your own token instead of the generated one.
  - **`REVIEW_TOKEN=` (empty)** — treated exactly the same as unset: a token is still
    generated. Too many operators left this blank by accident and got an unauthenticated
    root-owned endpoint without meaning to; an empty value can no longer opt out of auth.
  - **`REVIEW_AUTH=off`** — the only way to disable auth. This is a deliberate operator
    opt-out for a network you already trust completely, **not** something to set if you plan
    to expose the port beyond your LAN (a reverse proxy, a port-forward, a VPN with other
    members). If you do that, put your own auth in front of it instead.
  ```

- [ ] Add `REVIEW_AUTH` to `.env.example`, right after the existing `REVIEW_TOKEN=` line
      (currently `.env.example:41-47`):

  ```
  # --- Repair-review web UI auth --------------------------------------------
  #
  # Leave unset (blank here) to auto-generate a token at startup (printed to
  # the log once, also readable at $CONFIG_ROOT/review_token). Set to a
  # non-empty value to pin it. An explicitly empty REVIEW_TOKEN no longer
  # disables auth -- it is treated the same as unset. See SECURITY.md.
  REVIEW_TOKEN=

  # Auth is disabled ONLY by setting this to "off" -- do this only on a network
  # you fully trust. Leave commented (unset) to keep auth on. See SECURITY.md.
  #REVIEW_AUTH=off
  ```

- [ ] Add `REVIEW_AUTH` to `compose.yaml`'s `environment:` block, right after the existing
      `REVIEW_TOKEN: ${REVIEW_TOKEN:-}` line (currently `compose.yaml:64-66`):

  ```yaml
  # --- repair-review web UI auth — leave REVIEW_TOKEN unset (or blank) to
  # auto-generate a token at startup (printed to the log, also readable at
  # /config/review_token). An explicitly empty REVIEW_TOKEN no longer
  # disables auth -- only REVIEW_AUTH=off does. See SECURITY.md. ---
  REVIEW_TOKEN: ${REVIEW_TOKEN:-}
  REVIEW_AUTH: ${REVIEW_AUTH:-}
  ```

- [ ] Add a `REVIEW_AUTH` row to `docs/wiki/Reference.md`'s "Review server" table, right after
      the existing `REVIEW_TOKEN` row (currently `docs/wiki/Reference.md:164`):

  ```
  | `REVIEW_AUTH`           | _(unset)_                        | Set to `off` to disable auth entirely -- see Authentication below |
  ```

  and replace the Authentication table's third row (currently `docs/wiki/Reference.md:280-284`):

  ```
  | `REVIEW_TOKEN`          | Behaviour                                                               |
  | ----------------------- | ----------------------------------------------------------------------- |
  | Unset                   | A token is **generated**, persisted `0600`, and printed to the log once |
  | Set to a value          | That value is the token                                                 |
  | Set to the empty string | **Auth disabled.** Only an explicit empty value does this               |
  ```

  with:

  ```
  | `REVIEW_TOKEN`          | Behaviour                                                               |
  | ----------------------- | ----------------------------------------------------------------------- |
  | Unset                   | A token is **generated**, persisted `0600`, and printed to the log once |
  | Set to a value          | That value is the token                                                 |
  | Set to the empty string | Treated the same as unset -- a token is still generated                 |

  Auth is disabled only by setting `REVIEW_AUTH=off` -- an operator decision about their own
  network, independent of `REVIEW_TOKEN`.
  ```

- [ ] `git add compose.yaml .env.example`

- [ ] Verify the Compose default no longer diverges from the `docker run` Quick Start. Run
      `docker compose config | grep REVIEW_` and expect exactly:

  ```
        REVIEW_TOKEN: ""
        REVIEW_AUTH: ""
  ```

  Both render empty because neither is set in the shell — and per the fix above, neither
  value now disables auth; only the literal string `off` in `REVIEW_AUTH` would.

- [ ] `git add review_server.py tests/test_review_server.py README.md SECURITY.md docs/wiki/Reference.md`

- [ ] Commit: `git commit -m "fix(review): treat an empty REVIEW_TOKEN as unset; REVIEW_AUTH=off is the only disable"`.

## Task 3: Classify and clean up the untracked/modified hygiene ledger

Sprint: 010 Scope: [S-3]

Files: `.gitignore` (two new entries), `docs/agents/domain.md`, `docs/agents/issue-tracker.md`,
`docs/beta-feedback/2026-09-07-r-animedubs.md`, the 8 files under `docs/promo/v0.1.0/`,
`ISSUE-s32e02-timing.md`, `.procoder/github/LESSONS.md` (already modified in the working
tree, +21 lines).

Interfaces: none.

This task assumes Tasks 1 and 2 already ran and committed their own files (the ruff fix, and
`compose.yaml` / `.env.example` / `review_server.py` / the doc updates) — the commands below
only handle what is left after that.

Correction to the stated facts: `git stash show --stat stash@{0}` does not show "only
`tests/test_export_reviewed.py`" — it shows two files:

```
 tests/test_export_reviewed.py | 186 ++++++++++++++++++++++++++++++++++++++++++
 tools/export_reviewed.py      | 146 +++++++++++++++++++++++++++++++++
 2 files changed, 332 insertions(+)
```

Both are superseded, not just the test file: `git ls-files tests/test_export_reviewed.py tools/export_reviewed.py`
prints both paths (both tracked, both landed in commit `7ab366f feat(export): the
qualifying-episode manifest for the subtitle release`, at 273 and 141 lines respectively —
larger and different from the stashed drafts). The stash is fully superseded on both files,
not partially.

- [ ] Confirm the current hygiene ledger matches what this task expects. Run
      `git status --porcelain` and expect exactly:

  ```
   M .procoder/github/LESSONS.md
  ?? .craftsman-baseline.json
  ?? .lycheecache
  ?? ISSUE-s32e02-timing.md
  ?? docs/agents/
  ?? docs/beta-feedback/
  ?? docs/promo/
  ```

  (`compose.yaml`, `.env.example`, `review_server.py`, `tests/test_review_server.py`,
  `README.md`, `SECURITY.md`, `docs/wiki/Reference.md`, and `tests/test_gen_loop_set_e.py` no
  longer appear here, because Tasks 1-2 already committed them.)

- [ ] Classify `.craftsman-baseline.json` (277 KB) and `.lycheecache` as host-local caches
      that must never be committed. `.craftsman-baseline.json` is a `procoder maintain`
      complexity-baseline snapshot whose own content is dominated by paths under
      `.claude/worktrees/` and virtualenvs — confirmed by `head -c 500 .craftsman-baseline.json`
      showing `.claude/worktrees/frontend-review-expansion/...` as its first two entries — and
      `.lycheecache` is the lychee markdown-link-checker's local cache. Append to
      `.gitignore` (which currently ends after the `docs/asr-bakeoff/*-report.json` line),
      matching the file's existing per-block comment style:

  ```
  # procoder maintain: a local complexity/lint baseline snapshot regenerated from a full
  # scan (worktrees and venvs included), never a project artifact.
  .craftsman-baseline.json

  # lychee (markdown link checker) cache -- regenerated per run, host-local.
  .lycheecache
  ```

- [ ] `git add .gitignore`

- [ ] Commit: `git commit -m "chore(hygiene): ignore the local craftsman baseline and lychee cache"`.

- [ ] Classify everything else as commit (owner default: keep). `docs/agents/domain.md` and
      `docs/agents/issue-tracker.md` have no topical overlap with `AGENTS.md` and were never
      generated from it (confirmed: no `.cursorrules`, `.windsurfrules`, or nested `CLAUDE.md`
      exist in this repo) — they are original content, not stale generated drift, so they are
      committed as-is. `docs/beta-feedback/2026-09-07-r-animedubs.md` and the 8 files under
      `docs/promo/v0.1.0/` are real, already-finished beta-feedback and promo-copy artifacts.
      `ISSUE-s32e02-timing.md` is an open issue tracked as a plain root-level file, matching
      the existing `ISSUE-*.md` convention — commit it so it is visible on `main`, not just on
      a laptop. Run `git add docs/agents/ docs/beta-feedback/ docs/promo/ ISSUE-s32e02-timing.md .procoder/github/LESSONS.md`.

- [ ] Commit: `git commit -m "docs: commit agent rules, beta feedback, promo copy, and a lesson"`.

- [ ] Resolve the stash. Run `git stash show --stat stash@{0}` and expect the 2-file,
      332-insertion stat shown above. Then run
      `git ls-files tests/test_export_reviewed.py tools/export_reviewed.py` and expect both
      paths printed, confirming both are already tracked and superseded. Then run
      `python3 -m pytest tests/test_export_reviewed.py -q` and expect all tests in that file
      to pass against the in-tree `tools/export_reviewed.py`, confirming the committed
      version — not the stashed draft — is the live one. Then drop it:
      `git stash drop stash@{0}`, expecting `Dropped stash@{0} (<sha>)`.

- [ ] Re-sync the per-editor rule files. The commit gate blocks on these today: `procoder check`
      reports 12 rule files as "drifted from AGENTS.md" (`.cursor/rules/procoder.mdc`,
      `.windsurf/rules/procoder.md`, `.clinerules/procoder.md`, `.kilo/rules/procoder.md`,
      `.kilocode/rules/procoder.md`, `.roo/rules/procoder.md`, `.kiro/steering/procoder.md`,
      `.agents/rules/procoder.md`, `.qoder/rules/procoder.md`, `.github/copilot-instructions.md`,
      `.codex/AGENTS.md`, `skills/procoder/SKILL.md`; six of them are tracked). The weekly
      note's "there is no editor-rule drift" claim was checked against the wrong files. Run
      `procoder agents`; for every block it prints as `DRIFTED — rewrite <path> with:`, write
      the printed content to that path verbatim (it is `AGENTS.md` wrapped in each host's
      front matter). Then run `procoder agents` again and expect every host reported as
      `in sync`, and `procoder check` to list zero `(agents)` findings.

- [ ] `git add` the twelve rule files and commit:
      `git commit -m "chore(agents): resync per-editor rule files with AGENTS.md"`.

- [ ] Verify the tree is clean. Run `git status --porcelain` and expect no output (empty
      string).

## Task 4: Production snapshot (OWNER/LIVE)

Sprint: 010 Scope: [S-4]

Files: a new vault note at
`/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/2026-09-22 Production Snapshot.md`.
No repository files change; this is a read-only live-environment check. Live-host facts
(IPs, hostnames, the review token's actual value) go only into that vault note, never into
this plan or any other file in this repository — commands below reference the worker host
generically because `AGENTS.md`'s own "Where this actually runs" section warns it has moved
three times already and to verify with `docker ps` rather than trust a remembered address.

Interfaces: none (the deliverable is the note, not code).

- [ ] Resolve the current worker host per `AGENTS.md`'s "Where this actually runs" section,
      then confirm it live rather than trusting the doc:
      `ssh <candidate-host> docker ps --filter name=dubtitle-builder --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'`.
      Record in the note, under a heading "Active worker": the resolved host/IP and the
      literal Names/Image/Status/Ports line — empty output means no worker is running there;
      record that too, it is a valid and important finding.

- [ ] Confirm no concurrent worker exists elsewhere — this repo has already had two workers
      race against the same library once, the 2026-09-08 fasc incident. Run the same
      `docker ps --filter name=dubtitle-builder ...` command against every other host that has
      ever run this container. Record under "Concurrent-worker check": each host checked and
      its result; expect empty output on all but the one confirmed active worker. If any other
      host shows a running `dubtitle-builder`, stop — do not proceed to any sweep — and
      escalate to the owner instead of silently stopping it from this note.

- [ ] Record the deployed review-server posture. On the active worker host, run:
      `ssh <worker-host> docker exec dubtitle-builder printenv | grep -E '^(REVIEW_BIND|REVIEW_PORT|REVIEW_AUTH)='`;
      and, without ever printing the token's own value into the note:
      `ssh <worker-host> docker exec dubtitle-builder sh -c "[ -n \"$REVIEW_TOKEN\" ] && echo set-via-env || echo not-set-via-env"`;
      and `ssh <worker-host> docker exec dubtitle-builder test -f /config/review_token && echo file-present || echo file-absent`.
      Record under "Review server posture": bind address, port, the `REVIEW_AUTH` value
      (expected unset/absent, since Task 2 has not shipped to this host yet — that is the
      correct pre-deploy state, not a bug), whether `REVIEW_TOKEN` is set via env, and whether
      the persisted token file exists.

- [ ] Record the deployed config paths:
      `ssh <worker-host> docker exec dubtitle-builder printenv | grep -E '^(ANIME_ROOT|MERGE_ROOTS|MUX_ROOTS|DECISIONS_DIR|GLOSSARY_DIR|ANIME_ORDER)='`.
      Record verbatim under "Deployed config".

- [ ] Compare the queue's deployed order file against what `watch_queue.py` would currently
      produce — a mechanical drift check only; item 8's pin-validation logic itself is already
      fixed and is not being re-verified here. `watch_queue.py --dry-run` prints a numbered
      list to stdout and writes nothing (`watch_queue.py:259-263`: it loops
      `for i, d in enumerate(order, 1): print(f"  {i:>2} {d}")`, then under `--dry-run` prints
      "(dry run -- nothing written)" and returns before ever touching `--out`) — so `--out`
      has no effect together with `--dry-run` and must not be passed expecting a file written.
      Two ways to get the comparison; use whichever the host supports and record which one was
      actually used.

  Inside the container:

  ```
  ssh <worker-host> docker exec dubtitle-builder sh -c "python3 watch_queue.py --dry-run | sed -En 's/^ *[0-9]+ //p' > /tmp/dry-run-order.txt; diff /tmp/dry-run-order.txt /config/anime_order.txt; echo DIFF_RC=\$?"
  ```

  On the host, reading the file directly (the config bind-mount and app-checkout host paths
  come from `deploy/dubtitlerr-publish.service`: `/home/claude/dubtitle-config` and
  `/home/claude/DubTitlerr` — verify these still match with
  `ssh <worker-host> systemctl cat dubtitlerr-publish.service` before trusting them, since
  they are declared once in a unit file, not read live):

  ```
  ssh <worker-host> sh -c "cd /home/claude/DubTitlerr && python3 watch_queue.py --root '/mnt/r520-media-full/Anime Library' --dry-run | sed -En 's/^ *[0-9]+ //p' > /tmp/dry-run-order.txt; diff /tmp/dry-run-order.txt /home/claude/dubtitle-config/anime_order.txt; echo DIFF_RC=\$?"
  ```

  Record under "Queue drift": which method was used, the literal diff output (or "no diff,
  DIFF_RC=0"), and the current `anime_order.txt` show count.

- [ ] Verify the publish timers are installed and valid:
      `ssh <worker-host> systemctl list-timers dubtitlerr-publish.timer` and
      `ssh <worker-host> systemd-analyze verify /etc/systemd/system/dubtitlerr-publish.service /etc/systemd/system/dubtitlerr-publish.timer`.
      Record under "Publish timers": next/last trigger time from `list-timers`, and whether
      `systemd-analyze verify` printed anything (empty output means valid).

- [ ] Record the current repo state on the worker host for comparison against this branch:
      `ssh <worker-host> git -C /home/claude/DubTitlerr rev-parse --abbrev-ref HEAD` and
      `ssh <worker-host> git -C /home/claude/DubTitlerr rev-parse HEAD`. Record under
      "Deployed branch/commit". Do not deploy or restart anything from this task — recording
      only.

- [ ] Write the note. Create
      `/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/2026-09-22 Production Snapshot.md`
      with the sections named above (Active worker, Concurrent-worker check, Review server
      posture, Deployed config, Queue drift, Publish timers, Deployed branch/commit), each
      filled with the literal recorded values, plus a one-line header stating this is a
      read-only snapshot and no library-wide sweep was started — per the v0.2.0 exit
      checklist's "No library-wide sweep is launched until the above safety checks are
      complete."

## Task 5: Declare the v0.2.0 scope boundary in CHANGELOG.md

Sprint: 010 Scope: [S-5]

Files: `CHANGELOG.md` (one new top-level section).

Interfaces: none — this is a documentation-only scope declaration; it does not gate any other
task's code.

`CHANGELOG.md` currently starts, lines 1-9:

```
# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Nothing has been
tagged yet — this file starts at the public beta. `TRANSCRIBE_VERSION`/`TEXT_VERSION` in
`common.py` are the pipeline's own version history (they say what changed in the _output_,
and only a stamp bump puts the fix into already-processed files); the entries below summarize
that history alongside everything else that shipped since.

## [Unreleased]
```

- [ ] Insert a new section between line 7 and line 9 — immediately before the existing
      `## [Unreleased]` heading, which keeps tracking already-shipped-but-untagged fixes
      separately from this forward-looking scope declaration:

  ```markdown
  ## 0.2.0 - Unreleased

  Scope boundary for the v0.2.0 hardening pass, set 2026-09-21. The scope ids S-1 through
  S-22 are defined in `.procoder/specs/v0-2-0-hardening.md`; the tasks that deliver them are
  in `.procoder/plans/v0-2-0-hardening.md` (sprints 010-015).

  ### Included

  - S-1 through S-5 (sprint 010, Ground truth): get main's CI green again (ruff check . was
    failing on tests/test_gen_loop_set_e.py since 2026-09-05); commit compose.yaml and
    .env.example for the first time and fix the review server's auth default so an empty
    REVIEW_TOKEN no longer silently disables auth; clear the untracked/modified hygiene
    ledger; take a read-only production snapshot; this scope declaration.
  - S-6 through S-9 (sprint 011, Fail closed): a durable per-episode stage-status artifact
    with typed outcomes so a failed repair/signs/mux stage can never produce a
    current-looking .done stamp; merge_pass.sh captures and classifies exit codes; a
    transient signs-extraction failure is distinguished from a genuinely signs-free episode;
    the MP4-to-MKV conversion's stamp-before-remove ordering gets crash/failure tests and a
    documented recovery policy.
  - S-10 through S-13 (sprint 012, Provenance and policy): words.json schema v2 persists
    compute_type and beam_size and read_words() compares model/initial_prompt/compute_type/
    beam_size against the current config, counting mismatches instead of only checking
    transcribe_version (S-10); the unanchored-repair rollout is reconciled against the
    3-episode human review that justified it, including the 4 outstanding S31 verdicts
    recorded through the actual decision store (S-11); the phonetic-name-guard issue is
    closed as resolved by a different design (S-12); the REPAIR_BACKEND_SECONDARY
    recommendation is retired from IMPROVEMENTS.md and REVIEW.md (S-13).
  - S-14 through S-16 (sprint 013, Posture and liveness): every data surface of the review
    server — the /api/ routes and the rendered pages — is gated behind the same token as
    writes, and REQUIRE_TOKEN=1 hard-fails startup if auth ends up disabled anyway (S-14);
    a real-socket HTTP integration test covers auth, slow reads and the concurrency bound
    (S-15); a heartbeat file, a GET /healthz route and a Docker HEALTHCHECK let liveness be
    checked without inferring it from an idle-looking container (S-16).
  - S-17 through S-20 (sprint 014, Measurement): tools/timing_compare.py's real-media
    validation (T12) runs on 3 representative shows with a written go/no-go report, and
    specs/timing-compare/tasks.md's stale checklist is reconciled with what already shipped
    on main (S-17); the queue/publish operational checklist (timers, order-file drift,
    manifest policy) is verified live (S-18); the storage/host checklist is closed and
    FFMPEG_TIMEOUT's default is raised from 600 s to 1800 s, measured too short against a
    556 MB episode on the production NFS mount (S-19); the signs/songs-extraction prototype
    (tools/sns_extract.py) is built read-only with a false-positive inventory (S-20).
  - S-21 and S-22 (sprint 015, Release): the osv-scanner/pyproject extractor gap is
    tracked and the uv.lock scanning decision recorded (S-21); the 0.2.0 release itself
    (S-22).

  ### Deferred

  Carried forward from the 2026-09-21 weekly plan's "Beyond v0.2.0 / visible backlog" — not
  silently promoted into this release:

  - Web UI dashboard expansion, glossary editor, community glossary auto-fetch/push.
  - Full decoder/config fingerprint migration if not taken as S-10 through S-13 this release.
  - Full cross-host locking/claim mechanism beyond the current "never run two workers"
    operational rule.
  - Full ASS coordinate transformation for mismatched PlayResX/PlayResY; the current
    timing/signs work only warns.
  - Card splitting as a broader automatic feature; card_split.py stays deliberately limited
    to human corrections.
  - Automatic subtitle-repository reopen sweep; the beta design explicitly chose manual
    reopen.
  - Full CI/workflow consolidation if the current GitHub beta workflows are green; do not
    relitigate launch mechanics unless a concrete failure is found.
  - V1/V2 polish backlog items: style-collision logs, WrapStyle audit, font MIME warnings,
    mux.partners() optimization, extra data-file extraction, and broad observability
    polish, unless promoted by evidence from post-beta checks.
  - Phase-1 timing gating (using the timing-compare signal to drop/flag/snap cards): a
    separate spec, written only if S-17's go/no-go says GO.
  ```

- [ ] `git add CHANGELOG.md`

- [ ] Commit: `git commit -m "docs(changelog): declare the v0.2.0 scope boundary"`.

## Task 6: Stage status artifact + recorders

Sprint: 011 Scope: [S-6]
Files: `common.py` (add `STAGES_SUFFIX`, `STAGE_OUTCOMES`, `write_stage`, `read_stages`,
`failed_stage`, plus `import time`), `repair.py` (add `LLM_TIMEOUT` sentinel, distinguish
timeout from other transport failures in `llm_ollama`/`llm_llamacpp`, record the `"repair"`
stage at every `process()` return site), `dub_signs_merge.py` (distinguish `"extract-error"`
from `"no-signs"` in `build()`, record the `"signs"` stage at every `process_one()` return
site), `mux.py` (record the `"mux"` stage at the current pre-reorder return sites in
`process()` — Task 9 restates this block with the reordered body), `tests/test_common.py`,
`tests/test_repair.py`, `tests/test_dub_signs_merge.py`, `tests/test_mux.py`.
Interfaces:

- `common.STAGES_SUFFIX = ".dubtitles.stages.json"`
- `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty", "backend-unreachable", "extract-error", "build-error", "no-video", "timeout", "crashed", "unwritable")`
- `common.write_stage(stem: str, stage: str, outcome: str, detail: str = "") -> None` — `stage ∈ {"repair", "signs", "mux"}`; raises `ValueError` for an `outcome` not in `STAGE_OUTCOMES`; merges `{"<stage>": {"outcome": ..., "detail": ..., "at": <unix float>}}` into `<stem>STAGES_SUFFIX`.
- `common.read_stages(stem: str) -> dict` — `{}` when the file is absent or unreadable.
- `common.failed_stage(stem: str) -> str | None` — first of `("repair", "signs", "mux")` (pipeline order) whose recorded outcome is not in `{"ok", "no-reference", "no-video"}`; `None` when nothing recorded is a failure.
- `repair.LLM_TIMEOUT = "\x00timeout"` — new sentinel, alongside the existing `repair.LLM_UNREACHABLE = "\x00unreachable"`.

- [ ] Read `common.py:1-19` (imports) and confirm `time` is not already imported (it is not: the block is `http.client, json, os, re, subprocess, tempfile, urllib.parse, pysubs2`).
- [ ] Write the failing test in `tests/test_common.py` (append after `test_write_stamp_still_records_a_legacy_version_key` at the end of the file):
  ```python
  # --- stage status artifact (sprint 011, S-6) ----------------------------------


  def test_write_stage_read_stage_round_trip(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "repair", "ok", "targets=0")
      doc = common.read_stages(stem)
      assert doc["repair"]["outcome"] == "ok"
      assert doc["repair"]["detail"] == "targets=0"
      assert isinstance(doc["repair"]["at"], float)


  def test_write_stage_merges_two_stages_without_clobbering(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "repair", "ok")
      common.write_stage(stem, "signs", "build-error", "boom")
      doc = common.read_stages(stem)
      assert doc["repair"]["outcome"] == "ok"
      assert doc["signs"]["outcome"] == "build-error"
      assert doc["signs"]["detail"] == "boom"


  def test_write_stage_overwrites_the_same_stage_in_place(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "mux", "crashed", "first attempt")
      common.write_stage(stem, "mux", "ok", "retry succeeded")
      doc = common.read_stages(stem)
      assert doc["mux"]["outcome"] == "ok"
      assert doc["mux"]["detail"] == "retry succeeded"
      assert len(doc) == 1


  def test_read_stages_unreadable_file_returns_empty_dict(tmp_path):
      stem = str(tmp_path / "ep")
      with open(stem + common.STAGES_SUFFIX, "w") as f:
          f.write("{not valid json")
      assert common.read_stages(stem) == {}


  def test_read_stages_missing_file_returns_empty_dict(tmp_path):
      assert common.read_stages(str(tmp_path / "nope")) == {}


  def test_write_stage_rejects_an_unknown_outcome(tmp_path):
      stem = str(tmp_path / "ep")
      try:
          common.write_stage(stem, "repair", "not-a-real-outcome")
          raise AssertionError("expected ValueError")
      except ValueError:
          pass
      assert common.read_stages(stem) == {}, "a rejected write must not touch the file"


  def test_failed_stage_none_when_all_stages_are_ok(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "repair", "ok")
      common.write_stage(stem, "signs", "ok")
      common.write_stage(stem, "mux", "ok")
      assert common.failed_stage(stem) is None


  def test_failed_stage_none_for_no_reference_and_no_video(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "repair", "no-reference")
      common.write_stage(stem, "signs", "no-video")
      assert common.failed_stage(stem) is None


  def test_failed_stage_returns_the_first_failure_in_pipeline_order(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "repair", "backend-unreachable")
      common.write_stage(stem, "signs", "ok")
      assert common.failed_stage(stem) == "repair"


  def test_failed_stage_skips_a_stage_that_never_ran_this_sweep(tmp_path):
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "mux", "crashed", "rc=1")  # repair/signs never recorded
      assert common.failed_stage(stem) == "mux"


  def test_failed_stage_empty_record_is_none(tmp_path):
      assert common.failed_stage(str(tmp_path / "nope")) is None
  ```
  Run `python3 -m pytest tests/test_common.py -k "write_stage or read_stages or failed_stage" -q`; expect FAIL with `AttributeError: module 'common' has no attribute 'write_stage'`.
- [ ] Implement in `common.py`. Add `import time` to the import block (`common.py:11-19`) — alphabetical order: after `tempfile`, before `urllib.parse`:
  ```python
  import http.client
  import json
  import os
  import re
  import subprocess
  import tempfile
  import time
  import urllib.parse
  ```
  Add after the `STAMP_SUFFIX = ".dubtitles.done"` line (`common.py:90`) and before the
  `TRACK_NAME` block, so the stage artifact sits beside the other idempotency constants:
  ```python
  # STAGES_SUFFIX: the per-episode record of what repair/signs/mux each ACTUALLY did, keyed
  # by outcome rather than by exit code -- merge_pass.sh has no `set -e` and checks no
  # exit status, so a stage that crashed used to be indistinguishable from one that ran
  # clean. Additive: no existing reader is affected by its presence or absence.
  STAGES_SUFFIX = ".dubtitles.stages.json"
  # A transport failure to the LLM backend is recorded as "backend-unreachable" or
  # "timeout", NEVER "llm-empty" -- a prior outage dumped roughly 1,300 queue entries
  # under llm_empty that were really a dead endpoint, not the model declining to answer.
  STAGE_OUTCOMES = (
      "ok",
      "no-reference",
      "llm-empty",
      "backend-unreachable",
      "extract-error",
      "build-error",
      "no-video",
      "timeout",
      "crashed",
      "unwritable",
  )


  def write_stage(stem: str, stage: str, outcome: str, detail: str = "") -> None:
      """Merge one stage's outcome into <stem>STAGES_SUFFIX. Same discipline as every
      other sidecar (unresolved._rewrite, generate._atomic_write): temp file in the same
      directory, os.chmod(SIDECAR_MODE), os.replace -- through out_for() so a configured
      OUTPUT_ROOT is honoured, same as write_words. Raises OSError on a write failure
      (unlike unresolved._rewrite, which swallows it): a caller that needs to react to a
      failed stage write, the way mux.process() reacts to a failed write_stamp, needs the
      exception to reach it rather than a silently-dropped return value."""
      if outcome not in STAGE_OUTCOMES:
          raise ValueError(f"unknown stage outcome {outcome!r} (not in STAGE_OUTCOMES)")
      path = out_for(stem + STAGES_SUFFIX)
      doc = read_stages(stem)
      doc[stage] = {"outcome": outcome, "detail": detail, "at": time.time()}
      d = os.path.dirname(path) or "."
      fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
      try:
          with os.fdopen(fd, "w") as f:
              json.dump(doc, f)
          os.chmod(tmp, SIDECAR_MODE)
          os.replace(tmp, path)
      except OSError:
          try:
              os.remove(tmp)
          except OSError:
              pass
          raise


  def read_stages(stem: str) -> dict:
      """The per-episode stage-outcome record, or {} when absent/unreadable -- never an
      exception (mirrors read_words/read_stamp: an unreadable sidecar reads as "nothing
      recorded yet", not a reason to abort the caller)."""
      try:
          with open(out_for(stem + STAGES_SUFFIX)) as f:
              return json.load(f)
      except (OSError, ValueError):
          return {}


  def failed_stage(stem: str) -> str | None:
      """The first pipeline stage -- checked in PIPELINE order (repair, then signs, then
      mux), not JSON key order -- whose recorded outcome is neither "ok" nor one of the
      two other legitimate completions: "no-reference" (nothing to anchor a repair on)
      and "no-video" (no matching video file, so signs/mux never got a chance to run --
      that is not a failure of either of them). A stage with no entry at all (it never
      ran this sweep, e.g. because the .ass sidecar already existed and the assemble step
      was skipped) is not a failure either -- None for "nothing recorded", same as
      read_stages()."""
      doc = read_stages(stem)
      for stage in ("repair", "signs", "mux"):
          entry = doc.get(stage)
          if entry and entry.get("outcome") not in ("ok", "no-reference", "no-video"):
              return stage
      return None
  ```
- [ ] Run `python3 -m pytest tests/test_common.py -k "write_stage or read_stages or failed_stage" -q`; expect pass (10 tests).
- [ ] Run `ruff check common.py`; expect "All checks passed!"
- [ ] Commit: `git commit -m "feat(common): add the per-episode stage-status artifact"`

- [ ] Read `repair.py:572-654` (`llm_ollama`, `LLM_UNREACHABLE`, `llm_llamacpp`) and `repair.py:713-1176` (`process`) again to confirm the exact insertion points below still match (line numbers shift only if an earlier task in this file already landed; re-grep `def llm_ollama` / `def process` if they don't).
- [ ] Write the failing tests in `tests/test_repair.py` (append at the end of the file):
  ```python
  # --- stage status artifact (sprint 011, S-6) ----------------------------------


  def test_llm_ollama_signals_timeout_distinctly_from_other_transport_failures(monkeypatch):
      def boom(url, body):
          raise TimeoutError("timed out")

      monkeypatch.setattr(repair, "_post_json", boom)
      assert repair.llm_ollama("p") == repair.LLM_TIMEOUT


  def test_llm_llamacpp_signals_timeout_distinctly_from_other_transport_failures(monkeypatch):
      def boom(url, body):
          raise TimeoutError("timed out")

      monkeypatch.setattr(repair, "_post_json", boom)
      assert repair.llm_llamacpp("p", "m") == repair.LLM_TIMEOUT


  def test_llm_timeout_sentinel_is_distinct_from_unreachable_and_empty():
      assert repair.LLM_TIMEOUT not in ("", repair.LLM_UNREACHABLE)


  def test_process_records_backend_unreachable_and_refuses(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_unreachable")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
      )
      g = gl()
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_unreachable.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
      monkeypatch.setattr(repair, "llm", lambda prompt, model=None: repair.LLM_UNREACHABLE)

      assert repair.process(conf_path) == "refused"
      assert common.read_stages(stem)["repair"]["outcome"] == "backend-unreachable"


  def test_process_records_timeout_when_every_target_times_out(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_timeout")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
      )
      g = gl()
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_timeout.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
      monkeypatch.setattr(repair, "llm", lambda prompt, model=None: repair.LLM_TIMEOUT)

      assert repair.process(conf_path) == "refused"
      assert common.read_stages(stem)["repair"]["outcome"] == "timeout"


  def test_process_records_backend_unreachable_on_a_mixed_timeout_and_unreachable_episode(tmp_path, monkeypatch):
      """Not every target timed out, so the outcome is the broader "backend-unreachable"
      rather than the narrower "timeout" -- both targets still failed to reach the
      backend, and only an all-timeout episode gets the more specific label."""
      stem = str(tmp_path / "ep_stage_mixed")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path,
          srt_path,
          [
              {"start": 0.0, "end": 1.0, "text": "garbled one", "avg_logprob": -0.9, "no_speech_prob": 0.1},
              {"start": 2.0, "end": 3.0, "text": "garbled two", "avg_logprob": -0.9, "no_speech_prob": 0.1},
          ],
      )
      g = gl()
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_mixed.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "sub one"), (2.0, 3.0, "sub two")])

      calls = []

      def fake_llm(prompt, model=None):
          calls.append(prompt)
          return repair.LLM_TIMEOUT if len(calls) == 1 else repair.LLM_UNREACHABLE

      monkeypatch.setattr(repair, "llm", fake_llm)

      assert repair.process(conf_path) == "refused"
      assert common.read_stages(stem)["repair"]["outcome"] == "backend-unreachable"


  def test_process_records_no_reference_on_the_prior_repairs_guard(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_no_ref")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path,
          srt_path,
          [{"start": 0.0, "end": 2.0, "text": "our mods will never give up", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
      )
      open(srt_path, "w").write("1\n00:00:00,000 --> 00:00:02,000\nOur mods will never give up.\n\n")
      json.dump({"targets": 144, "repaired": 3, "skipped_no_ref": 0}, open(stem + ".dubtitles.repair-summary.json", "w"))
      g = glossary.load_dict({"show": "One Pace"})
      monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_no_ref.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

      assert repair.process(conf_path) == "refused"
      assert common.read_stages(stem)["repair"]["outcome"] == "no-reference"


  def test_process_records_ok_on_a_normal_repair_run(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_ok")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path, srt_path, [{"start": 0.0, "end": 4.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
      )
      g = gl()
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_ok.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 4.0, "the official sub")])
      monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

      assert repair.process(conf_path) == "repaired"
      assert common.read_stages(stem)["repair"]["outcome"] == "ok"


  def test_process_records_ok_when_there_are_no_targets(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_clean")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "clean line", "avg_logprob": -0.01, "no_speech_prob": 0.1}]
      )
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_clean.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: gl())

      assert repair.process(conf_path) == "clean"
      assert common.read_stages(stem)["repair"]["outcome"] == "ok"


  def test_process_records_llm_empty_when_every_target_gets_an_empty_reply(tmp_path, monkeypatch):
      stem = str(tmp_path / "ep_stage_llm_empty")
      conf_path = stem + repair.CONF_SUFFIX
      srt_path = stem + repair.SRT_SUFFIX
      _write_conf(
          conf_path, srt_path, [{"start": 0.0, "end": 4.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
      )
      g = gl()
      monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stage_llm_empty.mkv"))
      monkeypatch.setattr(repair, "glossary_for", lambda video: g)
      monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 4.0, "the official sub")])
      monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "")

      assert repair.process(conf_path) == "repaired"
      assert common.read_stages(stem)["repair"]["outcome"] == "llm-empty"


  def test_process_no_stage_written_on_a_plain_skip(tmp_path):
      """No video/srt/conf yet is "nothing to do", not a repair attempt -- nothing is
      recorded, matching read_stages()'s empty-dict-for-absent contract."""
      stem = str(tmp_path / "ep_stage_skip")
      conf_path = stem + repair.CONF_SUFFIX  # never written
      assert repair.process(conf_path) == "skip"
      assert common.read_stages(stem) == {}
  ```
  Add `import common` to `tests/test_repair.py`'s import block (`tests/test_repair.py:8-17`
  currently has `csv, json, os` then `common, decisions, glossary, reflow, repair,
unresolved` — `common` is already imported there; no change needed).
  Run `python3 -m pytest tests/test_repair.py -k "stage" -q`; expect FAIL with
  `AttributeError: module 'repair' has no attribute 'LLM_TIMEOUT'`.
- [ ] Implement in `repair.py`. Add the timeout sentinel next to `LLM_UNREACHABLE`
      (`repair.py:590`):
  ```python
  # A transport failure is NOT an empty reply. Both used to return "", which made a dead
  # endpoint indistinguishable from "the model left the line alone" -- so every target on an
  # episode landed in llm_empty, `fixed` stayed 0, and the srt was rebuilt from conf.json as
  # raw ASR over whatever the last run shipped. A distinct sentinel is the smallest thing that
  # lets the caller tell the two apart.
  LLM_UNREACHABLE = "\x00unreachable"
  # A TIMEOUT is also not an empty reply, and it is not the same fact about the release as a
  # generic transport failure: connection-refused/DNS-failure means the backend is not running
  # at all, while a timeout means it IS running but not answering inside the configured
  # window -- worth a distinct stage outcome ("timeout" vs "backend-unreachable") so an
  # operator tuning REPAIR_TIMEOUT_READ can tell the two apart from the stage record alone.
  LLM_TIMEOUT = "\x00timeout"
  ```
  Edit `llm_ollama` (`repair.py:572-582`) to catch `TimeoutError` before the generic
  `Exception` handler (Python's stdlib `socket.timeout` is an alias of the builtin
  `TimeoutError` since 3.10, and this project requires `>=3.11`; a connect-phase timeout
  on `conn.connect()` and a read-phase stall on `conn.sock.settimeout(...)` +
  `getresponse()`/`.read()` inside `_post_json` both raise it — `ConnectionRefusedError`
  and DNS failures are different `OSError` subclasses and are NOT `TimeoutError`, so they
  still fall through to the generic branch below):
  ```python
  def llm_ollama(prompt, model=None):
      """Ollama /api/generate backend (the original/default path — byte-for-byte the same
      request shape and response parsing as before A1's dispatch refactor)."""
      # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
      body = {"model": model or MODEL, "prompt": prompt, "stream": False, "think": False, "options": {"temperature": 0}}
      try:
          out = _post_json(OLLAMA, body).get("response", "").strip()
          return out.splitlines()[0].strip().strip('"').strip() if out else ""
      except TimeoutError as e:
          log("  llm timeout:", e)
          return LLM_TIMEOUT
      except Exception as e:
          log("  llm fail:", e)
          return LLM_UNREACHABLE
  ```
  Edit `llm_llamacpp` (`repair.py:593-623`) the same way:
  ```python
  def llm_llamacpp(prompt, model):
      """llama.cpp backend, via the OpenAI-compatible /v1/chat/completions endpoint. ...
      (docstring unchanged)"""
      body = {
          "messages": [{"role": "user", "content": prompt}],
          "temperature": 0,
          "max_tokens": 80,
          "chat_template_kwargs": {"enable_thinking": False},
      }
      try:
          msg = _post_json(LLAMACPP_URL, body)["choices"][0]["message"]
          out = (msg.get("content") or "").strip()
          return out.splitlines()[0].strip().strip('"').strip() if out else ""
      except TimeoutError as e:
          log("  llm timeout:", e)
          return LLM_TIMEOUT
      except Exception as e:
          log("  llm fail:", e)
          return LLM_UNREACHABLE
  ```
  Add `write_stage` to the `common` import (`repair.py:84`):
  ```python
  from common import MEDIA_GID, MEDIA_UID, dialogue_intervals, find_video, out_for, read_words, ts_srt, write_stage
  ```
  In `process()`, add the `timed_out` counter next to `unreachable` (`repair.py:785`):
  ```python
      llm_empty = 0
      unreachable = 0
      timed_out = 0  # S-6: distinct from `unreachable` -- see LLM_TIMEOUT's docstring
      rejected_secondary = 0  # C5: second-pass output refused by the gate
  ```
  Change the transport-failure branch (`repair.py:853-867`) to recognise both sentinels:
  ```python
          if new in (LLM_UNREACHABLE, LLM_TIMEOUT):
              # The BACKEND is down or not answering in time, which is a fact about the
              # release, not about this card. A human cannot review "the server was
              # unreachable" or "the server timed out", and unresolved.record's own
              # docstring says llm_empty carries no proposal and was never a decision --
              # so nothing is queued. The episode-level guard below refuses the rewrite.
              if new == LLM_TIMEOUT:
                  timed_out += 1
              else:
                  unreachable += 1
              new = ""
              bucket = apply_human_text(c, store, stem, words_doc)
              if bucket == "rescued":
                  verdict_rescued += 1
              elif bucket == "unfittable":
                  verdict_unfittable += 1
              elif bucket == "owed":
                  verdict_owed += 1
              continue
  ```
  Add the `"clean"` recorder (`repair.py:778-780`):
  ```python
      targets = [(i, c) for i, c in enumerate(conf) if is_target(c, gloss)]
      if not targets:
          write_stage(stem, "repair", "ok", "no repair targets")
          return "clean"  # nothing to repair (e.g. S15E01)
  ```
  Replace guard (a) (`repair.py:1060-1067`):
  ```python
      if targets and (unreachable + timed_out) == len(targets):
          outcome = "timeout" if timed_out == len(targets) else "backend-unreachable"
          log(
              f"  REFUSED {os.path.basename(stem)}: the repair backend was unreachable/timed out for all"
              f" {len(targets)} targets ({timed_out} timeout, {unreachable} unreachable). Rebuilding the srt"
              " would overwrite the shipped text with raw ASR, and a dead endpoint is not a review item, so"
              " nothing was queued. Check REPAIR_LLAMACPP_URL / REPAIR_BACKEND and re-run."
          )
          write_stage(stem, "repair", outcome, f"{timed_out} timeout, {unreachable} unreachable of {len(targets)} targets")
          return "refused"
  ```
  Add a `write_stage` call to guard (c) (`repair.py:1068-1075`, only the added line shown
  in context):
  ```python
      if targets and fixed == 0 and skipped_no_ref == len(targets) and prior_repairs(stem) > 0:
          log(
              f"  REFUSED {os.path.basename(stem)}: every one of {len(targets)} targets was skipped for want of a"
              f" fansub anchor, but the last run shipped {prior_repairs(stem)} repairs. Rebuilding the srt would"
              " overwrite them with raw ASR. Declare `unanchored_repair` in this show's glossary if its copies"
              " carry no English subtitles for the Japanese audio."
          )
          write_stage(
              stem, "repair", "no-reference",
              f"every target skipped for want of a fansub anchor; refused to overwrite {prior_repairs(stem)} prior repairs",
          )
          return "refused"
  ```
  Add the final-path recorder right before `return "repaired"` (`repair.py:1144-1152`):
  ```python
      if targets and fixed == 0 and skipped_no_ref == len(targets):
          log(
              f"  WARNING every one of {len(targets)} targets on {os.path.basename(stem)} was skipped for want of a"
              " reference — this release has no English subtitles for the Japanese audio, so there is nothing to"
              ' anchor a repair on. Set "unanchored_repair": true in this show\'s glossary to repair from the'
              " glossary alone (wider guesses, fewer missed names), or leave it off to ship the ASR text as-is."
          )
      if targets and llm_empty == len(targets):
          write_stage(stem, "repair", "llm-empty", f"llm returned empty for all {len(targets)} targets")
      else:
          write_stage(stem, "repair", "ok", f"repaired={fixed} targets={len(targets)} skipped_no_ref={skipped_no_ref}")
      log(f"  targets={len(targets)} repaired={fixed}")
      return "repaired"
  ```
  The `"skip"` return (`repair.py:720-722`) gets NO `write_stage` call — the inputs are not
  ready yet (no video, no srt, or no conf.json), which is not a repair attempt.
- [ ] Run `python3 -m pytest tests/test_repair.py -q`; expect pass (whole file, no
      regressions in `test_llm_ollama_signals_a_transport_failure_rather_than_swallowing_it` /
      `test_llm_llamacpp_signals_a_transport_failure_rather_than_swallowing_it`, which raise a
      plain `OSError` and must still get `LLM_UNREACHABLE`).
- [ ] Run `ruff check repair.py`; expect "All checks passed!"
- [ ] Commit: `git commit -m "feat(repair): distinguish timeout from unreachable and record the repair stage"`

- [ ] Read `dub_signs_merge.py:146-309` (`build`, `process_one`) again to confirm line
      numbers.
- [ ] Write the failing tests in `tests/test_dub_signs_merge.py` (append at the end):
  ```python
  # --- stage status artifact (sprint 011, S-6) ----------------------------------


  def test_build_reports_extract_error_when_every_attempted_stream_fails(monkeypatch, tmp_path):
      """Distinct from "no-signs": a signs-ish stream WAS identified, but every attempt to
      extract or parse it failed -- a real failure, not "this release has no signs track"."""
      monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [3])
      monkeypatch.setattr(dsm, "extract", lambda video, idx, out: False)
      status, signs, dub = dsm.build("fake-video.mkv", str(tmp_path / "dub.srt"), str(tmp_path / "out.ass"))
      assert status == "extract-error"


  def test_build_still_reports_no_signs_when_nothing_signs_ish_was_identified(monkeypatch, tmp_path):
      monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [])
      status, signs, dub = dsm.build("fake-video.mkv", str(tmp_path / "dub.srt"), str(tmp_path / "out.ass"))
      assert status == "no-signs"


  def test_process_one_records_no_video_stage(tmp_path):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      assert dsm.process_one(srt) == "no-video"
      assert common.read_stages(stem)["signs"]["outcome"] == "no-video"


  def test_process_one_records_build_error_stage(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))

      def boom(video, srt, out_ass):
          raise RuntimeError("mkvextract exploded")

      monkeypatch.setattr(dsm, "build", boom)
      assert dsm.process_one(srt) == "build-error"
      assert common.read_stages(stem)["signs"]["outcome"] == "build-error"


  def test_process_one_records_extract_error_stage(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))
      monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("extract-error", 0, 0))
      assert dsm.process_one(srt) == "extract-error"
      assert common.read_stages(stem)["signs"]["outcome"] == "extract-error"


  def test_process_one_records_build_error_stage_on_a_save_failure(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))
      monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("save-fail", 2, 3))
      assert dsm.process_one(srt) == "save-fail"
      assert common.read_stages(stem)["signs"]["outcome"] == "build-error"


  def test_process_one_records_ok_when_no_signs_track_exists(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))
      monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("no-signs", 0, 0))
      assert dsm.process_one(srt) == "no-signs"
      assert common.read_stages(stem)["signs"]["outcome"] == "ok"


  def test_process_one_records_build_error_when_dub_lines_are_zero(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))
      monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("ok", 4, 0))
      assert dsm.process_one(srt) == "empty"
      assert common.read_stages(stem)["signs"]["outcome"] == "build-error"


  def test_process_one_records_ok_on_a_successful_merge(tmp_path, monkeypatch):
      srt = str(tmp_path / ("ep" + dsm.SUFFIX))
      open(srt, "w").close()
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(dsm, "find_video", lambda s: str(tmp_path / "ep.mkv"))
      monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("ok", 3, 5))
      assert dsm.process_one(srt) == "merged"
      stage = common.read_stages(stem)["signs"]
      assert stage["outcome"] == "ok"
      assert stage["detail"] == "signs=3 dub=5"
  ```
  Add `import common` to `tests/test_dub_signs_merge.py`'s import block (currently
  `pysubs2`, `common`, `dub_signs_merge as dsm` — `common` is already imported; no change
  needed).
  Run `python3 -m pytest tests/test_dub_signs_merge.py -k "stage or extract_error" -q`;
  expect FAIL with `AssertionError` (status compares `"no-signs"` where `"extract-error"`
  is expected, since `build()` does not yet distinguish the two).
- [ ] Implement in `dub_signs_merge.py`. Add `write_stage` to the `common` import
      (`dub_signs_merge.py:42`):
  ```python
  from common import MEDIA_GID, MEDIA_UID, find_video, log, out_for, signs_sub_streams, write_stage
  ```
  Distinguish "no signs-ish stream was ever identified" from "one was, but every attempt
  to extract/parse it failed" in `build()` (`dub_signs_merge.py:146-197`, only the changed
  lines shown in context):
  ```python
  def build(video, dub_srt, out_ass):
      base = None  # the merged ScriptInfo/styles canvas
      kept = []  # (event, source_style_name)
      seen = set()
      base_ws = None  # D3: base track's WrapStyle, for cross-track comparison
      resolutions = []  # D5: (PlayResX, PlayResY) per source track, for mismatch warning
      attempted = failed = 0  # S-6: "no signs track exists" vs "extraction/parse failed"
      for _n, idx in enumerate(signs_sub_streams(video, SUB_LANGS)):
          attempted += 1
          with tempfile.TemporaryDirectory() as td:
              ex = os.path.join(td, "s.ass")
              if not extract(video, idx, ex):
                  failed += 1
                  continue
              try:
                  subs = pysubs2.load(ex)
              except Exception as e:
                  log("  load fail", idx, e)
                  failed += 1
                  continue
          src_events = list(subs.events)  # snapshot BEFORE any clearing (base may alias subs)
          resolutions.append((subs.info.get("PlayResX"), subs.info.get("PlayResY")))  # D5
          if base is None:
              base = subs
              base.events = []
              base.info["ScaledBorderAndShadow"] = "yes"  # D4: consistent cross-player rendering
              base_ws = base.info.get("WrapStyle")  # D3
          else:
              track_ws = subs.info.get("WrapStyle")  # D3
              if track_ws != base_ws:
                  log(f"WrapStyle differs: base={base_ws} track={track_ws} — using base")
              for sname, sty in subs.styles.items():  # carry styles from later tracks
                  if sname in base.styles:
                      existing = base.styles[sname]  # D1: flag conflicting redefinitions
                      if existing.fontname != sty.fontname or existing.fontsize != sty.fontsize:
                          log(f"  style conflict: '{sname}' — font/size differ, using first definition")
                  else:
                      base.styles[sname] = sty
          for ev in src_events:
              if not keep_event(ev):
                  continue
              key = (int(ev.start), int(ev.end), ev.style, ev.layer, ev.text)
              if key in seen:
                  continue
              seen.add(key)
              base.events.append(ev)
              kept.append(ev)
      if base is None:
          # A signs-ish stream was identified and every attempt on it failed -> real
          # failure (S-6 "extract-error"). No signs-ish stream was ever identified ->
          # this release genuinely has none; the dub-only srt is the correct output.
          return ("extract-error" if attempted and failed == attempted else "no-signs"), 0, 0
  ```
  Record the `"signs"` stage at every `process_one()` return site
  (`dub_signs_merge.py:287-309`):
  ```python
  def process_one(srt):
      stem = srt[: -len(SUFFIX)]
      out_ass = out_for(stem + ".eng.dubtitles.ass")
      video = find_video(stem)
      if not video:
          write_stage(stem, "signs", "no-video", "no matching video file for this dubtitle sidecar")
          return "no-video"
      try:
          res, signs, dub = build(video, srt, out_ass)
      except Exception as e:
          log("build error:", srt, e)
          write_stage(stem, "signs", "build-error", str(e))
          return "build-error"
      if res == "extract-error":
          write_stage(stem, "signs", "extract-error", "every signs-track extraction/parse attempt failed")
          return res
      if res == "no-signs":
          write_stage(stem, "signs", "ok", "no signs/songs track present; dialogue-only .srt used downstream")
          return res
      if res == "save-fail":
          write_stage(stem, "signs", "build-error", "base.save() produced no output file")
          return res
      if dub == 0:
          write_stage(stem, "signs", "build-error", "zero dub dialogue lines added from the dub srt")
          return "empty"
      try:
          os.chown(out_ass, MEDIA_UID, MEDIA_GID)
      except OSError as e:
          log(f"chown failed for {out_ass}: {e}")
      try:
          os.remove(srt)
      except OSError:
          pass
      log(f"  signs/songs/credits kept={signs}  dub lines={dub}")
      write_stage(stem, "signs", "ok", f"signs={signs} dub={dub}")
      return "merged"
  ```
- [ ] Run `python3 -m pytest tests/test_dub_signs_merge.py -q`; expect pass (whole file,
      no regressions in `test_build_finds_no_signs_when_the_only_sub_is_our_dubtitle` — its
      scenario has `signs_sub_streams` returning `[]`, so `attempted` stays `0` and the
      branch still yields `"no-signs"`).
- [ ] Run `ruff check dub_signs_merge.py`; expect "All checks passed!"
- [ ] Commit: `git commit -m "feat(dub_signs_merge): distinguish extract-error and record the signs stage"`

- [ ] Read `mux.py:41-56` (imports) and `mux.py:431-494` (`process`) again to confirm line
      numbers before editing (Task 9 restates this whole block with its own reordering; this
      step only adds `write_stage` calls at the CURRENT return sites, unreordered).
- [ ] Write the failing tests in `tests/test_mux.py` (append at the end of the file):
  ```python
  # --- stage status artifact (sprint 011, S-6) ----------------------------------


  def test_mux_records_ok_on_a_successful_mux(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))

      assert mux.process(v, apply=True) == "muxed"
      assert common.read_stages(stem)["mux"]["outcome"] == "ok"


  def test_mux_records_crashed_on_a_verify_failure(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(mux, "verify", lambda o, out: "missing-av")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))

      assert mux.process(v, apply=True) == "verify-missing-av"
      assert common.read_stages(stem)["mux"]["outcome"] == "crashed"


  def test_mux_records_unwritable_on_a_stamp_write_failure(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))
      monkeypatch.setattr(mux, "write_stamp", lambda *a, **kw: (_ for _ in ()).throw(OSError("read-only")))

      assert mux.process(v, apply=True) == "stamp-write-failed"
      assert common.read_stages(stem)["mux"]["outcome"] == "unwritable"


  def test_mux_records_crashed_on_an_unhandled_exception(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")

      def boom(cmd, **kw):
          raise RuntimeError("mkvmerge segfaulted")

      monkeypatch.setattr(mux.subprocess, "run", boom)

      assert mux.process(v, apply=True) == "error"
      assert common.read_stages(stem)["mux"]["outcome"] == "crashed"
  ```
  Add `import common` to `tests/test_mux.py`'s import block (`tests/test_mux.py:1-6`
  currently `os, time, mux`):
  ```python
  import os
  import time

  import common
  import mux
  ```
  Run `python3 -m pytest tests/test_mux.py -k "test_mux_records" -q`; expect FAIL with
  `KeyError: 'mux'` (nothing writes the stage yet).
- [ ] Implement in `mux.py`. Add `write_stage` to the `common` import (`mux.py:51`):
  ```python
  from common import MEDIA_GID, MEDIA_UID, STAMP_SUFFIX, TRACK_NAME, is_our_track, log, read_stamp, stamp_valid, write_stage, write_stamp
  ```
  Add `write_stage` calls at the current return sites inside the `try` block of
  `process()` (`mux.py:454-494`, whole block shown so the insertion points are unambiguous
  — Task 9 supersedes this exact block with a reordered version):
  ```python
      try:
          st = os.stat(orig)
          subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800, check=False)
          res = verify(orig, out)
          if res != "ok":
              if os.path.exists(out):
                  os.remove(out)
              write_stage(stem, "mux", "crashed", f"verify failed: {res}")
              return "verify-" + res
          os.chown(out, st.st_uid or MEDIA_UID, st.st_gid or MEDIA_GID)
          _finalize(out, final)  # write the muxed mkv
          if os.path.abspath(orig) != os.path.abspath(final) and os.path.exists(orig):
              os.remove(orig)  # mp4->mkv: drop the OLD library link (partner survives)
          try:
              write_stamp(stamp, final, stages=_stages_ran(stem, src))
              # stamp BEFORE removing sidecars (crash-safe skip)
          except OSError as e:
              log(
                  f"  ERROR: muxed OK but stamp write FAILED ({e}) — {os.path.basename(final)} "
                  f"will be re-muxed every sweep until the stamp can be written"
              )
              write_stage(stem, "mux", "unwritable", str(e))
              return "stamp-write-failed"
          for suff in (ASS_SUFFIX, SRT_SUFFIX):
              try:
                  os.remove(stem + suff)
              except OSError:
                  pass
          with open(stem + ".dubtitles.mux.log", "w") as f:
              f.write(f"muxed {os.path.basename(orig)} -> mkv; eng audio + Dubtitles default\n")
              f.write("dropped non-keep tracks: " + ", ".join(dropped) + "\n")
          log(f"  muxed ({ext}->mkv); dropped {len(dropped)} foreign track(s)")
          write_stage(stem, "mux", "ok", f"muxed dropped={len(dropped)}")
          return "muxed"
      except Exception as e:
          if os.path.exists(out):
              os.remove(out)
          write_stage(stem, "mux", "crashed", str(e))
          log("  mux error:", e)
          return "error"
  ```
- [ ] Run `python3 -m pytest tests/test_mux.py -q`; expect pass (whole file).
- [ ] Run `ruff check mux.py`; expect "All checks passed!"
- [ ] Run `python3 -m pytest -q`; expect pass (whole suite — confirms no cross-file
      regression from the shared `common.write_stage` addition).
- [ ] Commit: `git commit -m "feat(mux): record the mux stage on every process() outcome"`

## Task 7: merge_pass.sh exit capture

Sprint: 011 Scope: [S-7]
Files: `merge_pass.sh` (rewritten in full — 68 lines today, grows to capture `rc=$?` after
every stage invocation and print a fail-closed summary line), `tests/test_merge_pass_exit_capture.py`
(new, parses the shell script the same way `tests/test_gen_loop_set_e.py` parses `gen_loop.sh`).
Interfaces: consumes `common.write_stage` and `common.failed_stage` from Task 6 (already
landed in `common.py` by the time this task runs, since tasks execute in file order within
a sprint — but this task's own diff is self-contained and does not need Task 6's code to be
read to be understood: it only needs those two function NAMES, which are fixed by the
shared interface list).

- [ ] Read `merge_pass.sh` in full (68 lines) and `tests/test_gen_loop_set_e.py` in full
      (the precedent for parsing a shell script structurally in a pytest file — it reads
      `gen_loop.sh` as text, joins backslash-continued lines into logical statements, and
      asserts a structural property over every matching statement).
- [ ] Write the failing test `tests/test_merge_pass_exit_capture.py` (new file):
  ```python
  """Regression for sprint 011 [S-7]: merge_pass.sh has no `set -e` and checked no stage's
  exit status, so a crashed repair.py/dub_signs_merge.py/mux.py invocation still let the
  loop continue to mux/stamp the episode and the final line ("MERGE_PASS_DONE ...")
  printed unconditionally regardless of any per-episode failure.

  This test parses merge_pass.sh as text (same technique as test_gen_loop_set_e.py for
  gen_loop.sh) and asserts, structurally, that:
    1. every one of the three stage invocations (repair.py, dub_signs_merge.py, mux.py)
       is immediately followed by an `rc=$?` capture,
    2. each capture is followed by a conditional write_stage(..., "crashed", "rc=<n>")
       fallback for the case where the stage itself recorded nothing,
    3. the final summary line is NEVER an unconditional print -- it must be inside an
       if/else whose two branches are the literal "MERGE PASS COMPLETE" and
       "MERGE PASS INCOMPLETE: ... episodes with a failed stage" strings.
  """

  import re
  from pathlib import Path

  MERGE_PASS = Path(__file__).resolve().parent.parent / "merge_pass.sh"


  def _read():
      return MERGE_PASS.read_text()


  def _lines():
      return _read().splitlines()


  def test_every_stage_invocation_is_followed_by_an_rc_capture():
      src = _read()
      for script in ("repair.py", "dub_signs_merge.py", "mux.py"):
          for m in re.finditer(re.escape(script), src):
              # the invocation line ends at the next newline; rc=$? must appear on one of
              # the next 2 lines (the invocation itself may end with `</dev/null`, and the
              # capture is the line right after).
              tail = src[m.end() : m.end() + 200]
              assert "rc=$?" in tail, f"{script} invocation at offset {m.start()} has no rc=$? capture within 200 chars"


  def test_every_rc_capture_has_a_write_stage_fallback_for_a_silent_crash():
      src = _read()
      rc_positions = [m.start() for m in re.finditer(r"rc=\$\?", src)]
      assert rc_positions, "no rc=$? captures found at all"
      for pos in rc_positions:
          tail = src[pos : pos + 400]
          assert "write_stage" in tail, f"rc=$? capture at offset {pos} has no write_stage(...) fallback within 400 chars"
          assert "crashed" in tail


  def test_write_stage_fallback_only_fires_when_the_stage_recorded_nothing():
      """The fallback must be conditional on absence, not unconditional -- an unconditional
      write_stage would CLOBBER a real outcome the crashed stage already recorded (e.g.
      dub_signs_merge.py exiting non-zero AFTER it already wrote "build-error")."""
      src = _read()
      for m in re.finditer(r"write_stage", src):
          # every write_stage call in this script must be reached through a Python-level
          # "not already recorded" check, not a bare unconditional call from the shell.
          window = src[max(0, m.start() - 300) : m.start()]
          assert "read_stages" in window or "not in common.read_stages" in window or "stage not in" in window, (
              f"write_stage at offset {m.start()} is not guarded by a read_stages()-based presence check"
          )


  def test_merge_pass_complete_is_never_printed_unconditionally():
      src = _read()
      assert re.search(r"^\s*echo\s+\"MERGE PASS COMPLETE\"\s*$", src, re.MULTILINE) is None or re.search(
          r"if\s.*\n(?:.*\n)*?\s*echo \"MERGE PASS COMPLETE\"", src
      ), "MERGE PASS COMPLETE must be inside a conditional, not a bare echo"
      assert "MERGE PASS COMPLETE" in src
      assert "MERGE PASS INCOMPLETE" in src


  def test_merge_pass_incomplete_reports_a_failed_stage_count():
      src = _read()
      assert re.search(r"MERGE PASS INCOMPLETE: \$\{?\w+\}? episodes with a failed stage", src), (
          "the incomplete line must interpolate a count variable, not a hardcoded number"
      )


  def test_summary_decision_reads_common_failed_stage():
      src = _read()
      assert "common.failed_stage" in src, "the pass/fail decision must be common.failed_stage, not a shell heuristic"
  ```
  Run `python3 -m pytest tests/test_merge_pass_exit_capture.py -q`; expect FAIL with
  `AssertionError: repair.py invocation at offset ... has no rc=$? capture within 200 chars`.
- [ ] Implement: replace `merge_pass.sh` in full with:
  ```sh
  #!/bin/sh
  # ONE merge+mux pass over the whole Anime Library (runs in the container, as root).
  # For every episode with a dubtitle sidecar that isn't muxed yet:
  #   1. assemble: repair low-confidence lines + merge signs/songs into a .ass (mkv);
  #      mp4 episodes have no embedded signs so they stay a dialogue-only .srt,
  #   2. mux: embed the .ass (mkv) / .srt (mp4) into the video as a default "Dubtitles"
  #      track WITH the embedded fonts (mp4 is remuxed to mkv) -> signs render correctly,
  #      a .dubtitles.done stamp is written, sidecars removed.
  # Idempotent: a muxed episode has the stamp + embedded track, so it's skipped next pass.
  # Per-episode availability; refreshes Plex when this pass muxed anything new.
  #
  # [S-7] fail-closed exit capture: each of the three per-episode stage scripts has no
  # `set -e` upstream of it and this script has none of its own, so a crashed stage used
  # to leave the loop running as though nothing happened. `rc=$?` is captured after every
  # invocation; a non-zero rc that the stage itself did not already turn into a
  # common.write_stage(...) record (repair.py/dub_signs_merge.py/mux.py all record their
  # own outcome on every return path as of sprint 011 [S-6]) is recorded here as a bare
  # "crashed" so no failure is silently unrecorded. The final line reflects
  # common.failed_stage() over every episode this pass touched, never printed
  # unconditionally.
  # Env: MERGE_ROOTS, OLLAMA_URL, REPAIR_MODEL, GLOSSARY_DIR, PLEX_URL, PLEX_TOKEN, PLEX_SECTION,
  #      MIN_FREE_GB, KEEP_LANGS.
  ROOT="${MERGE_ROOTS:-/media/Anime Library}"
  APP="${APP_DIR:-/scripts}"
  command -v ffmpeg >/dev/null 2>&1 || {
  	echo "FATAL: ffmpeg not found — image is misbuilt"
  	exit 1
  }
  command -v mkvmerge >/dev/null 2>&1 || {
  	echo "FATAL: mkvmerge not found — image is misbuilt"
  	exit 1
  }
  python3 -c "import pysubs2" >/dev/null 2>&1 || {
  	echo "FATAL: pysubs2 not found — image is misbuilt"
  	exit 1
  }
  cd "$ROOT" || {
  	echo "merge_pass: missing $ROOT"
  	exit 1
  }

  # EXTRA_DIRS single source of truth (B7/B9): data/extras.txt via shell/lib.sh, with an
  # inline fallback (the pre-consolidation regex) if the lib or data file isn't present
  # (e.g. run under the deprecated $APP=/scripts flow, which doesn't ship these files).
  #
  # The file test is load-bearing, NOT belt-and-braces: `.` is a POSIX special builtin, so
  # sourcing a missing file is a fatal error that terminates a non-interactive shell BEFORE
  # the `|| true` is ever considered. Written as `. file || true`, this whole script exited
  # silently -- no output, status 2, nothing assembled -- whenever APP_DIR was not /app,
  # which is exactly the fallback case the comment above claims to support.
  [ -f "$APP/shell/lib.sh" ] && . "$APP/shell/lib.sh"
  PATTERN=$(extras_grep_pattern "$APP/data/extras.txt" 2>/dev/null || echo '(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)')

  # [S-7] Records a stage as "crashed" ONLY when the stage's own script did not already
  # record an outcome for it -- a script that recorded "build-error" and then happened to
  # exit non-zero for an unrelated reason must not have that real outcome clobbered by a
  # generic "crashed". PYTHONPATH is set explicitly: `python3 -c` has no script directory
  # of its own to add to sys.path the way `python3 "$APP/repair.py"` does.
  record_crash_if_unrecorded() {
  	# $1=stem $2=stage $3=rc
  	PYTHONPATH="$APP" python3 -c "
  import sys
  import common
  stem, stage, rc = sys.argv[1], sys.argv[2], sys.argv[3]
  if stage not in common.read_stages(stem):
      common.write_stage(stem, stage, 'crashed', 'rc=' + rc)
  " "$1" "$2" "$3" 2>/dev/null
  }

  before=$(find . -type f -name "*.dubtitles.done" | wc -l)
  STEMS_FILE=$(mktemp)
  trap 'rm -f "$STEMS_FILE"' EXIT
  # episodes with a sidecar (srt or ass) -> dedup to the stem
  find . -type f \( -name "*.eng.dubtitles.srt" -o -name "*.eng.dubtitles.ass" \) |
  	grep -ivE "/$PATTERN/" |
  	sed -E 's/\.eng\.dubtitles\.(srt|ass)$//' | sort -u | while IFS= read -r stem; do
  	[ -f "$stem.dubtitles.fail" ] && continue # generate crashed on it -> skip
  	echo "$stem" >>"$STEMS_FILE"
  	if [ ! -f "$stem.eng.dubtitles.ass" ] && [ -f "$stem.eng.dubtitles.srt" ]; then
  		echo "### assemble $stem"
  		python3 "$APP/repair.py" "$stem.dubtitles.conf.json" </dev/null
  		rc=$?
  		[ "$rc" -ne 0 ] && record_crash_if_unrecorded "$stem" repair "$rc"

  		python3 "$APP/dub_signs_merge.py" "$stem.eng.dubtitles.srt" </dev/null
  		rc=$?
  		[ "$rc" -ne 0 ] && record_crash_if_unrecorded "$stem" signs "$rc"
  	fi
  	for ext in mkv mp4 m4v; do # mux the video (root); embeds + stamps
  		[ -f "$stem.$ext" ] && {
  			python3 "$APP/mux.py" --apply "$stem.$ext" </dev/null
  			rc=$?
  			[ "$rc" -ne 0 ] && record_crash_if_unrecorded "$stem" mux "$rc"
  			break
  		}
  	done
  done
  after=$(find . -type f -name "*.dubtitles.done" | wc -l)

  if [ "$after" -gt "$before" ] && [ -n "${PLEX_TOKEN:-}" ]; then
  	echo "muxed $((after - before)) new episode(s) -> refreshing Plex"
  	python3 "$APP/plex_refresh.py" "watch" </dev/null
  fi
  echo "MERGE_PASS_DONE new=$((after - before)) total_done=$after $(date)"

  # [S-7] The fail-closed verdict: COMPLETE only when common.failed_stage() is None for
  # every episode this pass touched. An empty STEMS_FILE (no episodes touched at all) is
  # trivially COMPLETE -- nothing was attempted, so nothing can have failed.
  failed_count=0
  if [ -s "$STEMS_FILE" ]; then
  	failed_count=$(PYTHONPATH="$APP" python3 -c "
  import sys
  import common
  n = 0
  for stem in sys.stdin.read().splitlines():
      if stem and common.failed_stage(stem):
          n += 1
  print(n)
  " <"$STEMS_FILE")
  fi
  if [ "$failed_count" -eq 0 ]; then
  	echo "MERGE PASS COMPLETE"
  else
  	echo "MERGE PASS INCOMPLETE: $failed_count episodes with a failed stage"
  fi
  ```
- [ ] Run `python3 -m pytest tests/test_merge_pass_exit_capture.py -q`; expect pass (6 tests).
- [ ] Run `shellcheck merge_pass.sh` if `shellcheck` is installed locally (`command -v
shellcheck`); this repo's CI does not run shellcheck, so treat this as advisory only —
      do not block the commit on it if it is not installed.
- [ ] Run `python3 -m pytest -q`; expect pass (whole suite).
- [ ] Run `ruff check .`; expect "All checks passed!" (no `.py` files touched in this task,
      but the gate runs over the whole tree regardless).
- [ ] Commit: `git commit -m "fix(merge_pass): capture per-stage exit codes and fail closed on the summary line"`

## Task 8: Signs transient vs signs-free

Sprint: 011 Scope: [S-8]
Files: `mux.py` (add `_prior_ass_had_signs`, a `STALE_SUFFIX` constant, `import pysubs2`,
`import dub_signs_merge`, `read_stages` to the `common` import, and the pre-stamp refusal
check in `process()`), `tests/test_mux.py`.
Interfaces: reads `common.read_stages(stem)["signs"]["outcome"]` (Task 6); reads
`generate.STALE_SUFFIX`'s value (`".stale"`, duplicated as a literal here rather than
imported — importing `generate.py` from `mux.py` would pull in `faster_whisper` at module
load time, which CI's `mux.py` test path does not install); calls
`dub_signs_merge.keep_event(ev)` (existing, `dub_signs_merge.py:83-107`) against the
PARKED stale `.ass` sidecar that `generate.park_stale_sidecars` (`generate.py:412-459`)
leaves behind as `<stem>.eng.dubtitles.ass.stale` when a version bump supersedes it —
that parked file, not the current sidecar `sub_source()` would pick, is what still proves
"this episode used to have signs" once dub_signs_merge.py has failed to produce a fresh
`.ass` this pass.

- [ ] Read `mux.py:403-409` (`sub_source`) and `generate.py:412-459`
      (`park_stale_sidecars`) again to confirm the exact stale-file naming convention:
      `<stem><ASS_SUFFIX><STALE_SUFFIX>` = `<stem>.eng.dubtitles.ass.stale`.
- [ ] Write the failing tests in `tests/test_mux.py` (append at the end of the file):
  ```python
  # --- signs transient vs signs-free (sprint 011, S-8) --------------------------


  def test_prior_ass_had_signs_true_for_a_parked_ass_with_a_positioned_event(tmp_path):
      stem = str(tmp_path / "ep")
      (tmp_path / ("ep" + mux.ASS_SUFFIX + mux.STALE_SUFFIX)).write_text(
          "[Script Info]\n\n[Events]\n"
          "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
          r"Dialogue: 0,0:00:00.00,0:00:01.00,Sign,,0,0,0,,{\pos(100,200)}A SIGN" + "\n"
      )
      assert mux._prior_ass_had_signs(stem) is True


  def test_prior_ass_had_signs_false_when_no_parked_file_exists(tmp_path):
      assert mux._prior_ass_had_signs(str(tmp_path / "ep")) is False


  def test_prior_ass_had_signs_false_for_a_dialogue_only_parked_ass(tmp_path):
      stem = str(tmp_path / "ep")
      (tmp_path / ("ep" + mux.ASS_SUFFIX + mux.STALE_SUFFIX)).write_text(
          "[Script Info]\n\n[Events]\n"
          "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
          "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Just plain dialogue\n"
      )
      assert mux._prior_ass_had_signs(stem) is False


  def test_prior_ass_had_signs_false_for_an_unparseable_parked_file(tmp_path):
      stem = str(tmp_path / "ep")
      (tmp_path / ("ep" + mux.ASS_SUFFIX + mux.STALE_SUFFIX)).write_bytes(b"\x00\x01not an ass file")
      assert mux._prior_ass_had_signs(stem) is False


  def test_mux_refuses_a_dialogue_only_replacement_when_signs_failed_and_prior_had_signs(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      # This pass's signs stage failed transiently, so no FRESH .ass sidecar exists...
      os.remove(stem + mux.ASS_SUFFIX)
      (tmp_path / ("ep" + mux.SRT_SUFFIX)).write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n")
      # ...but a PARKED prior .ass survives from before the re-transcription that
      # triggered this pass, and it carries a real positioned sign.
      prior_ass_path = tmp_path / ("ep" + mux.ASS_SUFFIX + mux.STALE_SUFFIX)
      prior_ass_path.write_text(
          "[Script Info]\n\n[Events]\n"
          "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
          r"Dialogue: 0,0:00:00.00,0:00:01.00,Sign,,0,0,0,,{\pos(100,200)}A SIGN" + "\n"
      )
      prior_bytes = prior_ass_path.read_bytes()
      common.write_stage(stem, "signs", "build-error", "extraction crashed")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))

      assert mux.process(v, apply=True) == "signs-regression-refused"
      assert not os.path.exists(stem + mux.STAMP_SUFFIX)
      assert not os.path.exists(stem + ".muxtmp.mkv")
      assert prior_ass_path.read_bytes() == prior_bytes, "the parked prior .ass must be untouched"
      assert common.read_stages(stem)["mux"]["outcome"] == "crashed"


  def test_mux_proceeds_when_signs_stage_recorded_no_video(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "signs", "no-video", "no matching video")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))
      assert mux.process(v, apply=True) == "muxed"


  def test_mux_proceeds_when_signs_stage_recorded_ok(tmp_path, monkeypatch):
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "signs", "ok", "signs=2 dub=10")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))
      assert mux.process(v, apply=True) == "muxed"


  def test_mux_proceeds_when_signs_failed_but_nothing_prior_had_signs(tmp_path, monkeypatch):
      """The other half of the AND: a build-error with no parked prior .ass (or one with
      no keep_event-worthy content) has nothing to demote -- the mux must not be refused."""
      v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
      stem = str(tmp_path / "ep")
      common.write_stage(stem, "signs", "build-error", "boom")
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))
      assert mux.process(v, apply=True) == "muxed"
  ```
  Add `import common` to `tests/test_mux.py` (already added in Task 6's diff to this same
  file; if this task lands standalone, add it — see Task 6's import-block diff).
  Run `python3 -m pytest tests/test_mux.py -k "prior_ass_had_signs or signs_regression or signs_stage" -q`;
  expect FAIL with `AttributeError: module 'mux' has no attribute 'ASS_SUFFIX' and no attribute 'STALE_SUFFIX'`
  (`ASS_SUFFIX` already exists at `mux.py:82`; `STALE_SUFFIX` does not exist yet, so the
  actual failure is `AttributeError: module 'mux' has no attribute 'STALE_SUFFIX'`).
- [ ] Implement in `mux.py`. Add imports (`mux.py:41-56`, only the changed lines):
  ```python
  import argparse
  import errno
  import json
  import os
  import re
  import shutil
  import subprocess
  import time

  import pysubs2

  import dub_signs_merge
  import unresolved
  from common import MEDIA_GID, MEDIA_UID, STAMP_SUFFIX, TRACK_NAME, is_our_track, log, read_stages, read_stamp, stamp_valid, write_stage, write_stamp
  ```
  Add the stale-suffix constant next to `ASS_SUFFIX`/`SRT_SUFFIX` (`mux.py:82-83`):
  ```python
  ASS_SUFFIX = ".eng.dubtitles.ass"
  SRT_SUFFIX = ".eng.dubtitles.srt"
  # generate.park_stale_sidecars (generate.py:371,412-459) renames a superseded .ass to
  # <path>.stale rather than deleting it, exactly so a signs-carrying prior output
  # survives a version bump. Duplicated here as a literal, not imported from generate.py:
  # generate.py imports faster_whisper at module load time, which mux.py's own test path
  # does not install.
  STALE_SUFFIX = ".stale"
  ```
  Add the helper after `sub_source` (`mux.py:403-409`):
  ```python
  def _prior_ass_had_signs(stem: str) -> bool:
      """True if this episode's PARKED stale .ass sidecar (see the STALE_SUFFIX comment
      above) carries at least one event dub_signs_merge.keep_event() would keep. This is
      the one place a signs-carrying prior output is at risk of being silently replaced
      by a dialogue-only one: sub_source()'s ASS-then-SRT fallback has no way to know a
      fresh .ass USED to exist this episode before this pass's signs stage failed to
      rebuild it. False (never raises) for a missing or unparseable parked file -- an
      episode with no surviving prior signs has nothing this guard needs to protect."""
      path = stem + ASS_SUFFIX + STALE_SUFFIX
      if not os.path.exists(path):
          return False
      try:
          events = pysubs2.load(path).events
      except Exception:
          return False
      return any(dub_signs_merge.keep_event(ev) for ev in events)
  ```
  Insert the refusal check in `process()`, immediately after the `verify()` success check
  and before `os.chown(out, ...)` (`mux.py:457-462`, shown with one line of context on
  each side — this sits BETWEEN the `write_stage(..., "crashed", ...)` verify-failure line
  Task 6 added and the `os.chown` line Task 6 left unchanged):
  ```python
          res = verify(orig, out)
          if res != "ok":
              if os.path.exists(out):
                  os.remove(out)
              write_stage(stem, "mux", "crashed", f"verify failed: {res}")
              return "verify-" + res
          stages = read_stages(stem)
          signs_outcome = (stages.get("signs") or {}).get("outcome")
          if signs_outcome in ("extract-error", "build-error", "timeout", "crashed") and _prior_ass_had_signs(stem):
              log(
                  f"  REFUSED {os.path.basename(orig)}: the signs stage failed this pass ({signs_outcome}) and the"
                  " parked prior .ass already carried signs/songs/credits -- muxing the dialogue-only replacement"
                  " now would silently DEMOTE a signs-carrying episode to signs-free. Leaving the existing output"
                  " and stamp untouched; retry once the signs stage succeeds."
              )
              if os.path.exists(out):
                  os.remove(out)
              write_stage(stem, "mux", "crashed", "signs failed but prior output had signs")
              return "signs-regression-refused"
          os.chown(out, st.st_uid or MEDIA_UID, st.st_gid or MEDIA_GID)
  ```
- [ ] Run `python3 -m pytest tests/test_mux.py -q`; expect pass (whole file).
- [ ] Run `ruff check mux.py`; expect "All checks passed!"
- [ ] Commit: `git commit -m "fix(mux): refuse a signs-free remux when the signs stage failed transiently"`

## Task 9: MP4 durability (stamp before remove) + README

Sprint: 011 Scope: [S-9]
Files: `mux.py` (reorder `process()`'s success path to `verify → _finalize →
write_stamp(final) → os.remove(orig)`, and add the interrupted-retry recovery guard at the
top of `process()`), `tests/test_mux.py`, `README.md` (line 69).
Interfaces: `common.write_stamp`/`common.read_stamp`/`common.stamp_valid` (existing,
unchanged signatures); `common.write_stage` (Task 6); restates the same `try` block Task 6
and Task 8 already modified, in its final reordered form, so this task is readable on its
own without re-reading Task 6/8's diffs.

- [ ] Read `mux.py:431-494` (`process`, current order: `verify → chown → _finalize →
os.remove(orig) → write_stamp → remove sidecars → mux.log`) again, and
      `README.md:58-70` for the exact sentence to replace.
- [ ] Write the failing tests in `tests/test_mux.py` (append at the end of the file):
  ```python
  # --- MP4 durability: stamp before remove (sprint 011, S-9) --------------------


  def test_mp4_source_keeps_orig_and_removes_final_when_write_stamp_fails(tmp_path, monkeypatch):
      """The core guarantee: a stamp-write failure must not have already destroyed the
      source. `orig` (the mp4) is untouched; the half-written `final` (the new mkv, whose
      existence the failed stamp cannot vouch for) is removed rather than left as a stale,
      unstamped file sitting next to a live mp4."""
      orig = tmp_path / "ep.mp4"
      orig.write_bytes(b"mp4-bytes")
      (tmp_path / ("ep" + mux.SRT_SUFFIX)).write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n")
      tracks = [{"id": 0, "type": "video", "properties": {}}, {"id": 1, "type": "audio", "properties": {"language": "eng"}}]
      monkeypatch.setattr(mux, "identify", lambda p: {"tracks": tracks})
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"mkv-bytes"))
      monkeypatch.setattr(mux, "write_stamp", lambda *a, **kw: (_ for _ in ()).throw(OSError("read-only file system")))

      assert mux.process(str(orig), apply=True) == "stamp-write-failed"
      assert orig.exists() and orig.read_bytes() == b"mp4-bytes"
      final = tmp_path / "ep.mkv"
      assert not final.exists()
      assert not (tmp_path / "ep.dubtitles.done").exists()
      assert common.read_stages(str(tmp_path / "ep"))["mux"]["outcome"] == "unwritable"


  def test_interrupted_after_finalize_is_recovered_as_a_noop_next_pass(tmp_path, monkeypatch):
      """Simulates a kill between write_stamp(final) succeeding and the os.remove(orig)
      that follows it: `final` ends up stamped and CURRENT, `orig` (the mp4) survives.
      RECOVERY RULE (implemented, not just documented): the top of process() checks
      whether `final` is already current-stamped and, if so, treats a surviving `orig` as
      dead weight from a mux that already completed -- it removes `orig` and returns
      "already-muxed" WITHOUT re-running mkvmerge. This is what makes the next pass a
      no-op retry rather than a redundant remux."""
      orig = tmp_path / "ep.mp4"
      orig.write_bytes(b"mp4-bytes")
      (tmp_path / ("ep" + mux.SRT_SUFFIX)).write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n\n")
      tracks = [{"id": 0, "type": "video", "properties": {}}, {"id": 1, "type": "audio", "properties": {"language": "eng"}}]
      monkeypatch.setattr(mux, "identify", lambda p: {"tracks": tracks})
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"mkv-bytes"))

      real_remove = os.remove
      calls = []

      def boom_once(path):
          calls.append(path)
          if len(calls) == 1:
              raise KeyboardInterrupt()
          real_remove(path)

      monkeypatch.setattr(mux.os, "remove", boom_once)

      try:
          mux.process(str(orig), apply=True)
          raise AssertionError("expected KeyboardInterrupt to propagate")
      except KeyboardInterrupt:
          pass

      final = tmp_path / "ep.mkv"
      stamp_path = tmp_path / "ep.dubtitles.done"
      assert final.exists() and stamp_path.exists(), "the mux and the stamp both completed before the interruption"
      assert orig.exists(), "the interruption happened before os.remove(orig)"
      assert calls == [str(orig)], "os.remove's first (and only, before the crash) call must be for orig, not final"

      monkeypatch.setattr(mux.os, "remove", real_remove)  # back to normal for the retry
      assert mux.process(str(orig), apply=True) == "already-muxed"
      assert not orig.exists(), "the stale mp4 is cleaned up without a redundant remux"


  def test_mkv_source_success_path_never_calls_os_remove(tmp_path, monkeypatch):
      """orig == final for an mkv source, so the reordered os.remove(orig) step must be a
      no-op by construction (the abspath-equality guard), not merely a coincidence of this
      test's inputs. Pinned directly: os.remove must never be called with orig's path."""
      v = tmp_path / "ep.mkv"
      v.write_bytes(b"x" * 10)
      (tmp_path / ("ep" + mux.ASS_SUFFIX)).write_text("[Script Info]\n")
      tracks = [{"id": 0, "type": "video", "properties": {}}, {"id": 1, "type": "audio", "properties": {"language": "eng"}}]
      monkeypatch.setattr(mux, "identify", lambda p: {"tracks": tracks})
      monkeypatch.setattr(mux, "verify", lambda o, out: "ok")
      monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"y" * 10))

      real_remove = os.remove

      def guarded_remove(path):
          assert os.path.abspath(path) != os.path.abspath(str(v)), "orig must never be removed for an mkv source"
          real_remove(path)

      monkeypatch.setattr(mux.os, "remove", guarded_remove)

      assert mux.process(str(v), apply=True) == "muxed"


  def test_dry_run_recovery_guard_never_deletes_the_stale_mp4():
      """apply=False (--plan, no --apply) must never delete anything, including a stale
      orig the recovery guard would otherwise clean up under --apply."""
      pass  # documented in the implementation step below; see the `apply and` guard clause
  ```
  Run `python3 -m pytest tests/test_mux.py -k "durability or interrupted_after or mkv_source_success" -q`;
  expect FAIL with `AssertionError: expected KeyboardInterrupt to propagate` /
  `AssertionError: assert False` (the reorder has not landed yet, so `orig` is removed
  before `write_stamp` is ever attempted).
- [ ] Implement in `mux.py`. Replace `process()` in full (`mux.py:431-494` as modified by
      Tasks 6 and 8 above — this is the FINAL form, restated whole rather than as an
      incremental diff, per the plan-writing rule that tasks are read out of order):
  ```python
  def process(orig, apply):
      stem, ext = os.path.splitext(orig)
      stamp = stem + STAMP_SUFFIX
      final = stem + ".mkv"  # every episode ends as an mkv
      # [S-9] Recovery for an interruption between write_stamp(final) succeeding and the
      # os.remove(orig) that follows it below: `final` is already durably stamped as
      # CURRENT, so a surviving `orig` is dead weight from a mux that already completed,
      # not new work. Removing it here -- instead of re-running mkvmerge against it --
      # makes a crash in that narrow window a retryable no-op on the next sweep instead of
      # a redundant remux. Gated on `apply`: a dry run must never delete anything.
      if (
          apply
          and os.path.abspath(orig) != os.path.abspath(final)
          and os.path.exists(final)
          and stamp_valid(read_stamp(stamp), final)
      ):
          try:
              os.remove(orig)
          except OSError:
              pass
          return "already-muxed"
      src = sub_source(stem)
      if src is None:
          return "no-sub"
      if stamp_valid(read_stamp(stamp), orig):
          return "already-muxed"  # stat-only, version-aware stamp is the ONLY guard
      # AFTER the stamp check, not before it (the plan sketched the reverse). An episode that
      # already shipped cannot be held back -- reporting a hold for it would inflate the
      # backlog count with episodes no review can affect, and hide "already-muxed" behind a
      # status the operator is meant to act on.
      if held_for_review(stem):
          return "held-for-review"
      if not has_room(_free_bytes(orig), os.path.getsize(orig)):
          log("  skip (low disk):", os.path.basename(orig))
          return "skip-no-room"
      out = stem + ".muxtmp.mkv"
      cmd, dropped = build_cmd(identify(orig), orig, src, out)
      if not apply:
          log(f"  PLAN mux {os.path.basename(orig)} ({ext}->mkv)  drop-tracks={dropped}")
          return "plan"
      try:
          st = os.stat(orig)
          subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800, check=False)
          res = verify(orig, out)
          if res != "ok":
              if os.path.exists(out):
                  os.remove(out)
              write_stage(stem, "mux", "crashed", f"verify failed: {res}")
              return "verify-" + res
          stages = read_stages(stem)
          signs_outcome = (stages.get("signs") or {}).get("outcome")
          if signs_outcome in ("extract-error", "build-error", "timeout", "crashed") and _prior_ass_had_signs(stem):
              log(
                  f"  REFUSED {os.path.basename(orig)}: the signs stage failed this pass ({signs_outcome}) and the"
                  " parked prior .ass already carried signs/songs/credits -- muxing the dialogue-only replacement"
                  " now would silently DEMOTE a signs-carrying episode to signs-free. Leaving the existing output"
                  " and stamp untouched; retry once the signs stage succeeds."
              )
              if os.path.exists(out):
                  os.remove(out)
              write_stage(stem, "mux", "crashed", "signs failed but prior output had signs")
              return "signs-regression-refused"
          os.chown(out, st.st_uid or MEDIA_UID, st.st_gid or MEDIA_GID)
          _finalize(out, final)  # write the muxed mkv -- `orig` is UNTOUCHED until the
          # stamp below lands. [S-9]: this is the reorder. The stamp used to be written
          # AFTER os.remove(orig) for an mp4 source, so a write_stamp failure right here
          # meant the mp4 was already gone with nothing durable saying the remux happened.
          try:
              write_stamp(stamp, final, stages=_stages_ran(stem, src))
          except OSError as e:
              # The remux landed at `final`, but nothing durable says so yet. `orig` was
              # NEVER touched at this point -- its removal happens strictly AFTER this
              # block succeeds -- so removing the half-written `final` and returning is
              # retryable, with no data loss and no duplicate episode.
              if os.path.abspath(final) != os.path.abspath(orig) and os.path.exists(final):
                  os.remove(final)
              log(
                  f"  ERROR: muxed OK but stamp write FAILED ({e}) — {os.path.basename(final)} "
                  f"will be re-muxed every sweep until the stamp can be written"
              )
              write_stage(stem, "mux", "unwritable", str(e))
              return "stamp-write-failed"
          if os.path.abspath(orig) != os.path.abspath(final) and os.path.exists(orig):
              # mp4->mkv: NOW it is safe to drop the old library link -- the remux is
              # durably stamped, so any crash from here on is a no-op retry (see the
              # recovery guard at the top of this function), never data loss. The seeding
              # download hardlink partner is left alone -- the orphan-reaper owns it.
              os.remove(orig)
          for suff in (ASS_SUFFIX, SRT_SUFFIX):
              try:
                  os.remove(stem + suff)
              except OSError:
                  pass
          with open(stem + ".dubtitles.mux.log", "w") as f:
              f.write(f"muxed {os.path.basename(orig)} -> mkv; eng audio + Dubtitles default\n")
              f.write("dropped non-keep tracks: " + ", ".join(dropped) + "\n")
          log(f"  muxed ({ext}->mkv); dropped {len(dropped)} foreign track(s)")
          write_stage(stem, "mux", "ok", f"muxed dropped={len(dropped)}")
          return "muxed"
      except Exception as e:
          if os.path.exists(out):
              os.remove(out)
          write_stage(stem, "mux", "crashed", str(e))
          log("  mux error:", e)
          return "error"
  ```
- [ ] Run `python3 -m pytest tests/test_mux.py -q`; expect pass (whole file — including
      the pre-existing `test_process_reports_a_failed_stamp_write_and_keeps_the_sidecar`,
      which uses an mkv source and must still pass unchanged: `final == orig` there, so the
      `os.path.abspath(final) != os.path.abspath(orig)` guard in the `except OSError` branch
      correctly skips removing it).
- [ ] Delete the placeholder `test_dry_run_recovery_guard_never_deletes_the_stale_mp4`
      written above and replace it with a real assertion, since a bare `pass` test proves
      nothing:
  ```python
  def test_dry_run_recovery_guard_never_deletes_the_stale_mp4(tmp_path, monkeypatch):
      orig = tmp_path / "ep.mp4"
      orig.write_bytes(b"mp4-bytes")
      final = tmp_path / "ep.mkv"
      final.write_bytes(b"mkv-bytes")
      stamp_path = tmp_path / "ep.dubtitles.done"
      common.write_stamp(str(stamp_path), str(final))
      # no sidecar at all -- if the recovery guard ran unconditionally it would still try
      # to clean up `orig`; apply=False must refuse to touch the filesystem regardless.
      assert mux.process(str(orig), apply=False) == "no-sub"
      assert orig.exists(), "a dry run (--apply not passed) must never delete anything"
  ```
  Run `python3 -m pytest tests/test_mux.py -k dry_run_recovery -q`; expect pass.
- [ ] Run `ruff check mux.py`; expect "All checks passed!"
- [ ] Read `README.md:58-70` and replace line 69's sentence. Current text
      (`README.md:66-69`):
  ```
  6. **Mux + fonts** — embed the result **with the MKV's fonts** as a default "Dubtitles" track so
     signs render in their real typeface (mp4 episodes are remuxed to mkv); English audio set default.
  ```
  New text:
  ```
  6. **Mux + fonts** — embed the result **with the MKV's fonts** as a default "Dubtitles" track so
     signs render in their real typeface (mp4 episodes are remuxed to mkv, and the original mp4/m4v
     is deleted only after the remux is verified and its `.dubtitles.done` stamp is durably written —
     a failed stamp write keeps the original mp4/m4v untouched and retries next sweep); English audio
     set default.
  ```
- [ ] Run `python3 -m pytest -q`; expect pass (whole suite).
- [ ] Run `ruff check .`; expect "All checks passed!"
- [ ] Commit: `git commit -m "fix(mux): stamp before removing the original mp4/m4v, not after"`

## Task 10: words.json schema 2 + decoder_identity()

Sprint: 012 Scope: [S-10]
Files: `common.py` (bump `WORDS_SCHEMA_VERSION` to 2, one line + comment), `generate.py`
(add `decoder_identity()`, make `write_words` persist `compute_type`/`beam_size` and the
resolved `model` through it), `tests/test_generate.py` (three new tests).
Interfaces: `generate.decoder_identity() -> dict` returning `{"model": MODEL,
"initial_prompt": INITIAL_PROMPT, "compute_type": COMPUTE, "beam_size":
int(os.environ.get("WHISPER_BEAM_SIZE", "7"))}`; `common.WORDS_SCHEMA_VERSION == 2`;
`generate.WORDS_SUFFIX` sidecar gains `"compute_type"` (str) and `"beam_size"` (int)
alongside the existing `"model"`/`"initial_prompt"`/`"schema_version"`/
`"transcribe_version"`/`"audio_duration"`/`"segments"`/`"words"` keys. Task 11 consumes
`decoder_identity()` as `read_words`'s `expect=` argument.

- [ ] Write the failing test for the new function's shape:
  ```python
  def test_decoder_identity_reports_the_active_decoder_settings(monkeypatch):
      monkeypatch.setenv("WHISPER_BEAM_SIZE", "5")
      identity = generate.decoder_identity()
      assert identity == {
          "model": generate.MODEL,
          "initial_prompt": generate.INITIAL_PROMPT,
          "compute_type": generate.COMPUTE,
          "beam_size": 5,
      }
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_decoder_identity_reports_the_active_decoder_settings -q`;
  expect FAIL with `"AttributeError: module 'generate' has no attribute 'decoder_identity'"`.
- [ ] Write the failing test for what `write_words` persists:
  ```python
  def test_write_words_persists_compute_type_and_beam_size(tmp_path, monkeypatch):
      monkeypatch.setenv("WHISPER_BEAM_SIZE", "7")
      words, segments = _clamped_fixture()
      stem = str(tmp_path / "ep")
      generate.write_words(stem, words, segments, 7.0, initial_prompt="x")
      doc = json.load(open(stem + generate.WORDS_SUFFIX))
      assert doc["schema_version"] == 2
      assert doc["model"] == generate.MODEL
      assert doc["compute_type"] == generate.COMPUTE
      assert doc["beam_size"] == 7
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_write_words_persists_compute_type_and_beam_size -q`;
  expect FAIL with `"assert 1 == 2"` (today's `WORDS_SCHEMA_VERSION` is 1, so the first
  assertion fails before the missing keys are even reached).
- [ ] Write the failing test pinning backward compatibility (the 366 live sidecars have
      neither new key):
  ```python
  def test_a_schema_1_sidecar_with_no_compute_fields_still_reads(tmp_path):
      words, segments = _clamped_fixture()
      stem = str(tmp_path / "ep")
      generate.write_words(stem, words, segments, 7.0, initial_prompt="x")
      path = stem + generate.WORDS_SUFFIX
      doc = json.load(open(path))
      doc["schema_version"] = 1
      del doc["compute_type"]
      del doc["beam_size"]
      with open(path, "w") as f:
          json.dump(doc, f)
      assert common.read_words(stem) is not None
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_a_schema_1_sidecar_with_no_compute_fields_still_reads -q`;
  expect FAIL with `"KeyError: 'compute_type'"` (today's `write_words` never writes that
  key, so `del doc["compute_type"]` raises before `read_words` is even reached).
- [ ] Implement `common.py`'s bump (`common.py:220`):
  ```python
  # v2 (2026-09-2x): +compute_type, +beam_size (see generate.decoder_identity()), so a
  # words.json records the full decoder configuration, not only the model name and
  # transcribe_version. Schema-1 files (the 366 live sidecars) have neither key --
  # read_words does not gate on schema_version, so they keep reading; Task 11's
  # expect= treats a missing field as words_config_unknown, never as a mismatch.
  WORDS_SCHEMA_VERSION = 2
  ```
- [ ] Implement `generate.py`'s `decoder_identity()`, inserted right after
      `load_glossary()` (after `generate.py:147`'s closing `)` of the `print(...)` call,
      before the `# Plex "local extras"...` comment):
  ```python
  def decoder_identity() -> dict:
      """The decoder settings that determine whether a persisted words.json still
      matches what today's transcription would produce. Read live, not cached, so a
      mid-run glossary swap (INITIAL_PROMPT, mutated by load_glossary()) or an
      operator's env change (WHISPER_BEAM_SIZE) is reflected -- MODEL and COMPUTE are
      resolved once at import time, exactly as WMODEL is loaded from them."""
      return {
          "model": MODEL,
          "initial_prompt": INITIAL_PROMPT,
          "compute_type": COMPUTE,
          "beam_size": int(os.environ.get("WHISPER_BEAM_SIZE", "7")),
      }
  ```
- [ ] Implement `write_words`'s doc-building (`generate.py:394-401`), replacing:
  ```python
      doc = {
          "schema_version": WORDS_SCHEMA_VERSION,
          "transcribe_version": TRANSCRIBE_VERSION,
          "model": os.environ.get("WHISPER_MODEL", ""),
          "initial_prompt": initial_prompt,
          "audio_duration": audio_duration,
          "segments": segments,
          "words": words,
      }
  ```
  with:
  ```python
      identity = decoder_identity()
      doc = {
          "schema_version": WORDS_SCHEMA_VERSION,
          "transcribe_version": TRANSCRIBE_VERSION,
          "model": identity["model"],
          "compute_type": identity["compute_type"],
          "beam_size": identity["beam_size"],
          "initial_prompt": initial_prompt,
          "audio_duration": audio_duration,
          "segments": segments,
          "words": words,
      }
  ```
  (`model` is now the resolved `MODEL` constant, not `os.environ.get("WHISPER_MODEL",
"")` -- this is the fix for the pre-existing bug where an unset env wrote `""`.)
- [ ] Run `python3 -m pytest tests/test_generate.py -q`; expect pass.
- [ ] Run `ruff check .`; expect `"All checks passed!"`.
- [ ] Commit: `git commit -m "feat(generate): words.json schema 2 records decoder identity"`.

## Task 11: read_words(expect=) + counters + future-version test

Sprint: 012 Scope: [S-10]
Files: `common.py` (`read_words` gains `expect=`; `stale_tiers` docstring gains one
sentence), `generate.py` (`partition_todo`/`process_text` pass `expect=decoder_identity()`;
new `_LAST_WORDS_STATS` module global + `_note_words_stats()` helper called from
`process()`/`process_text()`; `build_lastrun` gains an optional `words_totals` parameter
and three report keys; `main()` accumulates and passes it), `tests/test_generate.py`
(eight new tests). `repair.py:727`, `review_apply.py:116` and `tools/reapply_glossary.py:132`
are UNCHANGED: all three call `read_words(stem)` with no `rec`/`expect` because they only
read `doc["initial_prompt"]`/`doc["words"]` as text-tier inputs -- they never replay a
decode, so a decoder-identity mismatch has nothing for them to invalidate.
Interfaces: `common.read_words(stem, rec=None, expect: dict | None = None) -> dict | None`;
new counters `words_config_mismatch`, `words_config_unknown` (via `rec.count`, same
un-registered-in-`qc.COUNTERS` convention as the existing `words_missing`/
`words_version_mismatch`/`words_reused`); `generate._LAST_WORDS_STATS: dict`;
`generate._note_words_stats(rec) -> None`; `generate.build_lastrun(show, elapsed_s,
episodes_total, transcribed, totals, census, words_totals=None) -> dict` (new 7th
parameter, default-compatible with every existing call site) adds `"words_missing"`,
`"words_version_mismatch"`, `"words_reused"` keys to the returned dict.

- [ ] Write the four failing mismatch tests (one field each), using a helper that builds
      a sidecar whose stored fields match `decoder_identity()` exactly, then mutates one:
  ```python
  def _write_words_matching_identity(tmp_path, monkeypatch, initial_prompt="Custom prompt A", beam_size=7):
      monkeypatch.setattr(generate, "INITIAL_PROMPT", initial_prompt)
      monkeypatch.setenv("WHISPER_BEAM_SIZE", str(beam_size))
      words, segments = _clamped_fixture()
      stem = str(tmp_path / "ep")
      generate.write_words(stem, words, segments, 7.0, initial_prompt=generate.INITIAL_PROMPT)
      return stem, generate.decoder_identity()


  def test_read_words_rejects_a_model_mismatch(tmp_path, monkeypatch):
      stem, expect = _write_words_matching_identity(tmp_path, monkeypatch)
      expect = dict(expect, model="a-different-model")
      rec = qc.Recorder()
      assert common.read_words(stem, rec=rec, expect=expect) is None
      assert rec.counters["words_config_mismatch"] == 1


  def test_read_words_rejects_an_initial_prompt_mismatch(tmp_path, monkeypatch):
      stem, expect = _write_words_matching_identity(tmp_path, monkeypatch)
      expect = dict(expect, initial_prompt="a different prompt")
      rec = qc.Recorder()
      assert common.read_words(stem, rec=rec, expect=expect) is None
      assert rec.counters["words_config_mismatch"] == 1


  def test_read_words_rejects_a_compute_type_mismatch(tmp_path, monkeypatch):
      stem, expect = _write_words_matching_identity(tmp_path, monkeypatch)
      expect = dict(expect, compute_type="float16")
      rec = qc.Recorder()
      assert common.read_words(stem, rec=rec, expect=expect) is None
      assert rec.counters["words_config_mismatch"] == 1


  def test_read_words_rejects_a_beam_size_mismatch(tmp_path, monkeypatch):
      stem, expect = _write_words_matching_identity(tmp_path, monkeypatch)
      expect = dict(expect, beam_size=expect["beam_size"] + 1)
      rec = qc.Recorder()
      assert common.read_words(stem, rec=rec, expect=expect) is None
      assert rec.counters["words_config_mismatch"] == 1
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_read_words_rejects_a_model_mismatch -q`;
  expect FAIL with `"TypeError: read_words() got an unexpected keyword argument 'expect'"`
  (all four fail identically today, for the same reason).
- [ ] Write the failing "unknown, not mismatch" test for a schema-1-shaped doc:
  ```python
  def test_read_words_treats_a_missing_field_as_unknown_not_a_mismatch(tmp_path, monkeypatch):
      stem, expect = _write_words_matching_identity(tmp_path, monkeypatch)
      path = stem + generate.WORDS_SUFFIX
      doc = json.load(open(path))
      del doc["compute_type"]
      del doc["beam_size"]
      doc["model"] = ""  # the pre-existing bug: an unset WHISPER_MODEL wrote "" here
      with open(path, "w") as f:
          json.dump(doc, f)
      rec = qc.Recorder()
      result = common.read_words(stem, rec=rec, expect=expect)
      assert result is not None
      assert rec.counters["words_config_unknown"] == 1
      assert rec.counters.get("words_config_mismatch", 0) == 0
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_read_words_treats_a_missing_field_as_unknown_not_a_mismatch -q`;
  expect FAIL with `"TypeError: read_words() got an unexpected keyword argument 'expect'"`.
- [ ] Write the future-version test. This pins behavior `common.py`'s current `version
!= TRANSCRIBE_VERSION` check ALREADY provides (it fires on greater-than as much as
      less-than) -- it is expected to PASS immediately with no implementation change, and
      exists so that fact stays tested rather than merely commented:
  ```python
  def test_read_words_counts_a_transcribe_version_ahead_of_current_as_a_mismatch(tmp_path):
      words, segments = _clamped_fixture()
      stem = str(tmp_path / "ep")
      generate.write_words(stem, words, segments, 7.0, initial_prompt="x")
      path = stem + generate.WORDS_SUFFIX
      doc = json.load(open(path))
      doc["transcribe_version"] = common.TRANSCRIBE_VERSION + 1
      with open(path, "w") as f:
          json.dump(doc, f)
      rec = qc.Recorder()
      assert common.read_words(stem, rec=rec) is None
      assert rec.counters["words_version_mismatch"] == 1
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_read_words_counts_a_transcribe_version_ahead_of_current_as_a_mismatch -q`;
  expect PASS immediately (no implementation step touches this branch).
- [ ] Write the failing call-site test pinning `partition_todo`/`process_text`:
  ```python
  def test_partition_todo_and_process_text_request_the_decoder_identity():
      src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generate.py")).read()
      assert "read_words(stem, expect=decoder_identity())" in src
      assert "read_words(stem, rec=rec, expect=decoder_identity())" in src
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_partition_todo_and_process_text_request_the_decoder_identity -q`;
  expect FAIL with `"assert 'read_words(stem, expect=decoder_identity())' in "` (source
  scan finds neither literal call yet).
- [ ] Write the two failing `build_lastrun` tests:
  ```python
  def test_build_lastrun_reports_the_words_counters():
      totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
      census = {"transcribe_stale": 0, "text_stale": 0}
      words_totals = {"words_missing": 2, "words_version_mismatch": 1, "words_reused": 5}
      doc = generate.build_lastrun("One Pace", 1.0, 8, 8, totals, census, words_totals)
      assert doc["words_missing"] == 2
      assert doc["words_version_mismatch"] == 1
      assert doc["words_reused"] == 5


  def test_build_lastrun_defaults_the_words_counters_to_zero_for_the_old_call_shape():
      """Pins the pre-existing 6-positional-arg call in
      test_the_census_is_reported_per_tier_in_lastrun so this task cannot silently
      break it."""
      totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
      census = {"transcribe_stale": 0, "text_stale": 0}
      doc = generate.build_lastrun("One Pace", 1.0, 8, 8, totals, census)
      assert doc["words_missing"] == 0
      assert doc["words_version_mismatch"] == 0
      assert doc["words_reused"] == 0
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_build_lastrun_reports_the_words_counters -q`;
  expect FAIL with `"TypeError: build_lastrun() takes 6 positional arguments but 7 were given"`.
  Run `python3 -m pytest tests/test_generate.py -k test_build_lastrun_defaults_the_words_counters_to_zero_for_the_old_call_shape -q`;
  expect FAIL with `"KeyError: 'words_missing'"`.
- [ ] Implement `common.read_words` (`common.py:223-256`), replacing the signature and
      docstring:
  ```python
  def read_words(stem, rec=None, expect: dict | None = None):
      """The persisted word list, or None when it cannot be used -- never an exception.

      Every unusable state is COUNTED rather than swallowed, because the failure mode this
      guards is silent: a sidecar that is never found looks exactly like an episode that
      simply needs transcribing, and would re-transcribe forever while reporting healthy.
      Read through out_for() to match write_words -- following one convention on write and
      the other on read is precisely that silent miss.

      ``expect``, when given, is generate.decoder_identity() -- what today's process would
      use to transcribe. A stored field that IS RECORDED and DIFFERS invalidates the whole
      doc (words_config_mismatch): replaying it would serve a transcript decoded under
      different settings. A field the sidecar does not carry at all -- every schema-1
      file, or `model` written from an unset WHISPER_MODEL env as "" -- is UNKNOWN, not a
      mismatch (words_config_unknown), and the doc is still returned: the 366 live
      sidecars predate this check and must keep being served."""
  ```
  and adding, right before the final `if rec: rec.count("words_reused")` / `return doc`:
  ```python
      if expect:
          mismatched = False
          unknown = False
          for field, want in expect.items():
              got = doc.get(field)
              if got is None or got == "":
                  unknown = True
              elif got != want:
                  mismatched = True
          if unknown and rec:
              rec.count("words_config_unknown")
          if mismatched:
              if rec:
                  rec.count("words_config_mismatch")
              return None
  ```
- [ ] Implement the `stale_tiers` docstring addition (`common.py:325-330`), appending one
      sentence before the closing `"""`:
  ```python
      independently, so a TEXT_VERSION bump costs CPU minutes instead of GPU hours.

      Assumes size+mtime is a reliable proxy for content: a same-size, same-mtime
      replacement of the source video is treated as the unchanged file it appears to be.
      This is an accepted default, not upgraded to a content hash (owner decision,
      confirmed at sprint 010 open)."""
  ```
- [ ] Implement `generate.py`'s module-level accumulator, next to `_LAST_STATS`
      (`generate.py:165`):
  ```python
  _LAST_STATS: dict = {}
  # Sibling accumulator for the three words_* qc.Recorder counters (words_missing,
  # words_version_mismatch, words_reused). Populated on EVERY episode process()/
  # process_text() touches, not only the "ok" ones _LAST_STATS covers, because a
  # words.json write failure or a config mismatch matters to the operator even when
  # the episode itself completes.
  _LAST_WORDS_STATS: dict = {}


  def _note_words_stats(rec):
      """Snapshot this episode's words_* counters so main() can add them into
      lastrun.json regardless of the episode's overall status."""
      _LAST_WORDS_STATS.clear()
      _LAST_WORDS_STATS.update(
          {k: rec.counters.get(k, 0) for k in ("words_missing", "words_version_mismatch", "words_reused")}
      )
  ```
- [ ] Implement `partition_todo`'s call site (`generate.py:905`), replacing:
  ```python
          elif read_words(stem) is not None:
  ```
  with:
  ```python
          elif read_words(stem, expect=decoder_identity()) is not None:
  ```
- [ ] Implement `process_text`'s call site (`generate.py:912-921`), replacing:
  ```python
  def process_text(video):
      """Re-run the TEXT tier from the persisted word list -- no GPU, no punctuation LLM.

      Runs the identical text_stages() a fresh transcription runs, so a replay cannot
      quietly diverge from the run it claims to reproduce. Writes a new srt and conf;
      merge_pass then re-muxes the episode, because its stamp is text-stale."""
      stem = os.path.splitext(video)[0]
      rec = qc.Recorder()
      doc = read_words(stem, rec=rec)
      if doc is None:
          return "no-words"
  ```
  with:
  ```python
  def process_text(video):
      """Re-run the TEXT tier from the persisted word list -- no GPU, no punctuation LLM.

      Runs the identical text_stages() a fresh transcription runs, so a replay cannot
      quietly diverge from the run it claims to reproduce. Writes a new srt and conf;
      merge_pass then re-muxes the episode, because its stamp is text-stale."""
      stem = os.path.splitext(video)[0]
      rec = qc.Recorder()
      doc = read_words(stem, rec=rec, expect=decoder_identity())
      _note_words_stats(rec)
      if doc is None:
          return "no-words"
  ```
- [ ] Implement `process`'s write_words site (`generate.py:1036-1041`), replacing:
  ```python
      try:
          write_words(stem, words, segments, audio_duration, initial_prompt=INITIAL_PROMPT)
      except Exception as e:
          rec.count("words_missing")
          log("words.json write failed (episode stays GPU-only):", stem, e)
      return text_stages(stem, words, segments, audio_duration, rec, fail)
  ```
  with:
  ```python
      try:
          write_words(stem, words, segments, audio_duration, initial_prompt=INITIAL_PROMPT)
      except Exception as e:
          rec.count("words_missing")
          log("words.json write failed (episode stays GPU-only):", stem, e)
      _note_words_stats(rec)
      return text_stages(stem, words, segments, audio_duration, rec, fail)
  ```
- [ ] Implement `build_lastrun`'s signature and return dict (`generate.py:1044-1066`),
      replacing:
  ```python
  def build_lastrun(show, elapsed_s, episodes_total, transcribed, totals, census):
  ```
  with:
  ```python
  def build_lastrun(show, elapsed_s, episodes_total, transcribed, totals, census, words_totals=None):
  ```
  and, inside the function body, replacing:
  ```python
          "transcribe_stale": census["transcribe_stale"],
          "text_stale": census["text_stale"],
          "model": MODEL,
  ```
  with:
  ```python
          "transcribe_stale": census["transcribe_stale"],
          "text_stale": census["text_stale"],
          "words_missing": (words_totals or {}).get("words_missing", 0),
          "words_version_mismatch": (words_totals or {}).get("words_version_mismatch", 0),
          "words_reused": (words_totals or {}).get("words_reused", 0),
          "model": MODEL,
  ```
- [ ] Implement `main()`'s accumulation (`generate.py:1153-1173`), replacing:
  ```python
      t0 = time.monotonic()  # V2 C1: per-show run summary
      transcribed = 0
      totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
      # Text tier first: it is CPU-minutes per episode, so the cheap wins land before the
      # GPU queue starts consuming the night.
      for v in text_todo:
          log("→", os.path.basename(v), "(text)")
          try:
              log("  ", process_text(v))
          except Exception as e:
              log("  ERROR", type(e).__name__, e)  # one bad sidecar must not abort the show
      for v in transcribe_todo:
          log("→", os.path.basename(v))
          try:
              status = process(v)  # one bad episode must not abort the show
              log("  ", status)
              if status == "ok":
                  transcribed += 1
                  for k in totals:
                      totals[k] += _LAST_STATS.get(k, 0)
  ```
  with:
  ```python
      t0 = time.monotonic()  # V2 C1: per-show run summary
      transcribed = 0
      totals = {"cards_written": 0, "dropped_hallucination": 0, "collapsed_runs": 0, "flagged": 0}
      words_totals = {"words_missing": 0, "words_version_mismatch": 0, "words_reused": 0}
      # Text tier first: it is CPU-minutes per episode, so the cheap wins land before the
      # GPU queue starts consuming the night.
      for v in text_todo:
          log("→", os.path.basename(v), "(text)")
          try:
              status = process_text(v)
              log("  ", status)
              for k in words_totals:
                  words_totals[k] += _LAST_WORDS_STATS.get(k, 0)
          except Exception as e:
              log("  ERROR", type(e).__name__, e)  # one bad sidecar must not abort the show
      for v in transcribe_todo:
          log("→", os.path.basename(v))
          try:
              status = process(v)  # one bad episode must not abort the show
              log("  ", status)
              for k in words_totals:
                  words_totals[k] += _LAST_WORDS_STATS.get(k, 0)
              if status == "ok":
                  transcribed += 1
                  for k in totals:
                      totals[k] += _LAST_STATS.get(k, 0)
  ```
  and, further down (`generate.py:1202`), replacing:
  ```python
      lastrun = build_lastrun(show, round(time.monotonic() - t0, 1), len(todo), transcribed, totals, census)
  ```
  with:
  ```python
      lastrun = build_lastrun(show, round(time.monotonic() - t0, 1), len(todo), transcribed, totals, census, words_totals)
  ```
- [ ] Run `python3 -m pytest tests/test_generate.py -q`; expect pass.
- [ ] Run `ruff check .`; expect `"All checks passed!"`.
- [ ] Commit: `git commit -m "feat(generate): validate words.json against the decoder that would run today"`.

## Task 12: Unanchored policy reconciliation

Sprint: 012 Scope: [S-11]
Files: a vault operator note `2026-09-2x Unanchored Repair Policy.md` (deliverable, no
repo file); `.procoder/state/handoff.md` (lines 183-185 marked superseded, gitignored
local state, still edited); `docs/wiki/How-To-Guides.md` (line 44 replaced);
`docs/wiki/Reference.md` (line 106 row replaced); `tests/test_public_repo_hygiene.py`
(one new test). The decision-store write itself (part a) touches no repo file: it
writes to `DECISIONS_DIR` on the worker host, which is a runtime mount, not tracked.
Interfaces: none produced for other tasks. Consumes `decisions.locked(show, dir)`,
`decisions.load(show, dir)`, `decisions.record(store, orig, proposed, verdict, text="",
note="", promoted=None)`, `decisions.save(store, show, dir)`, `decisions.lookup(store,
orig, proposed)` exactly as they exist today (no code change to `decisions.py`).

- [ ] (a) OWNER/LIVE step, on the worker host. First find the running container --
      do not assume a name:
  ```bash
  docker ps --format '{{.Names}}\t{{.Image}}'
  ```
  Substitute the printed name for `<container>` below. Record these four rejected
  targets from `docs/Adversarial Reviews/REVIEW-2026-08-27-unanchored-repair-45-lines.md`
  (lines 34-35, 42-43, 50-51, 108-109) into the One Pace decision store:
  ```bash
  docker exec -i <container> python3 - <<'EOF'
  import decisions

  show = "One Pace"
  rejects = [
      ("We're looking for a factory.", "We're looking for a needle."),
      ("Spare Mata-koth for me!", "Sparing Mata-koth for me!"),
      ("It's a VIVRA card?", "It's a Vivi card?"),
      ("CP-0.", "CP?"),
  ]
  with decisions.locked(show):
      store = decisions.load(show)
      for orig, proposed in rejects:
          decisions.record(store, orig, proposed, "reject", note="REVIEW-2026-08-27 human verdict")
      ok = decisions.save(store, show)
      print("saved:", ok, "decisions:", len(store.get("decisions", [])))
  EOF
  ```
  Expect the printed line to read `saved: True decisions: <N>` where `<N>` is at least 4.
- [ ] Verify the four verdicts are readable back as `"reject"`:
  ```bash
  docker exec -i <container> python3 -c "
  import decisions
  store = decisions.load('One Pace')
  pairs = [
      (\"We're looking for a factory.\", \"We're looking for a needle.\"),
      ('Spare Mata-koth for me!', 'Sparing Mata-koth for me!'),
      (\"It's a VIVRA card?\", \"It's a Vivi card?\"),
      ('CP-0.', 'CP?'),
  ]
  for orig, proposed in pairs:
      e = decisions.lookup(store, orig, proposed)
      print(orig, '->', e.get('verdict') if e else None)
  "
  ```
  Expect all four printed lines to end in `-> reject`.
- [ ] (b) Implement the `handoff.md` supersede. Replace `.procoder/state/handoff.md:183-185`,
      currently:
  ```
  **Do not** flip `REPAIR_UNANCHORED` on before that read. Every S31 card is unanchored, so a
  regression there is permanent -- recovery is manual (edit glossary, re-run, CPU-tier), not
  automatic.
  ```
  with:
  ```
  **SUPERSEDED 2026-09-06.** `REPAIR_UNANCHORED` was flipped on in this host's compose
  before every one of the 45 lines below got a human read (see `common.py:167`'s v10
  changelog note, which is what forced the TEXT_VERSION bump that re-derives the whole
  library against it). 41 of the 45 were approved and 4 rejected
  (`REVIEW-2026-08-27-unanchored-repair-45-lines.md`); all 4 rejections are now recorded
  in the One Pace decision store as `reject` verdicts, so `repair.py`'s `[S-4]` consult
  refuses them on any future re-run. Recovery for a bad unanchored repair is a `reject`
  verdict through `decisions.record` followed by `review_apply.py`, not disabling the
  flag -- the flag stays on library-wide (owner decision, confirmed at sprint 010 open).
  ```
- [ ] (c) Implement the How-To-Guides.md reconciliation. Replace
      `docs/wiki/How-To-Guides.md:44`, currently:
  ```
  There is also a global `REPAIR_UNANCHORED` variable. **Do not use it.** It is recorded in no
  committed file, which is precisely how a season's corrections were once silently reverted to
  raw speech recognition.
  ```
  with:
  ```
  There is also a global `REPAIR_UNANCHORED` variable. It has been deployed library-wide
  on the reference install since 2026-09-06 (see `common.py`'s v10 changelog note) --
  every show without an explicit `unanchored_repair` field in its glossary is repaired
  unanchored by default there. **Prefer the per-show glossary field for any new
  install**: it is committed to git and reviewable, where the global flag is host
  configuration that a `git pull` cannot show you. If an unanchored repair ships
  something wrong, the recovery is a `reject` verdict recorded with `decisions.record`
  followed by `review_apply.py`, not disabling the flag.
  ```
- [ ] Implement the Reference.md row reconciliation. Replace
      `docs/wiki/Reference.md:106`'s row, currently:
  ```
  | `REPAIR_UNANCHORED`                | _(unset — closed)_                          | Global override; prefer the per-show glossary field                                                                                                                                                                                              |
  ```
  with:
  ```
  | `REPAIR_UNANCHORED`                | `1` (deployed 2026-09-06 on the reference install) | Global override; per-show glossary field preferred for new installs — see How-To-Guides.md |
  ```
- [ ] (d) Write the vault operator note. Deliverable file:
      `/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/2026-09-2x Unanchored Repair Policy.md`.
      On the worker host, list the glossaries directory to determine which shows declare
      `unanchored_repair` (verify the mount path with `docker exec <container> env | grep
GLOSSARY_DIR` first -- do not assume `/config/glossaries`):
  ```bash
  docker exec <container> python3 -c "
  import glob, json, os
  d = os.environ.get('GLOSSARY_DIR', '/config/glossaries')
  for p in sorted(glob.glob(os.path.join(d, '*.json'))):
      try:
          cfg = json.load(open(p))
      except Exception as e:
          print(os.path.basename(p), 'UNREADABLE', e)
          continue
      print(os.path.basename(p), 'unanchored_repair=', bool(cfg.get('unanchored_repair')))
  "
  ```
  Write the note with these literal fields, filled from the command's real output (never
  fabricated):
  ```
  # 2026-09-2x Unanchored Repair Policy

  ## Deployed value
  REPAIR_UNANCHORED=1, set in <worker host>'s compose since 2026-09-06 (common.py v10).

  ## Shows covered by the 45-line human review
  One Pace S31E01-E03 (docs/Adversarial Reviews/REVIEW-2026-08-27-unanchored-repair-45-lines.md):
  41 of 45 lines approved, 4 rejected -- all 4 now recorded as `reject` verdicts in the
  One Pace decision store.

  ## Shows running unreviewed under the global flag
  <paste the per-show glossary listing from the command above; every show whose glossary
  has no unanchored_repair field but is nonetheless running unanchored repair because the
  GLOBAL flag is on -- these have zero human review coverage>

  ## Recovery procedure
  1. Identify the bad line's exact ORIG/PROPOSED text pair from the shipped .ass or a qc
     event.
  2. `decisions.record(store, orig, proposed, "reject", note="<why>")` under
     `decisions.locked(show, dir)`, then `decisions.save(store, show, dir)`.
  3. Run `review_apply.py` for the show so the stored verdict reaches the shipped track
     without a full re-transcribe.
  ```
- [ ] Write the failing docs-honesty test:
  ```python
  def test_the_wiki_discloses_when_repair_unanchored_was_deployed():
      """The wiki used to say 'do not use REPAIR_UNANCHORED' / 'unset -- closed' while the
      reference install had quietly turned it on months earlier (common.py's v10 note,
      2026-09-06) -- exactly the silent-drift failure this suite exists to catch, just in
      prose instead of code."""
      for path in _tracked("docs/wiki/How-To-Guides.md", "docs/wiki/Reference.md"):
          with open(path, encoding="utf-8") as f:
              text = f.read()
          assert "2026-09-06" in text, f"{path} does not disclose the REPAIR_UNANCHORED deploy date"
  ```
  Run `python3 -m pytest tests/test_public_repo_hygiene.py -k test_the_wiki_discloses_when_repair_unanchored_was_deployed -q`;
  expect FAIL with `"AssertionError: docs/wiki/How-To-Guides.md does not disclose the REPAIR_UNANCHORED deploy date"`.
- [ ] Run `python3 -m pytest tests/test_public_repo_hygiene.py -q`; expect pass.
- [ ] Run `ruff check .`; expect `"All checks passed!"`.
- [ ] Commit: `git commit -m "docs(unanchored): reconcile wiki/handoff with the 2026-09-06 deploy and record the 4 S31 rejects"`
      (this commit covers b/c/the test; part a is a live-host action with no repo diff and
      is not part of this commit).

## Task 13: Guard close + secondary retire

Sprint: 012 Scope: [S-12] [S-13]
Files: `ISSUE-phonetic-name-guard.md` (status header prepended), `IMPROVEMENTS.md`
(§5 removed at lines 174-253; two residual mentions at lines 273 and 370 updated),
`REVIEW.md` (lines 1025-1029, 1074, and 1099 updated), `tests/test_public_repo_hygiene.py`
(one new regression test).
Interfaces: none produced for other tasks; no code changes (`repair.py` is read, not
edited -- `invents_name`/`substitutes_a_vouched_name`/`PHONETIC_MIN` already exist and
already match the issue's proposed fix).

- [ ] Implement the ISSUE-phonetic-name-guard.md status header. Insert before the
      file's current first line (`## Problem`):
  ```
  **Status: resolved differently (2026-09-2x).** The guard shipped, but not as the
  edit-distance check this issue proposes. `repair.invents_name(orig, new, gloss)`
  (repair.py:418) refuses a repair that introduces a capitalised, glossary-shaped token
  found in neither the glossary nor the original -- membership only, no edit distance,
  by deliberate design (repair.py:437-438). `repair.substitutes_a_vouched_name(orig,
  new, gloss)` (repair.py:474) covers the phonetic half this issue asked for: it refuses
  an UNKNOWN -> KNOWN substitution unless `jellyfish.jaro_winkler_similarity` clears
  `PHONETIC_MIN` (repair.py:401, `REPAIR_PHONETIC_MIN` env, default `0.75`). Both are
  live and tested; no further work is planned against this issue.

  ---

  ```
  (the file's original `## Problem` line follows unchanged).
- [ ] Implement the IMPROVEMENTS.md §5 removal. Replace `IMPROVEMENTS.md:174-253`
      (the entire `## 5. Architecture: Two-Backend Repair` section, from its header through
      its closing `---`) with:
  ```
  _Retired: `REPAIR_MODEL_SECONDARY` covers the two-pass check; a second backend was
  never built._

  ---
  ```
  (the file's `## 6. Recommended Action Plan` at the old line 255 follows unchanged).
- [ ] Implement the two residual IMPROVEMENTS.md mentions outside §5, found by
      `grep -n REPAIR_BACKEND_SECONDARY IMPROVEMENTS.md` after the §5 removal. Delete the
      Phase 2 table row at `IMPROVEMENTS.md:273`, currently:
  ```
  | 4   | Add `REPAIR_BACKEND_SECONDARY` env var         | ~10 line code change in `repair.py`     |
  ```
  entirely (the numbering gap at 5/6/7 is left as-is; these are table labels, not code).
  Delete the candidate-value table row at `IMPROVEMENTS.md:370`, currently:
  ```
  | `REPAIR_BACKEND_SECONDARY` | —                                   | `llamacpp`         | **Needs code change** |
  ```
  entirely.
- [ ] Implement `REVIEW.md:1025-1029`'s replacement, currently:
  ```
  2. **`REPAIR_BACKEND_SECONDARY` is not implemented.**
     `IMPROVEMENTS.md` recommends a separate backend for the secondary verification pass
     (e.g., GPU primary / CPU secondary). `repair.py` dispatches both primary and
     secondary through the same `REPAIR_BACKEND`, so a true two-backend setup is
     impossible without code changes.
  ```
  with:
  ```
  2. **A second backend for the repair secondary pass was proposed and retired
     (2026-09-2x).** `IMPROVEMENTS.md` §5 described adding a separate backend so the
     primary and secondary repair passes could run on different backends (GPU vs CPU);
     it was never built, and `REPAIR_MODEL_SECONDARY` already covers the second-opinion
     need with a second MODEL on the SAME backend. See `IMPROVEMENTS.md`'s one-line
     pointer where §5 used to be.
  ```
- [ ] Implement `REVIEW.md:1074`'s replacement, currently:
  ```
  ships two documented features (phonetic-name guard and `REPAIR_BACKEND_SECONDARY`)
  that are not actually implemented. Combined with the broken local test environment,
  ```
  with:
  ```
  shipped two documented gaps that are now resolved rather than implemented: the
  phonetic-name guard (`ISSUE-phonetic-name-guard.md`'s status header) and the
  separate secondary-pass backend proposal (retired, see the outstanding-issues list
  above). Combined with the broken local test environment,
  ```
- [ ] Implement `REVIEW.md:1099`'s row replacement, currently:
  ```
  | #2 `REPAIR_BACKEND_SECONDARY`        | the two-pass re-check exists as `REPAIR_MODEL_SECONDARY` (a second _model_, not a second backend — a separate GPU/CPU backend split is still unimplemented) |
  ```
  with:
  ```
  | #2 (separate secondary-pass backend) | retired (2026-09-2x) — `REPAIR_MODEL_SECONDARY` already covers the second-opinion need; a second backend was never built |
  ```
- [ ] Write the failing regression test that makes the grep verification below
      permanent, in `tests/test_public_repo_hygiene.py`:
  ```python
  def test_repair_backend_secondary_is_retired_not_referenced_outside_history():
      """REPAIR_BACKEND_SECONDARY was proposed in IMPROVEMENTS.md, never implemented,
      and retired 2026-09-2x (REVIEW.md's outstanding-issues list, `.procoder/specs/
      v0-2-0-hardening.md`'s S-13). A name that keeps reappearing in ACTIVE docs after
      retirement is exactly the kind of drift IMPROVEMENTS.md and REVIEW.md used to
      carry themselves."""
      allowed_prefixes = (
          "docs/Adversarial Reviews/",
          "docs/superpowers/plans/2026-08-22-observability-and-dead-path-cleanup.md",
          ".procoder/specs/v0-2-0-hardening.md",
      )
      offenders = []
      for path in _tracked("*.md"):
          if any(path.startswith(p) for p in allowed_prefixes):
              continue
          with open(path, encoding="utf-8", errors="replace") as f:
              if "REPAIR_BACKEND_SECONDARY" in f.read():
                  offenders.append(path)
      assert not offenders, f"REPAIR_BACKEND_SECONDARY referenced outside history: {offenders}"
  ```
  Run `python3 -m pytest tests/test_public_repo_hygiene.py -k test_repair_backend_secondary_is_retired_not_referenced_outside_history -q`;
  expect FAIL with `"REPAIR_BACKEND_SECONDARY referenced outside history: ['IMPROVEMENTS.md', 'REVIEW.md']"`
  (run BEFORE the doc edits above; after them the offenders list is empty).
- [ ] Run the grep verification directly, to see the same result the test now pins:
  ```bash
  grep -rn REPAIR_BACKEND_SECONDARY --include=*.md .
  ```
  Expect matches ONLY under `docs/Adversarial Reviews/` (historical measurement logs),
  in `docs/superpowers/plans/2026-08-22-observability-and-dead-path-cleanup.md` (an
  already-completed historical plan), and in `.procoder/specs/v0-2-0-hardening.md` (the
  current spec's own S-13 entry, which names the retired variable to describe retiring
  it). Zero matches in `IMPROVEMENTS.md` or `REVIEW.md`.
- [ ] Run `python3 -m pytest tests/test_public_repo_hygiene.py -q`; expect pass.
- [ ] Run `ruff check .`; expect `"All checks passed!"`.
- [ ] Commit: `git commit -m "docs(repair): close the phonetic-guard issue and retire REPAIR_BACKEND_SECONDARY"`.

## Task 14: GET gating + REQUIRE_TOKEN + posture docs

Sprint: 013 Scope: [S-14]
Files: `review_server.py` (authorised() drops its GET/HEAD bypass, route()'s 401 message
changes, serve() gains a REQUIRE_TOKEN pre-flight exit), `tests/test_review_server.py`
(two existing tests updated to the new contract, new tests for the gate and for
REQUIRE_TOKEN), `SECURITY.md` (the GET-routes paragraph, corrected and rewritten),
`README.md` (the review-server paragraph gains one sentence), `docs/wiki/Reference.md`
(env table rows for `REQUIRE_TOKEN`/`REVIEW_AUTH`, route table gets `/healthz`, the
Authentication section's "read routes never do" sentence is replaced).
Interfaces: this task assumes sprint 010's task has already changed
`auth_required()` (currently, verified at review_server.py:212-214, it reads `return not
("REVIEW_TOKEN" in os.environ and os.environ["REVIEW_TOKEN"] == "")`) to the contract the
plan's shared interface states: empty/unset `REVIEW_TOKEN` no longer disables auth; only
`REVIEW_AUTH=off` does. This task does not re-implement `auth_required()` and every test
below drives that contract only through `REVIEW_AUTH=off` (never through an empty
`REVIEW_TOKEN`, which sprint 010 already stopped meaning "disabled"). This task adds
`authorised(method, presented) -> bool` (signature unchanged) and
`route(method: str, path: str, body: dict, token) -> tuple` (401 payload text changes).

Finding from reading `do_GET` (review_server.py:1122-1133): `route()` is reached ONLY for
paths starting `/api/` — `/`, `/index.html` and `/shared` are served directly inside
`do_GET`, calling `render_page()`/`render_shared()` in-process, before `route()` (and
therefore `authorised()`) is ever reached for them. Making `authorised()` require the
token for every method, with no GET/HEAD carve-out, gates every `/api/*` route (GET and
HEAD included) but does nothing, by itself, for `/`, `/index.html` or `/shared`: those
three render `handle_index()`/`handle_episode()`/`handle_shared()` output directly, which
discloses every absolute stem and the original/proposed subtitle text under review to any
unauthenticated LAN peer who simply requests the page. That gap is closed in Task 17 (same
sprint), which gates those three pages too, via a cookie the token box's own JS sets — a
plain page navigation cannot carry the `X-Review-Token` header a `curl`/`fetch()` caller
uses. Only `/healthz` (wired in Task 16) stays open with no token check of any kind, by
design — it reports process liveness, nothing about episodes.

- [ ] Write the failing test in `tests/test_review_server.py` (add `import pytest` to the
      import block at the top, alongside the existing `import json` / `import os` /
      `import stat` / `from typing import Any` / `import decisions` / `import review_server`
      / `import unresolved`):
  ```python
  def test_get_api_episodes_without_token_is_401_with_the_literal_body(tmp_path, monkeypatch):
      """authorised() now gates GET the same as POST for every /api/* route -- route()
      is reached only from api paths (verified: do_GET serves /, /index.html and
      /shared directly, before route() is ever called), so this cannot affect those
      three paths or /healthz (Task 16)."""
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      tok = review_server.resolve_token(str(tmp_path))

      wire = _Wire()
      h = wire.as_handler("/api/episodes")
      h.do_GET()
      assert wire.status == 401
      assert json.loads(wire.wfile.getvalue()) == {"error": "a token is required"}

      wire2 = _Wire()
      wire2.headers[review_server.TOKEN_HEADER] = tok
      h2 = wire2.as_handler("/api/episodes")
      h2.do_GET()
      assert wire2.status == 200


  def test_head_on_api_paths_is_gated_the_same_as_get():
      """No do_HEAD is defined (verified: Handler defines only do_GET and do_POST), so
      HEAD is exercised against authorised() directly -- the one function route()
      consults for every method. A future do_HEAD inherits the same gate for free."""
      assert review_server.authorised("HEAD", None) is False
      assert review_server.authorised("HEAD", "wrong") is False


  def test_get_index_page_stays_open_without_a_token(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(review_server, "known_stems", lambda: [])

      wire = _Wire()
      h = wire.as_handler("/")
      h.do_GET()
      assert wire.status == 200


  def test_require_token_with_auth_disabled_exits_before_resolving_a_token(monkeypatch):
      """REQUIRE_TOKEN=1 is a fail-closed check for an unattended deploy: refuse to
      start at all rather than run with REVIEW_AUTH=off silently. Checked before
      resolve_token() (which would otherwise mint/print a token nobody needs) and
      before BoundedHTTPServer is constructed, so nothing binds even transiently."""
      monkeypatch.setenv("REQUIRE_TOKEN", "1")
      monkeypatch.setattr(review_server, "auth_required", lambda: False)
      monkeypatch.setattr(
          review_server,
          "resolve_token",
          lambda *a, **k: pytest.fail("resolve_token must not run when REQUIRE_TOKEN blocks startup"),
      )
      monkeypatch.setattr(
          review_server,
          "BoundedHTTPServer",
          lambda *a, **k: pytest.fail("BoundedHTTPServer must not be constructed"),
      )

      with pytest.raises(SystemExit) as exc:
          review_server.serve()

      assert exc.value.code == 2


  def test_require_token_with_auth_enabled_does_not_exit(monkeypatch):
      monkeypatch.setenv("REQUIRE_TOKEN", "1")
      monkeypatch.setattr(review_server, "auth_required", lambda: True)
      monkeypatch.setattr(review_server, "resolve_token", lambda *a, **k: "tok")
      monkeypatch.setattr(review_server, "announce_token", lambda *a, **k: None)

      class _FakeServer:
          server_address = ("127.0.0.1", 0)

          def serve_forever(self):
              raise KeyboardInterrupt  # stop the loop; reaching this proves no exit fired

      monkeypatch.setattr(review_server, "BoundedHTTPServer", lambda *a, **k: _FakeServer())
      monkeypatch.setattr(review_server.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())

      with pytest.raises(KeyboardInterrupt):
          review_server.serve()
  ```
      Run `python3 -m pytest tests/test_review_server.py -k "api_episodes_without_token or head_on_api or index_page_stays_open or require_token" -q`;
  expect FAIL: the first test fails with `assert 200 == 401` (the current
  `authorised()` returns `True` for every GET); `test_require_token_with_auth_disabled...`
  fails with `Failed: resolve_token must not run when REQUIRE_TOKEN blocks startup`
  (nothing in `serve()` checks `REQUIRE_TOKEN` yet, so it falls straight through).
- [ ] Update the two existing tests that assert the OLD (GET-is-never-gated) contract, so
      the suite does not hold two contradictory truths at once. In
      `tests/test_review_server.py`, replace:
  ```python
      assert review_server.authorised("GET", None) is True, "reads are not gated"
  ```
      with:
  ```python
      assert review_server.authorised("GET", None) is False, "GET on an api path is gated like a write"
      assert review_server.authorised("GET", tok) is True
  ```
      (this is inside `test_a_write_route_without_the_token_is_refused_and_a_read_route_is_not`;
  `tok` is already bound two lines above via `review_server.resolve_token(str(tmp_path))`
  -- add that line if the test does not already capture it under that name). And in
  `test_the_router_gates_writes_and_passes_reads`, replace:
  ```python
      assert review_server.route("GET", "/api/episodes", {}, None)[0] == 200
  ```
      with:
  ```python
      assert review_server.route("GET", "/api/episodes", {}, None)[0] == 401
      assert review_server.route("GET", "/api/episodes", {}, tok)[0] == 200
  ```
- [ ] Implement minimally. In `review_server.py`, replace `authorised()`:
  ```python
  def authorised(method: str, presented) -> bool:
      """Write routes require the token; read routes never do."""
      if method.upper() in ("GET", "HEAD"):
          return True
      if not auth_required():
          return True
      # compare_digest, not ==: a plain comparison leaks the shared prefix through timing,
      # and this token is the only thing between a LAN and a root-owned write endpoint.
      return bool(presented) and secrets.compare_digest(str(presented), resolve_token())
  ```
      with:
  ```python
  def authorised(method: str, presented) -> bool:
      """Every route behind route() requires the token once auth is required -- GET and
      HEAD included. route() itself is reached only for /api/* paths; do_GET calls
      this function directly for /, /index.html and /shared too (Task 17), to decide
      whether to render the real page or a locked shell. Only /healthz bypasses this
      function entirely, structurally -- it reports process liveness, nothing about
      episodes."""
      if not auth_required():
          return True
      # compare_digest, not ==: a plain comparison leaks the shared prefix through timing,
      # and this token is the only thing between a LAN and a root-owned write endpoint.
      return bool(presented) and secrets.compare_digest(str(presented), resolve_token())
  ```
      In `route()`, replace:
  ```python
      if not authorised(method, token):
          return 401, {"error": "a token is required for writes"}
  ```
      with:
  ```python
      if not authorised(method, token):
          return 401, {"error": "a token is required"}
  ```
      In `serve()`, replace:
  ```python
  def serve(port: int = 0):
      resolve_token()  # generates and prints the VALUE on first start, before anything is served
      announce_token()  # and on every start, says where to find it
      srv = BoundedHTTPServer((REVIEW_BIND, port or REVIEW_PORT), Handler)
  ```
      with:
  ```python
  def serve(port: int = 0):
      # Checked before ANYTHING else, including resolve_token() (which would otherwise
      # mint/print a token nobody needs). A fail-closed opt-in for an unattended deploy:
      # REQUIRE_TOKEN=1 means "never start wide open", so a REVIEW_AUTH=off left behind
      # in an old .env is caught at start, not discovered later by whoever finds the
      # port open.
      if os.environ.get("REQUIRE_TOKEN") == "1" and not auth_required():
          log("review server: REQUIRE_TOKEN=1 but auth is disabled (REVIEW_AUTH=off)")
          raise SystemExit(2)
      resolve_token()  # generates and prints the VALUE on first start, before anything is served
      announce_token()  # and on every start, says where to find it
      srv = BoundedHTTPServer((REVIEW_BIND, port or REVIEW_PORT), Handler)
  ```
      Note for the reviewer: `route()`'s 404 fallback (an unmapped path under something
  other than `/api/`, reached only if a client GETs a path `do_GET` does not special-case)
  now also 401s without a token before it ever reaches the 404. Harmless -- nothing
  maps such a path to data -- but worth stating rather than leaving a reviewer to
  discover it.
- [ ] Run `python3 -m pytest tests/test_review_server.py -q`; expect pass.
- [ ] Implement the doc changes. In `SECURITY.md`, replace the paragraph (lines 27-30):
  ```
  GET routes (the episode/queue listing) are unauthenticated by design — they disclose show
  names and episode counts, the same information any DLNA browse or Plex share on the same
  network already exposes. Only the write routes (recording a verdict, applying decisions)
  require the token.
  ```
      with:
  ```
  GET routes disclose more than show names and episode counts — the JSON (and the
  review page itself) includes absolute `stem` paths (`handle_index`, `handle_episode`
  and `handle_shared` all carry it) and the original/proposed subtitle text under
  review. Every route now requires the token: `/api/*` for GET and HEAD as well as for
  writes — `curl http://host:8842/api/episodes` without the header gets a 401, where it
  used to return the whole index — and the review pages (`/`, `/index.html`, `/shared`)
  via a cookie the token box's own JS sets once you paste the token (Task 17; a plain
  page navigation cannot carry the `X-Review-Token` header a `curl`/`fetch()` caller
  uses). Without a token, cookie or header, a page renders an empty shell asking for
  one — no episode, no stem, no subtitle text. `/healthz` is the one true exception: it
  reports process liveness only (no path, no subtitle text, not gated at all) so the
  Docker `HEALTHCHECK` can reach it. Set `REQUIRE_TOKEN=1` if you want the process to
  refuse to start outright rather than run with `REVIEW_AUTH=off`.
  ```
- [ ] In `README.md`, immediately after the sentence ending
      `for the full auth model.` (the sentence that links SECURITY.md, in the "Reviewing what the
      repair stage changed" section), insert:
  ```
  The page itself now needs the token too — paste it into the box once and its own JS
  sets a cookie, so a plain page load carries it the same way a browser cookie always
  does (Task 17); without it you get an empty shell asking for the token, never the
  episode list. The `/api/*` JSON routes underneath it (`/api/episodes`, `/api/episode`,
  `/api/shared`, and the write routes) take it as a header instead — that's what the
  page's own `fetch()` calls already send. `curl` any of them without either and you get
  a 401. Set `REQUIRE_TOKEN=1` if you want the container to refuse to start rather than
  silently run with `REVIEW_AUTH=off`.
  ```
- [ ] In `docs/wiki/Reference.md`, in the "Review server" env table (after the
      `REVIEW_RESTART` row), add two rows:
  ```
  | `REQUIRE_TOKEN`         | _(unset)_                        | `1` refuses to start if auth ends up disabled |
  | `REVIEW_AUTH`           | _(unset)_                        | `off` disables auth (see sprint 010)          |
  ```
      In the route table, add a row after the `/shared` row:
  ```
  | GET    | `/healthz`         | Liveness probe for the Docker `HEALTHCHECK` — open, no token          |
  ```
      Replace the sentence:
  ```
  **Write routes require the token. Read routes never do.** The server runs in a root-owned
  process tree and its write routes rewrite subtitles and force re-muxes, so do not expose it
  to a network you do not control.
  ```
      with:
  ```
  **Every route requires the token now.** `/api/*` takes it as the `X-Review-Token`
  header, for GET and HEAD as well as for writes. `/`, `/index.html` and `/shared` take
  it as a cookie the token box's own JS sets (Task 17) — without it they render a
  locked shell instead of the real page. Only `/healthz` is never gated at all. The
  server runs in a root-owned process tree and its write routes rewrite subtitles and
  force re-muxes, so do not expose it to a network you do not control.
  ```
- [ ] Run `python3 -m pytest -q`; expect pass.
- [ ] Run `ruff check .`; expect "All checks passed!"
- [ ] Commit: `git commit -m "fix(review_server): gate GET/HEAD on /api/* and add REQUIRE_TOKEN"`

## Task 15: real-socket HTTP test

Sprint: 013 Scope: [S-15]
Files: `tests/test_review_server_http.py` (new — the only file this task touches; no
production code changes, since the behaviour under test — `authorised()`'s gate after
Task 14, `Handler.timeout`, `BoundedHTTPServer`'s semaphore — already exists).
Interfaces consumed: `review_server.BoundedHTTPServer`, `review_server.Handler`,
`review_server.resolve_token`, `review_server.TOKEN_DIR`, `review_server.known_stems`,
`review_server.TOKEN_HEADER`, `review_server.MAX_CONCURRENT`. No new interfaces produced.

This is the layer `tests/test_review_server.py`'s `_Wire` fixture (lines 462-494,
verified: it drives `Handler.do_POST`/`do_GET` with fake `rfile`/`wfile` streams and never
opens a socket) cannot reach: real TCP accept, real per-connection threads, a real socket
timeout firing. There is no production-code change in this task, so there is no red phase
in the usual sense — each test is written once and is expected to pass immediately,
because it is pinning behaviour Tasks 1-14 already implement correctly. What IS being
verified for the first time is that the behaviour survives an actual socket, not just the
`route()`-level unit tests.

- [ ] Write `tests/test_review_server_http.py`:
  ```python
  """Real-socket coverage of the review server's transport layer -- the layer _Wire
  (tests/test_review_server.py) cannot reach because it drives Handler methods with
  fake streams and never opens a socket. Everything else about the server (routing,
  auth logic, the HTML the page renders) is covered there, without a socket, and stays
  there; this file exists only for the three things that need a real one: accept,
  per-connection threading, and a socket-level read timeout actually firing."""

  import http.client
  import socket
  import threading
  import time

  import pytest

  import review_server


  @pytest.fixture
  def live_server(monkeypatch, tmp_path):
      """A real BoundedHTTPServer bound to 127.0.0.1:0 (OS-assigned port), serving on a
      daemon thread. Yields (host, port, token); shuts down on teardown."""
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      tok = review_server.resolve_token(str(tmp_path))

      srv = review_server.BoundedHTTPServer(("127.0.0.1", 0), review_server.Handler)
      host, port = srv.server_address
      t = threading.Thread(target=srv.serve_forever, daemon=True)
      t.start()
      try:
          yield host, port, tok
      finally:
          srv.shutdown()
          srv.server_close()
          t.join(timeout=5)


  def test_get_api_episodes_401_without_token_200_with_token(live_server):
      host, port, tok = live_server
      conn = http.client.HTTPConnection(host, port, timeout=5)
      conn.request("GET", "/api/episodes")
      r = conn.getresponse()
      assert r.status == 401
      r.read()
      conn.close()

      conn = http.client.HTTPConnection(host, port, timeout=5)
      conn.request("GET", "/api/episodes", headers={review_server.TOKEN_HEADER: tok})
      r = conn.getresponse()
      assert r.status == 200
      r.read()
      conn.close()


  def test_a_stalled_client_is_closed_after_the_handler_timeout(live_server, monkeypatch):
      """Handler.timeout (30s in production) bounds how long a connection that sends
      headers and then stops can pin a worker thread. Set to 1s here so the test does
      not itself take 30s; read live, right before opening the stalling socket, not
      patched at server-construction time -- timeout is read per-connection in
      StreamRequestHandler.setup(), not captured by BoundedHTTPServer.__init__."""
      monkeypatch.setattr(review_server.Handler, "timeout", 1)
      host, port, _ = live_server

      sock = socket.create_connection((host, port), timeout=5)
      try:
          sock.sendall(b"GET /api/episodes HTTP/1.1\r\nHost: x\r\n")  # no terminating blank line
          start = time.monotonic()
          data = sock.recv(4096)
          elapsed = time.monotonic() - start
      finally:
          sock.close()

      assert data == b"", "the connection must be closed, not held open indefinitely"
      assert elapsed < 3, f"must close at ~1s (Handler.timeout=1), took {elapsed:.1f}s"


  def test_the_third_connection_over_max_concurrent_is_closed(monkeypatch, tmp_path):
      """MAX_CONCURRENT is read at BoundedHTTPServer.__init__ (self._slots =
      threading.Semaphore(MAX_CONCURRENT)), so it must be monkeypatched BEFORE
      construction -- patching it after would leave the semaphore at its already-built
      size. Uses its own server (not the live_server fixture, which builds with the
      real MAX_CONCURRENT=16 before this test could patch it) and its own, longer
      Handler.timeout (5s, not the 1s the stall test uses above) so the two connections
      held open to fill both slots do not get closed out from under the test before the
      third connection is attempted."""
      monkeypatch.setattr(review_server, "MAX_CONCURRENT", 2)
      monkeypatch.setattr(review_server.Handler, "timeout", 5)
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      review_server.resolve_token(str(tmp_path))

      srv = review_server.BoundedHTTPServer(("127.0.0.1", 0), review_server.Handler)
      host, port = srv.server_address
      t = threading.Thread(target=srv.serve_forever, daemon=True)
      t.start()
      sockets = []
      try:
          for _ in range(2):
              s = socket.create_connection((host, port), timeout=5)
              s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n")  # no blank line -- holds the slot
              sockets.append(s)
          time.sleep(0.2)  # let both connections be accepted and their handlers start

          third = socket.create_connection((host, port), timeout=5)
          sockets.append(third)
          data = third.recv(4096)

          assert data == b"", "the third connection must be refused while 2 are already in flight"
      finally:
          for s in sockets:
              try:
                  s.close()
              except OSError:
                  pass
          srv.shutdown()
          srv.server_close()
          t.join(timeout=5)
  ```
- [ ] Run `python3 -m pytest tests/test_review_server_http.py -q`; expect pass immediately
      (no red phase: this task adds coverage of transport behaviour Tasks 1-14 already
      implement; there is no production-code change here for a failing state to precede).
- [ ] Run `python3 -m pytest -q`; expect pass.
- [ ] Run `ruff check .`; expect "All checks passed!"
- [ ] Commit: `git commit -m "test(review_server): cover auth, timeout and concurrency over a real socket"`

## Task 16: heartbeat + /healthz + HEALTHCHECK

Sprint: 013 Scope: [S-16]
Files: `common.py` (adds `HEARTBEAT_PATH`, `heartbeat()`, `read_heartbeat()`),
`tests/test_common.py` (tests for the three), `gen_loop.sh` (two `heartbeat()` calls at
the sweep boundaries), `merge_pass.sh` (rewrites the stem loop out of a pipeline subshell,
adds `considered`/`changed`/`failed`/`held` counters and a `heartbeat()` call),
`tests/test_merge_pass_heartbeat.py` (new — structural checks on `merge_pass.sh`, same
static-parse style as `tests/test_gen_loop_set_e.py`), `review_server.py` (adds
`handle_healthz()` and wires `GET /healthz` into `do_GET`, ahead of `route()`),
`tests/test_review_server.py` (tests for `handle_healthz()`), `Dockerfile.builder` (adds
`HEALTHCHECK`), `tests/test_dockerfile_copy.py` (a structural test for that line),
`compose.yaml` (a matching `healthcheck:` block — no automated test: nothing in this
repo's CI executes compose files; verified by eye against the `Dockerfile.builder` line).
Interfaces produced: `common.HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH",
"/config/heartbeat.json")`, `common.heartbeat(**fields) -> None`,
`common.read_heartbeat() -> dict`, `review_server.handle_healthz() -> tuple`.

Design decision this task must state explicitly rather than leave implied: staleness is
judged from `last_sweep_end` ALONE, never from `last_sweep_start`. A heartbeat whose
`last_sweep_start` is recent but whose `last_sweep_end` is old (or absent) is reported
UNHEALTHY once past the `3 * RESCAN_INTERVAL` floor. That is deliberate: `/healthz` is a
coarse "is the loop still alive at all" signal for the container orchestrator, not a fine
per-episode one that this sprint does not add — an in-progress sweep is indistinguishable,
at this granularity, from one wedged mid-episode with no crash, which is exactly the
failure mode this exists to catch. An operator with an unusually large library should
raise `RESCAN_INTERVAL` rather than have this probe special-case a sweep in progress. A
heartbeat with `last_sweep_start` set but no `last_sweep_end` at all (the very first sweep
since container start) is reported unhealthy immediately, with reason `"stale: no sweep
has completed yet"` -- not treated as fresh, and not a crash on `now - None`.

- [ ] Write the failing tests in `tests/test_common.py` (add `import time` to the existing
      `import json` / `import os` / `import types` / `import pysubs2` / `import common`
      block):
  ```python
  def test_heartbeat_merges_rather_than_replaces(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(last_sweep_start=1.0, considered=5)
      common.heartbeat(last_sweep_end=2.0)  # a second writer, later, different fields

      hb = common.read_heartbeat()

      assert hb["last_sweep_start"] == 1.0, "the first writer's field must survive the second write"
      assert hb["considered"] == 5
      assert hb["last_sweep_end"] == 2.0


  def test_heartbeat_write_is_atomic_no_tmp_file_left_behind(tmp_path, monkeypatch):
      path = tmp_path / "heartbeat.json"
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(path))
      common.heartbeat(last_sweep_start=1.0)

      assert path.exists()
      assert list(tmp_path.glob("*.tmp")) == [], "the mkstemp temp file must be replaced, not left behind"


  def test_read_heartbeat_missing_file_returns_empty_dict(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "does-not-exist.json"))
      assert common.read_heartbeat() == {}
  ```
      Run `python3 -m pytest tests/test_common.py -k heartbeat -q`; expect FAIL with
  "AttributeError: module 'common' has no attribute 'heartbeat'".
- [ ] Implement minimally. Append to the end of `common.py` (after `within_window`):
  ```python
  HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH", "/config/heartbeat.json")


  def read_heartbeat() -> dict:
      """The heartbeat fields, or {} when the file is absent, unreadable or not a
      JSON object. Never raises -- a caller like /healthz must be able to treat any
      failure here identically to "no heartbeat has ever been written"."""
      try:
          with open(HEARTBEAT_PATH, encoding="utf-8") as f:
              data = json.load(f)
          return data if isinstance(data, dict) else {}
      except (OSError, ValueError):
          return {}


  def heartbeat(**fields) -> None:
      """Merge-write process liveness facts into HEARTBEAT_PATH, atomically.

      MERGE, not replace: gen_loop.sh writes last_sweep_start/last_sweep_end and
      merge_pass.sh writes considered/changed/failed/held/roots_readable/
      order_file_present/last_success_stem_name/last_error, from two separate shells
      that never see each other's values -- a replace would have the second writer of
      a pass erase the first's fields. Atomic via the same mkstemp + os.replace idiom
      as decisions.save and unresolved._rewrite: a reader in review_server's
      /healthz sees the old file or the new one, never a partial write. NEVER RAISES
      past its own failure: a heartbeat write that took a loop down would be worse
      than a stale heartbeat, which /healthz already reports as unhealthy on its own."""
      try:
          existing = read_heartbeat()
          existing.update(fields)
          d = os.path.dirname(HEARTBEAT_PATH) or "/config"
          os.makedirs(d, exist_ok=True)
          fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(HEARTBEAT_PATH) + ".", suffix=".tmp")
          with os.fdopen(fd, "w", encoding="utf-8") as f:
              json.dump(existing, f)
          os.replace(tmp, HEARTBEAT_PATH)
      except OSError as e:
          log(f"heartbeat: could not write {HEARTBEAT_PATH} ({e})")
  ```
- [ ] Run `python3 -m pytest tests/test_common.py -q`; expect pass.
- [ ] Wire `gen_loop.sh` at its two sweep boundaries. Replace:
  ```sh
  	echo "==== GENERATE SWEEP $(date) ===="
  ```
      with:
  ```sh
  	echo "==== GENERATE SWEEP $(date) ===="
  	python3 -c "import time, common; common.heartbeat(last_sweep_start=time.time())" </dev/null ||
  		echo "  heartbeat write failed (continuing)"
  ```
      and replace:
  ```sh
  	echo "==== SWEEP COMPLETE — idle ${RESCAN_INTERVAL:-21600}s $(date) ===="
  	sleep "${RESCAN_INTERVAL:-21600}"
  ```
      with:
  ```sh
  	echo "==== SWEEP COMPLETE — idle ${RESCAN_INTERVAL:-21600}s $(date) ===="
  	python3 -c "import time, common; common.heartbeat(last_sweep_end=time.time())" </dev/null ||
  		echo "  heartbeat write failed (continuing)"
  	sleep "${RESCAN_INTERVAL:-21600}"
  ```
      (both calls run with cwd `/app`, `gen_loop.sh` never `cd`s elsewhere, so `import
  common`resolves without a`PYTHONPATH`, unlike `merge_pass.sh` below.)
- [ ] Write the failing tests in `tests/test_merge_pass_heartbeat.py` (new):
  ```python
  """Structural checks on merge_pass.sh's heartbeat wiring, in the same static-parse
  style as tests/test_gen_loop_set_e.py (no shell is executed).

  merge_pass.sh's stem loop is, at HEAD 1e8eaaa, the tail of a pipeline
  (`find | grep | sed | sort -u | while read`); in POSIX sh a `while` at the end of a
  pipeline runs in a SUBSHELL, so a variable assigned inside it (considered=$((...+1)))
  is invisible the instant the pipeline's last `|` returns -- the existing before=/
  after= counts sidestep this with separate `find | wc -l` calls, which cannot answer
  "how many had a failed stage". Left as a pipeline, a heartbeat call after the loop
  would report considered=0, changed=0, failed=0, held=0 forever: the exact
  "a correct fallback nothing reports taking" failure shape, and nothing about the
  loop's own behaviour would look wrong."""

  import re
  from pathlib import Path

  MERGE_PASS = Path(__file__).resolve().parent.parent / "merge_pass.sh"


  def _read():
      return MERGE_PASS.read_text()


  def test_the_stem_loop_is_not_the_tail_of_a_pipeline():
      src = _read()
      assert not re.search(r"\|\s*\n?\s*while IFS= read -r stem; do", src), (
          "the stem loop must not be piped into -- a `while read` at the end of a "
          "pipeline runs in a subshell in POSIX sh, so considered/changed/failed/held "
          "would reset to 0 every iteration and never reach the heartbeat call"
      )
      assert 'done <"$STEM_LIST"' in src or 'done < "$STEM_LIST"' in src, (
          'the loop must read from a file (done <"$STEM_LIST"), not a pipe, so counters '
          "assigned inside it are visible once it exits"
      )


  def test_considered_changed_failed_held_are_all_assigned():
      src = _read()
      for var in ("considered", "changed", "failed", "held"):
          assert re.search(rf"\b{var}=", src), f"merge_pass.sh never assigns ${{{var}}}"


  def test_a_heartbeat_call_follows_the_loop_with_every_field():
      src = _read()
      assert "common.heartbeat(" in src, "merge_pass.sh never calls common.heartbeat"
      tail = src.split("common.heartbeat(", 1)[1]
      for field in ("considered=", "changed=", "failed=", "held=", "roots_readable", "order_file_present"):
          assert field in tail, f"the heartbeat call is missing {field}"


  def test_the_heartbeat_python_call_sets_pythonpath_to_app():
      """merge_pass.sh cd's into $ROOT (the media library) before the loop, so a bare
      `python3 -c "import common"` after that cd resolves sys.path[0] to $ROOT, not
      /app -- unlike the `python3 "$APP/repair.py"` calls, which get /app for free
      because they name a script file there. Verified: no other call in this file
      imports a local module without either naming a script under $APP or setting
      PYTHONPATH first."""
      src = _read()
      heartbeat_calls = [
          line for line in src.splitlines() if "import common" in line or 'PYTHONPATH="$APP"' in line
      ]
      assert any('PYTHONPATH="$APP"' in line for line in src.splitlines()), (
          "a bare `python3 -c \"import common...\"` after `cd \"$ROOT\"` needs "
          'PYTHONPATH="$APP" or it cannot find common.py'
      )
  ```
      Run `python3 -m pytest tests/test_merge_pass_heartbeat.py -q`; expect FAIL with
  "the stem loop must not be piped into" (the current file, read at HEAD 1e8eaaa,
  pipes `sort -u | while IFS= read -r stem; do` directly).
- [ ] Implement minimally. This diff assumes sprint 011 Task 7 has already restructured
      this same loop to capture `rc=$?` after each stage invocation and call
      `common.write_stage(...)` on a nonzero rc with no stage record (per the plan's shared
      interface). This task's replacement uses `common.failed_stage(stem)` — also a
      sprint-011 interface, read fresh per stem after that stage plumbing runs — to derive
      `held` independently of that plumbing's exact shape, so this hunk does not need to
      guess its literal text: apply this loop restructuring and counter/heartbeat addition
      around whatever per-stage `rc=$?`/`write_stage` calls Task 7 left inside the loop
      body. In `merge_pass.sh`, replace everything from `before=$(find . -type f -name
"*.dubtitles.done" | wc -l)` through the final `echo "MERGE_PASS_DONE ..."` line with:
  ```sh
  before=$(find . -type f -name "*.dubtitles.done" | wc -l)
  considered=0
  changed=0
  failed=0
  held=0
  last_ok=""
  last_error=""
  STEM_LIST=$(mktemp)
  # episodes with a sidecar (srt or ass) -> dedup to the stem. Written to a FILE and
  # read with `done <"$STEM_LIST"`, not piped into the loop: a `while read` at the tail
  # of a pipeline runs in a subshell in POSIX sh, and considered/changed/failed/held
  # assigned inside it would vanish the instant the pipeline's last `|` returned.
  find . -type f \( -name "*.eng.dubtitles.srt" -o -name "*.eng.dubtitles.ass" \) |
  	grep -ivE "/$PATTERN/" |
  	sed -E 's/\.eng\.dubtitles\.(srt|ass)$//' | sort -u >"$STEM_LIST"
  while IFS= read -r stem; do
  	considered=$((considered + 1))
  	if [ -f "$stem.dubtitles.fail" ]; then # generate crashed on it -> skip
  		failed=$((failed + 1))
  		continue
  	fi
  	if [ ! -f "$stem.eng.dubtitles.ass" ] && [ -f "$stem.eng.dubtitles.srt" ]; then
  		echo "### assemble $stem"
  		python3 "$APP/repair.py" "$stem.dubtitles.conf.json" </dev/null
  		python3 "$APP/dub_signs_merge.py" "$stem.eng.dubtitles.srt" </dev/null
  	fi
  	for ext in mkv mp4 m4v; do # mux the video (root); embeds + stamps
  		[ -f "$stem.$ext" ] && {
  			python3 "$APP/mux.py" --apply "$stem.$ext" </dev/null
  			[ -f "$stem.dubtitles.done" ] && last_ok=$(basename "$stem")
  			break
  		}
  	done
  	stage=$(PYTHONPATH="$APP" python3 -c "import common,sys; print(common.failed_stage(sys.argv[1]) or '')" "$stem")
  	if [ -n "$stage" ]; then
  		held=$((held + 1))
  		last_error="$stage"
  	fi
  done <"$STEM_LIST"
  rm -f "$STEM_LIST"
  after=$(find . -type f -name "*.dubtitles.done" | wc -l)
  changed=$((after - before))

  PYTHONPATH="$APP" python3 -c "
  import os, sys
  import common
  mr = os.environ.get('MERGE_ROOTS', '/media/Anime Library').split(':')
  rr = all(os.path.isdir(r) and os.access(r, os.R_OK) and os.listdir(r) for r in mr)
  common.heartbeat(
      considered=$considered, changed=$changed, failed=$failed, held=$held,
      last_success_stem_name=sys.argv[1], last_error=sys.argv[2],
      roots_readable=rr,
      order_file_present=os.path.exists(os.environ.get('ANIME_ORDER', '/config/anime_order.txt')),
  )
  " "$last_ok" "$last_error"

  if [ "$after" -gt "$before" ] && [ -n "${PLEX_TOKEN:-}" ]; then
  	echo "muxed $((after - before)) new episode(s) -> refreshing Plex"
  	python3 "$APP/plex_refresh.py" "watch" </dev/null
  fi
  echo "MERGE_PASS_DONE new=$((after - before)) total_done=$after $(date)"
  ```
- [ ] Run `python3 -m pytest tests/test_merge_pass_heartbeat.py -q`; expect pass.
- [ ] Write the failing tests for `/healthz` in `tests/test_review_server.py` (add `import
common` and `import time` to the top-level imports):
  ```python
  def test_healthz_ok_on_a_fresh_heartbeat(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(
          last_sweep_start=time.time() - 100, last_sweep_end=time.time() - 10,
          roots_readable=True, order_file_present=True,
      )

      status, payload = review_server.handle_healthz()

      assert (status, payload) == (200, {"ok": True})


  def test_healthz_stale_after_3x_rescan_interval(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      monkeypatch.setenv("RESCAN_INTERVAL", "100")
      common.heartbeat(
          last_sweep_start=time.time() - 1000, last_sweep_end=time.time() - 301,
          roots_readable=True, order_file_present=True,
      )

      status, payload = review_server.handle_healthz()

      assert status == 503
      assert payload["ok"] is False
      assert any(r.startswith("stale: last sweep ended") for r in payload["reasons"])
      assert "/" not in __import__("json").dumps(payload), "no filesystem path may leak through /healthz"


  def test_healthz_recent_sweep_start_does_not_rescue_a_stale_sweep_end(tmp_path, monkeypatch):
      """Staleness is judged from last_sweep_end alone, by design: an in-progress
      sweep (recent last_sweep_start) cannot be told apart, at this granularity, from
      one wedged mid-episode with no crash -- exactly the failure this probe exists to
      catch. See this task's design-decision note."""
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      monkeypatch.setenv("RESCAN_INTERVAL", "100")
      common.heartbeat(
          last_sweep_start=time.time() - 5, last_sweep_end=time.time() - 301,
          roots_readable=True, order_file_present=True,
      )

      status, _ = review_server.handle_healthz()

      assert status == 503


  def test_healthz_roots_unreadable(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(
          last_sweep_start=time.time(), last_sweep_end=time.time(),
          roots_readable=False, order_file_present=True,
      )

      status, payload = review_server.handle_healthz()

      assert status == 503
      assert "roots_readable is false" in payload["reasons"]


  def test_healthz_order_file_missing(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(
          last_sweep_start=time.time(), last_sweep_end=time.time(),
          roots_readable=True, order_file_present=False,
      )

      status, payload = review_server.handle_healthz()

      assert status == 503
      assert "order_file_present is false" in payload["reasons"]


  def test_healthz_missing_heartbeat_file(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "does-not-exist.json"))

      status, payload = review_server.handle_healthz()

      assert (status, payload) == (503, {"ok": False, "reasons": ["no heartbeat yet"]})


  def test_healthz_never_shipped_no_sweep_completed_yet(tmp_path, monkeypatch):
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(last_sweep_start=time.time())  # no last_sweep_end at all

      status, payload = review_server.handle_healthz()

      assert status == 503
      assert "stale: no sweep has completed yet" in payload["reasons"]


  def test_get_healthz_is_open_without_a_token(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "heartbeat.json"))
      common.heartbeat(
          last_sweep_start=time.time(), last_sweep_end=time.time(),
          roots_readable=True, order_file_present=True,
      )

      wire = _Wire()
      h = wire.as_handler("/healthz")
      h.do_GET()

      assert wire.status == 200
  ```
      Run `python3 -m pytest tests/test_review_server.py -k healthz -q`; expect FAIL with
  "AttributeError: module 'review_server' has no attribute 'handle_healthz'".
- [ ] Implement minimally. Add to `review_server.py`, after `announce_token()` and before
      `authorised()` (both already import `os`; add `import common` alongside the existing
      `from common import log`):
  ```python
  def handle_healthz() -> tuple:
      """(status, payload) from common.read_heartbeat(). Meant to be curled
      unauthenticated by a Docker HEALTHCHECK, so it must say nothing an /api/* route
      would need a token to say -- no path, no episode name, no subtitle text.

      Staleness is judged from last_sweep_end ALONE, never last_sweep_start: an
      in-progress sweep and one wedged mid-episode with no crash look identical at this
      granularity, and this is a coarse "is the loop alive" signal, not a fine one."""
      hb = common.read_heartbeat()
      if not hb:
          return 503, {"ok": False, "reasons": ["no heartbeat yet"]}
      reasons = []
      rescan = float(os.environ.get("RESCAN_INTERVAL", "21600"))
      last_end = hb.get("last_sweep_end")
      if last_end is None:
          reasons.append("stale: no sweep has completed yet")
      else:
          age = time.time() - float(last_end)
          if age > 3 * rescan:
              reasons.append(f"stale: last sweep ended {int(age)}s ago")
      if hb.get("roots_readable") is False:
          reasons.append("roots_readable is false")
      if hb.get("order_file_present") is False:
          reasons.append("order_file_present is false")
      if reasons:
          return 503, {"ok": False, "reasons": reasons}
      return 200, {"ok": True}
  ```
      Wire it into `do_GET`. Replace:
  ```python
          if u.path in ("/", "/index.html"):
              stem = (parse_qs(u.query).get("stem") or [""])[0]
              return self._send(200, render_page(stem).encode(), "text/html; charset=utf-8")
          q = {k: v[0] for k, v in parse_qs(u.query).items()}
  ```
      with:
  ```python
          if u.path in ("/", "/index.html"):
              stem = (parse_qs(u.query).get("stem") or [""])[0]
              return self._send(200, render_page(stem).encode(), "text/html; charset=utf-8")
          if u.path == "/healthz":
              status, payload = handle_healthz()
              return self._send(status, payload)
          q = {k: v[0] for k, v in parse_qs(u.query).items()}
  ```
- [ ] Run `python3 -m pytest tests/test_review_server.py -q`; expect pass.
- [ ] Write the failing test in `tests/test_dockerfile_copy.py` (uses the file's own
      `ROOT` constant, already defined at the top):
  ```python
  def test_healthcheck_targets_healthz():
      """A HEALTHCHECK must exist and hit /healthz -- Task 16's own liveness endpoint,
      not some other port or path that would silently stop meaning anything the moment
      either side changed alone."""
      with open(os.path.join(ROOT, "Dockerfile.builder")) as f:
          body = f.read()
      assert re.search(r"^HEALTHCHECK\b.*CMD\b", body, re.M), "no HEALTHCHECK instruction found"
      assert "/healthz" in body, "the HEALTHCHECK must target /healthz"
  ```
      Run `python3 -m pytest tests/test_dockerfile_copy.py -k healthcheck -q`; expect FAIL
  with "AssertionError: no HEALTHCHECK instruction found" (verified: `Dockerfile.builder`
  has no `HEALTHCHECK` instruction anywhere at HEAD 1e8eaaa).
- [ ] Implement minimally. In `Dockerfile.builder`, immediately before the final
      `ENTRYPOINT ["sh", "/app/container_run.sh"]` line, insert:
  ```dockerfile
  # [S-7] liveness for the container orchestrator -- see review_server.handle_healthz().
  # start-period=10m: the model bake + first-boot cache warm can legitimately take that
  # long; interval/retries chosen so a wedge is reported inside ~20 minutes of it
  # actually going stale, not immediately on one slow request.
  HEALTHCHECK --interval=5m --timeout=10s --start-period=10m --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8842/healthz', timeout=5).status==200 else 1)"
  ```
- [ ] Run `python3 -m pytest tests/test_dockerfile_copy.py -q`; expect pass.
- [ ] Add the matching `healthcheck:` block to `compose.yaml`. In the `dubtitlerr:`
      service, immediately after `restart: unless-stopped`, insert:
  ```yaml
      healthcheck:
        test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8842/healthz', timeout=5).status==200 else 1)"]
        interval: 5m
        timeout: 10s
        start_period: 10m
        retries: 3
  ```
      No automated test: nothing in this repo's CI parses or runs `compose.yaml`; it is
  verified by eye against the `HEALTHCHECK` line above, which the structural test does
  cover. An `autoheal` label to actually act on an unhealthy container is an
  out-of-repo, host-`docker-compose.yml` concern — a live check of that belongs to
  sprint 014, not this task.
- [ ] Run `python3 -m pytest -q`; expect pass.
- [ ] Run `ruff check .`; expect "All checks passed!"
- [ ] Commit: `git commit -m "feat(heartbeat): add process liveness heartbeat, /healthz and a HEALTHCHECK"`

## Task 17: token-gate the rendered pages via a cookie

Sprint: 013 Scope: [S-14]
Files: `review_server.py` (a new `_cookie_token()`, a new `render_locked()`, `do_GET`/
`do_POST` compute a combined header-or-cookie `presented` value and `do_GET` gates `/`,
`/index.html` and `/shared` on it, the two existing token-box JS blocks in `render_page`/
`render_shared` gain a cookie sync), `tests/test_review_server.py` (new tests; no existing
test's assertions change).
Interfaces produced: `review_server._cookie_token(headers) -> str | None`,
`review_server.render_locked(page_kind: str) -> str` (`page_kind` is `"page"` or
`"shared"`). Cookie name `dubtitlerr_token`, attributes `Path=/; SameSite=Strict`, cleared
with `Max-Age=0`. Interfaces consumed: `review_server.authorised`, `review_server.TOKEN_HEADER`,
`review_server.TOKEN_DIR`, `review_server.known_stems`.

The hole Task 14 left: `route()` is reached only for `/api/*`. `/`, `/index.html` and
`/shared` are served by `do_GET` calling `render_page()`/`render_shared()` directly
(review_server.py:1122-1133, unchanged by Task 14), which call `handle_index()`/
`handle_episode()`/`handle_shared()` in-process — every absolute `stem` and every original/
proposed subtitle line, to any unauthenticated LAN peer who just requests the page. Gating
`GET /api/*` did nothing about this because the page never calls its own API over HTTP.
Fixed here by gating the pages too. A page load cannot carry the `X-Review-Token` header
`fetch()` uses (that header is set in JS, and a plain navigation is not a `fetch()`), so the
token box's own JS also writes it into a cookie, and `authorised()` is given a cookie
fallback to read.

Kept from the original scope of this task, unchanged by the redesign: grepping the whole
file for `fetch(` (verified) finds exactly two call sites, both POST, both already carrying
`TOKEN_HEADER` — review_server.py:832-834 (`render_shared`) and review_server.py:1041-1043
(`render_page`), byte-for-byte the same two lines. Those two writes were never the gap;
this task pins them alongside the new cookie behaviour rather than opening a second task
for it.

- [ ] Write the failing test for the cookie parser in `tests/test_review_server.py`:
  ```python
  def test_cookie_token_parses_the_dubtitlerr_token_cookie_among_others():
      headers = {"Cookie": "foo=bar; dubtitlerr_token=abc123; baz=qux"}
      assert review_server._cookie_token(headers) == "abc123"


  def test_cookie_token_missing_cookie_header_returns_none():
      assert review_server._cookie_token({}) is None


  def test_cookie_token_malformed_cookie_header_returns_none():
      assert review_server._cookie_token({"Cookie": ";;;=== not a cookie"}) is None
  ```
      Run `python3 -m pytest tests/test_review_server.py -k cookie_token -q`; expect FAIL
  with "AttributeError: module 'review_server' has no attribute '_cookie_token'".
- [ ] Implement minimally. Add `import http.cookies` to `review_server.py`'s imports
      (alongside the existing `import http.server`), and add, right after the
      `TOKEN_HEADER = "X-Review-Token"` line:
  ```python
  def _cookie_token(headers) -> str | None:
      """The token from the Cookie header's dubtitlerr_token entry, or None.

      A fallback for the PAGE routes only (/, /index.html, /shared): a plain page
      navigation cannot attach a custom X-Review-Token header, so the token the page's
      own JS already stores has nowhere to travel except a cookie. /api/* callers
      (curl, the page's own fetch() calls) keep sending the header; this fallback
      widens what authorised() will accept, it narrows nothing."""
      raw = headers.get("Cookie") if hasattr(headers, "get") else None
      if not raw:
          return None
      jar = http.cookies.SimpleCookie()
      try:
          jar.load(raw)
      except http.cookies.CookieError:
          return None
      morsel = jar.get("dubtitlerr_token")
      return morsel.value if morsel else None
  ```
- [ ] Run `python3 -m pytest tests/test_review_server.py -k cookie_token -q`; expect pass.
- [ ] Write the failing test for the locked shell in `tests/test_review_server.py`:
  ```python
  def test_render_locked_page_has_no_episode_data_and_no_fetch_call():
      out = review_server.render_locked("page")
      assert "needs-token" in out
      assert "fetch(" not in out, "the locked shell must not call any write route either"
      assert "id=tok" in out


  def test_render_locked_shared_uses_the_shared_title():
      out = review_server.render_locked("shared")
      assert "Shared lines" in out
      assert "needs-token" in out
  ```
      Run `python3 -m pytest tests/test_review_server.py -k render_locked -q`; expect FAIL
  with "AttributeError: module 'review_server' has no attribute 'render_locked'".
- [ ] Implement minimally. Add to `review_server.py`, after `render_page` (before the
      `# --- HTTP ---` section):
  ```python
  def render_locked(page_kind: str) -> str:
      """The shell shown instead of render_page()/render_shared() when authorised()
      refuses the GET -- same chrome (title, CSS, the token box and its JS) as the real
      page, but the episode/shared list is never built: handle_index()/handle_episode()/
      handle_shared() walk MERGE_ROOTS and the decision stores and return every stem and
      every card's original/proposed text, so the one thing this shell must not do is
      call any of them. NO fetch() call either -- there is nothing to save from a page
      that was never shown data. page_kind ("page" or "shared") picks only the <h1>; the
      token box and its JS are identical between the two, so there is exactly one place
      a cookie gets synced from this shell."""
      h1 = "Shared lines" if page_kind == "shared" else "Review"
      back = '<p><a href="/">← all episodes</a></p>' if page_kind == "shared" else ""
      return (
          "<!doctype html><meta charset=utf-8><title>DubTitlerr review</title>"
          f"<style>{_CSS}</style>"
          f"<h1>{h1}</h1>"
          "<p>Token: <input id=tok size=44 placeholder='paste from the container log'></p>"
          f"{back}"
          '<p id="needs-token">Paste the review token to load the queue.</p>'
          "<script>"
          "const TOK=document.getElementById('tok');"
          "function syncTokenCookie(){if(TOK.value){document.cookie="
          "'dubtitlerr_token='+encodeURIComponent(TOK.value)+'; Path=/; SameSite=Strict'}"
          "else{document.cookie='dubtitlerr_token=; Path=/; SameSite=Strict; Max-Age=0'}}"
          "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
          "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}"
          "syncTokenCookie();clearTimeout(window.__tokReload);"
          "window.__tokReload=setTimeout(()=>location.reload(),300)});"
          "</script>"
      )
  ```
      Note: this does not auto-reload on page load even when `localStorage` already holds a
  token from before this cookie existed — only the `input` event (debounced 300ms)
  triggers a reload. An on-load auto-reload was deliberately left out: with a stale or
  wrong cached token it would reload, still render locked, see the same non-empty
  `TOK.value`, and reload again -- an infinite loop with no server-side signal to break
  it. A returning user with a still-valid cached token sees the prompt once and clears
  it by touching the box (even a single keystroke and undo); this is the accepted
  trade-off for not adding loop-prevention state this task does not otherwise need.
- [ ] Run `python3 -m pytest tests/test_review_server.py -k render_locked -q`; expect pass.
- [ ] Write the failing tests for the existing pages' cookie-sync JS and the do_GET/do_POST
      wiring in `tests/test_review_server.py`:
  ```python
  def test_the_token_box_js_syncs_a_cookie_next_to_localstorage(monkeypatch):
      """The existing TOK 'input' listener (review_server.py:829-831 in render_shared,
      byte-for-byte the same at :1038-1040 in render_page) already writes to
      localStorage; it must ALSO write the cookie authorised() now reads, in the SAME
      handler, so the two never drift out of sync."""
      monkeypatch.setattr(review_server, "known_stems", lambda: [])

      for out in (review_server.render_page(), review_server.render_shared()):
          start = out.index("TOK.addEventListener('input'")
          handler = out[start : start + 400]
          assert "localStorage.setItem('dubtitlerr_token'" in handler
          assert "syncTokenCookie()" in handler
          assert "document.cookie=" in out


  def test_get_index_without_a_token_shows_the_locked_shell_not_the_queue(tmp_path, monkeypatch):
      """Verified: handle_index() appends `{"stem": stem, "name": os.path.basename(stem),
      ...}` per episode with anything pending, and render_page renders that name into
      an <a href> -- so an unauthenticated GET / must never reach render_page() at all."""
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path, name="S01E01")
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

      wire = _Wire()
      h = wire.as_handler("/")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "needs-token" in body
      assert "S01E01" not in body


  def test_get_index_with_the_cookie_shows_the_real_queue(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path, name="S01E01")
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
      tok = review_server.resolve_token(str(tmp_path))

      wire = _Wire()
      wire.headers["Cookie"] = f"dubtitlerr_token={tok}"
      h = wire.as_handler("/")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "needs-token" not in body
      assert "S01E01" in body


  def test_get_index_with_the_header_also_shows_the_real_queue(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path, name="S01E01")
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
      tok = review_server.resolve_token(str(tmp_path))

      wire = _Wire()
      wire.headers[review_server.TOKEN_HEADER] = tok
      h = wire.as_handler("/")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "S01E01" in body


  def test_get_shared_without_a_token_shows_the_locked_shell(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path)
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

      wire = _Wire()
      h = wire.as_handler("/shared")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "needs-token" in body
      assert 'id="shared-sort"' not in body, "the real shared page's sort control must not render"


  def test_get_shared_with_the_cookie_shows_the_real_page(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path)
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
      tok = review_server.resolve_token(str(tmp_path))

      wire = _Wire()
      wire.headers["Cookie"] = f"dubtitlerr_token={tok}"
      h = wire.as_handler("/shared")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "needs-token" not in body
      assert 'id="shared-sort"' in body


  def test_get_healthz_is_never_gated_by_the_token(tmp_path, monkeypatch):
      monkeypatch.delenv("REVIEW_TOKEN", raising=False)
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      monkeypatch.setattr(common, "HEARTBEAT_PATH", str(tmp_path / "does-not-exist.json"))

      wire = _Wire()
      h = wire.as_handler("/healthz")
      h.do_GET()

      assert wire.status != 401


  def test_review_auth_off_keeps_every_page_open_with_no_token(tmp_path, monkeypatch):
      """REVIEW_AUTH=off is sprint 010's contract for disabling auth entirely; this task
      must not add a second, cookie-shaped way to accidentally require one."""
      monkeypatch.setenv("REVIEW_AUTH", "off")
      monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
      stem = _episode(tmp_path, name="S01E01")
      monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

      wire = _Wire()
      h = wire.as_handler("/")
      h.do_GET()
      body = wire.wfile.getvalue().decode()

      assert wire.status == 200
      assert "needs-token" not in body
      assert "S01E01" in body
  ```
      Run `python3 -m pytest tests/test_review_server.py -k "locked_shell or shows_the_real or healthz_is_never_gated or auth_off_keeps" -q`;
  expect FAIL with "assert 'needs-token' in " (`do_GET` does not check `authorised()`
  for `/`/`/shared` yet, so the current, unmodified render is returned regardless of
  any token).
- [ ] Implement minimally. In `review_server.py`, this exact three-line block appears
      twice, byte-for-byte identical — review_server.py:829-831 inside `render_shared` and
      review_server.py:1038-1040 inside `render_page`. Replace it at BOTH sites:

  ```python
          "const TOK=document.getElementById('tok');"
          "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
          "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}});"
  ```

      with:

  ```python
          "const TOK=document.getElementById('tok');"
          "function syncTokenCookie(){if(TOK.value){document.cookie="
          "'dubtitlerr_token='+encodeURIComponent(TOK.value)+'; Path=/; SameSite=Strict'}"
          "else{document.cookie='dubtitlerr_token=; Path=/; SameSite=Strict; Max-Age=0'}}"
          "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
          "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}syncTokenCookie()});"
  ```

      (deliberately no reload here, unlike `render_locked`'s copy of this listener: these

  two pages are already showing real data, so reloading on every keystroke in the token
  box would discard any unsaved radio selections; only the locked shell, which has
  nothing to lose, reloads automatically once the cookie is set).

  Then wire the gate and the combined token lookup into `Handler`. Replace:

  ```python
      def do_GET(self):
          from urllib.parse import parse_qs, urlparse

          u = urlparse(self.path)
          if u.path == "/shared":
              return self._send(200, render_shared().encode(), "text/html; charset=utf-8")
          if u.path in ("/", "/index.html"):
              stem = (parse_qs(u.query).get("stem") or [""])[0]
              return self._send(200, render_page(stem).encode(), "text/html; charset=utf-8")
          if u.path == "/healthz":
              status, payload = handle_healthz()
              return self._send(status, payload)
          q = {k: v[0] for k, v in parse_qs(u.query).items()}
          status, payload = route("GET", u.path, q, self.headers.get(TOKEN_HEADER))
          self._send(status, payload)
  ```

      with:

  ```python
      def do_GET(self):
          from urllib.parse import parse_qs, urlparse

          u = urlparse(self.path)
          # A plain page load cannot carry a custom header, so the cookie the token
          # box's own JS sets is the fallback here -- /api/* callers (curl, the page's
          # own fetch() calls) keep sending the header, which still wins when present.
          presented = self.headers.get(TOKEN_HEADER) or _cookie_token(self.headers)
          if u.path == "/shared":
              if not authorised("GET", presented):
                  return self._send(200, render_locked("shared").encode(), "text/html; charset=utf-8")
              return self._send(200, render_shared().encode(), "text/html; charset=utf-8")
          if u.path in ("/", "/index.html"):
              if not authorised("GET", presented):
                  return self._send(200, render_locked("page").encode(), "text/html; charset=utf-8")
              stem = (parse_qs(u.query).get("stem") or [""])[0]
              return self._send(200, render_page(stem).encode(), "text/html; charset=utf-8")
          if u.path == "/healthz":
              status, payload = handle_healthz()
              return self._send(status, payload)
          q = {k: v[0] for k, v in parse_qs(u.query).items()}
          status, payload = route("GET", u.path, q, presented)
          self._send(status, payload)
  ```

      And in `do_POST`, replace:

  ```python
          status, payload = route("POST", self.path, body, self.headers.get(TOKEN_HEADER))
  ```

      with:

  ```python
          status, payload = route("POST", self.path, body, self.headers.get(TOKEN_HEADER) or _cookie_token(self.headers))
  ```

      (the header still wins when present -- every `fetch()` call in the page sends it, so

  this only widens what a write route will accept, for a caller that has the
  `SameSite=Strict` cookie but, for some reason, not the header; it does not narrow
  anything the write routes already accepted).

- [ ] Run `python3 -m pytest tests/test_review_server.py -q`; expect pass.
- [ ] Write the pin tests for the two existing `fetch()` calls (unchanged behaviour, kept
      from this task's original scope):
  ```python
  def test_every_fetch_call_on_the_index_page_still_carries_the_token_header(monkeypatch):
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      page = review_server.render_page()
      assert page.count("fetch(") == 1, "expected exactly one fetch() call on the index page"
      assert f"'{review_server.TOKEN_HEADER}':TOK.value" in page


  def test_every_fetch_call_on_the_shared_page_still_carries_the_token_header(monkeypatch):
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      page = review_server.render_shared()
      assert page.count("fetch(") == 1, "expected exactly one fetch() call on the shared page"
      assert f"'{review_server.TOKEN_HEADER}':TOK.value" in page


  def test_a_401_is_still_surfaced_by_alert_and_the_token_box_stays_visible(monkeypatch):
      monkeypatch.setattr(review_server, "known_stems", lambda: [])
      page = review_server.render_page()
      shared = review_server.render_shared()
      assert "id=tok" in page and "if(r.error){alert(r.error)" in page
      assert "id=tok" in shared and "if(r.error){alert(r.error)" in shared
  ```
- [ ] Run `python3 -m pytest tests/test_review_server.py -q`; expect pass (these three were
      already true before this task and stay true after it; they guard against a future
      edit accidentally dropping the header from a POST while adding the cookie fallback).
- [ ] Run `python3 -m pytest -q`; expect pass.
- [ ] Run `ruff check .`; expect "All checks passed!"
- [ ] Commit: `git commit -m "fix(review_server): gate the rendered pages behind a token cookie"`

## Task 18: T12 real-media run (owner/live) and Phase-0 report artifact

Sprint: 014 Scope: [S-17]
Files: `docs/timing-compare/<YYYY-MM-DD>-phase0-report.json` (new, the raw `--out` report,
committed as evidence), `docs/timing-compare/<YYYY-MM-DD>-phase0-go-no-go.md` (new, the
owner's written decision).
Interfaces consumed: `tools/timing_compare.py`'s CLI (`show_dir` nargs+, `--tolerance`,
`--out`, `--lang`, `--vad {webrtcvad,ffmpeg-silencedetect}`, `--vad-aggressiveness 0-3`,
`--summary-only`) and its schema_version-2 report shape: top-level
`{"schema_version": 2, "config": {...}, "shows": {"<show>": {"episodes":
{"<basename>": <episode-report>}, "aggregate": {...}}}, "aggregate": {...}}`; a
non-"analyzed" episode collapses to the bare `{"status": "no-conf"|"bad-conf"|"no-reference"}`
(no `reference_track` key at all); an "analyzed" episode carries `reference_track`
(`{"stream_index", "codec", "cue_count", "density_score"}`), `drift_b`, `offset_a_s`,
`false_in_gap_rate`, and `kept_in_gap` (`{"total", "in_gap_silent", "in_gap_speech",
"in_gap_vad_error", "by_nsp", "by_lp", "by_flag"}`); a show/overall `aggregate` carries
`no_conf`, `no_reference`, `bad_conf`, `analyzed`, `applicability_ratio`,
`pct_cards_on_cue`, `kept_in_gap`, `in_gap_speech`, `in_gap_silent`, `in_gap_vad_error`,
`false_in_gap_rate` (all as plain ints/floats/`None`, not nested, at this level — verified
in `tools/timing_compare.py`'s `aggregate_episodes()`).

This is v0.2.0 candidate item 9 ("Close timing-compare's real-media validation loop") from
the 2026-09-21 weekly plan. T1–T11 are already on `main` (commits `51ead55` T1, `4163e91`
T2–T6, `fb25397` a lang-set fix, `6b723ad` T7, `d339ccd` T8, `3936de9` T9–T11, `7267b64`
an aggregate-null fix — verified `git merge-base --is-ancestor <hash> HEAD`, all true).
Only T12 ("integration check on a real show, user-reviewed and accepted") has never run.
`webrtcvad` does not install in this repo's py3.14 dev venv (`tools/vad.py`'s module
docstring) — this run MUST use the `dubtitle-builder:0.1.0` image, whose
`Dockerfile.builder` best-effort-installs `webrtcvad` (`|| echo "webrtcvad install failed
... NOT fatal for generation"`), or pass `--vad ffmpeg-silencedetect` to stay dep-free.

- [ ] **OWNER/LIVE, on the worker host (verify with `docker ps` first per AGENTS.md's
      "Where this actually runs" — vm102 as of 2026-09-08, but confirm live, don't trust a
      stale note):** discover which library shows have a real fansub dialogue track vs a
      signs-only track, so the run covers both cases plus the unanchored One Pace case. Run,
      substituting three real show directory names for `ShowA`/`ShowB`/`ShowC`:
  ```sh
  MEDIA_ROOT="/media/Anime Library"
  for d in "ShowA" "ShowB" "One Pace"; do
    echo "=== $d ==="
    f=$(find "$MEDIA_ROOT/$d" -type f \( -iname '*.mkv' -o -iname '*.mp4' \) | head -1)
    [ -n "$f" ] || { echo "no video found"; continue; }
    docker run --rm --entrypoint ffprobe -v "$MEDIA_ROOT:/media:ro" dubtitle-builder:0.1.0 \
      -v error -select_streams s -show_entries stream=index:stream_tags=language,title \
      -of json "/media${f#"$MEDIA_ROOT"}"
  done
  ```
  Selection rule: pick as `ShowA` the show whose subtitle streams include one with a
  real dialogue track (language `eng`/`en`/untagged, NOT titled "Signs" and carrying
  dozens of short conversational cues, not just top-line song/sign text) — this is the
  one expected to get a `reference_track`. Pick as `ShowB` a show whose only English
  subtitle stream is signs-only (few cues, short bursts, or explicitly titled
  "Signs"/"Songs") — this is the expected `no-reference` case. `ShowC` is `One Pace`,
  already known to be the unanchored case from `feedback_dubtitlerr_test_beyond_one_pace`.
- [ ] **OWNER/LIVE:** run the tool itself, inside the builder image so `webrtcvad` is
      available, media mounted read-only, writing into a host-owned `--out` directory:
  ```sh
  mkdir -p /home/claude/timing-compare-out
  DATE=$(date -u +%F)
  docker run --rm --entrypoint python3 \
    -v "/mnt/r520-media-full/Anime Library:/media/Anime Library:ro" \
    -v /home/claude/timing-compare-out:/out \
    -v "$PWD/tools:/app/tools:ro" \
    dubtitle-builder:0.1.0 /app/tools/timing_compare.py \
    "/media/Anime Library/ShowA" "/media/Anime Library/ShowB" "/media/Anime Library/One Pace" \
    --vad webrtcvad --vad-aggressiveness 2 \
    --out "/out/${DATE}-phase0-report.json"
  ```
  Expect: three `analyzed`/`no-reference`/`analyzed` (or similar) per-episode status
  lines, a per-show and `OVERALL` summary line printed
  (`applicability_ratio=... pct_cards_on_cue=... kept_in_gap.total=... in_gap_speech=...
false_in_gap_rate=...`), and `wrote /out/<DATE>-phase0-report.json`.
- [ ] **OWNER/LIVE:** acceptance check — reference track resolved for the dialogue show,
      `no-reference` for the signs-only show:
  ```sh
  python3 -c "
  import json, sys
  r = json.load(open('/home/claude/timing-compare-out/${DATE}-phase0-report.json'))
  a_eps = r['shows']['ShowA']['episodes']
  assert any(e.get('status') == 'analyzed' and e.get('reference_track') is not None for e in a_eps.values()), 'ShowA got no reference_track'
  b_eps = r['shows']['ShowB']['episodes']
  assert all(e.get('status') == 'no-reference' for e in b_eps.values()), 'ShowB was not all no-reference'
  print('reference_track / no-reference check OK')
  "
  ```
  Expect: `reference_track / no-reference check OK`; a non-zero exit / `AssertionError`
  means the show selection in the first step picked the wrong pair and must be redone.
- [ ] **OWNER/LIVE:** acceptance check — `drift_b` is plausible (no gross frame-rate
      mismatch or unit bug: `|drift_b| < 0.01`, i.e. under 1% clock drift) wherever it was
      computed (≥10 inliers, per `RANSAC_MIN_INLIERS`):
  ```sh
  python3 -c "
  import json
  r = json.load(open('/home/claude/timing-compare-out/${DATE}-phase0-report.json'))
  bad = []
  for show, s in r['shows'].items():
      for ep, e in s['episodes'].items():
          b = e.get('drift_b')
          if e.get('status') == 'analyzed' and b is not None and abs(b) >= 0.01:
              bad.append((show, ep, b))
  assert not bad, bad
  print('drift_b plausible OK')
  "
  ```
  Expect: `drift_b plausible OK`. A failure here is a real finding for the go/no-go
  note (record the offending show/episode/drift_b, do not silently raise the threshold).
- [ ] **OWNER/LIVE:** acceptance check — `in_gap_vad_error` is counted separately from
      `in_gap_silent`/`in_gap_speech`, and a show/overall `false_in_gap_rate` of `null`
      only happens when in-gap cards exist and every one of them is `vad_error`:
  ```sh
  python3 -c "
  import json
  r = json.load(open('/home/claude/timing-compare-out/${DATE}-phase0-report.json'))
  for label, agg in list(r['shows'].items()) + [('OVERALL', r['aggregate'])]:
      fig = agg['false_in_gap_rate']
      all_error = agg['kept_in_gap'] > 0 and agg['in_gap_speech'] == 0 and agg['in_gap_silent'] == 0
      if agg['kept_in_gap'] == 0:
          assert fig is None, (label, 'expected null with 0 kept_in_gap cards')
      elif all_error:
          assert fig is None, (label, 'expected null when every in-gap card is vad_error')
      else:
          assert fig is not None, (label, 'expected a numeric rate')
      print(label, 'kept_in_gap=', agg['kept_in_gap'], 'in_gap_vad_error=', agg['in_gap_vad_error'], 'false_in_gap_rate=', fig)
  "
  ```
  Expect: one printed line per show plus `OVERALL`, no `AssertionError`. If webrtcvad
  failed to install in the image, expect every show's `false_in_gap_rate` to print
  `None` with `in_gap_vad_error == kept_in_gap` — a real "unmeasured" result, not a bug;
  record it as such in the go/no-go note rather than treating it as a pass.
- [ ] **OWNER/LIVE:** acceptance check — no leftover scratch files under the media root
      (report writes are atomic-via-tempfile in `--out`'s own directory, not under media;
      VAD audio windows extract into a `tempfile.TemporaryDirectory()`, also not under
      media — this check exists as a safety net against a future regression, not because
      either path is expected to leak):
  ```sh
  find "/mnt/r520-media-full/Anime Library" -iname '.timing-compare.*.tmp' -o -iname 'gap_*.wav'
  ```
  Expect: no output. Any hit is a real leak and blocks go/no-go until root-caused.
- [ ] **OWNER/LIVE:** write the go/no-go note at
      `docs/timing-compare/${DATE}-phase0-go-no-go.md` with these literal headings:
  ```markdown
  # Timing Compare Phase 0 — go/no-go (<DATE>)

  ## Shows
  <ShowA/ShowB/ShowC real names, episode counts run, which was the dialogue-track /
  signs-only / unanchored case>

  ## Applicability
  <applicability_ratio per show and OVERALL, from the printed summary/report>

  ## false_in_gap_rate per show
  <the numeric or `null` value per show and OVERALL, from the acceptance check above,
  with the null reason spelled out when it applies (all-vad_error vs 0 kept_in_gap)>

  ## VAD error rate
  <in_gap_vad_error / kept_in_gap per show — this is the "how much of the previous
  section is actually unmeasured" number>

  ## Decision: GO/NO-GO for a Phase-1 gating spec
  <one paragraph: does false_in_gap_rate look safety-first and materially useful
  across these 3 shows? Phase 0's own trigger note: "false_in_gap_rate ≤ ~2% across
  ≥3 shows" (specs/timing-compare/tasks.md T12). State whether that trigger held, and
  whether GO means "write specs/timing-compare/... a Phase-1 gate spec next" or
  NO-GO means "run more shows first" / "fix VAD availability first">

  ## Calibration of VAD_MIN_VOICED_RATIO
  <tools/vad.py's VAD_MIN_VOICED_RATIO_DEFAULT is 0.3, flagged "PENDING calibration"
  in its own comment; record whether this run's by_nsp/by_lp cross-tab on in-gap
  speech verdicts gives any evidence to move it, or state explicitly "no evidence
  either way from this sample size">
  ```
- [ ] Copy the report and the go/no-go note into the repo (report is evidence, not
      regenerated by CI):
  ```sh
  mkdir -p docs/timing-compare
  cp /home/claude/timing-compare-out/${DATE}-phase0-report.json docs/timing-compare/
  cp /home/claude/timing-compare-out/${DATE}-phase0-go-no-go.md docs/timing-compare/ 2>/dev/null || true
  ```
  (the go/no-go note is written directly at the repo path in the previous step if
  working from a repo checkout on the host; the `cp` above only applies if it was
  drafted elsewhere first.)
- [ ] Run `ruff check docs/` (no-op — `pyproject.toml`'s `extend-exclude = ["*.md"]` and
      the report is JSON, not lint-checked, but running it confirms nothing else broke):
      `ruff check .`; expect `All checks passed!`.
- [ ] Commit: `git add docs/timing-compare/ && git commit -m "docs(timing-compare): T12 real-media run + Phase-0 go/no-go"`

## Task 19: specs/timing-compare/tasks.md reconcile

Sprint: 014 Scope: [S-17]
Files: `specs/timing-compare/tasks.md` (edit only — tick T1–T11, correct the header, strike
the stale closing steps).
Interfaces: none (documentation-only task; depends on Task 18 only for T12's own line,
which stays a checkbox referencing the artifact Task 18 produced).

`specs/timing-compare/tasks.md` currently opens with the header line
`**Branch:** \`feat/timing-compare\` (base: \`main\`)`, and every task line is `[ ]`—
both stale.`git branch -a`confirms no
branch named`feat/timing-compare`or`timing-compare`ever existed; the actual work
landed as standalone commits directly reachable from`main`/this branch (verified in Task
18 via `git merge-base --is-ancestor`).

- [ ] Replace the header. Current text:
  ```markdown
  **Branch:** `feat/timing-compare` (base: `main`)
  ```
  New text:
  ```markdown
  **Delivered on `main` via the commits above** — T1–T11 landed as standalone commits
  (no `feat/timing-compare` branch was ever created; `git branch -a` confirms this).
  Reconciled 2026-09-21 after v0.2.0 candidate item 9 found the checklist below stale
  against the actual `git log`.
  ```
- [ ] Tick T1, quoting its commit: replace
  ```markdown
  - [ ] **T1 — Refactor `common.py`/`repair.py` (do FIRST — live blast radius).**
  ```
  with
  ```markdown
  - [x] **T1 — Refactor `common.py`/`repair.py` (do FIRST — live blast radius).**
        Delivered in `51ead55` (`refactor(T1): hoist dialogue_intervals from repair.py
        into common.py`).
  ```
- [ ] Tick T2–T6 as one group (they shipped in one commit), quoting it: replace
  ```markdown
  - [ ] **T2 — Scaffold `tools/timing_compare.py`.**
  ```
  with
  ```markdown
  - [x] **T2 — Scaffold `tools/timing_compare.py`.** Delivered in `4163e91`
        (`feat(timing-compare/T2-T6): tool core -- CLI, conf.json, track selection,
        RANSAC fit, classification`), together with T3–T6 below (one commit covers
        all four — see each task's own tick for the cross-reference).
  ```
  and similarly tick T3, T4, T5, T6 (`- [ ] **T3 — ...` → `- [x] **T3 — ...`, etc.),
  each appending: `Delivered in `4163e91` (see T2's note).` A lang-set correctness fix
  landed the same day in `fb25397` (`fix(timing-compare): keep blank lang token in
--lang set to match common.SUB_LANGS`) — append that reference to T4's line only
  (it is the track-selection task the fix touches):
  ```markdown
  - [x] **T4 — Subtitle extraction + dialogue-track selection.** Delivered in `4163e91`
        (see T2's note); a lang-set correctness fix followed in `fb25397` (`fix
        (timing-compare): keep blank lang token in --lang set to match
        common.SUB_LANGS`).
  ```
- [ ] Tick T7, quoting its commit: replace
  ```markdown
  - [ ] **T7 — VAD probe (`tools/vad.py`).**
  ```
  with
  ```markdown
  - [x] **T7 — VAD probe (`tools/vad.py`).** Delivered in `6b723ad` (`feat(timing-
        compare/T7): VAD probe of in-gap cards -- tools/vad.py + wiring`).
  ```
- [ ] Tick T8, quoting its commit: replace
  ```markdown
  - [ ] **T8 — Add `webrtcvad` dependency.**
  ```
  with
  ```markdown
  - [x] **T8 — Add `webrtcvad` dependency.** Delivered in `d339ccd` (`feat(timing-
        compare/T8): add webrtcvad dependency (analysis extra + builder image)`).
  ```
- [ ] Tick T9 and T10, quoting their commit and its follow-up fix: replace
  ```markdown
  - [ ] **T9 — Band bucketing + report generation.**
  ```
  with
  ```markdown
  - [x] **T9 — Band bucketing + report generation.** Delivered in `3936de9` (`feat
        (timing-compare/T9-T11): schema_version-2 report + aggregates + edge
        hardening`), together with T10/T11 below.
  ```
  and replace
  ```markdown
  - [ ] **T10 — Edge/aggregate hardening.**
  ```
  with
  ```markdown
  - [x] **T10 — Edge/aggregate hardening.** Delivered in `3936de9` (see T9's note); a
        follow-up null-safety fix landed in `7267b64` (`fix(timing-compare): aggregate
        false_in_gap_rate null on all-vad_error + doc/strip cleanups`) — the aggregate
        level had the same bug T10 already fixed at the per-episode level.
  ```
- [ ] Tick T11, quoting its commit: replace
  ```markdown
  - [ ] **T11 — Unit test file.**
  ```
  with
  ```markdown
  - [x] **T11 — Unit test file.** Delivered in `3936de9` (see T9's note; the test file
        grew again in `7267b64`'s fix).
  ```
- [ ] Leave T12 as `[ ]` — replace only its closing clause "the user has reviewed the
      output and accepted it" cross-reference with a pointer to Task 18's artifact:
  ```markdown
  - [ ] **T12 — Integration check on a real show.** ... **done when:** the user has
        reviewed the output and accepted it — see `docs/timing-compare/*-phase0-
        report.json` and `docs/timing-compare/*-phase0-go-no-go.md` (added by the
        v0.2.0 hardening plan's sprint 014, Task 18). Tick this box by hand once that
        go/no-go note records a decision.
  ```
- [ ] Strike the stale closing steps (no branch to push, no PR to draft) — replace
  ```markdown
  - [ ] **Push the branch:** `git push origin feat/timing-compare`. — done when: on origin.
  - [ ] **Draft the PR:** Summary / Notable Decisions / Test Plan; pause for approval. — done when: user
        approved.
  ```
  with
  ```markdown
  - [x] ~~**Push the branch:** `git push origin feat/timing-compare`.~~ N/A — no
        `feat/timing-compare` branch ever existed; T1–T11 are already on `main` as
        standalone commits (see the header above).
  - [x] ~~**Draft the PR:** Summary / Notable Decisions / Test Plan; pause for approval.~~
        N/A for the same reason — nothing to open a PR against.
  ```
  Leave the `CI / gates:` closing line as `[ ]` — it is still meaningful (run it once
  more after Task 18's real-media run to confirm nothing regressed):
  ```sh
  ruff check tools/timing_compare.py tools/vad.py tests/test_timing_compare.py
  python3 -m pytest tests/test_timing_compare.py tests/test_vad.py -q
  ```
  Expect: `All checks passed!` and all tests passing; tick that box once confirmed.
- [ ] Commit: `git add specs/timing-compare/tasks.md && git commit -m "docs(timing-compare): reconcile tasks.md against the commits that actually shipped"`

## Task 20: Queue and publish operations verification (owner/live)

Sprint: 014 Scope: [S-18]
Files: none in the repository — this task's deliverable is a written note at
`/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/<YYYY-MM-DD> Queue and Publish Verification.md`
(the vault, never the repo — live host facts don't go in public source).
Interfaces consumed: `watch_queue.py`'s `main()` (`--dry-run`, `--out` default
`os.environ.get("ANIME_ORDER", "/config/anime_order.txt")`), `deploy/dubtitlerr-
publish.{service,timer}` (`Type=oneshot`, `TimeoutStartSec=3h`, `OnCalendar=*-*-* 08:00:00`
/ `22:00:00`, `Persistent=true`), `tools/publish_subtitles.sh`, `tools/export_subtitles.py`'s
`published_title(basename)` (strips `RELEASE_TAG_TAIL`/`BARE_TAG_TAIL` from the media
filename so the public repo publishes `Show - SxxExx - Episode Title`, never the rip name).

This is v0.2.0 candidate item 8. The owner's 2026-09-21 correction already closed the
"zero-real-directory pin" risk (fixed by commit `030ad4a` — `watch_queue.py`'s `build()`
already routes every `--pin` through the same three-tier matching a watched title gets, and
refuses to write on zero matches). This task is the mechanical operational verification
that's left: timers installed and valid, the deployed order file isn't stale against what
`watch_queue.py` would produce today, and the title-stripping policy is still intentional.

- [ ] **OWNER/LIVE:** confirm which host actually runs the publish timer before touching
      anything — do not assume vm102 or fasc:
  ```sh
  for h in vm102 fasc; do echo "=== $h ==="; ssh "$h" "systemctl list-timers 'dubtitlerr*' 2>&1"; done
  ```
  Expect: exactly one host lists `dubtitlerr-publish.timer` with a `NEXT`/`LEFT`
  column; record which host in the vault note (field: `Host`).
- [ ] **OWNER/LIVE**, on that host, from a checkout of this repo (or copy `deploy/` there):
      validate the unit file itself:
  ```sh
  systemd-analyze verify deploy/dubtitlerr-publish.service
  ```
  Expect: no output (a clean verify prints nothing); any `Failed to parse` or
  `Unknown key` line is a real defect — record it in the vault note (field: `Unit
verify`) and do not proceed to the timer-status step until it's fixed or explicitly
  accepted as a known/ignorable systemd-analyze quirk.
- [ ] **OWNER/LIVE:** check the timer's live status and the last run's result:
  ```sh
  systemctl status dubtitlerr-publish.timer
  systemctl status dubtitlerr-publish.service
  journalctl -u dubtitlerr-publish.service -n 50
  ```
  Expect: the timer `active (waiting)` with a `Trigger:` timestamp near the next
  08:00/22:00 slot; the service's last run `Main PID: ... status=0/SUCCESS` (or a
  named, understood failure); the journal tail ending in either `publish: pushed N
file(s)` or `publish: nothing changed — no commit` (both are healthy — see
  `tools/publish_subtitles.sh`'s own comment: "CONTENT... a run that re-derives the
  library without changing any output produces an empty diff"). Record the last run's
  timestamp and outcome in the vault note (fields: `Last run`, `Result`).
- [ ] **OWNER/LIVE:** order-file drift check — does the deployed `/config/anime_order.txt`
      match what `watch_queue.py` would currently produce (mechanical drift only; the
      matching/pin logic itself is already verified correct per the 2026-09-21 correction,
      so this step is NOT re-testing that):
  ```sh
  cat /config/anime_order.txt > /tmp/current_order.txt
  docker run --rm --entrypoint python3 \
    -v /home/claude/dubtitle-config:/config:ro \
    -v "/mnt/r520-media-full/Anime Library:/media/Anime Library:ro" \
    -e WATCHSTATE_URL -e WATCHSTATE_API_KEY -e PLEX_URL -e PLEX_TOKEN \
    dubtitle-builder:0.1.0 /app/watch_queue.py --dry-run \
    | sed -n 's/^ *[0-9]\+ //p' > /tmp/candidate_order.txt
  diff /tmp/current_order.txt /tmp/candidate_order.txt
  ```
  Expect: no diff, or a diff whose only changes are shows that fell outside/into the
  90-day `--window-days` watch window (not a bug — the queue is meant to move as
  watch activity ages out). A diff that DROPS a show still mid-watch, or introduces a
  show nobody has watched, is a real drift — record it in the vault note (field:
  `Order-file drift`) with the diff output, and re-run `watch_queue.py` for real
  (without `--dry-run`) only after the owner confirms the new order is correct.
- [ ] **OWNER/LIVE:** title-policy spot-check — confirm `published_title()`'s stripping
      behavior is still what the public repository should ship. Quoting the function
      itself (`tools/export_subtitles.py:178-190`, unchanged from what's on `main`):
  ```python
  def published_title(basename: str) -> str:
      """The episode's name as it appears in the public repository: `Show - SxxExx - Title`.
      ...
      Idempotent by construction, which is load-bearing: `entry_key` is built from this, so a
      title that changed shape would present every already-published episode as new."""
      stripped = BARE_TAG_TAIL.sub("", RELEASE_TAG_TAIL.sub("", basename)).strip()
      return stripped or basename
  ```
  and `tools/publish_subtitles.sh`'s own comment on what it does NOT publish: no
  license file (subtitle text, not code) and no republish on an unchanged diff (change
  detection is `export_subtitles.py`'s job, by content hash, never by mtime). Spot-check
  against 2-3 real published filenames on the target host:
  ```sh
  docker run --rm --entrypoint python3 -v "$PWD":/app:ro dubtitle-builder:0.1.0 -c "
  import sys; sys.path.insert(0, '/app')
  from tools.export_subtitles import published_title
  for name in ['Show Name - S01E01 - Title [WEBDL-1080p][8bit][AAC 2.0][x264]-GROUP.mkv',
               'Show.Name.S01E02.Title.1080p.6ch.x265.mkv']:
      print(name, '->', published_title(name))
  "
  ```
  Expect: both print a clean `Show Name - S01E0N - Title` with no bracketed or bare
  release tags. Record the two before/after pairs in the vault note (field: `Title
policy spot-check`) as evidence the policy is still intentional, not drifted.
- [ ] **OWNER/LIVE:** write the vault note at
      `/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/<YYYY-MM-DD> Queue and Publish Verification.md`
      with these fields: `Host`, `Unit verify`, `Last run`, `Result`, `Order-file drift`,
      `Title policy spot-check`, `Rollback location` (where `SUBS_REPO`'s checkout lives on
      the host, for reverting a bad publish via `git revert` there).
- [ ] No commit in this repository — this task's evidence lives entirely in the vault note
      above (per this plan's OWNER/LIVE convention: live-host facts never go in public
      source).

## Task 21: Storage/host checklist (owner/live) and the FFMPEG_TIMEOUT default

Sprint: 014 Scope: [S-19]
Files: `generate.py` (bump `FFMPEG_TIMEOUT`'s default and its docstring line), `docs/wiki/
Reference.md` (env-table row), `tests/test_generate.py` (update the existing default-value
regression test).
Interfaces: `generate.FFMPEG_TIMEOUT` (module-level `int`, read once at import from
`os.environ.get("FFMPEG_TIMEOUT", "1800")`) — unchanged shape, only the literal default
changes; every other consumer (`extract_wav()`'s `subprocess.run(..., timeout=
FFMPEG_TIMEOUT)`) is untouched.

This is v0.2.0 candidate item 14. The owner's 2026-09-21 correction already established
`FFMPEG_TIMEOUT` is NOT hard-coded — it's `int(os.environ.get("FFMPEG_TIMEOUT", "600"))`
at `generate.py:117`, documented as tunable at `generate.py:32-33` — so this task is
"raise the shipped default," not "add an env override that doesn't exist." A 556 MB
episode already failed at the default 600s on the measured NAS read rate. The other
bullets under item 14 (single-worker verification, mergerfs `pfrd` persistence, the `sdc1`
writer, the stopped 3200g container, `llama-embed` GPU contention) are OWNER/LIVE
observations with no corresponding code change — they're checklist steps below, not
inputs to the code change.

- [ ] Write the failing test first — update the existing regression test that pins the
      pre-change default (it currently asserts the OLD literal, so it must go red before
      the code changes): in `tests/test_generate.py`, replace
  ```python
  def test_ffmpeg_timeout_defaults_match_the_pre_override_literals():
      """Breaks if adding the override silently changed production behaviour. An unset
      env must reproduce exactly the timeouts that were compiled in before."""
      assert generate.FFMPEG_TIMEOUT == 600
      assert generate.FFPROBE_TIMEOUT == 60
  ```
  with
  ```python
  def test_ffmpeg_timeout_defaults_match_the_pre_override_literals():
      """Breaks if the shipped default silently changes again. Raised 600 -> 1800
      (v0.2.0, storage/host checklist item 14): a 556 MB episode measured on the NAS
      failed at 600s. FFPROBE_TIMEOUT (a much smaller read) is untouched."""
      assert generate.FFMPEG_TIMEOUT == 1800
      assert generate.FFPROBE_TIMEOUT == 60
  ```
  Run `python3 -m pytest tests/test_generate.py -k test_ffmpeg_timeout_defaults_match_the_pre_override_literals -q`;
  expect FAIL with `assert 600 == 1800`.
- [ ] Implement minimally: in `generate.py`, change
  ```python
  FFMPEG_TIMEOUT = int(os.environ.get("FFMPEG_TIMEOUT", "600"))
  ```
  to
  ```python
  FFMPEG_TIMEOUT = int(os.environ.get("FFMPEG_TIMEOUT", "1800"))
  ```
  and update the docstring two lines above it (currently `generate.py:32-33`):
  ```python
  FFMPEG_TIMEOUT  default 600  (seconds; the wav decode in extract_wav. Raise it on a
                  slow NFS mount -- a timeout here fails the episode)
  ```
  to
  ```python
  FFMPEG_TIMEOUT  default 1800  (seconds; the wav decode in extract_wav. Raised from
                  600 -- a 556 MB episode failed at 600s on the measured NAS read
                  rate. Raise it further on a slower mount; a timeout here fails
                  the episode)
  ```
- [ ] Update `docs/wiki/Reference.md`'s env-table row. Current line:
  ```markdown
  | `FFMPEG_TIMEOUT` / `FFPROBE_TIMEOUT` | `600` / `60`     | Seconds                                                                                        |
  ```
  New line:
  ```markdown
  | `FFMPEG_TIMEOUT` / `FFPROBE_TIMEOUT` | `1800` / `60`    | Seconds                                                                                        |
  ```
- [ ] Run `python3 -m pytest tests/test_generate.py -q`; expect pass (the whole file, not
      just the one test — `FFMPEG_TIMEOUT` is read at several other test sites via
      `monkeypatch.setattr`, which is unaffected by the default changing, but confirm
      nothing else hard-coded the old literal).
- [ ] Run `ruff check .`; expect `All checks passed!`.
- [ ] Commit: `git commit -m "fix(generate): raise FFMPEG_TIMEOUT default 600 -> 1800 for slow NFS reads"`
- [ ] **OWNER/LIVE, remainder of item 14's checklist (no further code change):** confirm
      exactly one worker container is running against the library, across every host that
      has ever hosted it:
  ```sh
  for h in vm102 fasc 3200g-docker; do echo "=== $h ==="; ssh "$h" "docker ps --filter ancestor=dubtitle-builder:0.1.0 2>&1"; done
  ```
  Expect: exactly one host shows a running container; any second host with one running
  is the exact "two workers race against one library" hazard AGENTS.md warns about —
  stop the extra one immediately (record which host/container in the vault note before
  stopping it, in case it needs to be restarted elsewhere).
- [ ] **OWNER/LIVE:** identify the mergerfs `create` policy currently in force and whether
      `pfrd` is set, on the OMV host managing the pool:
  ```sh
  getfattr -n user.mergerfs.category.create /srv/mergerfs/pool/.mergerfs
  ```
  Expect: a policy name (e.g. `mfs`, `epmfs`, `pfrd`). If it is not `pfrd` and `pfrd`
  is still wanted, persist it through OMV's managed config (not a raw runtime
  `setfattr`, which OMV will revert on its next apply) — record the exact OMV UI path
  or `omv-rpc` call used in the vault note (field: `mergerfs create policy`).
- [ ] **OWNER/LIVE:** identify the unexplained continuous writer on `sdc1`:
  ```sh
  iotop -aoP -d 5 -n 12
  pidstat -d 5 12
  ```
  Expect: 12 samples over 60s; record the top writer's process name/PID and whether
  it correlates with a known service (Plex library scan, mergerfs balance, DubTitlerr
  itself) in the vault note (field: `sdc1 writer`). An unidentified writer is a real
  open finding, not a step to silently resolve here.
- [ ] **OWNER/LIVE:** classify the stopped `dubtitle-builder` container on the old 3200g
      host — dead weight or standby:
  ```sh
  ssh 3200g-docker "docker ps -a --filter name=dubtitle-builder"
  ```
  Expect: one `Exited (...)` container. Per `project_dubtitlerr_3200g_move` (the GPU
  was physically removed from that host 2026-08-23), this container cannot be
  restarted there — record the decision "dead weight, remove" or "standby, keep" in
  the vault note (field: `3200g container`); if "remove", `docker rm` it as a separate
  explicit step the owner runs, not bundled into this verification pass.
- [ ] **OWNER/LIVE:** restart `llama-embed` on vm102 before any bake-off needing the 1050
      Ti, and record current GPU contention:
  ```sh
  nvidia-smi
  docker ps --filter name=llama-embed
  ```
  Expect: `nvidia-smi` lists the 1050 Ti's current processes (Jellyfin transcode,
  ollama, subgen/dubtitle-builder, llama-embed — whichever are live); record the
  snapshot in the vault note (field: `GPU contention`) so a future bake-off has a
  baseline to compare against, and restart `llama-embed` only if it is not already
  the process holding the card.
- [ ] **OWNER/LIVE:** write/extend the vault note at
      `/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/<YYYY-MM-DD> Storage and Host Checklist.md`
      with the fields named above (`Worker host`, `mergerfs create policy`, `sdc1 writer`,
      `3200g container`, `GPU contention`) plus an explicit line: "do not start a
      library-wide sweep as a substitute for this checklist — production has no locking."

## Task 22: S&S extract-only prototype

Sprint: 014 Scope: [S-20]
Files: `tools/sns_extract.py` (new, ~100 lines), `tests/test_sns_extract.py` (new),
`docs/beta-feedback/<YYYY-MM-DD>-sns-extract-fp-inventory.md` (new template, filled in
after the owner runs it on real tracks).
Interfaces produced: `sns_extract.off_default_position(ev: pysubs2.SSAEvent, play_res_y:
int) -> bool`; `sns_extract.classify_event(ev: pysubs2.SSAEvent, play_res_y: int) -> str`
(one of `"position_only"`, `"keep"`, `"drop"`); `sns_extract.extract(path: str, out_dir:
str) -> tuple[pysubs2.SSAFile, collections.Counter]`. Interfaces consumed: `dub_signs_
merge.keep_event(ev)` (imported, not reimplemented).

This is v0.2.0 candidate item 12, from the r/Animedubs beta thread
(`docs/beta-feedback/2026-09-07-r-animedubs.md`): u/RelativeMundane9045's tip that pirate
groups build S&S tracks by "isolating all the text that's not in the default location," and
u/BlueSpark4's request for "a slimmed down version... which only extracts... signs&text
subs from a full English subtitle track." **This is explicitly NOT wired into
`merge_pass.sh` or any pipeline stage** — it is a read-only research prototype to scope a
possible future feature, per the weekly plan's own instruction ("do not wire it into
production before the classifier has fixtures").

- [ ] Write the failing tests first, in `tests/test_sns_extract.py`:
  ```python
  """Unit tests for tools/sns_extract.py: off_default_position()/classify_event() with
  programmatic pysubs2.SSAEvent fixtures (no .ass files exist in tests/fixtures -- same
  pattern as tests/test_dub_signs_merge.py's ev() helper)."""

  import pysubs2
  import sns_extract as sns

  PLAY_RES_Y = 288


  def ev(text="hello", style="Default"):
      return pysubs2.SSAEvent(text=text, style=style)


  # --- classify_event() matrix -------------------------------------------------


  def test_classify_event_keeps_positioned_sign():
      e = ev(text=r"{\pos(400,50)}Sign text", style="Text")
      assert sns.classify_event(e, PLAY_RES_Y) in ("keep", "position_only")


  def test_classify_event_keeps_karaoke():
      e = ev(text=r"{\k30}ka{\k30}ra{\k30}o{\k30}ke", style="Text")
      assert sns.classify_event(e, PLAY_RES_Y) in ("keep", "position_only")


  def test_classify_event_drops_plain_dialogue():
      e = ev(text="Just talking.", style="Main")
      assert sns.classify_event(e, PLAY_RES_Y) == "drop"


  def test_classify_event_an8_top_alignment_counted_position_only():
      # A KNOWN FP class: plain dialogue top-aligned with \an8 and nothing else --
      # dub_signs_merge.keep_event would ALSO return True for this (its own POSITIONED
      # regex matches \an8), but off_default_position is checked first here so the
      # reason attributes to "position_only", not "keep" -- see module docstring.
      e = ev(text=r"{\an8}Top-aligned dialogue, not actually a sign.", style="Default")
      assert sns.off_default_position(e, PLAY_RES_Y) is True
      assert sns.classify_event(e, PLAY_RES_Y) == "position_only"


  def test_classify_event_keeps_credits_style():
      e = ev(text="Directed by Someone", style="Credits")
      assert sns.classify_event(e, PLAY_RES_Y) == "keep"


  def test_off_default_position_false_for_an2_bottom_center():
      e = ev(text=r"{\an2}Bottom-center dialogue.", style="Default")
      assert sns.off_default_position(e, PLAY_RES_Y) is False


  def test_off_default_position_false_with_no_override_tags():
      e = ev(text="Plain line, no tags at all.", style="Default")
      assert sns.off_default_position(e, PLAY_RES_Y) is False


  def test_off_default_position_true_for_move_near_top():
      e = ev(text=r"{\move(100,50,300,50)}Moving sign", style="Text")
      assert sns.off_default_position(e, PLAY_RES_Y) is True


  # --- mixed-track counting -----------------------------------------------------


  def test_extract_counts_a_mixed_track(tmp_path):
      subs = pysubs2.SSAFile()
      subs.info["PlayResY"] = "288"
      subs.append(ev(text="Just talking.", style="Main"))  # drop
      subs.append(ev(text=r"{\k30}ka{\k30}ra", style="Text"))  # keep or position_only
      subs.append(ev(text=r"{\an8}Top dialogue.", style="Default"))  # position_only
      subs.append(ev(text="Directed by Someone", style="Credits"))  # keep
      src = tmp_path / "track.ass"
      subs.save(str(src))

      out_dir = tmp_path / "out"
      out_dir.mkdir()
      kept, counts = sns.extract(str(src), str(out_dir))

      assert counts[("Main", "drop")] == 1
      assert counts[("Default", "position_only")] == 1
      assert counts[("Credits", "keep")] == 1
      assert len(kept.events) == 3  # everything except the dropped "Main" line
      assert (out_dir / "track.sns.ass").exists()
  ```
  Run `python3 -m pytest tests/test_sns_extract.py -q`; expect FAIL with
  `ModuleNotFoundError: No module named 'sns_extract'`.
- [ ] Implement minimally — the full file at `tools/sns_extract.py`:
  ```python
  #!/usr/bin/env python3
  """S&S extract-only prototype (docs/beta-feedback/2026-09-07-r-animedubs.md): pull just
  the signs/songs/credits events out of a full English subtitle track, no Whisper involved.

  Two independent classifiers decide KEEP, either is enough:
    - dub_signs_merge.keep_event(ev): the existing tag/style classifier (karaoke, \\pos/
      \\move, drawing, animated, or a sign/song/credit style name).
    - off_default_position(ev, play_res_y): a numeric heuristic from the beta-feedback
      thread's own description of how pirate groups build S&S tracks -- "extract what's
      not in the default location" -- checked FIRST so its hits are attributable in the
      per-reason table even when keep_event() would also have kept the same event (e.g. an
      \\an8 top-aligned line: dub_signs_merge's own POSITIONED regex already matches \\an8,
      so without checking position first every such line would be silently folded into
      keep_event's bucket and this heuristic's real hit rate -- and its false-positive
      rate on plain top-aligned dialogue -- would be invisible).

  Read-only: never mutates the source .ass. Writes `<stem>.sns.ass` into --out (a
  directory), never beside the source media. NOT wired into merge_pass.sh -- this is a
  prototype for scoping the feature request, not a pipeline stage.

  Built with help of Claude (Anthropic).
  """

  from __future__ import annotations

  import argparse
  import os
  import re
  import sys
  from collections import Counter

  import pysubs2

  sys.path.insert(0, ".")
  import dub_signs_merge as dsm

  DEFAULT_PLAY_RES_Y = 288  # matches dub_signs_merge.py's no-PlayRes-declared fallback
  OFF_DEFAULT_Y_FRACTION = 0.75  # top 75% of the frame is "not where dialogue sits"

  _POS_RE = re.compile(r"\\pos\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)")
  _MOVE_RE = re.compile(r"\\move\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,")
  _AN_RE = re.compile(r"\\an(\d)")


  def off_default_position(ev: pysubs2.SSAEvent, play_res_y: int) -> bool:
      """True if `ev`'s override tags place it away from the bottom-center dialogue spot:
      an explicit \\pos(x,y)/\\move(x1,y1,...) whose y sits above the bottom quarter of the
      frame (y < 0.75 * play_res_y -- ASS y grows downward, so a SMALL y is a sign near the
      top), or an explicit \\an<N> alignment override where N is not 2 (bottom-center,
      libass's default). `play_res_y` must be > 0 -- callers resolve a missing/zero
      PlayResY to DEFAULT_PLAY_RES_Y before calling this."""
      t = ev.text
      m = _POS_RE.search(t) or _MOVE_RE.search(t)
      if m and float(m.group(2)) < OFF_DEFAULT_Y_FRACTION * play_res_y:
          return True
      m2 = _AN_RE.search(t)
      return bool(m2 and m2.group(1) != "2")


  def classify_event(ev: pysubs2.SSAEvent, play_res_y: int) -> str:
      """One of "position_only" (off_default_position fired -- checked first, see module
      docstring), "keep" (dub_signs_merge.keep_event fired and position did not), or
      "drop"."""
      if off_default_position(ev, play_res_y):
          return "position_only"
      if dsm.keep_event(ev):
          return "keep"
      return "drop"


  def extract(path: str, out_dir: str) -> tuple[pysubs2.SSAFile, Counter]:
      """Load `path`, classify every event, build the kept-only SSAFile (styles imported
      from the source so KEEP_STYLE-matched lines still render), write
      `<stem>.sns.ass` under `out_dir`, and return (kept_subs, per (style, reason) counts)."""
      subs = pysubs2.load(path)
      play_res_y = int(subs.info.get("PlayResY") or 0) or DEFAULT_PLAY_RES_Y

      counts: Counter = Counter()
      kept = pysubs2.SSAFile()
      kept.info.update(subs.info)
      kept.import_styles(subs)
      for ev in subs.events:
          reason = classify_event(ev, play_res_y)
          counts[(ev.style or "", reason)] += 1
          if reason != "drop":
              kept.append(ev)

      stem = os.path.splitext(os.path.basename(path))[0]
      out_path = os.path.join(out_dir, stem + ".sns.ass")
      kept.save(out_path)
      return kept, counts


  def print_counts(path: str, counts: Counter) -> None:
      print(f"{path}:")
      for (style, reason), n in sorted(counts.items()):
          print(f"  {style:<20} {reason:<14} {n}")


  def build_arg_parser() -> argparse.ArgumentParser:
      ap = argparse.ArgumentParser(description="Extract-only S&S prototype (see module docstring).")
      ap.add_argument("ass_file", nargs="+", help="one or more extracted subtitle-stream .ass files")
      ap.add_argument("--out", required=True, help="directory to write <stem>.sns.ass into (never beside the media)")
      return ap


  def main(argv=None) -> int:
      a = build_arg_parser().parse_args(argv)
      os.makedirs(a.out, exist_ok=True)
      for path in a.ass_file:
          _kept, counts = extract(path, a.out)
          print_counts(path, counts)
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```
- [ ] Run `python3 -m pytest tests/test_sns_extract.py -q`; expect `9 passed`.
- [ ] Run `ruff check .`; expect `All checks passed!` (verified against this repo's actual
      `pyproject.toml` config: `ruff check --config pyproject.toml tools/sns_extract.py
tests/test_sns_extract.py` returns no findings).
- [ ] Commit: `git add tools/sns_extract.py tests/test_sns_extract.py && git commit -m "feat(tools): sns_extract -- read-only S&S extract-only prototype"`
- [ ] Write the FP-inventory template at
      `docs/beta-feedback/<YYYY-MM-DD>-sns-extract-fp-inventory.md`:
  ```markdown
  # S&S extract-only prototype — false-positive inventory (<DATE>)

  Run against 3 real extracted subtitle-stream .ass tracks (one per show class from
  Task 18's discovery: a fansub dialogue track, a signs-only track, One Pace) via:

  \`\`\`sh
  python3 tools/sns_extract.py track1.ass track2.ass track3.ass --out /tmp/sns-out
  \`\`\`

  ## FP classes observed

  - **position_only, alignment-only (\\an8/\\an7/... with no \\pos):** count and 2-3
    example lines. This is the class `test_classify_event_an8_top_alignment_counted_
    position_only` names explicitly as "known" -- record whether it's actually noisy
    on real tracks or mostly correct in practice.
  - **position_only, genuine sign but style already matched by dub_signs_merge.keep_
    event:** count -- these are harmless double-counts, not a real FP class, but worth
    separating from the above so the alignment-only class isn't overcounted.
  - **drop, should have been kept (false negative):** any sign/credit/karaoke line
    that fell through both classifiers -- count and example lines; this is the class
    that would need a THIRD heuristic if the feature moves forward.
  - **keep, should have been dropped (false positive from dub_signs_merge itself):**
    any plain dialogue kept only because of a style-name guess (KEEP_STYLE/WEAK_DROP_
    STYLE) -- not new to this prototype, but worth noting if it shows up disproportion-
    ately in the tracks sampled here.

  ## Decision

  <standalone script vs. future pipeline stage -- per the weekly plan, do not wire
  this into merge_pass.sh regardless of the answer here; that requires fixtures beyond
  this prototype's programmatic ones, i.e. a follow-up task, not this one.>
  ```
- [ ] Commit: `git add docs/beta-feedback/ && git commit -m "docs(beta-feedback): S&S extract-only FP-inventory template"`

## Task 23: osv-scanner gap ledger

Sprint: 015 Scope: [S-21]
Files: `.github/workflows/ci.yml` (new job), `AGENTS.md` (one sentence on the host-local
shim).
Interfaces: none new — this wires the existing `uv.lock` (already in the repo, 132 KB,
already scans clean at 35 packages / 0 vulnerabilities per a manual run recorded in
`.procoder/state/handoff.md`) into CI via the third-party `google/osv-scanner-action`,
pinned to a commit SHA the same way `ci.yml`'s existing `actions/checkout`/`actions/setup-
python` steps already are.

This is v0.2.0 candidate item 15. Quoting `.procoder/state/handoff.md`'s relevant lines
verbatim:

```
Machine-local tool workaround, invisible to this repo: `~/.local/bin/osv-scanner`
is now a shim over `osv-scanner.real` that appends `--verbosity error` to
scan-shaped invocations. osv-scanner 2.5.1 writes scalibr progress to stderr and
procoder 2.0.1 parses the scanner's combined output, so every gate run reported
"osv-scanner output unreadable — dependencies were NOT checked". Undo with
`rm ~/.local/bin/osv-scanner && mv ~/.local/bin/osv-scanner.real ~/.local/bin/osv-scanner`.

UNRESOLVED: with the noise gone, the gate now reports the real problem —
procoder hands osv-scanner `pyproject.toml`, which has no extractor in 2.5.1.
`uv.lock` is the scannable artifact and procoder never asks for it. Scanned
manually 2026-08-24: uv.lock, 35 packages, 0 vulnerabilities. Needs an upstream
procoder fix for uv-based Python projects.
```

`osv-scanner` has no PyPI package (`pip install osv-scanner` fails: "No matching
distribution found") — it ships as a Go binary / Docker image only, so the CI job must use
`google/osv-scanner-action`, not a `pip install` step.

- [ ] File the upstream gap on procoder's own repository. procoder's plugin manifest
      (`~/.claude/plugins/cache/procoder/procoder/2.0.1/package.json`) names its source:
      `"url": "git+https://github.com/azrtydxb/procoder.git"`.
  ```sh
  gh issue create --repo azrtydxb/procoder \
    --title "osv-scanner: uv-based Python projects need uv.lock scanned, not pyproject.toml" \
    --body "$(cat <<'EOF'
  procoder's dependency-vulnerability check (\`security --deep\` / the release
  controller's credit/vuln pass) hands osv-scanner 2.5.1 \`pyproject.toml\`, which has
  no extractor in that osv-scanner version -- the scan silently checks nothing.

  For a uv-managed Python project, \`uv.lock\` is the scannable lockfile artifact
  (osv-scanner's own lockfile extractors cover it). procoder should detect \`uv.lock\`
  alongside \`pyproject.toml\` and pass that to \`osv-scanner scan --lockfile
  uv.lock\` instead of (or in addition to) the manifest.

  Reproduced on DubTitlerr (github.com/XenaRathon/DubTitlerr): \`uv.lock\` scans clean
  manually (\`osv-scanner scan --lockfile uv.lock\`: 35 packages, 0 vulnerabilities,
  2026-08-24), but the procoder-driven scan against \`pyproject.toml\` reports nothing
  useful either way -- a real vulnerability in a uv-locked dependency would currently
  go undetected by the gate.

  Workaround in place on our end: CI scans \`uv.lock\` directly via
  \`google/osv-scanner-action\` (not through procoder) until this is fixed upstream.
  EOF
  )"
  ```
  Expect: a new issue URL printed; record it (for cross-reference, not required in
  this repo).
- [ ] Add the CI job. `.github/workflows/ci.yml`'s existing jobs pin actions to commit SHAs
      (`actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5`), so the new job
      follows the same convention. Resolve `google/osv-scanner-action`'s `v2.5.1` tag to a
      commit SHA the same way the existing pins were presumably obtained:
  ```sh
  gh api repos/google/osv-scanner-action/commits/v2.5.1 --jq .sha
  ```
  Expect: `6e4298ebc4db23e847df9b2e2de2939d6f066c67` (verified 2026-09-21; re-run
  before committing in case the tag has moved, though a moved release tag would itself
  be a supply-chain red flag worth stopping on). Add this job to `.github/workflows/
ci.yml`, after the existing `lint` job:
  ```yaml
    osv-scan:
      runs-on: ubuntu-latest
      timeout-minutes: 10
      steps:
        - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5
        # Scans uv.lock directly, not pyproject.toml -- procoder's own gate hands
        # osv-scanner 2.5.1 pyproject.toml, which has no extractor in that version
        # (see the upstream issue filed against azrtydxb/procoder). uv.lock is the
        # scannable lockfile artifact and already scans clean (35 packages / 0
        # vulnerabilities, verified manually 2026-08-24).
        - uses: google/osv-scanner-action/osv-scanner-action@6e4298ebc4db23e847df9b2e2de2939d6f066c67 # v2.5.1
          with:
            scan-args: |-
              --lockfile=./uv.lock
  ```
- [ ] Verify the action's own inputs before committing (this repo has no way to run a
      Docker-based composite action locally, so verify the underlying command directly
      with the installed CLI instead — same scan the action will run):
  ```sh
  osv-scanner scan --lockfile=./uv.lock
  ```
  Expect: `No issues found` (matches the manual 2026-08-24 result recorded in
  `handoff.md`; a real finding here means the dependency picture changed since and
  should be resolved before this job goes live, not silenced).
- [ ] Add one sentence to `AGENTS.md`'s "Repo conventions" section making the host-local
      shim explicit, so it's never mistaken for something CI or a fresh clone needs:
  ```markdown
  - **`osv-scanner` on this maintainer's machine** is a host-local shim over the real
    binary (appends `--verbosity error` so procoder's gate can parse its output) — it
    is not part of this repository and a fresh clone needs nothing like it; CI scans
    `uv.lock` directly via `google/osv-scanner-action` instead (`.github/workflows/
    ci.yml`).
  ```
- [ ] Run `ruff check .`; expect `All checks passed!` (no Python changed, but the gate
      runs on every commit per this repo's `[lint] policy = "block"`).
- [ ] Commit: `git add .github/workflows/ci.yml AGENTS.md && git commit -m "ci(security): scan uv.lock with osv-scanner-action, file the procoder gap upstream"`

## Task 24: Release 0.2.0

Sprint: 015 Scope: [S-22]
Files: `pyproject.toml` (version bump), `CHANGELOG.md` (finalize `[Unreleased]` into a
dated entry, open a fresh empty `[Unreleased]`).
Interfaces: none new — this task exercises `procoder release <version>`, the pre-tag
controller already installed for this repo (`.procoder/config.toml`'s `[release] files =
["pyproject.toml"]`, `[test] policy = "block"`), and depends on every prior task in this
plan already being committed (sprints 010-015) — it is the last task in the plan by
design.

**Verified detail that corrects a natural first guess:** procoder's release controller
matches the changelog heading by exact first-field equality after `## ` (`internal/
release/release.go`'s `changelogHasVersion()`: `strings.Fields(line[3:])[0] == version`).
The existing `## 0.1.0 - 2026-09-04` heading has NO brackets around the version — a
`## [0.2.0] - <date>` heading would make the first field literally `[0.2.0]`, which does
NOT equal `0.2.0`, and the release check would report "CHANGELOG.md has no `## 0.2.0`
heading" even with the entry sitting right there. This task uses the repo's own existing
(bracket-free) convention, not the bracketed Keep-a-Changelog style.

- [ ] Bump the version. Current line in `pyproject.toml`:
  ```toml
  version = "0.1.0"
  ```
  New line:
  ```toml
  version = "0.2.0"
  ```
- [ ] Finalize the changelog. Rename the `## [Unreleased]` heading to a dated `## 0.2.0`
      entry (bracket-free, matching `## 0.1.0 - 2026-09-04`'s own shape and
      `changelogHasVersion`'s exact-first-field match), then open a fresh empty
      `[Unreleased]` above it for whatever lands after this tag:
  ```sh
  python3 - <<'EOF'
  import datetime, re
  path = "CHANGELOG.md"
  text = open(path).read()
  today = datetime.date.today().isoformat()
  text = text.replace(
      "## [Unreleased]",
      f"## [Unreleased]\n\n## 0.2.0 - {today}",
      1,
  )
  open(path, "w").write(text)
  EOF
  ```
  Expect: `CHANGELOG.md` now has an empty `## [Unreleased]` section immediately
  followed by `## 0.2.0 - <today>` holding every entry that was previously under
  `[Unreleased]` (the replace only touches the heading line, so the existing bullet
  content below it is now attributed to the `0.2.0` heading — this is correct: those
  bullets ARE what's shipping in 0.2.0).
- [ ] Run the pre-tag controller:
  ```sh
  procoder release 0.2.0
  ```
  A run against the tree as it stood before this task's own changes (2026-09-21)
  printed:
  ```
  newest version in CHANGELOG.md: 0.1.0
  release 0.1.0 is NOT ready:
    the working tree is dirty (untracked counts) — commit everything first
    the gate is not clean — run `procoder check` and fix what it lists
  ```
  confirming the controller genuinely runs every check (version-sync, changelog
  heading, clean tree, gate, suite) rather than trusting the caller. After every prior
  task in this plan is committed and the two edits above are in place, expect instead:
  ```
  release 0.2.0 is ready — tag it:
    git tag -a v0.2.0 -m "0.2.0"
  ```
  If it instead lists failures, fix every one named (it lists them all in one pass,
  never just the first) and rerun — do not hand-wave past a listed failure.
- [ ] Run the suite directly as well, since the controller's own suite leg only runs under
      `[test] policy = "block"` (which this repo has, but confirm explicitly before
      tagging):
  ```sh
  python3 -m pytest -q
  ruff check .
  ```
  Expect: full pass, `All checks passed!`.
- [ ] Commit the version bump and changelog finalize:
  ```sh
  git add pyproject.toml CHANGELOG.md
  git commit -m "release: prepare 0.2.0 -- version bump and changelog finalize"
  ```
- [ ] Record the tag command for the owner to run (the binary never tags — P-CONTROL).
      Printed by `procoder release 0.2.0` above:
  ```sh
  git tag -a v0.2.0 -m "0.2.0"
  git push origin v0.2.0
  ```
- [ ] Record the draft GitHub release command for the owner (draft, not published, so the
      owner reviews before it goes live):
  ```sh
  gh release create v0.2.0 --repo XenaRathon/DubTitlerr --draft \
    --title "v0.2.0" --notes-file <(sed -n '/^## 0.2.0/,/^## 0.1.0/p' CHANGELOG.md | sed '$d')
  ```
  Expect: a draft release URL printed; the owner reviews and publishes it manually.
- [ ] **OWNER/LIVE: representative-media verification checklist**, run against the actual
      deployed worker (verify host with `docker ps` first) before calling 0.2.0 done — three
      episodes, chosen to exercise the three real shapes this release touches. Substitute
      each episode's real stem for `<stem>`:
  ```sh
  docker exec <worker-container> python3 -c "
  import common
  print(common.read_stages('<stem>'))
  print(common.failed_stage('<stem>'))
  "
  ```
- [ ] Run the check above against one `.mp4` episode with no signs track. Expect
      `common.read_stages(stem)` to show `{"repair": {"outcome": "ok", ...}, "mux":
{"outcome": "ok", ...}}` (no `"signs"` stage, or `"signs"` outcome
      `"no-video"`/`"no-reference"` — both legitimate per `common.failed_stage()`'s
      exemption list) and `failed_stage` to print `None`.
- [ ] Run the same check against one `.mkv` episode with a real signs track. Expect a
      `"signs"` stage present with outcome `"ok"`, and `failed_stage` prints `None`.
- [ ] Run the same check against one One Pace episode (the unanchored case). Expect
      `failed_stage` prints `None`; additionally confirm the episode's
      `.dubtitles.conf.json` exists and the muxed file plays with a "Dubtitles" track (per
      `export_subtitles.py`'s own `dubtitles_stream_index()` convention — the muxed video's
      own TRACK_NAME-titled subtitle stream).
- [ ] Confirm `GET /healthz` on the review server reports healthy:
  ```sh
  curl -s http://<worker-host>:8842/healthz
  ```
  Expect: `{"ok": true, ...}` (200). A `503 {"ok": false, "reasons": [...]}` blocks
  calling 0.2.0 verified-in-production — investigate the listed reasons (per sprint
  013's heartbeat/staleness rule) before publishing the draft release.
- [ ] Record all four checks above (the three episode stems checked, their
      `read_stages`/`failed_stage` output, and the `/healthz` response) in the vault at
      `/home/xenarathon/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/<YYYY-MM-DD> 0.2.0 Representative-Media Verification.md`.
