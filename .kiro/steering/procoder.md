---
inclusion: always
---

# DubTitlerr — agent notes

DubTitlerr transcribes English-dub anime audio into subtitles, repairs them with an LLM, merges the signs/songs track, and muxes the result into a live media library. Treat it as production media infrastructure: a bad run burns hours of GPU time or leaves an episode's subtitle track worse than before.

**Start with the [agent guide](https://github.com/XenaRathon/DubTitlerr/blob/main/docs/AGENT-GUIDE.md)** (`docs/AGENT-GUIDE.md` in the repo): setup, the file map, the checks CI runs, contribution conventions, the PR checklist, and the changes that need the maintainer's sign-off first. It is the single source for those. This file holds only the working rules the guide doesn't cover.

## Working rules

- **Commits** follow Conventional Commits with a scope where one fits: `fix:`, `feat:`, `docs:`, `test(web):`, `chore:`.
- **Issues and specs** live in GitHub issues on `XenaRathon/DubTitlerr`. Command shapes: [issue tracker](https://github.com/XenaRathon/DubTitlerr/blob/main/docs/agents/issue-tracker.md). Domain docs: [domain](https://github.com/XenaRathon/DubTitlerr/blob/main/docs/agents/domain.md).
- **Validate on a spread of shows**, never one: one with a fansub track and one without, one whose glossary came from acquisition and one that was only mined. One Pace is the least representative title, because it holds nearly all the curated `hard_fixes` and its seasons differ in whether a fansub track exists.
- **One worker per library.** Nothing in the code locks across workers. Two workers on one library race on `<stem>.muxtmp.mkv` and re-transcribe each other's episodes. Building a real claim/lock is open work; a change that assumes a lock exists is a bug.
- **Persist incrementally** in any expensive stage: write per item or per batch (append-only JSONL is the house idiom; see `unresolved.py`), so a killed run keeps the work it finished. A longer timeout can unblock a run, but the fix is incremental writes.
- **Glossaries are a shipped deliverable.** `glossaries/*.json` are pre-seeded dictionaries for everyone who clones the repo. The glossary a deployment actually uses lives in its config volume and drifts from the repo copy, so check the deployed one when debugging a live library.
- **LLM calls speak the OpenAI-compatible REST API**, so hosted endpoints and local servers (llama.cpp, Ollama) stay drop-in replacements for each other. A `503 Loading model` from the repair backend means the model is still warming up; check the backend before treating it as a pipeline regression.
- **`.ass` output keeps its override tags** (`\pos`, `\an`, `\fad`), and sign/song events stay anchored where the source placed them.

## Working alongside Jules

Google Jules (`google-labs-jules[bot]`) contributes asynchronously on GitHub: it picks up issues labelled `jules`, works on its own branch, and opens a PR against `main`.

- **GitHub (`origin`) is the source of truth.** Any other remote is a mirror that trails it. Sync with `origin/main` before starting a change and again before pushing.
- **Delegate** boundary-isolated work (a missing test, a regex tweak, a doc fix, a lint fix) by opening an issue: `gh issue create --label jules --title "test: ..." --body "..."`. The body names the files to inspect and the test that proves the change.
- **Jules' branches belong to Jules.** Review and comment on its PRs; push changes through your own branch. `main` only moves forward: merge, never force-push.
- **Shared files first get a PR check.** Before editing `AGENTS.md`, `pyproject.toml`, `uv.lock` or a Dockerfile, run `gh pr list` and confirm no open PR (Jules' or anyone's) touches the same file.
