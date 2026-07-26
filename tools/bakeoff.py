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
    ap.add_argument("--raw", help="captured faster-whisper dump (needs a GPU re-transcribe)")
    ap.add_argument("--conf", help="a production <stem>.dubtitles.conf.json (what repair.py reads)")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--ollama", default="http://192.168.1.196:11434/api/generate")
    ap.add_argument("--models", nargs="+", default=["qwen3:8b", "qwen3.5:4b", "qwen2.5:7b"])
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()

    gloss = glossary.load(a.glossary)
    cards = load_cards(a.raw, a.conf)
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
