#!/usr/bin/env python3
"""ADDITIVE glossary mining. For one show: load its existing dictionary (if any), mine the
NEW (not-yet-dubtitled) episodes' embedded English subtitles for recurring proper nouns
(character/place names — the official spellings), and ADD any new ones to the dictionary.
Never rebuilds from scratch: curated names, hard_fixes and a curated initial_prompt are
preserved; mining only appends. Runs BEFORE generate (in gen_loop) so the grown dictionary
applies to the very episodes being transcribed, and grows again whenever new episodes appear.

CPU only (ffmpeg + pysubs2). Env: GLOSSARY_DIR (default /config/glossaries),
MINE_MIN_COUNT (a name must recur >= this across the new episodes, default 3).
Built with help of Claude (Anthropic).
"""
import os, sys, re, json, subprocess, tempfile
import pysubs2

GLOSS_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
MIN_COUNT = int(os.environ.get("MINE_MIN_COUNT", "3"))
EXTRA_DIRS = {"behind the scenes","deleted scenes","featurettes","interviews",
              "scenes","shorts","trailers","other","extras"}
SKIP_FILE_RE = re.compile(r"\bNC(ED|OP|BD)\b|-\s*scene\b|creditless", re.I)
# words that are capitalized for position/grammar, not proper nouns — never mine these
COMMON = set("""the a an and or but of to in on at is was are were be been being have has had do does did
will would can could should shall may might must i you he she it we they me him her us them my your his
her its our their this that these those with from for not no nor yes all out up down here there then now
what who whom whose when where why how which while because if so as than too very just only even still
oh ah hey hmm well yeah yes okay ok hello goodbye please thank thanks sorry sir madam mister missus doctor
get got go going gone come came see saw seen know knew known think thought say said tell told want need
make made take took give gave find found let look looked good bad great little big small new old one two
three four five six seven eight nine ten first last next every some any many much more most right left
wait stop help yes mom dad mother father brother sister friend everyone someone something nothing
today tomorrow yesterday day night morning time year hand way thing people man woman boy girl
master lady lord king queen captain general doctor mister""".split())


def eng_sub_text(video):
    """Return plaintext of the video's English (or und) ASS/SSA/SRT subtitle, or ''."""
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","s","-show_entries",
                            "stream=index,codec_name:stream_tags=language","-of","json","-nostdin",video],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception:
        return ""
    cand = [s for s in streams
            if (s.get("tags") or {}).get("language","").lower() in ("eng","en","und","")
            and s.get("codec_name") in ("ass","ssa","subrip")]
    if not cand:
        return ""
    idx = cand[0]["index"]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "s.ass")
        subprocess.run(["ffmpeg","-y","-v","error","-nostdin","-i",video,"-map",f"0:{idx}",out],
                       capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        if not os.path.exists(out):
            return ""
        try:
            subs = pysubs2.load(out)
        except Exception:
            return ""
        return "\n".join(ev.plaintext for ev in subs if not ev.is_comment)


def mine_text(text, counter, midsentence):
    """Count capitalized proper-noun candidates; track which appear MID-sentence (not just
    sentence-initial, where any word is capitalized)."""
    for sent in re.split(r"[.!?…]+|\n", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]{2,}", sent)
        for i, w in enumerate(words):
            core = w.strip("'’-")
            if re.match(r"^[A-Z][a-z]{3,}$", core):
                counter[core] = counter.get(core, 0) + 1
                if i > 0:                       # not the first word of the sentence
                    midsentence.add(core)


def main():
    if len(sys.argv) < 2:
        print("usage: mine_glossary.py <show_dir>"); return
    show_dir = sys.argv[1].rstrip("/")
    show = os.path.basename(show_dir)
    gpath = os.path.join(GLOSS_DIR, show + ".json")
    cfg = {"show": show, "initial_prompt": "", "names": [], "hard_fixes": {}}
    if os.path.exists(gpath):
        try: cfg.update(json.load(open(gpath)))
        except Exception as e: print("mine: bad glossary, starting fresh:", e)
    existing = {n.lower() for n in cfg.get("names", [])}

    counter, mid = {}, set()
    mined_eps = 0
    for dp, dns, fs in os.walk(show_dir):
        dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]
        for fn in fs:
            if not fn.lower().endswith((".mkv",".mp4")) or SKIP_FILE_RE.search(fn):
                continue
            stem = os.path.splitext(os.path.join(dp, fn))[0]
            # only NEW episodes (no dubtitle yet) -> each episode mined exactly once, additively
            if os.path.exists(stem + ".eng.dubtitles.ass") or os.path.exists(stem + ".eng.dubtitles.srt"):
                continue
            txt = eng_sub_text(os.path.join(dp, fn))
            if txt:
                mine_text(txt, counter, mid); mined_eps += 1

    new = sorted({t for t in mid
                  if counter[t] >= MIN_COUNT and t.lower() not in COMMON and t.lower() not in existing})
    if not new:
        print(f"mine[{show}]: {mined_eps} new ep(s), no new terms (dict has {len(existing)})")
        return
    cfg["names"] = cfg.get("names", []) + new
    # build a prompt from the top names only if there is no curated one
    if not cfg.get("initial_prompt"):
        top = sorted(cfg["names"], key=lambda n: -counter.get(n, 0))[:30]
        title = re.sub(r"\s*\{tvdb-\d+\}|\s*\(\d{4}\)", "", show)
        cfg["initial_prompt"] = (f"This is {title}, a Japanese anime (English dub). Spell names "
                                 f"correctly: " + ", ".join(top) + ".")
    os.makedirs(GLOSS_DIR, exist_ok=True)
    json.dump(cfg, open(gpath, "w"), indent=2, ensure_ascii=False)
    print(f"mine[{show}]: +{len(new)} terms from {mined_eps} new ep(s) -> {new[:15]}")


if __name__ == "__main__":
    main()
