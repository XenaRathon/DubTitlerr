# `AGENTS.md` documents the `~/.local/bin/osv-scanner` shim as host-local only.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 015-release-osv-scanner-gap-ledger-and-the-0-2-0-release

## Description

Scope S-21 of `.procoder/specs/v0-2-0-hardening.md`: Close the osv-scanner/`pyproject.toml` extractor gap as a tracked, documented workaround: file/track the procoder issue, record the decision on whether the gate should scan `uv.lock` directly, and document the machine-local `~/.local/bin/osv-scanner` shim in `AGENTS.md` as host-local only, never a repo-portable fix.

Delivered by Task 23 of `.procoder/plans/v0-2-0-hardening.md` (sprint 015); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `AGENTS.md` documents the `~/.local/bin/osv-scanner` shim as host-local only.

## Evidence

- `sed -n '91,95p' AGENTS.md` -> the sentence is present verbatim: "**`osv-scanner` on this
  maintainer's machine** is a host-local shim over the real binary (appends `--verbosity error`
  so procoder's gate can parse its output) — it is not part of this repository and a fresh clone
  needs nothing like it; CI scans `uv.lock` directly via `google/osv-scanner-action` instead
  (`.github/workflows/ci.yml`)."
- `AGENTS.md` is intentionally not tracked in this checkout: `git check-ignore -v AGENTS.md`
  -> `.git/info/exclude:11:AGENTS.md`. The same sentence _is_ tracked, propagated by
  `33101c3` (`chore(agents): resync per-editor rule files with AGENTS.md`) into the 11
  per-editor rule files: `.agents/rules/procoder.md`, `.clinerules/procoder.md`,
  `.cursor/rules/procoder.mdc`, `.github/copilot-instructions.md`, `.kilo/rules/procoder.md`,
  `.kilocode/rules/procoder.md`, `.kiro/steering/procoder.md`, `.qoder/rules/procoder.md`,
  `.roo/rules/procoder.md`, `.windsurf/rules/procoder.md`, `skills/procoder/SKILL.md`.
- Shipped in `33101c3` (the tracked per-editor-rule half) with the source file's own edit on top.
