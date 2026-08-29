"""Amplifier tool module for amplifier-work-tracker.

Exposes `work_claim`, `work_declare`, `work_resolve`, `work_release`,
`work_status`, `work_stats`, `work_file`, `work_add`, `work_move`,
`work_list`, `work_subscribe`, `work_unsubscribe`, and `work_subscriptions`
as agent-callable tools, backed directly by `amplifier_work_tracker.adapter`
/ `amplifier_work_tracker.custody`.
This module contains no Beads knowledge of its own and shells out to nothing --
all domain logic lives in the `amplifier_work_tracker` package it imports.

`work_subscribe`/`work_unsubscribe`/`work_subscriptions` (amplifier-bxq) let a
session opt a project's status IN to (or out of) a compact, cadence-gated
reminder injected into its context by the separate `hooks-work-subscribe-
reminder` hook module -- ready/held counts, whether this session holds
anything, and whether that held item's custody is stale. `work_claim`
auto-subscribes to whatever project it claims from (see `claim`'s
`lane:gb-subscribe` note), so the common case needs no extra call. This tool
module never injects anything itself: it only computes and exposes
`WorkTrackerSession.reminder_snapshot` as the `work_tracker.reminder_snapshot`
CAPABILITY (`coordinator.register_capability`, see `mount`), which the hook
module reads. Subscriptions are session-scoped, in-memory only -- see
`WorkTrackerSession.__init__`'s `lane:gb-subscribe` note for why that is an
explicit design choice, not an oversight.

`work_move` is the sanctioned way to migrate a work item from one project's
queue to another -- before it existed, there was no supported path for an
agent (or a human, via the CLI's `move` counterpart) to do this at all. No
held item required (unlike `work_file`/`work_resolve`/`work_release`); it
delegates entirely to `adapter.move_item` (via `Workspace.move_item`) for the
refusal/atomicity contract -- see that function's docstring for the full
story on HELD-item safety, id preservation, and cross-project dependency
handling.

`work_list` is the read-only per-item view `work_status` deliberately does
not provide (that tool reports project-level counts only). It exists because
a real three-agent contention test surfaced a genuine gap: every agent could
see `{held: 0, ready: 0}` after the queue drained, but none of them had a
sanctioned way to see WHICH items existed, WHO held each one, or what
resolution a closed item ended up with -- forcing a raw `bd list --all
--json` shell-out to verify the run, exactly the kind of seam-leaking escape
this bundle exists to make unnecessary. Strictly read-only: it never claims,
mutates, or touches custody -- see `WorkTrackerSession.list_items`.

`work_list`'s `item_id` parameter closes the OTHER read gap: until now,
`work_claim` was the ONLY thing that returned an item's `description` /
`acceptance` / `design` -- so an agent that merely wanted to understand what
an item was asking for had to take ownership of it first to find out. Pass
`item_id` to `work_list` (or `--id` to the CLI's `list`) to read one item's
full record instead, exactly like `work_claim`'s own directed-by-`item_id`
mode (PR #4), but without claiming, mutating, or touching custody -- see
`adapter.Beads.get_readonly`.

`work_add` is the sanctioned path for filing a project's FIRST work item (or
any later one) with no held item required -- unlike `work_file`, which
requires this session to already be holding something and links
discovered-from it. Before `work_add` existed, there was no tool-level way
to seed a brand-new project's queue at all: `work_file` refused (nothing
held yet), and the CLI's `new` only creates the PROJECT, not any work inside
it. That gap forced a real session to go around the seam entirely -- raw
`bd create` plus a hand-guessed `bd label add <id> lane:eng` (inferring the
lane label vocabulary from an unrelated agent description) -- exactly the
kind of raw-`bd` escape the `claiming-work-safely` skill's "never touch
`bd` directly" rule forbids. `work_add` (and the CLI's `add`) apply the
engineering lane label themselves; a caller never needs to know `lane:eng`
exists.

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
separate "start custody" tool -- that would reopen the mis-bound-PID hazard
this module exists to close. It DOES support two claim modes, both routed
through the same atomic-claim-then-custody path: the default queue claim
(next ready item), and a directed claim by item_id (a specific item, e.g.
one a human or planning session named). Both are single atomic bd calls --
`bd ready --claim` for the queue path, `bd update <id> --claim` for the
directed path -- never the two-step "list, pick, then claim" race that
double-claims under contention. See `amplifier_work_tracker.adapter.Beads
.claim_item` for why a directed claim is safe (measured atomicity) and what
it refuses (already-held, not-found, blocked-by-open-dependency).
"""

from __future__ import annotations

import os
import socket
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from amplifier_core import ToolResult

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

from ._guard import guarded
from .service_tools import WorkTrackerInstallTool, WorkTrackerStatusTool

_MIN_RENEW_INTERVAL_SECONDS = 5


def _summary_errored(summary: A.ProjectSummary) -> bool:
    """A project's summary represents a genuine READ failure -- an
    unreadable database whose status is a truncated `"ERROR: ..."` string
    (see `adapter.project_summary`). `STATUS_OK`, and the honest
    mid-creation / left-broken states (`STATUS_CREATING`/`STATUS_BROKEN`),
    are NOT read failures: they are the operation succeeding and reporting a
    known non-`ok` condition, exactly as an empty project is a success.
    Only a real error flips the outer envelope to `success=False`, matching
    the pre-`project_summary` behaviour where a caught `A.BeadsError` was
    the only thing that did.
    """
    return summary.status.startswith("ERROR")


def _project_summary_row(summary: A.ProjectSummary) -> dict[str, Any]:
    """One project's full `ProjectSummary` as a JSON-ready row -- every
    status field (open/ready/held/intake/blocked/deferred/resolved) plus the
    aging/throughput figures, keyed under `project` (not `name`) to match the
    long-standing `work_status` payload shape. This is the SAME computation
    the CLI's `instances`/`status` commands and the web dashboard render, so
    the tool surface can never silently disagree with them.
    """
    row: dict[str, Any] = {"project": summary.name}
    for key, value in asdict(summary).items():
        if key != "name":
            row[key] = value
    return row


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
        # lane:gb-subscribe -- session-scoped subscription list (see
        # `subscribe`/`unsubscribe`/`subscriptions`/`reminder_snapshot` below).
        # Ordered, de-duplicated project names. Deliberately in-memory only:
        # this list lives exactly as long as `_held` does above -- for the
        # life of THIS mounted session's process, never persisted to disk and
        # never inherited by a forked sub-session (each gets its own fresh
        # `WorkTrackerSession`, per amplifier-core's one-mount()-per-session
        # contract -- see hooks-status-context's docstring for the same
        # invariant applied to its own per-session cache). A session that
        # wants reminders again after a restart must re-subscribe (or rely on
        # auto-subscribe-on-claim, see `claim` below) -- this is an explicit
        # design choice, not an oversight: durable cross-session subscription
        # state would need its own identity/storage story (which session
        # "is" which across a restart?) that nothing else in this module has
        # today, and nothing in the source request asked for it.
        self._subscriptions: list[str] = []

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
            except A.BeadsError as e:
                # Any renew failure ends this loop for good -- no retry on
                # the next interval, by design: a single failed renew already
                # means the signal wasn't refreshed, and the custody TTL will
                # do the rest regardless.
                #
                # A.FencedError specifically means bd no longer considers us
                # the holder (reaped while idle, or taken over) -- in that
                # case this session's OWN belief that it holds the item must
                # be dropped too. Leaving self._held set here was the
                # self-poisoning bug: work_claim/work_declare/work_resolve
                # for ANY item refused forever, for the rest of this
                # process's life, with no tool call able to clear it -- the
                # ordinary "held an item long enough to be reaped, did
                # nothing else" path this bundle exists to survive. A plain
                # (non-fenced) BeadsError -- e.g. a transient bd/dolt command
                # failure -- does NOT clear self._held: bd still considers us
                # the holder, so work_resolve can still succeed via its own
                # live fence check even though background renewal stopped.
                with self._lock:
                    held.lost_reason = str(e)
                    held.stop.set()
                    if isinstance(e, A.FencedError) and self._held is held:
                        self._held = None
                return
            with self._lock:
                held.generation = rec["generation"]

    # ------------------------------------------------------------ tools

    async def claim(self, project: str, *, item_id: str | None = None) -> ToolResult:
        """Claim work and establish custody in one indivisible call.

        Two modes, both atomic, both starting custody identically -- a
        directed claim is not a lesser claim:
          - `item_id` omitted (default): next ready item off the queue
            (`bd ready --claim`).
          - `item_id` given: that SPECIFIC item (`bd update <id> --claim`,
            see `adapter.Beads.claim_item`). Refuses (raises via
            A.BeadsError, surfaced below as a failed ToolResult) if it is
            already held by someone else, does not exist, or is blocked by
            an open dependency -- no override; resolve the blocker or
            claim again.
        """
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
                if item_id:
                    item = bd.claim_item(item_id, actor=self._actor)
                else:
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
            # lane:gb-subscribe -- auto-subscribe to the project this session
            # just claimed from. A reasonable default (an agent that is now
            # actively working a project's queue is exactly who benefits from
            # its status reminders), and additive-only: it never removes an
            # existing subscription, and an explicit `unsubscribe` still wins
            # if the agent doesn't want it.
            self._subscribe_locked(project)
            return ToolResult(
                success=True,
                output={
                    "claimed": item.id,
                    "title": item.title,
                    "acceptance": item.acceptance,
                    "description": item.description,
                    "design": item.design,
                    # Workspace-bootstrap metadata parsed from the item's
                    # description (see adapter.parse_bootstrap_metadata) --
                    # structured lists of the repos to check out and the
                    # context files this lane needs. Empty lists for an item
                    # that carries no fenced ```yaml block.
                    "repos": item.repos,
                    "context": item.context,
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
            except A.FencedError as e:
                # Reclaimed/reassigned while we were away -- clear local
                # state and stop custody so this session can claim again.
                # See `claim`'s "already holding" refusal and the
                # reap-recovery tests: leaving self._held set here is the
                # session-poisoning bug this fix closes.
                held.stop.set()
                self._held = None
                return ToolResult(success=False, output=str(e))
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
            except A.FencedError as e:
                # Reclaimed/reassigned while we were away -- clear local
                # state and stop custody so this session can claim again.
                # See `claim`'s "already holding" refusal and the
                # reap-recovery tests: leaving self._held set here is the
                # session-poisoning bug this fix closes.
                held.stop.set()
                self._held = None
                return ToolResult(success=False, output=str(e))
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            held.stop.set()
            self._held = None
            return ToolResult(
                success=True, output={"resolved": item.id, "resolution": item.resolution}
            )

    async def status(self) -> ToolResult:
        """Read-only project roll-up -- every known project with its FULL
        status breakdown (open/ready/held/intake/blocked/deferred/resolved,
        plus aging/throughput and custody-staleness signals), computed by
        `adapter.project_summary` -- the SAME function the CLI's `instances`
        command and the web dashboard use, so this tool can never silently
        disagree with them about what "ready"/"held" mean. It no longer
        hand-rolls its own `ready`/`held` counts.

        `success` is honest about whether EVERY project's status was
        actually retrieved: a project a real read error occurred for still
        gets an entry (its truncated `"ERROR: ..."` text, same as before --
        one broken project must never hide the healthy ones), but that
        error must not be invisible to the outer envelope too. Before this
        was fixed, a real, caught error here was buried as a string inside
        one project's entry while the overall ToolResult still reported
        `success=True` -- machine-invisible to any caller that only checks
        the envelope. An empty project (zero items) is NOT an error and
        never affects this -- that is 'the operation succeeded and the
        answer is empty', the case this must not conflate with a genuine
        failure. `project_summary` never raises: an unreadable database
        comes back as a summary whose `status` starts with `"ERROR"` (see
        `_summary_errored`), and the mid-creation / left-broken states are
        reported honestly without being treated as read failures.
        """
        projects: list[dict[str, Any]] = []
        any_project_errored = False
        for name in self._ws.names():
            summary = A.project_summary(self._ws, name)
            if _summary_errored(summary):
                any_project_errored = True
            projects.append(_project_summary_row(summary))
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
        return ToolResult(
            success=not any_project_errored, output={"projects": projects, "holding": holding}
        )

    async def stats(self, project: str) -> ToolResult:
        """The full `project_summary` breakdown for ONE named project in a
        single call -- the same per-status counts and aging/throughput/
        custody-staleness figures `status()` reports for every project,
        scoped to just this one. Read-only; never claims, mutates, or
        touches custody.

        `success` follows the same honesty rule as `status()`: `False` only
        when this project's database genuinely could not be read (its
        summary `status` starts with `"ERROR"` -- see `_summary_errored`),
        never for an empty, mid-creation, or left-broken project, which are
        all reported as honest non-failure states. `project_summary` never
        raises, so this method needs no try/except of its own.
        """
        summary = A.project_summary(self._ws, project)
        return ToolResult(
            success=not _summary_errored(summary), output=_project_summary_row(summary)
        )

    # ------------------------------------------------------- lane:gb-subscribe
    # Subscription management + the reminder-hook data source. See this
    # module's docstring for the design (session-scoped, not persisted; the
    # separate hook module never computes status itself -- it only reads
    # `reminder_snapshot()` below via the `work_tracker.reminder_snapshot`
    # capability registered in `mount()`).

    def _subscribe_locked(self, project: str) -> bool:
        """Add `project` to the subscription list if not already present.
        Caller must hold `self._lock`. Returns True if this call actually
        added it (False if already subscribed) -- used by `claim`'s
        auto-subscribe to report only genuine changes, and by `subscribe`
        to report idempotency honestly rather than always claiming success
        added something new.
        """
        if project in self._subscriptions:
            return False
        self._subscriptions.append(project)
        return True

    async def subscribe(self, project: str) -> ToolResult:
        """Subscribe this session to `project`'s status reminders.

        Validates the project actually exists first (`Workspace.project` --
        a local filesystem check, no dolt round trip) so a typo'd name fails
        loudly here rather than silently reminding about nothing forever.
        Idempotent: subscribing to an already-subscribed project is a
        no-op that still reports success.
        """
        try:
            self._project(project)
        except A.BeadsError as e:
            return ToolResult(success=False, output=str(e))
        with self._lock:
            added = self._subscribe_locked(project)
        return ToolResult(
            success=True,
            output={
                "subscribed": project,
                "already_subscribed": not added,
                "subscriptions": list(self._subscriptions),
            },
        )

    async def unsubscribe(self, project: str) -> ToolResult:
        """Unsubscribe this session from `project`'s status reminders.
        Idempotent: unsubscribing from a project never subscribed to is a
        no-op that still reports success (mutating nothing, refusing
        nothing -- there is nothing unsafe about this operation, unlike
        `unclaim`/`resolve`, so it needs no ownership fence).
        """
        with self._lock:
            was_subscribed = project in self._subscriptions
            if was_subscribed:
                self._subscriptions.remove(project)
            subs = list(self._subscriptions)
        return ToolResult(
            success=True,
            output={
                "unsubscribed": project,
                "was_subscribed": was_subscribed,
                "subscriptions": subs,
            },
        )

    async def subscriptions(self) -> ToolResult:
        """List this session's current subscriptions. Read-only."""
        with self._lock:
            subs = list(self._subscriptions)
        return ToolResult(success=True, output={"subscriptions": subs})

    async def reminder_snapshot(self) -> dict[str, Any]:
        """Compact status snapshot for the reminder-injection hook -- NOT a
        `ToolResult` (this is called directly by the hook module via the
        `work_tracker.reminder_snapshot` capability, not by an agent).

        For each subscribed project: the SAME `project_summary` row
        `status()`/`stats()` return (never a second, independently-computed
        set of counts). Plus this session's own holding pointer and, ONLY
        when holding something, whether that ONE held item's custody is
        currently reclaim-eligible -- a single extra `get_readonly` read,
        bounded to at most one item (never a project-wide scan), using the
        exact same `custody.reclaim_eligible` check `project_summary`'s own
        `held_stale` count is built from (see `_held_stale_count`). Never
        raises: a project that cannot be read reports `project_summary`'s
        own truncated `"ERROR: ..."` status like every other consumer; a
        failure reading the held item's fresh custody state reports
        `custody_stale=None` (unknown), never a fabricated True/False.
        """
        with self._lock:
            subs = list(self._subscriptions)
            held = self._held
        projects = [_project_summary_row(A.project_summary(self._ws, name)) for name in subs]
        holding: dict[str, Any] | None = None
        if held is not None:
            holding = {"project": held.project, "id": held.item_id, "custody_stale": None}
            try:
                bd = self._project(held.project)
                item = bd.get_readonly(held.item_id)
                meta = item.meta.get(C.CUSTODY_KEY) if isinstance(item.meta, dict) else None
                holding["custody_stale"] = C.reclaim_eligible(meta)[0]
            except A.BeadsError:
                pass  # custody_stale stays None -- unknown, not fabricated
        return {"subscriptions": projects, "holding": holding}

    async def unclaim(self, item_id: str) -> ToolResult:
        """Voluntarily hand a HELD item back to the queue -- the inverse of
        `claim`, and a sibling of `resolve` that sets NO resolution. Returns
        the item to open/ready and STOPS this session's custody-renewal
        thread, so the item is immediately claimable by anyone (including
        this session again) with no reclaim-timeout wait.

        Refuses -- clear error, mutates nothing -- if this session is not
        currently holding exactly `item_id`, the same fence `resolve` uses:
        a session must never release work it does not own. On a real bd
        failure the hold is left intact (custody keeps renewing), mirroring
        `resolve`'s non-fenced-error path; only a confirmed release stops
        custody and clears local state.
        """
        with self._lock:
            held = self._held
            if held is None or held.item_id != item_id:
                return ToolResult(
                    success=False,
                    output=(
                        f"not currently holding {item_id!r} in this session -- "
                        f"refusing to release an item this session did not claim"
                    ),
                )
            try:
                bd = self._project(held.project)
                bd.release(item_id)
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            held.stop.set()
            self._held = None
            return ToolResult(
                success=True,
                output={
                    "released": item_id,
                    "custody": "stopped -- item returned to the queue, no resolution set",
                },
            )

    async def list_items(
        self,
        project: str,
        *,
        item_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> ToolResult:
        """Read-only per-item listing -- id, title, status, holder, and
        (for closed items) resolution. Never claims, mutates, or touches
        custody: this method does not read or write `self._held`/`self._lock`
        at all, unlike every other tool method above. See
        `adapter.Beads.list_bounded` for the capping/truncation contract --
        `truncated`/`total_count` are always honest, never a silent cap.

        `item_id`, when given, switches to a directed single-item READ (see
        `adapter.Beads.get_readonly`): the full record for exactly that item
        -- including `acceptance`/`description`/`design`, the body fields
        only a successful `work_claim` used to return -- with no claim, no
        mutation, no custody touched. `status`/`limit` are ignored in this
        mode; mirrors `work_claim`'s own `item_id` (directed claim, PR #4)
        so the two directed-by-id shapes stay coherent. This is THE fix for
        the gap where understanding what an item asks for required first
        taking ownership of it.
        """
        if item_id:
            try:
                bd = self._project(project)
                item = bd.get_readonly(item_id)
            except A.BeadsError as e:
                return ToolResult(success=False, output=str(e))
            return ToolResult(
                success=True,
                output={
                    "project": project,
                    "items": [item.summary(full=True)],
                    "returned_count": 1,
                    "total_count": 1,
                    "truncated": False,
                    "limit": 1,
                },
            )
        try:
            bd = self._project(project)
            result = bd.list_bounded(status=status, limit=limit)
        except A.BeadsError as e:
            return ToolResult(success=False, output=str(e))
        return ToolResult(
            success=True,
            output={
                "project": project,
                "items": [i.summary() for i in result.items],
                "returned_count": result.returned_count,
                "total_count": result.total_count,
                "truncated": result.truncated,
                "limit": result.limit,
            },
        )

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

    async def add(
        self,
        project: str,
        title: str,
        *,
        description: str | None = None,
        acceptance: str | None = None,
    ) -> ToolResult:
        """File a new engineering-lane item directly -- no held item
        required. THE sanctioned path for seeding a project's first item(s)
        (see this module's docstring for why that gap otherwise forces a
        raw-`bd` escape). Applies A.LANE_WORK itself; callers never need to
        know the label vocabulary."""
        try:
            bd = self._project(project)
            new_id = bd.create(
                title,
                kind="task",
                tags=[A.LANE_WORK],
                description=description,
                acceptance=acceptance,
                actor=self._actor,
            )
        except A.BeadsError as e:
            return ToolResult(success=False, output=str(e))
        return ToolResult(
            success=True, output={"added": new_id, "project": project, "lane": A.LANE_WORK}
        )

    async def move(self, item_id: str, from_project: str, to_project: str) -> ToolResult:
        """Move one item from `from_project` to `to_project`, preserving its
        id -- no held item required (unlike `file`/`resolve`/`unclaim`, this
        never touches `self._held`/`self._lock` at all). Delegates entirely
        to `adapter.move_item` (via `Workspace.move_item`) for the actual
        refusal/atomicity contract: refuses if the item is currently HELD,
        does not exist in `from_project`, or already exists in
        `to_project`; a dependency edge to an item that is NOT moving is
        dropped rather than silently corrupted, and reported back here.
        """
        try:
            report = self._ws.move_item(from_project, to_project, item_id)
        except A.BeadsError as e:
            return ToolResult(success=False, output=str(e))
        return ToolResult(
            success=True,
            output={
                "moved": report.item_id,
                "from": report.src,
                "to": report.dst,
                "dropped_dependency_edges": report.dropped_dependency_edges,
            },
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
            "Atomically claim work AND establish PID-bound custody in one "
            "indivisible call. There is no separate 'start custody' step -- "
            "calling this tool IS both the claim and the custody start, bound "
            "to this session's own process. Two modes, both equally atomic: "
            "omit item_id for the default (next ready item off a project's "
            "queue -- prevents multiple agents converging on the same top "
            "item); pass item_id to claim a SPECIFIC item instead (e.g. one a "
            "human or planning session assigned directly). A directed claim "
            "refuses -- loudly, with no override -- if the item is already "
            "held by someone else (names the holder), does not exist, or is "
            "blocked by an open dependency (names the blocker). Returns the "
            "item's acceptance criteria (your spec) and description/design "
            "for color, or {claimed: null} if the queue is empty -- which is "
            "a normal terminal outcome, not an error (queue mode only; a "
            "directed claim either succeeds or raises, it never returns null)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Named project to claim from."},
                "item_id": {
                    "type": "string",
                    "description": (
                        "Optional. Claim this SPECIFIC item by id instead of the "
                        "next queued one. Refuses if already held by someone "
                        "else, not found, or blocked by an open dependency -- "
                        "no override flag."
                    ),
                },
            },
            "required": ["project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.claim(input["project"], item_id=input.get("item_id"))


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

    @guarded
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

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.resolve(input["id"], input["reason"])


class WorkReleaseTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_release"

    @property
    def description(self) -> str:
        return (
            "Voluntarily hand the item this session currently holds back to the "
            "queue -- the inverse of work_claim, WITHOUT setting a resolution "
            "(use work_resolve when the work is actually done). Returns the item "
            "to open/ready and stops this session's custody renewal, so it is "
            "immediately claimable again with no reclaim-timeout wait. Use it "
            "when you claimed something you should not work after all, or need to "
            "put it back for another agent. Refuses (mutating nothing) if this "
            "session does not hold the named item -- a session can never release "
            "work it does not own."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Item id this session holds."},
            },
            "required": ["id"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.unclaim(input["id"])


class WorkStatusTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_status"

    @property
    def description(self) -> str:
        return (
            "Read-only: every known project with its FULL status breakdown -- "
            "total plus per-status counts (ready/held/intake/blocked/deferred/"
            "resolved), aging/throughput (oldest-unclaimed age, resolved in the "
            "last 24h/7d), and custody-staleness signals (held_stale, who holds "
            "what) -- the same figures the CLI and web dashboard show. Also "
            "reports what this session currently holds (if anything), including "
            "whether its custody was lost since claiming. Takes no arguments. "
            "For the same breakdown scoped to ONE named project, use work_stats."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.status()


class WorkStatsTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_stats"

    @property
    def description(self) -> str:
        return (
            "Read-only: the FULL status breakdown for ONE named project in a "
            "single call -- total plus per-status counts (ready/held/intake/"
            "blocked/deferred/resolved), aging (oldest-unclaimed age), "
            "throughput (resolved in the last 24h/7d), and custody-staleness "
            "signals (held_stale, held_by). The same figures work_status "
            "reports for every project, scoped to just this one. Never claims, "
            "mutates, or touches custody."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Named project to report the full breakdown for.",
                },
            },
            "required": ["project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.stats(input["project"])


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

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.file(
            input["title"],
            description=input.get("description"),
            acceptance=input.get("acceptance"),
        )


class WorkAddTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_add"

    @property
    def description(self) -> str:
        return (
            "File a new engineering-lane work item directly into a project's queue -- the "
            "sanctioned way to seed the FIRST item(s) in a brand-new project, or add more work "
            "later. Unlike work_file (which requires holding an item and links it "
            "discovered-from that item), work_add needs no held item at all. Use this when a "
            "user asks you to add/file/create a task or work item that isn't already in the "
            "queue -- never fall back to a raw storage-layer CLI to do this. Applies the "
            "engineering lane label itself; you never need to know the label vocabulary (e.g. "
            "'lane:eng') exists. The new item becomes claimable via work_claim immediately."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Named project to add the item to."},
                "title": {"type": "string", "description": "Short title for the new item."},
                "description": {
                    "type": "string",
                    "description": "What needs to be done.",
                },
                "acceptance": {
                    "type": "string",
                    "description": "Given/When/Then acceptance criteria, if known.",
                },
            },
            "required": ["project", "title"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.add(
            input["project"],
            input["title"],
            description=input.get("description"),
            acceptance=input.get("acceptance"),
        )


class WorkMoveTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_move"

    @property
    def description(self) -> str:
        return (
            "Move one item from one project to another, preserving its id -- the feature request "
            "behind this tool: before it existed, there was no sanctioned way (for an agent OR a "
            "human) to migrate a work item to a different project's queue at all. No held item "
            "required -- unlike work_file/work_resolve/work_release, this never touches this "
            "session's custody state. Refuses (mutating nothing) if the item is currently HELD (an "
            "agent may be actively working it -- resolve or reap it first), does not exist in the "
            "source project, or already exists at the destination. A dependency edge to an item "
            "that is NOT also moving cannot be expressed once the two live in different projects "
            "-- such an edge is dropped (never silently left dangling) and reported back in "
            "dropped_dependency_edges so you can see exactly what did not survive."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "Item id to move."},
                "from_project": {
                    "type": "string",
                    "description": "Project the item currently lives in.",
                },
                "to_project": {
                    "type": "string",
                    "description": "Project to move the item into.",
                },
            },
            "required": ["item_id", "from_project", "to_project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.move(
            input["item_id"],
            input["from_project"],
            input["to_project"],
        )


class WorkListTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_list"

    @property
    def description(self) -> str:
        return (
            "List items in a project (read-only) -- id, title, status, holder, and (for "
            "closed items) resolution. Filterable by status; defaults to every status, "
            f"capped at {A.LIST_DEFAULT_LIMIT} (max {A.LIST_MAX_LIMIT} via limit) -- the "
            "response always reports total_count/returned_count/truncated so a cap is never "
            "silent. Strictly read-only: never claims, mutates, or touches custody. Use this "
            "to see who holds an item, or what happened to items you didn't claim (closed "
            "items and their resolution are visible here, not just open ones) -- never shell "
            "out to a raw storage-layer CLI to answer this. "
            "Pass item_id to read ONE item's FULL record instead -- including "
            "acceptance/description/design, the same body work_claim returns -- WITHOUT "
            "claiming it, mutating it, or touching custody. This is how to understand what an "
            "item is asking for before deciding whether to claim it at all; work_claim is the "
            "only tool that used to expose that body, and it takes the item to do so."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Named project to list items from."},
                "item_id": {
                    "type": "string",
                    "description": (
                        "Optional. Read this SPECIFIC item's full record (including "
                        "acceptance/description/design) instead of listing -- never claims, "
                        "mutates, or touches custody. Ignores status/limit when given. Mirrors "
                        "work_claim's own item_id (directed claim) so the directed-by-id shape "
                        "is consistent across both tools."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": list(A.STATUSES),
                    "description": (
                        "Optional. Filter to items with exactly this status. Omit to see every "
                        "status. Ignored when item_id is given."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Optional. Max items to return (default {A.LIST_DEFAULT_LIMIT}, "
                        f"clamped to {A.LIST_MAX_LIMIT}). Ignored when item_id is given."
                    ),
                },
            },
            "required": ["project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.list_items(
            input["project"],
            item_id=input.get("item_id"),
            status=input.get("status"),
            limit=input.get("limit"),
        )


# --------------------------------------------------------------------------
# lane:gb-subscribe -- subscription management tools (amplifier-bxq).
# --------------------------------------------------------------------------


class WorkSubscribeTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_subscribe"

    @property
    def description(self) -> str:
        return (
            "Subscribe THIS session to a project's status reminders -- a compact, cadence-gated "
            "note (ready/held counts, whether you hold anything, whether it's stale) injected "
            "into your context by the hooks-work-subscribe-reminder hook, shaped like the "
            "existing todo/status system-reminders. work_claim already auto-subscribes you to "
            "whatever project you claim from; call this to also watch a project you have not "
            "(yet) claimed anything in. Subscriptions live only for this session -- they do NOT "
            "persist across a restart and are NOT inherited by a forked sub-session. Idempotent: "
            "subscribing again is a no-op that still reports success."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Named project to subscribe to."},
            },
            "required": ["project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.subscribe(input["project"])


class WorkUnsubscribeTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_unsubscribe"

    @property
    def description(self) -> str:
        return (
            "Stop THIS session's status reminders for a project (see work_subscribe). Does not "
            "touch custody or any held item -- purely a reminder-noise preference. Idempotent: "
            "unsubscribing from a project you were never subscribed to is a no-op that still "
            "reports success."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Named project to unsubscribe from.",
                },
            },
            "required": ["project"],
        }

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.unsubscribe(input["project"])


class WorkSubscriptionsTool:
    def __init__(self, session: WorkTrackerSession):
        self._session = session

    @property
    def name(self) -> str:
        return "work_subscriptions"

    @property
    def description(self) -> str:
        return (
            "List the projects THIS session is currently subscribed to for status reminders "
            "(see work_subscribe/work_unsubscribe). Read-only; never claims, mutates, or "
            "touches custody."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @guarded
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return await self._session.subscriptions()


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mount all thirteen work_* tools, sharing one WorkTrackerSession.

    IRON LAW: every tool below is registered via `coordinator.mount()`.
    Skipping any of them (or returning without mounting) fails
    `protocol_compliance` for every agent that uses this behavior.

    lane:gb-subscribe -- also registers the `work_tracker.reminder_snapshot`
    CAPABILITY (`coordinator.register_capability`), a bound method on this
    session that the separate `hooks-work-subscribe-reminder` hook module
    reads to build its context injection. This is the ONLY channel that hook
    uses to learn anything about work-tracker state -- it contains no Beads
    knowledge of its own (see that module's docstring). A session that never
    mounts this tool module simply has no capability registered; the hook
    treats that as a silent no-op (`get_capability` returns `None`), never an
    error.
    """
    session = WorkTrackerSession(config)
    tools = [
        WorkClaimTool(session),
        WorkDeclareTool(session),
        WorkResolveTool(session),
        WorkReleaseTool(session),
        WorkStatusTool(session),
        WorkStatsTool(session),
        WorkFileTool(session),
        WorkAddTool(session),
        WorkMoveTool(session),
        WorkListTool(session),
        WorkSubscribeTool(session),
        WorkUnsubscribeTool(session),
        WorkSubscriptionsTool(session),
        WorkTrackerStatusTool(config),
        WorkTrackerInstallTool(config),
    ]
    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
    coordinator.register_capability("work_tracker.reminder_snapshot", session.reminder_snapshot)
    return {
        "name": "tool-work-tracker",
        "version": "0.1.0",
        "provides": [tool.name for tool in tools],
    }
