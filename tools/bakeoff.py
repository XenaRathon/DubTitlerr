#!/usr/bin/env python3
"""C1 model bake-off: run the candidate repair models on REAL transcription target
lines and print a side-by-side comparison for judging, so REPAIR_MODEL is locked by
evidence on the actual hardware (not guessed).

Pipeline: load captured raw whisper output (dump_whisper.py JSON) -> reflow into cards
-> apply the deterministic glossary correction -> pick the repair targets (is_target) ->
ask each model to repair each target (glossary-only prompt; pass --refs for an mkv's
fansub if you have one) -> print orig vs each model + per-model latency.

Usage:
  python3 tools/bakeoff.py --raw raw.json --glossary "glossaries/One Pace.json" \\
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


def cards_from_raw(raw):
    words, segments = [], []
    for si, s in enumerate(raw):
        segments.append({"start": s["start"], "end": s["end"], "no_speech_prob": s["no_speech_prob"]})
        for w in (s["words"] or []):
            words.append({"text": w["word"], "start": w["start"], "end": w["end"],
                          "prob": w["probability"] or 1.0, "seg": si})
    return reflow.reflow(words, segments)


def ask(ollama, model, prompt):
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0}}
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(ollama, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read()).get("response", "").strip()
        out = out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        out = f"<ERROR {e}>"
    return out, time.monotonic() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--glossary", default="")
    ap.add_argument("--ollama", default="http://192.168.1.196:11434/api/generate")
    ap.add_argument("--models", nargs="+", default=["qwen3:8b", "qwen3.5:4b", "qwen2.5:7b"])
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()

    gloss = glossary.load(a.glossary)
    cards = cards_from_raw(json.load(open(a.raw)))
    for c in cards:                                  # deterministic layer first (as in prod)
        c["text"] = glossary.correct(c["text"], gloss)[0]
    targets = [c for c in cards if repair.is_target(c, gloss)][:a.limit]
    prompts = [repair.build_prompt(c["text"], "", gloss) for c in targets]   # glossary-only (mp4)
    print(f"cards={len(cards)} targets={len(targets)} (showing {len(targets)})  models={a.models}\n")

    # model-OUTER so each model loads once (avoids reload thrash on the 8GB GPU)
    outs = {m: [] for m in a.models}
    totals = dict.fromkeys(a.models, 0.0)
    for m in a.models:
        for p in prompts:
            out, dt = ask(a.ollama, m, p)
            outs[m].append(out)
            totals[m] += dt

    for i, c in enumerate(targets):
        print("ORIG:", c["text"])
        for m in a.models:
            print(f"  {m:14}: {outs[m][i]}")
        print()
    print("avg latency/line:", {m: round(totals[m] / max(1, len(targets)), 2) for m in a.models})


if __name__ == "__main__":
    main()
