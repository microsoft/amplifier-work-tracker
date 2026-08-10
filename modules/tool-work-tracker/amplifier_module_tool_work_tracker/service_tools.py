"""`work_tracker_status` / `work_tracker_install` -- the bundle-bootstrap tools.

The scenario these exist for: a user installs ONLY the work-tracker behavior
bundle, then generically asks a session "use work-tracker for this task."
From a completely fresh machine (no service installed, no dolt server
running, maybe not even bd on PATH yet), the session needs a way to figure
out what's missing and fix it -- without guessing, and without silently
doing something invasive on the user's behalf.

Modeled on muxplex's `muxplex_status` tool pattern (structured state +
the exact fix command for each state), extended with this project's own
service-install state:

  - not_installed          -- no service, no dolt server reachable
  - installed_not_running  -- service exists but isn't active (or is active
                               but dolt hasn't come up yet)
  - running_healthy        -- service active AND dolt actually reachable
  - foreign_server_on_port -- something IS answering on the dolt port, but
                               not via our service -- see supervisor.py's
                               `classify_port_holders` for why this is kept
                               distinct rather than folded into "healthy"

`work_tracker_install` is the ONLY thing that changes system state, and it is
never invoked as a side effect of `work_tracker_status` or any other tool --
both reference projects (amplifier-browser-bridge, muxplex) deliberately
refuse ambient side effects for exactly this class of action (installing a
persistent background service). The LLM must decide to call it, once,
explicitly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from amplifier_core import ToolResult

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import service as S
from amplifier_work_tracker import supervisor as SV

WorkTrackerState = Literal[
    "not_installed", "installed_not_running", "running_healthy", "foreign_server_on_port"
]

_INSTALL_WAIT_TIMEOUT_S = 15.0
_INSTALL_WAIT_POLL_S = 0.5


def _resolve_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    root_raw = cfg.get("root")
    return A.Workspace(Path(root_raw) if root_raw else None).root


def classify_state(root: Path) -> tuple[WorkTrackerState, str]:
    """The whole state machine, and nothing else decides it. Pure given its
    three inputs (`service.describe_service()`'s installed/active,
    `supervisor.port_holder_responds()`) -- kept as a small, directly
    testable function separate from the async tool plumbing around it.

    Returns (state, fix_command) -- `fix_command` is empty only for
    `running_healthy`, where there is nothing to fix.
    """
    info = S.describe_service()
    port_reachable = SV.port_holder_responds(SV.DEFAULT_DOLT_HOST, SV.DEFAULT_DOLT_PORT)

    if port_reachable and not (info.installed and info.active):
        return (
            "foreign_server_on_port",
            f"something is already answering on {SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT} "
            f"but not via this service -- inspect it first (`lsof -i :{SV.DEFAULT_DOLT_PORT}`), "
            f"stop it if it's safe to, then run work_tracker_install",
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
            "'not_installed', 'installed_not_running', 'running_healthy', or "
            "'foreign_server_on_port', plus the exact fix command for that state. Call this "
            "FIRST the first time you use work-tracker in a session -- work_claim/work_status "
            "and the amplifier-work-tracker CLI both need a reachable dolt server, and this is "
            "how you find out whether one exists before assuming it does."
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
        state, _ = await asyncio.to_thread(classify_state, root)
        if state == "foreign_server_on_port":
            return ToolResult(
                success=False,
                output=(
                    f"refusing to install: something else is already answering on "
                    f"{SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT} that this service did not "
                    f"start. Stop it first (check `lsof -i :{SV.DEFAULT_DOLT_PORT}`), then retry."
                ),
            )
        try:
            info = await asyncio.to_thread(S.service_install, root)
        except S.ServiceUnsupportedError as e:
            return ToolResult(success=False, output=f"could not install: {e}")
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
