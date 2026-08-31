#!/usr/bin/env python3
"""C1 model bake-off: run the candidate repair models on REAL transcription target
lines and print a side-by-side comparison for judging, so REPAIR_MODEL is locked by
evidence on the actual hardware (not guessed).

Pipeline: load cards -- either a captured raw whisper dump (--raw, reflowed here) or a
production <stem>.dubtitles.conf.json (--conf, already reflowed; the same file repair.py
consumes, so the models are judged on exactly the lines production sends them) --
-> apply the deterministic glossary correction -> pick the repair targets (is_target) ->
ask each model to repair each target (glossary-only prompt; pass --refs for an mkv's
fansub if you have one) -> print orig vs each model, then SCORE every model and suggest a
shortlist to hand-judge.

Why the scores exist: the candidate pool is ~19 models, and at --limit 15 that is ~285
line pairs for a human to read. docs/model-candidates-4-5gb-vram.md names three judging
signals -- safe-fix count, name-edit count, and inertness ("a model that changes nothing
is as bad as one that rewrites everything"). Only safe-fix genuinely needs human eyes, so
the rest are computed here (see score_model): inert rate, the rate at which
repair.accept_repair -- production's OWN gate, not a re-implemented bar -- would admit the
repair, the name-edit count, and the <ERROR>/<EMPTY> rate. Every model's full output still
prints as it lands, every model appears in the ranked table however badly it scored, and
the shortlist is a recommendation the report explains rather than a filter it applies.

Usage:
  python3 tools/bakeoff.py --conf "/media/.../Ep.dubtitles.conf.json" \\
      --glossary "glossaries/One Pace.json" \\
      --ollama http://127.0.0.1:11434/api/generate \\
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
        for w in s["words"] or []:
            words.append({"text": w["word"], "start": w["start"], "end": w["end"], "prob": w["probability"] or 1.0, "seg": si})
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
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _first_line(out):
    return out.splitlines()[0].strip().strip('"').strip() if out else ""


def ask_ollama(ollama, model, prompt):
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model, "prompt": prompt, "stream": False, "think": False, "options": {"temperature": 0}}
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
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 80,
        "chat_template_kwargs": {"enable_thinking": False},
    }
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


def _norm(s):
    """Casefolded, whitespace-collapsed form used ONLY for the inertness test.

    Deliberately at least as wide as ``accept_repair``'s own "nothing changed" check
    (``new.lower() == orig.lower()``): a reply that differs from the input by spacing or
    casing alone changed nothing of substance, and counting it as an edit would inflate
    every other rate against the model. Because it is wider, a line counted inert is
    always also refused by accept_repair -- the two signals cannot disagree."""
    return " ".join((s or "").split()).lower()


def _all_cores(text):
    """Every bare token core in ``text``, lowercased -- the same reduction
    ``repair.invents_name`` performs on its original, via ``glossary._TOKEN_RE``."""
    return {m.group(2).lower() for m in (glossary._TOKEN_RE.match(t) for t in (text or "").split()) if m}


def changed_a_name(orig, new):
    """Whether ``new`` edited a proper noun relative to ``orig``.

    Reuses ``repair._proper_cores`` -- the repo's single shared definition of "the tokens
    both name guards reason about" (capitalised, long enough for the fuzzy tier, not an
    English word) -- rather than adding a second name matcher that could drift from it.

    A name is edited if a proper core was GAINED that no token of the original carried, or
    one was LOST that no token of the output carries. Both sides compare against ALL cores
    (``_all_cores``), not just the capitalised ones, exactly as ``invents_name`` does: a
    word merely re-capitalised by punctuation restoration (``that's`` -> ``That's``) was
    not a name edit, and comparing against the capitalised cores alone reports it as one.

    This counts every touch of a name, right or wrong: ``Zolo`` -> ``Zoro`` and ``Zolo`` ->
    ``Zorro`` both score here. Paired with the admitted rate (which refuses the fabricated
    one via ``invents_name``) that separates "edits names well" from "edits names at all"
    -- the pair of numbers the candidate doc asks to be judged on."""
    orig_cores, new_cores = repair._proper_cores(orig), repair._proper_cores(new)
    orig_all, new_all = _all_cores(orig), _all_cores(new)
    gained = any(c.lower() not in orig_all for c in new_cores)
    lost = any(c.lower() not in new_all for c in orig_cores)
    return gained or lost


def _card_duration(card):
    """Display seconds for a card, or None when the card cannot say.

    ``accept_repair`` REQUIRES a duration (C2: a repair that does not fit the card it is
    repairing is rejected, never accommodated by moving the card), so a caller that cannot
    supply one must not be allowed to skip the check. An undatable card is reported in
    ``no_duration`` rather than gated on a guessed length."""
    start, end = card.get("start"), card.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return (end - start) if end > start else None


def score_model(model, targets, outs, total_s, gloss, ref=""):
    """The computable half of the bake-off judgment for ONE model. Pure: no network.

    docs/model-candidates-4-5gb-vram.md judges candidates on safe-fix count, name-edit
    count and inertness. Only safe-fix needs human eyes; the rest are counted here so the
    ~19-model pool can be narrowed before anyone reads 285 line pairs.

    ``outs`` may be SHORTER than ``targets`` (a model killed mid-run). Those lines are
    counted in ``missing`` and excluded from every denominator -- padding the tail with
    "unchanged" would score a wall-clock kill as inertness, and dropping it would hide the
    shortfall entirely.

    ``ref`` is the fansub reference handed to ``accept_repair``. It defaults to "" because
    ``main()`` builds glossary-only prompts (``build_prompt(text, "", gloss)``): scoring
    against a reference the model was never shown would measure a gate the run did not
    face, and the empty reference is what keeps ``substitutes_a_vouched_name`` live.

    Every rate is over ``scored`` (results actually produced) and is None when that is 0,
    so a model that returned nothing renders as a row rather than a ZeroDivisionError."""
    n = len(outs)
    inert = changed = errors = empties = admitted = name_edits = no_duration = 0
    for i, out in enumerate(outs):
        orig = targets[i]["text"] if i < len(targets) else ""
        # <ERROR ...>/<EMPTY ...> mean the model produced NOTHING. They are never compared
        # against the original: "" or an error marker is not the model leaving the line
        # alone, and scoring it that way turns a dead backend into a clean no-op.
        if out.startswith("<ERROR"):
            errors += 1
            continue
        if out.startswith("<EMPTY"):
            empties += 1
            continue
        if _norm(out) == _norm(orig):
            inert += 1
            continue
        changed += 1
        if changed_a_name(orig, out):
            name_edits += 1
        dur = _card_duration(targets[i]) if i < len(targets) else None
        if dur is None:
            no_duration += 1
            continue
        # THE production gate itself, not a re-implemented bar: what this counts is what
        # would actually ship if this model were REPAIR_MODEL.
        if repair.accept_repair(orig, out, ref, dur, gloss):
            admitted += 1

    def rate(k):
        return (k / n) if n else None

    return {
        "model": model,
        "targets": len(targets),
        "scored": n,
        "missing": max(0, len(targets) - n),
        "inert": inert,
        "changed": changed,
        "errors": errors,
        "empties": empties,
        "admitted": admitted,
        "name_edits": name_edits,
        "no_duration": no_duration,
        "inert_rate": rate(inert),
        "change_rate": rate(changed),
        "error_rate": rate(errors + empties),
        "admitted_rate": rate(admitted),
        "name_edit_rate": rate(name_edits),
        "avg_latency_s": (total_s / n) if n else None,
    }


def _note_head(s, shortlisted, shortlist_n):
    """Where this model stands, in one clause -- the first true thing about it."""
    if s["errors"] + s["empties"] == s["scored"]:
        return "every call failed — the backend, not the model, is what was measured"
    if s["inert"] == s["scored"]:
        return "fully inert — returned the input on every line, so there is no fix to judge"
    if s["inert_rate"] is not None and s["inert_rate"] >= INERT_FLAG:
        return f"near-inert — left {s['inert']}/{s['scored']} lines untouched"
    if s["admitted"] == 0:
        return "nothing it produced would pass accept_repair — none of it would ship"
    if shortlisted:
        return f"shortlisted — {s['admitted']}/{s['scored']} of its repairs would ship"
    return f"below the top-{shortlist_n} cut ({s['admitted']}/{s['scored']} would ship)"


def _note_caveats(s):
    """Everything else the owner needs before trusting this row -- dead calls, an
    unfinished run, cards the ship gate could not be run on, wholesale rewriting."""
    bits = []
    if s["errors"] or s["empties"]:
        bits.append(f"{s['errors'] + s['empties']}/{s['scored']} calls produced <ERROR>/<EMPTY>")
    if s["missing"]:
        bits.append(f"finished only {s['scored']} of {s['targets']} lines")
    if s["no_duration"]:
        bits.append(f"{s['no_duration']} card(s) carried no duration, so the ship gate could not run on them")
    if s["change_rate"] == 1.0 and s["scored"] >= REWRITE_FLAG_MIN:
        bits.append("rewrote every line — left nothing alone")
    return bits


def _note(s, shortlisted, shortlist_n):
    """Why this model sits where it does. Every model gets one: a model that ranks last
    is never dropped from the table, it is told why it ranks last."""
    if s["scored"] == 0:
        return "no results at all — nothing to judge"
    bits = _note_caveats(s)
    return _note_head(s, shortlisted, shortlist_n) + ("; " + "; ".join(bits) if bits else "")


# A model is worth a human's eyes only if at least one of its repairs would actually be
# written by production. accept_repair is what decides that, so "admitted == 0" is the
# shortlist cut -- it subsumes both failure modes the candidate doc names: a fully inert
# model admits nothing (accept_repair refuses new == orig outright), and a model whose
# every reply is <ERROR> admits nothing either. It is a RECOMMENDATION: nothing is ever
# removed from the table for failing it.
INERT_FLAG = 0.9  # near-inert warning in the note; nanbeige measured 1 edit in 120 (0.992)
# "changed every line" is only evidence of the doc's over-rewriting failure on a sample
# big enough to mean it. `is_target` hands the models pre-selected SUSPECT lines, so at
# --limit 2 a model that fixes both is doing its job, not rewriting everything.
REWRITE_FLAG_MIN = 10


def rank_models(scores, shortlist_n=5):
    """Order every model best-first and mark the suggested shortlist. Returns copies of
    all inputs -- ranking never drops a row."""
    ranked = sorted(
        (dict(s) for s in scores),
        key=lambda s: (
            -(s["admitted_rate"] or 0.0),
            s["avg_latency_s"] if s["avg_latency_s"] is not None else float("inf"),
            s["model"],
        ),
    )
    picked = 0
    for i, s in enumerate(ranked, 1):
        s["rank"] = i
        s["shortlisted"] = bool(s["admitted"]) and picked < shortlist_n
        picked += s["shortlisted"]
    for s in ranked:
        s["note"] = _note(s, s["shortlisted"], shortlist_n)
    return ranked


def _pct(v):
    return "  n/a" if v is None else f"{100 * v:4.0f}%"


def format_summary(ranked, bounds=()):
    """The final report: a ranked row for EVERY model, then the suggested shortlist.

    The shortlist is a recommendation, not a filter -- the table always carries the whole
    pool, because "this model went inert" is a result the owner needs to see, not an
    absence of one. ``bounds`` are the things that limited coverage (a --limit, a model
    that never ran, a mid-run kill); they are printed unconditionally so a partial run is
    never read as a complete one."""
    w = max([len(s["model"]) for s in ranked] + [5])
    out = ["\n=== SCORES (ranked; safe-fix quality still needs your eyes) ==="]
    out.append(f"  {'#':>2}  {'model':<{w}}  {'ship':>5} {'inert':>5} {'names':>5} {'err':>5}  {'lines':>7}  {'s/line':>7}")
    for s in ranked:
        lat = "    n/a" if s["avg_latency_s"] is None else f"{s['avg_latency_s']:7.1f}"
        lines = f"{s['scored']:>3}/{s['targets']:<3}"
        out.append(
            f"  {s['rank']:>2}  {s['model']:<{w}}  {_pct(s['admitted_rate'])} {_pct(s['inert_rate'])} "
            f"{_pct(s['name_edit_rate'])} {_pct(s['error_rate'])}  {lines}  {lat}"
        )
    out.append("")
    out.append("  ship  = would repair.accept_repair() write it? (production's own gate, no reference)")
    out.append("  inert = reply identical to the input after casefold/whitespace — no fix offered")
    out.append("  names = touched a proper noun (right or wrong; pair with ship to tell which)")
    out.append("  err   = <ERROR>/<EMPTY> — the model produced nothing, NOT 'left the line alone'")
    out.append("")
    for s in ranked:
        out.append(f"  {s['rank']:>2}. {s['model']}: {s['note']}")
    short = [s["model"] for s in ranked if s["shortlisted"]]
    out.append("")
    out.append("=== SUGGESTED SHORTLIST TO HAND-JUDGE ===")
    out.append("  " + (", ".join(short) if short else "none — no model produced a repair production would ship"))
    out.append("  (a recommendation only: every model above is reported in full, and safe-fix")
    out.append("   quality is the one signal no counter can decide.)")
    out.append("")
    out.append("=== WHAT BOUNDED THIS RUN ===")
    for b in bounds or ["nothing — every model ran every target line"]:
        out.append("  - " + b)
    return "\n".join(out)


def coverage_bounds(scores, all_targets, targets, limit, gloss):
    """Everything that narrowed what was actually measured, as report lines.

    No silent caps: a --limit, a model killed part-way, a card whose duration the ship
    gate needed and did not get -- each makes the numbers mean less than they look, and
    a partial run read as a complete one is how a candidate gets locked in on evidence
    that was never gathered. An empty list means nothing bounded the run."""
    bounds = []
    if len(targets) < len(all_targets):
        bounds.append(f"--limit {limit} judged {len(targets)} of {len(all_targets)} target lines in this episode")
    if not gloss["names"]:
        bounds.append("no glossary names loaded — the name-edit column and the phonetic-name guard have nothing to match")
    for s in scores:
        if s["missing"]:
            bounds.append(f"{s['model']} finished only {s['scored']} of {s['targets']} lines")
        if s["no_duration"]:
            bounds.append(f"{s['model']}: {s['no_duration']} card(s) had no duration, so accept_repair could not be run on them")
    return bounds


def format_score_line(s):
    """The one-line score printed right after a model's own block, so a run killed later
    still leaves that model's numbers behind, not just its raw output."""
    if not s["scored"]:
        return f"  SCORE {s['model']}: no results"
    return (
        f"  SCORE {s['model']}: ship {s['admitted']}/{s['scored']} | inert {s['inert']} | "
        f"names {s['name_edits']} | err {s['errors'] + s['empties']} | {s['avg_latency_s']:.1f}s/line"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="captured faster-whisper dump (needs a GPU re-transcribe)")
    ap.add_argument("--conf", help="a production <stem>.dubtitles.conf.json (what repair.py reads)")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434/api/generate")
    ap.add_argument("--models", nargs="+", default=["qwen3:8b", "qwen3.5:4b", "qwen2.5:7b"])
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument(
        "--shortlist",
        type=int,
        default=5,
        metavar="N",
        help="how many models to SUGGEST hand-judging (default 5). Every model is "
        "reported and ranked regardless — this only sizes the recommendation.",
    )
    ap.add_argument(
        "--llamacpp",
        nargs="*",
        default=[],
        metavar="NAME=URL",
        help="serve these model names from a llama.cpp /completion endpoint "
        "instead of Ollama (raw prompt — mirrors repair.py exactly)",
    )
    ap.add_argument(
        "--llamacpp-chat",
        nargs="*",
        default=[],
        metavar="NAME=URL",
        help="same, but via /v1/chat/completions so the model's chat template "
        "is applied and thinking is disabled (needed by templated instruct "
        "models; repair.py's raw /completion path cannot drive them)",
    )
    a = ap.parse_args()

    llamacpp = parse_llamacpp_specs(a.llamacpp)
    llamacpp_chat = parse_llamacpp_specs(a.llamacpp_chat)
    gloss = glossary.load(a.glossary)
    cards = load_cards(a.raw, a.conf)
    for c in cards:  # deterministic layer first (as in prod)
        c["text"] = glossary.correct(c["text"], gloss)[0]
    all_targets = [c for c in cards if repair.is_target(c, gloss)]
    targets = all_targets[: a.limit]
    prompts = [repair.build_prompt(c["text"], "", gloss) for c in targets]  # glossary-only (mp4)
    print(f"cards={len(cards)} targets={len(targets)} of {len(all_targets)} (--limit {a.limit})  models={a.models}\n")

    # model-OUTER so each model loads once (avoids reload thrash on the 8GB GPU).
    # Each model's block is printed AS SOON AS that model finishes: these runs can take
    # hours when a candidate spills to CPU, and buffering everything to the end meant a
    # wall-clock kill threw away the models that had already completed. The per-model
    # SCORE line lands with that block for the same reason.
    outs = {m: [] for m in a.models}
    totals = dict.fromkeys(a.models, 0.0)
    scores = []
    for m in a.models:
        for n, p in enumerate(prompts, 1):
            out, dt = ask(a.ollama, m, p, llamacpp, llamacpp_chat)
            outs[m].append(out)
            totals[m] += dt
            print(f"    [{m} {n}/{len(prompts)}] {dt:5.1f}s  {out[:70]}", flush=True)
        print(format_model_block(m, targets, outs[m], totals[m]), flush=True)
        s = score_model(m, targets, outs[m], totals[m], gloss)
        scores.append(s)
        print(format_score_line(s), flush=True)

    print("\n=== SIDE BY SIDE ===")
    for i, c in enumerate(targets):
        print("ORIG:", c["text"])
        for m in a.models:
            got = outs[m][i] if i < len(outs[m]) else "<no result>"
            print(f"  {m:16}: {got}")
        print()

    print(format_summary(rank_models(scores, a.shortlist), coverage_bounds(scores, all_targets, targets, a.limit, gloss)))


if __name__ == "__main__":
    main()
