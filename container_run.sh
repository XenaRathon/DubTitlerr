#!/bin/sh
# Entrypoint for the dubtitle-builder container. Runs three loops in parallel:
#   - merge loop  (CPU + local LLM): every MERGE_INTERVAL, repair+merge+Plex-refresh any
#     newly finished episode across the library -> subs appear in Plex per-episode.
#   - review loop (idle): the [S-7] review page, where a human rules on the repairs
#     accept_repair admitted without anything checking their meaning.
#   - generate loop (GPU): sweep the show order transcribing English dubs; when the sweep
#     is fully caught up, idle RESCAN_INTERVAL then sweep again to pick up newly added anime.
# Idempotent + restart-safe: done episodes are skipped instantly, so a restart just resumes.
set -u
export APP_DIR=/app
: "${MERGE_INTERVAL:=600}"    # seconds between merge sweeps
: "${RESCAN_INTERVAL:=21600}" # seconds to idle after a full generate sweep (default 6h)
: "${REVIEW_RESTART:=15}"     # seconds before restarting the review server after an exit

echo "==== dubtitle-builder up $(date) — merge_interval=${MERGE_INTERVAL}s rescan=${RESCAN_INTERVAL}s ===="

# merge loop in the background
(
	while :; do
		sh /app/merge_pass.sh || echo "merge_pass error (continuing)"
		sleep "$MERGE_INTERVAL"
	done
) &

# review server in the background. [S-8]: its failure must not take down the container, so
# it is a restart loop inside a subshell rather than a bare launch -- a port already in use
# or an unwritable token directory is an annoyance to be logged and retried, never an outage
# that stops the GPU sweep mid-episode and leaves a .dubtitles.fail poison marker behind.
# It NEVER takes the exec slot below: that is the generate loop's, and it is what keeps the
# container alive.
(
	while :; do
		python3 /app/review_server.py || echo "review_server exited (restarting in ${REVIEW_RESTART}s)"
		sleep "$REVIEW_RESTART"
	done
) &

# generate loop in the foreground keeps the container alive
exec sh /app/gen_loop.sh
