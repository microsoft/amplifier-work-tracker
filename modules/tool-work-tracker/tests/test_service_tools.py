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

import pytest
from amplifier_module_tool_work_tracker.service_tools import (
    WorkTrackerInstallTool,
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
