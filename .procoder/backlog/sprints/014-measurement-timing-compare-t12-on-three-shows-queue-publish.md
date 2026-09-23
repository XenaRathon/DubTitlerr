# Measurement: timing-compare T12 on three shows, queue/publish and storage/host checklists, FFMPEG_TIMEOUT default, S&S prototype

Status: closed 2026-09-23
Created: 2026-09-23

## Goal

Measure before building: prove the timing-compare pipeline on real media (T12), check the
queue/publish path and the storage/host assumptions against a live host, raise
`FFMPEG_TIMEOUT`'s default to survive a slow NAS read, and prototype an S&S extract-only
tool that stays unwired from the merge path.

## Result

committed: 8
done: 5 (20260921-a-false-positive-inventory-file-exists-under-docs-beta, 20260921-programmatic-pysubs2-ssaevent-fixtures-covering-a-genuine, 20260921-python3-c-import-generate-assert-generate-ffmpeg-timeout, 20260921-specs-timing-compare-tasks-md-shows-t1-t11-checked-and-no, 20260921-tools-sns-extract-py-exists-imports-only-dub-signs-merge)
carried: 3 (20260921-a-vault-note-records-systemd-analyze-verify-output-the, 20260921-a-vault-note-records-the-confirmed-single-active-worker, 20260921-tools-timing-compare-py-produces-docs-timing-compare-date)

## Retro

What slowed us down this sprint: this was the first sprint in this repo whose owner/live half (plan Tasks 18, 20 and 21) had no host access at all, so every measurement promise in the sprint goal went unmeasured. `docs/timing-compare/` does not exist, so no `<date>-phase0-report.json` and no `<date>-phase0-go-no-go.md` were produced, and `specs/timing-compare/tasks.md:87` (T12) is still an unchecked box because the decision it encodes is the owner's, not the machine's. The two vault notes this sprint promised — the queue/publish verification under S-18 and the storage/host checklist under S-19 — were likewise never written, because each needs live output (`systemd-analyze verify`, publish-timer status, a deployed-order-file vs `watch_queue.py --dry-run` diff; `docker ps` and `nvidia-smi` on the worker host) that only a login to the box can produce. Three of eight stories therefore had to be carried rather than closed, and the sprint's most consequential item — proving the timing-compare pipeline against real media — is the one it did not do.

The structural snag underneath that: S-17's scope split into two stories with different verifiability, and only the documentation half was closable this pass. `specs/timing-compare/tasks.md` T1–T11 came out reconciled and correct (`f75bb55`), but the very same scope's measurement story could not be; T12 stayed `[ ]` and the sibling carried. A scope that mixes "fix the prose" with "run the pipeline on three named shows" will always split like this when the host is unreachable, and reading it as one unit hides that only half of it landed. S-19 split the same way for the same reason: Task 21's code half (the `FFMPEG_TIMEOUT` default of 1800, its `docs/wiki/Reference.md:95` row and its `tests/test_generate.py:1736` regression assertion) shipped in `81f8f32` and closed as its own story, while the owner/live half — confirming one active worker, mergerfs `pfrd` persistence, the continuous `sdc1` writer, and `llama-embed` back on the 1050 Ti — carried open. Splitting those stories on the verifiability boundary, rather than after the fact, is what the next sprint should do from the start.

What we change next sprint because of it: do not open a sprint containing owner/live tasks without confirming host access first. The plan's own line 39 predicted Tasks 18, 20 and 21 "can run in parallel with 011–013 whenever the owner is at a host" — that did not happen in this pass, and the sprint went to closure with its measurement goal unfulfilled as a direct result. The concrete change is to treat `docs/timing-compare/*-phase0-go-no-go.md` as the blocking artifact it is: it gates `specs/timing-compare/tasks.md:87` (T12), it needs a human go/no-go written down, and until it exists the timing-compare work is unmeasured no matter how green the unit suite is. Raise that gap with the owner as the first item of the next pass rather than re-carrying it a third time.

One adaptation from this sprint worth keeping: when a sprint's remaining work is genuinely split between "closable now" and "needs a live host", close the closable half on its own evidence and carry the rest with the reason spelled out — do not let one unreachable story hold an otherwise-verified one open, and do not close a measurement story on bookkeeping. Every one of the five closes here names the commit that carries it and the exact command that proves it; every one of the three carries names what is missing and why the agent cannot produce it. That split is the honest shape, and it is worth repeating.
