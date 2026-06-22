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

CPU/network only — the LLM runs on the 2070 (Ollama). Env:
  OLLAMA_URL    default http://ollama.local:11434/api/generate
  REPAIR_MODEL  default qwen2.5:7b
  LOGPROB_MIN   default -0.8   (repair segments below this avg_logprob)
  NSP_MAX       default 0.5    (…and below this no_speech_prob — i.e. it IS speech)
  SUB_LANGS     accepted embedded-sub languages (default eng,en,und,)
  MEDIA_UID/GID default 1000/100
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""
import csv, json, os, re, subprocess, sys, tempfile, urllib.request
import pysubs2

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")   # write sidecars to a branch with space
def out_for(p):
    if OUTPUT_ROOT and p.startswith(MEDIA_ROOT):
        q = OUTPUT_ROOT + p[len(MEDIA_ROOT):]
        os.makedirs(os.path.dirname(q), exist_ok=True)
        return q
    return p

OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
MODEL = os.environ.get("REPAIR_MODEL", "qwen2.5:7b")
LOGPROB_MIN = float(os.environ.get("LOGPROB_MIN", "-0.8"))
NSP_MAX = float(os.environ.get("NSP_MAX", "0.5"))
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"

KARAOKE = re.compile(r"\\[kK][fo]?\d")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
DROP_STYLE = re.compile(r"warning", re.I)        # junk, never a dialogue reference
KEEP_STYLE = re.compile(r"karaoke|translat|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)

PROMPT = (
    "You are correcting an English-dub subtitle line that automatic speech recognition "
    "may have garbled. You are given the ASR attempt and, for context, the official "
    "subtitle for the same moment — which is a DIFFERENT translation (the dub is localized, "
    "so wording differs; do NOT copy the subtitle). Return the most likely actual English "
    "DUB line: keep the ASR wording where it is plausible, only fix clearly garbled parts "
    "using the subtitle as a meaning hint. Keep it about the same length. If the ASR line "
    "already reads fine, return it unchanged. Return ONLY the corrected line, no quotes, no notes.\n\n"
    "ASR attempt: {asr}\nOfficial subtitle (context only): {sub}\nCorrected dub line:")


def log(*a): print(*a, flush=True)


def find_video(stem):
    for e in VIDEO_EXTS:
        if os.path.exists(stem + e):
            return stem + e
    return None


def eng_sub_streams(video):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s",
                            "-show_entries", "stream=index,codec_name:stream_tags=language",
                            "-of", "json", video], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception:
        return []
    out = []
    for st in streams:
        if st.get("codec_name") not in ("ass", "ssa"):
            continue
        if ((st.get("tags") or {}).get("language", "") or "").lower() in SUB_LANGS:
            out.append(st["index"])
    return out


def extract(video, idx, out):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}",
                    "-c:s", "copy", out], capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}", out],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    return os.path.exists(out) and os.path.getsize(out) > 0


def dialogue_intervals(video):
    """Embedded DIALOGUE lines (the translation track) as (start_s, end_s, text)."""
    ivals = []
    for idx in eng_sub_streams(video):
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


def llm(asr, sub):
    body = {"model": MODEL, "prompt": PROMPT.format(asr=asr, sub=sub),
            "stream": False, "options": {"temperature": 0}}
    try:
        req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read()).get("response", "").strip()
        out = out.splitlines()[0].strip().strip('"').strip() if out else ""
        return out
    except Exception as e:
        log("  llm fail:", e); return ""


def ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def process(conf_path):
    stem = conf_path[:-len(CONF_SUFFIX)]
    srt = stem + SRT_SUFFIX
    video = find_video(stem)
    if not video or not os.path.exists(srt):
        return "skip"
    conf = json.load(open(conf_path))
    targets = [c for c in conf
               if c.get("avg_logprob", 0) < LOGPROB_MIN and c.get("no_speech_prob", 1) < NSP_MAX]
    if not targets:
        return "clean"          # nothing to repair (e.g. S15E01)
    ivals = dialogue_intervals(video)
    audit, fixed = [], 0
    for c in targets:
        ref = overlap_ref(ivals, c["start"], c["end"])
        if not ref:
            continue            # no anchor -> leave whisper's text
        new = llm(c["text"], ref)
        if new and new.lower() != c["text"].lower() and 0.4 <= len(new) / max(1, len(c["text"])) <= 2.5:
            audit.append((c["text"], new, ref[:80])); c["text"] = new; fixed += 1
    # rewrite srt from (possibly repaired) conf rows
    srt_out = out_for(srt); rep_out = out_for(stem + ".dubtitles.repair.csv")
    with open(srt_out, "w") as f:
        for i, c in enumerate(conf, 1):
            f.write(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n\n")
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
