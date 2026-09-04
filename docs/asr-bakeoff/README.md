# ASR bakeoff — measured results

Per-entrant results from `tools/asr_bakeoff.py`, run 2026-09-04 on two cards. The narrative
— which model wins, why each failure is a hardware ceiling or an environment bug — is
[Choosing an ASR model](../wiki/Choosing-an-ASR-Model.md). These files are the numbers behind it.

| File                | Card                         |
| ------------------- | ---------------------------- |
| `gtx1060-6gb.json`  | GTX 1060, 6 GB, Pascal       |
| `rtx2070s-8gb.json` | RTX 2070 Super, 8 GB, Turing |

**Metrics only.** The harness also emits every entrant's full transcript (`texts`, `words`,
per-episode `text`) — that is a commercial dub's script, so it is stripped before the report
enters this repository, along with the release tags in each episode filename. `wer_vs_ref`,
`peak_vram_mib`, `load_s`, `wall_s` and the confidence distributions are what the write-up
cites, and they are all kept. Re-run the harness locally if you need the transcripts.
