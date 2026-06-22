#!/bin/sh
# HOST watcher: every INTERVAL seconds, run one merge_pass over the whole Anime Library so
# dubtitles appear in Plex PER-EPISODE as each finishes — decoupled from the GPU generate
# rollout (anime_library.sh GENERATE_ONLY=1), so the CPU/LLM merge runs in parallel with
# the GPU. Run detached:  setsid sh /scripts/merge_watcher.sh >> /scripts/merge_watch.log 2>&1 &
# Uses dub-signs-merge:latest if present (ffmpeg+pysubs2 baked) else falls back to python:slim.
set -u
MEDIA="${MEDIA:-/srv/mergerfs/media/Storage/Media}"
DB="${DB:-/srv/mergerfs/media/Storage/_dubtitle-builder}"
INTERVAL="${INTERVAL:-600}"
PLEX_URL="${PLEX_URL:-http://plex.local:32400}"
PLEX_SECTION="${PLEX_SECTION:-7}"
PLEX_TOKEN="${PLEX_TOKEN:-}"
OLLAMA_URL="${OLLAMA_URL:-http://ollama.local:11434/api/generate}"
REPAIR_MODEL="${REPAIR_MODEL:-qwen2.5:7b}"
if docker image inspect dub-signs-merge:latest >/dev/null 2>&1; then
  IMG="dub-signs-merge:latest"; else IMG="python:3.12-slim"; fi
echo "==== MERGE WATCHER $(date) — image=$IMG interval=${INTERVAL}s ===="

while :; do
  docker rm -f dubmerge-watch >/dev/null 2>&1
  docker run --rm --name dubmerge-watch \
    -v "$MEDIA:/media" -v "$DB:/scripts" \
    -e "MERGE_ROOTS=/media/Anime Library" \
    -e "OLLAMA_URL=$OLLAMA_URL" -e "REPAIR_MODEL=$REPAIR_MODEL" \
    -e "PLEX_URL=$PLEX_URL" -e "PLEX_TOKEN=$PLEX_TOKEN" -e "PLEX_SECTION=$PLEX_SECTION" \
    --entrypoint sh "$IMG" /scripts/merge_pass.sh
  sleep "$INTERVAL"
done
