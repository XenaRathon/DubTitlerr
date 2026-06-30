# Plan — A1: Sentence-split & re-timing reflow

> Written after `spec.md` approval. Approving this plan triggers the kickoff
> (branch creation) phase of `dev-lifecycle`.

## Branch and delivery

- **Branch:** `feat/a1-reflow-timing` (base: **`main`** — this repo has no `develop`;
  dev-lifecycle's develop-based flow is adapted to `main`).
- **PR slicing:** single PR. One self-contained step (~6 tasks).

## Technical approach

Extract the reflow as a **pure, dependency-free module** `reflow.py` so it can be
unit-tested without CUDA/whisper, then wire it into `generate.py`. `reflow.py`
takes plain word/segment dicts and returns finished cards; `generate.py` only
adapts whisper's objects into those dicts, calls reflow, and writes the `.srt` +
per-card `conf.json`. This keeps the segmentation/timing logic (the part with all
the rules) isolated and 100% testable, and leaves `generate.py`'s crash-resilience,
idempotency, and `OUTPUT_ROOT` behavior untouched. Built test-first (TDD): each
acceptance rule gets a failing unit test before its implementation.

## Affected files (by layer)

| Layer | File | Change |
|---|---|---|
| Core logic (new) | `reflow.py` | New stdlib-only module. `reflow(words, segments) -> list[Card]` plus helpers: `split_spans` (>0.5 s gap), `segment_span` (sentence → largest-pause → clause → word-wrap), `wrap_balance` (≤2 lines ≤42, balance), `time_cards` (start=onset, extend end into trailing silence, ≥2-frame gap, 0.83–7 s), `card_confidence` (mean `ln(prob)`, clamp `1e-4`; max overlapping `no_speech_prob`). |
| Orchestration | `generate.py` | In `process()`: build the word list from `segment.words` capturing `word.probability` + source-segment index; call `reflow(...)`; write `.srt` and per-card `conf.json` from the returned cards. Keep per-card `BLOCKLIST` drop + existing `correct()`. Extend the summary log with card count, max duration, and any acceptance-rule violations (verification aid). |
| Image | `Dockerfile.builder` | `COPY reflow.py` into `/app` so the container ships the new module. |
| Tests (new) | `tests/test_reflow.py` | pytest units for every rule + edge case (table below). |
| Dev config (new) | `pyproject.toml` | Minimal `[tool.pytest]`/`[tool.ruff]` config (repo has none today). No runtime deps added. |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| Reflow changes the `.srt` for **all** shows; a bad rule regresses good episodes. | Comprehensive pure unit tests; before container rollout, re-run `generate.py` on `S19E16` (dialogue) + one S15 karaoke ep and eyeball against the acceptance criteria. Ship only after both pass. |
| `word.probability`/timestamps missing or `None` on some words. | Interpolate timing from neighbors/segment bounds; clamp prob to `1e-4` before `ln`. Covered by an edge-case test. |
| Already-transcribed episodes won't show the new reflow (idempotency skips existing `.srt`). | Operational: to re-process, delete the episode's `.srt`+`.conf.json` (or a show's) and let the loop re-run. Documented in the PR; not a code change. |
| New module not baked into the image → container `ImportError`. | `Dockerfile.builder` COPY + rebuild/redeploy is part of the rollout checklist, not the merge. |

## Rollback and reversibility

- Fully reversible: revert the PR and rebuild the image. No data migration, no
  schema. Existing sidecars are unaffected on disk; only future transcriptions change.

## Testing strategy

- **Unit (pytest, the bulk):** `reflow.py` is pure → exhaustive table-driven tests:

  | Rule under test | Assertion |
  |---|---|
  | Gap > 0.5 s | words across the gap land in different cards |
  | Sentence split | `. ! ? …` ends a card |
  | Overflow > 2×42 | breaks by largest pause, then clause, then wrap (order verified) |
  | Wrap/balance | no line > 42; ≤ 2 lines; lines balanced |
  | Start pinning | card.start == first word onset (never earlier) |
  | Hold time | short/dense card extends END into trailing silence, capped 7 s, start fixed |
  | Gap enforcement | ≥ 2-frame gap; no overlap with next card |
  | Confidence | avg_logprob == mean ln(prob) (clamped); no_speech_prob == max overlap |
  | Edge: None timestamp | interpolated, no crash |
  | Edge: empty/blank card | dropped from both `.srt` and `conf.json` |
  | Edge: >7 s no-gap no-punct sentence | still split to ≤7 s & ≤2 lines |

- **Integration (manual, on server):** re-run `generate.py` on `S19E16` + one S15
  karaoke ep in the container; confirm zero cards > 7 s and the mid-sentence
  cross-boundary breaks are gone.
- **Coverage target:** ≥ 90 % on `reflow.py` (the critical logic).

## Observability / performance

- Not an LLM step. Reflow is O(words), negligible vs whisper.
- `generate.py` log line extended to: `cards=N max_dur=Xs over_cps=K violations=…`
  so a run is self-verifying against the acceptance criteria.
