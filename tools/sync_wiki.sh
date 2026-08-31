#!/usr/bin/env bash
# Publish docs/wiki/ to the GitHub and forgejo wiki repositories.
#
# The wiki is authored in this repository so it is reviewed in pull requests and stays
# version-locked to the release it documents. The two hosts each keep their own wiki git
# repository, so neither can be a git remote of the other; this script is the bridge.
#
# Page names are chosen so both hosts render the same title: each host maps "-" in a
# filename to a space, so a name with no intentional hyphen in its title round-trips
# identically on both. Do not add a page whose title needs a literal hyphen.
#
# Usage:
#   tools/sync_wiki.sh            # dry run: show what would change
#   tools/sync_wiki.sh --push     # commit and push to both hosts
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/docs/wiki"
GITHUB_WIKI="${GITHUB_WIKI:-https://github.com/XenaRathon/DubTitlerr.wiki.git}"
FORGEJO_WIKI="${FORGEJO_WIKI:-https://git.ourserver.party/xenarathon/DubTitlerr.wiki.git}"
PUSH=0
[ "${1:-}" = "--push" ] && PUSH=1

[ -d "$SRC" ] || {
	echo "no such directory: $SRC" >&2
	exit 1
}
ls "$SRC"/*.md >/dev/null 2>&1 || {
	echo "no pages in $SRC" >&2
	exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

for host in github forgejo; do
	case "$host" in
	github) url="$GITHUB_WIKI" ;;
	forgejo) url="$FORGEJO_WIKI" ;;
	esac

	echo "=== $host: $url"
	dst="$work/$host"
	if ! git clone --quiet "$url" "$dst" 2>/dev/null; then
		echo "  SKIP: cannot clone. Create the first wiki page in the web UI, then re-run." >&2
		continue
	fi

	# Replace the whole page set: pages removed from docs/wiki/ are removed from the wiki.
	# Deliberate -- a stale page nobody links to is worse than a missing one, because it is
	# still found by search and still read as current.
	find "$dst" -maxdepth 1 -name '*.md' -delete
	cp "$SRC"/*.md "$dst/"

	if git -C "$dst" diff --quiet && [ -z "$(git -C "$dst" status --porcelain)" ]; then
		echo "  already current"
		continue
	fi

	git -C "$dst" add -A
	echo "  changes:"
	git -C "$dst" status --short | sed 's/^/    /'

	if [ "$PUSH" -eq 1 ]; then
		git -C "$dst" commit --quiet -m "wiki: sync from docs/wiki at $(git -C "$SRC/.." rev-parse --short HEAD)"
		git -C "$dst" push --quiet
		echo "  pushed"
	else
		echo "  (dry run -- pass --push to publish)"
	fi
done
