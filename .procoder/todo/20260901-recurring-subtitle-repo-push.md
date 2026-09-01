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

- [ ] A documented (or scripted) mechanism exists for pushing new/changed subtitle
      exports to the public subtitle repo without a person re-running today's manual
      steps by hand.
- [ ] The mechanism states its own cadence and change-detection rule explicitly.
- [ ] `tools/export_subtitles.py` (added 2026-09-01) is reused or explicitly
      superseded — not duplicated.

## Evidence

