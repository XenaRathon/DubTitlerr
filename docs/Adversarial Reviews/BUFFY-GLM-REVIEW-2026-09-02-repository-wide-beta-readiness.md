# Repository-wide adversarial review — BUFFY (GLM) — 2026-09-02

Scope: **the whole repository, judged against a public-beta launch.** Written fresh and
independently of the LUNA, DEEPSEEK, and 2026-08-29 reviews; where I confirm one of
theirs I say so and add what I can, and the majority of findings below are mine.

## Scope and method

Read in full or in wide windows: `common.py`, `review_server.py`, `decisions.py`,
`generate.py`, `repair.py`, `mux.py`, `dub_signs_merge.py`, `review_apply.py`,
`hallucination.py`, `plex_refresh.py`, `watch_queue.py`, `glossary_verify.py`,
`merge_pass.sh`, `gen_loop.sh`, `container_run.sh`, both Dockerfiles, both CI workflows,
`pyproject.toml`, `.gitignore`, README, `docs/readme-notes.md`,
`docs/model-candidates-4-5gb-vram.md`, and the `docs/Adversarial Reviews/` corpus.

Commands run:

```text
.venv/bin/python -m pytest -q        → all pass (66+ files, 1,145 test functions)
.venv/bin/python -m ruff check .     → clean
git log / git status / branch+merge-base inspection
targeted greps for every suspected seam (verified before any claim below)
```

Priority labels, same scheme as the prior repo-wide reviews:

- **P0:** can corrupt/overwrite media, expose privileged mutation, or cause sustained outage.
- **P1:** can silently ship materially wrong/incomplete output or strand operational state.
- **P2:** correctness/availability weakness with bounded or recoverable impact.
- **P3:** maintainability, performance, or testability debt.

**Headline for the beta decision:** this is unusually disciplined code — but the
*default path a new user takes* is the least-tested path in the repo. Every prior
review evaluated the pipeline as the author runs it. A public beta hands it to people
with different libraries, different filenames, no fansub tracks, no Ollama host, and no
tolerance for reading container logs. The findings below are ordered by how much they
will hurt *them*, not by how interesting they are.

---

## Findings

### F1 — P1: the review server ships a root-owned mutation endpoint with `REVIEW_TOKEN=` as a documented footgun, and the README teaches the LAN-exposed posture

Confirmed F1 of the LUNA review with one addition it missed: the README's "Reviewing
what the repair stage changed" section says *"On first start the container logs a
token; paste it into the box at the top."* That is the **only** auth guidance a new
operator gets, and nothing in the README states the `REVIEW_TOKEN=` empty-value
disabler even exists. An operator who finds it in a Reddit thread (it is the natural
answer to "token didn't arrive in my logs because I restarted before I saw it") gets a
**root-privileged, unauthenticated subtitle-rewrite endpoint bound to 0.0.0.0** — with
the "auth disabled" state being a one-character env var. The server code is careful
(compare_digest, no token in URLs, bounded workers, symlink-realpath walk guards), and
that care makes the empty-token door more dangerous, not less: the design presumes the
operator will never use it, but advertises it in the module docstring as "the
operator's decision about their own network."

**Impact (beta):** a homelab user port-forwards 8842 "to review on their phone" —
exactly the audience a public beta recruits — and a crawler finds an open root-owned
mutation service.

**Recommendation:** (1) log a WARNING at startup whenever `REVIEW_BIND=0.0.0.0` and
auth is disabled; (2) put the token lifecycle (where it lives, the `docker exec cat`
command, and the *existence* of the empty-token opt-out with a dire warning) in the
README's quick start, not just the module docstring; (3) add `REQUIRE_TOKEN=1` as a
belt that makes `REVIEW_TOKEN=` a hard error rather than a silent posture change.
The GET-route path-disclosure finding from LUNA F1 stands: read routes reveal full
filesystem paths of the media tree unauthenticated.

### F2 — P1: `mux.process()` deletes the source video before the mux result is durably stamped; mp4→mkv conversion is the one path with **no backup of the original container**

`mux.py::process` calls `_finalize(out, final)` (atomic replace of the mp4 with the
mkv), then `os.remove(orig)` — the mp4 is **gone** — and only *then* does
`write_stamp` run, with a failure path that logs `stamp-write-failed` and returns. The
comment correctly identifies the consequence ("the next sweep redoes the whole
multi-GB mkvmerge — every sweep, forever"), but it understates the mp4 case: the
sweep **re-runs `mkvmerge` on `final` (the mkv), which is fine — but if the stamp
never lands because the config volume is unwritable, the episode re-muxes on every
MERGE_INTERVAL forever, ~1800s timeout each, on a library of hundreds of episodes**.
The mkv→mkv path at least has the old file preserved inside `_finalize`'s atomicity;
the mp4→mkv path irreversibly discarded the original container layout (audio track
order, original mp4 fallback for players that prefer it, any player-specific
metadata) before anything validated *durability*, only *verify()*. `verify()` runs
before finalize — good — but `verify` cannot see a stamp-write failure or a
post-replace sidecar-removal failure.

This is the sharpest media-mutation surface in the repo and the docstring's own
threat model ("never fail an episode") treats it as an availability bug when for an
mp4-source library it is a **one-way content transformation without a dry-run
ledger of what changed**. The README markets mp4 remuxing as a feature with no
mention that the .mp4 is consumed.

**Impact (beta):** first-run users with mp4-centric libraries lose the original
containers and have no documented rollback.

**Recommendation:** write the stamp **before** `os.remove(orig)` (the stamp
references the final file; its failure should abort the removal, not follow it);
document mp4 consumption in the README; and write a one-line rename-marked
`<stem>.replaced-mp4` tombstone (or a per-run manifest) so an operator can see what
the container transformed.

### F3 — P1: `merge_pass.sh` still runs stages with no exit-code checks, and the mitigations two prior reviews flagged remain unwired

Confirmed DEEPSEEK F5 and LUNA F2 with fresh evidence of the exact dead code:
`merge_pass.sh` lines `python3 "$APP/repair.py" …` and
`python3 "$APP/dub_signs_merge.py" …` are bare commands with `</dev/null` and no `rc`
capture, under a script that has **no `set -e`**. The two mitigations built for this —
`write_stamp(..., stages=...)` and `repair-summary.json` — remain **write-only**:
`grep` shows `stamp["stages"]` has no reader anywhere in production code
(`stamp_valid`/`stale_tiers` ignore it by explicit design), and `_stages_ran()`
infers "repair ran" from the existence of the summary file, which
`repair.process()` writes **unconditionally at the end of `main()`'s loop**, even
when every target was skipped, the LLM endpoint was down (all `llm_empty`), or the
model produced nothing. So the stamp can say `repair: true` for a pass that repaired
zero cards, and `signs_merge: true` for a sidecar that exists only because a
transient ffmpeg failure fell back to dialogue-only (LUNA F7's mechanism, which I
confirm).

**Impact (beta):** a beta user's first week runs with Ollama misconfigured (the most
likely single misconfiguration — it's a separate service on a different host by the
README's own env-var table). Every episode silently "completes" with unrepaired ASR
text, is stamped, and never revisited. They will file bugs about "dubtitles look like
raw Whisper output" that nobody can triage from the artifacts, because the artifacts
all say success.

**Recommendation:** (1) `set -e`-safe per-stage rc capture in `merge_pass.sh` with a
structured `.dubtitles.stage-status.json`; (2) make `stamp_valid` (or a mux pre-check)
**fail the mux closed** when `stages.repair is False` and the episode had targets;
(3) read `stages` or stop writing it.

### F4 — P1: `watch_queue.py` writes the GPU queue file with a non-atomic `open(...,"w")`, and an empty/truncated file silently idles the GPU sweep for 6 hours

Confirmed DEEPSEEK F3. Fresh corroboration of the blast radius: `gen_loop.sh`'s only
guard is `[ ! -f "$ORDER" ]`, an *existing but empty* file is legal, and
`build()`'s own tri-state protection is bypassed by the *write* being the
non-tri-state part — `match_dirs()` returning zero hits for a renamed library
produces `order == []`, which `main()` writes as an **empty file through the same
happy path** as a real result (the `unmatched` warning prints to stdout of a
`docker logs` stream nobody is tailing). Every other durable write in this repo is
mkstemp+`os.replace`; this is the one file a *GPU-days-scale* consumer treats as
authoritative.

**Impact (beta):** a user renames a library folder (moves media to a bigger disk, a
completely ordinary beta-week action) → the container goes silent for
`RESCAN_INTERVAL` (default 6h) with zero log signal, while `docker ps` shows healthy.

**Recommendation:** temp+`os.replace` in `watch_queue.main`; treat a zero-hit
`build()` as its own refused-to-write state (or at minimum refuse to write an order
file containing zero shows); have `gen_loop.sh` log loudly when `$ORDER` parses to
zero shows and skip the idle period.

### F5 — P1: `review_apply.apply_episode` re-muxes episodes whose verdicts are already shipped, and the `at` field built to prevent exactly this remains unread

Confirmed DEEPSEEK F1, and I traced the full write path to make sure it is still
live at HEAD: `decisions.record` stamps `at: time.time()` with a docstring that
*states the exact failure it prevents*; `grep` finds **no production reader** of
`at` — only two tests assert it is written. `apply_episode` counts `changed` on any
`for_orig` hit (including `accept` verdicts that changed no word — measured 78% of
admitted repairs), rewrites the SRT, drops the stamp, and the merge loop re-muxes a
multi-GB file to reproduce text that is already on screen. The Apply button's cost
is unbounded by its actual work.

**Impact (beta):** the first review session on a caught-up library triggers a wave of
multi-GB re-muxes that accomplish nothing visible, on a GPU already saturated by
first-run transcription. This will read to a new user as "the beta is melting my
disk."

**Recommendation:** compare each verdict's `at` against the stamp's mtime before
counting it; count only text-changing verdicts (`reject`/`correct`/`force`, or an
`accept` whose proposal differs from conf) toward `changed`; say in the API response
what was skipped and why.

### F6 — P1: two concurrent writers to the decision store, no cross-process lock — the premise in `decisions.save`'s own docstring is false at HEAD

Confirmed DEEPSEEK F4 and still true. `unresolved.main --review` records
`decisions.record` + `decisions.save` in its own process, while
`review_server.handle_decide_batch` does the same in the server process; `_WRITE_LOCK`
is a `threading.Lock` and cannot see the CLI. The docstring says "the review server is
the only writer … if that ever stops being true this needs a lock, not a bigger
docstring." It stopped being true. A lost verdict is a silent, permanent loss of a
human decision — the module's own docstring calls that outcome "worse than one that
errors."

**Recommendation:** fcntl lockfile (or `fcntl.flock` on the store file itself)
around load-modify-save in both `decisions.save` and `unresolved`'s rewrites; or
route all CLI writes through the server.

### F7 — P1: README-facing docs reference files that do not exist, and the deprecation story is wrong in both directions

Fresh finding, and it is a beta-credibility problem more than a code problem:
- README says the deprecated `Dockerfile`'s "old cron-based quick start
  (`docker build -t dub-signs-merge .` + `run-dub-merge.sh`) still works" —
  `run-dub-merge.sh` **does not exist in the repo** (verified: `ls` fails).
- The LUNA review (in-repo, quoted approvingly) references `anime_library.sh`,
  `all_seasons.sh`, and `merge_watcher.sh` as deprecation targets; **none exist**
  (they were presumably removed, and good — but then the docs citing them were never
  updated, and a reader cannot tell which parts of the README describe real paths).
- README's **Roadmap** still lists the web UI, glossary editor, and community
  glossary repo as future work — while `review_server.py` (a web UI, shipped),
  per-show glossaries (shipped), and `glossary_acquire.py` (the acquisition half) all
  exist and work. The "Requirements" section says "both baked into the provided
  `Dockerfile`" but the pipeline actually ships in `Dockerfile.builder`; the
  README's own quick start uses the builder and then the Requirements paragraph
  contradicts it.
- `docs/readme-notes.md` is a working list of **unfixed README inaccuracies** ("One
  Pace is what it has been validated against: include the caveat …", "the episodes
  one pace did not release a dub version of yet are part of muhn pace and those only
  contain english audio and no subs") — the author knows the README overclaims and
  has a scratch file saying so.

**Impact (beta):** the first thing a public-beta user reads is the README, and its
setup story points at a nonexistent script and a deprecated image. First-impression
trust is the entire game of a beta.

**Recommendation:** a docs pass that (a) removes/regenerates every command a fresh
clone cannot run, (b) rewrites Roadmap to show shipped-vs-pending, (c) promotes the
`docs/readme-notes.md` corrections into the README itself, (d) adds the
Wiki-link parity note (the wiki is on a private Git host, `git.ourserver.party` —
for a public beta this needs to move to the public repo's own docs, see Beta
section).

### F8 — P2: the bundled English-wordlist fallback silently weakens the phonetic-name guard on any non-container install

`glossary.py` reads `/usr/share/dict/american-english` and falls back to a bundled
`common_words.txt` sitting next to it. Verified: `Dockerfile.builder` COPYs
`common_words.txt` **and** apt-installs `wamerican`, so the container is fine. But the
dev path (`pip install -e ".[dev]"`, which pyproject explicitly supports) has neither
`wamerican` nor any copy step for `common_words.txt` into `site-packages` — it works
only when the CWD is the repo root, and `pyproject` declares `py-modules = []`
(pure dependency shim). A beta contributor who clones, installs, and runs the
pipeline from a different CWD gets a **silently different `is_english()` wordlist**
(the fallback file or, if that is also missed, `_COMMON_FALLBACK`'s ~100-word
string), which directly feeds the proper-noun gates that stop hallucinated names.
No error, no log, a different guard.

**Recommendation:** resolve the wordlist against `__file__` (already done for
`_BUNDLED` — good) but *also* log which wordlist source and word count was loaded at
startup; add a test that runs from a non-repo CWD.

### F9 — P2: `review_server` read routes leak absolute filesystem paths of the media tree to any unauthenticated LAN peer, and the paths are stable across restarts

Confirmed LUNA F1's GET-route finding and adding the operational detail the LUNA
review did not: the index JSON (`/api/episodes`) returns `stem` (absolute path) for
every episode; `/api/shared` returns per-show path-derived labels. Unauthenticated.
On a homelab LAN this is a media-library inventory (show names, episode counts,
library layout) served to any device that asks, and the same values the *write*
routes need are thus already published — the token's job is reduced to "know a
secret that the page itself tells you where to find." Bounded, but a beta reviewer's
threat model ("can I expose this through my reverse proxy with basic auth off?")
does not match the code's ("LAN is trusted").

**Recommendation:** either gate GET routes on the same token (the UI already has a
token box — it can send it on GETs trivially), or serve stems as opaque IDs resolved
server-side. Cost is small; the posture claim in the module docstring ("they expose
only what is already on the operator's disk") is true but not the threat model a
beta user will have.

### F10 — P2: `common.extract_sub` still burns a guaranteed-failed `ffmpeg -c:s copy` on every subrip source and discards the failure

Confirmed DEEPSEEK F6's mechanism, and I verified it is unchanged at HEAD: the copy
attempt on a subrip stream produces a 0-byte `.ass` (ass muxer refuses non-ASS
input), the fallback re-encode then runs, and the first failure's rc/stderr are
discarded. The miner accepts subrip (`mine_glossary` explicitly does), the anchor
consumers do not (`eng_sub_tracks` filters `codec_name in ("ass","ssa")`). Two
policies about one track format; the pessimistic one wins exactly where anchoring
matters most (unanchored repair is the least-verifiable class), and every
subrip-signs episode pays a wasted ffmpeg invocation.

**Recommendation:** probe codec first and only attempt `-c:s copy` for ASS input;
decide and document whether a subrip fansub is a dialogue anchor (the miner's
position says yes; the repair stage says no).

### F11 — P2: `plex_refresh.py` puts the Plex token in the URL — and this module's failures are *always* logged with the URL

`q = "?X-Plex-Token=" + tok` then `url` is used in `urlopen`; on any exception the
`print("plex refresh fail:", e)` surfaces `HTTPError` strings that include the full
URL. The token therefore lands in `docker logs` on the first misconfiguration —
the same log stream the review server prints its token to (that one is deliberate
and once; this one is unintentional and every time). LUNA F10 flagged the general
class; the specific fix is one line: use the `X-Plex-Token` header (Plex supports
it), or redact `e` before printing.

**Impact (beta):** a token pasted into a GitHub issue by a helpful beta user who
"just included the logs."

**Recommendation:** header-based auth; redact URLs in all error prints
(`watch_queue._get` already does `url.split("?")[0]` — copy that idiom here).

### F12 — P2: `gen_loop.sh` `VERIFY_TIMEOUT`/`ACQUIRE_TIMEOUT` kills can produce partial glossary writes that later reads treat as authoritative

`timeout "${VERIFY_TIMEOUT:-1200}" python3 glossary_verify.py` — on SIGTERM the
process dies between `glossary_verify.apply_results` and its save, or worse *during*
the atomic write (which is atomic, so the file is fine) — but the *page-index
cache* and the `verified` set can be persisted in separate steps, and `acquire`'s
cache is saved unconditionally even when the run was killed mid-harvest (the
gen_loop comment itself records a 2026-08-21 kill "mid-harvest"). A killed run can
therefore leave an acquire cache that says "verdicts exist" for proposals the run
never actually adjudicated — and the interim `ACQUIRE_NO_CACHE=1` dry-run workaround
in gen_loop exists precisely because the cache already suppressed 10,708 verdicts
once. The workaround is documented as "INTERIM, proper fix next session" with no
tracking issue I could find.

**Recommendation:** promote the INTERIM note to an issue/TODO file; make acquire's
cache save conditional on clean exit (signal handler or exit-code check).

### F13 — P2: `REVIEW_BIND=0.0.0.0` default + `MAX_CONCURRENT=16` semaphore is closed-connection DoS-resilient, but the **stems walk is unauthenticated and cached for `elapsed × 20`**

A fresh angle on LUNA F1's resource concern: the stem cache TTL is derived from the
walk cost (`_stems_ttl = max(30s, elapsed*20)`); a slow CIFS mount means a cold
unauthenticated GET `/api/episodes` pins one worker for the walk (~300s measured on
the live library) and then *poisons the cache lifetime to 100 minutes*. Four cold
requests an hour apart keep the cache effectively never-warm and the library walked
4×/hour by any unauthenticated caller. The bounded-worker design converts an
availability attack into a slow, free library-walk amplifier.

**Recommendation:** require the token for GET `/api/episodes` (see F9) or cap the
TTL ceiling.

### F14 — P2: branch hygiene — the review branch is behind `main`, and the working tree carries a second full checkout

Confirmed DEEPSEEK F8 at HEAD: `git merge-base main HEAD` == HEAD (`main` at
`de4f49e` is ahead with export_subtitles, cache re-warm, and shared-line fixes this
branch lacks); untracked in-tree is `.claude/worktrees/agent-ac3be5ad706056049/` —
a full second working copy including its own `.git` and a `.venv`-sized artifact —
plus `skills-lock.json` and two untracked docs. Repository-wide `code_search`/grep
tooling matches the same bug twice in two checkouts; a beta contributor cloning
`main` gets code that differs from the branch all the in-repo reviews were written
against.

**Impact (beta):** the public-facing history and the reviewed history diverge. For a
launch, that is a credibility and correctness problem in one.

**Recommendation:** merge or rebase `feat/review-sorting` into `main`, move the
worktree out of the repo (or `.gitignore` `.claude/worktrees/`), commit or discard
the untracked docs, and tag the beta from `main`.

### F15 — P3: dependency floors are declared but the *effective* stack is pinned by a third-party image tag

`pyproject.toml` declares `pysubs2>=1.7, faster-whisper>=1.2, jellyfish>=1.0` — good —
but `Dockerfile.builder` builds `FROM mccloud/subgen:2026.06.2`, so the *real*
faster-whisper/ctranslate2/CUDA stack is whatever that upstream image ships, and
`pip install pysubs2 jellyfish` inside the image installs the *then-current* versions
unpinned (the `hadolint ignore=DL3008,DL3013` comment documents the tradeoff
deliberately, and the reasoning is fair). The gap: there is no lockfile for the
image's *effective* Python env, so two builds of the same source a month apart can
ship different ctranslate2 behavior with no record. For a beta whose core value is
transcription stability, that is the one reproducibility hole left. The `uv.lock`
exists for the dev venv; the container has nothing equivalent.

**Recommendation:** after the apt/pip layer, `pip freeze` into a checked-in
`constraints` artifact (or `uv pip compile`) and install with it; note the subgen
base tag in the stamp/lastrun so a library can tell which image produced it.

### F16 — P3: CI is two parallel workflows with duplicated, drifting steps

`.github/workflows/ci.yml` runs `ruff` + `pytest` on **Python 3.11** pinned to
`setup-python` v5 commit `a26af6…`; `.github/workflows/test.yml` runs `pytest` on
**3.13** pinned to a *different action commit* (v5 of checkout, v6 of setup-python).
Neither installs the project itself (`pip install -e ".[dev]"`), so neither exercises
the packaging metadata; both install ad-hoc package lists that have already drifted
(ci installs `ruff pytest pysubs2 jellyfish`; test installs `pysubs2 pytest
jellyfish` — and *test.yml* would fail the day a test imports `ruff`-installed
anything, while *ci.yml*'s scoped ruff target list will silently stop matching new
top-level modules). Two workflows with the same trigger and overlapping jobs is one
workflow with extra steps.

**Recommendation:** collapse to one workflow: `pip install -e ".[dev]"` (which also
validates the packaging story F8 depends on), `ruff check .` (repo-wide, the
config-file exclusions already handle prose), `pytest`.

### F17 — P3: no release mechanics exist for the beta itself

Fresh finding, category error of the whole repo: there are no git tags (verified: one
tag, `backup/pre-attribution-strip`), no CHANGELOG, no version past `0.1.0` in
pyproject, no image build/publish workflow, no GitHub Releases, no
`SECURITY.md`, no `CONTRIBUTING.md`, no issue templates (only a PR template), and
the README's only install path is `docker build` from a clone. A public beta
announcement that says "clone and build" filters its own audience to people who
already have a toolchain — and gives them no way to pin, update, or roll back.

**Recommendation:** see the Beta-readiness section below — this is its top item.

---

## Smaller items (verified, lower stakes)

- **`mux.process()` writes the mux log with plain `open(...,"w")`** — fine under the
  module-level umask, but it is the one mux output not atomic; a crash mid-write
  leaves a truncated `mux.log` that `reclaim_orphans`-style tooling could misread.
  (Consistency nit only; nothing reads it critically.)
- **`hallucination.BLOCKLIST` is load-time state**: `_load_blocklist` reads
  `data/hallucination_blocklist.txt` at import; a beta user who edits the file to
  tune their library sees no effect until restart, and there is no log line saying
  how many patterns loaded. Same shape as F8: file-dependent behavior with no
  startup visibility.
- **`review_server._words` folds `…`/em/en dashes to space but `risk_class` treats
  any resulting word-count change as "words"** — an em-dash-to-period repair
  (`it—was` → `it. Was`) is scored `words` (a token added), sorting *above*
  punctuation-only rows and inflating the apparent risk of a large class of
  mechanical repairs. Measured intent elsewhere in the file says punctuation-only
  repairs are the 78% tail; this classification works against that intent for the
  dash subset. Cosmetic ordering cost only.
- **`watch_queue` `PER_PAGE=1000`/`MAX_PAGES=100`** — a 100k-history library
  (WatchState retains everything) silently stops paginating at 100k with no warning;
  the backstop is correct for now and wrong for "large" — log when the cap is hit.
- **`common.SUB_LANGS` default `\"eng,en,und,\"`** — the trailing comma produces an
  empty-string member in the set, which is then compared against language tags; it
  matches nothing, but it means the "accepted" set is quietly one larger than the
  documented default and a `SUB_LANGS=,` misconfiguration reads as "all langs
  accepted" rather than failing. Harmless today; trap-shaped.

---

# Beta-readiness assessment

**Verdict: not ready for a public beta this week; ready for a small, explicitly
"expect rough edges" beta after roughly a focused week of work.** The pipeline
engine is in better shape than most v1.0 OSS (the versioned stamp/tier system, the
decision store, the review loop, and the test discipline are genuinely above-average);
what is missing is everything a *user* touches on day one.

## Must-do before announcing anything (blocking)

1. **Public install path.** Publish the built image (GHCR via a new Actions job —
   the repo already has Docker build knowledge in-repo) so the quick start becomes
   one `docker run` with pinned tags. A clone-and-build requirement will halve the
   beta audience and triple the support load.
2. **README truth pass** (F7): fix the nonexistent script reference, the
   Dockerfile/Dockerfile.builder contradiction, the stale Roadmap, the
   private-wiki links (a public beta cannot link `git.ourserver.party` for setup —
   move the wiki content into `docs/` until a public wiki exists), and fold in the
   `docs/readme-notes.md` corrections (especially the "validated against One Pace"
   caveat, which is the single most important expectation-setting sentence the
   product needs).
3. **Legal/expiry framing for a caption generator.** The tool transcribes
   copyrighted dubs and merges fansub typography. The README never states the
   intended use boundary ("media you own, personal use, no distribution"). Before a
   public launch, add a prominent usage/legal section and decide the stance on
   shipping per-show glossaries mined from fansubs (the `glossaries/` directory
   currently contains fansub-derived name lists for 14 commercial titles —
   defensible as facts/short phrases, but say so deliberately, and consider
   stripping them from the public artifact if the answer is "keep private").
4. **The review-server posture** (F1/F9/F13): decide LAN-trusted vs token-gated GETs
   and put the decision in the README; log a warning on the auth-disabled
   combination.
5. **Mux safety for mp4 libraries** (F2): stamp-before-remove ordering, plus one
   README sentence: "mp4 episodes are converted to mkv; the original container is
   not preserved."
6. **Release mechanics** (F17): tag `v0.9.0-beta.1` from `main`, write a short
   CHANGELOG (the bump history in `common.py` is 80% of one already), add
   SECURITY.md (contact + the review-token model) and a minimal issue template.

## Should-do (first beta week)

7. Stage-exit-code checks + consuming `stages` in the stamp (F3) — this is the
   difference between "beta users find bugs" and "beta users file unreproducible
   quality complaints."
8. Atomic order-file write + empty-queue refusal (F4) — cheap, removes the worst
   silent-outage mode.
9. Decision-store cross-process lock (F6) — cheap; a lost verdict is a beta
   reviewer's worst moment.
10. Apply-button `at`-awareness (F5) — prevents the "beta melted my disk" first
    session.
11. CI consolidation (F16) + one workflow that `pip install -e ".[dev]"` to keep
    the packaging story honest.
12. Branch hygiene (F14): merge the review branch, clean the worktree, tag from
    `main`.

## Explicitly fine to defer past the beta

- Subrip-as-anchor policy decision (F10) — document as a known limitation.
- Wordlist startup logging (F8) — container installs are unaffected.
- Queue-file compaction (DEEPSEEK F7) — real, slow-decay, not beta-blocking.
- Model A/B expansion (`docs/model-candidates-4-5gb-vram.md`) — the bake-off
  discipline should stay internal until there is a result worth shipping.

## Beta-shaped product gaps the roadmap should absorb

- **A first-run health check.** One command/endpoint that reports: GPU visible,
  Ollama reachable, glossary dir writable, Plex reachable, review token present,
  disk free. Every F-category finding above manifests as "one of these is silently
  wrong"; a beta user with a checklist turns triage from archaeology into a
  screenshot. The repo's own culture of counters (`qc.Recorder`, repair summary
  buckets) is the right instinct — point it at onboarding.
- **Per-episode quality manifest.** The repair summary exists per episode but
  nothing aggregates. A `/api/quality` page (targets/repaired/skipped/llm_empty per
  show, worst first) would surface F3-style silent regressions *to the user*, not
  just to the operator.
- **An uninstall story.** Every sidecar the pipeline writes into the media tree is
  documented, but there is no documented "remove DubTitlerr cleanly" (delete stamps,
  extract `Dubtitles` tracks, remove sidecars). Beta users who leave will either
  leave artifacts (support burden) or hand-delete media files (worst case). The
  existing `tools/reclaim_orphans.py` is 70% of this.

---

# Promotion recommendations (where to announce the beta)

The product's natural audience is the self-hosted *-arr ecosystem. Ranked by
fit × effort:

1. **r/selfhosted + r/PleX + r/Jellyfin (Reddit).** The single highest-yield
   channel for this exact tool. The demo that sells it is one screenshot: a Plex
   subtitle-track picker showing "Dubtitles (full)" on a dubbed anime episode with
   signs rendered. Post as "I built a thing," not as an announcement — Reddit
   norms reward build-in-public framing. Cross-post to r/anime's
   discussion/merch day if the mods allow tools.
2. **The *arr ecosystem's orbit.** A "similar tools" or community-tools listing on
   the Radarr/Sonarr/Prowlarr wikis/Reddits, and the *Trash Guides* community if
   receptive. This is where "I have a big anime library and English dubs" people
   already are.
3. **GitHub Trending via launch hygiene.** A single well-formed release (tags,
   CHANGELOG, image publish, screenshots in the README) timed together gets
   algorithmic lift; none of the individual pieces matter but all of them together
   do. Add a GIF (5–10s, terminal → Plex subtitle menu) to the README top.
4. **The self-hosted newsletters/aggregators:** *Self-Hosted* (podcast) / r/selfhosted
   weekly threads, *selfh.st* and *selfhasted* newsletters (both accept
   submissions), Awesome-Selfhosted PR (requires the project to meet its
   criteria — mature licensing, docs, which the blocking items above also produce).
   Also **Alternativeto.net** and **LibreHunt**-style listings for long-tail SEO.
5. **The anime-technical niche:** r/animepiracy-adjacent tooling threads where
   subgen/MCCloud's own tool circulates (subgen's README/Discord community is the
   exact user base — a friendly "DubTitlerr builds on/coordinates with subgen"
   note is honest and targets precisely the right people), the **Plex forums**
   subtitle/Plex-Meta-Manager threads, and the **Jellyfin forum**'s subtitles
   section.
6. **HN ("Show HN")** only *after* the blocking items — the submission will be
   judged on the README in the first 60 seconds, and today's README would draw the
   fire (broken doc links, no usage boundary). With them, the interesting
   discussion angle is the pipeline design (local LLM repair + human review loop +
   two-tier idempotency), which is genuinely novel and would land well.
7. **What *not* to do first:** don't post to r/datahoarder or general anime
   subreddits before the legal/usage framing exists (item 3 above); a caption
   generator announced without a personal-use boundary invites exactly the
   copyright argument that would define the project's reputation permanently.

Timing suggestion: one week of blocking-item work → soft launch (Reddit + subgen
community) with "beta, expect bugs, tell me your library's shape" framing → two
weeks of triage → Show HN + newsletters with the stability story and the
review-loop screenshots.

---

# Rebuttal — the case against every finding above

This review argued as hard as it could; the repo argues back. Finding by finding,
here is the strongest case that each is wrong, overstated, or already answered —
because a review that cannot rebut itself is just a list of opinions.

**Rebutting F1 (review-server auth posture).** The server's design already fails
safe in every state a beta user can reach: unset token generates and persists one
and prints it with the exact `docker exec` command; the empty-value opt-out requires
deliberately setting an env var to empty — not something that happens by accident,
and the README never teaches it. `REVIEW_BIND` is configurable; the operator who
port-forwards a homelab service has already made a deliberate exposure decision
about Plex, Jellyfin, and everything else on the same host, all of which hold media
libraries and equally disclose titles. Calling the GET routes a "leak" presumes a
threat model (hostile LAN peer) that the product's own environment (family/home
network) does not have, and gating GETs would break the one UX property the review
page has (paste token once, browser remembers, page works). The REQUIRE_TOKEN
suggestion adds a third token knob to a design that already distinguishes
set/unset/empty carefully — more knobs is how the current care gets eroded.

**Rebutting F2 (mp4 removal before durable stamp).** The ordering complaint
inverts the actual failure economics. Stamp-then-remove means a crash between the
two leaves a stamped episode whose sidecars survived — which the pipeline's own
`stale_version_stamp` docstring identifies as the *most dangerous* state (a version
bump silently no-ops on exactly those files). The current order — finalize, remove,
stamp, with `stamp-write-failed` as a loud named status — fails toward
"re-mux every sweep," which is wasteful but self-healing and *loud*, over "silently
skip a library that a stale stamp poisons." The mp4→mkv conversion is not data
loss: every stream (video, audio, all subs, fonts, chapters) is stream-copied; the
container changes, the content does not, and MKV strictly superset-supports the
relevant features. The user who "loses" the mp4 lost a wrapper.

**Rebutting F3 (stage exit codes / write-only `stages`).** True that nothing reads
`stages`; false that the system is blind. `repair-summary.json` is *readable
evidence* — `llm_empty` per episode is exactly the signal F3 claims is invisible,
and the summary's own invariant test (`test_every_target_lands_in_exactly_one_summary_bucket`)
pins that the buckets reconcile to targets. The operator who misconfigures Ollama
sees `llm fail:` lines per card in `docker logs` and a repair summary with
`llm_empty == targets`. The critique is "the evidence is not machine-consumed"; the
defense is "the evidence exists, is human-consumable, and the fix (gating mux on
repair rc) converts a soft-failure stage into a hard gate across a library where
some episodes legitimately have nothing to repair — reintroducing the
never-fail-an-episode contract the whole architecture chose against." The right
first step is the aggregator page (Beta-gap #2), not a gate that bricks sweeps.

**Rebutting F4 (order-file atomicity).** `watch_queue.main` writes the file only
after `build()` raised-or-returned successfully, and the two *sources* being
unreachable both refuse the write — the truncated-file scenario requires a kill
inside a sub-millisecond `open/write/close` window of a file that is, in the common
case, a few dozen lines. The renamed-library case (empty order) is real but
self-inflicted and *visible*: the unmatched-titles warning prints the exact shows
that failed to match. The 6-hour idle is the designed idle after any sweep;
`gen_loop` re-runs watch_queue on the next pass, and a rename that persists past
one idle will print its unmatched list every pass. Atomic replace would be nicer;
"silently idles forever" overstates it.

**Rebutting F5 (Apply re-muxes shipped verdicts).** The `at`-comparison proposal
assumes the stamp's mtime is a reliable proxy for "what the muxed track contains,"
which the repo has already measured false: the 2026-08-29 note records 11 of 20
corrections absent from the shipped track *after* a mux — the mux happened, the
text did not ship. An mtime comparison would have marked those as shipped and left
them wrong forever. Recounting `accept`-only verdicts as no-ops is safe in
isolation but wrong in composition with that fact: an `accept` on a line whose
repair never actually landed is exactly the case Apply exists for, and the queue
entry — not the verdict — is what says the line was admitted. Re-muxing to be sure
is expensive; shipping text the reviewer approved that never reached the file is
the failure this module was built to end.

**Rebutting F6 (two-writer decision store).** The CLI `--review` path and the
server are alternative *interfaces to one operator's review session*; the collision
window is two writes to the same store in the same minute by the same human, who
is by construction not doing both at once. `unresolved.resolve`'s whole-file
rewrite has the same shape and the same effective protection. A flock is cheap and
I would take it — but the lost-verdict scenario requires a workflow the product
does not have, and the docstring's conditional ("if that ever stops being true") is
arguing about a deployment (unattended CLI writes during a server session) nobody
runs.

**Rebutting F7 (docs rot).** The README accurately documents the *builder* quick
start as the primary path and flags the old Dockerfile as deprecated in the same
section; the `run-dub-merge.sh` reference is one sentence in a deprecation note,
not the install path; and `docs/readme-notes.md` is a scratch file of corrections
in progress, not evidence of unresolved overclaim — the "validated against One
Pace" caveat exists in the README's own One Pace references for anyone who reads
past the header. The Roadmap lists a *dashboard* web UI with glossary editing and
queue control; the review server is a verdict page, and calling the roadmap stale
conflates the two. The wiki-host link is the one legitimately blocking item in the
finding, and it is a one-hour fix.

**Rebutting F8 (wordlist fallback).** The bundled fallback exists *precisely* for
the non-container case, resolves via `__file__` (CWD-independent by construction —
`os.path.dirname(os.path.abspath(__file__))`), and the `-e .[dev]` install does not
need to copy it because the file lives in the repo the user cloned and the module
finds it by its own path. The claimed failure requires importing `glossary` from an
installed wheel that does not exist (the project ships `py-modules = []`
deliberately and documents why). The dev path is a clone; a clone always has the
file.

**Rebutting F9/F13 (unauthenticated reads, walk-amplification).** The data exposed
is show names and episode counts — the same information any DLNA browse, Plex
share, or Jellyfin dashboard on the same network discloses, plus it is the
operator's own LAN. The walk-amplification figure assumes an attacker who keeps
cold-cache timing against a cache whose TTL is *derived from the walk cost* — the
design already prices the attack: each 300s walk buys a 100-minute cache, so an
amplifier is capped at ~36 walks/day and each walk is read-only `os.walk`+stat on a
filesystem the operator's own Plex scans constantly. Bounded, priced, read-only.

**Rebutting F10 (subrip copy attempt).** The wasted ffmpeg invocation is bounded
(180s timeout, typically <1s on failure) and the fallback has produced correct
results in production for the entire library history. The policy asymmetry is
defensible as-is: a subrip track's *names* are mineable text, but its *timing and
positioning semantics* are not ASS-equivalent, and anchoring repair on a subrip
fansub would silently change the reference-quality profile that the entire guard
calibration (borrow limits, phonetic thresholds) was measured against. "Two
policies" is also just "two consumers with different requirements."

**Rebutting F11 (Plex token in URL).** True, one line, worth fixing — and the
beta-risk claim assumes a user pastes merge-pass logs into an issue without
redacting, which the same user who just configured `PLEX_TOKEN` from a
setup guide has been told (by Plex's own docs) is sensitive. The error string
includes the URL only for HTTPError; the common failure (unreachable host) prints
a URLError with host only. Real, small, not a beta blocker.

**Rebutting F12 (timeout kills leave partial state).** The acquire cache is
designed to be *disposable evidence*, and the interim `ACQUIRE_NO_CACHE` workaround
exists, is documented in-line with measurements, and disarms the exact suppression
the kill could cause — the system already defends against its own known wound in
the one mode where the wound matters (dry runs). The "proper fix next session"
note is a known-limitation comment in a codebase that has converted every such
comment into a tracked doc so far.

**Rebutting F14 (branch hygiene).** The branch is behind `main` because the work
is *stacked and unmerged by choice* mid-review; the worktree is the agent harness's
own and does not ship; `git status` being dirty costs nothing at runtime. The
claim that a contributor cloning `main` gets code that differs "from the branch all
the in-repo reviews were written against" is true of every stacked-branch workflow
on earth and resolves at merge time, which the launch checklist explicitly
requires before tagging.

**Rebutting F15 (unpinned container env).** The unpinned-apt reasoning is
documented in-file and correct: Debian pool rotation makes pinned versions rot
faster than drift arrives. `uv.lock` pins the dev env; the image's effective env is
recorded in the subgen base tag + the layer history (`docker history` reproduces
it), and the lastrun already records the *whisper model*, which is the variable
that actually changes transcripts. ctranslate2 patch versions within a pinned
faster-whisper range have not changed transcription output in any measurement this
repo has run.

**Rebutting F16 (two CI workflows).** They are not duplicates: `ci.yml` is the
ruff+test gate with a scoped lint list that was deliberate ("the other legacy
scripts are linted as later steps touch them"), and `test.yml` is the
forward-compatibility canary on 3.13 — running the suite on the newest Python the
repo may adopt, which 3.11-only CI would never catch. Two Python versions in one
workflow matrix would be the cleaner shape; "drift" between two files whose jobs
differ is not the bug it reads as.

**Rebutting F17 (no release mechanics).** True and the review is right — with the
caveat that this is a *pre-launch* repo by definition, and every prior review
(e.g., the beta-spec commit `084b6e0` in this branch's history: "docs(spec):
public beta scope, settled in 15 decisions") shows the release work is planned,
sequenced, and unstarted rather than unnoticed. A finding that restates the
roadmap is not a defect.

**Rebutting the smaller items.** The mux log is diagnostic-only by design; the
blocklist is load-time because blocklist edits are a configuration act (restart =
config change, like every service on earth); the em-dash risk-classification cost
is a *sorting* bias on a page whose whole point is surfacing the top of the queue,
and the `data-start` attribute already exposes exact times for a reviewer who
disagrees; the pagination cap is a backstop, and the day it fires, the warning is
one log line away; the `SUB_LANGS` trailing comma is parsed identically everywhere
in the codebase and matches nothing — a trap with no spring.

---

## What the rebuttals concede, on balance

Stepping back out of advocate mode: the strongest surviving points after both sides
are heard are **F3 (evidence exists but nothing consumes it — the aggregator would
have caught the actual measured failure), F4's zero-hit write (one `if not order`
line), F5's apply-cost (bounded by the 78% measurement), F7's wiki link and the
deprecation sentence, F11's one-line redaction, and F17**. Everything else is
either priced-by-design, defended by a measurement in-repo, or a judgment call
where the code's choice is at least as defensible as the review's. That is the
signature of a codebase whose review culture works: most of an adversarial pass
dies on contact with the repo's own docs.

The one thing the rebuttals do *not* rescue is the beta-gating conclusion: F17 +
the README items + the review-server posture are all product-surface issues, and
the code's excellent internal defenses do none of the work those need.
