"""Run the supervisor (`amplifier-work-tracker serve`) as a system service
(systemd --user on Linux, launchd on macOS) so the shared dolt server, reap,
and notify sweeps survive logout and reboot instead of living in a terminal
someone has to keep open.

Modeled on amplifier-browser-bridge's `service.py`, which is itself modeled on
muxplex/service.py -- see those modules' docstrings for the traps a
service-management module of this shape has already hit in production. Kept
from them, deliberately:

  - systemd **--user** (never a system-wide unit, never sudo). A work-queue
    supervisor running as root would be indefensible -- this stays scoped to
    the invoking user's own systemd/launchd instance.
  - launchd's ``ProgramArguments`` needs each argv token as its OWN
    ``<string>``; launchd does not shell-split inside one, so an element like
    ``"amplifier-work-tracker serve"`` is treated as a literal (nonexistent)
    executable name and the job silently fails to start. See
    `_resolve_bin_tokens`.
  - Gate every systemd operation on `systemctl` actually being on PATH --
    never assume a Linux box uses systemd (containers, WSL without systemd
    enabled, other init systems all exist).
  - bootout-and-wait before bootstrap on macOS, so a restart/reinstall can't
    race launchd's asynchronous teardown and silently leave the OLD process
    serving (the exact bug amplifier-browser-bridge's own test suite
    documents for `service restart`).
  - install: daemon-reload -> enable --now -> restart. The third line is not
    redundant -- `enable --now` is a no-op on an already-running unit, so a
    re-install (new --root) would silently keep serving the STALE argument
    without it.
  - uninstall removes the unit ONLY. It never touches the dolt data
    directory or the workspace root -- that is the work queue, and deleting
    it on uninstall would be catastrophic data loss disguised as cleanup.
  - Restart=always, not on-failure -- measured outage, 2026-08-14: something
    sent SIGTERM to a whole group of user services (this one included).
    `_request_stop` in supervisor.py handles that signal and exits 0 (a
    "clean" shutdown, by design, for genuine `systemctl stop`/`disable`
    requests). `Restart=on-failure` never restarts a clean (status 0) exit
    -- so the service stayed `inactive` until a human noticed and manually
    restarted it, port 3308 dead the whole time. `Restart=always` restarts
    unconditionally on ANY exit (clean or not), any signal, or a timeout.
    This is still safe for a genuinely-intended stop: systemd honors an
    explicit `systemctl --user stop` (and `disable`) regardless of the
    configured Restart= policy -- an operator-requested stop is never
    second-guessed. Verified empirically against a real unit in
    tests/unit/test_service.py (`Restart=always` unit clean-exits and comes
    back; the same unit, once explicitly stopped, stays stopped) rather
    than assumed from the systemd docs alone.

The one thing genuinely different from amplifier-browser-bridge's hub: this
service has exactly ONE install-time input that matters -- the workspace
--root. Per the "load-bearing --root" design note in cli.py, that path is
baked into the unit as an explicit ExecStart ARGUMENT (`serve --root <abs>`),
never as an `Environment=`/`EnvironmentVariables` line -- systemd/launchd do
not reliably inherit the installing shell's environment, and baking the value
in as an argument sidesteps that class of bug entirely for the one value that
actually needs to survive into the unit.
"""

from __future__ import annotations

import glob
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

SERVICE_NAME = "amplifier-work-tracker"

_SYSTEMD_UNIT_DIR: Path = Path.home() / ".config" / "systemd" / "user"
_SYSTEMD_UNIT_PATH: Path = _SYSTEMD_UNIT_DIR / f"{SERVICE_NAME}.service"

_LAUNCHD_LABEL: str = f"com.{SERVICE_NAME}"
_LAUNCHD_PLIST_DIR: Path = Path.home() / "Library" / "LaunchAgents"
_LAUNCHD_PLIST_PATH: Path = _LAUNCHD_PLIST_DIR / f"{_LAUNCHD_LABEL}.plist"
_LAUNCHD_LOG_DIR: Path = Path.home() / "Library" / "Logs" / SERVICE_NAME

_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=amplifier-work-tracker supervisor (shared dolt server + reap/notify)
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
# Restart=always, not on-failure -- see this module's docstring section
# "Restart=always, not on-failure" for the outage this fixes. The
# supervisor's own SIGTERM/SIGINT handler (`_request_stop` in supervisor.py)
# exits 0 on an unintended termination signal (e.g. something SIGTERM'd a
# whole group of user services), and `on-failure` never restarts a clean
# (status 0) exit -- that is precisely how the 2026-08-14 outage stayed down
# until a human noticed. `always` restarts regardless of exit status,
# signal, or timeout. This is still safe for an OPERATOR-requested stop:
# `systemctl --user stop` (or `disable`) is honored by systemd regardless of
# Restart= policy -- an explicit stop request is never treated as a failure
# to recover from. Verified empirically against a real unit (not merely
# read from the docs) in tests/unit/test_service.py.
Restart=always
RestartSec=5s
TimeoutStopSec=10
KillMode=mixed
Environment=PATH={safe_path}
# --root is baked into ExecStart above as an explicit argument, not an
# Environment= line here -- see this module's docstring. WorkingDirectory is
# belt-and-suspenders (every path the supervisor needs is already absolute),
# set to the user's home so a hypothetical future relative-path argument
# fails predictably rather than wherever systemd's own default happens to be.
WorkingDirectory=%h

[Install]
WantedBy=default.target
"""

_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{program_arguments_xml}
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{safe_path}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{err_path}</string>
</dict>
</plist>
"""

_WINDOWS_UNSUPPORTED_DETAIL = (
    "service management is not implemented for Windows in this release -- there is no "
    "systemd/launchd equivalent this module drives there yet. Run `amplifier-work-tracker "
    "serve --root <path>` directly instead, or wrap it yourself as a real Windows service "
    "(Task Scheduler set to run at log on, or NSSM/WinSW)."
)


class ServiceUnsupportedError(RuntimeError):
    """Raised when a service operation is requested on a platform/configuration this
    module cannot drive (Windows, or Linux without `systemctl` on PATH). Never a
    silent no-op or a quiet fallback to a foreground process -- see module docstring.
    """


@dataclass
class ServiceInfo:
    """Structured, read-only description of the current service state -- what
    `amplifier-work-tracker service status` prints for a human, and what `doctor`
    consumes to tell "installed but not running" apart from "never installed" or
    "this platform can't run a service at all."
    """

    platform: str  # "linux", "darwin", "windows", or "other"
    supported: bool
    installed: bool
    active: bool | None  # None when not installed, or state genuinely unknown
    unit_path: Path | None
    detail: str


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def _is_darwin() -> bool:
    return sys.platform == "darwin"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _have_systemctl() -> bool:
    """Gates every systemd operation -- never assume a Linux box uses systemd."""
    return shutil.which("systemctl") is not None


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _resolve_bin_tokens() -> list[str]:
    """The `amplifier-work-tracker` executable as separate argv tokens, for launchd.

    launchd's ProgramArguments does NOT shell-split inside a single
    ``<string>`` -- an element like ``"python3 -m amplifier_work_tracker.cli"``
    is a literal (nonexistent) executable name, and the job silently fails to
    start. Each element returned here must become its own ``<string>``.

    Prefers the stable `~/.local/bin/amplifier-work-tracker` console-script
    symlink an install creates (survives reinstall); falls back to a PATH
    lookup, then to an explicit, correctly-split `[python, -m, ...]`
    invocation.
    """
    local_bin = Path.home() / ".local" / "bin" / SERVICE_NAME
    if local_bin.exists() and os.access(str(local_bin), os.X_OK):
        return [str(local_bin)]
    which = shutil.which(SERVICE_NAME)
    if which:
        return [which]
    return [sys.executable, "-m", "amplifier_work_tracker.cli"]


# The one directory layout `uv tool install` actually uses:
# ~/.local/share/uv/tools/<tool-name>/bin/<console-script>. A console script
# that isn't the primary entry point of the tool it was installed alongside
# (e.g. bundled in via `--with`) can land here without ever getting a
# top-level PATH shim.
_UV_TOOLS_BIN_GLOB = str(
    Path.home() / ".local" / "share" / "uv" / "tools" / "*" / "bin" / SERVICE_NAME
)


def resolve_console_script() -> tuple[str | None, str | None]:
    """Is the `amplifier-work-tracker` console script itself reachable by
    name on PATH? This is deliberately NOT about `bd`/`dolt` -- those are
    prerequisites this package depends on (see `prereqs.py`). This is about
    our OWN CLI.

    `uv tool install` can leave a SECONDARY console script installed but
    unlinked: present on disk, invisible to `shutil.which`, when it lands
    inside another tool's own venv (e.g. bundled in via `--with`) rather
    than getting its own top-level PATH shim. Measured cost of not
    detecting this in a DTU run: a session that got `command not found`
    for `amplifier-work-tracker doctor`, then spent 6 tool calls (`ps`,
    `find`, `which`) hunting for the binary by hand, and along the way
    reported a spurious `not_installed` state because it never found the
    binary it needed to ask.

    Returns `(resolved_path, fix)`. Both are `None` when the script is
    already on PATH (nothing to report -- this is the common case and
    callers should treat it as "no issue"). When off PATH but found via
    the one `uv tool install` layout, returns its absolute path plus the
    exact remediation (a stable `~/.local/bin` symlink -- the same
    resolution `_resolve_bin_tokens` already prefers -- or a direct PATH
    export), never a bare "not found" that sends the caller hunting.
    """
    if shutil.which(SERVICE_NAME):
        return None, None
    matches = sorted(p for p in glob.glob(_UV_TOOLS_BIN_GLOB) if os.access(p, os.X_OK))
    if not matches:
        return None, None
    resolved = matches[0]
    target = Path.home() / ".local" / "bin" / SERVICE_NAME
    fix = (
        f"'{SERVICE_NAME}' is not on PATH, but IS installed at {resolved} -- most "
        f"likely `uv tool install` put it inside another tool's own venv (e.g. bundled "
        f"in via --with) instead of giving it its own top-level PATH shim. Fix: "
        f"ln -s {resolved} {target}  (create ~/.local/bin first if it doesn't exist, "
        f"and make sure that directory is on PATH), or add its directory directly: "
        f'export PATH="{Path(resolved).parent}:$PATH"'
    )
    return resolved, fix


def _serve_argv_tail(
    root: Path,
    *,
    dolt_host: str | None = None,
    dolt_port: int | None = None,
) -> list[str]:
    """The `serve` subcommand and its arguments, explicit and absolute --
    never an environment variable a service manager might not propagate.
    Shared by both the systemd (joined into one ExecStart string) and
    launchd (kept as separate argv tokens) install paths so the two can
    never drift apart on what gets baked in."""
    argv = ["serve", "--root", str(root)]
    if dolt_host is not None:
        argv += ["--dolt-host", dolt_host]
    if dolt_port is not None:
        argv += ["--dolt-port", str(dolt_port)]
    return argv


def _resolve_root(root: str | Path) -> Path:
    """Absolute path to bake into the unit/plist. Never left relative -- a
    service has no meaningful "current directory," and a relative --root
    baked into a unit would resolve against whatever WorkingDirectory happens
    to be rather than what the operator meant."""
    return Path(root).expanduser().resolve()


# ---------------------------------------------------------------------------
# systemd (Linux)
# ---------------------------------------------------------------------------


def _systemd_unit_content(root: Path, *, dolt_host: str | None, dolt_port: int | None) -> str:
    """Render the systemd unit's text, and nothing else -- pure and directly
    testable (e.g. with `systemd-analyze verify` against the rendered text)
    without touching a real systemd or writing to `_SYSTEMD_UNIT_PATH`.

    Uses `_resolve_bin_tokens()` -- the SAME token-list resolver launchd's
    `_launchd_install` uses -- rather than a systemd-only string resolver.
    Every element of `exec_argv` is therefore a single, independently
    exec-able token (an absolute path, `-m`, or a dotted module name -- never
    a token containing embedded whitespace of its own). `shlex.join` then
    quotes ONLY tokens that need it (e.g. a path containing a space),
    never accidentally folding multiple tokens into one quoted blob. Before
    this, the module-fallback token (`f"{sys.executable} -m ...cli"`, a
    single string already containing spaces) was passed as ONE list element,
    so `shlex.join` quoted the whole thing and systemd treated it as a
    single, nonexistent executable path -- see this module's docstring and
    `tests/unit/test_service.py`'s `systemd-analyze verify` regression tests
    for both resolution paths.
    """
    exec_argv = [
        *_resolve_bin_tokens(),
        *_serve_argv_tail(root, dolt_host=dolt_host, dolt_port=dolt_port),
    ]
    exec_start = shlex.join(exec_argv)
    safe_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return _SYSTEMD_UNIT_TEMPLATE.format(exec_start=exec_start, safe_path=safe_path)


def _systemd_call(args: list[str], *, check: bool) -> subprocess.CompletedProcess:
    """Every non-interactive systemctl invocation in this module goes
    through here: `capture_output=True` so nothing -- e.g. a
    session-bus-less container's `Failed to connect to bus: No medium
    found` -- prints directly to the caller's terminal outside of any
    tool result. `_systemd_status`/`_systemd_logs` are the deliberate
    exception (they exist specifically to stream/print for a human at a
    terminal) and do NOT go through this helper."""
    return subprocess.run(args, capture_output=True, text=True, check=check)


def _observe(label: str, result: subprocess.CompletedProcess) -> str:
    """One line describing what a rollback step actually did -- OBSERVED
    from the real subprocess result, never asserted. Used to build
    `rollback_detail` so a caller (`work_tracker_install`) can report what
    happened instead of a hardcoded claim that may not be true."""
    if result.returncode == 0:
        return f"{label}: ok"
    detail = (result.stderr or result.stdout or "").strip()[:150]
    return f"{label}: exit {result.returncode}" + (f" ({detail})" if detail else "")


def _systemd_rollback_unit_file() -> str:
    """Best-effort rollback after a failed install: disable, remove the
    unit file THIS call wrote, daemon-reload. Returns a human-readable,
    OBSERVED report of each step -- never a hardcoded assertion that
    nothing was left behind."""
    steps = [
        _observe(
            "disable", _systemd_call(["systemctl", "--user", "disable", SERVICE_NAME], check=False)
        )
    ]
    existed = _SYSTEMD_UNIT_PATH.exists()
    try:
        _SYSTEMD_UNIT_PATH.unlink(missing_ok=True)
        steps.append(
            f"remove unit file: ok ({_SYSTEMD_UNIT_PATH})"
            if existed
            else f"remove unit file: nothing to remove ({_SYSTEMD_UNIT_PATH} did not exist)"
        )
    except OSError as e:
        steps.append(f"remove unit file: FAILED ({e})")
    steps.append(
        _observe(
            "daemon-reload", _systemd_call(["systemctl", "--user", "daemon-reload"], check=False)
        )
    )
    return "; ".join(steps)


def _systemd_install(root: Path, *, dolt_host: str | None, dolt_port: int | None) -> None:
    unit_content = _systemd_unit_content(root, dolt_host=dolt_host, dolt_port=dolt_port)

    _SYSTEMD_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    _SYSTEMD_UNIT_PATH.write_text(unit_content, encoding="utf-8")
    try:
        _systemd_call(["systemctl", "--user", "daemon-reload"], check=True)
        _systemd_call(["systemctl", "--user", "enable", "--now", SERVICE_NAME], check=True)
        # `enable --now` is a no-op on an already-running unit, so a
        # re-install (new --root, new dolt host/port) would silently keep
        # serving the STALE arguments without this. `restart` also starts a
        # stopped unit, so it is safe on both first install and re-install.
        _systemd_call(["systemctl", "--user", "restart", SERVICE_NAME], check=True)
    except subprocess.CalledProcessError as e:
        # Transactional: a failure at any systemctl step below the unit file
        # write must not leave that file (or an enabled-but-broken unit)
        # behind -- see `service_install`'s rollback contract. Best-effort,
        # never raising a SECOND exception that would mask the original.
        # `rollback_detail` carries what ACTUALLY happened at each rollback
        # step -- attached to the exception rather than asserted by a
        # caller -- see `WorkTrackerInstallTool.execute`.
        e.rollback_detail = _systemd_rollback_unit_file()  # type: ignore[attr-defined]
        raise


def _systemd_uninstall() -> None:
    # stop/disable are intentionally NOT check=True -- uninstalling an
    # already-stopped or never-enabled unit is a normal, successful
    # uninstall, not an error.
    _systemd_call(["systemctl", "--user", "stop", SERVICE_NAME], check=False)
    _systemd_call(["systemctl", "--user", "disable", SERVICE_NAME], check=False)
    _SYSTEMD_UNIT_PATH.unlink(missing_ok=True)
    _systemd_call(["systemctl", "--user", "daemon-reload"], check=False)


def _systemd_start() -> None:
    _systemd_call(["systemctl", "--user", "start", SERVICE_NAME], check=True)


def _systemd_stop() -> None:
    # Not check=True -- stopping an already-stopped service is a normal no-op.
    _systemd_call(["systemctl", "--user", "stop", SERVICE_NAME], check=False)


def _systemd_restart() -> None:
    _systemd_call(["systemctl", "--user", "restart", SERVICE_NAME], check=True)


def _systemd_status() -> None:
    # Not check=True -- a stopped/failed unit is a normal `status` outcome
    # (nonzero exit), not a reason to raise.
    subprocess.run(["systemctl", "--user", "status", SERVICE_NAME, "--no-pager"], check=False)


def _systemd_logs() -> None:
    try:
        subprocess.run(["journalctl", "--user", "-u", SERVICE_NAME, "-f"], check=False)
    except KeyboardInterrupt:
        pass


def _systemd_describe() -> ServiceInfo:
    installed = _SYSTEMD_UNIT_PATH.is_file()
    active: bool | None = None
    if installed:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True,
            check=False,
        )
        active = result.stdout.strip() == "active"
    if not installed:
        detail = f"not installed (would install at {_SYSTEMD_UNIT_PATH})"
    elif active:
        detail = f"installed and active (unit: {_SYSTEMD_UNIT_PATH})"
    else:
        detail = f"installed but NOT active (unit: {_SYSTEMD_UNIT_PATH})"
    return ServiceInfo(
        platform="linux",
        supported=True,
        installed=installed,
        active=active,
        unit_path=_SYSTEMD_UNIT_PATH if installed else None,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# launchd (macOS)
# ---------------------------------------------------------------------------


def _launchd_is_loaded(uid: int) -> bool:
    """True if launchd currently knows about our label."""
    return (
        subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{_LAUNCHD_LABEL}"], capture_output=True, check=False
        ).returncode
        == 0
    )


def _launchd_bootout_and_wait(uid: int, *, timeout: float = 10.0) -> bool:
    """bootout the job and WAIT for launchd to actually finish tearing it down.

    `launchctl bootout` returns before the job is gone. Not waiting is the
    exact bug that made amplifier-browser-bridge's `service restart` a
    silent no-op: bootstrap raced the teardown, saw the OLD job still
    loaded, and reported success while the old process kept serving. Stop
    must mean stopped before start can mean started.

    Returns True if the job is confirmed gone, False if it outlived the timeout.
    """
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{_LAUNCHD_LABEL}"], capture_output=True, check=False
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _launchd_is_loaded(uid):
            return True
        time.sleep(0.25)
    return not _launchd_is_loaded(uid)


def _launchd_bootstrap(uid: int, *, attempts: int = 6, accept_already_loaded: bool = False) -> None:
    """bootstrap the plist, retrying through launchd's asynchronous teardown.

    Exit 5 ("Input/output error") right after a bootout is the teardown
    race, not a real failure, so it is retried.

    `accept_already_loaded` is the load-bearing distinction. For `start` --
    "make sure it is running" -- finding it already loaded IS the desired
    state. For `install` and `restart` the caller has just booted the job
    out and is replacing it, so an already-loaded job means the OLD one
    survived; reporting success there is a lie that hides a failed upgrade.
    Only `start` opts in.

    Real failures fail LOUDLY, with launchd's own stderr and an actionable
    hint rather than a raw CalledProcessError traceback.
    """
    last = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(0.5)
        last = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(_LAUNCHD_PLIST_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        if last.returncode == 0:
            return
        # Exit 5 (EIO) and 37 are the teardown race; retry. Anything else is a
        # genuine error and retrying only delays the report.
        if last.returncode not in (5, 37):
            break

    if accept_already_loaded and _launchd_is_loaded(uid):
        return

    detail = (last.stderr or last.stdout or "").strip() if last else ""
    code = last.returncode if last else "unknown"
    raise RuntimeError(
        f"launchctl bootstrap failed (exit {code})"
        + (f": {detail}" if detail else "")
        + f"\n  The service plist is at {_LAUNCHD_PLIST_PATH}."
        + f"\n  Try: launchctl bootout gui/{uid}/{_LAUNCHD_LABEL} && "
        + f"launchctl bootstrap gui/{uid} {_LAUNCHD_PLIST_PATH}"
        + "\n  Or run 'amplifier-work-tracker serve --root <path>' directly, no service manager."
    )


def _launchd_install(root: Path, *, dolt_host: str | None, dolt_port: int | None) -> None:
    bin_tokens = _resolve_bin_tokens()
    argv = bin_tokens + _serve_argv_tail(root, dolt_host=dolt_host, dolt_port=dolt_port)
    # Each argv token is its own <string> element. launchd does NOT
    # shell-split inside a <string>, so the whole command must NEVER be put
    # into one element.
    program_arguments_xml = "\n".join(
        f"        <string>{_xml_escape(arg)}</string>" for arg in argv
    )
    base_path = os.environ.get("PATH", "/usr/bin:/bin")
    safe_path = f"/opt/homebrew/bin:/usr/local/bin:{base_path}"

    _LAUNCHD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    plist_content = _LAUNCHD_PLIST_TEMPLATE.format(
        label=_LAUNCHD_LABEL,
        program_arguments_xml=program_arguments_xml,
        safe_path=safe_path,
        log_path=str(_LAUNCHD_LOG_DIR / "supervisor.log"),
        err_path=str(_LAUNCHD_LOG_DIR / "supervisor.err"),
    )
    _LAUNCHD_PLIST_DIR.mkdir(parents=True, exist_ok=True)
    _LAUNCHD_PLIST_PATH.write_text(plist_content, encoding="utf-8")

    uid = os.getuid()
    # bootstrap on an already-loaded label fails with EEXIST-style errors, so
    # bootout first (ignore failure if it wasn't loaded) to force the new
    # plist's arguments (e.g. an updated --root) to actually apply on
    # re-install, not just on first install.
    _launchd_bootout_and_wait(uid)
    try:
        _launchd_bootstrap(uid)
    except RuntimeError as e:
        # Transactional, matching _systemd_install: a bootstrap failure must
        # not leave a written-but-never-loaded plist behind -- see
        # `service_install`'s rollback contract. `rollback_detail` records
        # what was OBSERVED (plist present and removed vs. already gone vs.
        # removal itself failing) -- never a hardcoded assertion that
        # nothing was left behind. See `WorkTrackerInstallTool.execute`.
        existed = _LAUNCHD_PLIST_PATH.exists()
        try:
            _LAUNCHD_PLIST_PATH.unlink(missing_ok=True)
            detail = (
                f"remove plist: ok ({_LAUNCHD_PLIST_PATH})"
                if existed
                else f"remove plist: nothing to remove ({_LAUNCHD_PLIST_PATH} did not exist)"
            )
        except OSError as unlink_err:
            detail = f"remove plist: FAILED ({unlink_err})"
        e.rollback_detail = detail  # type: ignore[attr-defined]
        raise


def _launchd_uninstall() -> None:
    uid = os.getuid()
    # Not check=True -- bootout on an already-unloaded (or never-loaded)
    # label is a normal, successful uninstall, not an error.
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{_LAUNCHD_LABEL}"], check=False)
    _LAUNCHD_PLIST_PATH.unlink(missing_ok=True)


def _launchd_start() -> None:
    _launchd_bootstrap(os.getuid(), accept_already_loaded=True)


def _launchd_stop() -> None:
    _launchd_bootout_and_wait(os.getuid())


def _launchd_restart() -> None:
    uid = os.getuid()
    if not _launchd_bootout_and_wait(uid):
        raise RuntimeError(
            f"launchctl bootout did not release {_LAUNCHD_LABEL} within the timeout, "
            f"so restarting would leave the OLD process running.\n"
            f"  Check it: launchctl print gui/{uid}/{_LAUNCHD_LABEL}\n"
            f"  Then:     launchctl bootout gui/{uid}/{_LAUNCHD_LABEL}"
        )
    _launchd_bootstrap(uid)


def _launchd_status() -> None:
    subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{_LAUNCHD_LABEL}"], check=False)


def _launchd_logs() -> None:
    try:
        subprocess.run(["tail", "-f", str(_LAUNCHD_LOG_DIR / "supervisor.log")], check=False)
    except KeyboardInterrupt:
        pass


def _launchd_describe() -> ServiceInfo:
    installed = _LAUNCHD_PLIST_PATH.is_file()
    active = _launchd_is_loaded(os.getuid()) if installed else None
    if not installed:
        detail = f"not installed (would install at {_LAUNCHD_PLIST_PATH})"
    elif active:
        detail = f"installed and loaded (plist: {_LAUNCHD_PLIST_PATH})"
    else:
        detail = f"installed but NOT loaded (plist: {_LAUNCHD_PLIST_PATH})"
    return ServiceInfo(
        platform="darwin",
        supported=True,
        installed=installed,
        active=active,
        unit_path=_LAUNCHD_PLIST_PATH if installed else None,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Public API -- platform-dispatching wrappers
# ---------------------------------------------------------------------------


def _no_systemctl_detail() -> str:
    return (
        "service management requires `systemctl`, which was not found on PATH. This "
        "system does not appear to use systemd (e.g. a container without systemd, "
        "WSL1, or another init system). Run `amplifier-work-tracker serve --root <path>` "
        "directly to start the supervisor without a service manager."
    )


def service_install(
    root: str | Path,
    *,
    dolt_host: str | None = None,
    dolt_port: int | None = None,
) -> ServiceInfo:
    """Install (or re-install) the supervisor service unit for the current
    user and start it.

    Safe to re-run -- e.g. to change --root, re-run with the new path to
    rebake and restart the unit against it.

    Transactional: if `systemctl`/`launchctl` fails partway through (unit
    written but never enabled/loaded), the unit file written by THIS call is
    removed before the exception propagates -- a caller that catches the
    raised error never has to separately clean up a half-installed unit.
    Only what this call itself created is rolled back; a unit from a prior,
    successful install is never touched by a later call's failure.
    """
    resolved_root = _resolve_root(root)

    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_install(resolved_root, dolt_host=dolt_host, dolt_port=dolt_port)
        return _launchd_describe()
    if _have_systemctl():
        _systemd_install(resolved_root, dolt_host=dolt_host, dolt_port=dolt_port)
        return _systemd_describe()
    raise ServiceUnsupportedError(_no_systemctl_detail())


def service_uninstall() -> None:
    """Stop and remove the supervisor service unit for this user.

    Removes the unit ONLY -- never touches the dolt data directory or any
    amplifier-work-tracker workspace root. That is the work queue; deleting
    it here would be data loss disguised as cleanup.
    """
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_uninstall()
    elif _have_systemctl():
        _systemd_uninstall()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def service_start() -> None:
    """Start the installed supervisor service."""
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_start()
    elif _have_systemctl():
        _systemd_start()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def service_stop() -> None:
    """Stop the supervisor service without uninstalling it."""
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_stop()
    elif _have_systemctl():
        _systemd_stop()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def service_restart() -> None:
    """Restart the supervisor service."""
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_restart()
    elif _have_systemctl():
        _systemd_restart()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def service_status() -> None:
    """Print the service manager's own raw status output (for a human at a terminal).

    See `describe_service` for a structured version other code (`doctor`) can
    consume without scraping this text.
    """
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_status()
    elif _have_systemctl():
        _systemd_status()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def service_logs() -> None:
    """Stream or print the supervisor service's logs."""
    if _is_windows():
        raise ServiceUnsupportedError(_WINDOWS_UNSUPPORTED_DETAIL)
    if _is_darwin():
        _launchd_logs()
    elif _have_systemctl():
        _systemd_logs()
    else:
        raise ServiceUnsupportedError(_no_systemctl_detail())


def describe_service() -> ServiceInfo:
    """Read-only, side-effect-free (beyond a couple of status subprocess calls)
    description of the current service state. Never raises -- an unsupported
    platform is reported as `supported=False` with `detail` explaining why, not
    an exception, so callers like `doctor` can always show something rather
    than needing a try/except around this specific call.
    """
    if _is_windows():
        return ServiceInfo(
            platform="windows",
            supported=False,
            installed=False,
            active=None,
            unit_path=None,
            detail=_WINDOWS_UNSUPPORTED_DETAIL,
        )
    if _is_darwin():
        return _launchd_describe()
    if _have_systemctl():
        return _systemd_describe()
    return ServiceInfo(
        platform="linux" if sys.platform.startswith("linux") else "other",
        supported=False,
        installed=False,
        active=None,
        unit_path=None,
        detail=_no_systemctl_detail(),
    )


__all__ = [
    "SERVICE_NAME",
    "ServiceInfo",
    "ServiceUnsupportedError",
    "describe_service",
    "service_install",
    "service_logs",
    "service_restart",
    "service_start",
    "service_status",
    "service_stop",
    "service_uninstall",
]
