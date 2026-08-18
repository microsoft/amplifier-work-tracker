"""The `amplifier-work-tracker serve` supervisor process.

This is the ExecStart target of the systemd/launchd service (see
`service.py`). One process owns three responsibilities for as long as it
runs:

  1. Spawn and supervise a `dolt sql-server` CHILD process serving the
     shared server bd's own `--shared-server` mode expects, so it survives
     reboot without needing an agent to first run a `bd` command that lazily
     starts one.
  2. Run `reap` as an in-process asyncio sweep loop across every known
     project (releases stale custody back to the queue).
  3. Run `notify` as an in-process asyncio sweep loop across every known
     project (propagates resolved work back to reporters).

Deliberately NOT systemd timers for #2/#3: neither amplifier-browser-bridge
nor muxplex uses timers for their periodic work, and a second unit type
doubles the install surface (two things that can silently fail to survive a
reboot instead of one) for no benefit an in-process asyncio loop doesn't
already provide.

Dolt data-directory convention -- read this before changing it
----------------------------------------------------------------
`bd init --shared-server` documents (and this was independently verified by
inspecting a live process) that the shared dolt server lives at
``~/.beads/shared-server/dolt`` -- a FIXED location, independent of
``AMPLIFIER_WORK_TRACKER_ROOT``. This module deliberately reuses that exact
location and the same default port (3308, also verified against a live
process) instead of inventing a second one. Every existing `bd` project,
regardless of which amplifier-work-tracker workspace root it was created
under, already points at this one server; a second location would silently
split the world into two incompatible shared servers.

One consequence, stated plainly: this supervisor is designed to OWN and
monitor the dolt server on this port. If something else (a human running
`dolt sql-server` by hand, or `bd`'s own lazy auto-start from an earlier,
unrelated session) is already healthily serving it when `serve` starts, this
module refuses to silently adopt or kill it -- see `classify_port_holders`.
Stop the foreign instance first, or point `--dolt-port` elsewhere.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import adapter as A
from . import custody as C
from . import heartbeat as HB

logger = logging.getLogger(__name__)

DEFAULT_DOLT_HOST = os.environ.get("AMPLIFIER_WORK_TRACKER_DOLT_HOST", "127.0.0.1")
DEFAULT_DOLT_PORT = int(os.environ.get("AMPLIFIER_WORK_TRACKER_DOLT_PORT", "3308"))

DEFAULT_REAP_INTERVAL_SECONDS = int(
    os.environ.get("AMPLIFIER_WORK_TRACKER_REAP_INTERVAL_SECONDS", "300")
)
DEFAULT_NOTIFY_INTERVAL_SECONDS = int(
    os.environ.get("AMPLIFIER_WORK_TRACKER_NOTIFY_INTERVAL_SECONDS", "300")
)
DEFAULT_DOLT_RESTART_BACKOFF_SECONDS = 2.0

# Measured outage, 2026-08-14 17:14: dolt sql-server was SIGKILLed 8 times in
# ~30 seconds, and `dolt_supervisor_loop` restarted it every time -- forever,
# silently. Nothing ever told anyone the child was dying in a tight loop; the
# supervisor just kept trying at `DEFAULT_DOLT_RESTART_BACKOFF_SECONDS`
# intervals. A budget bounds that: once the child has exited unexpectedly
# `DEFAULT_DOLT_RESTART_BUDGET_COUNT` times within
# `DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS`, the loop gives up LOUDLY (see
# `DoltSupervisionExhaustedError`) instead of spinning forever quietly.
# 5-in-60s is well inside the shape of the measured incident (8 in ~30s) --
# it fires fast enough to stop hammering a genuinely broken dolt, but not so
# tight that a couple of ordinary restarts (e.g. two real crashes an hour
# apart) ever trips it.
DEFAULT_DOLT_RESTART_BUDGET_COUNT = 5
DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS = 60.0

_PORT_PROBE_TIMEOUT_S = 2.0
_PORT_HOLDER_KILL_WAIT_S = 1.0


def default_dolt_dir() -> Path:
    """bd's own shared-server dolt directory -- see module docstring."""
    return Path.home() / ".beads" / "shared-server" / "dolt"


# ---------------------------------------------------------------------------
# reap / notify -- the domain logic, shared by the single-project CLI
# commands (`amplifier-work-tracker reap --project X`) and the all-project
# sweeps below. One home for the logic; two callers.
# ---------------------------------------------------------------------------


def reap_project(
    bd: A.Beads,
    *,
    ttl_seconds: int | None = None,
    escalation_hours: float | None = None,
) -> dict[str, Any]:
    """Release items in *one* project whose custody has gone stale or hit the
    escalation ceiling. Identical logic to `cli.cmd_reap` -- extracted here so
    the sweep (below) and the single-project CLI command can never drift
    apart on what "reap" means.
    """
    ttl = ttl_seconds if ttl_seconds is not None else C.CUSTODY_TTL_SECONDS
    esc = escalation_hours if escalation_hours is not None else C.ESCALATION_HOURS
    held = [i for i in bd.list(include_resolved=False) if i.status == "held"]
    reclaimed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for item in held:
        rec = item.meta.get(C.CUSTODY_KEY)
        eligible, reason = C.reclaim_eligible(rec, ttl=ttl, escalation_hours=esc)
        if eligible:
            bd.release(item.id)
            reclaimed.append({"id": item.id, "was_holder": item.holder, "reason": reason})
        else:
            note = "quiet (awaiting_human)" if not C.should_notify(rec) else "ok"
            kept.append({"id": item.id, "holder": item.holder, "note": note})
    return {"reclaimed": reclaimed, "reclaimed_count": len(reclaimed), "kept": kept}


def notify_project(bd: A.Beads) -> dict[str, Any]:
    """Propagate resolved work in *one* project back to the reports that
    prompted it. Identical logic to `cli.cmd_notify` -- see `reap_project`'s
    docstring for why this is factored out rather than duplicated.
    """
    flipped: list[dict[str, Any]] = []
    for item in bd.list(lane=A.LANE_WORK, include_resolved=True):
        if item.status != "resolved":
            continue
        full = bd.get(item.id, with_links=True)
        reason = full.resolution or "resolved"
        for link in full.links:
            if link["direction"] != "from" or link["type"] != A.LINK_DISCOVERED_FROM:
                continue
            src = bd.get(link["id"])
            if src.status == "resolved":
                continue
            bd.resolve(src.id, f"Resolved by {item.id}: {reason}", actor="notifier")
            flipped.append({"report": src.id, "by": item.id})
    return {"flipped": flipped, "count": len(flipped)}


def reap_sweep(
    ws: A.Workspace,
    *,
    ttl_seconds: int | None = None,
    escalation_hours: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Sweep `reap_project` across every known project. This is what tests
    call directly. One project's exception is caught and recorded per-project
    rather than allowed to abort the sweep -- a broken project must never
    prevent every OTHER project's stale custody from being released.
    """
    out: dict[str, dict[str, Any]] = {}
    for name in ws.names():
        try:
            out[name] = reap_project(
                ws.project(name), ttl_seconds=ttl_seconds, escalation_hours=escalation_hours
            )
        except Exception as e:  # noqa: BLE001 -- one broken project must never break the sweep
            out[name] = {"error": str(e)}
    return out


def notify_sweep(ws: A.Workspace) -> dict[str, dict[str, Any]]:
    """Sweep `notify_project` across every known project. See `reap_sweep`'s
    docstring -- same per-project isolation."""
    out: dict[str, dict[str, Any]] = {}
    for name in ws.names():
        try:
            out[name] = notify_project(ws.project(name))
        except Exception as e:  # noqa: BLE001 -- one broken project must never break the sweep
            out[name] = {"error": str(e)}
    return out


async def reap_loop(
    ws: A.Workspace,
    *,
    interval: float,
    stop_event: asyncio.Event,
    ttl_seconds: int | None = None,
    escalation_hours: float | None = None,
    heartbeat_path: Path | None = None,
) -> None:
    """Trivial wrapper: sleep, sweep, repeat -- until `stop_event` fires.

    A sweep that raises is caught and logged (`logger.exception`) rather than
    allowed to kill this task. A silently-dead reaper is the exact failure
    this whole feature exists to fix -- letting an exception propagate out
    of this loop would recreate it.

    Writes a heartbeat (see `amplifier_work_tracker.heartbeat`): once at
    startup, before the first sweep, and again after every sweep that
    completes without raising. This is what lets `doctor`'s `sweeps.alive`
    check distinguish "quietly healthy" from "silently dead," which the
    exception-only logging above cannot do by itself.
    """
    hb_path = heartbeat_path if heartbeat_path is not None else HB.heartbeat_path(ws.root)
    HB.record_loop_started(hb_path, HB.REAP, pid=os.getpid())
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            await asyncio.to_thread(
                reap_sweep, ws, ttl_seconds=ttl_seconds, escalation_hours=escalation_hours
            )
            HB.record_sweep_completed(hb_path, HB.REAP, pid=os.getpid())
        except Exception:  # noqa: BLE001 -- see docstring
            logger.exception("reap sweep crashed -- continuing on the next interval")


async def notify_loop(
    ws: A.Workspace,
    *,
    interval: float,
    stop_event: asyncio.Event,
    heartbeat_path: Path | None = None,
) -> None:
    """Trivial wrapper around `notify_sweep` -- see `reap_loop`'s docstring,
    including the heartbeat writes."""
    hb_path = heartbeat_path if heartbeat_path is not None else HB.heartbeat_path(ws.root)
    HB.record_loop_started(hb_path, HB.NOTIFY, pid=os.getpid())
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            await asyncio.to_thread(notify_sweep, ws)
            HB.record_sweep_completed(hb_path, HB.NOTIFY, pid=os.getpid())
        except Exception:  # noqa: BLE001 -- see docstring
            logger.exception("notify sweep crashed -- continuing on the next interval")


# ---------------------------------------------------------------------------
# Port safety -- three-way discrimination, extended from muxplex's
# `_kill_stale_port_holder` / `_port_holder_is_healthy_muxplex` pair.
#
# muxplex's original problem: on service restart, the old process may still
# be holding the port (TIME_WAIT, or simply not exited yet). Killing
# whatever holds the port unconditionally means a stray second invocation
# silently terminates a healthy, serving instance -- indistinguishable from a
# mystery outage. muxplex's fix was a two-way split: stale (kill) vs healthy
# (refuse). We extend it to three, because unlike muxplex's single-owner
# port, this port can be legitimately served by something we did not spawn
# (bd's own lazy auto-start, or a human) -- see module docstring.
# ---------------------------------------------------------------------------

PortAction = Literal["proceed", "kill_stale", "refuse_ours", "refuse_foreign"]


def get_port_holder_pids(port: int) -> list[int]:
    """PIDs currently holding *port*, via `lsof -ti :port`.

    A missing `lsof`, a permission error, or any other failure returns an
    empty list rather than raising -- same policy as muxplex's own
    `_kill_stale_port_holder`: a missing tool must never prevent startup.
    Whatever tries to bind the port next will simply fail naturally if it's
    actually taken.
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001 -- see docstring
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    pids: list[int] = []
    for line in result.stdout.strip().splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return pids


def port_holder_responds(host: str, port: int, timeout: float = _PORT_PROBE_TIMEOUT_S) -> bool:
    """Raw TCP probe: does *something* answer a connection on host:port within
    timeout?

    Dolt speaks the MySQL wire protocol and sends a handshake packet
    immediately on connect, so receiving ANY bytes back means a live,
    actively-responding server -- not just a socket lingering in TIME_WAIT
    with nothing behind it. Never raises: every failure mode (refused,
    timeout, reset) means "not responding," which is exactly the "stale/hung"
    signal `classify_port_holders` needs.

    Also used, unmodified, as the `dolt.reachable` doctor check.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            return bool(sock.recv(4))
    except OSError:
        return False


def read_owned_pid(pid_file: Path) -> int | None:
    """The PID this supervisor itself last recorded as its own dolt child, or
    None if there is no record (never started one, or it exited cleanly and
    removed the file)."""
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def classify_port_holders(
    *, holders: list[int], responds: bool, owned_pid: int | None
) -> tuple[PortAction, str]:
    """THE port-safety decision, and nothing else decides it.

    Pure and exhaustively testable: every input is a plain value (a list of
    ints, a bool, an optional int) -- no sockets, subprocesses, or real PIDs
    touched here. `ensure_port_available` is the impure caller that gathers
    these three inputs and acts on the verdict.

    Four outcomes:
      - no holders                     -> proceed        (port is free)
      - holders, NOT responding        -> kill_stale      (stale/hung --
                                           muxplex's exact restart-race case;
                                           safe to SIGTERM and take the port)
      - holders, responding, IS ours   -> refuse_ours     (a healthy dolt
                                           this supervisor already owns is
                                           running -- refuse to double-serve;
                                           the caller exits non-zero and lets
                                           RestartSec back off rather than
                                           killing a live server)
      - holders, responding, NOT ours  -> refuse_foreign  (a healthy dolt is
                                           serving this port/data-dir but we
                                           have no record of spawning it --
                                           refuse and explain; silently
                                           killing or silently adopting an
                                           unverified server is worse than an
                                           honest refusal)
    """
    if not holders:
        return "proceed", "port is free"
    if not responds:
        return "kill_stale", f"holder(s) {holders} do not respond -- stale/hung, safe to reclaim"
    if owned_pid is not None and owned_pid in holders:
        return (
            "refuse_ours",
            f"a healthy dolt server this supervisor already owns (pid {owned_pid}) is running",
        )
    return (
        "refuse_foreign",
        f"port already served by a healthy process (pid(s) {holders}) not spawned by us",
    )


class PortConflictError(RuntimeError):
    """Raised for refuse_ours / refuse_foreign. Never raised for kill_stale,
    which `ensure_port_available` handles by terminating the stale holder(s)
    and proceeding."""


def ensure_port_available(host: str, port: int, pid_file: Path, *, force: bool = False) -> None:
    """Gather the three classification inputs, decide, and act.

    `force=True` restores the old unconditional behaviour (kills whatever
    holds the port, no questions asked) -- an explicit escape hatch, never
    the default.
    """
    if force:
        for pid in get_port_holder_pids(port):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if get_port_holder_pids(port):
            time.sleep(_PORT_HOLDER_KILL_WAIT_S)
        return

    holders = get_port_holder_pids(port)
    responds = port_holder_responds(host, port) if holders else False
    owned_pid = read_owned_pid(pid_file)
    action, reason = classify_port_holders(holders=holders, responds=responds, owned_pid=owned_pid)

    if action == "proceed":
        return
    if action == "kill_stale":
        logger.warning("dolt port %s: %s -- terminating stale holder(s)", port, reason)
        for pid in holders:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(_PORT_HOLDER_KILL_WAIT_S)
        return
    if action == "refuse_ours":
        raise PortConflictError(
            f"refusing to start: {reason}. This looks like a duplicate `serve` invocation -- "
            f"check `amplifier-work-tracker service status`, or use `service restart` instead of "
            f"starting a second one."
        )
    raise PortConflictError(
        f"refusing to start: {reason}. If this is bd's own lazily-started shared server (or a "
        f"human-started one), stop it before installing/starting this service -- this supervisor "
        f"is designed to own and monitor the dolt server on this port, not silently share or kill "
        f"it. Check what's listening: ss -ltn | grep :{port}  (chosen over other port-listing "
        f"tools because it is present on minimal containers where they often are not)"
    )


# ---------------------------------------------------------------------------
# Dolt child process supervision
# ---------------------------------------------------------------------------


def spawn_dolt(host: str, port: int, data_dir: Path) -> subprocess.Popen:
    data_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(["dolt", "sql-server", "-H", host, "-P", str(port)], cwd=str(data_dir))


def _record_exit_and_over_budget(
    recent_exits: list[float], *, now: float, budget_count: int, window: float
) -> bool:
    """Record one unexpected-exit timestamp and report whether the trailing
    window now holds `budget_count` or more of them.

    Pure and exhaustively testable -- a plain list, a plain float clock
    reading, two plain numeric thresholds, no asyncio and no real clock --
    mirroring this module's existing `classify_port_holders` convention of
    keeping a decision free of I/O so it can be tested directly rather than
    only indirectly through a real, timed async loop. Mutates `recent_exits`
    in place: appends `now`, then drops any entry older than `window`
    seconds behind it, so the budget "resets" simply by enough real time
    passing between failures -- there is no separate explicit reset on
    success, because a successful run never calls this at all.
    """
    recent_exits.append(now)
    recent_exits[:] = [t for t in recent_exits if now - t <= window]
    return len(recent_exits) >= budget_count


class DoltSupervisionExhaustedError(RuntimeError):
    """Raised by `dolt_supervisor_loop` when the dolt child has exited
    unexpectedly `restart_budget_count` times within
    `restart_budget_window` seconds -- see the module-level
    `DEFAULT_DOLT_RESTART_BUDGET_COUNT`/`_WINDOW_SECONDS` docstring for why
    this budget exists.

    This is the deeper bug behind the 2026-08-14 outage, one layer below
    "the unit needs Restart=always": a supervisor that gives up trying to
    keep dolt alive must say so LOUDLY and exit non-zero -- never fall
    through to a tidy, silent return that looks, from the outside (and to
    systemd), identical to an operator's own clean `systemctl stop`. A
    fallback that hides a failure behind a clean exit is exactly the
    anti-pattern this project forbids (see AGENTS.md / project
    IMPLEMENTATION_PHILOSOPHY). Letting this propagate out of `_async_serve`
    is what makes `serve()` return 1 instead of 0.
    """


async def dolt_supervisor_loop(
    *,
    host: str,
    port: int,
    data_dir: Path,
    pid_file: Path,
    stop_event: asyncio.Event,
    state: dict[str, subprocess.Popen | None],
    restart_backoff: float = DEFAULT_DOLT_RESTART_BACKOFF_SECONDS,
    restart_budget_count: int = DEFAULT_DOLT_RESTART_BUDGET_COUNT,
    restart_budget_window: float = DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS,
) -> None:
    """Own, spawn, and restart the dolt sql-server child for as long as this
    supervisor runs.

    An unexpected exit (crash, OOM, `kill -9`) is restarted after
    `restart_backoff` seconds, logged loudly, never silently -- this is what
    makes "kill the dolt child" a self-healing event instead of a permanent
    outage. Exits only when `stop_event` is set (the supervisor is shutting
    down), in which case the child has already been asked to terminate by the
    caller (see `_async_serve`'s signal handler) and this loop simply stops
    restarting it.

    If the child exits unexpectedly `restart_budget_count` times within a
    trailing `restart_budget_window`-second window, this loop stops trying
    and raises `DoltSupervisionExhaustedError` instead of restarting again --
    see that exception's docstring for why silently spinning forever is
    itself the bug. The window is a simple trailing list of monotonic
    timestamps, trimmed on every exit; it is reset implicitly by time simply
    passing (old exits age out), never explicitly reset by a success, since
    a *successful* run doesn't record an exit at all.

    `state["proc"]` is kept up to date with the current child so an external
    signal handler can terminate it promptly on shutdown without this loop
    needing to know anything about signals.
    """
    recent_exits: list[float] = []
    while not stop_event.is_set():
        ensure_port_available(host, port, pid_file)
        proc = spawn_dolt(host, port, data_dir)
        state["proc"] = proc
        pid_file.write_text(str(proc.pid), encoding="utf-8")
        logger.info("dolt sql-server started (pid %s) on %s:%s", proc.pid, host, port)
        try:
            returncode = await asyncio.to_thread(proc.wait)
        finally:
            state["proc"] = None
            pid_file.unlink(missing_ok=True)
        if stop_event.is_set():
            logger.info("dolt sql-server stopped (exit %s) -- supervisor shutting down", returncode)
            return
        logger.warning(
            "dolt sql-server exited unexpectedly (code %s) -- restarting in %.1fs",
            returncode,
            restart_backoff,
        )
        over_budget = _record_exit_and_over_budget(
            recent_exits,
            now=time.monotonic(),
            budget_count=restart_budget_count,
            window=restart_budget_window,
        )
        if over_budget:
            raise DoltSupervisionExhaustedError(
                f"dolt sql-server exited unexpectedly {len(recent_exits)} times within "
                f"{restart_budget_window:.0f}s (budget: {restart_budget_count} exits) -- "
                f"giving up rather than restarting it forever in a silent tight loop. "
                f"The service manager will restart the WHOLE supervisor per its own "
                f"Restart= policy (see service.py); if this keeps recurring, the underlying "
                f"dolt failure needs investigation directly (disk space, a corrupt data "
                f"dir at {data_dir}, or something else already listening on {host}:{port})."
            )
        await asyncio.sleep(restart_backoff)


# ---------------------------------------------------------------------------
# Web dashboard integration -- `serve --web-port`, the 4th concurrent task.
#
# The dashboard (`webapp.py`/`webauth.py`) has always been runnable as its
# OWN standalone client of the shared dolt server via `amplifier-work-tracker
# web` (`cli.cmd_web`). This section folds it into the supervisor itself as
# an OPTIONAL fourth `asyncio.gather`-ed task, so it can be always-on and
# reboot-surviving (the systemd/launchd unit already is) instead of a
# separate foreground process someone has to remember to start, in a
# terminal, after every reboot.
#
# `resolve_web_config` (webapp.py) is the ONE place both this path and
# `cmd_web` resolve --host/--public/--auth-mode -- see that function's
# docstring. `import_web_modules` below is the ONE guarded-import path both
# use too, so the two callers can never drift on the ImportError message
# shown when the optional `web` extra isn't installed.
# ---------------------------------------------------------------------------

_WEB_EXTRA_ERROR_TEMPLATE = (
    "the web dashboard requires the 'web' extra: {e}\n"
    "Install it with: uv tool install --reinstall --with 'amplifier-work-tracker[web]' "
    "'git+https://github.com/microsoft/amplifier-work-tracker@main'\n"
    "(or, for a dev checkout: uv pip install -e '.[web]')"
)


def import_web_modules():
    """Guarded import of `webapp` -- it (transitively, via its own `from .
    import webauth as WA`) requires the optional `web` extra (fastapi/
    uvicorn/itsdangerous/python-pam/...), so importing it outside a
    `web`-extra install raises `ImportError`. Converts that into a clear,
    actionable `RuntimeError` -- never a bare traceback -- shared by
    `cli.py`'s `cmd_web` and this module's own `web_server_loop` so the two
    paths can never drift apart on the message a caller sees.

    NOTE for `web_server_loop` callers: this raises plain `RuntimeError`,
    NOT `WebServerStartupError` -- it is also called by `cli.py`'s
    `cmd_web`, a standalone foreground command with no supervisor/gather
    involved, which already catches `RuntimeError` directly. Callers that
    run inside the supervisor's `asyncio.gather` (i.e. `web_server_loop`)
    MUST catch this `RuntimeError` and re-raise as `WebServerStartupError`
    themselves -- see that function's own comment for why this is not
    optional (a plain `RuntimeError` here previously escaped `_async_serve`'s
    except clause entirely, which only matches `WebServerStartupError`/
    `DoltSupervisionExhaustedError`, silently degrading a real supervisor to
    dolt-only with the web dashboard simply never bound).
    """
    try:
        from . import webapp
    except ImportError as e:
        raise RuntimeError(_WEB_EXTRA_ERROR_TEMPLATE.format(e=e)) from e
    return webapp


@dataclass
class WebIntegrationConfig:
    """`serve --web-port`'s web-specific inputs -- the same shape `cmd_web`
    accepts (`--host`/`--public`/`--port`/`--auth-mode`/`--session-ttl`/
    `--tls-cert`/`--tls-key`/`--http-port`, the latter three named
    `--web-tls-cert`/`--web-tls-key`/`--web-http-port` on `serve` to
    distinguish them from the bare `--dolt-*` flags), just carried as one
    value so `_async_serve`'s signature gains a single new optional
    parameter instead of eight."""

    host: str | None
    public: bool
    port: int
    auth_mode: str
    session_ttl: int
    tls_cert: str | None = None
    tls_key: str | None = None
    # Companion plain-HTTP trust-bootstrap port -- see `webtrust.py`'s
    # module docstring and `webapp._resolve_http_bootstrap_port`. None (the
    # default) lets `resolve_web_config` decide (no listener if TLS isn't
    # active; `port + 1` if it is and this wasn't given explicitly).
    http_port: int | None = None


class WebServerStartupError(RuntimeError):
    """Raised when the integrated web dashboard cannot start -- a rejected
    host/auth-mode combination (`webapp.WebConfigError`), or a real bind
    failure (e.g. the port already in use).

    A bind failure is, internally, uvicorn's OWN `Server.startup()` calling
    `sys.exit(STARTUP_FAILURE)` on an `OSError` from `loop.create_server(...)`
    -- a bare `SystemExit` raised from inside an asyncio task, which would
    otherwise surface as an opaque, hard-to-diagnose failure (or, worse, a
    silently-swallowed one) rather than the loud, actionable error this
    supervisor's fail-loud policy requires everywhere else (see
    `PortConflictError`, `DoltSupervisionExhaustedError`). `web_server_loop`
    catches both cases and re-raises as this exception, a plain `Exception`
    `asyncio.gather` propagates normally -- never a silent fallback that
    continues serving without the web dashboard.
    """


async def _web_stop_watcher(server: Any, stop_event: asyncio.Event) -> None:
    """Mirror THIS supervisor's `stop_event` into uvicorn's own `should_exit`
    flag -- the ONLY shutdown signal the web task responds to. See
    `web_server_loop`'s docstring for why uvicorn's own signal capturing is
    deliberately bypassed in favor of this single-authority approach."""
    await stop_event.wait()
    server.should_exit = True


async def web_server_loop(
    ws: A.Workspace,
    web: WebIntegrationConfig,
    *,
    stop_event: asyncio.Event,
) -> None:
    """Run the web dashboard as the supervisor's 4th concurrent task, for as
    long as `serve` runs, sharing the EXACT SAME `stop_event` the dolt/reap/
    notify tasks already use -- one shutdown authority for the whole
    process, not four independent ones.

    Deliberately calls uvicorn's private `Server._serve(...)` rather than
    its public `Server.serve()`. The public method wraps the real serve
    loop in `capture_signals()`, which installs ITS OWN SIGTERM/SIGINT
    handlers via `signal.signal(...)` -- directly on top of the handlers
    `_async_serve` already installed via `loop.add_signal_handler(...)` for
    the exact same two signals. Two independent, competing signal handlers
    for the same signal is exactly the kind of hidden, order-dependent state
    this codebase avoids elsewhere (see `classify_port_holders`'s docstring
    on `_kill_stale_port_holder`-style discrimination). `_web_stop_watcher`
    mirrors `stop_event` into `server.should_exit` instead, so a real
    SIGTERM (`_request_stop`, already wired to `stop_event`) drains the web
    server exactly like the other three tasks -- through the same single
    path, whether the trigger was a real OS signal or (as the test suite
    does, matching `reap_loop`/`notify_loop`'s own tests) a direct
    `stop_event.set()` with no signal involved at all.

    `import_web_modules()` is called inside a try/except here -- NOT bare,
    as it was before this fix -- because it raises plain `RuntimeError`
    (see its own docstring: it is shared with `cli.py`'s standalone
    `cmd_web`, which already expects that type). A bare `RuntimeError`
    escaping this task does NOT match `_async_serve`'s except clause
    (`DoltSupervisionExhaustedError`/`WebServerStartupError` only), so it
    silently missed the supervisor's whole fail-loud path: this was the
    live bug -- a `uv tool install` with the `[web]` extra missing left the
    dolt server and reap/notify sweeps running seemingly fine forever,
    with the web dashboard simply never bound and nothing said so. Wrap it
    here, exactly like the `import uvicorn` case just below, so BOTH of
    this task's only two possible import failures become the same
    exception type `_async_serve` already knows how to fail loud on.
    """
    try:
        webapp = import_web_modules()
    except RuntimeError as e:
        raise WebServerStartupError(str(e)) from e
    try:
        import uvicorn
    except ImportError as e:
        raise WebServerStartupError(_WEB_EXTRA_ERROR_TEMPLATE.format(e=e)) from e

    try:
        config, messages = webapp.resolve_web_config(
            host=web.host,
            public=web.public,
            port=web.port,
            auth_mode=web.auth_mode,
            session_ttl=web.session_ttl,
            tls_cert=web.tls_cert,
            tls_key=web.tls_key,
            http_port=web.http_port,
        )
    except webapp.WebConfigError as e:
        raise WebServerStartupError(str(e)) from e

    for m in messages:
        logger.info("web: %s", m)
    # Scheme is derived from whether resolve_web_config actually resolved a
    # TLS cert/key pair -- never hardcoded -- so this log line can't drift
    # from what uvicorn is about to be handed below.
    scheme = "https" if config.tls_cert else "http"
    logger.info(
        "web dashboard listening on %s://%s:%s (root=%s)",
        scheme,
        config.host,
        config.port,
        ws.root,
    )

    app = webapp.create_app(ws, config.auth)
    ssl_kwargs: dict = {}
    if config.tls_cert and config.tls_key:
        ssl_kwargs = {"ssl_certfile": config.tls_cert, "ssl_keyfile": config.tls_key}
    uv_config = uvicorn.Config(
        app, host=config.host, port=config.port, log_level="info", **ssl_kwargs
    )
    server = uvicorn.Server(uv_config)

    # Companion plain-HTTP trust-bootstrap listener -- see `webtrust.py`'s
    # module docstring. `resolve_web_config` already decided whether this
    # runs at all (`config.http_port` is None unless TLS is active) and
    # which port it lands on; this task just brings up a SECOND uvicorn
    # server for it, sharing this same task/stop_event/fail-loud path --
    # never a separate top-level supervisor task, so a bind failure on
    # EITHER listener surfaces through the identical `WebServerStartupError`
    # handling below.
    trust_server: Any = None
    if config.http_port is not None:
        from . import webtrust as WTR

        trust_app = WTR.create_trust_app(https_port=config.port, tls_cert_path=config.tls_cert)
        trust_uv_config = uvicorn.Config(
            trust_app, host=config.host, port=config.http_port, log_level="info"
        )
        trust_server = uvicorn.Server(trust_uv_config)

    watcher = asyncio.create_task(_web_stop_watcher(server, stop_event))
    trust_watcher = (
        asyncio.create_task(_web_stop_watcher(trust_server, stop_event))
        if trust_server is not None
        else None
    )
    try:
        if trust_server is not None:
            # noqa: SLF001 for both -- see docstring: bypasses uvicorn's own signal capture
            await asyncio.gather(server._serve(), trust_server._serve())  # noqa: SLF001
        else:
            await server._serve()  # noqa: SLF001 -- see docstring: bypasses uvicorn's own signal capture
    except SystemExit as e:
        raise WebServerStartupError(
            f"web dashboard (or its trust-bootstrap companion) failed to start on "
            f"{config.host}:{config.port}"
            + (f"/{config.http_port}" if config.http_port is not None else "")
            + f" (uvicorn exited during startup, code {e.code}) -- most likely a port is "
            f"already in use. Check: ss -ltn | grep -E ':({config.port}"
            + (f"|{config.http_port}" if config.http_port is not None else "")
            + ")'"
        ) from e
    finally:
        if trust_watcher is not None:
            trust_watcher.cancel()
            try:
                await trust_watcher
            except asyncio.CancelledError:
                pass
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _configure_logging(level: int = logging.INFO) -> None:
    """Ensure this package's own log records reach a real handler.

    Deliberately scoped to the `amplifier_work_tracker` logger namespace, not
    the root logger -- every module here does `logging.getLogger(__name__)`,
    so all of them are children of `amplifier_work_tracker` and pick up this
    handler via normal propagation. Idempotent: safe to call more than once
    without installing duplicate handlers.
    """
    package_logger = logging.getLogger("amplifier_work_tracker")
    package_logger.setLevel(level)
    if not any(h.name == "amplifier-work-tracker-supervisor" for h in package_logger.handlers):
        handler = logging.StreamHandler()
        handler.name = "amplifier-work-tracker-supervisor"
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        package_logger.addHandler(handler)


async def _async_serve(
    root: Path,
    *,
    host: str,
    port: int,
    reap_interval: float,
    notify_interval: float,
    dolt_restart_backoff: float,
    dolt_restart_budget_count: int = DEFAULT_DOLT_RESTART_BUDGET_COUNT,
    dolt_restart_budget_window: float = DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS,
    web: WebIntegrationConfig | None = None,
) -> int:
    ws = A.Workspace(root)
    data_dir = default_dolt_dir()
    root.mkdir(parents=True, exist_ok=True)
    pid_file = root / ".dolt-server.pid"
    stop_event = asyncio.Event()
    state: dict[str, subprocess.Popen | None] = {"proc": None}

    def _request_stop() -> None:
        logger.info("shutdown requested")
        stop_event.set()
        proc = state.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass  # rare platforms without add_signal_handler support

    dolt_task = asyncio.create_task(
        dolt_supervisor_loop(
            host=host,
            port=port,
            data_dir=data_dir,
            pid_file=pid_file,
            stop_event=stop_event,
            state=state,
            restart_backoff=dolt_restart_backoff,
            restart_budget_count=dolt_restart_budget_count,
            restart_budget_window=dolt_restart_budget_window,
        )
    )
    reap_task = asyncio.create_task(reap_loop(ws, interval=reap_interval, stop_event=stop_event))
    notify_task = asyncio.create_task(
        notify_loop(ws, interval=notify_interval, stop_event=stop_event)
    )
    tasks = [dolt_task, reap_task, notify_task]
    # The web task is OPTIONAL (only when `--web-port` was given) -- when
    # absent, `serve` behaves EXACTLY as before this feature: three tasks,
    # no uvicorn/fastapi import, no behavior change whatsoever.
    if web is not None:
        tasks.append(asyncio.create_task(web_server_loop(ws, web, stop_event=stop_event)))

    try:
        await asyncio.gather(*tasks)
    except (DoltSupervisionExhaustedError, WebServerStartupError) as e:
        # The deeper bug this closes: giving up on dolt (or failing to start
        # the web dashboard) must be LOUD and non-zero, never a tidy
        # shutdown indistinguishable from an operator's own `systemctl
        # stop` -- see DoltSupervisionExhaustedError's/WebServerStartupError's
        # own docstrings. `asyncio.gather` (without `return_exceptions=True`)
        # re-raises the first task exception immediately but does NOT itself
        # cancel the still-running tasks -- do that explicitly, for whichever
        # tasks are still alive (the one that raised is already done), so the
        # process can exit promptly instead of leaving the rest running as
        # orphans. Generalized over `tasks` (not hand-enumerated) so this
        # keeps working correctly regardless of whether `web` is present.
        #
        # `_request_stop()`, not a bare `stop_event.set()` -- this is the
        # second half of the same bug. Cancelling `dolt_task` (below) only
        # cancels the ASYNCIO wrapper around `await
        # asyncio.to_thread(proc.wait)`; it does NOT terminate the real
        # `dolt sql-server` OS process, which keeps its executor thread
        # blocked in `proc.wait()` for as long as dolt stays alive (i.e.
        # forever, for a healthy server). `asyncio.run()`'s own cleanup
        # (`shutdown_default_executor()`) then blocks waiting for that
        # thread to finish -- so with only `stop_event.set()` here, this
        # whole process would hang indefinitely rather than actually
        # exiting non-zero, reproducing the exact silent-degrade symptom
        # (dolt still up, nothing telling anyone the web task died) this
        # fix exists to close. `_request_stop()` does everything
        # `stop_event.set()` did AND sends the real child process a
        # SIGTERM, so `dolt_supervisor_loop`'s blocking wait actually
        # resolves and this function can really return/raise.
        logger.error("supervisor giving up: %s", e)
        _request_stop()
        remaining = [t for t in tasks if not t.done()]
        for t in remaining:
            t.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)
        raise
    return 0


def serve(
    root: Path,
    *,
    host: str = DEFAULT_DOLT_HOST,
    port: int = DEFAULT_DOLT_PORT,
    reap_interval: float = DEFAULT_REAP_INTERVAL_SECONDS,
    notify_interval: float = DEFAULT_NOTIFY_INTERVAL_SECONDS,
    dolt_restart_backoff: float = DEFAULT_DOLT_RESTART_BACKOFF_SECONDS,
    dolt_restart_budget_count: int = DEFAULT_DOLT_RESTART_BUDGET_COUNT,
    dolt_restart_budget_window: float = DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS,
    web: WebIntegrationConfig | None = None,
) -> int:
    """Synchronous entry point for `amplifier-work-tracker serve` -- what
    cli.py's `cmd_serve` calls, and what the systemd/launchd unit's
    ExecStart ultimately runs.

    `web` is OPTIONAL (`cmd_serve` only builds one when `--web-port` was
    given). When `None`, this behaves EXACTLY as it always has -- three
    tasks, no uvicorn/fastapi import, no new dependency required at
    runtime. When given, the web dashboard runs as a 4th concurrent task
    (see `web_server_loop`), always-on and reboot-surviving for as long as
    this supervisor (and the systemd/launchd unit wrapping it) runs.

    Returns 1 (never a bare, silent 0) for a port conflict,
    `DoltSupervisionExhaustedError`, OR `WebServerStartupError` -- the
    supervisor giving up on dolt, or failing to start the web dashboard, is
    a real failure and must be reported as one at the process-exit level,
    not swallowed into a tidy-looking shutdown. See those exceptions'
    docstrings.
    """
    _configure_logging()
    try:
        return asyncio.run(
            _async_serve(
                root,
                host=host,
                port=port,
                reap_interval=reap_interval,
                notify_interval=notify_interval,
                dolt_restart_backoff=dolt_restart_backoff,
                dolt_restart_budget_count=dolt_restart_budget_count,
                dolt_restart_budget_window=dolt_restart_budget_window,
                web=web,
            )
        )
    except PortConflictError as e:
        print(f"amplifier-work-tracker serve: {e}", file=sys.stderr)
        return 1
    except DoltSupervisionExhaustedError as e:
        print(f"amplifier-work-tracker serve: {e}", file=sys.stderr)
        return 1
    except WebServerStartupError as e:
        print(f"amplifier-work-tracker serve: {e}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_DOLT_HOST",
    "DEFAULT_DOLT_PORT",
    "DEFAULT_DOLT_RESTART_BACKOFF_SECONDS",
    "DEFAULT_DOLT_RESTART_BUDGET_COUNT",
    "DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS",
    "DEFAULT_NOTIFY_INTERVAL_SECONDS",
    "DEFAULT_REAP_INTERVAL_SECONDS",
    "DoltSupervisionExhaustedError",
    "PortAction",
    "PortConflictError",
    "WebIntegrationConfig",
    "WebServerStartupError",
    "classify_port_holders",
    "default_dolt_dir",
    "dolt_supervisor_loop",
    "ensure_port_available",
    "get_port_holder_pids",
    "import_web_modules",
    "notify_loop",
    "notify_project",
    "notify_sweep",
    "port_holder_responds",
    "reap_loop",
    "reap_project",
    "reap_sweep",
    "read_owned_pid",
    "serve",
    "spawn_dolt",
]
