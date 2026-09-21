# Ground truth: CI green, Compose committed with a safe auth default, hygiene ledger cleared, production snapshot taken, v0.2.0 scope frozen

Status: active
Created: 2026-09-21

## Goal

Get `main`'s CI green again (the `ruff check .` failure on `tests/test_gen_loop_set_e.py`
since 2026-09-05), commit `compose.yaml` and `.env.example` for the first time with a safe
review-server auth default (an explicitly empty `REVIEW_TOKEN` no longer silently disables
auth — only `REVIEW_AUTH=off` does), clear the untracked/modified hygiene ledger accumulated
since the last commit, take a read-only production snapshot of the live worker host, and
declare the v0.2.0 scope boundary in `CHANGELOG.md`. Delivers S-1 through S-5 of
`.procoder/specs/v0-2-0-hardening.md`.
