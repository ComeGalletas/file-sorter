#!/usr/bin/env bash
# Which reviewer subagent a PR gets (RUN-006.D1). Prints one line:
#   reviewer-quick (<reason>)   small PR that changes only docs/ and README.md: static Haiku review
#   reviewer (<reason>)         everything else: the full Sonnet review, reproductions included
# The privacy-auditor runs on every PR regardless.
#
# Usage: bash scripts/review_route.sh <pr-number>
# Tests set REVIEW_ROUTE_FILES (one path per line) and REVIEW_ROUTE_BODY instead of calling gh.
set -euo pipefail

if [ -n "${REVIEW_ROUTE_FILES+x}" ]; then
  files="$REVIEW_ROUTE_FILES"
  body="${REVIEW_ROUTE_BODY:-}"
else
  pr="${1:-}"
  [ -n "$pr" ] || { echo "usage: bash scripts/review_route.sh <pr-number>" >&2; exit 64; }
  files="$(gh pr view "$pr" --json files --jq '.files[].path')"
  body="$(gh pr view "$pr" --json body --jq '.body')"
fi

# The triage block's size (CLAUDE.md section 2.1), first occurrence, case-insensitive.
size="$(printf '%s\n' "$body" | tr -d '\r' \
  | sed -nE 's/^[[:space:]]*Size:[[:space:]]*(small|medium|large)\b.*/\1/Ip' | head -1 \
  | tr 'A-Z' 'a-z')"

[ -n "${files//[[:space:]]/}" ] || { echo "reviewer (no changed files listed)"; exit 0; }
[ "$size" = small ] || { echo "reviewer (triage size: ${size:-missing})"; exit 0; }

while IFS= read -r f; do
  f="${f%$'\r'}"
  [ -n "$f" ] || continue
  case "$f" in
    docs/*|README.md) ;;
    *) echo "reviewer (touches $f)"; exit 0 ;;
  esac
done <<<"$files"

echo "reviewer-quick (small, docs only)"
