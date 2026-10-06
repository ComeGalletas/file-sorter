"""RUN-006.1: scripts/review_route.sh picks the reviewer subagent (RUN-006.D1).

Only a PR whose triage says Size: small AND that changes nothing but docs/ and README.md gets
the quick (Haiku, static) review; everything else gets the full reviewer. The script is fed
through REVIEW_ROUTE_FILES / REVIEW_ROUTE_BODY, so no gh call is made.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_route.sh"


def triage(size: str) -> str:
    return f"## Triage\n\n```\nSize: {size} — why\nTests: unit\n```\n"


def route(files: list[str], body: str) -> str:
    env = {**os.environ, "REVIEW_ROUTE_FILES": "\n".join(files), "REVIEW_ROUTE_BODY": body}
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30, check=True
    )
    return result.stdout.strip()


def agent(files: list[str], body: str) -> str:
    return route(files, body).split()[0]


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


@pytest.mark.parametrize("size", ["medium", "large"])
def test_medium_and_large_get_the_full_reviewer_even_for_docs(size: str) -> None:
    assert route(["docs/plans/m1.md"], triage(size)) == f"reviewer (triage size: {size})"


def test_missing_triage_gets_the_full_reviewer() -> None:
    assert route(["docs/plans/m1.md"], "no triage block here") == "reviewer (triage size: missing)"


def test_size_is_read_case_insensitively_and_with_crlf() -> None:
    body = "```\r\nSIZE: Small — docs\r\n```\r\n"
    assert agent(["docs/x.md"], body) == "reviewer-quick"


def test_first_size_line_wins() -> None:
    # A later "Size: small" (e.g. quoted in the text) must not downgrade a medium PR.
    body = triage("medium") + "\nEarlier rounds said Size: small.\n"
    assert agent(["docs/x.md"], body) == "reviewer"


def test_no_files_gets_the_full_reviewer() -> None:
    assert route([], triage("small")) == "reviewer (no changed files listed)"
