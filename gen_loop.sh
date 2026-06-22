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
    GLOSS="$GLOSS_DIR/$show.json"; [ -f "$GLOSS" ] || GLOSS=""
    echo "#### GENERATE $show $(date)"
    # crash-resume: re-run until clean exit or no progress (poison files get a .fail marker)
    attempt=0
    while :; do
      attempt=$((attempt+1))
      before=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
      SHOW_NAME="$show" GLOSSARY_FILE="$GLOSS" REQUIRE_ENG=1 COMPUTE_TYPE="${COMPUTE_TYPE:-int8}" \
        python3 /app/generate.py --root "$ANIME/$show"
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
