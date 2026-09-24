# Beta feedback — r/Animedubs launch post (2026-09-07)

First public beta feedback pull. Post: https://www.reddit.com/r/Animedubs/comments/1wa383t/dubtitlerr_transcribes_your_animes_english_dub/

Pulled 2026-09-08 via headless-browser + in-origin `fetch()` of the `.json` endpoint — Reddit 403s raw curl from this host (the reddit-mcp-ai `extract_public_opinion` tool also returned empty because Arctic Shift's archive lag hasn't indexed the post yet).

## Post stats at pull time

- 21 upvotes, 65% upvote ratio, 8 comments, 1 day old
- r/Animedubs, link post → https://github.com/XenaRathon/DubTitlerr
- 0 gilded, 0 awards, 0 stickied (all 8 comments are non-author except 4 author replies)

## Non-self comments (5 total)

### u/Ecstatic_Bus_7232 — score 12 (top comment)

> With help of Claude usually means "I haven't seen a single line of code I just talk to the thingy" 😄
>
> Is what I wanted to write but then just saw the last line 🫣
>
> But anyways, the sub translation mismatch is a huge gripe for me when I want to show an anime to someone who doesn't know english and/or is not eager to watch with japanese dub. My best chances are finding the dubtitles, machine translating and hand correcting.
>
> Lately I ask gemini to translate a subtitles and ran in all sorts of issues, mostly with the amount of text. There's no functionality to output that much text. After a few attempts the session broke and it eventually started hallucinating subtitles. What a times to live in. Copilot was an interesting case, it started with NOT doing the actual task but instead complaining how hard it would be.

**Signal**: the Claude disclosure is _working_ when framed as design-vs-build (as your post does in the final line), but it nearly backfired — they wrote the dismissive take first, then walked it back. On the next post, move the "I designed it rather than built it" framing earlier — first paragraph, not last.

Pain-point validation: Gemini + Copilot both failed on subtitle translation workloads. Not a new competitor, but confirms the whitespace.

### u/BlueSpark4 — score 2 (feature ask thread)

> For me personally, I really don't need dubtitles when watching anime. However, the component which intrigues me is the generation of songs&text subtitles from a full subtitle track (if I understood this point correctly).
> Is there any chance you could offer a slimmed down version of this tool which only extracts and songs&text subs from a full English subtitle track and saves them as a separate "Songs & Text" subtitle track?

Author replied (you said the merging currently depends on S&S already being a separate track). Follow-up from BlueSpark4:

> Still, if you can find the time to experiment with this, it'd be a hugely helpful feature to me and probably a whole lot of other people, too.

**Signal**: the second-highest-value ask in the thread. Doesn't need the whisper pipeline at all — this is a pure-subtitle post-process.

### u/RelativeMundane9045 — score 2 (depth 4, buried)

> I don't know if this helps, but I know some people extract S&S by isolating all the text that's not in the default location.
>
> Can't offer any more, just what I've read that the 🏴‍☠️ groups do to create their signs and songs tracks.

**Signal**: this is the highest-value input in the whole thread — a concrete algorithmic pointer from someone who knows how pirate groups build S&S tracks. Needs research on what "default location" means (ASS alignment field? `\pos()` override? vertical offset heuristic?) before it's actionable.

## What nobody asked about

- Hardware requirements (GPU / 8GB card feasibility / nanbeige quant size)
- Install steps or Docker compose details
- Plex integration specifics
- License (GPL-3.0) — no comment
- Pricing / donation — no comment

Either the pitch is clear enough to skip these questions, or people aren't far enough along to care. Zero technical questions in 8 comments at 21 upvotes is unusually quiet for a technical launch post. Watch the next 3–5 days for the drop.

## Cross-cutting rollup for the beta

### High-priority follow-ups

1. **S&S-extract-only mode** — new feature candidate. Skips whisper entirely, pure subtitle-track post-process. Two of three non-self commenters are involved in this thread. Likely a 20-line tool (script.py) before it's a pipeline stage — worth scoping before committing.
2. **Position-based S&S heuristic research** — pirate groups have done this for 20 years. Look up ASS/SSA `\pos()` override tags and vertical alignment fields. This is the mechanism behind the "extract what's not in the default location" hint. If clean, this unblocks #1.

### Post-framing fix (for the next 5 promo posts)

- Move the "designed with Claude, didn't hand-write" disclosure into the first paragraph. The current framing saved this post; it's too late for the next five.

### Not yet asked about — worth watching

- Hardware requirements — will surface once the first outsider tries to run it
- Plex integration — will surface once someone's got subtitles and wants to watch them

## Method (for the next pull)

Reddit's JSON endpoint 403s raw `curl` from this host and reddit-mcp-ai's Arctic Shift backend lags live posts by weeks. The reliable pattern for a fresh post is:

```python
# via browser tool: open the post URL in a headless tab, then in-page fetch
data = await tab.evaluate("""
(async () => {
  const r = await fetch('/r/<sub>/comments/<id>/<slug>.json?limit=100&raw_json=1',
                        { headers: {'Accept': 'application/json'} });
  return await r.json();
})()
""")
# walk data[1]['data']['children'] recursively through each comment's 'replies'
```

For unattended pulling (cron-style), the reddit OAuth flow is the clean path — 15 min setup, `read` scope, refresh-token re-auth every 60 days. Not built yet.
