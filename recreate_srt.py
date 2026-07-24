#!/usr/bin/env python3
"""Rebuild <stem>.eng.dubtitles.srt from <stem>.dubtitles.conf.json — used when the
srt was already consumed by a (buggy) assemble and we want to re-assemble without
re-transcribing. Pass conf.json paths as args.  Built with help of Claude (Anthropic)."""
import json
import os
import sys

from common import ts_srt

for conf in sys.argv[1:]:
    stem = conf[:-len(".dubtitles.conf.json")]
    srt = stem + ".eng.dubtitles.srt"
    if os.path.exists(srt):
        continue
    d = json.load(open(conf))
    with open(srt, "w") as f:
        for i, c in enumerate(d, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{c['text']}\n\n")
    print("recreated", os.path.basename(srt))
