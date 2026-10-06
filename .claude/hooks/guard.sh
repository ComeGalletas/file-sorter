#!/usr/bin/env bash
# PreToolUse role guard (RUN-002.D8, RUN-005.D1). agent-office passes its own --settings to
# every desk, so per-desk settings layers can't be attached there; this hook enforces the
# roles by LOCATION instead, for agent-office desks only (AGENT_OFFICE_WORKER_ID is set).
#
# It governs the REPO TREE (the main checkout, including .agent-office/worktrees/):
#   main checkout   -> lead:   inside the tree, edits only docs/ and .task;
#                              merge only with --merge; no mN tags
#   linked worktree -> worker: inside its own worktree, no index/plans/spec edits;
#                              anywhere else in the tree (main checkout, other desks) denied;
#                              no merge, no tag, no push to main
# Paths outside the tree (Claude memory, the workspace's agent-logs\, temp) are not the
# guard's business; Claude Code's own permissions still apply there.
# The human's own sessions (no AGENT_OFFICE_WORKER_ID) are not guarded (RUN-002.D16).
# Messages are ASCII on purpose: hook stderr reaches Claude in the console code page (RUN-005.D3).
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
lower() { printf '%s' "$1" | tr 'A-Z' 'a-z'; }

# Where a write lands: "own:<path relative to this tree>", "repo" (elsewhere in the main
# checkout tree) or "outside". Tolerates D:\ vs D:/ and drive-letter case.
where() {
  local f="$1" top main lf ltop lmain
  f="${f//\\\\//}"; f="${f//\\//}"
  case "/$f/" in
    */../*) deny "use a normalized path without '..' segments (RUN-005.D1)" ;;
  esac
  case "$f" in
    /*|[A-Za-z]:/*) ;;
    *) printf 'own:%s' "${f#./}"; return ;;   # relative paths resolve inside this tree
  esac
  top="$(git rev-parse --show-toplevel)"; main="$(main_checkout)"
  lf="$(lower "$f")"; ltop="$(lower "$top")"; lmain="$(lower "$main")"
  case "$lf" in "$ltop"/*) printf 'own:%s' "${f:$((${#top} + 1))}"; return ;; esac
  case "$lf" in "$lmain"|"$lmain"/*) printf 'repo'; return ;; esac
  printf 'outside'
}

if in_linked_worktree; then
  case "$tool" in
    Bash)
      printf '%s' "$cmd" | grep -Eq '(^|[;&|( ])(gh pr merge|git merge|git tag)( |$)' \
        && deny "workers never merge or tag; the lead merges (CLAUDE.md section 1.6)"
      printf '%s' "$cmd" | grep -Eq 'git push.*([ :]main( |$)|HEAD:main)' \
        && deny "workers never push to main; push your task branch and open a PR"
      ;;
    Edit|Write|MultiEdit|NotebookEdit)
      loc="$(where "$file")" || exit 2
      case "$loc" in
        own:docs/journals/INDEX.md|own:docs/plans/*)
          deny "only the lead edits the index and milestone plans (CLAUDE.md section 1.4)" ;;
        own:DESIGN.md|own:CLAUDE.md)
          deny "only the human changes DESIGN.md and CLAUDE.md; open a design-question issue" ;;
        repo)
          deny "workers edit only inside their own worktree, never the main checkout or another desk's tree (RUN-005.D1)" ;;
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
      loc="$(where "$file")" || exit 2
      case "$loc" in
        own:docs/*|own:.task|outside) ;;
        *) deny "inside the repo the lead edits only docs/ (plans, journals, index); code, tests and config belong to the workers (CLAUDE.md Roles)" ;;
      esac
      ;;
  esac
fi
exit 0
