# Shared shell helpers for the DubTitlerr pipeline stages (merge_pass.sh, post_show.sh).
# The Python-side single source of truth is common.py::load_extras(); this is its shell
# counterpart, both reading data/extras.txt (see specs/v2-models-ops/spec.md, "EXTRA_DIRS
# consolidation"). Meant to be `source`d, not executed.

# extras_grep_pattern [path] — reads data/extras.txt (one dir name per line, `#` comments
# allowed, default path "data/extras.txt") and prints a grep -iE alternation pattern, e.g.
# '(Behind The Scenes|Deleted Scenes|Featurettes|Interviews|Scenes|Shorts|Trailers|Other|Extras)'
# — the same set the pre-consolidation inline regex in merge_pass.sh/post_show.sh matched
# (title-case is cosmetic only: callers use `grep -i`, so matching is case-insensitive
# regardless). Prints nothing (empty parens) if the file is missing/empty/unreadable --
# callers should fall back to an inline pattern in that case (see B9).
extras_grep_pattern() {
    dir="${1:-data/extras.txt}"
    pattern=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$dir" 2>/dev/null \
        | awk '{for (i = 1; i <= NF; i++) $i = toupper(substr($i, 1, 1)) substr($i, 2); print}' \
        | paste -sd'|' -)
    printf '(%s)' "$pattern"
}
