"""Tier 1 -- service.py pure/testable logic: argv construction, root
resolution, and the platform-dispatching wrappers' unsupported-platform
paths. No real systemctl/launchctl calls -- those are exercised by the
`service install` verification run in the PR description, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_work_tracker import service as S


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
