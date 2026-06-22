#!/bin/sh
# ONE merge pass over the whole Anime Library (runs in a container). For every finished
# dubtitle (.eng.dubtitles.srt) that isn't merged yet (no .eng.dubtitles.ass): repair the
# low-confidence lines via the local LLM, then merge signs/songs into the final .ass.
# Idempotent — once an episode has its .ass it's skipped, so each episode is processed
# exactly once. Refreshes Plex only if this pass actually merged something new.
# Env: MERGE_ROOTS, OLLAMA_URL, REPAIR_MODEL, PLEX_URL, PLEX_TOKEN, PLEX_SECTION.
ROOT="${MERGE_ROOTS:-/media/Anime Library}"
APP="${APP_DIR:-/scripts}"        # where repair.py / dub_signs_merge.py / plex_refresh.py live
command -v ffmpeg >/dev/null 2>&1 || { apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq ffmpeg >/dev/null 2>&1; }
python3 -c "import pysubs2" >/dev/null 2>&1 || pip install -q pysubs2 >/dev/null 2>&1
cd "$ROOT" || { echo "merge_pass: missing $ROOT"; exit 1; }

before=$(find . -type f -name "*.eng.dubtitles.ass" | wc -l)
find . -type f -name "*.eng.dubtitles.srt" \
  | grep -ivE '/(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)/' \
  | sort | while IFS= read -r srt; do
    stem="${srt%.eng.dubtitles.srt}"
    [ -f "$stem.eng.dubtitles.ass" ] && continue    # already merged
    [ -f "$stem.dubtitles.fail" ] && continue        # generate crashed on it -> skip
    echo "### $stem"
    python3 $APP/repair.py "$stem.dubtitles.conf.json" </dev/null    # no-op if high-confidence
    python3 $APP/dub_signs_merge.py "$srt" </dev/null
  done
after=$(find . -type f -name "*.eng.dubtitles.ass" | wc -l)

if [ "$after" -gt "$before" ] && [ -n "${PLEX_TOKEN:-}" ]; then
  echo "merged $((after - before)) new episode(s) -> refreshing Plex"
  python3 $APP/plex_refresh.py "watch" </dev/null
fi
echo "MERGE_PASS_DONE new=$((after - before)) total_ass=$after $(date)"
