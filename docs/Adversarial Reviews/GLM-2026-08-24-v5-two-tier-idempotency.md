# Adversarial review — v5 two-tier idempotency

**Reviewer:** GLM (Buffy), 2026-08-24
**Spec under review:** `.procoder/specs/v5-two-tier-idempotency.md`
**Prior art:** `docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md`,
`docs/superpowers/specs/2026-08-21-project-review-brief.md`, and my three previous
reviews in this directory.

Method: every claim about code below was checked against source at the cited line.
The spec's own citations check out (the anchors in its Problem/In-scope sections —
`generate.py:679`, `:684`, `mux.py:325-326`, `:354`, `common.py:205` — are
accurate). The live-library measurements (3,889 / 813 / 576 / 236 / 1 / 67 / 46 /
31) cannot be re-measured from this checkout; I treat them as accepted and test
them for internal consistency where possible.

**Bottom line: the two-tier idea is right, and the cut is decidable. Three
load-bearing details are wrong as written, and one of them is unsatisfiable with
the schema the spec itself publishes. Those three block the build:**

- **[S-2] — `words.json` as specced cannot reproduce the original cards** (F1).
  The sidecar omits `segments` and media duration, and the [S-2] round-trip
  acceptance criterion can only pass by testing the cached path against a
  non-production variant of itself.
- **[S-3] — hash the *prompt string*, not the glossary *file*** (F2). Hashing the
  file re-marks every episode of a show transcription-stale for glossary edits
  that changed nothing about the decoder input — converting the spec's own
  motivating case ("a glossary correction that needs only a re-mux") back into a
  full GPU queue.
- **[S-1] — start `TRANSCRIBE_VERSION` at 4, not 5** (F3). Starting both tiers at
  5 re-transcribes all 576 watched v4 episodes at adoption — the exact recurring
  cost this spec exists to eliminate, for a change that is definitionally a text
  bump.

Everything else is a note.

---

## F1 — [S-2] BLOCK: `words.json` as specced cannot reproduce the original cards

The spec's Data section persists exactly one input beyond metadata: `words`. But
`reflow.reflow()` consumes **two**, and the second is not recoverable from the
first:

- `_clamp_to_segments` (`reflow.py:391-401`) pulls each word's timestamps inside
  `segments[w["seg"]]`'s `[start, end]`. On a cached re-run without segments this
  pass vanishes. Whisper's word DTW does place words outside their segment — the
  function exists because it happens — so **card boundaries differ whenever it
  fired on the original run.**
- `card_confidence` (`reflow.py:358-366`) derives each card's `no_speech_prob` as
  the max over `segments[s].get("no_speech_prob", 0.0)`. Without segments every
  cached card ships `no_speech_prob = 0.0` — a defaulted value silently answering
  the question asked. Not cosmetic:
  - the `music` drop rule (`hallucination.py:57-67`, `nsp > 0.95 and lp < -2.0`)
    and the `maybe_silence` flag (`nsp > 0.5`) become inert on exactly the path
    this spec exists to make cheap. Today they are *already* inert because turbo's
    nsp is collapsed to ~1e-10 (`hallucination.py:60-67` records this) — but
    [S-7] is the model bake-off whose point is that this could change, and on
    `large-v3` the cached path would silently lose the gate entirely. [S-2] and
    [S-7] are in quiet contradiction.
  - `conf.json` rows carry `no_speech_prob` (`generate.py:775-776`), and the
    `low_conf` bookkeeping derives from **both** lp and nsp (`generate.py:817-818`).
    A cached run's conf differs from the original run's conf even where the cards
    are identical.
- `audio_duration` is absent from the schema. `time_cards` uses it for the tail
  clamp (`en[-1] = audio_duration`, `reflow.py:339-352`) and for
  `CascadeInfeasible`. A cached run with `audio_duration=None` is unbounded at the
  tail and can never raise the exception the fresh path can — different tail card,
  different failure surface.
- `punctuation.restore(words, segments, ...)` bails early on `not segments`
  (`punctuation.py:255`). The cached path would skip the very pass the spec's
  Problem statement is written about ("punctuation restoration operates on the
  word list before splitting"); the `v3` note in `common.py:112-126` says 27% of
  cards arrived with no terminal punctuation before that pass existed.

**Net:** a text-tier re-run produces different cards than the original run whenever
the original needed clamping, carried a non-zero nsp, or ran a tail clamp. The
first [S-2] acceptance criterion — "round-trips through reflow to the same cards
as the in-memory list produced by the same run" — can only pass by comparing the
cached path against *another* run that also omits `segments` and `audio_duration`:
i.e. a test that validates the cached path against a non-production variant of the
same path. That is the "acceptance passes while the behaviour is broken" shape,
and it is the single most valuable finding in this review.

**Fix:** persist per-segment records — one dict `{start, end, no_speech_prob}` per
`seg` index (the shape `generate.py:710` already builds) — plus the episode's media
duration (whisper's `_info.duration` is available where the words are built). That
adds ~5-10 KB to a 200-300 KB sidecar. Do not reconstruct segments from words:
clamp bounds derived from already-unclamped words are not the original bounds, and
`no_speech_prob` is unrecoverable, period.

## F2 — [S-3] BLOCK (design, cheap to fix): hash the *prompt string*, not the glossary *file*

The only glossary-derived input to the decoder is `initial_prompt`
(`generate.py:112-118`: `INITIAL_PROMPT = GLOSS["initial_prompt"]` or a
`SHOW_NAME`-derived neutral; `:684` passes it to whisper). Everything else the
glossary drives — `names`, `hard_fixes` (→ `token_fixes`/`phrase_fixes`) — is
consumed at C1 by `glossary.correct()` (`glossary.py:151-166`), the **text** tier.

[S-3] hashes the whole file into `glossary_sha256`. Consequences:

1. `mine_glossary.py` runs before generate on *every sweep of a watched show*
   (`gen_loop.sh:27-31`) and appends `hard_fixes`, which never touch
   `initial_prompt`. `glossary_acquire.py` regenerates the prompt only for names
   (its own docstring: the prompt regeneration is the cut that keeps a wrong
   entry from biasing Whisper). So the file changes regularly for reasons that
   change **nothing** about audio→words — and each change re-marks every stamped
   episode of that show transcription-stale. One Pace is ~1,100 episodes; a single
   mined hard_fix re-queues the entire show for the GPU.
2. The prompt string is **already in the payload you are writing** —
   `"initial_prompt"` is literally a `words.json` field. Comparing it needs no
   extra hash at all, and where you do want one, `generate._glossary_version()`
   (`generate.py:130-140`) already computes a sha256 ([:12]) of the file for
   `lastrun.json`.

Recommended rule, one sentence: *an episode is transcription-stale iff the stored
`initial_prompt` differs from the one the current glossary produces; text-stale iff
the correction maps differ.* A glossary edit that leaves the prompt byte-identical
is text-tier only — exactly the "costs CPU-minutes, not GPU-hours" case the
Problem statement opens with. As written, [S-3] converts the spec's own motivating
example into a full GPU re-queue, from the other direction.

## F3 — [S-1] BLOCK (number): start `TRANSCRIBE_VERSION` at 4

The spec's acceptance says a v4 stamp "reports both tiers as 4", and its Data
example writes `transcribe_version: 5`. If both constants start at 5 (the prose
default), every one of the 576 live v4 stamps reads both-stale, and step one of
this change is a ~2-day, 576-episode full re-transcription — the exact recurring
cost the Problem statement leads with — for a change that is *definitionally* a
text-tier bump: the transcription output has not changed at all.

The correct adoption point is `TRANSCRIBE_VERSION = 4, TEXT_VERSION = 5`:
- v4 stamps → transcribe 4 == 4 → fresh; text 4 < 5 → stale. `words.json` cannot
  exist for them yet → [S-2]'s own edge case ("a stamp with tier keys but no
  words.json on disk: text tier cannot run; episode is transcription-stale")
  handles it by transcribing *once* per episode — a migration, not a bump. After
  the first text-tier pass, every future text bump is CPU-only.
- The 236 v2s stay both-stale (correct — they were decoded by an older pipeline),
  drained on the watch queue exactly as today.

The spec does not say which it intends. It must, and cost-of-being-wrong requires
the 4/5 split (or an explicit, documented decision to eat 576 re-transcriptions).

## F4 — [S-4] the "converge to one consistent state" user story is false; the 236-at-v2 is the proof

`gen_loop.sh` processes only the shows named in the watch-ordered `ORDER` file
(`gen_loop.sh:29-33`); `watch_queue.py` regenerates that file from watch history,
unioning WatchState and Plex; and `watch_queue.py`'s module docstring states the
design: once a show is queued, the *whole series* regenerates — **narrowing never
happens and unwatched shows are never queued.**

236 of 813 stamped episodes sat at v2 for 28 days, and 1 at v3, while 576 drained
to v4 in ~3 days: draining works, but only for shows the queue contains. Nothing
is broken; it is the design. What it says about the spec:

1. The Users section's promise — "the library to converge to one consistent state
   rather than silently splitting into treated and untreated halves" — is not
   achievable under the chosen drain mechanism, in either tier. An unwatched
   show's text-stale episodes sit behind nobody. The honest invariant, which the
   system does hold, is *converges ahead of the viewer*.
2. [S-4]'s acceptance ("drains in the order `watch_queue.py` yields — asserted
   against a fixture, not observed") has no live half. A fixture asserting an
   in-process queue order says nothing about whether anything drains. Per the
   review brief's §5.2 lesson (`flag` was decorative for four days), a new "queue
   depth readable as a number" with no consumer will sit unread for 28 days the
   way the version split itself did. The number needs a *reader before it ships*:
   fold it into `lastrun.json` (which generate already writes per show,
   `generate.py:120-127`) or an aggregation script, and add an operator-checkable
   live assertion ("after TEXT_VERSION bump on a pinned show, sweep and observe
   `words_reused > 0`").

Related wrinkle: the mine/verify/acquire chain also runs in watched order. A
glossary edit for show X while the viewer is pinned to show Y leaves X's text-tier
(CPU-cheap!) undone indefinitely. Under F2's classification (text-only edit → text
tier only), the "applies immediately" promise in [S-3] should be qualified:
immediately *for watched shows*, queued otherwise.

## F5 — [S-5] choose the comparison and make the tool verify before it re-keys

**What produces 15 size-match-not-mtime: content-copies, not collisions.** 46 of
67 orphans match a video by size; only 31 also by mtime. A rename-without-rewrite
(the original orphan mechanism) keeps both — that is the 31. A `cp` without
`-p` (a re-download, a library reorg that copied then deleted, a torrent re-check) is
the same content with only the mtime changed — the 15 most likely come from
exactly that. Size+mtime alone gives up on them; a content hash reclaims them. Have
`--dry-run` hash the candidates and print the verdict: if all 15 are
byte-identical to their size-match, rejecting them leaves a third of the recoverable
orphans on the table. That is a measurement the spec should take, not a decision it
should make blind.

**Collision math:** episode sizes land somewhere in a ~2e8–2e9 byte range, so a
uniform-random collision probability per pair is ≈ 1/1.5e9; 15 size-only
candidates × 3,889 library videos ≈ 4e-5 expected false positives (and the
library-wide “any two videos share a size” term is ≈ 0.5%, not nothing when
the action is re-keying — see self-critique S5). Size-only is numerically
safe against coincidence. The residual hazard is *adversarial*, not combinatorial:
same input + same encode settings frequently yields bit-identical output, so a
re-encode of a different episode can byte-collide with the recorded size — a
content hash on the ≤46 size-first candidates removes the entire risk class at a
trivial NFS read cost (a few MB at the head and tail, not the whole file).

Mechanics the spec should add:

- **The re-key set is never enumerated.** "[S-5] re-keys the sidecar set" must
  name: `.dubtitles.done`, `.dubtitles.conf.json`, `.dubtitles.qc.json`,
  `.eng.dubtitles.srt`/`.ass`, `words.json` (the new sidecar), `.repair.csv`,
  `.dubtitles.mux.log` — and must **not** move `.fail`/`.stale`/`.muxtmp.mkv`.
- **`tools/recover_dub_srt.py` already exists** and rebuilds an `.srt` from the
  embedded Dubtitles track. For a renamed-but-muxed video the embed is still
  there; re-keying is a fast path, but the tool should report the embedded-track
  recovery path too, since the `.ass` may be missing while the track is present.
- **Live-sweep guard:** `--apply` must refuse while either of the two loops in
  `container_run.sh` is running. Generate/mux write and delete exactly the files
  reclaim renames; a re-key racing a live mux re-creates the silent-corruption
  class this whole project is about. Cross-host locking (§6.5) being out of scope
  is fine in general; [S-5] is a *new writer* into that namespace and still needs
  "the pipeline is not live" as a precondition. This is the one place I will say
  §6.5 is load-bearing *for this change specifically*.
- The spec's edge ("two orphan stamps matching the same video → re-key neither")
  is right; add its mirror ("one orphan matching two videos").

## F6 — [S-6] "falls back to the display window" is vacuous on 99% of the cases it promises to fix

Your own measured fact, from the VAD design §2: **on 99% of gated cards,
`end == source_end` exactly — the display window IS the word's timestamp span.**
"Falling back to the display window" is therefore numerically *identical* to the
broken window in ~99% of the cases the guard fires on, and *wider* (hence worse —
more neighbour-cue pickup) on the displaced ~1%.

The two call sites are exactly as the spec says — `generate.py:266-267`
(`_card_word_probs`: `card.get("source_start", card["start"])`) and
`repair.py:410` (`overlap_ref(ivals, c.get("source_start", c["start"]), ...)`) —
and both carry the `.get()` default that the VAD review's own notes condemned. But
the correct result for a card whose evidence window is known-invalid is **no
reference at all**: `overlap_ref` → `""` and `_card_word_probs` → `[]`, both
counted. A "repaired" line whose only justification was borrowed from a neighbour
is exactly the failure the VAD §6 documented ("1 would be flagged for repair purely
on borrowed evidence"); the display-window fallback recreates it under a new name.
The spec's acceptance for [S-6] ("returns the display-window reference") encodes
that mistake — it should assert *empty* reference and *empty* probabilities, with
both counters moving. The counters remain the real value of [S-6]; treat it as
observability, not recovery.

## F7 — the two-tier cut is decidable; the missing piece is the decision rule, written down

The classification the prompt asks about (attack #1) is decidable. Everything
computed from `(words, segments, conf.json, fansub, LLM)` is text; everything from
audio/decoder is transcribe. A concrete enumeration:

| input | tier | note |
|---|---|---|
| `initial_prompt`, model choice, `WHISPER_BEAM_SIZE`, `COMPUTE_TYPE`, whisper thresholds | transcribe | nothing below reads them |
| whisper word list, per-seg `no_speech_prob` | transcribe-derived, consumed at text time | the only true boundary leak → resolved by F1 (persist segments) |
| punctuation constants, reflow constants, glossary names+hard_fixes | text | CPU |
| `audio_duration` | neither — persist it | F1 |

The genuinely undecidable-that-kills-silently case is one: whisper-affecting
*environment* (the list above). Today the single `PIPELINE_VERSION` carries that
burden by fiat — any output-relevant change, regardless of layer, demands a bump.
With two tiers, "the operator changed `COMPUTE_TYPE`" has no mechanical signal at
all. The spec's only defence is the written bump manual: the current one lives in
`common.py:95-127`'s per-version block, and the spec replaces the constant with
two without preserving the manual. Port it into the docstring of both constants,
explicitly stating that decoder-affecting configuration changes require a
`TRANSCRIBE_VERSION` bump. Documentation is the load-bearing register here — the
same register that kept v2 → v3 → v4 bumps honest. The alignment between "my
configured output changed" and "something marks it stale" is the entire feature.

## F8 — smaller things, all NOTE

- **[S-2] `words.json` needs a version-mismatch consumer.** The sidecar records
  `transcribe_version` but nothing in the spec says what sees it. A `words.json`
  whose `transcribe_version != TRANSCRIBE_VERSION` must be treated as absent (a
  crashed stint between transcription and stamping leaves exactly that); without
  it, the cache can serve words from an older pipeline to the text tier.
- **`park_stale_sidecars` must learn `words.json`.** `generate.py:273`
(`SIDECAR_SUFFIXES`) enumerates the suffix set that the rename-to-`.stale` path
handles. A parked old-version `words.json` would otherwise be read by the cached
path — see previous bullet.
- **`main()`'s model-load gate must split text-todo from transcribe-todo.**
  `generate.py:886-888` loads `WhisperModel` whenever `todo` is non-empty. A
  text-only stale population would still pay the ~40 s GPU load on every sweep,
  and load the model to do zero transcription — the cheapest half of the cheap
  tier quietly isn't cheap. The spec doesn't call this out.
- **[S-2] write point**: "immediately after transcription, before reflow" is
  correct (`generate.py:713-746`, between `fail`-mark and `fail`-clear), and the
  failure mode ("write fails, counted as `words_missing`, never fails the run")
  is right. Good.
- **[S-7] is a different change, on a moved box.** The 1050 Ti has left the 3200g
  for VM 102 on R520 (swap plan, `docs/superpowers/plans/2026-08-22-1050ti-to-r520-swap.md`,
  and commit `4f0b827`, "resized and verified"). The bake-off must (a) re-derive
  its VRAM/eviction story from `nvidia-smi` on the *new* box (the E5-2450 is
  2.1 GHz vs the 3200G's 3.6 GHz — minutes-per-episode will differ, and the
  llama-embed co-tenant may not be), (b) be sequenced *after* the idempotency work
  — nothing in [S-1..S-6] depends on it — and (c) keep "OOM recorded as the
  result": a model that doesn't fit is a finding. The "llama-embed restored"
  acceptance is precisely the ops step that silently doesn't happen; keep it.
- **[S-8]** is trivial and the plan file does still say "planned, not started".
  Fine.

## What I tried hardest to break — and what stopped me

1. **"`words` is the list reflow already consumes, unmodified"** (spec Data).
   This is the claim the design leans on hardest, so I checked it hardest — and it
   is false: reflow consumes `(words, segments)`; `segments` carries `nsp` and
   clamp bounds. F1 is this strait. (The author's failure-mode note predicted
   checking the *defaulted values*; segments was the non-defaulted thing I nearly
   let pass.)
2. **"(size, mtime) — the same comparison `common.py:205` already trusts"**
   (`_stamp_matches_file`, the `abs(mtime) < 1.0` tolerance). I tested whether
   stamp-recorded mtime is trustworthy on NFS (seconds-only after copies). It
   held: the comparison is byte-identical to what the pipeline itself uses, so
   S-5 adopting it is coherent; my only objection is the 15 it writes off.
3. **The `.get("source_start", ...)` default** in both call sites — for F6. The
   subtler claim, that the guard must fire *before* the default is applied (a
   `.get()` inside the repaired path recreates the original bug), is correct in
   the spec's Edge cases. Unbroken.
4. **"The review brief's '285 of 861' is superseded"** — 67/813 = 8.2% vs the
   brief's 285/861 = 33.1%; 813 stamps it 20.9% of a 3,889-video library, leaving
   ~3,076 unstamped. Both figures internally consistent; I accept the
   supersession. One flag: the spec should say *why* the old number was wrong
   (what heuristic it was the product of), or the next reader re-raises the same
   doubt about these.

## Acceptance criteria that would pass while the behaviour is broken

- **[S-2] "round-trips through reflow to the same cards"** — passes on a fixture
  that omits `segments`/`audio_duration`, while the cached path diverges on every
  real episode that needs clamping or carries nsp. (F1)
- **[S-3] "changing the glossary changes the hash and marks the episode
  transcription-stale, and still applies the name correction through the text
  tier in the same run"** — passes while the design re-queues the whole show for
  work that did not change the transcript. The test observes the flag, not how
  many episodes it newly flags. (F2)
- **[S-4] "drains in the order watch_queue yields (fixture)"** — passes while no
  live drain is observed anywhere; the 236-at-v2 shows the system can hold that
  state for a month without a peep. (F4)
- **[S-6] "overlap_ref returns the display-window reference"** — passes while, on
  99% of gated cards, the display window is numerically identical to the window
  being guarded. (F6)
- **[S-7] catch-rate numbers** — pass on the old host's VRAM story and are wrong
  on the new one unless re-measured post-move. (F8)

*(F1 and F3 do not depend on measurements: F1 is structural from reading
`reflow.py`; F3 is arithmetic from the spec's own numbers.)*

## What I agree with — they should have said

- Orphan reclaim + two-tier constants, as designed, address the largest recurring
  cost in the system ranked by the previous review; the [S-4] queue reuses an
  existing path rather than inventing a scheduler.
- [S-6]'s counters continue the `_tick` liveness pattern — correct instinct.
- The spec is unusually candid about its own failure modes and edge cases, and
  each of my three blocks is a morning's work to close.

---

## Self-critique — the same argument, attacked (2026-08-24, later the same day)

Assignment: argue against the review above. I re-checked every finding against the
spec and the code, and this time asked what the repo itself already contradicts me
with. Three findings survive intact, two survive narrowed, one is wrong in fact,
and the biggest miss is a file I never opened. Recorded the way the VAD design's
§7 records its own corrections: the errors are instructive.

### Verdicts in one line

| finding | verdict | one-line reason |
|---|---|---|
| F1 (words.json needs segment data) | **survives, narrowed** | `no_speech_prob` + `audio_duration` genuinely unrecoverable; but the clamp-boundary half is defeatable by persisting post-transform words, and my punctuation framing was half-wrong |
| F2 (hash the prompt, not the file) | **survives, replaced** | right, but the real fix is "route glossary edits to conf.json" — the tool already exists (S1) |
| F3 (start TRANSCRIBE_VERSION at 4) | **narrowed** | the spec never says both start at 5, and 4/5 defers the GPU bill, it cannot avoid it (S3) |
| F4 (236-at-v2 proves queues don't drain) | **narrowed** | the 236 are unwatched shows the gate deliberately skips; the drain provably works for queued shows (S4) |
| F5 (hash before re-key) | **survives** | but I committed the unmeasured "most likely" sin the brief told me to avoid, and the collision math is sloppy (S5) |
| F6 (display fallback is vacuous) | **partly wrong** | the spec already says `_card_word_probs` returns empty — only the `overlap_ref` branch is mine to attack (S6) |
| F7 (decidable + written bump rule) | survives | |
| F8 (missing consumer, parking, model gate) | survives | plus a convention I missed entirely: OUTPUT_ROOT vs raw paths (S7) |

### S1 — the biggest miss: `tools/reapply_glossary.py` is already the cheap tier for the spec's own motivating example

The tool exists, in the repo, and its docstring says: "No GPU, no LLM, no
re-transcription." Per episode it reads `<stem>.dubtitles.conf.json`, runs
`glossary.correct()` over every card, and if anything changed, rewrites conf,
renders the `.srt`, and **drops the `.dubtitles.done` stamp** — reopening the
episode for `merge_pass` to re-mux. It even draws the boundary I spent F1 arguing
around, in its own words: "Anything that changes how text is **DIVIDED** needs a
full regenerate; this tool only changes what the text **SAYS**."

**So a glossary correction never needed `words.json` at all.** The spec's Problem
statement ("a text-only change cannot be re-run without the GPU, because
punctuation restoration operates on the word list before splitting") is false
for the example it opens with: `glossary.correct()` runs at the *card* level
(C1, `generate.py:757-763`), long after the word list has done its job. What the
repo actually lacks is not word persistence — it's that `reapply_glossary.py`
is **manual, un-versioned, and not watch-gated**: nothing records in the stamp
that "this episode's text was corrected against glossary X".

Consequences for my own review:

- F1 and F2 attacked the spec's GPU-facing re-derivation path as if that were the
  whole cheap tier. Under S1, the cheap tier for glossary edits is conf.json, no
  words required — so [S-3]'s "applies immediately through the text tier" is a
  conf-file operation (absorb/deprecate `reapply_glossary`), and [S-2]'s words
  sidecar is needed only when how text is *divided* changes — punctuation or
  reflow config, a far rarer event than every glossary save. That materially
  lowers the blast radius of my own F1.
- F2's "hash the prompt string" survives, but its frame changes: prompt-hash is
  the gate for whether the *word* layer needs re-running, not the mechanism for
  applying glossary edits.
- The spec (and me) should have named two text tiers: **card text** (
  `conf.json`, glossary edits, CPU today) and **word reflow** (needs
  segment-class data — F1's real half). The spec conflates them.

I should have read `tools/` before blocking on a schema change.

### S2 — F1's over-reach: what's truly unrecoverable vs what I overstated

- **Punctuation**: my "the cached path skips the very pass … v3 note, 27%"
  argument is half wrong. The spec's Data says "words is the list reflow already
  consumes"; the list reflow actually consumes is **post-punctuation** —
  `punctuation.restore()` mutates `word["text"]` in place before reflow's
  `split_spans` sees it (`generate.py:743-744` → `:737`). So a cached run
  *should* skip the punctuation LLM call without losing anything, provided the
  sidecar is written *after* restore. The honest observation is an ordering
  ambiguity — "immediately after transcription **and before reflow**" admits
  both — not a lost pass. I should have said "pin the write point after restore,
  or resume restore on replay and eat a double LLM call".
- **Clamp/dejitter**: I claimed reproducing the cards "cannot" happen without
  storing segments. Wrong as a fix, right as a fact: there is a cheaper
  construction — store the words *post-transform* (after
  `normalize`/`clamp_to_segments`/`dejitter`), and have the cached path skip those
  three transforms entirely. Then `split_spans`/`segment_span`/`time_cards` see
  byte-identical inputs and card boundaries match with **zero segment records**.

What genuinely cannot be recovered from words: per-segment `no_speech_prob`
(conf.json carries it only per-card, after collapse, `generate.py:775`) and
`audio_duration` (the tail clamp and `CascadeInfeasible`). So the load-bearing
half of F1 is "persist per-segment nsp and duration, and define exactly which
transform state the sidecar stores" — my "must store segments" overbuilt it. The
acceptance-criterion criticism survives: the criterion still demands the cached
path replay from the same inputs, whatever storage is chosen.

### S3 — F3 claims to save what it only defers

The spec never says both constants start at 5. The Data example's
`transcribe_version: 5` is the *first re-transcribed* episode under the new
scheme, not the adoption constants; "the prose default" was my own invention.
Under 4/5, adoption leaves 576 v4 episodes transcribe-fresh but text-stale with
**no `words.json` anywhere** — which, per the spec's own edge case ("stamp with
tier keys but no words.json on disk: text tier cannot run; episode is
transcription-stale"), makes them transcription-stale the moment the queue
looks. The 576 re-transcriptions I claimed 4/5 avoids are therefore only
**deferred**: they arrive at the watch-gated pace instead of all at once (and
could be minimised by adopting the words sidecar in the same sweep). Deferred
is still a genuine, meaningful release — no forced whole-library burn on a
bookkeeping change — and starting both at 5 *would* burn them immediately, so
F3 remains a real numbering correction. But my "after the first text pass, every
future text bump is CPU-only" is only per-episode, per post-migration episode.
I sold a deferral as a saving.

### S4 — the 236-at-v2: I pointed at the wrong villain

"Two versions behind for 28 days, apparently unnoticed" — I read that as proof
invalidation drains don't. Wrong read. `watch_queue.py` exists precisely to
*skip* unwatched shows; the 236 are the unwatched residue. The drain mechanism
working is *demonstrated by the other 576 arriving in ~3 days*. The 236 say
one true thing about this spec: the operator has no *visibility* into the
residual — the queue depth, unread, is the repair the spec proposes, and the
count exists today (812/576/236), it is just not telegraphed. My "no live half"
complaint about the fix for fixture-only acceptance stands; my "this proves no
invalidation scheme drains" does not.

### S5 — the review's own rule, violated by the reviewer

- "the 15 most likely come from cp-without-p" — an unmeasured story asserted as
  a guess. The one rule of the brief is "verify before asserting"; I did not
  verify, and then the very next paragraph recommended measuring exactly that
  with a hash. The claim "15 = copies" stays unknown until a byte hash says so.
- "expected false positives ≈ 4e-5" — muddled denominator. The number for 15
  candidates × 3,889 videos is ≈ 4e-5, but the re-key action involves the 46
  size-matched candidates, and a library-wide pairwise term (c(3889,2) ≈ 7.5e6
  × 6.7e-10) ≈ 5e-3 — one chance in 200 that *somewhere* two different videos
  share a size. Both numbers argue for hashing; my prose lumped them into one.
- "One Pace is ~1,100 episodes" — asserted without source. The acquire timeout
  comment in `gen_loop.sh` quotes "463 episodes" for a full pass; neither is
  verified by me. The claim "a hard_fix re-queues the whole show" doesn't
  depend on the exact count, but I used a figure I never measured — the very
  behavior I'm supposed to flush out of everyone else's writing.

### S6 — F6 attributed to the spec a block that is already empty

The spec's [S-6] says `generate._card_word_probs()` returns **empty** ("rather
than inheriting neighbouring cards' probabilities") and the acceptance enforces
it. My F6 attacked "the two call sites … the display window fallback" together —
as though the spec proposed falling back in both. It doesn't. Only
`repair.overlap_ref()` falls back to the display window, and *there* my argument
holds exactly: on 99% of gated cards display == source, so the fallback
reproduces the window the guard just declared implausible, and the right result
is empty (repair skips) with the counters moving. The "empty probabilities"
half of my recommendation was pushing an open door.

### S7 — a gap all of F1-F8 miss: the OUTPUT_ROOT/raw-path convention

The spec declares the sidecar but not where it lives. This codebase splits
*sidecar writes* and *sidecar reads*: srt/conf/qc are written via `out_for`
(redirecting onto OUTPUT_ROOT) but existence-checked at the raw path
(`generate.py:777-790`, `:653-655`); stamps are raw everywhere; and a comment at
`generate.py:302-304` asserts "OUTPUT_ROOT resolves into the same mergerfs pool
view". If `words.json` follows the write side and the read side uses the raw
path (or vice versa), the cache misses *silently* — `words_missing` forever,
full transcription every sweep, which is exactly the failure budget [S-2] exists
to contain. The spec must pin: written via `out_for` and read via `out_for`, or
neither — not by accident.

### Re-stated bottom line

- Blocks that survive: **F1's narrow half** (`no_speech_prob` + `audio_duration`
  are unrecoverable; the round-trip acceptance as worded cannot pass; the spec
  must define which transform state the words store and when it writes).
  **F2's replacement** (glossary edits go to the conf-tier via the existing
  tool; prompt-hash only gates the word layer).
- Block that becomes a numbering decision, not a saving: **F3** — pick 4/5 and
  say so; the transition happens once, at watch speed.
- Notes that survive, plus one missed: F4 (real visibility gap; wrong proof),
  F5 (hash, with my mea culpa), F6 (narrowed to the `overlap_ref` branch),
  F7, F8 (plus the OUTPUT/raw convention, and a version-mismatch rule for the
  sidecar).

The review was not wrong about enough — the failure case is that it was right
about the GPU-facing design but missed that the repo's own `tools/` directory
had already shot at the target twice and hit nothing. The next pass should build
on `reapply_glossary` rather than around its shadows.