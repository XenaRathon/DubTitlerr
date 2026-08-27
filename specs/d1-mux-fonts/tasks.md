# Tasks — D1: Mux dubtitles + fonts into the MKV

> Persistent memory. New session: read `spec.md` + this file, check out the branch first.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/d1-mux-fonts` (base: `main`)

Rules: ≤~1h each, dependency-ordered, verifiable, test-first, gates green (ruff · pytest),
1 task = 1 conventional commit.

## Tasks

- [x] **T1 — Scaffold + extract pure helpers.** In `mux.py`: `tests/test_mux.py`; extract/define
      `read_stamp`/`write_stamp`/`stamp_valid`, `has_room`, `keep_sub`, `is_muxed` signatures +
      constants (`MIN_FREE_GB`, `DELETE_BROKEN_HARDLINKS=0`). — done when: ruff clean, pytest collects.
- [x] **T2 — Stamp helpers.** `.dubtitles.done` write (size+mtime+muxed) / read / `stamp_valid`
      (matches current file). — done when: round-trip + staleness tests pass.
- [x] **T3 — `has_room`.** free-bytes vs needed (file size × factor) ≥ MIN_FREE_GB margin.
      — done when: boundary tests pass.
- [x] **T4 — `keep_sub`.** keep eng/nld/und/original; ALSO keep `mul` or signs/songs-named tracks;
      drop other-language dialogue subs. — done when: keep/drop + signs-songs-survive tests pass.
- [x] **T5 — `build_cmd` flags (refine/confirm).** eng audio default, jpn kept non-default,
      Dubtitles default (not forced), foreign dropped, attachments kept — over a fake `mkvmerge -J`
      dict. — done when: track/flag unit tests pass.
- [x] **T6 — Process wiring (mkv + mp4) + stamp + no-partner-delete + EXDEV-safe finalize.**
      `process()`: free-space gate; mkv→embed `.ass`; mp4→remux to mkv embed `.srt` + remove old
      `.mp4` link only; verify→finalize→write stamp→remove sidecar; never delete partners.
      — done when: ruff clean, pytest green, mp4/mkv branch unit-tested (subprocess stubbed).
- [x] **T7 — Wire into `merge_pass.sh`** (per-episode mux after assemble / terminal mp4 srt, root).
      — done when: script invokes mux, skips stamped.
- [x] **T8 — `generate.py` stamp skip.** `needs_work()` + `process()` skip on valid `.done`.
      — done when: full pytest green, generate.py parses.
- [x] **T9 — `Dockerfile.builder` `mkvtoolnix`.** — done when: grep shows it.

## Closing (the _close_ phase — always keep last)

- [x] **FULL A1→D1 end-to-end on the server** (the user's requirement): a random episode each from
      **One Pace, Reborn as a Vending Machine, JoJo (2012), Fullmetal Alchemist Brotherhood, + 1–2
      random shows**; generate→repair→assemble→mux; verify reflow timing, names, no hallucinations,
      and an embedded default Dubtitles track WITH fonts (esp. JoJo signs/songs). — done when: all pass.
- [x] CI: add `mux.py` to the ruff scope — done when: pipeline green.
- [x] Push `feat/d1-mux-fonts`; merge to `main`. — done when: merged + pushed.
- [ ] **Then:** GitHub mirror of the whole repo + rollout (rebuild image, sync glossaries→`/config`,
      mux/regenerate library) — tracked in [[project_dubtitle_builder]], separate from D1.

## Done

<move [x] tasks here, preserving the done criterion>
