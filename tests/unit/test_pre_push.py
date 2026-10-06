"""RUN-002.10.4: the pre-push gate's ref rules (RUN-002.D5, D15), run in a throwaway repo.

The hook and its helper are copied into a fresh `git init` under tmp_path, so the test never
touches this repo's refs, remotes or .env. Each case feeds git's pre-push stdin format:
`<local ref> <local sha> <remote ref> <remote sha>`, one line per ref being pushed.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ZERO = "0" * 40
SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    for rel in (".githooks/pre-push", ".claude/hooks/common.sh"):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def push(sandbox: Path, *refs: tuple[str, str, str, str]) -> subprocess.CompletedProcess:
    stdin = "".join(" ".join(ref) + "\n" for ref in refs)
    env = {k: v for k, v in os.environ.items() if k != "ALLOW_MAIN_PUSH"}
    return subprocess.run(
        ["bash", ".githooks/pre-push", "origin", "https://example.invalid/repo.git"],
        cwd=sandbox,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_deletion_only_push_skips_the_test_run(sandbox: Path) -> None:
    result = push(sandbox, ("(delete)", ZERO, "refs/heads/old-branch", SHA_A))
    assert result.returncode == 0, result.stderr
    assert "branch deletion only" in result.stdout


def test_deleting_main_is_still_refused(sandbox: Path) -> None:
    result = push(sandbox, ("(delete)", ZERO, "refs/heads/main", SHA_A))
    assert result.returncode == 1
    assert "direct pushes to main" in result.stderr


def test_pushing_to_main_without_allow_is_refused(sandbox: Path) -> None:
    result = push(sandbox, ("refs/heads/main", SHA_B, "refs/heads/main", SHA_A))
    assert result.returncode == 1
    assert "direct pushes to main" in result.stderr


def test_mixed_push_is_still_gated(sandbox: Path) -> None:
    # A deletion plus a real ref must not take the deletion shortcut. The sandbox has no
    # .env, so reaching the .env check proves the gate went past the shortcut.
    result = push(
        sandbox,
        ("(delete)", ZERO, "refs/heads/old-branch", SHA_A),
        ("refs/heads/feature", SHA_B, "refs/heads/feature", ZERO),
    )
    assert result.returncode == 1
    assert "no .env" in result.stderr
    assert "branch deletion only" not in result.stdout
