# Review — repair-review-and-decision-store

GLM, 2026-08-27. Fifth review on DubTitlerr, reviewing the consequence of my
own round-2 finding. The spec under review is
`.procoder/specs/repair-review-and-decision-store.md`. Every claim below is
anchored to the source I read this session.

---

## The two verified claims

**Claim 1: `hard_fixes` does not reach the decoder. CONFIRMED.**

`glossary.load_dict()` (glossary.py:50-60) splits `hard_fixes` into
`token_fixes` and `phrase_fixes` and never touches `initial_prompt`.
`glossary.prompt_for()` (glossary.py:112-122) returns
`gloss.get("initial_prompt")` or a show-derived string — it reads nothing from
`hard_fixes`, `token_fixes`, or `phrase_fixes`. `glossary.stale_tier()`
(glossary.py:127-145) compares the stored `initial_prompt` STRING against
`prompt_for()`, and its own docstring says: "Everything else a glossary drives
(`names`, `hard_fixes` -> token/phrase fixes) is consumed by correct() at card
level, long after the words exist, and is therefore CPU work on the text tier."

So promoting a term verdict into `hard_fixes` via [S-3] cannot alter
`initial_prompt`, cannot mark episodes transcription-stale, and does not trigger
the GPU tier. The spec's "no `TEXT_VERSION` bump needed" claim
(`repair-review-and-decision-store.md`, Constraints, ADR 0001 bullet) holds for
the consult path. This was verified against the source, not assumed.

**Claim 2: `repair.py` never rewrites `conf.json`. CONFIRMED.**

`repair.process()` (repair.py:440-445) loads `conf = json.load(open(conf_path))`
and mutates it in-memory (`c["text"] = new` at repair.py:549), but the only files
written are `srt_out` (repair.py:686), `rep_out` (repair.py:687, the repair.csv),
and `summary_out` (repair.py:698, the summary json). `conf_path` is never opened
for writing. `recreate_srt.py:22-29` reads conf.json to rebuild the srt the same
way. So [S-5]'s mechanism — rebuild the srt from conf.json with decisions applied
— is buildable: the PRE-repair text is still in conf.json when a `reject` verdict
needs to restore it. The spec's claim holds.

Both claims that "were exactly the shape that has been wrong before" are correct
this time. I checked them hardest and could not break them.

---

## Item 1 — The portability premise is unmeasured, and everything rests on it

**This is the review's highest priority. I am BLOCKING on this until it is
measured.**

### What the premise claims

`[S-2]` keys decisions on the normalised `(orig, proposed)` text pair "so they
survive a re-run and mean something in another library" (spec, In scope, [S-2]).
The spec's own Constraints section says: "Decisions must be portable. Card index
and episode number do not survive a `TEXT_VERSION` bump and mean nothing in
another user's library; the text pair does." The Edge cases section admits: "The
model's output changes, so `proposed` no longer matches. No match, falls through
to `accept_repair`."

The author flagged this as unmeasured (spec, Open questions — empty, but the
Edge cases entry is the tell) and did not measure it. The entire collaborative
goal — a downstream user pulling the maintainer's committed decisions and having
them apply — depends on the `orig` text recurring byte-identically (after
normalisation) across a model change, a `TRANSCRIBE_VERSION` bump, or a different
user's library.

### Why this is the shape that fails

This is a hypothesis-that-sounds-right recorded as a design invariant, which is
exactly the failure mode the prompt warned about (`[S-16]` coverage,
`[S-9]` scope narrowing, the Kanjuro three-wrong-explanations). The intuition is
"ASR is deterministic at temperature 0, so the same audio produces the same
text." But:

- `condition_on_previous_text=False` (generate.py:897, documented in the
  arc-scoped spec) means each segment is decoded cold. Whisper is not
  deterministic across segment boundaries, VAD settings, beam size, or compute
  type — all of which are `TRANSCRIBE_VERSION`-bumping changes per ADR 0001
  (`common.py` comment block at the `TRANSCRIBE_VERSION` definition).
- The measured 45-line review (`REVIEW-2026-08-27-unanchored-repair-45-lines.md`)
  shows `orig` text like `"running forever Let's go along with curiosity Our
  feelings lead"` — a run-together, unpunctuated Whisper output. A different
  decoder version, VAD threshold, or beam size will split segments differently,
  producing different card boundaries and therefore different `orig` strings.
  The card text is the JOINED output of per-segment decoding + reflow, not raw
  Whisper output, so even byte-identical segments can produce different cards if
  the split points move.
- The spec itself stores `orig` NORMALISED (lowercase, whitespace-collapsed,
  punctuation preserved). But `orig` comes from `conf.json`'s `text` field, which
  is already flattened by generate.py (replacing `\n` with ` `, per
  repair.py:680-684). A `TRANSCRIBE_VERSION` bump that changes word
  tokenisation or segment boundaries will produce a different flattened string.

### The experiment that settles this

Run the same episodes through two transcription configurations that differ in a
`TRANSCRIBE_VERSION`-bumping dimension and measure the pair-hit rate:

1. Take One Pace S31E01-E03 (already transcribed at the current
   `TRANSCRIBE_VERSION=4`).
2. Re-transcribe with a change that bumps `TRANSCRIBE_VERSION`: a different
   `WHISPER_MODEL`, a different `WHISPER_BEAM_SIZE`, or a different compute type.
   (The `WHISPER_MODEL` default change is explicitly out of scope for THIS spec
   but is the cheapest experimental lever.)
3. Run `repair.py` on both outputs with `REPAIR_UNANCHORED=1`.
4. For every `(orig_A, proposed_A)` pair accepted in arm A, check whether
   `decisions.lookup(store, orig_B, proposed_B)` hits in arm B, where the store
   is built from arm A's verdicts.

The hit rate is the portability number. If it is near zero, the store is
"a file only its author can use" and the collaborative goal is dead.

### My prediction

I predict the `orig` hit rate across a model change will be **40-70%**, not
near-zero and not near-100%. Here is my reasoning:

- The 45-line review shows that many `orig` strings are short, common English
  ("That come together.", "Roger's treasure belongs to me"). Short utterances
  are more stable across decoder changes than long run-together ones.
- But the run-together cards ("running forever Let's go along with curiosity Our
  feelings lead") are segmentation-dependent and will drift. Those are the ones
  most likely to need repair (they are the targets), so the hit rate on the
  REPAIRED subset will be lower than the hit rate on all cards.
- The `proposed` text comes from the LLM, which is temperature-0 but
  non-deterministic across backend, prompt, or model — and the spec's own
  arc-scoped spec documented that the repair prompt itself changed
  (`_glossary_terms` reordering, [S-13]). So even if `orig` matches, `proposed`
  may not.

A 40-70% hit rate means: roughly half the maintainer's committed decisions apply
to a downstream user's library, and the other half silently fall through to
`accept_repair`. That is not "portable." It is "partially portable," and the
spec does not say that.

### Does the design have a fallback?

Partially. The Edge cases entry says a no-match "degrades to today's behaviour
rather than misapplying a stale verdict." That is correct and safe — a miss is
a no-op, not a wrong application. But "safe no-op" is not the same as "portable."
If half the decisions miss, the downstream user gets half the maintainer's
curation and the other half of their episodes run ungated through
`accept_repair` — which is exactly the state the spec exists to prevent.

**The spec must either (a) measure this before shipping [S-2] as a
collaborative artifact, or (b) downgrade the portability claim from invariant to
aspirational and state the expected hit rate honestly.** I am blocking on (a)
or (b). The claim that the text pair "survives a re-run and means something in
another library" is unverified and is the foundation of every collaborative
item in the spec.

---

## Item 2 — `force` reintroduces the exact class the guards were built for

### The case against `force`

`force` lets a human override `invents_name` and `[S-15]`'s phonetic guard. Those
guards exist because of measured failures:

- `Oimo -> Zoro` in the bake-off (the reason `substitutes_a_vouched_name` exists,
  repair.py:393-431, docstring at :395).
- Hotwords turning `Kanjuro` into `Kanjudo` by listing a phonetically adjacent
  name (arc-scoped spec, [S-10] CUT, `RESULTS-2026-08-26-hotwords-full-episode.md`).

The spec's own verdict set (Data section) says `force` is for:
"`accept_repair` refused this repair and was wrong to; admit it." The reasoning
(spec, Data, decided 2026-08-27): "the gate provably errs in BOTH directions.
[S-14] and [S-15] blocked nothing across 21 repairs, and the 4 proposals the
gate did refuse have never been judged by anyone."

Here is the problem. The 4 refused proposals have never been judged — so the spec
is building an override for a case it has zero evidence about. The spec is saying
"the gate errs in both directions" when it has measured the gate erring in ONE
direction (admitting bad repairs) and ASSUMED it errs in the other (refusing good
ones). That is the hypothesis-as-fact pattern.

The human exercising `force` is reading TEXT in a web queue
(`review_server.py`, [S-7]). The stated bar (repair.py:318-320, accept_repair
docstring) is that "a dubtitle must carry what the DUB AUDIO says." The reviewer
is not listening to the dub audio. They are reading text on a screen and judging
whether a refused repair "looks right." That is exactly the failure mode that
produced `VIVRA -> Vivi`: the model proposed something that looks plausible
(both are character-adjacent) and a text-only reviewer cannot tell it is a
wrong referent without the audio.

`force` records distinctly from `accept` "so they can be counted" (spec, Data).
But counting is not auditing. A `force` verdict that ships a wrong repair on an
unanchored card — where the spec's own Problem section says "a regression shipped
there has no downstream repair path" — is permanent. The spec builds a permanent
override with no audio check, for a case it has not measured.

### The case for `force`

The other side is real. `accept_repair` is documented (repair.py:318-351) as
deliberately permissive for the case the reference exists to serve: "a single
misheard proper noun corrected from it." The gate's length-ratio band (0.6-1.5),
the ref-borrow cap (MAX_REF_BORROW=3), and the name guards are all mechanical
proxies for a semantic judgement they cannot make. A correct repair that the
gate refuses — say, a repair that shortens a name beyond the 0.6 ratio, or one
that borrows 4 reference words to fix a garbled 6-word line — is unreachable
without `force`. And on an unanchored card, nothing downstream can reach it
either (the spec's core Problem).

The 4 refused proposals (rejected_guard=4 in the measurement) carry
`proposed_text` in the unresolved queue (repair.py:536-542). They are visible to
the reviewer. A human reading the proposed text against the original CAN make a
better judgement than the gate — the gate cannot read, the human can. The
spec's argument that "making the human the authority in one direction only would
leave a correct repair the gate wrongly refused permanently unreachable" is
structurally sound.

### Which wins

**The case against wins, but only on the unanchored path.** The spec should
restrict `force` to cards that HAVE a fansub reference (`ref` is non-empty), and
should refuse it on unanchored cards. Here is why:

- On an anchored card, `force` overrides a gate that refused a repair backed by
  a reference. The reviewer can read the reference (it is in the queue entry,
  `unresolved._EVIDENCE["rejected_guard"]` includes `reference`), read the ASR
  text, and read the proposal. That is a meaningful judgement.
- On an unanchored card, `force` overrides `invents_name` and
  `substitutes_a_vouched_name` — the guards that exist specifically because
  glossary-only repair hallucinates (repair.py:162, skips_unanchored docstring:
  "the bake-off showed glossary-only repair hallucinates names (Oimo->Zoro) even
  on qwen3:8b"). The reviewer has no reference, no audio, and is overriding the
  exact guard that was built for this case. That is the failure.

**Evidence that would change my mind:** measure the 4 refused proposals from the
E01 run. If any of them is a correct repair the gate wrongly refused — a real
false negative, not just "the gate refused something" — then `force` on
unanchored cards is justified by evidence rather than assumed. The spec has not
done this. Until it does, `force` on unanchored cards is the gate being
overridden in the exact direction it was built to guard, by a reviewer who
cannot hear the audio.

**Verdict: NOTE, not block — IF `force` is restricted to anchored cards. If
`force` ships unmodified (applies to unanchored cards), BLOCK.** The spec does
not distinguish, which means it allows the dangerous case. Adding the `ref`
guard to `force` is a one-line change in the consult path and it eliminates the
failure mode without losing the anchored-card value.

---

## Item 3 — The queue asks two incompatible questions with one vocabulary

### The problem

`[S-1]` puts `repair_applied/accepted` entries ("was this repair right?") in the
same queue as `rejected_guard` entries ("was the GATE right?"). The verdict set
is: `accept / reject / correct / force`. One vocabulary, two question types.

On a `repair_applied/accepted` entry:
- `accept` = the repair was right, keep it.
- `reject` = the repair was wrong, restore ASR text.
- `correct` = neither was right, use my text.
- `force` = N/A (the repair was already applied; force is for refused repairs).

On a `rejected_guard` entry:
- `accept` = ...the gate was wrong? The repair should have been applied?
- `reject` = ...the gate was right? The proposal was bad?
- `correct` = ...use my text instead of the proposal?
- `force` = the gate was wrong, admit the proposal.

`reject` on a `rejected_guard` entry is ambiguous: it could mean "the gate was
right to refuse" (affirming the gate) or "the proposal was bad" (affirming the
proposal's wrongness, which is the same outcome but a different mental model).
The spec does not disambiguate.

### Is the data model coherent?

Partially. The ACTIONS are coherent even if the SEMANTICS are not:

- On an `accepted` entry, `reject` means "restore ASR text" — [S-4] and [S-5]
  both handle this.
- On a `rejected_guard` entry, `accept` means "apply the proposal the gate
  refused" — which is exactly what `force` does on an `accepted` entry. So
  `accept` on a `rejected_guard` entry and `force` on an `accepted` entry produce
  the same outcome: a repair the gate refused gets applied.

The spec has quietly merged two verdicts (`accept` on a refused entry == `force`
on an accepted entry) into one vocabulary, and the merge is invisible to the
reviewer. A reviewer looking at a `rejected_guard` entry and choosing `accept`
is performing a `force` without the distinct recording the spec says `force`
exists to provide ("Force verdicts are recorded distinctly from accept precisely
so they can be counted").

### Does this need two vocabularies?

The spec needs to either:

1. **Split the vocabularies.** `accepted` entries get `{accept, reject, correct}`.
   `rejected_guard` entries get `{admit, uphold, correct}`. `admit` is what
   `force` is on the other path; `uphold` is "the gate was right." This makes the
   counting the spec wants actually work — `force` verdicts on `accepted` entries
   are counted as `force`, and `admit` verdicts on `rejected_guard` entries are
   counted separately.
2. **Or: unify the queue entry type into the verdict.** Record
   `entry_type: "accepted" | "rejected_guard"` on each queue entry, and define
   the verdict semantics per entry type in the spec. The Data model already
   carries the stage/reason from `unresolved.record()`, so the entry type is
   implicit — but the spec does not say what each verdict MEANS per entry type.

**Verdict: NOTE.** This is a data-model coherence issue, not a correctness bug.
The actions are all buildable. But the spec's claim that `force` is "recorded
distinctly so they can be counted" is undermined by `accept` on a
`rejected_guard` entry being functionally identical to `force` on an `accepted`
entry, with no distinct recording. The spec should either split the vocabularies
or explicitly document that `accept` on `rejected_guard` IS the `force` count.

---

## Item 4 — `[S-6]` has no escape

### The problem

`[S-6]` gates mux for shows in `REVIEW_GATE_SHOWS`: `mux.py` skips any episode
with pending `repair_applied` entries. The spec's Failure modes section names
the exact failure: "a gate that silently holds every episode forever is the
failure to avoid; the pending check must be the only condition." And then does
not prevent it.

There is no timeout. No bypass. No alert. The human reviews in evening batches
(spec, Users: "Reviews in batches in the evening, not while the pipeline
runs"). After two weeks away, every episode of every gated show that produced
queue entries is held. The library falls behind the viewer.

### What is the state after two weeks away?

- Every episode with a pending `repair_applied` entry is un-muxed. Its subtitle
  sidecar (`.eng.dubtitles.srt` or `.ass`) exists but is not embedded.
- `mux.py:process()` (mux.py:196-198) checks `stamp_valid(read_stamp(stamp),
  orig)` and returns `"already-muxed"` — but the episode was never muxed because
  the gate held it, so there is no stamp. It would mux on the next pass IF the
  gate were not holding it.
- The gate is the ONLY condition (spec, Failure modes), so the episode stays
  held until its queue entries are resolved. Two weeks of episodes accumulate.
- `unresolved.record()` fires ~86x per episode (spec, Environment). Even if only
  `repair_applied/accepted` entries are gated (not `no_reference` or
  `llm_empty`), that is ~21 entries per episode (the E01 measurement) × 14 days
  × episodes per day. The queue grows unboundedly.

### Design the escape or argue the gate should not ship

The gate should ship, but with an escape. Three options, in order of
preference:

1. **A timeout with auto-accept.** An entry pending longer than
   `REVIEW_GATE_TIMEOUT` (default 7 days) is auto-resolved as `accept` (the
   repair ships as-is). This is the safe default: `accept_repair` already
   admitted the repair, so auto-accept is today's behaviour. The timeout means
   "if the human does not review in time, the pipeline proceeds as if the review
   subsystem did not exist" — which is exactly the pre-spec state. The escape
   degrades to today's behaviour, which is the spec's own stated principle for
   the consult path (Edge cases: "degrades to today's behaviour rather than
   misapplying a stale verdict").
2. **A stall alert.** `mux.py` logs a LOUD warning when it holds an episode for
   longer than the timeout, and the merge loop's summary includes the held
   count. This does not unblock the episode but makes the stall visible. The
   spec's `unresolved.py` contract is "observability that must never raise"
   (unresolved.py:6-8) — a stall alert is observability, not a failure.
3. **A bypass env var.** `REVIEW_GATE_BYPASS=1` skips the gate entirely,
   muxing everything. This is the manual escape for "I am going on vacation and
   the library must not fall behind." It is coarse but safe (it returns to
   today's behaviour).

**The spec has none of these.** The Failure modes section says the gate "must be
the only condition" and then does not add a time condition. That is the bug.

**Verdict: BLOCK.** A gate with no escape that holds episodes forever is the
exact failure the spec names and then does not prevent. Adding option 1
(auto-accept after timeout) is a small change to the `[S-6]` consult in `mux.py`
and eliminates the stall. Without it, a two-week absence produces a library
that cannot catch up without manual intervention on every held episode.

---

## Item 5 — `[S-7]`/`[S-8]` put an unauthenticated write endpoint inside a root container

### The problem

`container_run.sh` (line 1, the `set -u` and `exec sh /app/gen_loop.sh`) runs
as root — the spec says so (Problem section: "The container runs as root so
`generate.py` can chown sidecars"). `mux.py:process()` chowns the muxed file to
`MEDIA_UID`/`MEDIA_GID` (mux.py:242, `os.chown(out, ...)`), which requires root.

The spec adds `review_server.py` (stdlib `http.server`, [S-7]) as a third loop in
`container_run.sh` ([S-8]). Its write routes (`POST /decide`, `POST /apply/<stem>`)
rewrite subtitle files and trigger re-muxes. `REVIEW_TOKEN` is unset by default
and "LAN-only, documented" is the justification (spec, Out of scope: "Any
authentication stronger than a shared token").

### Is this defensible?

For the maintainer on his own LAN, yes. For downstream users who may use host
networking, no. Here is why:

- Docker host networking (`--network host`) puts the server on the host's
  network interface, not a bridge. `REVIEW_PORT=8842` is now reachable from
  anywhere the host is reachable. A downstream user who runs this container with
  host networking (common for media servers that need to see the host's
  filesystem) and does not set `REVIEW_TOKEN` has an unauthenticated write
  endpoint that can rewrite subtitle files and trigger re-muxes.
- `POST /apply/<stem>` invokes [S-5], which invalidates `.dubtitles.done` stamps
  and triggers re-muxing. That is a write to the media tree, performed as root.
  An unauthenticated POST can force the container to re-mux arbitrary episodes.
- The spec's reasoning ("requiring a token to approve a subtitle line on one's
  own LAN is the friction that stops the review happening at all") is about
  FRICTION, not security. The friction argument is valid for the maintainer. It
  is not valid for a downstream user whose container is on a network they do not
  fully control.

### What the default must be

`REVIEW_TOKEN` must default to REQUIRED, not unset. The spec should:

1. Generate a random token on first start (write it to `/config/review_token`
   if the env var is unset), and require it on every write route.
2. Print the token to the container log on startup so the maintainer can read
   it once and use it.
3. Document that `REVIEW_TOKEN=` (explicitly empty) disables auth, and that this
   is only safe on a fully isolated network.

This preserves the maintainer's workflow (read the token from the log once, use
it in the browser) and protects downstream users. The friction of pasting a
token into a browser is negligible; the friction of recovering from an
unauthenticated write to a media library is not.

**Verdict: BLOCK.** An unauthenticated write endpoint running as root, with a
default that is unsafe for host networking, is not defensible for software
intended to be run by downstream users. The fix (default to required, auto-
generate, print on startup) is small and does not change the maintainer's
workflow.

---

## Item 6 — Which acceptance criteria pass while the behaviour is broken?

There are 23 acceptance criteria. I examined each for the "trivially
satisfiable" or "proves the wrong thing" failure. The spec already suspects two
(empty store produces byte-identical output; `DECISIONS_APPLY=0` produces
byte-identical output). I found four more:

### a. "[S-1] An accepted repair writes one `repair_applied`/`accepted` entry
... the entry count equals the summary's `repaired` count for that episode."

This is trivially satisfiable by writing the entry AFTER `c["text"] = new`
(repair.py:549) unconditionally — i.e., writing the queue entry for every
accepted repair, which is exactly what the criterion asks. But it does not prove
the entry carries the right EVIDENCE. The criterion checks the COUNT, not the
FIELDS. A queue entry with `original_text=""` and `proposed_text=""` passes this
criterion. The criterion should assert the entry's `original_text` equals the
card's pre-repair text and `proposed_text` equals the applied text, not just
that the count matches.

### b. "[S-4] With a `reject` verdict stored for the pair, `repair.py` leaves
the card's ASR text unchanged and writes no `repair_applied` entry."

This proves the consult happens BEFORE the repair is applied. But it does not
prove the consult happens at the right MOMENT — specifically, after
`glossary.correct()` (spec, [S-4]: "after `glossary.correct()` and before
`accept_repair`"). If the consult happens BEFORE `glossary.correct()`, the `orig`
key is the pre-correction ASR text, not the post-correction text that
`accept_repair` sees. A `reject` verdict would then leave the PRE-correction text
in place, but `glossary.correct()` would still run and might change it — so the
card's text is NOT "unchanged." The criterion should assert the text equals the
POST-correction ASR text, and the spec should pin the consult point to a specific
line in `repair.process()`.

### c. "[S-5] `review_apply.py` on an episode with a stored `reject` rewrites
the `.srt` with the ASR text restored and invalidates the `.dubtitles.done`
stamp"

This proves the srt is rewritten. But `repair.py:process()` already rewrites
the srt from conf.json on every run (repair.py:685-689). So "rewrites the srt
with ASR text restored" is satisfiable by running `repair.py` again — the srt is
always rebuilt from conf.json, which holds the pre-repair text (verified, Claim
2). The criterion should assert that `review_apply.py` does this WITHOUT
re-running the LLM — i.e., that it rebuilds from conf.json directly (like
`recreate_srt.py:22-29`) rather than calling `repair.process()`. Otherwise the
criterion is satisfiable by re-running repair, which is not what [S-5] is for.

### d. "[S-7] `GET /ep/<stem>` returns the primary queue by default and the full
walk with `?all=1`"

This proves the server returns something. It does not prove the primary filter
is correct. The spec's [S-1] says `unresolved.pending()` "filtered to the primary
stages returns exactly the accepted repairs plus the guard rejections." But
`unresolved.pending()` (unresolved.py:73-74) returns ALL pending entries — it
does not filter by stage. The filtering is the spec's responsibility, and the
criterion does not test that the filter is `stage == "repair" and reason in
("accepted", "rejected_guard", "rejected_name_invented")`. A server that returns
all pending entries (including `no_reference` and `llm_empty`) passes "returns
the primary queue by default" if the test does not also assert that
`no_reference` entries are absent. The criterion should assert the absence of
non-primary reasons in the default view.

### e. The spec's own two suspects, confirmed

- "An empty store produces byte-identical output" — confirmed trivially
  satisfiable. If `decisions.lookup()` returns `None` for every pair (empty
  store), and the consult code is `if verdict: ... else: <today's path>`, then an
  empty store is a no-op. But the criterion does not prove the consult code is
  REACHED — a `return` before the consult point satisfies it. The criterion
  should assert the consult function is CALLED (e.g., via a mock or a counter),
  not just that the output is identical.
- "`DECISIONS_APPLY=0` produces byte-identical output" — confirmed. This proves
  the FLAG works, not that the flag is READ at the right moment. If
  `DECISIONS_APPLY` is checked once at import time and cached, and the consult
  code reads the cached value, the flag works. But if the flag is checked AFTER
  the consult (e.g., `if DECISIONS_APPLY: apply_verdict(verdict)`), then the
  consult still runs (wasting time) and the flag only gates the application, not
  the lookup. The criterion should assert that with `DECISIONS_APPLY=0`, the
  consult function is NOT called (or is called but its result is provably
  discarded before any branch).

**Verdict: NOTE.** These are test-quality issues, not design bugs. But the spec
should tighten them, because the pattern of "criterion passes while behaviour is
broken" is exactly what let the v3/v4 wrapping defect ship (the library had
zero multi-line cues and 25-32% of cues over 42 chars, per common.py's TEXT_VERSION
history). Each criterion above is satisfiable by an implementation that does not
do what the spec intends.

---

## Item 7 — Is the two-store split right, or does it just move the problem?

### The split

`[S-3]` promotes term-level verdicts into `hard_fixes` (show-wide, via
`glossary.correct()`), and leaves line-level verdicts in the decision store
(per-pair, consulted in `repair.py`). The spec's example (Data section):
`Samadai -> Samurai` is a term (promoted to `hard_fixes`), while
`factory -> needle` is a line (stays in the store).

### Who decides which a verdict is?

The spec does not say clearly. The Data section shows a `promoted` field on a
`correct` verdict, implying the human decides at review time. But the Interfaces
section says `record(store, orig, proposed, verdict, text="", note="",
promoted=None)` — the `promoted` argument is optional, defaulting to `None`.
The spec does not say:

- What happens if the human does not pass `promoted` on a verdict that IS a
  term-level fix (e.g., they `correct` `Samadai -> Samurai` with text
  `"Samurai"` but do not set `promoted`). The term is in the decision store as a
  line-level `correct`, applied only to that exact pair. It is NOT in
  `hard_fixes`, so `glossary.correct()` never sees it, and the next episode with
  `Samadai` gets no correction. The term is misfiled.
- What happens if the human passes `promoted` on a verdict that is NOT a term
  (e.g., they promote `factory -> needle` as a `hard_fix`). Now
  `glossary.correct()` replaces every `factory` with `needle` show-wide. That
  is the exact regression the decision store exists to catch, now applied
  everywhere.

### Is the classification decidable?

Partially. A term-level fix has a clear signature: the `orig` and `proposed`
differ in exactly one token, and that token is a proper noun or a known name.
The spec could auto-detect this: if `orig` and `proposed` differ in exactly one
`_TOKEN_RE`-matched core (glossary.py:147, `_TOKEN_RE`), and that core is in the
glossary's `names` or is non-English (`glossary.is_english`), the verdict is
term-level and should be promoted. Otherwise it is line-level.

But the `factory -> needle` case shows this is not always clear: `factory` and
`needle` are both ordinary English words, so the auto-detect would classify it
as line-level (correct). And `the flame flame fruit -> the Flame-Flame Fruit`
has multiple token differences (punctuation, capitalisation, and a deleted
word), so the auto-detect would also classify it as line-level (correct — it is
not a term-level fix, it is a line-level correction). The hard cases are the
ones where a single-token proper-noun substitution IS the fix (`Samadai ->
Samurai`), and those are auto-detectable.

### What happens to a verdict misfiled in either direction?

- **Term misfiled as line:** the fix applies to one pair only. The same
  mis-transcription on another episode's card does not get corrected. The
  decision store degrades to "a file only its author can use" for that term —
  which is the portability problem from Item 1, but self-inflicted.
- **Line misfiled as term:** the fix applies show-wide via
  `glossary.correct()`. A line-level `correct` that happens to share a token
  with another card now overwrites that card's text too. This is the more
  dangerous direction, because it is silent and show-wide.

**Verdict: NOTE.** The split is right in principle (term-level fixes belong in
the glossary, line-level fixes belong in the store), but the spec must either
(a) auto-classify based on the token-difference signature, or (b) make the
`promoted` argument REQUIRED and document its semantics explicitly. The current
design — `promoted=None` default, no classification rule — lets a human misfile
in either direction with no guard. The dangerous direction (line misfiled as
term) is silent and show-wide.

---

## Item 8 — What is missing from the spec entirely

### a. The `REPAIR_UNANCHORED` flip is load-bearing for THIS change

The spec says flipping `REPAIR_UNANCHORED` is "a separate decision, owned by the
maintainer" (Out of scope). But the spec's own Problem section says:
"`REPAIR_UNANCHORED` is the last gate holding back [S-12] of the arc-scoped
spec. Every card in One Pace S31 is unanchored (6,492 `no_reference`), so a
regression shipped there has no downstream repair path." And the spec's Users
section says the review loop exists to make regressions "correctable per line."

If `REPAIR_UNANCHORED` stays default-off (which it does today, repair.py:162:
`return not ref and not REPAIR_UNANCHORED`), then the 6,492 unanchored cards
produce ZERO `repair_applied` entries, ZERO queue entries, and ZERO decisions.
The review loop is built for a path that is not open. The spec's entire Problem
section — the 21 repairs, the 45 reviewed lines, the 80% pass rate — is about
UNANCHORED repairs. If the gate stays closed, the review loop has nothing to
review on the show that motivated it.

This is not "merely related." The spec builds the instrument that produces the
data for the `REPAIR_UNANCHORED` flip — but if the flip does not happen, the
instrument is inert on the show it was built for. The spec should either (a) flip
the default as part of this change (which the owner has deferred), or (b) state
explicitly that the review loop is inert on unanchored shows until the owner
flips the gate, and that the 45-line review was a one-off measurement, not a
recurring workflow.

### b. The `accept_repair` tightening is NOT load-bearing for THIS change

The spec says tightening `accept_repair` is "deferred by the owner pending more
human-reviewed data. This spec BUILDS the instrument that produces that data; it
does not change the gate." This is correct and not load-bearing. The review loop
works with the current gate; tightening it later changes which repairs are
queued, not how the queue is reviewed. This is genuinely out of scope.

### c. The `WHISPER_MODEL` default is NOT load-bearing for THIS change

The spec says changing the baked `WHISPER_MODEL` default "changes transcription
and therefore stales the `TRANSCRIBE_VERSION` tier per ADR 0001. Its own commit,
its own decision about re-transcription." This is correct. But it IS the cheapest
lever for the Item 1 portability experiment — re-transcribing with a different
model is the measurement that settles whether the text pair recurs. The spec
should note that the portability experiment (Item 1) and the `WHISPER_MODEL`
change are the same experiment, even though the spec change is separate.

### d. What is actually missing: the consult point is not pinned to a line

The spec says [S-4] consults the store "after `glossary.correct()` and before
`accept_repair`." Looking at `repair.process()` (repair.py:513-555):

```
new = llm(prompt)
if new:
    new = glossary.correct(new, gloss)[0]   # line 545-546
...
if not accept_repair(c["text"], new, ref, dur, gloss):   # line 551
    ...
else:
    audit.append(...)   # line 558
    c["text"] = new     # line 549 (actually before the audit append)
```

The consult must go between line 546 (after `glossary.correct()`) and line 551
(before `accept_repair`). But the spec does not pin it to a line, and the
`orig` text for the lookup must be `c["text"]` (the card's text BEFORE repair),
not `new` (the post-correction proposal). The spec's Data section stores `orig`
as the normalised pair key, but does not say whether `orig` is the pre- or
post-correction text. This matters: if `orig` is post-correction, then a
`glossary.correct()` change (e.g., a new `hard_fix`) invalidates every stored
`orig` key for episodes that go through that glossary. If `orig` is
pre-correction, it is stable across glossary changes (which is the point of
keying on text).

The spec should pin the consult point to a specific line range in
`repair.process()` and state that `orig` is the PRE-correction ASR text
(`c["text"]` before `glossary.correct()` runs). This is not in the spec and it
is load-bearing for the portability premise (Item 1) and the two-store split
(Item 7).

**Verdict: NOTE on (b) and (c) — genuinely out of scope. NOTE on (a) — the
`REPAIR_UNANCHORED` flip is not this spec's work but the spec must acknowledge
its review loop is inert on unanchored shows without it. BLOCK-strengthening on
(d) — the consult point and the `orig` keying are load-bearing and unspecified.**

---

## Summary of verdicts

### BLOCK (must fix before shipping)

1. **Item 1: Portability is unmeasured.** The text-pair keying is the foundation
   of the collaborative premise and has not been measured. Either measure the
   hit rate across a `TRANSCRIBE_VERSION` change, or downgrade the claim from
   invariant to aspirational and state the expected hit rate.
2. **Item 2 (conditional): `force` on unanchored cards.** If `force` ships
   without a `ref` guard, it overrides the exact guards built for the unanchored
   path, by a reviewer who cannot hear the audio. Restrict `force` to anchored
   cards, or measure the 4 refused proposals to prove the gate has false
   negatives.
3. **Item 4: `[S-6]` has no escape.** A gate with no timeout that holds episodes
   forever is the named failure. Add an auto-accept timeout (option 1) or a
   bypass.
4. **Item 5: `[S-7]`/`[S-8]` unauthenticated write as root.** `REVIEW_TOKEN`
   must default to required, auto-generate on first start, and print to the log.
   The current default (unset = no auth) is unsafe for host networking.

### NOTE (should fix, does not block)

5. **Item 3: One vocabulary for two question types.** Split the vocabularies or
   document that `accept` on `rejected_guard` IS the `force` count.
6. **Item 6: Four acceptance criteria are trivially satisfiable.** Tighten the
   criteria to test evidence fields, consult point, no-LLM rebuild, and primary
   filter absence.
7. **Item 7: The two-store split has no classification rule.** Auto-classify or
   make `promoted` required with documented semantics.
8. **Item 8(a): The review loop is inert on unanchored shows without the
   `REPAIR_UNANCHORED` flip.** Acknowledge this in the spec.
9. **Item 8(d): The consult point and `orig` keying are unspecified.** Pin to a
   line range and state that `orig` is pre-correction text.

### What I tried hardest to break and could not

- **The "no `TEXT_VERSION` bump needed" claim.** I traced `hard_fixes` through
  `glossary.load_dict()` → `token_fixes`/`phrase_fixes` → `glossary.correct()`,
  and confirmed `initial_prompt` is untouched. The GPU tier is not triggered.
  The claim holds.
- **The `[S-5]` rebuild-from-conf.json mechanism.** I confirmed `repair.py`
  never writes conf.json back. The pre-repair text is in conf.json. [S-5] is
  buildable as written.
- **The atomic write claim.** `unresolved._rewrite()` (unresolved.py:82-101)
  uses `tempfile.mkstemp` + `os.replace`, and the spec's `decisions.save()`
  mirrors it. The atomic-write claim is sound.
- **The never-fail-an-episode claim for the queue side.** `unresolved.record()`
  (unresolved.py:104-122) returns `bool` and catches `OSError`/`ValueError`. The
  queue side inherits this contract. The claim holds.

### Where I am speculating rather than reasoning from source

- The 40-70% portability hit rate prediction (Item 1) is speculation based on
  the character of Whisper output, not a measurement. I have flagged it as a
  prediction.
- The auto-classification signature for the two-store split (Item 7) is a design
  suggestion, not something I found in the source.
- The `force` restriction to anchored cards (Item 2) is a design argument, not a
  source-derived constraint.

---

## The architectural ladder

The maintainer's standing default is: deterministic rules first, LLM only for
what rules cannot settle, human only for what the LLM cannot — each layer
recording why it escalated.

This spec implements the human rung correctly: it records what the LLM settled
(`repair_applied/accepted`), what the LLM could not settle
(`rejected_guard`), and lets the human override both. That is the ladder
working as designed.

But the spec violates the ladder in one place: **`force` on unanchored cards
skips the LLM rung's own guards.** The ladder is rules → LLM → human. The LLM
rung has guards (`invents_name`, `substitutes_a_vouched_name`) that are the LLM
rung's own quality boundary. `force` lets the human override those guards —
which is the human rung reaching BELOW the LLM rung to undo its safety, not
reaching ABOVE it to settle what the LLM could not. That is the ladder inverted.
On anchored cards, the human is settling what the LLM could not (was the repair
right?); on unanchored cards, the human is undoing what the LLM's guards
decided (was the guard right to refuse?), with no audio and no reference. The
former is the ladder working; the latter is the ladder broken.

---

## Rebuttal of my own findings

I wrote the review above in the register the prompt demands — refute, don't
validate. But a review that cannot rebut itself is not evidence either; it is
the same coin flipped once. Below I argue the strongest counter to each of my
own BLOCKs and NOTEs, from the source, and then say whether the rebuttal
survives contact with the code I read this session.

### Rebutting Item 1 (portability is unmeasured — BLOCK)

**The counter-argument:** I demanded a measurement I myself have not run, and
blocked on it, while the spec already contains the measurement's answer in its
Edge cases. The spec says: "The model's output changes, so `proposed` no longer
matches. No match, falls through to `accept_repair`. Degrades to today's
behaviour rather than misapplying a stale verdict." That is a safety claim,
not a portability claim, and I conflated them. The spec does not say the store
is portable; it says a MISS IS SAFE. The portability claim lives in the
Constraints section ("the text pair does"), but the collaborative goal lives
in the Users section, and the Users section describes the downstream user as
phase 2, out of scope: "(phase 2, out of scope here) contributes decisions
back." The contribution channel is explicitly out of scope (spec, Out of
scope, first bullet). So the collaborative premise I called "dead on arrival"
is not the premise this spec ships — it is a future premise this spec does not
claim to serve.

Furthermore, the 45-line review (REVIEW-2026-08-27-unanchored-repair-45-lines.md)
shows that the SAME repair targets recur ACROSS EPISODES within the same season:
"That come together." appears in E01, E02, and E03 with the same fix. "Roger's
Treasure belongs to me" appears in all three. The `orig` text recurs
byte-identically across episodes of the SAME transcription run, because the
same audio (the opening theme) produces the same Whisper output. That is not
portability across a model change, but it IS portability across episodes —
which is the maintainer's actual workflow: review once, apply show-wide. The
spec's Edge case "The same line appears on several cards" explicitly designs
for this. So the store has a real, measured use case (show-wide recurrence)
even if the cross-model use case is unmeasured.

Finally, the `REPAIR_UNANCHORED` flip is out of scope, which means the
unanchored path is not open yet. The store ships BEFORE the path it serves.
That means the store can accumulate decisions from ANCHORED repairs first —
where `orig` comes from conf.json, which is stable across a `TEXT_VERSION` bump
(the srt is rebuilt from conf.json on every repair run, repair.py:685-689, and
conf.json is never rewritten, verified in my Claim 2). So the FIRST decisions
in the store are from anchored cards, where the portability question is
narrower: `orig` is the pre-repair ASR text, which only changes on a
`TRANSCRIBE_VERSION` bump, not a `TEXT_VERSION` bump. The spec can ship the
store, accumulate anchored decisions, and measure the portability question on
real data before the unanchored path opens.

**Does the rebuttal survive?** Partially. The distinction between "safe miss"
and "portable" is real and I under-weighted it — the spec's safety claim is
sound. The show-wide recurrence argument is strong: the 45-line review proves
the same `orig` text recurs across episodes, and one verdict settling multiple
cards is a real, immediate value that does not depend on cross-model
portability. And the contribution channel being out of scope means the
collaborative premise is not what this spec ships.

But: the spec's Constraints section says "Decisions must be portable" — that is
a stated invariant, not a future aspiration. And the spec's S-9 item says the
format is "a plain per-show JSON file so a network fetcher can later sit behind
`decisions.load()`" — that is designing for the collaborative case now. So the
spec IS making a portability claim, not just a safety claim. The rebuttal
weakens my BLOCK but does not eliminate it: the spec should either measure the
cross-model hit rate or downgrade the Constraints claim from "must be
portable" to "must degrade safely on a miss," which is what the Edge cases
actually deliver. **My BLOCK on Item 1 should be a NOTE with a required
measurement before the contribution channel (phase 2) opens, not before THIS
spec ships.** The store is safe to ship; the portability claim is what needs
downgrading.

### Rebutting Item 2 (force on unanchored cards — conditional BLOCK)

**The counter-argument:** I argued that `force` on unanchored cards overrides
the exact guards built for that path, by a reviewer who cannot hear the audio.
But the reviewer ALREADY cannot hear the audio on `accept` verdicts for
unanchored cards — `accept_repair` admits the repair and the human's `accept`
verdict confirms it, all without audio. If the audio absence is disqualifying
for `force`, it is equally disqualifying for `accept`, and the entire review
loop is invalid on unanchored cards. But the spec's Problem section says the
45-line review — which was done WITHOUT audio, by reading text — is the
enforcement mechanism. The owner's bar (arc-scoped spec, "What counts as an
acceptable repair") is explicitly text-based: "A deviation that still carries
the same meaning is acceptable; one that changes the meaning is not." The owner
judged `factory -> needle` as a regression by READING THE TEXT, not by listening
to the audio. So the audio-absence argument proves too much: it would invalidate
the entire review loop, not just `force`.

Furthermore, the guards I said `force` overrides are the same guards the
spec's own measurement proved are INERT on this sample. The unanchored
measurement (RESULTS-2026-08-26-unanchored-repair.md) says: "Both guards --
known->known refusal, and phonetic proximity on the unknown->known path -- were
enabled and produced a set BYTE-IDENTICAL to ungated. Zero regressions
prevented, zero fixes lost." So `force` overrides guards that blocked nothing.
The guards are insurance against `Oimo -> Zoro`, which did not recur in this
sample. If `force` is used on a card where `Oimo -> Zoro` would have been the
result, the reviewer reading the text CAN see that `Zoro` is a different name
than `Oimo` — that is a text-readable judgement, not an audio judgement. The
spec's own review of the 45 lines caught `VIVRA -> Vivi` and `factory -> needle`
by reading text, not audio.

And my proposed restriction (force only on anchored cards) creates the exact
asymmetry the spec argues against: a correct repair the gate wrongly refused on
an unanchored card is permanently unreachable, while the same refusal on an
anchored card can be forced. The spec's reasoning is: "on an unanchored card,
nothing downstream can reach it either." So the unanchored case is where `force`
matters MOST, not least — it is the only escape hatch for a correct repair the
gate refused on a card with no other recovery path.

**Does the rebuttal survive?** Yes, on the audio argument. I over-argued: the
owner's bar is text-based, the 45-line review was text-based, and `accept` on
unanchored cards is also audio-free. The audio absence is not specific to
`force`; it is the design of the review loop. If the audio absence
invalidates `force`, it invalidates `accept` too, and I did not call for
blocking `accept`.

But: the guards-are-inert argument has a weakness. The guards blocked nothing in
a 21-repair sample, but the spec's own arc-scoped spec says they are "insurance
against a documented prior failure that did not recur in this sample, not an
observed improvement." Insurance that has not paid out is not insurance that
never will. `force` removes the insurance permanently for the pair it is applied
to. The rebuttal weakens my conditional BLOCK but does not eliminate it: the
strongest remaining argument is not about audio but about the permanence. A
`force` verdict is `run: "review"` and mirrors R4 (glossary_acquire.py:700-716):
it is never reverted by an automated sweep. So a wrong `force` is permanent on
an unanchored card. That is the real risk, and it is not addressed by the
rebuttal. **My conditional BLOCK should become a NOTE: the audio argument was
wrong, but the permanence argument stands. The spec should document that a
`force` verdict on an unanchored card is irreversible and has no recovery path,
so the reviewer knows the stakes.**

### Rebutting Item 3 (one vocabulary for two questions — NOTE)

**The counter-argument:** I said `accept` on a `rejected_guard` entry is
functionally identical to `force` on an `accepted` entry, undermining the
distinct recording. But the spec's Data model stores the verdict on the
DECISION, not on the QUEUE ENTRY. The queue entry carries `stage`/`reason` from
`unresolved.record()` (unresolved.py:44-50, the REASONS dict). The decision
store carries `verdict` on the `(orig, proposed)` pair (spec, Data section).
So the entry type and the verdict are in DIFFERENT stores. A `reject` on a
`rejected_guard` entry resolves the QUEUE entry (it stops appearing in
`pending()`). The corresponding DECISION — if the reviewer also records one —
is a separate action via `POST /decide` (spec, review_server.py interfaces).
The spec's `POST /decide` takes `{stem, index, verdict, text?, note?}` — the
`index` is the queue index, the `verdict` is the decision. So one POST both
resolves the queue entry AND records the decision. The entry type is implicit
in the queue entry's `reason` field, and the decision's `verdict` field is what
gets counted. So `accept` on a `rejected_guard` entry records a decision with
`verdict: "accept"` for a pair the gate refused. `force` on an `accepted`
entry records a decision with `verdict: "force"` for a pair the gate admitted.
These ARE distinct in the decision store, because the `verdict` field differs.

My confusion was between the queue entry's resolution and the decision's
verdict. They are not the same thing: resolving a queue entry is
`unresolved.resolve(stem, index, accept, note)` (unresolved.py:104-113), which
sets `resolved: True, accepted: bool`. Recording a decision is
`decisions.record(store, orig, proposed, verdict, ...)`. The spec's server does
both in one POST, but they are separate calls into separate stores. The
verdict vocabulary applies to the DECISION store, not the queue resolution. So
the counting the spec wants (`force` verdicts counted distinctly) works,
because the decision store's `verdict` field is what carries the `force` label.

**Does the rebuttal survive?** Yes. I made a category error: I conflated the
queue entry's `accepted` boolean (unresolved.py:108) with the decision store's
`verdict` string. They are different fields in different stores. The spec's
server calls both, but the counting is on the decision store's `verdict` field,
which does carry `force` distinctly from `accept`. So the spec's claim that
"force verdicts are recorded distinctly so they can be counted" is correct —
the distinct recording is in the decision store, not the queue entry. **My NOTE
on Item 3 should be withdrawn, or reduced to: document that the verdict is on
the decision, not the queue entry, so an implementer does not conflate them as I
did.**

### Rebutting Item 4 ([S-6] has no escape — BLOCK)

**The counter-argument:** I said a gate with no timeout holds episodes forever.
But the spec says `REVIEW_GATE_SHOWS` defaults to `""` (spec, Environment).
The gate is OPT-IN: a show must be explicitly named in the env var for the gate
to hold anything. The spec's Users section says: "never require attention on
shows he has not opted into gating." So the gate only holds episodes of shows
the maintainer EXPLICITLY named. If the maintainer names a show and goes on
vacation for two weeks, that is the maintainer's choice, not the spec's failure.
The spec cannot prevent the operator from opting into a gate and then not
reviewing — that is a human workflow issue, not a design defect.

Furthermore, the spec's Failure modes section says: "A gate that silently holds
every episode of a show forever is the failure to avoid; the pending check must
be the only condition." I read this as the spec naming the failure and not
preventing it. But the sentence says the pending check must be the ONLY
CONDITION — meaning the gate must not also check for a timeout, a file age, or
any other heuristic, because those would introduce false positives (an episode
held by a timeout that fired too early, or an episode released by a file-age
check before the human reviewed it). The spec is saying: the gate should hold
exactly when there are pending entries, and release exactly when there are not.
Adding a timeout introduces a path where the gate releases WITHOUT the human
reviewing — which is the pre-spec state (the repair ships without review). The
spec's Problem section says that is the exact state the spec exists to prevent.
So my proposed escape (auto-accept after timeout) undoes the spec's purpose.

The spec's Users section says the maintainer "Reviews in batches in the
 evening, not while the pipeline runs." That is a workflow, not a 24/7 SLA. If
the maintainer is away for two weeks, the held episodes simply wait — they are
not lost, not muxed wrong, and not shipped. The sidecars exist; the stamps are
not written. When the maintainer returns and reviews, the episodes mux. The
library falls behind the viewer for those episodes — which is the CORRECT
behaviour for a gated show: better behind than shipping unreviewed repairs.

**Does the rebuttal survive?** Yes, on the opt-in argument. The gate is
opt-in (`REVIEW_GATE_SHOWS` defaults to `""`), so it only holds what the
maintainer explicitly gated. That is not the spec holding episodes forever; that
is the maintainer choosing to gate and then not reviewing. The spec cannot
prevent that.

But: the spec's own Failure modes section names the failure and then says "the
pending check must be the only condition." I read that as "the spec does not
prevent the failure." The rebuttal reads it as "the spec deliberately does not
add other conditions, because other conditions introduce false release paths."
That is a stronger reading, and it is consistent with the spec's stated purpose
(holding is the point, releasing without review is the failure). My proposed
timeout would release without review — which is the pre-spec state the spec
exists to prevent. **My BLOCK on Item 4 should become a NOTE: the gate is
opt-in, the stall is the maintainer's workflow choice, and an auto-accept
timeout would undo the spec's purpose. The spec should document that the gate
holds until reviewed and that going on vacation while a show is gated will hold
episodes — but that is documentation, not a design fix.**

### Rebutting Item 5 (unauthenticated write as root — BLOCK)

**The counter-argument:** I said `REVIEW_TOKEN` defaulting to unset is unsafe for
host networking. But the spec's Out of scope section says: "Decided with the
owner 2026-08-27: `REVIEW_TOKEN` unset means no auth, which is the LAN default."
The spec's Users section lists the downstream user as someone who "Runs the
container, gets the maintainer's committed decisions applied automatically,
reviews nothing, configures nothing, and never sees this subsystem." So the
downstream user who is NOT reviewing does not need the server at all — the
server is for the maintainer and the downstream user who opts into reviewing.
The spec's `review_server.py` is a third loop in `container_run.sh` ([S-8]),
but its failure must not take down the container. If a downstream user does not
set `REVIEW_TOKEN` and does not use the server, the server is running but idle.

The host-networking risk I raised is real in general, but this container
already runs as root with access to the entire media tree — the review server's
write routes are a strictly smaller attack surface than `generate.py`'s chown
operations, `mux.py`'s atomic replace of mkv files, and `repair.py`'s srt
writes, all of which already run as root and are triggered by the merge and
generate loops. An attacker who can reach the container's filesystem can already
do anything. The review server adds an HTTP write endpoint, but the container's
security model is already "if you can reach the container, you can write to the
media tree." The spec's security posture is: this is a LAN application, the
container is not internet-facing, and the root requirement is documented and
load-bearing (for chown). Adding auth to the review server while leaving the
rest of the container's root access open is perimeter security on one door of a
tent.

Furthermore, the spec's reasoning is: "requiring a token to approve a subtitle
line on one's own LAN is the friction that stops the review happening at all --
which is the failure this entire spec exists to prevent." The spec's Problem
section says the human review is the ONLY enforcement of the acceptance bar. If
the token stops the review, the acceptance bar is unenforced. So the token is
not a security-vs-convenience tradeoff; it is a security-vs-CORRECTNESS tradeoff,
where the correctness side is the entire reason the spec exists.

**Does the rebuttal survive?** Partially, on the relative-risk argument. The
container already runs as root with filesystem access; the review server's
write routes are a smaller surface than what already exists. And the
friction-vs-correctness argument is real: if the token stops the review, the
spec's purpose is defeated.

But: the relative-risk argument proves too much. It would justify any
unauthenticated endpoint on any root container. The point of `REVIEW_TOKEN` is
not to protect against an attacker who has already compromised the container —
it is to protect against an unauthenticated write from a network neighbour who
has NOT compromised the container but CAN reach port 8842. Host networking
makes that possible. The container running as root is load-bearing (chown);
the review server running without a token is not load-bearing in the same way —
the maintainer can paste a token. My proposed fix (auto-generate, print to log)
preserves the maintainer's workflow (read the log once) and protects the
downstream user. **My BLOCK on Item 5 stands, but should acknowledge the
relative-risk argument: the fix is defense-in-depth, not a new perimeter. The
spec should default `REVIEW_TOKEN` to required and auto-generate, but the
rebuttal correctly identifies that this is a smaller surface than what already
exists, so the urgency is lower than I stated.**

### Rebutting Item 6 (trivially satisfiable criteria — NOTE)

**The counter-argument:** I said four criteria are trivially satisfiable. But
the spec's acceptance criteria are not the implementation's test suite — they
are the spec's acceptance CONTRACT, verified by `procoder test` green and
`procoder check` with zero blocking findings (spec, final criterion). The
criteria describe what the implementation must do; the TEST SUITE verifies it.
A criterion that says "the entry count equals the summary's `repaired` count"
is satisfiable by a bad implementation, but the test suite would also test that
the entry's fields are correct — because the spec's [S-1] item says the entry
carries `original_text`, `proposed_text` and `avg_logprob`, and the criterion
says "carrying `original_text`, `proposed_text` and `avg_logprob`" in its first
line. I quoted the second sentence (the count check) and ignored the first
sentence (the fields check). The criterion IS two-part: it checks the fields
AND the count. A bad implementation that writes empty fields passes the count
but fails the fields check, because the criterion says "carrying
`original_text`, `proposed_text` and `avg_logprob`."

Similarly, the [S-4] criterion I said does not prove the consult point is at
the right moment: the spec's [S-4] item says "after `glossary.correct()` and
before `accept_repair`." The criterion says "`repair.py` leaves the card's ASR
text unchanged." If the consult is before `glossary.correct()`, then
`glossary.correct()` runs after the consult and may change the text, so the
card's text is NOT unchanged — and the criterion fails. So the criterion DOES
test the consult point, indirectly: it can only pass if the consult is after
`glossary.correct()` (so no further correction changes the text) and before the
repair is applied (so the ASR text is what remains). My argument that the
criterion is satisfiable by a wrong consult point was wrong: the criterion's
"leaves the card's ASR text unchanged" is only true if the consult is at the
right point.

**Does the rebuttal survive?** Yes, on criteria (a) and (b). I cherry-picked
the second sentence of criterion (a) and ignored the first, and I missed that
criterion (b)'s "unchanged" is only satisfiable at the right consult point. The
criteria are better than I said.

But: criteria (c) and (d) still stand. Criterion (c) is satisfiable by
re-running `repair.py`, and criterion (d) does not assert the ABSENCE of
non-primary reasons in the default view. So the rebuttal weakens (a) and (b)
but leaves (c) and (d). **My NOTE on Item 6 should be reduced: criteria (a) and
(b) are better than I said; criteria (c) and (d) still have the gaps I
identified.**

### Rebutting Item 7 (two-store split has no classification rule — NOTE)

**The counter-argument:** I said the spec does not say who decides whether a
verdict is term-level or line-level, and that `promoted=None` is a silent
misfiling risk. But the spec's Data section shows `promoted` as a field on the
DECISION, not a parameter the human passes blindly. The example decision has
`"promoted": { "hard_fix": { "Samadai": "Samurai" } }`. The spec's [S-3] says:
"Where a decision's lesson is a TERM (`Samadai -> Samurai`) rather than a line,
write it to `hard_fixes` so it applies show-wide through `glossary.correct()`."
So the classification IS stated: if the lesson is a term, promote it. The
human decides whether the lesson is a term — just as the human decides whether
the verdict is `accept`, `reject`, `correct`, or `force`. The spec does not
auto-classify because the classification is a JUDGEMENT, and the spec's
architectural ladder puts judgements at the human rung.

My proposed auto-classification (one-token difference + proper noun) would
misclassify the word-deletion regression (`the flame flame fruit -> the flame
fruit`), which has multiple token differences but is a LINE-level correction.
It would also misclassify `factory -> needle`, which is one token but is NOT a
term — it is a meaning change. So auto-classification would make the exact
mistakes I warned about: misfiling in both directions. The human is better at
this than a heuristic, because the human can read the text and tell whether
`Samadai -> Samurai` is a term (same referent, different spelling) or
`factory -> needle` is a meaning change (different referent). That is the same
judgement the human makes for the verdict itself.

Furthermore, `glossary_acquire.py`'s `record_decision` (glossary_acquire.py:728-770)
already has the pattern: a human accepts a term via `--review`, and the term is
written to `hard_fixes` with `run: "review"`. The spec's [S-3] mirrors this
exactly. The `promoted` field is not a new classification mechanism; it is a
RECORD of what the human promoted, so the decision store and the glossary stay
in sync. The spec does not need auto-classification because the human IS the
classifier, and the `promoted` field is the audit trail of what they decided.

**Does the rebuttal survive?** Yes. My auto-classification proposal was a
design suggestion, not a source-derived requirement, and I flagged it as such.
The rebuttal correctly identifies that auto-classification would misclassify the
exact cases the spec is about. The `promoted` field is an audit trail, not a
classification rule, and the human is the classifier — which is consistent with
the architectural ladder. The spec's silence on "who decides" is not a gap; it
is the same delegation-to-human that the verdict itself uses. **My NOTE on Item
7 should be reduced: the classification is a human judgement, not a missing rule.
The spec should document that `promoted` is set by the human at review time and
is an audit trail, but the design is sound.**

### Rebutting Item 8(a) (REPAIR_UNANCHORED is load-bearing — NOTE)

**The counter-argument:** I said the review loop is inert on unanchored shows
without the `REPAIR_UNANCHORED` flip, so the spec builds an instrument for a
path that is not open. But the spec's Problem section says: "Building the loop
first makes it correctable per line." The spec is explicitly BUILDING BEFORE
OPENING. That is the spec's stated purpose: the review loop must exist BEFORE
`REPAIR_UNANCHORED` is flipped, because flipping it without the loop makes each
regression permanent (spec, Problem: "Opening that gate without a review loop
makes each regression permanent. Building the loop first makes it correctable
per line."). So the instrument is not inert; it is a PRECONDITION for the flip.
The spec's build order is: build the loop (this spec), then flip the gate
(owner's separate decision). The loop is not built for a path that is not open;
it is built so that the path CAN be opened safely.

Furthermore, the review loop is NOT inert on anchored shows. `accept_repair`
admits anchored repairs today, and those repairs are queued by [S-1] and
reviewed by [S-7]. The 45-line review was unanchored, but the spec's [S-1] says
"Add stage `repair_applied`, reason `accepted`, recorded on the success path
alongside the existing `audit.append`." That success path fires for EVERY
accepted repair, anchored or not. So the review loop has work to do on anchored
shows from day one — the same `accept_repair` that admits `Dothamingo ->
Doflamingo` on an anchored card also admits it on an unanchored card once the
gate opens. The loop is not waiting for the flip; it is running on anchored
repairs now.

**Does the rebuttal survive?** Yes. I under-read the spec's build-order
argument. The spec explicitly says the loop is a precondition for the flip, not
a consequence of it. And the loop does have work on anchored shows — I focused on
the unanchored measurement (the 45 lines) and missed that `accept_repair` admits
anchored repairs too, which the loop would queue. **My NOTE on Item 8(a) should be
withdrawn: the spec's build order is correct (loop first, then flip), and the
loop is not inert on anchored shows.**

### Rebutting Item 8(d) (consult point and orig keying unspecified — NOTE)

**The counter-argument:** I said the spec does not pin the consult point to a
line and does not say whether `orig` is pre- or post-correction. But the spec's
[S-4] says: "Consult the store inside `repair.py`, after `glossary.correct()`
and before `accept_repair`." That IS the pin: between `glossary.correct()`
(repair.py:646, `new = glossary.correct(new, gloss)[0]`) and `accept_repair`
(repair.py:651, `if not accept_repair(...)`). The spec does not give a line
number, but it names the two functions that bracket the consult, and those
functions are in the source I read. The consult point is pinned to a
four-line gap in `repair.process()`.

On the `orig` keying: the spec's Data section says `orig` and `proposed` are
"stored normalised (they are the key)." The spec's [S-4] says a `reject`
verdict "keeps the ASR text." The ASR text is `c["text"]` — the card's text
before the LLM proposal. The LLM proposal is `new` (after `glossary.correct()`).
So `orig` in the pair is the ASR text (`c["text"]`), and `proposed` is the
corrected LLM output (`new`). The spec does not say this in so many words, but
it is the only reading consistent with "a `reject` verdict keeps the ASR text" —
if `orig` were the post-correction text, a `reject` would keep something other
than the ASR text.

And the spec's acceptance criteria for [S-2] test the keying: `lookup()` on a
store built from a recorded verdict returns that verdict for the same pair. The
pair is `(orig, proposed)`, and the criterion says `None` for a pair differing
only in `proposed`. So the `orig` is part of the key and is stable. Whether it
is pre- or post-correction is an implementation detail, but the spec's
`samadai -> samadai` example (Data section) shows `orig` as the ASR text
(`"i relied on the brave assistance of my fellow samadai,"`) — lowercase,
unpunctuated — which is the pre-correction ASR text, not the post-correction
text (which would be `"Samadai"` capitalised by `glossary.correct()` if it were
in the glossary, which it is not yet). So the example demonstrates that `orig`
is pre-correction.

**Does the rebuttal survive?** Yes. The spec pins the consult point by naming
the bracketing functions, and the example in the Data section demonstrates that
`orig` is pre-correction ASR text. I demanded line numbers and an explicit
statement where the spec provided function names and a worked example. The spec
does not need to say `repair.py:647`; it says "after `glossary.correct()` and
before `accept_repair`," and those are the two functions at lines 646 and 651.
**My NOTE on Item 8(d) should be reduced: the consult point is pinned by
function name, and `orig` is demonstrated as pre-correction by the spec's own
example. The spec could be more explicit, but the information is there.**

### Net effect of the rebuttals

Of my four BLOCKs:

1. **Item 1 (portability):** Reduced to NOTE. The spec's safety claim (miss is
   a no-op) is sound. The collaborative premise is phase 2, out of scope. The
   store has immediate value on show-wide recurrence (measured in the 45-line
   review). The portability claim in Constraints should be downgraded, but the
   store is safe to ship.
2. **Item 2 (force on unanchored):** Reduced to NOTE. The audio argument was
   wrong — the owner's bar is text-based and the entire review loop is
   audio-free. The permanence argument stands: a wrong `force` on an unanchored
   card is irreversible. The spec should document the stakes, not restrict the
   feature.
3. **Item 4 (no escape):** Reduced to NOTE. The gate is opt-in. An auto-accept
   timeout would undo the spec's purpose (releasing without review is the
   failure the spec exists to prevent). The stall is the maintainer's workflow
   choice. The spec should document the hold behaviour, not add an escape.
4. **Item 5 (unauthenticated write):** BLOCK stands but with reduced urgency.
   The relative-risk argument is valid (the container is already root with
   filesystem access). The fix (auto-generate token, default to required) is
   defense-in-depth, not a new perimeter. But the host-networking risk is real
   and the fix is cheap.

Of my five NOTEs:

5. **Item 3 (one vocabulary):** Withdrawn. I conflated the queue entry's
   `accepted` boolean with the decision store's `verdict` string. They are
   different fields in different stores. The counting works.
6. **Item 6 (trivially satisfiable):** Reduced — criteria (a) and (b) are
   better than I said; (c) and (d) still have gaps.
7. **Item 7 (two-store split):** Reduced. The classification is a human
   judgement, not a missing rule. Auto-classification would misclassify the
   exact cases the spec is about.
8. **Item 8(a) (REPAIR_UNANCHORED):** Withdrawn. The spec's build order is
   correct (loop first, then flip). The loop has work on anchored shows from
   day one.
9. **Item 8(d) (consult point):** Reduced. The consult point is pinned by
   function name, and `orig` is demonstrated as pre-correction by the spec's
   own example.

**Net: one BLOCK stands (Item 5, with reduced urgency), three BLOCKs are
reduced to NOTEs, two NOTEs are withdrawn, three NOTEs are reduced.** The spec
is stronger than my initial review made it sound. The rebuttal did not change
my mind on Item 5 (the host-networking risk is real and the fix is cheap), but
it changed my mind on Items 1, 2, 3, 4, 7, 8(a), and 8(d). The strongest thing
I tried to break and could not — the two verified claims — remained unbroken
through the rebuttal. The spec's design is sound on the points I attacked
hardest; the remaining work is documentation, not architecture.
