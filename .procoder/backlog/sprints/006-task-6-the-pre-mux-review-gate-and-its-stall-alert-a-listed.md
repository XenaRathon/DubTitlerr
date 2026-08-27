# Task 6: the pre-mux review gate and its stall alert -- a listed show holds an episode with pending accepted repairs, and a hold is never auto-released

Status: active
Created: 2026-08-27

## Goal

An optional, per-show hold. For a show named in `REVIEW_GATE_SHOWS`, `mux.py` skips any
episode that still has pending `repair_applied` entries -- the repairs `accept_repair`
admitted without anything checking their meaning. Unlisted shows behave exactly as today,
which is the default for every install.

The hold is NEVER auto-released. Releasing unreviewed repairs on a timer is the failure
this entire spec exists to prevent, so `REVIEW_GATE_STALE_DAYS` buys a loud log line and a
count in the sweep summary, and nothing else. An alert that becomes a release is worse than
no alert, because it looks like supervision.

## On-disk state at gate time, verified before design (sprint 005 lesson)

- `<stem>.dubtitles.unresolved.jsonl` SURVIVES mux: `mux.py:367-371` removes only the
  `.ass` and `.srt`. The queue is therefore readable at gate time and afterwards.
- It is NOT in `generate.SIDECAR_SUFFIXES`, so `park_stale_sidecars` does not park it on a
  version bump -- entries outlive a regeneration. Noted as a real property, not assumed.
- `repair.py` runs immediately before `mux.py` in the same `merge_pass.sh` pass
  (merge_pass.sh:58-66), so on a first generation the queue already holds this run's
  accepted repairs when the gate reads it. A listed show therefore holds on its very first
  pass, which is the point of an opt-in gate.
- The queue carries no timestamp per entry, so the sidecar's mtime is the only staleness
  signal available. That is an approximation and must be documented as one.

## Carried from the sprint 005 retro

Before the first test, write down the on-disk state of a real instance and verify each file
against the code that creates and deletes it (done above). And when a finding contradicts
the spec, trace it end to end before reporting it as established.

## Retro

What slowed us down: I traced a suspicion, got the answer wrong, and reported the wrong
answer as verified. I suspected the stall alert could never fire because repair.py refreshes
the queue file's mtime, went looking, read `dub_signs_merge.py` from line 160, saw
`base.save(out_ass)` and concluded the .ass always exists so repair never re-runs. The early
`return "no-signs", 0, 0` is at line 126 -- thirty-four lines ABOVE where I started reading.
My suspicion had been right; my check was wrong; and I told the owner the suspicion was
wrong. The review caught it.

That is the second consecutive sprint where reading a fragment of a function produced a
confident false conclusion (sprint 005: the on-disk state of a muxed episode). Both times
the missing evidence was above or beside what I read, and both times the conclusion was
stated rather than hedged.

What we change next sprint: when checking a control-flow claim about a function, read the
function from its `def` line, not from the region that looks relevant. An early return is
invisible from below, and it is exactly what a control-flow question is about. If a function
is too long to read whole, that is a finding in itself, not a licence to skim.

Adaptation worth keeping: the gate exposed a defect that predates it. repair.py re-queueing
on every sweep was always true; nothing noticed because episodes were muxed promptly and the
queue was never read twice. Holding an episode turned a harmless re-append into unbounded
growth AND disarmed the alert meant to surface it. A feature that makes an existing state
last longer will find every bug that assumed the state was transient -- worth asking
directly, of any new hold/pause/gate: what did the old code assume would end soon?
