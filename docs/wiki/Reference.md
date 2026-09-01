# Reference

Information-oriented. Values, shapes and filenames, looked up rather than read.

Every default below is the value in the code, not the value in a compose example. Where a
default differs between modules, that is stated rather than smoothed over.

---

## Container

**Image:** `ghcr.io/xenarathon/dubtitlerr`

**Tags:** the git tag of a release (`v0.1.0-beta`), plus `latest` pointing at the most recent
release. `latest` never tracks `main`.

**Entrypoint:** `container_run.sh`, which starts three loops in one container:

| Loop     | Script             | Cadence                                   | Work                                              |
| -------- | ------------------ | ----------------------------------------- | ------------------------------------------------- |
| Generate | `gen_loop.sh`      | continuous, then `RESCAN_INTERVAL` idle   | GPU: mine, acquire, verify, transcribe            |
| Merge    | `merge_pass.sh`    | every `MERGE_INTERVAL`                    | CPU + LLM: repair, merge signs, mux, Plex refresh |
| Review   | `review_server.py` | restarts after `REVIEW_RESTART` s on exit | HTTP review UI                                    |

**Stage order within `gen_loop.sh`:** `watch_queue.py` → `mine_glossary.py` →
`glossary_acquire.py` → `glossary_verify.py` → `generate.py`

**Stage order within `merge_pass.sh`:** `repair.py` → `dub_signs_merge.py` → `mux.py` →
`plex_refresh.py`

The container runs as **root**, so `generate.py` can chown into the media tree.

---

## Per-episode files

All are written beside the video, sharing its basename.

| Suffix                           | Written by                                    | Read by                                      | Contents                                                                      |
| -------------------------------- | --------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------- |
| `.eng.dubtitles.srt`             | `generate.py`, `repair.py`, `review_apply.py` | `dub_signs_merge.py`, `mux.py`               | The dialogue transcript from the dub audio                                    |
| `.eng.dubtitles.ass`             | `dub_signs_merge.py`, `review_apply.py`       | `mux.py`                                     | Dialogue plus signs, songs and credits                                        |
| `.dubtitles.conf.json`           | `generate.py`, `repair.py`                    | `repair.py`, `glossary_acquire.py`, `mux.py` | Per-cue `avg_logprob` and `no_speech_prob`                                    |
| `.dubtitles.words.json`          | `generate.py`                                 | `generate.py`                                | Per-word confidences and audio duration; lets a text-tier re-run skip the GPU |
| `.dubtitles.done`                | `common.py`, `mux.py`                         | `generate.py`, `mux.py`                      | Completion stamp: muxed size, mtime, tier versions                            |
| `.dubtitles.fail`                | `generate.py`                                 | `generate.py`                                | Poison marker after a hard crash. Delete it to retry                          |
| `.dubtitles.crash.json`          | `generate.py`                                 | —                                            | Exception type, message and time from that crash                              |
| `.dubtitles.qc.json`             | `generate.py`                                 | `mux.py`                                     | Counters, cps quantiles, layout violations                                    |
| `.dubtitles.repair.csv`          | `repair.py`                                   | —                                            | Audit trail: original, repaired, reference, latency                           |
| `.dubtitles.repair-summary.json` | `repair.py`                                   | `mux.py`                                     | Targets, repaired, skipped, latency, model, rules                             |
| `.dubtitles.unresolved.jsonl`    | `unresolved.py`                               | `unresolved.py`, `review_server.py`          | Rejections awaiting human triage — the review queue                           |
| `.dubtitles.mux.log`             | `mux.py`                                      | —                                            | Tracks dropped, defaults set                                                  |

A `.stale` suffix is appended to prior-version output during a version upgrade, e.g.
`.eng.dubtitles.srt.stale`.

Per **show** rather than per episode: `.lastrun.json` and the glossary's
`.acquire-cache.json`.

---

## Environment variables

### Paths and roots

| Var              | Default                     | Meaning                                            |
| ---------------- | --------------------------- | -------------------------------------------------- |
| `MEDIA_ROOT`     | `/media`                    | Media mount                                        |
| `OUTPUT_ROOT`    | _(empty)_                   | Write sidecars elsewhere than beside the video     |
| `ANIME_ROOT`     | `/media/Anime Library`      | Root the generate loop walks                       |
| `MERGE_ROOTS`    | `/data/Media/Anime Library` | Roots the merge pass walks (colon-separated)       |
| `MUX_ROOTS`      | `/data/Media/Anime Library` | Roots `mux.py` walks                               |
| `ANIME_ORDER`    | `/config/anime_order.txt`   | Show order file                                    |
| `GLOSSARY_DIR`   | `/config/glossaries`        | Per-show glossaries                                |
| `DECISIONS_DIR`  | `/config/decisions`         | Per-show verdict stores                            |
| `WIKI_CACHE_DIR` | `/config/wiki_cache`        | Cached Fandom wiki responses                       |
| `MODEL_DIR`      | `/subgen/models`            | Whisper model directory                            |
| `HARDLINK_ROOTS` | _(unset)_                   | Roots to search when preserving download hardlinks |

> **`ANIME_ROOT` and `MERGE_ROOTS` have different defaults.** The generate loop defaults to
> `/media/Anime Library` and the merge pass to `/data/Media/Anime Library`. Set both
> explicitly; do not rely on either default lining up with the other.

### Transcription

| Var                                  | Default          | Meaning                                             |
| ------------------------------------ | ---------------- | --------------------------------------------------- |
| `WHISPER_MODEL`                      | `large-v3-turbo` | Whisper model                                       |
| `COMPUTE_TYPE`                       | `int8`           | Precision. `float16` for maximum quality            |
| `WHISPER_BEAM_SIZE`                  | `7`              | Beam width                                          |
| `REQUIRE_ENG`                        | `1`              | Skip episodes with no English audio track           |
| `SKIP_IF_SRT`                        | `1`              | Skip an episode that already has a dubtitle sidecar |
| `SHOW_NAME`                          | _(empty)_        | Override the show name derived from the path        |
| `GLOSSARY_FILE`                      | _(empty)_        | Override the glossary resolved from the show        |
| `FFMPEG_TIMEOUT` / `FFPROBE_TIMEOUT` | `600` / `60`     | Seconds                                             |

### Repair

| Var                                | Default                                     | Meaning                                                                                                                                     |
| ---------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPAIR_MODEL`                     | `nanbeige4.2-3b`                            | Repair model                                                                                                                                |
| `REPAIR_BACKEND`                   | `llamacpp`                                  | `llamacpp` or `ollama`                                                                                                                      |
| `REPAIR_LLAMACPP_URL`              | `http://127.0.0.1:8090/v1/chat/completions` | llama.cpp chat endpoint. The server behind it **must** be started with `--jinja` for `nanbeige4.2-3b`, or it returns empty content silently |
| `OLLAMA_URL`                       | `http://127.0.0.1:11434/api/generate`       | Ollama endpoint                                                                                                                             |
| `REPAIR_MODEL_SECONDARY`           | _(same as primary)_                         | Second-opinion model for name changes                                                                                                       |
| `REPAIR_UNANCHORED`                | _(unset — closed)_                          | Global override; prefer the per-show glossary field                                                                                         |
| `DECISIONS_APPLY`                  | `1`                                         | Apply stored human verdicts during repair                                                                                                   |
| `LOGPROB_MIN`                      | `-0.4`                                      | Below this average logprob, a line is a repair target                                                                                       |
| `NSP_MAX`                          | `0.5`                                       | Above this no-speech probability, a line is skipped                                                                                         |
| `LEN_RATIO_MIN` / `LEN_RATIO_MAX`  | `0.6` / `1.5`                               | Accepted length change                                                                                                                      |
| `MAX_REF_BORROW`                   | `3`                                         | Words a repair may take from the reference                                                                                                  |
| `REPAIR_PHONETIC_MIN`              | `0.75`                                      | Phonetic similarity floor for a name correction                                                                                             |
| `REPAIR_TIMEOUT_CONNECT` / `_READ` | `10` / `120`                                | Seconds                                                                                                                                     |

### Punctuation restore

| Var                   | Default                            | Meaning                                    |
| --------------------- | ---------------------------------- | ------------------------------------------ |
| `RESTORE_PUNCTUATION` | `1`                                | Enable the punctuation-restore stage       |
| `RESTORE_MODEL`       | _(falls back to `REPAIR_MODEL`)_   | Model for this stage                       |
| `RESTORE_BACKEND`     | _(falls back to `REPAIR_BACKEND`)_ | Backend for this stage                     |
| `RESTORE_MIN_RUN`     | `2`                                | Minimum run of unpunctuated cues to act on |
| `RESTORE_MAX_TOKENS`  | `2048`                             | Generation cap                             |

### Glossary mining, acquisition and verification

| Var                  | Default                            | Meaning                                               |
| -------------------- | ---------------------------------- | ----------------------------------------------------- |
| `MINE_MIN_COUNT`     | `3`                                | Occurrences before a mined term is kept               |
| `ACQUIRE`            | `1`                                | Run the acquisition step (`gen_loop.sh`)              |
| `ACQUIRE_APPLY`      | _(unset — dry run)_                | Write acquired names rather than only reporting       |
| `ACQUIRE_MIN_COUNT`  | `3`                                | Occurrences before a candidate is considered          |
| `ACQUIRE_MIN_SHARE`  | `0.80`                             | Share of occurrences that must agree                  |
| `ACQUIRE_MIN_SIM`    | `0.72`                             | Similarity floor for a candidate match                |
| `ACQUIRE_UNSEEN_SIM` | `0.98`                             | Similarity above which a term counts as already known |
| `ACQUIRE_GROWTH_MAX` | `2`                                | Cap on glossary growth per pass                       |
| `ACQUIRE_NO_CACHE`   | _(unset)_                          | Bypass the acquire cache on dry runs                  |
| `VERIFY_MODEL`       | `qwen3:8b`                         | Adjudication model for wiki verification              |
| `VERIFY_BACKEND`     | _(falls back to `REPAIR_BACKEND`)_ | Backend for verification                              |
| `VERIFY_WORKERS`     | `4`                                | Concurrent wiki lookups                               |
| `WIKI_HTTP_TIMEOUT`  | `20`                               | Seconds                                               |
| `WIKI_CACHE_TTL`     | `2592000`                          | 30 days, in seconds                                   |
| `WORDLIST_PATH`      | `/usr/share/dict/american-english` | The real-English-word gate                            |

### Mux

| Var                       | Default                  | Meaning                                                                                           |
| ------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------- |
| `KEEP_LANGS`              | `eng,en,dut,nld,nl,und,` | Audio and subtitle languages kept                                                                 |
| `SUB_LANGS`               | `eng,en,und,`            | Subtitle languages considered as a reference                                                      |
| `MIN_FREE_GB`             | `5`                      | Skip a mux below this free space rather than failing                                              |
| `DUR_TOL`                 | `2`                      | Seconds of duration mismatch tolerated                                                            |
| `DUB_SUFFIX`              | `.eng.dubtitles.srt`     | Sidecar the merge step looks for                                                                  |
| `REVIEW_GATE_SHOWS`       | _(empty)_                | Shows whose episodes wait for review before muxing                                                |
| `REVIEW_GATE_STALE_DAYS`  | `7`                      | A hold older than this is reported loudly and **stays held**. It buys a log line, never a release |
| `MEDIA_UID` / `MEDIA_GID` | `1000` / `100`           | Ownership set on written files                                                                    |

### Review server

| Var                     | Default                          | Meaning                                            |
| ----------------------- | -------------------------------- | -------------------------------------------------- |
| `REVIEW_PORT`           | `8842`                           | Listen port                                        |
| `REVIEW_BIND`           | `0.0.0.0`                        | Listen address                                     |
| `REVIEW_TOKEN`          | _(unset — a token is generated)_ | See **Authentication** below                       |
| `REVIEW_MAX_CONCURRENT` | `16`                             | Concurrent request cap                             |
| `REVIEW_STEMS_TTL`      | `30`                             | Seconds an episode listing is cached               |
| `REVIEW_RESTART`        | `15`                             | Seconds before restarting the server after an exit |

### Ordering and watch queue

| Var                                        | Default                     | Meaning                                 |
| ------------------------------------------ | --------------------------- | --------------------------------------- |
| `SEASON_START`                             | `0`                         | Global watch-order start season         |
| `SEASON_PRIORITY_FILE`                     | _(unset)_                   | Per-show start seasons                  |
| `WATCH_QUEUE_WINDOW_DAYS`                  | _(unset — step skipped)_    | Days of watch history to consider       |
| `WATCH_QUEUE_PIN`                          | _(unset)_                   | Restrict the watch queue to named shows |
| `WATCHSTATE_URL` / `WATCHSTATE_API_KEY`    | _(empty)_                   | WatchState source                       |
| `PLEX_URL` / `PLEX_TOKEN` / `PLEX_SECTION` | _(empty)_ / _(empty)_ / `7` | Plex refresh and watch source           |
| `PLEX_PATH`                                | _(empty)_                   | Path prefix Plex sees, if it differs    |

### Loop cadence

| Var                                        | Default            | Meaning                                                                                                                                         |
| ------------------------------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `MERGE_INTERVAL`                           | `600`              | Seconds between merge passes                                                                                                                    |
| `MERGE_WINDOW`                             | _(empty — always)_ | Hours a merge sweep may run, `HH:MM-HH:MM`. May cross midnight. The end is exclusive. Set it when the repair backend is only up part of the day |
| `RESCAN_INTERVAL`                          | `21600`            | Idle seconds after a full generate sweep                                                                                                        |
| `ACQUIRE_TIMEOUT`                          | `1800`             | Seconds                                                                                                                                         |
| `VERIFY_TIMEOUT`                           | `1200`             | Seconds                                                                                                                                         |
| `LLM_TIMEOUT_CONNECT` / `LLM_TIMEOUT_READ` | `10` / `120`       | Seconds                                                                                                                                         |

---

## Glossary file

`$GLOSSARY_DIR/<Show folder name>.json`. Keys not listed here are ignored on load.

```json
{
  "show": "One Piece",
  "wiki": "https://onepiece.fandom.com/api.php",
  "initial_prompt": "This is One Piece. Spell names correctly: Luffy, Zoro, ...",
  "unanchored_repair": false,
  "names": ["Luffy", "Zoro", "Spandam"],
  "phrases": ["Enies Lobby", "Water 7"],
  "hard_fixes": { "ruffy": "Luffy", "spondum": "Spandam" },
  "verified": ["Luffy", "Zoro"],
  "flagged": { "SomeName": "no-match" }
}
```

| Key                 | Type   | Meaning                                                                                                                |
| ------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------- |
| `show`              | string | Display name, used in prompts                                                                                          |
| `wiki`              | string | Fandom API override when auto-resolution misses                                                                        |
| `initial_prompt`    | string | Passed to Whisper. **Measured to make no difference** to output; kept for compatibility                                |
| `unanchored_repair` | bool   | `true` when your copies of this show carry no English subtitles for the Japanese audio                                 |
| `names`             | list   | Proper nouns                                                                                                           |
| `phrases`           | list   | Multi-word terms                                                                                                       |
| `hard_fixes`        | object | Exact replacements. A key containing a space is matched as a phrase, otherwise as a token. Keys are lowercased on load |
| `verified`          | list   | Verifier bookkeeping                                                                                                   |
| `flagged`           | object | Terms the verifier could not confirm                                                                                   |

`glossary_verify.py` can be run by hand:

```sh
python3 glossary_verify.py "/config/glossaries/<Show>.json" [--wiki URL] [--force]
```

---

## Decision store

`$DECISIONS_DIR/<Show folder name>.json`. One store per show, intended to be committed to
git.

An entry is keyed on the **normalised text pair**, never on episode or line number:

```json
{
  "orig": "dothamingo's coming",
  "proposed": "doflamingo's coming",
  "verdict": "correct",
  "text": "Doflamingo's coming.",
  "run": "review",
  "at": 1756600000.0
}
```

**Verdicts:** `accept`, `reject`, `correct`, `force`.

`force` admits a repair the mechanical gate refused. It overrides the judgement checks but
never the card-fit check, because card timing is immutable.

**Normalisation for matching:** case and runs of whitespace are folded; the curly apostrophe
`'` is folded to `'`. **Punctuation is otherwise kept** — it is part of a line's identity.

---

## Review server

Started by `container_run.sh`; takes no command-line arguments. Port comes from
`REVIEW_PORT`.

| Method | Path               | Purpose                                                         |
| ------ | ------------------ | --------------------------------------------------------------- |
| GET    | `/`, `/index.html` | Review page. `?stem=<episode>` filters to one episode           |
| GET    | `/shared`          | Lines appearing in two or more episodes                         |
| GET    | `/api/episodes`    | Every episode with pending items                                |
| GET    | `/api/episode`     | One episode's queue, in decision order                          |
| GET    | `/api/shared`      | Repair pairs occurring in two or more episodes                  |
| POST   | `/api/decide`      | Record verdicts                                                 |
| POST   | `/api/shared`      | Record verdicts on shared lines                                 |
| POST   | `/api/apply`       | Rewrite the subtitle and drop the stamp so the episode re-muxes |

### Authentication

The token is presented in an `X-Review-Token` header.

| `REVIEW_TOKEN`          | Behaviour                                                               |
| ----------------------- | ----------------------------------------------------------------------- |
| Unset                   | A token is **generated**, persisted `0600`, and printed to the log once |
| Set to a value          | That value is the token                                                 |
| Set to the empty string | **Auth disabled.** Only an explicit empty value does this               |

**Write routes require the token. Read routes never do.** The server runs in a root-owned
process tree and its write routes rewrite subtitles and force re-muxes, so do not expose it
to a network you do not control.

To retrieve a generated token:

```sh
docker exec <container> cat /config/review_token
```
