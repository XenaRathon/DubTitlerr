# DubTitlerr

**Dubtitles for anime: subtitles that say what the English dub actually says.**

Most anime already ships an English subtitle track, but it is a translation of the _Japanese_
audio — different wording, sometimes different meaning. Watching a dub with it on gives you
two scripts at once. DubTitlerr transcribes the dub audio itself, corrects the proper nouns,
and writes the result back into the file as a subtitle track your player picks up.

It runs as one container, per episode, incrementally.

> **This is a beta.** One Pace is the only configuration validated end to end. Other shows
> work and are also where the bugs are found. Version stamps may be invalidated without
> notice — pin your image tag.

---

## Start here

| I want to…                                  | Go to                                              |
| ------------------------------------------- | -------------------------------------------------- |
| Get it running on one show, start to finish | **[Your first show](Your-First-Show)**             |
| Solve one specific problem                  | **[How-to guides](How-To-Guides)**                 |
| Look up a variable, a filename, a schema    | **[Reference](Reference)**                         |
| Understand why it behaves the way it does   | **[Why it works this way](Why-It-Works-This-Way)** |

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
  [choosing a quantisation](How-To-Guides#choose-a-quantisation-for-your-card).
- Docker with the NVIDIA container runtime.
- Somewhere to serve a small GGUF language model over an OpenAI-compatible endpoint.
- A library with English dub audio, laid out as `Show Name (Year)/Season 01/…S01E01…`.

**Image:** `ghcr.io/xenarathon/dubtitlerr`

---

## Related repositories

- **Glossaries** — community per-show name dictionaries, pulled into `GLOSSARY_DIR`.
- **Subtitles** — finished dubtitle files for episodes that have had a human review pass,
  published as review completes.
