#!/usr/bin/env bash
# PreToolUse role guard (RUN-002.D8, RUN-005.D1, D5). agent-office passes its own --settings
# to every desk, so per-desk settings layers can't be attached there; this hook enforces the
# roles by LOCATION instead, for agent-office desks only (AGENT_OFFICE_WORKER_ID is set).
#
# Every write target is first resolved to its REAL location (links and NTFS junctions
# followed) and compared case-insensitively (NTFS), then classified:
#   images  -> under SOURCE_ROOT or RESULTS_ROOT (from the main checkout's local .env):
#              denied to every desk; only the app writes there, through Docker (RUN-005.D5)
#   own     -> inside this desk's own tree
#   repo    -> elsewhere in the main checkout tree (the main checkout, another desk's worktree)
#   outside -> anywhere else (Claude memory, the workspace's agent-logs\, temp): not the guard's
#              concern; Claude Code's own permissions still apply
# Roles:
#   main checkout   -> lead:   inside the tree, edits only docs/ and .task;
#                              merge only with --merge; no mN tags
#   linked worktree -> worker: own tree minus index/plans/spec; never "repo";
#                              no tag, no PR merge, no push to main; the only merge is
#                              origin/main into its own branch, the only pull --ff-only;
#                              shell commands detected broadly and failed closed (RUN-008)
# Shell commands are not path-checked: the guard covers Claude's file tools and the
# merge/tag/push commands (RUN-005 Results). The human's own sessions are not guarded
# (RUN-002.D16). Messages are ASCII on purpose (RUN-005.D3). Exit 2 blocks the tool call.
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

# Mixed form (D:/x/y) on Windows/Git Bash, plain form elsewhere.
mixed() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# Real path of an existing directory (symlinks and junctions resolved).
canon_dir() { (cd "$1" 2>/dev/null && mixed "$(pwd -P)"); }

# Real path of a write target that may not exist yet: resolve the target itself when it
# exists (catches a file symlink), else its nearest existing ancestor plus the rest.
canon_path() {
  local f="$1" d rest=""
  if [ -e "$f" ]; then
    [ -d "$f" ] && { canon_dir "$f"; return; }
    d="$(readlink -f -- "$f" 2>/dev/null)" && [ -n "$d" ] && { mixed "$d"; return; }
  fi
  d="$(dirname -- "$f")"; rest="/$(basename -- "$f")"
  while [ ! -d "$d" ]; do
    [ "$d" = "$(dirname -- "$d")" ] && { printf '%s%s' "${d%/}" "$rest"; return; }
    rest="/$(basename -- "$d")$rest"; d="$(dirname -- "$d")"
  done
  d="$(canon_dir "$d")"
  printf '%s%s' "${d%/}" "$rest"   # ${d%/}: the root "/" must not give "//x"
}

# A path from the main checkout's .env (quotes stripped), canonicalized when it exists.
env_root() {
  local v; v="$(sed -n "s/^$1=//p" "$(main_checkout)/.env" 2>/dev/null | head -1 | tr -d '\r')"
  v="${v#\"}"; v="${v%\"}"; v="${v//\\//}"
  [ -n "$v" ] || return 0
  if [ -d "$v" ]; then canon_dir "$v"; else printf '%s' "$v"; fi
}

under() { case "$(lower "$1")" in "$(lower "$2")"|"$(lower "$2")"/*) return 0 ;; esac; return 1; }

# RUN-008.D4: worker shell commands are checked by DETECT BROADLY, ALLOW EXACTLY, FAIL CLOSED.
# The command is normalized first: case-folded (Windows runs GIT and Git.exe as git), quotes
# removed (bash -c "git merge x", git -C "a b" merge x), backslashes turned into slashes,
# whitespace squeezed, then split into simple commands on ; & | ( ) and backticks.
norm_segments() {
  printf '%s\n' "$cmd" | tr 'A-Z' 'a-z' | tr -d "\"'" | tr '\\' '/' \
    | tr ';&|()`' '\n\n\n\n\n\n' \
    | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
}

# A whole word in a normalized segment; a path prefix counts (/usr/bin/git, c:/x/git.exe).
has_word() { printf '%s' "$1" | grep -Eq "(^| |/)($2)( |\$)"; }

# Any segment that mentions git (or gh) together with a guarded word is treated as that
# operation, whatever comes between (global options, -c/-C values, aliases, a wrapping shell).
# Only the exact sync forms pass (D1, D2). A commit message that mentions these words must
# go through `git commit -F <file>`: the false positive is the price of failing closed.
worker_bash_ok() {
  local seg
  while IFS= read -r seg; do
    [ -n "$seg" ] || continue
    if has_word "$seg" 'gh|gh\.exe' && printf '%s' "$seg" | grep -Eq '(^| |/)merge( |$|\?)'; then
      why="workers never merge a PR; the lead merges (CLAUDE.md section 1.6)"; return 1
    fi
    has_word "$seg" 'git|git\.exe' || continue
    case "$seg" in *alias.*)
      why="no git aliases on a worker desk (RUN-008.D4)"; return 1 ;;
    esac
    if has_word "$seg" 'tag'; then
      why="workers never tag; the mN-approved tags are the human's (CLAUDE.md section 1.6)"; return 1
    fi
    if has_word "$seg" 'push' && printf '%s' "$seg" | grep -Eq '(^| |:|\+)(refs/heads/)?main( |$)'; then
      why="workers never push to main; push your task branch and open a PR"; return 1
    fi
    if has_word "$seg" 'merge'; then
      printf '%s' "$seg" | grep -Eq '^git merge( --no-edit| --no-ff)* origin/main$' && continue
      printf '%s' "$seg" | grep -Eq '^git merge --(abort|continue)$' && continue
      why="the only merge a worker runs is 'git merge [--no-edit] origin/main' into its own branch, or --abort/--continue (RUN-008.D1). A commit message that mentions merge goes through 'git commit -F <file>'"; return 1
    fi
    if has_word "$seg" 'pull'; then
      [ "$seg" = "git pull --ff-only" ] && continue
      why="the only pull a worker runs is 'git pull --ff-only' (RUN-008.D2). A commit message that mentions pull goes through 'git commit -F <file>'"; return 1
    fi
  done <<EOF
$(norm_segments)
EOF
  return 0
}

# Classify a write target: images | own:<lowercased path relative to this tree> | repo | outside
where() {
  local f="$1" real top main root
  f="${f//\\\\//}"; f="${f//\\//}"
  # RUN-005.D7: no NTFS alternate data streams (CLAUDE.md:hidden); a ':' is allowed only
  # as the drive letter's.
  case "${f#[A-Za-z]:}" in
    *:*) deny "alternate data streams are not allowed in desk writes (RUN-005.D7)" ;;
  esac
  # RUN-005.D6: Win32 silently drops trailing dots and spaces from every path segment, so
  # "CLAUDE.md." and "CLAUDE.md " ARE CLAUDE.md. Normalize the same way before any check.
  # Lone "." and ".." segments are left as they are ('..' is refused just below).
  f="$(printf '%s' "$f" | sed -E 's#([^/. ])[. ]+(/|$)#\1\2#g')"
  case "/$f/" in
    */../*) deny "use a normalized path without '..' segments (RUN-005.D1)" ;;
  esac
  case "$f" in
    /*|[A-Za-z]:/*) ;;
    *) f="$(git rev-parse --show-toplevel)/${f#./}" ;;   # relative paths start in this tree
  esac
  real="$(canon_path "$f")"
  for root in "$(env_root SOURCE_ROOT)" "$(env_root RESULTS_ROOT)"; do
    [ -n "$root" ] && under "$real" "$root" && { printf 'images'; return; }
  done
  top="$(canon_dir "$(git rev-parse --show-toplevel)")"
  main="$(canon_dir "$(main_checkout)")"
  if under "$real" "$top"; then printf 'own:%s' "$(lower "${real:$((${#top} + 1))}")"; return; fi
  if under "$real" "$main"; then printf 'repo'; return; fi
  printf 'outside'
}

if in_linked_worktree; then
  case "$tool" in
    Bash)
      why=""
      worker_bash_ok || deny "$why"
      ;;
    Edit|Write|MultiEdit|NotebookEdit)
      loc="$(where "$file")" || exit 2
      case "$loc" in
        images)
          deny "desks never write to the image folders (SOURCE_ROOT, RESULTS_ROOT); only the app does, through Docker (RUN-005.D5)" ;;
        own:docs/journals/index.md|own:docs/plans/*)
          deny "only the lead edits the index and milestone plans (CLAUDE.md section 1.4)" ;;
        own:design.md|own:claude.md)
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
        images)
          deny "desks never write to the image folders (SOURCE_ROOT, RESULTS_ROOT); only the app does, through Docker (RUN-005.D5)" ;;
        own:docs/*|own:.task|outside) ;;
        *) deny "inside the repo the lead edits only docs/ (plans, journals, index); code, tests and config belong to the workers (CLAUDE.md Roles)" ;;
      esac
      ;;
  esac
fi
exit 0
