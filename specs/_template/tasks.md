# Tasks — <feature name>

> Persistent memory between sessions. When starting a new session, read this file + `spec.md`
> and check out the branch below before anything else.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `<type>/<kebab-case-description>` (base: `develop`)

Rules:
- Each task ≤ ~1h, ordered by dependency.
- Each task has a **verifiable** done criterion ("test X passes", not "improve Y").
- Before marking `[x]`: run the repo's gates — **lint, type-check, and tests** — all green.
- Before marking `[x]`: self-check the code against the coding principles in the
  `dev-lifecycle` checkpoint phase (**KISS, YAGNI, DRY, SoC**) and refactor if violated —
  autonomously, no user prompt.
- When marking `[x]`: make the **conventional commit** (in English) for the task —
  the *checkpoint* phase of the `dev-lifecycle` skill. **1 task = 1 commit.** Never accumulate.

## Tasks

- [ ] <small task> — done when: <verifiable criterion>
- [ ] <small task> — done when: <verifiable criterion>
- [ ] <small task> — done when: <verifiable criterion>

## Closing (the *close* phase of `dev-lifecycle` — always keep last)

- [ ] Evolve tests/CI to cover the changes (create CI if none exists) — done when: pipeline green
- [ ] Push the branch to origin — done when: branch published
- [ ] Draft the PR (Summary / Notable Decisions / Test Plan, in English) and **pause for approval** — done when: user approved title + description

## Done

<move tasks marked [x] here as you progress, preserving the done criterion>
