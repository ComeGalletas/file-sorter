#!/usr/bin/env bash
# Which reviewer subagent a PR gets (RUN-006.D1, D5). Prints one line:
#   reviewer-quick (<reason>)   small PR that changes only docs/ and README.md: static Haiku review
#   reviewer (<reason>)         everything else: the full Sonnet review, reproductions included
# The privacy-auditor runs on every PR regardless.
#
# Any doubt routes to the full reviewer: a gh failure, a file listing that doesn't match
# GitHub's changedFiles, a rename whose OLD name is outside docs/, no fenced triage block, or
# triage blocks that disagree. There is deliberately no `set -e`: a failure must still print
# "reviewer", never nothing (PR #10 review, finding 7).
#
# Usage: bash scripts/review_route.sh <pr-number>
# Tests set instead of calling gh:
#   REVIEW_ROUTE_FILES     current paths, one per line
#   REVIEW_ROUTE_PREVIOUS  previous paths of renamed files, one per line (optional)
#   REVIEW_ROUTE_CHANGED   GitHub's changedFiles count (optional)
#   REVIEW_ROUTE_BODY      the PR body
set -uo pipefail

full() { echo "reviewer ($*)"; exit 0; }

if [ -n "${REVIEW_ROUTE_FILES+x}" ]; then
  files="$REVIEW_ROUTE_FILES"
  previous="${REVIEW_ROUTE_PREVIOUS:-}"
  changed="${REVIEW_ROUTE_CHANGED:-}"
  body="${REVIEW_ROUTE_BODY:-}"
else
  pr="${1:-}"
  [ -n "$pr" ] || { echo "usage: bash scripts/review_route.sh <pr-number>" >&2; exit 64; }
  changed="$(gh pr view "$pr" --json changedFiles --jq '.changedFiles' 2>/dev/null)" \
    || full "could not read PR $pr"
  [[ "$changed" =~ ^[0-9]+$ ]] || full "could not read the changedFiles count of PR $pr"
  body="$(gh pr view "$pr" --json body --jq '.body' 2>/dev/null)" || full "could not read PR $pr"
  # Paginated and rename-aware: gh pr view --json files stops at 100 and shows new names only.
  listing="$(gh api --paginate "repos/{owner}/{repo}/pulls/$pr/files" \
    --jq '.[] | "F\t\(.filename)", (if .previous_filename then "P\t\(.previous_filename)" else empty end)' \
    2>/dev/null)" || full "could not list the files of PR $pr"
  files="$(printf '%s\n' "$listing" | sed -n 's/^F\t//p')"
  previous="$(printf '%s\n' "$listing" | sed -n 's/^P\t//p')"
fi

nfiles="$(printf '%s\n' "$files" | grep -c '[^[:space:]]')"
[ "$nfiles" -gt 0 ] || full "no changed files listed"
if [ -n "$changed" ] && [ "$changed" != "$nfiles" ]; then
  full "listed $nfiles of $changed changed files"
fi

# The triage size: only from a fenced block that also has Tests: and Agents: lines, after
# removing HTML comments (CLAUDE.md section 2.1; PR #10 review, finding 3).
sizes="$(printf '%s\n' "$body" | tr -d '\r' | awk '
  {
    line = $0; out = ""
    while (1) {
      if (incomment) {
        e = index(line, "-->"); if (!e) { line = ""; break }
        line = substr(line, e + 3); incomment = 0
      } else {
        b = index(line, "<!--"); if (!b) { out = out line; break }
        out = out substr(line, 1, b - 1); line = substr(line, b + 4); incomment = 1
      }
    }
    l = tolower(out)
  }
  l ~ /^[ \t]*```/ {
    if (infence) { if (s != "" && t && a) print s; infence = 0 }
    else { infence = 1; s = ""; t = 0; a = 0 }
    next
  }
  infence {
    if (s == "" && l ~ /^[ \t]*size:[ \t]*(small|medium|large)([^a-z]|$)/) {
      s = l; sub(/^[ \t]*size:[ \t]*/, "", s); sub(/[^a-z].*$/, "", s)
    }
    if (l ~ /^[ \t]*tests:/) t = 1
    if (l ~ /^[ \t]*agents:/) a = 1
  }
' | sort -u)"
case "$(printf '%s\n' "$sizes" | grep -c .)" in
  0) full "triage size: missing" ;;
  1) size="$sizes" ;;
  *) full "triage blocks disagree: $(printf '%s' "$sizes" | tr '\n' ' ')" ;;
esac
[ "$size" = small ] || full "triage size: $size"

# Every current AND previous path must be docs (PR #10 review, finding 1).
while IFS= read -r f; do
  f="${f%$'\r'}"
  [ -n "$f" ] || continue
  case "$f" in
    docs/*|README.md) ;;
    *) full "touches $f" ;;
  esac
done < <(printf '%s\n%s\n' "$files" "$previous")

echo "reviewer-quick (small, docs only)"
