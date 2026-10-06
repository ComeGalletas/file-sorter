#!/usr/bin/env bash
# Stop: at the end of a WORKER turn, run the unit tests of the packages it touched (C-17).
# Main checkout (lead, human): does nothing. The hard gate is the pre-push hook.
# Exit 2 keeps the worker going with the failure in front of it.
set -u
. "$(dirname "$0")/common.sh"
input="$(cat)"
printf '%s' "$input" | grep -q '"stop_hook_active" *: *true' && exit 0   # no loops
in_linked_worktree || exit 0

base="$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main 2>/dev/null)" || exit 0
changed="$({ git diff --name-only "$base"; git diff --name-only; git ls-files --others --exclude-standard; } | sort -u)"

targets=()
for pkg in $(printf '%s\n' "$changed" | sed -n 's#^classifier/\([^/]*\)/.*#\1#p' | sort -u); do
  [ -d "tests/unit/$pkg" ] && targets+=("tests/unit/$pkg")
done
while IFS= read -r t; do [ -n "$t" ] && [ -f "$t" ] && targets+=("$t"); done \
  < <(printf '%s\n' "$changed" | grep -E '^tests/unit/.*\.py$' || true)
[ "${#targets[@]}" -eq 0 ] && exit 0

if out="$(compose_test pytest -q -m unit "${targets[@]}" 2>&1)"; then
  printf '{"ts":"%s","event":"StopTests","result":"pass","targets":"%s"}\n' "$(date -u +%FT%TZ)" "${targets[*]}" >> "$(log_dir)/events.jsonl"
  exit 0
fi
printf '{"ts":"%s","event":"StopTests","result":"fail","targets":"%s"}\n' "$(date -u +%FT%TZ)" "${targets[*]}" >> "$(log_dir)/events.jsonl"
printf 'Unit tests for the packages you touched fail (C-17). Fix them before stopping:\n%s\n' \
  "$(printf '%s\n' "$out" | tail -40)" >&2
exit 2
