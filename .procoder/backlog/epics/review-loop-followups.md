# review-loop-followups

Status: done 2026-08-27
Created: 2026-08-27

## Why

The pre-merge adversarial round on `feat/phonetic-name-guard` — Luna's review and GLM 5.3
Flash's rebuttal of it, both under `docs/Adversarial Reviews/` — produced one gating fix
(landed in `3bd20a4`) and a short list of things deliberately deferred past the merge.

This epic is that list, and nothing else. Everything here is either a real behavioural gap
that does not change shipped subtitles today, or a test for a path both reviewers agreed was
unexercised. Two of the four test follow-ups GLM named were already covered while fixing the
gating item and are NOT repeated here:

- `decisions.save()` succeeds and `unresolved.resolve()` fails →
  `test_decide_reports_a_failed_resolve_instead_of_claiming_success`
- a non-constant offered value through `render_page` →
  `test_an_offered_verdict_is_encoded_for_the_javascript_context`

## Scope

- **[F-1]** A `--review` CLI verdict never reaches the decision store, so a human's
  "needs fixing" is silently dropped on the next run.
- **[F-2]** A changed proposal for the same original line creates a competing pending entry;
  settling one does not settle the other.
- **[F-3]** The write-back × `no-signs` / `empty` / `build-error` path is untested.
- **[F-4]** The review server bounds request TIME but not concurrent connections.

## Out of scope

The claims both reviews raised and the rebuttal rejected on the trace — Finding 4's "held
forever" and Finding 5's "signs silently absent" — are not reopened here. `mux.held_for_review`
makes the durable verdict the hold's authority, and `merge_pass.sh` re-runs repair on every
write-back pass. Reopening them would be re-litigating a settled trace.
