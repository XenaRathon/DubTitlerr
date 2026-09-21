# Reddit promo post — anime enthusiast subreddits

**Target subreddits:** r/onepace, r/animedubs, r/anime, r/AnimeDubs (if applicable)

**Title:** DubTitlerr — transcribes your anime's English dub into subtitles and merges the signs/songs track in (self-hosted, Docker + GPU)

**Body:**

> If you watch anime with the English dub, you've probably run into this: the subtitles that come with the release are the Japanese translation, not what's actually being said in the dub. So you're reading one thing and hearing another. And if your release has a signs and songs track (translated on-screen text, song lyrics, episode titles), most players only show one subtitle track at a time, so you have to pick: dub dialogue or signs. Not both.
>
> I couldn't find a tool that did both, so I built one.
>
> DubTitlerr watches your anime library and, for every episode that has an English dub:
>
> - Transcribes the dub audio with Whisper
> - Fixes character names against a per-show glossary it builds from your subs and wiki-verifies (so "Dothamingo" becomes "Doflamingo," not the other way around)
> - Runs a local LLM (qwen3-4b-instruct) to clean up ASR errors, using the existing fansub dialogue as a reference so it's correcting against something real
> - Drops the garbage Whisper inserts when there's no speech: the "thank you for watching" stingers, music beds, silence, repeated lines
> - Merges the signs and song lyrics into the same subtitle file so one track shows everything in the right font and position
> - Muxes it back into the MKV as a default "Dubtitles" track with the original fonts, and refreshes Plex per-episode
>
> The glossary part is the thing I'm most happy with. It mines the character names from the embedded subtitles on your files, verifies them against the wiki for the canonical and dub-preferred spellings, and applies them during transcription. So the names are right before the LLM ever sees them. There's a separate community glossary repo if you want to contribute corrections for a show.
>
> Most of my testing during development has been against One Pace / Muhn Pace dubs, but the pipeline works on any anime. It builds its glossary from whatever subs you have. If you try it on something else and a name comes out wrong, file an issue with the show name and what it should be, and I can add it to the glossary or you can submit a PR to the glossary repo.
>
> It's in beta. It runs as one Docker container and needs a GPU (a 6GB card is enough). Pin your image tag if you pull it, since version stamps may change during the beta.
>
> https://github.com/XenaRathon/DubTitlerr
>
> ---
>
> This is 100% vibe-coded slop. I wrote it with Claude driving. But I didn't just say "make the thing with no mistakes." The whole project has specs, epics and stories, adversarial reviews (had other models try to break it), and real test coverage. I've been project managing it like an actual engineering effort, not a prompt-and-pray. I'm sharing it because it fills a gap I couldn't find a solution for, and I thought it might be a useful accessibility tool for people who want dub-matched subtitles without waiting for an official SDH release. This isn't meant to replace human-transcribed SDH subtitle tracks. Those are always going to be better. It's for when they don't exist.
