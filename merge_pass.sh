#!/bin/sh
# ONE merge+mux pass over the whole Anime Library (runs in the container, as root).
# For every episode with a dubtitle sidecar that isn't muxed yet:
#   1. assemble: repair low-confidence lines + merge signs/songs into a .ass (mkv);
#      mp4 episodes have no embedded signs so they stay a dialogue-only .srt,
#   2. mux: embed the .ass (mkv) / .srt (mp4) into the video as a default "Dubtitles"
#      track WITH the embedded fonts (mp4 is remuxed to mkv) -> signs render correctly,
#      a .dubtitles.done stamp is written, sidecars removed.
# Idempotent: a muxed episode has the stamp + embedded track, so it's skipped next pass.
# Per-episode availability; refreshes Plex when this pass muxed anything new.
# Env: MERGE_ROOTS, OLLAMA_URL, REPAIR_MODEL, GLOSSARY_DIR, PLEX_URL, PLEX_TOKEN, PLEX_SECTION,
#      MIN_FREE_GB, KEEP_LANGS.
ROOT="${MERGE_ROOTS:-/media/Anime Library}"
APP="${APP_DIR:-/scripts}"
command -v ffmpeg  >/dev/null 2>&1 || { apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq ffmpeg >/dev/null 2>&1; }
command -v mkvmerge >/dev/null 2>&1 || { apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq mkvtoolnix >/dev/null 2>&1; }
python3 -c "import pysubs2" >/dev/null 2>&1 || pip install -q pysubs2 >/dev/null 2>&1
cd "$ROOT" || { echo "merge_pass: missing $ROOT"; exit 1; }

before=$(find . -type f -name "*.dubtitles.done" | wc -l)
# episodes with a sidecar (srt or ass) -> dedup to the stem
find . -type f \( -name "*.eng.dubtitles.srt" -o -name "*.eng.dubtitles.ass" \) \
  | grep -ivE '/(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)/' \
  | sed -E 's/\.eng\.dubtitles\.(srt|ass)$//' | sort -u | while IFS= read -r stem; do
    [ -f "$stem.dubtitles.fail" ] && continue            # generate crashed on it -> skip
    if [ ! -f "$stem.eng.dubtitles.ass" ] && [ -f "$stem.eng.dubtitles.srt" ]; then
        echo "### assemble $stem"
        python3 "$APP/repair.py" "$stem.dubtitles.conf.json" </dev/null
        python3 "$APP/dub_signs_merge.py" "$stem.eng.dubtitles.srt" </dev/null
    fi
    for ext in mkv mp4 m4v; do                           # mux the video (root); embeds + stamps
        [ -f "$stem.$ext" ] && { python3 "$APP/mux.py" --apply "$stem.$ext" </dev/null; break; }
    done
done
after=$(find . -type f -name "*.dubtitles.done" | wc -l)

if [ "$after" -gt "$before" ] && [ -n "${PLEX_TOKEN:-}" ]; then
  echo "muxed $((after - before)) new episode(s) -> refreshing Plex"
  python3 "$APP/plex_refresh.py" "watch" </dev/null
fi
echo "MERGE_PASS_DONE new=$((after - before)) total_done=$after $(date)"
