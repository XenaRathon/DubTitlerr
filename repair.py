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

C1: targets are broadened to mid-confidence-AND-lower OR name-suspect lines; the show
glossary is injected into a STRICT prompt (canonical spellings, never invent/swap a name);
the LLM only runs on lines with a fansub anchor (the bake-off showed glossary-only repair
hallucinates names even on qwen3:8b, so no-anchor lines keep the deterministic text); the
LLM output is run back through the deterministic correction to enforce canon.

CPU/network only — the LLM runs on the 2070 (Ollama). Env:
  OLLAMA_URL    default http://ollama.local:11434/api/generate
  REPAIR_MODEL  default qwen3:8b   (locked by the C1 bake-off)
  LOGPROB_MIN   default -0.4   (mid-confidence-and-lower; below this is a repair target)
  NSP_MAX       default 0.5    (…and below this no_speech_prob — i.e. it IS speech)
  GLOSSARY_DIR  default /config/glossaries   (per-show glossary, resolved from the path)
  SUB_LANGS     accepted embedded-sub languages (default eng,en,und,)
  MEDIA_UID/GID default 1000/100
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""
import csv
import json
import os
import re
import sys
import tempfile
import urllib.request

import pysubs2

import glossary
from common import MEDIA_GID, MEDIA_UID, eng_sub_streams, find_video, out_for, ts_srt
from common import extract_sub as extract

OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
MODEL = os.environ.get("REPAIR_MODEL", "qwen3:8b")
LOGPROB_MIN = float(os.environ.get("LOGPROB_MIN", "-0.4"))   # mid-confidence-and-lower (C1)
NSP_MAX = float(os.environ.get("NSP_MAX", "0.5"))
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"

KARAOKE = re.compile(r"\\[kK][fo]?\d")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
DROP_STYLE = re.compile(r"warning", re.I)        # junk, never a dialogue reference
KEEP_STYLE = re.compile(r"karaoke|translat|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)

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


def is_target(c, gloss):
    """A conf row to send to the LLM: it must be speech (low no_speech_prob) AND either
    mid-confidence-or-lower OR name-suspect."""
    if c.get("no_speech_prob", 1.0) >= NSP_MAX:
        return False
    return c.get("avg_logprob", 0.0) < LOGPROB_MIN or glossary.name_suspect(c.get("text", ""), gloss)


def _glossary_terms(gloss):
    terms = list(gloss["names"]) + list(gloss["phrases"])
    terms += list(gloss["token_fixes"].values()) + list(gloss["phrase_fixes"].values())
    seen, out = set(), []
    for t in terms:                       # de-dup, preserve order, cap the prompt size
        if t not in seen:
            seen.add(t); out.append(t)
    return ", ".join(out)[:1000]


def build_prompt(asr, sub, gloss, prev_text="", next_text=""):
    """Build a STRICT repair prompt: glossary names always; the fansub reference only when
    present (graceful glossary-only fallback for mp4). The strictness is deliberate — the
    bake-off showed a loose prompt makes models hallucinate glossary names into lines.

    prev_text/next_text (C1 Phase 3): the neighboring lines' text, when available, given as
    extra context only — never part of what gets corrected. Omitted from the prompt entirely
    when empty, so a call with no prev/next produces the exact same prompt as before."""
    names = _glossary_terms(gloss)
    ref_intro = ("For reference, the official subtitle for this moment (a DIFFERENT translation — "
                 "do NOT copy its wording) is given below; use it only to resolve garbled words and "
                 "confirm names. ") if sub else ""
    head = "You fix speech-recognition errors in one English-dub subtitle line. " + ref_intro
    name_line = f"Canonical spellings of known proper nouns: {names}.\n" if names else ""
    rules = (
        "Rules:\n"
        "- Change a word ONLY if it is clearly garbled, or a clear MISSPELLING of one of the "
        "canonical names above (close in sound/spelling) — then use the canonical spelling.\n"
        "- NEVER introduce a name that is not already in the line. NEVER replace a name in the line "
        "with a different name. If a name in the line is NOT in the list, leave it EXACTLY as written "
        "— it may be a character that isn't listed.\n"
        "- Do NOT turn ordinary words into names. Keep the wording and length almost identical.\n"
        "- If the line already reads fine, or you are unsure, return it UNCHANGED.\n"
        "Return ONLY the line — no quotes, no notes.\n\n")
    prev_line = f'Previous line (for context): "{prev_text}"\n' if prev_text else ""
    next_line = f'Next line (for context): "{next_text}"\n' if next_text else ""
    ref_line = f"Official subtitle (reference only): {sub}\n" if sub else ""
    return f"{head}{name_line}{rules}ASR line: {asr}\n{prev_line}{next_line}{ref_line}Corrected line:"


def dialogue_intervals(video):
    """Embedded DIALOGUE lines (the translation track) as (start_s, end_s, text)."""
    ivals = []
    for idx in eng_sub_streams(video, SUB_LANGS):
        with tempfile.TemporaryDirectory() as td:
            ex = os.path.join(td, "s.ass")
            if not extract(video, idx, ex):
                continue
            try:
                subs = pysubs2.load(ex)
            except Exception:
                continue
        for ev in subs.events:
            if ev.is_comment:
                continue
            t = ev.text
            if KARAOKE.search(t) or POSITIONED.search(t):   # sign/song, not dialogue
                continue
            if KEEP_STYLE.search(ev.style or "") or DROP_STYLE.search(ev.style or ""):
                continue
            txt = ev.plaintext.strip()
            if txt:
                ivals.append((ev.start / 1000.0, ev.end / 1000.0, txt))
    ivals.sort()
    return ivals


def overlap_ref(ivals, a, b):
    hits = [t for (s, e, t) in ivals if e > a and s < b]   # any time overlap
    return " ".join(hits)[:300]


def llm(prompt):
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0}}
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read()).get("response", "").strip()
        out = out.splitlines()[0].strip().strip('"').strip() if out else ""
        return out
    except Exception as e:
        log("  llm fail:", e); return ""


def process(conf_path):
    stem = conf_path[:-len(CONF_SUFFIX)]
    srt = stem + SRT_SUFFIX
    video = find_video(stem)
    if not video or not os.path.exists(srt):
        return "skip"
    conf = json.load(open(conf_path))
    gloss = glossary_for(video)
    targets = [c for c in conf if is_target(c, gloss)]
    if not targets:
        return "clean"          # nothing to repair (e.g. S15E01)
    ivals = dialogue_intervals(video)
    audit, fixed = [], 0
    for c in targets:
        ref = overlap_ref(ivals, c["start"], c["end"])
        if not ref:
            continue        # no fansub anchor -> skip the LLM. The bake-off showed glossary-only
                            # repair hallucinates names (Oimo->Zoro) even on qwen3:8b; without a
                            # reference the deterministic layer (hard_fixes) is the safe ceiling.
        new = llm(build_prompt(c["text"], ref, gloss))
        if new:
            new = glossary.correct(new, gloss)[0]         # enforce canonical spelling on output
        if new and new.lower() != c["text"].lower() and 0.4 <= len(new) / max(1, len(c["text"])) <= 2.5:
            audit.append((c["text"], new, ref[:80])); c["text"] = new; fixed += 1
    # rewrite srt from (possibly repaired) conf rows
    srt_out = out_for(srt); rep_out = out_for(stem + ".dubtitles.repair.csv")
    with open(srt_out, "w") as f:
        for i, c in enumerate(conf, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{c['text']}\n\n")
    with open(rep_out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["orig", "repaired", "ref"]); w.writerows(audit)
    for p in (srt_out, rep_out):
        try: os.chown(p, MEDIA_UID, MEDIA_GID)
        except OSError: pass
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
