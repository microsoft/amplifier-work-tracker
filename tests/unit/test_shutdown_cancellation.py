"""Supervisor-only cancellation leaves ordinary adapter calls untouched."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A


def test_cancellation_scope_is_thread_local_and_does_not_leak() -> None:
    event = threading.Event()
    assert A.current_supervisor_cancellation() is None
    with A.supervisor_cancellation_scope(event):
        assert A.current_supervisor_cancellation() is event
    assert A.current_supervisor_cancellation() is None


def test_cancellation_scope_restores_an_outer_scope() -> None:
    outer = threading.Event()
    inner = threading.Event()
    with A.supervisor_cancellation_scope(outer):
        with A.supervisor_cancellation_scope(inner):
            assert A.current_supervisor_cancellation() is inner
        assert A.current_supervisor_cancellation() is outer


def test_cancellation_scope_does_not_leak_from_a_reused_worker_thread() -> None:
    event = threading.Event()

    def scoped_call():
        with A.supervisor_cancellation_scope(event):
            assert A.current_supervisor_cancellation() is event
        return A.current_supervisor_cancellation()

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(scoped_call).result() is None
        assert executor.submit(A.current_supervisor_cancellation).result() is None


def test_scoped_retry_sleep_interrupts_without_waiting() -> None:
    event = threading.Event()
    event.set()
    with A.supervisor_cancellation_scope(event), pytest.raises(A.SupervisorShutdownError):
        A._sleep_or_cancel(60)


def test_unscoped_retry_sleep_keeps_normal_behavior(monkeypatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(A.time, "sleep", waits.append)
    A._sleep_or_cancel(0.25)
    assert waits == [0.25]


def _wait_for(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.01)


def _pid_is_gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except FileNotFoundError:
        return True
    return state == "Z"


def test_scoped_cancellation_kills_pipe_less_term_ignoring_descendant(tmp_path: Path) -> None:
    """The group's known PGID survives after its TERM-exiting parent does not."""
    ready = tmp_path / "ready"
    child_pid_path = tmp_path / "child.pid"
    parent = tmp_path / "parent.py"
    parent.write_text(
        """
import signal
import subprocess
import sys
import time
from pathlib import Path

ready = Path(sys.argv[1])
child_pid_path = Path(sys.argv[2])
child = subprocess.Popen([
    sys.executable, "-c",
    "import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "os.dup2(os.open('/dev/null', os.O_WRONLY), 1); os.dup2(os.open('/dev/null', os.O_WRONLY), 2); "
    "time.sleep(600)",
])
child_pid_path.write_text(str(child.pid), encoding="utf-8")
ready.write_text("ready", encoding="utf-8")
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
time.sleep(600)
""",
        encoding="utf-8",
    )
    cancelled = threading.Event()
    outcome: dict[str, BaseException] = {}

    def run() -> None:
        try:
            with A.supervisor_cancellation_scope(cancelled):
                A._run_bounded(
                    [sys.executable, str(parent), str(ready), str(child_pid_path)], timeout=30
                )
        except BaseException as error:  # asserted below; preserve thread failure
            outcome["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    child_pid: int | None = None
    try:
        _wait_for(ready)
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        cancelled.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert isinstance(outcome.get("error"), A.SupervisorShutdownError)
        assert _pid_is_gone(child_pid), f"owned pipe-less descendant survived: {child_pid}"
    finally:
        cancelled.set()
        worker.join(timeout=5)
        if child_pid is not None and not _pid_is_gone(child_pid):
            os.kill(child_pid, signal.SIGKILL)
