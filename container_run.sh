#!/bin/sh
# Entrypoint (supervisor) for the dubtitle-builder container. Runs three loops in parallel:
#   - merge loop  (CPU + local LLM): every MERGE_INTERVAL, repair+merge+Plex-refresh any
#     newly finished episode across the library -> subs appear in Plex per-episode.
#   - review loop (idle): the [S-7] review page, where a human rules on the repairs
#     accept_repair admitted without anything checking their meaning.
#   - generate loop (GPU): sweep the show order transcribing English dubs; when the sweep
#     is fully caught up, idle RESCAN_INTERVAL then sweep again to pick up newly added anime.
# Idempotent + restart-safe: done episodes are skipped instantly, so a restart just resumes.
#
# SOFT STOP. The host stops the container with `docker stop`, i.e. SIGTERM to PID 1 and,
# after the grace period, SIGKILL -- and a SIGKILL during transcription leaves a permanent
# <stem>.dubtitles.fail poison marker. So this script is a supervisor, not an exec: on
# SIGTERM/SIGINT it only touches $STOP_FLAG. gen_loop.sh, merge_pass.sh and generate.py
# check the flag BETWEEN units of work, finish the unit in flight, and exit; the signal is
# never forwarded to them (only to the stateless review server).
set -u
: "${APP_DIR:=/app}"
export APP_DIR
: "${STOP_FLAG:=/tmp/dubtitlerr.stop}"
export STOP_FLAG
rm -f "$STOP_FLAG" # a stale flag from an earlier `docker stop` + `docker start` must not stop a fresh run
: "${MERGE_INTERVAL:=600}"    # seconds between merge sweeps
: "${RESCAN_INTERVAL:=21600}" # seconds to idle after a full generate sweep (default 6h)
: "${REVIEW_RESTART:=15}"     # seconds before restarting the review server after an exit
# Hours in which a merge sweep may run, "HH:MM-HH:MM". EMPTY BY DEFAULT: an install that has
# not opted in behaves exactly as before. Set it when the repair backend is only up for part
# of the day -- a sweep that runs with the endpoint down used to queue one unreviewable
# llm_empty entry per target (measured: 1,299 across 11 episodes) before repair.process
# learned to refuse. The window stops the wasted work; the guard stops the damage.
: "${MERGE_WINDOW:=}"

echo "==== dubtitle-builder up $(date) — merge_interval=${MERGE_INTERVAL}s rescan=${RESCAN_INTERVAL}s ===="

if [ -f "$APP_DIR/shell/lib.sh" ]; then
	. "$APP_DIR/shell/lib.sh"
else # lib missing (misbuilt image): never stop, plain sleeps
	stop_requested() { return 1; }
	sleep_unless_stopped() { sleep "$1"; }
fi

# merge loop in the background. It checks the flag at the top of each iteration; the merge
# pass in flight finishes first (merge_pass.sh stops starting new stems on its own).
(
	while :; do
		if stop_requested; then break; fi
		if [ -n "$MERGE_WINDOW" ] && ! python3 -c "import sys,time,common; t=time.localtime(); sys.exit(0 if common.within_window(sys.argv[1], t.tm_hour, t.tm_min) else 1)" "$MERGE_WINDOW" 2>/dev/null; then
			echo "merge_pass: outside MERGE_WINDOW=$MERGE_WINDOW ($(date +%H:%M)) — skipping this sweep"
		else
			sh "$APP_DIR/merge_pass.sh" || echo "merge_pass error (continuing)"
		fi
		sleep_unless_stopped "$MERGE_INTERVAL"
	done
) &
merge_pid=$!

# review server in the background. [S-8]: its failure must not take down the container, so
# it is a restart loop inside a subshell rather than a bare launch -- a port already in use
# or an unwritable token directory is an annoyance to be logged and retried, never an outage
# that stops the GPU sweep mid-episode and leaves a .dubtitles.fail poison marker behind.
# The generate loop below is what keeps the container alive. The review server is stateless,
# so unlike the other loops it IS killed on SIGTERM (the subshell's TERM trap does it) and is
# not restarted once the stop flag exists.
(
	while :; do
		if stop_requested; then break; fi
		python3 "$APP_DIR/review_server.py" &
		c=$!
		trap 'kill $c 2>/dev/null; exit 0' TERM
		wait "$c" || echo "review_server exited (restarting in ${REVIEW_RESTART}s)"
		if stop_requested; then break; fi
		sleep_unless_stopped "$REVIEW_RESTART"
	done
) &
review_pid=$!

# generate loop in the background too; this script supervises it.
sh "$APP_DIR/gen_loop.sh" &
gen_pid=$!

# PID 1 only: the signal becomes a flag. Nothing here ever signals gen_loop/merge/generate/mux.
trap 'touch "$STOP_FLAG"; echo "soft stop requested $(date)"; kill -TERM "$review_pid" 2>/dev/null' TERM INT

# `wait` returns early when a trapped signal arrives; loop until the child is really gone.
rc=0
while :; do
	wait "$gen_pid"
	rc=$?
	kill -0 "$gen_pid" 2>/dev/null || break
done

if stop_requested; then
	# soft stop: gen_loop exited because of the flag; let the merge pass in flight finish
	while :; do
		wait "$merge_pid"
		kill -0 "$merge_pid" 2>/dev/null || break
	done
	echo "soft stop complete $(date)"
	exit 0
fi

# gen_loop died on its own: fail loud (container exits, the restart policy restarts it).
kill "$merge_pid" "$review_pid" 2>/dev/null
exit "$rc"
