#!/bin/sh
# Per-season repair + assemble + per-episode Plex refresh (runs in python:slim).
# Env: SEASON_NAME (e.g. "Season 13"), PLEX_URL, PLEX_TOKEN, PLEX_SECTION.
apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq ffmpeg >/dev/null 2>&1
pip install -q pysubs2 >/dev/null 2>&1
export PLEX_PATH="A:\\Storage\\Media\\Anime Library\\One Pace\\$SEASON_NAME"
cd "/media/Anime Library/One Pace/$SEASON_NAME" || exit 1
ls *.eng.dubtitles.srt 2>/dev/null | sort | while IFS= read -r srt; do
  stem="${srt%.eng.dubtitles.srt}"
  echo "### $stem"
  python3 /scripts/repair.py "$stem.dubtitles.conf.json" </dev/null
  python3 /scripts/dub_signs_merge.py "$srt" </dev/null
  python3 /scripts/plex_refresh.py "$stem" </dev/null
done
echo "POST_DONE $SEASON_NAME"
