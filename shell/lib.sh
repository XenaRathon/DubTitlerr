# shellcheck shell=sh  # sourced by merge_pass.sh, which is #!/bin/sh
# Shared shell helpers for the DubTitlerr pipeline stages (merge_pass.sh, post_show.sh).
# The Python-side single source of truth is common.py::load_extras(); this is its shell
# counterpart, both reading data/extras.txt (see specs/v2-models-ops/spec.md, "EXTRA_DIRS
# consolidation"). Meant to be `source`d, not executed.

# extras_grep_pattern [path] — reads data/extras.txt (one dir name per line, `#` comments
# allowed, default path "data/extras.txt") and prints a grep -iE alternation pattern, e.g.
# '(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)'
# — the same set the pre-consolidation inline regex in merge_pass.sh/post_show.sh matched
# (title-case is cosmetic only: callers use `grep -i`, so matching is case-insensitive
# regardless). Fails (prints nothing, returns 1) if the file is missing/empty/unreadable
# -- callers should fall back to an inline pattern in that case (see B9); a pattern that
# always prints even a hollow "()" would make `grep -ivE` match (and thus exclude) every
# line, since an empty alternation matches the empty string in any input.
# Returns 1 (prints nothing) if the file is missing/empty/unreadable so callers can
# detect the failure via `||` on the command substitution -- see B9 in
# specs/v2-models-ops/tasks.md for the source/fallback pattern this is designed for.
extras_grep_pattern() {
	dir="${1:-data/extras.txt}"
	pattern=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$dir" 2>/dev/null |
		awk '{for (i = 1; i <= NF; i++) $i = toupper(substr($i, 1, 1)) substr($i, 2); print}' |
		paste -sd'|' -)
	[ -z "$pattern" ] && return 1
	printf '(%s)' "$pattern"
}

# stop_requested — true once the soft-stop flag file exists. container_run.sh (PID 1) touches
# $STOP_FLAG on SIGTERM; every loop that STARTS work checks it and winds down instead of
# starting the next unit. With STOP_FLAG unset (manual runs, tests) nothing ever stops.
# Use inside if/&&/|| only: it returns 1 in the normal case, which `set -e` would treat as fatal.
stop_requested() {
	[ -n "${STOP_FLAG:-}" ] && [ -e "$STOP_FLAG" ]
}

# sleep_unless_stopped SECONDS — an interruptible sleep without any signal plumbing: sleeps in
# 5 s steps and returns early once the stop flag exists. Always returns 0 (safe under set -e).
# An argument that is not a plain integer ("1.5", "6h") is passed to plain sleep as is.
sleep_unless_stopped() {
	case "${1:-}" in
	'' | *[!0-9]*) # not whole seconds ("1.5", "6h"): let sleep parse it, uninterruptibly
		sleep "${1:-0}"
		return 0
		;;
	esac
	_sus_left="$1"
	while [ "$_sus_left" -gt 0 ]; do
		if stop_requested; then
			return 0
		fi
		if [ "$_sus_left" -gt 5 ]; then
			sleep 5
			_sus_left=$((_sus_left - 5))
		else
			sleep "$_sus_left"
			_sus_left=0
		fi
	done
	return 0
}
