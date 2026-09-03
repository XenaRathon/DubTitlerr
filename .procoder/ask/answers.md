# What a human decided

Written 2026-09-03 01:49 UTC. procoder reads this
file to avoid asking a question twice; edit an answer here to change what
it believes. Reword the question and it will be asked again.

## (no longer asked)

Key: 12e96403baaf
Question: W292 [*] No newline at end of file (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: added the trailing newline. (Owner decision 2026-09-02 -- the file is scratch tooling for an unrelated mergerfs pool-dedup task that happens to live in this repo root, and it was blocking every commit.)

## (no longer asked)

Key: e3fd390c66c2
Question: I001 [*] Import block is un-sorted or un-formatted (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Not a false positive — fixed. It was whitespace alignment around the `# noqa: E402` comment, not actual import reordering (verified with `ruff check --diff --select I001`). Applied via `procoder format`.

## (no longer asked)

Key: f6179790a81d
Question: B007 Loop control variable `size` not used within loop body (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: `size` -> `_size` at pool-dedup-hash.py:56 -- the loop body uses only `group`. Renamed rather than rewritten to `by_size.values()`, to keep the diff minimal on someone else's in-progress file.

## (no longer asked)

Key: fe94be41da80
Question: E741 Ambiguous variable name: `l` (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: `l` -> `line` in the comprehension at pool-dedup-hash.py:40. Minimal rename, the author's structure untouched.
