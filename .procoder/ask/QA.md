# Questions procoder cannot answer for you

Written 2026-09-02 22:55 UTC.

Answer each one by writing a line beginning `Answer: ` under it, then
hand the file back with `procoder ask --file .procoder/ask/QA.md`.
Leave the `Key:` lines alone — they are what ties an answer to its question.

## Q1: [lint] pool-dedup-hash.py:107

Key: 12e96403baaf
Question: W292 [*] No newline at end of file (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: added the trailing newline. (Owner decision 2026-09-02 -- the file is scratch tooling for an unrelated mergerfs pool-dedup task that happens to live in this repo root, and it was blocking every commit.)

## Q2: [lint] pool-dedup-hash.py:40

Key: fe94be41da80
Question: E741 Ambiguous variable name: `l` (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: `l` -> `line` in the comprehension at pool-dedup-hash.py:40. Minimal rename, the author's structure untouched.

## Q3: [lint] pool-dedup-hash.py:56

Key: f6179790a81d
Question: B007 Loop control variable `size` not used within loop body (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Worth fixing. Real finding, fixed: `size` -> `_size` at pool-dedup-hash.py:56 -- the loop body uses only `group`. Renamed rather than rewritten to `by_size.values()`, to keep the diff minimal on someone else's in-progress file.
