# Recurring push to the public subtitle repo

Status: open
Created: 2026-09-01

## Description

A one-off export of every completed-dubtitle One Pace episode was pushed to the new
public subtitle repository today (2026-09-01), gated only on a valid `.dubtitles.done`
mux stamp — NOT on decision 11's per-line review gate (see
`docs/superpowers/specs/2026-08-31-public-beta-design.md`, Workstream C; that gate is
still the bar for a "reviewed" release, just not for this WIP drop). The owner asked
for a note that this week we still need an easy, repeatable way to push new/changed
subtitles into that repo as the pipeline keeps producing them, rather than doing this
by hand again.

Open design questions this task should resolve, not silently decide:

- Cadence: on every mux (event-driven from merge_pass.sh), or a periodic sweep?
- What counts as "changed" for an episode already in the repo (re-mux after a
  TEXT_VERSION bump, a review verdict landing, a corrected glossary re-run)?
- Whether the strict `tools/export_reviewed.py` gate and this WIP export ever merge
  into one mechanism with a status field, or stay two separate tools/repos long-term.

## Acceptance criteria

- [x] `tools/publish_subtitles.sh` runs the export across every show and commits+pushes the
      result. Dry run by default; `PUBLISH_APPLY=1` publishes.
- [x] The mechanism states its cadence and change-detection rule in its own header, and the
      change rule is enforced in code rather than described:
      `tests/test_export_subtitles.py::test_a_remux_that_produces_identical_bytes_is_not_republished`
- [x] `tools/export_subtitles.py` is EXTENDED, not duplicated or superseded. The reviewed
      gate is `unresolved.undecided` -- the same call `export_reviewed` makes, imported
      rather than reimplemented.

## Decisions (owner, 2026-09-02)

The three questions this task existed to ask, and the answers:

1. **Cadence: twice daily, 08:00 and 22:00** (`deploy/dubtitlerr-publish.timer`). The two
   slots do different jobs. 08:00 ships what the generate/merge loops finished overnight.
   22:00 ships what a human reviewed during the day -- a verdict reopens its episode, so
   the re-mux has to land before the export can see the corrected text, and an evening slot
   is what makes a day's review reach the public repo the same day. Periodic and decoupled
   from `merge_pass.sh`, not event-driven: publishing is irreversible once anyone clones.
2. **"Changed" means the CONTENT changed** -- sha256 over the published `.ass`+`.srt`, held
   in the manifest. Not stamp mtime, not `text_version`. The 8->9 bump re-derives and
   re-muxes the whole library while altering the output of only the 24 shows carrying
   Japanese song lyrics, and an mtime rule would have republished everything to ship that.
   A stamp fingerprint is kept as a cheap pre-filter so an unchanged episode never pays for
   an ffmpeg extraction, but it can only say "look again", never "publish".
3. **One tool, one repository, a `status` field.** Two tools that both walk the library and
   both build manifests drift; the cost of two writers of one artifact was measured twice
   on 2026-09-02. `export_reviewed`'s stricter gate becomes a per-episode status, which
   matters because it qualifies ZERO episodes today -- a separate reviewed repository would
   ship empty.

Also settled: **no LICENSE file in the subtitle repository** -- it is subtitle text, not
code, and does not need copyleft; DubTitlerr stays GPL-3.0 for the tooling. And **the
`.ass` ships**: carrying signs and songs alongside dialogue is the point of dubtitles, not
a side effect. (An audit reading of SAO's 5,096 kept events as fansub karaoke was wrong --
that show is dense with video-game HUD screens, which is exactly the content this is for.)

## Evidence

Implemented on `feat/review-sorting`, 2026-09-02.

- `export_subtitles`: `content_hash`, `source_fingerprint`, `read_manifest`, `plan_export`,
  classifying every episode as new / updated / rederived-identical / unchanged / skipped and
  printing the count that actually needs republishing. `is_reviewed` sets `status`.
- `tools/publish_subtitles.sh` -- the runner. Refuses a `SUBS_REPO` that is not a git
  checkout, continues past a show that fails rather than abandoning the library, exits
  without committing when nothing changed, dry-run unless `PUBLISH_APPLY=1`, writes no
  LICENSE.
- `deploy/dubtitlerr-publish.{service,timer}` -- the 08:00/22:00 schedule, `Persistent=true`
  so a missed run publishes at next boot. Both pass `systemd-analyze verify`.
- 4 new tests, mutation-checked both ways: replacing the content hash with a
  fingerprint-only rule fails the rederived test; removing the pre-filter fails the
  unchanged test. Full suite green (exit 0).

NOT done, deliberately: the units are written but NOT INSTALLED on vm102, and the manifest
still carries the full release filename (`[WEBRip-1080p ...]-Trix`) as `episode_title`.
Both are the owner's call at deploy time; the second was raised in the publish audit and is
not yet answered.
