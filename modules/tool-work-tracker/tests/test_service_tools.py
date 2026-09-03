"""service_tools.py -- classify_state's dependency-ordering (prereqs FIRST,
service/port checks skipped once a prerequisite fails) and
WorkTrackerInstallTool's loud refusal on a missing prerequisite.

Not part of root CI today (this module's dev extras -- pytest,
pytest-asyncio, amplifier-core -- exist specifically so a developer can
`uv pip install -e ".[dev]"` inside `modules/tool-work-tracker` and run
these locally; ci.yml only exercises the root `tests/` tree). Run with:

    cd modules/tool-work-tracker
    uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"
    .venv/bin/python -m pytest tests/ -v

Fake-PATH only -- no network, no real downloads, no real systemd/launchd
calls (those are exercised by `tests/unit/test_service.py` in the root
suite already).
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from dataclasses import dataclass

import pytest
from amplifier_module_tool_work_tracker.service_tools import (
    WorkTrackerInstallTool,
    WorkTrackerStatusTool,
    classify_state,
)

import amplifier_work_tracker.service as S
import amplifier_work_tracker.supervisor as SV


def _write_stub(bin_dir, name: str, version_output: str) -> None:
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\necho '{version_output}'\nexit 0\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_classify_state_reports_bd_missing_before_touching_service_or_port(tmp_path, monkeypatch):
    """Dependency ordering, proven from the OUTSIDE: even though nothing
    stops `service.describe_service()`/`supervisor.port_holder_responds()`
    from being callable, `classify_state` must never reach them when
    prereqs.check() already failed -- confirmed by monkeypatching both to
    raise, so a call would be an immediate, loud test failure rather than a
    silently-passing coincidence."""

    def _must_not_be_called(*a, **k):
        raise AssertionError("downstream service/port check was called despite bd_missing")

    monkeypatch.setattr(S, "describe_service", _must_not_be_called)
    monkeypatch.setattr(SV, "port_holder_responds", _must_not_be_called)

    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    state, fix = classify_state(tmp_path / "root")
    assert state == "bd_missing"
    assert "bd is not on PATH" in fix


def test_classify_state_reports_bd_too_old_via_forged_version(tmp_path, monkeypatch):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_stub(stub_bin, "bd", "bd version 0.9.0")
    monkeypatch.setenv("PATH", str(stub_bin))

    state, fix = classify_state(tmp_path / "root")
    assert state == "bd_too_old"
    assert "0.9.0" in fix


@pytest.mark.asyncio
async def test_status_tool_surfaces_console_script_fix_when_off_path(tmp_path, monkeypatch):
    """`work_tracker_status` must report OUR OWN CLI being off-PATH (a
    separate concern from `state`/`fix`, which are about bd/dolt/the
    service) -- this is the field a session should check before ever
    shelling out to `amplifier-work-tracker` by name, instead of
    discovering `command not found` and burning 6 tool calls hunting for
    the binary."""
    monkeypatch.setattr(
        S,
        "resolve_console_script",
        lambda: ("/fake/path/amplifier-work-tracker", "ln -s /fake/path ~/.local/bin/..."),
    )
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerStatusTool(config=None)
    result = await tool.execute({})

    assert result.success is True
    output = result.output
    assert isinstance(output, dict)
    assert output["console_script_path"] == "/fake/path/amplifier-work-tracker"
    assert "ln -s" in output["console_script_fix"]


@pytest.mark.asyncio
async def test_status_tool_omits_console_script_fields_when_on_path(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "resolve_console_script", lambda: (None, None))
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerStatusTool(config=None)
    result = await tool.execute({})

    output = result.output
    assert isinstance(output, dict)
    assert "console_script_path" not in output
    assert "console_script_fix" not in output


@pytest.mark.asyncio
async def test_install_tool_reports_observed_rollback_detail_on_service_install_failure(
    tmp_path, monkeypatch
):
    """The old message hardcoded "No partial install was left behind"
    regardless of whether that was true. This proves the tool now reports
    whatever `service_install` actually observed instead."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)

    def fake_service_install(root):
        err = RuntimeError("systemctl enable failed")
        err.rollback_detail = "disable: ok; remove unit file: ok; daemon-reload: exit 1 (no bus)"  # type: ignore[attr-defined]
        raise err

    monkeypatch.setattr(S, "service_install", fake_service_install)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output)
    assert "No partial install was left behind" not in output
    assert "daemon-reload: exit 1 (no bus)" in output


@pytest.mark.asyncio
async def test_install_tool_admits_unknown_rollback_when_no_detail_was_observed(
    tmp_path, monkeypatch
):
    """If the underlying failure carries no `rollback_detail` at all (an
    exception this code didn't anticipate), the message must say the
    outcome is unknown -- never assert a specific, unobserved claim."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)

    def fake_service_install(root):
        raise RuntimeError("something unanticipated")

    monkeypatch.setattr(S, "service_install", fake_service_install)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output)
    assert "No partial install was left behind" not in output
    assert "unknown" in output.lower()


@pytest.mark.asyncio
async def test_install_tool_refuses_loudly_when_bd_missing(tmp_path, monkeypatch):
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output)
    assert "refusing to install" in output
    assert "bd is not on PATH" in output


@pytest.mark.asyncio
async def test_install_tool_refuses_loudly_when_dolt_missing(tmp_path, monkeypatch):
    real_bd = shutil.which("bd")
    if real_bd is None:
        pytest.skip("real `bd` binary not present in this environment")

    shim_dir = tmp_path / "bd_shim"
    shim_dir.mkdir()
    (shim_dir / "bd").symlink_to(real_bd)
    monkeypatch.setenv("PATH", str(shim_dir))
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output)
    assert "refusing to install" in output
    assert "dolt is not on PATH" in output


# ---------------------------------------------------------------------------
# running_unmanaged -- a healthy-but-unmanaged dolt must never be classified
# (or advised) as something to kill.
# ---------------------------------------------------------------------------


@dataclass
class _FakeServiceInfo:
    installed: bool
    active: bool | None
    supported: bool = True
    platform: str = "linux"
    unit_path: object = None
    detail: str = ""


def _bypass_prereqs(monkeypatch) -> None:
    """Prereqs are proven fine and out of scope for these tests -- bypass
    `prereqs.check()` directly rather than faking a whole bd/dolt PATH."""
    import amplifier_work_tracker.prereqs as P

    monkeypatch.setattr(P, "check", lambda: None)


def test_classify_state_reports_running_unmanaged_not_foreign_when_port_is_healthy(
    tmp_path, monkeypatch
):
    """The literal regression this fix targets: a healthy dolt on our port
    that this service didn't start must classify as `running_unmanaged`
    (adopt-friendly), never the old `foreign_server_on_port` (kill-advising)
    state."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)

    state, fix = classify_state(tmp_path / "root")

    assert state == "running_unmanaged"
    assert "stop it" not in fix.lower()
    assert "kill" not in fix.lower()
    assert "usable" in fix.lower() or "working" in fix.lower() or "healthy" in fix.lower()


def test_classify_state_running_unmanaged_advises_adoption_not_shutdown(tmp_path, monkeypatch):
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)

    _, fix = classify_state(tmp_path / "root")
    assert "work_tracker_install" in fix
    assert (
        "use it directly" in fix.lower() or "usable as-is" in fix.lower() or "use it" in fix.lower()
    )


@pytest.mark.asyncio
async def test_install_tool_refuses_running_unmanaged_without_advising_to_kill_it(
    tmp_path, monkeypatch
):
    """`work_tracker_install` must still refuse (installing on top of an
    already-bound port would crash-loop), but its OWN message must not tell
    the caller to stop/kill a working server either."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output).lower()
    assert "works as-is" in output or "already healthy" in output
    assert "just to install" not in output or "do not stop it just to install" in output


# ---------------------------------------------------------------------------
# running_systemd_unreachable -- a genuinely-managed unit must never be
# reported as `running_unmanaged` just because THIS process couldn't query
# systemd --user (see service.py's `_systemd_user_env`). The literal
# first-time-setup bug this closes: a peer's `work_tracker_status` reported
# a real, systemd-managed, active unit as `running_unmanaged` purely because
# this process's own environment (spawned outside a login session) lacked a
# reachable session bus.
# ---------------------------------------------------------------------------


def test_classify_state_reports_running_systemd_unreachable_not_running_unmanaged(
    tmp_path, monkeypatch
):
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S,
        "describe_service",
        lambda: _FakeServiceInfo(
            installed=True,
            active=None,
            detail="installed, but active/inactive could not be determined -- XDG_RUNTIME_DIR ...",
        ),
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)

    state, fix = classify_state(tmp_path / "root")

    assert state == "running_systemd_unreachable"
    assert state != "running_unmanaged"
    assert "stop" not in fix.lower() or "do not stop" in fix.lower()


def test_classify_state_reports_installed_not_running_when_systemd_unreachable_and_port_down(
    tmp_path, monkeypatch
):
    """Same bus-unreachable `active=None`, but no dolt server answering
    either -- this is honestly `installed_not_running` (with an explanation),
    never `running_systemd_unreachable` (which claims a server IS
    reachable)."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=True, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)

    state, fix = classify_state(tmp_path / "root")

    assert state == "installed_not_running"
    assert "XDG_RUNTIME_DIR" in fix


def test_classify_state_never_reachable_unknown_state_when_never_installed(tmp_path, monkeypatch):
    """Regression guard for the existing `running_unmanaged` behaviour:
    `installed=False` also carries `active=None` by convention (see
    `ServiceInfo`), and must NOT be caught by the new
    `running_systemd_unreachable` branch -- only `installed=True` with
    `active=None` means "couldn't query systemd."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)

    state, _fix = classify_state(tmp_path / "root")

    assert state == "running_unmanaged"


@pytest.mark.asyncio
async def test_install_tool_refuses_running_systemd_unreachable_without_advising_to_kill_it(
    tmp_path, monkeypatch
):
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=True, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: True)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output).lower()
    assert "not installing" in output
    assert "stop" not in output or "do not stop" in output


# ---------------------------------------------------------------------------
# work_tracker_install's diagnosis of a REAL systemctl failure -- the other
# half of the measured bug. A `subprocess.CalledProcessError` carrying a
# bus-connection stderr must be diagnosed via `diagnose_systemd_failure`
# (naming XDG_RUNTIME_DIR), never the old generic "systemd/launchd itself
# isn't functioning here" text.
# ---------------------------------------------------------------------------


def _bus_unreachable_called_process_error(rollback_detail: str | None = None):
    err = subprocess.CalledProcessError(
        1,
        ["systemctl", "--user", "daemon-reload"],
        output="",
        stderr="Failed to connect to bus: No medium found\n",
    )
    if rollback_detail is not None:
        err.rollback_detail = rollback_detail  # type: ignore[attr-defined]
    return err


@pytest.mark.asyncio
async def test_install_tool_diagnoses_bus_unreachable_instead_of_generic_systemd_message(
    tmp_path, monkeypatch
):
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)

    def fake_service_install(root):
        raise _bus_unreachable_called_process_error(
            "disable: ok; remove unit file: ok; daemon-reload: ok"
        )

    monkeypatch.setattr(S, "service_install", fake_service_install)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    output = str(result.output)
    assert "XDG_RUNTIME_DIR" in output
    # The old misdiagnosis, measured on a peer's machine -- must be gone.
    assert "isn't functioning here" not in output
    assert "does not appear to use systemd" not in output


@pytest.mark.asyncio
async def test_install_tool_still_admits_unknown_rollback_for_called_process_error(
    tmp_path, monkeypatch
):
    """Same `rollback_detail`-honesty contract as the generic-exception path
    (see `test_install_tool_admits_unknown_rollback_when_no_detail_was_observed`),
    now proven for the new `CalledProcessError` branch too."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)

    def fake_service_install(root):
        raise _bus_unreachable_called_process_error(None)

    monkeypatch.setattr(S, "service_install", fake_service_install)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    assert "unknown" in str(result.output).lower()


@pytest.mark.asyncio
async def test_install_tool_reports_not_the_init_system_when_marker_absent(tmp_path, monkeypatch):
    """A `CalledProcessError` whose stderr matches NEITHER known pattern, on
    a host genuinely without `/run/systemd/system` -- the ONLY case
    reserved for "does not appear to use systemd" now."""
    _bypass_prereqs(monkeypatch)
    monkeypatch.setattr(
        S, "describe_service", lambda: _FakeServiceInfo(installed=False, active=None)
    )
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port: False)
    monkeypatch.setattr(S, "_systemd_is_init_system", lambda: False)

    def fake_service_install(root):
        raise subprocess.CalledProcessError(
            1, ["systemctl", "--user", "daemon-reload"], output="", stderr="some other error\n"
        )

    monkeypatch.setattr(S, "service_install", fake_service_install)
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))

    tool = WorkTrackerInstallTool(config=None)
    result = await tool.execute({})

    assert result.success is False
    assert "does not appear to use systemd" in str(result.output)
