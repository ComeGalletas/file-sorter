#!/usr/bin/env bash
# `make init` helper (RUN-001.D8, RUN-002.D3): create the git-ignored local files.
# In a linked worktree, .env and sanitize.yaml are copied from the main checkout,
# because compose cannot parse without the .env values and worktrees only hold tracked files.
set -euo pipefail
main="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
here="$(git rev-parse --show-toplevel)"
for f in .env sanitize.yaml; do
  [ -f "$f" ] && continue
  if [ "$main" != "$here" ] && [ -f "$main/$f" ]; then
    cp "$main/$f" "$f"; echo "copied $f from the main checkout"
  elif [ "$f" = .env ]; then
    cp .env.example .env; echo "created .env: set SOURCE_ROOT and RESULTS_ROOT"
  else
    cp sanitize.example.yaml sanitize.yaml; echo "created sanitize.yaml: put your real values there"
  fi
done
