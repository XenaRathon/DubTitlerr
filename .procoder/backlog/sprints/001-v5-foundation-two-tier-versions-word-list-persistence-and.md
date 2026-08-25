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

<!-- What slowed us down this sprint. -->

<!-- What we change next sprint because of it. -->

<!-- One adaptation from this sprint worth keeping. -->
