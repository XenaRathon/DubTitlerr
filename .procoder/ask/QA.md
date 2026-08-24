# Questions procoder cannot answer for you

Written 2026-08-24 14:55 UTC.

Answer each one by writing a line beginning `Answer: ` under it, then
hand the file back with `procoder ask --file .procoder/ask/QA.md`.
Leave the `Key:` lines alone — they are what ties an answer to its question.

## Q1: [lint] tools/reapply_glossary.py:57

Key: e3fd390c66c2
Question: I001 [*] Import block is un-sorted or un-formatted (lint) — is this finding worth fixing here, or a false positive to be explained?
Answer: Not a false positive — fixed. It was whitespace alignment around the `# noqa: E402` comment, not actual import reordering (verified with `ruff check --diff --select I001`). Applied via `procoder format`.
