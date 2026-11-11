"""`classifier serve`: the read-only API and UI under uvicorn (CLI-008.1; R-API-1, §7).

Defaults come from `api.host` and `api.port`. In compose, the `app` service passes
`--host 0.0.0.0` on the internal network, and only the localhost proxy publishes it
(RUN-019.D2). No request line is ever logged (m4 item 15): `create_app` disables
`uvicorn.access`, and `serve` also passes `access_log=False`.
"""

import logging
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from classifier.api.app import create_app
from classifier.config import ConfigError, load_config

CONFIG_FAILED = "error: {error}"
NO_DSN = "error: config.db.dsn is not set"
LISTEN_FAILED = "error: could not listen on the configured address"
APP_FAILED = "error: the app could not start"


class _DropErrors(logging.Filter):
    """uvicorn logs a bind failure or a startup crash with the OS or exception text, which can
    carry the address or a value. `serve` prints its own fixed line instead."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


_ERRORS_FILTER = _DropErrors()


def serve(
    host: Annotated[
        str | None, typer.Option("--host", help="Address to bind; default api.host.")
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", min=1, max=65535, help="Port to bind; default api.port."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Config file; default $CLASSIFIER_CONFIG.")
    ] = None,
) -> None:
    """Serve the read-only status API and dashboard (no request is ever logged)."""
    try:
        config = load_config(config_path)
    except ConfigError as error:  # value-free: load_config wraps YAML and validation errors
        typer.echo(CONFIG_FAILED.format(error=error), err=True)
        raise typer.Exit(2) from None
    if not config.db.dsn:
        typer.echo(NO_DSN, err=True)
        raise typer.Exit(2)
    bind_host = host if host is not None else config.api.host
    bind_port = port if port is not None else config.api.port

    failed = False
    try:
        app = create_app(config)
    except Exception:  # noqa: BLE001 — fixed text below; the message may carry a value
        failed = True
    if failed:
        typer.echo(APP_FAILED, err=True)
        raise typer.Exit(2)

    error_log = logging.getLogger("uvicorn.error")
    error_log.addFilter(_ERRORS_FILTER)
    typer.echo(f"serving on {bind_host}:{bind_port}")
    stopped_badly = False
    try:
        uvicorn.run(
            app,
            host=bind_host,
            port=bind_port,
            access_log=False,  # m4 item 15; create_app also disables uvicorn.access
            server_header=False,  # no version advertised
            log_config=None,  # no uvicorn handlers; nothing per request
        )
    except SystemExit as stop:  # uvicorn exits 1 when it can't bind or start
        stopped_badly = stop.code not in (0, None)
    except OSError:
        stopped_badly = True
    finally:
        error_log.removeFilter(_ERRORS_FILTER)
    if stopped_badly:
        typer.echo(LISTEN_FAILED, err=True)
        raise typer.Exit(1)
