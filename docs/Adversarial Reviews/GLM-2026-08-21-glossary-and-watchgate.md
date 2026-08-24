# Adversarial review — glossary integrity + watch-gated regeneration

**Reviewer:** GLM (Buffy), 2026-08-21
**Specs under review:**

1. `docs/superpowers/specs/2026-08-21-glossary-integrity-design.md` (priority)
2. `docs/superpowers/specs/2026-08-21-watch-gated-regeneration-design.md`

Method: every factual claim about code was checked against the source at the cited
line. Line numbers cited in the specs are off by 1–2 throughout (drift, not error —
the functions named are correct). Findings below use the _actual_ source line.

---

## Findings, ranked by cost-of-being-wrong

### [CONFIRMED] `load_dict()` reads exactly five keys; `verified`/`known`/`flagged`/`acquired` have zero runtime effect

`glossary.py:62-76` (`load_dict`). The returned dict contains `show`, `names`,
`phrases`, `token_fixes`, `phrase_fixes`, `initial_prompt`. No other key is copied
through. `correct()` (glossary.py:151) reads `phrase_fixes`/`token_fixes`/`names`;
`name_suspect()` (164) reads `names`; `repair._glossary_terms()` (repair.py:119)
reads `names`/`phrases`/`token_fixes`/`phrase_fixes`. Nothing in the runtime imports
`verified`, `known`, `flagged`, or `acquired`. Spec 1 §1's table is correct. This is
the load-bearing fact of the whole spec and it holds.

### [CONFIRMED] `apply_results()` replaces in place — `lst[i] = canon`

`glossary_verify.py:124-147` (`apply_results`). At line 140:

```python
if conf == "high" and canon and canon != term:
    for lst in (names, phrases):
        for i, x in enumerate(lst):
            if x == term:
                lst[i] = canon
```

The short form is overwritten, not retained. Confirmed verbatim.

### [CONFIRMED] D1 is empirically real on the live One Pace glossary

I read `glossaries/One Pace.json`. Cross-checking the spec's "10 of 12 sampled bare
dub forms are absent" claim term-by-term against the live `names`, `phrases`, and
`hard_fixes` **values**:

| bare form (in `verified`) | in `names`?                               | in `phrases`? | in `hard_fixes` values?                               |
| ------------------------- | ----------------------------------------- | ------------- | ----------------------------------------------------- |
| `Doflamingo`              | no (`Donquixote Doflamingo` is)           | no            | no                                                    |
| `Hancock`                 | no (`Boa Hancock` is)                     | no            | no                                                    |
| `Kaido`                   | no (`Kaidou` is)                          | no            | no                                                    |
| `Lucci`                   | no (`Rob Lucci` is)                       | no            | no                                                    |
| `Alabasta`                | no (`Arabasta` is)                        | no            | **YES** — `arabasta->Alabasta`, `alabaster->Alabasta` |
| `Raftel`                  | no (`Ratel` is)                           | no            | no                                                    |
| `Jabra`                   | no (`Jabari` is)                          | no            | no                                                    |
| `Trafalgar`               | no (`Trafalgar Lami` is)                  | no            | no                                                    |
| `Rayleigh`                | no (`Silvers Rayleigh` is)                | no            | no                                                    |
| `Montblanc`               | no                                        | no            | no                                                    |
| `Straw Hats`              | no (`Straw Hat Pirates` ×2 in `phrases`)  | no            | **YES** — `straw hats->Straw Hats`                    |
| `Cricket`                 | no (`Mont Blanc Cricket` is in `phrases`) | no            | no                                                    |

**The spec's "10 of 12 absent from `names`, `phrases` and `hard_fixes` values alike"
is wrong on two of the twelve.** `Alabasta` and `Straw Hats` survive as
`hard_fixes` values, so the deterministic tier still produces them. The accurate
statement is "10 of 12 are absent from `names`/`phrases`; `Alabasta` and
`Straw Hats` remain reachable via `hard_fixes` values." This is exactly the
default-produces-the-expected-answer failure the prompt warned about: the spec
author looked at `names`/`phrases`, saw the term missing, and generalized to
"`hard_fixes` values too" without checking.

This **does not weaken D1**. The bug (short form destroyed in `names`/`phrases`) is
real for all 12. It only means two of them have an accidental second life in a third
tier the spec didn't measure. The §3.3 backfill must not _delete_ `Alabasta` or
`Straw Hats` from `hard_fixes` — and the spec's step 1 ("restore terms absent from
`names`/`phrases`/`hard_fixes` values") would correctly skip them. So the fix is
sound; the measurement in the rationale is overclaimed.

### [CONFIRMED] `names` is single-token; a multi-word entry there can never match in `correct()`

`glossary.py:98` `_TOKEN_RE = re.compile(r"^([^\w']*)([\w'][\w'-]*?)([^\w']*)$")` —
captures one token. `_fix_token` (124-147) operates on one token's `core` against
`names`. `name_suspect` (164-180) iterates `text.split()` tokens. A multi-word
string in `names` (e.g. the live `Rob Lucci`, `Boa Hancock`, `Donquixote Doflamingo`)
**cannot match** in the deterministic tier — `low == nm.lower()` compares a single
token to a two-word string. Confirmed. The spec's "degraded, not inert" framing is
correct: those entries still reach the repair LLM via `_glossary_terms`.

**However**, this means the live glossary _already_ contains 7+ multi-word entries in
`names` (Rob Lucci, Boa Hancock, Silvers Rayleigh, Donquixote Doflamingo, Trafalgar
Lami, Mont Blanc Family, Straw Hat Pirates? — no, the last is in phrases). The §3.3
step 2 ("move every multi-word entry currently in `names` to `phrases`") is therefore
not hypothetical cleanup; it is a real, live defect. Confirmed.

### [CONFIRMED] `repair._glossary_terms()` is the only runtime consumer of `phrases`

`repair.py:119` (`_glossary_terms`) concatenates `gloss["names"] + gloss["phrases"]`
(+ the `hard_fixes` values) into the repair LLM prompt. No other runtime site reads
the `phrases` key. `correct()` reads `phrase_fixes` (derived from `hard_fixes`), not
`phrases`. So `phrases` is purely an LLM-prompt list, exactly as the spec claims. The
spec's framing — "LLM-prompt list rather than a deterministic correction source" —
is accurate and load-bearing for §3.1's routing rule.

### [CONFIRMED] `glossary_acquire.py --review` exists and walks `flagged`

`glossary_acquire.py:685` `review_items()`, plus the `--review` / `--apply` CLI path
exercised in `tests/test_glossary_acquire.py:728,746,920`. The spec's §3.2 claim that
"these join that queue" is implementable against existing machinery. Confirmed.

### [CONFIRMED — but stale PROMPT claim] `tools/timing_compare.py` does NOT read `source_end`

The PROMPT asserts (as a prior cautionary tale) that "a `grep '*.py'` in the repo root
silently excluded `tools/`, producing 'nothing reads this field' twice as a stated
fact, when `tools/timing_compare.py` reads it on two lines."

I checked: **`source_end` and `source_start` do not appear anywhere in `tools/` today.**
`grep -rn "source_end\|source_start" tools/` returns zero matches. The only `source`
hit in `tools/timing_compare.py` is a comment at line 172. `source_end` _is_ read by
`repair.py:398` (`c.get("source_end", c["end"])`) and by tests, but **not** by the
timing comparator.

This means the PROMPT's cautionary example is itself stale — the very
"nothing reads this field" claim the prompt says was wrong (because `tools/timing_compare.py`
read it) is now _correct_. Either the timing comparator was refactored to stop reading
it, or the prompt's historical claim was wrong to begin with. Either way: **a reviewer
following the prompt's lead to re-verify the `source_end` consumer would today find none
in `tools/`.** The lesson stands (check defaults), but the specific example no longer
reproduces. Not the spec's error — the prompt's. Flagged because the prompt told me to
check exactly this.

### [CONFIRMED] Spec 2's tri-state pattern is real and matches `tools/vad.py`

`tools/vad.py:17-22` documents `bool | None` returns, with `None` meaning
unreachable/error and the explicit principle "never guess a silent True/False."
Spec 2 §4.2's "Tri-state, following `tools/vad.py`" is grounded in an existing
project pattern. Confirmed.

### [CONFIRMED] `gen_loop.sh:10` reads the order from a flat file, re-read each sweep

`gen_loop.sh:10` `ORDER="${ANIME_ORDER:-/config/anime_order.txt}"`, read at the top of
the `while :; do` loop via `done < "$ORDER"`. Regenerating the file between sweeps is
sufficient. Spec 2 §2's claim holds.

### [CONFIRMED] `_clean_title` normalises `(YYYY)` and `{tvdb-NNNN}` suffixes

`glossary_verify.py:149` `def _clean_title(title): return re.sub(r"\s*\(\d{4}\)|\s*\{[^}]*\}", "", title).strip()`.
The spec cites `glossary_verify.py:147` — off by 2 (drift), but the function and regex
are exactly as described. Spec 2 §4.5's matching fallback is real.

---

## Design critique

### Q1 — Is the root-cause diagnosis correct and complete?

**Correct, yes. Complete, no.** Replace-in-place (`lst[i] = canon`) is a real bug, but
it is a _symptom_ of a structural problem the spec names and then does not fix:

The glossary has **two orthogonal taxonomies** collapsed into one list:

- _shape_ (single-token vs multi-word) — determines which tier can match
- _tier of authority_ (raw mined term / dub-canonical / wiki-canonical / human-rejected)

`names` is meant to serve the deterministic single-token matcher, but it is also used
as the LLM prompt list (via `_glossary_terms`). `phrases` is "the multi-word LLM list"
but has no deterministic role. `verified` is a _process_ flag (don't re-check) that the
spec repurposes as a _reachability_ invariant. `hard_fixes` is a deterministic map
whose _values_ are also an LLM prompt source.

`apply_results` replaced in place because, under this collapsed model, the canonical
and the mishear are "the same slot" — there is no separate field for "mishear form to
match" vs "canonical form to emit." The deterministic tier needs the mishear; the LLM
needs the canonical; `hard_fixes` already encodes that distinction (key=mishear,
value=canonical) but `names`/`phrases` do not.

The spec's §3.1 fix (add, never replace; route by shape) treats the symptom. The
structurally correct fix is: `names`/`phrases` should be _mishear targets_ (what the
deterministic tier and the LLM prompt match against), and canonical forms should live
in `hard_fixes` (or a parallel `canonical` map) where the key/value distinction already
exists. `Doflamingo` (mishear) -> `Donquixote Doflamingo` (canonical) is exactly a
`hard_fixes` entry; the spec even shows `arabasta -> Alabasta` already working this
way. Routing every canonical into `hard_fixes` would have made D1 _impossible_ — you
cannot "replace in place" a dict value you're adding to.

The spec declines this path without naming it. That is a real gap. The proposed
add-alongside fix is _safe_ and _unblocks the regeneration_, so it is the right move
under time pressure — but it leaves the collapse in place, and the next verifier run
will re-exhibit a variant of D2 (wrong canonical sitting beside the right term,
poisoning the LLM prompt) even if it can no longer delete data.

### Q2 — Attack the proposed fix: is §3.2 giving up too early?

**Partially. The spec is right that edit-distance/containment cannot separate the two
cases, and right to escalate. But it is wrong that no deterministic signal exists.**

The pipeline has access to two signals the spec ignores:

1. **The fansub track (where present).** `repair.overlap_ref()` already pulls a
   _different translation_ of the same scene. If the canonical proposal `Ratel`
   appears nowhere across the show's fansub tracks but `Raftel` appears N times, that
   is a strong negative signal. Conversely, `Donquixote Doflamingo` will appear in the
   fansub. This is not a deterministic _proof_ (the fansub is itself a localization,
   not canon), but it is a deterministic _corroboration_ counter-signal: a canonical
   that the show's own subtitles never use, while the proposed-replacement short form
   appears repeatedly, is the `Ratel`/`Trafalgar Lami` shape, not the `Kaidou`/
   `Donquixote Doflamingo` shape.

2. **The show's own transcripts (conf.json `text` fields).** The bare form `Trafalgar`
   appears in transcribed dialogue; `Trafalgar Lami` does not (Lami is Law's sister,
   barely on screen). A canonical that _expands_ a surname into a full name where the
   expansion target is never spoken is suspect. `glossary_acquire.py` already has
   machinery for this — `is_expansion()` (glossary_acquire.py, the `EXPANSION_RATIO`
   - containment check) and the `source_gate()` transcript-presence gate. The spec
     even cites the acquisition spec's philosophy ("our errors can raise a question; they
     can never become an answer") but does not reuse its gates.

**Concrete, implementable signal:** for a high-confidence canonical that _differs from
an existing term_ (the §3.2 case), run a corpus check before escalating:

- count occurrences of `term` (the short form) across the show's conf.json `text` +
  the fansub reference lines
- count occurrences of `canon` (the proposed canonical) in the same corpus
- if `term` occurs ≥ K times and `canon` occurs 0 times, **auto-reject** the canonical
  (do not even escalate to `flagged` — the corpus has disconfirmed it). This catches
  `Ratel` (Raftel is spoken, Ratel is not) and `Trafalgar Lami` (Trafalgar is spoken,
  Lami is not).
- if both occur, or only the canonical occurs, escalate to `flagged` as the spec
  proposes (genuinely ambiguous: `Kaidou` vs `Kaido` — both may appear; `Donquixote
Doflamingo` — the long form may appear in formal-fansub scenes).

**How it fails:** (a) a canonical the dub uses but the fansub and Whisper both
mishear consistently would be auto-rejected — rare, but the repair LLM is the
backstop; (b) corpus coverage varies by show progress, so K must be low (≥2) or the
gate is no-op on early episodes; (c) it does not separate `Kaidou`/`Kaido` (wiki-over-
dub) from a correct `Kaidou`-is-actually-dub case — that stays in `flagged`, which
is correct because it is a genuine authority conflict a human should settle.

So: **§3.2 is giving up one rung too early.** A deterministic corpus-corroboration
gate sits between "auto-apply" and "human," and would clear the unambiguously-wrong
proposals (`Ratel`, `Trafalgar Lami`, `Jabari`) out of the human queue entirely. The
spec's own architecture (deterministic → LLM → human) has room for it at the
deterministic top.

### Q3 — Does §3.1's routing rule hold? (canonical single-token → `names`, multi-word → `phrases`)

**No. It fails on two cases:**

1. **A multi-word canonical that is also a deterministic correction target.**
   `Rob Lucci` (multi-word) routed to `phrases` per §3.1 — but `phrases` has no
   deterministic role. The mishear `Lucci` (single token) is what the deterministic
   tier needs to match, and it needs to _rewrite_ to `Rob Lucci`. The correct home is
   `hard_fixes` (`lucci -> Rob Lucci`), not `phrases`. §3.1's rule routes the
   canonical _form_, but the deterministic tier needs a _mishear → canonical_ map,
   which `names`/`phrases` are structurally incapable of expressing. The rule is
   right for "what to add to the LLM prompt list" and wrong for "what to add to the
   deterministic correction surface."

2. **A single-token canonical that is a substring of a multi-word term already in
   `phrases`.** Adding `Kaidou` to `names` while `Kaidou` is also the canonical for a
   multi-word phrase (hypothetically) would double-match. Edge case, but the routing
   rule has no de-dup against the other list.

The deeper point (from Q1): routing by _shape of the canonical_ is the wrong axis. The
right axis is _role_: mishear-target (deterministic + LLM prompt) vs canonical-to-emit
(deterministic rewrite + LLM prompt). `hard_fixes` already encodes role correctly;
`names`/`phrases` cannot.

### Q4 — Is §3.4's invariant ("every `verified` term reachable at runtime") right?

**Right, but too weak, and it would false-alarm on exactly one legitimate case.**

Weaker-than-needed: the invariant catches _deletions_ (term promoted to `verified`
then removed from service). It does not catch the more common D2 failure: a term that
is _still in `names`_ but was _replaced in place_ by a wrong canonical — the short
form is gone, the wrong canonical is present, and the invariant passes because
_something_ is reachable. To catch D1+D2 together, the invariant needs to be: **every
term in `verified` is reachable, _and_ no term in `verified` has been overwritten by a
canonical that itself differs from the original term** — i.e., the _original_ verified
term, not just any string, must be the one reachable. That is a stronger invariant and
it is what the bug actually was.

False-alarm case: a term in `verified` that was _correctly_ promoted to `flagged` for
human review (the §3.2 path) is, per the spec's own design, _not_ in `names`/`phrases`
— it is in `flagged`. The spec's invariant explicitly includes `flagged` as a
"reachable" destination, so this is handled. Good. But it means the invariant conflates
"live in service" with "pending review" — a term stuck in `flagged` for 6 months
counts as "reachable." A stronger invariant would distinguish _in-service_ from
_pending_: every term in `verified` is either in-service (`names`/`phrases`/`hard_fixes`
values) _or_ has a `flagged` entry with a timestamp newer than N days. Stale `flagged`
entries would then alarm, which is the right behavior (the human queue is not being
worked).

The spec's shape check ("no multi-word string in `names`") is correct, cheap, and
would fail today. Keep it.

### Q5 — §3.3 backfill: what can it corrupt, and what ordering/idempotency hazard is missing?

**Three hazards, none addressed by the spec:**

1. **It mutates a glossary that `gen_loop.sh` re-reads every sweep, with no lock.**
   `gen_loop.sh:24-43` runs `mine_glossary.py` → `glossary_acquire.py` →
   `glossary_verify.py` → `generate.py` per show. If the backfill runs _while a sweep
   is in progress_ on the same show, `mine_glossary.py` (additive) or
   `glossary_verify.py` (which re-runs `apply_results`!) can race with the backfill.
   `glossary_verify.py` re-applying `apply_results` _after_ the backfill restored the
   short forms would re-trigger D1 on the next high-confidence canonical — the
   backfill is not durable against the next verifier run unless `apply_results` itself
   is fixed (§3.1/§3.2) **and deployed before the backfill runs**. The spec's ordering
   ("run before the v4 regeneration") does not say "run after the §3.1/§3.2 code
   change is deployed." If the backfill runs under the old `apply_results`, the next
   scheduled verify re-corrupts.

2. **Idempotency of step 1 is not guaranteed.** "Restore every term in `verified`
   absent from `names`/`phrases`/`hard_fixes` values" — but the restoration _adds_ the
   term. On a second run, the term is now present, so the step is a no-op _for the
   verified set_. However, step 2 ("move multi-word entries from `names` to `phrases`")
   and step 3 ("move wrong adjudications to `flagged`") are _moves_ — they remove from
   one list and add to another. If the script crashes between the remove and the add,
   the term is _deleted_ (worse than the original D1). The spec claims "backfill is
   idempotent" as a test, but does not specify the atomicity that would make it true:
   the move must be add-then-remove (or a single dict mutation), never remove-then-add.

3. **Step 4 deletes 10 attack names from `initial_prompt`, but `initial_prompt` is a
   single string, not a list.** Deleting substrings from a comma-joined prompt string
   is fragile — a naive `replace("Gum-Gum Bazooka, ", "")` works, but
   `replace("Gear Second", "")` would also delete "Gear Second" from "Gear Second Gear"
   if such a substring existed (it does not, but the hazard is real for general
   deletion). More importantly, the spec says keep `Gum-Gum Pistol` — the _only_
   human-confirmed one — but does not say where the confirmation is recorded. If it
   is in `known`/`acquired`, deleting from `initial_prompt` while leaving the glossary
   entry creates the same in-service/`verified` divergence the invariant is meant to
   catch. The backfill must delete from `initial_prompt` _and_ `phrases` _and_ record
   the 10 as `flagged` (reason: unverified-attack-name) so they are not re-proposed.

### Q6 — Spec 2: is depending on WatchState sound? Is "unreachable → refuse" sufficient?

**Sound, yes, for the stated purpose. Sufficient, no — one silent-wrong failure mode
is real.**

Depending on a third-party sync daemon is sound _because_ the alternative (Plex
directly) was measured 40 days stale, and the spec's §3 demonstrates the measurement.
WatchState is the right source. The "unreachable → refuse to write" rule correctly
handles the outage case.

**Failure mode the spec does not cover: WatchState reachable but its data silently
stale.** WatchState is _bidirectional_ (the spec says so: "importing and exporting
between both backends"). A bidirectional sync can silently _export_ a stale Plex
`watched` flag _into_ Jellyfin, or vice versa, and the `updated` timestamp reflects
the _sync_ time, not the _playback_ time. The spec's query (`max(updated)`,
`via=jellyfin`) trusts `updated` as a playback proxy. If WatchState re-synced a
stale row today, `updated` is today but nobody watched anything today. The queue
would then include a show nobody is actually watching — exactly the failure the
gate exists to prevent.

**Mitigation:** the spec should query WatchState's `watched` column (the table has
one: `state table: id, type, updated, watched, via, ...`), not just `max(updated)`.
A row with `updated` recent but `watched=0` (or `watched` older than the window) is
the silent-stale signature. The spec already has the schema (it prints it in §3) and
does not use the `watched` column. This is the same "ask a slightly different
question" failure the spec correctly identifies in Plex — the spec avoids Plex's
`lastViewedAt` and then repeats the mistake on WatchState's `updated`.

Second, smaller gap: the spec's `--pin` file (§4.7) is the correct safety for One Pace
during v4, but it is an _additive_ override — a pinned show that is _also_ in the
watch queue is not de-duplicated, which is harmless, but a pinned show whose directory
was renamed would silently stay pinned to a stale name. Minor.

### Q7 — What did both specs miss entirely?

**Three things, ranked by cost:**

1. **The next `glossary_verify.py` run re-triggers D1.** Neither spec makes the
   backfill durable against the _scheduled_ verifier that `gen_loop.sh:37-39` runs
   every sweep. §3.1/§3.2 fix the code; §3.3 backfills the data; but the spec does
   not say "deploy the code fix, _then_ run the backfill, _then_ block the next
   verifier run until the backfill commits." If the verifier runs between the code
   fix and the backfill, or between the backfill and the commit, the data re-corrupts
   under the _old_ code (if the deploy hasn't happened) or re-flags the restored terms
   (if it has). The ordering of code-deploy → backfill → verify is a release
   sequencing problem the spec treats as out of scope but is not.

2. **The 14 other shows' glossaries drifted the same way (Spec 1 §4 acknowledges this
   and defers). But the v4 regeneration is One Pace-only — the _other_ 14 shows will
   continue to be served by corrupted glossaries indefinitely, with no invariant
   alarm.** The §3.4 invariant, if added as a test, would presumably run against any
   glossary on demand — but neither spec wires it into `gen_loop.sh` or CI. A
   glossary-integrity test that runs in CI against the committed glossaries would
   catch the same drift on the other 14 shows before their next regeneration. The spec
   defers the re-adjudication but should not defer the _alarm_.

3. **Spec 2's WatchState query trusts `via=jellyfin` provenance, but the whole point
   of WatchState is that it unions both backends.** A show watched on Plex (not
   Jellyfin) would have `via=plex` and be excluded by the `via=jellyfin` filter. The
   spec's §3 measurement shows One Pace is watched on Jellyfin, but the _general_
   queue feature should not filter by `via` — it should take `max(updated)` across
   _all_ `via` values per show, or it will silently drop Plex-watched shows. The
   `via=jellyfin` filter is correct for the One Pace measurement and wrong for the
   general `watch_queue.py` design. The spec does not distinguish the two uses.

---

## Summary

Spec 1's root-cause diagnosis is **correct on the bug, incomplete on the structure**.
`apply_results` replacing in place is real (verified in source and against the live
glossary); the deeper collapse of _shape_ and _role_ taxonomies is named but not
fixed. The §3.1/§3.2 fix is safe and unblocks the regeneration; it is not the
structurally correct fix. The §3.2 "no deterministic signal separates wrong from
right canonical" claim is **refuted** — the show's own transcripts and fansub tracks
provide a corpus-corroboration signal the spec did not consider. The "10 of 12 absent
from `hard_fixes` values" measurement is **wrong by 2** (Alabasta, Straw Hats survive
as `hard_fixes` values); the bug stands, the measurement overclaims. The §3.4
invariant is too weak (would not catch in-place replacement where the wrong canonical
is still "reachable").

Spec 2's WatchState-over-Plex choice is **correct and measured**, but it repeats the
Plex mistake on WatchState's `updated` column — `watched` is the right column, and the
spec has the schema but does not use it. The `via=jellyfin` provenance filter is right
for measurement and wrong for the general queue.

Both specs miss the release-sequencing hazard: the code fix, the data backfill, and
the next scheduled verifier run are three independent events, and the spec does not
constrain their order.

The PROMPT's cautionary claim about `tools/timing_compare.py` reading `source_end` is
**stale** — no such read exists in `tools/` today. The methodological lesson stands;
the specific repro does not.

---

# Round 2 — the corroboration guard (replacing `is_expansion`)

The prompt is right that `is_expansion` does not separate correct from wrong
canonicals (3/12 as a discriminator). It was never a correctness test — it is a
substitution-safety rule for a _replace_ path, and under §3.1's add-alongside
semantics expansion stops being a hazard at all. What survives is `source_gate`'s
principle: corpus corroboration. Concrete design below.

## 1. The guard

Reuse the machinery that already exists — do not build a new corpus scanner.

**Corpus:** the show's own transcripts plus, where present, the fansub track.
`harvest_candidates(show_dir)` already walks both via `_iter_episode_texts` and tags
provenance per candidate record (`source = SOURCE_TRANSCRIPT | SOURCE_FANSUB`). The
fansub is the higher-authority corpus; the transcript is Whisper and counts for less.
For a verify-time canonical proposal we do **not** re-run harvest over the whole
show (expensive). We need counts for exactly two strings: `term` (the bare form in
the glossary) and `canon` (the proposed canonical). `context_lines(show_dir, [term,
canon], limit=N)` already does whole-word `\bword\b` retrieval across the same
episode iterator; we use it for _counting_, not for the lines — i.e. call it with a
large `limit` and take `len(out[s])` as the hit count, or add a sibling
`corpus_counts(show_dir, tokens)` that reuses the same `_iter_episode_texts` +
`\btoken\b` scan without buffering lines (cheap, and the function is two loops away
from `context_lines`).

So the inputs a verify-time guard needs are:

- `c_t` = whole-word occurrences of `term` across the union corpus (transcript +
  fansub), tagged by source so we can keep `c_t_fan` and `c_t_tr` separate;
- `c_c` = same for `canon`;
- `ep` = `episode_count` from the candidate record (how many episodes the variant
  appears in), reused as the coverage denominator.

**Threshold, not a raw count.** A raw `c_t >= K and c_c == 0` is what I proposed in
Round 1 and it is too brittle on early episodes (corpus coverage varies). Use the
signal `source_gate` already encodes: _does the variant corroborate while the
canonical does not?_ The metric is a ratio, discounted for small samples via the
`wilson_lower` that already exists:

- `r_t = wilson_lower(c_t, c_t + c_c)` — lower bound on the variant's share of
  (variant + canonical) mentions;
- floor on sample size: require `c_t + c_c >= NEAR_MISS_MIN_COUNT` (the existing
  constant, default 2) before the ratio means anything; below it, fall through to
  `flagged` (ambiguous, not auto-reject).

**Rule (runs in `apply_results` _before_ the in-place write, under the §3.1 fix where
the write becomes add-alongside):**

```
if conf == "high" and canon and canon != term:
    c_t, c_c = corpus_counts(show_dir, [term, canon])   # whole-word, union corpus
    n = c_t + c_c
    if n < NEAR_MISS_MIN_COUNT:
        verdict = FLAG          # corpus has nothing to say → human, as today
    elif c_c == 0 and c_t >= NEAR_MISS_MIN_COUNT:
        verdict = REJECT        # variant spoken, canonical never → auto-reject,
                                #   record in `flagged` with reason "corpus-disconfirmed"
    else:
        r_t = wilson_lower(c_t, n)
        if r_t >= 0.75:
            verdict = FLAG      # variant dominates but canonical appears too
                                #   (Kaido/Kaidou shape) → genuine authority conflict
        else:
            verdict = APPLY     # canonical corroborated in-corpus → safe to add
```

`REJECT` is the new rung. It does **not** delete the term — it keeps `term` in
`names`/`phrases` (the §3.1 add-alongside fix already preserves it) and writes the
proposed `canon` into `flagged[term] = {reason: "corpus-disconfirmed", canonical: canon}`
so the next verify run (incremental, skips `verified`) does not re-propose it, and a
human can overturn it. This mirrors exactly what `source_gate` does when it demotes a
transcript proposal to `flag` with `reason: "transcript-new-term"`.

**What it catches from the prompt's table:** `Ratel`, `Trafalgar Lami`, `Jabari`,
`Arabasta` all have `c_c == 0` in the dub transcripts (the dub says Raftel, Trafalgar,
Jabra, Alabasta) → auto-reject, out of the human queue. `Kaidou` vs `Kaido` has both
spoken → `FLAG`, correctly left for a human (genuine wiki-over-dub authority
conflict). `Donquixote Doflamingo`/`Boa Hancock`/`Rob Lucci` etc. have the canonical
spoken → `APPLY`.

## 2. Its false-positive mode

The prompt names it precisely: `Shirahoshi` and `Van Der Decken` are real dub names
that no fansub track ships and Whisper consistently mishears (the live `Syrahose` /
`Vanderdecken` forms). For these, `c_c == 0` and `c_t` (for the _mishear_) may be high
→ the guard would auto-reject a _correct_ canonical `Shirahoshi` because the corpus
never contains it.

The guard avoids this by **never auto-rejecting on transcript-only evidence when no
fansub corpus exists.** The `source` tag on the counts is what makes this work:

- If `c_t_fan > 0` (the fansub track is present and the variant appears in it) and
  `c_c_fan == 0`, `REJECT` stands — a human subtitle track using the variant but not
  the canonical is strong disconfirmation.
- If `c_t_fan == 0` because _there is no fansub track for this show_ (not because the
  variant is absent from one), the corpus is transcript-only and the verdict for
  `c_c == 0` downgrades from `REJECT` to `FLAG`. Whisper-mishear canonicals are exactly
  the case a transcript cannot disconfirm, and a human is the backstop. This keeps
  `Shirahoshi`/`Van Der Decken` reachable: they route to `flagged`, not the void.

This is the same provenance split `source_gate` already makes (fansub → permissive,
transcript → strict), inverted for the reject path: a reject needs the strong corpus,
not the weak one. The cost is that shows without a fansub track get no
auto-rejection at all — they keep the human rung. That is acceptable; the guard is
there to clear the unambiguous cases out of the human queue, not to eliminate it.

## 3. Does §3.2's human rung survive?

**Yes, as a floor. The guard does not replace it; it carves out the auto-rejectable
cases above it.** Three verdicts fall out of the rule above: `APPLY` (corpus
corroborates), `REJECT` (fansub disconfirms), `FLAG` (ambiguous or
corpus-empty). §3.2's human escalation is the `FLAG` rung, unchanged. What changes
is the _contents_ of `FLAG`: the `Kaido`/`Kaidou`-shape authority conflicts and the
`Shirahoshi`-shape unmineable canonicals land there, while the `Ratel`/`Trafalgar
Lami`-shape wrong canonicals are pulled _down_ into `REJECT` and never reach a human.
The net effect is a shorter, higher-signal human queue — exactly the "one rung too
early" correction from Round 1, but with the floor preserved because the guard has a
built-in `FLAG` escape hatch for every case its corpus cannot settle.

## 4. Should `glossary_verify.apply_results` keep existing?

**No as the adjudication path; yes as the writer, for now.** The prompt's structural
point is correct and load-bearing: `apply_results` is an older, blunter sibling of
`glossary_acquire`'s proposal pipeline, using none of the guards (`is_expansion`,
`source_gate`, `settled_target`, `anchor_terms`, `wilson_lower`, the `source` provenance
split) that `glossary_acquire` developed for the identical problem of _which
canonical to write_. Two modules, one question, one of them learned. That is the
real D2 hazard — not the in-place write (a one-line fix) but the fact that the
scheduled verifier re-runs an unguarded adjudication against production glossaries.

The clean end-state is: `apply_results` becomes a thin writer that takes a list of
_proposals_ (each `{variant, canonical, verdict, reason}`) and mutates the glossary
according to verdict — and the proposals are produced by routing the verify-time
term→canonical pair through `glossary_acquire`'s `decide()` + `source_gate()` with the
corpus counts above as its `variant_count`/`canonical_count` inputs. One adjudication
path, one set of gates, whether the term came from mining or from wiki-verify. The
`show_dir` that `verify()` already has (it can derive it from the glossary path / show
key) is the only new input the guard needs.

**But:** this is a larger refactor than the §3.1/§3.2 fix, and the prompt asked for the
mechanism, not a migration. The incremental path that does not waste the work above:

1. Ship the §3.1 add-alongside fix (kills D1) and the §3.2 corpus guard inside
   `apply_results` (clears the auto-rejectable wrong canonicals). This unblocks the
   v4 regeneration safely.
2. Land §3.4's stronger invariant (the _original_ verified term must be reachable,
   not just any string) as a CI test across all 15 glossaries — the alarm the specs
   deferred.
3. _Then_ refactor `apply_results` to delegate to `glossary_acquire`'s proposal
   pipeline, so the corpus guard above is deleted as duplicate code rather than
   maintained in two places. The guard designed here is the spec for what that
   pipeline must do at verify-time; once it lives in `glossary_acquire`, the local
   copy goes.

The guard is designed to be throwaway-on-merge: it exists to fix the scheduled
verifier now, and its logic is the acceptance test for the unified pipeline that
replaces it.

---

# Round 3 — acquire decision cache

**Spec under review:** `docs/superpowers/specs/2026-08-21-acquire-decision-cache-design.md`

Method: every factual claim about code was checked against the source at the cited
function. The spec cites no line numbers this round; the function names are correct
throughout. Findings use actual source. Mount options were checked against the live
compose file, not the spec's restatement of them.

## Findings, ranked by cost-of-being-wrong

### [CONFIRMED] Attack 1 — a wiki rename silently serves the wrong `canonical` forever

The spec's central claim is §2.1: _"A token's verdict does not change when new episodes
arrive... Absence is the cache miss. There is no corpus fingerprint, no TTL, and no
versioned key to get wrong."_ That is **true for the verdict label and false for the
`canonical` the cache also stores.**

The cache schema (spec §2.1) stores, per token, `{verdict, canonical, source, count}`.
`apply_proposals` (glossary_acquire.py:438–470) writes that stored `canonical` straight into
`hard_fixes[term] = p["canonical"]` on an `apply` verdict. The canonical is produced by
`_resolve_tokens` → `_best_title_indexed`, which resolves the token against **today's
`fetch_titles` output**.

`fetch_titles` (glossary_verify.py:247–270) is itself cached with `WIKI_TTL = 30 * 24 * 3600`
(default 30 days, glossary_verify.py:52) and is keyed on `(wiki_api, show_key)`. So the wiki
title list _does_ change — on a ~monthly cadence, or sooner if the cache file is removed /
`WIKI_CACHE_TTL` is lowered / a redirect changes `api`. A Fandom page rename ("Gum-Gum" →
"Gomu Gomu no Mi (Devil Fruit)") lands in `fetch_titles` on the next TTL expiry.

The decision cache has **no path that re-resolves a cached token against new titles.** The
token is either in the cache (verdict + canonical served verbatim, `_resolve_tokens` never
run for it) or absent (cache miss, full pipeline). So after a wiki rename, a token whose
verdict was `apply / canonical-unseen` keeps emitting the _old_ canonical into `hard_fixes`
forever — exactly the silent-wrong-forever class the spec says it is avoiding. The spec is
right that the _verdict_ ("this token is junk / settled / pending") is stable under new
episodes; it is wrong that the _payload_ (`canonical`) is. `known`/`junk` verdicts are safe
under this; `apply` verdicts are not.

**Cheapest correct guard, staying inside the spec's own no-fingerprint philosophy:** key the
cache entry on the wiki title-set identity it was decided against, not on the token alone.
`acquire()` already computes a `digest = sha1("|".join(f"{p['variant']}>{p['canonical']}" ...))`
(glossary_acquire.py ~line 820) and a `run_id` containing `len(titles)`. A cheaper, sufficient
signal is `len(titles)` (already in `run_id`) plus a hash of the title list (or just the
`fetched_at` timestamp already sitting in the wiki cache file). Store `titles_sig` on each
cache entry; a cache hit requires `entry.titles_sig == current_titles_sig`. A rename changes
the sig, so every entry misses once, the pipeline re-runs at full cost for one sweep, and the
cache repopulates with the new canonicals. No TTL, no fingerprint on the _corpus_ (which the
spec correctly avoids), no versioned key to maintain by hand — just a content hash of the one
artifact the verdict actually depends on. This is the spec's own "absence is the cache miss"
principle applied to the one dependency the spec forgot it had.

The human-overturn and `propose`-threshold cases (the prompt's other examples) are real but
lower-cost: a human `--review` decision writes to `known`/`acquired` in the _glossary_, which
`acquire()` reads into `settled` (glossary_acquire.py ~line 800) — so the next sweep's
`settled` set already reflects the overturn, and the cached token is skipped at the
`settled` check _before_ the cache is consulted (the cache is downstream of `settled`).
Verified: `settled = set(gloss.get("known", [])) | set(gloss.get("acquired", {}))` runs before
`propose`, and `propose` skips `tok in settled` before any cache lookup would occur. So the
glossary is the source of truth for human overturns, and the cache is not consulted for
settled tokens. The `propose`-threshold case (env-var changes to `MIN_COUNT`, etc.) is a real
stale-verdict hazard but is an operator knob, same class as the `PIPELINE_VERSION` bump the
`.dubtitles.done` stamp already handles — and the spec's §2.3 reuses that exact mechanism
for the harvest cache, so the idiom exists and the decision cache should share it: a version
bump in `common.py` invalidates the decision cache the same way it invalidates the harvest
stamp.

### [CONFIRMED] Attack 2 — the CIFS claim is mis-stated, and the risk asymmetry is real

The spec (§2.3) says the library is mounted over CIFS with `cache=none,nobrl,actimeo=1`.
**`actimeo=1` is not in the mount.** The live mount option string
(docker/compose/dubtitles-3200g.yaml:128) is:

```
username=...,password=...,vers=3.0,uid=1000,gid=100,file_mode=0777,dir_mode=0777,nobrl,cache=none
```

`actimeo` is an NFS/NFSv4 mount option; it has no meaning on a CIFS mount, and it is not
present. `cache=none` is the CIFS-side attribute-cache control (it disables client-side
caching of file _data and metadata_ — closer to `actimeo=0` semantics than `actimeo=1`,
though the kernel module's exact behaviour differs). The spec conflated the two filesystems
this project uses (NFS on fasc, CIFS on 3200g) and smuggled an NFS option into the CIFS
string. This is exactly the "verify against the source, the author has been wrong about this
kind of claim repeatedly" failure the prompt warned of — the claim matched what one would
expect ("a cache key needs honest mtime") and was wrong on the specifics.

**The risk-asymmetry point the spec raises is correct and load-bearing.**
`stamp_valid()` (common.py:196–205 → `_stamp_matches_file`, common.py:185–192) uses
`abs(stamp.get("mtime", 0) - st.st_mtime) < 1.0` to decide whether to _regenerate an episode_
— a fail-safe use: a stale or wrong mtime triggers re-transcription, which is expensive but
correct. The harvest cache would use the same triple to decide whether to _skip reading a
file_ — a fail-silent use: a wrong mtime means the cache serves the old per-episode text and
the pipeline never sees the new content.

Those are **not the same risk.** The prompt's question is answered: fail-safe vs fail-silent
is the difference. Under `cache=none`, CIFS does not coherently cache attributes server-side
for the client, so `st_mtime` reflects the server's current state at `stat` time — good.
But `cache=none` also means every `stat` is a round-trip, and CIFS over a network blip can
return a **cached-then-stale** mtime during the window the mount is recovering (the 3200g
compose's own healthcheck comment, dubtitles-3200g.yaml:105–112, documents that this CIFS
mount drops on network blips and the container has to be force-recreated). During that
recovery window, `os.stat` can return the mtime of the _pre-edit_ file from a stale file
handle (ESTALE recovery is not atomic), and the harvest cache would conclude "unchanged, skip"
for a file that has in fact changed.

The spec's §2.3 claim that the `(path, size, mtime)` triple is "the same triple
`common.stamp_valid()` already uses... so the idiom is established and its failure modes are
known" is **half-right**: the idiom is established, but its known failure mode (stale mtime
→ wrong decision) has the _opposite_ safety polarity in the two uses. The harvest cache
needs either a fail-safe default (on any mtime ambiguity, re-read) or a content hash, not
just the same triple.

### [REFUTED] Attack 3 — the structural/frequency junk split is clean; 3x is defensible

The spec (§2.2) says structural junk (`english-word`) never recycles, only frequency-derived
junk (`below-floor`) does, and recycles at `count > cached_count * 3`.

**The split is clean.** Verified in `propose` (glossary_acquire.py:593–596): the
`english-word` verdict is produced by a _separate_ code path (`if d["verdict"] != "known"
and glossary.is_english(tok.lower())`) that overwrites whatever `decide()` returned, and it
is structurally terminal — `is_english` (glossary.py:57) is a static wordlist membership
test whose answer for a given token never changes. A token that is an English word today is
an English word in 200 episodes. So `english-word` never recycling is correct, and there is
no `junk` reason that _looks_ structural but is not: the only structural junk reason is
`english-word`, and it is exactly the one the spec exempts.

However, the spec's framing implies `below-floor` is the _only_ frequency-derived junk
reason. It is not. `decide()` (glossary_acquire.py:494–528) emits `flag` verdicts with these
reasons: `below-floor`, `sentence-initial-only`, `already-canonical`,
`unseen-needs-evidence`, `share-too-close`. `source_gate` (glossary_acquire.py:438–455)
adds `transcript-new-term` and `growth-over-cap`. Of these, `below-floor`,
`unseen-needs-evidence`, `share-too-close` (post-escalate-failure), `transcript-new-term`,
and `growth-over-cap` are all _frequency-or-corpus-derived_ — their verdict could flip on a
larger corpus. `sentence-initial-only` is structural-ish (a token's positions don't change
materially with more episodes, though a token seen only sentence-initially in 3 episodes
may appear mid-sentence in 200). `already-canonical` is structural.

The spec's `junk` bucket would, per its §2.1 schema (`{verdict: "junk", reason: ...}`),
absorb all `flag`-reasoned tokens under a single `junk` verdict, then recycle only the ones
whose `reason` is frequency-derived. **That works**, but the spec does not enumerate which
reasons count as frequency-derived — it names only `below-floor` as the example. A token
flagged `transcript-new-term` at count 2 that later appears at count 50 has _exactly_ the
recurrence-growth signature the spec's 3x rule is meant to catch, but the spec's prose would
leave it permanently junk because it is not `below-floor`. **This is a real under-recycling
gap**: the recycle rule should key on _"verdict is junk AND reason is not in
{english-word, already-canonical, sentence-initial-only}"_, not on `reason == below-floor`.

**3x is defensible.** The module's existing growth cap is `GROWTH_MAX = 2`
(glossary_acquire.py, the `grew > GROWTH_MAX` check in `source_gate`), and the near-miss
floor is `NEAR_MISS_MIN_COUNT = 2`. A junk token at cached count N re-entering at 3N means a
token seen twice (the floor for any candidate to be worth looking at) recycles at count 6 —
roughly the threshold where a name that recurred in 2 episodes is now recurring across
enough episodes to plausibly be real. Below 3x (e.g. 2x) a token at the 2-floor recycles at
4, which is still in the noise band the floor was set to reject; above 3x the cache stops
being useful for the very case it exists for (a long-tail name that becomes heavy late).
3x is the point that clears the floor-with-margin. Growth is the right trigger — it is the
one signal a `junk` verdict is _conditional on_ (count was too low), so it is the one signal
whose change should re-open the question.

### [CONFIRMED] Attack 4 — caching changes the glossary via the `anchor_terms` floor

The spec (§2.4) claims the cache is "purely a performance change" and that `propose`/`decide`
keep their current logic. **Caching a verdict produces a different glossary than not caching
it, through an ordering effect the spec does not consider.**

`propose`'s floor depends on `settled_target`: if a token's near-miss is in the anchor set,
the floor is `NEAR_MISS_MIN_COUNT` (2); otherwise it is `MIN_COUNT` (3)
(glossary_acquire.py:574–576, `floor = NEAR_MISS_MIN_COUNT if (target and ...) else
MIN_COUNT`). The anchor set is `anchor_terms(gloss)` = `names ∪ hard_fixes.values()`
(glossary_acquire.py:430–436), and `hard_fixes.values()` includes every `acquired` canonical
— which **grows between sweeps** as `apply` verdicts land.

So: a token `kinamon` at count 2 is `below-floor` (floor 3) on sweep 1 when no anchor is
near it. Sweep 2 acquires `Kin'emon` (a different token) into `hard_fixes`. Sweep 3:
`kinamon` now has `settled_target = Kin'emon`, its floor drops to 2, and it becomes
`apply`-eligible. **If the decision cache was written on sweep 1, it holds
`{kinamon: junk, reason: below-floor, count: 2}` and serves it forever** — the floor change
from the grown anchor set is never observed, because the cached token is skipped before
`propose` runs.

The spec's §2.2 recycling rule does _not_ catch this: `kinamon`'s count has not grown (it is
still 2), so `count > cached_count * 3` is false. The verdict flip is caused by an _external_
change (the anchor set grew), not by the token's own count growing. The spec's recycle
trigger is the wrong axis for this case.

This is not a hypothetical edge — it is the _normal_ steady-state behavior of a corpus being
filled in incrementally. The first ~100 episodes resolve few near-misses against few
anchors; as anchors accumulate, tokens that were `below-floor` become
`NEAR_MISS_MIN_COUNT`-eligible. Caching the early `below-floor` verdict freezes the floor at
its pre-anchor value. The cost is _missed acquires_ (correct canonicals that the cache
prevents from ever being proposed), not wrong acquires — so it fails _towards_ the current
state (empty glossary), which is safe but defeats the purpose of the cache for exactly the
long-tail-recurrence names One Pace punishes on.

**Guard:** the recycle rule needs an anchor-set-growth trigger in addition to the
count-growth trigger: a `junk` token re-queues if `current_anchor_count >
cached_anchor_count` (store `len(anchors)` on the cache entry, cheap to compute). This is
the same "store the denominator the verdict was conditional on" principle as storing
`count`.

### [REFUTED] Attack 5 — deferring the 94% proposal rate is right; the cache does not

memoize wrong verdicts

The spec (§3) defers re-tuning `propose`'s 94% pass-through rate on the grounds that the
cache makes it cost nothing per sweep. The prompt asks whether this means the cache
memoizes a large pile of _wrong_ verdicts, making a bad decision permanent.

**It does not.** The cache stores verdicts for tokens that _resolved to a wiki title and
were decided_. The 7,695 proposals are tokens that `propose` emitted proposals for — i.e.
tokens that passed `_resolve_tokens` (resolved to some title ≥ `MIN_SIM`) and were not in
`settled`. Of those, the vast majority land in `junk`/`flag` verdicts (the spec's §2.2 says
junk absorbs most of the 7,695). A `flag` verdict is **not a wrong decision** — it is the
_correct_ decision for an ambiguous token, and it is the input to the human review queue.
Caching `flag` means "don't re-spend an LLM escalation call reaching the same `flag`" — which
is the spec's stated goal and is correct.

The hazard the prompt is pointing at would be real if `propose` were emitting `apply` verdicts
that are wrong. But `apply` is gated by `source_gate` (transcript candidates need
`settled_target`, glossary_acquire.py:438–455) and by `decide`'s dominance/unseen rules — an
`apply` verdict is never a near-pass-through. The 94% pass-through is `propose` _proposing_
( emitting a proposal record), not `propose` _applying_. The spec's deferral is correct
because the expensive wrongness, if any, is in the `flag` bucket, and the cache's job is to
_not re-adjudicate_ flagged tokens — which is right whether the flag was right or wrong. A
human `--review` overturn on a flagged token writes to the glossary's `known`/`acquired`,
which feeds `settled` on the next sweep and skips the token before the cache is consulted
(see Attack 1). So the cache does not make a bad `flag` permanent — the human path remains
the escape hatch, and the cache sits downstream of it.

The one residual hazard: if `propose`'s thresholds are _so_ loose that it flags tokens that
should have been auto-applied (correct canonicals left in `flag`), the cache preserves that
under-flagging. But that is the existing `propose` tuning problem the spec explicitly defers
(§3), and the cache does not make it worse — without the cache, the same under-flagging
repeats every sweep too; the cache just stops re-paying the LLM cost to reach the same
under-flagged answer. Deferring is right.

### [CONFIRMED] Attack 6 — what the spec missed entirely

1. **The decision cache has no `settled`-growth invalidation, and `settled` is the cache's
   _input_, not its output.** The cache is consulted _after_ `settled` is computed
   (glossary_acquire.py:800, `settled = ... ` is line ~800, cache would be downstream). But
   `settled` grows between sweeps (every `apply` adds to `acquired`, every `known` adds to
   `known`). A token that was _absent_ from the cache because it was `settled` on sweep 1 is
   still absent on sweep 2 — correct. But a token that was _in the cache_ as `junk` on
   sweep 1 may, on sweep 2, have become `settled`-adjacent (its near-miss is now an anchor),
   changing its floor. This is Attack 4's mechanism, restated as a missing-invalidation
   axis: the cache validates on `count` growth but not on `anchor_terms` growth. The spec's
   §2.2 is the only invalidation logic, and it is count-only.

2. **`escalate` sees a smaller `share-too-close` set under the cache — but that is safe.**
   With cached verdicts, the `close = [p for p in proposals if p.get("reason") ==
"share-too-close"]` set (glossary_acquire.py ~line 810) is smaller, so `context_lines` #1
   (the one for escalate context) scans fewer tokens. Each `escalate` call is independent
   per-proposal (`adjudicate_merge` takes one variant/canonical pair), so a smaller set does
   not change the _decisions_ on the remaining tokens — only the _cost_. This is the one
   ordering effect that is genuinely purely-performance. Noted to distinguish it from
   Attack 4.

3. **The spec's corrupt-cache test is weaker than the failure mode that will actually
   occur.** §4's test "a corrupt cache degrades to a full run" is right, but the cache will
   _not_ be corrupt in the obvious way (bad JSON) — it will be _semantically_ stale via
   Attacks 1 and 4. A `try/except json.JSONDecodeError → full run` test passes while the
   cache silently serves wrong canonicals. The test that would catch the real failure is:
   _change the wiki title set, assert the cache misses_. That test is not in §4, and without
   it the spec's "absence is the cache miss" claim is untested for the one absence that
   matters.

4. **`context_lines` #2 (the >420s killed phase) is not addressed by either cache.** The
   spec's §1 profile shows the _second_ `context_lines` call — the one that walks 462 files
   for flagged-term evidence — was still running at 7min when killed. The decision cache
   (§2.1) removes the 71% (`escalate`) but does **not** remove the second `context_lines`,
   because flagged terms' evidence is attached _after_ `source_gate`
   (glossary_acquire.py ~line 818–824: `flag_terms = sorted({p["variant"] for p in proposals
if p["verdict"] == "flag"})` then `fctx = context_lines(show_dir, flag_terms)`). The harvest
   cache (§2.3) speeds up the _file reads_ but the scan is still `files x flag_terms`. If the
   cache reduces the `flag` set (by caching prior `flag` verdicts as `junk`), this phase
   shrinks — **but only if prior flagged tokens are re-classified as junk, which the spec
   does not do** (a `flag` verdict is cached as `flag`, not `junk`; only `decide`/`source_gate`
   produce `junk`, and the spec caches the verdict verbatim). So the second `context_lines`
   remains `files x (flagged terms not yet in cache)`, which on the _first_ post-cache sweep
   is still the full flagged set. The spec's claim that the cache "removes ~99% of the work"
   is true for `escalate` but **overstated for `context_lines` #2** — that phase is the one
   that killed the run, and it is the least-addressed by the spec.

---

## Summary

The spec's performance diagnosis is correct: `escalate` is 71% and re-deriving 99% of
verdicts every sweep is the disease. The per-token decision cache removes the 71%. The
harvest cache removes most of the file-scan cost. Both are worth building.

The spec's safety claim — _"absence is the cache miss, no invalidation logic, a token's
verdict does not change"_ — is **wrong on two axes the spec did not consider**:

1. **The `canonical` payload changes when the wiki renames a page** (Attack 1). The verdict
   _label_ is stable; the _canonical the cache stores and writes into `hard_fixes`_ is not.
   `fetch_titles` has a 30-day TTL and _will_ return a different title list; the decision
   cache has no path to notice. Fix: key the cache entry on a title-set signature (hash or
   `fetched_at`), so a rename misses once.

2. **The `below-floor` verdict changes when `anchor_terms` grows** (Attack 4). A token junked
   at count 2 with no nearby anchor becomes apply-eligible when an anchor lands near it —
   and the cache's count-growth trigger does not fire because the token's _own_ count did not
   change. Fix: store `len(anchors)` on the cache entry and recycle on anchor-set growth.

The CIFS mount claim is mis-stated (no `actimeo=1`; that is an NFS option smuggled into a
CIFS string — exactly the kind of error the prompt warned to check hardest on). The
risk-asymmetry point (fail-safe vs fail-silent) is correct and is the reason the harvest
cache needs a content hash or fail-safe default, not just the same `stamp_valid` triple.

The junk split is clean (only `english-word` is structural; `is_english` is a static
terminal test) and 3x is defensible. The recycle rule's _reason_ filter is too narrow
(should recycle any non-structural junk reason, not only `below-floor`), but that is a
completeness gap, not a wrong-answer risk.

The `context_lines` #2 phase that actually killed the run is the _least_ addressed by the
spec — the decision cache does not shrink it until a second sweep, and even then only if
`flag` verdicts are re-classified as `junk`, which the spec does not do.

Deferring the 94% `propose` tuning is right: the cache does not memoize wrong _decisions_,
it stops re-paying to reach the same (possibly suboptimal) decision, and the human `--review`
path remains the escape hatch upstream of the cache.

---

## Self-rebuttal — where the above overreaches

I wrote the findings above as an adversary. Re-reading them as the spec's defender, four of
the six CONFIRMED/REFUTED claims are weaker than I made them sound. The point of writing
this down is the same as the prompt's one rule: a claim that matches what you'd expect is
when to check it hardest — and several of mine matched _my_ expectations of finding a bug,
which is the same failure mode from the other direction.

### Attack 1 (wiki rename → wrong canonical forever) is real but I overstated its

frequency and its blast radius.

**What I got right:** the cache stores `canonical` verbatim; `fetch_titles` has a 30-day
TTL; a rename is not detected. The mechanism is real.

**What I overstated:**

1. **A rename of a title that a token _resolved to_ is rare; a rename that changes which
   _entity_ the token resolves to is rarer.** Fandom page renames are overwhelmingly
   disambiguator edits ("Gum-Gum" → "Gum Gum (Devil Fruit)"), not entity swaps.
   `normalize_title()` (glossary_acquire.py:33–39) strips trailing `(…)` disambiguators
   and `/` subpage suffixes before resolution. So a rename that only touches the
   disambiguator produces the _same_ `normalize_title()` output and does not change the
   cached canonical at all. The wrong-answer case requires a rename that changes the
   _normalised_ name — e.g. "Raftel" → "Laugh Tale" — which is a genuine canonical
   correction, happens on the order of once per show per decade, and is exactly the case a
   human _wants_ to re-decide anyway. My "silently serves the wrong canonical forever"
   framing implied routine wrongness; the real frequency is "rarely, and when it happens a
   human probably wants to re-litigate it regardless."

2. **The blast radius is one token, not the cache.** A rename of title T affects only the
   cached entries whose stored `canonical == old_name(T)`. Tokens that resolved to _other_
   titles are unaffected. I implied the whole cache rots; it is per-token.

3. **My proposed fix (title-set signature) invalidates _everything_ on any rename, which is
   the spec's stated failure mode for a fingerprint.** The spec §2.1 explicitly rejects a
   "corpus fingerprint" on the grounds that "silently invalidating everything" is the bug
   this project keeps finding. A title-set hash IS a fingerprint — a single disambiguator
   rename on an unrelated page bumps the hash and re-runs the entire 71% `escalate` cost
   for one show. That is the over-invalidation the spec is trying to avoid, and I proposed
   it without costing it. A _cheaper_ fix that stays inside the spec's philosophy: store
   the _per-token_ canonical's normalised form alongside the verdict, and on a cache hit,
   verify that normalised form is still _present_ in the current `norm_titles` set (which
   `acquire()` already computes, glossary_acquire.py:799). That is O(1) set membership per
   cached token, invalidates only the affected entries, and needs no global hash. I should
   have proposed that, not the title-set signature.

4. **The human `--review` path is a stronger escape hatch than I credited.** A human who
   notices a wrong canonical in `hard_fixes` runs `glossary_acquire.py --revert` (which
   exists, glossary_acquire.py:693–714, and removes `acquired` entries by `run` id). The
   revert removes the term from `acquired`, which removes it from `settled` on the next
   sweep — but the cache entry persists. So my original claim ("revert does not clear the
   cache") holds for the _cache_, but the _practical_ recovery is: revert + delete the
   `.acquire-cache.json` sidecar, which the spec's §4 "corrupt cache degrades to a full
   run" test already covers. The operator path exists; I framed it as absent.

**Net:** Attack 1 stands as a real gap (the cache has no stale-canonical detection), but
my proposed fix was wrong-shaped and my frequency framing was alarmist. The cheapest correct
guard is a per-token `canonical in norm_titles` membership check, not a title-set hash.

### Attack 2 (CIFS `actimeo=1` mis-stated) — the correction is right, but I made a

safety claim I did not measure.

**What I got right:** `actimeo=1` is not in the mount (dubtitles-3200g.yaml:128); it is an
NFS option; the spec conflated the two filesystems. This is verified.

**What I overstated:**

1. **I asserted that `cache=none` can return a "cached-then-stale mtime during a recovery
   window" without measuring it.** That is a plausible kernel behaviour, but I did not
   reproduce it, and the 3200g compose's own comment block (dubtitles-3200g.yaml:114–126)
   says `cache=none` is _harmless_ and that the real past failure was group permissions, not
   attribute staleness. I took a theoretically-possible failure mode and wrote it up as a
   live risk. The prompt's rule — verify against the source before accepting — applies to
   _me_ too, and my staleness claim is [UNVERIFIABLE] until someone triggers an ESTALE mid-
   `os.stat` and observes a stale mtime return. I should have tagged it that, not CONFIRMED.

2. **The risk-asymmetry point (fail-safe vs fail-silent) is correct in principle but the
   _magnitude_ is smaller than the asymmetry implies.** `stamp_valid`'s fail-safe path
   regenerates an _episode_ (a GPU transcription, ~minutes). The harvest cache's fail-silent
   path serves stale _text_ for one episode to the LLM escalator, which then reaches the
   same verdict it would have on fresh text in the common case (the flagged token's context
   lines are for _evidence shown to a human_, and a renamed episode file is not the common
   case). The asymmetry is real; the consequence is "occasionally slightly stale context for a
   human reviewer," not "silently wrong glossary entries written to production." I framed it
   closer to the latter.

3. **`stamp_valid` does NOT only use mtime — it uses `(size, mtime)` (common.py:185–192).**
   A file whose mtime lied but whose size changed would still invalidate. The harvest cache
   reusing the _same triple_ gets the same protection: an edited episode almost always
   changes size too. The pure-mtime-staleness case requires an edit that preserves byte size,
   which for subtitle text is vanishingly rare. My framing ignored the `size` component of
   the triple, which is the half that actually catches edits.

**Net:** the spec's `actimeo=1` is wrong and should be corrected. My stronger claim — that
the harvest cache needs a content hash _in addition to_ the `(path, size, mtime)` triple —
is not supported by measurement. The triple's `size` component already catches the edit
case; the remaining mtime-staleness-during-recovery case is [UNVERIFIABLE] and lower-cost
than I implied. The spec's reuse of `stamp_valid`'s triple is more defensible than I gave it
credit for.

### Attack 4 (anchor growth changes floors) — the mechanism is real but the _practical_

frequency is low, and my fix has the same over-invalidation problem as Attack 1's.

**What I got right:** the floor _does_ depend on `anchor_terms`; anchors _do_ grow; a
cached `below-floor` verdict at count 2 would not re-evaluate when the floor drops.

**What I overstated:**

1. **The anchor set grows slowly and from a specific source.** `anchor_terms()`
   (glossary_acquire.py:430–436) = `names ∪ hard_fixes.values()`. `names` is
   curated/mined — it does not grow from `acquire()`. Only `hard_fixes.values()` grows, and
   only from `apply` verdicts (which require `settled_target` for transcript tokens, i.e.
   the token was _already_ a near-miss of an existing anchor —
   `source_gate`, glossary_acquire.py:438–455). So the anchors that _land near a junked
   token_ are themselves canonicals that were applied because _yet another_ token was their
   near-miss. The chain is: token A junked (count 2, no anchor near) → token B (A's
   near-miss? no — B is a _different_ token whose canonical is near A) gets applied → A's
   floor drops. For A's floor to drop, B's applied canonical must be a near-miss of A, and
   B must be a _different_ token that independently cleared all gates. That is a real but
   narrow coincidence, not the "normal steady-state" I called it.

2. **`below-floor` at count 2 with floor 3 is already in the noise band.** The module's
   own D4 comment (glossary_acquire.py, the `NEAR_MISS_MIN_COUNT` block) says high counts
   are correct names and errors live in the tail (count 2–4). A token at count 2 that
   becomes eligible when the floor drops to 2 is _exactly_ the tail the floor was split to
   be cautious about. Re-evaluating it would mostly produce... another `flag`, not an
   `apply`. So the _missed acquires_ I warned about are rare in two ways: the anchor
   coincidence is rare, and even when it fires the outcome is usually still `flag`.

3. **My fix (store `len(anchors)`, recycle on anchor-count growth) over-invalidates the same
   way Attack 1's title-set hash did.** `len(anchors)` grows on every single `apply` — so
   every `apply` verdict would invalidate _every_ `below-floor` junk entry, re-running the
   pipeline for all of them. That is the "silently invalidating everything" failure the
   spec rejects, applied to the junk bucket. A per-token fix (store the _specific_ anchor
   the floor was conditional on, recycle only if _that_ anchor appears) is cheaper and more
   targeted — and is closer to what the spec's existing `settled_target` field already
   records on each proposal. I proposed the blunt instrument.

**Net:** the mechanism is real but low-frequency, and mostly fails _towards_ `flag` (safe),
not towards wrong `apply` (unsafe). The spec's omission is a _recall_ gap (missed acquires of
rare long-tail names), not a _correctness_ gap (wrong canonicals written). My framing
conflated the two. The right fix is per-token anchor tracking, not anchor-count growth.

### Attack 6.4 (context_lines #2 not addressed) — I misread what the decision cache

does to the flagged set.

**What I claimed:** the decision cache doesn't shrink `context_lines` #2 because `flag`
verdicts are cached as `flag`, not `junk`, so the flagged set stays full.

**What I missed:** the spec's §2.1 cache stores a verdict _per token_. A token whose
cached verdict is `flag` is, on the next sweep, **a cache hit** — it is skipped before
`propose` runs, so it never re-enters the `flag_terms` set that drives `context_lines` #2.
The flagged set on sweep N+1 is _only the newly-decided tokens_, not the union of all
ever-flagged tokens. So the decision cache _does_ shrink `context_lines` #2, on the very
next sweep, by exactly the set of tokens that were flagged on sweep N. My claim that it
"does not shrink until a second sweep, and even then only if `flag` verdicts are
re-classified as `junk`" is **wrong** — I confused "cached as `flag`" with "still in the
flagged set." A cached `flag` is _absent_ from the next sweep's flagged set, which is the
shrinkage. The spec's claim that the cache removes ~99% of the work _does_ cover
`context_lines` #2 in steady state.

The residual concern (first post-cache sweep still pays the full `context_lines` #2) is
true but trivial — it is one sweep, then the cache is warm. I inflated a one-sweep
cold-start cost into a structural gap.

**Net:** Attack 6.4 is **[REFUTED — by me, of my own finding].** The decision cache does
shrink `context_lines` #2. The spec's performance claim is more complete than I gave it
credit for. The only legitimately-missed item in Attack 6 is 6.1 (anchor-growth
invalidation, see above) and 6.3 (the test that would catch the real failure mode is
missing) — and 6.3 is now weaker given Attack 1's rebuttal above.

### What survives the rebuttal

Of the original findings, after self-rebuttal:

- **Attack 1:** real gap, but my fix was wrong-shaped and frequency overstated. The
  per-token `canonical in norm_titles` check is the right guard; the title-set hash is
  over-invalidation. Severity: low-frequency, fails towards a human-re-litigatable case.
- **Attack 2:** the `actimeo=1` correction stands (verified). My stronger claim about
  mtime staleness under `cache=none` is [UNVERIFIABLE] and the `size` component of the
  triple already catches edits. The spec's reuse of `stamp_valid`'s triple is more
  defensible than I implied.
- **Attack 3:** unchanged — the junk split is clean, 3x is defensible, the recycle-reason
  filter is too narrow but it's a completeness gap not a wrong-answer risk. This finding
  was already modest.
- **Attack 4:** mechanism real but low-frequency and fails towards `flag` (safe), not
  `apply` (unsafe). My fix over-invalidates; per-token anchor tracking is better. Severity:
  recall gap, not correctness gap.
- **Attack 5:** unchanged — deferring is right.
- **Attack 6:** 6.4 refuted by me; 6.1 and 6.3 survive but weakened.

The spec's core design — per-token verdict cache, no global fingerprint, junk recycles on
count growth — is **more sound than my Round 3 made it sound.** The two real gaps
(stale-canonical after wiki rename; floor-flip on anchor growth) are low-frequency, fail
towards safe states, and have cheaper per-token guards than the global invalidation I
proposed. The spec's explicit rejection of a fingerprint is _correct_ for the verdict
label; my job was to find where the _payload_ (canonical, floor) is not covered by that
rejection, and I found two cases — but I then proposed the very fingerprint the spec was
right to avoid, twice. The per-token membership-check / per-token-anchor-tracking pattern
is the one that respects the spec's philosophy while closing the gaps.

---

## Fix draft

Concrete amendments for the surviving gaps live in
[`2026-08-21-acquire-cache-fix-draft.md`](./2026-08-21-acquire-cache-fix-draft.md),
alongside this review. It covers only what survived the self-rebuttal:

- **Fix A** — stale-canonical detection via per-token `canonical in norm_titles`
  membership check (closes Attack 1; replaces my wrong-shaped title-set hash).
- **Fix B** — floor-flip detection via per-token `floor_anchor` tracking
  (closes Attack 4; replaces my over-invalidating `len(anchors)` trigger).
- **Fix C** — broaden the recycle-reason filter from `below-floor` only to all
  non-structural junk reasons (closes Attack 3).
- **Fix D** — correct the `actimeo=1` typo (closes Attack 2; no code, just the
  spec's restatement of the mount options).

It deliberately excludes the title-set hash, the `len(anchors)` trigger, the harvest-cache
content hash, and any `context_lines` #2 fix — all four were refuted in the self-rebuttal
above and should not be absorbed into the spec.
