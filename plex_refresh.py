#!/usr/bin/env python3
"""Trigger a targeted Plex library folder refresh so a newly-written sidecar/track
is picked up. Env: PLEX_URL, PLEX_TOKEN, PLEX_SECTION (default 7), PLEX_PATH
(the Plex-side folder path to rescan).  Built with help of Claude (Anthropic)."""
import os, sys, urllib.parse, urllib.request

base = os.environ["PLEX_URL"].rstrip("/")
tok = os.environ["PLEX_TOKEN"]
sec = os.environ.get("PLEX_SECTION", "7")
path = os.environ.get("PLEX_PATH", "")
q = "?X-Plex-Token=" + tok + ("&path=" + urllib.parse.quote(path) if path else "")
url = f"{base}/library/sections/{sec}/refresh{q}"
try:
    urllib.request.urlopen(url, timeout=20).read()
    print("plex refreshed:", sys.argv[1] if len(sys.argv) > 1 else sec)
except Exception as e:
    print("plex refresh fail:", e)
