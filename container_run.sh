#!/bin/sh
# Entrypoint for the dubtitle-builder container. Runs two loops in parallel:
#   - merge loop  (CPU + local LLM): every MERGE_INTERVAL, repair+merge+Plex-refresh any
#     newly finished episode across the library -> subs appear in Plex per-episode.
#   - generate loop (GPU): sweep the show order transcribing English dubs; when the sweep
#     is fully caught up, idle RESCAN_INTERVAL then sweep again to pick up newly added anime.
# Idempotent + restart-safe: done episodes are skipped instantly, so a restart just resumes.
set -u
export APP_DIR=/app
: "${MERGE_INTERVAL:=600}"        # seconds between merge sweeps
: "${RESCAN_INTERVAL:=21600}"     # seconds to idle after a full generate sweep (default 6h)

echo "==== dubtitle-builder up $(date) — merge_interval=${MERGE_INTERVAL}s rescan=${RESCAN_INTERVAL}s ===="

# merge loop in the background
(
  while :; do
    sh /app/merge_pass.sh || echo "merge_pass error (continuing)"
    sleep "$MERGE_INTERVAL"
  done
) &

# generate loop in the foreground keeps the container alive
exec sh /app/gen_loop.sh
