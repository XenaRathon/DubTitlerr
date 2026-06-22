#!/bin/sh
# Per-SHOW repair + assemble + Plex refresh (runs in python:slim). Generalizes
# post_season.sh from One Pace to any Anime Library show. Walks the show folder
# recursively (handles multi-season shows), repairs low-confidence dub lines via the
# local LLM, merges signs/songs, then refreshes the Plex anime section once.
# Env: SHOW_DIR (folder name under "Anime Library"), OLLAMA_URL, REPAIR_MODEL,
#      PLEX_URL, PLEX_TOKEN, PLEX_SECTION.
apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq ffmpeg >/dev/null 2>&1
pip install -q pysubs2 >/dev/null 2>&1
cd "/media/Anime Library/$SHOW_DIR" || { echo "POST: missing $SHOW_DIR"; exit 1; }
n=0
find . -type f -name "*.eng.dubtitles.srt" \
  | grep -ivE '/(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)/' \
  | sort | while IFS= read -r srt; do
  stem="${srt%.eng.dubtitles.srt}"
  [ -f "$stem.eng.dubtitles.ass" ] && continue   # already assembled -> skip
  echo "### $stem"
  python3 /scripts/repair.py "$stem.dubtitles.conf.json" </dev/null
  python3 /scripts/dub_signs_merge.py "$srt" </dev/null
  n=$((n+1))
done
# One section-level refresh per show (simpler + reliable across multi-season layouts).
if [ -n "${PLEX_URL:-}" ] && [ -n "${PLEX_TOKEN:-}" ]; then
  python3 /scripts/plex_refresh.py "$SHOW_DIR" </dev/null
fi
echo "POST_DONE $SHOW_DIR"
