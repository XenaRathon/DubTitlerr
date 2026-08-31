# Why it works this way

Understanding-oriented. Nothing here is a step to follow; it is the reasoning behind
choices that otherwise look arbitrary, or look like bugs.

If you want to _do_ something, see [How-to guides](How-To-Guides). If you want a value
looked up, see [Reference](Reference).

---

## What a dubtitle is, and why it cannot be a fansub

A dubtitle is a subtitle that carries **what the English dub audio actually says**.

That sounds obvious until you hold it next to the alternative. Most anime releases already
ship an English subtitle track: a translation of the _Japanese_ audio, written by a fansub
group or a licensor. It is usually excellent prose. It is also a **different translation of
the same scene** — different word choices, different sentence breaks, often a different
register, and sometimes a different meaning where the dub script was rewritten for lip
flap.

So a dubtitle cannot be produced by taking the existing subtitle track and re-timing it.
That produces a subtitle that reads beautifully and is wrong against the sound. This is the
worst failure mode available here, because it does not look like an error. A viewer reading
along has no way to notice.

Everything downstream follows from that single constraint. The transcript comes from the
dub audio and nothing else. The existing subtitle track, where one exists, is used only as
a _reference_ — never as a source.

---

## Anchored and unanchored repair

Speech recognition is good at English sentences and bad at invented proper nouns. It will
hear `Doflamingo` and write `Dothamingo`. No amount of audio quality fixes this: the word
is not in any dictionary the model has.

So a repair stage takes the low-confidence and name-suspect lines and asks a small language
model to fix them. That model needs to know what it is allowed to write.

**Anchored repair** happens when your copy of the episode carries an English subtitle track
for the Japanese audio. The repair model gets the overlapping reference line as context. It
can see that the scene involves a character called Doflamingo, and correct the name without
inventing anything.

**Unanchored repair** happens when there is no such track — a dub-only release. The model
gets only the show's glossary. This is more dangerous, and the danger is measured, not
theoretical: on an earlier model, glossary-only repair turned `Oimo` into `Zoro`. A
confident, fluent, entirely fabricated name.

### Why the default is off, and why you may still want it on

Because unanchored repair can fabricate, it is **off by default**. But leaving it off is not
free either. Measured on One Pace S31E01: 161 lines were refused for want of an anchor and 0
were repaired. That season carries 6,492 such lines. Among them was `Dothamingo`, which the
deterministic glossary matcher cannot reach either — too far from `Doflamingo` by edit
distance, and phonetically distinct under Metaphone. Nothing in the pipeline could fix it.

Re-running those 161 lines with the gate open produced 21 repairs, 18 of them acceptable,
including `Dothamingo` → `Doflamingo`.

That is one episode, of one show, on one model. Not enough to flip a default. Enough to make
the choice yours.

### Why it is declared per show, not globally

Originally this was a single environment variable. That turned out to be a trap.

The One Pace library was produced with the flag hand-set in a shell. **Nothing committed
recorded that.** A later merge pass, run from the committed scripts with no hand-set
environment, therefore skipped every line for want of an anchor — and then rebuilt the
subtitle from the raw transcript **over the top of the shipped repairs.** Reproduced on
S31E24: 144 targets, 0 repaired, 144 skipped, and a season's worth of corrections silently
reverted to raw speech recognition.

The setting now lives in the show's glossary file, which is a committed artifact. A show
that declares nothing behaves exactly as it did before. And a run that would skip _every_
line on an episode that already has repairs now refuses that episode and says so, rather
than quietly overwriting it.

The question the setting answers is one you can answer about your own library without
knowing any of the above: **does your copy of this show have English subtitles for the
Japanese audio?** If no, unanchored repair is what you want.

---

## Why the repair stage rejects so much

The repair model proposes a line. A gate decides whether to write it.

The standard the gate is trying to enforce is **same referent, same sense** — not
word-for-word fidelity. Shortening `Hawkeye Dracule Mihawk` to `Mihawk` is fine: same
character, same information. Changing `factory` to `needle` is not. Changing `VIVRA card` to
`Vivi card` swaps an item for a character.

**The gate cannot tell those apart.** Its checks are mechanical — length ratio, does it fit
the card's timing, how many words were lifted from the reference, does it invent a name that
is not in the glossary. Both bad examples above pass every one of them.

This is stated plainly rather than hidden because it determines what the human review stage
is _for_. The mechanical gate removes the obviously wrong. A person removes the plausibly
wrong. There is no third thing.

### The reference-borrowing check

The most common way a repair goes wrong is not fabrication — it is the model quietly
copying the reference translation instead of correcting the transcript.

Measured across every repair the library had accumulated: one model imported reference
wording in **84.1%** of its repairs, a quarter of them importing three or more words.
`That's enough of that, idiots!` became `Hold it, you brats!` — the reference, verbatim, and
not what the dub says.

The old gate was a length band, which a same-length rewrite passes without slowing down. The
check now counts words taken from the reference.

### Why a repair that does not fit is rejected rather than accommodated

A card's timing comes from the spoken onset in the dub audio. It is not adjustable at repair
time. If a corrected line does not fit the card it is correcting — too many characters for
the seconds available — the repair is refused.

The alternative would be to move or extend the card, which desynchronises it from the audio
to make room for text. That trades a visible problem for an invisible one.

This has a consequence worth knowing: **some genuinely correct repairs are refused for want
of room.** Splitting a card so a longer correction fits is a known gap, deliberately out of
scope for the beta.

---

## What "reviewed" claims, and what it does not

The review stage does not present you with the whole episode. It presents the lines the
pipeline was **unsure about** — low confidence, or suspected of containing a mangled name.

So when an episode is described as reviewed, the claim is precisely:

> Every line the pipeline flagged as uncertain has been read and judged by a human.

It is **not** a claim that the episode was proofread. The lines the pipeline was confident
about were never shown to anyone, and some of them are wrong.

This distinction is why verdicts are stored the way they are.

### Why verdicts are keyed on text, not position

A decision records the pair `(original text, proposed text)`, normalised — never the
episode and line number.

Position is fragile. It does not survive a re-transcription, and it means nothing in
somebody else's library where the same show is a different encode. The text survives both.

It also pays for itself: `Roger's treasure belongs to me` occurs in three consecutive
episodes with an identical mis-transcription. One verdict settles all three. In a season
with heavy catchphrase repetition this is the difference between a reviewable workload and
an unreviewable one.

The trade is that a verdict is show-wide. Judging a line in one episode judges it
everywhere in that show. That is intended — it is the same line — but it means the review
page shows you which other episodes a verdict will touch before you make it.

### Why punctuation is part of a line's identity

Verdict matching folds away case and whitespace, but **keeps punctuation**.

Restoring punctuation is most of what the repair stage does, so punctuation is signal, not
noise. `CP-0.` and `CP?` are a real transcript/proposal pair; the owner rejected that
repair. If punctuation were folded, the rejection would match — and suppress — the very text
it was rejecting in favour of.

The one exception is the apostrophe. `'` and `'` are two renderings of one character, and
English dub dialogue is mostly contractions, so this is not an edge case but the majority of
lines.

---

## Why saving a verdict does not change the video

The review page has two buttons, deliberately.

**Save verdicts** is cheap. It records your judgement and changes what the next repair run
ships for those lines.

**Apply decisions to this episode** rewrites the subtitle, drops the completion stamp, and
lets the merge loop re-mux the file. On a multi-gigabyte MKV that is not something to do
every time a reviewer scrolls halfway down a list and closes the tab.

One button for both would trigger a full re-mux on every partial pass through an episode.
So there are two, and the page says which does what.

The consequence: **an episode you have already reviewed and muxed does not update itself.**
Nothing re-opens it. If you want your verdicts in the video, press the second button.

---

## Why One Pace is the only supported configuration

The code is general. It has no One Pace special cases.

But "general" and "validated" are different claims, and only one of them is honest here.
One Pace is what the pipeline has been measured against, episode by episode, for months. It
is the show whose glossary is complete, whose failure modes are catalogued, and whose output
has been watched.

Other shows work. They are also where the bugs are found — the audio-offset defect that
shifted every cue in an episode was found on Sword Art Online, not One Pace. That is why
this version emits loud, non-fatal warnings when it meets a configuration it has not been
validated on, formatted so you can paste them into an issue.

Point it at your library. Expect to file something.
