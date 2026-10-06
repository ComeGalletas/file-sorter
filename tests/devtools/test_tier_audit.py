"""TST-002.2: the tier audit (CLAUDE.md §3, R-TST tier layout).

A `unit` test touches nothing external: fakes for the db, models and Ollama. This audit scans
every module whose tier is `unit` (by `tier_of()` in tests/conftest.py, so the audit and the
markers cannot drift) and fails when one opens a db connection, loads a model or calls Ollama.
Each failure names the move or the `TIER_BY_DIR` line that puts the module in its right tier.

The scan is static (`ast`): test modules are never imported, so the audit needs no db or GPU.
There is no per-line escape hatch; the fix is the tier.

Named gap (TST-002.2 Results): a unit test that reaches a db or model through a `classifier.*`
helper is only caught if the helper's dotted name is in INDIRECT_DB / INDIRECT_MODEL below.
Whether a helper needs the db or a model is not reliably decidable from the test's source, so
the lists start empty and a task that adds such a helper registers it here.
"""

import ast
import importlib.util
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]

# Concatenated so this module does not trip its own scan of string constants.
DB_ENV_VAR = "DB_" + "DSN"
OLLAMA_PORT = "114" + "34"

DB_IMPORTS = {"psycopg", "psycopg2", "psycopg_pool", "asyncpg"}
DB_CALLS = {"create_engine", "create_async_engine"}
DB_FIXTURES = {"db", "migrated_db"}
MODEL_IMPORTS = {"torch", "transformers", "open_clip", "sentence_transformers", "timm"}
MODEL_CALLS = {"from_pretrained"}
OLLAMA_IMPORTS = {"ollama"}
HTTP_MODULES = {"httpx", "requests"}
HTTP_CALLS = {"get", "post", "put", "patch", "delete", "head", "request", "stream", "send"}

# Dotted prefixes of classifier helpers known to need the db or a model (see the named gap).
INDIRECT_DB: tuple[str, ...] = ()
INDIRECT_MODEL: tuple[str, ...] = ()

# What each kind of violation needs: the tier the module belongs in.
TIER_FOR = {"db": "db", "model": "gpu", "ollama": "gpu"}


@dataclass(frozen=True)
class Violation:
    kind: str  # db | model | ollama
    line: int
    what: str


def _load_conftest():
    spec = importlib.util.spec_from_file_location("tier_audit_conftest", TESTS / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root(dotted: str) -> str:
    return dotted.split(".")[0]


def _call_name(node: ast.Call) -> tuple[str | None, str]:
    """(receiver root name, called attribute or function name) for a call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return None, func.id
    if isinstance(func, ast.Attribute):
        base = func.value
        while isinstance(base, ast.Attribute):
            base = base.value
        return (base.id if isinstance(base, ast.Name) else None), func.attr
    return None, ""


def scan_source(
    source: str,
    indirect_db: Iterable[str] = INDIRECT_DB,
    indirect_model: Iterable[str] = INDIRECT_MODEL,
) -> list[Violation]:
    tree = ast.parse(source)
    found: list[Violation] = []
    own_fixtures = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    indirect_db, indirect_model = tuple(indirect_db), tuple(indirect_model)

    def add(kind: str, node: ast.AST, what: str) -> None:
        found.append(Violation(kind, node.lineno, what))

    def check_dotted(dotted: str, node: ast.AST) -> None:
        root = _root(dotted)
        if root in DB_IMPORTS:
            add("db", node, f"imports {dotted}")
        elif root in MODEL_IMPORTS:
            add("model", node, f"imports {dotted}")
        elif root in OLLAMA_IMPORTS:
            add("ollama", node, f"imports {dotted}")
        if dotted.startswith(indirect_db):
            add("db", node, f"imports {dotted}, which needs the db")
        if dotted.startswith(indirect_model):
            add("model", node, f"imports {dotted}, which needs a model")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check_dotted(alias.name, node)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            check_dotted(node.module, node)
            for alias in node.names:
                check_dotted(f"{node.module}.{alias.name}", node)
        elif isinstance(node, ast.Call):
            receiver, name = _call_name(node)
            if name in DB_CALLS:
                add("db", node, f"calls {name}()")
            elif name in MODEL_CALLS:
                add("model", node, f"calls {name}()")
            elif receiver in HTTP_MODULES and name in HTTP_CALLS:
                add("ollama", node, f"calls {receiver}.{name}() (a real HTTP request)")
            elif name == "usefixtures":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in DB_FIXTURES:
                        add("db", node, f"uses the {arg.value} fixture")
        elif isinstance(node, ast.FunctionDef):
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.arg in DB_FIXTURES and arg.arg not in own_fixtures:
                    add("db", node, f"requests the {arg.arg} fixture")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == DB_ENV_VAR:
                add("db", node, f"reads {DB_ENV_VAR}")
            elif OLLAMA_PORT in node.value:
                add("ollama", node, "names the Ollama port")
    return sorted(set(found), key=lambda v: (v.line, v.kind, v.what))


def fix_for(rel: Path, kind: str) -> str:
    """The move, or the TIER_BY_DIR line, that puts the module in its right tier."""
    tier = TIER_FOR[kind]
    parts = rel.parts
    if len(parts) > 1 and parts[0] == "unit":
        return f"move it to tests/{tier}/{'/'.join(parts[1:])}"
    if len(parts) > 1:
        return f'add `"{parts[0]}": "{tier}",` to TIER_BY_DIR in tests/conftest.py'
    return f"move it to tests/{tier}/{rel.name}"


def audit(root: Path = TESTS) -> list[str]:
    conftest = _load_conftest()
    messages: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name in {"conftest.py", "__init__.py"} or ".pytest_cache" in path.parts:
            continue
        if root == TESTS and conftest.tier_of(path) != "unit":
            continue
        rel = path.relative_to(root)
        for v in scan_source(path.read_text(encoding="utf-8")):
            messages.append(
                f"tests/{rel.as_posix()}:{v.line} is a unit test but {v.what} "
                f"({v.kind} tier work): {fix_for(rel, v.kind)}"
            )
    return messages


def test_no_unit_test_touches_db_models_or_ollama() -> None:
    problems = audit()
    assert not problems, "tier audit failed:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("import psycopg\n", "db"),
        ("from psycopg import connect\n", "db"),
        ("import asyncpg\n", "db"),
        ("from sqlalchemy import create_engine\ncreate_engine('x')\n", "db"),
        ("def test_a(db):\n    pass\n", "db"),
        ("def test_a(migrated_db):\n    pass\n", "db"),
        ("import pytest\n@pytest.mark.usefixtures('db')\ndef test_a():\n    pass\n", "db"),
        (f"import os\nos.environ['{DB_ENV_VAR}']\n", "db"),
        (f"import os\nos.getenv('{DB_ENV_VAR}')\n", "db"),
        ("import torch\n", "model"),
        ("from transformers import AutoModel\n", "model"),
        ("def f(m):\n    m.from_pretrained('x')\n", "model"),
        ("import ollama\n", "ollama"),
        ("import httpx\nhttpx.post('http://x')\n", "ollama"),
        ("import requests\nrequests.get('http://x')\n", "ollama"),
        (f"URL = 'http://ollama:{OLLAMA_PORT}'\n", "ollama"),
    ],
)
def test_scanner_flags_each_forbidden_use(source: str, kind: str) -> None:
    assert kind in {v.kind for v in scan_source(source)}


@pytest.mark.parametrize(
    "source",
    [
        "import json\nfrom pathlib import Path\n\ndef test_a(tmp_path):\n    assert tmp_path\n",
        "import httpx\nclient = httpx.Client(transport=httpx.MockTransport(lambda r: None))\n",
        "import pytest\n\n@pytest.fixture\ndef db():\n    return 1\n\ndef test_a(db):\n    pass\n",
        "from classifier.config import load\n",
    ],
)
def test_scanner_passes_clean_modules(source: str) -> None:
    assert scan_source(source) == []


def test_indirect_helpers_are_flagged_when_registered() -> None:
    source = "from classifier.db.session import a\nfrom classifier.models.siglip import b\n"
    assert scan_source(source) == []
    found = scan_source(source, ("classifier.db.session",), ("classifier.models.siglip",))
    assert {v.kind for v in found} == {"db", "model"}


def test_fix_names_the_move_or_the_conftest_line() -> None:
    assert fix_for(Path("unit/graph/test_x.py"), "db") == "move it to tests/db/graph/test_x.py"
    assert fix_for(Path("devtools/test_x.py"), "model") == (
        'add `"devtools": "gpu",` to TIER_BY_DIR in tests/conftest.py'
    )
    assert fix_for(Path("test_x.py"), "ollama") == "move it to tests/gpu/test_x.py"


def test_audit_reports_a_bad_unit_module_with_its_fix(tmp_path: Path) -> None:
    (tmp_path / "unit").mkdir()
    (tmp_path / "unit" / "test_bad.py").write_text("import psycopg\n", encoding="utf-8")
    (tmp_path / "unit" / "test_ok.py").write_text("import json\n", encoding="utf-8")
    problems = audit(tmp_path)
    assert len(problems) == 1
    assert "tests/unit/test_bad.py:1" in problems[0]
    assert "move it to tests/db/test_bad.py" in problems[0]


def test_audit_skips_modules_outside_the_unit_tier() -> None:
    conftest = _load_conftest()
    assert conftest.tier_of(TESTS / "db" / "test_db_reachable.py") == "db"
    assert conftest.tier_of(TESTS / "devtools" / "test_tier_audit.py") == "unit"
