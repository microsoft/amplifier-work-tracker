"""Tier 1 -- `sweeps.reclaiming`: the instrument that tells "the reap loop
is turning" apart from "the reap loop is doing anything" (`model_performance-oy4`).

THE GAP THIS CLOSES. `supervisor.reap_sweep` catches every per-project
exception into its return value so one broken project cannot abort the sweep
-- correct, and the reason a sweep in which EVERY project raised still
returns normally. `reap_loop` then discarded that return value and stamped a
completed heartbeat regardless. `sweeps.alive` reads that stamp, so it
reported healthy either way, and `work_tracker_status` reported
`running_healthy` on top of it. During the `model_performance-oy4` incident
that pairing was observed for 23 minutes while (it appeared) nothing was
being reclaimed, and no instrument anywhere could separate the two states.

Three layers are pinned here, all pure -- no service, no sleeps, no sweeps:
  - `supervisor.sweep_failures`: what counts as "the sweep failed here".
  - `heartbeat.evaluate_reclaiming`: the verdict, including the case that
    must not be fudged -- a record from a supervisor too old to know.
  - `cli._check_sweeps_reclaiming`: the doctor wiring and its skip rules.
"""

from __future__ import annotations

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
    supported: bool = True
    installed: bool = True
    active: bool | None = True
    unit_path = None
    detail: str = "installed and active"
    platform: str = "linux"


# --------------------------------------------------------------------------
# supervisor.sweep_failures -- one definition of "failed here".
# --------------------------------------------------------------------------


def test_sweep_failures_names_a_project_that_raised_wholesale():
    result = {"good": {"reclaimed_count": 1, "failed_count": 0}, "broken": {"error": "boom"}}
    assert SV.sweep_failures(result) == ["broken"]


def test_sweep_failures_names_a_project_whose_individual_release_failed():
    """A project that swept fine except for one item whose release raised is
    still not doing its job for that item -- and that item is exactly the
    stranded hold this whole feature exists to free.
    """
    result = {
        "ok": {"reclaimed_count": 2, "failed_count": 0},
        "partly": {"reclaimed_count": 1, "failed_count": 1, "failed": [{"id": "x-1"}]},
    }
    assert SV.sweep_failures(result) == ["partly"]


def test_sweep_failures_is_empty_for_a_clean_sweep():
    assert SV.sweep_failures({"a": {"reclaimed_count": 0, "failed_count": 0}}) == []


def test_sweep_failures_treats_a_non_dict_result_as_a_failure():
    """Defensive: an unexpected shape is reported, never silently read as
    success -- the failure mode this whole item is about.
    """
    assert SV.sweep_failures({"weird": None}) == ["weird"]  # type: ignore[dict-item]


# --------------------------------------------------------------------------
# heartbeat.evaluate_reclaiming -- the verdict.
# --------------------------------------------------------------------------


def test_clean_sweep_is_ok_and_reports_the_counts():
    ok, detail = HB.evaluate_reclaiming(
        {
            "pid": 1,
            "loop_started_at": _ts(600),
            "last_completed": _ts(10),
            "projects": 32,
            "reclaimed": 0,
            "failed_projects": [],
        }
    )
    assert ok is True
    assert "32 project(s)" in detail
    assert "0 failed" in detail


def test_a_sweep_with_failed_projects_fails_loudly_and_names_them():
    """THE FAIL-BEFORE for the doctor half: before this, exactly this record
    was indistinguishable from the clean one above.
    """
    ok, detail = HB.evaluate_reclaiming(
        {
            "pid": 1,
            "loop_started_at": _ts(600),
            "last_completed": _ts(10),
            "projects": 32,
            "reclaimed": 0,
            "failed_projects": ["model_performance", "cortex"],
        }
    )
    assert ok is False
    assert "model_performance" in detail
    assert "cortex" in detail
    assert "not reclaiming" in detail
    # A failure detail must carry its own next step, per this repo's
    # error-visibility convention.
    assert "journalctl" in detail


def test_many_failed_projects_are_truncated_but_counted_honestly():
    names = [f"p{i}" for i in range(14)]
    ok, detail = HB.evaluate_reclaiming(
        {
            "pid": 1,
            "loop_started_at": _ts(600),
            "last_completed": _ts(10),
            "projects": 20,
            "reclaimed": 0,
            "failed_projects": names,
        }
    )
    assert ok is False
    assert "FAILED on 14" in detail
    assert "+4 more" in detail


def test_a_record_from_an_older_supervisor_says_unknown_not_zero():
    """The case that must not be fudged. A heartbeat with no
    `failed_projects` key was written by a supervisor that never recorded
    one -- reporting it as "0 failed" would invent precisely the reassurance
    this check exists to stop being invented.
    """
    ok, detail = HB.evaluate_reclaiming(
        {"pid": 1, "loop_started_at": _ts(600), "last_completed": _ts(10)}
    )
    assert ok is True
    assert "unknown" in detail
    assert "predates" in detail
    assert "restart the service" in detail


def test_no_record_defers_to_the_liveness_check():
    ok, detail = HB.evaluate_reclaiming(None)
    assert ok is True
    assert "skipped" in detail


def test_notify_loop_completion_does_not_claim_zero_failures(tmp_path):
    """`record_sweep_completed` with no outcome arguments (the notify loop,
    which has no reclaim semantics) must NOT write an empty
    `failed_projects`, or the reap check would read a claim nobody made.
    """
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.NOTIFY, pid=1)
    HB.record_sweep_completed(path, HB.NOTIFY, pid=1)
    rec = HB.read_loop_heartbeat(path, HB.NOTIFY)
    assert rec is not None
    assert "failed_projects" not in rec


def test_reap_loop_outcome_round_trips_through_the_heartbeat_file(tmp_path):
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(
        path, HB.REAP, pid=1, projects=3, reclaimed=2, failed_projects=["bad"]
    )
    rec = HB.read_loop_heartbeat(path, HB.REAP)
    assert rec is not None
    assert rec["projects"] == 3
    assert rec["reclaimed"] == 2
    assert rec["failed_projects"] == ["bad"]
    assert HB.evaluate_reclaiming(rec)[0] is False


def test_recording_an_outcome_does_not_break_the_liveness_check(tmp_path):
    """The two checks read the same record; adding fields to it must not
    disturb `evaluate_freshness`, which existing behaviour depends on.
    """
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(path, HB.REAP, pid=1, projects=1, reclaimed=0, failed_projects=[])
    rec = HB.read_loop_heartbeat(path, HB.REAP)
    ok, _ = HB.evaluate_freshness(
        rec, loop=HB.REAP, interval=SV.DEFAULT_REAP_INTERVAL_SECONDS, is_pid_alive=lambda _p: True
    )
    assert ok is True


# --------------------------------------------------------------------------
# cli._check_sweeps_reclaiming -- the doctor wiring.
# --------------------------------------------------------------------------


def test_check_is_skipped_when_the_service_is_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=False, active=None))
    result = cli._check_sweeps_reclaiming(tmp_path)
    assert result.id == "sweeps.reclaiming"
    assert result.ok is True
    assert "skipped" in result.detail


def test_check_is_skipped_when_the_service_is_installed_but_inactive(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=False))
    result = cli._check_sweeps_reclaiming(tmp_path)
    assert result.ok is True
    assert "service.installed already failed" in result.detail


def test_check_fails_when_the_last_sweep_failed_on_a_project(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(
        path, HB.REAP, pid=1, projects=4, reclaimed=0, failed_projects=["model_performance"]
    )
    result = cli._check_sweeps_reclaiming(tmp_path)
    assert result.ok is False
    assert "model_performance" in result.detail


def test_check_passes_on_a_clean_sweep(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(path, HB.REAP, pid=1, projects=4, reclaimed=1, failed_projects=[])
    result = cli._check_sweeps_reclaiming(tmp_path)
    assert result.ok is True


def test_sweeps_alive_and_sweeps_reclaiming_are_two_distinct_assumptions(monkeypatch, tmp_path):
    """The whole point: a heartbeat can be FRESH (loop alive) and still prove
    the sweep is not reclaiming. Both verdicts are computed from the same
    record and must disagree here.
    """
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    for loop in (HB.REAP, HB.NOTIFY):
        HB.record_loop_started(path, loop, pid=1)
    HB.record_sweep_completed(path, HB.NOTIFY, pid=1)
    HB.record_sweep_completed(
        path, HB.REAP, pid=1, projects=2, reclaimed=0, failed_projects=["stuck"]
    )
    monkeypatch.setattr(HB, "pid_alive", lambda _p: True)
    alive = cli._check_sweeps_alive(tmp_path)
    reclaiming = cli._check_sweeps_reclaiming(tmp_path)
    assert alive.ok is True, alive.detail
    assert reclaiming.ok is False
