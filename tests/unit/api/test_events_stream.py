"""API-001.2.1: the SSE generator, with a fake sleep and a fake disconnect (no real sleep).

API-001.D3 (the status whenever it changes), D10 (a keep-alive after 15 s with no frame),
D11 (one fixed `unavailable` event per transition; the stream stays open).
"""

from collections.abc import Callable, Iterable

import anyio
import pytest
from fastapi import HTTPException

from classifier.api.events import KEEPALIVE, status_events, status_frame, unavailable_frame

SECRET = "Zhyndel-planted-secret"
INTERNAL = "internal error"
UNAVAILABLE = "database unavailable"


class _Script:
    """`read_status` that plays a script: a JSON string, or an exception to raise."""

    def __init__(self, steps: Iterable[str | Exception]) -> None:
        self.steps = list(steps)
        self.calls = 0

    def __call__(self) -> str:
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


def _run(
    read: Callable[[], str],
    *,
    ticks: int | None = None,
    disconnect_after: int | None = None,
    interval: float = 2.0,
    keepalive_after: float = 15.0,
) -> tuple[list[bytes], list[float]]:
    frames: list[bytes] = []
    slept: list[float] = []
    checks = 0

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def is_disconnected() -> bool:
        nonlocal checks
        checks += 1
        return disconnect_after is not None and checks > disconnect_after

    async def main() -> None:
        stream = status_events(
            read,
            interval=interval,
            keepalive_after=keepalive_after,
            sleep=sleep,
            is_disconnected=is_disconnected,
            internal_error=INTERNAL,
            max_ticks=ticks,
        )
        async for frame in stream:
            frames.append(frame)

    anyio.run(main)
    return frames, slept


def test_frames_are_exact_sse() -> None:
    assert status_frame('{"a":1}') == b'event: status\ndata: {"a":1}\n\n'
    assert unavailable_frame(UNAVAILABLE) == (
        b'event: unavailable\ndata: {"detail": "database unavailable"}\n\n'
    )
    assert KEEPALIVE == b": keep-alive\n\n"


def test_first_tick_sends_then_only_changes() -> None:
    read = _Script(['{"n":1}', '{"n":1}', '{"n":2}', '{"n":2}', '{"n":1}'])
    frames, slept = _run(read, ticks=5)
    assert frames == [status_frame('{"n":1}'), status_frame('{"n":2}'), status_frame('{"n":1}')]
    assert read.calls == 5
    assert slept == [2.0] * 4  # the injected interval; no sleep after the last tick


def test_keepalive_after_15_s_with_no_frame() -> None:
    """API-001.D10: at a 2 s interval, the 8th quiet tick (16 s) sends the comment."""
    frames, _ = _run(_Script(['{"n":1}']), ticks=1 + 8 + 8)
    assert frames == [status_frame('{"n":1}'), KEEPALIVE, KEEPALIVE]


def test_a_change_resets_the_quiet_period() -> None:
    steps = ['{"n":1}'] * 7 + ['{"n":2}'] + ['{"n":2}'] * 7
    frames, _ = _run(_Script(steps), ticks=len(steps))
    assert frames == [status_frame('{"n":1}'), status_frame('{"n":2}')]  # never 15 s quiet


def test_one_unavailable_per_transition_and_recovery() -> None:
    """API-001.D11: the stream stays open through a failure and resends once readable."""
    down = HTTPException(status_code=503, detail=UNAVAILABLE)
    read = _Script(['{"n":1}', down, down, down, '{"n":1}', '{"n":1}', down])
    frames, _ = _run(read, ticks=7)
    assert frames == [
        status_frame('{"n":1}'),
        unavailable_frame(UNAVAILABLE),
        status_frame('{"n":1}'),  # unchanged, but resent after the failure
        unavailable_frame(UNAVAILABLE),
    ]


def test_failures_carry_fixed_text_only() -> None:
    """The plant is in the raised error (proved first), never in a frame."""
    plain = RuntimeError(f"/source/{SECRET}")
    non_str = HTTPException(status_code=500, detail={"input_value": SECRET})
    assert SECRET in str(plain) and SECRET in str(non_str.detail)
    for error in (plain, non_str):
        frames, _ = _run(_Script([error]), ticks=1)
        assert frames == [unavailable_frame(INTERNAL)]
        assert SECRET.encode() not in b"".join(frames)


def test_stream_ends_on_disconnect() -> None:
    read = _Script(['{"n":1}', '{"n":2}', '{"n":3}'])
    frames, _ = _run(read, disconnect_after=2)  # no tick limit: only the disconnect ends it
    assert frames == [status_frame('{"n":1}'), status_frame('{"n":2}')]
    assert read.calls == 2


def test_stream_ends_on_cancellation() -> None:
    read = _Script(['{"n":1}'])
    got: list[bytes] = []

    async def sleep(_seconds: float) -> None:
        await anyio.sleep_forever()

    async def connected() -> bool:
        return False

    async def main() -> None:
        with anyio.move_on_after(0.5) as scope:
            stream = status_events(
                read,
                interval=2.0,
                keepalive_after=15.0,
                sleep=sleep,
                is_disconnected=connected,
                internal_error=INTERNAL,
            )
            async for frame in stream:
                got.append(frame)
        assert scope.cancelled_caught

    anyio.run(main)
    assert got == [status_frame('{"n":1}')]
    assert read.calls == 1


@pytest.mark.parametrize("ticks", [0, 1])
def test_tick_limit(ticks: int) -> None:
    frames, slept = _run(_Script(['{"n":1}']), ticks=ticks)
    assert len(frames) == ticks and slept == []
