# `specs/timing-compare/tasks.md` shows T1–T11 checked and no longer references the nonexistent `feat/timing-compare` branch.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 014-measurement-timing-compare-t12-on-three-shows-queue-publish

## Description

Scope S-17 of `.procoder/specs/v0-2-0-hardening.md`: Run the T12 real-media leg of timing-compare on 3 selected shows (one fansub dialogue track, one signs-only, one One Pace episode), producing a report and a go/no-go note under `docs/timing-compare/`.

Delivered by Task 18 and 19 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `specs/timing-compare/tasks.md` shows T1–T11 checked and no longer references the nonexistent `feat/timing-compare` branch.

## Evidence

- `grep -n '^\- \[' specs/timing-compare/tasks.md` → T1–T11 all `[x]` (lines 17, 25, 33, 37, 45, 51, 55, 63, 67, 75, 82); the only remaining `[ ]` boxes are T12 (line 87) and the CI/gates line (97), neither of which this criterion claims.
- `grep -n "feat/timing-compare" specs/timing-compare/tasks.md` → three occurrences, all negations: line 8 "(no `feat/timing-compare` branch was ever created; `git branch -a` confirms this).", line 98 the struck-through push step marked N/A, line 99 the struck-through PR step. No live instruction to create or push that branch remains.
- `git grep -c 'feat/timing-compare'` → remaining matches are only `.procoder/` plan/spec/story files, `specs/timing-compare/REVIEW.md`, `specs/timing-compare/plan.md` (historical planning prose) and `tasks.md` itself; no source, script, or task step depends on that branch.
- Shipped in `f75bb55` (`specs/timing-compare/tasks.md | 51+/18-`).
