# Plan — B1: Hallucination confidence-gate

> After spec approval. Approving this triggers kickoff (branch).

## Branch and delivery

- **Branch:** `feat/b1-hallucination-gate` (base: `main`).
- **PR slicing:** single, direct-merge to main (build flow, no PR).

## Technical approach

New pure stdlib module `hallucination.py` (mirrors reflow/glossary): houses the extended
`BLOCKLIST`, repetition detection, the drop/flag classifiers, and the consecutive-run
collapse — all operating on plain card dicts, so fully unit-testable without CUDA. `generate.py`
applies it after reflow + C1 correction (drop → flag → collapse), and adds the one decode-time
param. Test-first.

## Affected files (by layer)

| Layer | File | Change |
|---|---|---|
| Core (new) | `hallucination.py` | `BLOCKLIST` (extended), `is_repetition(text)`, `drop_reason(card)`, `flag_reason(card)`, `collapse_runs(cards)`. Constants for thresholds (NSP 0.8, LP -1.0, run ≥4). |
| Orchestration | `generate.py` | Replace inline `BLOCKLIST` drop with `hallucination.drop_reason`; annotate kept-but-suspect conf rows via `flag_reason`; `collapse_runs` over survivors; add `hallucination_silence_threshold=2.0` to `WMODEL.transcribe`. |
| Image | `Dockerfile.builder` | `COPY hallucination.py`. |
| Tests (new) | `tests/test_hallucination.py` | Table-driven: each drop signal, flag tier, within/across repetition, run-collapse threshold, "don't drop real / ≤3 survive". |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| Over-dropping real low-conf dialogue | Conservative multi-signal drop; single weak signal only flags. Regression: 0 drops on clean S19E16. |
| Collapsing a deliberate ≤3 repeat | Run threshold ≥4; unit-tested. |
| `hallucination_silence_threshold` removes quiet dialogue in pauses | Modest 2.0s; decode-time, validated on a sample at rollout; reversible env. |
| Repetition detector false-positive on chants/stutters | Require the repeat to dominate the card (high coverage); tested with emphatic-repeat cases. |

## Rollback and reversibility

- Revert PR + rebuild image. Pure logic + one decode param; no data/schema. The transcribe
  param is env-overridable.

## Testing strategy

- **Unit (pytest), the bulk — `hallucination.py`:**
  | Rule | Assertion |
  |---|---|
  | blocklist drop | a known phrase → drop_reason == "blocklist" |
  | within-card repetition | "go go go go go" → drop_reason == "repetition" |
  | music combo | nsp 0.9 + lp -1.5 → "music"; nsp 0.9 alone → not dropped (flag) |
  | flag tier | mid nsp OR mid lp → flag_reason set, drop_reason None |
  | run collapse ≥4 | 5 identical → 1 (start of first, end of last); 3 identical → unchanged |
  | near-identical | case/punct-different dups counted in a run |
  | real line safe | normal varied line → no drop, no flag |
- **Integration (offline):** run the gate over real S19E16 cards (raw.json → reflow → correct →
  gate); confirm 0 real lines dropped. Decode param validated on a sample at rollout.
- Coverage ≥90% on `hallucination.py`.

## Observability

- `generate.py` summary log already reports `dropped-hallucination`; extend with collapsed-run
  count and flagged count so a run is self-describing.
