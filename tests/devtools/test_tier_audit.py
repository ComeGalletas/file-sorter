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

Also not detected: a real transport hidden behind `httpx.Client(...)` (module-level calls and
`from httpx import post` are flagged; a `MockTransport` stays legal), a db reached through an
autouse fixture in a conftest.py, and dynamic imports whose argument is not a string constant.
Setting an env var such as DB_DSN opens no connection, so it is not flagged.
"""

import ast
import importlib.util
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]

# Concatenated so this module does not trip its own scan of string constants.
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

# What each kind of violation needs: the tier the module belongs in. A real HTTP request has no
# tier of its own: the unit-test fix is a fake transport.
TIER_FOR = {"db": "db", "model": "gpu", "ollama": "gpu"}
FAKE_TRANSPORT_FIX = "use a fake transport (httpx.MockTransport) instead of a real request"
DYNAMIC_IMPORTS = {"import_module", "__import__"}


@dataclass(frozen=True)
class Violation:
    kind: str  # db | model | ollama | http
    line: int
    what: str


# TST-004: the real fixtures. Concatenated so this module does not trip its own scan.
FIXTURES = "fix" + "tures"
REAL_FIXTURES = {"images": FIXTURES + "/images", "labels": FIXTURES + "/labels.csv"}
# Whole path segments only: the committed fixtures/labels.example.csv stays legal.
REAL_FIXTURE_RE = re.compile(rf"(?<![\w.-]){FIXTURES}/(images|labels\.csv)(?![\w.-])")


@dataclass(frozen=True)
class FixtureRef:
    line: int
    target: str  # fixtures/images | fixtures/labels.csv
    text: str  # the exact source text, which NAMES_FIXTURES_WITHOUT_READING pins


def _real_fixture_in(value: str) -> str | None:
    """The real fixture a string names, as `fixtures/<x>`, or None."""
    match = REAL_FIXTURE_RE.search(value.replace("\\", "/").casefold())
    return f"{FIXTURES}/{match.group(1)}" if match else None


def _joined_fixture(first: ast.expr, second: ast.expr) -> str | None:
    """The real fixture named by two adjacent path parts ("fixtures", "images"), or None."""
    if not all(isinstance(p, ast.Constant) and isinstance(p.value, str) for p in (first, second)):
        return None
    if first.value.replace("\\", "/").strip("/").casefold() != FIXTURES:
        return None
    return _real_fixture_in(f"{FIXTURES}/{second.value.lstrip('/')}")


def _docstring_ids(tree: ast.Module) -> set[int]:
    owners = [tree] + [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    return {
        id(o.body[0].value)
        for o in owners
        if o.body
        and isinstance(o.body[0], ast.Expr)
        and isinstance(o.body[0].value, ast.Constant)
        and isinstance(o.body[0].value.value, str)
    }


def scan_fixture_refs(source: str) -> list[FixtureRef]:
    """Every reference to the real fixtures in a module's code: a string constant (f-string
    parts included) or a path join of "fixtures" and "images" / "labels.csv". Docstrings are
    prose, not code, so they are not references."""
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    found: list[FixtureRef] = []

    def add(node: ast.AST, target: str) -> None:
        text = ast.get_source_segment(source, node) or ""
        found.append(FixtureRef(node.lineno, target, text))

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = [v for v in node.values if isinstance(v, ast.Constant)]
            skip.update(id(p) for p in parts)
            target = _real_fixture_in("".join(str(p.value) for p in parts))
            if target:
                add(node, target)
        elif isinstance(node, ast.Constant) and id(node) not in skip:
            value = node.value
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            if isinstance(value, str) and (target := _real_fixture_in(value)):
                add(node, target)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = node.left
            if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
                left = left.right  # root / "fixtures" / "images"
            if isinstance(left, ast.Call) and left.args:
                left = left.args[-1]  # Path("fixtures") / "images"
            if target := _joined_fixture(left, node.right):
                add(node, target)
        elif isinstance(node, ast.Call):
            for first, second in zip(node.args, node.args[1:], strict=False):
                if target := _joined_fixture(first, second):
                    add(node, target)
    return sorted(set(found), key=lambda r: (r.line, r.target, r.text))


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


def _is_fixture_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (isinstance(target, ast.Name) and target.id == "fixture") or (
        isinstance(target, ast.Attribute) and target.attr == "fixture"
    )


def scan_source(
    source: str,
    indirect_db: Iterable[str] = INDIRECT_DB,
    indirect_model: Iterable[str] = INDIRECT_MODEL,
) -> list[Violation]:
    tree = ast.parse(source)
    found: list[Violation] = []
    own_fixtures = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_is_fixture_decorator(d) for d in n.decorator_list)
    }
    http_modules: dict[str, str] = {}  # local name -> httpx | requests
    http_functions: dict[str, str] = {}  # local name -> "httpx.post"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) in HTTP_MODULES:
                    http_modules[alias.asname or _root(alias.name)] = _root(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if _root(node.module) in HTTP_MODULES:
                for alias in node.names:
                    if alias.name in HTTP_CALLS:
                        http_functions[alias.asname or alias.name] = f"{node.module}.{alias.name}"
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
                if alias.name in HTTP_CALLS and _root(node.module) in HTTP_MODULES:
                    add("http", node, f"imports the request function {node.module}.{alias.name}")
        elif isinstance(node, ast.Call):
            receiver, name = _call_name(node)
            if name in DYNAMIC_IMPORTS and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    check_dotted(first.value, node)
            if name in DB_CALLS:
                add("db", node, f"calls {name}()")
            elif name in MODEL_CALLS:
                add("model", node, f"calls {name}()")
            elif receiver in http_modules and name in HTTP_CALLS:
                add("http", node, f"calls {http_modules[receiver]}.{name}() (a real HTTP request)")
            elif receiver is None and name in http_functions:
                add("http", node, f"calls {http_functions[name]}() (a real HTTP request)")
            elif name == "usefixtures":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in DB_FIXTURES:
                        add("db", node, f"uses the {arg.value} fixture")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.arg in DB_FIXTURES and arg.arg not in own_fixtures:
                    add("db", node, f"requests the {arg.arg} fixture")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if OLLAMA_PORT in node.value:
                add("ollama", node, "names the Ollama port")
    return sorted(set(found), key=lambda v: (v.line, v.kind, v.what))


def fix_for(rel: Path, kind: str) -> str:
    """The move, or the TIER_BY_DIR line, that puts the module in its right tier."""
    if kind == "http":
        return FAKE_TRANSPORT_FIX
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
        ("import torch\n", "model"),
        ("from transformers import AutoModel\n", "model"),
        ("def f(m):\n    m.from_pretrained('x')\n", "model"),
        ("import ollama\n", "ollama"),
        ("import httpx\nhttpx.post('http://x')\n", "http"),
        ("import requests\nrequests.get('http://x')\n", "http"),
        ("import httpx as h\nh.post('http://x')\n", "http"),
        ("import requests as r\nr.get('http://x')\n", "http"),
        ("from httpx import post\n", "http"),
        ("from requests import get as fetch\nfetch('http://x')\n", "http"),
        ("import importlib\nimportlib.import_module('psycopg')\n", "db"),
        ("from importlib import import_module\nimport_module('torch.nn')\n", "model"),
        ("__import__('ollama')\n", "ollama"),
        ("async def test_a(db):\n    pass\n", "db"),
        ("def db():\n    return 1\n\ndef test_a(db):\n    pass\n", "db"),
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
        "def test_a(monkeypatch):\n    monkeypatch.setenv('DB_DSN', 'x')\n",
        "import importlib\nimportlib.import_module('json')\nimportlib.import_module(name)\n",
        "import httpx\nr = httpx.Response(200)\nh = httpx.MockTransport(lambda q: r)\n",
        "import pytest\n\n@pytest.fixture\nasync def db():\n    return 1\n"
        "\nasync def test_a(db):\n    pass\n",
    ],
)
def test_scanner_passes_clean_modules(source: str) -> None:
    assert scan_source(source) == []


F = FIXTURES  # synthetic sources below name the fixtures without this module doing so


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (f"P = '{F}/images'\n", "images"),
        (f"P = '/app/{F}/images/'\n", "images"),
        (f"P = r'{F}\\images'\n", "images"),
        (f"P = '{F.upper()}/Images'\n", "images"),
        (f"P = b'{F}/images'\n", "images"),
        (f"P = '{F}/labels.csv'\n", "labels"),
        (f"P = f'{{root}}/{F}/images'\n", "images"),
        (f"P = f'{{root}}/{F}/labels.csv'\n", "labels"),
        (f"P = root / '{F}' / 'images'\n", "images"),
        (f"P = root / '{F}' / 'images' / 'a.png'\n", "images"),
        (f"P = root / '{F}' / 'labels.csv'\n", "labels"),
        (f"P = Path('{F}') / 'images'\n", "images"),
        (f"P = Path(root, '{F}', 'images')\n", "images"),
        (f"P = os.path.join(root, '{F}', 'labels.csv')\n", "labels"),
        (f"P = root.joinpath('{F}', 'images')\n", "images"),
        (f"def test_a():\n    open(REPO / '{F}' / 'labels.csv')\n", "labels"),
    ],
)
def test_fixture_scanner_flags_each_reference(source: str, target: str) -> None:
    found = scan_fixture_refs(source)
    assert [r.target for r in found] == [REAL_FIXTURES[target]]
    assert found[0].line == source.count("\n")  # each reference is on the last line


@pytest.mark.parametrize(
    "source",
    [
        "def test_a(tmp_path):\n    (tmp_path / 'images' / 'a.png').write_bytes(b'')\n",
        f"def test_a(tmp_path):\n    d = tmp_path / '{F}'\n",
        f"P = '{F}'\nQ = 'images'\n",
        f"P = '{F}/labels.example.csv'\n",
        f"P = root / '{F}' / 'labels.example.csv'\n",
        f"P = '{F}/images_synthetic'\n",
        f"P = 'my{F}/images'\n",
        f"'''Reads {F}/images only in the gate tier.'''\n",
        f"def test_a():\n    '''Not {F}/labels.csv.'''\n",
        f"P = root / 'images' / '{F}'\n",
    ],
)
def test_fixture_scanner_passes_clean_modules(source: str) -> None:
    assert scan_fixture_refs(source) == []


def test_fixture_scanner_keeps_the_exact_source_text() -> None:
    source = f"A = sandbox['wt'] / '{F}' / 'images'\nB = f'x={{m}}/{F}/images'\n"
    assert [(r.line, r.text) for r in scan_fixture_refs(source)] == [
        (1, f"sandbox['wt'] / '{F}' / 'images'"),
        (2, f"f'x={{m}}/{F}/images'"),
    ]


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
