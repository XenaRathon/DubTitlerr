#!/bin/sh
# Run the dubtitles+signs merge in a container, then refresh Plex if anything
# changed. Schedule from cron (e.g. every 20 minutes). All paths/URLs are env
# vars so nothing host-specific is hard-coded.
#
#   MEDIA_ROOT   host path mounted to /data in the container (your media root)
#   IMAGE        the built image tag (default: dub-signs-merge:latest)
#   PLEX_URL     e.g. http://127.0.0.1:32400   (optional; skip refresh if unset)
#   PLEX_TOKEN   Plex auth token               (optional)
#   PLEX_SECTION numeric library section id to refresh (optional)
set -eu

MEDIA_ROOT="${MEDIA_ROOT:?set MEDIA_ROOT to your media folder}"
IMAGE="${IMAGE:-dub-signs-merge:latest}"

OUT=$(docker run --rm -u 0 -v "$MEDIA_ROOT":/data "$IMAGE" 2>&1)
printf '%s\n' "$OUT"

MERGED=$(printf '%s\n' "$OUT" | sed -n "s/.*'merged': \([0-9]\{1,\}\).*/\1/p" | tail -1)
if [ "${MERGED:-0}" -gt 0 ] && [ -n "${PLEX_URL:-}" ] && [ -n "${PLEX_TOKEN:-}" ] && [ -n "${PLEX_SECTION:-}" ]; then
  echo "merged $MERGED -> refreshing Plex section $PLEX_SECTION"
  curl -s -o /dev/null "$PLEX_URL/library/sections/$PLEX_SECTION/refresh?X-Plex-Token=$PLEX_TOKEN"
fi
