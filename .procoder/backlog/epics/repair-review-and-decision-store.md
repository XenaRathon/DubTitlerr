# repair-review-and-decision-store

Status: done 2026-08-27
Created: 2026-08-27
Spec: repair-review-and-decision-store @ d7bbc368dd1a

## Description

The repair stage has no human rung. `accept_repair` states the acceptance bar in its own
docstring and then says nothing below enforces it -- measured, not feared: `factory -> needle`
and `VIVRA card -> Vivi card` both pass every gate, and so does dropping a word from
`the flame flame fruit`. The only enforcement is a person reading the lines, and today that
happens by hand-annotating a Markdown file an agent generated and an agent parsed back.

This epic delivers one coherent unit: the verdicts become software. Every accepted repair and
every gate rejection is queued with its evidence, a person settles it through a web UI, the
verdict is stored in a per-show artifact that ships in git the way the 15 glossaries already
do, and it is applied both to future runs and to episodes already generated.

It is one unit because none of the halves is worth shipping alone -- a queue nobody can act on
is the Markdown workflow again, and a store with nothing feeding it stays empty. Done means a
person can approve, reject or rewrite a repaired line in a browser and see it reach the episode
without an agent in the middle.

Plan: `.procoder/plans/repair-review-and-decision-store.md` (eight tasks).
Reviewed adversarially: `docs/Adversarial Reviews/GLM-2026-08-27-repair-review-and-decision-store.md`.
