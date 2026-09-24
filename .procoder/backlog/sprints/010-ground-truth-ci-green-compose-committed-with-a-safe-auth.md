# Ground truth: CI green, Compose committed with a safe auth default, hygiene ledger cleared, production snapshot taken, v0.2.0 scope frozen

Status: closed 2026-09-21
Created: 2026-09-21

## Goal

Get `main`'s CI green again (the `ruff check .` failure on `tests/test_gen_loop_set_e.py`
since 2026-09-05), commit `compose.yaml` and `.env.example` for the first time with a safe
review-server auth default (an explicitly empty `REVIEW_TOKEN` no longer silently disables
auth — only `REVIEW_AUTH=off` does), clear the untracked/modified hygiene ledger accumulated
since the last commit, take a read-only production snapshot of the live worker host, and
declare the v0.2.0 scope boundary in `CHANGELOG.md`. Delivers S-1 through S-5 of
`.procoder/specs/v0-2-0-hardening.md`.

## Result

committed: 9
done: 9 (20260921-a-vault-note-exists-homelab-projects-dubtitlerr-date, 20260921-changelog-md-contains-a-0-2-0-unreleased-heading-listing, 20260921-git-ls-files-compose-yaml-env-example-lists-both-currently, 20260921-git-merge-base-is-ancestor-github-main-head-succeeds-and, 20260921-git-status-porcelain-shows-no-untracked-entry-for-craftsman, 20260921-python3-m-pytest-tests-test-review-apply-py-q-passes, 20260921-readme-md-s-review-server-section-and-security-md-both, 20260921-ruff-check-tests-test-gen-loop-set-e-py-prints-all-checks, 20260921-with-review-token-set-the-compose-default-shape-review)
carried: 0

## Retro

<!-- What slowed us down this sprint. -->

Owner/live Task 4 required SSH checks on three production hosts (vm102, OG/fasc, 3200g-docker) — the vault's host notes were stale (showed dubtitle-builder as exited on 3200g-docker but not on vm102, and OG's note didn't mention DubTitlerr at all). The actual worker was confirmed on vm102 (1050 Ti for Whisper v3 large-turbo), repair model on OG (1060 for qwen3-4b-instruct). The container had crashed on vm102 ~6.5h before the snapshot (exit 137, clean SIGTERM, no auto-restart). All docker exec checks failed because container was stopped. This host-confidence gap is the single biggest slowdown — next sprint, verify host state first via a quick docker ps before assuming any note is current.

<!-- What we change next sprint because of it. -->

Add a "host verification" micro-step at sprint start: run `docker ps --filter name=dubtitle-builder` on the expected worker host before any other work. If stopped, note it and proceed; don't let stale vault notes block or mislead.

<!-- One adaptation from this sprint worth keeping. -->

The owner directive to merge the PR into main (at 08fa1bef) rather than leave it open for manual merge saved a round-trip — when the plan says "leave for owner to merge by hand" but the owner explicitly directs merge, follow the owner. The retro capture format itself (what slowed / what changes / what keeps) is a good template for future sprints.
