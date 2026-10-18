"""RUN-017: the human's private prompt addenda stay local, and reach worktrees through `make init`.

`prompts/local/*.md` is git-ignored except for the committed `*.example.md` files. The init helper
copies each addendum the worktree lacks from the main checkout, never overwrites one, and skips the
examples. Runs in a throwaway git repo with synthetic stand-ins; it never reads a real addendum.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]


def ignored(repo: Path, path: str) -> bool:
    out = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=repo)
    return out.returncode == 0


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "init_local_files.sh", repo / "scripts" / "init_local_files.sh")
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")
    with (repo / ".gitignore").open("a", encoding="utf-8") as fh:
        fh.write("wt/\n")
    (repo / ".env.example").write_text("SOURCE_ROOT=\n")
    (repo / "sanitize.example.yaml").write_text("rules: []\n")
    (repo / "prompts" / "local").mkdir(parents=True)
    (repo / "prompts" / "local" / "classify_v1.example.md").write_text("example\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # The main checkout's addendum: a synthetic stand-in, never the real one.
    (repo / "prompts" / "local" / "classify_v1.md").write_text("PLANTED-ADDENDUM\n")
    wt = repo / "wt" / "w1"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/w1", str(wt)], cwd=repo, check=True
    )
    return {"repo": repo, "wt": wt}


def test_addenda_are_ignored_and_examples_are_not(sandbox: dict) -> None:
    # The sandbox carries the repo's real .gitignore.
    assert ignored(sandbox["repo"], "prompts/local/classify_v1.md")
    assert ignored(sandbox["repo"], "prompts/local/nsfw_level_v1.md")
    assert not ignored(sandbox["repo"], "prompts/local/classify_v1.example.md")


def init(where: Path) -> None:
    script = ["bash", "scripts/init_local_files.sh"]
    subprocess.run(script, cwd=where, check=True, capture_output=True)


def test_init_copies_an_addendum_into_a_worktree(sandbox: dict) -> None:
    init(sandbox["wt"])
    copied = sandbox["wt"] / "prompts" / "local" / "classify_v1.md"
    assert copied.read_text() == "PLANTED-ADDENDUM\n"
    # The addendum was never committed: the worktree only had it from the copy.
    listed = subprocess.run(
        ["git", "ls-files", "prompts/local"],
        cwd=sandbox["repo"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = listed.stdout.split()
    assert tracked == ["prompts/local/classify_v1.example.md"]


def test_init_never_overwrites_a_worktree_addendum(sandbox: dict) -> None:
    mine = sandbox["wt"] / "prompts" / "local" / "classify_v1.md"
    mine.write_text("LOCAL-EDIT\n")
    init(sandbox["wt"])
    assert mine.read_text() == "LOCAL-EDIT\n"


def test_init_copies_nothing_without_addenda(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "init_local_files.sh", repo / "scripts" / "init_local_files.sh")
    (repo / ".env.example").write_text("SOURCE_ROOT=\n")
    (repo / "sanitize.example.yaml").write_text("rules: []\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    init(repo)
    assert not (repo / "prompts").exists()
