"""RUN-010.D5: `make init` shuts down the test projects of worktrees that no longer exist.

Runs scripts/prune_test_projects.sh in a throwaway git repo with a fake `docker` that lists
compose projects and records which ones are taken down. No real container is touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]

FAKE_DOCKER = """#!/usr/bin/env bash
if [ "$1" = ps ]; then
  printf '%s\\n' file-sorter file-sorter-live-desk file-sorter-gone-desk other-app \\
    file-sorter-gone-desk
elif [ "$1" = compose ]; then
  echo "$3" >> "$DOWN_LOG"
fi
"""


def test_prunes_only_projects_of_missing_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "prune_test_projects.sh", repo / "scripts")
    (repo / "README").write_text("x\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # A live desk whose folder name needs the same slug as the Makefile: case and "." folded.
    live = tmp_path / "desks" / "Live.Desk"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/live", str(live)], cwd=repo, check=True
    )

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAKE_DOCKER)
    (bin_ / "docker").chmod(0o755)
    log = tmp_path / "down.log"
    env = {
        **os.environ,
        "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
        "DOWN_LOG": str(log),
    }
    out = subprocess.run(
        ["bash", "scripts/prune_test_projects.sh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    downed = log.read_text().split() if log.exists() else []
    # Only the gone desk, once; never the main checkout's project, a live desk or another app.
    assert downed == ["file-sorter-gone-desk"]
    assert "pruned test project file-sorter-gone-desk" in out.stdout


def test_prunes_nothing_when_the_worktree_list_cannot_be_read(tmp_path: Path) -> None:
    # Outside any git repo, `git worktree list` fails: every desk would look gone.
    outside = tmp_path / "not-a-repo"
    (outside / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "prune_test_projects.sh", outside / "scripts")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(FAKE_DOCKER)
    (bin_ / "docker").chmod(0o755)
    log = tmp_path / "down.log"
    env = {
        **os.environ,
        "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
        "DOWN_LOG": str(log),
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    result = subprocess.run(["bash", "scripts/prune_test_projects.sh"], cwd=outside, env=env)
    assert result.returncode == 0
    assert not log.exists()


def test_never_fails_init_when_docker_is_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "prune_test_projects.sh", repo / "scripts")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text("#!/usr/bin/env bash\nexit 1\n")
    (bin_ / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(["bash", "scripts/prune_test_projects.sh"], cwd=repo, env=env)
    assert result.returncode == 0
