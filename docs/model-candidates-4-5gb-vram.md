# Repair/verify model candidates — 4–5 GB VRAM A/B pool

Reference for A/B-testing candidate LLMs against the locked `qwen3:8b` baseline.
Compiled 2026-08-31; sizes are approximate Q4 footprints (Ollama download size
where available). All candidates fit a 4–5 GB VRAM budget.

## Task profile these candidates are judged against

- **Repair** (`repair.py`, `REPAIR_MODEL`): strict single-line text correction.
  Short prompt (~30 tokens), short output (~30–60 tokens), temperature 0,
  `think:false`, glossary-anchored names. Known failure modes measured in this
  repo: **inertness** (nanbeige4.2-3b made 1 edit across 120 targets on
  prohibition-heavy prompts) and **over-rewriting** (qwen3.5:9b rewrote 42% of
  lines). Safe-fix rate and name-edit rate are the judgment signals.
- **Verify/adjudicate** (`glossary_verify.py`, `VERIFY_MODEL`): canonical-spelling
  selection and merge yes/no — JSON output (`{"canonical": ...}`), classification.
  JSON validity is a separate judgment axis.
- **Punctuation restore** (`punctuation.py`, `RESTORE_MODEL`): defaults to
  `REPAIR_MODEL`.

Backends: Ollama (`/api/generate`, `think:false` supported) and llama.cpp
(raw `/completion` or `/v1/chat/completions` for templated models, via
`REPAIR_BACKEND=llamacpp` / `--llamacpp NAME=URL` in the bake-off).

## Already in the pool — your current contenders

| Model                              | Footprint                                                    | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| :--------------------------------- | :----------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `qwen3:8b`                         | ~5.0 GB total (Q4_K_M)                                       | Current locked baseline (`REPAIR_MODEL`/`VERIFY_MODEL` default). Everything below is judged against it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `lfm` (Liquid AI LFM2 / LFM2.5)    | 2.6B–3B class (dense); LFM2-8B-A1B MoE (8B total, 1B active) | **Hybrid linear-attention** architecture — a genuinely different inference profile from the dense Transformers in this pool (same niche slot as Zamba2, but an actively maintained, instruct-tuned family). Edge/on-device focus; GGUF for llama.cpp and Ollama. **Strengths:** fast, tiny VRAM, strong instruction following for size. **Caveats:** younger ecosystem — early community reports of llama.cpp/Ollama compatibility hiccups (largely resolved by 2026); LFM2.5 is VL-capable, so confirm text-only behavior under `/api/generate`. Watch whether hybrid attention holds up on exact-rewrite tasks — that's what the bake-off is for. |
| `ling` (inclusionAI Ling-lite-1.5) | 16.8B total / 2.75B active (MoE), 128K ctx                   | Strong code/math/long-context model (2506/2507 refresh). **Key constraint: only the active params fit the VRAM budget** — full weights at Q4 are ~9–10 GB, so it does _not_ fit 4–5 GB VRAM. Treat it as a **CPU / secondary-model candidate** (`REPAIR_MODEL_SECONDARY`), the same role IMPROVEMENTS.md proposes for qwen3.6:35b-a3b: a second opinion on name-changing repairs, not the GPU primary. On-GPU at all would need a heavy quant (Q2) that likely erases the quality edge. MoE routing quality varies per input — fine for a re-check gate, risky as the only judge.                                                                   |
| `tinyllama` (TinyLlama 1.1B)       | 1.1B, small context                                          | **Floor / sanity control.** Cheap enough to run anywhere, including CPU. **Caveats:** quality ceiling is low, and the repair task already struggles at 3B (nanbeige went inert) — expect it to lose badly on safe-fix and name-edit rates. Keep it only as a latency/throughput reference point, or drop it if the A/B gets too big.                                                                                                                                                                                                                                                                                                                |
| `nanbeige4.2-3b`                   | ~3B (Q8_0 GGUF, patched llama.cpp)                           | The repo's **measured champion of the bounded-structured-task profile** — strong at agentic tool-calling and constrained extraction; beat qwen in 3 of 4 evals (REVIEW.md addendum). Best fit is the **verify/adjudicate path**, not repair. **Caveats (all measured in-repo):** goes **inert** on prohibition-only prompts (1 edit across 120 targets in the repair sweep), and the raw llama.cpp `/completion` endpoint returns nothing but newlines — must use the chat/templated path (hence the patched llama.cpp + `ask_llamacpp_chat` in the bake-off).                                                                                      |

**How they slot into the A/B:** `lfm` and `nanbeige` are GPU primary candidates; `ling` is a CPU/secondary re-check model; `tinyllama` is the floor control.

## Mainstream candidates

### Tier 1 — same family as the proven baseline (lowest risk)

| Tag          | Size (Q4) | Why                                                                                                                                                                                                                                                                       | Caveat                                                                                                                             |
| :----------- | :-------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------- |
| `qwen3.5:4b` | 3.4 GB    | 4B sibling of `qwen3.5:9b` (rated an "incremental" upgrade over the 8B baseline in IMPROVEMENTS.md). Same tokenizer, same `think:false` handling; already a default in `tools/bakeoff.py`. If the 9B's over-rewrite is a size effect, the 4B should be more conservative. | Native VLM wrapper; if RENDERER/PARSER misbehaves under `/api/generate`, use community text-only build `frob/qwen3.5-instruct:4b`. |
| `qwen3:4b`   | 2.6 GB    | Prior-gen 4B — head-to-head with `qwen3.5:4b` isolates generation bump from size bump.                                                                                                                                                                                    | Older gen.                                                                                                                         |
| `qwen3.5:2b` | 2.7 GB    | Smaller sibling; finds the floor of the family.                                                                                                                                                                                                                           | Quality drops below 4B.                                                                                                            |

### Tier 2 — best-credentialed small models for this task profile

| Tag             | Size (Q4)     | Why                                                                                                                                                                                        | Caveat                                                                                  |
| :-------------- | :------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------- |
| `phi4-mini`     | 3.8B, ~2.5 GB | Phi-4 family is this repo's own bet for "fix the garbled words, don't change anything else" — literal text transformation is its headline strength (see IMPROVEMENTS.md's Phi-4 14B note). | Thinking model — confirm `think:false` is honored.                                      |
| `granite4.2:3b` | ~2.5 GB       | IBM dense-reasoning 3B with **native structured JSON + tool-calling** — exactly the verify path's needs.                                                                                   | Reasoning-flavored; watch trace emission. `granite4:3b` (hybrid prior gen) as fallback. |
| `smollm3:3b`    | ~2 GB         | Topped several sub-4B reasoning/instruction benchmarks (incl. Qwen3-4B, Gemma3-4B). Cheapest footprint; good lower-bound control.                                                          | Thin fine-tune ecosystem.                                                               |

### Tier 3 — niche strengths / coverage

| Tag             | Size (Q4)                   | Why                                                                        | Caveat                                                                                                        |
| :-------------- | :-------------------------- | :------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------ |
| `gemma3n:e2b`   | ~3 GB (5B total, 2B active) | Fast (2B active), strong instruction following.                            | Without PLE caching on fast storage, memory use nearly triples — skip on a tight budget unless cache is warm. |
| `nemotron-mini` | 4B, ~2.6 GB                 | Tuned for RAG/function-calling/structured output; historically clean JSON. | Newer Nemotron 3 4B had reported structured-output regressions — validate JSON in the verify path.            |
| `mistral:7b`    | 4.1 GB                      | Fits the top of the budget; size-matched control.                          | Aging, formulaic output.                                                                                      |

## Niche candidates

### Structured-output / tool-use specialists (verify path)

| Model                                                       | Size (Q4) | Why                                                                                                                                                  | Caveat                                                                                                    |
| :---------------------------------------------------------- | :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| `exaone-deep:7.8b`                                          | 4.8 GB    | LG AI Research. Community-rated **best-in-class among small models for tool calling & structured output**; beats same-size open models on reasoning. | "Deep" = reasoning series — watch trace emission. `exaone-deep:2.4b` (~1.6 GB) if 7.8B crowds the budget. |
| Megrez-3B-Instruct (`JollyLlama/Megrez-3B-Instruct:Q4_K_M`) | ~1.9 GB   | Infinigence. Purpose-built for edge agentic/tool-use; strong function calling, tiny footprint.                                                       | Community tag, not official library.                                                                      |
| MiniCPM3-4B (`yefx/minicpm3_4b`)                            | ~2.7 GB   | OpenBMB. Function-call + code-interpreter tuning, 32K ctx. Underrated in the West.                                                                   | Community tag, not official library.                                                                      |

### Different architectures

| Model                | Size (Q4) | Why                                                                                                                                                          | Caveat                                                                                                                                                                                     |
| :------------------- | :-------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Zamba2-2.7B (Zyphra) | ~1.7 GB   | **Mamba2 + attention hybrid**: fixed-size SSM state instead of KV cache → tiny VRAM, fast, different inductive bias from the dense Transformers in the pool. | Not on the official Ollama library (long-standing support request) — run via llama.cpp GGUF (`REPAIR_BACKEND=llamacpp`), same path Nanbeige uses in the bake-off. Zamba2-1.2B also exists. |
| OLMo 2 7B (Allen AI) | ~4.4 GB   | Fully-open-data research model; answers "is the gap data or recipe?" in the A/B.                                                                             | Weaker at instruct than Qwen.                                                                                                                                                              |

### Size-matched control

| Model        | Size (Q4) | Why                                                                                                                      | Caveat |
| :----------- | :-------- | :----------------------------------------------------------------------------------------------------------------------- | :----- |
| `falcon3:7b` | 4.6 GB    | TII, Apache 2.0, ~11T tokens. 7B nearly matches the 8B baseline's size — isolates lab/architecture from parameter count. | —      |

### New / experimental

| Model                  | Size (Q4)      | Why                                                                                         | Caveat                                                                                                                                                                  |
| :--------------------- | :------------- | :------------------------------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tiny Aya (Cohere Labs) | 3.35B, ~2.2 GB | Released Feb 2026. Open-weight research release, 70+ languages, designed to run on a phone. | Not on the official Ollama library — pull via `hf.co/CohereLabs/tiny-aya-global` or GGUF/llama.cpp. Verify the variant is instruct/chat-tuned before committing a slot. |

## Explicitly skipped (with reasons)

| Model                     | Size        | Reason                                                                                                                              |
| :------------------------ | :---------- | :---------------------------------------------------------------------------------------------------------------------------------- |
| `glm4:9b` (GLM-4-9B-0414) | 6.2 GB Q4   | Over the 4–5 GB budget.                                                                                                             |
| DeepSeek-R1 distills      | up to ~5 GB | Reasoning traces fight a temp=0 single-line-output task; they want temp 0.5–0.7, which the pipeline forbids.                        |
| `llama3.2:3b`             | ~2 GB       | Bake-off already found the Llama family worse than Qwen for instruct.                                                               |
| `nemotron-3-nano:4b`      | ~2.6 GB     | New NVIDIA edge-agentic 4B, but community reported structured-output failures at launch; `nemotron-mini` already covers the family. |
| `marco-o1:7b`             | 4.7 GB      | Reasoning model — same objection as R1 distills.                                                                                    |
| `bespoke-minitron:4b`     | ~2.6 GB     | Solid local-agent favorite but coder-flavored; weak fit for prose repair.                                                           |

## How to run the A/B

```bash
# Ollama-hosted models (qwen3.5:4b is already a bake-off default):
python3 tools/bakeoff.py --conf ".../Ep.dubtitles.conf.json" \
  --glossary "glossaries/One Pace.json" \
  --ollama http://ollama.local:11434/api/generate \
  --models qwen3:8b qwen3.5:4b qwen3:4b phi4-mini granite4.2:3b smollm3:3b nemotron-mini \
  --limit 15

# GGUF-only candidates (Zamba2, Tiny Aya) via the llama.cpp path:
python3 tools/bakeoff.py --conf ".../Ep.dubtitles.conf.json" \
  --glossary "glossaries/One Pace.json" \
  --ollama http://ollama.local:11434/api/generate \
  --models qwen3:8b \
  --llamacpp zamba2=http://host:8090/completion tiny-aya=http://host:8091/completion \
  --limit 15
```

Judge on the three signals the repo already tracks: **safe-fix count, name-edit
count, and inertness** (a model that changes nothing is as bad as one that
rewrites everything). For the verify path, check **JSON validity** separately —
granite, exaone-deep, nemotron, and phi are the ones to watch there.
