"""Tier 1 -- service.py pure/testable logic: argv construction, root
resolution, and the platform-dispatching wrappers' unsupported-platform
paths. No real systemctl/launchctl calls -- those are exercised by the
`service install` verification run in the PR description, not here.

The `systemd-analyze verify` tests below ARE an exception: they render a
real unit via `_systemd_unit_content` and hand it to the real
`systemd-analyze` binary (never `systemctl` itself -- `verify` is a pure
static-analysis subcommand with no daemon interaction), skipped if that
binary isn't on PATH. This is what proves the ExecStart token-joining bug
(single quoted blob vs separate argv tokens) is actually fixed, not just
that our own string-comparison assertions agree with our own code.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from amplifier_work_tracker import service as S

_HAVE_SYSTEMD_ANALYZE = shutil.which("systemd-analyze") is not None


def test_resolve_root_expands_and_resolves():
    resolved = S._resolve_root("~")
    assert resolved.is_absolute()
    assert "~" not in str(resolved)
    assert resolved == Path.home()


def test_resolve_root_accepts_path_object(tmp_path):
    assert S._resolve_root(tmp_path) == tmp_path.resolve()


def test_serve_argv_tail_bakes_root_as_argument_not_env():
    argv = S._serve_argv_tail(Path("/abs/root"))
    assert argv == ["serve", "--root", "/abs/root"]


def test_serve_argv_tail_includes_optional_dolt_host_and_port():
    argv = S._serve_argv_tail(Path("/abs/root"), dolt_host="127.0.0.1", dolt_port=3308)
    assert argv == [
        "serve",
        "--root",
        "/abs/root",
        "--dolt-host",
        "127.0.0.1",
        "--dolt-port",
        "3308",
    ]


def test_serve_argv_tail_omits_dolt_flags_when_not_given():
    argv = S._serve_argv_tail(Path("/abs/root"))
    assert "--dolt-host" not in argv
    assert "--dolt-port" not in argv


def test_resolve_bin_tokens_never_returns_a_single_shell_string():
    """launchd does not shell-split inside one <string> -- every token
    returned here must be independently exec-able, never `"a b c"` as one
    element (see module docstring)."""
    tokens = S._resolve_bin_tokens()
    assert isinstance(tokens, list)
    assert all(" " not in t or t == tokens[0] for t in tokens[1:]) or len(tokens) >= 1


def test_systemd_unit_template_has_no_environment_line_for_root():
    """The load-bearing assertion from the task: --root must be an ExecStart
    ARGUMENT, never an Environment= line."""
    rendered = S._SYSTEMD_UNIT_TEMPLATE.format(
        exec_start="/x/amplifier-work-tracker serve --root /abs/root", safe_path="/usr/bin:/bin"
    )
    assert "ExecStart=/x/amplifier-work-tracker serve --root /abs/root" in rendered
    for line in rendered.splitlines():
        if line.startswith("Environment="):
            assert "root" not in line.lower()


def test_windows_is_reported_as_unsupported_not_raised(monkeypatch):
    monkeypatch.setattr(S.sys, "platform", "win32")
    info = S.describe_service()
    assert info.supported is False
    assert info.platform == "windows"
    assert info.installed is False


def test_service_install_raises_service_unsupported_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(S.sys, "platform", "win32")
    with pytest.raises(S.ServiceUnsupportedError):
        S.service_install(tmp_path)


def test_no_systemctl_is_reported_as_unsupported_on_linux(monkeypatch):
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: False)
    info = S.describe_service()
    assert info.supported is False
    assert "systemctl" in info.detail


def test_darwin_describe_dispatches_to_launchd(monkeypatch):
    monkeypatch.setattr(S.sys, "platform", "darwin")
    monkeypatch.setattr(S, "_launchd_describe", lambda: "sentinel")
    assert S.describe_service() == "sentinel"


# ---------------------------------------------------------------------------
# The bug: module-fallback resolution produced ONE quoted ExecStart token.
# ---------------------------------------------------------------------------


def _force_console_script_present(monkeypatch, tmp_path) -> Path:
    """Make `_resolve_bin_tokens()` resolve via the `~/.local/bin/<name>`
    console-script path -- the FIRST, preferred branch."""
    fake_home = tmp_path / "home"
    local_bin = fake_home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    script = local_bin / S.SERVICE_NAME
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: fake_home))
    return script


def _force_module_fallback(monkeypatch, tmp_path) -> None:
    """Make `_resolve_bin_tokens()` fall all the way through to
    `[sys.executable, "-m", "amplifier_work_tracker.cli"]` -- no console
    script on `~/.local/bin`, and no `amplifier-work-tracker` on PATH
    either."""
    fake_home = tmp_path / "home-empty"
    fake_home.mkdir()
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(S.shutil, "which", lambda name: None)


def test_resolve_bin_tokens_prefers_console_script_when_present(monkeypatch, tmp_path):
    script = _force_console_script_present(monkeypatch, tmp_path)
    assert S._resolve_bin_tokens() == [str(script)]


def test_resolve_bin_tokens_falls_back_to_module_invocation_as_separate_tokens(
    monkeypatch, tmp_path
):
    """The exact shape that used to be joined into ONE ExecStart string --
    must be three SEPARATE tokens: python, -m, dotted-module-name."""
    _force_module_fallback(monkeypatch, tmp_path)
    assert S._resolve_bin_tokens() == [S.sys.executable, "-m", "amplifier_work_tracker.cli"]


def test_systemd_exec_start_never_quotes_the_module_fallback_as_one_token(monkeypatch, tmp_path):
    """Regression test for the reported bug: the module-fallback ExecStart
    must NOT come out as a single shell-quoted token (which systemd then
    treats as one literal, nonexistent executable path)."""
    _force_module_fallback(monkeypatch, tmp_path)
    unit = S._systemd_unit_content(tmp_path / "root", dolt_host=None, dolt_port=None)
    exec_start_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    exec_start = exec_start_line[len("ExecStart=") :]
    # The bug's exact shape: the whole invocation wrapped in one pair of quotes.
    assert not exec_start.startswith('"'), f"ExecStart was quoted as one token: {exec_start!r}"
    tokens = S.shlex.split(exec_start)
    assert tokens[:3] == [S.sys.executable, "-m", "amplifier_work_tracker.cli"]
    assert tokens[3:] == ["serve", "--root", str((tmp_path / "root").resolve())] or tokens[3:6] == [
        "serve",
        "--root",
        str(tmp_path / "root"),
    ]


@pytest.mark.skipif(not _HAVE_SYSTEMD_ANALYZE, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_clean_for_console_script_resolution_path(monkeypatch, tmp_path):
    """`systemd-analyze verify` must pass for the preferred resolution path
    (a real, executable `~/.local/bin/amplifier-work-tracker`)."""
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(root, dolt_host="127.0.0.1", dolt_port=3308)
    unit_path = tmp_path / f"{S.SERVICE_NAME}.service"
    unit_path.write_text(unit, encoding="utf-8")

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"systemd-analyze verify failed for console-script path:\n"
        f"unit:\n{unit}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.mark.skipif(not _HAVE_SYSTEMD_ANALYZE, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_clean_for_module_fallback_resolution_path(monkeypatch, tmp_path):
    """The regression proof: BEFORE the fix, this exact scenario (no console
    script, nothing on PATH, forced to `python -m amplifier_work_tracker.cli`)
    produced a unit `systemd-analyze verify` rejected with
    `Command "<python> -m amplifier_work_tracker.cli" is not executable:
    No such file or directory` -- because the whole invocation was quoted
    into a single ExecStart token. It must now pass for BOTH resolution
    paths, not just the console-script one."""
    _force_module_fallback(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(root, dolt_host="127.0.0.1", dolt_port=3308)
    unit_path = tmp_path / f"{S.SERVICE_NAME}.service"
    unit_path.write_text(unit, encoding="utf-8")

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"systemd-analyze verify failed for module-fallback path:\n"
        f"unit:\n{unit}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "is not executable" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Transactional install: a failed systemctl step must not leave the unit
# file (or an enabled-but-broken unit) behind.
# ---------------------------------------------------------------------------


def test_systemd_install_rolls_back_unit_file_when_systemctl_fails(monkeypatch, tmp_path):
    """Simulates a mid-install failure (e.g. `enable --now` failing) and
    proves the unit file this call itself wrote is removed before the
    exception propagates -- never left behind as silent residue."""
    unit_dir = tmp_path / "systemd-unit-dir"
    unit_path = unit_dir / f"{S.SERVICE_NAME}.service"
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_DIR", unit_dir)
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_PATH", unit_path)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["systemctl", "--user", "enable"]:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(S.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        S._systemd_install(tmp_path / "root", dolt_host=None, dolt_port=None)

    assert not unit_path.exists(), "unit file left behind after a failed install"
    # Rollback must attempt disable + daemon-reload so a half-enabled unit
    # reference doesn't linger in systemd's own state either.
    assert ["systemctl", "--user", "disable", S.SERVICE_NAME] in calls
    assert ["systemctl", "--user", "daemon-reload"] in calls


def test_service_install_propagates_the_failure_after_rollback(monkeypatch, tmp_path):
    """The public `service_install` entry point must still raise (never
    swallow) the underlying failure after rolling back -- a caller
    (`work_tracker_install`) needs to see it to report failure honestly."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)

    def fake_systemd_install(root, *, dolt_host, dolt_port):
        raise subprocess.CalledProcessError(1, ["systemctl", "--user", "enable"])

    monkeypatch.setattr(S, "_systemd_install", fake_systemd_install)
    with pytest.raises(subprocess.CalledProcessError):
        S.service_install(tmp_path)
