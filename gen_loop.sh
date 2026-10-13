#!/bin/sh
# GPU generate loop (in-container, no nested docker). Sweeps the show order transcribing
# each show's English dub; after a full sweep, idles RESCAN_INTERVAL then sweeps again so
# newly added anime get dubtitled automatically. generate.py skips the model load entirely
# when a sweep finds nothing new, so idle rescans are cheap.
set -u
set -e # fail loud (exit, taking down the entrypoint) on anything NOT explicitly tolerated
# below; mine/verify/generate keep their `||` fallthroughs so crash-resume +
# stall-detection (the $after -le $before comparison) still runs even when one fails.
ORDER="${ANIME_ORDER:-/config/anime_order.txt}"
ANIME="${ANIME_ROOT:-/media/Anime Library}"
GLOSS_DIR="${GLOSSARY_DIR:-/config/glossaries}"
CONFIG_DIR="${CONFIG_DIR:-/config}"
REQUESTS_DIR="${REQUESTS_DIR:-$CONFIG_DIR/requests}"
SCHEDULE_FILE="${SCHEDULE_FILE:-$CONFIG_DIR/schedule.json}"
EFFECTIVE_ENV_FILE="${EFFECTIVE_ENV_FILE:-$CONFIG_DIR/effective.env}"
RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-$CONFIG_DIR/runtime.env}"
export CONFIG_DIR RUNTIME_ENV_FILE EFFECTIVE_ENV_FILE

# Snapshot initial container environment for allow-listed runtime settings
_INIT_REPAIR_BACKEND="${REPAIR_BACKEND:-}"
_HAS_INIT_REPAIR_BACKEND="${REPAIR_BACKEND+1}"

_INIT_REPAIR_LLAMACPP_URL="${REPAIR_LLAMACPP_URL:-}"
_HAS_INIT_REPAIR_LLAMACPP_URL="${REPAIR_LLAMACPP_URL+1}"

_INIT_REPAIR_OPENAI_URL="${REPAIR_OPENAI_URL:-}"
_HAS_INIT_REPAIR_OPENAI_URL="${REPAIR_OPENAI_URL+1}"

_INIT_REPAIR_OPENAI_KEY_ENV="${REPAIR_OPENAI_KEY_ENV:-}"
_HAS_INIT_REPAIR_OPENAI_KEY_ENV="${REPAIR_OPENAI_KEY_ENV+1}"

_INIT_REPAIR_MODEL="${REPAIR_MODEL:-}"
_HAS_INIT_REPAIR_MODEL="${REPAIR_MODEL+1}"

_INIT_VERIFY_BACKEND="${VERIFY_BACKEND:-}"
_HAS_INIT_VERIFY_BACKEND="${VERIFY_BACKEND+1}"

_INIT_VERIFY_DECISION_MODEL="${VERIFY_DECISION_MODEL:-}"
_HAS_INIT_VERIFY_DECISION_MODEL="${VERIFY_DECISION_MODEL+1}"

_INIT_REQUIRE_ENG="${REQUIRE_ENG:-}"
_HAS_INIT_REQUIRE_ENG="${REQUIRE_ENG+1}"

restore_runtime_env() {
	if [ -n "$_HAS_INIT_REPAIR_BACKEND" ]; then export REPAIR_BACKEND="$_INIT_REPAIR_BACKEND"; else unset REPAIR_BACKEND; fi
	if [ -n "$_HAS_INIT_REPAIR_LLAMACPP_URL" ]; then export REPAIR_LLAMACPP_URL="$_INIT_REPAIR_LLAMACPP_URL"; else unset REPAIR_LLAMACPP_URL; fi
	if [ -n "$_HAS_INIT_REPAIR_OPENAI_URL" ]; then export REPAIR_OPENAI_URL="$_INIT_REPAIR_OPENAI_URL"; else unset REPAIR_OPENAI_URL; fi
	if [ -n "$_HAS_INIT_REPAIR_OPENAI_KEY_ENV" ]; then export REPAIR_OPENAI_KEY_ENV="$_INIT_REPAIR_OPENAI_KEY_ENV"; else unset REPAIR_OPENAI_KEY_ENV; fi
	if [ -n "$_HAS_INIT_REPAIR_MODEL" ]; then export REPAIR_MODEL="$_INIT_REPAIR_MODEL"; else unset REPAIR_MODEL; fi
	if [ -n "$_HAS_INIT_VERIFY_BACKEND" ]; then export VERIFY_BACKEND="$_INIT_VERIFY_BACKEND"; else unset VERIFY_BACKEND; fi
	if [ -n "$_HAS_INIT_VERIFY_DECISION_MODEL" ]; then export VERIFY_DECISION_MODEL="$_INIT_VERIFY_DECISION_MODEL"; else unset VERIFY_DECISION_MODEL; fi
	if [ -n "$_HAS_INIT_REQUIRE_ENG" ]; then export REQUIRE_ENG="$_INIT_REQUIRE_ENG"; else unset REQUIRE_ENG; fi
}

apply_runtime_env() {
	restore_runtime_env
	if [ -f "$APP_DIR/review_settings_write.py" ]; then
		_exp_err_file="${CONFIG_DIR:-/config}/.exporter.err"
		_exp_out=$(python3 "$APP_DIR/review_settings_write.py" export --scope gen 2>"$_exp_err_file") || true
		if [ -s "$_exp_err_file" ] && [ "${_EXPORTER_LOGGED_THIS_SWEEP:-0}" -eq 0 ]; then
			cat "$_exp_err_file" >&2
			_EXPORTER_LOGGED_THIS_SWEEP=1
		fi
		rm -f "$_exp_err_file"
		eval "$_exp_out" || true
		python3 "$APP_DIR"/review_requests.py write-effective-env "$EFFECTIVE_ENV_FILE" </dev/null 2>&1 || echo "  effective.env write failed (continuing)"
	fi
}

# Soft stop (container_run.sh touches $STOP_FLAG on SIGTERM): stop STARTING work, never kill
# work in flight -- a killed generate.py leaves a permanent .dubtitles.fail poison marker. So
# this script has no `trap` and no `wait`; it only looks at the flag between units.
APP_DIR="${APP_DIR:-/app}"
if [ -f "$APP_DIR/shell/lib.sh" ]; then
	# shellcheck disable=SC1091
	. "$APP_DIR/shell/lib.sh"
else # lib missing (misbuilt image): never stop, plain sleeps
	stop_requested() { return 1; }
	sleep_unless_stopped() { sleep "$1"; }
fi

check_window_open() {
	_win_err_file="${CONFIG_DIR:-/config}/.window.err"
	is_open=$(python3 "$APP_DIR"/review_requests.py window-open "$SCHEDULE_FILE" 2>"$_win_err_file") && rc=0 || rc=$?
	if [ -s "$_win_err_file" ] && [ "${_WINDOW_WARN_LOGGED:-0}" -eq 0 ]; then
		cat "$_win_err_file" >&2
		_WINDOW_WARN_LOGGED=1
	fi
	rm -f "$_win_err_file"
	[ "$rc" -eq 0 ] || is_open="open"
}

wait_for_window() {
	while :; do
		if stop_requested; then return 0; fi
		check_window_open
		[ "$is_open" = "open" ] && return 0
		echo "gen_loop: schedule window closed — sleeping ${SCHEDULE_CHECK_INTERVAL:-60}s"
		sleep_unless_stopped "${SCHEDULE_CHECK_INTERVAL:-60}"
	done
}

drain_requests() {
	if [ "${pruned_this_sweep:-0}" -eq 0 ]; then
		python3 "$APP_DIR"/review_requests.py prune "$REQUESTS_DIR" 7 </dev/null 2>&1 || true
		pruned_this_sweep=1
	fi
	last_req_path=""
	while :; do
		if stop_requested; then return 0; fi
		check_window_open
		[ "$is_open" = "open" ] || break

		req_json=$(python3 "$APP_DIR"/review_requests.py next "$REQUESTS_DIR" 2>/dev/null) && req_rc=0 || req_rc=$?
		[ "$req_rc" -eq 0 ] && [ -n "$req_json" ] || break

		req_out=$(python3 "$APP_DIR"/review_requests.py unpack "$req_json" 2>/dev/null) || break

		req_path="" req_show="" req_gen_re="" req_req_eng=""
		while IFS='=' read -r k v; do
			case "$k" in
				PATH) [ -z "$req_path" ] && req_path="$v" ;;
				SHOW) [ -z "$req_show" ] && req_show="$v" ;;
				GENERATE_ONLY_RE) [ -z "$req_gen_re" ] && req_gen_re="$v" ;;
				REQUIRE_ENG) [ -z "$req_req_eng" ] && req_req_eng="$v" ;;
			esac
		done <<EOF
$req_out
EOF
		[ -n "$req_path" ] && [ -n "$req_show" ] || break

		if [ "$req_path" = "$last_req_path" ]; then
			echo "gen_loop: request $req_path seen twice without progress — stopping drain"
			break
		fi
		last_req_path="$req_path"

		if [ ! -d "$ANIME/$req_show" ]; then
			echo "request show directory not found: $ANIME/$req_show"
			if ! python3 "$APP_DIR"/review_requests.py finish "$req_path" fail "show directory not found" </dev/null 2>&1; then
				echo "gen_loop: failed to mark request $req_path as failed — stopping drain"
				break
			fi
			continue
		fi

		echo "#### RUN REQUEST for $req_show ($req_path) $(date)"
		if ! python3 "$APP_DIR"/review_requests.py start "$req_path" </dev/null 2>&1; then
			echo "gen_loop: failed to claim request $req_path — stopping drain"
			break
		fi

		apply_runtime_env

		req_eng="${req_req_eng:-${REQUIRE_ENG:-1}}"
		GLOSS="$GLOSS_DIR/$req_show.json"
		[ -f "$GLOSS" ] || GLOSS=""

		attempt=0
		rc=""
		while :; do
			if stop_requested; then
				echo "gen_loop: soft stop, not starting a generate pass on request $req_path"
				break
			fi
			attempt=$((attempt + 1))
			before=$(find "$ANIME/$req_show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
			SHOW_NAME="$req_show" GLOSSARY_FILE="$GLOSS" REQUIRE_ENG="$req_eng" COMPUTE_TYPE="${COMPUTE_TYPE:-int8}" \
				GENERATE_ONLY_RE="$req_gen_re" \
				python3 "$APP_DIR"/generate.py --root "$ANIME/$req_show" </dev/null && rc=0 || rc=$?
			after=$(find "$ANIME/$req_show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
			[ "$rc" = "0" ] && break
			if [ "$after" -le "$before" ]; then
				echo "GENERATE stalled on request $req_path (rc=$rc) — moving on"
				break
			fi
			[ "$attempt" -ge 40 ] && {
				echo "GENERATE max passes on request $req_path"
				break
			}
			echo "GENERATE crashed on request $req_path (rc=$rc) — resume pass $((attempt + 1)) $(date)"
		done

		if stop_requested; then
			echo "gen_loop: soft stop around request $req_path — requeuing"
			python3 "$APP_DIR"/review_requests.py requeue "$req_path" </dev/null 2>&1 || echo "gen_loop: failed to requeue request $req_path"
			break
		fi

		if [ "$rc" = "0" ]; then
			if ! python3 "$APP_DIR"/review_requests.py finish "$req_path" ok </dev/null 2>&1; then
				echo "gen_loop: failed to mark request $req_path as done — stopping drain"
				break
			fi
		else
			if ! python3 "$APP_DIR"/review_requests.py finish "$req_path" fail "generate failed (rc=$rc)" </dev/null 2>&1; then
				echo "gen_loop: failed to mark request $req_path as failed — stopping drain"
				break
			fi
		fi
	done
}

while :; do
	pruned_this_sweep=0
	_EXPORTER_LOGGED_THIS_SWEEP=0
	_WINDOW_WARN_LOGGED=0
	if stop_requested; then
		echo "gen_loop: soft stop, not starting the next sweep"
		exit 0
	fi
	wait_for_window
	if stop_requested; then
		echo "gen_loop: soft stop, not starting the next sweep"
		exit 0
	fi
	# Watch-gated queue: rewrite $ORDER from what is actually being watched, unioning
	# WatchState (household/Jellyfin) with Plex history across ALL accounts. Neither source
	# is a superset of the other. watch_queue.py exits non-zero and leaves $ORDER untouched
	# if either is unreachable, so a `||` fallthrough is correct here -- last sweep's queue is
	# a safe answer, an empty one is not. Disabled by leaving WATCH_QUEUE_WINDOW_DAYS unset.
	if [ -n "${WATCH_QUEUE_WINDOW_DAYS:-}" ]; then
		echo "#### WATCH QUEUE $(date)"
		ANIME_ROOT="$ANIME" python3 "$APP_DIR"/watch_queue.py \
			--window-days "$WATCH_QUEUE_WINDOW_DAYS" --out "$ORDER" \
			${WATCH_QUEUE_PIN:+--pin "$WATCH_QUEUE_PIN"} </dev/null ||
			echo "  watch_queue declined to write (keeping the existing order file)"
	fi
	if [ ! -f "$ORDER" ]; then
		echo "gen_loop: no order file $ORDER — idle 300s"
		sleep_unless_stopped 300
		continue
	fi
	echo "==== GENERATE SWEEP $(date) ===="
	python3 "$APP_DIR"/review_requests.py recover "$REQUESTS_DIR" </dev/null 2>&1 || echo "  recover failed (continuing)"
	apply_runtime_env
	[ -f "$APP_DIR/review_settings_write.py" ] || python3 "$APP_DIR"/review_requests.py write-effective-env "$EFFECTIVE_ENV_FILE" </dev/null 2>&1 || echo "  effective.env write failed (continuing)"
	drain_requests
	while IFS= read -r show; do
		if stop_requested; then
			echo "gen_loop: soft stop, not starting ${show:-the next show}"
			exit 0
		fi
		wait_for_window
		if stop_requested; then
			echo "gen_loop: soft stop, not starting ${show:-the next show}"
			exit 0
		fi
		drain_requests
		case "$show" in '' | \#*) continue ;; esac
		[ -d "$ANIME/$show" ] || {
			echo "skip-missing: $show"
			continue
		}
		apply_runtime_env
		# ADDITIVE dictionary: load the show's existing glossary + mine its NEW episodes'
		# embedded subs for new proper nouns, appending them (never rebuilds). Runs before
		# generate so the grown dictionary applies to the episodes about to be transcribed.
		# Each prep step can run for many minutes (ACQUIRE up to 30, VERIFY up to 20): a stop
		# that arrives during one show's prep must not wait for the rest of it.
		if stop_requested; then
			echo "gen_loop: soft stop, not starting MINE on $show"
			exit 0
		fi
		echo "#### MINE $show $(date)"
		GLOSSARY_DIR="$GLOSS_DIR" python3 "$APP_DIR"/mine_glossary.py "$ANIME/$show" </dev/null 2>&1 || echo "  mine failed (continuing)"
		# Acquire names the miner cannot reach: releases with no embedded fansub track leave the
		# glossary empty for that stretch of the show. Wiki-owned canonicals only. Two separate
		# gates: ACQUIRE enables the step at all (default on, dry-run: it only logs proposals);
		# ACQUIRE_APPLY additionally authorises writing them. Default production behaviour is
		# dry-run-and-log until the Punk Hazard verification run has passed. Failure-swallowed
		# so it can never stall a sweep either way.
		if [ "${ACQUIRE:-1}" != "0" ] && [ -f "$GLOSS_DIR/$show.json" ]; then
			if stop_requested; then
				echo "gen_loop: soft stop, not starting ACQUIRE on $show"
				exit 0
			fi
			echo "#### ACQUIRE $show $(date)"
			ACQ_FLAGS=""
			[ -n "${ACQUIRE_APPLY:-}" ] && ACQ_FLAGS="--apply"
			# acquire_cache only memoises escalate()'s LLM adjudication now, never a
			# proposal's final verdict, so a dry run and a later --apply run always
			# propose the same terms -- no ACQUIRE_NO_CACHE workaround needed. See
			# .procoder/todo/20260829-acquire-cache-suppresses-every-verdict.md for the bug
			# this replaced (a dry run's cached verdict used to fold into `settled` and skip
			# the term on every later run, suppressing 22 apply, 1,654 known and 10,708 flag
			# verdicts -- that last group being review-queue entries that would never have
			# surfaced for a human).
			# 600s was also an incremental-era number; a first full acquisition pass over 463
			# episodes exceeded it and was killed mid-harvest on 2026-08-21.
			timeout "${ACQUIRE_TIMEOUT:-1800}" python3 "$APP_DIR"/glossary_acquire.py \
				"$GLOSS_DIR/$show.json" "$ANIME/$show" \
				$ACQ_FLAGS </dev/null 2>&1 || echo "  acquire skipped (continuing)"
		fi
		GLOSS="$GLOSS_DIR/$show.json"
		[ -f "$GLOSS" ] || GLOSS=""
		# Arc tags + arc titles (opt-in, default off): one wiki fetch per distinct season.nfo arc, cached on disk, tags the
		# glossary's names (repair weights its prompt by them) and stores the arc titles VERIFY_ARC_GATE checks writes against.
		# Additive, atomic, failure-swallowed like every prep step; a title that is not an arc changes nothing.
		if [ "${GLOSSARY_ARC_TAGS:-0}" = "1" ] && [ -n "$GLOSS" ]; then
			if stop_requested; then
				echo "gen_loop: soft stop, not starting ARC TAGS on $show"
				exit 0
			fi
			echo "#### ARC TAGS $show $(date)"
			timeout "${ARC_TAGS_TIMEOUT:-600}" python3 "$APP_DIR"/glossary_verify.py "$GLOSS" --tag-arcs "$ANIME/$show" </dev/null 2>&1 ||
				echo "  arc tagging skipped (continuing)"
		fi
		# wiki-verify the (mined/updated) glossary: canonical, dub-preferred spellings. Incremental +
		# cached, and timeout-bounded + failure-swallowed so a slow/down wiki never stalls the sweep.
		if [ -n "$GLOSS" ]; then
			if stop_requested; then
				echo "gen_loop: soft stop, not starting VERIFY on $show"
				exit 0
			fi
			echo "#### VERIFY $show $(date)"
			# 300s was sized for INCREMENTAL verification -- pending_terms() skips anything
			# already in `verified`, so a steady-state run adjudicates a handful of terms. A
			# full re-adjudication (after `verified` is cleared, as on 2026-08-21) is 121 terms
			# for One Pace and hit the wall at exactly 300s. `timeout` returns 124; anything
			# else is a real failure, and collapsing the two into one "skipped" line is how a
			# stage that never once completed still looked like a normal sweep.
			# `&& rc=0 || rc=$?` (the generate.py pattern on line 96) so a `timeout`-killed
			# verify -- exit 124 -- does not trip `set -e` and exit the container before the
			# rc-classified message below ever runs. Verified on vm102 2026-09-05: every restart
			# over the prior 14h exited with code 124, journal-confirmed, with VERIFY_TIMEOUT
			# (1200s) firing on One Pace within ~2s of the restart in every measured instance.
			timeout "${VERIFY_TIMEOUT:-1200}" python3 "$APP_DIR"/glossary_verify.py "$GLOSS" </dev/null 2>&1 && rc=0 || rc=$?
			[ "$rc" -eq 0 ] || { [ "$rc" -eq 124 ] &&
				echo "  verify TIMED OUT after ${VERIFY_TIMEOUT:-1200}s (continuing; terms stay unverified)" ||
				echo "  verify failed rc=$rc (continuing)"; }
		fi
		echo "#### GENERATE $show $(date)"
		# crash-resume: re-run until clean exit or no progress (poison files get a .fail marker)
		attempt=0
		while :; do
			if stop_requested; then
				echo "gen_loop: soft stop, not starting a generate pass on $show"
				break
			fi
			attempt=$((attempt + 1))
			before=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
			# `&& rc=0 || rc=$?` (not a bare command + `rc=$?` on the next line) so a nonzero
			# exit from generate.py doesn't trip `set -e` and kill the container before the
			# crash-resume logic below ever sees it — while still capturing the real exit code.
			SHOW_NAME="$show" GLOSSARY_FILE="$GLOSS" REQUIRE_ENG="${REQUIRE_ENG:-1}" COMPUTE_TYPE="${COMPUTE_TYPE:-int8}" \
				python3 "$APP_DIR"/generate.py --root "$ANIME/$show" </dev/null && rc=0 || rc=$?
			after=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
			[ "$rc" = "0" ] && break
			if [ "$after" -le "$before" ]; then
				echo "GENERATE stalled on $show (rc=$rc) — moving on"
				break
			fi
			[ "$attempt" -ge 40 ] && {
				echo "GENERATE max passes on $show"
				break
			}
			echo "GENERATE crashed on $show (rc=$rc) — resume pass $((attempt + 1)) $(date)"
		done
	done <"$ORDER"
	echo "==== SWEEP COMPLETE — idle ${RESCAN_INTERVAL:-21600}s $(date) ===="
	idle_target="${RESCAN_INTERVAL:-21600}"
	elapsed=0
	last_check=0
	poll_interval="${REQUEST_POLL_INTERVAL:-${IDLE_CHECK_INTERVAL:-60}}"
	while [ "$elapsed" -lt "$idle_target" ]; do
		if stop_requested; then
			echo "gen_loop: soft stop, leaving the idle wait"
			exit 0
		fi
		if [ $((elapsed - last_check)) -ge "$poll_interval" ] || [ "$elapsed" -eq 0 ]; then
			last_check="$elapsed"
			check_window_open
			if [ "$is_open" = "open" ]; then
				req_pending=$(python3 "$APP_DIR"/review_requests.py next "$REQUESTS_DIR" 2>/dev/null) && req_rc=0 || req_rc=$?
				if [ "$req_rc" -eq 0 ] && [ -n "$req_pending" ]; then
					echo "gen_loop: pending request detected during idle wait"
					drain_requests
				fi
			fi
		fi
		sleep_unless_stopped 1
		elapsed=$((elapsed + 1))
	done
	if stop_requested; then
		echo "gen_loop: soft stop, leaving the idle wait"
		exit 0
	fi
done
