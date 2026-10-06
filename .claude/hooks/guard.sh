#!/usr/bin/env bash
# PreToolUse role guard (RUN-002.D8). agent-office passes its own --settings to every desk,
# so per-desk settings layers can't be attached there; this hook enforces the roles by
# LOCATION instead, for agent-office desks only (AGENT_OFFICE_WORKER_ID is set):
#   linked worktree -> worker: no merge, no tag, no push to main; no index/plans/spec edits
#   main checkout   -> lead:   edits only under docs/ (and .task); merge only with --merge; no mN tags
# The human's own sessions (no AGENT_OFFICE_WORKER_ID) are not guarded.
# Exit 2 blocks the tool call and tells Claude why.
set -u
[ -n "${AGENT_OFFICE_WORKER_ID:-}${FILE_SORTER_GUARD:-}" ] || exit 0
. "$(dirname "$0")/common.sh"
input="$(cat)"
tool="$(printf '%s' "$input" | json_field tool_name)"
cmd="$(printf '%s' "$input" | json_field command)"
file="$(printf '%s' "$input" | json_field file_path)"
[ -n "$file" ] || file="$(printf '%s' "$input" | json_field notebook_path)"

deny() { printf 'BLOCKED by the role guard (RUN-002.D8): %s\n' "$*" >&2; exit 2; }

# Repo-relative path, tolerant of D:\ vs D:/ and of drive-letter case.
rel_path() {
  local f="$1" top ltop lf
  f="${f//\\\\//}"; f="${f//\\//}"
  top="$(git rev-parse --show-toplevel)"
  ltop="$(printf '%s' "$top" | tr 'A-Z' 'a-z')"; lf="$(printf '%s' "$f" | tr 'A-Z' 'a-z')"
  case "$lf" in "$ltop"/*) printf '%s' "${f:$((${#top} + 1))}" ;; *) printf '%s' "$f" ;; esac
}

if in_linked_worktree; then
  case "$tool" in
    Bash)
      printf '%s' "$cmd" | grep -Eq '(^|[;&|( ])(gh pr merge|git merge|git tag)( |$)' \
        && deny "workers never merge or tag; the lead merges (CLAUDE.md §1.6)"
      printf '%s' "$cmd" | grep -Eq 'git push.*([ :]main( |$)|HEAD:main)' \
        && deny "workers never push to main; push your task branch and open a PR"
      ;;
    Edit|Write|MultiEdit|NotebookEdit)
      case "$(rel_path "$file")" in
        docs/journals/INDEX.md|docs/plans/*) deny "only the lead edits the index and milestone plans (CLAUDE.md §1.4)" ;;
        DESIGN.md|CLAUDE.md) deny "only the human changes DESIGN.md and CLAUDE.md; open a design-question issue" ;;
      esac
      ;;
  esac
else
  case "$tool" in
    Bash)
      printf '%s' "$cmd" | grep -Eq 'git tag +(-[a-z]+ +)*m[0-9]' \
        && deny "mN-approved tags are the human's G1 gate; never tag"
      if printf '%s' "$cmd" | grep -Eq 'gh pr merge'; then
        printf '%s' "$cmd" | grep -Eq -- '--(squash|rebase|admin)' && deny "merge with --merge only (DOC-001.D12)"
        printf '%s' "$cmd" | grep -Eq -- '--merge( |$)' || deny "merge with --merge (DOC-001.D12)"
      fi
      ;;
    Edit|Write|MultiEdit|NotebookEdit)
      case "$(rel_path "$file")" in
        docs/*|.task) ;;
        *) deny "the lead edits only docs/ (plans, journals, index); code, tests and config belong to the workers (CLAUDE.md Roles)" ;;
      esac
      ;;
  esac
fi
exit 0
