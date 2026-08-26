# A/B results — does `initial_prompt` affect name recognition?

Measured 2026-08-26 on VM102 (GTX 1050 Ti 4 GB), One Pace S31E01–E03 (Dressrosa arc).

## Result

**No. Two sharply different prompts produced word-identical transcripts, and every one of
15 arc names appeared the same number of times in both arms.**

## Method

Both arms ran `generate.py` over the SAME three episode files, copied to local disk (the
NFS mount was reading at 4.5 MB/s and caused `generate.py:246`'s hard-coded
`timeout=600` ffmpeg extraction to fail in the library). Identical model
(`large-v3-turbo`, int8), beam, audio filter, and identical glossary `names` (92) and
`hard_fixes` (77). Hardlinked media, so both arms decoded byte-identical audio.

**The prompt was the only variable.** Verified per episode: each arm's `words.json`
recorded a different `initial_prompt` string.

    arm A   the live glossary prompt — Enies Lobby / Water 7 cast:
            Spandam, Lucci, Kaku, Kalifa, Blueno, Jabra, Kumadori, Fukurou, Iceburg,
            Aokiji, Sengoku, Garp, Cipher Pol, CP9, Buster Call, Enies Lobby, Water 7,
            Ohara, Pluton, Going Merry  (~120 tokens)

    arm B   a Dressrosa-arc prompt built from the wiki, 47 terms at 222 of 223 tokens:
            ... Caesar Clown, Sugar, Mera Mera no Mi, Chinjao, Gladius, Cavendish,
            Kin'emon, Bellamy, Trebol, Viola, Riku Doldo III, Diamante, Sabo, Bartolomeo,
            Straw Hat Pirates, Corrida Colosseum, Pica, Kyros, Roronoa Zoro, Rebecca,
            Dressrosa, Trafalgar D. Water Law, Donquixote Doflamingo, + the crew

## Word-level comparison

Card text, lowercased, punctuation stripped, compared as token sequences. Punctuation is
excluded deliberately: `punctuation.py` calls an LLM (`punctuation.restore` at
`generate.py:941`, before `write_words` at `:949`), so punctuation differs between any two
runs regardless of prompt. An index-aligned card diff mistakes one segmentation change for
ten differences; this does not.

    episode    cards A   cards B   word similarity   differing runs
    S31E01         586       586            0.9984                2
    S31E02         393       389            0.9991                1
    S31E03         500       496            0.9984                2

    total word tokens   A = 10,487   B = 10,459
    total differing runs across three episodes: 5

All five differences are hallucination-gate artifacts, not decoder differences:

    A[so let s wake up wake up wake up wake up] -> B[]      (E01, opening theme repetition)
    A[now what]                                -> B[]      (E01, duplicated line)
    A[karoo karoo oh huh] -> B[grrgrrgrrrrrrghhh...]        (E02, non-speech noise)
    A[so let s wake up wake up wake up wake up] -> B[]      (E03, opening theme repetition)
    A[pipsqueak]                               -> B[]      (E03)

## Arc-name recall — the measurement that matters

Arm B's prompt named every term below. Arm A's named none of them.

    term            A      B
    Dressrosa      12     12
    Doflamingo      7      7
    Rebecca         2      2
    Corrida         1      1
    Colosseum       3      3
    Bartolomeo      4      4
    Cavendish       3      3
    Sabo            1      1
    Diamante        5      5
    Bellamy         1      1
    Caesar          7      7
    Law             8      8
    Sugar           1      1
    Green Bit       3      3
    Kin            28     28

**Arc terms whose count differs between arms: 0 of 15.**

Conversely, none of arm A's Enies Lobby names (Spandam, Lucci, Kaku, Kalifa, Blueno,
Jabra, Iceburg, Enies, Ohara, Pluton, Merry) appeared in EITHER transcript. The wrong-arc
prompt did not inject wrong names.

## The mechanism — stated carefully, after one correction

`generate.py:890` passes `condition_on_previous_text=False`.
`faster_whisper/transcribe.py:1372-1383` then sets `prompt_reset_since = len(all_tokens)`
when that flag is False, so `previous_tokens = all_tokens[prompt_reset_since:]` (`:1187`)
is empty after the first window. **Direct** priming from `initial_prompt` is therefore
confined to the first window of the audio.

**CORRECTION.** An earlier version of this document claimed the prompt's EFFECTS are
confined there too. That is wrong, and the clip spike below refutes it: with
`initial_prompt` set, `Mihawk` was fixed at 46.3 s and `Dressrosa` at 53.0 s of a 180 s
clip — past the first window. The route is indirect: the prompt changed SEGMENTATION in the
first window (one long run at 45.1 s became separate segments at 46.3 s and 53.0 s), which
shifts where later windows begin and therefore what they decode. Direct priming is
first-window-only; consequences cascade.

That cascade is why the two results are consistent rather than contradictory. On a clip
starting at 600 s the first window is dialogue, so there is something for the prompt to
change and the cascade starts. On a real episode the first window is the OPENING THEME —
sung, no character names — so nothing is primed, nothing cascades, and three full episodes
show zero name differences.

`condition_on_previous_text` cannot simply be flipped back: `generate.py:897` records that
`True` OOMs the card, measured 2026-08-20 on a 6 GB 1060 with the GPU otherwise idle. This
box has 4 GB.

## Spike: does `hotwords` do what `initial_prompt` cannot?

`transcribe.py:1542` is `if previous_tokens or (hotwords and not prefix):` — so `hotwords`
applies on EVERY window, including those where `previous_tokens` is empty. faster-whisper
1.2.1 exposes it as a public `transcribe()` argument (`:296`, `:788`). The pipeline does not
use it.

Probe: S31E01, a 180 s clip from 600 s, so the known mishear at 657.3 s sits ~57 s in —
well past the first window. Three arms, identical settings otherwise, 12 arc terms.

    arm                        target phrase at 57.2s                       vram     time
    A  no prompt, no hotwords  "Don Quixote do Flamingo."                 923 MiB   18.3s
    B  initial_prompt = terms  "Don Quixote do Flamingo."                 923 MiB   18.0s
    C  hotwords = terms        "Don Quixote Doflamingo"                   923 MiB   18.1s

    determinism: arm C run twice -> word similarity 1.0000, 0 differing runs

**`hotwords` fixed the name that `initial_prompt` could not**, at a position past the first
window, with no measurable VRAM or time cost at 12 terms.

### But it is not free

Comparing A against C at word level, 10 differing runs. One is the fix. One is a
REGRESSION:

    A:  "the genius jester, Bucky."     <- correct (Buggy the Clown is a jester)
    C:  "The Genius Dester, Bucky"      <- "Dester" is not a word or a name

`hotwords` biased the decoder toward name-shaped tokens and corrupted a correct English
word into a capitalised non-word. That token would then read as a proper noun to
`glossary.name_suspect` and to `repair.invents_name`, and `glossary.correct()` cannot
repair it because it is near no glossary name. Also observed: `going to` -> `gonna`, and
capitalised-token count rising 71 (A) -> 84 (B) -> 96 (C), though much of that rise is
legitimate title-casing ("The Heavenly Demon" is a title).

**One fix and one regression in 180 seconds of audio.** `hotwords` is a real mechanism, not
a free win, and the fix/regression ratio has to be measured at scale before it is adopted.

## Bearing on the spec

`.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md` argues that the wrong-arc
prompt manufactures mishears throughout Season 31 and that a per-season prompt would fix
them. **Both halves are unsupported by this measurement.** The wrong-arc prompt cost
nothing measurable and the right-arc prompt bought nothing measurable.

## The defect that IS demonstrated

Arm B's prompt listed `Donquixote Doflamingo` explicitly. Arm B still produced the mishear
`Dothamingo`, in the same place arm A did. `Doflamingo` is in the glossary's 92 names, and
`glossary.correct()` still cannot repair it:

    Dothamingo -> correct() = Dothamingo   (unchanged)
      fuzzy tier:    difflib 0.800  vs cutoff 0.84 (glossary.fuzzy_cutoff, len 10)  MISS
      phonetic tier: metaphone T0MNK vs TFLMNK                                       MISS

and `repair.py:493` skips the card because it has no fansub anchor — one of S31's 6,492
`no_reference` cards. So no stage in the pipeline can fix a name whose correct spelling was
already in the glossary. That is a near-miss in the correction tiers with no fallback on
non-fansub releases, and it is the defect this evidence actually supports acting on.
