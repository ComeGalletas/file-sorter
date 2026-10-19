"""RUN-018: images, build output and root scratch files can't be committed by mistake.

Runs `git check-ignore` in a sandbox repo carrying the repo's real `.gitignore`, so it works in the
test container, where the worktree's own git metadata isn't reachable. Synthetic paths only.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repo = tmp_path_factory.mktemp("ignore") / "repo"
    repo.mkdir()
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return repo


def ignored(repo: Path, path: str) -> bool:
    out = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=repo)
    return out.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "example_0001.png",
        "docs/example_0001.JPG",
        "tests/data/example_0001.jpeg",
        "classifier/example.webp",
        "deep/nested/example.HEIC",
        "example.gif",
        "example.tiff",
    ],
)
def test_images_are_ignored_anywhere(sandbox: Path, path: str) -> None:
    assert ignored(sandbox, path)


@pytest.mark.parametrize(
    "path",
    ["msg001.txt", "scratch.log", "classifier.egg-info/PKG-INFO", "build/lib/x.py", "dist/x.whl"],
)
def test_scratch_and_build_output_are_ignored(sandbox: Path, path: str) -> None:
    assert ignored(sandbox, path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "config.yaml",
        "prompts/classify_v1.md",
        "prompts/local/classify_v1.example.md",
        "tests/recordings/models/0123abcd.json",
        "eval/data/entity_synthetic.yaml",
        "docs/notes.txt",
    ],
)
def test_tracked_kinds_stay_committable(sandbox: Path, path: str) -> None:
    # Root-only scratch rules must not reach nested text files or the committed sources.
    assert not ignored(sandbox, path)
