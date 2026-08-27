# What a human decided

Written 2026-08-24 21:52 UTC. procoder reads this
file to avoid asking a question twice; edit an answer here to change what
it believes. Reword the question and it will be asked again.

## (no longer asked)

Key: e3fd390c66c2
Question: I001 [*] Import block is un-sorted or un-formatted (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Not a false positive — fixed. It was whitespace alignment around the `# noqa: E402` comment, not actual import reordering (verified with `ruff check --diff --select I001`). Applied via `procoder format`.
