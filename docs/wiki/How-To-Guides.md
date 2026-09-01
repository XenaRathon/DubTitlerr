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

There is also a global `REPAIR_UNANCHORED` variable. **Do not use it.** It is recorded in no
committed file, which is precisely how a season's corrections were once silently reverted to
raw speech recognition.

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

**`--jinja` is required by any model whose chat template is not built into llama.cpp** —
`nanbeige4.2-3b`, the default, is one of them. Without it the server loads, answers
`/health` with `200`, and returns empty content forever.

Do not use `/health` as a readiness check. It reports `200` while weights are still
loading. Ask for a real completion instead, as above.

---

## Choose a quantisation for your card

**Problem:** you want Whisper and the repair model resident at once on one card.

Measured: `nanbeige4.2-3b` at **Q8_0** is **4.43 GB** of weights at 16k context. On a 6 GB
card that leaves roughly 1.4 GB — **not enough for Whisper alongside it.**

Options, cheapest first:

1. **A smaller quantisation.** Q4_K_M or Q5_K_M plausibly leave room. The quality cost is
   being measured; this page carries the table when it lands.
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

## Secure the review page

**Problem:** the review server's write routes rewrite subtitles and force re-muxes, from a
root-owned process.

**The default is already safe.** With `REVIEW_TOKEN` unset a token is generated, persisted
`0600`, and printed once:

```sh
docker exec <container> cat /config/review_token
```

Write routes require it in an `X-Review-Token` header. **Read routes never require it** — a
GET can enumerate your library.

To set your own:

```yaml
REVIEW_TOKEN: "a-long-random-string"
```

To **disable authentication entirely**, set it to the empty string. Only an explicit empty
value does this, and it is a decision about your own network:

```yaml
REVIEW_TOKEN: ""
```

Do not expose port 8842 to the internet either way.

---

## Share your glossaries and verdicts

**Problem:** curated glossaries and reviewed seasons are trapped on one machine.

`GLOSSARY_DIR` and `DECISIONS_DIR` are plain directories of JSON, one file per show, designed
to be committed to git. A `git pull` on the host is what makes them current — the container
reads whatever is in the mount.

```sh
cd ~/dubtitlerr/glossaries && git init && git add . && git commit -m "glossaries"
```

The review token is deliberately stored **beside** `DECISIONS_DIR`, never inside it, so a
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
