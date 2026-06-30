#!/usr/bin/env python3
"""Gold dubtitle GENERATION — transcribe an anime's English-dub audio into a
time-coded subtitle, biased toward correct franchise spellings and with per-segment
confidence captured for a downstream repair pass.

Runs in the subgen CUDA image (mccloud/subgen:2026.06.2) so it inherits the exact
faster-whisper 1.2.1 / ctranslate2 4.8.0 stack that already works on the 1060
(Pascal) + driver 550 — no new CUDA surface. Only extra dep is none (uses ffmpeg +
faster_whisper already present).

Per video:
  1. pick the English audio stream (by language tag) and extract 16k mono wav,
  2. faster-whisper large-v3, task=transcribe (English dub -> English text),
     word_timestamps + vad_filter + initial_prompt glossary,
  3. conservative name-correction sweep against the franchise glossary,
  4. write <stem>.eng.dubtitles.srt + <stem>.dubtitles.conf.json (segment
     confidences: start,end,avg_logprob,no_speech_prob) for the repair stage.

Usage:
  python3 generate.py /media/.../Episode.mkv [more.mkv ...]   # explicit files
  python3 generate.py --root "/media/Anime Library/One Pace/Season 15"  # walk dir

Env:
  WHISPER_MODEL   default large-v3
  COMPUTE_TYPE    default int8  (Pascal-friendly, fits 6GB; try float16 for max quality)
  MODEL_DIR       default /subgen/models  (reuse subgen's downloaded model)
  MEDIA_UID/GID   default 1000/100
Built with help of Claude (Anthropic).
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile

from faster_whisper import WhisperModel

import glossary
import hallucination
import mux
import reflow

# OUTPUT_ROOT: write sidecars to this branch path instead of next to the mkv, so writes
# land on a disk with space (mergerfs unifies branches, so the file still shows next to the
# mkv in the pool view). READS still use the mergerfs path. Empty = write in place.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")
def out_for(p):
    if OUTPUT_ROOT and p.startswith(MEDIA_ROOT):
        q = OUTPUT_ROOT + p[len(MEDIA_ROOT):]
        os.makedirs(os.path.dirname(q), exist_ok=True)
        return q
    return p

MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
COMPUTE = os.environ.get("COMPUTE_TYPE", "int8")
MODEL_DIR = os.environ.get("MODEL_DIR", "/subgen/models")
UID = int(os.environ.get("MEDIA_UID", "1000")); GID = int(os.environ.get("MEDIA_GID", "100"))
SUFFIX = ".eng.dubtitles.srt"
WMODEL = None        # the WhisperModel, lazily loaded in main() once there's work to do

# --- Per-show glossary (optional) ---------------------------------------------------
# Name correction is OPT-IN per show (GLOSSARY_FILE), so One Piece's spellings can never
# leak onto another show. The tiered correction itself lives in glossary.py (C1). With no
# file, GLOSS is empty (correct() is a no-op) and the prompt is a neutral one from SHOW_NAME.
GLOSS = glossary.load("")
INITIAL_PROMPT = ""

def load_glossary():
    global GLOSS, INITIAL_PROMPT
    show = os.environ.get("SHOW_NAME", "")
    GLOSS = glossary.load(os.environ.get("GLOSSARY_FILE", ""))
    show = show or GLOSS.get("show", "")
    INITIAL_PROMPT = GLOSS["initial_prompt"] or (
        (f"This is {show}, a Japanese anime (English dub). Transcribe the spoken English "
         f"accurately, with natural punctuation.") if show else
        "Japanese anime, English dub. Transcribe the spoken English accurately, with natural punctuation.")
    print(f"glossary: show={show!r} names={len(GLOSS['names'])} "
          f"fixes={len(GLOSS['token_fixes']) + len(GLOSS['phrase_fixes'])} "
          f"prompt={'custom' if GLOSS['initial_prompt'] else 'neutral'}", flush=True)


# Plex "local extras" subfolders + creditless/scene clips — never real episodes, often
# mismatched junk from the scraper, and a frequent source of malformed-clip crashes. The
# --root walk prunes these so a library run only ever transcribes actual episodes.
EXTRA_DIRS = {"behind the scenes", "deleted scenes", "featurettes", "interviews",
              "scenes", "shorts", "trailers", "other", "extras"}
SKIP_FILE_RE = re.compile(r"\bNCED\b|\bNCOP\b|\bNCBD\b|-\s*scene\b|creditless", re.I)


def log(*a): print(*a, flush=True)


def has_dubtitles_track(video):
    """True if the mkv already carries a subtitle track titled 'Dubtitles' (muxed) —
    the idempotency gate for the muxed workflow; skip such files."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s",
                            "-show_entries", "stream_tags=title", "-of", "json", video],
                           capture_output=True, text=True, timeout=60)
        for st in json.loads(r.stdout).get("streams", []):
            if ((st.get("tags") or {}).get("title", "") or "") == "Dubtitles":
                return True
    except Exception:
        pass
    return False


def eng_audio_index(video):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index:stream_tags=language",
                            "-of", "json", video], capture_output=True, text=True, timeout=60)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed", video, e); return None
    eng = [s for s in streams if ((s.get("tags") or {}).get("language", "").lower() in ("eng", "en"))]
    if eng:
        return eng[0]["index"]
    # No English-tagged audio. On a library-wide run this means a sub-only release —
    # do NOT fall back to stream 0 (that would transcribe the Japanese audio AS English
    # and produce garbage). Skip it. Set REQUIRE_ENG=0 only for pre-filtered single-audio
    # English collections (e.g. the One Pace mover already guarantees English audio).
    if os.environ.get("REQUIRE_ENG", "1") == "1":
        return None
    return streams[0]["index"] if streams else None


def extract_wav(video, idx, wav):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
                   capture_output=True, timeout=600)
    return os.path.exists(wav) and os.path.getsize(wav) > 1000


def ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def process(video):
    stem = os.path.splitext(video)[0]
    if mux.stamp_valid(mux.read_stamp(stem + mux.STAMP_SUFFIX), video):  # muxed (stat-only) -> skip
        return "already-muxed"
    if os.path.exists(stem + ".eng.dubtitles.ass"):     # assembled already -> skip (idempotent)
        return "already-ass"
    if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"):
        return "already-srt"                            # generated, awaiting (a retry of) assemble
    if os.environ.get("SKIP_IF_MUXED", "1") == "1" and has_dubtitles_track(video):
        return "already-muxed"
    fail = stem + ".dubtitles.fail"
    if os.path.exists(fail):                      # a previous attempt hard-crashed on this
        return "skip-prior-crash"                 # file -> skip it (rm the .fail to retry)
    idx = eng_audio_index(video)
    if idx is None: return "no-eng-dub"          # sub-only release (or no audio) -> skip
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        if not extract_wav(video, idx, wav): return "extract-failed"
        try: open(fail, "w").close()             # mark in-flight (a segfault here leaves the
        except OSError: pass                     # marker, so a resume skips this poison file)
        segs, _info = WMODEL.transcribe(
            wav, language="en", task="transcribe", beam_size=5,
            word_timestamps=True, vad_filter=True, condition_on_previous_text=True,
            initial_prompt=INITIAL_PROMPT)
        # NOTE: hallucination_silence_threshold was removed — verification on S19E16 showed it
        # ~doubled the "dialogue with no subtitle" gaps (28 vs 14) by skipping real speech. B1's
        # post-hoc gate (blocklist/repetition/music drop + collapse) handles hallucinations instead.
        # Consume the (lazy) generator while the wav still exists, adapting whisper's
        # objects to the plain dicts reflow expects: one word dict per word (with its
        # source segment index), plus a per-segment record for no_speech_prob.
        words, segments = [], []
        for si, s in enumerate(segs):
            segments.append({"start": s.start, "end": s.end, "no_speech_prob": s.no_speech_prob})
            sw = s.words or []
            if sw:
                for w in sw:
                    words.append({"text": w.word, "start": w.start, "end": w.end,
                                  "prob": getattr(w, "probability", 1.0) or 1.0, "seg": si})
            else:                                # no word timestamps -> whole segment as one "word"
                words.append({"text": s.text, "start": s.start, "end": s.end,
                              "prob": min(1.0, math.exp(s.avg_logprob)), "seg": si})
    try: os.remove(fail)                          # transcription finished -> clear in-flight mark
    except OSError: pass
    # A1: reflow whisper's words into clean, well-timed cards. C1: name-correct each card.
    # B1: drop near-certain hallucinations, flag the suspect, collapse runaway repeat runs.
    cards = reflow.reflow(words, segments)
    kept, fixes, dropped = [], 0, 0
    for c in cards:
        if hallucination.drop_reason(c):          # blocklist / repetition / music -> drop
            dropped += 1; continue
        lines, n = [], 0
        for ln in c["text"].split("\n"):          # correct per line so the wrap is preserved
            fixed, k = glossary.correct(ln, GLOSS); lines.append(fixed); n += k
        fixes += n
        kc = dict(c); kc["text"] = "\n".join(lines)
        kc["flag"] = hallucination.flag_reason(c)  # weaker single signal -> kept but marked
        kept.append(kc)
    collapsed = hallucination.collapse_runs(kept)
    rows = [(c["start"], c["end"], c["text"]) for c in collapsed]
    conf = []
    for c in collapsed:
        row = {"start": round(c["start"], 3), "end": round(c["end"], 3),
               "avg_logprob": round(c["avg_logprob"], 3),
               "no_speech_prob": round(c["no_speech_prob"], 3),
               "text": c["text"].replace("\n", " ")}
        if c.get("flag"):
            row["flag"] = c["flag"]
        conf.append(row)
    srt = out_for(stem + SUFFIX); confp = out_for(stem + ".dubtitles.conf.json")
    with open(srt, "w") as f:
        for i, (a, b, t) in enumerate(rows, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n")
    with open(confp, "w") as f:
        json.dump(conf, f)
    for p in (srt, confp):
        try: os.chown(p, UID, GID)
        except OSError: pass
    low = sum(1 for c in conf if c["avg_logprob"] < -0.8 or c["no_speech_prob"] > 0.6)
    max_dur = max((b - a for a, b, _ in rows), default=0.0)
    over_cps = sum(1 for a, b, t in rows
                   if len(t.replace("\n", " ")) / max(b - a, 1e-6) > reflow.MAX_CPS)
    bad = sum(1 for a, b, t in rows
              if b - a > 7.001 or len(t.split("\n")) > 2 or any(len(ln) > 42 for ln in t.split("\n")))
    collapsed_n = len(kept) - len(collapsed)
    flagged = sum(1 for c in conf if c.get("flag"))
    log(f"  cards={len(rows)} name-fixes={fixes} dropped-hallucination={dropped} "
        f"collapsed={collapsed_n} flagged={flagged} low-conf={low} "
        f"max_dur={max_dur:.1f}s over_cps={over_cps} violations={bad} "
        f"meanlp={sum(c['avg_logprob'] for c in conf)/max(1,len(conf)):.2f}")
    return "ok"


def main():
    args = sys.argv[1:]
    files = []
    if args and args[0] == "--root":
        for dp, dns, fs in os.walk(args[1]):
            dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]   # prune extras dirs
            for fn in fs:
                if fn.lower().endswith((".mkv", ".mp4")) and not SKIP_FILE_RE.search(fn):
                    files.append(os.path.join(dp, fn))
        files.sort()
    else:
        files = args
    load_glossary()
    # Cheap pre-filter (stat only, no ffprobe/model): drop files already done so a perpetual
    # re-scan doesn't pay the ~40s model load when there's nothing new to transcribe.
    def needs_work(v):
        stem = os.path.splitext(v)[0]
        if mux.stamp_valid(mux.read_stamp(stem + mux.STAMP_SUFFIX), v): return False  # muxed -> done
        if os.path.exists(stem + ".eng.dubtitles.ass"): return False
        if os.environ.get("SKIP_IF_SRT", "1") == "1" and os.path.exists(stem + ".eng.dubtitles.srt"): return False
        if os.path.exists(stem + ".dubtitles.fail"): return False
        return True
    todo = [v for v in files if needs_work(v)]
    log(f"model={MODEL} compute={COMPUTE} require_eng={os.environ.get('REQUIRE_ENG','1')} files={len(files)} todo={len(todo)}")
    if not todo:
        log("nothing to transcribe (all done) — skipping model load"); return
    globals()["WMODEL"] = WhisperModel(MODEL, device="cuda", compute_type=COMPUTE, download_root=MODEL_DIR)
    for v in todo:
        log("→", os.path.basename(v))
        try:
            log("  ", process(v))                 # one bad episode must not abort the show
        except Exception as e:
            log("  ERROR", type(e).__name__, e)
            if any(k in str(e).lower() for k in ("cuda", "out of memory", "device ordinal", "cublas")):
                # A CUDA OOM/device error poisons the context — every later file would also
                # fail and get falsely marked. Exit so the loop relauncher restarts with a
                # fresh context; the OOM'd file keeps its .fail (skipped on resume), the rest
                # transcribe cleanly. (Usually means another process grabbed the GPU.)
                log("  CUDA error -> exiting to rebuild a clean GPU context (show resumes on restart)")
                sys.exit(3)
            try: os.remove(os.path.splitext(v)[0] + ".dubtitles.fail")  # non-CUDA: let it retry
            except OSError: pass


if __name__ == "__main__":
    main()
