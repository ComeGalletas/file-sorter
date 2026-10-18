"""TST-011.1: the default tiers run with PROMPTS_LOCAL=off (CLS-004.D16, RUN-017, TST-010).

The human's local prompt addenda are copied into every worktree by `make init`. A default-tier
replay is keyed on the exact prompt text, so no default-tier test may see an addendum. The
fixture lives in tests/conftest.py; these tests run it on a copy of the real conftest in a
synthetic tests tree, so the real tier mapping is what is exercised.
"""

import os
import re
from pathlib import Path

import pytest

from classifier.models.prompts import PROMPTS_DIR, load_effective_prompt, load_prompt

pytest_plugins = ["pytester"]

REPO_TESTS = Path(__file__).resolve().parents[1]
ENV = "PROMPTS_LOCAL"
TIERS = ("unit", "db", "integration", "gpu", "gate")

PROBE = """
import os
from pathlib import Path


def test_value():
    print(f"VALUE {Path(__file__).parent.name}={os.environ.get('PROMPTS_LOCAL')!r}")
"""
CHILD_PROBE = """
import subprocess
import sys


def test_child_sees_it():
    out = subprocess.run(
        [sys.executable, "-I", "-c", "import os; print(os.environ.get('PROMPTS_LOCAL'))"],
        capture_output=True,
        text=True,
        check=True,
    )
    print("CHILD=" + out.stdout.strip())
"""


@pytest.fixture
def inner(pytester: pytest.Pytester) -> pytest.Pytester:
    """A copy of the real conftest and helpers, with a probe module in every tier."""
    tests = pytester.path / "tests"
    (tests / "recordings").mkdir(parents=True)
    for rel in (
        "conftest.py",
        "recordings/replay.py",
        "recordings/vision.py",
        "recordings/vision_backend.py",
    ):
        (tests / rel).write_text((REPO_TESTS / rel).read_text(encoding="utf-8"), encoding="utf-8")
    for tier in TIERS:
        (tests / tier).mkdir(exist_ok=True)
        (tests / tier / "test_probe.py").write_text(PROBE, encoding="utf-8")
    (tests / "unit" / "test_child.py").write_text(CHILD_PROBE, encoding="utf-8")
    return pytester


def run_inner(inner: pytest.Pytester) -> str:
    result = inner.runpytest_subprocess(
        "--import-mode=importlib", "-p", "no:cacheprovider", "-s", "-m", "", "-q"
    )
    result.assert_outcomes(passed=len(TIERS) + 1)
    return result.stdout.str()


@pytest.mark.parametrize("outer", [None, "on", "off"])
def test_each_tier_gets_its_value(
    inner: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, outer: str | None
) -> None:
    """Whatever the shell holds, the default tiers see `off`; gpu and gate see it unset."""
    if outer is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, outer)
    seen = dict(re.findall(r"VALUE (\w+)=(\S+)", run_inner(inner)))
    assert seen == {
        "unit": "'off'",
        "db": "'off'",
        "integration": "'off'",
        "gpu": "None",
        "gate": "None",
    }


def test_a_subprocess_inherits_the_switch(inner: pytest.Pytester) -> None:
    assert "CHILD=off" in run_inner(inner)


def test_the_real_tiers_of_this_repo_run_with_it_off() -> None:
    assert os.environ.get(ENV) == "off"


PLACEHOLDER = "Placeholder addendum text, planted by a test."


@pytest.fixture
def planted(tmp_path: Path) -> Path:
    """A prompts dir holding a copy of `classify_v1` and a placeholder local addendum."""
    (tmp_path / "classify_v1.md").write_bytes((PROMPTS_DIR / "classify_v1.md").read_bytes())
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "classify_v1.md").write_text(PLACEHOLDER, encoding="utf-8")
    return tmp_path


def test_a_planted_addendum_changes_nothing_in_the_default_tiers(planted: Path) -> None:
    prompt = load_effective_prompt("classify_v1", prompts_dir=planted)
    assert prompt == load_prompt("classify_v1", planted)
    assert prompt.addendum is None
    assert prompt.addendum_hash is None
    assert prompt.effective_version == prompt.version == "classify_v1"
    assert PLACEHOLDER not in prompt.template


def test_the_same_addendum_applies_once_the_switch_is_not_off(
    planted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the planted file is live, so the test above is not vacuous."""
    monkeypatch.delenv(ENV)
    prompt = load_effective_prompt("classify_v1", prompts_dir=planted)
    assert prompt.addendum == PLACEHOLDER
    assert prompt.effective_version.startswith("classify_v1+")
