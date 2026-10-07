#!/usr/bin/env bash
# One JSON line per lifecycle event -> $AGENT_LOG_ROOT/<role>/events.jsonl (C-18, local only).
# Usage (settings.json): bash .claude/hooks/log_event.sh <EventName>
# Never fails the session: logging problems are swallowed.
set -u
. "$(dirname "$0")/common.sh" 2>/dev/null || exit 0
event="${1:-unknown}"
input="$(cat)"
dir="$(log_dir 2>/dev/null)" || exit 0
printf '{"ts":"%s","event":"%s","role":"%s","issue":"%s","session":"%s","tool":"%s","file":"%s","branch":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$(agent_role)" "${AGENT_ISSUE:-$(task_field issue)}" \
  "$(printf '%s' "$input" | json_field session_id)" \
  "$(printf '%s' "$input" | json_field tool_name)" \
  "$(printf '%s' "$input" | json_field file_path | tr '\\' '/' | tr -d '"')" \
  "$(git branch --show-current 2>/dev/null)" >> "$dir/events.jsonl" 2>/dev/null
exit 0
