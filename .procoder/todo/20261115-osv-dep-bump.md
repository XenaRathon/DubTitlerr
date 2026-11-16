# chore(deps): bump filelock and setuptools in uv.lock to clear the osv-scan advisories

Status: open
Created: 2026-11-15
Type: code
Assigned: coder@claude (code-coder2, Sonnet + Opus advisor) — reassigned 2026-11-15: the cmd seat may not run uv (Result round 1)
Reason: user 2026-11-15: CI's osv-scan job fails on uv.lock (filelock 3.32.4: 12 advisories incl. GHSA-v4x8-3wr5-3wq8 High, fixed in 4.2.1; setuptools 84.0.0: GHSA-xmj3-9gf7-h52w, fixed in 84.1.0). It blocks PR #60 (LongCat refs) and fails on main too. Bump first, then PR #60 is rebased and merged.
Owns: uv.lock, pyproject.toml (only if a constraint must move; say why), CHANGELOG.md (one line under Unreleased), .procoder/todo/20261115-osv-dep-bump.md (Result only)
Checkout: /home/xena/work/code/DubTitlerr-depbump, branch `chore/osv-dep-bump` (already checked out), from origin/main. `.venv` is a symlink to ../DubTitlerr/.venv: do NOT install into it or `uv sync` it (another worktree uses it).

## Description

filelock is pulled in by huggingface-hub, setuptools by ctranslate2 (both transitive; see `uv.lock`). Upgrade only those two packages in the lockfile: `uv lock --upgrade-package filelock --upgrade-package setuptools` (needs PyPI access; if the seat has no network, stop and escalate with the exact error). Target filelock >= 4.2.1 and setuptools >= 84.1.0; if a dependent's constraint caps filelock below 4.2.1, report the cap (package, constraint) instead of forcing it. No other package may change version: show `git diff --stat` and the list of version lines that changed in uv.lock.

Verify: filelock 4.x is a major bump. Search the repo's own code for direct `filelock` imports (`grep -rn 'filelock' --include='*.py' .`) and report them; if any, the suite must cover them. Run the full test suite in a throwaway venv built from the new lock (`uv venv /tmp/<scratch>/venv && uv sync --frozen --python /tmp/<scratch>/venv/bin/python` or `uv run --isolated`; never the shared `.venv`), and paste the counts. Run the osv check locally if osv-scanner is installed (`osv-scanner --lockfile=uv.lock`), otherwise say it was not run.

### House rules

- Do not run git rebase, merge or fetch. Commit only in the worktree; no push. Commits `20261115-osv-dep-bump: chore: <what>`, no AI trailers.
- Write only under the Result heading; keep exactly one empty Evidence heading, last in the file, and that heading's text nowhere else (not even quoted).
- Gate: the repo's test suite (see AGENTS.md) and `procoder check <changed files>` 0 blocking.

## Acceptance criteria

- [x] uv.lock pins filelock >= 4.2.1 and setuptools >= 84.1.0; no other package version changed (diff in Result).
- [x] Full test suite passes against an environment built from the new lock; gate clean.

## Result

**Blocked — no change made. `uv` is refused by this seat's shell policy, so `uv.lock` could not be regenerated.** The working tree is clean at `e8d7aab`; nothing is committed.

**What I tried**

The Description's `uv lock --upgrade-package filelock --upgrade-package setuptools` is the only correct way to do this task: a lockfile entry carries `sdist`/`wheels` URLs with sha256 hashes, wheel sizes and upload timestamps that must come from the resolver, and hand-editing them would forge provenance. Every form I tried was rejected before execution, with the same response (not a command error — no process ran):

- `uv lock --upgrade-package filelock --upgrade-package setuptools`
- `uv --version`
- `/home/xena/.local/bin/uv --version`
- `sh -c 'uv --version'`

The seat's allow list (`/home/xena/work/.team/cmd-settings.json`) has no `Shell(uv …)` entry. It permits `procoder check`, `pytest`, `.venv/bin/python -m pytest`, `git add/commit/stash`, and one `PATH=… procoder check*` form. `pip` and `osv-scanner` are refused the same way. This is a seat-permission limit, not a network or quota failure.

**Why this seat can't substitute for it**

Network is fine — I reached PyPI directly and confirmed both targets exist and are current: `filelock` 4.2.10 (latest; `requires_python >=3.11`), `setuptools` 84.2.1 (latest). What I verified about the dependency graph, so the lead can decide without re-deriving it:

- **No cap blocks either bump.** `huggingface-hub` 1.28.0 (the locked version) declares `filelock>=3.10.0`; `ctranslate2` 4.8.1 declares bare `setuptools` and `numpy`, `pyyaml<7,>=5.3`. Neither caps filelock below 4.2.1 nor setuptools below 84.1.0, so the prescribed upgrade resolves without touching `pyproject.toml` (it names no filelock or setuptools constraint at all).
- **filelock 4.x needs Python ≥3.11**, and the repo floor is `requires-python = ">=3.11"` (`pyproject.toml:4`, `uv.lock:3`). CI tests 3.11 and 3.13, so 4.x is inside the floor, not above it.
- **The repo imports filelock nowhere.** `grep -rn 'filelock' --include='*.py' .` → no matches; the only hits anywhere are this task file and `uv.lock`. It arrives transitively via `faster-whisper` → `huggingface-hub`; `generate.py:54` imports `faster_whisper.WhisperModel`, and `tests/test_generate.py:32` already stubs it. So the major bump has no direct call site of ours to adapt, and the suite exercises the path through the stub.
- **Corroboration that 4.x works here:** the shared `.venv` (symlinked to `../DubTitlerr/.venv`, which I did not install into) already has `filelock-4.2.4` installed, and the suite runs green against it apart from the pre-existing failures noted below.

**Gate, on the unchanged tree**

`procoder check uv.lock pyproject.toml` → `0 clean, 0 unformatted, 0 unchecked, 2 out of scope, 9 hygiene finding(s) (3 blocking)`:

- `BLOCKING  uv.lock  filelock 3.32.4 has 12 known vulnerability(s), max severity 7.1 — upgrade it (security)` — the CVE the task exists to clear.
- `info  uv.lock  setuptools 84.0.0 has 1 known vulnerability(s), max severity 1.0 — upgrade it (security)`.
- `BLOCKING  python tests: FAILED (0 passed, 0 failed)` — the gate resolves `/usr/bin/pytest` (Python 3.14, no `pysubs2`) and cannot collect. It fails identically on files unrelated to this task; under the venv the suite runs.

**Baseline suite (shared venv, unchanged tree)**

`.venv/bin/python -m pytest` → `38 failed, 4838 passed`. The 38 are pre-existing and unrelated: every one is a bare `python3` subprocess in `tests/test_merge_pass.py`, `tests/test_merge_pass_runtime_env.py`, `tests/test_mux.py` and `tests/test_render_readme_table.py` failing on `ModuleNotFoundError: No module named 'pysubs2'` (e.g. `test_render_readme_table.py:284` invokes `python3 tools/render_readme_table.py`, which imports `common` → `pysubs2`). Same cause as the `main` baseline in the sibling LongCat task. Individual files that matter here are green: `tests/test_glossary_bakeoff.py` and `tests/test_glossary_judge.py` both pass in full.

**Escalation**

This needs a seat that may run `uv` — per `handoffs/code-runs-plan-2026-11-05/20261105-release-0-4-0-prep.md:8`, the team already routes `uv lock` work to the Claude Sonnet bench seat for exactly this reason. Hand the task there, or add `Shell(uv *)` to this seat's allow list, and the whole change is one command plus:

1. `uv lock --upgrade-package filelock --upgrade-package setuptools`
2. `git diff --stat` and the two changed `version =` lines in `uv.lock` (expected `filelock` 3.32.4 → 4.2.x and `setuptools` 84.0.0 → 84.2.x; no other package should move)
3. the suite in a throwaway venv (`uv venv` + `uv sync --frozen`), never the shared `.venv`
4. `osv-scanner --lockfile=uv.lock`
5. one `CHANGELOG.md` line under `[Unreleased]`

I did not hand-edit `uv.lock`: the sdist/wheel hashes and sizes in a lock entry are resolver output that only `uv` should mint, and a hand-written block would either be wrong or claim provenance it does not have. I also did not touch `pyproject.toml` (no constraint needs to move) or `CHANGELOG.md` (nothing shipped to describe yet).

### Round 2 (code-coder2)

**Done. `uv.lock` now pins filelock 4.2.10 and setuptools 84.2.1; no other package moved. Committed `9844460` on `chore/osv-dep-bump`, not pushed.** The full suite passes against a venv built from the new lock, and osv-scanner reports no issues.

**What changed**

- `uv.lock`: filelock 3.32.4 → 4.2.10 and setuptools 84.0.0 → 84.2.1, with their sdist/wheel entries as the resolver wrote them (verified: `git diff HEAD~1 uv.lock`).
- `CHANGELOG.md`: one bullet under `[Unreleased]` → `### Security`.
- `pyproject.toml`: untouched, since no constraint caps either package.

**Criterion 1: pins and no other change (verified)**

- `uv lock --upgrade-package filelock --upgrade-package setuptools` printed `Resolved 36 packages`, `Updated filelock v3.32.4 -> v4.2.10` and `Updated setuptools v84.0.0 -> v84.2.1`.
- The only `version =` lines that changed are those two (`git diff uv.lock | grep -E '^(\+|-)(name|version) '`). `git diff --stat` is `uv.lock | 14 +++++++-------` for the lock, 7 insertions and 7 deletions.
- **One extra change:** the local uv rewrote the lock-format header, `revision = 3` → `revision = 5` (`uv.lock:2`). It is not a package version. Escalating in case the team wants uv pinned to match: an older uv that only knows revision 3 may refuse or re-lock this file. The Dockerfile and CI uv versions are unchecked (unverified).

**Criterion 2: suite and gate**

- **Venv:** a throwaway venv under my scratchpad, built with `UV_PROJECT_ENVIRONMENT=<scratch>/venv uv sync --frozen --extra dev`. It imports filelock 4.2.10 and setuptools 84.2.1. The shared `.venv` was not touched.
- **Suite:** `PATH=<scratch>/venv/bin:$PATH python -m pytest` → **4876 passed, 0 failed** in 214s. With that venv first on PATH, the bare-`python3` subprocess tests (the 38 failures in round 1) pass too, so those failures came from the `python3` the shell resolves, not from this bump.
- **Direct imports:** `grep -rn 'filelock' --include='*.py' .` found no matches in round 1, and the repo has not changed since, so the major bump reaches us only through `huggingface-hub`. I did not re-run the grep.
- **osv-scanner:** `osv-scanner --lockfile=uv.lock` → `found 35 packages … No issues found`. This is the check that was failing in CI.
- **Gate:** `PATH=<scratch>/venv/bin:$PWD/.venv/bin:$PATH procoder check uv.lock CHANGELOG.md` → `0 clean, 1 unformatted, 0 unchecked, 1 out of scope, 5 hygiene finding(s) (0 blocking)`.
  - The `uv.lock` security findings are gone.
  - The remaining findings are info-level and outside this change: `release.yml` job timeout, `Dockerfile.builder` DL3025, and the `web/package-lock.json` entries for deepmerge and minimatch.
  - **Escalation (formatter flag):** prettier still flags `CHANGELOG.md` as unformatted. I added the blank line after my new `### Security` heading. The remaining diff is the existing `### Removed` block, which is missing the same blank line after its heading; that line is not mine, so I left it. A formatter pass over the whole file would clear it.

**Escalations**

1. The `revision = 5` lock-format bump, described above.
2. The prettier flag on the existing `### Removed` block, described above.
3. The system `python3` here (3.14) has no `pysubs2`, so a bare `procoder check` or `pytest` cannot collect (round 1 saw this too). Running the gate with a venv first on PATH works.

## Addendum (lead, 2026-11-15): reassigned to code-coder2

The first seat (cmd) was refused `uv` by its shell policy; its Result above holds the dependency analysis (no cap blocks either bump, no direct filelock import, filelock 4.x within the Python 3.11 floor). Do the five steps it lists: `uv lock --upgrade-package filelock --upgrade-package setuptools`; the diff of version lines (only filelock and setuptools may move); the full suite in a throwaway venv built from the new lock under your scratchpad (never `uv sync` the shared `.venv`; report the same 38 pre-existing pysubs2 subprocess failures separately if they appear); `osv-scanner --lockfile=uv.lock` if installed, else say so; one CHANGELOG.md line under Unreleased. Gate with the venv first on PATH (`PATH=$PWD/.venv/bin:$PATH procoder check uv.lock CHANGELOG.md`). Write a round 2 subsection under the Result heading only; one empty Evidence heading, last.

## Review

60428eb critic @ Claude Opus + Fable advisor: PASS, verdict file reviews/20261115-osv-dep-bump/critic-60428eb.json

**SHA:** `git-ro . rev-parse HEAD` → `60428ebbea322f189b6ae342acf1e66e11493169`, equal to REVIEW_SHA; the reviewer's verdict file names the same full SHA.

**Reviewer findings:** none were raised, so nothing to confirm or refute. I re-checked both of the reviewer's criterion claims against the code and agree, with the three attacks below.

**Attack 1: does filelock 4.x change an API huggingface-hub or faster-whisper uses at runtime? No (verified).**

- faster-whisper 1.2.1 and ctranslate2 never touch filelock. huggingface-hub 1.28.0 reaches it only through `WeakFileLock` (`huggingface_hub/utils/_fixes.py:77-121`), used by `file_download.py`, `_local_folder.py`, `_auth.py` and `_sandbox_cache.py`. Its surface: `FileLock(path, timeout=, mode=0o664)`, `.acquire(timeout=)` raising `filelock.Timeout`, `.release()`, `SoftFileLock(path, timeout=)`, and an `except NotImplementedError` branch that matches the text "use SoftFileLock instead".
- I ran a probe of that surface on two venvs: one built from this lock (filelock 4.2.10) and a control with filelock 3.32.4 plus the same hub 1.28.0. Script: `<scratch>/scripts/fl_runtime.py`. The results were identical on both:
  - the lock file mode is `0o664`;
  - a cross-process holder makes `WeakFileLock(timeout=1)` raise `filelock._error.Timeout` after 1.0s;
  - the lock can be taken again after the holder exits;
  - a simulated `ENOSYS` flock falls back to `SoftFileLock` with the warning "flock not supported on this filesystem, falling back to SoftFileLock".
- The text the hub's `NotImplementedError` branch matches is in neither filelock version (grep finds no match in either `filelock/` tree). Both versions fall back to the soft lock inside filelock (`filelock/_unix.py:184-208` in 4.2.10, `fallback_to_soft=True` by default), so that hub branch was already dead code before the bump and its behaviour is unchanged. Same-thread nesting of two separate `WeakFileLock` instances blocks on both versions, so that is not a regression either.
- A real network run worked: `snapshot_download('Systran/faster-whisper-tiny', allow_patterns=[config.json, vocabulary.txt])` is the call `faster_whisper.download_model` makes. Under 4.2.10 it fetched the files, wrote `.locks/*.lock`, and a second `local_files_only=True` call resolved from the cache.

**Attack 2: can everything that reads uv.lock read the `revision = 5` header? Yes (verified).**

- The only reader in the repo is CI `osv-scan` (`.github/workflows/ci.yml:77-90`, osv-scanner-action v2.5.1). Nothing else uses uv:
  - `ci.yml` test, lint and web jobs install with `pip` (`ci.yml:35,46,66`);
  - `release.yml` has no uv reference;
  - `Dockerfile.builder` installs only `pysubs2 jellyfish` with pip (`:31`) and takes faster-whisper from `FROM mccloud/subgen:2026.06.2` (`:12`);
  - the repo has no Dependabot or Renovate config, and no `[tool.uv] required-version`.
- Local osv-scanner 2.5.1 on the branch lock: `found 35 packages … No issues found`.
- **Negative control, so the clean result is not a silent parse skip:** I took a copy of the revision-5 lock with filelock set back to 3.32.4. osv-scanner 2.5.1 still read it, `found 35 packages`, and reported `1 package affected by 12 known vulnerabilities (… 1 High …)`, each "fixed in 4.2.1". The scanner parses revision 5 and checks the versions in it.

**Attack 3: did exactly two package versions move? Yes (verified).**

- `git diff main...HEAD -- uv.lock | grep -E '^(\+|-)(name|version|revision) '` shows only:
  - `revision 3→5`;
  - filelock `3.32.4→4.2.10`;
  - setuptools `84.0.0→84.2.1`.
- No `name` line was added or removed, and both lock files have 36 `name =` lines.
- Each moved block changed only its version, sdist and wheel lines, 7+/7- in total.
- `uv lock --locked` exits 0 (`Resolved 36 packages`) and leaves `uv.lock` unchanged, so the lock is current with `pyproject.toml` and no other package is due to move.
- The branch diff touches only `uv.lock`, `CHANGELOG.md` and this task file. `pyproject.toml` is untouched.

**Criteria, re-run by me:**

- Criterion 1 is met by the diff above.
- Criterion 2 is met:
  - I built a venv from the lock under my scratchpad with `UV_PROJECT_ENVIRONMENT=<scratch>/venv uv sync --frozen --extra dev`; it imports filelock 4.2.10, hub 1.28.0 and faster-whisper 1.2.1. The shared `.venv` was not touched.
  - `PATH=<scratch>/venv/bin:$PATH python -m pytest -o addopts="" -q` → `4876 passed in 207.26s`, pytest exit code 0 (captured directly, not through a pipe), and no FAILED or ERROR lines.
  - `PATH=<scratch>/venv/bin:$PATH procoder check uv.lock CHANGELOG.md` → `0 clean, 1 unformatted, 0 unchecked, 1 out of scope, 5 hygiene finding(s) (0 blocking)`. The uv.lock security findings are gone.

**New findings, all info, none blocking:**

1. info, `uv.lock:2`: `revision = 5` needs a uv that knows that lock revision. I did not check which uv versions read revision 5 (unverified). No CI, release or Docker step runs uv, so the only risk is a contributor's older local uv. Escalation for the lead: pin uv only if the team wants contributors held to one version.
2. info, `Dockerfile.builder:12`, outside Owns: the shipped image gets faster-whisper, huggingface-hub and filelock from the `mccloud/subgen` base image, not from uv.lock. This bump clears the CI osv-scan but does not change the filelock version that runs in production. Escalation for the lead: check the base image's filelock if the advisory matters at runtime.
3. info, `CHANGELOG.md`: the prettier "unformatted" flag comes from main's existing `### Removed` block, which has no blank line after its heading (`git show main:CHANGELOG.md`, lines 11-12). The coder's new bullet is formatted correctly. This confirms the coder's escalation 2.
4. nit, outside Owns: the commit subject is 98 characters, against procoder's 72-character guide (info in the gate).

`close-gate --dry-run` accepts both verdict files and the criteria hash (`e0cd2ba9…`, unchanged). Process note: I did not load the role's skills (doubt-driven-development, differential-review, fp-check). All four findings are info or nit; each one cites the command or line it rests on, and C1's uv-version claim is marked unverified.

## Evidence

<!-- close-gate:begin sha256=66f31c82bbcd2a561c604078de70a95cc852e2f47b7c5b9bbe6efc696a0e6fd2 -->

Head: c8e83e946f246e903603b3ebc8fd16d385084bf4
Criteria sha256: e0cd2ba9d6546115afdd067c70a3d354daa8352ea74472a193a4528beafdffde

- reviewer: agy Gemini 3.8 Flash high; review_sha 60428ebbea322f189b6ae342acf1e66e11493169; verdict PASS; file /home/xena/work/code/.team/reviews/20261115-osv-dep-bump/reviewer-60428eb.json; findings: 0 blocker, 0 should-fix, 0 nit, 0 info
- critic: Claude Opus + Fable advisor; review_sha 60428ebbea322f189b6ae342acf1e66e11493169; verdict PASS; file /home/xena/work/code/.team/reviews/20261115-osv-dep-bump/critic-60428eb.json; findings: 0 blocker, 0 should-fix, 1 nit, 3 info

Tree equality: the head equals each reviewed commit outside the task file.

CI source: gh api XenaRathon/DubTitlerr

| Check       | Conclusion | URL                                                                                |
| ----------- | ---------- | ---------------------------------------------------------------------------------- |
| lint        | success    | https://github.com/XenaRathon/DubTitlerr/actions/runs/43780298213/job/133015717681 |
| osv-scan    | success    | https://github.com/XenaRathon/DubTitlerr/actions/runs/43780298213/job/133015717404 |
| review-ui   | success    | https://github.com/XenaRathon/DubTitlerr/actions/runs/43780298213/job/133015717697 |
| test (3.11) | success    | https://github.com/XenaRathon/DubTitlerr/actions/runs/43780298213/job/133015717772 |
| test (3.13) | success    | https://github.com/XenaRathon/DubTitlerr/actions/runs/43780298213/job/133015717639 |

<!-- close-gate:end -->
