#!/bin/sh
# Periodic publish of the subtitle export to the public repository.
#
# CADENCE: twice daily, 08:00 and 22:00 -- deploy/dubtitlerr-publish.timer. The two slots
# are not arbitrary and are not the same job:
#   08:00  publishes what the generate/merge loops finished OVERNIGHT.
#   22:00  publishes what a HUMAN reviewed during the day. A verdict reopens its episode,
#          so the re-mux has to land before the export can see the corrected text -- an
#          evening slot is what makes a day's review reach the public repo the same day.
#
# A TIMER, deliberately not a hook in merge_pass.sh. Publishing is outward-facing and
# effectively irreversible once anyone has cloned, so it is decoupled from the pipeline: a
# bad sweep gets a window to be noticed before it ships, and a TEXT_VERSION bump lands as
# one batch instead of hundreds of pushes.
#
# CHANGE DETECTION belongs to export_subtitles.py, not to this script. It republishes on
# CONTENT, so a run that re-derives the library without changing any output produces an
# empty diff and this script exits without committing. Do not add an mtime check here.
#
# NO LICENSE FILE is written into the subtitle repository. It is subtitle text, not code;
# DubTitlerr itself stays GPL-3.0 and that covers the tooling, not the output.
#
# Env:
#   SUBS_REPO      checkout of the public subtitle repo (required)
#   MEDIA_ROOT     library root (default /media/Anime Library)
#   DECISIONS_DIR  decision stores, for the reviewed/unreviewed status field
#   SHOWS          newline- or space-separated show directory names (default: all)
#   PUBLISH_APPLY  set to 1 to commit and push; unset = dry run
set -eu

APP="${APP_DIR:-/app}"
MEDIA_ROOT="${MEDIA_ROOT:-/media/Anime Library}"
DECISIONS_DIR="${DECISIONS_DIR:-/config/decisions}"
: "${SUBS_REPO:?SUBS_REPO must point at a checkout of the public subtitle repo}"

[ -d "$SUBS_REPO/.git" ] || {
	echo "publish: $SUBS_REPO is not a git checkout — refusing" >&2
	exit 2
}

shows="${SHOWS:-}"
if [ -z "$shows" ]; then
	shows=$(find "$MEDIA_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
fi

echo "$shows" | while IFS= read -r show; do
	[ -n "$show" ] || continue
	out=$(python3 "$APP/tools/export_subtitles.py" \
		--show "$show" \
		--media-root "$MEDIA_ROOT" \
		--out "$SUBS_REPO/subtitles" \
		--manifest "$SUBS_REPO/manifest/$show.json" \
		--decisions-dir "$DECISIONS_DIR" 2>&1) || {
		# One unreadable show must not abandon the rest of the library.
		echo "publish: FAILED for $show — $out" >&2
		continue
	}
	echo "$show: $(echo "$out" | tail -1)"
done

cd "$SUBS_REPO"

# git is what publishes. Without it every command below is an empty string, and the
# porcelain check then reads "nothing changed" and exits 0 -- a silent success that
# publishes nothing, forever. Observed 2026-09-04: the container image carried no git and
# a full library sweep reported success while committing nothing.
command -v git >/dev/null 2>&1 || {
	echo "publish: git is not installed in this environment — refusing" >&2
	exit 3
}

if [ -z "$(git status --porcelain)" ]; then
	echo "publish: nothing changed — no commit"
	exit 0
fi

git add -A
n=$(git diff --cached --name-only | wc -l)
if [ "${PUBLISH_APPLY:-}" != "1" ]; then
	echo "publish: DRY RUN — $n file(s) would be committed and pushed"
	git diff --cached --stat | tail -20
	git reset -q
	exit 0
fi

git -c user.name="dubtitlerr" -c user.email="dubtitlerr@localhost" \
	commit -q -m "subtitles: sync $(date -u +%Y-%m-%dT%H:%MZ) ($n file(s))"
git push -q
echo "publish: pushed $n file(s)"
