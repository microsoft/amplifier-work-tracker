"""`work_tracker_status` / `work_tracker_install` -- the bundle-bootstrap tools.

The scenario these exist for: a user installs ONLY the work-tracker behavior
bundle, then generically asks a session "use work-tracker for this task."
From a completely fresh machine (no service installed, no dolt server
running, not even `bd`/`dolt` on PATH yet), the session needs a way to figure
out what's missing and fix it -- without guessing, and without silently
doing something invasive on the user's behalf.

Modeled on muxplex's `muxplex_status` tool pattern (structured state +
the exact fix command for each state), extended with this project's own
service-install state. Checked in dependency order -- see `prereqs.check`'s
docstring -- because there is no point classifying service/port state when
there is no `bd`/`dolt` binary to run anything with in the first place:

  - bd_missing             -- `bd` is not on PATH at all
  - bd_too_old             -- `bd` is on PATH but below `adapter.MIN_VERSION`
                               (or its version could not be read at all)
  - dolt_missing           -- `dolt` is not on PATH at all
  - not_installed          -- no service, no dolt server reachable
  - installed_not_running  -- service exists but isn't active (or is active
                               but dolt hasn't come up yet)
  - running_healthy        -- service active AND dolt actually reachable
  - running_unmanaged      -- something IS answering on the dolt port, but
                               not via our service -- and it IS a healthy,
                               usable dolt server (bd's shared-server
                               topology is one server per host:port,
                               regardless of who started it -- a human, an
                               earlier `bd`-lazy-autostart, or a completely
                               separate session). This is a WORKING server,
                               not an intruder: the fix is "use it as-is, or
                               install to bring it under supervision" --
                               never "stop it." See supervisor.py's
                               `classify_port_holders` for the same
                               responds/owned-by-us discrimination applied
                               at `serve` startup time.

`work_tracker_install` is the ONLY thing that changes system state, and it is
never invoked as a side effect of `work_tracker_status` or any other tool --
both reference projects (amplifier-browser-bridge, muxplex) deliberately
refuse ambient side effects for exactly this class of action (installing a
persistent background service). The LLM must decide to call it, once,
explicitly. It refuses loudly (never attempts, never guesses) when a
prerequisite binary is missing -- see `WorkTrackerInstallTool.execute`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from amplifier_core import ToolResult

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import prereqs as P
from amplifier_work_tracker import service as S
from amplifier_work_tracker import supervisor as SV

WorkTrackerState = Literal[
    "bd_missing",
    "bd_too_old",
    "dolt_missing",
    "not_installed",
    "installed_not_running",
    "running_healthy",
    "running_unmanaged",
]

# States where the fix is "install a missing/too-old binary yourself" --
# work_tracker_install must refuse rather than attempt a service install
# that would only fail confusingly later (e.g. `dolt sql-server` spawned
# from a PATH that has no `dolt` on it).
_PREREQ_STATES: frozenset[WorkTrackerState] = frozenset(
    {"bd_missing", "bd_too_old", "dolt_missing"}
)

_INSTALL_WAIT_TIMEOUT_S = 15.0
_INSTALL_WAIT_POLL_S = 0.5


def _resolve_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    root_raw = cfg.get("root")
    return A.Workspace(Path(root_raw) if root_raw else None).root


def classify_state(root: Path) -> tuple[WorkTrackerState, str]:
    """The whole state machine, and nothing else decides it. Pure given its
    inputs (`prereqs.check()`'s bd/dolt presence and version,
    `service.describe_service()`'s installed/active,
    `supervisor.port_holder_responds()`) -- kept as a small, directly
    testable function separate from the async tool plumbing around it.

    Dependency-ordered: `prereqs.check()` runs FIRST, and if it reports a
    missing/too-old binary, the service/port checks below never run at all
    -- mirroring `cli.py`'s `cmd_doctor` (`_check_dolt_reachable` is
    `skipped` once `service.installed` already failed) rather than piling
    unrelated red on top of the one real root cause.

    Returns (state, fix_command) -- `fix_command` is empty only for
    `running_healthy`, where there is nothing to fix.
    """
    prereq = P.check()
    if prereq is not None:
        return prereq.state, prereq.fix

    info = S.describe_service()
    port_reachable = SV.port_holder_responds(SV.DEFAULT_DOLT_HOST, SV.DEFAULT_DOLT_PORT)

    if port_reachable and not (info.installed and info.active):
        # A real, actively-responding dolt IS a usable shared server --
        # bd's shared-server topology is one server per host:port,
        # regardless of who started it (a human, an earlier `bd`-lazy
        # autostart, or a completely separate session). Advising "stop it"
        # here would steer a caller into killing a functioning queue that
        # may hold live claims -- see this module's docstring and
        # supervisor.classify_port_holders, whose refuse_ours/refuse_foreign
        # split this mirrors: a healthy responder is never something to
        # kill, only something this service either uses as-is or declines
        # to double-serve.
        return (
            "running_unmanaged",
            f"a dolt server is already healthy and reachable on "
            f"{SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT}, it just isn't managed by this "
            f"service yet -- this is a WORKING server, not a problem to fix. You can use it "
            f"directly right now (work_claim/work_status/the CLI will all work against it), or "
            f"call work_tracker_install to bring it under this service's supervision so it "
            f"survives reboot and gets the reap/notify sweeps -- installing does NOT stop or "
            f"replace it; the supervisor refuses to double-serve instead of colliding with it. "
            f"Do not stop this process -- it may be holding live claims from other sessions "
            f"(`lsof -i :{SV.DEFAULT_DOLT_PORT}` to see what it is, if you want to know).",
        )
    if not info.installed:
        return "not_installed", "call work_tracker_install to set up the background service"
    if not info.active:
        return (
            "installed_not_running",
            "amplifier-work-tracker service start  (or `service logs` to see why it stopped)",
        )
    if not port_reachable:
        return (
            "installed_not_running",
            "service is active but dolt is not yet reachable -- try again shortly, or "
            "`amplifier-work-tracker service logs`",
        )
    return "running_healthy", ""


async def _wait_for_dolt_reachable(
    host: str, port: int, *, timeout: float = _INSTALL_WAIT_TIMEOUT_S
) -> bool:
    """Poll (never a bare sleep-and-hope) until dolt answers, or timeout.
    Turns "the unit file was written" into "dolt is actually reachable" --
    these are not the same fact (see service.py's install docstring: a
    freshly-installed unit can still be failing to bind)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if await asyncio.to_thread(SV.port_holder_responds, host, port):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(_INSTALL_WAIT_POLL_S)


class WorkTrackerStatusTool:
    def __init__(self, config: dict[str, Any] | None):
        self._config = config

    @property
    def name(self) -> str:
        return "work_tracker_status"

    @property
    def description(self) -> str:
        return (
            "Read-only: is the amplifier-work-tracker background service (shared dolt server + "
            "reap/notify sweeps) installed and healthy on THIS machine? Returns one of "
            "'bd_missing', 'bd_too_old', 'dolt_missing', 'not_installed', "
            "'installed_not_running', 'running_healthy', or 'running_unmanaged', plus the exact "
            "fix command for every state except 'running_healthy'/'running_unmanaged' (both "
            "already work; nothing to fix). 'running_unmanaged' means a dolt server is already "
            "healthy and reachable but not managed by this service -- it is USABLE as-is, never "
            "something to stop. Call this FIRST the first time you use work-tracker in a session "
            "-- work_claim/work_status and the amplifier-work-tracker CLI both need a reachable "
            "dolt server, and this is how you find out whether one exists before assuming it does."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        root = _resolve_root(self._config)
        state, fix = await asyncio.to_thread(classify_state, root)
        output: dict[str, Any] = {"state": state, "root": str(root)}
        if fix:
            output["fix"] = fix
        # Separate from `state`/`fix` above: this is about OUR OWN CLI, not
        # bd/dolt or the background service. A session that only calls this
        # tool (never shells out to `amplifier-work-tracker` by name) would
        # never notice the console script is unreachable -- but a session
        # that reads this field before trying `amplifier-work-tracker
        # doctor`/`status` at a shell gets the resolved path and the exact
        # fix instead of a `command not found` and a multi-call hunt.
        console_script_path, console_script_fix = await asyncio.to_thread(S.resolve_console_script)
        if console_script_fix:
            output["console_script_path"] = console_script_path
            output["console_script_fix"] = console_script_fix
        return ToolResult(success=True, output=output)


class WorkTrackerInstallTool:
    def __init__(self, config: dict[str, Any] | None):
        self._config = config

    @property
    def name(self) -> str:
        return "work_tracker_install"

    @property
    def description(self) -> str:
        return (
            "Install and start the amplifier-work-tracker background service (systemd --user on "
            "Linux, launchd on macOS): the shared dolt server plus the reap/notify sweeps, so "
            "they survive logout and reboot. Installs, starts, and VERIFIES the dolt server is "
            "actually reachable before reporting success -- a partial/failed install is reported "
            "as failure, never silently swallowed. This is the ONLY tool that changes system "
            "state here; it is never invoked automatically by work_tracker_status or any other "
            "tool -- call it explicitly, and only when work_tracker_status says you need to."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        root = _resolve_root(self._config)
        state, fix = await asyncio.to_thread(classify_state, root)
        if state in _PREREQ_STATES:
            # Refuse loudly rather than attempt a service install that would
            # only fail confusingly downstream (e.g. a unit whose ExecStart
            # spawns `dolt sql-server` from a PATH that has no `dolt` on it).
            # Never auto-download the missing binary ourselves -- see this
            # module's docstring and prereqs.py's: report + exact command,
            # let the agent or human run it.
            return ToolResult(
                success=False,
                output=f"refusing to install: {fix}",
            )
        if state == "running_unmanaged":
            # Refuses to INSTALL (a fresh unit would immediately crash-loop
            # against the already-bound port -- see supervisor.py's
            # refuse_foreign), but the advice is adoption, never "kill it":
            # this is a working server, and the classification above already
            # says so.
            return ToolResult(
                success=False,
                output=(
                    f"not installing: a dolt server is already healthy and reachable on "
                    f"{SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT} -- it works as-is, so there "
                    f"is nothing broken to fix here. Use it directly (work_claim/work_status/the "
                    f"CLI all work against it right now), or if you want it to survive reboot and "
                    f"get the reap/notify sweeps, stop whatever is running it yourself first, "
                    f"THEN call work_tracker_install -- installing on top of a server already "
                    f"bound to this port would only crash-loop, not adopt it. Do not stop it "
                    f"just to install; only do so if you actually want the switch to the "
                    f"supervised service."
                ),
            )
        try:
            info = await asyncio.to_thread(S.service_install, root)
        except S.ServiceUnsupportedError as e:
            return ToolResult(success=False, output=f"could not install: {e}")
        except Exception as e:  # noqa: BLE001 -- see module docstring: never a raw traceback string
            # A raw `str(CalledProcessError(...))` (e.g. "Command
            # ['systemctl', '--user', 'daemon-reload'] returned non-zero exit
            # status 1.") reads like an unhandled crash and gives no hint
            # this might mean "no systemd --user session in this
            # container/environment." Wrap it with what was attempted and an
            # actionable next step.
            #
            # `rollback_detail`, when `service_install` set it (see
            # service.py's `_systemd_install`/`_launchd_install`), reports
            # what rollback ACTUALLY did -- observed per-step results, never
            # an asserted claim. Never hardcode "nothing was left behind":
            # that was a lie whenever rollback itself failed a step (e.g.
            # the unit file couldn't be removed), and this code has no way
            # to know that without asking what actually happened.
            rollback_detail = getattr(e, "rollback_detail", None)
            rollback_report = (
                f"Rollback attempted: {rollback_detail}"
                if rollback_detail
                else "Rollback outcome unknown -- this failure did not come with an observed "
                "rollback report; check `amplifier-work-tracker service status` / "
                "`systemctl --user status amplifier-work-tracker` for any residue."
            )
            return ToolResult(
                success=False,
                output=(
                    f"could not install the background service: {e}. This usually means "
                    f"systemd/launchd itself isn't functioning here (e.g. a container without a "
                    f"running --user systemd instance, or without `systemctl`/`launchctl` able to "
                    f"reach a session bus) rather than anything wrong with amplifier-work-tracker "
                    f"itself. {rollback_report} If this platform can't run a background service, "
                    f"run `amplifier-work-tracker serve --root {root}` directly in a persistent "
                    f"terminal/tmux session instead."
                ),
            )
        reachable = await _wait_for_dolt_reachable(SV.DEFAULT_DOLT_HOST, SV.DEFAULT_DOLT_PORT)
        if not reachable:
            return ToolResult(
                success=False,
                output=(
                    f"service installed ({info.platform}, unit: {info.unit_path}) but dolt never "
                    f"became reachable on {SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT} within "
                    f"{_INSTALL_WAIT_TIMEOUT_S:.0f}s -- check `amplifier-work-tracker service logs`"
                ),
            )
        return ToolResult(
            success=True,
            output={
                "installed": True,
                "platform": info.platform,
                "unit": str(info.unit_path) if info.unit_path else None,
                "dolt_reachable": True,
            },
        )


__all__ = ["WorkTrackerInstallTool", "WorkTrackerStatusTool", "classify_state"]
