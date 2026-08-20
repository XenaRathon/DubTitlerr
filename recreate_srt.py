#!/usr/bin/env python3
"""Rebuild <stem>.eng.dubtitles.srt from <stem>.dubtitles.conf.json — used when the
srt was already consumed by a (buggy) assemble and we want to re-assemble without
re-transcribing. Pass conf.json paths as args.  Built with help of Claude (Anthropic)."""
import json
import os
import sys

import reflow
from common import ts_srt

CONF_SUFFIX = ".dubtitles.conf.json"


def recreate(conf: str) -> str | None:
    """Rebuild one srt from its conf.json. Returns the srt path, or None if it already
    exists. Split out of the argv loop so the wrap below is testable: importing this
    module used to execute the loop against pytest's own sys.argv."""
    stem = conf[:-len(CONF_SUFFIX)]
    srt = stem + ".eng.dubtitles.srt"
    if os.path.exists(srt):
        return None
    d = json.load(open(conf))
    # conf.json stores text FLATTENED (generate.py replaces '\n' with ' '), so re-wrap
    # here -- same defect, same fix as repair.py's srt rewrite. Without it every episode
    # recreated this way ships as unwrapped single lines.
    with open(srt, "w") as f:
        for i, c in enumerate(d, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n"
                    f"{reflow.wrap_balance(c['text'])}\n\n")
    return srt


if __name__ == "__main__":
    for conf in sys.argv[1:]:
        out = recreate(conf)
        if out: print("recreated", os.path.basename(out))
