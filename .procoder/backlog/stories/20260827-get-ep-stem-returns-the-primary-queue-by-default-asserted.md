# `GET /ep/<stem>` returns the primary queue by default -- asserted on the ABSENCE of `no_reference` and `llm_empty` entries, since `unresolved.pending()` applies no stage filter of its own and a server returning everything would otherwise pass -- and the full walk with `?all=1`; `POST /decide` persists through `decisions.py` and the entry becomes resolved; `POST /apply/<stem>` invokes the write-back of Task 5. Handlers are tested directly, no socket.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 007-task-7-the-review-server-plus-the-orphan-entry-fix-the

## Description

Task 7. The owner asked for the judgement-worthy lines by default with a full deep-dive available. Done
means the default view carries neither `no_reference` nor `llm_empty` and `?all=1` includes them.

Asserted on the absence, for the same reason as the queue filter: `unresolved.pending()` filters
nothing on its own.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `GET /ep/<stem>` returns the primary queue by default -- asserted on the ABSENCE of `no_reference` and `llm_empty` entries, since `unresolved.pending()` applies no stage filter of its own and a server returning everything would otherwise pass -- and the full walk with `?all=1`; `POST /decide` persists through `decisions.py` and the entry becomes resolved; `POST /apply/<stem>` invokes the write-back of Task 5. Handlers are tested directly, no socket.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
