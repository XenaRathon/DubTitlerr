#!/usr/bin/env python3
"""C1 model bake-off: run the candidate repair models on REAL transcription target
lines and print a side-by-side comparison for judging, so REPAIR_MODEL is locked by
evidence on the actual hardware (not guessed).

Pipeline: load cards -- either a captured raw whisper dump (--raw, reflowed here) or a
production <stem>.dubtitles.conf.json (--conf, already reflowed; the same file repair.py
consumes, so the models are judged on exactly the lines production sends them) --
-> apply the deterministic glossary correction -> pick the repair targets (is_target) ->
ask each model to repair each target (glossary-only prompt; pass --refs for an mkv's
fansub if you have one) -> print orig vs each model + per-model latency.

Usage:
  python3 tools/bakeoff.py --conf "/media/.../Ep.dubtitles.conf.json" \\
      --glossary "glossaries/One Pace.json" \\
      --ollama http://192.168.1.196:11434/api/generate \\
      --models qwen3:8b qwen3.5:4b qwen2.5:7b --limit 15

No GPU needed locally — the models run on the Ollama host. Built with help of Claude.
"""
import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")
import glossary  # noqa: E402
import reflow  # noqa: E402
import repair  # noqa: E402


def load_cards(raw_path, conf_path):
    """Cards to judge, from exactly one of the two inputs.

    ``--raw`` is the original path: a captured faster-whisper dump, reflowed here the same
    way generate.py does. It needs a capture tool this repo does not ship, so it means
    re-transcribing an episode on the GPU.

    ``--conf`` is the practical path: a production ``<stem>.dubtitles.conf.json``. Those
    rows are already post-reflow, post-hallucination-gate and post-collapse, and carry
    every field ``repair.is_target()`` reads — and it is the very file ``repair.py``
    consumes in production, so the bake-off judges the models on precisely the lines the
    live pipeline would have sent them. No GPU, no re-derivation."""
    if bool(raw_path) == bool(conf_path):
        sys.exit("give exactly one of --raw (whisper dump) or --conf (dubtitles.conf.json)")
    if raw_path:
        return cards_from_raw(json.load(open(raw_path)))
    rows = json.load(open(conf_path))
    if not isinstance(rows, list):
        sys.exit(f"{conf_path}: expected a JSON list of conf rows")
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or "text" not in r:
            sys.exit(f"{conf_path}: row {i} has no 'text' — not a dubtitles.conf.json")
    return rows


def cards_from_raw(raw):
    words, segments = [], []
    for si, s in enumerate(raw):
        segments.append({"start": s["start"], "end": s["end"], "no_speech_prob": s["no_speech_prob"]})
        for w in (s["words"] or []):
            words.append({"text": w["word"], "start": w["start"], "end": w["end"],
                          "prob": w["probability"] or 1.0, "seg": si})
    return reflow.reflow(words, segments)


def parse_llamacpp_specs(specs):
    """``NAME=URL`` pairs -> {name: completion_url}. Lets a model that Ollama cannot serve
    take part in the bake-off: Nanbeige's GGUF, for one, needs a patched llama.cpp and
    `ollama create` refuses it ("failed to validate GGUF ... without compatibility
    patches"). repair.py can already run such a model (REPAIR_BACKEND=llamacpp), so the
    bake-off has to be able to judge it too."""
    out = {}
    for spec in specs or []:
        name, _, url = spec.partition("=")
        if not name or not url:
            sys.exit(f"--llamacpp expects NAME=URL, got {spec!r}")
        out[name] = url
    return out


def _post_json(url, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _first_line(out):
    return out.splitlines()[0].strip().strip('"').strip() if out else ""


def ask_ollama(ollama, model, prompt):
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0}}
    t0 = time.monotonic()
    try:
        out = _first_line(_post_json(ollama, body).get("response", "").strip())
    except Exception as e:
        out = f"<ERROR {e}>"
    return out, time.monotonic() - t0


def ask_llamacpp(url, prompt):
    """Mirrors repair.llm_llamacpp exactly — no model selector (the server has one model
    loaded), n_predict/stop bounded, reply read from "content". Sending anything else
    would measure a configuration that isn't the one that would ship."""
    body = {"prompt": prompt, "temperature": 0, "n_predict": 50, "stop": ["\n"]}
    t0 = time.monotonic()
    try:
        out = _first_line(_post_json(url, body).get("content", "").strip())
    except Exception as e:
        out = f"<ERROR {e}>"
    return out, time.monotonic() - t0


def ask_llamacpp_chat(url, prompt):
    """llama.cpp OpenAI-compatible /v1/chat/completions — unlike /completion this APPLIES
    the model's chat template, which a templated instruct model needs to produce anything
    at all (Nanbeige returns nothing but newlines through the raw endpoint).

    ``enable_thinking: False`` is passed through to the template: this fork otherwise
    spends its entire budget on ``reasoning_content`` and returns an empty message —
    measured empty after 114 s at max_tokens=512, versus correct output in 4.3 s with
    thinking off. An empty reply is surfaced as <EMPTY ...> rather than "", because ""
    would score as "model correctly left the line alone" — a silent false pass."""
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0,
            "max_tokens": 80, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.monotonic()
    try:
        msg = _post_json(url, body)["choices"][0]["message"]
        out = _first_line((msg.get("content") or "").strip())
        if not out:
            why = "thinking not disabled?" if msg.get("reasoning_content") else "no content"
            out = f"<EMPTY {why}>"
    except Exception as e:
        out = f"<ERROR {e}>"
    return out, time.monotonic() - t0


def ask(ollama, model, prompt, llamacpp=None, llamacpp_chat=None):
    raw = (llamacpp or {}).get(model)
    if raw:
        return ask_llamacpp(raw, prompt)
    chat = (llamacpp_chat or {}).get(model)
    if chat:
        return ask_llamacpp_chat(chat, prompt)
    return ask_ollama(ollama, model, prompt)


def format_model_block(model, targets, outs, total_s):
    """One model's finished results, printed the moment that model completes so a later
    timeout cannot destroy them. Tolerates outs shorter than targets (killed mid-run)."""
    lines = [f"\n----- {model}  (avg {total_s / max(1, len(outs)):.1f}s/line over {len(outs)} line(s)) -----"]
    for i, c in enumerate(targets):
        got = outs[i] if i < len(outs) else "<no result>"
        lines.append(f"  ORIG: {c['text']}")
        lines.append(f"   ->   {got}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="captured faster-whisper dump (needs a GPU re-transcribe)")
    ap.add_argument("--conf", help="a production <stem>.dubtitles.conf.json (what repair.py reads)")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--ollama", default="http://192.168.1.196:11434/api/generate")
    ap.add_argument("--models", nargs="+", default=["qwen3:8b", "qwen3.5:4b", "qwen2.5:7b"])
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--llamacpp", nargs="*", default=[], metavar="NAME=URL",
                    help="serve these model names from a llama.cpp /completion endpoint "
                         "instead of Ollama (raw prompt — mirrors repair.py exactly)")
    ap.add_argument("--llamacpp-chat", nargs="*", default=[], metavar="NAME=URL",
                    help="same, but via /v1/chat/completions so the model's chat template "
                         "is applied and thinking is disabled (needed by templated instruct "
                         "models; repair.py's raw /completion path cannot drive them)")
    a = ap.parse_args()

    llamacpp = parse_llamacpp_specs(a.llamacpp)
    llamacpp_chat = parse_llamacpp_specs(a.llamacpp_chat)
    gloss = glossary.load(a.glossary)
    cards = load_cards(a.raw, a.conf)
    for c in cards:                                  # deterministic layer first (as in prod)
        c["text"] = glossary.correct(c["text"], gloss)[0]
    targets = [c for c in cards if repair.is_target(c, gloss)][:a.limit]
    prompts = [repair.build_prompt(c["text"], "", gloss) for c in targets]   # glossary-only (mp4)
    print(f"cards={len(cards)} targets={len(targets)} (showing {len(targets)})  models={a.models}\n")

    # model-OUTER so each model loads once (avoids reload thrash on the 8GB GPU).
    # Each model's block is printed AS SOON AS that model finishes: these runs can take
    # hours when a candidate spills to CPU, and buffering everything to the end meant a
    # wall-clock kill threw away the models that had already completed.
    outs = {m: [] for m in a.models}
    totals = dict.fromkeys(a.models, 0.0)
    for m in a.models:
        for n, p in enumerate(prompts, 1):
            out, dt = ask(a.ollama, m, p, llamacpp, llamacpp_chat)
            outs[m].append(out)
            totals[m] += dt
            print(f"    [{m} {n}/{len(prompts)}] {dt:5.1f}s  {out[:70]}", flush=True)
        print(format_model_block(m, targets, outs[m], totals[m]), flush=True)

    print("\n=== SIDE BY SIDE ===")
    for i, c in enumerate(targets):
        print("ORIG:", c["text"])
        for m in a.models:
            got = outs[m][i] if i < len(outs[m]) else "<no result>"
            print(f"  {m:16}: {got}")
        print()
    print("avg latency/line:", {m: round(totals[m] / max(1, len(targets)), 2) for m in a.models})


if __name__ == "__main__":
    main()
