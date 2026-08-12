"""Tier 1 -- sweep heartbeat mechanics: the write side (record_loop_started /
record_sweep_completed), the read side (read_loop_heartbeat), and the pure
freshness decision (evaluate_freshness) `cli._check_sweeps_alive` runs.

Every timestamp is forged (`_ts`, matching test_custody.py's convention) --
nothing here sleeps for a real interval. `pid_alive` is exercised against a
real, deterministically-dead pid (a subprocess that has already been waited
on) rather than a guessed high number, so the "left over from a previous
run" scenario is proven against a REAL dead process, not an assumption.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from amplifier_work_tracker import heartbeat as HB


def _ts(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _dead_pid() -> int:
    """A pid guaranteed to no longer be running: spawn a trivial subprocess
    and wait for it to exit (and be reaped) before returning its old pid.
    """
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


# --------------------------------------------------------------- write/read


def test_record_loop_started_then_read_shows_no_completion_yet(tmp_path):
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=12345)
    rec = HB.read_loop_heartbeat(path, HB.REAP)
    assert rec is not None
    assert rec["pid"] == 12345
    assert rec["last_completed"] is None
    assert rec["loop_started_at"]


def test_record_sweep_completed_sets_last_completed_and_keeps_loop_started_at(tmp_path):
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=111)
    before = HB.read_loop_heartbeat(path, HB.REAP)
    assert before is not None
    started = before["loop_started_at"]
    HB.record_sweep_completed(path, HB.REAP, pid=111)
    rec = HB.read_loop_heartbeat(path, HB.REAP)
    assert rec is not None
    assert rec["last_completed"] is not None
    assert rec["loop_started_at"] == started


def test_record_sweep_completed_without_prior_started_still_works(tmp_path):
    """Defensive: a sweep completing with no `record_loop_started` on file
    yet (should not normally happen, but must not crash) still produces a
    usable record."""
    path = HB.heartbeat_path(tmp_path)
    HB.record_sweep_completed(path, HB.NOTIFY, pid=1)
    rec = HB.read_loop_heartbeat(path, HB.NOTIFY)
    assert rec is not None
    assert rec["last_completed"] is not None
    assert rec["loop_started_at"]


def test_reap_and_notify_records_are_independent(tmp_path):
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_loop_started(path, HB.NOTIFY, pid=2)
    HB.record_sweep_completed(path, HB.REAP, pid=1)
    reap = HB.read_loop_heartbeat(path, HB.REAP)
    notify = HB.read_loop_heartbeat(path, HB.NOTIFY)
    assert reap is not None
    assert notify is not None
    assert reap["last_completed"] is not None
    assert notify["last_completed"] is None  # only reap completed a sweep


def test_read_loop_heartbeat_missing_file_is_none(tmp_path):
    path = HB.heartbeat_path(tmp_path)  # never written
    assert HB.read_loop_heartbeat(path, HB.REAP) is None


def test_read_loop_heartbeat_corrupt_file_is_none(tmp_path):
    path = HB.heartbeat_path(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    assert HB.read_loop_heartbeat(path, HB.REAP) is None


def test_record_loop_started_overwrites_a_previous_runs_completion(tmp_path):
    """The core anti-staleness mechanism: a NEW run's `record_loop_started`
    call must discard the OLD run's `last_completed`, even though that old
    value was recent -- otherwise a brand new process could look like it
    already proved a sweep before it has done any work.
    """
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=999)
    HB.record_sweep_completed(path, HB.REAP, pid=999)
    first = HB.read_loop_heartbeat(path, HB.REAP)
    assert first is not None
    assert first["last_completed"] is not None

    # A new process (new pid) starts the same loop again.
    HB.record_loop_started(path, HB.REAP, pid=1000)
    rec = HB.read_loop_heartbeat(path, HB.REAP)
    assert rec is not None
    assert rec["pid"] == 1000
    assert rec["last_completed"] is None


# --------------------------------------------------------------------- pid_alive


def test_pid_alive_true_for_current_process():
    assert HB.pid_alive(os.getpid()) is True


def test_pid_alive_false_for_a_really_dead_process():
    assert HB.pid_alive(_dead_pid()) is False


# ------------------------------------------------------------- evaluate_freshness


def test_fresh_completion_passes():
    record = {"pid": 1, "loop_started_at": _ts(400), "last_completed": _ts(10)}
    ok, detail = HB.evaluate_freshness(
        record, loop="reap", interval=300, is_pid_alive=lambda pid: True
    )
    assert ok is True
    assert "reap" in detail


def test_stale_completion_fails_and_names_loop_and_fix():
    record = {"pid": 1, "loop_started_at": _ts(2000), "last_completed": _ts(1000)}
    ok, detail = HB.evaluate_freshness(
        record, loop="reap", interval=300, is_pid_alive=lambda pid: True
    )
    assert ok is False
    assert "reap" in detail
    assert "not completed in 10" in detail  # staleness duration, ~1000s (timing-tolerant)
    assert "service restart" in detail  # the fix


def test_no_record_at_all_fails_and_names_loop():
    ok, detail = HB.evaluate_freshness(
        None, loop="notify", interval=300, is_pid_alive=lambda pid: True
    )
    assert ok is False
    assert "notify" in detail
    assert "no heartbeat ever recorded" in detail


def test_startup_window_no_completion_yet_but_recent_start_passes():
    record = {"pid": 1, "loop_started_at": _ts(5), "last_completed": None}
    ok, detail = HB.evaluate_freshness(
        record, loop="reap", interval=300, is_pid_alive=lambda pid: True
    )
    assert ok is True
    assert "pending" in detail


def test_startup_window_exceeded_with_no_completion_fails():
    record = {"pid": 1, "loop_started_at": _ts(10_000), "last_completed": None}
    ok, detail = HB.evaluate_freshness(
        record, loop="reap", interval=300, is_pid_alive=lambda pid: True
    )
    assert ok is False
    assert "never completed a sweep" in detail


def test_dead_pid_with_recent_completion_does_not_read_as_fresh():
    """The scenario this feature exists to catch: a heartbeat left behind by
    a process that has since died, whose `last_completed` LOOKS fresh by
    timestamp alone. Must fail, and must say why.
    """
    record = {"pid": 4242, "loop_started_at": _ts(400), "last_completed": _ts(10)}
    ok, detail = HB.evaluate_freshness(
        record, loop="reap", interval=300, is_pid_alive=lambda pid: False
    )
    assert ok is False
    assert "4242" in detail
    assert "no longer running" in detail


def test_dead_pid_check_uses_real_pid_alive_by_default():
    """End-to-end (no injected fake): a real dead pid, produced the same way
    as test_pid_alive_false_for_a_really_dead_process, must fail through the
    default `is_pid_alive=pid_alive` wiring -- not just when a test stubs it
    out."""
    dead = _dead_pid()
    record = {"pid": dead, "loop_started_at": _ts(400), "last_completed": _ts(10)}
    ok, detail = HB.evaluate_freshness(record, loop="reap", interval=300)
    assert ok is False
    assert str(dead) in detail


def test_threshold_is_interval_times_stale_multiple():
    record = {"pid": 1, "loop_started_at": _ts(1000), "last_completed": _ts(199)}
    ok, _ = HB.evaluate_freshness(
        record,
        loop="reap",
        interval=100,
        stale_multiple=2.0,
        is_pid_alive=lambda pid: True,
    )
    assert ok is True  # 199 <= 100*2
    ok2, _ = HB.evaluate_freshness(
        record,
        loop="reap",
        interval=100,
        stale_multiple=1.0,
        is_pid_alive=lambda pid: True,
    )
    assert ok2 is False  # 199 > 100*1
