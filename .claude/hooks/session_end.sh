#!/usr/bin/env bash
# SessionEnd (RUN-012.D1): when a Claude session in this repo ends, shut down the test
# containers it leaves behind, so a closed desk holds no db-test, no Ollama (GPU memory) and
# no compose network. Never fails or delays the session's end beyond the hook timeout.
#   linked worktree (a desk) -> its own project file-sorter-<worktree> goes down entirely:
#                               db-test, ollama (RUN-011), test runs and the network.
#   main checkout (the lead) -> only an idle db-test is removed. The app stack (db, ollama,
#                               searxng, app) is the human's and is never touched, and a test
#                               run still in progress keeps its db-test.
# Then the prune (RUN-010.D5) catches the projects of desks that were closed without this hook
# running (a killed session), as SessionStart and `make init` also do.
set -u
. "$(dirname "$0")/common.sh" 2>/dev/null || exit 0
cat >/dev/null 2>&1 || true   # the hook input isn't needed
cd "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || exit 0   # compose reads this tree's .env

p="$(wt_project)"
if [ -n "$p" ]; then
  docker compose -p "$p" down --remove-orphans >/dev/null 2>&1 || true
else
  running="$(docker ps -q --filter label=com.docker.compose.project=file-sorter \
    --filter label=com.docker.compose.oneoff=True 2>/dev/null)"
  if [ -z "$running" ]; then
    docker compose --profile test rm -sf db-test >/dev/null 2>&1 || true
  fi
fi

prune="$(git rev-parse --show-toplevel 2>/dev/null)/scripts/prune_test_projects.sh"
[ -f "$prune" ] && bash "$prune" >/dev/null 2>&1
exit 0
