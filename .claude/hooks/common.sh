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

# RUN-002.D2: a linked worktree's compose project, file-sorter-<worktree> (the Makefile's slug).
# Empty in the main checkout, whose project is the default (file-sorter).
wt_project() {
  in_linked_worktree || return 0
  printf 'file-sorter-%s' "$(basename "$(git rev-parse --show-toplevel)" | tr 'A-Z.' 'a-z-' | tr -cd 'a-z0-9_-')"
}

# RUN-011.D1: Ollama is started only for the gpu tier and the gates: a tests/gpu/ path, `-m gpu`
# or a gate script among the arguments. Unit, db and integration runs never start it, so a
# desk's Ollama holds GPU memory only while its gpu tests or gates run.
needs_ollama() {
  local a prev=""
  for a in "$@"; do
    case "$a" in tests/gpu|tests/gpu/*|scripts/gate_*) return 0 ;; esac
    [ "$prev" = "-m" ] && [ "$a" = gpu ] && return 0
    prev="$a"
  done
  return 1
}

# RUN-002.D2: each linked worktree runs tests in its own compose project.
# RUN-009.D1: ...and mounts the main checkout's git-ignored fixtures/images/, read-only.
compose_test() {
  local project=() fixtures=() p
  p="$(wt_project)"
  if [ -n "$p" ]; then
    project=(-p "$p")
    fixtures=("FIXTURE_IMAGES=$(main_checkout)/fixtures/images")
  fi
  if needs_ollama "$@"; then
    # A failed start isn't fatal here: the gpu tests then fail with their prerequisite message.
    docker compose "${project[@]}" up -d ollama >/dev/null 2>&1 || true
  fi
  env "${fixtures[@]}" docker compose "${project[@]}" --profile test run --rm -T test "$@"
}

# The git-ignored .task file at the worktree root (RUN-002.D4): key=value lines
#   role=pipeline   issue=12   acceptance=tests/unit/classify/test_margin.py
# A desk cannot set environment variables for its own hooks, so they read this file.
task_field() {
  # Always succeeds (empty output when absent): callers run under `set -e`, and a failing
  # command substitution would kill the pre-push hook silently instead of explaining why.
  local f; f="$(git rev-parse --show-toplevel 2>/dev/null)/.task"
  [ -f "$f" ] || return 0
  sed -n "s/^$1=//p" "$f" | head -1 | tr -d '\r'
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
# RUN-008.D5: a JSON string runs to its first UNESCAPED quote. The old pattern stopped at the
# first \" and hid the rest of any command with a double quote from the guard. The value is
# then unescaped (\\ \" \n \t), so a heredoc's lines reach the guard one by one.
json_field() {
  sed -n 's/.*"'"$1"'" *: *"\(\([^"\\]\|\\.\)*\)".*/\1/p' | head -1 \
    | sed 's/\\\\/\x01/g; s/\\"/"/g; s/\\n/\n/g; s/\\t/\t/g; s/\x01/\\/g'
}
