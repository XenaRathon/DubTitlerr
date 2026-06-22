#!/bin/sh
# HOST orchestrator (docker user): for each One Pace season in priority order,
# generate dubtitles on the 1060, then repair+assemble+Plex-refresh per episode.
# S13/S14 first (showcase the romaji+transcribed karaoke), then the rest. Skips S15
# and any episode that already has an .ass. Run detached via setsid.
MEDIA=/srv/mergerfs/media/Storage/Media
DB=/srv/mergerfs/media/Storage/_dubtitle-builder
MODELS=/srv/dev-disk-by-uuid-bc4780a4-fed0-45c3-a164-19fdb9430dc3/docker/subgen/models
OPHOST="$MEDIA/Anime Library/One Pace"
ORDER="13 14 1 2 3 4 5 6 7 8 9 11 12 16 17 18 19 25 27 28 34 35 36"
for s in $ORDER; do
  SEASON=$(printf 'Season %02d' "$s")
  [ -d "$OPHOST/$SEASON" ] || { echo "skip-missing $SEASON"; continue; }
  echo "############ GENERATE $SEASON $(date)"
  docker rm -f dubgen-roll >/dev/null 2>&1
  docker run --rm --name dubgen-roll --gpus all \
    -v "$MEDIA:/media" -v "$DB:/scripts" -v "$MODELS:/subgen/models" \
    -e COMPUTE_TYPE=int8 --entrypoint python3 mccloud/subgen:2026.06.2 \
    /scripts/generate.py --root "/media/Anime Library/One Pace/$SEASON"
  echo "############ ASSEMBLE+PLEX $SEASON $(date)"
  docker rm -f dubpost-roll >/dev/null 2>&1
  docker run --rm --name dubpost-roll \
    -v "$MEDIA:/media" -v "$DB:/scripts" \
    -e "SEASON_NAME=$SEASON" \
    -e PLEX_URL=http://plex.local:32400 \
    -e PLEX_TOKEN=${PLEX_TOKEN} -e PLEX_SECTION=7 \
    python:3.12-slim sh /scripts/post_season.sh
done
echo "ALLSEASONS_DONE $(date)"
