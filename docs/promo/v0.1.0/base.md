# Reddit promo post — base template

**Title:** DubTitlerr — self-hosted tool that transcribes your anime's English dub and merges the signs/songs track into one subtitle

**Body:**

> Been working on this for a while, figured I'd share.
>
> The problem: you watch an anime with the English dub, and you want subtitles that match the dub localization, not just the Japanese translation. But you also want the on-screen signs and song lyrics translated. Most players only show one subtitle track at a time, so you get one or the other.
>
> DubTitlerr fixes both. It's a self-hosted service (one Docker container, needs a GPU) that watches your anime library and for every episode with an English dub:
>
> - Transcribes the dub audio with Whisper
> - Fixes character names against a per-show glossary it mines from your subs and wiki-verifies (so "Dothamingo" becomes "Doflamingo")
> - Runs a local LLM (qwen3-4b-instruct) to clean up ASR errors, anchored on the existing fansub dialogue so it has something real to work from
> - Drops hallucinations: the "thank you for watching" Whisper loves to throw in, music beds, silence, repeats
> - Pulls the signs and song lyrics into the same subtitle file so one track shows everything
> - Muxes it back into the MKV with the original fonts as a default "Dubtitles" track, refreshes Plex per-episode
>
> There's a review page that queues every change the LLM made, worst first, with a timestamp so you can seek to the line in your player. Most of what the repair does is punctuation. On a 48-episode run, 78% of repairs changed no words, and the page focuses on the ones that did.
>
> Idempotent (version-stamped sidecars, re-runs are safe), incremental (one episode at a time), runs entirely on your own hardware.
>
> Most of my testing during development has been against One Pace / Muhn Pace dubs, but it's designed to work with any anime, so feel free to try it on whatever's in your library and file an issue if something looks off. It's in beta, so pin your image tag if you pull it.
>
> https://github.com/XenaRathon/DubTitlerr
>
> ---
>
> This is 100% vibe-coded slop. I wrote it with Claude driving. But I didn't just say "make the thing with no mistakes." The whole project has specs, epics and stories, adversarial reviews (had other models try to break it), and real test coverage. I've been project managing it like an actual engineering effort, not a prompt-and-pray. I'm sharing it because it fills a gap I couldn't find a solution for, and I thought it might be a useful accessibility tool for people who want dub-matched subtitles without waiting for an official SDH release. This isn't meant to replace human-transcribed SDH subtitle tracks. Those are always going to be better. It's for when they don't exist.
