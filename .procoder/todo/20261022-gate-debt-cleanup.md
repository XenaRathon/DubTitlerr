# chore: clear four procoder gate findings (conflict marker, review links, SC2016, eqeqeq)

Status: closed 2026-10-23
Created: 2026-10-22
Type: code
Assigned: jules@google-jules
  Reason: issue-sized chore on a GitHub repo (lint + doc fixes), the Jules lane in the workspace route.
Owns: IMPROVEMENTS.md, docs/Adversarial Reviews/LUNA-2026-09-02-beta-readiness-final-review.md, tools/publish_subtitles.sh, web/src/lib/settingsModel.js, web/tests/browser/settings.spec.ts (added 2026-10-22, see Scope amendment)
Jules session: 13703970121789706032

## Description

Clear the 17 blocking findings `procoder check` reports on four files on `main`. Change only these four files, branch from `main`, and open one PR. Line numbers below are from `main` at 08fe003.

1. **`IMPROVEMENTS.md`: leftover merge conflict.** Line 327 is a stray `=======` and line 334 a stray `>>>>>>> origin/fix/published-episode-titles`; there is no `<<<<<<<`. Lines 328-333 between them are a newer copy of the Repair env-var table (`### Repair (repair.py)`, live copy at lines 286-292), stranded at the end of section 8. Fix it like this:
   - Delete lines 327-334: both markers and the stranded table. Section 8 then ends with its "**Caveat:**" paragraph.
   - Update the live table at lines 286-292 from the stranded copy. Add the `REPAIR_MODEL_SECONDARY` row (default "(same as primary)", candidate `qwen3.6:35b-a3b`, "CPU second opinion"). Set the `REPAIR_LLAMACPP_URL` default to `http://<llm-host>:8080/completion` with Why "Points at Xeon server", which replaces the hard-coded LAN IP. Keep the other rows as they are and keep the table aligned.
   - Change nothing else in the file.
2. **`docs/Adversarial Reviews/LUNA-2026-09-02-beta-readiness-final-review.md`: 13 broken links** on lines 19 (x2), 20, 46, 47, 76, 77, 78, 103, 126, 154, 155 and 183. The files they point to still exist at the repo root (`common.py`, `mux.py`, `dub_signs_merge.py`, `review_apply.py`, `repair.py`, `glossary_acquire.py`, `acquire_cache.py`, `watch_queue.py`, `decisions.py`, `review_server.py`). The links break because the target has a `:<line>` suffix, as in `(../../common.py:143)`, which the checker reads as part of the file name. Change each suffix to a GitHub line anchor, `(../../common.py#L143)`; we checked that this form resolves. Fix only the link targets. The link text (e.g. `[common.py:143-162]`) and all prose stay as they are: this is a historical review, so its findings, wording and line numbers must not change.
3. **`tools/publish_subtitles.sh:109`: ShellCheck SC2016.** The single quotes around the `credential.helper='!f() { ... "$GITHUB_PAT"; }; f'` value are on purpose. git runs the helper in its own shell, so `$GITHUB_PAT` has to reach git unexpanded; that keeps the token out of argv and `ps` (see the comment on lines 103-106). Do NOT switch to double quotes. Put `# shellcheck disable=SC2016` on its own line right above line 109, with a short reason (e.g. `# expanded by git's helper shell, not here`). The script must behave exactly as before.
4. **`web/src/lib/settingsModel.js:130`: eqeqeq.** In `isDirty`, `connections != null || stages != null` is true for any value except `null` and `undefined`. A plain `!==` would change that, because `undefined !== null` is true. Keep the behaviour: write `(connections !== null && connections !== undefined) || (stages !== null && stages !== undefined)`, or an equivalent that uses only strict operators. Do not change the ESLint config.

Out of scope: everything else, including other gate findings (e.g. `release.yml` timeout, `Dockerfile.builder` DL3025), formatting other files, and PR #29.

## Acceptance criteria

- [x] `procoder check IMPROVEMENTS.md "docs/Adversarial Reviews/LUNA-2026-09-02-beta-readiness-final-review.md" tools/publish_subtitles.sh web/src/lib/settingsModel.js` reports 0 BLOCKING findings (it reported 17 on `main`).
- [x] `grep -nE '^(<<<<<<<|=======|>>>>>>>)' IMPROVEMENTS.md` prints nothing. The `### Repair` table has a `REPAIR_MODEL_SECONDARY` row and the `<llm-host>` URL. Section 8 ends with the Caveat paragraph.
- [x] In the LUNA review, `git diff` changes only link targets (`:<n>` → `#L<n>`) on the 13 listed lines; link text and prose are byte-identical.
- [x] `tools/publish_subtitles.sh` line 109 is unchanged apart from moving down; the only addition is the `shellcheck disable=SC2016` comment. `shellcheck tools/publish_subtitles.sh` shows no SC2016.
- [x] `isDirty` uses only strict comparisons and gives the same result as before for `null`, `undefined`, `0`, `''`, `false` and `{}` in `connections` and `stages`. The web unit tests still pass (`cd web && npm test`, if the suite exists).
- [x] The Python suite passes: `python -m pytest -q` with the repo's `.venv/bin` first on PATH.
- [x] `git diff --stat main...HEAD` lists exactly these 4 files, plus `web/tests/browser/settings.spec.ts` (Scope amendment).

Scope amendment (user decision, 2026-10-22): the PR also owns `web/tests/browser/settings.spec.ts`, for a whitespace-only prettier fix to two `// gitleaks:allow` comments. Main already fails `npm run format:check` on that file, and the web CI job passes only with it (critic N1).

## Review brief

Review Jules's PR https://github.com/XenaRathon/DubTitlerr/pull/32 (head 038555b, base `main` 94bae4d) against the Description and Acceptance criteria above.

- **Where:** this task file is on the local branch `task/jules-debt-cleanup` in the worktree `~/work/code/scratch-dt-main`. Fetch the PR head with `git fetch origin pull/32/head`. Leave `~/work/code/DubTitlerr` alone; it is the user's checkout on `main`. Do not comment on, push to or merge the PR.
- **Tooling gap:** in a fresh clone, procoder reports `web/src/lib/settingsModel.js` as UNCHECKED, because prettier can't load `prettier-plugin-svelte` without `web/node_modules`. `~/work/code/DubTitlerr/web/node_modules` exists and can be symlinked in. CI (`.github/workflows/ci.yml:70`) runs `npm run format:check` in `web/`.
- **Python suite:** run it with `~/work/code/DubTitlerr/.venv/bin` first on PATH.
- Jules has no procoder, so criterion 1 is unverified until you run it.
- **Critic:** the PR tip is now 60250be (a second Jules commit, which reformatted with prettier). Review that, in the checkout `~/work/code/scratch-dt-pr32` at 60250be; `web/node_modules` and `.venv` are linked there. The lead confirmed that `git diff --stat origin/main...60250be` lists 5 files, including `web/tests/browser/settings.spec.ts`.
- **Git outside your cwd:** use `~/work/.team/bin/git-ro <repo> <subcommand>` (read-only, allow-listed), e.g. `~/work/.team/bin/git-ro ~/work/code/scratch-dt-main diff --stat origin/main...038555b`. Do not use `git -C`.

## Review

reviewer @ agy Gemini 3.8 Flash high: PASS

Findings:
1. `web/tests/browser/settings.spec.ts:550,641` — `should-fix` (applies to remote PR branch tip `60250beb`, not assigned head `038555b`).
   - Failure scenario: At assigned head `038555b`, `git diff --stat main...038555b` lists exactly the 4 files in `Owns:`. However, on GitHub PR #32, a subsequent commit `60250beb` was pushed that ran prettier across `web/`, which reformatted whitespace before `// gitleaks:allow` on lines 550 and 641 in `web/tests/browser/settings.spec.ts`. This causes `git diff --stat main...FETCH_HEAD` to list 5 files instead of 4, violating Criterion 7 and modifying files outside `Owns:`. Recommend either merging `038555b` directly or dropping the changes to `web/tests/browser/settings.spec.ts` from PR #32.
2. `tools/publish_subtitles.sh:109` — `nit`
   - Failure scenario: Description requested adding a short explanation comment with the disable directive (e.g., `# expanded by git's helper shell, not here`), but only `# shellcheck disable=SC2016` was added. Shellcheck SC2016 is cleanly suppressed, and the preceding comments on lines 103-106 already explain why git helper shell expansion is needed, so no functional or lint failure occurs.

## Evidence

Verified by the lead at PR #32 tip 60250be (`~/work/code/scratch-dt-pr32`, `git rev-parse --short HEAD` = 60250be). This replaces evidence a reviewer seat had written here against 038555b.

1. `procoder check` on the 5 files: `3 clean, 0 unformatted, 2 unchecked, 0 out of scope, 2 hygiene finding(s) (0 blocking)`. The 2 unchecked are the .js/.ts files, because procoder's prettier can't load prettier-plugin-svelte from the repo root. In `web/`, `npm run format:check` passes and covers that gap.
2. `grep -cE '^(<<<<<<<|=======|>>>>>>>)' IMPROVEMENTS.md` → 0. The table has the `REPAIR_MODEL_SECONDARY` row and `http://<llm-host>:8080/completion` (line 293). The file ends with the Caveat paragraph.
3. LUNA review: after mapping `#L<n>` back to `:<n>` in link targets, `diff` against origin/main is empty. That leaves 13 links changed on 13 lines.
4. `shellcheck tools/publish_subtitles.sh` → exit 0. Line 110 is byte-identical to main's line 109. The disable line carries no reason (reviewer/critic nit, accepted).
5. `isDirty`: 242 input combinations, old `!=` vs new code, 0 mismatches. The web CI line (`npm run format:check && npm run check && npm test && npm run build`) → exit 0, with 105 pass and 0 fail.
6. `PATH=.venv/bin:$PATH python -m pytest -q` → exit 0.
7. `git diff --name-only origin/main...HEAD` → the 4 owned files plus web/tests/browser/settings.spec.ts.
8. `gh pr checks 32`: lint, osv-scan, review-ui and test (3.11, 3.13) all pass.

## Result
Jules COMPLETED (https://jules.google.com/session/13703970121789706032), verified via GET /sessions/13703970121789706032.
PR: https://github.com/XenaRathon/DubTitlerr/pull/32

critic @ claude-opus-5-5: PASS (code is correct at 60250be. One scope point goes to the user, see N1.)

Reviewed `~/work/code/scratch-dt-pr32` at 60250be (`git rev-parse --short HEAD` = 60250be), `git diff origin/main...HEAD`.

### Reviewer findings

1. **settings.spec.ts out of scope: the observation is CONFIRMED, the remedy is REFUTED.** At 60250be the diff covers 5 files. The extra file is `web/tests/browser/settings.spec.ts:553,644` (the reviewer's 550/641 are the hunk starts), and the only change is two spaces → one before `// gitleaks:allow`. But "merge 038555b directly" would break CI. Each file was checked with `npx prettier --check --stdin-filepath <f>` in `web/`:
   - `origin/main:web/tests/browser/settings.spec.ts`: rc=1. main already fails `npm run format:check` (the whitespace came in with PR #29).
   - `038555b:web/src/lib/settingsModel.js`: rc=1. Jules's first commit left `isDirty` as one line that is too long.
   - At 60250be, `npm run format:check`: "All matched files use Prettier code style!" (rc 0).
   CI runs `npm run format:check && ... npm test` as one step (`.github/workflows/ci.yml:70`). So 038555b fails that step on two files, and 60250be is the only head that passes it. Dropping the spec change or merging 038555b both leave the web job red. The spec change still lies outside `Owns:` and breaks criterion 7 as written. That is the user's decision: see N1.
   The edit doesn't weaken the gitleaks suppression: `gitleaks detect --no-git --source web/tests/browser/settings.spec.ts` prints "no leaks found".
2. **publish_subtitles.sh: no reason on the disable line. CONFIRMED, nit.** At `tools/publish_subtitles.sh:109`, the Description asked for "a short reason" next to the directive, and only `# shellcheck disable=SC2016` was added. The comment on lines 103-106 already explains why, and `shellcheck tools/publish_subtitles.sh` exits 0. The command line itself is byte-identical, only moved down one line. This doesn't block.

### New findings

- **N1, escalate (scope / criterion 7):** the PR needs `web/tests/browser/settings.spec.ts` to get CI green, but the task doesn't own that file. The fix is a pure whitespace change. The user should either accept the fifth file, or amend the task so it owns that file. The failure is on main, not caused by this PR, so main's web CI job is red today.
- **N2, info (criterion 1 only partly met):** `procoder check` on the 4 files plus the spec file prints `3 clean, 0 unformatted, 2 unchecked ... (0 blocking)`. The two `.js`/`.ts` files come out UNCHECKED, not clean: procoder runs prettier from the repo root, and the `web/node_modules` symlink doesn't fix it ("Cannot find package 'prettier-plugin-svelte' imported from .../noop.js"). "0 blocking" holds, but procoder never formatted the JS. I covered the gap by running `npm run format:check` in `web/` (pass, above). This is a procoder tooling gap, outside `Owns:`.
- **N3, nit:** both commits carry the same subject, `fix: clear procoder blocking findings in 4 files`. The work is a `chore:`, and the second commit touches 5 files. A squash-merge with a `chore:` title fixes both.

### Attempts to break it

1. **isDirty equivalence, tested wide:** I compared old (`!=`) and new code on `values ∈ {{}, {a:1}}` × `connections, stages ∈ {null, undefined, 0, '', false, {}, [], NaN, 'x', 1, true}`. Result: 242 cases, 0 mismatches (`node scratchpad/eq.mjs`).
2. **IMPROVEMENTS.md:** `grep -nE '^(<<<<<<<|=======|>>>>>>>)'` finds nothing. The live table matches the stranded copy row for row: `REPAIR_MODEL_SECONDARY` is added, the `<llm-host>:8080` URL replaces the LAN IP, and the columns are realigned. The file ends with the Caveat paragraph and a trailing newline (`od -c`). No other hunks.
3. **LUNA links:** the diff has 13 replacements on the listed lines, each `:<n>)` → `#L<n>)` inside the link target only. Link text such as `[common.py:143-162]` and the prose are unchanged.
4. **Shell behaviour:** the single quotes stay, so `$GITHUB_PAT` still reaches git's helper shell unexpanded (nothing goes into argv). shellcheck exits 0.
5. **Gitleaks regression from the whitespace edit:** none (see finding 1).

### Gates

- `npm test` (web): pass 105, fail 0, skipped 1.
- `PATH=.venv/bin:$PATH python -m pytest -q -x`: all passed, rc 0.
- `npm run format:check`: pass.
- PR #32 CI status: **unverified**. `with-secret GH_TOKEN=GITHUB_PAT -- gh pr checks 32` printed nothing, so this seat may lack the grant. The boss should check the checks on 60250be before merging.
