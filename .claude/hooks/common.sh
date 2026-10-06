#!/usr/bin/env bash
# Shared helpers for the Claude Code hooks and the git pre-push gate (RUN-002).
# Sourced, never executed. POSIX tools only: these run in Git Bash on Windows.

# Absolute path of the main checkout (the same from any linked worktree).
main_checkout() {
  dirname "$(git rev-parse --path-format=absolute --git-common-dir)"
}

# True inside a linked worktree (a worker desk), false in the main checkout.
in_linked_worktree() {
  [ "$(git rev-parse --path-format=absolute --git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ]
}

# RUN-002.D2: each linked worktree runs tests in its own compose project.
compose_test() {
  local project=()
  if in_linked_worktree; then
    local wt
    wt="$(basename "$(git rev-parse --show-toplevel)" | tr 'A-Z.' 'a-z-' | tr -cd 'a-z0-9_-')"
    project=(-p "file-sorter-$wt")
  fi
  docker compose "${project[@]}" --profile test run --rm -T test "$@"
}

# The git-ignored .task file at the worktree root (RUN-002.D4): key=value lines
#   role=pipeline   issue=12   acceptance=tests/unit/classify/test_margin.py
# A desk cannot set environment variables for its own hooks, so they read this file.
task_field() {
  local f; f="$(git rev-parse --show-toplevel 2>/dev/null)/.task"
  [ -f "$f" ] && sed -n "s/^$1=//p" "$f" | head -1 | tr -d '\r'
}

agent_role() { printf '%s' "${AGENT_ROLE:-$(task_field role)}" | grep . || echo unassigned; }

# Per-role local log folder (C-18, CLAUDE.md §2.2). Never inside the repo.
log_dir() {
  local root="${AGENT_LOG_ROOT:-../agent-logs}"
  case "$root" in
    /*|[A-Za-z]:/*|[A-Za-z]:\\*) ;;
    *) root="$(main_checkout)/$root" ;;
  esac
  local dir="$root/$(agent_role)"
  mkdir -p "$dir" && printf '%s' "$dir"
}

# First string value of a top-level-ish JSON key from the hook input on stdin (RUN-002.D7).
json_field() {
  sed -n "s/.*\"$1\" *: *\"\([^\"]*\)\".*/\1/p" | head -1
}
