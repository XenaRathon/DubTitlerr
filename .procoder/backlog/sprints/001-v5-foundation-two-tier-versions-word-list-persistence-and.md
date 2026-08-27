# v5 foundation: two-tier versions, word-list persistence, and the two independent guards

Status: closed 2026-08-25
Created: 2026-08-24

## Goal

At the end of this sprint a change that alters only what a caption says costs CPU
minutes instead of GPU hours, and the pipeline records which of the two tiers an
episode is behind on rather than invalidating the whole library on any change.

Concretely: the 576 episodes currently stamped v4 are recognised as
transcribe-fresh and text-stale, so adopting the new scheme migrates them at
watch-gated pace instead of re-transcribing them; the word list survives a run, so
a punctuation or reflow change can replay on CPU; and two defects that need no
part of that machinery — sidecars orphaned by external renames, and two stages
trusting a word timestamp already proven implausible — stop being live.

Deliberately excluded: the model bake-off and the library sweep. Both depend on
hardware time rather than on this code, and a sprint that cannot close until a GPU
finishes is a sprint that reports "in progress" indefinitely. They are the next
sprint, and nothing here depends on them.

## Result

committed: 11
done: 10 (20260824-a-cached-re-run-invokes-no-whisper-model-runs-no, 20260824-a-glossary-edit-that-changes-only-hard-fixes-leaves-initial, 20260824-a-sweep-whose-stale-population-is-text-only-completes, 20260824-a-v4-stamp-version-4-parses-reports-both-tiers-as-4-and, 20260824-bumping-text-version-alone-leaves-stale-tiers-free-of, 20260824-dry-run-reports-for-all-46-size-matched-orphans-whether, 20260824-on-a-2-word-card-with-source-end-source-start-max-dur, 20260824-on-an-episode-where-clamp-to-segments-actually-moved-at, 20260824-the-swap-plan-states-the-move-as-completed-and-verified, 20260824-words-json-is-written-through-out-for-and-found-by-the-read)
carried: 1 (20260824-per-tier-stale-counts-appear-in-lastrun-json-and-are-non)

## Retro

Written 2026-08-27, reconstructed from the sprint's own artifacts -- the carried story's
carry reason and Evidence section, and the 24 commits between `4d1f0ed` and `c01a94c`.
Late, which is itself the first finding: the next sprint could not open until it existed.

**What slowed us down.** One story of eleven -- `per-tier stale counts appear in
lastrun.json` -- stalled on evidence rather than on code. Its second half demanded a LIVE
observation (bump `TEXT_VERSION` on a pinned show, sweep, see `words_reused > 0`), and
production was deliberately stopped and staying stopped until the week's changes were
committed. The fixture half was green. The story was carried rather than closed, on the
grounds recorded at carry time: "a fixture proves ordering but never proves anything
drains" is precisely what that story existed to guard, so closing on fixtures would have
closed it against its own purpose. The delay was not the stoppage. It was that the
criterion had been written as though "live" meant "the live library", when what it
actually needed was a real stamp in a real code path -- which turned out to be reachable
without production at all.

**What we change next sprint because of it.** Any criterion demanding live evidence names
the smallest reproduction that is still real, at the moment it is written, not at the
moment it blocks. The resolution here was one COPIED episode in an isolated tree -- and it
produced better evidence than a library sweep would have: `transcribe_stale=0 text_stale=1`,
`words_reused: 1`, and generate's own log confirming no Whisper model was ever constructed.
Had that scope been written into the criterion up front, nothing would have been carried.
The repair-review epic inherits this directly: its `[S-5]` and `[S-6]` stories assert on
what a call did NOT do -- the LLM never invoked, the held episode still not muxed -- which
is observable on a fixture without needing the pipeline running.

**One adaptation worth keeping.** The stamp was AGED to `text_version=4` -- the real state
of all 576 live episodes -- instead of patching `TEXT_VERSION` down in the working tree.
Editing the constant under test would have manufactured the condition the test was meant to
find in the wild; aging the artifact reproduced the actual one. Keep the rule: when a test
needs the library's current state, move the artifact to meet the code, never the code to
meet the artifact.
