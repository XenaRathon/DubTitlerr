# DubTitlerr agent guide

For a coding agent working on a person's behalf: get DubTitlerr running, diagnose it, or change it. The README and wiki are the human versions of the same material.

## 0. Read order

- **Set up or run:** sections 1 and 2, then [Your first show](https://github.com/xenarathon/DubTitlerr/wiki/Your-First-Show) for the full walkthrough.
- **Troubleshoot:** section 5. Each row links the wiki recipe that holds the full procedure.
- **Contribute:** section 4.
- **Look up** an environment variable, glossary field, sidecar suffix or stage outcome: [Reference](https://github.com/xenarathon/DubTitlerr/wiki/Reference). Design rationale: [Why it works this way](https://github.com/xenarathon/DubTitlerr/wiki/Why-It-Works-This-Way). ASR evidence: [Choosing an ASR model](https://github.com/xenarathon/DubTitlerr/wiki/Choosing-an-ASR-Model).
- The wiki pages also live in `docs/wiki/`. This guide describes `main`. When this file and the code disagree, the code wins.

## 1. Orientation

DubTitlerr watches an anime library and, per episode, transcribes English-dub audio into timed captions, corrects names, repairs selected lines, merges signs and songs, then muxes one subtitle track into the video.

| Stage | Module or runner | Main output or marker |
| --- | --- | --- |
| Mine | `mine_glossary.py` | Additive per-show glossary JSON under `GLOSSARY_DIR` |
| Transcribe and reflow | `generate.py` | `<stem>.eng.dubtitles.srt`, `<stem>.dubtitles.conf.json`, `<stem>.dubtitles.words.json`; a hard crash leaves `<stem>.dubtitles.fail` and `<stem>.dubtitles.crash.json` |
| Repair | `repair.py` | Rewrites the SRT; writes `<stem>.dubtitles.repair.csv` and `<stem>.dubtitles.repair-summary.json` |
| Merge signs and songs | `dub_signs_merge.py` | `<stem>.eng.dubtitles.ass` for MKV episodes |
| Mux | `mux.py` | Video with a default `Dubtitles` track and the `<stem>.dubtitles.done` stamp |
| Stage record | `common.py` (called by each stage and `merge_pass.sh`) | `<stem>.dubtitles.stages.json` |

Invariants to keep:

- **Timing:** repair changes text and leaves card timing alone. A proposed line that does not fit its card is refused.
- **Provenance:** transcription comes exclusively from the English-dub audio. The embedded fansub track serves repair as a reference, and the pipeline skips its own `Dubtitles` output when it looks for references.
- **One worker per library:** the code has no cross-worker lock, so parallel workers race on the same episode and its temporary mux files.
- **Fail closed:** a failed repair or signs stage does not ship. Read `<stem>.dubtitles.stages.json`; merge skips mux for that episode and retries it on a later pass.

## 2. Set up and run

### Prerequisites and config

Docker with NVIDIA container GPU support (Whisper), an anime library with English-dub audio, and a repair-model server: llama.cpp or an OpenAI-compatible API (both `/v1/chat/completions`), or Ollama (`/api/generate`). The published image is `ghcr.io/xenarathon/dubtitlerr`. Build from `Dockerfile.builder`.

Minimum config directory, mounted at `/config`:

```text
dubtitlerr-config/
  anime_order.txt
  glossaries/
  decisions/
  wiki_cache/
```

`anime_order.txt` holds one show-directory name per line; start with only the show to process.

With Compose, set two host paths: `MEDIA_ROOT` (the library's parent, mounted at `/media`) and `CONFIG_ROOT` (the directory above, mounted at `/config`). `compose.yaml` derives `MERGE_ROOTS` and `MUX_ROOTS` from `ANIME_ROOT` (default `/media/Anime Library`) and sets the glossary, decisions, wiki-cache and order-file paths. Without Compose, set `ANIME_ROOT`, `MERGE_ROOTS` and `MUX_ROOTS` to the same in-container library root, because their built-in defaults differ.

### Choose a repair backend

- **llama.cpp** (default): `REPAIR_BACKEND=llamacpp`, `REPAIR_MODEL=qwen3-4b-instruct`, `REPAIR_LLAMACPP_URL` set to the full `/v1/chat/completions` endpoint (Compose defaults it to `http://host.docker.internal:8090/v1/chat/completions`). Start `llama-server` with `--jinja`; [Your first show, step 1](https://github.com/xenarathon/DubTitlerr/wiki/Your-First-Show#step-1--serve-the-repair-model) has a verified command. Test a real completion, because `/health` can answer before the model finishes loading.
- **Ollama:** `REPAIR_BACKEND=ollama`, `REPAIR_MODEL` set to an installed model, `OLLAMA_URL` set to the full `/api/generate` endpoint reachable from the container (module default `http://127.0.0.1:11434/api/generate`).
- **OpenAI-compatible API:** `REPAIR_BACKEND=openai`, `REPAIR_OPENAI_URL` set to the full chat-completions URL, `REPAIR_MODEL` set to the provider's model id, and `REPAIR_OPENAI_KEY_ENV` set to the *name* of the environment variable that holds the key (pass that variable through the container environment). `REPAIR_MAX_TOKENS` defaults to `1024`. `REPAIR_EXTRA_BODY` takes a JSON object of provider options, for example one that turns reasoning off; a reasoning model that spends the whole token budget thinking returns empty content, which repair reports as unreachable. Only `message.content` is read. HTTP 429 and 5xx retry up to `REPAIR_OPENAI_RETRIES` times (default `2`, `Retry-After` honoured up to 30 s) within a per-episode sleep budget (`REPAIR_RETRY_SLEEP_BUDGET`, default 600 s).

### First-run checks

Each step ends with the result that means it worked.

1. **GPU:** `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` prints the NVIDIA device.
2. **Config folders:** `mkdir -p dubtitlerr-config/{glossaries,decisions,wiki_cache}`; `ls dubtitlerr-config` lists all three.
3. **One show:** write that show's exact media folder name as the only non-comment line in `dubtitlerr-config/anime_order.txt`; `cat` prints that name alone.
4. **Compose paths:** export `MEDIA_ROOT` and `CONFIG_ROOT` (or put them in a `.env` beside `compose.yaml`); `docker compose config` exits 0 and shows both mounts and the three library roots (`ANIME_ROOT`, `MERGE_ROOTS`, `MUX_ROOTS`).
5. **Start:** `docker compose pull && docker compose up -d` (or `docker compose up -d --build`); the log shows the `dubtitle-builder up` line.
6. **Repair backend:** llama.cpp and OpenAI-compatible: the short completion request from the wiki's step 1 returns JSON with non-empty `choices[0].message.content`. Ollama: its `/api/generate` response carries non-empty `response` text.
7. **First episode:** `docker compose logs -f`. After a complete episode the media directory holds a current `.dubtitles.done` stamp (mux removes the temporary `.srt` and `.ass` sidecars once the track is embedded) and the player lists an embedded `Dubtitles` track.
8. **Review page:** port `8842` (published by `compose.yaml`). On first start without accounts, browse to `http://<host>:8842` to create the initial admin account at `/review/setup`. An optional one-time seed from `REVIEW_USERNAME` and `REVIEW_PASSWORD` (or `REVIEW_PASSWORD_FILE`) creates it automatically at boot.

## 3. Where the full lists live

- Environment variables and defaults, glossary fields, review-queue reasons, sidecar suffixes, stage-outcome names: `docs/wiki/Reference.md`. The guard and queue settings (`VERIFY_*`, `REPAIR_*`) have a measured number beside each; read it before changing a default.
- Why a guard or queue behaves as it does, with the evidence: `docs/wiki/Why-It-Works-This-Way.md`.
- Compose mounts, roots and environment wiring: `compose.yaml`.
- Dependencies, Python floor, pytest settings, Ruff rules: `pyproject.toml`.
- Repair backend behaviour and its variables: the header docstring of `repair.py`.

For a minimum run, set `MEDIA_ROOT`, `CONFIG_ROOT` and a reachable repair endpoint; Compose supplies the rest.

## 4. Contribute

| Path | Responsibility |
| --- | --- |
| `generate.py` | Transcription, reflow, confidence sidecars, per-episode generation |
| `repair.py` | Anchored repair, the repair gates, the repair-stage outcome |
| `dub_signs_merge.py` | Merge signs and song events into the subtitle output |
| `mux.py` | Verify and mux subtitle tracks and fonts into the video |
| `common.py` | Shared paths, atomic writes, stamps, stage outcomes |
| `mine_glossary.py`, `glossary_acquire.py`, `glossary_verify.py` | Mine names from embedded subtitles, acquire them from a wiki, verify spellings |
| `glossary_decision.py`, `decision_client.py` | The opt-in decision-model backend for verify (and acquire) |
| `wiki_scope.py`, `glossary_lock.py` | Wiki scope for shows without arc names; the per-glossary lock |
| `unresolved.py`, `review_apply.py` | The review queue file and applying verdicts to a subtitle |
| `review_server.py` | Authenticated repair-review HTTP interface |
| `tools/bakeoff.py` | Compare repair models on real transcript targets |
| `container_run.sh`, `gen_loop.sh`, `merge_pass.sh`, `shell/lib.sh` | Container supervisor, generation loop, merge loop, shared shell helpers |
| `settings_registry.py` | The one list of settings: type, range, default, scope, when it applies, first wave or read-only |
| `settings_store.py`, `settings_api.py`, `settings_connections.py`, `settings_migrate.py` | `settings.json` / `secrets.json`, the settings API, named LLM connections, the one-time `runtime.env` import |
| `review_settings_write.py` | The exporter the shell loops run: stored settings for one scope, as shell-quoted `export` lines |

### Add or change a setting

A setting lives in one place, `settings_registry.py`. The API, the validation and the settings page follow it.

To add a setting:

1. Add an entry: key, category, label, help, type, default, `scope` (the process that reads it: `gen`, `merge`, `server`, `container`) and `applies`. `applies` is `restart` exactly when the scope is only `server` and/or `container`.
2. Read the key where the pipeline already reads it. The exporter delivers the stored value through the environment, so the pipeline needs no second reader.
3. Make it editable by adding it with `_wave(...)` (a `first_wave` entry). An entry added in the table at the bottom of the module is shown read-only.

Done when `tests/test_settings_registry_scan.py` (it fails on any variable the code reads that the registry lacks) and `tests/test_settings_registry.py` pass, and the row appears on its category page.

CI runs Python `3.11` and `3.13`. Run the same checks locally:

```sh
pip install pytest pysubs2 jellyfish
pytest
pip install ruff
ruff check .
```

Both finish clean before a PR. Conventions:

- Write the failing test first. Tests mock HTTP and model calls and use fake credentials.
- Write product sidecars through `common.atomic_write` (temporary file plus `os.replace`), so a failed write leaves the previous output intact.
- Record each stage result through `common.write_stage` with a name from `common.STAGE_OUTCOMES`; a failed outcome blocks mux.
- For API failures log a fixed diagnostic, the exception class or the HTTP status. Response bodies and exception text can carry a key.
- Put user-visible changes under `## [Unreleased]` in `CHANGELOG.md`. `TRANSCRIBE_VERSION` and `TEXT_VERSION` in `common.py` decide whether a change reaches already-processed episodes; read their history before deciding on a bump.

PR checklist:

- [ ] Tests cover the behaviour and its failure path.
- [ ] A failed stage cannot leave a current-looking `.done` stamp or overwrite the last good output.
- [ ] New settings, outcomes and sidecars are documented where their full list lives (section 3).
- [ ] Fixtures, logs and the diff hold no real key, personal path or host detail.
- [ ] The description says what changed, which tests ran, and any migration or output-version consequence.

Ask the maintainer first when a change touches card timing, transcript provenance, output-version migration, glossary admission policy, or anything that replaces media in place. These decide what ships into a library.

## 5. Troubleshoot

Read the marker or stage record first.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Episode skipped; `<stem>.dubtitles.fail` exists | A hard generation crash left the poison marker (a soft stop does not create it). | Read `<stem>.dubtitles.crash.json`, fix the cause, clear the marker. [Recover an episode that crashed](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#recover-an-episode-that-crashed) |
| Repair stage `backend-unreachable` | The repair model failed too often, so the episode was refused and the `.srt` left as it was. A failure is a connection error, a timeout, HTTP 401, 403, 408, 429 or 5xx, a missing or malformed key, or invalid `REPAIR_EXTRA_BODY` JSON. Refusal triggers: the failure rate reaches `REPAIR_UNREACHABLE_REFUSE_PCT` (default 10), `REPAIR_MAX_CONSECUTIVE_UNREACHABLE` (default 5) targets fail in a row, the episode passes `REPAIR_EPISODE_DEADLINE` (default 3600 s), or every request is rejected with HTTP 400, 404, 409, 413 or 422 (wrong model id or URL; a single rejected line just keeps its transcript text). | Check backend name, full endpoint URL, model readiness and the key variable, then let the next pass retry. [Fix a repair stage that silently does nothing](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#fix-a-repair-stage-that-silently-does-nothing) |
| Repair summary shows `llm_empty` above 0 and lines sit in `<stem>.dubtitles.unresolved.jsonl` (the stage still records `ok`) | The model answered a target with empty content; a reasoning or template setup can spend the whole budget. With the API backend, an empty reply that hit the token limit counts as unreachable instead (previous row). | Send a real completion and inspect `choices[0].message`. llama.cpp: `--jinja` plus the model's reasoning setting. API: raise `REPAIR_MAX_TOKENS` or turn reasoning off through `REPAIR_EXTRA_BODY`. [Fix a repair stage that silently does nothing](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#fix-a-repair-stage-that-silently-does-nothing) |
| Repair stage `stopped`; log shows `skip mux: repair failed (stopped)` | A soft stop reached repair between targets, before it rewrote the srt. The merge pass reports `MERGE PASS INCOMPLETE` for it. | Nothing to fix: the next pass clears the record and re-runs repair. [Stop the container without losing work](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#stop-the-container-without-losing-work) |
| `.dubtitles.mux-recovery` exists, or the log says `recovery pending` | A cross-device copy may have failed after partly replacing the episode; the complete mux output is kept separately. | Read the marker's `kept` path, validate that file with `ffprobe`, restore it over the episode, remove the marker. [Resolve a mux recovery marker](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#resolve-a-mux-recovery-marker) |
| Container exit `0` after `docker stop`, or `137` | `0` with `soft stop complete`: the unit in flight finished. `137`: the grace period ran out and SIGKILL landed. | Set the stop grace period longer than the longest unit (`MERGE PASS STOPPED` marks a stopped merge pass). [Stop the container without losing work](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#stop-the-container-without-losing-work) |
| `glossary busy: <stage> skipped` in a log | An unattended stage found the glossary locked by another run and skipped instead of waiting. It exits 0. | Nothing to fix; the next sweep runs it. If it repeats every night, a human `--review` is holding the glossary: finish it. [Triage the review queue](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#triage-the-review-queue) |
| Verify prints `refused`, or the stage does nothing after `REPAIR_BACKEND=openai` | `VERIFY_BACKEND` is unset and the repair backend is not `llamacpp` or `ollama`, so the stage will not guess a backend. | Set `VERIFY_BACKEND`. [Decision backend](https://github.com/xenarathon/DubTitlerr/wiki/Reference#decision-backend) |
| The review queue is huge | `no-match` terms or large-change rejections are being listed. | Check `VERIFY_QUEUE_NO_MATCH` and `REPAIR_AUTO_DISMISS_WORDS`; `--review --all` lists what is collapsed. [Triage the review queue](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#triage-the-review-queue) |
| Repair summary shows `rejected_name_part` or `dismissed_large_change` | The name-part check refused a repair, or a large-change rejection was hidden from the default view. Both are recorded in `<stem>.dubtitles.unresolved.jsonl`. | Read the entries (`guard` names the check). `REPAIR_KEEP_NAME_PARTS=0` turns the check off. [Review queue entries](https://github.com/xenarathon/DubTitlerr/wiki/Reference#review-queue-entries) |
| API provider answers HTTP 429 | The provider rate-limited the request or the account. | Check quota and wait out the provider's window. Repair retries a bounded number of times, then reports the target unreachable so the stage cannot ship a partial result. [Repair variables](https://github.com/xenarathon/DubTitlerr/wiki/Reference#repair) |
| Locked out of the web UI or administrator password lost | No admin account is accessible. | Run `python3 review_users.py reset-admin <name>` inside the container. It resets the password, prints a new one-time password, and clears existing sessions. [Recover an administrator account](https://github.com/xenarathon/DubTitlerr/wiki/How-To-Guides#recover-an-administrator-account) |

## 6. Guardrails

- Confirm with the person that the library has a backup before the first run or any step that rewrites video files, then start with one show and inspect the muxed track and the review queue before queueing more.
- Read a marker (`.dubtitles.fail`, `.dubtitles.stages.json`, `.dubtitles.mux-recovery`) and follow its recovery recipe before removing it.
- Keep every key in an environment variable. Config files, command-line arguments, logs, fixtures and commits hold only the variable's name.
- Treat a change to a guard or queue default as a change to glossary admission policy, and ask the maintainer first. Each default rests on a blind-judged sample listed in the Why page.
