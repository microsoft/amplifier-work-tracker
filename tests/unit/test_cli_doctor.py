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


# ---------------------------------------------------------------- restart_policy
#
# Regression pin for the 2026-08-14 outage: `_check_restart_policy` reads the
# INSTALLED unit's own Restart= line -- the doctor-level wiring around it,
# same dependency-ordering convention as `_check_sweeps_alive` above (skip,
# don't fail, whenever a prerequisite state isn't there to check).


def _unit_with(tmp_path, restart_line: str | None):
    unit_path = tmp_path / "amplifier-work-tracker.service"
    body = "[Unit]\nDescription=x\n\n[Service]\nExecStart=/x\n"
    if restart_line is not None:
        body += f"{restart_line}\n"
    unit_path.write_text(body, encoding="utf-8")
    return unit_path


def test_restart_policy_skipped_when_service_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=False, active=None))
    service_check = cli.contract.Result("service.installed", True, "not installed")
    result = cli._check_restart_policy(service_check)
    assert result.ok is True
    assert "skipped" in result.detail


def test_restart_policy_skipped_when_platform_unsupported(monkeypatch):
    monkeypatch.setattr(
        S, "describe_service", lambda: _Info(supported=False, installed=False, active=None)
    )
    service_check = cli.contract.Result("service.installed", True, "n/a")
    result = cli._check_restart_policy(service_check)
    assert result.ok is True


def test_restart_policy_skipped_on_non_linux_platform_with_no_unit_file(monkeypatch, tmp_path):
    info = _Info(installed=True, active=True, platform="darwin")
    info.unit_path = None
    monkeypatch.setattr(S, "describe_service", lambda: info)
    service_check = cli.contract.Result("service.installed", True, "ok")
    result = cli._check_restart_policy(service_check)
    assert result.ok is True
    assert "skipped" in result.detail


def test_restart_policy_passes_when_unit_has_restart_always(monkeypatch, tmp_path):
    unit_path = _unit_with(tmp_path, "Restart=always")
    info = _Info(installed=True, active=True, platform="linux")
    info.unit_path = unit_path
    monkeypatch.setattr(S, "describe_service", lambda: info)
    service_check = cli.contract.Result("service.installed", True, "ok")
    result = cli._check_restart_policy(service_check)
    assert result.ok is True
    assert result.id == "service.restart_policy"


def test_restart_policy_fails_when_unit_still_has_restart_on_failure(monkeypatch, tmp_path):
    """The exact regression this pins: the OLD policy, still on disk because
    the fixed package was never re-installed."""
    unit_path = _unit_with(tmp_path, "Restart=on-failure")
    info = _Info(installed=True, active=True, platform="linux")
    info.unit_path = unit_path
    monkeypatch.setattr(S, "describe_service", lambda: info)
    service_check = cli.contract.Result("service.installed", True, "ok")
    result = cli._check_restart_policy(service_check)
    assert result.ok is False
    assert "on-failure" in result.detail
    assert "service install" in result.detail


def test_restart_policy_fails_when_unit_has_no_restart_line_at_all(monkeypatch, tmp_path):
    unit_path = _unit_with(tmp_path, None)
    info = _Info(installed=True, active=True, platform="linux")
    info.unit_path = unit_path
    monkeypatch.setattr(S, "describe_service", lambda: info)
    service_check = cli.contract.Result("service.installed", True, "ok")
    result = cli._check_restart_policy(service_check)
    assert result.ok is False
    assert "no Restart=" in result.detail


# ------------------------------------------------------------- service.installed
#
# `info.active is None` while `info.installed` is True is a DIFFERENT fact
# than "never installed" (installed=False, also active=None) -- it means this
# process could not query systemd --user at all (most commonly no reachable
# session bus). Reporting a hard FAIL here would repeat the exact
# misdiagnosis measured on a peer's first-time setup: systemd --user was
# genuinely fine, this process just couldn't ask it.


def test_service_installed_passes_with_a_note_when_active_is_genuinely_unknown(monkeypatch):
    monkeypatch.setattr(
        S,
        "describe_service",
        lambda: _Info(
            installed=True,
            active=None,
            detail="installed, but active/inactive could not be determined -- XDG_RUNTIME_DIR ...",
        ),
    )
    result = cli._check_service_installed()
    assert result.ok is True
    assert result.id == "service.installed"
    assert "systemd.user_bus_reachable" in result.detail


def test_service_installed_still_fails_when_genuinely_confirmed_inactive(monkeypatch):
    monkeypatch.setattr(
        S,
        "describe_service",
        lambda: _Info(installed=True, active=False, detail="installed but NOT active"),
    )
    result = cli._check_service_installed()
    assert result.ok is False


def test_service_installed_passes_when_never_installed(monkeypatch):
    monkeypatch.setattr(S, "describe_service", lambda: _Info(installed=False, active=None))
    result = cli._check_service_installed()
    assert result.ok is True
    assert "not installed" in result.detail


# ------------------------------------------------------- systemd.user_bus_reachable


def test_systemd_user_bus_reachable_skips_when_probe_reports_skipped(monkeypatch):
    monkeypatch.setattr(
        S, "probe_systemd_user_bus", lambda: ("skipped", "no systemd --user bus on this platform")
    )
    result = cli._check_systemd_user_bus_reachable()
    assert result.ok is True
    assert result.id == "systemd.user_bus_reachable"
    assert "skipped" in result.detail


def test_systemd_user_bus_reachable_passes_when_probe_reports_reachable(monkeypatch):
    monkeypatch.setattr(
        S,
        "probe_systemd_user_bus",
        lambda: ("reachable", "systemctl --user show-environment succeeded"),
    )
    result = cli._check_systemd_user_bus_reachable()
    assert result.ok is True


def test_systemd_user_bus_reachable_fails_when_probe_reports_unreachable(monkeypatch):
    monkeypatch.setattr(
        S,
        "probe_systemd_user_bus",
        lambda: (
            "unreachable",
            "systemctl --user cannot reach the user session bus ... XDG_RUNTIME_DIR ...",
        ),
    )
    result = cli._check_systemd_user_bus_reachable()
    assert result.ok is False
    assert "XDG_RUNTIME_DIR" in result.detail
