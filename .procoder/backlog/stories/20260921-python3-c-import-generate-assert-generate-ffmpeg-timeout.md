# `python3 -c "import generate; assert generate.FFMPEG_TIMEOUT == 1800"` passes with `FFMPEG_TIMEOUT` unset in the environment; the README/Reference table and `generate.py:32-33`'s comment both state the new default.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 014-measurement-timing-compare-t12-on-three-shows-queue-publish

## Description

Scope S-19 of `.procoder/specs/v0-2-0-hardening.md`: Write a storage/host checklist note: the single active worker confirmed (not assumed), mergerfs `pfrd` persistence through the OMV-managed config, the unexplained continuous writer on `sdc1`, and `llama-embed` confirmed back on the 1050 Ti after any heavy run.

Delivered by Task 21 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `python3 -c "import generate; assert generate.FFMPEG_TIMEOUT == 1800"` passes with `FFMPEG_TIMEOUT` unset in the environment; the README/Reference table and `generate.py:32-33`'s comment both state the new default.

## Evidence

- `env -u FFMPEG_TIMEOUT .venv/bin/python -c "import generate; assert generate.FFMPEG_TIMEOUT == 1800; print('OK', generate.FFMPEG_TIMEOUT)"` → `OK 1800`. Run under the repo venv (`.venv/bin/python`), the interpreter where `generate`'s imports resolve; `env -u` guarantees the variable is unset.
- `generate.py:119` → `FFMPEG_TIMEOUT = int(os.environ.get("FFMPEG_TIMEOUT", "1800"))`; `generate.py:32` docstring line → `FFMPEG_TIMEOUT  default 1800  (seconds; the wav decode in extract_wav. Raised from …)`.
- `grep -n FFMPEG_TIMEOUT docs/wiki/Reference.md` → line 95 `| \`FFMPEG_TIMEOUT\` / \`FFPROBE_TIMEOUT\` | \`1800\` / \`60\` | Seconds |`. The "README/Reference table" the criterion names is the Reference env table; this repo's README carries no environment-variable table (`grep -n "FFMPEG_TIMEOUT\|FFPROBE_TIMEOUT" README.md` → no match).
- `grep -n FFMPEG_TIMEOUT tests/test_generate.py` → line 1736 `assert generate.FFMPEG_TIMEOUT == 1800`, with line 1708 monkeypatching it to 1234 so the env-override path stays covered.
- Shipped in `81f8f32` (`docs/wiki/Reference.md`, `generate.py`, `tests/test_generate.py`).
