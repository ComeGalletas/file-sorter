"""RUN-008.D5: the hooks read JSON string values whole.

The old `json_field` stopped at the first escaped quote, so the guard never saw the rest of a
command that contained a double quote. These tests feed real `json.dumps` payloads through
`json_field` and the log hook. Everything is synthetic.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]


def json_field(key: str, payload: dict) -> str:
    out = subprocess.run(
        ["bash", "-c", f'. "{HOOKS / "common.sh"}"; json_field {key}'],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.removesuffix("\n")


@pytest.mark.parametrize(
    "value",
    [
        'bash -c "git merge x" && echo hi',
        'echo "a" && gh pr merge 5 --squash',
        'git commit -F - <<EOF\nX.1: subject\n\nbody with "quotes" and a back\\slash\nEOF',
        'printf "%s\\n" "x"',
        "plain value",
        "",
    ],
)
def test_command_round_trips(value: str) -> None:
    assert json_field("command", {"tool_name": "Bash", "tool_input": {"command": value}}) == value


def test_windows_path_round_trips() -> None:
    path = "D:\\work\\repo\\CLAUDE.md"
    assert json_field("file_path", {"tool_input": {"file_path": path}}) == path


def test_first_matching_key_wins_over_later_text() -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": 'echo "tool_name"'}}
    assert json_field("tool_name", payload) == "Bash"


def test_log_line_stays_valid_json_for_a_windows_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    for name in ("common.sh", "log_event.sh"):
        (repo / ".claude" / "hooks" / name).write_bytes((HOOKS / name).read_bytes())
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    logs = tmp_path / "logs"
    payload = {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "D:\\a\\b.py"}}
    subprocess.run(
        ["bash", ".claude/hooks/log_event.sh", "PostToolUse"],
        cwd=repo,
        input=json.dumps(payload),
        text=True,
        check=True,
        env={**os.environ, "AGENT_LOG_ROOT": str(logs)},
    )
    lines = list(logs.rglob("events.jsonl"))
    assert len(lines) == 1
    record = json.loads(lines[0].read_text().splitlines()[-1])
    assert record["file"] == "D:/a/b.py"
    assert record["tool"] == "Edit"
