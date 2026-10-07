"""CLI-002.1: `classifier dry-run [--csv]` (the acceptance test).

Synthetic images only, generated under `tmp_path`. The command runs `run`, which commits, so
the module has its own migrated schema (see schema_support).
"""

import csv
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli.dry_run_report import COLUMNS
from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema

REAL_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"
SOURCE_NAMES = ("alpha.png", "bravo.png", "alpha-copy.png", "notes.txt")


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    with migrated_schema(require_db_dsn()) as dsn:
        yield dsn


@pytest.fixture(autouse=True)
def clean_ledger(schema_dsn: str) -> None:
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("truncate files")


def _setup(tmp_path: Path, dsn: str, *, results: str = "results") -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    first = source / "alpha.png"
    Image.new("RGB", (8, 6), (10, 20, 30)).save(first)
    Image.new("RGB", (8, 6), (200, 20, 30)).save(source / "bravo.png")
    (source / "alpha-copy.png").write_bytes(first.read_bytes())
    (source / "notes.txt").write_text("not an image")
    data = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    results_root = tmp_path / results
    data["paths"] = {"source_root": str(source), "results_root": str(results_root)}
    data["db"] = {"dsn": dsn}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    return source, results_root, config


def _invoke(config: Path, *extra: str):
    return CliRunner().invoke(app, ["dry-run", "--config", str(config), *extra])


def _tree(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


def _ledger_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute("select count(*) from files").fetchone()[0]


def test_prints_the_run_counts_without_names(tmp_path: Path, schema_dsn: str) -> None:
    _, _, config = _setup(tmp_path, schema_dsn)
    result = _invoke(config)
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "new: 2" in out
    assert "skipped-known: 0" in out
    assert "skipped-unreadable: 1" in out
    assert "duplicates: 1" in out
    assert "total: 4" in out
    assert "ledger skipped, " in out and out.count("ledger skipped, ") == 1
    assert not any(name in out for name in SOURCE_NAMES)
    assert "/source" not in out


def test_csv_lists_the_ledger_rows_by_path(tmp_path: Path, schema_dsn: str) -> None:
    source, results, config = _setup(tmp_path, schema_dsn)
    result = _invoke(config, "--csv")
    assert result.exit_code == 0, result.output
    reports = list((results / "reports").glob("dry-run-*.csv"))
    assert len(reports) == 1
    assert reports[0].name in result.stdout
    with reports[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == COLUMNS
    body = [dict(zip(COLUMNS, row, strict=True)) for row in rows[1:]]
    assert len(body) == 3  # one row per source_hash: the byte-identical copy is not a row
    paths = [row["source_path"] for row in body]
    assert paths == sorted(paths)
    assert all(Path(p).parent == source for p in paths)
    assert sorted(row["status"] for row in body) == ["queued", "queued", "skipped"]
    skipped = next(row for row in body if row["status"] == "skipped")
    assert skipped["reason"]
    assert all(row["proposed_output"] == "" for row in body)
    assert all(row["short_hash"] == row["source_hash"][:8] for row in body)


def test_writes_only_reports_under_results_and_nothing_under_source(
    tmp_path: Path, schema_dsn: str
) -> None:
    source, results, config = _setup(tmp_path, schema_dsn)
    before = _tree(source)
    assert _invoke(config, "--csv").exit_code == 0
    assert _tree(source) == before
    assert [p.name for p in results.iterdir()] == ["reports"]


def test_without_csv_nothing_is_written_to_results(tmp_path: Path, schema_dsn: str) -> None:
    _, results, config = _setup(tmp_path, schema_dsn)
    assert _invoke(config).exit_code == 0
    assert not results.exists()


def test_second_run_reports_everything_known_and_adds_no_rows(
    tmp_path: Path, schema_dsn: str
) -> None:
    _, _, config = _setup(tmp_path, schema_dsn)
    assert _invoke(config).exit_code == 0
    rows = _ledger_count(schema_dsn)
    second = _invoke(config)
    assert second.exit_code == 0, second.output
    assert "new: 0" in second.stdout
    assert "skipped-known: 4" in second.stdout
    assert _ledger_count(schema_dsn) == rows == 3


def test_nested_roots_fail_the_root_check(tmp_path: Path, schema_dsn: str) -> None:
    source, _, config = _setup(tmp_path, schema_dsn)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["paths"]["results_root"] = str(source / "results")
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config, "--csv")
    assert result.exit_code != 0
    assert "R-FOP-9" in result.output
    assert not (source / "results").exists()
    assert _ledger_count(schema_dsn) == 0


def test_missing_config_exits_non_zero(tmp_path: Path) -> None:
    result = _invoke(tmp_path / "absent.yaml")
    assert result.exit_code != 0
    assert "config file not found" in result.output


def test_csv_lists_only_rows_under_the_scanned_root(tmp_path: Path, schema_dsn: str) -> None:
    source, results, config = _setup(tmp_path, schema_dsn)
    sibling = str(tmp_path / "source2" / "x.png")  # same prefix as `source`, not under it
    other = str(tmp_path / "elsewhere" / "y.png")
    with psycopg.connect(schema_dsn) as conn:
        for digest, path in (("c" * 64, sibling), ("d" * 64, other)):
            conn.execute(
                "insert into files"
                " (source_hash, short_hash, source_path, source_mtime, ext, status)"
                " values (%s, %s, %s, now(), 'png', 'queued')",
                (digest, digest[:8], path),
            )
    assert _invoke(config, "--csv").exit_code == 0
    (report,) = (results / "reports").glob("dry-run-*.csv")
    with report.open(encoding="utf-8", newline="") as handle:
        paths = [row["source_path"] for row in csv.DictReader(handle)]
    assert len(paths) == 3
    assert all(Path(p).parent == source for p in paths)
    assert sibling not in paths and other not in paths


def test_validation_error_exits_2_without_echoing_values(tmp_path: Path, schema_dsn: str) -> None:
    _, _, config = _setup(tmp_path, schema_dsn)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["thumbs"]["size"] = "SECRET-VALUE-123"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config)
    assert result.exit_code == 2
    assert "thumbs.size" in result.output
    assert "SECRET-VALUE-123" not in result.output
    assert "Traceback" not in result.output


def test_database_error_exits_non_zero_without_echoing_the_dsn(tmp_path: Path) -> None:
    _, _, config = _setup(tmp_path, "postgresql://user:hunter2@127.0.0.1:1/db?connect_timeout=2")
    result = _invoke(config)
    assert result.exit_code == 1
    assert "database error" in result.output
    assert "hunter2" not in result.output
    assert "127.0.0.1" not in result.output
