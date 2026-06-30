#!/bin/sh
# GPU generate loop (in-container, no nested docker). Sweeps the show order transcribing
# each show's English dub; after a full sweep, idles RESCAN_INTERVAL then sweeps again so
# newly added anime get dubtitled automatically. generate.py skips the model load entirely
# when a sweep finds nothing new, so idle rescans are cheap.
set -u
ORDER="${ANIME_ORDER:-/config/anime_order.txt}"
ANIME="${ANIME_ROOT:-/media/Anime Library}"
GLOSS_DIR="${GLOSSARY_DIR:-/config/glossaries}"

while :; do
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
    GLOSS="$GLOSS_DIR/$show.json"; [ -f "$GLOSS" ] || GLOSS=""
    # wiki-verify the (mined/updated) glossary: canonical, dub-preferred spellings. Incremental +
    # cached, and timeout-bounded + failure-swallowed so a slow/down wiki never stalls the sweep.
    if [ -n "$GLOSS" ]; then
        echo "#### VERIFY $show $(date)"
        timeout 300 python3 /app/glossary_verify.py "$GLOSS" </dev/null 2>&1 || echo "  verify skipped (continuing)"
    fi
    echo "#### GENERATE $show $(date)"
    # crash-resume: re-run until clean exit or no progress (poison files get a .fail marker)
    attempt=0
    while :; do
      attempt=$((attempt+1))
      before=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
      SHOW_NAME="$show" GLOSSARY_FILE="$GLOSS" REQUIRE_ENG=1 COMPUTE_TYPE="${COMPUTE_TYPE:-int8}" \
        python3 /app/generate.py --root "$ANIME/$show" </dev/null
      rc=$?
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
