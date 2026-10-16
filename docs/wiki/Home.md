# DubTitlerr

**Dubtitles for anime: subtitles that say what the English dub actually says.**

Most anime already ships an English subtitle track, but it is a translation of the _Japanese_
audio — different wording, sometimes different meaning. Watching a dub with it on gives you
two scripts at once. DubTitlerr transcribes the dub audio itself, corrects the proper nouns,
and writes the result back into the file as a subtitle track your player picks up.

It runs as one container, per episode, incrementally.

> **This is a beta.** One Pace is the only configuration validated end to end. Other shows
> work and are also where the bugs are found. Version stamps may be invalidated without
> notice: pin your image tag.
> If you have pulled a newer image but are not ready to re-transcribe, stop the container until you are.

---

## Start here

| I want to…                                  | Go to                                                                                     |
| ------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Get it running on one show, start to finish | **[Your first show](Your-First-Show.md)**                                                 |
| Solve one specific problem                  | **[How-to guides](How-To-Guides.md)**                                                     |
| Look up a variable, a filename, a schema    | **[Reference](Reference.md)**                                                             |
| Understand why it behaves the way it does   | **[Why it works this way](Why-It-Works-This-Way.md)**                                     |
| Pick a transcription model for your GPU     | **[Choosing an ASR model](Choosing-an-ASR-Model.md)**                                     |
| Point an AI agent at the project            | **[Agent guide](https://github.com/xenarathon/DubTitlerr/blob/main/docs/AGENT-GUIDE.md)** |

---

## What it does, per episode

1. **Transcribe** the English dub audio with Whisper, then reflow it into readable cards —
   sentence-split, at most two lines, timed to the spoken onset.
2. **Correct names** against a per-show glossary that is mined from your own files and
   checked against the show's wiki.
3. **Repair** the low-confidence and name-suspect lines with a small local language model,
   anchored on the existing subtitle track where you have one.
4. **Gate** the result — drop hallucinated music and silence lines, collapse runaway
   repetition, and flag what it is unsure about for you to read.
5. **Merge** the on-screen signs and song lyrics back in.
6. **Mux** the finished track into the file with its original fonts, so signs render in their
   real typeface.

Then it stops and waits for you. The lines it was unsure about are queued at
**http://localhost:8842**, and a verdict you give there applies to that line everywhere in
the show.

---

## What it does not do

- It does not translate. It transcribes English audio.
- It does not proofread. The review queue holds the lines the pipeline **doubted** — the ones
  it was confident about were never shown to anyone, and some are wrong.
- It does not re-mux an episode because you saved a verdict. That is a separate button, on
  purpose.

---

## Requirements

- An NVIDIA card with CUDA. 6 GB works; see
  [choosing a quantisation](How-To-Guides.md#choose-a-quantisation-for-your-card).
- Docker with the NVIDIA container runtime.
- Somewhere to serve a small GGUF language model over an OpenAI-compatible endpoint.
- A library with English dub audio, laid out as `Show Name (Year)/Season 01/…S01E01…`.

**Image:** `ghcr.io/xenarathon/dubtitlerr`

---

## Roadmap

- **Arr API and poster library view** - connect directly to Sonarr and Radarr APIs to present a poster grid with status bars, replacing filesystem walks and letting you set a show's wiki URL before its glossary exists.
- **Run a show again from the Runs page** - a show that already ran is skipped. Queueing it again
  will ask whether you want to run it again or cancel, so you don't redo one by mistake. Run again
  redoes only that show and season. This helps after a new version changes the output.
- **Season ranges in run requests** - a request on the Runs page targets one season or the whole
  show. It should also take a range of seasons, so queueing a show's early arcs is one request
  instead of one per season.
- **Remove a queued request** - queued requests can be added but not withdrawn yet. The Runs page
  should let you remove one before it starts.
- **What the current run is doing** - a status section on the Runs page showing the show, episode
  and stage being worked on right now.
- **Wiki scope for more shows** - the scoped wiki lookup is built and tested live against Naruto,
  Pokémon and two one-season shows. What is left is trying it on each show's real library and
  writing the `wiki_scope` block for the shows people actually run.
- **Reference lines from a published subtitle file** - repair anchors on the English subtitle track
  embedded in the video. Dub re-cuts made from another release carry none, so repair works from the
  glossary alone. The idea is to match each dub line, by its words, to a published English subtitle
  file for the same scene, allowing the timing offset to change partway through an episode. A
  first blind test on three episodes of one arc preferred the referenced output over the
  glossary-only output on 34 of 65 contested lines, against 7 the other way. It needs a wider test
  and a spot-check before it is built.
- **Community glossary repo** - [XenaRathon/DubTitlerr-glossaries](https://github.com/XenaRathon/DubTitlerr-glossaries)
  is the shared repository of per-show glossaries. Planned for v1.0.0 or a later 1.x release:
  downloading glossaries from it and uploading yours back, from inside the app. Downloads will
  never overwrite your own fixes or a wiki you set. Today it is a `git clone` into your
  `GLOSSARY_DIR` and a `git pull` to update, which `decisions.py` already documents as the
  intended flow.

  **This repository's `glossaries/` directory is a snapshot**, used by the tests and by the
  examples in these docs. The pipeline reads whatever is mounted at `GLOSSARY_DIR` and never
  the copy in its own source tree, so the shared repository is the one to install.

---

## Related repositories

- **Glossaries** — community per-show name dictionaries, pulled into `GLOSSARY_DIR`.
- **Subtitles** — finished dubtitle files for episodes that have had a human review pass,
  published as review completes.
