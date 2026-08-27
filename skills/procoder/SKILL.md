---
name: procoder
description: >-
  Work like a senior developer in a repository governed by procoder: run the
  commit gate before calling anything done, format and lint through the
  binary, and drive the spec, plan, todo, backlog, and sprint chain in
  .procoder/. Use this skill when the repository contains a .procoder/
  directory or an AGENTS.md naming procoder, or when the user asks to run the
  gate, check formatting, open a spec or plan, close a task, or prepare a
  release.
license: Apache-2.0
metadata:
  category: development
  author: pascal-watteel
---

# Crush notes — this repo

No repo-specific escalation rules here — the global tiering in
`~/.config/crush/CRUSH.md` applies as-is: local nanbeige by default,
judgment-based escalation to Devstral or Claude Code depending on what the
task actually needs, chaining Devstral -> Claude only on an actual failure
(not as a default strategy).

If this repo turns out to need its own rules (unusual stakes, conventions
that bite, a deploy model like the docker repo has), add them here.
