#!/usr/bin/env python3
"""C1 model bake-off: run the candidate repair models on REAL transcription target
lines and print a side-by-side comparison for judging, so REPAIR_MODEL is locked by
evidence on the actual hardware (not guessed).

Pipeline: load cards -- either a captured raw whisper dump (--raw, reflowed here) or a
production <stem>.dubtitles.conf.json (--conf, already reflowed; the same file repair.py
consumes, so the models are judged on exactly the lines production sends them) --
-> apply the deterministic glossary correction -> pick the repair targets (is_target) ->
ask each model to repair each target -> print orig vs each model, then SCORE every model
and suggest a shortlist to hand-judge. By default the prompt is glossary-only; production's
normal path is ANCHORED (the line plus the overlapping line of the video's embedded English
subtitle track), which the two-step --dump-refs / --refs mode reproduces: the video is only
needed for the first step, so the model runs can happen on a machine without the media.

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

  # anchored, step 1 (where the video is; no model calls; --limit 0 = every target):
  python3 tools/bakeoff.py --conf "/media/.../Ep.dubtitles.conf.json" \\
      --glossary "glossaries/One Pace.json" --video "/media/.../Ep.mkv" \\
      --dump-refs refs.json --limit 0
  # anchored, step 2 (anywhere; targets without a fansub line are skipped unless
  # --include-unanchored or the glossary sets unanchored_repair):
  python3 tools/bakeoff.py --conf "Ep.dubtitles.conf.json" --glossary "glossaries/One Pace.json" \\
      --refs refs.json --models qwen3:8b qwen2.5:7b

  # any OpenAI-compatible API (key is read from the env var NAMED by --key-env):
  python3 tools/bakeoff.py --conf ... --models vendor/model-x \\
      --openai-url https://api.example.com/v1/chat/completions --key-env EXAMPLE_API_KEY

No GPU needed locally — the models run on the Ollama host. Built with help of Claude.
"""

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
import common  # noqa: E402
import glossary  # noqa: E402
import hallucination  # noqa: E402
import ordering  # noqa: E402
import qc  # noqa: E402
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


def _sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def dump_refs(conf_path, cards, gloss, video, limit, sample, glossary_path=""):
    """Anchored step 1: the fansub reference for each target, exactly as repair.process
    selects it, as a JSON-able dict. Needs the video; makes no model calls.

    ``cards`` must be the RAW conf rows -- process() uses the conf as generate.py wrote it and
    never re-runs glossary.correct on it, so is_target, bad_source_window, the dumped text and
    the prev/next lines all see that same raw text. (main() therefore skips its correction
    pass in the anchored modes.) ``idx`` is the row's position in the conf list, which --refs
    keys on; ``start``/``end`` let --refs notice a conf that was retimed since. ``limit`` 0
    means every target. ``episode``/``arc`` are what process() passes to build_prompt.
    ``glossary_path`` is fingerprinted (sha256 of the file) so --refs can tell a changed glossary."""
    ivals = common.dialogue_intervals(video)
    rec = qc.Recorder()
    picked = [(i, c) for i, c in enumerate(cards) if repair.is_target(c, gloss)]
    out = []
    for i, c in sample_targets(picked, limit, sample):
        # Same two lines as repair.process: S-6 bad source window -> no reference, else the
        # overlap on the SOURCE window (C6).
        if hallucination.bad_source_window(c, rec=rec):
            ref = ""
        else:
            ref = repair.overlap_ref(ivals, c.get("source_start", c["start"]), c.get("source_end", c["end"]))
        out.append(
            {
                "idx": i,
                "text": c["text"],
                "ref": ref,
                "prev": cards[i - 1]["text"] if i > 0 else "",
                "next": cards[i + 1]["text"] if i + 1 < len(cards) else "",
                "start": c.get("start"),
                "end": c.get("end"),
                "source_start": c.get("source_start"),
                "source_end": c.get("source_end"),
            }
        )
    return {
        "conf": os.path.basename(conf_path),
        "cards": len(cards),
        "episode": ordering.episode_key(video),
        "arc": glossary.arc_for(video),
        "glossary_sha256": _sha256_file(glossary_path) if glossary_path else None,
        "targets": out,
    }


def load_refs(refs_path, cards, conf_path, allow_conf_mismatch=False, glossary_path="", allow_glossary_mismatch=False):
    """Anchored step 2: targets from a --dump-refs file, as card dicts carrying their own
    ``_ref`` / ``_prev`` / ``_next`` / ``_arc`` / ``_episode``. ``cards`` are the RAW conf rows.

    Every way the file can disagree with the conf is a different bake-off than the one the refs
    were cut for, so each exits with a message naming the problem: another conf, a different
    card count, a duplicate or non-integer idx, a target with no text, a card retimed since, or
    text that differs from the conf's."""
    doc = json.load(open(refs_path))
    if not isinstance(doc, dict) or not isinstance(doc.get("targets"), list):
        sys.exit(f"{refs_path}: not a --dump-refs file (expected an object with a 'targets' list)")
    if doc.get("conf") != os.path.basename(conf_path) and not allow_conf_mismatch:
        sys.exit(
            f"{refs_path}: cut from {doc.get('conf')!r}, but --conf is {os.path.basename(conf_path)!r} "
            "(--allow-conf-mismatch if it is a renamed copy)"
        )
    dumped_sha = doc.get("glossary_sha256")
    if dumped_sha and glossary_path and not allow_glossary_mismatch:
        now = _sha256_file(glossary_path)
        if now != dumped_sha:
            sys.exit(
                f"{refs_path}: cut with glossary sha256 {dumped_sha[:12]}, but --glossary is {now[:12]} "
                "(--allow-glossary-mismatch to run anyway)"
            )
    if doc.get("cards") != len(cards):
        sys.exit(f"{refs_path}: cut from a conf with {doc.get('cards')} cards, this one has {len(cards)}")
    out, seen = [], set()
    for t in doc["targets"]:
        i = t.get("idx") if isinstance(t, dict) else None
        if type(i) is not int or not 0 <= i < len(cards):
            sys.exit(f"{refs_path}: idx {i!r} is not a card in this conf ({len(cards)} cards)")
        if i in seen:
            sys.exit(f"{refs_path}: duplicate idx {i}")
        seen.add(i)
        if not isinstance(t.get("text"), str):
            sys.exit(f"{refs_path}: idx {i} has no 'text'")
        if cards[i]["text"] != t["text"]:
            sys.exit(
                f"{refs_path}: idx {i} does not match this conf: refs file has {t['text']!r}, "
                f"conf card is {cards[i]['text']!r} (wrong --conf?)"
            )
        for k in ("start", "end", "source_start", "source_end"):
            if k in t and t[k] != cards[i].get(k):
                sys.exit(f"{refs_path}: idx {i} was retimed since the dump ({k} {t[k]!r} -> {cards[i].get(k)!r})")
        out.append(
            {
                **cards[i],
                "_ref": t.get("ref", ""),
                "_prev": t.get("prev", ""),
                "_next": t.get("next", ""),
                "_arc": doc.get("arc"),
                "_episode": doc.get("episode"),
            }
        )
    return out


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


def parse_extra_body(raw):
    """``--extra-body`` JSON object -> dict (exit on anything else, like the other arg parsers)."""
    if not raw:
        return {}
    try:
        extra = json.loads(raw)
    except ValueError as e:
        sys.exit(f"--extra-body is not valid JSON: {e}")
    if not isinstance(extra, dict):
        sys.exit("--extra-body must be a JSON object")
    return extra


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would re-send a redirected POST (as a GET) with the Authorization header to
    whatever host the Location names. Refuse: the 3xx surfaces as an HTTPError instead."""

    def redirect_request(self, *a, **k):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _post_json(url, body, timeout=180, headers=None, follow_redirects=True):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}
    )
    opener = urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open
    with opener(req, timeout=timeout) as r:
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


def _retry_after(err, default=5.0, cap=60.0):
    """Seconds to wait after a 429. Only a finite number of seconds in 0..cap is believed;
    nan, inf, negatives, an HTTP-date or garbage all fall back to ``default``."""
    try:
        wait = float(err.headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return default
    return wait if math.isfinite(wait) and 0 <= wait <= cap else default


def _dig(obj, *path):
    """obj[path[0]][path[1]]... through dicts only; None when anything on the way is not one."""
    for p in path:
        obj = obj.get(p) if isinstance(obj, dict) else None
    return obj


def _usage_of(resp):
    u = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(u, dict):
        return None
    usage = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}
    cached = _dig(u, "prompt_tokens_details", "cached_tokens")
    if cached is not None:
        usage["cached_tokens"] = cached
    return usage


def _error_label(e):
    """What may be printed about a failure. Never str(e): http.client's ValueError quotes the
    Authorization header value, and a provider's error body may echo the key."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} redirect refused" if 300 <= e.code < 400 else f"HTTP {e.code}"
    name = type(e).__name__
    if isinstance(e, urllib.error.URLError):
        name += f"({type(e.reason).__name__})"
    return name


def ask_openai(url, model, prompt, key_env, extra_body=None, usage_sink=None, max_tokens=1024):
    """Any OpenAI-compatible chat API; mirrors repair.llm_openai (same body and headers).

    The key is read from the env var NAMED ``key_env`` and never printed (a key with spaces or
    control characters exits naming only the variable). HTTP 429 is the provider throttling us,
    not the model saying nothing, so it is retried once (Retry-After honoured when it is 0..60 s,
    else 5 s) and, if it persists, reported as ``<ERROR rate-limited ...>`` -- a dead call in the
    score, never an <EMPTY>. A reply cut off at max_tokens with no content is
    ``<ERROR truncated ...>``. Redirects are refused.

    The returned latency covers the last attempt only: a Retry-After sleep is not model time.
    ``usage_sink`` (a list) gets exactly one entry per call: the token counts from ``usage``
    (``cached_tokens`` when the provider reports it) or None."""
    usage = None
    raw = os.environ.get(key_env, "")
    key = repair.clean_api_key(raw)
    if raw.strip() and key is None:
        sys.exit(f"the key in env var {key_env} contains spaces or control characters (CRLF .env?)")
    t0 = time.monotonic()
    if not key:
        out = f"<ERROR env var {key_env} is not set>"
    else:
        body = {
            "temperature": 0,
            "max_tokens": max_tokens,
            **(extra_body or {}),
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {key}", "User-Agent": "DubTitlerr/repair"}
        out = None
        for attempt in (0, 1):
            t0 = time.monotonic()
            try:
                resp = _post_json(url, body, headers=headers, follow_redirects=False)
                choice = resp["choices"][0]
                out = _first_line((choice["message"].get("content") or "").strip())
                if not out:
                    truncated = choice.get("finish_reason") == "length"
                    out = "<ERROR truncated (finish_reason=length)>" if truncated else "<EMPTY no content>"
                usage = _usage_of(resp)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt == 0:
                        time.sleep(_retry_after(e))
                        continue
                    out = "<ERROR rate-limited (HTTP 429)>"
                else:
                    out = f"<ERROR {_error_label(e)}>"
                break
            except Exception as e:
                out = f"<ERROR {_error_label(e)}>"
                break
    if usage_sink is not None:
        usage_sink.append(usage)
    return out, time.monotonic() - t0


def ask(ollama, model, prompt, llamacpp=None, llamacpp_chat=None, openai=None, usage_sink=None):
    raw = (llamacpp or {}).get(model)
    if raw:
        return ask_llamacpp(raw, prompt)
    chat = (llamacpp_chat or {}).get(model)
    if chat:
        return ask_llamacpp_chat(chat, prompt)
    if openai:
        return ask_openai(
            openai["url"], model, prompt, openai["key_env"], openai.get("extra_body"), usage_sink, openai.get("max_tokens", 1024)
        )
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

    A target carrying its own ``_ref`` (anchored mode) overrides ``ref`` for that target;
    ``ref_borrow`` counts outputs that import at least one word present in that reference
    and absent from the ASR line -- the model copying the fansub.

    Every rate is over ``scored`` (results actually produced) and is None when that is 0,
    so a model that returned nothing renders as a row rather than a ZeroDivisionError."""
    n = len(outs)
    inert = changed = errors = empties = admitted = name_edits = no_duration = ref_borrow = 0
    for i, out in enumerate(outs):
        orig = targets[i]["text"] if i < len(targets) else ""
        t_ref = targets[i].get("_ref", ref) if i < len(targets) else ref
        # <ERROR ...>/<EMPTY ...> mean the model produced NOTHING. They are never compared
        # against the original: "" or an error marker is not the model leaving the line
        # alone, and scoring it that way turns a dead backend into a clean no-op.
        if out.startswith("<ERROR"):
            errors += 1
            continue
        if out.startswith("<EMPTY"):
            empties += 1
            continue
        # Production ships glossary.correct(reply) (repair.py), so that is what is judged.
        new = glossary.correct(out, gloss)[0]
        if _norm(new) == _norm(orig):
            inert += 1
            continue
        changed += 1
        if changed_a_name(orig, new):
            name_edits += 1
        if repair.borrowed_from_ref(orig, new, t_ref):
            ref_borrow += 1
        dur = _card_duration(targets[i]) if i < len(targets) else None
        if dur is None:
            no_duration += 1
            continue
        # THE production gate itself, not a re-implemented bar: what this counts is what
        # would actually ship if this model were REPAIR_MODEL.
        if repair.accept_repair(orig, new, t_ref, dur, gloss):
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
        "ref_borrow": ref_borrow,
        "anchored": bool(targets) and all("_ref" in t for t in targets),
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
    anchored = any(s.get("anchored") for s in ranked)
    out = ["\n=== SCORES (ranked; safe-fix quality still needs your eyes) ==="]
    borrow_h = f" {'borrow':>6}" if anchored else ""
    out.append(
        f"  {'#':>2}  {'model':<{w}}  {'ship':>5} {'inert':>5} {'names':>5} {'err':>5}{borrow_h}  {'lines':>7}  {'s/line':>7}"
    )
    for s in ranked:
        lat = "    n/a" if s["avg_latency_s"] is None else f"{s['avg_latency_s']:7.1f}"
        lines = f"{s['scored']:>3}/{s['targets']:<3}"
        borrow = f" {s.get('ref_borrow', 0):>6}" if anchored else ""
        out.append(
            f"  {s['rank']:>2}  {s['model']:<{w}}  {_pct(s['admitted_rate'])} {_pct(s['inert_rate'])} "
            f"{_pct(s['name_edit_rate'])} {_pct(s['error_rate'])}{borrow}  {lines}  {lat}"
        )
    out.append("")
    ref_note = "each line's own fansub reference" if anchored else "no reference"
    out.append(f"  ship  = would repair.accept_repair() write it? (production's own gate, {ref_note})")
    out.append("  inert = reply identical to the input after casefold/whitespace — no fix offered")
    out.append("  names = touched a proper noun (right or wrong; pair with ship to tell which)")
    out.append("  err   = <ERROR>/<EMPTY> — the model produced nothing, NOT 'left the line alone'")
    if anchored:
        out.append("  borrow = outputs importing a word from the fansub reference that the ASR line lacked (copying)")
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


def sample_targets(targets, limit, mode="spread"):
    """Which of an episode's targets to judge on.

    "head" is `targets[:limit]` -- the original behaviour, kept so an earlier run can be
    reproduced exactly. It is a bad default: targets are in CARD ORDER, an episode opens with
    its theme song, and Whisper is least confident on sung lyrics, so songs crowd the front of
    the list. Measured on One Pace S31E06, the first 15 of 212 targets were ALL opening-song
    lines with not one proper noun among them -- which let an 8-model bake-off run to
    completion while being unable to measure name handling at all.

    "spread" walks the whole episode at an even stride, so dialogue, names and songs appear in
    proportion to how the episode actually contains them. Order is preserved and the first
    target is always included, so the sample still reads like the episode."""
    if limit <= 0 or len(targets) <= limit:
        return list(targets)
    if mode == "head":
        return list(targets[:limit])
    stride = len(targets) / limit
    return [targets[int(i * stride)] for i in range(limit)]


def format_comparison(runs):
    """Every model's answer to the SAME line, one block per line.

    Ship rate cannot rank models on its own: 40% shipped may be 40% garbage, and 13% may be a
    model correctly leaving good lines alone. Whether a change is an improvement is the one
    judgment no counter makes, and making it requires reading what each model did to the same
    input, next to each other.

    `bakeoff.py` prints that side-by-side when every model runs in one invocation. A 6GB card
    holds one model at a time, so the pool runs one model per invocation and the comparison
    has to be rebuilt from the separate runs -- which is what this does.

    ``runs`` is {model: [{"orig", "out", "admitted"}, ...]}, each list in target order.
    A model that failed on a line is SHOWN as failed rather than omitted: a blank would read
    as "left it alone", which is a different and much better outcome than not answering."""
    models = list(runs)
    origs = []
    for rows in runs.values():
        for i, r in enumerate(rows):
            if i >= len(origs):
                origs.append(r["orig"])
    w = max((len(m) for m in models), default=0)
    out = ["\n=== WHAT EACH MODEL ACTUALLY DID (ship = production's gate would write it) ==="]
    for i, orig in enumerate(origs):
        out.append(f"\nORIG: {orig}")
        for m in models:
            rows = runs[m]
            if i >= len(rows):
                out.append(f"  {m:<{w}}  [no result — run ended before this line]")
                continue
            r = rows[i]
            mark = "ship" if r.get("admitted") else "  — "
            out.append(f"  {m:<{w}}  {mark}  {r['out']}")
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
        + (f" | borrow {s['ref_borrow']}" if s.get("anchored") else "")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="captured faster-whisper dump (needs a GPU re-transcribe)")
    ap.add_argument("--conf", help="a production <stem>.dubtitles.conf.json (what repair.py reads)")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434/api/generate")
    ap.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="model names (default: qwen3:8b qwen3.5:4b qwen2.5:7b; required with --openai-url)",
    )
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--json", help="also write per-line results here, for cross-model comparison")
    ap.add_argument(
        "--sample",
        choices=("spread", "head"),
        default="spread",
        help="spread: sample evenly across the episode (default -- a head slice is all opening song); "
        "head: the first --limit targets, the pre-2026-08-31 behaviour",
    )
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
    ap.add_argument(
        "--openai-url",
        default="",
        help="send the --models names (as the request's \"model\") to this OpenAI-compatible "
        "chat/completions URL instead of Ollama (OpenRouter, Kilo, CommandCode, NVIDIA, ...); "
        "names also listed in --llamacpp / --llamacpp-chat go there instead. Needs --models and --key-env",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=repair.env_int("REPAIR_MAX_TOKENS", 1024, lo=1),
        help="max_tokens for --openai-url requests (default: $REPAIR_MAX_TOKENS or 1024)",
    )
    ap.add_argument("--key-env", default="", metavar="NAME", help="NAME of the env var holding the API key (with --openai-url)")
    ap.add_argument(
        "--extra-body", default="", metavar="JSON", help="JSON object merged into the body, e.g. '{\"enable_thinking\": false}'"
    )
    ap.add_argument(
        "--video",
        help="the episode's video (with --dump-refs): its embedded English subtitle track supplies the fansub reference",
    )
    ap.add_argument(
        "--dump-refs",
        metavar="OUT.json",
        help="anchored step 1: write each target's fansub reference to OUT.json and exit "
        "(needs --conf and --video; no model calls; --limit 0 = every target)",
    )
    ap.add_argument(
        "--refs",
        metavar="REFS.json",
        help="anchored step 2: judge the models on the targets in this --dump-refs file, with "
        "their references in the prompt (needs --conf; the file's targets are used as-is, "
        "--limit/--sample do not apply)",
    )
    ap.add_argument(
        "--include-unanchored",
        action="store_true",
        help="with --refs: also judge targets that have no fansub reference (production skips "
        "them unless the glossary sets unanchored_repair)",
    )
    ap.add_argument(
        "--allow-conf-mismatch",
        action="store_true",
        help="with --refs: accept a refs file cut from a conf with a different file name (a renamed copy)",
    )
    ap.add_argument(
        "--allow-glossary-mismatch",
        action="store_true",
        help="with --refs: run even though the glossary file differs from the one the refs were cut with",
    )
    a = ap.parse_args()

    if a.dump_refs and a.refs:
        sys.exit("--dump-refs and --refs are two separate steps; give one")
    if (a.dump_refs or a.refs) and not a.conf:
        sys.exit("--dump-refs / --refs work from a production --conf")
    if a.dump_refs and not a.video:
        sys.exit("--dump-refs needs --video (the file whose embedded English subtitles are the reference)")
    if a.refs and not a.glossary:
        sys.exit("--refs needs --glossary (the prompt's reference spellings and the output correction come from it)")
    if a.dump_refs and not a.glossary:
        # is_target consults glossary.name_suspect: a dump cut without the glossary silently drops those targets.
        sys.exit("--dump-refs needs --glossary (it decides which lines are targets)")

    openai = None
    if a.openai_url:
        if not a.key_env:
            sys.exit("--openai-url needs --key-env NAME")
        if not a.models:
            sys.exit("--openai-url needs an explicit --models list (the Ollama defaults must never be sent to a provider)")
        raw_key = os.environ.get(a.key_env, "")
        if not raw_key.strip():
            sys.exit(f"--key-env: env var {a.key_env} is not set")
        if repair.clean_api_key(raw_key) is None:
            sys.exit(f"--key-env: the key in env var {a.key_env} contains spaces or control characters (CRLF .env?)")
        openai = {
            "url": a.openai_url,
            "key_env": a.key_env,
            "extra_body": parse_extra_body(a.extra_body),
            "max_tokens": a.max_tokens,
        }
    if not a.models:
        a.models = ["qwen3:8b", "qwen3.5:4b", "qwen2.5:7b"]
    llamacpp = parse_llamacpp_specs(a.llamacpp)
    llamacpp_chat = parse_llamacpp_specs(a.llamacpp_chat)
    gloss = glossary.load(a.glossary)
    cards = load_cards(a.raw, a.conf)
    if not (a.dump_refs or a.refs):
        # Glossary-only mode: deterministic layer first. The anchored modes keep the RAW conf text
        # instead, because that is what repair.process sees (it never re-corrects the conf).
        for c in cards:
            c["text"] = glossary.correct(c["text"], gloss)[0]
    if a.dump_refs:
        doc = dump_refs(a.conf, cards, gloss, a.video, a.limit, a.sample, a.glossary)
        with open(a.dump_refs, "w") as f:
            json.dump(doc, f, indent=2)
        with_ref = sum(1 for t in doc["targets"] if t["ref"])
        n = len(doc["targets"])
        print(f"targets={n} with_ref={with_ref} without_ref={n - with_ref} -> {a.dump_refs}")
        return
    extra_bounds = []
    if a.refs:
        entries = load_refs(a.refs, cards, a.conf, a.allow_conf_mismatch, a.glossary, a.allow_glossary_mismatch)
        targets = [t for t in entries if a.include_unanchored or not repair.skips_unanchored(t["_ref"], gloss)]
        all_targets = targets  # --limit does not apply here; the dump already chose
        if len(targets) < len(entries):
            extra_bounds.append(
                f"{len(entries) - len(targets)} target(s) skipped: no fansub reference, and production skips those "
                "(--include-unanchored, or unanchored_repair in the glossary, judges them)"
            )
        prompts = [
            repair.build_prompt(t["text"], t["_ref"], gloss, t["_prev"], t["_next"], t["_arc"], t["_episode"]) for t in targets
        ]
        print(
            f"cards={len(cards)} targets={len(targets)} of {len(entries)} in {a.refs} "
            f"({len(entries) - len(targets)} skipped for no ref)  models={a.models}\n"
        )
    else:
        all_targets = [c for c in cards if repair.is_target(c, gloss)]
        targets = sample_targets(all_targets, a.limit, a.sample)
        prompts = [repair.build_prompt(c["text"], "", gloss) for c in targets]  # glossary-only (mp4)
        print(f"cards={len(cards)} targets={len(targets)} of {len(all_targets)} (--limit {a.limit})  models={a.models}\n")

    # model-OUTER so each model loads once (avoids reload thrash on the 8GB GPU).
    # Each model's block is printed AS SOON AS that model finishes: these runs can take
    # hours when a candidate spills to CPU, and buffering everything to the end meant a
    # wall-clock kill threw away the models that had already completed. The per-model
    # SCORE line lands with that block for the same reason.
    outs = {m: [] for m in a.models}
    totals = dict.fromkeys(a.models, 0.0)
    usages = {m: [] for m in a.models}
    scores = []
    for m in a.models:
        for n, p in enumerate(prompts, 1):
            out, dt = ask(a.ollama, m, p, llamacpp, llamacpp_chat, openai, usages[m])
            outs[m].append(out)
            totals[m] += dt
            print(f"    [{m} {n}/{len(prompts)}] {dt:5.1f}s  {out[:70]}", flush=True)
        print(format_model_block(m, targets, outs[m], totals[m]), flush=True)
        s = score_model(m, targets, outs[m], totals[m], gloss)
        scores.append(s)
        print(format_score_line(s), flush=True)
        if a.json:
            # Per-line rows, so a pool run on a card that holds one model at a time can be
            # reassembled into the side-by-side this tool prints when every model runs at
            # once. `admitted` is repair.accept_repair's verdict, recorded per line rather
            # than only aggregated, because "is this change an improvement" is judged line by
            # line and a rate cannot be read back into one.
            rows = []
            for i, (c, out) in enumerate(zip(targets, outs[m])):
                dur = (c.get("end") or 0) - (c.get("start") or 0)
                ref = c.get("_ref", "")  # anchored targets carry their own; glossary-only runs score with none
                live = dur > 0 and not out.startswith(("<ERROR", "<EMPTY"))
                shipped = glossary.correct(out, gloss)[0] if live else out  # as production ships it
                admitted = bool(live and repair.accept_repair(c["text"], shipped, ref, dur, gloss))
                row = {"orig": c["text"], "out": out, "admitted": admitted}
                if i < len(usages[m]) and usages[m][i]:
                    row.update(usages[m][i])  # prompt_tokens / completion_tokens / cached_tokens
                if a.refs:
                    row["ref"] = c["_ref"]
                rows.append(row)
            with open(a.json, "w") as f:
                json.dump({m: rows}, f, indent=2)

    print("\n=== SIDE BY SIDE ===")
    for i, c in enumerate(targets):
        print("ORIG:", c["text"])
        for m in a.models:
            got = outs[m][i] if i < len(outs[m]) else "<no result>"
            print(f"  {m:16}: {got}")
        print()

    bounds = [*coverage_bounds(scores, all_targets, targets, a.limit, gloss), *extra_bounds]
    print(format_summary(rank_models(scores, a.shortlist), bounds))


if __name__ == "__main__":
    main()
