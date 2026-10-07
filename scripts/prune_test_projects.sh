#!/usr/bin/env bash
# RUN-010.D5: shut down the test compose projects of worktrees that no longer exist.
# Each linked worktree tests in its own project, file-sorter-<worktree> (RUN-002.D2). The test
# container is removed after every run, but its db-test keeps running, and so does the
# project's network. Desks come and go, so those leftovers pile up until Docker runs out of
# network address pools. `make init` runs this, so every new desk tidies up after the old ones.
# Only projects named file-sorter-<x> with no live worktree <x> are touched; the main
# checkout's own project (file-sorter) and every live desk's are left alone. db-test is tmpfs,
# so nothing is lost.
set -uo pipefail

# The project suffix for a worktree folder name, exactly as the Makefile and compose_test make it.
slug() { printf '%s' "$1" | tr 'A-Z.' 'a-z-' | tr -cd 'a-z0-9_-'; }

live=" "
while IFS= read -r path; do
  [ -n "$path" ] && live="$live$(slug "$(basename "$path")") "
done <<EOF
$(git worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
EOF

projects="$(docker ps -a --filter label=com.docker.compose.project \
  --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | sort -u)"
for p in $projects; do
  case "$p" in file-sorter-*) ;; *) continue ;; esac
  wt="${p#file-sorter-}"
  case "$live" in *" $wt "*) continue ;; esac
  if docker compose -p "$p" down --remove-orphans >/dev/null 2>&1; then
    echo "pruned test project $p (worktree gone)"
  fi
done
exit 0
