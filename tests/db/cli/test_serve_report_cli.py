"""CLI-008 acceptance: `classifier serve` (CLI-008.1) and `classifier report` (CLI-008.2).

`serve`: `uvicorn.run` is replaced by a recorder, so no port is ever opened. The app it
receives is exercised through Starlette's TestClient on a migrated schema.
`report`: writes to a results root under tmp_path, never the real one, from a planted ledger.
Every value is synthetic.
"""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import typer
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli import report as report_module
from classifier.cli import serve as serve_module
from classifier.config import ConfigError, load_config
from classifier.models import ollama
from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema

ROOT = Path(__file__).resolve().parents[3]
CONFIG = str(ROOT / "config.yaml")
PLANT = "Qorvex"
CONFIG_FAILED = "error: the config could not be loaded; check the config file and DB_DSN"
runner = CliRunner()


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    with migrated_schema(require_db_dsn()) as dsn:
        yield dsn


@pytest.fixture
def calls(schema_dsn: str, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Point the command at the schema and record each uvicorn.run call instead of serving."""
    monkeypatch.setenv("DB_DSN", schema_dsn)
    seen: list[dict[str, Any]] = []

    def record(app_: object, **kwargs: Any) -> None:
        seen.append({"app": app_, **kwargs})

    monkeypatch.setattr(serve_module.uvicorn, "run", record)
    return seen


def _serve(*args: str):
    return runner.invoke(app, ["serve", "--config", CONFIG, *args])


def test_defaults_come_from_the_config_and_no_request_is_logged(
    calls: list[dict[str, Any]],
) -> None:
    result = _serve()
    assert result.exit_code == 0, result.output

    expected = load_config(CONFIG).api
    (call,) = calls
    assert (call["host"], call["port"]) == (expected.host, expected.port)
    assert call["access_log"] is False  # m4 item 15 (Nibble's note on #215)
    assert call["server_header"] is False
    assert call["log_config"] is None
    assert set(call) == {"app", "host", "port", "access_log", "server_header", "log_config"}
    assert result.output == f"serving on {expected.host}:{expected.port}\n"
    assert logging.getLogger("uvicorn.access").disabled  # create_app's half of item 15


def test_host_and_port_override_the_config(calls: list[dict[str, Any]]) -> None:
    result = _serve("--host", "0.0.0.0", "--port", "8123")  # RUN-019.D2's compose form
    assert result.exit_code == 0, result.output
    assert (calls[0]["host"], calls[0]["port"]) == ("0.0.0.0", 8123)


def test_the_app_is_create_apps_read_only_api(calls: list[dict[str, Any]]) -> None:
    assert _serve().exit_code == 0
    served = calls[0]["app"]
    assert isinstance(served, FastAPI)
    with TestClient(served) as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        assert isinstance(status.json(), dict)  # the StatusView shape is API-001's to test
        assert client.post("/api/status").status_code == 405  # read-only
        assert client.get("/docs").status_code == 404  # docs_url=None


@pytest.mark.parametrize("port", ["0", "65536", "-1", "http"])
def test_a_bad_port_is_refused_before_serving(calls: list[dict[str, Any]], port: str) -> None:
    result = _serve("--port", port)
    assert result.exit_code == 2
    assert calls == []


def test_no_dsn_exits_2_with_fixed_text(
    calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DB_DSN")
    result = _serve()
    assert result.exit_code == 2
    assert result.output == CONFIG_FAILED + "\n"
    assert calls == []


def _planted_config(tmp_path: Path) -> Path:
    """A --config path holding the plant, which load_config's own text would echo."""
    path = tmp_path / f"{PLANT} private" / f"{PLANT}.yaml"
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert PLANT in str(caught.value)  # proved: the raw ConfigError text carries the path
    return path


def test_a_bad_config_is_fixed_text_without_the_path(
    calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    """CLI-008.2.1: the --config path never reaches the console."""
    path = _planted_config(tmp_path)
    result = runner.invoke(app, ["serve", "--config", str(path)])
    assert result.exit_code == 2
    assert result.output == CONFIG_FAILED + "\n"
    assert PLANT not in result.output
    assert calls == []

    with pytest.raises(typer.Exit) as raised:  # called directly: unchained
        serve_module.serve(host=None, port=None, config_path=path)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_a_bind_failure_prints_fixed_text_and_hides_uvicorns_message(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uvicorn logs the OS error, address included, on uvicorn.error, then exits 1."""
    monkeypatch.setenv("DB_DSN", schema_dsn)

    def cannot_bind(app_: object, **kwargs: Any) -> None:
        logging.getLogger("uvicorn.error").error(
            "[Errno 98] error while attempting to bind on address ('%s', %d): %s",
            kwargs["host"], kwargs["port"], PLANT,
        )  # fmt: skip
        raise SystemExit(1)

    monkeypatch.setattr(serve_module.uvicorn, "run", cannot_bind)
    result = _serve("--host", "0.0.0.0", "--port", "8123")

    assert result.exit_code == 1
    assert result.output == (
        "serving on 0.0.0.0:8123\nerror: could not listen on the configured address\n"
    )
    assert PLANT not in result.output and "Errno" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # The filter is gone afterwards: other users of uvicorn.error are unaffected.
    assert not logging.getLogger("uvicorn.error").filters


def test_an_os_error_from_uvicorn_is_fixed_text(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_DSN", schema_dsn)

    def refuse(app_: object, **kwargs: Any) -> None:
        raise OSError(f"bind {PLANT}")

    monkeypatch.setattr(serve_module.uvicorn, "run", refuse)
    result = _serve()
    assert result.exit_code == 1
    assert result.output.endswith("error: could not listen on the configured address\n")
    assert PLANT not in result.output


def test_a_clean_stop_exits_0(schema_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_DSN", schema_dsn)

    def stop(app_: object, **kwargs: Any) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(serve_module.uvicorn, "run", stop)
    assert _serve().exit_code == 0


def test_a_create_app_failure_is_fixed_text(
    schema_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_DSN", schema_dsn)

    def broken(config: object) -> FastAPI:
        raise ValueError(f"{PLANT} in a value")

    monkeypatch.setattr(serve_module, "create_app", broken)
    result = _serve()
    assert result.exit_code == 2
    assert result.output == "error: the app could not start\n"


# --- CLI-008.2: classifier report -------------------------------------------------------

SANITIZED = "Brindle_one"  # a made-up sanitized stem; served as Brindle_one.png
RAW = "Zhyndel"  # a made-up raw name, in the paths only
INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, duplicate_paths, source_mtime,"
    " ext, status, original_sanitized, proposed_path, caption)"
    " values (%s, %s, %s, %s, now(), 'png', 'queued', %s, %s, %s)"
)


@pytest.fixture
def report_env(
    schema_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """A config whose roots are under tmp_path, DB_DSN at the schema, and a planted ledger."""
    monkeypatch.setenv("DB_DSN", schema_dsn)
    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    results = tmp_path / "results"
    (tmp_path / "source").mkdir()
    results.mkdir()
    data["paths"] = {"source_root": str(tmp_path / "source"), "results_root": str(results)}
    data["db"] = {"dsn": None}  # CFG-001.D2
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    caption = json.dumps({"text": f"{PLANT} {RAW} caption"})
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("truncate files, runs cascade")
        conn.execute(
            INSERT_FILE,
            (
                "a" * 64, "aaaaaaaa",
                f"/source/{PLANT} trip/{PLANT}_{RAW}.png",
                [f"/source/{RAW} copy/{RAW}_{PLANT}.png"],
                SANITIZED,
                f"/results/{PLANT}/{RAW}.png",
                caption,
            ),
        )  # fmt: skip
        conn.execute(
            INSERT_FILE,
            ("b" * 64, "bbbbbbbb", "/source/x.png", [], "<script>alert(1)</script>", None, None),
        )
    return config, results


def _report(config: Path, *extra: str):
    return runner.invoke(app, ["report", "--config", str(config), *extra])


def test_the_report_serves_sanitized_names_and_never_a_path_or_raw_name(
    report_env: tuple[Path, Path], schema_dsn: str
) -> None:
    config, results = report_env
    # Proved held first: the ledger stores the plants (DOC-004.D3).
    with psycopg.connect(schema_dsn) as conn:
        held = conn.execute(
            "select source_path, duplicate_paths, proposed_path, caption::text from files"
            " where short_hash = 'aaaaaaaa'"
        ).fetchone()
    assert all(PLANT in str(value) and RAW in str(value) for value in held)

    result = _report(config)
    assert result.exit_code == 0, result.output
    (written,) = (results / "reports").glob("report-*.html")
    assert result.output == f"report written: {written.name}\n"  # the name only, no folder
    html = written.read_text(encoding="utf-8")

    # Proved served: the sanitized names and hashes are in the report...
    assert f"{SANITIZED}.png" in html and "aaaaaaaa" in html and "bbbbbbbb" in html
    # ...and only then: no path, no raw name, no caption, no live HTML from a name.
    for absent in (PLANT, RAW, "/source/", "/results/", "<script>alert(1)"):
        assert absent not in html
    # CLI-008.2.1: self-contained, no outbound URL and no thumbnail (API-001.D6, m4 item 5).
    # A bare "http" would match the CSP's <meta http-equiv>, so the URL forms are checked.
    lowered = html.lower()
    for absent in ("<img", "http:", "https:", '="//', "src=", "url(", "/thumbs/"):
        assert absent not in lowered
    assert 'http-equiv="content-security-policy"' in lowered  # the one "http", proved benign
    assert "&lt;script&gt;" in html
    assert "n/a" in html  # CLI-008.D1: no Ollama probe, the models stay n/a


def test_the_report_makes_no_ollama_call(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("report built an Ollama client")

    monkeypatch.setattr(ollama.OllamaClient, "__init__", refuse)
    monkeypatch.setattr(ollama.OllamaClient, "from_env", refuse, raising=False)
    result = _report(report_env[0])
    assert result.exit_code == 0, result.output


class _Frozen(datetime):
    @classmethod
    def now(cls, tz: object = None) -> "_Frozen":
        return cls(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_the_default_name_is_the_utc_stamp_and_a_clash_gets_a_suffix(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_module, "datetime", _Frozen)
    config, results = report_env
    folder = results / "reports"
    first = _report(config)
    first_bytes = (folder / "report-20260102T030405Z.html").read_bytes()
    second = _report(config)

    assert first.output == "report written: report-20260102T030405Z.html\n"
    assert second.output == "report written: report-20260102T030405Z-1.html\n"
    assert (folder / "report-20260102T030405Z.html").read_bytes() == first_bytes
    assert sorted(p.name for p in folder.iterdir()) == [
        "report-20260102T030405Z-1.html", "report-20260102T030405Z.html",
    ]  # fmt: skip


def test_out_writes_a_new_file_and_refuses_an_existing_one(
    report_env: tuple[Path, Path], tmp_path: Path
) -> None:
    config, results = report_env
    target = tmp_path / "mine.html"
    made = _report(config, "--out", str(target))
    assert made.exit_code == 0, made.output
    assert made.output == "report written: mine.html\n"
    assert "aaaaaaaa" in target.read_text(encoding="utf-8")
    assert not (results / "reports").exists()  # --out replaces the default target

    target.write_bytes(b"keep me")
    refused = _report(config, "--out", str(target))
    assert refused.exit_code == 2
    assert refused.output == "error: --out already exists; choose a new file\n"
    assert target.read_bytes() == b"keep me"


def test_an_unwritable_folder_is_fixed_text(report_env: tuple[Path, Path]) -> None:
    config, results = report_env
    (results / "reports").write_text("a file where the folder goes")
    result = _report(config)
    assert result.exit_code == 1
    assert result.output == "error: could not write the report\n"


def test_a_database_error_is_fixed_text_without_the_dsn(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_DSN", "postgresql://user:hunter2@127.0.0.1:1/db?connect_timeout=2")
    config, results = report_env
    result = _report(config)
    assert result.exit_code == 1
    assert result.output == "error: database error, see the db service logs\n"
    assert not (results / "reports").exists()


def test_report_with_no_dsn_exits_2(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DB_DSN")
    result = _report(report_env[0])
    assert result.exit_code == 2
    assert result.output == CONFIG_FAILED + "\n"


# --- CLI-008.2.1: round 1 on PR #240 ------------------------------------------------------


def _direct(config: Path | None, out: Path | None = None) -> typer.Exit:
    """Call the command function itself and return the Exit it raises."""
    with pytest.raises(typer.Exit) as raised:
        report_module.report(out=out, config_path=config)
    return raised.value


def _unchained(exit_: typer.Exit) -> None:
    assert exit_.__cause__ is None and exit_.__context__ is None


def test_report_a_bad_config_is_fixed_text_without_the_path(tmp_path: Path) -> None:
    path = _planted_config(tmp_path)
    result = _report(path)
    assert result.exit_code == 2
    assert result.output == CONFIG_FAILED + "\n"
    assert PLANT not in result.output
    _unchained(_direct(path))


def test_the_report_reads_one_repeatable_read_read_only_snapshot(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []
    real = report_module.build_status

    def spy(conn, **kwargs):  # noqa: ANN001, ANN003, ANN202 — a test double
        row = conn.exec_driver_sql(
            "select current_setting('transaction_isolation'),"
            " current_setting('transaction_read_only')"
        ).one()
        seen.append(tuple(row))
        return real(conn, **kwargs)

    monkeypatch.setattr(report_module, "build_status", spy)
    assert _report(report_env[0]).exit_code == 0
    assert seen == [("repeatable read", "on")]


def test_report_a_database_error_is_unchained(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_DSN", "postgresql://user:hunter2@127.0.0.1:1/db?connect_timeout=2")
    _unchained(_direct(report_env[0]))


def test_report_a_write_failure_is_unchained(report_env: tuple[Path, Path]) -> None:
    config, results = report_env
    (results / "reports").write_text("a file where the folder goes")
    _unchained(_direct(config))


def test_report_an_existing_out_is_unchained(report_env: tuple[Path, Path], tmp_path: Path) -> None:
    target = tmp_path / "taken.html"
    target.write_bytes(b"keep me")
    exit_ = _direct(report_env[0], target)
    assert exit_.exit_code == 2
    _unchained(exit_)
    assert target.read_bytes() == b"keep me"


def test_any_render_failure_is_fixed_text(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-008.2.1: the broad catch in report(); an unexpected message never reaches the console."""

    def broken(status: object, files: object) -> str:
        raise RuntimeError(f"{PLANT} in a message")

    monkeypatch.setattr(report_module, "render_report", broken)
    config, results = report_env
    result = _report(config)
    assert result.exit_code == 1
    assert result.output == "error: database error, see the db service logs\n"
    assert PLANT not in result.output
    assert not (results / "reports").exists()
    _unchained(_direct(config))


def test_an_encode_failure_leaves_no_file_and_no_folder(
    report_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(report_module, "render_report", lambda status, files: "ok \ud800")
    config, results = report_env
    result = _report(config)
    assert result.exit_code == 1
    assert result.output == "error: could not write the report\n"
    assert not (results / "reports").exists()  # encoded before any mkdir or open
    target = tmp_path / "never.html"
    exit_ = _direct(config, target)
    _unchained(exit_)
    assert not target.exists()
