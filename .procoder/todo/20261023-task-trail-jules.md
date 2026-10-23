# docs: land the task-file trail for the Jules jobs (#32, #35)

Status: in review (reviewer PASS, critic next, 2026-10-23)
Created: 2026-10-23
Type: code
Assigned: code-coder
Reason: a docs-only trail change that runs through the normal route; the user approved one small PR.
Owns: .procoder/todo/20261022-gate-debt-cleanup.md, .procoder/todo/20261023-pre-1-0-cleanup-redo.md, .procoder/todo/20261023-task-trail-jules.md (Result only)

## Description

Two Jules jobs ran with their procoder task files on local branches. Jules opened the PRs from its own branches, so those files never reached `main`: PR #32 (task `20261022-gate-debt-cleanup`, merged 57a6463) and PR #35 (task `20261023-pre-1-0-cleanup-redo`, merged 9ef25e2). Both tasks are closed. Bring both closed files onto `main` in one small PR.

- **Checkout:** `/home/xena/work/code/scratch-dt-trail`, on branch `chore/task-trail-jules` from `origin/main` 9ef25e2. `.venv` and `web/node_modules` are symlinked there; keep them out of commits.
- **Sources:** these local branches in the same repository:
  - `task/jules-debt-cleanup` carries `.procoder/todo/20261022-gate-debt-cleanup.md`.
  - `task/jules-pre-1.0-redo` carries `.procoder/todo/20261023-pre-1-0-cleanup-redo.md`.
  - Each branch adds only that one file compared with its merge base on `main`. Take each file exactly as its branch has it, for example with `git checkout <branch> -- <path>`. Don't edit its content.
- **Public repo check:** the repo is public and `.procoder/` is published. Read both files. If either contains anything that shouldn't be public (a secret value, a credential, personal data), stop and escalate it in Result instead of committing. Local absolute paths, seat names and the Jules session URL are fine.
- **Commits:** message `20261023-task-trail-jules: <what changed>`, with no AI or Co-Authored-By trailers (the repo gate blocks them). Don't push; the boss pushes and opens the PR.
- **Untouched:** every other path.

## Acceptance criteria

- [ ] `git diff --stat origin/main HEAD` lists only the two task files, plus this task file.
- [ ] Each file is byte-identical to its source branch: `git diff task/jules-debt-cleanup HEAD -- .procoder/todo/20261022-gate-debt-cleanup.md` and `git diff task/jules-pre-1.0-redo HEAD -- .procoder/todo/20261023-pre-1-0-cleanup-redo.md` are both empty.
- [ ] Both files read `Status: closed`.
- [ ] `procoder check` on the two files reports 0 BLOCKING.
- [ ] Neither file contains a secret value, credential or personal data (escalate if unsure).

## Review

472e9de: reviewer @ agy Gemini 3.8 Flash high: PASS

Reviewed checkout /home/xena/work/code/scratch-dt-trail at REVIEW_SHA 472e9de94b1d1174dab8589cf2c758743aafbe70 (HEAD 3ab0237 differs only by the task file Status line update on branch chore/task-trail-jules; base origin/main 9ef25e2).

Summary: All Acceptance criteria are satisfied. The two closed task files from jobs #32 and #35 are brought onto `main` byte-identical to their source branches, with zero edits and no untracked or unrelated files. Public-repo inspection confirms no secrets, credentials, or personal data are exposed.

Verification:
- File set: `git diff --stat origin/main 472e9de` (and `HEAD`) lists only `.procoder/todo/20261022-gate-debt-cleanup.md`, `.procoder/todo/20261023-pre-1-0-cleanup-redo.md`, and this task file `.procoder/todo/20261023-task-trail-jules.md`. Untracked symlinks (`.venv`, `web/node_modules`) are excluded from git.
- Byte-identity: `git diff task/jules-debt-cleanup HEAD -- .procoder/todo/20261022-gate-debt-cleanup.md` and `git diff task/jules-pre-1.0-redo HEAD -- .procoder/todo/20261023-pre-1-0-cleanup-redo.md` are both completely empty.
- Closed status: Both files read `Status: closed 2026-10-23` on line 3.
- Gate: `procoder check` on both task files reports `1 clean, 1 unformatted, 0 unchecked, 0 out of scope, 3 hygiene finding(s) (0 blocking)`. (Unformatted on `20261022-gate-debt-cleanup.md` is non-blocking and preserved unedited per the byte-identity requirement).
- Public repo check: Full manual read and regex scans for credentials, API tokens, passwords, private keys, IPv4 addresses, and `.env` values confirm zero secrets, credentials, or personal data. All referenced strings are standard identifiers (`X-Review-Token`, `X-Api-Key`, `_cookie_token`, `GITHUB_PAT` / `GH_TOKEN` secret names), git SHAs, seat names, local paths, or public Jules URLs.
- Commits: Commit messages follow convention (`20261023-task-trail-jules: <what changed>`) with no AI or Co-Authored-By trailers.

Findings: none.

472e9de: critic @ claude-opus-5-5: PASS

SHA: `git-ro ... rev-parse HEAD` = 2fc61ed, not the REVIEW_SHA. That is expected under the brief: `git diff 472e9de HEAD` touches only this task file (its Status line and the reviewer's verdict), and `git diff --quiet 472e9de HEAD` on the two trail files exits 0. I reviewed 472e9de, the head the reviewer also checked.

### Independent checks
- **File set:** `git diff --stat origin/main 472e9de` lists the two trail files plus this task file, 3 files, +459. The worktree is clean apart from the untracked symlinks.
- **Byte-identity:** `git diff --quiet task/jules-debt-cleanup 472e9de -- .procoder/todo/20261022-gate-debt-cleanup.md` and the same check for `task/jules-pre-1.0-redo` on `20261023-pre-1-0-cleanup-redo.md` both exit 0.
- **Status:** line 3 of each file reads `Status: closed 2026-10-23`.
- **procoder check** on the two files: `1 clean, 1 unformatted, 0 unchecked, 0 out of scope, 3 hygiene finding(s) (0 blocking)`. The unformatted file is `20261022-gate-debt-cleanup.md`, which has to stay as it is to keep byte-identity. Info: ff1f04e's subject is 79 characters.
- **Commits:** none of ff1f04e, 472e9de or 437a653 carries a `Co-Authored-By` or AI trailer.
- **Public-repo read:** I read both files in full, then scanned them with grep for email addresses, IPv4 addresses, `sk-`/`ghp_`/`github_pat_`/`AKIA` key shapes, `-----BEGIN`, bearer strings, `password=`, and the user's name or email.
  - The only hits are `/home/xena/...` local paths in the pre-1-0 file (8 lines), which the task allows.
  - Secrets appear by name only (`GITHUB_PAT`, `GH_TOKEN`), never by value.
  - `IMPROVEMENTS.md`'s old LAN IP isn't quoted; the gate-debt file says "the hard-coded LAN IP" and `<llm-host>`.
  - "Xeon server" is a hardware description that `IMPROVEMENTS.md` already publishes.
  - `jules@google-jules` is a seat label, and the URLs are a Jules session and a public PR comment.
  - No secret value, credential or personal data.

### Reviewer's 472e9de PASS
**CONFIRMED** on all five points (file set, byte-identity, Status, gate, public read): I re-ran each one above. The reviewer reported no findings, so nothing needed refuting.

### Attempts to break it
1. **Content drift since review:** the two files are unchanged from 472e9de to HEAD.
2. **A secret hiding in prose:** the full read and pattern scan above found none, including the PAT name in the gate-debt Description and my old `with-secret` command line, which names the variable only.
3. **Paths outside Owns:** none. The diff covers exactly 3 files.

### New findings (info only; byte-identity forbids fixing them in this PR)
- **I1, `.procoder/todo/20261022-gate-debt-cleanup.md:75`:** my own 60250be critic verdict sits below `## Result` instead of under `## Review` (line 48). My first run appended it to the end of the file. Anyone reading the closed file finds the critic verdict in an unexpected section. Nothing else breaks. The boss can move it in a later trail edit or leave it as historical.
- **I2, `.procoder/todo/20261023-pre-1-0-cleanup-redo.md` (Result, opening lines):** stale status lines ("Jules AWAITING_USER_FEEDBACK ... No PR. Boss: read the session and decide.", twice) sit next to "PR: .../pull/35". This is a historical log and the lines below it explain the sequence, so no action is needed.

## Evidence

## Result
Outcome: done on `chore/task-trail-jules` (not pushed). Commit ff1f04e adds the two closed task files, taken unedited from their branches with `git checkout <branch> -- <path>`.

Evidence (verified):
- `git diff --stat origin/main HEAD`: `.procoder/todo/20261022-gate-debt-cleanup.md` (+108), `.procoder/todo/20261023-pre-1-0-cleanup-redo.md` (+306), `.procoder/todo/20261023-task-trail-jules.md` (+35, this file as dispatched). Nothing else; `.venv` and `web/node_modules` stay untracked.
- Byte-identical: `git diff task/jules-debt-cleanup HEAD -- .procoder/todo/20261022-gate-debt-cleanup.md` and `git diff task/jules-pre-1.0-redo HEAD -- .procoder/todo/20261023-pre-1-0-cleanup-redo.md` both print nothing.
- Status: line 3 of each reads `Status: closed 2026-10-23` (the pre-1-0 file continues `(reviewer + critic PASS at 8f7ecf1; pushed to #35 at d19b94e, 2026-10-23)`).
- `procoder check` on the two files (`.venv/bin` on PATH): `1 clean, 1 unformatted, 0 unchecked, 0 out of scope, 3 hygiene finding(s) (0 blocking)`. The unformatted one is `20261022-gate-debt-cleanup.md`; non-blocking, and I did not edit it, because the criteria require byte-identity.
- Public-repo read: I read both files in full. Grep for secret/token/password/api-key/bearer/key-prefix patterns, private-key headers, IPv4 addresses, `.env` and long opaque strings found only identifier names (`_cookie_token`, `X-Review-Token`, `X-Api-Key`, `GITHUB_PAT` / `GH_TOKEN` as secret names, not values), git SHAs, branch and test names, local absolute paths, the Jules session URL, and the seat label `jules@google-jules`. No secret value, credential or personal data. The one email-like string is that seat label. Judged fine under the task's rule; flagged here only because it looks like an address.

Escalations: none.
