# `ISSUE-phonetic-name-guard.md` has a status header naming `repair.invents_name()` and `repair.substitutes_a_vouched_name()` (`PHONETIC_MIN=0.75`) as the shipped resolution; no new fixture file is added for this item.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 012-provenance-and-policy-decoder-identity-in-words-json

## Description

Scope S-12 of `.procoder/specs/v0-2-0-hardening.md`: Close the phonetic-name-guard issue as resolved by a different design: `ISSUE-phonetic-name-guard.md` gets a status header pointing at `repair.invents_name()` (the glossary-membership half) and `repair.substitutes_a_vouched_name()` (the Jaro-Winkler half, `PHONETIC_MIN` default `0.75`).

Delivered by Task 13 of `.procoder/plans/v0-2-0-hardening.md` (sprint 012); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `ISSUE-phonetic-name-guard.md` has a status header naming `repair.invents_name()` and `repair.substitutes_a_vouched_name()` (`PHONETIC_MIN=0.75`) as the shipped resolution; no new fixture file is added for this item. `ISSUE-phonetic-name-guard.md` has a status header naming `repair.invents_name()` and `repair.substitutes_a_vouched_name()` (`PHONETIC_MIN=0.75`) as the shipped resolution; no new fixture file is added for this item.

## Evidence

`git grep -n 'Status: resolved differently' ISSUE-phonetic-name-guard.md` -> line 1 verified in commit 21e2656.
