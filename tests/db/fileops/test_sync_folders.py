"""FOP-002.2 acceptance: `sync_folders` and `classifier categories sync-folders`.

R-CLS-7, R-FOP-9, FOP-002.D3 (what is made), FOP-002.D4 (the plan is checked first). Every
directory lives under `tmp_path`; the real source and results roots are never named. Category
names and folders are synthetic coinages.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from classifier.cli import app
from classifier.config import Config, PathsConfig, load_config
from classifier.db.url import to_sqlalchemy_url
from classifier.fileops import folders as folders_module
from classifier.fileops.folders import FiledPair, FolderSyncError, plan_folders, sync_folders
from classifier.models.classify_rules import CategoryRule
from tests.db.db_support import require_db_dsn

ROOT = Path(__file__).resolve().parents[3]
INI = ROOT / "classifier" / "db" / "alembic.ini"
CONFIG = ROOT / "config.yaml"
runner = CliRunner()


def _config() -> Config:
    return load_config(CONFIG)


def _rule(id: int, axis: str, name: str, folder: str, parent_id: int | None = None) -> CategoryRule:
    return CategoryRule(id, axis, name, folder, None, "any", parent_id)


UNSORTED_RULE = _rule(1, "format", "unsorted", "Unsorted")
RULES = [
    UNSORTED_RULE,
    _rule(2, "format", "qorvex-shots", "Qorvex Shots"),
    _rule(3, "format", "zhyndel-art", "Zhyndel Art"),
    _rule(4, "topic", "Plimbo", "Plimbo"),
    _rule(5, "topic", "Plimbo Racing", "Racing", parent_id=4),
]


@pytest.fixture
def roots(tmp_path: Path) -> tuple[PathsConfig, Path, Path]:
    source = tmp_path / "src"
    results = tmp_path / "res"
    source.mkdir()
    results.mkdir()
    return PathsConfig(source_root=str(source), results_root=str(results)), source, results


def _tree(results: Path) -> set[str]:
    return {p.relative_to(results).as_posix() for p in results.rglob("*")}


BASE_TREE = {
    ".work",
    "reports",
    "General",
    "General/Qorvex Shots",
    "General/Zhyndel Art",
    "Unsorted",
    "Adult",
    "Adult/General",
    "Adult/General/Qorvex Shots",
    "Adult/General/Zhyndel Art",
    "Adult/Unsorted",
}


def test_creates_the_base_tree_and_nothing_for_unfiled_rows(roots) -> None:
    paths, _source, results = roots
    config = _config()
    made = sync_folders(paths, RULES, [], config.folders, config.nsfw)
    assert _tree(results) == BASE_TREE
    assert made.created == len(BASE_TREE)
    assert not (results / "General" / "Qorvex Shots" / "Animated").exists()  # never ahead of time


def test_filed_rows_add_topic_format_pairs_in_both_branches(roots) -> None:
    paths, _source, results = roots
    config = _config()
    filed = [
        FiledPair("Plimbo", "qorvex-shots", "safe"),
        FiledPair("Plimbo Racing", "zhyndel-art", "nsfw"),  # nested topic: D2
        FiledPair(None, "qorvex-shots", None),  # no topic: General, already planned
        FiledPair("Removed Topic", "qorvex-shots", "safe"),  # category since removed: skipped
    ]
    sync_folders(paths, RULES, filed, config.folders, config.nsfw)
    assert _tree(results) - BASE_TREE == {
        "Plimbo",
        "Plimbo/Qorvex Shots",
        "Adult/Plimbo",
        "Adult/Plimbo/Racing",
        "Adult/Plimbo/Racing/Zhyndel Art",
    }


def test_second_run_creates_nothing(roots) -> None:
    paths, _source, results = roots
    config = _config()
    sync_folders(paths, RULES, [], config.folders, config.nsfw)
    before = _tree(results)
    assert sync_folders(paths, RULES, [], config.folders, config.nsfw).created == 0
    assert _tree(results) == before


def test_an_existing_folder_is_not_counted(roots) -> None:
    paths, _source, results = roots
    config = _config()
    (results / "General").mkdir()
    made = sync_folders(paths, RULES, [], config.folders, config.nsfw)
    assert made.created == len(BASE_TREE) - 1


def _refused(call) -> FolderSyncError:
    with pytest.raises(FolderSyncError) as info:
        call()
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    return info.value


def test_separate_mode_fails_fast_naming_the_key(roots) -> None:
    paths, _source, results = roots
    config = _config()
    nsfw = config.nsfw.model_copy(update={"mode": "separate"})
    error = _refused(lambda: sync_folders(paths, RULES, [], config.folders, nsfw))
    assert "nsfw.mode" in str(error)
    assert _tree(results) == set()


def test_other_layout_fails_fast(roots) -> None:
    paths, _source, results = roots
    config = _config()
    folders = config.folders.model_copy(update={"layout": "{format}/{topic}"})
    error = _refused(lambda: sync_folders(paths, RULES, [], folders, config.nsfw))
    assert "folders.layout" in str(error)
    assert _tree(results) == set()


def test_case_only_collision_among_planned_siblings_names_categories(roots) -> None:
    paths, _source, results = roots
    config = _config()
    rules = [*RULES, _rule(6, "topic", "Qorvex Topic", "plimbo")]
    filed = [
        FiledPair("Plimbo", "qorvex-shots", "safe"),
        FiledPair("Qorvex Topic", "qorvex-shots", "safe"),
    ]
    error = _refused(lambda: sync_folders(paths, rules, filed, config.folders, config.nsfw))
    text = str(error)
    assert "Plimbo" in text and "Qorvex Topic" in text
    assert str(results) not in text and str(paths.source_root) not in text
    assert _tree(results) == set()


def test_a_topic_folder_equal_to_a_reserved_folder_is_refused(roots) -> None:
    paths, _source, results = roots
    config = _config()
    rules = [*RULES, _rule(6, "topic", "Qorvex Topic", "Reports")]
    filed = [FiledPair("Qorvex Topic", "qorvex-shots", "safe")]
    error = _refused(lambda: sync_folders(paths, rules, filed, config.folders, config.nsfw))
    assert "Qorvex Topic" in str(error)
    assert _tree(results) == set()


def test_case_only_collision_with_a_folder_on_disk_creates_nothing(roots) -> None:
    paths, _source, results = roots
    config = _config()
    (results / "general").mkdir()
    error = _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    text = str(error)
    assert "folders.no_topic" in text
    assert str(results) not in text and "general" not in text.replace("General", "")
    assert _tree(results) == {"general"}


def test_a_symlinked_parent_is_refused(roots, tmp_path: Path) -> None:
    paths, _source, results = roots
    config = _config()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        (results / "General").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.fail("the test needs to create a symlink under tmp_path")
    error = _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert str(tmp_path) not in str(error)
    assert list(elsewhere.iterdir()) == []
    assert _tree(results) == {"General"}


def test_a_file_where_a_folder_is_planned_is_refused(roots) -> None:
    paths, _source, results = roots
    config = _config()
    (results / "General").write_text("x")
    _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert _tree(results) == {"General"}


def test_results_root_inside_or_around_source_root_is_refused(tmp_path: Path) -> None:
    config = _config()
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    for source, results in ((outer, inner), (inner, outer), (outer, outer)):
        paths = PathsConfig(source_root=str(source), results_root=str(results))
        _refused(lambda paths=paths: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert list(inner.iterdir()) == []


def test_results_root_that_links_into_source_root_is_refused(tmp_path: Path) -> None:
    config = _config()
    source = tmp_path / "src"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source, target_is_directory=True)
    paths = PathsConfig(source_root=str(source), results_root=str(link))
    _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert list(source.iterdir()) == []


def test_missing_or_relative_roots_are_refused(tmp_path: Path) -> None:
    config = _config()
    missing = PathsConfig(source_root=str(tmp_path / "s"), results_root=str(tmp_path / "nope"))
    _refused(lambda: sync_folders(missing, RULES, [], config.folders, config.nsfw))
    relative = PathsConfig(source_root="src", results_root="res")
    _refused(lambda: sync_folders(relative, RULES, [], config.folders, config.nsfw))


def test_os_errors_become_fixed_unchained_text(roots, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, _source, results = roots
    config = _config()
    secret = "Qorvex-Secret-Dir"

    def listing(_path):
        raise OSError(secret)

    monkeypatch.setattr(folders_module.os, "listdir", listing)
    error = _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert secret not in str(error)
    monkeypatch.undo()

    def make(self, *args, **kwargs):
        raise OSError(secret)

    monkeypatch.setattr(Path, "mkdir", make)
    error = _refused(lambda: sync_folders(paths, RULES, [], config.folders, config.nsfw))
    assert secret not in str(error)
    assert _tree(results) == set()


def test_reprs_hide_names_and_paths() -> None:
    config = _config()
    secret = "Zhyndel-Secret-Name"
    rules = [UNSORTED_RULE, _rule(2, "format", secret, secret), _rule(3, "topic", secret, secret)]
    pair = FiledPair(secret, secret, "safe")
    plan = plan_folders(rules, [pair], config.folders, config.nsfw)
    for value in (pair, plan):
        assert secret not in repr(value) and secret not in str(value)


def test_plan_has_no_file_system_and_no_animated_folder() -> None:
    config = _config()
    plan = plan_folders(
        RULES, [FiledPair("Plimbo", "qorvex-shots", "safe")], config.folders, config.nsfw
    )
    assert ("Plimbo", "Qorvex Shots") in plan.folders
    assert not any("Animated" in part for path in plan.folders for part in path)
    assert not any(part == "unsorted" for path in plan.folders for part in path)


# --- the command ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    name = f"sync_{uuid.uuid4().hex[:12]}"
    base = require_db_dsn()
    url = make_url(to_sqlalchemy_url(base)).update_query_dict(
        {"options": f"-c search_path={name},public"}
    )
    options = quote(f"-c search_path={name},public", safe="")
    dsn = f"{base}{'&' if '?' in base else '?'}options={options}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'create schema "{name}"')
        try:
            cfg = AlembicConfig(str(INI))
            cfg.set_main_option(
                "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
            )
            command.upgrade(cfg, "head")
            yield dsn
        finally:
            admin.execute(f'drop schema "{name}" cascade')


def _config_file(tmp_path: Path, source: Path, results: Path) -> str:
    text = CONFIG.read_text(encoding="utf-8")
    text = text.replace("source_root: /source", f"source_root: {source.as_posix()}", 1)
    text = text.replace("results_root: /results", f"results_root: {results.as_posix()}", 1)
    file = tmp_path / "config.yaml"
    file.write_text(text, encoding="utf-8")
    return str(file)


def _sync(schema_dsn: str, monkeypatch: pytest.MonkeyPatch, config_file: str):
    monkeypatch.setenv("DB_DSN", schema_dsn)
    return runner.invoke(app, ["categories", "sync-folders", "--config", config_file])


def test_command_creates_the_seeded_tree_and_echoes_only_a_count(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch, roots, tmp_path: Path
) -> None:
    _paths, source, results = roots
    config_file = _config_file(tmp_path, source, results)
    result = _sync(schema_dsn, monkeypatch, config_file)
    assert result.exit_code == 0, result.output
    tree = _tree(results)
    assert result.output.strip() == f"created {len(tree)} folders"
    assert {".work", "reports", "General", "Unsorted", "Adult/General", "Adult/Unsorted"} <= tree
    assert "General/Photos" in tree and "Adult/General/Photos" in tree
    assert not any(p.endswith("/Animated") for p in tree)
    again = _sync(schema_dsn, monkeypatch, config_file)
    assert again.exit_code == 0 and again.output.strip() == "created 0 folders"
    assert os.listdir(source) == []  # the source is never touched


def test_command_refuses_a_disk_clash_with_category_names_and_no_path(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch, roots, tmp_path: Path
) -> None:
    _paths, source, results = roots
    (results / "unsorted").mkdir()
    result = _sync(schema_dsn, monkeypatch, _config_file(tmp_path, source, results))
    assert result.exit_code == 2
    assert result.output.startswith("error: ")
    assert str(results) not in result.output and str(tmp_path) not in result.output
    assert _tree(results) == {"unsorted"}


def test_command_fails_fast_on_separate_mode(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch, roots, tmp_path: Path
) -> None:
    _paths, source, results = roots
    config_file = Path(_config_file(tmp_path, source, results))
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace("mode: mirror", "mode: separate", 1),
        encoding="utf-8",
    )
    result = _sync(schema_dsn, monkeypatch, str(config_file))
    assert result.exit_code == 2
    assert "nsfw.mode" in result.output
    assert _tree(results) == set()
