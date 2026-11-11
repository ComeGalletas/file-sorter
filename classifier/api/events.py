"""API-001.2: the `/api/events` stream (R-API-2, API-001.D3, D10, D11).

`status_events` yields Server-Sent Events frames: the `/api/status` JSON whenever it changes
(checked every `interval` seconds), a keep-alive comment after `keepalive_after` seconds with
no frame (API-001.D10), and one fixed `unavailable` event each time the status stops being
readable (API-001.D11). The stream stays open through a failure and resumes when the status
is readable again. No exception text is kept or logged: a failure's detail is one of the
fixed strings `guarded` raises.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable

import anyio.to_thread
from fastapi import HTTPException

KEEPALIVE = b": keep-alive\n\n"


def status_frame(status_json: str) -> bytes:
    return f"event: status\ndata: {status_json}\n\n".encode()


def unavailable_frame(detail: str) -> bytes:
    return f"event: unavailable\ndata: {json.dumps({'detail': detail})}\n\n".encode()


async def status_events(
    read_status: Callable[[], str],
    *,
    interval: float,
    keepalive_after: float,
    sleep: Callable[[float], Awaitable[None]],
    is_disconnected: Callable[[], Awaitable[bool]],
    internal_error: str,
    max_ticks: int | None = None,
) -> AsyncIterator[bytes]:
    """Poll `read_status` (sync, run off the event loop) and yield SSE frames.

    `read_status` returns the status JSON, or raises `guarded`'s fixed HTTPException; any
    other failure reads as `internal_error` (the app's fixed 500 text).
    The stream ends when the client disconnects, or after `max_ticks` ticks (tests only;
    production passes None and streams until the disconnect).
    """
    last: str | None = None
    unavailable = False
    quiet = 0.0
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        if await is_disconnected():
            return
        ticks += 1
        detail: str | None = None
        current: str | None = None
        try:
            current = await anyio.to_thread.run_sync(read_status)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else internal_error
        except Exception:  # guarded raises only HTTPException; keep no text either way
            detail = internal_error
        frame: bytes | None = None
        if current is not None:
            if unavailable or current != last:
                frame = status_frame(current)
            last, unavailable = current, False
        elif not unavailable:
            frame = unavailable_frame(detail or internal_error)
            unavailable = True
        if frame is None:
            quiet += interval
            if quiet >= keepalive_after:
                frame = KEEPALIVE
        if frame is not None:
            quiet = 0.0
            yield frame
        if max_ticks is not None and ticks >= max_ticks:
            return
        await sleep(interval)
