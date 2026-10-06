"""RUN-005.1: the role guard (RUN-002.D8, RUN-005.D1) in a throwaway repo with a real worktree.

Layout under tmp_path:
    repo/                               main checkout  -> the lead's location
    repo/.agent-office/worktrees/w1/    linked worktree -> a worker's location
    memory/                             outside the repo (like Claude's memory, agent-logs)
The guard is run exactly as Claude Code runs a PreToolUse hook: JSON on stdin, exit 2 = blocked.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("guard")
    repo, memory = root / "repo", root / "memory"
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    memory.mkdir()
    for name in ("guard.sh", "common.sh"):
        shutil.copy(SRC / name, hooks / name)
    (repo / ".gitignore").write_text(".agent-office/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    wt = repo / ".agent-office" / "worktrees" / "w1"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/w1", str(wt)], cwd=repo, check=True
    )
    return {"repo": repo, "wt": wt, "memory": memory, "guard": hooks / "guard.sh"}


def guard(sb: dict[str, Path], where: str, payload: dict, desk: bool = True) -> int:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("FILE_SORTER_GUARD", "AGENT_OFFICE_WORKER_ID")
    }
    if desk:
        env["AGENT_OFFICE_WORKER_ID"] = "w-test"
    result = subprocess.run(
        ["bash", str(sb["guard"])],
        cwd=sb[where],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result.returncode


def edit(path: Path | str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# ---- lead: the main checkout ----


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("repo:docs/journals/INDEX.md", 0),
        ("repo:docs/plans/m1.md", 0),
        ("repo:.task", 0),
        ("repo:classifier/cli/__init__.py", 2),
        ("repo:config.yaml", 2),
        ("repo:.agent-office/worktrees/w1/classifier/x.py", 2),  # a worker's tree
        ("memory:lead_note.md", 0),  # RUN-005.D1: outside the repo (memory, agent-logs)
    ],
)
def test_lead_edits(sandbox: dict[str, Path], target: str, expected: int) -> None:
    base, rel = target.split(":", 1)
    assert guard(sandbox, "repo", edit(sandbox[base] / rel)) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("gh pr merge 5 --merge --delete-branch", 0),
        ("gh pr merge 5 --squash", 2),
        ("gh pr merge 5", 2),
        ("git tag -a m1-approved -m ok", 2),
        ("git tag -l 'm*-approved'", 0),
    ],
)
def test_lead_commands(sandbox: dict[str, Path], command: str, expected: int) -> None:
    assert guard(sandbox, "repo", bash(command)) == expected


# ---- worker: a linked worktree ----


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("wt:classifier/cli/__init__.py", 0),
        ("wt:docs/journals/harness_journal.md", 0),  # its own task lines
        ("wt:docs/journals/INDEX.md", 2),
        ("wt:docs/plans/m1.md", 2),
        ("wt:DESIGN.md", 2),
        ("wt:CLAUDE.md", 2),
        ("repo:classifier/cli/__init__.py", 2),  # RUN-005.D1: the main checkout
        ("repo:.agent-office/worktrees/w2/x.py", 2),  # RUN-005.D1: another desk's tree
        ("memory:worker_note.md", 0),  # outside the repo
    ],
)
def test_worker_edits(sandbox: dict[str, Path], target: str, expected: int) -> None:
    base, rel = target.split(":", 1)
    assert guard(sandbox, "wt", edit(sandbox[base] / rel)) == expected


def test_worker_relative_paths(sandbox: dict[str, Path]) -> None:
    assert guard(sandbox, "wt", edit("classifier/cli/__init__.py")) == 0
    assert guard(sandbox, "wt", edit("DESIGN.md")) == 2


def test_dotdot_segments_are_refused(sandbox: dict[str, Path]) -> None:
    # Starts with the worktree's own prefix but points into the main checkout.
    sneaky = f"{sandbox['wt']}/../../../classifier/cli/__init__.py"
    assert guard(sandbox, "wt", edit(sneaky)) == 2
    assert guard(sandbox, "wt", edit("../../../classifier/cli/__init__.py")) == 2


def test_backslash_paths_are_normalized(sandbox: dict[str, Path]) -> None:
    windows_style = str(sandbox["repo"] / "classifier" / "x.py").replace("/", "\\")
    assert guard(sandbox, "wt", edit(windows_style)) == 2


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("gh pr merge 3 --merge", 2),
        ("git fetch && git merge origin/main", 2),
        ("git push origin main", 2),
        ("git push origin HEAD:main", 2),
        ("git tag v1", 2),
        ("git push -u origin HEAD", 0),
        ("git rebase origin/main", 0),
    ],
)
def test_worker_commands(sandbox: dict[str, Path], command: str, expected: int) -> None:
    assert guard(sandbox, "wt", bash(command)) == expected


# ---- the human's own session ----


def test_human_session_is_not_guarded(sandbox: dict[str, Path]) -> None:
    assert (
        guard(sandbox, "repo", edit(sandbox["repo"] / "classifier/cli/__init__.py"), desk=False)
        == 0
    )
    assert guard(sandbox, "wt", bash("gh pr merge 3 --merge"), desk=False) == 0
