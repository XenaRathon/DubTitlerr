# v5 foundation: two-tier versions, word-list persistence, and the two independent guards

Status: active
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
