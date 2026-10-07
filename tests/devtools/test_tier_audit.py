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

TST-004: only the `gate` and `gpu` tiers read the real fixtures (CLAUDE.md §3, RUN-009). Every
other module, conftest.py and helper modules included, fails if its code names
fixtures/images or fixtures/labels.csv: a string constant (f-string parts included) or a path
join. Synthetic data under tmp_path stays legal, and so does fixtures/labels.example.csv. A
module that names the path without reading it is pinned in NAMES_FIXTURES_WITHOUT_READING
(TST-004.D1). The audit never opens the fixtures.

Named gaps (TST-004): a path built from variables (`root / FIX / IMAGES`) or by runtime
concatenation, and a path read from an env var or config (such as FIXTURE_IMAGES), are not
detected.
"""

import ast
import importlib.util
import re
from collections import Counter
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
TIER_FOR = {"db": "db", "model": "gpu", "ollama": "gpu", "fixtures": "gpu"}
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
    col: int = 0  # keeps two identical references on one line apart


@dataclass(frozen=True)
class Exemption:
    reason: str
    texts: tuple[str, ...]  # each reference's exact source text, once per occurrence


def _pin(reason: str, *texts: str) -> Exemption:
    # `{F}` stands for the fixtures folder, so this registry does not trip its own scan.
    return Exemption(reason, tuple(t.replace("{F}", FIXTURES) for t in texts))


# TST-004.D1: modules that name the real fixtures without reading them, each pinned to the exact
# references it may make. A new reference in a listed module still fails, and so does a pin the
# module no longer has. QA reviews every entry; there is no per-line escape hatch.
NAMES_FIXTURES_WITHOUT_READING: dict[str, Exemption] = {
    "unit/gate/test_gate_1_verdict.py": _pin(
        "matches the text of gate 1's error for a missing fixtures folder",
        'r"{F}/images/ is missing"',
    ),
    "unit/runtime/test_fixtures_mount.py": _pin(
        "RUN-009: asserts the compose mount and make init's output, and builds a tmp sandbox repo",
        '"/app/{F}/images"',
        '"${FIXTURE_IMAGES:-./{F}/images}"',
        '".env\\nsanitize.yaml\\n{F}/labels.csv\\nwt/\\n"',
        'repo / "{F}" / "labels.csv"',
        'f"FIXTURE_IMAGES={Path(main).parent.as_posix()}/{F}/images"',
        'sandbox["wt"] / "{F}" / "labels.csv"',
        'sandbox["repo"] / "{F}" / "labels.csv"',
        'sandbox["wt"] / "{F}" / "images"',
        'repo / "{F}" / "labels.csv"',
    ),
}


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
        found.append(FixtureRef(node.lineno, target, text, node.col_offset))

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
    return sorted(found, key=lambda r: (r.line, r.col))


def _load_conftest():
    spec = importlib.util.spec_from_file_location("tier_audit_conftest", TESTS / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TIER_DIRS = frozenset(_load_conftest().TIER_BY_DIR)
FIXTURE_TIERS = {"gate", "gpu"}  # the only tiers that read the real fixtures (CLAUDE.md §3)


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
    if len(parts) > 1 and parts[0] in TIER_DIRS:
        move = f"move it to tests/{tier}/{'/'.join(parts[1:])}"
    elif len(parts) > 1:
        move = f'add `"{parts[0]}": "{tier}",` to TIER_BY_DIR in tests/conftest.py'
    else:
        move = f"move it to tests/{tier}/{rel.name}"
    return f"generate synthetic data under tmp_path, or {move}" if kind == "fixtures" else move


def _tier(conftest, root: Path, path: Path) -> str:
    if root == TESTS:
        return conftest.tier_of(path)
    parts = path.relative_to(root).parts  # a synthetic tree, laid out like tests/
    return conftest.TIER_BY_DIR.get(parts[0], "unit") if len(parts) > 1 else "unit"


def _fixture_messages(
    rel: str, tier: str, refs: list[FixtureRef], pinned: Exemption | None
) -> list[str]:
    """One message per unpinned reference, and one per pinned text the module no longer has."""
    allowed = Counter(pinned.texts if pinned else ())
    messages = []
    for r in refs:
        if allowed[r.text] > 0:
            allowed[r.text] -= 1
            continue
        messages.append(
            f"tests/{rel}:{r.line} is in the {tier} tier but references the real fixtures "
            f"({r.target}): only the gate and gpu tiers read them; "
            f"{fix_for(Path(rel), 'fixtures')}. If it only names the path and never reads it, "
            "ask QA to pin it in NAMES_FIXTURES_WITHOUT_READING (TST-004.D1)"
        )
    messages += [
        f"NAMES_FIXTURES_WITHOUT_READING pins {text!r} in tests/{rel}, which no longer has it: "
        "remove the stale pin"
        for text in sorted(allowed.elements())
    ]
    return messages


def audit(root: Path = TESTS, exempt: dict[str, Exemption] | None = None) -> list[str]:
    """Every tier violation under `root`. The fixtures registry applies to the real tests/
    unless `exempt` is given, so a synthetic tree is audited without it."""
    if exempt is None:
        exempt = NAMES_FIXTURES_WITHOUT_READING if root == TESTS else {}
    conftest = _load_conftest()
    messages: list[str] = []
    scanned: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if ".pytest_cache" in path.parts:
            continue
        tier, rel = _tier(conftest, root, path), path.relative_to(root)
        source = path.read_text(encoding="utf-8")
        if tier not in FIXTURE_TIERS:  # TST-004: conftests and helpers too
            scanned.add(rel.as_posix())
            refs = scan_fixture_refs(source)
            messages += _fixture_messages(rel.as_posix(), tier, refs, exempt.get(rel.as_posix()))
        if tier != "unit" or path.name in {"conftest.py", "__init__.py"}:
            continue
        for v in scan_source(source):
            messages.append(
                f"tests/{rel.as_posix()}:{v.line} is a unit test but {v.what} "
                f"({v.kind} tier work): {fix_for(rel, v.kind)}"
            )
    messages += [
        f"NAMES_FIXTURES_WITHOUT_READING exempts tests/{rel}, which the fixtures audit does not "
        "scan (missing, or in the gate or gpu tier): remove the stale entry"
        for rel in sorted(set(exempt) - scanned)
    ]
    return messages


def test_every_test_module_stays_in_its_tier() -> None:
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


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, source in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(source, encoding="utf-8")
    return root


IMAGES_REF = f"P = '{F}/images'\n"
LABELS_JOIN = f"def f(repo):\n    return repo / '{F}' / 'labels.csv'\n"


def test_audit_flags_the_real_fixtures_outside_gate_and_gpu(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "integration/test_bad.py": IMAGES_REF,
            "integration/conftest.py": LABELS_JOIN,
            "db/helper_support.py": IMAGES_REF,
            "unit/__init__.py": IMAGES_REF,
            "test_top.py": IMAGES_REF,
            "gpu/test_ok.py": IMAGES_REF + LABELS_JOIN,
            "gate/test_ok.py": IMAGES_REF + LABELS_JOIN,
            "unit/test_synthetic.py": "def test_a(tmp_path):\n    (tmp_path / 'images').mkdir()\n",
        },
    )
    problems = audit(root)
    assert [p.split(" ")[0] for p in problems] == [
        "tests/db/helper_support.py:1",
        "tests/integration/conftest.py:2",
        "tests/integration/test_bad.py:1",
        "tests/test_top.py:1",
        "tests/unit/__init__.py:1",
    ]
    bad = problems[2]
    assert f"is in the integration tier but references the real fixtures ({F}/images)" in bad
    assert "generate synthetic data under tmp_path, or move it to tests/gpu/test_bad.py" in bad
    assert f"({F}/labels.csv)" in problems[1]
    assert "NAMES_FIXTURES_WITHOUT_READING (TST-004.D1)" in bad


def test_pinned_references_pass_and_a_new_one_fails(tmp_path: Path) -> None:
    pinned = {"unit/test_mount.py": Exemption("names it", (f"'{F}/images'",))}
    root = _tree(tmp_path, {"unit/test_mount.py": IMAGES_REF})
    assert audit(root, pinned) == []
    _tree(tmp_path, {"unit/test_mount.py": IMAGES_REF + IMAGES_REF + LABELS_JOIN})
    problems = audit(root, pinned)
    assert [p.split(" ")[0] for p in problems] == [
        "tests/unit/test_mount.py:2",  # the same text again: pinned once, so the copy fails
        "tests/unit/test_mount.py:4",
    ]


def test_a_pin_covers_one_occurrence_even_on_the_same_line(tmp_path: Path) -> None:
    pinned = {"unit/test_mount.py": Exemption("names it", (f"'{F}/images'",))}
    root = _tree(tmp_path, {"unit/test_mount.py": f"P, Q = '{F}/images', '{F}/images'\n"})
    assert [p.split(" ")[0] for p in audit(root, pinned)] == ["tests/unit/test_mount.py:1"]


def test_stale_pins_and_entries_fail(tmp_path: Path) -> None:
    pinned = {
        "unit/test_mount.py": Exemption("names it", (f"'{F}/images'", "'gone'")),
        "unit/test_missing.py": Exemption("gone", (f"'{F}/images'",)),
        "gpu/test_real.py": Exemption("reads them, legally", (f"'{F}/images'",)),
    }
    root = _tree(tmp_path, {"unit/test_mount.py": IMAGES_REF, "gpu/test_real.py": IMAGES_REF})
    problems = audit(root, pinned)
    assert problems == [
        "NAMES_FIXTURES_WITHOUT_READING pins \"'gone'\" in tests/unit/test_mount.py, which no "
        "longer has it: remove the stale pin",
        "NAMES_FIXTURES_WITHOUT_READING exempts tests/gpu/test_real.py, which the fixtures audit "
        "does not scan (missing, or in the gate or gpu tier): remove the stale entry",
        "NAMES_FIXTURES_WITHOUT_READING exempts tests/unit/test_missing.py, which the fixtures "
        "audit does not scan (missing, or in the gate or gpu tier): remove the stale entry",
    ]


def test_the_registry_applies_only_to_the_real_tests_tree(tmp_path: Path) -> None:
    assert audit(_tree(tmp_path, {"unit/test_ok.py": "import json\n"})) == []
    for rel, entry in NAMES_FIXTURES_WITHOUT_READING.items():
        assert entry.reason and entry.texts, rel
        assert (TESTS / rel).is_file(), rel


def test_fix_for_the_real_fixtures_offers_synthetic_data_first() -> None:
    assert fix_for(Path("integration/test_x.py"), "fixtures") == (
        "generate synthetic data under tmp_path, or move it to tests/gpu/test_x.py"
    )
    assert fix_for(Path("devtools/x.py"), "fixtures").endswith(
        'add `"devtools": "gpu",` to TIER_BY_DIR in tests/conftest.py'
    )


def test_audit_skips_modules_outside_the_unit_tier() -> None:
    conftest = _load_conftest()
    assert conftest.tier_of(TESTS / "db" / "test_db_reachable.py") == "db"
    assert conftest.tier_of(TESTS / "devtools" / "test_tier_audit.py") == "unit"
