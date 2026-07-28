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
command -v ffmpeg   >/dev/null 2>&1 || { echo "FATAL: ffmpeg not found — image is misbuilt"; exit 1; }
command -v mkvmerge >/dev/null 2>&1 || { echo "FATAL: mkvmerge not found — image is misbuilt"; exit 1; }
python3 -c "import pysubs2" >/dev/null 2>&1 || { echo "FATAL: pysubs2 not found — image is misbuilt"; exit 1; }
cd "$ROOT" || { echo "merge_pass: missing $ROOT"; exit 1; }

# EXTRA_DIRS single source of truth (B7/B9): data/extras.txt via shell/lib.sh, with an
# inline fallback (the pre-consolidation regex) if the lib or data file isn't present
# (e.g. run under the deprecated $APP=/scripts flow, which doesn't ship these files).
#
# The file test is load-bearing, NOT belt-and-braces: `.` is a POSIX special builtin, so
# sourcing a missing file is a fatal error that terminates a non-interactive shell BEFORE
# the `|| true` is ever considered. Written as `. file || true`, this whole script exited
# silently -- no output, status 2, nothing assembled -- whenever APP_DIR was not /app,
# which is exactly the fallback case the comment above claims to support.
[ -f "$APP/shell/lib.sh" ] && . "$APP/shell/lib.sh"
PATTERN=$(extras_grep_pattern "$APP/data/extras.txt" 2>/dev/null || echo '(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)')

before=$(find . -type f -name "*.dubtitles.done" | wc -l)
# episodes with a sidecar (srt or ass) -> dedup to the stem
find . -type f \( -name "*.eng.dubtitles.srt" -o -name "*.eng.dubtitles.ass" \) \
  | grep -ivE "/$PATTERN/" \
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
