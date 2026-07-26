# DubTitlerr — Accuracy & Model Improvements

> Research findings: transcription model alternatives, LLM repair model upgrades,
> and two-pass architecture for a dual-GPU+CPU homelab (GTX 1060 6 GB for Whisper,
> RTX 2070 Super 8 GB for Ollama, 2012 Xeon CPU server for llama.cpp).

---

## Table of Contents

1. [Hardware Constraints](#1-hardware-constraints)
2. [Transcription Model Analysis](#2-transcription-model-analysis)
3. [GPU Repair Model Candidates](#3-gpu-repair-model-candidates)
4. [CPU MoE as Secondary Model](#4-cpu-moe-as-secondary-model)
5. [Architecture: Two-Backend Repair](#5-architecture-two-backend-repair)
6. [Recommended Action Plan](#6-recommended-action-plan)
7. [Bake-off Procedure](#7-bake-off-procedure)

---

## 1. Hardware Constraints

| Component | Hardware | Role | Free for model |
| :--- | :--- | :--- | :--- |
| **Whisper GPU** | GTX 1060 6 GB (Pascal) | Transcribe (faster-whisper) | ~3–4 GB at int8 |
| **LLM GPU** | RTX 2070 Super 8 GB | Repair (Ollama) | ~6.5–7 GB |
| **CPU server** | 2012 Xeon, DDR3 | llama.cpp | CPU RAM only |

**Current defaults:**
- `WHISPER_MODEL=large-v3` (int8 on 1060)
- `REPAIR_MODEL=qwen3:8b` (Q4_K_M on 2070S via Ollama)
- `REPAIR_MODEL_SECONDARY` = same (no-op two-pass)
- `REPAIR_BACKEND=ollama`

---

## 2. Transcription Model Analysis

### Can any local model beat Whisper large-v3 for English anime dub audio?

**No.** Large-v3 is the most accurate publicly available local model for English ASR.
The alternatives below trade accuracy for speed, size, or language coverage.

| Model | Accuracy vs large-v3 | Why it doesn't help | Verdict |
| :--- | :--- | :--- | :--- |
| **Faster-Whisper** | Identical | Already in use | ✅ Already adopted |
| **Whisper.cpp** | Identical | Same model, CPU-only | ↔ Lateral move |
| **Distil-Whisper** | ~1 % WER *worse* | Speed optimization, not quality | ❌ Regression |
| **Large-v3-turbo** | ~identical | ~2× faster, same accuracy | ✅ Speed-for-beam trade |
| **Meta MMS** | Worse on English | 1,100 languages | ❌ Wrong task |
| **Vosk / Silero / wav2vec 2.0** | Significantly worse | Edge/embedded targets | ❌ Wrong task |

### The real leverage: large-v3-turbo + higher beam size

The one transcription-side change worth testing:

| Change | Effect | Risk |
| :--- | :--- | :--- |
| `WHISPER_MODEL=large-v3-turbo` | ~2× faster inference on Pascal | Untested on 1060 6GB at int8 — may OOM |
| `WHISPER_BEAM_SIZE=15` | Higher beam explores more candidates → fewer garbled lines | Needs turbo's speed headroom to avoid wall-clock regression |

**Recommendation:** Test `large-v3-turbo` on one episode. If it fits at int8 without OOM,
bump `WHISPER_BEAM_SIZE` incrementally (10, 12, 15) until latency matches current
large-v3 + beam=7. This is the only transcription-side accuracy improvement available.

```bash
# One-liner test (inside the container or on the server):
WHISPER_MODEL=large-v3-turbo WHISPER_BEAM_SIZE=12 python3 generate.py /path/to/one/episode.mkv
```

---

## 3. GPU Repair Model Candidates

### Constraint: ~6.5–7 GB free VRAM on the RTX 2070 Super

The repair task is ideal for aggressive quantization because:
- **Tiny KV cache**: single subtitle line (5–20 words) → ~30 tokens prompt
- **Short output**: one corrected line → ~30–60 tokens
- **Temperature=0**: deterministic, no sampling overhead

| Model | Quant | Weights | Total (w/ KV) | Fits? | Quality vs qwen3:8b |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen 3 8B** (current) | Q4_K_M | ~4.9 GB | ~5.0 GB | ✅ | Baseline |
| **Qwen 3.5 9B** | Q4_K_M | ~5.5 GB | ~5.6 GB | ✅ | Incremental |
| **Phi-4 14B** | **Q3_K_M** | **~6.5 GB** | **~6.6 GB** | ⚠️ Tight | **Best chance of meaningful upgrade** |
| **Phi-4 14B** | IQ4_XS | ~6.8 GB | ~6.9 GB | ❌ OOM risk | Too tight |
| **Qwen 2.5 14B** | IQ3_XS | ~6.0 GB | ~6.1 GB | ✅ | Solid, but heavy quant loses edge |
| **Mistral Nemo 12B** | Q4_K_S | ~6.5 GB | ~6.6 GB | ⚠️ Tight | Lateral move from 8B |
| **Llama 3.1 8B** | Q4_K_M | ~4.9 GB | ~5.0 GB | ✅ | Worse than Qwen 3 for instruct |

### Phi-4 14B (Q3_K_M) — the most promising GPU upgrade

Microsoft's Phi-4 14B is unusually good at precise instruction following — it
consistently beats larger models on literal text transformation tasks. For "fix the
garbled words, don't change anything else," Phi-4 is near the top of the leaderboard
even vs 70B-class models.

At Q3_K_M (~6.5 GB weights), with minimal KV cache, it should **just fit** in 7 GB.
The reality is it'll be tight — close other GPU consumers (monitor, browser) while it
runs, or free another ~100 MB.

```bash
ollama pull phi-4:14b-q3_K_M
```

**Warning:** Phi-4 is a "thinking" model — ensure `think: false` in the Ollama request.
The existing `repair.py` code already sends `"think": false` in the request body, so
this should work out of the box.

### Qwen 2.5 14B (IQ3_XS) — safer fallback

If Phi-4 OOMs, Qwen 2.5 14B at IQ3_XS (~6 GB weights) fits more comfortably.
The aggressive quantization loses some of the advantage over the 8B variant, but
the extra 5B parameters' worth of stored knowledge helps with obscure anime names.

```bash
ollama pull qwen2.5:14b-iq3_xs
```

---

## 4. CPU MoE as Secondary Model

### The candidate: qwen3.6:35b-a3b (35B MoE, 3B active)

This model runs on the 2012 Xeon server via llama.cpp. It has 35B total parameters
but only 3B active per token — so on CPU, inference is RAM-bandwidth bound, not
compute bound.

| Quant | Total RAM | Est. tok/s on DDR3-1333 | Per-repair latency (60 tok output) |
| :--- | :--- | :--- | :--- |
| Q4_K_M | ~17.5 GB | ~2–4 tok/s | ~15–30 s |
| Q3_K_M | ~13 GB | ~3–5 tok/s | ~12–20 s |
| Q2_K | ~9 GB | ~3–5 tok/s | ~12–20 s |

### Would it be better than qwen3:8b for this task?

This is the key question, and the answer is **not obvious**:

| Factor | For MoE | Against MoE |
| :--- | :--- | :--- |
| Active params per token | 3B | **← 8B dense has more compute** |
| Total stored knowledge | 35B total → more name awareness | Only relevant if the MoE's experts route correctly |
| Instruction following | Qwen 3.6 series is solid | Dense 8B models are proven more reliable for constrained tasks |
| Speed | ~15–30 s per line | **← qwen3:8b does it in ~0.5–2 s** |

**My assessment:** For this specific constrained task (temperature=0, strict rules,
short output), the **qwen3:8b dense model on GPU is likely better** than the 35B MoE
on CPU. The 8B model has 2.7× more active compute per token, 100× lower latency,
and dense models are more reliable for precise instruction following than MoE models
with few active experts.

**The only way to know** is to run `tools/bakeoff.py` with both and compare outputs
side by side — that's exactly what it was built for.

### Where the MoE could shine: secondary re-verification

As a **secondary model** (`REPAIR_MODEL_SECONDARY`), the MoE's high total parameter
count becomes an advantage: when qwen3:8b produces a name-changing repair, having a
second opinion from a model with 35B total parameters' worth of knowledge (even if
only 3B are active) provides a genuinely independent verification signal.

The two-pass flow would be:
1. **Primary (fast, GPU):** qwen3:8b via Ollama → repairs all targets
2. **Secondary (slow, CPU):** qwen3.6:35b-a3b via llama.cpp → re-verifies only
   name-changing repairs (the `_needs_secondary_check()` gate)

---

## 5. Architecture: Two-Backend Repair

### The gap: current code routes both passes through one backend

Looking at `repair.py`, the `llm()` dispatch function checks a single `REPAIR_BACKEND`
env var:

```python
def llm(prompt, model=None):
    if REPAIR_BACKEND == "llamacpp":
        return llm_llamacpp(prompt, model or MODEL)
    return llm_ollama(prompt, model)
```

And both passes go through it:

```python
# Primary pass (line 261):
new = llm(prompt)

# Secondary pass (line 280):
if MODEL_SECONDARY != MODEL and _needs_secondary_check(c["text"], new, gloss):
    new2 = llm(prompt, model=MODEL_SECONDARY)
```

This means **primary and secondary must use the same backend**. You can't have
primary on Ollama (GPU) and secondary on llama.cpp (CPU) without a code change.

### Required code change: `REPAIR_BACKEND_SECONDARY` env var

A ~10-line addition to `repair.py` to support a separate backend for the secondary
pass:

```python
# New env var (defaults to REPAIR_BACKEND — preserves current behavior):
REPAIR_BACKEND_SECONDARY = os.environ.get("REPAIR_BACKEND_SECONDARY", REPAIR_BACKEND)

# Modified secondary call:
if MODEL_SECONDARY != MODEL and _needs_secondary_check(c["text"], new, gloss):
    new2 = llm(prompt, model=MODEL_SECONDARY, backend=REPAIR_BACKEND_SECONDARY)
```

And update `llm()` to accept an optional backend override:

```python
def llm(prompt, model=None, backend=None):
    backend = backend or REPAIR_BACKEND
    if backend == "llamacpp":
        return llm_llamacpp(prompt, model or MODEL)
    return llm_ollama(prompt, model)
```

**Note:** `llm_llamacpp()` ignores the `model` parameter (llama.cpp serves one
loaded model at a time — there's no model selector in the request body). So
`REPAIR_MODEL_SECONDARY` is documented in the audit trail but isn't sent to the
server; just make sure the right GGUF is loaded when `llama-server` starts.

### The config for a two-backend setup

```bash
# .env or docker-compose vars:

# Primary (fast, GPU via Ollama):
REPAIR_MODEL=qwen3:8b
REPAIR_BACKEND=ollama
OLLAMA_URL=http://ollama.local:11434/api/generate

# Secondary (slow, CPU via llama.cpp on Xeon server):
REPAIR_MODEL_SECONDARY=qwen3.6:35b-a3b
REPAIR_BACKEND_SECONDARY=llamacpp
REPAIR_LLAMACPP_URL=http://192.168.1.232:8080/completion
```

This way:
- ~90% of repairs complete in ~1 s each on GPU
- Only name-changing/ambiguous repairs hit the slow CPU model (~15–30 s each)
- Typical episode with 2–5 targets: ~3–5 s if no re-verify needed, ~20–60 s if it is

---

## 6. Recommended Action Plan

Ordered by impact / effort ratio:

### Phase 1 — Low effort, immediate (this weekend)

| # | Change | Env var | Expected impact |
| :--- | :--- | :--- | :--- |
| 1 | Test `large-v3-turbo` OOM on 1060 | `WHISPER_MODEL=large-v3-turbo` | Speed headroom for higher beam |
| 2 | Bake-off: qwen3:8b vs phi-4:14b-q3_K_M | `REPAIR_MODEL=phi-4:14b-q3_K_M` | Best GPU upgrade candidate |
| 3 | Bake-off: qwen3:8b vs qwen3.6:35b-a3b (CPU) | `REPAIR_BACKEND=llamacpp` | Evidence for MoE utility |

Use `tools/bakeoff.py` for all bake-offs (see §7 below).

### Phase 2 — Moderate effort (next session)

| # | Change | What's needed |
| :--- | :--- | :--- |
| 4 | Add `REPAIR_BACKEND_SECONDARY` env var | ~10 line code change in `repair.py` |
| 5 | If Phi-4 wins bake-off: switch default | `REPAIR_MODEL=phi-4:14b-q3_K_M` |
| 6 | If MoE wins bake-off: `REPAIR_MODEL_SECONDARY` | Two-backend config (Ollama + llama.cpp) |
| 7 | Bump `WHISPER_BEAM_SIZE` incrementally | If turbo fits, test beam 10, 12, 15 |

### Phase 3 — Nice to have (deferred)

| # | Change | Why deferred |
| :--- | :--- | :--- |
| 8 | Switch to `qwen3.5:9b` as default | Incremental gain, may not justify retest |
| 8 | Test Qwen 2.5 14B IQ3_XS | Only if Phi-4 OOMs |
| 9 | Upgrade LLM to Qwen 3.6 14B or equivalent | Needs 2026 hardware upgrade |

---

## 7. Bake-off Procedure

The project's `tools/bakeoff.py` is designed exactly for this. Here's how to run it:

### Step 1: Capture raw Whisper output

You need a `raw.json` from a real episode's transcription. The spec mentions
`dump_whisper.py` for this — or you can generate one from any recent run's
`dubtitles.conf.json` and the matching audio (ask if you need help).

### Step 2: Run the bake-off

```bash
# Install the candidate models first:
ollama pull phi-4:14b-q3_K_M
ollama pull qwen2.5:14b-iq3_xs

# Run comparison:
cd DubTitlerr
python3 tools/bakeoff.py \
    --raw /path/to/raw_whisper_output.json \
    --glossary "/config/glossaries/One Pace.json" \
    --models qwen3:8b phi-4:14b-q3_K_M qwen2.5:14b-iq3_xs \
    --limit 20
```

For the CPU MoE model:
```bash
# llama.cpp on the Xeon server needs to serve the model:
# (on the Xeon server)
llama-server -m qwen3.6-35b-a3b-Q4_K_M.gguf --host 0.0.0.0 --port 8080

# Then bake-off pointing at it (you'll need a modified bakeoff
# that hits llama.cpp's API, or just test manually).
# Alternatively, recent llama.cpp versions support `--ollama` on the server
# to expose an Ollama-compatible /api/generate endpoint, letting bakeoff work
# unchanged — check your llama-server --help for the flag.
python3 tools/bakeoff.py \
    --raw /path/to/raw.json \
    --glossary "/config/glossaries/One Pace.json" \
    --models qwen3:8b \
    --limit 15 \
    --ollama http://192.168.1.232:8080/completion  # llama.cpp endpoint
```

### Step 3: Judge by these criteria

| What to look for | Good | Bad |
| :--- | :--- | :--- |
| Name correction | Fixes "zolo" → "Zoro" | Changes "Luffy" → "Monkey" |
| Grammar | Fixes tense/missing article | Rephrases completely |
| Hallucination | Leaves fine lines unchanged | Invents words or names |
| Length | Output ~same length as input | Doubles or halves the line |
| Latency | < 3 s per line | > 15 s per line |

### What to do with results

1. Copy the bake-off output (terminal text)
2. Compare each model's output against the original ASR line
3. Count: correct repairs, incorrect changes, unchanged-but-should-have-been
4. Pick the model with the best repair:false-positive ratio

---

## Quick Reference: All Env Vars

### Transcription (`generate.py`)

| Env var | Current default | Candidate value | Why |
| :--- | :--- | :--- | :--- |
| `WHISPER_MODEL` | `large-v3` | `large-v3-turbo` | 2× speed, same accuracy |
| `WHISPER_BEAM_SIZE` | `7` | `12` | Better word accuracy |
| `COMPUTE_TYPE` | `int8` | `int8` | Pascal-friendly |

### Repair (`repair.py`)

| Env var | Current default | Candidate value | Why |
| :--- | :--- | :--- | :--- |
| `REPAIR_MODEL` | `qwen3:8b` | `phi-4:14b-q3_K_M` | Best GPU upgrade |
| `REPAIR_BACKEND` | `ollama` | `ollama` | GPU primary |
| `REPAIR_MODEL_SECONDARY` | (same as primary) | `qwen3.6:35b-a3b` | CPU second opinion |
| `REPAIR_BACKEND_SECONDARY` | — | `llamacpp` | **Needs code change** |
| `REPAIR_LLAMACPP_URL` | `http://192.168.1.232:8080/completion` | — | Points at Xeon server |
