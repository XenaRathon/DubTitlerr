#!/bin/sh
# HOST orchestrator (docker user) for the WHOLE Anime Library — the generalization of
# all_seasons.sh from One Pace to every dubbed show. For each show folder listed in
# anime_order.txt (priority order), it:
#   1. GENERATE on the 1060: transcribe the English-dub audio (skips sub-only releases
#      via REQUIRE_ENG=1; uses a per-show glossary if glossaries/<show>.json exists),
#   2. POST: repair low-confidence lines (local LLM) + merge signs/songs + refresh Plex.
# Idempotent & resumable: every stage skips episodes already done, so re-running just
# continues. Run detached:  setsid sh /scripts/anime_library.sh >> /scripts/anime.log 2>&1 &
set -u
MEDIA="${MEDIA:-/srv/mergerfs/media/Storage/Media}"
DB="${DB:-/srv/mergerfs/media/Storage/_dubtitle-builder}"
MODELS="${MODELS:-/srv/dev-disk-by-uuid-bc4780a4-fed0-45c3-a164-19fdb9430dc3/docker/subgen/models}"
SUBGEN_IMAGE="${SUBGEN_IMAGE:-mccloud/subgen:2026.06.2}"
POST_IMAGE="${POST_IMAGE:-python:3.12-slim}"
LIST="${1:-${LIST:-$DB/anime_order.txt}}"
PLEX_URL="${PLEX_URL:-http://plex.local:32400}"
PLEX_SECTION="${PLEX_SECTION:-7}"
PLEX_TOKEN="${PLEX_TOKEN:-}"          # pass at invocation; empty -> skip Plex refresh
OLLAMA_URL="${OLLAMA_URL:-http://ollama.local:11434/api/generate}"
REPAIR_MODEL="${REPAIR_MODEL:-qwen2.5:7b}"
ANIME="$MEDIA/Anime Library"

[ -f "$LIST" ] || { echo "no order list: $LIST"; exit 1; }
echo "==== ANIME LIBRARY DUBTITLE ROLLOUT $(date) — list=$LIST ===="

while IFS= read -r show; do
  case "$show" in ''|\#*) continue;; esac
  [ -d "$ANIME/$show" ] || { echo "skip-missing: $show"; continue; }
  GLOSS="/scripts/glossaries/$show.json"
  [ -f "$DB/glossaries/$show.json" ] || GLOSS=""

  echo "############ GENERATE $show $(date)"
  # Crash-resume: a hard whisper/ffmpeg crash kills the container; re-run resumes (done
  # files skipped, the poison file gets a .fail marker so it's skipped too). Stop when it
  # exits clean, or when a whole pass adds no new output (genuinely stuck), max 40 passes.
  attempt=0
  while :; do
    attempt=$((attempt+1))
    before=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
    docker rm -f dubgen-roll >/dev/null 2>&1
    docker run --rm --name dubgen-roll --gpus all \
      -v "$MEDIA:/media" -v "$DB:/scripts" -v "$MODELS:/subgen/models" \
      -e COMPUTE_TYPE=int8 -e REQUIRE_ENG=1 -e "SHOW_NAME=$show" -e "GLOSSARY_FILE=$GLOSS" \
      --entrypoint python3 "$SUBGEN_IMAGE" \
      /scripts/generate.py --root "/media/Anime Library/$show"
    rc=$?
    after=$(find "$ANIME/$show" \( -name "*.eng.dubtitles.srt" -o -name "*.dubtitles.fail" \) 2>/dev/null | wc -l)
    [ "$rc" = "0" ] && break
    if [ "$after" -le "$before" ]; then echo "GENERATE stalled on $show (rc=$rc, no progress) — moving on"; break; fi
    [ "$attempt" -ge 40 ] && { echo "GENERATE hit max passes on $show"; break; }
    echo "GENERATE crashed on $show (rc=$rc) — resume pass $((attempt+1)) $(date)"
  done

  # POST (repair+merge+refresh) per show — SKIP when GENERATE_ONLY=1, i.e. when the
  # decoupled merge_watcher.sh is handling repair/merge/refresh per-episode instead.
  if [ "${GENERATE_ONLY:-0}" != "1" ]; then
    echo "############ POST $show $(date)"
    docker rm -f dubpost-roll >/dev/null 2>&1
    docker run --rm --name dubpost-roll \
      -v "$MEDIA:/media" -v "$DB:/scripts" \
      -e "SHOW_DIR=$show" \
      -e "OLLAMA_URL=$OLLAMA_URL" -e "REPAIR_MODEL=$REPAIR_MODEL" \
      -e "PLEX_URL=$PLEX_URL" -e "PLEX_TOKEN=$PLEX_TOKEN" -e "PLEX_SECTION=$PLEX_SECTION" \
      "$POST_IMAGE" sh /scripts/post_show.sh
  fi
done < "$LIST"
echo "==== ANIME_LIBRARY_DONE $(date) ===="
