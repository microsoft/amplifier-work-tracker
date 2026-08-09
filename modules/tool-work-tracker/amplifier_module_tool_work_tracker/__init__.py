"""Amplifier tool module for amplifier-work-tracker.

Exposes `work_claim`, `work_declare`, `work_resolve`, `work_status`, and
`work_file` as agent-callable tools, backed directly by
`amplifier_work_tracker.adapter` / `amplifier_work_tracker.custody`. This
module contains no Beads knowledge of its own and shells out to nothing --
all domain logic lives in the `amplifier_work_tracker` package it imports.

Why a tool module, and not "just shell out to the CLI in bash":
`amplifier-work-tracker custody` binds its liveness signal to a PID, and
defaults that PID to `os.getppid()`. Invoked as a backgrounded bash call, the
parent is the transient shell the bash tool spawned for that one call -- a
process that can exit the moment the call returns, well before the agent's
real work is done. The custody renewal thread would then watch a PID that is
already gone, the supervisor would see "holder died," and `reap` would
release the item back to the queue mid-work, silently. A tool module runs
*inside* the durable agent session process. `os.getpid()` here names that
actual long-lived process, so there is no shorter-lived intermediary PID to
accidentally bind custody to.

`work_claim` is deliberately the ONLY way to take an item: it performs the
atomic claim and starts custody in one indivisible call. There is no
separate "start custody" tool and no claim-by-id tool -- both would reopen
the double-claim and mis-bound-PID hazards this module exists to close.
"""

from __future__ import annotations

import os
import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amplifier_core import ToolResult

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

_MIN_RENEW_INTERVAL_SECONDS = 5


def _resolve_actor(config: dict[str, Any] | None) -> str:
    """One holder identity per mounted session.

    Preference order: explicit config, then an operator-supplied env var,
    then a generated fallback that is at least stable for the life of this
    OS process (so a crash-and-restart doesn't reuse a dead identity).
    """
    cfg = config or {}
    explicit = cfg.get("actor") or os.environ.get("AMPLIFIER_WORK_TRACKER_ACTOR")
    if explicit:
        return str(explicit)
    return f"agent-{socket.gethostname()}-{os.getpid()}"


def _renew_interval_seconds(config: dict[str, Any] | None) -> int:
    cfg = config or {}
    raw = cfg.get("renew_interval_seconds") or os.environ.get(
        "AMPLIFIER_WORK_TRACKER_RENEW_INTERVAL_SECONDS", str(C.RENEW_INTERVAL_SECONDS)
    )
    return max(int(raw), _MIN_RENEW_INTERVAL_SECONDS)


@dataclass
class _Held:
    """The single item this session currently holds, and the background
    thread renewing its custody signal. One session holds at most one item
    at a time -- claiming a second before resolving the first is refused,
    matching the "exactly one owner per item" model this bundle exists to
    enforce.
    """

    project: str
    item_id: str
    actor: str
    generation: int
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    lost_reason: str | None = None


class WorkTrackerSession:
    """Backs all five work_* tools for one mounted session.

    Holds at most one claimed item's custody-renewal thread at a time. The
    renewal thread is the direct replacement for `amplifier-work-tracker
    custody &` -- it does the same renew-on-a-timer job, but bound to this
    process's own PID rather than a caller-supplied one, and without
    needing a second backgrounded process at all.
    """

    def __init__(self, config: dict[str, Any] | None):
        self._config = config or {}
        self._actor = _resolve_actor(config)
        root_raw = self._config.get("root") or os.environ.get("AMPLIFIER_WORK_TRACKER_ROOT")
        self._ws = A.Workspace(Path(root_raw) if root_raw else None)
        self._held: _Held | None = None
        self._lock = threading.Lock()

    def _project(self, name: str) -> A.Beads:
        return self._ws.project(name, actor=self._actor)

    def _renew_loop(self, held: _Held) -> None:
        interval = _renew_interval_seconds(self._config)
        bd = self._project(held.project)
        while not held.stop.wait(interval):
            try:
                rec = bd.renew_custody(
                    held.item_id,
                    holder=held.actor,
                    generation=held.generation,
                    pid=os.getpid(),
                )
                held.generation = rec["generation"]
            except A.BeadsError as e:
                # Fenced out: someone else now holds this item (a reap, or a
                # takeover). Stop renewing -- work_status/work_resolve report
                # the loss rather than silently keep trying forever.
                held.lost_reason = str(e)
                held.stop.set()
                return

    # ------------------------------------------------------------ tools

    async def claim(self, project: str) -> ToolResult:
        with self._lock:
            if self._held is not None:
                return ToolResult(
                    success=False,
                    output=(
                        f"already holding {self._held.item_id!r} in project "
                        f"{self._held.project!r} -- resolve it with work_resolve "
                        f"before claiming another item"
                    ),
                )
            try:
                bd = self._project(project)
                item = bd.claim_next(lane=A.LANE_WORK, actor=self._actor)
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            if item is None:
                return ToolResult(
                    success=True,
                    output={
                        "claimed": None,
                        "reason": (
                            "no ready work in lane -- this is a normal terminal "
                            "outcome, not an error. Stop; do not invent work."
                        ),
                    },
                )
            try:
                rec = bd.take_custody(
                    item.id,
                    holder=self._actor,
                    pid=os.getpid(),
                    host=socket.gethostname(),
                )
            except A.BeadsError as e:
                return ToolResult(
                    success=False,
                    output=f"claimed {item.id} but could not establish custody: {e}",
                )
            held = _Held(
                project=project,
                item_id=item.id,
                actor=self._actor,
                generation=rec["generation"],
            )
            held.thread = threading.Thread(
                target=self._renew_loop, args=(held,), daemon=True, name=f"custody-{item.id}"
            )
            held.thread.start()
            self._held = held
            return ToolResult(
                success=True,
                output={
                    "claimed": item.id,
                    "title": item.title,
                    "acceptance": item.acceptance,
                    "description": item.description,
                    "design": item.design,
                    "custody": "established -- renewing automatically in the background",
                },
            )

    async def declare(self, state: str) -> ToolResult:
        if state not in C.VALID_STATES:
            return ToolResult(
                success=False,
                output=f"state must be one of {C.VALID_STATES}, got {state!r}",
            )
        with self._lock:
            held = self._held
            if held is None:
                return ToolResult(success=False, output="not holding any item -- claim one first")
            try:
                bd = self._project(held.project)
                rec = bd.renew_custody(
                    held.item_id,
                    holder=held.actor,
                    generation=held.generation,
                    pid=os.getpid(),
                    declared_state=state,
                )
                held.generation = rec["generation"]
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            return ToolResult(success=True, output={"id": held.item_id, "declared_state": state})

    async def resolve(self, item_id: str, reason: str) -> ToolResult:
        with self._lock:
            held = self._held
            if held is None or held.item_id != item_id:
                return ToolResult(
                    success=False,
                    output=(
                        f"not currently holding {item_id!r} in this session -- "
                        f"refusing to resolve an item this session did not claim"
                    ),
                )
            try:
                bd = self._project(held.project)
                item = bd.resolve(item_id, reason, actor=held.actor)
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            held.stop.set()
            self._held = None
            return ToolResult(
                success=True, output={"resolved": item.id, "resolution": item.resolution}
            )

    async def status(self) -> ToolResult:
        projects: list[dict[str, Any]] = []
        for name in self._ws.names():
            try:
                items = self._ws.project(name).list(include_resolved=True)
                projects.append(
                    {
                        "project": name,
                        "total": len(items),
                        "ready": sum(
                            1 for i in items if i.status == "open" and A.LANE_WORK in i.tags
                        ),
                        "held": sum(1 for i in items if i.status == "held"),
                    }
                )
            except A.BeadsError as e:
                projects.append({"project": name, "status": f"ERROR: {e}"[:120]})
        with self._lock:
            held = self._held
            holding = (
                {
                    "project": held.project,
                    "id": held.item_id,
                    "custody_lost": held.lost_reason,
                }
                if held
                else None
            )
        return ToolResult(success=True, output={"projects": projects, "holding": holding})

    async def file(
        self,
        title: str,
        *,
        description: str | None = None,
        acceptance: str | None = None,
    ) -> ToolResult:
        with self._lock:
            held = self._held
            if held is None:
                return ToolResult(
                    success=False,
                    output=(
                        "not holding any item -- discovered work must link "
                        "discovered-from the item you are currently working"
                    ),
                )
            try:
                bd = self._project(held.project)
                new_id = bd.create(
                    title,
                    kind="bug",
                    tags=[A.LANE_WORK],
                    description=description,
                    acceptance=acceptance,
                    discovered_from=[held.item_id],
                    actor=held.actor,
                )
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            return ToolResult(
                success=True, output={"filed": new_id, "discovered_from": held.item_id}
            )


# --------------------------------------------------------------------------
# Tool classes -- one per work_* tool, all sharing one WorkTrackerSession.
# --------------------------------------------------------------------------


class WorkClaimTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_claim"

    @property
    def description(self) -> str:
        return (
            "Atomically claim the next ready work item from a project's queue AND "
            "establish PID-bound custody in one indivisible call. There is no "
            "separate 'start custody' step and no claim-by-id path -- calling this "
            "tool IS both the claim and the custody start, bound to this session's "
            "own process. Returns the item's acceptance criteria (your spec) and "
            "description/design for color, or {claimed: null} if the queue is "
            "empty -- which is a normal terminal outcome, not an error."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Named project to claim from."},
            },
            "required": ["project"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.claim(input["project"])


class WorkDeclareTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_declare"

    @property
    def description(self) -> str:
        return (
            "Report this session's declared state for the item it currently "
            "holds: 'working' or 'awaiting_human'. This is reporting only -- it "
            "renews the custody signal (so it never causes staleness by itself) "
            "but never buys exemption from the custody clock, and "
            "'awaiting_human' only suppresses a human-attention notification, "
            "never reclaim eligibility. Use it right before you go idle waiting "
            "on a person, and again when you resume."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": list(C.VALID_STATES),
                    "description": "'working' or 'awaiting_human'.",
                },
            },
            "required": ["state"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.declare(input["state"])


class WorkResolveTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_resolve"

    @property
    def description(self) -> str:
        return (
            "Fenced close of the item this session currently holds. Refuses if "
            "this session's claim was reclaimed while it was away, so a stale "
            "session cannot silently close work it no longer owns. 'reason' is "
            "read by the person who reported the underlying issue -- write it "
            "for them, not for a changelog. Stops the custody-renewal thread on "
            "success."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Item id this session holds."},
                "reason": {
                    "type": "string",
                    "description": "User-readable resolution text.",
                },
            },
            "required": ["id", "reason"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.resolve(input["id"], input["reason"])


class WorkStatusTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_status"

    @property
    def description(self) -> str:
        return (
            "Read-only: every known project with its total/ready/held item "
            "counts, plus what this session currently holds (if anything), "
            "including whether its custody was lost since claiming. Takes no "
            "arguments."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.status()


class WorkFileTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_file"

    @property
    def description(self) -> str:
        return (
            "File a newly discovered problem, linked discovered-from the item "
            "this session currently holds. Non-blocking -- it will not wedge "
            "your current work, and does not need a resolved acceptance "
            "criteria of its own to land in the queue. Requires this session "
            "to be holding an item (work_claim first)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the new item."},
                "description": {
                    "type": "string",
                    "description": "What's actually happening.",
                },
                "acceptance": {
                    "type": "string",
                    "description": "Given/When/Then acceptance criteria, if known.",
                },
            },
            "required": ["title"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.file(
            input["title"],
            description=input.get("description"),
            acceptance=input.get("acceptance"),
        )


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mount all five work_* tools, sharing one WorkTrackerSession.

    IRON LAW: every tool below is registered via `coordinator.mount()`.
    Skipping any of them (or returning without mounting) fails
    `protocol_compliance` for every agent that uses this behavior.
    """
    session = WorkTrackerSession(config)
    tools = [
        WorkClaimTool(session),
        WorkDeclareTool(session),
        WorkResolveTool(session),
        WorkStatusTool(session),
        WorkFileTool(session),
    ]
    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
    return {
        "name": "tool-work-tracker",
        "version": "0.1.0",
        "provides": [tool.name for tool in tools],
    }
