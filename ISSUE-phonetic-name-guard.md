## Problem

After the prompt restructure (`a4f7dd2`), `qwen3.5:9b` no longer pastes glossary names over correct text — but it still **invents phonetic names**, which prompt tuning has not fixed.

Measured on One Pace S29E08, 40 repair targets, temperature 0:

```
ORIG: You're about to be a big, beautiful corpse, Syrahose!
 NEW: You're about to be a big, beautiful corpse, Shyarros!        <- invented

ORIG: Van Der Decken is going to capture my precious Syrahose!
 NEW: Van Der Decken is going to capture my precious Shirahoshi!   <- correct

ORIG: Just let me go after Deccan.
 NEW: Just let me go after Decman.                                 <- invented

ORIG: I can't let that beast catch Hirohoshi.
 NEW: I can't let that beast catch Hihohi.                         <- mangled to nonsense

ORIG: Garnus, too far away to tell Is something wrong?
 NEW: Garnel, too far away to tell if something wrong?             <- invented
```

The first two are the clearest signal: **the identical token `Syrahose` gets two different answers in the same episode** — once right (`Shirahoshi`, a real character) and once wrong. So the model is guessing phonetically per-call, not recognising anything.

`Hirohoshi -> Hihohi` is the worst case: it destroyed a name that was already close to correct and produced a non-word.

## Why prompt tuning won't finish this

Three prompt variants were measured (see `a4f7dd2` for the full write-up):

| approach                                                                    | result                                           |
| --------------------------------------------------------------------------- | ------------------------------------------------ |
| restate "never replace a name" more forcefully                              | no effect — the old prompt already said it       |
| remove the glossary from the prompt entirely                                | 42% -> 38%; the name list is not the trigger     |
| verification-only framing + worked examples + nothing trailing the ASR line | 42% -> 25%, glossary-name fabrication eliminated |

The third shipped. The residue above is what survives it. Further wording changes trade one failure for another: the same prompt applied to `nanbeige4.2-3b` drove it to **1 edit across 120 targets** — an inert no-op that also loses its genuine repairs.

## Proposed fix: a deterministic post-LLM guard

Validate the model's output rather than asking it more nicely. Reject an edit when it changes a capitalised token to something that is **neither** in the glossary **nor** within a small edit distance of the original:

- `Syrahose -> Shirahoshi` — in glossary → **accept**
- `Syrahose -> Shyarros` — not in glossary, edit distance far → **reject, keep original**
- `Deccan -> Decman` — not in glossary → **reject**
- `Hirohoshi -> Hihohi` — not in glossary → **reject**
- `zolo -> Zoro` — in glossary → **accept**

This is testable without a GPU, deterministic, and independent of which model is in use — unlike prompt wording, which we now have evidence is model-specific.

`jellyfish` is already a dependency (used by the phonetic-match tests), so metaphone/Jaro-Winkler are available for the distance check.

## Notes

- Non-name edits (punctuation, casing, `human -centric` -> `human-centric`) should pass through untouched; the guard should only police capitalised tokens.
- `glossary.name_suspect()` and the existing phonetic helpers are the natural place to look first for reuse.
- Worth re-running the three-show comparison after the guard lands to quantify the remaining error rate.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
