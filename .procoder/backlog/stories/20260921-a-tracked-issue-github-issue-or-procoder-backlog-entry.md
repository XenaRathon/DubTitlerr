# A tracked issue (GitHub issue or `.procoder/backlog` entry) records the osv-scanner/`pyproject.toml` extractor gap, with a recorded decision on scanning `uv.lock` directly.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -
Carried: 015-release-osv-scanner-gap-ledger-and-the-0-2-0-release — gh issue create --repo azrtydxb/procoder was never executed: #293 and #177 are the only lockfile-ish upstream hits and neither is the extractor gap, gh search issues --author @me --created >=2026-09-19 is empty, and XenaRathon/DubTitlerr has no issues at all (open_issues_count 0), yet .github/workflows/ci.yml cites an upstream issue that does not exist; the only backlog record is the 2026-08-27 story that mentions the gap in passing, predating S-21

## Description

Scope S-21 of `.procoder/specs/v0-2-0-hardening.md`: Close the osv-scanner/`pyproject.toml` extractor gap as a tracked, documented workaround: file/track the procoder issue, record the decision on whether the gate should scan `uv.lock` directly, and document the machine-local `~/.local/bin/osv-scanner` shim in `AGENTS.md` as host-local only, never a repo-portable fix.

Delivered by Task 23 of `.procoder/plans/v0-2-0-hardening.md` (sprint 015); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A tracked issue (GitHub issue or `.procoder/backlog` entry) records the osv-scanner/`pyproject.toml` extractor gap, with a recorded decision on scanning `uv.lock` directly.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
