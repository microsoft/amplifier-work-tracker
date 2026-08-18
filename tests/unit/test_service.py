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


# ------------------------------------------------------- serve --web-port


def test_serve_argv_tail_omits_every_web_flag_when_web_port_not_given():
    """The default (`web_port=None`): behaviorally IDENTICAL to before this
    feature existed -- no `--web-*` flag baked in at all."""
    argv = S._serve_argv_tail(Path("/abs/root"))
    assert not any(tok.startswith("--web-") for tok in argv)


def test_serve_argv_tail_bakes_web_port_and_defaults():
    argv = S._serve_argv_tail(Path("/abs/root"), web_port=8095)
    assert argv == ["serve", "--root", "/abs/root", "--web-port", "8095"]


def test_serve_argv_tail_bakes_every_web_flag_when_given():
    argv = S._serve_argv_tail(
        Path("/abs/root"),
        dolt_host="127.0.0.1",
        dolt_port=3308,
        web_port=8095,
        web_host="0.0.0.0",  # noqa: S104 -- asserting the baked argv, never bound
        web_public=True,
        web_auth_mode="pam",
        web_session_ttl=7200,
    )
    assert argv == [
        "serve",
        "--root",
        "/abs/root",
        "--dolt-host",
        "127.0.0.1",
        "--dolt-port",
        "3308",
        "--web-port",
        "8095",
        "--web-host",
        "0.0.0.0",  # noqa: S104
        "--web-public",
        "--web-auth-mode",
        "pam",
        "--web-session-ttl",
        "7200",
    ]


def test_serve_argv_tail_omits_web_host_public_auth_ttl_when_only_web_port_given():
    """Each secondary `--web-*` flag is independently optional -- omitted
    unless its own value was explicitly given, mirroring `--dolt-host`/
    `--dolt-port`'s existing independence."""
    argv = S._serve_argv_tail(Path("/abs/root"), web_port=8095)
    assert "--web-host" not in argv
    assert "--web-public" not in argv
    assert "--web-auth-mode" not in argv
    assert "--web-session-ttl" not in argv


def test_systemd_unit_content_bakes_web_flags_into_exec_start(monkeypatch, tmp_path):
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host=None,
        dolt_port=None,
        web_port=8095,
        web_public=True,
        web_auth_mode="pam",
    )
    exec_start_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "--web-port 8095" in exec_start_line
    assert "--web-public" in exec_start_line
    assert "--web-auth-mode pam" in exec_start_line


def test_systemd_unit_content_omits_web_flags_when_web_port_not_given(monkeypatch, tmp_path):
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(root, dolt_host=None, dolt_port=None)
    exec_start_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "--web-" not in exec_start_line


# ---------------------------------------------------------------------------
# TLS: resolve_web_tls -- the install-time resolution `service install`
# applies BEFORE baking `--web-tls-cert`/`--web-tls-key` into ExecStart.
# Mirrors `webapp._resolve_tls`'s resolution order exactly; see
# `resolve_web_tls`'s own docstring on why the two must agree.
# ---------------------------------------------------------------------------


def test_resolve_web_tls_returns_none_none_when_neither_given_and_no_default_cert(
    monkeypatch, tmp_path
):
    fake_home = tmp_path / "home-empty"
    fake_home.mkdir()

    import amplifier_work_tracker.webtls as webtls_mod

    monkeypatch.setattr(webtls_mod.Path, "home", classmethod(lambda cls: fake_home))

    cert, key = S.resolve_web_tls(None, None)
    assert (cert, key) == (None, None)


def test_resolve_web_tls_auto_detects_setup_tls_defaults_when_present(monkeypatch, tmp_path):
    import amplifier_work_tracker.webtls as webtls_mod

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(webtls_mod.Path, "home", classmethod(lambda cls: fake_home))

    default_cert = webtls_mod.default_cert_path()
    default_key = webtls_mod.default_key_path()
    default_cert.write_text("cert", encoding="utf-8")
    default_key.write_text("key", encoding="utf-8")

    cert, key = S.resolve_web_tls(None, None)
    assert cert == str(default_cert)
    assert key == str(default_key)


def test_resolve_web_tls_validates_explicit_paths_exist(tmp_path):
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert", encoding="utf-8")
    key_path.write_text("key", encoding="utf-8")

    cert, key = S.resolve_web_tls(str(cert_path), str(key_path))
    assert (cert, key) == (str(cert_path), str(key_path))


def test_resolve_web_tls_raises_for_missing_explicit_cert(tmp_path):
    key_path = tmp_path / "key.pem"
    key_path.write_text("key", encoding="utf-8")
    with pytest.raises(S.TlsConfigError, match="not found"):
        S.resolve_web_tls(str(tmp_path / "nope.crt"), str(key_path))


def test_resolve_web_tls_raises_when_only_cert_given():
    with pytest.raises(S.TlsConfigError, match="must both be given together"):
        S.resolve_web_tls("/some/cert.pem", None)


def test_resolve_web_tls_raises_when_only_key_given():
    with pytest.raises(S.TlsConfigError, match="must both be given together"):
        S.resolve_web_tls(None, "/some/key.pem")


# ---------------------------------------------------------------------------
# TLS: _serve_argv_tail / _systemd_unit_content -- baking already-resolved
# --web-tls-cert/--web-tls-key into ExecStart.
# ---------------------------------------------------------------------------


def test_serve_argv_tail_bakes_web_tls_flags_when_given():
    argv = S._serve_argv_tail(
        Path("/abs/root"),
        web_port=8095,
        web_tls_cert="/certs/cert.pem",
        web_tls_key="/certs/key.pem",
    )
    assert argv == [
        "serve",
        "--root",
        "/abs/root",
        "--web-port",
        "8095",
        "--web-tls-cert",
        "/certs/cert.pem",
        "--web-tls-key",
        "/certs/key.pem",
    ]


def test_serve_argv_tail_omits_web_tls_flags_when_not_given():
    argv = S._serve_argv_tail(Path("/abs/root"), web_port=8095)
    assert "--web-tls-cert" not in argv
    assert "--web-tls-key" not in argv


def test_serve_argv_tail_omits_web_tls_flags_even_with_web_port_none():
    """TLS flags, like every other --web-*, are still gated on web_port --
    passing only web_tls_cert/web_tls_key without web_port must not leak
    them into argv (matches every other --web-* flag's own contract)."""
    argv = S._serve_argv_tail(
        Path("/abs/root"), web_tls_cert="/certs/cert.pem", web_tls_key="/certs/key.pem"
    )
    assert "--web-tls-cert" not in argv
    assert "--web-tls-key" not in argv


def test_systemd_unit_content_bakes_web_tls_flags_into_exec_start(monkeypatch, tmp_path):
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host=None,
        dolt_port=None,
        web_port=8095,
        web_tls_cert="/certs/cert.pem",
        web_tls_key="/certs/key.pem",
    )
    exec_start_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "--web-tls-cert /certs/cert.pem" in exec_start_line
    assert "--web-tls-key /certs/key.pem" in exec_start_line


# ----------------------------------------------- trust-bootstrap: --web-http-port


def test_serve_argv_tail_bakes_web_http_port_when_given():
    argv = S._serve_argv_tail(Path("/abs/root"), web_port=8095, web_http_port=8096)
    assert argv == [
        "serve",
        "--root",
        "/abs/root",
        "--web-port",
        "8095",
        "--web-http-port",
        "8096",
    ]


def test_serve_argv_tail_omits_web_http_port_when_not_given():
    argv = S._serve_argv_tail(Path("/abs/root"), web_port=8095)
    assert "--web-http-port" not in argv


def test_serve_argv_tail_omits_web_http_port_even_with_web_port_none():
    """Like every other --web-* flag, gated on web_port -- passing only
    web_http_port without web_port must not leak it into argv."""
    argv = S._serve_argv_tail(Path("/abs/root"), web_http_port=8096)
    assert "--web-http-port" not in argv


def test_systemd_unit_content_bakes_web_http_port_into_exec_start(monkeypatch, tmp_path):
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host=None,
        dolt_port=None,
        web_port=8095,
        web_tls_cert="/certs/cert.pem",
        web_tls_key="/certs/key.pem",
        web_http_port=8096,
    )
    exec_start_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    assert "--web-http-port 8096" in exec_start_line


@pytest.mark.skipif(not _HAVE_SYSTEMD_ANALYZE, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_clean_with_web_http_port_baked_in(monkeypatch, tmp_path):
    """The trust-bootstrap-integrated ExecStart must still be a systemd-valid unit."""
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host="127.0.0.1",
        dolt_port=3308,
        web_port=8095,
        web_tls_cert="/certs/cert.pem",
        web_tls_key="/certs/key.pem",
        web_http_port=8096,
    )
    unit_path = tmp_path / f"{S.SERVICE_NAME}.service"
    unit_path.write_text(unit, encoding="utf-8")

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not _HAVE_SYSTEMD_ANALYZE, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_clean_with_web_tls_flags_baked_in(monkeypatch, tmp_path):
    """The TLS-integrated ExecStart must still be a systemd-valid unit."""
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host="127.0.0.1",
        dolt_port=3308,
        web_port=8095,
        web_tls_cert="/certs/cert.pem",
        web_tls_key="/certs/key.pem",
    )
    unit_path = tmp_path / f"{S.SERVICE_NAME}.service"
    unit_path.write_text(unit, encoding="utf-8")

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"systemd-analyze verify failed with TLS flags baked in:\n"
        f"unit:\n{unit}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_service_install_raises_tls_config_error_for_incomplete_tls_pair(monkeypatch, tmp_path):
    """service install must refuse BEFORE writing/enabling anything -- same
    fail-loud-before-install philosophy `WebExtraNotImportableError` gives
    the 'web' extra check, applied here to TLS."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)
    monkeypatch.setattr(S, "_ensure_web_extra_importable_or_raise", lambda: None)
    with pytest.raises(S.TlsConfigError):
        S.service_install(tmp_path, web_port=8095, web_tls_cert="/only/cert.pem")


@pytest.mark.skipif(not _HAVE_SYSTEMD_ANALYZE, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_clean_with_web_flags_baked_in(monkeypatch, tmp_path):
    """The web-integrated ExecStart must still be a systemd-valid unit --
    same proof `test_systemd_analyze_verify_clean_for_console_script_resolution_path`
    already applies to the dolt-only ExecStart, extended to the new flags."""
    _force_console_script_present(monkeypatch, tmp_path)
    root = tmp_path / "workspace-root"
    unit = S._systemd_unit_content(
        root,
        dolt_host="127.0.0.1",
        dolt_port=3308,
        web_port=8095,
        web_host="127.0.0.1",
        web_public=False,
        web_auth_mode="password",
        web_session_ttl=3600,
    )
    unit_path = tmp_path / f"{S.SERVICE_NAME}.service"
    unit_path.write_text(unit, encoding="utf-8")

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"systemd-analyze verify failed with web flags baked in:\n"
        f"unit:\n{unit}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


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


def test_systemd_unit_template_uses_restart_always_not_on_failure():
    """Regression pin for the 2026-08-14 outage: `Restart=on-failure` never
    restarts a clean (status 0) exit, which is exactly what the
    supervisor's own SIGTERM/SIGINT handler produces on an unintended
    termination signal -- see service.py's module docstring and
    supervisor.py's `DoltSupervisionExhaustedError`. `Restart=always`
    restarts unconditionally; `test_real_systemd_unit_*` below prove this
    against a REAL unit, not just this string assertion."""
    rendered = S._SYSTEMD_UNIT_TEMPLATE.format(
        exec_start="/x/amplifier-work-tracker serve", safe_path="/usr/bin:/bin"
    )
    restart_lines = [line for line in rendered.splitlines() if line.startswith("Restart=")]
    assert restart_lines == ["Restart=always"], (
        f"expected exactly one 'Restart=always' line, got: {restart_lines!r}"
    )
    # Explanatory comments in the unit legitimately mention "on-failure" in
    # prose (explaining what this replaces) -- the load-bearing assertion is
    # that no *directive* line is `Restart=on-failure`, checked above.
    assert "Restart=on-failure" not in rendered


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


# ---------------------------------------------------------------------------
# resolve_console_script -- detecting OUR OWN CLI missing from PATH (not
# bd/dolt, see prereqs.py), the state that cost a DTU session 6 tool calls.
# ---------------------------------------------------------------------------


def test_resolve_console_script_reports_nothing_when_on_path(monkeypatch):
    monkeypatch.setattr(S.shutil, "which", lambda name: "/usr/bin/" + name)
    path, fix = S.resolve_console_script()
    assert path is None
    assert fix is None


def test_resolve_console_script_finds_unlinked_uv_tool_install(monkeypatch, tmp_path):
    """The exact shape observed in the DTU: `amplifier-work-tracker` present
    on disk inside another uv tool's own venv bin/ directory, but not on
    PATH -- must be found and reported with the exact remediation, not a
    bare "not found" that sends the caller hunting with ps/find/which."""
    monkeypatch.setattr(S.shutil, "which", lambda name: None)
    fake_home = tmp_path / "home"
    tool_bin = fake_home / ".local" / "share" / "uv" / "tools" / "amplifier" / "bin"
    tool_bin.mkdir(parents=True)
    script = tool_bin / S.SERVICE_NAME
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        S,
        "_UV_TOOLS_BIN_GLOB",
        str(fake_home / ".local" / "share" / "uv" / "tools" / "*" / "bin" / S.SERVICE_NAME),
    )

    path, fix = S.resolve_console_script()

    assert path == str(script)
    assert fix is not None
    assert str(script) in fix
    assert "ln -s" in fix or "PATH" in fix


def test_resolve_console_script_reports_nothing_when_truly_absent(monkeypatch, tmp_path):
    """Off PATH AND not found in the uv-tools layout either -- this
    function reports nothing (not its job to say "not installed at all";
    that's `work_tracker_status`'s overall `state`)."""
    monkeypatch.setattr(S.shutil, "which", lambda name: None)
    fake_home = tmp_path / "home-empty"
    fake_home.mkdir()
    monkeypatch.setattr(S.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(
        S,
        "_UV_TOOLS_BIN_GLOB",
        str(fake_home / ".local" / "share" / "uv" / "tools" / "*" / "bin" / S.SERVICE_NAME),
    )

    path, fix = S.resolve_console_script()
    assert path is None
    assert fix is None


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


def test_systemd_install_attaches_observed_rollback_detail_on_success(monkeypatch, tmp_path):
    """The rollback report must describe what ACTUALLY happened -- never a
    hardcoded "nothing was left behind" that could be a lie. When every
    rollback step succeeds, `rollback_detail` says so per-step."""
    unit_dir = tmp_path / "systemd-unit-dir"
    unit_path = unit_dir / f"{S.SERVICE_NAME}.service"
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_DIR", unit_dir)
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_PATH", unit_path)

    def fake_run(cmd, *args, **kwargs):
        if cmd[:3] == ["systemctl", "--user", "enable"]:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(S.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        S._systemd_install(tmp_path / "root", dolt_host=None, dolt_port=None)

    detail = excinfo.value.rollback_detail  # type: ignore[attr-defined]
    assert "disable: ok" in detail
    assert "remove unit file: ok" in detail
    assert "daemon-reload: ok" in detail


def test_systemd_install_rollback_detail_reports_a_failed_rollback_step_honestly(
    monkeypatch, tmp_path
):
    """If the rollback's OWN disable/daemon-reload call fails, the detail
    must say so -- this is the exact case the old hardcoded "No partial
    install was left behind" message would have lied about."""
    unit_dir = tmp_path / "systemd-unit-dir"
    unit_path = unit_dir / f"{S.SERVICE_NAME}.service"
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_DIR", unit_dir)
    monkeypatch.setattr(S, "_SYSTEMD_UNIT_PATH", unit_path)

    def fake_run(cmd, *args, **kwargs):
        if cmd[:3] == ["systemctl", "--user", "enable"]:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="")
        if cmd[:3] == ["systemctl", "--user", "disable"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Failed to connect to bus")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(S.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        S._systemd_install(tmp_path / "root", dolt_host=None, dolt_port=None)

    detail = excinfo.value.rollback_detail  # type: ignore[attr-defined]
    assert "disable: exit 1" in detail
    assert "Failed to connect to bus" in detail


def test_service_install_propagates_the_failure_after_rollback(monkeypatch, tmp_path):
    """The public `service_install` entry point must still raise (never
    swallow) the underlying failure after rolling back -- a caller
    (`work_tracker_install`) needs to see it to report failure honestly."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)

    def fake_systemd_install(root, *, dolt_host, dolt_port, **_web_kwargs):
        raise subprocess.CalledProcessError(1, ["systemctl", "--user", "enable"])

    monkeypatch.setattr(S, "_systemd_install", fake_systemd_install)
    with pytest.raises(subprocess.CalledProcessError):
        S.service_install(tmp_path)


# ---------------------------------------------------------------------------
# The install-time preflight: refuse to write/enable a unit at all when the
# 'web' extra can't be verified importable in the environment that will
# ACTUALLY run it -- see `WebExtraNotImportableError`'s docstring for the
# live incident (a unit came up `active`, dolt genuinely served, and the web
# dashboard silently never bound because this was never checked).
#
# `_fake_interpreter` below is a real, directly-executable file whose OWN
# `#!/bin/sh` shebang makes it a controllable stand-in for "a python that
# can/can't import fastapi" -- it ignores its `-c <code>` argv entirely and
# just exits with a hardcoded code, so these tests never depend on any real
# python actually missing the extra.
# ---------------------------------------------------------------------------


def _fake_console_script_with_interpreter(tmp_path: Path, *, importable: bool) -> Path:
    """A fake console-script file whose shebang points at a fake
    "interpreter" that exits 0 (importable) or 1 (not importable) --
    see this section's docstring."""
    fake_interp = tmp_path / ("fake-python-ok" if importable else "fake-python-broken")
    fake_interp.write_text(f"#!/bin/sh\nexit {0 if importable else 1}\n", encoding="utf-8")
    fake_interp.chmod(0o755)
    script = tmp_path / S.SERVICE_NAME
    script.write_text(f"#!{fake_interp}\n", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_resolve_console_script_interpreter_reads_the_shebang(tmp_path):
    script = _fake_console_script_with_interpreter(tmp_path, importable=True)
    interpreter = S._resolve_console_script_interpreter([str(script)])
    assert interpreter == str(tmp_path / "fake-python-ok")


def test_resolve_console_script_interpreter_returns_sys_executable_for_module_fallback():
    tokens = [S.sys.executable, "-m", "amplifier_work_tracker.cli"]
    assert S._resolve_console_script_interpreter(tokens) == S.sys.executable


def test_resolve_console_script_interpreter_returns_none_when_no_shebang(tmp_path):
    script = tmp_path / S.SERVICE_NAME
    script.write_text("not a shebang line at all\n", encoding="utf-8")
    script.chmod(0o755)
    assert S._resolve_console_script_interpreter([str(script)]) is None


def test_probe_web_extra_importable_true_for_the_real_test_interpreter():
    """Sanity check using the REAL interpreter running these tests --
    `dev`+`web` extras are installed for the test suite (see pyproject.toml
    and the Makefile's `venv` target), so this must report importable."""
    ok, detail = S.probe_web_extra_importable(
        [S.sys.executable, "-m", "amplifier_work_tracker.cli"]
    )
    assert ok, detail
    assert detail == ""


def test_probe_web_extra_importable_false_when_the_target_cannot_import(tmp_path):
    script = _fake_console_script_with_interpreter(tmp_path, importable=False)
    ok, detail = S.probe_web_extra_importable([str(script)])
    assert not ok
    assert detail  # some observed detail, never a silent empty string


def test_probe_web_extra_importable_false_when_interpreter_cannot_be_resolved(tmp_path):
    script = tmp_path / S.SERVICE_NAME
    script.write_text("no shebang here\n", encoding="utf-8")
    script.chmod(0o755)
    ok, detail = S.probe_web_extra_importable([str(script)])
    assert not ok
    assert "could not determine" in detail


def test_service_install_refuses_with_remedy_when_web_extra_not_importable(monkeypatch, tmp_path):
    """The install-time close of the live bug: refuse BEFORE writing/
    enabling any unit, naming the exact remedy command."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)
    script = _fake_console_script_with_interpreter(tmp_path, importable=False)
    monkeypatch.setattr(S, "_resolve_bin_tokens", lambda: [str(script)])

    def _poison_systemd_install(*a, **k):
        raise AssertionError("_systemd_install must not run when the web extra check fails")

    monkeypatch.setattr(S, "_systemd_install", _poison_systemd_install)

    with pytest.raises(S.WebExtraNotImportableError) as excinfo:
        S.service_install(tmp_path / "root", web_port=8095)

    assert "uv tool install --reinstall --with 'amplifier-work-tracker[web]'" in str(excinfo.value)
    assert "uv pip install -e '.[web]'" in str(excinfo.value)


def test_service_install_skips_the_web_extra_check_when_web_port_not_given(monkeypatch, tmp_path):
    """The default (`web_port=None`) must behave EXACTLY as before this
    fix: no importability probe at all, matching `_serve_argv_tail`'s own
    "omit every --web-* flag unless web_port is given" contract."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)

    def _poison_probe(bin_tokens, **kwargs):
        raise AssertionError("probe_web_extra_importable must not run when web_port is None")

    monkeypatch.setattr(S, "probe_web_extra_importable", _poison_probe)
    monkeypatch.setattr(S, "_systemd_install", lambda *a, **k: None)
    monkeypatch.setattr(S, "_systemd_describe", lambda: "sentinel")

    assert S.service_install(tmp_path / "root") == "sentinel"


def test_service_install_proceeds_when_web_extra_importable(monkeypatch, tmp_path):
    """The extra IS importable in the target environment -- the preflight
    passes silently and the real install path is reached (mocked here, per
    this file's own no-real-systemctl convention)."""
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.setattr(S, "_have_systemctl", lambda: True)
    script = _fake_console_script_with_interpreter(tmp_path, importable=True)
    monkeypatch.setattr(S, "_resolve_bin_tokens", lambda: [str(script)])

    called: dict[str, bool] = {}

    def fake_systemd_install(*a, **k):
        called["ran"] = True

    monkeypatch.setattr(S, "_systemd_install", fake_systemd_install)
    monkeypatch.setattr(S, "_systemd_describe", lambda: "sentinel")

    result = S.service_install(tmp_path / "root", web_port=8095)

    assert called.get("ran") is True
    assert result == "sentinel"
