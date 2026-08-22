#!/bin/sh
# GPU generate loop (in-container, no nested docker). Sweeps the show order transcribing
# each show's English dub; after a full sweep, idles RESCAN_INTERVAL then sweeps again so
# newly added anime get dubtitled automatically. generate.py skips the model load entirely
# when a sweep finds nothing new, so idle rescans are cheap.
set -u
set -e   # fail loud (exit, taking down the entrypoint) on anything NOT explicitly tolerated
         # below; mine/verify/generate keep their `||` fallthroughs so crash-resume +
         # stall-detection (the $after -le $before comparison) still runs even when one fails.
ORDER="${ANIME_ORDER:-/config/anime_order.txt}"
ANIME="${ANIME_ROOT:-/media/Anime Library}"
GLOSS_DIR="${GLOSSARY_DIR:-/config/glossaries}"

while :; do
  # Watch-gated queue: rewrite $ORDER from what is actually being watched, unioning
  # WatchState (household/Jellyfin) with Plex history across ALL accounts. Neither source
  # is a superset of the other. watch_queue.py exits non-zero and leaves $ORDER untouched
  # if either is unreachable, so a `||` fallthrough is correct here -- last sweep's queue is
  # a safe answer, an empty one is not. Disabled by leaving WATCH_QUEUE_WINDOW_DAYS unset.
  if [ -n "${WATCH_QUEUE_WINDOW_DAYS:-}" ]; then
    echo "#### WATCH QUEUE $(date)"
    ANIME_ROOT="$ANIME" python3 /app/watch_queue.py \
      --window-days "$WATCH_QUEUE_WINDOW_DAYS" --out "$ORDER" \
      ${WATCH_QUEUE_PIN:+--pin "$WATCH_QUEUE_PIN"} </dev/null \
      || echo "  watch_queue declined to write (keeping the existing order file)"
  fi
  if [ ! -f "$ORDER" ]; then echo "gen_loop: no order file $ORDER — idle 300s"; sleep 300; continue; fi
  echo "==== GENERATE SWEEP $(date) ===="
  while IFS= read -r show; do
    case "$show" in ''|\#*) continue;; esac
    [ -d "$ANIME/$show" ] || { echo "skip-missing: $show"; continue; }
    # ADDITIVE dictionary: load the show's existing glossary + mine its NEW episodes'
    # embedded subs for new proper nouns, appending them (never rebuilds). Runs before
    # generate so the grown dictionary applies to the episodes about to be transcribed.
    echo "#### MINE $show $(date)"
    GLOSSARY_DIR="$GLOSS_DIR" python3 /app/mine_glossary.py "$ANIME/$show" </dev/null 2>&1 || echo "  mine failed (continuing)"
    # Acquire names the miner cannot reach: releases with no embedded fansub track leave the
    # glossary empty for that stretch of the show. Wiki-owned canonicals only. Two separate
    # gates: ACQUIRE enables the step at all (default on, dry-run: it only logs proposals);
    # ACQUIRE_APPLY additionally authorises writing them. Default production behaviour is
    # dry-run-and-log until the Punk Hazard verification run has passed. Failure-swallowed
    # so it can never stall a sweep either way.
    if [ "${ACQUIRE:-1}" != "0" ] && [ -f "$GLOSS_DIR/$show.json" ]; then
        echo "#### ACQUIRE $show $(date)"
        ACQ_FLAGS=""
        [ -n "${ACQUIRE_APPLY:-}" ] && ACQ_FLAGS="--apply"
        # 600s was also an incremental-era number; a first full acquisition pass over 463
        # episodes exceeded it and was killed mid-harvest on 2026-08-21.
        timeout "${ACQUIRE_TIMEOUT:-1800}" python3 /app/glossary_acquire.py "$GLOSS_DIR/$show.json" "$ANIME/$show" \
            $ACQ_FLAGS </dev/null 2>&1 || echo "  acquire skipped (continuing)"
    fi
    GLOSS="$GLOSS_DIR/$show.json"; [ -f "$GLOSS" ] || GLOSS=""
    # wiki-verify the (mined/updated) glossary: canonical, dub-preferred spellings. Incremental +
    # cached, and timeout-bounded + failure-swallowed so a slow/down wiki never stalls the sweep.
    if [ -n "$GLOSS" ]; then
        echo "#### VERIFY $show $(date)"
        # 300s was sized for INCREMENTAL verification -- pending_terms() skips anything
        # already in `verified`, so a steady-state run adjudicates a handful of terms. A
        # full re-adjudication (after `verified` is cleared, as on 2026-08-21) is 121 terms
        # for One Pace and hit the wall at exactly 300s. `timeout` returns 124; anything
        # else is a real failure, and collapsing the two into one "skipped" line is how a
        # stage that never once completed still looked like a normal sweep.
        timeout "${VERIFY_TIMEOUT:-1200}" python3 /app/glossary_verify.py "$GLOSS" </dev/null 2>&1
        rc=$?
        [ $rc -eq 0 ]   || { [ $rc -eq 124 ] \
            && echo "  verify TIMED OUT after ${VERIFY_TIMEOUT:-1200}s (continuing; terms stay unverified)" \
            || echo "  verify failed rc=$rc (continuing)"; }
    fi
    echo "#### GENERATE $show $(date)"
    # crash-resume: re-run until clean exit or no progress (poison files get a .fail marker)
    attempt=0
    while :; do
      attempt=$((attempt+1))
      before=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
      # `&& rc=0 || rc=$?` (not a bare command + `rc=$?` on the next line) so a nonzero
      # exit from generate.py doesn't trip `set -e` and kill the container before the
      # crash-resume logic below ever sees it — while still capturing the real exit code.
      SHOW_NAME="$show" GLOSSARY_FILE="$GLOSS" REQUIRE_ENG=1 COMPUTE_TYPE="${COMPUTE_TYPE:-int8}" \
        python3 /app/generate.py --root "$ANIME/$show" </dev/null && rc=0 || rc=$?
      after=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
      [ "$rc" = "0" ] && break
      if [ "$after" -le "$before" ]; then echo "GENERATE stalled on $show (rc=$rc) — moving on"; break; fi
      [ "$attempt" -ge 40 ] && { echo "GENERATE max passes on $show"; break; }
      echo "GENERATE crashed on $show (rc=$rc) — resume pass $((attempt+1)) $(date)"
    done
  done < "$ORDER"
  echo "==== SWEEP COMPLETE — idle ${RESCAN_INTERVAL:-21600}s $(date) ===="
  sleep "${RESCAN_INTERVAL:-21600}"
done
