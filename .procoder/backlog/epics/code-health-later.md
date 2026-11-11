# Code Health: Deferred Items

Status: roadmap, not started
Created: 2026-11-05

## Description

This epic tracks deferred code health items and cleanup tasks for future sprints (after the Runs work).

## Deferred Items

- **Env-parsing helpers:** Currently four variants exist (`repair.py:135`, `mine_glossary.py:199`, `glossary_decision.py:119/132`). Bare `int()` at import is used in `generate.py:122-126`, `review_server.py:77/102/109/140`. `WHISPER_BEAM_SIZE` is parsed three times (`generate.py:161/442/989`).
- **Splitting `repair._process_episode`:** The function is too large and needs splitting (`repair.py:1408-1931`).
- **Dead code:** Remove unused functions `_common_pairs` (`tools/glossary_score.py:450`) and `_review` (`tools/glossary_score.py:953`). Remove test-only dead code: `tools/bakeoff.py:827`, `tools/glossary_doctor.py:76`.
- **Duplicate duration probes:** Consolidate duplicate probing logic (`generate.py:253`, `mux.py:147`, `mux.py:248`, `tools/export_subtitles.py:99`, `tools/export_reviewed.py:21`).
- **English-stream filters:** Consolidate stream filtering logic (`generate.py:241`, `mine_glossary.py:131`, `review_server.py:938`).
- **Jev tier-C adjudicator bake-off:** Described in `docs/IMPROVEMENTS.md:297+`.
