# Reference

Information-oriented. Values, shapes and filenames, looked up rather than read.

Every default below is the value in the code, not the value in a compose example. Where a
default differs between modules, that is stated rather than smoothed over.

---

## Container

**Image:** `ghcr.io/xenarathon/dubtitlerr`

**Tags:** the git tag of a release (for example `v0.2.2`), plus `latest` pointing at the most recent
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

A failed repair or signs stage skips mux for that episode. The episode is retried on the next
pass. See [Stage outcomes](#stage-outcomes).

**Stopping:** the entrypoint traps SIGTERM and SIGINT and does not forward them to the work. It
creates the stop flag file (`STOP_FLAG`, default `/tmp/dubtitlerr.stop`) and prints
`soft stop requested`. While the flag exists, no loop starts a new show, episode, glossary step
or mux. The unit already running finishes, then the container prints `soft stop complete` and
exits 0. The flag is deleted at startup, so a stopped container that you start again runs
normally. `docker stop` sends SIGKILL once its `-t` grace period is over (10 seconds by
default), so set `-t` above your longest single unit of work. Inside the glossary steps,
`mine_glossary.py`, `glossary_acquire.py` and `glossary_verify.py` also check the flag between
episodes, terms and escalation pairs. Releases up to 0.2.2 check it only before a glossary step
starts, so an acquire step runs to its end or to `ACQUIRE_TIMEOUT`.

The container runs as **root**, so `generate.py` can chown into the media tree. `Dockerfile` builds a merge-only image (signs and dub merge, no transcribe or repair) and is deprecated. `Dockerfile.builder` is the recommended image.

---

## Per-episode files

All are written beside the video, sharing its basename. The merged `.ass` keeps the same `...eng.dubtitles.*` name, so it still shows up as the Dubtitles track with signs included. If the sidecar came from subgen with `SKIP_IF_EXTERNAL_SUBTITLES_EXIST`, replacing the `.srt` with the merged `.ass` does not trigger a re-transcribe loop.

| Suffix                           | Written by                                                   | Read by                                      | Contents                                                                                                            |
| -------------------------------- | ------------------------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `.eng.dubtitles.srt`             | `generate.py`, `repair.py`, `review_apply.py`                | `dub_signs_merge.py`, `mux.py`               | The dialogue transcript from the dub audio                                                                          |
| `.eng.dubtitles.ass`             | `dub_signs_merge.py`, `review_apply.py`                      | `mux.py`                                     | Dialogue plus signs, songs and credits                                                                              |
| `.dubtitles.conf.json`           | `generate.py`, `repair.py`                                   | `repair.py`, `glossary_acquire.py`, `mux.py` | Per-cue `avg_logprob` and `no_speech_prob`                                                                          |
| `.dubtitles.words.json`          | `generate.py`                                                | `generate.py`                                | Per-word confidences and audio duration; lets a text-tier re-run skip the GPU                                       |
| `.dubtitles.done`                | `common.py`, `mux.py`                                        | `generate.py`, `mux.py`                      | Completion stamp: muxed size, mtime, tier versions                                                                  |
| `.dubtitles.fail`                | `generate.py`                                                | `generate.py`                                | Poison marker after a hard crash. Delete it to retry. Stopping the container no longer leaves one (0.2.2 and later) |
| `.dubtitles.stages.json`         | `repair.py`, `dub_signs_merge.py`, `mux.py`, `merge_pass.sh` | `merge_pass.sh`, `mux.py`                    | One outcome per stage (repair, signs, mux). See [Stage outcomes](#stage-outcomes)                                   |
| `.dubtitles.mux-recovery`        | `mux.py`                                                     | `mux.py`, the `deploy/` close unit           | Written when a failed cross-device copy may have damaged the episode. While it exists, mux refuses that episode     |
| `.muxtmp.mkv.recovered`          | `mux.py`                                                     | you                                          | The complete muxed file that failed copy kept. The marker names its path                                            |
| `.dubtitles.crash.json`          | `generate.py`                                                | -                                            | Exception type, message and time from that crash                                                                    |
| `.dubtitles.qc.json`             | `generate.py`                                                | `mux.py`                                     | Quality counters, cps quantiles, layout violations, and duration flags (schema version 5: overlong and drip_chain)  |
| `.dubtitles.repair.csv`          | `repair.py`                                                  | -                                            | Audit trail: original, repaired, reference, latency                                                                 |
| `.dubtitles.repair-summary.json` | `repair.py`                                                  | `mux.py`                                     | Targets, repaired, skipped, latency, model, rules                                                                   |
| `.dubtitles.unresolved.jsonl`    | `unresolved.py`                                              | `unresolved.py`, `review_server.py`          | Rejections awaiting human triage (the review queue)                                                                 |
| `.dubtitles.mux.log`             | `mux.py`                                                     | -                                            | Tracks dropped, defaults set                                                                                        |

A `.stale` suffix is appended to prior-version output during a version upgrade, e.g.
`.eng.dubtitles.srt.stale`. The `.dubtitles.done` stamp is the only already-done signal: an embedded Dubtitles track alone does not count, so episodes muxed before stamps existed regenerate on the first sweep. Run `scripts/migrate_write_v1_stamps.py` first (dry run by default, `--apply` to write); it writes sidecar stamps only, never touches media, and never overwrites an existing stamp.

Per **show** rather than per episode: `.lastrun.json` and the glossary's
`.acquire-cache.json`.

Beside each glossary: `<glossary>.json.lock` (an advisory lock; the file is harmless to delete),
`<glossary>.json.review-pending` (answers a human gave while a stage held the lock, applied at the next `--review`)
and `<glossary>.json.review-pending.bad` (a pending file that did not parse; kept, never trusted).

### Review queue entries

`.dubtitles.unresolved.jsonl` holds one JSON object per line. Entries stay in the file after they
are resolved; the review view filters them. Keys: `stage`, `reason`, `original_text`,
`proposed_text`, `avg_logprob`, `resolved`, and since this release `guard` (the check that refused
a repair) and, for dismissed entries, `dismissed` and `changes`.

| Reason                   | Stage       | Meaning                                                                                                                                                                                    |
| ------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `no_reference`           | repair      | No fansub anchor overlapped the card. Not in the primary view                                                                                                                              |
| `rejected_guard`         | repair      | The model proposed an edit and `accept_repair` refused it. `guard` names the check: `length_ratio`, `fits_card`, `invents_name`, `vouched_name`, `ref_borrow`, `terminal_punct` and others |
| `rejected_name_invented` | repair      | The model substituted a proper noun that is in neither the glossary nor the original                                                                                                       |
| `rejected_name_part`     | repair      | The repair added or dropped part of a multi-word name the line already had a piece of                                                                                                      |
| `decision_unfittable`    | repair      | A human verdict whose text does not fit the card. The transcript text stands and the reviewer is told                                                                                      |
| `llm_empty`              | repair      | The model answered with nothing                                                                                                                                                            |
| `rejected_guard`         | punctuation | The punctuation-restore stage's own guard refused a proposal                                                                                                                               |

A rejected repair that changes more than `REPAIR_AUTO_DISMISS_WORDS` words carries
`"dismissed": true` and a `changes` count. The review page's default view and
`unresolved.pending(primary_only=True)` skip it; the all-reasons view and the command-line `--all`
show it. A stored human verdict is looked up before any guard runs, so dismissing never overrides one.

---

## Stage outcomes

`<stem>.dubtitles.stages.json` holds one record per stage (`repair`, `signs`, `mux`). Each
record has an `outcome` and a `detail`. For example, an episode that mux refused because of a
recovery marker has this mux record (the other stages are left out):

```json
{"mux": {"outcome": "crashed", "detail": "recovery-pending"}}
```

A stage writes its record when it returns. `merge_pass.sh` clears a stage's record before it
runs that stage again, so an old failure never stands in for a new result. A run that dies
mid-stage leaves a `crashed` record.

| Outcome                                                                                   | Counts as | Meaning                                                                                                           |
| ----------------------------------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------- |
| `ok`                                                                                      | passed    | The stage finished                                                                                                |
| `no-video`                                                                                | passed    | There is no media file for the stem                                                                               |
| `no-reference`                                                                            | passed    | Older records only. Nothing writes it any more                                                                    |
| `refused`                                                                                 | failed    | Repair declined to overwrite repairs that already shipped. The `.srt` on disk is raw speech recognition           |
| `stopped`                                                                                 | failed    | Repair saw a soft stop between two targets and quit before it rewrote the `.srt`. The next pass runs repair again |
| `crashed`, `timeout`, `unwritable`, `backend-unreachable`, `extract-error`, `build-error` | failed    | The stage failed for the reason in its name                                                                       |

A failed outcome blocks mux for that episode. The merge pass prints a `skip mux:` line for each
episode it holds back and reports `MERGE PASS INCOMPLETE` at the end. That includes an episode
repair stopped for a soft stop: the next pass clears the `stopped` record and repairs it again.

`llm-empty` is a name in the code's outcome list, but repair never writes it. When a model
answers a target with nothing, repair counts it as `llm_empty` in the repair summary, queues the
line for review, and the stage still records `ok`.

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

| Var                                  | Default          | Meaning                                                                                        |
| ------------------------------------ | ---------------- | ---------------------------------------------------------------------------------------------- |
| `WHISPER_MODEL`                      | `large-v3-turbo` | Whisper model. `large-v3` scores higher; see [Choosing an ASR model](Choosing-an-ASR-Model.md) |
| `COMPUTE_TYPE`                       | `int8`           | Precision. On Pascal cards `float16` does not load at all — this is not a quality knob there   |
| `WHISPER_BEAM_SIZE`                  | `7`              | Beam width                                                                                     |
| `REQUIRE_ENG`                        | `1`              | Skip episodes with no English audio track                                                      |
| `SKIP_IF_SRT`                        | `1`              | Skip an episode that already has a dubtitle sidecar                                            |
| `SHOW_NAME`                          | _(empty)_        | Override the show name derived from the path                                                   |
| `GLOSSARY_FILE`                      | _(empty)_        | Override the glossary resolved from the show                                                   |
| `FFMPEG_TIMEOUT` / `FFPROBE_TIMEOUT` | `1800` / `60`    | Seconds                                                                                        |

### Repair

| Var                                  | Default                                            | Meaning                                                                                                                                                                                                                                                                                                             |
| ------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPAIR_MODEL`                       | `qwen3-4b-instruct`                                | Repair model                                                                                                                                                                                                                                                                                                        |
| `REPAIR_BACKEND`                     | `llamacpp`                                         | `llamacpp`, `ollama` or `openai` (any OpenAI-compatible chat API; see the rows below)                                                                                                                                                                                                                               |
| `REPAIR_LLAMACPP_URL`                | `http://127.0.0.1:8090/v1/chat/completions`        | llama.cpp chat endpoint. The server behind it **must** be started with `--jinja`, or `chat_template_kwargs.enable_thinking=false` is silently ignored and a thinking-capable model burns its whole budget on reasoning and returns empty content                                                                    |
| `OLLAMA_URL`                         | `http://127.0.0.1:11434/api/generate`              | Ollama endpoint                                                                                                                                                                                                                                                                                                     |
| `REPAIR_MODEL_SECONDARY`             | _(same as primary)_                                | Second-opinion model for name changes                                                                                                                                                                                                                                                                               |
| `REPAIR_UNANCHORED`                  | `1` (deployed 2026-09-06 on the reference install) | Global override; per-show glossary field preferred for new installs (see How-To-Guides.md)                                                                                                                                                                                                                          |
| `DECISIONS_APPLY`                    | `1`                                                | Apply stored human verdicts during repair                                                                                                                                                                                                                                                                           |
| `LOGPROB_MIN`                        | `-0.4`                                             | Below this average logprob, a line is a repair target                                                                                                                                                                                                                                                               |
| `NSP_MAX`                            | `0.5`                                              | Above this no-speech probability, a line is skipped                                                                                                                                                                                                                                                                 |
| `LEN_RATIO_MIN` / `LEN_RATIO_MAX`    | `0.6` / `1.5`                                      | Accepted length change                                                                                                                                                                                                                                                                                              |
| `MAX_REF_BORROW`                     | `3`                                                | Words a repair may take from the reference                                                                                                                                                                                                                                                                          |
| `REPAIR_PHONETIC_MIN`                | `0.75`                                             | Phonetic similarity floor for a name correction                                                                                                                                                                                                                                                                     |
| `REPAIR_TIMEOUT_CONNECT` / `_READ`   | `10` / `120`                                       | Seconds. `_READ` applies to each socket read, not to the whole request; see `REPAIR_REQUEST_DEADLINE`                                                                                                                                                                                                               |
| `REPAIR_OPENAI_URL`                  | _(unset)_                                          | Full chat-completions URL of an OpenAI-compatible API. Used when `REPAIR_BACKEND=openai`                                                                                                                                                                                                                            |
| `REPAIR_OPENAI_KEY_ENV`              | _(unset)_                                          | The **name** of the environment variable that holds the API key. The key is read at call time, a trailing CR or LF is stripped, and its value is never logged                                                                                                                                                       |
| `REPAIR_MAX_TOKENS`                  | `1024`                                             | `max_tokens` for the `openai` backend. A reasoning model that spends all of it thinking returns empty content, which repair counts as the backend being unreachable. A value that is not a number logs a warning and uses the default                                                                               |
| `REPAIR_EXTRA_BODY`                  | _(unset)_                                          | JSON object merged into the request body, for provider options such as `{"enable_thinking": false}`. It cannot replace `model` or `messages`. A value that is not a JSON object makes every call fail as unreachable                                                                                                |
| `REPAIR_OPENAI_RETRIES`              | `2`                                                | Retries after HTTP 429 or 5xx, so three attempts in all. Each waits the `Retry-After` value (at most 30 s), or 2 s and then 4 s when there is none                                                                                                                                                                  |
| `REPAIR_RETRY_SLEEP_BUDGET`          | `600`                                              | Seconds of retry waiting allowed per episode. Once spent, each remaining target gets one attempt                                                                                                                                                                                                                    |
| `REPAIR_REQUEST_DEADLINE`            | `300`                                              | Seconds one HTTP request may take in total, connect plus response (minimum 10). A server that trickles bytes defeats `REPAIR_TIMEOUT_READ`, so this caps the whole request                                                                                                                                          |
| `REPAIR_EPISODE_DEADLINE`            | `3600`                                             | Seconds repair may spend on one episode; `0` turns it off. Past it, the episode is refused like an outage. The slowest of 1,631 production episodes took 897 s                                                                                                                                                      |
| `REPAIR_UNREACHABLE_REFUSE_PCT`      | `10`                                               | Refuse an episode when the backend failed this percent (1 to 100) or more of the targets that reached it                                                                                                                                                                                                            |
| `REPAIR_MAX_CONSECUTIVE_UNREACHABLE` | `5`                                                | This many failures in a row count as an outage and end the episode                                                                                                                                                                                                                                                  |
| `REPAIR_TRANSPORT_RETRIES`           | `2` (0 to 5)                                       | Retries on the `openai` backend after a failure that is known to happen before the request is sent: connection refused, DNS, connect timeout. A read timeout or a dropped connection after sending is never retried, because the provider may already have the request. `0` turns it off                            |
| `REPAIR_KEEP_NAME_PARTS`             | `1`                                                | A name said alone stays alone, and a full name stays full. Repair refuses a proposal that adds or drops a name part next to a name the line already has, and adds one sentence about it to the prompt when the glossary lists names. `0` turns both off. See [stored verdicts](#stored-verdicts-and-prompt-changes) |
| `REPAIR_AUTO_DISMISS_WORDS`          | `6`                                                | A repair a guard refused that changes more than this many words is still written to the queue file, marked `dismissed`, but the primary review view skips it. `off` turns it off. Words added plus words dropped are counted, so re-spacing a known phrase counts as no change                                      |
| `REPAIR_ACCEPT_PUNCT_CASE_ONLY`      | _(off)_                                            | `1` lets a proposal that only **adds** a `.` or `,` (and makes a safe case change) skip the "one more visible character" layout check. It never accepts removed or changed punctuation. Added commas can still change meaning, so audit a sample before you rely on it                                              |
| `REPAIR_GUARD_TERMINAL_PUNCT`        | _(off)_                                            | `1` refuses a proposal that adds or removes a terminal `?`, swaps `!` and `?`, or turns a trailing ellipsis into `.` or `!`. On 451 real pairs it refused 21, and most of those were corrections, so it is off                                                                                                      |

**When repair refuses an episode.** Repair leaves the `.srt` as it was, records
`backend-unreachable`, and retries the episode on a later pass when:

- the backend failed `REPAIR_UNREACHABLE_REFUSE_PCT` percent or more of the targets that reached it,
- `REPAIR_MAX_CONSECUTIVE_UNREACHABLE` failures came in a row, or
- the episode ran past `REPAIR_EPISODE_DEADLINE`.

A failure is a connection error, a timeout, HTTP 401, 403, 408, 429 or 5xx, a missing or
malformed key, or (on the `openai` backend) an empty reply that hit the token limit. HTTP 400,
404, 409, 413 and 422 mean the model rejected that one request: the line keeps its transcript text
and is queued like an empty reply, with no retry. If every request of an episode is rejected that
way, the episode is refused, because the model id or the URL is probably wrong. These rules apply
to every backend, not only `openai`.

#### Stored verdicts and prompt changes

A human verdict is keyed on the pair of original line and proposed text. Anything that changes
what the model proposes can therefore leave an approved verdict that no longer matches. The line
is then recorded as `verdict_stale_proposal` and the new proposal is judged on its own merits.
Rejected verdicts are untouched, and an approved verdict that still matches keeps applying.

`REPAIR_KEEP_NAME_PARTS=1` adds a sentence to the repair prompt whenever the glossary lists names,
so the first repair of an already-reviewed episode can produce proposals that differ from the ones
you approved. It does not make a stamped episode repair again: the `.dubtitles.done` stamp holds
version numbers and never the prompt. Only an episode repaired again for another reason sees the
new wording. Set `REPAIR_KEEP_NAME_PARTS=0` to restore the old prompt.

### Punctuation restore

| Var                   | Default                            | Meaning                                    |
| --------------------- | ---------------------------------- | ------------------------------------------ |
| `RESTORE_PUNCTUATION` | `1`                                | Enable the punctuation-restore stage       |
| `RESTORE_MODEL`       | _(falls back to `REPAIR_MODEL`)_   | Model for this stage                       |
| `RESTORE_BACKEND`     | _(falls back to `REPAIR_BACKEND`)_ | Backend for this stage                     |
| `RESTORE_MIN_RUN`     | `2`                                | Minimum run of unpunctuated cues to act on |
| `RESTORE_MAX_TOKENS`  | `2048`                             | Generation cap                             |

### Glossary mining, acquisition and verification

| Var                  | Default                            | Meaning                                                                                                  |
| -------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `MINE_MIN_COUNT`     | `3`                                | Occurrences before a mined term is kept                                                                  |
| `ACQUIRE`            | `1`                                | Run the acquisition step (`gen_loop.sh`)                                                                 |
| `ACQUIRE_APPLY`      | `True`                             | Apply acquired proper nouns by default; explicit 0, false, no, off, or dry-run enables dry-run mode      |
| `ACQUIRE_MIN_COUNT`  | `3`                                | Occurrences before a candidate is considered                                                             |
| `ACQUIRE_MIN_SHARE`  | `0.80`                             | Share of occurrences that must agree                                                                     |
| `ACQUIRE_MIN_SIM`    | `0.72`                             | Similarity floor for a candidate match                                                                   |
| `ACQUIRE_UNSEEN_SIM` | `0.98`                             | Similarity above which a term counts as already known                                                    |
| `ACQUIRE_GROWTH_MAX` | `2`                                | Cap on glossary growth per pass                                                                          |
| `ACQUIRE_NO_CACHE`   | _(unset)_                          | Bypass the acquire cache on dry runs                                                                     |
| `VERIFY_MODEL`       | `qwen3:8b`                         | Adjudication model for wiki verification                                                                 |
| `VERIFY_BACKEND`     | _(unset)_                          | Backend for verification and acquisition. See [Decision backend](#decision-backend) for what unset means |
| `VERIFY_WORKERS`     | `4`                                | Concurrent wiki lookups                                                                                  |
| `WIKI_HTTP_TIMEOUT`  | `20`                               | Seconds                                                                                                  |
| `WIKI_CACHE_TTL`     | `2592000`                          | 30 days, in seconds                                                                                      |
| `WORDLIST_PATH`      | `/usr/share/dict/american-english` | The real-English-word gate                                                                               |

### Glossary write guards and the review queue

Verify turns a model's pick into one of three outcomes: a name written to the glossary, a flag
for a human, or a record that nobody sees. These variables choose which. The first two guards
were measured on 163 blind-judged writes from a rebuild of the One Pace glossary: unguarded, the
Jev decision backend wrote 87 expansions of which 45% were right; with both guards it wrote 29,
86% right, and sent 58 to the queue.

| Var                               | Default | Meaning                                                                                                                                                                                                                                                                                                                    |
| --------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VERIFY_WRITE_WHOLE_WORD`         | `1`     | An expansion (`Zoro` → `Roronoa Zoro`) is written only when the term is a whole word of the title and has at least two letters. Anything else is flagged `respelling-needs-review`. `0` restores the older substring rule, which wrote `Usop` → `Usopp` and `Burn` → `Coburn`                                              |
| `VERIFY_SKIP_COMMON_WORDS`        | `1`     | A one-word term that `WORDLIST_PATH` spells in lowercase (`castle`, `government`) is flagged `common-word` instead of written. Names the list capitalises (`Hancock`) are not affected. If the list cannot be read, the guard falls back to a 228-word list, logs it once, and the verify report shows `wordlist: missing` |
| `VERIFY_COMMON_WORD_ARC_RESCUE`   | _(off)_ | `1` lifts a common-word block when the title is on an arc page. On the audit set it let 58 of 99 wrong writes back in, because ordinary words sit on arc pages, so it stays off                                                                                                                                            |
| `VERIFY_QUEUE_NO_MATCH`           | `0`     | A term with no wiki candidate is recorded in `verified` and counted (`no_match` in the report) but not flagged. `1` flags each one. On the One Pace rebuild this removed 578 of 687 queue items, none of which carried a decision                                                                                          |
| `VERIFY_QUEUE_BLOCKED_EXPANSIONS` | `1`     | `0` records an expansion a guard blocked, when the title has **more tokens** than the term, without queuing it. A same-length respelling such as `Usop` → `Usopp` is always queued, because it is a spelling fix and not an added name part                                                                                |
| `VERIFY_REFUSE_EXIT`              | _(off)_ | `1` makes a refused `--tag-arcs`, verify or acquire run exit 2 instead of 0. `gen_loop.sh` treats any non-zero exit except 124 as "continuing", so inside the loop it only shows up in the log                                                                                                                             |

Two settings undo each other's work. `VERIFY_ARC_GATE=1` together with
`VERIFY_QUEUE_BLOCKED_EXPANSIONS=0` hides every name that misses an arc page from every human.
Setting `REPAIR_AUTO_DISMISS_WORDS` below 4 hides fixes a human would have accepted.

### Decision backend

With `VERIFY_BACKEND=decision`, verify asks a decision model to pick among the wiki candidates
instead of asking a chat model to write JSON. Each call sends the **show name, the term and the
candidate titles** to the provider; no dialogue leaves the machine. Acquire stays on the local
model unless you set `ACQUIRE_BACKEND=decision`.

| Var                             | Default                                                                               | Meaning                                                                                                                                                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VERIFY_BACKEND`                | _(unset)_                                                                             | `llamacpp`, `ollama`, `openai` or `decision`. Unset follows `REPAIR_BACKEND` only when that is `llamacpp` or `ollama`; with `REPAIR_BACKEND=openai` the stage **refuses** until you set it                                                                                  |
| `ACQUIRE_BACKEND`               | _(unset)_                                                                             | Backend for acquire's LLM calls. Unset, acquire follows `VERIFY_BACKEND`, except that when that is `decision` it uses the local backend: the decision model scored 47% against the local model's 72% on the blind acquire pairs. `ACQUIRE_BACKEND=decision` opts acquire in |
| `VERIFY_DECISION_MODEL`         | `inception/mercury-decide:free`                                                       | Decision model. The maintainer's install uses `typesafe/jev` through CommandCode, which is paid. Span models are refused: they score one candidate at a time                                                                                                                |
| `VERIFY_DECISION_URL`           | _(the provider's endpoint)_                                                           | Override the endpoint. It must be https and on the provider's host                                                                                                                                                                                                          |
| `VERIFY_DECISION_KEY_ENV`       | `OPENROUTER_JEV_API_KEY` for OpenRouter models, `COMMANDCODE_API_KEY` for CommandCode | The **name** of the variable that holds the key, never the key. Read at call time, never logged                                                                                                                                                                             |
| `VERIFY_DECISION_TAU`           | `0.5` (0 to 1)                                                                        | A pick at or above this confidence is `high` and may be written; below it, it is flagged                                                                                                                                                                                    |
| `ACQUIRE_DECISION_TAU`          | `0.8` (0.5 to 1)                                                                      | The same threshold for acquire's same-entity question                                                                                                                                                                                                                       |
| `VERIFY_DECISION_FALLBACK`      | `none`                                                                                | `none`: a failed call leaves the term pending for the next sweep. `local`: the local model decides instead                                                                                                                                                                  |
| `VERIFY_DECISION_LOCAL_BACKEND` | `REPAIR_BACKEND` if that is `llamacpp` or `ollama`, else `ollama`                     | The local backend the fallback uses                                                                                                                                                                                                                                         |
| `VERIFY_DECISION_BREAKER`       | `5` (0 to 1000)                                                                       | After this many failed terms in a row the provider is not called again this run. `0` turns the breaker off                                                                                                                                                                  |
| `VERIFY_DECISION_WORKERS`       | `1` (1 to 16)                                                                         | Concurrent decisions. One keeps a rate limit from multiplying                                                                                                                                                                                                               |
| `VERIFY_DECISION_RETRIES`       | `0` (0 to 5)                                                                          | Retries after a 429 or 5xx inside one call. The next sweep retries anyway                                                                                                                                                                                                   |
| `VERIFY_OPENAI_URL`             | _(unset)_                                                                             | Chat-completions URL for `VERIFY_BACKEND=openai`                                                                                                                                                                                                                            |
| `VERIFY_OPENAI_KEY_ENV`         | _(unset, no default name)_                                                            | The name of the variable that holds that key                                                                                                                                                                                                                                |
| `VERIFY_OPENAI_EXTRA_BODY`      | _(unset)_                                                                             | JSON object merged into the request body                                                                                                                                                                                                                                    |

At the end of a run verify prints one line, for example
`decision backend: model=typesafe/jev calls=986 ok=985 failures=1 fallbacks=0 pending=1`.

### Arc tags and wiki scope

The arc stage fetches the wiki pages for each arc (or, for shows with no arc names, a scope you
configure) and stores the titles in the glossary. Names are then tagged with their arcs, which
puts the current arc's names first in the repair prompt, and the titles can gate verify's writes.
See [Glossary file](#glossary-file) for the stored keys.

| Var                 | Default                     | Meaning                                                                                                                                                                                                                                                             |
| ------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GLOSSARY_ARC_TAGS` | `0` (read by `gen_loop.sh`) | `1` runs `glossary_verify.py --tag-arcs` for each show, between acquire and verify                                                                                                                                                                                  |
| `ARC_TAGS_TIMEOUT`  | `600`                       | Seconds one `--tag-arcs` run may take                                                                                                                                                                                                                               |
| `ARC_MIN_TITLES`    | `10`                        | An arc with fewer wiki titles counts as missing. The smallest real One Piece arc has 38                                                                                                                                                                             |
| `VERIFY_ARC_GATE`   | _(off)_                     | `1` flags a would-be write whose title is on no arc page (`not-in-arc-pages`). It does nothing, and says so once, unless every arc of the show has stored titles with finished redirects. On the audit set it blocked 45 of 119 wrong writes and 8 of 42 right ones |
| `WIKI_HOST_ALLOW`   | _(unset)_                   | Comma-separated extra hosts `wiki_scope` may fetch. Built in: `fandom.com` and `bulbapedia.bulbagarden.net`                                                                                                                                                         |
| `WIKI_ALLOW_HTTP`   | _(unset)_                   | `1` lets `glossary_verify` fetch an `http://` wiki, for tests. `wiki_scope` is always https                                                                                                                                                                         |

Every wiki fetch is https-only. A redirect to another scheme is refused before the request is made.

### Glossary locks

| Var                              | Default | Meaning                                                                                                                                                            |
| -------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GLOSSARY_LOCK_WAIT`             | `5`     | Seconds an unattended stage waits for a busy glossary. After that it logs `glossary busy: <stage> skipped` and exits 0, so the nightly loop never waits on a human |
| `GLOSSARY_LOCK_WAIT_INTERACTIVE` | `600`   | Seconds a human's `--review`, `--revert` or `--prune-no-match` waits for the final write. On a timeout the answers are saved and applied at the next `--review`    |

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

The muxed `Dubtitles` track is appended last and flagged default, so the relative order of the other subtitle tracks is unchanged while players pick it up through the default flag. An MP4 or M4V source is removed only after the remuxed MKV verifies and the stamp writes. If the stamp write itself fails, the new MKV is rolled back and the original file is left untouched, so a failed run always leaves something complete on disk. Plex reads `.ass` sidecars and renders styling and positioning on direct-play clients; transcoding clients burn them in.

### Review server

| Var                     | Default                | Meaning                                                                                                                                           |
| ----------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `REVIEW_PORT`           | `8842`                 | Listen port. Editable in Settings > General; requires container restart                                                                           |
| `REVIEW_BIND`           | `0.0.0.0`              | Listen address. Editable in Settings > General; requires container restart                                                                        |
| `REVIEW_TOKEN`          | _(retired for web UI)_ | Retired for browser access. On initial startup without an API key file, an existing value is imported once into `/config/apikey` and then retired |
| `REVIEW_AUTH`           | _(unset)_              | Set to `off` to disable authentication entirely (see Authentication)                                                                              |
| `REVIEW_MAX_CONCURRENT` | `16`                   | Concurrent request cap                                                                                                                            |
| `REVIEW_STEMS_TTL`      | `30`                   | Seconds an episode listing is cached                                                                                                              |
| `REVIEW_RESTART`        | `15`                   | Seconds before restarting the server after an exit                                                                                                |

### Ordering and watch queue

| Var                                        | Default                     | Meaning                                                                                                                                                                                                                   |
| ------------------------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LIBRARY_SWEEP`                            | `True`                      | When True (default), loops sweep the whole library. When False, generator processes only queued requests and merge pass covers shows with requests pending, running, or finished in the last 7 days (Settings > Schedule) |
| `SEASON_START`                             | `0`                         | Global watch-order start season                                                                                                                                                                                           |
| `SEASON_PRIORITY_FILE`                     | _(unset)_                   | Per-show start seasons                                                                                                                                                                                                    |
| `WATCH_QUEUE_WINDOW_DAYS`                  | _(unset: step skipped)_     | Days of watch history to consider                                                                                                                                                                                         |
| `WATCH_QUEUE_PIN`                          | _(unset)_                   | Always queue this show first, watched or not                                                                                                                                                                              |
| `WATCHSTATE_URL` / `WATCHSTATE_API_KEY`    | _(empty)_                   | WatchState source                                                                                                                                                                                                         |
| `PLEX_URL` / `PLEX_TOKEN` / `PLEX_SECTION` | _(empty)_ / _(empty)_ / `7` | Plex refresh and watch source                                                                                                                                                                                             |
| `PLEX_PATH`                                | _(empty)_                   | Path prefix Plex sees, if it differs                                                                                                                                                                                      |

**How a watched show finds its folder:** by the show's TVDB id first — WatchState's
`parent.guid_tvdb`, or the `tvdb://` Guid on the Plex show — against the `{tvdb-N}` in the
folder name. Without an id it falls back to the title: exact, then with the `(YYYY)` kept,
then with it stripped, then case/punctuation-insensitive. A title two folders share (e.g.
`JoJo's Bizarre Adventure` for both the 1993 and 2012 series) is reported as unmatched, never
guessed — so name your folders `Title (YYYY) {tvdb-N}` and the id settles it.

### Loop cadence

| Var                                        | Default                | Meaning                                                                                                                                                  |
| ------------------------------------------ | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MERGE_INTERVAL`                           | `600`                  | Seconds between merge passes                                                                                                                             |
| `MERGE_WINDOW`                             | _(empty, always)_      | Hours a merge sweep may run, `HH:MM-HH:MM`. May cross midnight. The end is exclusive. Set it when the repair backend is only up part of the day          |
| `STOP_FLAG`                                | `/tmp/dubtitlerr.stop` | File the entrypoint creates on SIGTERM or SIGINT. While it exists, loops stop starting work. Deleted at startup. Unset (manual runs), nothing ever stops |
| `RESCAN_INTERVAL`                          | `21600`                | Idle seconds after a full generate sweep                                                                                                                 |
| `ACQUIRE_TIMEOUT`                          | `1800`                 | Seconds                                                                                                                                                  |
| `VERIFY_TIMEOUT`                           | `1200`                 | Seconds                                                                                                                                                  |
| `LLM_TIMEOUT_CONNECT` / `LLM_TIMEOUT_READ` | `10` / `120`           | Seconds                                                                                                                                                  |

---

## Settings pages

Every environment variable the pipeline reads has a row under **Settings** in the web UI, in nine categories: General, Library, Transcription, Glossary, Repair, Connections, Output, Schedule and Connect. `#/settings` shows one card per category. `#/settings/<category>` shows the rows of that category.

The first-wave rows are editable. Every other row shows its value and why it cannot be changed here: "Set in the container environment" for the values the container fixes, "Set through a Connection", "Retired: no longer read", or "edit in a later release". For a signed-in user who is not an admin, the rows that would be editable are read-only and say "Only an admin can change settings". **Show Advanced** in the toolbar reveals the rows that rarely change. The bootstrap values always list, under General.

Where a value comes from, in order: what you saved in the UI (**Set here**), else the container's environment (**From the container**), else the built-in default (**Default**). A saved value that hides an environment value reads "Overrides the container value". Resetting a row removes your saved value, so the container value or the default applies again.

Saved values live in `$CONFIG_DIR/settings.json` (values, Connections and stage choices) and `$CONFIG_DIR/secrets.json` (the secrets, mode 0600). Each save keeps one `.prev` copy of each file and writes one log line that names the keys and never a secret value.

| A row says       | The change applies                                                                                                                                                                                                                                                                        |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| nothing special  | at the next show, sweep or merge pass, never in the middle of an episode                                                                                                                                                                                                                  |
| Restart required | after the builder restarts. The rows you can change that need one are the web port and address, the merge interval and window, the webhook token and path mappings. The read-only rows carry the same badge, for example the sign-in values, the container paths and the tool thresholds. |

After a save that changed a restart-only row the page offers **Restart Now** and **Restart Later**. Restart Now asks the builder to finish the episode in flight and stop. Restart Later leaves a "Restart pending" banner until the next start. The banner appears whenever a saved restart-only value is not running yet. The container comes back only with a restart policy of `unless-stopped` or `always`, and the supplied `compose.yaml` sets `unless-stopped`.

**Connections** are named LLM servers: a kind (llama.cpp, Ollama or OpenAI-compatible), a URL, a model, a second model for repair, an extra request body and connect and read timeouts. Each stage (repair, restore, verify, decision, acquire) picks one. A stage with no Connection keeps the container's own settings. Only an admin can save them or run Test.

Rules a saved Connection obeys:

- The URL must not carry a query or a fragment. Tokens belong in a secret field.
- Addresses in 169.254.0.0/16 and fe80::/10 are refused, and so are the cloud metadata addresses 100.100.100.200 and fd00:ec2::254. Loopback and LAN addresses are fine.
- An API key is write-only. You can set it or clear it, and nothing ever shows it again. It is 8 to 512 characters on one line. Only an OpenAI-compatible Connection holds one, and it is only sent over https, or to a loopback host.
- The extra request body is write-only too. The page shows Set or Not set and a Replace body field. Only an OpenAI-compatible Connection carries one.
- Changing a URL or a kind clears the stored key unless you enter the key in the same save.
- The decision stage accepts only the hosts the decision client calls: openrouter.ai, api.commandcode.ai, or loopback.
- **Test** asks the server to probe a saved Connection with its own timeouts.

Secrets (the Plex token, the WatchState key, the webhook token and Connection keys) are entered only by a signed-in admin. Until login is enabled the page shows "available after login is enabled" and a plain set or not set.

The first start after the upgrade imports the keys an existing `runtime.env` carried: `REPAIR_MODEL`, `VERIFY_BACKEND`, `VERIFY_DECISION_MODEL`, `REQUIRE_ENG` and `ACQUIRE_APPLY`. A `REPAIR_PROFILE` choice becomes the repair stage. The old `RUNTIME_VERIFY_BACKENDS` and `RUNTIME_DECISION_MODELS` opt-in filter still applies to what is imported. The file is renamed `runtime.env.migrated`, or an empty one is written so the import runs once. Under its own `profiles.migrated` marker, each `REPAIR_PROFILES` entry becomes a Connection. `REPAIR_PROFILES`, `RUNTIME_VERIFY_BACKENDS` and `RUNTIME_DECISION_MODELS` are retired: nothing reads them after that, and General lists them while they are still set.

---

## Glossary file

`$GLOSSARY_DIR/<Show folder name>.json`. Keys not listed here are ignored on load. The wiki-verifier is reusable on its own: it makes any mined or community-submitted glossary as accurate as a hand-curated one.

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
  "flagged": { "Raftel": { "reason": "respelling-needs-review", "canonical": "Ratel" } }
}
```

| Key                  | Type   | Meaning                                                                                                                                                                   |
| -------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `show`               | string | Display name, used in prompts                                                                                                                                             |
| `wiki`               | string | MediaWiki API URL override (editable on the Glossary page with admin Test verification; empty auto-detects)                                                               |
| `initial_prompt`     | string | Passed to Whisper. **Measured to make no difference** to output; kept for compatibility                                                                                   |
| `unanchored_repair`  | bool   | `true` when your copies of this show carry no English subtitles for the Japanese audio                                                                                    |
| `names`              | list   | Proper nouns                                                                                                                                                              |
| `phrases`            | list   | Multi-word terms                                                                                                                                                          |
| `hard_fixes`         | object | Exact replacements. A key containing a space is matched as a phrase, otherwise as a token. Keys are lowercased on load                                                    |
| `verified`           | list   | Verifier bookkeeping                                                                                                                                                      |
| `flagged`            | object | Terms a human still has to decide, or that the verifier could not confirm. Each value is a reason string or an object `{"reason", "canonical", ...}`. See the table below |
| `known`              | list   | Terms a human marked correct as they stand                                                                                                                                |
| `acquired`           | object | Provenance of each name acquisition or a human review wrote                                                                                                               |
| `arc_titles`         | object | Arc name (or `scope:<rung>:<season>`) to the wiki titles stored for it. Written by `--tag-arcs`                                                                           |
| `arc_coverage`       | object | Per arc: how many titles, whether redirects finished, whether it is waived or stale. The gate trusts this                                                                 |
| `arc_titles_missing` | list   | Arcs whose fetch came back empty, partial or under `ARC_MIN_TITLES`. While it is non-empty the arc gate does nothing                                                      |
| `arc_tags`           | object | Lower-cased name to the arcs it belongs to                                                                                                                                |
| `arc_aliases`        | object | `{"Water Seven": "Water 7"}`: the wiki page to fetch for a season whose arc has another name. You write it                                                                |
| `arc_waived`         | list   | Seasons you accept as covered with no wiki titles, such as seasons that are not arcs. You write it                                                                        |
| `wiki_scope`         | object | Scope for a show with no arc names. See [Wiki scope](#wiki-scope)                                                                                                         |

**Flag reasons.** What a human sees in `glossary_acquire.py --review`:

| Reason                      | What it asks                                                                                                    | `y` does                            |
| --------------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `respelling-needs-review`   | The model picked a different spelling, or a same-length expansion the whole-word guard refused                  | Writes the fix                      |
| `common-word`               | An ordinary one-word term the model wants to expand                                                             | Writes the expansion to `phrases`   |
| `not-in-arc-pages`          | The title is on no arc page (only with `VERIFY_ARC_GATE=1`)                                                     | Writes the expansion to `phrases`   |
| `expansion-guarded`         | An expansion a guard blocked, shown only when `VERIFY_QUEUE_BLOCKED_EXPANSIONS=1` and the title has more tokens | Writes the expansion to `phrases`   |
| `low-confidence`            | The model had a candidate and was not sure                                                                      | Accepts the candidate               |
| `possessive_floor_crossing` | A possessive form that crossed the mining floor                                                                 | Keeps both forms                    |
| `no-match`                  | No candidate. Not queued unless `VERIFY_QUEUE_NO_MATCH=1`                                                       | Marks the term correct as it stands |

`--review` lists decisions first, in that order, and collapses the no-match terms into one line;
`--review --all` lists them too, and `--review --prune-no-match` removes the stored ones.
An answer is applied only to the proposal the human saw: if the term was flagged again with a
different canonical before the answer could be written, the answer is skipped and logged.

### Wiki scope

A show whose seasons carry no arc names (Naruto, Pokémon, a one-season show) gets its spelling
universe from a `wiki_scope` block in its glossary. `--tag-arcs` resolves one scope per library
season, or one for the whole show, and stores only **complete** results: a failed request, a
partial listing or an unparseable table stores nothing. The library files need an `SxxExx` tag in
their names for the season and episode scopes.

| Rung          | Reads                                                                                                                                       | Use for                                           |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `arc_index`   | An index page with one table per part (arc, chapters, episodes). Library episodes are mapped to the table's numbering with `season_offsets` | Naruto, Naruto Shippuden                          |
| `season_page` | One wiki page per season, with episode codes and episode titles dropped                                                                     | Pokémon (`S01` to `S25` on Bulbapedia)            |
| `whole_wiki`  | Every page of the wiki, with chapter, volume and episode pages dropped                                                                      | One-season shows (Marriagetoxin, Chainsmoker Cat) |

```json
{
  "wiki_scope": {
    "rung": "arc_index",
    "wiki": "https://naruto.fandom.com/api.php",
    "index_page": "Plot of Naruto",
    "part": "Part II",
    "season_offsets": { "2": 32, "3": 53 }
  }
}
```

A whole-wiki scope tags no names and is left out of the arc gate's universe, because it contains
every page verify could propose. Do not rely on a wiki's `Category:Characters`: Chainsmoker Cat's
has one member of 33. The full key list is in the docstring of `wiki_scope.py`.

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

## Review server routes

The review server is started by `container_run.sh` and listens on `REVIEW_BIND` and `REVIEW_PORT` (default `0.0.0.0:8842`).
Access is controlled by `ROUTE_ROLES`. Every route requires a specific role: `public`, `user`, or `admin`. Unlisted routes fail closed and require `admin`.

| Method | Path                      | Role      | Purpose                                                                  |
| ------ | ------------------------- | --------- | ------------------------------------------------------------------------ |
| GET    | `/healthz`                | `public`  | Health check probe                                                       |
| GET    | `/api/auth-mode`          | `public`  | Return setup_required and accounts_ok status                             |
| POST   | `/api/login`              | `public`  | Authenticate with username and password; sets session cookie             |
| POST   | `/api/setup`              | `public`  | Create initial administrator account (409 if already set up)             |
| GET    | `/review`, `/review/*`    | `public`  | Single-page application assets and review workspace                      |
| POST   | `/api/webhook/sonarr`     | `public`* | Sonarr webhook receiver (*requires `WEBHOOK_TOKEN` header or query)      |
| POST   | `/api/webhook/radarr`     | `public`* | Radarr webhook receiver (*requires `WEBHOOK_TOKEN` header or query)      |
| GET    | `/`, `/index.html`        | `user`    | Classic review page; `?stem=<episode>` filters to one episode            |
| GET    | `/shared`                 | `user`    | Lines appearing in two or more episodes                                  |
| GET    | `/api/audio`              | `user`    | Audio dialogue clip playback for cue review                              |
| GET    | `/api/episodes`           | `user`    | List episodes with pending review items                                  |
| GET    | `/api/shows`              | `user`    | List library shows                                                       |
| GET    | `/api/episode`            | `user`    | One episode's queue in decision order                                    |
| POST   | `/api/decide`             | `user`    | Record human verdicts on episode cues                                    |
| GET    | `/api/shared`             | `user`    | Repair pairs occurring across multiple episodes                          |
| POST   | `/api/shared`             | `user`    | Record verdicts on shared lines                                          |
| POST   | `/api/apply`              | `user`    | Rewrite subtitle and drop done stamp for re-mux                          |
| GET    | `/api/requests`           | `user`    | List queued and recent run requests                                      |
| GET    | `/api/schedule`           | `user`    | Read schedule window configuration                                       |
| GET    | `/api/settings`           | `user`    | Read effective settings values                                           |
| GET    | `/api/settings/schema`    | `user`    | Read settings registry schema metadata                                   |
| GET    | `/api/status`             | `user`    | Read builder status, active sweeps, and heartbeat                        |
| GET    | `/api/glossary`           | `user`    | List glossary shows or read one show glossary                            |
| POST   | `/api/glossary`           | `user`*   | Add, update, or delete glossary terms (*editing `wiki` requires `admin`) |
| GET    | `/api/me`                 | `user`    | Return authenticated username and role                                   |
| PUT    | `/api/me/password`        | `user`    | Self-service password change for currently signed-in user                |
| POST   | `/api/logout`             | `user`    | End session and revoke session token                                     |
| POST   | `/api/glossary/wiki-test` | `admin`   | Probe MediaWiki siteinfo for a wiki URL override                         |
| POST   | `/api/requests`           | `admin`   | Enqueue a new run request                                                |
| PUT    | `/api/schedule`           | `admin`   | Update schedule window settings                                          |
| PUT    | `/api/settings`           | `admin`   | Save setting values, connections, and stage assignments                  |
| POST   | `/api/settings/reset`     | `admin`   | Reset settings to environment or built-in defaults                       |
| POST   | `/api/settings/test`      | `admin`   | Test an LLM connection endpoint                                          |
| POST   | `/api/system/restart`     | `admin`   | Trigger a soft stop and restart of the builder container                 |
| GET    | `/api/apikey`             | `admin`   | Retrieve current administrator API key                                   |
| POST   | `/api/apikey/reset`       | `admin`   | Rotate administrator API key                                             |
| GET    | `/api/users`              | `admin`   | List user accounts and roles                                             |
| POST   | `/api/users`              | `admin`   | Create a new user account                                                |
| PUT    | `/api/users/*`            | `admin`   | Update a user's role or password                                         |
| DELETE | `/api/users/*`            | `admin`   | Delete a user account                                                    |

### Authentication and security

Authentication uses role-based access control with two roles: `admin` and `user`.

- **User sessions:** Browsers authenticate against scrypt password hashes in `$CONFIG_DIR/users.json`. A successful login sets an HttpOnly, SameSite=Strict session cookie backed by `$CONFIG_DIR/sessions.json`.
- **CSRF protection:** Browser state-changing requests (POST, PUT, DELETE) must provide an `X-DubTitlerr-Request: 1` header. Origin headers are validated against Host and X-Forwarded-Host headers.
- **Admin API key:** Automation scripts send the `X-Api-Key` header instead of browser cookies. The key is stored with mode 0600 at `$CONFIG_DIR/apikey`.
- **First-run setup:** When no accounts exist, unauthenticated requests to protected routes return 409, directing browsers to `/review/setup`. Setting `REVIEW_USERNAME` and `REVIEW_PASSWORD` (or `REVIEW_PASSWORD_FILE`) automatically creates the initial admin account at first boot.
- **Disabling authentication:** Setting `REVIEW_AUTH=off` disables role checks on all routes and treats all requests as administrator. Only use this on a private, trusted network.
- **Audit logging:** Actions that modify settings, connections, accounts, glossaries, or trigger container restarts write log lines that explicitly name the acting user or API key principal.
