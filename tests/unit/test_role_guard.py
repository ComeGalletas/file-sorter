"""RUN-005.1/.4: the role guard (RUN-002.D8, RUN-005.D1, D5) in a throwaway repo.

Layout under tmp_path:
    repo/                               main checkout  -> the lead's location (.env inside)
    repo/.agent-office/worktrees/w1/    linked worktree -> a worker's location
      escape -> repo/                   a directory symlink out of the worktree (RUN-005.4)
      link.md -> repo/CLAUDE.md         a file symlink out of the worktree (RUN-005.4)
    memory/                             outside the repo (like Claude's memory, agent-logs)
    images/, sorted/                    SOURCE_ROOT and RESULTS_ROOT from repo/.env (D5)
The guard is run exactly as Claude Code runs a PreToolUse hook: JSON on stdin, exit 2 = blocked.
A symlink exercises the same resolution path as an NTFS junction; the real junction is
checked on the Windows host (RUN-005 Results), since this container is Linux.
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
    images, sorted_ = root / "images", root / "sorted"
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    for d in (memory, images, sorted_):
        d.mkdir()
    for name in ("guard.sh", "common.sh"):
        shutil.copy(SRC / name, hooks / name)
    (repo / ".gitignore").write_text(".agent-office/\n.env\n")
    (repo / "CLAUDE.md").write_text("rules\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # Local, untracked, like the real .env: one value quoted, one not.
    (repo / ".env").write_text(f'SOURCE_ROOT="{images}"\nRESULTS_ROOT={sorted_}\n')
    wt = repo / ".agent-office" / "worktrees" / "w1"
    subprocess.run(
        [*GIT, "worktree", "add", "-q", "-b", "office/w1", str(wt)], cwd=repo, check=True
    )
    (wt / "escape").symlink_to(repo, target_is_directory=True)
    (wt / "link.md").symlink_to(repo / "CLAUDE.md")
    return {
        "repo": repo,
        "wt": wt,
        "memory": memory,
        "images": images,
        "sorted": sorted_,
        "guard": hooks / "guard.sh",
    }


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


# ---- RUN-005.4: links, case and the image folders (PR #9 review findings 1-3) ----


def test_symlink_escape_resolves_to_the_main_checkout(sandbox: dict[str, Path]) -> None:
    # Review finding 1: a link inside the worktree must not make the main checkout "own".
    assert guard(sandbox, "wt", edit(sandbox["wt"] / "escape" / "CLAUDE.md")) == 2
    assert guard(sandbox, "wt", edit(sandbox["wt"] / "escape" / "classifier" / "new.py")) == 2
    assert guard(sandbox, "wt", edit(sandbox["wt"] / "link.md")) == 2


@pytest.mark.parametrize(
    "rel",
    ["claude.md", "Claude.MD", "Design.md", "docs/Journals/INDEX.md", "DOCS/plans/m1.md"],
)
def test_worker_protected_names_are_case_insensitive(sandbox: dict[str, Path], rel: str) -> None:
    # Review finding 2: on NTFS, claude.md is CLAUDE.md.
    assert guard(sandbox, "wt", edit(sandbox["wt"] / rel)) == 2


def test_lead_docs_allowance_is_case_insensitive(sandbox: dict[str, Path]) -> None:
    assert guard(sandbox, "repo", edit(sandbox["repo"] / "Docs" / "journals" / "x.md")) == 0
    assert guard(sandbox, "repo", edit(sandbox["repo"] / "Classifier" / "x.py")) == 2


@pytest.mark.parametrize("where", ["repo", "wt"])
@pytest.mark.parametrize("folder", ["images", "sorted"])
def test_desks_never_write_to_the_image_folders(
    sandbox: dict[str, Path], where: str, folder: str
) -> None:
    # Review finding 3 / RUN-005.D5: SOURCE_ROOT and RESULTS_ROOT come from the local .env.
    assert guard(sandbox, where, edit(sandbox[folder] / "a.png")) == 2
    assert guard(sandbox, where, edit(sandbox[folder] / "sub" / "b.png")) == 2


def test_image_folders_are_matched_case_insensitively(sandbox: dict[str, Path]) -> None:
    upper = str(sandbox["images"]).upper() + "/a.png"
    assert guard(sandbox, "wt", edit(upper)) == 2


def test_human_may_still_touch_the_image_folders(sandbox: dict[str, Path]) -> None:
    assert guard(sandbox, "repo", edit(sandbox["images"] / "a.png"), desk=False) == 0


# ---- RUN-005.5: Win32 name tricks (PR #9 review round 2, findings 1-2) ----

PROTECTED = ["CLAUDE.md", "DESIGN.md", "docs/journals/INDEX.md"]


@pytest.mark.parametrize("name", PROTECTED)
@pytest.mark.parametrize("suffix", [".", " ", ". .", "..", " . "])
def test_trailing_dots_and_spaces_reach_the_protected_file(
    sandbox: dict[str, Path], name: str, suffix: str
) -> None:
    # Round 2, finding 1: Win32 strips trailing dots/spaces, so "CLAUDE.md." IS CLAUDE.md.
    assert guard(sandbox, "wt", edit(str(sandbox["wt"] / name) + suffix)) == 2


@pytest.mark.parametrize("name", PROTECTED)
@pytest.mark.parametrize("stream", [":hidden", ":hidden:$DATA", "::$DATA"])
def test_alternate_data_streams_are_refused(
    sandbox: dict[str, Path], name: str, stream: str
) -> None:
    # Round 2, finding 2, decided by the human: block streams (RUN-005.D7).
    assert guard(sandbox, "wt", edit(str(sandbox["wt"] / name) + stream)) == 2


def test_streams_are_refused_for_the_lead_too(sandbox: dict[str, Path]) -> None:
    assert guard(sandbox, "repo", edit(str(sandbox["repo"] / "docs" / "x.md") + ":hidden")) == 2


def test_trailing_dot_on_a_folder_segment_is_normalized(sandbox: dict[str, Path]) -> None:
    # "docs./journals./INDEX.md" is docs/journals/INDEX.md on Windows.
    assert guard(sandbox, "wt", edit(sandbox["wt"] / "docs." / "journals." / "INDEX.md")) == 2


@pytest.mark.parametrize(
    ("where", "rel"),
    [
        ("wt", "classifier/a.b.c.py"),  # inner dots are untouched
        ("wt", "classifier/./cli/x.py"),  # a lone "." segment is untouched
        ("repo", "docs/journals/x.md"),
        ("repo", "docs/journals/x.md."),  # normalizes to an allowed docs/ file
    ],
)
def test_normalization_leaves_ordinary_names_alone(
    sandbox: dict[str, Path], where: str, rel: str
) -> None:
    assert guard(sandbox, where, edit(f"{sandbox[where]}/{rel}")) == 0
