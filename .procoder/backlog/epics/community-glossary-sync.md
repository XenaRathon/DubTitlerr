# Community glossary repo: download and upload from the app

Status: roadmap, target v1.0.0 or a later 1.x release (user, 2026-10-15). Design not decided.

## Today

The shared repo is XenaRathon/DubTitlerr-glossaries. Installing it is a manual `git clone` into
`GLOSSARY_DIR` and `git pull` to update (README Roadmap, "Community glossary repo").

## Wanted

- **[C-1]** Download: fetch a show's glossary (or updates to it) from the community repo, from the
  web UI and/or on startup.
- **[C-2]** Upload: submit a mined or hand-curated glossary back to the repo.
- **[C-3]** Work out exactly how it works before building (user: "work out exactly how that works").

## Open questions for the design

- Upload path: GitHub pull request (needs a GitHub token or a fork flow) vs a relay service.
- Merge with local edits: a downloaded glossary must not overwrite local hand fixes, verified/flagged
  terms or a user-set wiki; per-key merge rules needed (the acquire-apply bug that deleted curated
  hard fixes is the cautionary case).
- Trust: reviewing community submissions, and refusing unsafe content (wiki URLs go through the same
  private-host refusal as the Glossary page).
- Which fields are shareable (names, hard_fixes, wiki, wiki_scope) and which stay local (verified,
  flagged, caches, journals).
