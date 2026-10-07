"""RUN-009: worker worktrees reach the git-ignored real fixtures without a copy of the images.

The test container mounts fixtures/images/ read-only; in a linked worktree the path points at
the main checkout's copy. Parses docker-compose.yml with PyYAML and runs the shell helpers in a
throwaway git repo with a fake `docker`. It never opens a real fixture.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
TARGET = "/app/fixtures/images"


def services() -> dict:
    data = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    return data.get("services") or {}


def fixture_mounts(service: dict) -> list[dict]:
    return [
        v
        for v in service.get("volumes") or []
        if isinstance(v, dict) and str(v.get("target", "")).startswith(TARGET)
    ]


def test_test_service_mounts_the_fixture_images_read_only() -> None:
    mounts = fixture_mounts(services()["test"])
    assert len(mounts) == 1
    mount = mounts[0]
    assert mount["type"] == "bind"
    assert mount["target"] == TARGET
    assert mount["read_only"] is True
    # The default is the checkout's own copy; only the env var points elsewhere.
    assert mount["source"] == "${FIXTURE_IMAGES:-./fixtures/images}"


def test_no_other_service_mounts_the_fixture_images() -> None:
    others = [n for n, s in services().items() if n != "test" and fixture_mounts(s)]
    assert others == []


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("fixtures")
    repo = root / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / "scripts").mkdir()
    for rel in (".claude/hooks/common.sh", "scripts/init_local_files.sh"):
        shutil.copy(REPO / rel, repo / rel)
    (repo / ".env.example").write_text("SOURCE_ROOT=\n")
    (repo / "sanitize.example.yaml").write_text("rules: []\n")
    (repo / ".gitignore").write_text(".env\nsanitize.yaml\nfixtures/labels.csv\nwt/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # The main checkout's local files: synthetic stand-ins, never the real ones.
    (repo / ".env").write_text("SOURCE_ROOT=/x\n")
    (repo / "fixtures").mkdir()
    (repo / "fixtures" / "labels.csv").write_text("file,format\nexample_0001.png,photos\n")
    wt = repo / "wt" / "w1"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/w1", str(wt)], cwd=repo, check=True
    )
    # A fake docker that reports what compose_test would hand it.
    bin_ = root / "bin"
    bin_.mkdir()
    fake = bin_ / "docker"
    fake.write_text(
        '#!/usr/bin/env bash\necho "FIXTURE_IMAGES=${FIXTURE_IMAGES-unset}"\necho "$*"\n'
    )
    fake.chmod(0o755)
    return {"repo": repo, "wt": wt, "bin": bin_}


def compose_test_output(sb: dict[str, Path], where: str) -> str:
    env = {**os.environ, "PATH": f"{sb['bin']}{os.pathsep}{os.environ['PATH']}"}
    env.pop("FIXTURE_IMAGES", None)
    out = subprocess.run(
        ["bash", "-c", ". .claude/hooks/common.sh; compose_test pytest -q"],
        cwd=sb[where],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def test_worktree_compose_test_points_at_the_main_checkout_images(sandbox: dict) -> None:
    out = compose_test_output(sandbox, "wt")
    main = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=sandbox["wt"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert f"FIXTURE_IMAGES={Path(main).parent.as_posix()}/fixtures/images" in out
    assert "-p file-sorter-w1" in out


def test_main_checkout_compose_test_uses_its_own_images(sandbox: dict) -> None:
    out = compose_test_output(sandbox, "repo")
    assert "FIXTURE_IMAGES=unset" in out
    assert "-p file-sorter" not in out


def test_init_copies_the_labels_into_a_worktree_only(sandbox: dict) -> None:
    subprocess.run(["bash", "scripts/init_local_files.sh"], cwd=sandbox["wt"], check=True)
    copied = sandbox["wt"] / "fixtures" / "labels.csv"
    assert copied.read_text() == (sandbox["repo"] / "fixtures" / "labels.csv").read_text()
    # It never copies images: those are mounted (D1).
    assert not (sandbox["wt"] / "fixtures" / "images").exists()


def test_init_makes_no_labels_placeholder(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "init_local_files.sh", repo / "scripts" / "init_local_files.sh")
    (repo / ".env.example").write_text("SOURCE_ROOT=\n")
    (repo / "sanitize.example.yaml").write_text("rules: []\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["bash", "scripts/init_local_files.sh"], cwd=repo, check=True)
    assert not (repo / "fixtures" / "labels.csv").exists()
