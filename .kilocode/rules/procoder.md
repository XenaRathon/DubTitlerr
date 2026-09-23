# DubTitlerr — agent notes

Self-hosted \*-arr-style service: transcribes English-dub audio into "dubtitles," repairs them
with a local LLM, merges the on-screen signs/songs track into the same subtitle file, and muxes
the result into the library. Runs as one long-lived worker container against a live anime
library — treat it like production media infrastructure, not a script: a bad run can burn hours
of GPU time or leave an episode's subtitle track worse than before.

## Homelab documentation vault — check before stating any infra fact

This repo touches real homelab hosts, NAS pools, and hardware. Before naming an IP, host, or
pool, read the vault: `/home/xenarathon/Documents/obsidian vaults/Xen-Server Documentation`
(plain markdown, no git — start at `Homelab Overview.md` or `01 Hosts/`). `memory_recall`
returns past conversations, which can carry forward a stale or wrong fact (this exact repo has
done that before — see the host history below) — it is not a substitute for reading the vault.
If you find the vault itself is stale while checking, invoke `vault-scribe` to fix it rather
than working around it silently.

## Where this actually runs — verify live, don't trust the last note you read

**As of 2026-09-08: the worker runs on `vm102` (`192.168.1.232`, GTX 1050 Ti passthrough,
R520/Proxmox guest).** Config/glossaries live at `vm102:/home/claude/dubtitle-config`; media is
the R520 NFS export, mounted there as `/media/Anime Library`.

This has moved **three times**: `3200g-docker` (hard-locked repeatedly, GPU physically removed
2026-08-23) → `vm102` → briefly duplicated onto `fasc` as well. **Don't bake today's host into
long-term memory as permanent** — confirm with `docker ps` on the actual box before relying on
it, the same way this note was corrected mid-session on 2026-09-08.

**Incident, 2026-09-08:** a second `dubtitle-builder` container was found running on `fasc`
(`192.168.1.209`) at the same time as `vm102`'s — up 4 days, actively cycling, pointed at the
same R520 media library but with a **separate, blind state directory**
(`/srv/mergerfs/media/Storage/_dubtitle-builder` vs. vm102's `dubtitle-config`). This is exactly
the race condition the "no locking" section below describes, not a hypothetical — it was live.
Stopped on fasc the same day; no `.muxtmp.mkv` leftovers or evidence of an actual file collision
were found on inspection, but that was verified once, after the fact — don't assume it's
impossible, confirm before trusting a "clean" state if this comes up again.

## No locking. None. Treat every workaround as fragile.

`flock`/`fcntl`/`lockfile`/`O_EXCL` — none of it exists anywhere in this repo. The only
coordination is a `.dubtitles.done` stamp plus sidecar-existence checks, both check-then-act
with a >150s window. **Never run two workers against the same media library at once** — they
will race on `<stem>.muxtmp.mkv` (same filename, both writing, the finalize step renames one
over the other) and can re-transcribe each other's episodes. Building a real claim/lock
mechanism is a real, not-yet-done project, not a "just be careful" situation — see the incident
above for what "just be careful" actually produces.

## Testing convention — never validate against One Pace alone

One Pace is the show under active watch, which makes it the natural test target and also the
**least representative** title in the library: it's the only show `glossary_acquire.py` has
ever run acquisition on, it carries nearly all the curated `hard_fixes` (74 vs. 0–3 elsewhere),
and even *within* One Pace, some seasons ship a fansub track to anchor repair against and others
(S29–33) don't — so testing one season answers a different question than testing another.

**Validate against a spread**: one show with a fansub track, one without, one that's run
acquisition, one that's only been mined. And always check the **deployed** glossary
(`vm102:/home/claude/dubtitle-config/glossaries/`), not the repo copy — they're separate files
with separate histories and have been caught 8-of-15 divergent while the repo looked clean.

## Repair backend

`REPAIR_LLAMACPP_URL` points at Nanbeige on `fasc` (`192.168.1.209:8090`, or `:8094` for the
tool-call-repaired endpoint) — unaffected by the 2026-09-07 litellm/SearXNG migration off that
host, since this repo calls the model directly, not through litellm. If repair calls start
failing with `503 Loading model`, that's the backend still warming up after a restart, not
necessarily this repo's bug — check the backend directly before assuming a pipeline regression
(this is exactly what preceded the fasc/vm102 incident above: vm102's run hit a dead backend,
correctly refused to overwrite good text with raw ASR, and stopped).

## Persist incrementally — a cache that only writes at the end is worthless to a stage that never finishes

Expensive stages (`glossary_acquire` in particular) have been killed mid-run by real
environmental failures (600s/1800s timeouts, a hard host lockup) more than once. A design that
only banks results on full success loses everything on a partial run — write per-item or
per-batch (append-only JSONL is the existing idiom, e.g. `unresolved.py`) so a killed run keeps
what it already did. Raising a timeout is a legitimate unblock in the moment; it is never the
actual fix for this class of problem.

## Repo conventions

- **Issues/specs**: GitHub issues via `gh` CLI (`github.com/XenaRathon/DubTitlerr`) — see
  `docs/agents/issue-tracker.md` for the exact command shapes.
- **Domain docs**: `CONTEXT.md` + `docs/adr/` at repo root if they exist — see
  `docs/agents/domain.md`. They don't exist yet as of 2026-09-08; per that doc's own rule,
  proceed silently rather than flagging the absence or creating them upfront.
- **Glossaries are a shipped deliverable**, not incidental state — `glossaries/*.json` in the
  repo are pre-seeded dictionaries for anyone else cloning this project. Refresh them from the
  deployed copies at the next push that's happening anyway; never push just for that.
- **`osv-scanner` on this maintainer's machine** is a host-local shim over the real
  binary (appends `--verbosity error` so procoder's gate can parse its output) — it
  is not part of this repository and a fresh clone needs nothing like it; CI scans
  `uv.lock` directly via `google/osv-scanner-action` instead
  (`.github/workflows/ci.yml`).
