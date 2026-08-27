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

## 3. Two sources are required, and neither is optional

### 3.1 WatchState covers the household, but only one Plex user

The homelab runs **WatchState** (`ghcr.io/arabcoders/watchstate`) on fasc — up 4 days,
healthy, bidirectionally importing and exporting between both backends:

    state table: id, type, updated, watched, via, title, year, season, episode,
                 parent, guids, metadata, extra, created_at, updated_at
    19,521 episodes + 641 movies, `via` naming the backend that reported each row

It is configured for **one Plex user**, `xena_rathon` (plex.tv id 4855123, server account
id 1), plus the Jellyfin server. Jellyfin is household-only, so WatchState's coverage is
"the household" — and nothing else.

### 3.2 Plex alone would miss the primary show

| source                                    | One Pace last activity |
| ----------------------------------------- | ---------------------- |
| Plex `lastViewedAt` on the show           | 2026-07-11 22:09       |
| WatchState `max(updated)`, `via=jellyfin` | **2026-08-20 22:50**   |

Exactly **40.0 days** apart. Playback happens on Jellyfin; WatchState syncs the _watched flag_
into Plex without bumping Plex's display `lastViewedAt`. A 30-day Plex-only gate would have
dropped One Pace — the show the v4 regeneration exists for — while returning a confident,
correctly-sorted list of everything else.

### 3.3 WatchState alone would miss other users' shows entirely

Plex has multiple users with real anime history that WatchState never sees. Measured from
`/status/sessions/history/all?librarySectionID=7` — 679 rows across 33 distinct shows:

    account 579973144 (aime_rose)      SPY x FAMILY 41 eps (2026-06-09)
                                       Serial Experiments Lain 15 eps (2026-05-29)
                                       Mashle 24, SK8 the Infinity 8
    account 229144292 (Joshua Vissers) Cowboy Bebop 4 eps (2026-06-04)
    account 660951940 (anastasi8631)   JUJUTSU KAISEN, Fire Force, Chainsaw Man (shared
                                       with account 1)

**SPY x FAMILY, Serial Experiments Lain, Mashle and SK8 the Infinity appear under no other
account.** They are invisible to WatchState and would never enter a WatchState-only queue.

So the gate unions **WatchState** (household/Jellyfin + Plex account 1) with **Plex history
across all accounts** (everyone else). Neither source is a superset of the other:

    WatchState only:  One Pace after 2026-07-11 (Jellyfin playback)
    Plex only:        every show watched by accounts other than 1

### 3.4 Access, verified today

**WatchState** — HTTP API on `192.168.1.209:8080`, reachable from the dubtitle host, keyed by
`WS_API_KEY`. Now deployed to the dubtitle stack as `WATCHSTATE_URL` /
`WATCHSTATE_API_KEY` (`.env`, mode 600, interpolated into compose).

    GET /v1/api/history   ->  200, 20,162 items, paginated (12/page, 1681 pages)
    GET /v1/api/backends  ->  200

**Plex** — `PLEX_URL` / `PLEX_TOKEN` / `PLEX_SECTION=7` already in the stack. The admin token
returns _all_ accounts' history; each `<Video>` row carries `accountID`, `grandparentTitle`
and `viewedAt`.

**Caution, measured:** the `viewedAt>>=<ts>` query parameter was **silently ignored** — a
60-day request returned rows back to 2025-08-29. The response was well-formed and gave no
indication the filter had not applied. **Filter client-side on `viewedAt`; do not trust the
server-side parameter.** This is the same shape as the rest of this document: a correct-looking
answer to a slightly different question.

## 4. Design

A small module, `watch_queue.py`, run once per sweep before the loop re-reads the order file.

    watch_queue.py --window-days 30 --out /config/anime_order.txt [--dry-run]

1. Query **both** sources for episode play events; group by show title, taking `max(viewedAt)`
   across the union.
   - WatchState: `/v1/api/history`, all backends.
   - Plex: `/status/sessions/history/all?librarySectionID=7`, all accounts, filtered
     client-side by timestamp.
2. **Tri-state per source**, following `tools/vad.py`: reachable-with-data / reachable-empty /
   unreachable. Unreachable is not zero.
3. If **either** source is unreachable, leave `anime_order.txt` untouched and exit non-zero
   with the reason logged. A stale queue is safe; a queue silently narrowed by an outage is
   not. Both reachable and both empty is also a refusal — that is "cannot tell", not "nothing
   watched".
4. Restrict to shows that exist as directories under `ANIME_ROOT`.
5. Match a source title to a library directory name: exact first, then the `_clean_title()`
   normalisation `glossary_verify.py:147` already uses to strip `(YYYY)` and `{tvdb-NNNN}`.
   Plex titles arrive HTML-escaped (`I&#39;m in Love with the Villainess`) — unescape before
   matching. Titles matching no directory are **reported, never dropped silently**.
6. Write the matched directory names, most-recently-watched first.
7. **Selection is per SHOW, and never narrows within one.** Once a show is queued, the whole
   series regenerates. Regenerating only the episodes already watched helps nobody — the
   value of a subtitle track is in the episodes about to be watched, and a viewer mid-series
   needs the ones ahead of them. The watch signal answers "is this show live?", never "which
   episodes deserve subtitles".

   This is already how the pipeline behaves and must stay that way: `ordering.py.order_files()`
   reorders a show's files so seasons >= the `season_priority.txt` start season come first,
   explicitly "without changing which files get processed, only the sequence". So
   `One Pace:30` means S30 first then S01-29 after, not S30 only.

8. Always retain shows listed in a `--pin` file, so a deliberate target (One Pace during v4)
   cannot fall out of the queue by going a month unwatched.

## 5. Open questions for review

1. **Window length.** 30 days is a guess. At 30 days only One Pace qualifies; the newest
   other-user activity is SPY x FAMILY at 2026-06-09, 73 days back. So the window decides
   whether other users are represented at all. Measure the union before choosing.
2. **Plex account scope.** Should every account count equally, or should external/guest
   accounts be excluded? `guest` and several `external_user` accounts exist.
3. **API vs direct DB read.** The API is reachable cross-host and needs no new mount; reading
   `watchstate_v02.db` (924 MB, on fasc's local disk) would need one and risks locking. API
   preferred — is there a reason to disagree?
4. **Pagination cost.** 12 items/page over 1,681 pages is a lot of round trips if the endpoint
   cannot be filtered by date or type. If it cannot, this becomes a `db:query` over the
   container's console instead. Needs confirming at implementation.
5. ~~**Per-show or per-season.**~~ **SETTLED 2026-08-21:** show-level only. The gate never
   drops seasons or episodes — see design rule 7.
6. **Interaction with `PIPELINE_VERSION`.** A show entering the queue after a version bump
   regenerates its whole back catalogue. Acceptable, or cap per sweep?

## 6. Out of scope

- Changing `gen_loop.sh`'s control flow — regenerating the file it already re-reads is enough.
- Watch history as a _quality_ signal (e.g. prioritising episodes rewatched often).
- Movies. WatchState tracks 641; the dubtitle pipeline is show-oriented.

## 7. Testing

| test                            | asserts                                                         |
| ------------------------------- | --------------------------------------------------------------- |
| unreachable source -> no write  | `anime_order.txt` byte-identical, non-zero exit, reason logged  |
| reachable but empty -> no write | distinguishes "nothing watched" from "could not tell"           |
| non-anime shows excluded        | a WatchState title with no `ANIME_ROOT` directory is not queued |
| title -> directory matching     | `{tvdb-...}` and `(YYYY)` suffixes resolve                      |
| unmatched title is reported     | appears in output, does not vanish                              |
| ordering                        | most-recently-watched first                                     |
| a queued show is not narrowed   | every episode of a queued show remains eligible, watched or not |
| pinned show always present      | even with a last-played far outside the window                  |
| union across sources            | a show seen only in Plex under another account is queued        |
| Plex date filter is not trusted | rows outside the window are dropped client-side                 |
| HTML-escaped titles             | `I&#39;m in Love with the Villainess` matches its directory     |
| dry-run writes nothing          | —                                                               |
