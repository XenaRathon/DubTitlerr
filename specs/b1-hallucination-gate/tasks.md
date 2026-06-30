# Tasks — B1: Hallucination confidence-gate

> Persistent memory. New session: read `spec.md` + this file, check out the branch first.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/b1-hallucination-gate` (base: `main`)

Rules: ≤~1h each, dependency-ordered, verifiable, test-first, gates green (ruff · pytest),
1 task = 1 conventional commit.

## Tasks

- [ ] **T1 — Scaffold.** `hallucination.py` skeleton (BLOCKLIST + signatures + threshold
      constants), `tests/test_hallucination.py`. — done when: ruff clean, pytest collects.
- [ ] **T2 — `is_repetition` + `drop_reason`.** within-card loop detector; drop = blocklist ∨
      repetition ∨ (nsp>0.8 ∧ lp<-1.0). — done when: drop-signal unit tests pass.
- [ ] **T3 — `flag_reason`.** weaker single signal (mid nsp OR mid lp) → flag, not drop.
      — done when: flag-tier tests pass (flag set, drop None).
- [ ] **T4 — `collapse_runs`.** merge runs of ≥4 near-identical consecutive cards to one
      (first start, last end); ≤3 untouched. — done when: collapse tests pass.
- [ ] **T5 — Wire into `generate.py`.** drop via `drop_reason`, annotate conf via `flag_reason`,
      `collapse_runs` survivors; add `hallucination_silence_threshold=2.0`; extend the log
      (collapsed/flagged counts). — done when: ruff clean, full pytest green, generate.py parses.
- [ ] **T6 — `Dockerfile.builder` COPY `hallucination.py`.** — done when: grep shows it.

## Closing (the *close* phase — always keep last)

- [ ] **Integration verify (offline):** gate over real S19E16 cards → 0 real lines dropped.
- [ ] CI: add `hallucination.py` to the ruff scope — done when: pipeline green.
- [ ] Push `feat/b1-hallucination-gate`; merge to `main` (no PR). — done when: merged + pushed.

## Done
<move [x] tasks here, preserving the done criterion>
