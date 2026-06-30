# specs/ — Spec-Driven Flow

Every non-trivial feature goes through three artifacts before becoming code. Each feature
lives in `specs/<feature-name>/` with the three files below, copied from `_template/`.

## The golden rule

```
spec.md approved  →  plan.md approved (declares the branch)  →  tasks.md  →
kickoff (branch)  →  code (1 commit per task)  →  close (tests/CI → push → PR draft, pause)
```

Never jump straight to implementation. Each stage advances only once the previous one is
approved. The git mechanics of kickoff / checkpoint / close live in the `dev-lifecycle` skill.

Once the specs are approved, the agent codes **autonomously** — it applies **KISS, YAGNI,
DRY, and SoC** to the code it writes and refactors any violation before each commit, without
pausing to ask. The source of these directives is the `dev-lifecycle` checkpoint phase.

## The three artifacts

| File | What it is | Who generates it |
|---|---|---|
| `spec.md` | The **what** and the **why**: problem, acceptance criteria, scope, contracts, edges. | `prompt-grill` skill |
| `plan.md` | The **how**: architecture, affected files by layer, risks, testing strategy. | Technical discussion |
| `tasks.md` | The **execution**: checklist of small tasks, ordered by dependency. | After the plan is approved |

## How to start a feature

1. Run the `prompt-grill` skill (or say "interview me about X"). It conducts the interview and
   writes `specs/<feature>/spec.md`.
2. With the spec approved, write `plan.md` (copy from `_template/plan.md`).
3. With the plan approved, break it into `tasks.md` (copy from `_template/tasks.md`).
4. Implement following the tasks, marking `[x]` as you complete each one.

## tasks.md is the memory between sessions

When starting a new session, read the feature's `spec.md` + `tasks.md` instead of relying on
the conversation history. The task state (`[ ]` / `[~]` / `[x]`) is the source of truth for
progress.
