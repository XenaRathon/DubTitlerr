# `AGENTS.md` documents the `~/.local/bin/osv-scanner` shim as host-local only.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-21 of `.procoder/specs/v0-2-0-hardening.md`: Close the osv-scanner/`pyproject.toml` extractor gap as a tracked, documented workaround: file/track the procoder issue, record the decision on whether the gate should scan `uv.lock` directly, and document the machine-local `~/.local/bin/osv-scanner` shim in `AGENTS.md` as host-local only, never a repo-portable fix.

Delivered by Task 23 of `.procoder/plans/v0-2-0-hardening.md` (sprint 015); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `AGENTS.md` documents the `~/.local/bin/osv-scanner` shim as host-local only.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
