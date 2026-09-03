"""Tier 1 -- the ROOT-SCOPE gate on `sweeps.alive` / `sweeps.reclaiming`
(`model_performance-jyg`).

The defect: both checks join a SERVICE-scoped fact (`describe_service()` --
one singleton unit per user) to a ROOT-scoped one (a heartbeat file under the
workspace root `doctor` happens to be pointed at). That join is only sound
when the two refer to the same root. Against any other root the heartbeat is
absent BY CONSTRUCTION, and `sweeps.alive` reported that absence as
"no heartbeat ever recorded ... the loop may never have started" -- a hard
FAIL, exit 1, on a machine whose sweep loops were provably running fine.

The cost was not merely noise. `tests/cli/test_cli_surface.py::
test_doctor_quick_succeeds_against_the_real_installed_bd` asserts
`returncode == 0` FIRST, so this environmental FAIL MASKED every later
assertion in that test -- twice measurably (`model_performance-wp6`, whose
`\\berror\\b` collision was invisible locally and only ever appeared in CI,
and `model_performance-kxk`).

The fix is a scope gate, not a softening. Two halves, and BOTH are pinned
here because either one alone can be faked:

  1. Root the service does NOT serve -> `unknown`, never FAIL. This follows
     `sweeps.reclaiming`'s own precedent (`model_performance-oy4`): where
     the evidence cannot answer the question, say so in the assumption's
     text rather than fail (red-lining a healthy box) or pass silently
     (claiming proof we do not have).

  2. The root the service DOES serve -> completely unchanged. A missing,
     stale, or dead-pid heartbeat is still a loud FAIL. This is the half a
     "fix" that merely turned everything green would break, so it is tested
     harder than the half that was actually changed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from amplifier_work_tracker import cli
from amplifier_work_tracker import heartbeat as HB
from amplifier_work_tracker import service as S
from amplifier_work_tracker import supervisor as SV


def _ts(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


@dataclass
class _Info:
    """A service that is installed and active, serving `served_root`."""

    served_root: object = None
    supported: bool = True
    installed: bool = True
    active: bool | None = True
    unit_path = None
    detail: str = "installed and active"
    platform: str = "linux"


def _install(monkeypatch, served_root):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(served_root=served_root))


def _fresh_heartbeats(root, *, failed_projects=None):
    path = HB.heartbeat_path(root)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(
        path, HB.REAP, pid=1, projects=2, reclaimed=0, failed_projects=failed_projects or []
    )
    HB.record_loop_started(path, HB.NOTIFY, pid=1)
    HB.record_sweep_completed(path, HB.NOTIFY, pid=1)


# ------------------------------------------- half 1: a root we do not serve


def test_sweeps_alive_is_unknown_not_failed_for_a_root_the_service_does_not_serve(
    monkeypatch, tmp_path
):
    """The measured failure, reduced: an isolated root with no heartbeat,
    while the real service serves somewhere else entirely."""
    served = tmp_path / "real-root"
    other = tmp_path / "isolated-test-root"
    other.mkdir()
    _install(monkeypatch, served)

    result = cli._check_sweeps_alive(other)

    assert result.ok is True, "an unservable root must not red-line a healthy service"
    assert result.id == "sweeps.alive"
    assert "unknown" in result.detail


def test_the_unknown_detail_names_BOTH_roots_and_how_to_evaluate_it_properly(monkeypatch, tmp_path):
    """`unknown` is only honest if it says which two roots disagreed --
    otherwise a reader cannot tell a scope mismatch from a broken check, and
    has no way to actually run the assumption."""
    served = tmp_path / "real-root"
    other = tmp_path / "isolated-test-root"
    other.mkdir()
    _install(monkeypatch, served)

    detail = cli._check_sweeps_alive(other).detail

    assert str(served.resolve()) in detail
    assert str(other.resolve()) in detail
    assert "AMPLIFIER_WORK_TRACKER_ROOT" in detail


def test_sweeps_reclaiming_gets_the_same_gate(monkeypatch, tmp_path):
    """It reads the same root-scoped heartbeat file, so it has the same
    blind spot and needs the same answer."""
    served = tmp_path / "real-root"
    other = tmp_path / "isolated-test-root"
    other.mkdir()
    _install(monkeypatch, served)

    result = cli._check_sweeps_reclaiming(other)

    assert result.ok is True
    assert result.id == "sweeps.reclaiming"
    assert "unknown" in result.detail


def test_a_matching_root_expressed_differently_is_still_the_same_root(monkeypatch, tmp_path):
    """`/x/./ws` and `/x/ws` are one root. Comparing unresolved strings
    would report a mismatch that does not exist and silently stop
    evaluating a root we genuinely do serve."""
    served = tmp_path / "ws"
    served.mkdir()
    _fresh_heartbeats(served)
    _install(monkeypatch, tmp_path / "." / "ws")

    result = cli._check_sweeps_alive(served)

    assert result.ok is True
    assert "unknown" not in result.detail
    assert "sweep completed" in result.detail


# ----------------------------------- half 2: the FAIL path must still fail
#
# Everything below runs against the SERVED root -- a real installation
# looking at its own workspace. None of it may go green.


def test_served_root_with_no_heartbeat_at_all_STILL_FAILS(monkeypatch, tmp_path):
    """The deliverable that a green-everything "fix" would break: on a real
    installation, against the root the service actually serves, a sweep loop
    that never recorded a heartbeat is still a loud failure."""
    _install(monkeypatch, tmp_path)

    result = cli._check_sweeps_alive(tmp_path)

    assert result.ok is False
    assert "no heartbeat ever recorded" in result.detail


def test_served_root_with_a_stale_heartbeat_STILL_FAILS(monkeypatch, tmp_path):
    """A loop that died silently -- the exact ambiguity this assumption
    exists to resolve -- is still caught."""
    _install(monkeypatch, tmp_path)
    path = HB.heartbeat_path(tmp_path)
    path.write_text(
        json.dumps(
            {
                HB.REAP: {
                    "pid": 1,
                    "loop_started_at": _ts(10_000),
                    "last_completed": _ts(SV.DEFAULT_REAP_INTERVAL_SECONDS * 10),
                },
                HB.NOTIFY: {"pid": 1, "loop_started_at": _ts(10), "last_completed": _ts(5)},
            }
        ),
        encoding="utf-8",
    )

    result = cli._check_sweeps_alive(tmp_path)

    assert result.ok is False
    assert HB.REAP in result.detail


def test_served_root_with_a_dead_pid_heartbeat_STILL_FAILS(monkeypatch, tmp_path):
    """A fresh-looking timestamp written by a process that no longer exists
    is not proof the current one is healthy."""
    _install(monkeypatch, tmp_path)
    # `evaluate_freshness` binds `is_pid_alive=pid_alive` as a DEFAULT at
    # def time, so patching `HB.pid_alive` would not reach it. Inject
    # through the module's own documented injection point instead -- the
    # real decision function still runs, only the process probe is faked.
    real_evaluate = HB.evaluate_freshness
    monkeypatch.setattr(
        HB,
        "evaluate_freshness",
        lambda record, **kw: real_evaluate(record, is_pid_alive=lambda _pid: False, **kw),
    )
    _fresh_heartbeats(tmp_path)

    result = cli._check_sweeps_alive(tmp_path)

    assert result.ok is False
    assert "no longer running" in result.detail


def test_served_root_with_a_sweep_that_failed_on_every_project_STILL_FAILS(monkeypatch, tmp_path):
    """`sweeps.reclaiming`'s own guarantee (`model_performance-oy4`) is not
    weakened by the new gate: alive-but-not-reclaiming still reports FAIL
    against the served root."""
    _install(monkeypatch, tmp_path)
    _fresh_heartbeats(tmp_path, failed_projects=["proj-a", "proj-b"])

    result = cli._check_sweeps_reclaiming(tmp_path)

    assert result.ok is False
    assert "proj-a" in result.detail


def test_when_the_served_root_cannot_be_determined_we_evaluate_anyway_and_can_still_FAIL(
    monkeypatch, tmp_path
):
    """The conservative default, stated as a test so it cannot be quietly
    inverted later. An unreadable unit (or one with no `--root`) means
    "cannot tell" -- and "cannot tell" must never become a way to make a
    real dead-loop failure disappear. Silence about a scope mismatch is far
    cheaper than silence about a stopped sweep.
    """
    _install(monkeypatch, None)

    result = cli._check_sweeps_alive(tmp_path)

    assert result.ok is False
    assert "no heartbeat ever recorded" in result.detail


def test_the_gate_never_runs_before_the_service_is_even_installed(monkeypatch, tmp_path):
    """Dependency ordering is unchanged: not-installed is still reported as
    'skipped (service not installed)', not as a root mismatch. A second
    explanation for a cause already named adds no information."""
    monkeypatch.setattr(
        S,
        "describe_service",
        lambda: _Info(served_root=tmp_path / "elsewhere", installed=False, active=None),
    )

    result = cli._check_sweeps_alive(tmp_path)

    assert result.ok is True
    assert "not installed" in result.detail
    assert "unknown" not in result.detail
