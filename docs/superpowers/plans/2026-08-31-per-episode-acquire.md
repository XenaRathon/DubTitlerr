# Per-episode acquire scoping — implementation plan

Written 2026-08-31. Implements
`.procoder/todo/20260829-acquire-scope-wiki-titles-per-episode.md`, which measured the
primitives and settled the approach. This plan adds what One Pace changes about it, and
lists the decisions still owed before code is written.

## The problem, in one line

`glossary_acquire.acquire()` scores every harvested token against **every main-namespace
page on the show's wiki** — 1,281 titles on Sword Art Online for a pass covering Season 1.
That breadth is what produced `What -> Whale`, `Whose -> Horse` and
`Would -> World Seed`. The `english-word` gate caught all of them, but the gate is the last
line, and it is absorbing damage the candidate set should never have contained.

## What was already settled (see the todo for the measurements)

The candidate set for an episode is the **`[[...]]` links in its wiki page's Plot section**
— 26–30 entities per episode, versus 1,281 franchise-wide. Measured against three
alternatives, all rejected: `categorymembers` is the wrong unit, `prop=links` is
navbox-polluted, `allpages` is the status quo.

Two traps the measurement exposed, both carried forward here: redirects must be resolved on
**both** sides (`Kirito` vs `Kirigaya Kazuto` — 6 of 15 known entities survived a naive
intersection), and `File:` links must be filtered (~20% of matches).

## What One Pace adds, measured 2026-08-31

A One Pace episode is a **re-cut spanning several original episodes**, so its own title has
no wiki page. The mapping is in the library metadata already:

```xml
<plot>Dressrosa! The Straw Hats split up ...

Covers anime episode(s): 628 - 631
Covers manga chapter(s): 700 - 701</plot>
```

**466 of 506 One Pace `.nfo` files (92%) carry that line.** So the resolution chain for One
Pace is one step longer than for SAO:

```
One Pace S31E01
  -> .nfo "Covers anime episode(s): 628 - 631"
  -> One Piece wiki pages for episodes 628, 629, 630, 631
  -> [[...]] from each Plot section
  -> ~100-120 arc-local candidates for this episode
```

Against 1,281 franchise-wide, that is roughly **11x tighter**, and it is tighter still per
constituent episode. It also generalises: any show whose episodes are re-cuts, and any show
whose `.nfo` names its source episodes, resolves the same way. A show whose episodes map
1:1 to wiki pages is the degenerate case of the same chain with an identity mapping.

**The 8% without the line need a policy**, which is open question 2 below.

## Design

Three collaborating pieces, smallest first.

### 1. `source_episodes(nfo_path) -> list[int]`

Pure parse of `Covers anime episode(s): 628 - 631` into `[628, 629, 630, 631]`. Handles the
range form, the comma form, and the single-episode form; returns `[]` when the line is
absent. No network, no wiki knowledge. This is where the One Pace-specific shape lives, and
it is the only new concept a reader has to hold.

### 2. `episode_page_titles(wiki, numbers, pattern) -> list[str]`

Resolves episode numbers to wiki page titles via a per-show `episode_page_pattern`
(question 1), fetches each page's wikitext, extracts `[[...]]` from the Plot section,
filters non-ns0 links, resolves redirects. Cached per page under the existing 30-day
`WIKI_CACHE_TTL` — 4 pages per One Pace episode across 506 episodes must not become 2,024
uncached round trips per sweep.

### 3. `acquire()` takes the narrowed set as its **admission filter only**

Per question 3's recommendation: `allpages` remains the authority on canonical _spelling_;
the per-episode set decides what is _eligible_ to be proposed. This keeps the change to one
predicate and leaves the scoring path untouched.

## Decisions owed before implementation

1. **`episode_page_pattern` per show.** SAO names pages `Sword Art Online Episode 05`; One
   Piece uses `Episode 628`. Nothing guarantees a third wiki agrees. Proposal: a
   `episode_page_pattern` string in the show's glossary beside the existing `wiki` override,
   `{n}` substituted; absent means fall back to today's behaviour.
2. **Fallback when an episode has no page or no mapping** (the One Pace 8%). Options: score
   against the franchise-wide set as today (safe, noisy) or contribute no candidates
   (tight, may miss real names). **Recommendation: fall back, and log it per episode** —
   silently widening reintroduces the noise for exactly the episodes nobody checked.
3. **Confirm the filter-not-replace reading of question 3.** The todo recommends it; this
   plan assumes it.

## Phases

| #   | Work                                          | Test that pins it                           |
| --- | --------------------------------------------- | ------------------------------------------- |
| 1   | `source_episodes` parse                       | range, comma, single, absent, malformed     |
| 2   | Plot-section link extraction + `File:` filter | a fixture page with a navbox and file links |
| 3   | Redirect resolution both sides                | `Kirito`/`Kirigaya Kazuto` specifically     |
| 4   | Per-page cache under `WIKI_CACHE_TTL`         | second call makes no request                |
| 5   | Wire into `acquire()` as admission filter     | a token eligible for E05 and not for E16    |
| 6   | Fallback policy + per-episode logging         | a mapping-less episode widens AND says so   |

## Acceptance

Inherits the todo's criteria, plus:

- A One Pace episode's candidate set is derived from its `.nfo` mapping, not the franchise.
- The 40 One Pace episodes with no `Covers anime episode(s)` line follow the question-2
  policy and are named in the report.
- Re-running the SAO dry pass proposes no `What -> Whale`, `Whose -> Horse`, or
  `With -> Witch of the West and the Three Treasures`.

## Why this blocks the re-transcription

`gen_loop.sh` runs `mine_glossary -> glossary_acquire -> glossary_verify -> generate`, and
`generate.py:796` applies `glossary.correct()` to every card before the srt is written. A
re-transcription against today's glossary bakes today's names into 455 episodes. Two further
facts make waiting the cheaper option: `ACQUIRE_APPLY` is unset by default, so acquire is a
**dry run that writes nothing** — a re-transcription now would not even pick up what acquire
found — and `initial_prompt`, the only glossary input Whisper itself sees, is measured to
make no difference. So the glossary's whole contribution to a transcription run happens in
that one correction call, which is exactly what this plan improves.
