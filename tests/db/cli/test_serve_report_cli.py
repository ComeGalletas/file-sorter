"""CLI-008.1 acceptance: `classifier serve` runs uvicorn on `create_app` with no request log.

`uvicorn.run` is replaced by a recorder, so no port is ever opened. The app it receives is
exercised through Starlette's TestClient on a migrated schema. Every value is synthetic.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli import serve as serve_module
from classifier.config import load_config
from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema

ROOT = Path(__file__).resolve().parents[3]
CONFIG = str(ROOT / "config.yaml")
PLANT = "Qorvex"
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
    assert result.output == "error: no database DSN: set DB_DSN\n"  # load_config's fixed text
    assert calls == []


def test_a_missing_config_exits_2(calls: list[dict[str, Any]], tmp_path: Path) -> None:
    result = runner.invoke(app, ["serve", "--config", str(tmp_path / "absent.yaml")])
    assert result.exit_code == 2
    assert "config file not found" in result.output
    assert calls == []


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
