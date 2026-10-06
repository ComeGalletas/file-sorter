#!/usr/bin/env bash
# PostToolUse on Edit|Write|MultiEdit: ruff on the edited Python file only (C-17).
# Runs in the ruff container, so nothing is installed on the host.
# Exit 2 sends the findings back to Claude, which then fixes them.
set -u
. "$(dirname "$0")/common.sh"
file="$(json_field file_path)"
case "$file" in *.py) ;; *) exit 0 ;; esac
file="${file//\\\\//}"   # JSON-escaped Windows backslashes -> /
file="${file//\\//}"
[ -f "$file" ] || exit 0
top="$(git rev-parse --show-toplevel)"
rel="$(cd "$(dirname "$file")" && git rev-parse --show-prefix)$(basename "$file")"
# MSYS_NO_PATHCONV: stop Git Bash rewriting the container path /io into C:/Program Files/Git/io.
if ! out="$(MSYS_NO_PATHCONV=1 docker run --rm -v "$top:/io" -w /io ghcr.io/astral-sh/ruff:0.16.10 check --quiet "$rel" 2>&1)"; then
  printf 'ruff found problems in %s (fix them before moving on):\n%s\n' "$rel" "$out" >&2
  exit 2
fi
exit 0
