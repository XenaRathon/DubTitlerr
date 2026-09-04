# Choosing an ASR model

Understanding-oriented. This is the evidence behind `WHISPER_MODEL` and `COMPUTE_TYPE`'s
defaults (see [Reference](Reference.md#transcription)) — what else was tried, why it lost,
and what would have to change for the answer to be different.

If you want a value looked up, see [Reference](Reference.md). If you want to pick a
quantisation for the _repair_ model rather than the transcription model, see
[How-to guides](How-To-Guides.md#choose-a-quantisation-for-your-card) — a separate decision.

---

## The result

**Whisper wins.** `large-v3` for quality, `large-v3-turbo` for speed. Nothing tested beats
it, on either GPU generation tested. That is the entire content of `WHISPER_MODEL`'s and
`COMPUTE_TYPE`'s defaults — they are not arbitrary, they are the winner of this bakeoff.

| Model                 | Precision |                              GTX 1060 (6 GB, Pascal) | RTX 2070 Super (8 GB, Turing) |
| --------------------- | --------- | ---------------------------------------------------: | ----------------------------: |
| **large-v3**          | int8      |                                           **18.93%** |                    **18.25%** |
| large-v3-turbo        | int8      |                                               20.76% |                        21.71% |
| Qwen3-ASR-1.7B        | fp16      |                                               23.69% |                        23.47% |
| parakeet-tdt-0.6b-v3  | fp16      |                                               28.55% |         crashed every attempt |
| parakeet-tdt_ctc-110m | fp16      |                                               29.04% |         crashed every attempt |
| Qwen3-ASR-0.6B        | fp16      |                                               29.11% |                        29.11% |
| canary-180m-flash     | fp16      |                                               72.72% |                        73.30% |
| canary-1b-v2          | fp16      |                                          OOM at load |  loaded; transcription broken |
| canary-qwen-2.5b      | —         | not tested — disqualified before running (see below) |

Figures are word error rate against a real reference transcript — not agreement between
models, an actual ground-truth script (how that happened is below). Lower is better. The
per-entrant numbers behind this table — VRAM peak, load and wall time, confidence
distributions — are in
[`docs/asr-bakeoff/`](https://github.com/xenarathon/DubTitlerr/tree/main/docs/asr-bakeoff).

---

## How this was measured

Every candidate that claims to beat Whisper on public leaderboards — NVIDIA NeMo's
Parakeet and Canary family, Alibaba's Qwen3-ASR — lives outside faster-whisper's
CTranslate2 stack, so the project's existing `tools/model_bakeoff.py` (which only speaks
CT2) could not judge them. `tools/asr_bakeoff.py` was built for this: it loads each
candidate stack **strictly sequentially**, with a full VRAM offload proven between loads,
transcribes the same three episodes on the pipeline's own audio path
(`generate.eng_audio_index` / `generate.extract_wav`), and scores every entrant by the
pipeline's own judge (blocklist hits, and no_speech_prob/logprob where a stack provides
them).

The three episodes were chosen for range: a normal 24-minute episode, a second-show
sanity check, and a 142-minute movie with heavy music and mixed calm/action audio, picked
specifically to stress a model across the full range of noise conditions a season
actually contains.

**The reference transcript is real, not assumed.** Most dub audio has no ground truth to
score against, so the default comparison is cross-model agreement — how much two models'
output differs, which tells you they disagree, not which one is right. One of the test
movies turned out to have a subtitle track _mislabelled_ "SDH": rather than sound-only
captions, it was the actual professional English dub script. That made a genuine WER
number possible instead of just an agreement number — the reference is real dialogue,
scored against real transcription, the way WER is supposed to work.

**The precision floors are not equal, and that is stated in every report, not buried.**
Whisper ran int8 — production's own default, chosen because Pascal cannot run efficient
fp16 (see below). Neither NeMo nor Qwen3-ASR has a working int8 inference path: NeMo's
route runs through a separate TensorRT Model Optimizer export pipeline days away from a
same-day bakeoff, and the standard `torch.quantization` route is a documented
compatibility dead end against these architectures. So every non-whisper entrant here ran
at fp16, the best available without a multi-day export project. A whisper-int8 number and
a Qwen-fp16 number are directly comparable on WER — WER measures transcription
correctness, not precision — but their VRAM figures are not: fp16 costs roughly double
what int8 does for a model of the same size, and that gap is baked into every VRAM number
above, not a fair fight between the stacks.

---

## What each finding actually means

### Pascal cannot run Whisper at fp16 at all

`large-v3-turbo` at `--compute-type float16` did not fail slowly on the GTX 1060 — it
failed to load, with a hard `ValueError`: the target device does not support efficient
float16 computation. This is not a preference; Pascal genuinely lacks the tensor-core path
fp16 needs. `COMPUTE_TYPE=int8` is not a quality/speed tradeoff on this hardware. It is
the only mode that runs.

### canary-1b-v2 does not fit 6 GB, and that is a real, hardware-specific ceiling

On the 1060 it failed to load — out of memory, even at fp16, even with nothing else
resident. On the 2070 Super it **loaded cleanly** at a 7.8 GB peak. Same model, same
weights, same precision: the only variable was VRAM. This confirms the earlier OOM was a
genuine capacity line at 6 GB, not something a smaller batch size or a code fix would move
— chasing it further on Pascal would be chasing a wall, not a bug.

### canary-180m-flash needed real fixes before its numbers meant anything

The first pass through canary-180m-flash didn't produce a merely-worse transcript — it
produced repetition-collapse: `itsssssssssssssss`, `It's awesome.` repeated forty times.
Two things were wrong, not one. First, the harness never passed `source_lang`,
`target_lang`, or `pnc` — canary is a multitask model and silently mis-decodes without an
explicit task. Second, its internal chunk size (300 seconds, copied from Parakeet, which
tolerates it) was far too long for canary's fixed-length generation cap — a chunk that
long guarantees the decoder runs out of budget mid-sentence and starts repeating. Dropping
the chunk to 40 seconds and adding the task kwargs turned garbage into the coherent, if
mediocre, 72–73% numbers above. Both fixes are now permanent in `asr_bakeoff.py` — the
lesson generalizes to any future NeMo multitask model tried here.

### Parakeet is real but broken on this specific Turing environment

Both Parakeet variants crashed identically, every single attempt, with a fatal CUDA
"illegal memory access" inside PyTorch's pinned-memory allocator — always on the second
`transcribe()` call, always the same stack trace. This reproduced with and without an
explicit `gc.collect()` around it, which ruled out the first suspect. The common factor is
the torch build this environment resolved: `2.14.0+cu130`, a considerably newer combination
than the `2.6.0+cu124` the 1060's environment landed on, where Parakeet ran without
incident. This reads as a real bug in that specific bleeding-edge torch/CUDA pairing, not
a limitation of Turing hardware — Parakeet's own numbers on the 1060 (28.55%, 29.04%) are
competitive. A from-scratch environment pinned to a known-good torch version is the
follow-up this would need, not more debugging inside the current one.

### Qwen3-ASR needed two real fixes, and still has a real cost

The 0.6B model's first honest run OOM'd on a 6 GB card — its own package chunks
internally up to 20 minutes per pass, and even that is still one non-windowed attention
pass, too large for 6 GB. External pre-chunking at 60 seconds fixed it. Separately, left
unconstrained, the model drifted into hallucinating **Chinese-language lyrics** during a
background song in an English-dub episode — `language="English"` forces text-only English
output and stopped it. Both fixes are permanent in the harness.

Even fixed, Qwen3-ASR-1.7B is real: 23.5–23.7% WER, the closest non-whisper contender
tested, and its 0.6B sibling landed at _the same_ 29.11% on both GPU generations — a
level of cross-hardware consistency that argues these are real model-quality ceilings, not
noise. But it is roughly **7x slower than whisper** on a single file with batch size 1 on
a consumer card — the vendor's published throughput numbers assume large-batch,
server-scale concurrency, a shape this pipeline's one-episode-at-a-time workload never
produces.

### canary-qwen-2.5b looked like the leaderboard winner and was disqualified before it ran

Public benchmarks put `nvidia/canary-qwen-2.5b` ahead of everything else tested here on
English WER. It was never actually run. Word-level timestamps are a hard requirement for
this pipeline — no timing, no subtitle cues — and canary-qwen turned out not to have any.
This was checked directly against NeMo's `SALM` model class source (the model card's own
usage section doesn't mention timestamps either, but the source was the actual proof): the
only public inference method is `generate()`, prompted chat-style
(`"Transcribe the following: <audio>"`), returning plain generated text. No `transcribe()`
method, no alignment output, nothing timestamp-shaped anywhere in the class. A model that
cannot produce timing cannot produce a dubtitle, regardless of its WER — disqualified on
architecture, not on a bad result.

---

## When this could change

- **A from-scratch Turing (or newer) environment, torch version pinned deliberately rather
  than left to `pip`'s resolver**, to get a real Parakeet number on non-Pascal hardware —
  the crash here looks like a dependency-version bug, not a hardware limit.
- **Qwen3-ASR's inference speed**, if a batching or serving change closes the ~7x gap to
  whisper for single-file workloads — it is already the strongest non-whisper contender on
  quality.
- **A production int8 export for NeMo or Qwen3-ASR**, which would remove the fp16-vs-int8
  asymmetry entirely and let VRAM numbers be compared as directly as the WER numbers
  already are.

Until one of those changes, `WHISPER_MODEL=large-v3-turbo` and `COMPUTE_TYPE=int8` are not
a placeholder default. They are the measured answer.
