# Re-run a show that already ran (Runs page)

Status: roadmap (user, 2026-10-15). Not scheduled.

## Problem

A show that has already been processed is skipped, because its episodes carry done stamps. During
development, and after a new version changes the output, the user wants to run it again from the
Runs page. Today that needs hand edits on the server (renaming the done request, clearing stamps).

## Wanted

- **[R-1]** Queueing a request for a show (or season) that already ran shows a confirmation:
  "This has already run. Run it again?" with Run again / Cancel. The cancel path protects a user
  who forgot it had run.
- **[R-2]** Run again makes the pipeline actually redo the work, by invalidating whatever it uses to
  skip done episodes (the done stamps, or a forced-version marker on the request), scoped to the
  request's show and season filter only.
- **[R-3]** The confirmation says what ran before (when, which version) so the choice is informed.

## Notes

- Decide at build time: clear the stamps vs a per-request `force` flag the worker honours. A force
  flag is safer (no stamp files deleted, nothing outside the scope touched).
- A stamp-version bump (TRANSCRIBE_VERSION / TEXT_VERSION) already re-runs everything library-wide;
  this item is the per-show, on-demand version.
- Related: LIBRARY_SWEEP (queued-only runs), request season filter (5c09f6f).
