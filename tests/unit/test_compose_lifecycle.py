"""RUN-011 and RUN-012: when the test stack's containers start and when they go away.

RUN-011: `compose_test` starts Ollama only for the gpu tier and the gates.
RUN-012: the SessionEnd hook takes a desk's test stack down, and on the main checkout removes
only an idle db-test, never the app stack.

Everything runs in a throwaway git repo with a linked worktree and a fake `docker` that
records its calls. No real container is touched.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]

# `docker ps -q ...` (the session-end oneoff check) prints $FAKE_ONEOFF;
# `docker ps -a ...` (the prune) prints no projects. Every call is logged.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
if [ "$1" = ps ]; then
  case " $* " in *" -q "*) [ -n "${FAKE_ONEOFF:-}" ] && echo "$FAKE_ONEOFF" ;; esac
fi
exit 0
"""


@pytest.fixture()
def sandbox(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    for rel in (
        ".claude/hooks/common.sh",
        ".claude/hooks/session_end.sh",
        "scripts/prune_test_projects.sh",
    ):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, repo / rel)
    (repo / ".gitignore").write_text("wt/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    wt = repo / "wt" / "Desk.One"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/one", str(wt)], cwd=repo, check=True
    )
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAKE_DOCKER)
    (bin_ / "docker").chmod(0o755)
    return {"repo": repo, "wt": wt, "bin": bin_, "log": tmp_path / "docker.log"}


def run(sb: dict[str, Path], where: str, script: str, **extra: str) -> list[str]:
    env = {
        **os.environ,
        "PATH": f"{sb['bin']}{os.pathsep}{os.environ['PATH']}",
        "DOCKER_LOG": str(sb["log"]),
        **extra,
    }
    subprocess.run(
        ["bash", "-c", script], cwd=sb[where], env=env, check=True, input="{}", text=True
    )
    return sb["log"].read_text().splitlines() if sb["log"].exists() else []


# ---- RUN-011: Ollama only for the gpu tier and the gates ----


@pytest.mark.parametrize(
    "args",
    [
        "pytest -q -m gpu",
        "pytest -q -m 'unit or db or integration or gpu or gate' tests/gpu/models/test_x.py",
        "python scripts/gate_2.py",
    ],
)
def test_gpu_and_gate_runs_start_ollama_in_the_desk_project(sandbox: dict, args: str) -> None:
    calls = run(sandbox, "wt", f". .claude/hooks/common.sh; compose_test {args}")
    assert "compose -p file-sorter-desk-one up -d ollama" in calls
    up = calls.index("compose -p file-sorter-desk-one up -d ollama")
    assert "run --rm -T test" in calls[up + 1]  # started before the tests run


@pytest.mark.parametrize(
    "args",
    [
        "pytest -q",
        "pytest -q -m unit tests/unit/sanitize",
        "pytest -q -m 'unit or db or integration or gpu or gate' tests/unit/test_smoke.py",
        "pytest -q -m 'not gpu and not gate'",
    ],
)
def test_other_runs_never_start_ollama(sandbox: dict, args: str) -> None:
    calls = run(sandbox, "wt", f". .claude/hooks/common.sh; compose_test {args}")
    assert not any("up -d ollama" in c for c in calls)


def test_main_checkout_uses_the_default_project(sandbox: dict) -> None:
    calls = run(sandbox, "repo", ". .claude/hooks/common.sh; compose_test pytest -q -m gpu")
    assert "compose up -d ollama" in calls
    assert not any("-p file-sorter" in c for c in calls)


# ---- RUN-012: the session-end clean-up ----


def test_desk_session_end_takes_its_whole_test_stack_down(sandbox: dict) -> None:
    calls = run(sandbox, "wt", "bash .claude/hooks/session_end.sh")
    assert "compose -p file-sorter-desk-one down --remove-orphans" in calls
    assert not any("rm -sf db-test" in c for c in calls)


def test_lead_session_end_removes_only_an_idle_db_test(sandbox: dict) -> None:
    calls = run(sandbox, "repo", "bash .claude/hooks/session_end.sh")
    assert "compose --profile test rm -sf db-test" in calls
    # The app stack (db, ollama, searxng, app) is never taken down from the main checkout.
    assert not any(" down" in f" {c}" for c in calls)


def test_lead_session_end_leaves_a_running_test_alone(sandbox: dict) -> None:
    calls = run(sandbox, "repo", "bash .claude/hooks/session_end.sh", FAKE_ONEOFF="abc123")
    assert not any("rm -sf db-test" in c for c in calls)


def test_session_end_never_fails(sandbox: dict) -> None:
    (sandbox["bin"] / "docker").write_text("#!/usr/bin/env bash\nexit 1\n")
    env = {**os.environ, "PATH": f"{sandbox['bin']}{os.pathsep}{os.environ['PATH']}"}
    for where in ("wt", "repo"):
        result = subprocess.run(
            ["bash", ".claude/hooks/session_end.sh"],
            cwd=sandbox[where],
            env=env,
            input="{}",
            text=True,
        )
        assert result.returncode == 0


# ---- the hooks are wired in settings.json ----


def test_settings_wire_the_session_hooks() -> None:
    hooks = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    end = [h["command"] for e in hooks["SessionEnd"] for h in e["hooks"]]
    start = [h["command"] for e in hooks["SessionStart"] for h in e["hooks"]]
    assert any("session_end.sh" in c for c in end)
    assert any("prune_test_projects.sh" in c for c in start)
