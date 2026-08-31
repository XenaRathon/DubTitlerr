"""Score a repair model against the verdicts a human already gave.

The bake-off in `bakeoff.py` counts what a model DID -- how many lines it changed, how many
its changes would ship past `accept_repair`. That is all a counter can see when nobody has
said what the right answer was, and it ranks a model that rewrites meaning above one that
corrects a name: measured 2026-08-31, `nemotron-mini` topped the ship count with four edits,
every one of which changed what the line said.

The decision store is the missing half. A human has already read these lines and written
down what they should say, so a model can be scored against the answer instead of against
its own confidence. Recovered store, 2026-08-31: 107 verdicts over One Pace, of which 17 are
`correct` and carry the reviewer's own typed text.

`near` exists because of what those 17 look like. The model reliably produces the right
WORDS and the wrong SURFACE -- no capitalisation, no hyphen in `Flame-Flame Fruit`, and a
full stop welded onto a line that continues. Scoring that as a miss hides how close the model
is; scoring it as a hit hides that it is not shippable. It is neither, so it is its own bucket.
"""

import os
import re

# Mirrors decisions.key: case and whitespace are noise, and the curly apostrophe and the
# straight one are two renderings of one character. Punctuation is KEPT -- restoring it is
# most of what this stage does, so it is the signal, not the noise.
_APOS = chr(0x2019)


def norm(text):
    """The comparison form: case, whitespace runs and apostrophe glyph folded away."""
    return " ".join((text or "").replace(_APOS, chr(0x27)).lower().split())


def loose(text):
    """`norm` reduced to words only, no surface.

    Separators become a SPACE rather than being deleted. Deleting them welds `Flame-Flame`
    into `flameflame`, which then fails to match the `flame flame` the model wrote -- the
    exact pair this bucket exists to catch."""
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", norm(text)).split())


def judge(kind, truth, orig, out):
    """Classify one model output against one human verdict.

    ``kind`` is the verdict: ``correct``/``accept``/``force`` carry a target in ``truth``;
    ``reject`` carries the text the human REFUSED, so leaving the line alone is the win and
    reproducing the refusal is the loss.

    An error marker is never compared against anything -- "" or `<ERROR ...>` is the model
    producing nothing, not the model leaving the line alone, and scoring it as inertness
    turns a dead backend into a clean no-op.
    """
    if not out or out.startswith("<ERROR") or out.startswith("<EMPTY"):
        return "error"
    if kind == "reject":
        if norm(out) == norm(truth):
            return "trap"
        return "exact" if norm(out) == norm(orig) else "wrong"
    if norm(out) == norm(truth):
        return "exact"
    # Before `near`, deliberately: a model that changed nothing has not come close to an
    # answer it never attempted, and crediting it would make inertness look like accuracy.
    if norm(out) == norm(orig):
        return "inert"
    if loose(out) == loose(truth):
        return "near"
    return "wrong"


def targets_from_store(store):
    """(orig, truth, kind) per verdict. `truth` is the answer for a positive verdict and the
    REFUSED text for a reject, which `judge` reads differently.

    A `correct` verdict with no typed text is dropped rather than fallen back to the
    proposal: `decisions.corrected_text` treats that same shape as owed-but-unresolved, and
    scoring a model against a proposal the human declined to endorse would invert the test.
    """
    out = []
    for e in store.get("decisions", []):
        kind, proposed = e.get("verdict"), e.get("proposed") or ""
        text = (e.get("text") or "").strip()
        if kind == "correct":
            if text:
                out.append((e.get("orig") or "", text, kind))
        elif kind in ("accept", "force", "reject"):
            out.append((e.get("orig") or "", proposed, kind))
    return out


def tally(results):
    """Counts per bucket, plus the two rates worth ranking on.

    `hit` is exact-or-near over the positive verdicts: the model found the answer, whether
    or not it dressed it correctly. `trap` is over the rejects alone -- a different
    denominator, because a model cannot fall into a trap it was never shown.
    """
    from collections import Counter

    c = Counter(v for _k, v in results)
    pos = sum(1 for k, _v in results if k != "reject")
    neg = sum(1 for k, _v in results if k == "reject")
    # Numerator over the SAME set as the denominator. A reject the model correctly left
    # alone also scores "exact", but it found no answer -- there was none to find -- and
    # counting it against a positives-only denominator reported a 167% hit rate live.
    hits = sum(1 for k, v in results if k != "reject" and v in ("exact", "near"))
    return {
        "n": len(results),
        "positives": pos,
        "rejects": neg,
        "exact": c["exact"],
        "near": c["near"],
        "inert": c["inert"],
        "wrong": c["wrong"],
        "trap": c["trap"],
        "error": c["error"],
        "hit_rate": (hits / pos) if pos else None,
        "trap_rate": (c["trap"] / neg) if neg else None,
    }


def main(argv=None):
    """Score one model against a recovered decision store."""
    import argparse
    import json
    import sys
    import time

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import glossary as glossary_mod
    import repair
    from tools.bakeoff import ask_llamacpp_chat

    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="a decisions/<Show>.json")
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--llamacpp-chat", required=True, help="chat-completions URL")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    gloss = glossary_mod.load_dict(json.load(open(a.glossary, encoding="utf-8")))
    targets = targets_from_store(json.load(open(a.store, encoding="utf-8")))
    if a.limit:
        targets = targets[: a.limit]

    results, rows, t0 = [], [], time.time()
    for i, (orig, truth, kind) in enumerate(targets, 1):
        prompt = repair.build_prompt(orig, "", gloss)
        try:
            out, secs = ask_llamacpp_chat(a.llamacpp_chat, prompt)
        except Exception as exc:  # a dead backend is a result, not a crash
            out, secs = f"<ERROR {type(exc).__name__}>", 0.0
        v = judge(kind, truth, orig, out)
        results.append((kind, v))
        rows.append({"kind": kind, "orig": orig, "truth": truth, "out": out, "judged": v, "secs": round(secs, 2)})
        print(f"  [{a.model} {i}/{len(targets)}] {secs:5.1f}s {v:<6} {out[:64]}", flush=True)

    t = tally(results)
    print(f"\n=== {a.model} : {t['n']} lines in {time.time() - t0:.0f}s ===")
    print(f"  exact {t['exact']}  near {t['near']}  inert {t['inert']}  wrong {t['wrong']}  trap {t['trap']}  error {t['error']}")
    hr, tr = t["hit_rate"], t["trap_rate"]
    print(f"  hit  rate (exact+near over {t['positives']:>3} answerable) : {hr:.0%}" if hr is not None else "  hit rate: n/a")
    print(f"  trap rate (over {t['rejects']:>3} the human refused) : {tr:.0%}" if tr is not None else "  trap rate: n/a")
    if a.json:
        json.dump({a.model: {"tally": t, "rows": rows}}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
