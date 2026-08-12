"""Tier 1 -- cli._check_sweeps_alive: the doctor-level wiring around
`heartbeat.evaluate_freshness`, exercising the three real states named in
the acceptance criteria: service not installed, service installed+active
with fresh/stale heartbeats, and (via `_check_service_installed` already
having failed) the "installed but not running" skip.

`S.describe_service` is monkeypatched -- no real systemctl/launchctl calls,
matching test_service.py's own convention for anything beyond pure/rendered
logic.
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
    supported: bool = True
    installed: bool = True
    active: bool | None = True
    unit_path = None
    detail: str = "installed and active"
    platform: str = "linux"


def test_not_installed_is_skipped_not_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=False, active=None))
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is True
    assert "skipped" in result.detail
    assert "not installed" in result.detail


def test_unsupported_platform_is_skipped_not_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        S, "describe_service", lambda: _Info(supported=False, installed=False, active=None)
    )
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is True


def test_installed_but_not_active_is_skipped_service_check_already_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=False))
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is True
    assert "service.installed already failed" in result.detail


def test_installed_and_active_with_fresh_heartbeats_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_sweep_completed(path, HB.REAP, pid=1)
    HB.record_loop_started(path, HB.NOTIFY, pid=1)
    HB.record_sweep_completed(path, HB.NOTIFY, pid=1)
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is True
    assert result.id == "sweeps.alive"


def test_installed_and_active_with_stale_reap_heartbeat_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    data = {
        HB.REAP: {
            "pid": 1,
            "loop_started_at": _ts(10_000),
            "last_completed": _ts(SV.DEFAULT_REAP_INTERVAL_SECONDS * 10),
        },
        HB.NOTIFY: {
            "pid": 1,
            "loop_started_at": _ts(10),
            "last_completed": _ts(5),
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is False
    assert HB.REAP in result.detail


def test_installed_and_active_startup_window_no_sweeps_yet_passes(monkeypatch, tmp_path):
    """Service just (re)started: both loops have recorded their start but
    neither has completed a sweep yet. Must not be a false failure."""
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    path = HB.heartbeat_path(tmp_path)
    HB.record_loop_started(path, HB.REAP, pid=1)
    HB.record_loop_started(path, HB.NOTIFY, pid=1)
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is True


def test_installed_and_active_no_heartbeat_file_at_all_fails(monkeypatch, tmp_path):
    """Installed+active but the heartbeat file has never been written at
    all (e.g. a build that predates this feature) is a real failure, not a
    skip -- there is simply no evidence the loops ever ran."""
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=True, active=True))
    result = cli._check_sweeps_alive(tmp_path)
    assert result.ok is False
