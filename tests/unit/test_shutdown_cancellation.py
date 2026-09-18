"""Supervisor-only cancellation leaves ordinary adapter calls untouched."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

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
