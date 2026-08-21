#!/usr/bin/env python3
"""REPAIR stage (gold) — fix garbled low-confidence dub dialogue using the video's
own embedded subtitle (a *different* translation of the same scene) as a semantic
anchor, via a local LLM. Runs between generate.py and the assemble stage.

Whisper sometimes mishears hard audio (overlap, SFX, mumbling). Those segments
carry a low ``avg_logprob`` (recorded by generate.py in ``<stem>.dubtitles.conf.json``).
For each such SPEECH segment (low logprob but not music — ``no_speech_prob`` low),
we find the embedded *dialogue* line(s) overlapping that time window and ask a
local LLM to reconstruct the most likely English-DUB line: keep the transcription's
wording where it's plausible, use the subtitle only to resolve the garbled parts,
never copy the subtitle verbatim (dub != sub — localization differs).

Then the ``.srt`` is rewritten from the (possibly repaired) confidence rows and a
``<stem>.dubtitles.repair.csv`` audit (orig -> repaired) is written. Timing untouched.
A ``<stem>.dubtitles.repair-summary.json`` (targets/repaired/skipped/latency stats/model(s))
is written alongside it (V2 A10).

C1: targets are broadened to mid-confidence-AND-lower OR name-suspect lines; the show
glossary is injected into a STRICT prompt (canonical spellings, never invent/swap a name);
the LLM only runs on lines with a fansub anchor (the bake-off showed glossary-only repair
hallucinates names even on qwen3:8b, so no-anchor lines keep the deterministic text); the
LLM output is run back through the deterministic correction to enforce canon.

CPU/network only — the LLM runs on the 2070 (Ollama) or, optionally, a llama.cpp server.
Env:
  OLLAMA_URL           default http://ollama.local:11434/api/generate
  REPAIR_MODEL         default qwen3:8b   (locked by the C1 bake-off)
  REPAIR_BACKEND         ollama | llamacpp  (default ollama — V2 A1)
  REPAIR_LLAMACPP_URL    default http://192.168.1.232:8080/v1/chat/completions
                         (chat endpoint: the raw /completion path applies no chat
                         template and yields empty output from instruct models)
  REPAIR_MODEL_SECONDARY default REPAIR_MODEL — two-pass re-check model (V2 A3; no-op if equal)
  REPAIR_TIMEOUT_CONNECT default 10   (seconds; V2 A2)
  REPAIR_TIMEOUT_READ    default 120  (seconds; V2 A2)
  MAX_REF_BORROW default 3     (reject a repair importing this many NEW words that are
                                present in the fansub reference — see accept_repair)
  LEN_RATIO_MIN default 0.6    (…and reject one whose length ratio leaves this band)
  LEN_RATIO_MAX default 1.5
                               C2/C4/C5: on top of these, a repair is rejected unless the
                               RESULT still fits the card — <=MAX_LINES lines of <=MAX_LINE
                               after reflow.wrap_balance, <=MAX_CHARS, and <=MAX_CPS at the
                               card's DISPLAY duration. Card timing is immutable in repair
                               (C1), so the repair gives way, never the timing. The
                               secondary-model pass goes through the identical gate.
  LOGPROB_MIN   default -0.4   (mid-confidence-and-lower; below this is a repair target)
  NSP_MAX       default 0.5    (…and below this no_speech_prob — i.e. it IS speech)
  GLOSSARY_DIR  default /config/glossaries   (per-show glossary, resolved from the path)
  SUB_LANGS     accepted embedded-sub languages (default eng,en,und,) -- read by
                common.dialogue_intervals (T1: hoisted out of this module)
  MEDIA_UID/GID default 1000/100
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""
import csv
import http.client
import json
import os
import re
import sys
import time
import urllib.parse

import glossary
import unresolved
import reflow
from common import MEDIA_GID, MEDIA_UID, dialogue_intervals, find_video, out_for, ts_srt

OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
MODEL = os.environ.get("REPAIR_MODEL", "qwen3:8b")
REPAIR_BACKEND = os.environ.get("REPAIR_BACKEND", "ollama")
LLAMACPP_URL = os.environ.get("REPAIR_LLAMACPP_URL",
                              "http://192.168.1.232:8080/v1/chat/completions")
MODEL_SECONDARY = os.environ.get("REPAIR_MODEL_SECONDARY", MODEL)
TIMEOUT_CONNECT = float(os.environ.get("REPAIR_TIMEOUT_CONNECT", "10"))
TIMEOUT_READ = float(os.environ.get("REPAIR_TIMEOUT_READ", "120"))
LOGPROB_MIN = float(os.environ.get("LOGPROB_MIN", "-0.4"))   # mid-confidence-and-lower (C1)
NSP_MAX = float(os.environ.get("NSP_MAX", "0.5"))
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"

def log(*a): print(*a, flush=True)


def glossary_for(path, gloss_dir=GLOSSARY_DIR):
    """Resolve the show glossary for an episode by walking up to the first ancestor
    directory that has a matching <Show>.json in the glossary dir; else a no-op glossary."""
    d = os.path.dirname(os.path.abspath(path))
    while d and d != os.path.dirname(d):
        gp = os.path.join(gloss_dir, os.path.basename(d) + ".json")
        if os.path.exists(gp):
            return glossary.load(gp)
        d = os.path.dirname(d)
    return glossary.load("")


LOW_WORD_PROB = 0.25   # V2 A7: a single word this unconfident marks the whole card a target


def has_low_prob_word(c):
    """True if any per-word linear probability in ``word_probs`` (V2 A6, generate.py) is
    below LOW_WORD_PROB -- catches a single wildly-mis-heard word hiding inside a card
    whose avg_logprob still looks fine overall. Missing/empty ``word_probs`` (older
    conf.json files predating A6, or a card generate.py couldn't join any words to) ->
    False, backward-compatible."""
    return any(p < LOW_WORD_PROB for p in c.get("word_probs", []))


def is_target(c, gloss):
    """A conf row to send to the LLM: it must be speech (low no_speech_prob) AND either
    mid-confidence-or-lower, name-suspect, OR containing a very-low-confidence word."""
    if c.get("no_speech_prob", 1.0) > NSP_MAX:
        return False
    return (c.get("avg_logprob", 0.0) < LOGPROB_MIN or has_low_prob_word(c)
            or glossary.name_suspect(c.get("text", ""), gloss))


def _glossary_terms(gloss):
    terms = list(gloss["names"]) + list(gloss["phrases"])
    terms += list(gloss["token_fixes"].values()) + list(gloss["phrase_fixes"].values())
    seen, out = set(), []
    for t in terms:                       # de-dup, preserve order
        if t not in seen:
            seen.add(t); out.append(t)
    # C12: cap the prompt size on WHOLE-TERM boundaries -- a raw [:1000] slice can cut a
    # name in half mid-word, which would feed the model a garbled "canonical spelling".
    result = ""
    for t in out:
        candidate = t if not result else f"{result}, {t}"
        if len(candidate) > 1000:
            break
        result = candidate
    return result


def build_prompt(asr, sub, gloss, prev_text="", next_text=""):
    """Build the repair prompt. Every element here is the result of a measured sweep over
    real conf.json targets (3 shows x 40 targets, temperature 0), not authorship taste.

    Two failure modes had to be balanced against each other:
      * qwen3.5:9b, told only what NOT to do, rewrote 42% of lines and pasted glossary
        names over correct text ("Border Control" -> "Cipher Pol", "Neptune" ->
        "Nefertari Vivi", "Uchihime" -> "Uchiha" -- a name from another franchise).
      * nanbeige4.2-3b, given the same prohibitions, went inert: 0 safe fixes across 120
        targets, returning the input verbatim, losing the real repairs it used to make.

    What resolved both at once:
      * the name list framed as VERIFICATION ONLY, never as material to apply;
      * an explicit POSITIVE DUTY -- rules phrased only as prohibitions produce a model
        that does nothing, which is not a repair stage;
      * NO worked example of leaving a name alone. Counter-intuitive, but it over-anchored
        inaction: removing it was the single biggest gain in the sweep (nanbeige 12 -> 16
        safe fixes, qwen 6 -> 23) *and* name edits went down for both;
      * nothing after the ASR line. An earlier version put a trailing "Remember:" reminder
        there and the model echoed that rule text into the subtitle output.

    Measured on 120 targets: qwen 6 -> 23 safe fixes (17 -> 14 name edits), nanbeige
    0 -> 16 safe fixes (1 -> 2 name edits), zero prompt leaks or length blowups for either.

    prev_text/next_text are extra context only -- never part of what gets corrected."""
    names = _glossary_terms(gloss)
    head = "You fix speech-recognition errors in one English-dub subtitle line.\n"
    name_line = (f"Reference spellings (VERIFICATION ONLY - this is NOT a list of names to "
                 f"insert): {names}.\n") if names else ""
    ref_intro = ("A DIFFERENT translation of this moment is quoted below; use it only to "
                 "resolve garbled words and confirm names, never to copy its wording.\n") if sub else ""
    rules = (
        "Rules:\n"
        "- You MUST fix: run-together sentences with missing punctuation, missing "
        "capitalisation at a sentence start, and obviously garbled ordinary words.\n"
        "- You MUST NOT change any proper noun unless it is an obvious phonetic "
        "misspelling of a reference spelling above.\n"
        "- Never insert a name that is not already in the line.\n"
        "- Do NOT turn ordinary words into names. Keep the wording and length almost identical.\n\n"
        'Example -> ASR line: it worked Now we run\n'
        'Corrected line: It worked. Now we run.\n'
        '(Two sentences were run together with no punctuation. That IS damage - fix it.)\n\n'
        "Return ONLY the corrected line - no quotes, no notes, no rule text.\n\n")
    # C9: the fansub reference is untrusted third-party text -- keep it wrapped in an XML
    # tag so it reads as quoted DATA, not instructions (prompt-injection guard). Context
    # and reference come BEFORE the ASR line: anything trailing it gets echoed into output.
    prev_line = f'Previous line (for context): "{prev_text}"\n' if prev_text else ""
    next_line = f'Next line (for context): "{next_text}"\n' if next_text else ""
    ref_line = f"<official_subtitle_reference>{sub}</official_subtitle_reference>\n" if sub else ""
    return (f"{head}{name_line}{ref_intro}{rules}"
            f"{prev_line}{next_line}{ref_line}"
            f"ASR line: {asr}\nCorrected line:")


def overlap_ref(ivals, a, b):
    hits = [t for (s, e, t) in ivals if e > a and s < b]   # any time overlap
    return " ".join(hits)[:300]


def _post_json(url, body):
    """POST body (dict) as JSON to url with separate connect (TIMEOUT_CONNECT) and read
    (TIMEOUT_READ) timeouts (V2 A2). stdlib's urllib.request.urlopen only exposes a single
    timeout for the whole call (connect + every read), so we go one layer lower via
    http.client: the connect timeout is set on the connection itself (used for connect()),
    then the read timeout is set on the underlying socket right after connecting."""
    parsed = urllib.parse.urlsplit(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=TIMEOUT_CONNECT)
    try:
        conn.connect()
        conn.sock.settimeout(TIMEOUT_READ)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn.request("POST", path, body=json.dumps(body).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {data[:200]!r}")
        return json.loads(data)
    finally:
        conn.close()


MAX_REF_BORROW = int(os.environ.get("MAX_REF_BORROW", "3"))
LEN_RATIO_MIN = float(os.environ.get("LEN_RATIO_MIN", "0.6"))
LEN_RATIO_MAX = float(os.environ.get("LEN_RATIO_MAX", "1.5"))

_WORD = re.compile(r"[a-z']+")


def _words(s):
    return _WORD.findall((s or "").lower())


def borrowed_from_ref(orig, new, ref):
    """Words the repair ADDED that are present in the fansub reference.

    These are the signature of the model treating the reference as the answer rather than
    as a disambiguation aid. Words already in the ASR line don't count (keeping them isn't
    borrowing), and invented words absent from the reference don't either — that is
    hallucination, a different failure with its own guards."""
    had, have, in_ref = set(_words(orig)), _words(new), set(_words(ref))
    return [w for w in have if w not in had and w in in_ref]


def fits_card(text, dur, orig=None):
    """Whether ``text`` can be DISPLAYED legally on a card lasting ``dur`` seconds (C4).

    Validates the candidate as it will actually be written: through the same
    ``reflow.wrap_balance`` + flatten normalisation generate.py uses, so the thing checked
    is the thing shipped. Per line, not total only -- a total-char check passes text that
    is visually invalid (an 85-char card wraps to two legal 42-char lines but is one
    character over the card ceiling; a 49-char card whose word boundaries fall badly wraps
    to a 44-char line), and that blind spot is exactly how the library-wide wrapping defect
    survived. Line lengths are integer character counts, so only cps needs EPS."""
    wrapped = reflow.wrap_balance((text or "").replace("\n", " "))
    if not reflow.layout_faults(wrapped, dur):
        return True
    if orig is None:
        return False
    # The card ALREADY breaks the profile -- ~28% of cards are over cps, and A2
    # deliberately does not retime for cps. Refusing every repair on those would refuse
    # to fix `Zorro`->`Zoro` on a dense line, which is the exact case repair exists to
    # serve. Accept a repair that worsens NO dimension; reject one that worsens any.
    before = reflow.layout_metrics(reflow.wrap_balance((orig or "").replace("\n", " ")), dur)
    after = reflow.layout_metrics(wrapped, dur)
    return all(a <= b + reflow.EPS for a, b in zip(after, before))


def accept_repair(orig, new, ref, dur):
    """Whether to write ``new`` over ``orig`` on a card lasting ``dur`` seconds.

    A dubtitle must match the DUB AUDIO. The reference is a different translation of the
    same scene, so lifting its phrasing produces a subtitle that reads well and is wrong
    against the sound — the worst kind of error here, because it looks correct.

    Measured over every repair the library had accumulated before this guard: qwen3:8b
    imported reference words in 84.1% of its repairs (29.2% imported three or more),
    nanbeige in 52.5% (17.1%). Lines like "That's enough of that, idiots!" became "Hold
    it, you brats!" — the reference, verbatim. The old gate was a 0.4–2.5 length band,
    which a same-length rewrite sails straight through.

    C2: the length ratio cannot see readability. LEN_RATIO_MAX is 1.5, so 40 chars on a
    3.0s card (13 cps) may become 58 (19.3 cps) with nothing re-checking it. The card's
    timing is immutable here (C1) -- a repair that does not fit the card it is repairing
    is rejected, never accommodated by moving the card -- so ``dur`` is required, not
    optional: a caller that does not know the card cannot be allowed to skip the check.

    Kept deliberately permissive for the case the reference exists to serve: a single
    misheard proper noun corrected from it."""
    if not new:
        return False
    if new.lower() == (orig or "").lower():
        return False                                   # nothing changed
    ratio = len(new) / max(1, len(orig))
    if not (LEN_RATIO_MIN <= ratio <= LEN_RATIO_MAX):
        return False                                   # added or dropped a clause
    if not fits_card(new, dur, orig):
        return False                                   # unreadable/undisplayable on THIS card
    return len(borrowed_from_ref(orig, new, ref)) < MAX_REF_BORROW


def llm_ollama(prompt, model=None):
    """Ollama /api/generate backend (the original/default path — byte-for-byte the same
    request shape and response parsing as before A1's dispatch refactor)."""
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model or MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0}}
    try:
        out = _post_json(OLLAMA, body).get("response", "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        log("  llm fail:", e); return ""


def llm_llamacpp(prompt, model):
    """llama.cpp backend, via the OpenAI-compatible /v1/chat/completions endpoint.

    This previously posted a RAW prompt to /completion, which applies NO chat template.
    Verified against a live Nanbeige 4.2-3B server, that path returns nothing but newlines
    -- 200 tokens of "\n" -- because a templated instruct model never sees its template.
    It could only ever have worked for a base/completion model, so REPAIR_BACKEND=llamacpp
    was effectively broken for the models anyone would actually use.

    ``chat_template_kwargs.enable_thinking=false`` is required by this fork: with the
    template applied but thinking still on, the model spends its whole budget on
    reasoning_content and returns an empty message (measured empty after 114s at
    max_tokens=512; correct output in 4.3s with thinking off). An empty reply is treated as
    "no repair" -- never as text to embed, which would put the model's monologue in a
    subtitle.

    No "model" selector is sent (the server has exactly one model loaded); ``model`` is
    accepted for signature parity with llm_ollama and the two-pass dispatch."""
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0,
            "max_tokens": 80, "chat_template_kwargs": {"enable_thinking": False}}
    try:
        msg = _post_json(LLAMACPP_URL, body)["choices"][0]["message"]
        out = (msg.get("content") or "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        log("  llm fail:", e); return ""


def llm(prompt, model=None):
    """Dispatch to the backend configured by REPAIR_BACKEND (ollama|llamacpp, default
    ollama — matches pre-A1 behavior exactly). model=None uses the backend's default
    (REPAIR_MODEL); pass it explicitly for the two-pass secondary-model re-check (A3)."""
    if REPAIR_BACKEND == "llamacpp":
        return llm_llamacpp(prompt, model or MODEL)
    return llm_ollama(prompt, model)


def _needs_secondary_check(orig, new, gloss):
    """A3 two-pass trigger: the first-pass repair looks divergent enough to re-verify with
    the (usually stronger/slower) secondary model — either the length changed a lot, or a
    glossary name showed up in the output that wasn't in the original line. NOTE (spec
    correction): the name-appeared condition fires on ~every successful name repair by
    design — inserting the correct name IS the point of repair — so this is "re-verify all
    name-changing repairs," not a rare-case optimization."""
    ratio = len(new) / max(1, len(orig))
    if ratio < 0.6 or ratio > 1.5:
        return True
    for name in gloss["names"]:
        pat = r"\b" + re.escape(name) + r"\b"
        if re.search(pat, new, re.I) and not re.search(pat, orig, re.I):
            return True
    return False


def _p95(values):
    """Nearest-rank 95th percentile; no numpy dependency for one summary stat (A10)."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]


def process(conf_path):
    stem = conf_path[:-len(CONF_SUFFIX)]
    srt = stem + SRT_SUFFIX
    video = find_video(stem)
    # No conf.json is a normal state, not an error: tools/recover_dub_srt.py rebuilds the
    # sidecar straight out of the already-muxed track for episodes whose conf was long
    # since cleaned up, and merge_pass.sh calls repair.py unconditionally. That dialogue
    # was already repaired when it was first built, so there is nothing to redo.
    if not video or not os.path.exists(srt) or not os.path.exists(conf_path):
        return "skip"
    conf = json.load(open(conf_path))
    gloss = glossary_for(video)
    targets = [(i, c) for i, c in enumerate(conf) if is_target(c, gloss)]
    if not targets:
        return "clean"          # nothing to repair (e.g. S15E01)
    ivals = dialogue_intervals(video)
    audit, fixed, skipped_no_ref, rejected = [], 0, 0, 0
    rejected_secondary = 0                           # C5: second-pass output refused by the gate
    repaired_lines = []                              # A10: per-line detail for the summary
    for i, c in targets:
        # C6: select the reference on the SOURCE window -- where the audio actually was --
        # not the display window, which the timing layer may have stolen forward onto the
        # NEIGHBOUR's cue. The .get fallback keeps every pre-C6 sidecar working unchanged.
        ref = overlap_ref(ivals, c.get("source_start", c["start"]), c.get("source_end", c["end"]))
        if not ref:
            skipped_no_ref += 1
            # The counter alone made this indistinguishable from "repair ran and found
            # nothing wrong". Record the card so a human can see WHICH lines went unrepaired
            # and judge whether the release simply has no fansub or the anchor logic missed.
            unresolved.record(stem, "repair", "no_reference", original_text=c["text"],
                              source_start=c.get("source_start", c["start"]),
                              source_end=c.get("source_end", c["end"]),
                              avg_logprob=c.get("avg_logprob"))
            continue        # no fansub anchor -> skip the LLM. The bake-off showed glossary-only
                            # repair hallucinates names (Oimo->Zoro) even on qwen3:8b; without a
                            # reference the deterministic layer (hard_fixes) is the safe ceiling.
        prev_text = conf[i - 1]["text"] if i > 0 else ""
        next_text = conf[i + 1]["text"] if i + 1 < len(conf) else ""
        prompt = build_prompt(c["text"], ref, gloss, prev_text, next_text)
        t0 = time.monotonic()                              # V2 A2: per-call latency
        new = llm(prompt)
        latency_ms = round((time.monotonic() - t0) * 1000)
        if new:
            new = glossary.correct(new, gloss)[0]         # enforce canonical spelling on output
        # C2: the card's DISPLAY duration -- how long the viewer actually has to read it.
        # (source_start/source_end anchor the EVIDENCE window above; they are not what is
        # on screen.) Timing stays immutable: a repair that does not fit is rejected.
        dur = c["end"] - c["start"]
        if not accept_repair(c["text"], new, ref, dur):
            if new and new.lower() != c["text"].lower():
                rejected += 1          # surfaced in the summary so the guard stays visible
                # ...but the PROPOSAL was discarded, and it is the whole evidence a human
                # needs to judge whether the guard was right or overzealous.
                unresolved.record(stem, "repair", "rejected_guard",
                                  original_text=c["text"], proposed_text=new,
                                  reference=ref[:120],
                                  avg_logprob=c.get("avg_logprob"))
        else:
            # A3: re-verify divergent-looking repairs (esp. name changes) with the secondary
            # model. No-op by default (REPAIR_MODEL_SECONDARY == REPAIR_MODEL).
            if MODEL_SECONDARY != MODEL and _needs_secondary_check(c["text"], new, gloss):
                t1 = time.monotonic()
                new2 = llm(prompt, model=MODEL_SECONDARY)
                latency_ms += round((time.monotonic() - t1) * 1000)
                if new2:
                    new2 = glossary.correct(new2, gloss)[0]
                    # C5: a stronger model is still a model. Its output went straight over
                    # the first pass with no validation at all -- same gate, same card. When
                    # it fails, the already-accepted first-pass repair stands rather than the
                    # card being left garbled.
                    if new2 and accept_repair(c["text"], new2, ref, dur):
                        new = new2
                    elif new2 and new2.lower() != new.lower():
                        rejected_secondary += 1
            audit.append((c["text"], new, ref[:80], latency_ms))
            repaired_lines.append({"orig": c["text"], "repaired": new, "ref": ref[:80], "latency_ms": latency_ms})
            c["text"] = new; fixed += 1
    # rewrite srt from (possibly repaired) conf rows. conf.json stores text FLATTENED
    # (generate.py replaces '\n' with ' '), so re-wrap here or every episode that
    # passes through repair ships as unwrapped single lines -- which is exactly what
    # the library did until this fix.
    srt_out = out_for(srt); rep_out = out_for(stem + ".dubtitles.repair.csv")
    with open(srt_out, "w") as f:
        for i, c in enumerate(conf, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n"
                    f"{reflow.wrap_balance(c['text'])}\n\n")
    with open(rep_out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["orig", "repaired", "ref", "latency_ms"]); w.writerows(audit)
    # A10: per-show repair summary, written alongside the srt/csv
    lat_values = [r["latency_ms"] for r in repaired_lines]
    summary = {
        "targets": len(targets),
        "repaired": fixed,
        "skipped_no_ref": skipped_no_ref,
        "rejected_guard": rejected,      # model proposed an edit, accept_repair() refused it
        "rejected_secondary": rejected_secondary,   # C5: second pass refused, first pass kept
        "mean_latency_ms": round(sum(lat_values) / len(lat_values)) if lat_values else 0,
        "p95_latency_ms": round(_p95(lat_values)) if lat_values else 0,
        "model": MODEL,
        "model_secondary": MODEL_SECONDARY,
        "repaired_lines": repaired_lines,
    }
    summary_out = out_for(stem + ".dubtitles.repair-summary.json")
    with open(summary_out, "w") as f:
        json.dump(summary, f, indent=2)
    for p in (srt_out, rep_out, summary_out):
        try: os.chown(p, MEDIA_UID, MEDIA_GID)
        except OSError as e: log(f"chown failed for {p}: {e}")
    log(f"  targets={len(targets)} repaired={fixed}")
    return "repaired"


def main():
    args = sys.argv[1:]
    confs = list(args) if args else []     # explicit .conf.json paths, else walk roots
    if not confs:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for f in files:
                    if f.endswith(CONF_SUFFIX):
                        confs.append(os.path.join(dp, f))
    counts = {}
    for cp in sorted(confs):
        res = process(cp)
        counts[res] = counts.get(res, 0) + 1
        log(f"{res}: {os.path.basename(cp)}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
