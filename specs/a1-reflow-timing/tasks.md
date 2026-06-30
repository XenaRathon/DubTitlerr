# Tasks — A1: Sentence-split & re-timing reflow

> Persistent memory between sessions. New session: read `spec.md` + this file and
> check out the branch below before anything else.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/a1-reflow-timing` (base: `main`)

Rules: each task ≤ ~1h, dependency-ordered, verifiable done criterion. Built
**test-first**. Before `[x]`: gates green (ruff · pytest). 1 task = 1 conventional commit.

## Tasks

- [ ] **T1 — Scaffold + contracts.** Add `pyproject.toml` (`[tool.pytest]`, `[tool.ruff]`),
      `tests/`, and `reflow.py` skeleton: `Card` shape, `reflow(words, segments)` +
      helper signatures (docstringed, `NotImplementedError`). Constants for the
      Netflix profile (42, 2, 17 cps, 0.83, 7.0, 0.5 gap, 2-frame=0.083).
      — done when: `ruff check` clean and `pytest` collects (skeleton tests xfail/skip).

- [ ] **T2 — `split_spans`.** Test-first: words split into spans wherever inter-word
      gap > 0.5 s. — done when: gap-split unit tests pass.

- [ ] **T3 — `segment_span`.** Sentence split (`. ! ? …`); overflow (>2×42 or >7 s)
      cut order = largest internal pause → clause `, ; :` near midpoint → word-wrap.
      — done when: segmentation-order + overflow unit tests pass.

- [ ] **T4 — `wrap_balance`.** Each card text → ≤2 lines, ≤42/line, balanced.
      — done when: wrap/balance unit tests pass (no line >42, ≤2 lines, balance check).

- [ ] **T5 — `time_cards`.** start = first-word onset (pinned); extend END into trailing
      silence to satisfy ≥0.83 s and ≤17 cps, capped 7 s; enforce ≥2-frame gap (no overlap).
      — done when: timing unit tests pass (start-pin, hold-time, cap, gap).

- [ ] **T6 — `card_confidence` + assemble `reflow()` + edges.** Per-card avg_logprob =
      mean `ln(max(prob,1e-4))`; no_speech_prob = max over overlapping segments. Tie the
      pipeline together; handle `None` timestamps (interpolate) and empty cards (drop).
      — done when: confidence + edge-case tests pass; coverage ≥90% on `reflow.py`.

- [ ] **T7 — Wire into `generate.py`.** Build word dicts from `segment.words`
      (capture `probability` + source-seg index); call `reflow`; write `.srt` + per-card
      `conf.json`; keep per-card `BLOCKLIST` + `correct()`; extend summary log
      (`cards= max_dur= over_cps= violations=`). Preserve `.fail`/idempotency/`OUTPUT_ROOT`.
      — done when: `ruff` clean, full pytest green, `python -c "import ast; ast.parse(open('generate.py').read())"` ok.

- [ ] **T8 — `Dockerfile.builder` COPY `reflow.py`.** — done when: grep shows the new
      module copied into `/app`.

## Closing (the *close* phase of `dev-lifecycle` — always keep last)

- [ ] **Integration verify (server, no rebuild):** `docker cp` updated `reflow.py` +
      `generate.py` into the live `dubtitle-builder` container, delete `S19E16`'s
      `.srt`+`.conf.json`, run `generate.py` on it + one S15 karaoke ep; confirm zero
      cards >7 s and the mid-sentence cross-boundary breaks are gone. — done when: both eyeball-pass.
- [ ] Ensure CI runs ruff + pytest (create `.github`/Forgejo workflow if none) — done when: pipeline green.
- [ ] Push `feat/a1-reflow-timing` to origin — done when: branch published.
- [ ] Draft PR (Summary / Notable Decisions / Test Plan, English) and **pause for approval** — done when: user approved.

## Done

<move [x] tasks here, preserving the done criterion>
