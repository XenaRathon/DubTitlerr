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
import os, sys, json, subprocess, tempfile, difflib, re
from faster_whisper import WhisperModel

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

# --- Per-show glossary (optional) ---------------------------------------------------
# Library-wide safety: the franchise name-forcing below is OPT-IN per show, so One
# Piece's "spell it Luffy/Zoro/Alabasta" tuning can never leak onto another show (which
# would corrupt e.g. "Sasuke" -> "Sabo"). A show gets franchise-accurate spelling only
# when GLOSSARY_FILE points at a JSON file shaped:
#   {"show": "...", "initial_prompt": "...", "names": [...],
#    "hard_fixes": {"misheard": "Canonical"}}
# With no file, GLOSSARY/HARD_FIXES are empty (correct() becomes a no-op) and the prompt
# is a neutral one built from SHOW_NAME — transcription only, zero name substitution.
GLOSSARY, HARD_FIXES, INITIAL_PROMPT = [], {}, ""

def load_glossary():
    global GLOSSARY, HARD_FIXES, INITIAL_PROMPT
    path = os.environ.get("GLOSSARY_FILE", "")
    show = os.environ.get("SHOW_NAME", "")
    names, hard, prompt = [], {}, ""
    if path and os.path.exists(path):
        try:
            cfg = json.load(open(path))
            names = cfg.get("names") or []
            hard = {str(k).lower(): v for k, v in (cfg.get("hard_fixes") or {}).items()}
            prompt = cfg.get("initial_prompt") or ""
            show = show or cfg.get("show", "")
        except Exception as e:
            print("glossary load failed:", path, e, flush=True)
    GLOSSARY = sorted({w for w in names if len(w) >= 4})
    HARD_FIXES = hard
    INITIAL_PROMPT = prompt or (
        (f"This is {show}, a Japanese anime (English dub). Transcribe the spoken English "
         f"accurately, with natural punctuation.") if show else
        "Japanese anime, English dub. Transcribe the spoken English accurately, with natural punctuation.")
    print(f"glossary: show={show!r} names={len(GLOSSARY)} hard_fixes={len(HARD_FIXES)} "
          f"prompt={'custom' if prompt else 'neutral'}", flush=True)
# whisper hallucination phrases that surface in music/silence — drop these segments outright
BLOCKLIST = re.compile(r"amara\.org|thank you for watching|thanks for watching|please subscribe|"
                       r"subtitles by|like and subscribe|see you next time|www\.|http", re.I)
COMMON = set("the a an and or but of to in on at is was are were be been being have has had "
             "do does did will would can could should i you he she it we they me him her us them "
             "this that these those with from for not no yes all out up down here there what who".split())


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


def fix_word(tok):
    """Correct a single token toward the glossary; return (token, changed)."""
    m = re.match(r"^([^\w]*)(\w[\w'-]*?)([^\w]*)$", tok)
    if not m: return tok, False
    pre, core, post = m.groups()
    low = core.lower()
    if low in COMMON or len(core) < 4: return tok, False
    if low in HARD_FIXES: return pre + HARD_FIXES[low] + post, True
    # already a correct glossary word?
    if any(low == g.lower() for g in GLOSSARY): return tok, False
    cand = difflib.get_close_matches(core.title(), GLOSSARY, n=1, cutoff=0.86)
    if cand and cand[0].lower() != low:
        return pre + cand[0] + post, True
    return tok, False


def correct(text):
    out, n = [], 0
    for tok in text.split():
        new, ch = fix_word(tok); out.append(new); n += ch
    return " ".join(out), n


def ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def process(video):
    stem = os.path.splitext(video)[0]
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
        segs, info = WMODEL.transcribe(
            wav, language="en", task="transcribe", beam_size=5,
            word_timestamps=True, vad_filter=True, condition_on_previous_text=True,
            initial_prompt=INITIAL_PROMPT)
        rows, conf, fixes, dropped = [], [], 0, 0
        for s in segs:
            raw = s.text.strip()
            if BLOCKLIST.search(raw):            # whisper hallucination in music/silence
                dropped += 1; continue
            txt, n = correct(raw); fixes += n
            # TIMING: segment.start drifts early (condition_on_previous_text); use the actual
            # WORD onsets instead, and end-anchor-cap any still-pathological span so a line never
            # lingers over silence before it's spoken.
            ws = [w for w in (s.words or []) if w.start is not None and w.end is not None]
            a = ws[0].start if ws else s.start
            b = ws[-1].end if ws else s.end
            cap = min(8.0, max(1.2, 0.07 * len(txt)))   # readable window from text length
            if b - a > cap + 1.0:                        # too long -> anchor to the (correct) end
                a = b - cap
            if b <= a:
                b = a + 1.0
            rows.append((a, b, txt))
            conf.append({"start": round(a, 3), "end": round(b, 3),
                         "avg_logprob": round(s.avg_logprob, 3),
                         "no_speech_prob": round(s.no_speech_prob, 3), "text": txt})
    try: os.remove(fail)                          # transcription finished -> clear in-flight mark
    except OSError: pass
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
    log(f"  segs={len(rows)} name-fixes={fixes} dropped-hallucination={dropped} low-conf={low} "
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
