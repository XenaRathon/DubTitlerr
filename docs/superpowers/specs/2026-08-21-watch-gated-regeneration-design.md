# Watch-gated regeneration: pick the queue from what is actually being watched

**Status:** design, awaiting review
**Raised:** 2026-08-21 — once nanbeige serves repair locally, throughput stops being the
binding constraint, so the queue should be scoped by relevance instead of by clock.
**Depends on:** nanbeige reachable from the dubtitle container (in progress)

---

## 1. Why this exists

Regeneration has been an overnight job because repair against a dead or remote endpoint costs
~10 s per target: 183 episodes x ~100 targets x 10 s is 50+ hours. With nanbeige local that
same work is roughly 8 hours, so the job no longer has to be nocturnal.

The remaining reason not to run everything is different, and it is not about speed: the
pipeline is still changing. v4 will not be the last version. Regenerating a show nobody is
watching spends hours to produce subtitles that a later revision supersedes before anyone
reads a line of them. The queue should therefore be **shows with recent watch activity**,
re-derived each sweep, not a static list.

## 2. What exists today

`gen_loop.sh:10` reads the show queue from a flat file:

    ORDER="${ANIME_ORDER:-/config/anime_order.txt}"   # one show directory name per line
    SEASON_PRIORITY_FILE=/config/season_priority.txt  # within-show season order (ordering.py)

Live `anime_order.txt` is currently a single line, `One Pace` — hand-narrowed. The loop reads
it top to bottom every sweep and re-reads it each pass, so **regenerating the file between
sweeps is enough**; no change to `gen_loop.sh`'s control flow is required.

## 3. The two history sources, and why one is not enough

Both media servers hold view state, and they disagree.

**Plex** — credentials already in the container, verified working today:

    PLEX_URL=http://192.168.1.196:32400   PLEX_SECTION=7 ("Anime")   PLEX_TOKEN set

    GET /library/sections/7/all?type=2&sort=lastViewedAt:desc

returns per show: `title`, `viewCount`, `lastViewedAt` (unix). Probed live — it works and is
already sorted. No new dependency: `plex_refresh.py` uses the same three env vars.

**Jellyfin** — found at `http://192.168.1.209:8096` ("XenFlix", 10.11.11). **No API key is
present in the container.** `GET /Users/{id}/Items?SortBy=DatePlayed&SortOrder=Descending`
with an `X-Emby-Token` header gives the equivalent.

The disagreement matters and is not hypothetical. Plex reports One Pace last viewed
**2026-07-11**, six weeks ago, while One Pace is the show actively being worked and watched.
Plex's view state is stale because playback happens elsewhere. A gate built on Plex alone
would return a confident, plausible list that omits the one show that matters — the same
shape as a fallback nobody reports taking.

**So the gate must union both sources, and must fail loudly if one is unreachable rather than
silently returning the other's answer.**

## 4. Design

A small module, `watch_queue.py`, run once per sweep before the loop re-reads the order file.

    watch_queue.py --window-days 30 --out /config/anime_order.txt [--dry-run]

1. Query Plex (section 7) and Jellyfin (anime library) for per-show last-played time.
2. **Tri-state per source**, following `tools/vad.py`: reachable-with-data / reachable-empty /
   unreachable. Unreachable is not zero.
3. If **either** source is unreachable, leave `anime_order.txt` untouched and log why. A stale
   queue is safe; a queue silently narrowed by an outage is not.
4. Union the two by show, taking the **most recent** timestamp per title.
5. Match a Plex/Jellyfin title to a library directory name. Exact match first, then the
   `_clean_title()` normalisation `glossary_verify.py:147` already uses to strip
   `(YYYY)` and `{tvdb-NNNN}`. Titles that match no directory are **reported, never dropped
   silently** — a rename would otherwise shrink the queue invisibly.
6. Write the matched directory names, most-recently-watched first.
7. Always retain shows listed in a `--pin` file, so a deliberate target (One Pace during v4)
   cannot fall out of the queue by going a month unwatched.

## 5. Open questions for review

1. **Jellyfin API key** — needs to be minted in the admin UI and added to the container env.
   Until then the gate cannot run, by rule 3. Is a read-only key acceptable, and should it be
   scoped to one user or the server?
2. **Window length.** 30 days is a guess. Plex's section-7 data shows a natural gap: 13 shows
   viewed within ~100 days, the rest much older. Worth choosing from the union, not from Plex.
3. **Per-show or per-season.** `season_priority.txt` already orders seasons within a show.
   Should the gate also drop *seasons* nobody has touched, or is show-level granularity enough?
   Show-level is simpler and probably sufficient.
4. **Interaction with `PIPELINE_VERSION`.** A show entering the queue after a version bump
   regenerates its whole back catalogue. Acceptable, or cap per sweep?

## 6. Out of scope

- Changing `gen_loop.sh`'s control flow — regenerating the file it already re-reads is enough.
- Watch history as a *quality* signal (e.g. prioritising episodes rewatched often).
- The 14 other shows' glossaries; see the glossary-integrity spec.

## 7. Testing

| test | asserts |
|---|---|
| union takes the newer timestamp | a show newer in Jellyfin than Plex sorts by the Jellyfin time |
| one source unreachable -> no write | `anime_order.txt` byte-identical, non-zero exit, reason logged |
| both reachable but empty -> no write | distinguishes "nothing watched" from "could not tell" |
| title -> directory matching | `{tvdb-...}` and `(YYYY)` suffixes resolve |
| unmatched title is reported | appears in output, does not vanish |
| pinned show always present | even with a last-played far outside the window |
| dry-run writes nothing | — |
