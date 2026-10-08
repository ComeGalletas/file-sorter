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
        ("gh pr merge 5 --merge --delete-branch --match-head-commit 0531338abcdef", 0),
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


# ---- RUN-008: a worker brings main into its own branch, and nothing else ----


@pytest.mark.parametrize(
    "command",
    [
        "git merge origin/main",
        "git fetch && git merge origin/main",
        "git fetch origin && git merge --no-edit origin/main",
        "git merge --no-ff --no-edit origin/main",
        "git merge --abort",
        "git merge --continue",
        "git pull --ff-only",
        "git merge-base --is-ancestor abc HEAD",
        "git log --merges",
        "GIT MERGE ORIGIN/MAIN",
        "gh pr view 5 --json mergeable,headRefOid",
        "gh pr checks 5",
        "git commit -F msg.txt",
        "git push -u origin HEAD",
        "git log origin/main..HEAD",
        "cat .git/HEAD | grep main",
        "git commit -F - <<EOF\nRUN-1.1: Bring main in\n\nResolves the merge of the journal\nEOF",
        'git push -u origin "$(git branch --show-current)"',
        'git commit -m "$(cat msg.txt)"',
        "git log --oneline -3 $(git merge-base HEAD origin/main)..HEAD",
        "git stash drop stash@{0}",
        "git commit --amend -F msg.txt",
        # round 1, finding 2: braces inside quotes are never expanded
        "gh pr view 5 --json number,title --jq '{n: .number, t: .title}'",
        'gh pr list --json number,title --jq ".[] | {n: .number, t: .title}"',
        'gh pr view 5 --jq \'{n: .number, t: "a \\" b"}\'',
        "git commit -F - <<EOF\nX.1: Don't stop at the first quote\nEOF",
        "git log --oneline @{u}..HEAD",
    ],
)
def test_worker_may_sync_with_main(sandbox: dict[str, Path], command: str) -> None:
    assert guard(sandbox, "wt", bash(command)) == 0


@pytest.mark.parametrize(
    "command",
    [
        "git merge office/other-desk",
        "git merge main",
        "git merge origin/main origin/office/other-desk",
        "git merge -X theirs origin/main",
        "git merge --squash origin/main",
        "git merge -m sync origin/main",
        "git merge origin/main; git merge office/other-desk",
        "git merge origin/main && git merge office/other-desk",
        "git -c core.editor=true merge office/other-desk",
        "git -C ../other merge origin/main",
        "env GIT_EDITOR=true git merge office/other-desk",
        "echo $(git merge office/other-desk)",
        "echo `git merge office/other-desk`",
        "(git merge office/other-desk)",
        "git pull",
        "git pull origin main",
        "git pull --rebase",
        "git pull --ff-only origin office/other-desk",
        "git -c x=y tag v1",
        "gh  pr merge 3 --merge",
        # PR #39 round 1, finding 1: detection was narrow and failed open.
        'bash -c "git merge office/other-desk"',
        "sh -c 'git merge office/other-desk'",
        'eval "git merge office/other-desk"',
        "git --no-pager merge office/other-desk",
        "git --git-dir=.git merge office/other-desk",
        "git -p merge office/other-desk",
        'git -C "a b" merge office/other-desk',
        "git.exe merge office/other-desk",
        "/usr/bin/git merge office/other-desk",
        "C:\\Program Files\\Git\\cmd\\git.exe merge office/other-desk",
        "GIT merge office/other-desk",
        "Git.exe pull origin main",
        "git -c alias.m=merge m office/other-desk",
        "git config alias.sync merge",
        # finding 4
        "git merge origin/main~0",
        "git merge FETCH_HEAD",
        "git merge --ff-only origin/main",
        "git merge origin/main && gh pr merge 5",
        "gh pr merge 5",
        "git tag v1",
        # finding 2: the PR-merge, tag and push denials had the same blind spots
        "git --no-pager tag v1",
        "gh -R owner/repo pr merge 5",
        "GH pr merge 5",
        "gh api -X PUT repos/o/r/pulls/5/merge",
        "git push origin HEAD:refs/heads/main",
        "git push origin +HEAD:main",
        "GIT push origin main",
        # D4: failing closed refuses a commit message that names a guarded word inline
        'git commit -m "merge notes"',
        # D5: a double quote used to hide the rest of the command from the guard
        'git commit -m "x" && git push origin main',
        'echo "x"; gh pr merge 5 --merge',
        'git status && echo "ok" && git merge office/other-desk',
        # PR #39 round 2, findings 1-3 (D6): backslashes, line continuations, indirection
        r"gi\t merge office/other-desk",
        r"g\it merge office/other-desk",
        r"git mer\ge office/other-desk",
        r"git ta\g v1",
        r"git pu\sh origin main",
        r"gh pr mer\ge 5",
        "git \\\nmerge office/other-desk",
        "git merge \\\n  office/other-desk",
        "$(echo git) merge office/other-desk",
        "x=git; $x merge office/other-desk",
        "git $(echo merge) office/other-desk",
        "m=merge; git ${m} office/other-desk",
        "eval git merge office/other-desk",
        "`echo git` merge office/other-desk",
        # round 2, finding 5: pushes that include main
        "git push --all origin",
        "git push --mirror origin",
        # RUN-010.D1: ANSI-C quoting and brace expansion
        "git $'merge' office/other-desk",
        r"git $'mer\x67e' office/other-desk",
        "git {merge,} office/other-desk",
        "git me{r,}ge office/other-desk",
        "gh pr {merge,} 5",
        "git ta{g,} v1",
        # PR #43 round 1, finding 1: the expansion builds the program name itself
        "g{i,}t merge office/other-desk",
        r"g$'\x69't merge office/other-desk",
        "{g,}it merge office/other-desk",
        "echo {1..3} && g{h,}h pr merge 5",
        # PR #43 round 2, finding 1: quote confusion
        "echo 'say \"hi' ; g{i,}t merge office/other-desk ; echo 'x\"'",
        'echo \\"; g{i,}t merge office/other-desk; echo \\"',
        'echo "it\'s" ; g{i,}t merge office/other-desk',
        "echo 'unclosed ; g{i,}t merge office/other-desk",
    ],
)
def test_worker_other_merges_pulls_and_tags_are_refused(
    sandbox: dict[str, Path], command: str
) -> None:
    assert guard(sandbox, "wt", bash(command)) == 2


def test_lead_merges_are_unchanged_by_the_worker_rule(sandbox: dict[str, Path]) -> None:
    assert guard(sandbox, "repo", bash("git merge --no-edit origin/main")) == 0
    assert guard(sandbox, "repo", bash("gh pr merge 5 --squash")) == 2


@pytest.mark.parametrize(
    "command",
    ['echo "a" && gh pr merge 5 --squash', 'echo "a" && git tag -a m1-approved -m ok'],
)
def test_lead_rules_see_past_a_double_quote(sandbox: dict[str, Path], command: str) -> None:
    assert guard(sandbox, "repo", bash(command)) == 2


@pytest.mark.parametrize("where", ["repo", "wt"])
def test_unreadable_shell_command_is_refused(sandbox: dict[str, Path], where: str) -> None:
    assert guard(sandbox, where, {"tool_name": "Bash", "tool_input": {}}) == 2


# ---- RUN-013.D1: the lead's merge names the reviewed head ----


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("gh pr merge 5 --merge --delete-branch", 2),
        ("gh pr merge 5 --merge --delete-branch --match-head-commit", 2),
        ("gh pr merge 5 --merge --delete-branch --match-head-commit HEAD", 2),
        ("gh pr merge 5 --merge --delete-branch --match-head-commit 0531338", 0),
        ("gh pr merge 5 --merge --match-head-commit=0531338abcdef0123 --delete-branch", 0),
        ("gh pr merge 5 --squash --match-head-commit 0531338", 2),
    ],
)
def test_lead_merge_names_the_reviewed_head(
    sandbox: dict[str, Path], command: str, expected: int
) -> None:
    assert guard(sandbox, "repo", bash(command)) == expected
