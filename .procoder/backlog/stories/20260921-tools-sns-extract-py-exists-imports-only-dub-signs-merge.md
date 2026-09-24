# `tools/sns_extract.py` exists, imports only `dub_signs_merge.keep_event` from the pipeline, and implements `off_default_position(ev, play_res_y)`.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 014-measurement-timing-compare-t12-on-three-shows-queue-publish

## Description

Scope S-20 of `.procoder/specs/v0-2-0-hardening.md`: Build a read-only S&S (signs & songs) extract-only prototype, `tools/sns_extract.py`: standalone, imports `dub_signs_merge.keep_event` and adds a numeric heuristic `off_default_position(ev, play_res_y)`.

Delivered by Task 22 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `tools/sns_extract.py` exists, imports only `dub_signs_merge.keep_event` from the pipeline, and implements `off_default_position(ev, play_res_y)`.

## Evidence

- `tools/sns_extract.py` exists (117 lines, added by `d604337`). Its import block is `import argparse`, `import os`, `import sys`, `import pysubs2`, and one pipeline import: line 35 `import dub_signs_merge as dsm`.
- `grep -n "dsm\." tools/sns_extract.py` → exactly one hit, line 66 `if dsm.keep_event(ev):`. `keep_event` is the only name reached through the pipeline module; the module alias itself is the whole import surface.
- `grep -n "^def \|^class " tools/sns_extract.py` → line 45 `def off_default_position(ev: pysubs2.SSAEvent, play_res_y: int) -> bool:`; also `classify_event` (line 60) and `extract(path, out_dir)` (line 71). `off_default_position` is package-local and does not call back into `dub_signs_merge`.
- Shipped in `d604337`.
