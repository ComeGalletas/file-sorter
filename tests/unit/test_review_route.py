"""RUN-006.1/.4: scripts/review_route.sh picks the reviewer subagent (RUN-006.D1, D5).

Only a PR whose fenced triage block says Size: small AND whose every current and previous
path is docs/ or README.md gets the quick (Haiku, static) review; any doubt routes to the
full reviewer. The script is fed through REVIEW_ROUTE_* variables, so no gh call is made,
except in the last test, which checks the fallback when gh can't be used.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_route.sh"


def triage(size: str) -> str:
    return f"## Triage\n\n```\nSize: {size} — why\nTests: unit\nAgents: solo\n```\n"


def route(
    files: list[str],
    body: str,
    previous: list[str] | None = None,
    changed: int | None = None,
) -> str:
    env = {
        **os.environ,
        "REVIEW_ROUTE_FILES": "\n".join(files),
        "REVIEW_ROUTE_PREVIOUS": "\n".join(previous or []),
        "REVIEW_ROUTE_BODY": body,
    }
    if changed is not None:
        env["REVIEW_ROUTE_CHANGED"] = str(changed)
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30, check=True
    )
    return result.stdout.strip()


def agent(*args, **kwargs) -> str:
    return route(*args, **kwargs).split()[0]


# ---- the quick path ----


@pytest.mark.parametrize(
    "files",
    [
        ["docs/journals/INDEX.md"],
        ["docs/plans/m1.md", "docs/journals/pipeline_journal.md"],
        ["README.md", "docs/journals/bootstrap_journal.md"],
    ],
)
def test_small_docs_only_pr_gets_the_quick_reviewer(files: list[str]) -> None:
    assert route(files, triage("small")) == "reviewer-quick (small, docs only)"


def test_matching_changed_count_keeps_the_quick_path() -> None:
    assert agent(["docs/a.md", "docs/b.md"], triage("small"), changed=2) == "reviewer-quick"


def test_rename_within_docs_stays_quick() -> None:
    files, previous = ["docs/journals/new.md"], ["docs/journals/old.md"]
    assert agent(files, triage("small"), previous=previous) == "reviewer-quick"


# ---- paths ----


@pytest.mark.parametrize(
    "path",
    [
        "classifier/cli/__init__.py",
        "tests/unit/test_smoke.py",
        "scripts/gate_3.py",
        ".claude/hooks/guard.sh",
        ".claude/agents/reviewer.md",
        ".claude/roles/lead.md",
        ".claude/settings.json",
        ".githooks/pre-push",
        "docker-compose.yml",
        "Dockerfile",
        "Makefile",
        "config.yaml",
        "CLAUDE.md",
        "DESIGN.md",
        "prompts/caption.md",
        "docs-not-really/x.md",  # only the docs/ folder counts, not a look-alike prefix
    ],
)
def test_any_non_docs_file_needs_the_full_reviewer(path: str) -> None:
    out = route(["docs/journals/x.md", path], triage("small"))
    assert out == f"reviewer (touches {path})"


@pytest.mark.parametrize("old", ["CLAUDE.md", ".claude/hooks/guard.sh", "scripts/review_route.sh"])
def test_rename_into_docs_is_judged_by_its_old_path(old: str) -> None:
    # Review finding 1: moving a protected file into docs/ must not look docs-only.
    out = route(["docs/moved.md"], triage("small"), previous=[old])
    assert out == f"reviewer (touches {old})"


def test_truncated_listing_needs_the_full_reviewer() -> None:
    # Review finding 2: a listing that doesn't match changedFiles may hide a non-docs file.
    files = [f"docs/f{i}.md" for i in range(100)]
    assert (
        route(files, triage("small"), changed=101) == "reviewer (listed 100 of 101 changed files)"
    )


def test_no_files_gets_the_full_reviewer() -> None:
    assert route([], triage("small")) == "reviewer (no changed files listed)"


# ---- size ----


@pytest.mark.parametrize("size", ["medium", "large"])
def test_medium_and_large_get_the_full_reviewer_even_for_docs(size: str) -> None:
    assert route(["docs/plans/m1.md"], triage(size)) == f"reviewer (triage size: {size})"


def test_missing_triage_gets_the_full_reviewer() -> None:
    assert route(["docs/plans/m1.md"], "no triage here") == "reviewer (triage size: missing)"


def test_size_outside_a_fenced_triage_block_is_ignored() -> None:
    # Review finding 3: a bare "Size: small" line is not a triage block.
    assert agent(["docs/x.md"], "Size: small\nTests: unit\nAgents: solo\n") == "reviewer"


def test_fenced_block_without_tests_and_agents_is_not_a_triage() -> None:
    assert agent(["docs/x.md"], "```\nSize: small\n```\n") == "reviewer"


def test_size_in_an_html_comment_is_ignored() -> None:
    # Review finding 3: the template's own comment, or a planted one, must not set the size.
    body = "<!-- " + triage("small") + " -->\n" + triage("medium")
    assert route(["docs/x.md"], body) == "reviewer (triage size: medium)"


def test_multiline_html_comment_is_ignored() -> None:
    body = "<!--\n" + triage("small") + "\n-->\nno real triage"
    assert route(["docs/x.md"], body) == "reviewer (triage size: missing)"


def test_disagreeing_triage_blocks_need_the_full_reviewer() -> None:
    out = route(["docs/x.md"], triage("small") + "\n" + triage("medium"))
    assert out.startswith("reviewer (triage blocks disagree")


def test_smaller_is_not_small() -> None:
    assert route(["docs/x.md"], triage("smaller")) == "reviewer (triage size: missing)"


def test_size_is_read_case_insensitively_and_with_crlf() -> None:
    body = "```\r\nSIZE: Small — docs\r\nTESTS: unit\r\nAgents: solo\r\n```\r\n"
    assert agent(["docs/x.md"], body) == "reviewer-quick"


def test_a_later_quoted_size_does_not_downgrade() -> None:
    body = triage("medium") + "\nEarlier rounds said Size: small.\n"
    assert agent(["docs/x.md"], body) == "reviewer"


# ---- failures ----


def test_gh_failure_falls_back_to_the_full_reviewer(tmp_path: Path) -> None:
    # Review finding 7: with no usable gh, the script must still print "reviewer".
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}  # no gh, sed, awk... on PATH
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "10"], capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "reviewer (could not read PR 10)"
