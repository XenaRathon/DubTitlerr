#!/usr/bin/env python3
"""Rebuild <stem>.eng.dubtitles.srt from <stem>.dubtitles.conf.json — used when the
srt was already consumed by a (buggy) assemble and we want to re-assemble without
re-transcribing. Pass conf.json paths as args.  Built with help of Claude (Anthropic)."""
import json, os, sys
def ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
for conf in sys.argv[1:]:
    stem = conf[:-len(".dubtitles.conf.json")]
    srt = stem + ".eng.dubtitles.srt"
    if os.path.exists(srt):
        continue
    d = json.load(open(conf))
    with open(srt, "w") as f:
        for i, c in enumerate(d, 1):
            f.write(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n\n")
    print("recreated", os.path.basename(srt))
