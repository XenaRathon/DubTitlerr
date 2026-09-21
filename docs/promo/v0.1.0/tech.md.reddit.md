# Reddit promo post — homelab / tech enthusiast subreddits

**Target subreddits:** r/selfhosted, r/docker, r/softwarr, r/arr, r/plex, r/coolgithubprojects

**Title:** DubTitlerr — self-hosted *-arr-style service that transcribes anime dubs into subtitles and muxes them back (Whisper + local LLM, Docker, GPU)

**Body:**

Been working on this for a while, figured I'd share here since it's very much a "homelab with a GPU" kind of project.

The problem it solves: when you watch an anime with the English dub, the subtitles that come with the release are usually the JP translation, not what's actually being said in the dub. And if you want the on-screen signs and song lyrics too, most players only show one subtitle track at a time, so you get dialogue or signs, not both.

DubTitlerr is a self-hosted service that watches your anime library and runs a full pipeline per episode:

- **Transcribe** — faster-whisper (large-v3-turbo default, large-v3 optional). Measured 18.9% WER vs 20.8% for turbo on a 6GB GTX 1060; both fit in 6GB at int8.
- **Reflow** — words into timed cards, sentence-split, ≤2 lines, ~17 cps, never shown before they're spoken.
- **Glossary** — per-show name dictionary, auto-mined from the embedded subs and wiki-verified (canonical + dub-preferred spellings). A separate glossary repo lets the community contribute corrections.
- **LLM repair** — local qwen3-4b-instruct, fansub-anchored. It fixes ASR errors by referencing the existing subtitle dialogue, with a refusal guard that blocks a full-episode rewrite if the pass would skip every line. No cloud calls.
- **Hallucination gate** — drops music/silence, blocklist lines, and within-card loops. Collapses runaway repeat runs. Flags the merely uncertain instead of dropping them.
- **Signs & songs merge** — lifts the positioned ASS events from the release's signs track into the same subtitle file.
- **Mux** — embeds with the MKV's original fonts as a default "Dubtitles" track. mp4 episodes get remuxed to mkv. English audio set as default.

It's idempotent: a version-stamped `.dubtitles.done` sidecar per episode makes re-runs safe and incremental. Bump `PIPELINE_VERSION` for a library-wide regeneration. Plex refreshes per-episode as each one finishes.

There's a built-in review server on `:8842` that queues every admitted repair for human review, grouped by show, worst-first, with a timestamp so you can seek to the line in your player. On a 48-episode run, 78% of repairs changed no words (only punctuation or capitalization), so the page surfaces the word-level changes first. Verdicts are stored per show, so a decision on the opening song propagates to every other episode that has it.

The whole thing is one Docker container (root, so it can rewrite and chown sidecars), runs on your own GPU, and makes zero cloud calls. Build with `Dockerfile.builder`.

Most of my testing during development has been against One Pace / Muhn Pace dubs, but the pipeline is show-agnostic. It builds its glossary from whatever subs you have. Try it on whatever's in your library and file an issue if something looks off. It's in beta, so pin your image tag if you pull it.

Open to collaboration — forks and PRs welcome, especially for glossary coverage on other shows.

https://github.com/XenaRathon/DubTitlerr

---

This is 100% vibe-coded slop. I wrote it with Claude driving. But I didn't just say "make the thing with no mistakes." The whole project has specs, epics and stories, adversarial reviews (had other models try to break it), and real test coverage. I've been project managing it like an actual engineering effort, not a prompt-and-pray. I'm sharing it because it fills a gap I couldn't find a solution for, and I thought it might be a useful accessibility tool for people who want dub-matched subtitles without waiting for an official SDH release. This isn't meant to replace human-transcribed SDH subtitle tracks. Those are always going to be better. It's for when they don't exist.
