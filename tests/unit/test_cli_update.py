"""Tier 1 -- cli.cmd_update's own logic, isolated from uv and the network.

`shutil.which` and `subprocess.run` are monkeypatched so these exercise the
command's decision logic -- the uv command it builds, the `--reinstall` flag,
and its fail-loud behaviour when uv is missing or exits non-zero -- without
invoking the real uv or touching the installed tool.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import cli


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Completed:
    def __init__(self, returncode: int):
        self.returncode = returncode


def _fake_run(recorder: list[list[str]], returncode: int = 0):
    def run(cmd, check=False):
        recorder.append(list(cmd))
        return _Completed(returncode)

    return run


def test_builds_uv_tool_upgrade(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/uv")
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls, 0))

    rc = cli.cmd_update(_Args(reinstall=False))

    assert rc == 0
    assert calls == [["/usr/bin/uv", "tool", "upgrade", "amplifier-work-tracker"]]


def test_reinstall_flag_adds_reinstall(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/uv")
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls, 0))

    cli.cmd_update(_Args(reinstall=True))

    assert calls[0] == [
        "/usr/bin/uv",
        "tool",
        "upgrade",
        "--reinstall",
        "amplifier-work-tracker",
    ]


def test_missing_uv_fails_loud_and_runs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    ran: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(ran, 0))

    with pytest.raises(SystemExit) as ei:
        cli.cmd_update(_Args(reinstall=False))

    assert ei.value.code == 1
    assert "uv tool upgrade amplifier-work-tracker" in capsys.readouterr().err
    assert ran == []  # never attempted to run anything without uv


def test_nonzero_uv_exit_propagates_code(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/uv")
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls, 3))

    with pytest.raises(SystemExit) as ei:
        cli.cmd_update(_Args(reinstall=False))

    assert ei.value.code == 3
    assert "self-update failed" in capsys.readouterr().err
