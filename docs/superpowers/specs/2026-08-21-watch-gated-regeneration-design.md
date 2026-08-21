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

Live `anime_order.txt` is currently a single line, `One Pace` — hand-narrowed. The loop
re-reads the file on every sweep, so **regenerating it between sweeps is enough**; no change
to `gen_loop.sh`'s control flow is required.

## 3. The source of truth is WatchState, not the media servers

The homelab already runs **WatchState** (`ghcr.io/arabcoders/watchstate`) on fasc — up 4 days,
healthy, bidirectionally importing and exporting between both backends. It holds the unified
record this feature needs, and it is authoritative in a way neither server is alone.

    state table: id, type, updated, watched, via, title, year, season, episode,
                 parent, guids, metadata, extra, created_at, updated_at
    19,521 episodes + 641 movies, `via` naming the backend that reported each row

**Querying Plex directly would give the wrong answer, and would look right doing it.** Measured
today:

| source | One Pace last activity |
|---|---|
| Plex `lastViewedAt` on the show | 2026-07-11 22:09 |
| WatchState `max(updated)`, `via=jellyfin` | **2026-08-20 22:50** |

Exactly **40.0 days** apart. Playback happens on Jellyfin; WatchState syncs the *watched flag*
into Plex without bumping Plex's display `lastViewedAt`. A 30-day Plex-only gate would have
dropped One Pace — the one show the v4 regeneration exists for — while returning a confident,
correctly-sorted list of everything else.

This is the recurring shape in this project: a fallback that is correct in its own terms and
that nothing reports taking. Plex is not broken and does not error; it answers a slightly
different question than the one being asked.

**Access, verified today:** WatchState exposes an HTTP API on `192.168.1.209:8080`, reachable
from the dubtitle host, keyed by `WS_API_KEY` from its `config/.env`.

    GET /v1/api/history   ->  200, 20,162 items, paginated (12/page, 1681 pages)
    GET /v1/api/backends  ->  200

No Jellyfin API key needs minting and no second HTTP client is needed: one source already
unions both backends, per episode, with provenance.

## 4. Design

A small module, `watch_queue.py`, run once per sweep before the loop re-reads the order file.

    watch_queue.py --window-days 30 --out /config/anime_order.txt [--dry-run]

1. Query the WatchState API for episode history newer than the window; group by show title,
   taking `max(updated)`.
2. **Tri-state**, following `tools/vad.py`: reachable-with-data / reachable-empty /
   unreachable. Unreachable is not zero.
3. If WatchState is unreachable **or returns an empty history**, leave `anime_order.txt`
   untouched and exit non-zero with the reason logged. A stale queue is safe; a queue silently
   emptied by an outage is not.
4. Restrict to shows that exist as directories under `ANIME_ROOT` — WatchState covers the whole
   library, most of which is not anime.
5. Match a WatchState title to a library directory name: exact first, then the `_clean_title()`
   normalisation `glossary_verify.py:147` already uses to strip `(YYYY)` and `{tvdb-NNNN}`.
   Titles matching no directory are **reported, never dropped silently** — a rename would
   otherwise shrink the queue invisibly.
6. Write the matched directory names, most-recently-watched first.
7. Always retain shows listed in a `--pin` file, so a deliberate target (One Pace during v4)
   cannot fall out of the queue by going a month unwatched.

## 5. Open questions for review

1. **Window length.** 30 days is a guess. In WatchState's 60-day window, 20 shows have
   activity, but most are not anime; the anime-only count is what matters and should be
   measured before choosing.
2. **API vs direct DB read.** The API is reachable cross-host and needs no new mount; reading
   `watchstate_v02.db` (924 MB, on fasc's local disk) would need one and risks locking. API
   preferred — is there a reason to disagree?
3. **Pagination cost.** 12 items/page over 1,681 pages is a lot of round trips if the endpoint
   cannot be filtered by date or type. If it cannot, this becomes a `db:query` over the
   container's console instead. Needs confirming at implementation.
4. **Per-show or per-season.** `season_priority.txt` already orders seasons within a show.
   Should the gate also drop *seasons* nobody has touched, or is show-level enough? Show-level
   is simpler and probably sufficient.
5. **Interaction with `PIPELINE_VERSION`.** A show entering the queue after a version bump
   regenerates its whole back catalogue. Acceptable, or cap per sweep?

## 6. Out of scope

- Changing `gen_loop.sh`'s control flow — regenerating the file it already re-reads is enough.
- Watch history as a *quality* signal (e.g. prioritising episodes rewatched often).
- Movies. WatchState tracks 641; the dubtitle pipeline is show-oriented.

## 7. Testing

| test | asserts |
|---|---|
| unreachable source -> no write | `anime_order.txt` byte-identical, non-zero exit, reason logged |
| reachable but empty -> no write | distinguishes "nothing watched" from "could not tell" |
| non-anime shows excluded | a WatchState title with no `ANIME_ROOT` directory is not queued |
| title -> directory matching | `{tvdb-...}` and `(YYYY)` suffixes resolve |
| unmatched title is reported | appears in output, does not vanish |
| ordering | most-recently-watched first |
| pinned show always present | even with a last-played far outside the window |
| dry-run writes nothing | — |
