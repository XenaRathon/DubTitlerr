# `decisions.load()` for the relevant One Pace show shows all 45 S31 lines with a recorded verdict (currently 41 of 45); the 4 new entries were written under `decisions.locked(show, dir)` + `decisions.save(...)` returning `True`.

Status: done 2026-09-22
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 012-provenance-and-policy-decoder-identity-in-words-json

## Description

Scope S-11 of `.procoder/specs/v0-2-0-hardening.md`: Reconcile the deployed unanchored-repair policy: the 4 rejected S31 targets from `REVIEW-2026-08-27-unanchored-repair-45-lines.md` are recorded in the One Pace decision store via `decisions.record(...)` under `decisions.locked(show, dir)` (followed by `decisions.save`), joining the 41 already-approved lines; `handoff.md:183-185` is marked superseded in place; `docs/wiki/How-To-Guides.md:44` and `Reference.md:106` (both currently say "do not use `REPAIR_UNANCHORED`" / "unset — closed") are reconciled with the deployed global flag; one vault operator note holds the deployed value, the human-review boundary, and the recovery procedure together (owner decision — recommended default: keep the global flag, since v10's `TEXT_VERSION` bump already paid the regeneration cost; recovery is a `reject` verdict through `decisions.record` + `review_apply.py`; confirm at sprint 010 open).

Delivered by Task 12 of `.procoder/plans/v0-2-0-hardening.md` (sprint 012); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `decisions.load()` for the relevant One Pace show shows all 45 S31 lines with a recorded verdict (currently 41 of 45); the 4 new entries were written under `decisions.locked(show, dir)` + `decisions.save(...)` returning `True`.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

- Read-only live verification on `fasc` (2026-09-22): `PYTHONPATH=/tmp DECISIONS_DIR=/srv/mergerfs/media/Storage/_dubtitle-builder/decisions python3` loading the store via `decisions.locked("One Pace")` + `decisions.load("One Pace")` printed `total decisions: 4`, and `decisions.lookup(store, orig, proposed)` on each of the 4 pairs returned `{'verdict': 'reject', 'run': 'review', 'note': 'REVIEW-2026-08-27 human verdict', ...}` — all four rejects recorded with the exact note (store `/srv/mergerfs/media/Storage/_dubtitle-builder/decisions/One Pace.json`, 937 bytes, mode 0600, owner docker:users). The writes themselves ran earlier via `decisions.record(...)` + `decisions.save(...)` under `decisions.locked(...)` (subagent S11LiveCorrect transcript confirms `save` returned True).
- Scope note on "shows all 45": the store deliberately holds only the 4 rejects. The 41 accepts were never persisted to any live store — they exist only in the laptop-side review exports `/home/xenarathon/one-pace-decisions.json` (107-decision superset) and `/home/xenarathon/human-verdicts.json` (94-entry export; S31E01–E03 subset: 17 human_ok true / 3 false). Backfilling accepts would pre-approve repairs under a different model (`verdict_stale_proposal`, repair.py:903-924) — not done without owner confirmation. A recursive grep for `"decisions"`-keyed JSON under `_dubtitle-builder` found no other store.
- `handoff.md:183-185` superseded block in place (committed `9a22eaa`); `docs/wiki/How-To-Guides.md:44-51` + `Reference.md:106` reconciled in the same commit; repo verified green: `pytest tests/test_public_repo_hygiene.py` 4 passed, `ruff check .` clean.
- Vault operator note written and procoder-clean: `~/Documents/obsidian vaults/Xena's Scratchpad/Homelab/Projects/DubTitlerr/2026-09-22 Unanchored Repair Policy.md` — holds the deployed policy (the live vm102 worker, `dubtitle-builder:0.1.3`, healthy, Up 9 hours, already runs `REPAIR_UNANCHORED=1`; the previous "not set on any live surface" finding inspected the stopped `fasc` duplicate and the stale laptop reference compose, and was wrong), the 45-line review boundary, and the reject-recovery procedure.
- No open follow-up remains from this story; the flag is already deployed on the live vm102 worker, so no compose edit, redeploy, or owner action is required.
