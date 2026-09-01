# Your first show

A lesson. Follow it start to finish on **one season of one show** and you will end with a
video file that plays a dubtitle track. Everything is deliberately narrow — one show, one
season, defaults everywhere — so that when something goes wrong you know where it was.

Budget about **20 minutes of your attention** and a few hours of the machine's. A 24-minute
episode takes roughly 5–15 minutes to transcribe depending on your card.

> This is a beta. One Pace is the only configuration that has been validated end to end.
> Other shows work, and are also where the bugs are. See
> [Why it works this way](Why-It-Works-This-Way.md#why-one-pace-is-the-only-supported-configuration).

---

## Before you start

You need:

1. **An NVIDIA card with CUDA.** 6 GB is enough if the language model lives elsewhere; see
   [How-to guides](How-To-Guides.md#choose-a-quantisation-for-your-card).
2. **Docker**, with the NVIDIA container runtime working. Check it:
   ```sh
   docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
   ```
   If that prints your card, you are ready.
3. **A show with an English dub**, in a folder named like `Show Name (Year)` containing
   `Season 01/` and files tagged `S01E01`.
4. **A place to run a small language model.** The repair stage needs one. Step 1 sets it up.

---

## Step 1 — Serve the repair model

The pipeline calls an **OpenAI-compatible chat-completions endpoint**. Anything that speaks
that protocol works; the validated setup is [llama.cpp](https://github.com/ggml-org/llama.cpp)
serving a GGUF.

The default model is **`nanbeige4.2-3b`**. Pick a quantisation that fits the VRAM you have
left after Whisper — see [How-to guides](How-To-Guides.md#choose-a-quantisation-for-your-card).

```sh
llama-server \
  -m /path/to/nanbeige4.2-3b-Q8_0.gguf \
  -c 16384 --jinja \
  --chat-template-kwargs '{"enable_thinking":false}' \
  --host 0.0.0.0 --port 8090 \
  --alias nanbeige4.2-3b
```

> **`--jinja` is not optional for this model.** llama.cpp has built-in chat templates for
> common architectures, but nanbeige's is not one of them. Without `--jinja` the server
> starts, reports healthy, and returns **empty replies** — the pipeline then repairs nothing
> and tells you nothing. Measured 2026-08-31 on a plain launch: every request came back
> empty.
>
> `--chat-template-kwargs '{"enable_thinking":false}'` is passed through that template. A
> model left thinking spends its whole token budget on reasoning and returns no content;
> measured on LFM2.5, 9.7 s per line for an empty reply.

**Check it is really ready.** A freshly started server answers `/health` with `200` while it
is still loading weights, then fails the first real request. Ask it something instead:

```sh
curl -s http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"nanbeige4.2-3b","messages":[{"role":"user","content":"hi"}],"max_tokens":4}'
```

When that returns JSON with a message in it, the model is loaded.

---

## Step 2 — Make a config directory

```sh
mkdir -p ~/dubtitlerr/{glossaries,decisions,wiki_cache}
```

Tell it which show to do. One line, exactly matching the folder name:

```sh
echo 'Show Name (Year)' > ~/dubtitlerr/anime_order.txt
```

Nothing else goes in this file yet. One show is the whole point of this lesson.

---

## Step 3 — Start the container

Save this as `docker-compose.yml`:

```yaml
services:
  dubtitlerr:
    image: ghcr.io/xenarathon/dubtitlerr:latest
    restart: unless-stopped
    ports:
      - "8842:8842"
    environment:
      # --- where things are ---
      ANIME_ROOT: /media/Anime Library
      MERGE_ROOTS: /media/Anime Library
      MUX_ROOTS: /media/Anime Library
      ANIME_ORDER: /config/anime_order.txt
      GLOSSARY_DIR: /config/glossaries
      DECISIONS_DIR: /config/decisions
      WIKI_CACHE_DIR: /config/wiki_cache

      # --- transcription ---
      WHISPER_MODEL: large-v3-turbo
      COMPUTE_TYPE: int8
      REQUIRE_ENG: "1"

      # --- repair model, from step 1 ---
      REPAIR_BACKEND: llamacpp
      REPAIR_MODEL: nanbeige4.2-3b
      REPAIR_LLAMACPP_URL: http://host.docker.internal:8090/v1/chat/completions

      # --- ownership of what it writes ---
      MEDIA_UID: "1000"
      MEDIA_GID: "100"
    volumes:
      - /path/to/your/media:/media
      - ~/dubtitlerr:/config
    extra_hosts:
      - "host.docker.internal:host-gateway"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Change the two `volumes` lines and `ANIME_ROOT` to match your library. Then:

```sh
docker compose up -d
docker compose logs -f
```

**`ANIME_ROOT` and `MERGE_ROOTS` have different built-in defaults**, which is why the
compose file sets all three roots explicitly. Do not remove them.

---

## Step 4 — Watch the first episode go through

In the log you will see, in order:

1. **Mining** — proper nouns pulled out of the episode's existing subtitle track, building
   `~/dubtitlerr/glossaries/Show Name (Year).json`.
2. **Verification** — those names checked against the show's Fandom wiki.
3. **Transcription** — Whisper on the English dub audio. This is the slow part.
4. **Repair** — the low-confidence and name-suspect lines sent to your model.
5. **Merge and mux** — signs and songs folded in, then written into the MKV as a default
   track named _Dubtitles_.

Then open the episode in your player. There is a subtitle track called **Dubtitles**. Play a
scene with dialogue.

**That is the lesson's goal, reached.** Everything below makes it better.

---

## Step 5 — Look at what the repair stage was unsure about

Open **http://localhost:8842**.

The first thing the log printed on startup was an access token:

```
review server: generated an access token, stored /config/review_token (0600)
review server: token = ...
```

You can also read it back at any time:

```sh
docker exec <container> cat /config/review_token
```

The page shows a tree of shows, seasons and episodes. Open your episode. You are looking at
**only the lines the pipeline was unsure about** — not the whole episode. Each row shows what
was transcribed, what the repair model proposed, and the lines either side for context.

For each one, choose:

- **accept** — the proposal is right
- **reject** — keep the original
- **correct** — neither is right; type what the dub actually says
- **force** — admit a repair the mechanical gate refused

Then press **Save verdicts**.

---

## Step 6 — Put your verdicts into the video

Saving is not enough. Saving records your judgement and changes what the _next_ repair run
ships. The video on disk has not changed.

Press **Apply decisions to this episode**.

That rewrites the subtitle, drops the completion stamp, and lets the merge loop re-mux the
file. Wait for the next merge pass (default: every 10 minutes), then reopen the episode.

Your corrections are in the track.

---

## What you have learned

- The pipeline transcribes the **dub audio**, never the existing subtitle track.
- Glossaries are built for you and live in `/config`, editable by hand.
- The review page shows **uncertain lines only**, and a verdict there applies to that line
  everywhere in the show.
- **Saving a verdict and changing the video are two separate actions.**

## Where to go next

- Your copies have no English subtitles for the Japanese audio? →
  [Turn on unanchored repair](How-To-Guides.md#turn-on-unanchored-repair-for-a-dub-only-show)
- Want the whole library, in watch order? →
  [Queue a library](How-To-Guides.md#queue-a-whole-library-in-watch-order)
- Something looks wrong and you want to know whether it is meant to →
  [Why it works this way](Why-It-Works-This-Way.md)
