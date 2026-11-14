"""RUN-020: the app image installs against constraints.txt, which pins every resolved package.

Reads constraints.txt, pyproject.toml and the Dockerfile as text. Nothing runs or is downloaded.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")


def pins() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (REPO / "constraints.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.match(line)
        assert match, f"constraints.txt has an unpinned line: {line!r}"
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        assert name not in out, f"constraints.txt pins {name} twice"
        out[name] = match.group(2)
    return out


def declared() -> list[str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    reqs = list(data["project"]["dependencies"])
    for extra in data["project"].get("optional-dependencies", {}).values():
        reqs.extend(extra)
    names = [re.split(r"[\[<>=!~ ;]", r, maxsplit=1)[0] for r in reqs]
    return [re.sub(r"[-_.]+", "-", n).lower() for n in names]


def test_every_line_is_an_exact_pin() -> None:
    assert len(pins()) > 20


def test_every_declared_dependency_is_pinned() -> None:
    missing = [name for name in declared() if name not in pins()]
    assert not missing, f"declared but not pinned: {missing}"


def test_the_torch_step_wheels_are_left_to_torch_version() -> None:
    assert not [n for n in pins() if n in {"torch", "triton"} or n.startswith("nvidia-")]


def test_the_dockerfile_installs_with_the_constraints() -> None:
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY [^\n]*\bconstraints\.txt\b", text, re.MULTILINE)
    assert re.search(r'^RUN pip install -c constraints\.txt -e "\.\[dev\]"$', text, re.MULTILINE)
