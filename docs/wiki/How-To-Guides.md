# How-to guides

Recipes. Each solves a single problem and assumes a working install — if you do not have
one, start with [Your first show](Your-First-Show.md).

---

## Turn on unanchored repair for a dub-only show

**Problem:** your copies have an English dub but **no English subtitle track for the Japanese
audio**. The repair stage has nothing to anchor against, refuses every line, and mangled
names stay on screen.

**Check whether this is you.** List an episode's subtitle tracks:

```sh
ffprobe -v error -select_streams s \
  -show_entries stream=index:stream_tags=language,title \
  -of default=noprint_wrappers=1 "Show - S01E01.mkv"
```

An English track carrying full dialogue means you are anchored and should **not** do this. A
_Signs and Songs_ track only counts as no reference.

> Seasons of one show can differ. Check the season you are about to process.

**Do it.** Add one key to that show's glossary file:

```json
{
  "show": "Show Name",
  "unanchored_repair": true,
  "names": ["..."]
}
```

The next repair pass sends glossary-only prompts for unanchored lines instead of skipping
them.

**Know the trade.** Glossary-only repair can fabricate names — measured turning `Oimo` into
`Zoro`. Review the results rather than turning this on and walking away. Reasoning:
[Why it works this way](Why-It-Works-This-Way.md#anchored-and-unanchored-repair).

There is also a global `REPAIR_UNANCHORED` variable. It has been deployed library-wide
on the reference install since 2026-09-06 (see `common.py`'s v10 changelog note) --
every show without an explicit `unanchored_repair` field in its glossary is repaired
unanchored by default there. **Prefer the per-show glossary field for any new
install**: it is committed to git and reviewable, where the global flag is host
configuration that a `git pull` cannot show you. If an unanchored repair ships
something wrong, the recovery is a `reject` verdict recorded with `decisions.record`
followed by `review_apply.py`, not disabling the flag.

---

## Queue a whole library, in watch order

**Problem:** the default order spends hours on seasons you watched years ago before reaching
the arc you are on.

**Choose the shows and their order** in `/config/anime_order.txt`, one folder name per line.
`#` comments and blanks are ignored:

```
One Pace (1999)
Cowboy Bebop (1998)
# Trigun (1998)   <- queued but paused
```

**Jump to where you actually are** with `/config/season_priority.txt`:

```
# Show folder name : start season
One Pace (1999):20
```

Seasons at or after the start go first, ascending; earlier ones wrap around after. The same
episodes, resequenced so the next arc lands soonest.

**This file has no default path.** Point at it explicitly:

```yaml
SEASON_PRIORITY_FILE: /config/season_priority.txt
```

Without that variable the log says `watch-order disabled` and the file is never read.
`SEASON_START` is a global fallback for when you have no per-show file.

When you move further along, bump the number and restart the container.

---

## Redo an episode from scratch

The pipeline never reads its own previous output here: stages that look at embedded subtitles skip the track named `Dubtitles`, and the mux replaces the old `Dubtitles` track in the same pass that adds the new one, so re-running needs no separate strip step for the old track.

Library-wide regeneration follows the pipeline's version stamps, `TRANSCRIBE_VERSION` and `TEXT_VERSION` in `common.py`. When a release raises one, episodes whose stamp records an older version are redone on later sweeps and their track is replaced in place; a failed run leaves the old track untouched. The [CHANGELOG](https://github.com/XenaRathon/DubTitlerr/blob/main/CHANGELOG.md) says which releases changed them.

Delete its sidecars and completion stamp:

```sh
rm "Show - S01E05".dubtitles.done \
   "Show - S01E05".eng.dubtitles.srt \
   "Show - S01E05".eng.dubtitles.ass \
   "Show - S01E05".dubtitles.conf.json
```

The next sweep re-transcribes it.

**To redo only the text, not the audio pass**, keep `.dubtitles.words.json`. Word-level
confidences live there, so the text tier replays without the GPU.

**This does not remove the already-muxed track.** To strip it from the video first:

```sh
mkvmerge -o out.mkv --subtitle-tracks '!<id>' in.mkv
```

---

## Recover an episode that crashed

**Problem:** one episode is skipped every sweep.

A hard crash leaves a poison marker so the pipeline does not loop on it:

```sh
ls  "Show - S01E05".dubtitles.fail
cat "Show - S01E05".dubtitles.crash.json
```

The crash file names the exception. When you have dealt with it — or want to try anyway —
delete the marker:

```sh
rm "Show - S01E05".dubtitles.fail
```

From 0.2.2, stopping the container with `docker stop` no longer leaves this marker, so one now
means a real crash. A SIGKILL or a power cut during transcription can still leave one. See
[Stop the container without losing work](#stop-the-container-without-losing-work).

---

## Stop the container without losing work

**Problem:** you stop the container on a schedule or by hand, and an episode that was being
transcribed is skipped from then on.

Before 0.2.2 the entrypoint ignored SIGTERM. `docker stop` waited out its grace period while the
loops kept starting new episodes, then sent SIGKILL. The episode killed mid-transcription kept
its `.dubtitles.fail` marker, so every later sweep skipped it. From 0.2.2 the container stops
softly: it starts no new work, lets the unit already running finish, and exits 0.

1. Set the grace period above your longest single unit of work. That is one episode's
   transcription, or one mux including a cross-device copy. Start with 900 seconds and tune it
   from your logs, using the time between episode start lines and the mux timestamps.

   ```sh
   docker stop -t 900 dubtitle-builder
   ```

2. Check how it ended. The exit code is 0 after a soft stop and 137 if the grace ran out and
   SIGKILL landed. The container log ends with `soft stop complete`.

   ```sh
   docker inspect -f '{{.State.ExitCode}}' dubtitle-builder
   ```

If you run a nightly window, `deploy/` has the systemd units for it. `dubtitlerr-window-open`
runs `docker start` at 00:00 and `dubtitlerr-window-close` runs `docker stop -t 900` at 10:00
(America/New_York), each from its own timer. The close unit logs the exit code, prints a warning
when it is not 0, and deletes orphan `*.muxtmp.mkv` files. It skips any episode that has a
`.dubtitles.mux-recovery` marker. The units use the author's container name and library path, so
edit those and the times before you install them.

Releases up to 0.2.2 check the stop flag only before a glossary step starts, so an acquire step
that is already running ends at its own end or at `ACQUIRE_TIMEOUT`. Set the grace period
accordingly or stop between steps.

---

## Resolve a mux recovery marker

**Problem:** the merge pass reports `recovery pending` for an episode and will not touch it.

For an `.mkv` source, the muxed file replaces the original. When the rename crosses
filesystems, mux falls back to a copy that overwrites the episode in place. If that copy fails
partway, the episode file may be damaged and the temp file may be the only complete copy. Mux
then keeps the temp file as `<episode>.muxtmp.mkv.recovered`, writes
`<episode>.dubtitles.mux-recovery`, and skips that episode on every pass until you resolve it.
Each pass reports `MERGE PASS INCOMPLETE` while the marker exists.

1. Read the marker. The `kept` field is the path of the complete copy.

   ```sh
   cat "Show - S01E05".dubtitles.mux-recovery
   ```

2. Check that the kept file plays and has the tracks you expect.

   ```sh
   ffprobe "<the path from kept>"
   ```

3. Move the kept file over the episode's `.mkv`, then delete the marker.

   ```sh
   mv "<the path from kept>" "Show - S01E05.mkv"
   rm "Show - S01E05".dubtitles.mux-recovery
   ```

If the kept file does not play either, restore the episode from your own copy of the release and
delete the marker. The next pass treats the episode like any other.

---

## See why an episode was not muxed

**Problem:** an episode has an `.srt` but never gets muxed.

Each stage records its outcome beside the video:

```sh
cat "Show - S01E05".dubtitles.stages.json
```

Read the stages in order (`repair`, `signs`, `mux`). The first one with a failed outcome is the
reason mux was skipped. [Stage outcomes](Reference.md#stage-outcomes) lists which outcomes count as
failures. The merge pass log has a matching `skip mux:` line, for example
`skip mux: repair failed (...)`.

Fix the cause. You do not need to delete anything: the merge pass clears a stage's record before
it runs that stage again, and a failed episode is retried on every pass.

---

## Hold a show until you have reviewed it

**Problem:** you do not want unreviewed output written into videos for a show you care about.

```yaml
REVIEW_GATE_SHOWS: "One Pace (1999):Cowboy Bebop (1998)"
```

Colon-separated **directory** names. Those episodes are transcribed and repaired as usual but
are **not muxed** until their review queue is settled.

A hold older than `REVIEW_GATE_STALE_DAYS` (default 7) is reported loudly and **stays held**.
The timer buys a warning, never a release — auto-releasing unreviewed output is the thing
the gate exists to prevent.

Empty by default: an install that has not opted in behaves exactly as before.

---

## Fix a repair stage that silently does nothing

**Problem:** the pipeline runs, the log shows repair targets, and every line comes back
unchanged. No errors.

**Check the model is actually replying:**

```sh
curl -s http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Reply with the word ok"}],"max_tokens":8}' \
  | python3 -m json.tool
```

Look at `choices[0].message`. Two failures look identical from the pipeline's side:

| What you see                              | Cause                                   | Fix                                                                    |
| ----------------------------------------- | --------------------------------------- | ---------------------------------------------------------------------- |
| `content` empty, `reasoning_content` full | The model is thinking and never answers | `--jinja` **and** `--chat-template-kwargs '{"enable_thinking":false}'` |
| `content` empty, nothing else             | The chat template was never applied     | `--jinja`                                                              |

**`--jinja` is required** for `chat_template_kwargs` (specifically `enable_thinking:false`,
which `repair.py` always sends) to take effect at all. Without it the server loads, answers
`/health` with `200`, and a thinking-capable model — `qwen3-4b-instruct`, the default,
included — spends its whole budget on reasoning and returns empty content forever.

Do not use `/health` as a readiness check. It reports `200` while weights are still
loading. Ask for a real completion instead, as above.

---

## Repair with a hosted model

**Problem:** you have a key for an OpenAI-compatible API and want repair to use it instead of a
model you serve yourself.

**Know where your text goes.** Every repair request carries the dub line, the lines around it,
the glossary names and the overlapping fansub line. All of it goes to the provider. Read the
provider's data terms before you point a real library at it.

**1. Pick a model that answers in one short line.** Repair asks for one corrected line. A model
without reasoning works best, or one whose reasoning you can switch off. A reasoning model that
spends its whole token budget thinking returns empty content, and repair counts that as the
backend being unreachable.

**2. Give the container the key by name.** Put the key in an environment variable on the host
and pass that variable through. `REPAIR_OPENAI_KEY_ENV` holds the variable's _name_; the key
itself stays out of config files, command lines and logs.

```yaml
environment:
  REPAIR_BACKEND: openai
  REPAIR_OPENAI_URL: https://api.example.com/v1/chat/completions
  REPAIR_MODEL: vendor/model-x
  REPAIR_OPENAI_KEY_ENV: EXAMPLE_API_KEY
  EXAMPLE_API_KEY: ${EXAMPLE_API_KEY}
```

Compose fills `${EXAMPLE_API_KEY}` from your shell or from a `.env` file beside `compose.yaml`.

**3. Switch reasoning off if the model reasons.** Put the provider's switch in
`REPAIR_EXTRA_BODY`. The switch differs by provider, so read the provider's documentation. As
one example, LongCat's API accepts `{"thinking":{"type":"disabled"}}`.

**4. Try a few lines before a whole episode.** `tools/bakeoff.py` sends real target lines from
one episode to the model and scores each reply with repair's own gate:

```sh
python3 tools/bakeoff.py --conf "<stem>.dubtitles.conf.json" \
    --glossary "glossaries/<Show>.json" \
    --openai-url https://api.example.com/v1/chat/completions \
    --key-env EXAMPLE_API_KEY \
    --extra-body '{"thinking":{"type":"disabled"}}' \
    --models vendor/model-x --limit 12
```

It ends with a table of results. If most lines come back as `<EMPTY ...>` or `<ERROR ...>`, fix
that first. `<ERROR rate-limited ...>` means the provider is throttling you, and
`<ERROR truncated ...>` means the model ran out of tokens before it answered, so reasoning is
still on or `REPAIR_MAX_TOKENS` is too low.

**5. Run one episode and read the summary.** Queue one show and wait for repair to finish an
episode. Then open `<stem>.dubtitles.repair-summary.json`. Repair worked when `unreachable` is
`0` and `repaired` is above `0`. `llm_empty` counts the targets the model answered with nothing,
and `rejected_4xx` counts the ones the provider refused as a request. `<stem>.dubtitles.stages.json`
shows the stage as `ok`.

**6. If repair refuses an episode.** The stage shows `backend-unreachable` and the `.srt` is
left as it was. The log says why: too many failed targets, too many in a row, or the episode
deadline. [When repair refuses an episode](Reference.md#repair) lists each rule and its
variable. The episode is tried again on the next pass.

---

## Use a decision model for glossary verification

**Problem:** the local model that checks glossary names against the wiki picks wrong titles. On a
rebuild of the One Pace glossary it wrote 106 expansions, 13 of them right. A decision model picks
among the wiki's candidates and reports how confident it is; on the same audit it wrote 87
expansions, 38 of them right.

**Know where your text goes.** Each decision sends the **show name, the term and the candidate
wiki titles** to the provider. No dialogue goes. CommandCode's `typesafe/jev`, the model the
maintainer uses, bills per call; OpenRouter's `inception/mercury-decide:free` does not, and in
testing it wrote few names, most of them right.

**1. Give the container the key by name.** The key lives in a host environment variable. Config
carries only the variable's name.

```yaml
environment:
  VERIFY_BACKEND: decision
  VERIFY_DECISION_MODEL: typesafe/jev
  COMMANDCODE_API_KEY: ${COMMANDCODE_API_KEY}
```

`VERIFY_DECISION_KEY_ENV` defaults to `COMMANDCODE_API_KEY` for CommandCode models and
`OPENROUTER_JEV_API_KEY` for OpenRouter ones. Set it only when you use a different name.

**2. Try it on a copy.** Verify rewrites the glossary it is given.

```sh
cp "/config/glossaries/<Show>.json" /tmp/<Show>.try.json
python3 glossary_verify.py /tmp/<Show>.try.json --force
```

**3. Read the last lines.** Verify prints one summary line,
`decision backend: model=typesafe/jev calls=986 ok=985 failures=1 fallbacks=0 pending=1`. A
failed call leaves its term pending for the next sweep. After five failed terms in a row the run
stops calling the provider (`VERIFY_DECISION_BREAKER`), so an outage costs five requests and not a
night's worth. `VERIFY_DECISION_FALLBACK=local` lets the local model answer instead.

**4. Know what acquisition does.** `glossary_acquire.py` asks a same-entity question. On the
audit set the decision model was worse than the local one at it (47% against 72%), so acquire
stays on the local model when verify uses the decision model. `ACQUIRE_BACKEND=decision` changes that.

---

## Triage the review queue

**Problem:** the review queue is long, and most of it is not worth your time.

**Glossary flags.** Run the review on the glossary and the show folder:

```sh
python3 glossary_acquire.py "/config/glossaries/<Show>.json" "/media/Anime Library/<Show>" --review
```

Without `--apply` it only shows what it would do. Add `--apply` to write your answers. Decisions
come first, in this order: `respelling-needs-review`, `common-word`, `not-in-arc-pages`,
`low-confidence`, `possessive_floor_crossing`. Terms with no wiki candidate are collapsed into one
line, because there is nothing to accept or reject. `--all` lists them, and `--prune-no-match`
removes the stored ones.

If a stage holds the glossary while you answer, your answers wait up to ten minutes, and are then
saved beside the glossary and applied at the next `--review`. An answer is applied only to the
proposal you saw. If the term was flagged again with another canonical in the meantime, the answer
is skipped and the log says so.

**Repair rejections.** The review page lists them. A rejection that changed more than six words is
kept in the file but hidden from the default view, because in a blind sample of 100 real
rejections no acceptable fix needed more than that. Show them with the all-reasons view. Raise
`REPAIR_AUTO_DISMISS_WORDS` to see more by default, or set it to `off` to see all.

**What to expect.** On the Wano run, about four in five rejections were right, so the queue is
mostly confirming a guard. The ones worth finding are casing, punctuation and single-name
respellings. See [Why the queues are smaller](Why-It-Works-This-Way.md#why-the-queues-are-smaller).

---

## Give a show without arc names a wiki scope

**Problem:** the arc stage names each season's arc from its `season.nfo`. Most shows have no such
name, so the stage has nothing to scope the wiki lookup by.

**1. Pick the rung that fits the wiki.**

| The wiki has                                      | Use           |
| ------------------------------------------------- | ------------- |
| An index page with arcs and their episode numbers | `arc_index`   |
| One page per season                               | `season_page` |
| Little structure, or the show has one season      | `whole_wiki`  |

**2. Add a `wiki_scope` block to the show's glossary.** For Naruto Shippuden:

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

The wiki's table restarts its episode numbers in each part, so `part` is required when the page
has several, and `season_offsets` maps your season's episode numbers to the table's. Library
seasons often do not line up with the wiki's arcs, so the scope is picked by episode number.

**3. Check the file names.** Season and episode scopes read `SxxExx` from the video file names. A
file without one gets no scope.

**4. Tag once by hand and read the result.**

```sh
python3 glossary_verify.py "/config/glossaries/<Show>.json" --tag-arcs
```

The glossary now has `arc_titles` and `arc_coverage`. A scope that failed, came back partial or
could not be parsed stores nothing and appears in `arc_titles_missing`. Fix that before you rely
on the stored titles. Set `GLOSSARY_ARC_TAGS=1` to run the same step every night.

**5. For a show that has arcs but some seasons that are not arcs**, tell the stage what to do with
them. One Pace's `Gaimon` and `Water Seven` seasons are the examples: Gaimon has no wiki arc page,
and Water Seven's page is named `Water 7`.

```json
{
  "arc_aliases": { "Water Seven": "Water 7", "Fishman Island": "Fish-Man Island" },
  "arc_waived": ["Gaimon", "The Adventures of Buggy's Crew", "The Trials of Koby-Meppo"]
}
```

`VERIFY_ARC_GATE=1` stays off until `arc_titles_missing` is empty. On the audit set the gate stopped
45 of 119 wrong writes and 8 of 42 right ones, so it is the weaker of the two write guards.

---

## Choose a quantisation for your card

**Problem:** you want Whisper and the repair model resident at once on one card.

This project runs **Q6_K**. On-disk weights, measured 2026-09-02:

| Quantisation | Size on disk |
| ------------ | ------------ |
| `Q8_0`       | 4.0 GB       |
| **`Q6_K`**   | **3.1 GB**   |
| `Q5_K_M`     | 2.7 GB       |
| `Q4_K_M`     | 2.4 GB       |

On a 6 GB card, Q8_0 leaves roughly 2 GB — tight alongside Whisper, and not necessarily
enough depending on your Whisper model and compute type. Q6_K buys back most of a
gigabyte, which is why it is the one this project settled on.

Options, cheapest first:

1. **A smaller quantisation.** Q5_K_M or Q4_K_M go further still. The quality cost below
   Q6_K is not measured here; the table above is sizes, not quality.
2. **Two cards.** Whisper on one, the repair model on the other. Nothing assumes they share
   a device — the repair stage talks to an HTTP endpoint.
3. **Sequential.** Run the transcription sweep and the merge sweep at different times, one
   model resident at a time. `generate.py` loads Whisper lazily and its process exits between
   shows, so this costs wall-clock rather than quality.

**Check what is actually resident** before blaming the pipeline for an OOM:

```sh
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

If another process holds the card, Whisper can CUDA-OOM. The pipeline exits cleanly and the
loop restarts with a fresh context, so it self-heals once VRAM frees — but do not run two
transcriptions on one small card at once.

---

## Sign in and manage accounts

**Problem:** you need to control access to the review workspace, add user accounts, or rotate keys.

**First-run setup.** On a fresh install without accounts, browse to `http://<host>:8842`. The server opens `/review/setup` to create your initial administrator account. Alternatively, set `REVIEW_USERNAME` and `REVIEW_PASSWORD` (or `REVIEW_PASSWORD_FILE`) in `compose.yaml` to seed the admin account once on first boot.

**Sign in and roles.** Sign in with your username and password at `http://<host>:8842/review`.

- **admin:** manages accounts, changes settings, tests connections, and rotates the admin API key.
- **user:** reviews episodes, submits verdicts, and changes their own password.
- Read and write routes both require authentication.

**Manage user accounts.** Signed in as an administrator, open **Settings > General** (`#/settings/general`) and scroll to **Accounts**. You can create accounts, promote or demote users between `admin` and `user`, reset passwords, or delete accounts. The server refuses to delete or demote the last remaining administrator.

**Change your password.** Click your username in the navigation bar and select **Change Password**.

**Automate with the admin API key.** External scripts send the `X-Api-Key` header instead of browser cookies. The key is stored in `/config/apikey`. You can view, copy, or reset it under **Settings > General > Security**.

**Disable authentication.** Set `REVIEW_AUTH=off` in your container environment only if you run DubTitlerr on an isolated, trusted network.

---

## Recover an administrator account

**Problem:** you forgot your administrator password or got locked out of the web UI.

**Run the recovery tool inside the container.** Execute `review_users.py reset-admin` with your administrator username:

```sh
docker compose exec dubtitlerr python3 review_users.py reset-admin <username>
```

The command generates a new 16-character password that stays until changed, prints it to your terminal, and clears existing sessions for that account. Sign in with the new password and update it when you are ready.

If `users.json` is unreadable or corrupt, the tool moves the file aside as `users.json.corrupt-<timestamp>` and creates a fresh administrator account with `<username>`.

---

## Point a show at its wiki

**Problem:** automatic wiki detection picks the wrong wiki or you want to set a custom MediaWiki API endpoint for a show.

**Requirement:** the show must already have a glossary file in `GLOSSARY_DIR`. Shows without a glossary cannot set a wiki URL here yet.

**1. Open the Glossary page.** In the web UI, open **Glossary** (`#/glossary`) and select your show.

**2. Enter the wiki URL.** In the **Wiki** field above the term tables, enter the MediaWiki site or API URL (for example `https://naruto.fandom.com` or `https://naruto.fandom.com/api.php`). Leaving the field empty clears the override and restores automatic detection.

**3. Test the URL.** Click **Test** to verify the endpoint before saving. DubTitlerr queries the siteinfo API and displays the confirmed site name.

**4. Respect URL constraints.** URLs must use `https` unless `WIKI_ALLOW_HTTP=1` is set in the container environment. The server refuses loopback addresses, private network IPs, link-local addresses, and embedded credentials.

**5. Save the glossary.** Click **Save** to write the wiki URL to the show's glossary JSON file.

---

## Run only what you queue

**Problem:** you want DubTitlerr to process only episodes you explicitly queue, instead of sweeping your entire media library continuously.

**1. Turn off library sweep.** In the web UI, open **Settings > Schedule** and set **Sweep the whole library** (`LIBRARY_SWEEP`) to **Off**. You can also set `LIBRARY_SWEEP: "false"` in `compose.yaml`.

**2. Know what changes.**

- The generation loop disables root library walks and only processes requests waiting in the run queue.
- The merge pass only checks show directories with requests that are pending, running, or finished in the last 7 days, leaving the rest of the library untouched.

**3. Queue episodes.** Open the **Runs** page (`#/runs`) to queue a show, season, or episode regex, or trigger runs automatically through Sonarr and Radarr webhooks.

---

## Connect Sonarr and Radarr

**Problem:** you want newly downloaded episodes queued automatically when Sonarr or Radarr imports them.

**1. Set the webhook token.** In `compose.yaml` (or in Settings > Connect > Webhook), set `WEBHOOK_TOKEN`:

```yaml
WEBHOOK_TOKEN: your-secret-webhook-token
```

When this variable is unset, webhook routes return 404.

**2. Map remote paths if needed.** If Sonarr or Radarr runs with different mount paths, set `REMOTE_PATH_MAPPINGS`:

```yaml
REMOTE_PATH_MAPPINGS: "/data/anime=/media/Anime Library;/downloads=/media/downloads"
```

**3. Add the webhook notification in Sonarr or Radarr.**
Go to **Settings > Connect > Add Notification > Webhook**:

- **URL:** `http://<host>:8842/api/webhook/sonarr` (or `/api/webhook/radarr`)
- **Method:** `POST`
- **Headers:** add `X-Webhook-Token: your-secret-webhook-token` (or append `?token=your-secret-webhook-token` to the URL)
- **Triggers:** enable **On Download** and **On Upgrade**.

Click **Test** in Sonarr or Radarr to confirm the connection.

---

## Configure LLM connections

**Problem:** you want to use local or remote LLM backends without restarting the container or editing Compose files.

**1. Open Connections.** In the web UI, go to **Settings > Connections** (`#/settings/connections`).

**2. Add a connection.**

- Enter a name and select a kind (`llama.cpp`, `Ollama`, or `OpenAI-compatible`).
- Set the endpoint URL and model name.
- For OpenAI-compatible providers, enter the API key in the write-only key field. Keys are stored in `secrets.json` (mode 0600) and never returned to the browser.
- Click **Test** to send a probe completion and verify the endpoint.

**3. Assign stages.** Pick which connection runs each stage (Repair, Restore, Verify, Decision, and Acquire). Stages without an assigned connection keep their container environment defaults.

---

## Restart the container from the web UI

**Problem:** you changed a setting marked "Restart required" and want to apply it without terminal access.

**1. Save your changes.** When you save a restart-required setting (such as port, bind address, or webhook paths), DubTitlerr prompts you with two choices:

- **Restart Now:** asks the builder to finish the current episode in flight and exit cleanly. Docker brings the container back up automatically under `restart: unless-stopped`.
- **Restart Later:** keeps running the current process and displays a "Restart pending" banner until the next container restart.

**2. Reconnection.** While the builder restarts, the web UI displays a reconnecting overlay and resumes your session once the new instance answers.

---

## Share your glossaries and verdicts

**Problem:** curated glossaries and reviewed seasons are trapped on one machine.

`GLOSSARY_DIR` and `DECISIONS_DIR` are plain directories of JSON, one file per show, designed
to be committed to git. A `git pull` on the host is what makes them current: the container
reads whatever is in the mount.

```sh
cd ~/dubtitlerr/glossaries && git init && git add . && git commit -m "glossaries"
```

The admin API key is deliberately stored **beside** `DECISIONS_DIR` (at `/config/apikey`), never inside it, so a
credential never rides along with a directory you publish.

Community glossaries live in their own repository with a pull-request path for contributions.

---

## Report a problem

Include:

1. The **log lines around the failure**. Unvalidated-configuration warnings are formatted to
   be pasted directly.
2. `.dubtitles.repair-summary.json` — it names the model, the rules and the counts.
3. `.dubtitles.crash.json`, if there is one.
4. Whether the show is **anchored or unanchored**, plus the `ffprobe` track listing from the
   first recipe on this page.

Do not include the video.
