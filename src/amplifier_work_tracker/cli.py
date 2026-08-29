"""amplifier-work-tracker -- multi-agent work coordination for parallel coding agents.

This CLI contains NO knowledge of Beads. Every Beads interaction goes through
`amplifier_work_tracker.adapter`, the single seam. That is deliberate: Beads is
moving fast, and we want its improvements without its churn reaching our
domain logic.

`amplifier-work-tracker doctor` runs the contract suite -- executable
assertions of every behaviour we depend on, checked against the live binary.
Run it after any bd upgrade. It is how a breaking change reaches us as a loud
failure instead of silently corrupted parallel work.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import NoReturn

from . import adapter as A
from . import contract
from . import custody as C
from . import heartbeat as HB
from . import service as S
from . import supervisor as SV

POLL_TICK_SECONDS = 5


def die(msg: str, code: int = 1) -> NoReturn:
    print(f"amplifier-work-tracker: {msg}", file=sys.stderr)
    sys.exit(code)


def _ws(a) -> A.Workspace:
    return A.Workspace(getattr(a, "root", None))


def _guard():
    """Refuse to operate on an unsupported Beads. Warn on an untested-new one."""
    _, warn = A.check_version()
    if warn:
        print(f"amplifier-work-tracker: NOTE -- {warn}", file=sys.stderr)


# ------------------------------------------------------------------ commands


def _check_service_installed() -> contract.Result:
    """Is the background service installed, and if so, active?

    Informational (`ok`) when never installed at all -- running
    `amplifier-work-tracker serve` by hand, or not needing it yet, are both
    normal. Only "installed but NOT active" is a `fail`: that state means an
    operator asked for this to survive reboot and it currently isn't running.
    """
    info = S.describe_service()
    if not info.supported:
        return contract.Result(
            "service.installed",
            True,
            f"service management unavailable on this platform: {info.detail}",
        )
    if not info.installed:
        return contract.Result(
            "service.installed",
            True,
            "not installed -- run `amplifier-work-tracker service install` so the shared dolt "
            "server and reap/notify sweeps survive logout and reboot",
        )
    if info.active:
        return contract.Result("service.installed", True, f"{info.detail}")
    return contract.Result(
        "service.installed",
        False,
        f"{info.detail} -- start it with `amplifier-work-tracker service start`, or see "
        f"`amplifier-work-tracker service logs` for why it isn't running",
    )


def _check_dolt_reachable(service_check: contract.Result) -> contract.Result:
    """Is the shared dolt server actually accepting connections on
    SV.DEFAULT_DOLT_HOST:DEFAULT_DOLT_PORT?

    Dependency-ordered on `service.installed`: if that check already failed
    (installed but not running), this is `skipped` rather than piling on a
    second red line for the same root cause -- a stopped service obviously
    means dolt isn't reachable either.
    """
    if not service_check.ok:
        return contract.Result("dolt.reachable", True, "skipped (service.installed already failed)")
    reachable = SV.port_holder_responds(SV.DEFAULT_DOLT_HOST, SV.DEFAULT_DOLT_PORT)
    if reachable:
        return contract.Result(
            "dolt.reachable",
            True,
            f"dolt sql-server responds on {SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT}",
        )
    return contract.Result(
        "dolt.reachable",
        False,
        f"nothing responds on {SV.DEFAULT_DOLT_HOST}:{SV.DEFAULT_DOLT_PORT} -- "
        f"`bd` commands against a shared-server project will fail until the dolt server is "
        f"running (`amplifier-work-tracker service install`, or `bd` will lazily start its own "
        f"on first use)",
    )


def _check_sweeps_alive(root) -> contract.Result:
    """Are the reap/notify sweep loops actually COMPLETING sweeps -- not
    merely is the unit `active`? See `amplifier_work_tracker.heartbeat`'s
    module docstring for the exact ambiguity `systemctl is-active` (and our
    own exception-only sweep logging) cannot resolve: silence in the journal
    means both "healthy" and "silently dead," and they are indistinguishable
    from outside the process without this.

    Same dependency-ordering convention as `_check_dolt_reachable`: skipped
    (never failed) whenever the service isn't installed and running at all
    -- that covers both the normal "not using the background service yet"
    case (a dev box, or a session driving the CLI directly) and a state
    `service.installed` has already reported as a failure. Piling a second
    red line on the same root cause would not add information.
    """
    info = S.describe_service()
    if not info.supported or not info.installed:
        return contract.Result(
            "sweeps.alive",
            True,
            "skipped (service not installed) -- sweep heartbeats only exist once "
            "`amplifier-work-tracker service install` (or a foregrounded `serve`) is running",
        )
    if not info.active:
        return contract.Result("sweeps.alive", True, "skipped (service.installed already failed)")
    path = HB.heartbeat_path(root)
    checks = [
        (HB.REAP, SV.DEFAULT_REAP_INTERVAL_SECONDS),
        (HB.NOTIFY, SV.DEFAULT_NOTIFY_INTERVAL_SECONDS),
    ]
    details = []
    all_ok = True
    for loop, interval in checks:
        record = HB.read_loop_heartbeat(path, loop)
        ok, detail = HB.evaluate_freshness(record, loop=loop, interval=interval)
        details.append(detail)
        all_ok = all_ok and ok
    return contract.Result("sweeps.alive", all_ok, "; ".join(details))


def _check_restart_policy(service_check: contract.Result) -> contract.Result:
    """Does the INSTALLED systemd unit actually carry the self-healing
    restart policy this project depends on (`Restart=always`, not
    `on-failure`)?

    This is the regression pin for the outage measured 2026-08-14 17:14:
    dolt sql-server was SIGKILLed repeatedly, the supervisor's own
    SIGTERM/SIGINT handler (`_request_stop` in supervisor.py) then received
    an unrelated termination signal and exited CLEANLY (status 0), and
    `Restart=on-failure` never restarts a clean exit -- so the whole service
    stayed `inactive` until a human noticed. `Restart=always` restarts
    regardless of exit status; an explicit `systemctl --user stop`/`disable`
    is still honored by systemd regardless of that policy (verified against
    a real unit in tests/unit/test_service.py, not merely read from docs).

    If a future edit to `service.py`'s unit template ever regresses this
    back to `on-failure` (or drops Restart= entirely), THIS check fails
    loudly here -- instead of the regression only resurfacing as a repeat
    outage days or months later.

    Same dependency-ordering convention as `_check_dolt_reachable` /
    `_check_sweeps_alive`: skipped (never failed) when the service isn't
    installed at all. Also skipped on a platform with no systemd unit file
    to inspect (macOS/launchd already uses `KeepAlive=true`, its own
    always-restart equivalent, hardcoded in `_LAUNCHD_PLIST_TEMPLATE` --
    there is no separate "on-failure vs always" distinction to regress
    there, so there is nothing further for this check to pin on that
    platform).
    """
    info = S.describe_service()
    if not info.supported or not info.installed:
        return contract.Result(
            "service.restart_policy",
            True,
            "skipped (service not installed) -- nothing to check yet",
        )
    if info.platform != "linux" or info.unit_path is None:
        return contract.Result(
            "service.restart_policy",
            True,
            f"skipped (platform {info.platform!r} has no systemd unit file to inspect)",
        )
    try:
        unit_text = info.unit_path.read_text(encoding="utf-8")
    except OSError as e:
        return contract.Result(
            "service.restart_policy",
            False,
            f"could not read installed unit at {info.unit_path}: {e}",
        )
    restart_lines = [
        line.strip() for line in unit_text.splitlines() if line.strip().startswith("Restart=")
    ]
    if not restart_lines:
        return contract.Result(
            "service.restart_policy",
            False,
            f"installed unit at {info.unit_path} has no Restart= line at all -- an "
            f"unintended exit (e.g. an external SIGTERM) will leave the service down until "
            f"a human notices; re-run `amplifier-work-tracker service install` to pick up "
            f"the current unit template",
        )
    if restart_lines[-1] != "Restart=always":
        return contract.Result(
            "service.restart_policy",
            False,
            f"installed unit at {info.unit_path} has {restart_lines[-1]!r}, not "
            f"'Restart=always' -- this is the exact policy gap that let the 2026-08-14 "
            f"outage stay down (a clean/status-0 exit is never restarted by on-failure); "
            f"re-run `amplifier-work-tracker service install` to pick up the current unit "
            f"template",
        )
    return contract.Result(
        "service.restart_policy",
        True,
        "installed unit has Restart=always -- survives a clean/unintended exit",
    )


def cmd_doctor(a):
    """Prove the installed Beads still behaves the way we depend on, and that
    our own service/dolt-reachability are in a state parallel agents can
    trust."""
    results = contract.run_all(quick=a.quick)
    service_check = _check_service_installed()
    results.append(service_check)
    results.append(_check_dolt_reachable(service_check))
    results.append(_check_sweeps_alive(_ws(a).root))
    results.append(_check_restart_policy(service_check))
    width = max(len(r.id) for r in results)
    failed = 0
    for r in results:
        if not r.ok:
            failed += 1
        print(f"  [{r.mark}] {r.id:<{width}}  {r.detail}")
    print()
    if failed:
        print(f"{failed} assumption(s) VIOLATED. Beads has changed underneath us.")
        print(
            "Fix scope: amplifier_work_tracker/adapter.py only -- "
            "nothing above the seam encodes Beads behaviour."
        )
        return 1
    print(f"All {len(results)} assumptions hold. Safe to run parallel agents.")
    return 0


def cmd_new(a):
    """Create a project -- or, if a database of the same name already
    exists on the shared server with no matching local directory, ATTACH
    to it and say so loudly.

    Measured bug this replaces: `Workspace.create` legitimately needs to
    attach to an already-existing, already-healthy database (recovering
    after an accidental directory deletion is a real, sanctioned path --
    see `Workspace.remove`'s docstring for why a directory and a database
    can end up out of sync). But the CLI printed the exact same "created
    ... (verified writable)" message either way, so an operator had no way
    to tell "brand new, empty project" from "reused someone else's queue,
    N items and all" -- silently resurrected data reported as a fresh
    success. The check happens BEFORE `create()` runs (not after) so a
    concurrent drop can't hide the adoption; worst case is a report of
    'adopted' for a database that got dropped a moment later, which is a
    race in the reporting only, never in what was actually done.

    Also reports honestly when `create()` had to HEAL an abandoned
    creation attempt first (see `Workspace.creation_state`/
    `_heal_abandoned`) -- `prior_state` is read BEFORE `create()` runs, for
    the same reason `pre_existing_db` is: so this call's own healing can
    never hide itself in the report.
    """
    _guard()
    ws = _ws(a)
    already_local = (ws.path(a.name) / ".beads").is_dir()
    pre_existing_db = False if already_local else A.database_exists(a.name)
    prior_state = ws.creation_state(a.name)  # None / "creating" / "abandoned", before healing
    try:
        path = ws.create(a.name)
    except A.BeadsError as e:
        die(str(e))
    if prior_state == "abandoned":
        print(
            f"HEALED project '{a.name}' at {path}: a previous `new` never finished "
            f"(interrupted mid-creation, e.g. by a timeout). The incomplete attempt was "
            f"cleared automatically and this is now a fresh, verified-writable project."
        )
        return
    if pre_existing_db:
        try:
            count = len(ws.project(a.name).list(include_resolved=True))
            count_note = f"{count} existing item(s)"
        except A.BeadsError as e:
            count_note = f"item count unavailable ({e})"
        print(
            f"ADOPTED existing project '{a.name}' at {path} -- a database of this name "
            f"already existed on the shared server with no local directory ({count_note}). "
            f"This is NOT a fresh project; if that is unexpected, inspect it before using it."
        )
        return
    print(f"created project '{a.name}' at {path} (verified writable)")


def cmd_remove(a):
    """Remove a project: its local `.beads` directory AND its shared-server
    database. Operator-only -- deliberately NOT exposed as an agent tool
    (see `modules/tool-work-tracker`); an agent must never be able to
    delete a work queue.

    Refuses without `--yes` (a second, independent gate on top of
    `Workspace.remove`'s own `force` requirement), refuses if any item is
    currently HELD, and never touches anything in the project directory
    other than `.beads` -- see `Workspace.remove`'s docstring for the full
    contract, including how it handles a database whose directory is
    already gone.
    """
    _guard()
    if not a.yes:
        die(
            f"refusing to remove project {a.name!r} without --yes -- "
            f"this is destructive and irreversible"
        )
    try:
        report = _ws(a).remove(a.name, force=True)
    except A.BeadsError as e:
        die(str(e))
    print(
        json.dumps(
            {
                "removed": report.name,
                "directory": str(report.directory),
                "had_beads_dir": report.had_beads_dir,
                "had_database": report.had_database,
                "beads_removed": report.beads_removed,
                "database_removed": report.database_removed,
                "directory_removed": report.directory_removed,
                "leftover": report.leftover,
            },
            indent=2,
        )
    )


def cmd_rename(a):
    """Rename a project: its directory, its shared-server database, and bd's
    local metadata, together -- atomically, or a clean failure that leaves the
    original untouched.

    Operator-only, like `remove` (see `modules/tool-work-tracker`) -- an agent
    must never be able to rename a work queue out from under other agents. The
    class of bug this closes is a rename that moves only the directory and
    leaves the database still named `<old>` on the shared server; this renames
    both. Refuses if `<new>` is already taken, if `<old>` is missing or in a
    split state, or if any item in `<old>` is currently HELD -- see
    `Workspace.rename`'s docstring for the full contract, including how item
    ids and the issue prefix are preserved.
    """
    _guard()
    try:
        report = _ws(a).rename(a.old, a.new)
    except A.BeadsError as e:
        die(str(e))
    print(
        json.dumps(
            {
                "renamed": report.old,
                "to": report.new,
                "directory": str(report.directory),
                "items": report.item_count,
                "old_database_dropped": report.old_database_dropped,
            },
            indent=2,
        )
    )


def cmd_move(a):
    """Move one item from project `--from` to project `--to`, preserving its
    id -- the single-item counterpart to `rename`/`remove`'s whole-project
    operations.

    Unlike `remove`/`rename`, this is NOT operator-only: it is also exposed
    as the `work_move` agent tool (see `modules/tool-work-tracker`), since
    moving a single item is a far narrower, safer operation than deleting or
    renaming an entire project's queue. Refuses (no override) if the item is
    currently HELD, does not exist in `--from`, or already exists in `--to`
    -- see `Workspace.move_item`/`adapter.move_item`'s docstring for the full
    contract, including how a dependency edge to an item that is NOT moving
    is dropped (and reported) rather than silently corrupted.
    """
    _guard()
    try:
        report = _ws(a).move_item(a.from_project, a.to_project, a.item)
    except A.BeadsError as e:
        die(str(e))
    print(
        json.dumps(
            {
                "moved": report.item_id,
                "from": report.src,
                "to": report.dst,
                "dropped_dependency_edges": report.dropped_dependency_edges,
            },
            indent=2,
        )
    )


def cmd_add(a):
    """File a new engineering-lane work item directly -- the sanctioned path
    for seeding a project's FIRST item(s), or adding more later.

    Deliberately the CLI/operator counterpart to `work_add` (the agent-facing
    tool): before this existed, nothing here could create the first item in
    a brand-new project without already holding one (`work_file` requires a
    held item; `new` only creates the PROJECT). The only way around that gap
    was raw `bd create` plus a hand-guessed `bd label add <id> lane:eng` --
    exactly the seam-leaking workaround this command exists to make
    unnecessary. Applies the engineering lane label itself; the caller never
    needs to know `lane:eng` exists.
    """
    _guard()
    try:
        new_id = (
            _ws(a)
            .project(a.project)
            .create(
                a.title,
                kind="task",
                tags=[A.LANE_WORK],
                description=a.description,
                acceptance=a.acceptance,
            )
        )
    except A.BeadsError as e:
        die(str(e))
    print(json.dumps({"added": new_id, "project": a.project, "lane": A.LANE_WORK}, indent=2))


def cmd_instances(a):
    """List every known project, honestly.

    Measured outage, 2026-08-15: this command reported a project whose
    creation had been interrupted as a blind `ok` (`TOTAL 0 READY 0 HELD 0
    INTAKE 0  ok`) -- `list()` happened to succeed (against a fallback
    database bd substitutes when its own project config is missing/broken),
    so `ok` ended up meaning nothing more than "this one subprocess call
    didn't raise." `Workspace.creation_state` is consulted FIRST, before
    ever attempting `list()`, so a project caught mid-creation or left
    broken by one that never finished is reported as such -- `creating` or
    `broken` -- and `ok` is restored to actually meaning "writable."

    Counting logic beyond creation-state lives in `adapter.project_summary`
    -- shared with the web dashboard (see `webapp.py`) so the two can never
    silently disagree on what "ready"/"held"/"intake"/"blocked" mean, or on
    the aging/throughput figures (`oldest_unclaimed_age_seconds`,
    `resolved_24h`, `resolved_7d`) folded in from `adapter.project_activity`.
    See those functions' docstrings for why an unreadable project reports
    `None` counts rather than zero.
    """
    _guard()
    ws = _ws(a)
    names = ws.names()
    if not names:
        print("no projects")
        return
    summaries = []
    for n in names:
        state = ws.creation_state(n)
        if state == "creating":
            summaries.append(
                A.ProjectSummary(
                    name=n,
                    status=(
                        "creating -- a `new` for this project is in progress elsewhere "
                        "right now; try again once it finishes"
                    ),
                )
            )
            continue
        if state == "abandoned":
            summaries.append(
                A.ProjectSummary(
                    name=n,
                    status=(
                        f"broken -- a previous `new` never finished; run "
                        f"`amplifier-work-tracker new {n}` to heal it automatically"
                    ),
                )
            )
            continue
        summaries.append(A.project_summary(ws, n))
    if a.json:
        rows = [
            (
                {
                    "project": s.name,
                    "total": s.total,
                    "ready": s.ready,
                    "held": s.held,
                    "intake": s.intake,
                    "blocked": s.blocked,
                    "deferred": s.deferred,
                    "resolved": s.resolved,
                    "held_by": s.held_by,
                    "last_activity": s.last_activity,
                    "oldest_unclaimed_age_seconds": s.oldest_unclaimed_age_seconds,
                    "resolved_24h": s.resolved_24h,
                    "resolved_7d": s.resolved_7d,
                    "status": s.status,
                }
                if s.status == "ok"
                else {"project": s.name, "status": s.status}
            )
            for s in summaries
        ]
        print(json.dumps(rows, indent=2))
        return
    print(
        f"{'PROJECT':<20} {'TOTAL':>6} {'READY':>6} {'HELD':>5} {'INTAKE':>7} "
        f"{'BLOCK':>6} {'DEFER':>6} {'RESOLV':>7}  STATUS"
    )
    for s in summaries:
        print(
            f"{s.name:<20} {s.total if s.total is not None else '':>6} "
            f"{s.ready if s.ready is not None else '':>6} "
            f"{s.held if s.held is not None else '':>5} "
            f"{s.intake if s.intake is not None else '':>7} "
            f"{s.blocked if s.blocked is not None else '':>6} "
            f"{s.deferred if s.deferred is not None else '':>6} "
            f"{s.resolved if s.resolved is not None else '':>7}  {s.status}"
        )


def _project_summary_row(s: A.ProjectSummary) -> dict:
    """One project's `ProjectSummary` as a JSON-ready dict -- the full field
    set (including the per-project-only `ready_age_buckets` histogram),
    shared by `cmd_status`'s `--json` output. `cmd_instances`'s own JSON rows
    stay hand-built (a narrower, list-view field set) rather than routed
    through this helper, so trimming a field from the detail view can never
    silently trim it from the summary table too.
    """
    if s.status != "ok":
        return {"project": s.name, "status": s.status}
    return {
        "project": s.name,
        "status": s.status,
        "total": s.total,
        "ready": s.ready,
        "held": s.held,
        "intake": s.intake,
        "blocked": s.blocked,
        "deferred": s.deferred,
        "resolved": s.resolved,
        "held_by": s.held_by,
        "last_activity": s.last_activity,
        "oldest_unclaimed_age_seconds": s.oldest_unclaimed_age_seconds,
        "resolved_24h": s.resolved_24h,
        "resolved_7d": s.resolved_7d,
        "ready_age_buckets": s.ready_age_buckets,
    }


def cmd_status(a):
    """Per-project detail view: the FULL status breakdown for exactly one
    project -- the cheap `instances` table's per-project counterpart.

    Reads through the exact same `Workspace.creation_state` + `adapter.
    project_summary` path `cmd_instances` uses (see that command's
    docstring for why creation-state is consulted first), so a project
    caught mid-`new` or left broken never reports a misleadingly healthy
    zeroed breakdown here either.

    Unlike `instances` (a multi-project listing, where one unreadable row
    must never abort the whole table), this is a DIRECTED single-project
    read -- like `list --project`/`claim --id` -- so a project that was
    never created at all (no `.beads` directory and no creation lock)
    fails loudly (non-zero exit), exactly like `Workspace.project()` does
    for every other directed command.
    """
    _guard()
    ws = _ws(a)
    state = ws.creation_state(a.project)
    if state == "creating":
        s = A.ProjectSummary(
            name=a.project,
            status=(
                "creating -- a `new` for this project is in progress elsewhere "
                "right now; try again once it finishes"
            ),
        )
    elif state == "abandoned":
        s = A.ProjectSummary(
            name=a.project,
            status=(
                f"broken -- a previous `new` never finished; run "
                f"`amplifier-work-tracker new {a.project}` to heal it automatically"
            ),
        )
    elif not (ws.path(a.project) / ".beads").is_dir():
        die(
            f"project {a.project!r} not found at {ws.path(a.project) / '.beads'}. "
            f"Create it first: amplifier-work-tracker new {a.project}"
        )
    else:
        s = A.project_summary(ws, a.project)
    if a.json:
        print(json.dumps(_project_summary_row(s), indent=2))
        return
    if s.status != "ok":
        print(f"{a.project}: {s.status}")
        return
    print(f"PROJECT:   {s.name}")
    print(f"TOTAL:     {s.total}")
    print(f"READY:     {s.ready}")
    print(f"HELD:      {s.held}  (by: {', '.join(s.held_by) if s.held_by else '-'})")
    print(f"INTAKE:    {s.intake}")
    print(f"BLOCKED:   {s.blocked}")
    print(f"DEFERRED:  {s.deferred}")
    print(f"RESOLVED:  {s.resolved}")
    print(f"LAST ACTIVITY:            {s.last_activity or '-'}")
    print(
        "OLDEST UNCLAIMED (seconds): "
        f"{s.oldest_unclaimed_age_seconds if s.oldest_unclaimed_age_seconds is not None else '-'}"
    )
    print(f"RESOLVED (24h):           {s.resolved_24h}")
    print(f"RESOLVED (7d):            {s.resolved_7d}")
    if s.ready_age_buckets:
        buckets = "  ".join(f"{label}d={count}" for label, count in s.ready_age_buckets.items())
        print(f"READY AGE BUCKETS:        {buckets}")


def _print_item_full(a, item: A.Item) -> None:
    """Render one item's FULL record (`--id` directed read) -- id, title,
    status, holder, resolution, plus the body fields only `claim` used to
    return (acceptance/description/design). See `adapter.Beads.get_readonly`
    -- this never claims, mutates, or touches custody.
    """
    row = item.summary(full=True)
    if a.json:
        print(
            json.dumps(
                {
                    "project": a.project,
                    "items": [row],
                    "returned_count": 1,
                    "total_count": 1,
                    "truncated": False,
                    "limit": 1,
                },
                indent=2,
            )
        )
        return
    print(f"ID:       {row['id']}")
    print(f"TITLE:    {row['title']}")
    print(f"STATUS:   {row['status']}")
    print(f"HOLDER:   {row['holder'] or ''}")
    if row.get("created_at"):
        by = f" by {row['created_by']}" if row.get("created_by") else ""
        print(f"CREATED:  {row['created_at']}{by}")
    if row.get("updated_at"):
        print(f"UPDATED:  {row['updated_at']}")
    if row.get("closed_at"):
        print(f"CLOSED:   {row['closed_at']}")
    if row.get("resolution"):
        print(f"\nRESOLUTION:\n{row['resolution']}")
    if row.get("acceptance"):
        print(f"\nACCEPTANCE:\n{row['acceptance']}")
    if row.get("description"):
        print(f"\nDESCRIPTION:\n{row['description']}")
    if row.get("design"):
        print(f"\nDESIGN:\n{row['design']}")


def cmd_list(a):
    """Read-only per-item listing: id, title, status, holder, resolution --
    the operator/CLI counterpart to the `work_list` agent tool. See
    `adapter.Beads.list_bounded` for the shared capping/truncation logic;
    this command is a thin wrapper, exactly like `work_add`/`add`.

    `--id` switches to a directed single-item READ: the full record
    (including description/acceptance/design -- everything `claim` returns)
    for exactly that item, with no claim, no mutation, no custody touched.
    Mirrors `claim`'s own `--id` (directed claim by id, PR #4) so the two
    directed-by-id shapes stay coherent; `--status`/`--limit` are ignored
    when `--id` is given, since a directed read is inherently one item.
    """
    _guard()
    bd = _ws(a).project(a.project)
    if a.id:
        try:
            item = bd.get_readonly(a.id)
        except A.BeadsError as e:
            die(str(e))
        _print_item_full(a, item)
        return
    try:
        result = bd.list_bounded(status=a.status, limit=a.limit)
    except A.BeadsError as e:
        die(str(e))
    rows = [i.summary() for i in result.items]
    if a.json:
        print(
            json.dumps(
                {
                    "project": a.project,
                    "items": rows,
                    "returned_count": result.returned_count,
                    "total_count": result.total_count,
                    "truncated": result.truncated,
                    "limit": result.limit,
                },
                indent=2,
            )
        )
        return
    if not rows:
        print(
            f"no items in project {a.project!r}"
            + (f" with status={a.status!r}" if a.status else "")
        )
        return
    width_id = max(len(r["id"]) for r in rows)
    print(f"{'ID':<{width_id}}  {'STATUS':<10} {'HOLDER':<20} TITLE")
    for r in rows:
        print(f"{r['id']:<{width_id}}  {r['status']:<10} {(r['holder'] or ''):<20} {r['title']}")
    if result.truncated:
        print(
            f"\n(showing {result.returned_count} of {result.total_count} matching items -- "
            f"pass --limit to see more, up to {A.LIST_MAX_LIMIT})"
        )


def cmd_claim(a):
    """Claim work: the default queue-based claim, or -- with `--id` -- a
    directed claim of one specific item. Both are single atomic bd calls
    (`bd ready --claim` / `bd update <id> --claim`); a directed claim
    refuses loudly (no override) if the item is already held, missing, or
    blocked by an open dependency -- see `adapter.Beads.claim_item`.
    """
    _guard()
    try:
        bd = _ws(a).project(a.project)
        if a.id:
            item = bd.claim_item(a.id, actor=a.actor)
        else:
            item = bd.claim_next(lane=a.lane, actor=a.actor)
    except A.BeadsError as e:
        die(str(e))
    if item is None:
        print(json.dumps({"claimed": None, "reason": "no ready work in lane"}))
        return 3
    print(
        json.dumps(
            {
                "claimed": item.id,
                "title": item.title,
                "holder": a.actor,
                "acceptance": item.acceptance,
                "description": item.description,
                "design": item.design,
                "next_step": (
                    f"run `amplifier-work-tracker custody --project {a.project} --actor {a.actor} "
                    f"--id {item.id}` in the background to establish and maintain "
                    f"custody while you work"
                ),
                "custody_renew_every_seconds": C.RENEW_INTERVAL_SECONDS,
            },
            indent=2,
        )
    )
    return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just isn't ours to signal -- still alive
    return True


MIN_TTL_MARGIN = 3  # ttl must be at least this many renewal intervals


def _emit(obj: dict) -> None:
    """Write one event and flush. Buffered supervisor output reads as 'dead'."""
    print(json.dumps(obj), flush=True)


def cmd_custody(a):
    """Establish custody of a claimed item, then renew it on a timer until
    the watched PID disappears -- at which point this exits, on its own,
    with no further action needed. Binding to a PID is what makes "supervisor
    outlives its agent" structurally impossible: there is no separate
    lifecycle to leak.
    """
    _guard()
    pid = a.pid or os.getppid()
    if not _pid_alive(pid):
        die(f"pid {pid} is not a live process -- nothing to watch")
    ttl = C.CUSTODY_TTL_SECONDS
    if a.interval * MIN_TTL_MARGIN > ttl:
        die(
            f"refusing to run: renewal interval {a.interval}s leaves too little "
            f"margin under a {ttl}s TTL. Each renewal costs a real round-trip, so "
            f"the observed period exceeds the configured interval. Use an interval "
            f"<= {ttl // MIN_TTL_MARGIN}s, or raise AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS."
        )
    bd = _ws(a).project(a.project)
    try:
        rec = bd.take_custody(
            a.id,
            holder=a.actor,
            pid=pid,
            host=socket.gethostname(),
            declared_state=a.declared_state,
        )
    except A.BeadsError as e:
        die(str(e))
    _emit(
        {
            "custody": "established",
            "id": a.id,
            "holder": a.actor,
            "pid": pid,
            "generation": rec["generation"],
        }
    )
    generation = rec["generation"]
    interval = max(a.interval, POLL_TICK_SECONDS)
    tick = min(POLL_TICK_SECONDS, interval)
    next_renew = time.monotonic() + interval
    while True:
        time.sleep(tick)
        if not _pid_alive(pid):
            _emit({"custody": "pid_exited", "id": a.id, "pid": pid})
            return 0
        if time.monotonic() < next_renew:
            continue
        try:
            rec = bd.renew_custody(
                a.id,
                holder=a.actor,
                generation=generation,
                pid=pid,
                declared_state=a.declared_state,
            )
        except A.BeadsError as e:
            die(f"custody fence violated -- stopping renewal: {e}")
        generation = rec["generation"]
        next_renew = time.monotonic() + interval
        _emit({"custody": "renewed", "id": a.id, "last_seen": rec["last_seen"]})


def cmd_reap(a):
    """Release items whose custody has gone stale, or hit the escalation
    ceiling, back to the queue. Never touches an item with a fresh, non-
    escalated custody signal -- see amplifier_work_tracker.custody.reclaim_eligible
    for the entire decision.
    """
    _guard()
    bd = _ws(a).project(a.project)
    ttl = a.ttl_seconds if a.ttl_seconds is not None else C.CUSTODY_TTL_SECONDS
    esc = a.escalation_hours if a.escalation_hours is not None else C.ESCALATION_HOURS
    held = [i for i in bd.list(include_resolved=False) if i.status == "held"]
    reclaimed, kept = [], []
    for item in held:
        rec = item.meta.get(C.CUSTODY_KEY)
        eligible, reason = C.reclaim_eligible(rec, ttl=ttl, escalation_hours=esc)
        if eligible:
            bd.release(item.id)
            reclaimed.append({"id": item.id, "was_holder": item.holder, "reason": reason})
        else:
            note = "quiet (awaiting_human)" if not C.should_notify(rec) else "ok"
            kept.append({"id": item.id, "holder": item.holder, "note": note})
    print(
        json.dumps(
            {"reclaimed": reclaimed, "reclaimed_count": len(reclaimed), "kept": kept}, indent=2
        )
    )


def cmd_resolve(a):
    _guard()
    try:
        item = _ws(a).project(a.project).resolve(a.id, a.reason, actor=a.actor)
    except A.BeadsError as e:
        die(str(e))
    print(json.dumps({"resolved": item.id, "resolution": item.resolution}, indent=2))


def cmd_unclaim(a):
    """Voluntarily release a HELD item back to the ready queue WITHOUT
    setting a resolution -- the inverse of `claim`, and deliberately distinct
    from `resolve` (which CLOSES the item with a reason). Use it when you have
    claimed work you will not finish, so another agent can pick it up.

    Errors clearly and mutates nothing if the item does not exist, or is not
    currently held (there is nothing to release). The status is checked FIRST,
    before any write, so this can never silently no-op an already-open item or
    be mistaken for `resolve`. Readback confirms the release actually landed --
    exit 0 is not proof, same discipline as `resolve` (see `adapter.Beads`).

    `--actor` is accepted for symmetry with `resolve`; releasing is not fenced
    on it (a held item's own holder is who unclaims it, and `reap` releases
    without a fence too -- see `cmd_reap`).
    """
    _guard()
    bd = _ws(a).project(a.project)
    try:
        item = bd.get(a.id)
    except A.BeadsError as e:
        die(str(e))
    if item.status != "held":
        die(
            f"cannot unclaim {a.id}: it is {item.status!r}, not held -- there is nothing to release"
        )
    try:
        bd.release(a.id)
    except A.BeadsError as e:
        die(str(e))
    back = bd.get(a.id)
    if back.status == "held":
        die(
            f"release of {a.id} reported success but readback still shows it held "
            f"by {back.holder!r} -- refusing to report success"
        )
    print(json.dumps({"unclaimed": a.id, "status": back.status, "holder": back.holder}, indent=2))


def cmd_edit(a):
    """Amend an item's own free-text fields IN PLACE (title/description/
    acceptance/design), attributed via an audit-trail comment -- or, with
    `--merge-into`, mark it superseded by a different item instead (a
    structural close, never a content edit). See `adapter.Beads.edit_item`
    / `adapter.Beads.supersede` for the full contract; this command is a
    thin wrapper, exactly like `add`/`move`.
    """
    _guard()
    bd = _ws(a).project(a.project)
    if a.merge_into:
        if any([a.title, a.description, a.acceptance, a.design]):
            die(
                "--merge-into cannot be combined with field edits -- "
                "edit the content first, then merge"
            )
        try:
            item = bd.supersede(a.id, a.merge_into, actor=a.actor)
        except A.BeadsError as e:
            die(str(e))
        print(
            json.dumps(
                {"superseded": item.id, "with": a.merge_into, "status": item.status}, indent=2
            )
        )
        return
    try:
        item = bd.edit_item(
            a.id,
            title=a.title,
            description=a.description,
            acceptance=a.acceptance,
            design=a.design,
            actor=a.actor,
        )
    except A.BeadsError as e:
        die(str(e))
    print(
        json.dumps(
            {
                "edited": item.id,
                "title": item.title,
                "description": item.description,
                "acceptance": item.acceptance,
                "design": item.design,
            },
            indent=2,
        )
    )


def cmd_defer(a):
    """Defer an open item with a reason (leaves `bd ready`/list views), or
    -- with `--clear` -- move a deferred item back to open. See
    `adapter.Beads.defer`/`undefer`.
    """
    _guard()
    bd = _ws(a).project(a.project)
    try:
        if a.clear:
            item = bd.undefer(a.id, actor=a.actor)
        else:
            if not a.reason:
                die("--reason is required unless --clear is given")
            item = bd.defer(a.id, a.reason, actor=a.actor)
    except A.BeadsError as e:
        die(str(e))
    print(json.dumps({"id": item.id, "status": item.status}, indent=2))


def cmd_block(a):
    """Block an open item with a reason (leaves `bd ready`/list views), or
    -- with `--clear` -- move a blocked item back to open. See
    `adapter.Beads.block`/`unblock`. Distinct from a dependency-based
    blocker (`dep`) -- this is a direct, reasoned status change with no
    other issue involved.
    """
    _guard()
    bd = _ws(a).project(a.project)
    try:
        if a.clear:
            item = bd.unblock(a.id, actor=a.actor)
        else:
            if not a.reason:
                die("--reason is required unless --clear is given")
            item = bd.block(a.id, a.reason, actor=a.actor)
    except A.BeadsError as e:
        die(str(e))
    print(json.dumps({"id": item.id, "status": item.status}, indent=2))


def cmd_dep(a):
    """Declare a dependency edge (`--depends-on`), or -- with neither flag
    -- display every dependency/dependent edge already on `--id`. See
    `adapter.Beads.add_dependency` / `adapter.Beads.get`'s `links` for the
    full contract, including what makes an edge an active claim-blocker.
    """
    _guard()
    bd = _ws(a).project(a.project)
    try:
        if a.depends_on:
            bd.add_dependency(a.id, a.depends_on, dep_type=a.type, actor=a.actor)
        item = bd.get_readonly(a.id, with_links=True)
    except A.BeadsError as e:
        die(str(e))
    print(json.dumps({"id": item.id, "links": item.links}, indent=2))


def cmd_notify(a):
    """Propagate resolved work back to the reports that prompted it.

    Beads does not do this for us -- measured: closing an item left every linked
    report untouched.
    """
    _guard()
    bd = _ws(a).project(a.project)
    flipped = []
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
    print(json.dumps({"flipped": flipped, "count": len(flipped)}, indent=2))


DIST_NAME = "amplifier-work-tracker"


def cmd_update(a):
    """Self-update this CLI to the latest version from its install source.

    The tool is distributed as a uv tool installed from git, so the correct
    update is `uv tool upgrade amplifier-work-tracker` -- which re-resolves the
    recorded git ref (e.g. `main`) to its newest commit and rebuilds. This
    subcommand runs exactly that so callers need not remember it. Note a plain
    `uv tool install --force-reinstall amplifier-work-tracker` does NOT work: the
    package is not published to any PyPI index, only installed from git.

    Fails loud rather than pretending: if `uv` is not on PATH, or uv reports a
    non-zero exit (e.g. the tool was installed some other way), it says so and
    prints the command to run by hand -- it never exits 0 on a silent no-op.
    """
    uv = shutil.which("uv")
    if uv is None:
        die(
            "cannot self-update: 'uv' is not on PATH. This CLI is distributed as a "
            "uv tool; install uv (https://docs.astral.sh/uv/), then run:\n"
            f"    uv tool upgrade {DIST_NAME}"
        )
    cmd = [uv, "tool", "upgrade"]
    if getattr(a, "reinstall", False):
        cmd.append("--reinstall")
    cmd.append(DIST_NAME)
    print(f"amplifier-work-tracker: {' '.join(cmd)}", file=sys.stderr)
    try:
        completed = subprocess.run(cmd, check=False)
    except OSError as e:  # uv vanished between which() and run(), or exec failed
        die(f"cannot self-update: failed to run uv: {e}")
    if completed.returncode != 0:
        die(
            f"self-update failed: uv exited {completed.returncode} (see its output "
            "above). If this CLI was not installed via `uv tool` (e.g. a pip or "
            "editable dev checkout), update it there instead -- e.g. `git pull` in "
            "your checkout.",
            code=completed.returncode,
        )
    return 0


def _root_parent_parser() -> argparse.ArgumentParser:
    """`--root` as a parent parser, composed into EVERY subcommand below via
    `parents=[...]`.

    This is load-bearing, not cosmetic: the systemd/launchd unit `service
    install` writes must bake the resolved workspace root in as an explicit
    `serve --root <abs>` ExecStart ARGUMENT, never an `Environment=` line --
    service managers do not reliably propagate the installing shell's
    environment (see service.py's module docstring). Giving every subcommand
    its own real `--root` flag (rather than only a top-level one, or only the
    env var) is what makes that argument meaningful and consistent everywhere
    `--root` might need to be passed explicitly, not just under `serve`.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--root", default=None, help="workspace root (default: $AMPLIFIER_WORK_TRACKER_ROOT)"
    )
    return parent


def cmd_setup_tls(a):
    """Generate a TLS certificate for `web` / `serve --web-port` and record it
    at the well-known location those commands auto-detect (`webtls.
    default_cert_path()`/`default_key_path()`) -- no separate settings file,
    the fixed path IS the record. Ported from muxplex's `setup-tls` (see
    `webtls.py`'s module docstring for exactly what was kept/adapted).

    Auto-detection chain (method='auto'): Tailscale -> self-signed. Use
    `--method` to force a specific certificate source. `--method ca`
    generates (or reuses) a persistent local CA under `webtls.
    default_ca_dir()` and signs a short-lived leaf with it -- install the CA
    on each client to get browser-trusted HTTPS without Tailscale or a
    public domain.

    Requires the `web` extra (`cryptography` lives there -- see pyproject.toml);
    a clear ImportError is what a caller sees if it isn't installed, same
    contract as `cmd_web`.
    """
    try:
        from . import webtls as T
    except ImportError as e:
        die(
            f"TLS support requires the 'web' extra: {e}\n"
            f"Install it with: pip install amplifier-work-tracker[web]"
        )
        return

    cert_path = T.default_cert_path()
    key_path = T.default_key_path()

    if cert_path.exists() and key_path.exists():
        info = T.get_cert_info(cert_path)
        if info is not None:
            print(f"TLS already configured (expires {str(info['expires'])[:10]}).")
        try:
            answer = input("Regenerate? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer.lower() not in ("y", "yes"):
            print("Keeping existing certificates.")
            return

    result = None
    method = a.method

    # Step 1: Try Tailscale.
    if method in ("auto", "tailscale"):
        tailscale_info = T.detect_tailscale()
        if tailscale_info:
            hostname = tailscale_info["hostname"]
            print(f"  Detected Tailscale: {hostname}")
            result = T.generate_tailscale(cert_path, key_path, hostname)
            if result:
                print("  Tailscale certificate obtained")
            else:
                print("  Tailscale certificate generation failed")
        if method == "tailscale" and result is None:
            die("Tailscale not available or certificate generation failed")

    # Step 2: Try self-signed, with the SAME SAN richness (LAN IP, tailnet
    # name) --method ca gets, so a self-signed cert isn't thinner than a
    # CA-signed leaf for the identical host.
    if result is None and method in ("auto", "selfsigned"):
        leaf_hostnames, leaf_ips = T.default_leaf_sans()
        result = T.generate_self_signed(
            cert_path, key_path, hostnames=leaf_hostnames, ip_addresses=leaf_ips
        )

    # Step 3: Local CA (explicit opt-in only -- not part of "auto").
    if result is None and method == "ca":
        ca_cert_path = T.default_ca_cert_path()
        ca_key_path = T.default_ca_key_path()

        ca_info = T.generate_local_ca(ca_cert_path, ca_key_path)
        if ca_info["regenerated"]:
            print(f"  Generated local CA at {ca_cert_path}")
        else:
            print(f"  Reusing existing local CA at {ca_cert_path}")

        leaf_hostnames, leaf_ips = T.default_leaf_sans()
        result = T.generate_leaf_signed_by_ca(
            ca_cert_path,
            ca_key_path,
            cert_path,
            key_path,
            hostnames=leaf_hostnames,
            ip_addresses=leaf_ips,
        )
        result["ca_cert_path"] = str(ca_cert_path)
        result["ca_regenerated"] = ca_info["regenerated"]

    if result is None:
        die("TLS certificate generation failed with all methods")

    hostnames_str = ", ".join(result["hostnames"])
    expiry_str = (
        result["expires"].strftime("%Y-%m-%d")
        if hasattr(result["expires"], "strftime")
        else str(result["expires"])
    )

    print("TLS setup complete")
    print(f"  Certificate: {result['cert_path']}")
    print(f"  Key:         {result['key_path']}")
    print(f"  Hostnames:   {hostnames_str}")
    print(f"  Expires:     {expiry_str}")
    print()

    method_used = result.get("method", "")
    if method_used == "selfsigned":
        print("  Note: Browsers will show a security warning for self-signed certificates.")
        print("  Consider --method ca (or --method tailscale, if available) for a trusted")
        print("  certificate.")
        print()
    elif method_used == "tailscale":
        print("  Note: Tailscale certificates expire after 90 days.")
        print("  Run 'amplifier-work-tracker setup-tls' to renew.")
        print()
    elif method_used == "ca":
        print(f"  Local CA:    {result.get('ca_cert_path', '')}")
        print()
        print("  Install the CA on each client to eliminate browser warnings.")
        print("  The leaf rotates without re-trusting; the CA is what you trust.")
        print()
        print("  Windows (PowerShell, no admin needed):")
        print(
            "    Import-Certificate -FilePath <path-to-ca.crt> "
            "-CertStoreLocation Cert:\\CurrentUser\\Root"
        )
        print()
        print("  macOS:")
        print(
            "    sudo security add-trusted-cert -d -r trustRoot "
            "-k /Library/Keychains/System.keychain <path-to-ca.crt>"
        )
        print()
        print("  Linux (system-wide):")
        print("    sudo cp <path-to-ca.crt> /usr/local/share/ca-certificates/")
        print("    sudo update-ca-certificates")
        print()
        print("  Leaf cert rotates yearly -- re-run 'amplifier-work-tracker setup-tls --method ca'")
        print("  to generate a fresh leaf signed by the same CA (no client re-trust).")
        print()

    print(f"  {cert_path} / {key_path} are auto-detected by `web` and `serve --web-port`")
    print("  (no --tls-cert/--tls-key or --web-tls-cert/--web-tls-key needed).")
    print("  Restart the service to apply: amplifier-work-tracker service restart")


def cmd_web(a):
    """Serve the web dashboard + full interaction UI as an ADDITIONAL client
    of the same shared dolt server the CLI and background service use.

    Never spawns, supervises, restarts, or reinstalls anything -- see
    `webapp.py`'s module docstring. Requires the `web` extra
    (`pip install amplifier-work-tracker[web]`); a clear ImportError message
    (not a bare traceback) is what a caller sees if it isn't installed.
    """
    _guard()
    try:
        webapp = SV.import_web_modules()
    except RuntimeError as e:
        die(str(e))

    try:
        config, messages = webapp.resolve_web_config(
            host=a.host,
            public=a.public,
            port=a.port,
            auth_mode=a.auth_mode,
            session_ttl=a.session_ttl,
            tls_cert=a.tls_cert,
            tls_key=a.tls_key,
            http_port=a.http_port,
        )
    except webapp.WebConfigError as e:
        die(str(e))

    for m in messages:
        print(f"amplifier-work-tracker web: {m}", file=sys.stderr)
    ws = _ws(a)
    scheme = "https" if config.tls_cert else "http"
    print(
        f"amplifier-work-tracker web: listening on {scheme}://{config.host}:{config.port} "
        f"(root={ws.root})"
    )
    return webapp.run(ws, config)


def cmd_serve(a):
    """Run the supervisor in the foreground: dolt sql-server child + reap/notify sweeps,
    plus -- OPTIONALLY, when `--web-port` is given -- the web dashboard as a 4th
    concurrent task (see `supervisor.web_server_loop`).

    This is the systemd/launchd ExecStart target (see service.py) -- it is
    also perfectly runnable directly in a terminal for local testing or on a
    platform with no service manager at all.

    Omitting `--web-port` (the default) is behaviorally IDENTICAL to before
    this flag existed: three tasks, no uvicorn/fastapi import.
    """
    root = A.Workspace(getattr(a, "root", None)).root
    web_config = None
    if a.web_port is not None:
        web_config = SV.WebIntegrationConfig(
            host=a.web_host,
            public=a.web_public,
            port=a.web_port,
            auth_mode=a.web_auth_mode,
            session_ttl=a.web_session_ttl,
            tls_cert=a.web_tls_cert,
            tls_key=a.web_tls_key,
            http_port=a.web_http_port,
        )
    return SV.serve(
        root,
        host=a.dolt_host,
        port=a.dolt_port,
        reap_interval=a.reap_interval,
        notify_interval=a.notify_interval,
        dolt_restart_backoff=a.dolt_restart_backoff,
        dolt_restart_budget_count=a.dolt_restart_budget_count,
        dolt_restart_budget_window=a.dolt_restart_budget_window,
        web=web_config,
    )


def cmd_service_install(a):
    try:
        info = S.service_install(
            A.Workspace(getattr(a, "root", None)).root,
            dolt_host=a.dolt_host,
            dolt_port=a.dolt_port,
            web_port=a.web_port,
            web_host=a.web_host,
            web_public=a.web_public,
            web_auth_mode=a.web_auth_mode,
            web_session_ttl=a.web_session_ttl,
            web_tls_cert=a.web_tls_cert,
            web_tls_key=a.web_tls_key,
            web_http_port=a.web_http_port,
        )
    except (S.ServiceUnsupportedError, S.WebExtraNotImportableError, S.TlsConfigError) as e:
        die(str(e))
    print(f"Installed and started the {S.SERVICE_NAME} service ({info.platform}).")
    print(f"  Unit: {info.unit_path}")
    print("Check it: amplifier-work-tracker service status")
    print("Logs:     amplifier-work-tracker service logs")


def cmd_service_uninstall(a):
    try:
        S.service_uninstall()
    except S.ServiceUnsupportedError as e:
        die(str(e))
    print(f"Removed the {S.SERVICE_NAME} service (data directories were left untouched).")


def cmd_service_start(a):
    try:
        S.service_start()
    except S.ServiceUnsupportedError as e:
        die(str(e))
    print(f"Started the {S.SERVICE_NAME} service.")


def cmd_service_stop(a):
    try:
        S.service_stop()
    except S.ServiceUnsupportedError as e:
        die(str(e))
    print(f"Stopped the {S.SERVICE_NAME} service.")


def cmd_service_restart(a):
    try:
        S.service_restart()
    except S.ServiceUnsupportedError as e:
        die(str(e))
    print(f"Restarted the {S.SERVICE_NAME} service.")


def cmd_service_status(a):
    info = S.describe_service()
    print(f"platform: {info.platform}")
    print(f"installed: {info.installed}")
    print(f"active: {info.active}")
    print(f"detail: {info.detail}")
    if not info.installed:
        return
    print()
    try:
        S.service_status()
    except S.ServiceUnsupportedError as e:
        die(str(e))


def cmd_service_logs(a):
    try:
        S.service_logs()
    except S.ServiceUnsupportedError as e:
        die(str(e))


def main():
    root_parent = _root_parent_parser()
    ap = argparse.ArgumentParser(
        prog="amplifier-work-tracker",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "doctor", help="verify our assumptions against the live bd", parents=[root_parent]
    )
    p.add_argument(
        "--quick", action="store_true", help="skip the concurrency check (fast, but proves less)"
    )
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("new", help="create a named project", parents=[root_parent])
    p.add_argument("name")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser(
        "remove",
        help=(
            "remove a project: its .beads directory AND its shared-server database "
            "(refuses if any item is HELD; irreversible; requires --yes)"
        ),
        parents=[root_parent],
    )
    p.add_argument("name")
    p.add_argument(
        "--yes",
        action="store_true",
        help="required confirmation -- this is destructive and irreversible",
    )
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser(
        "rename",
        help=(
            "rename a project: its directory AND its shared-server database, together "
            "(refuses if the new name is taken, the old is missing, or any item is HELD; "
            "item ids are preserved)"
        ),
        parents=[root_parent],
    )
    p.add_argument("old", help="current project name")
    p.add_argument("new", help="new project name (same rules as `new`: lowercase/underscore)")
    p.set_defaults(fn=cmd_rename)

    p = sub.add_parser(
        "move",
        help=(
            "move one item from one project to another, preserving its id "
            "(refuses if the item is HELD, missing, or already exists at the destination; "
            "dependency edges to an item NOT moving are dropped and reported)"
        ),
        parents=[root_parent],
    )
    p.add_argument("--item", required=True, help="item id to move")
    p.add_argument("--from", dest="from_project", required=True, help="current project name")
    p.add_argument("--to", dest="to_project", required=True, help="destination project name")
    p.set_defaults(fn=cmd_move)

    p = sub.add_parser(
        "add",
        help=(
            "file a new engineering-lane work item directly (the sanctioned way to seed a "
            "project's first item(s), or add more later -- applies the lane label itself)"
        ),
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("title", help="short title for the new item")
    p.add_argument("--description", default=None, help="what needs to be done")
    p.add_argument("--acceptance", default=None, help="Given/When/Then acceptance criteria")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("instances", help="list projects", parents=[root_parent])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_instances)

    p = sub.add_parser(
        "status",
        help=(
            "full status breakdown for ONE project -- open/ready/held/intake/blocked/"
            "deferred/resolved counts plus aging and throughput; read-only"
        ),
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser(
        "list",
        help=(
            "read-only per-item listing for one project -- id, title, status, holder, "
            "and (for closed items) resolution; never claims or mutates anything"
        ),
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument(
        "--status",
        default=None,
        choices=A.STATUSES,
        help="filter to items with exactly this status (default: all statuses)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=f"max items to return (default {A.LIST_DEFAULT_LIMIT}, max {A.LIST_MAX_LIMIT})",
    )
    p.add_argument(
        "--id",
        default=None,
        help=(
            "read this SPECIFIC item's full record -- including description/acceptance/"
            "design, everything `claim` returns -- WITHOUT claiming it; ignores "
            "--status/--limit when given (mirrors `claim`'s own --id, PR #4)"
        ),
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser(
        "claim",
        help="safely claim one ready item, or a specific item by --id",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--lane", default=A.LANE_WORK)
    p.add_argument(
        "--id",
        default=None,
        help=(
            "claim this SPECIFIC item by id instead of the next queued one; "
            "refuses if already held, missing, or blocked by an open dependency"
        ),
    )
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser(
        "custody",
        help=(
            "establish custody of a claimed item and renew it on a timer; "
            "exits the moment the watched --pid disappears"
        ),
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--pid", type=int, default=0, help="PID to watch (default: parent process)")
    p.add_argument(
        "--declared-state",
        default=C.STATE_WORKING,
        choices=C.VALID_STATES,
        help="reporting only -- never affects reclaim eligibility",
    )
    p.add_argument(
        "--interval", type=int, default=C.RENEW_INTERVAL_SECONDS, help="seconds between renewals"
    )
    p.set_defaults(fn=cmd_custody)

    p = sub.add_parser(
        "reap",
        help=(
            "release items whose custody has gone stale or hit the escalation "
            "ceiling back to the queue"
        ),
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help=f"override CUSTODY_TTL_SECONDS (default {C.CUSTODY_TTL_SECONDS})",
    )
    p.add_argument(
        "--escalation-hours",
        type=float,
        default=None,
        help=f"override ESCALATION_HOURS (default {C.ESCALATION_HOURS})",
    )
    p.set_defaults(fn=cmd_reap)

    p = sub.add_parser(
        "resolve", help="close an item with a user-readable reason", parents=[root_parent]
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser(
        "unclaim",
        help="release a held item back to the ready queue WITHOUT resolving it",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_unclaim)

    p = sub.add_parser(
        "edit",
        help="amend an item's title/description/acceptance/design, or --merge-into another item",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--description", default=None)
    p.add_argument("--acceptance", default=None)
    p.add_argument("--design", default=None)
    p.add_argument(
        "--merge-into",
        dest="merge_into",
        default=None,
        help="mark --id as superseded by this item id instead of editing content",
    )
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_edit)

    p = sub.add_parser(
        "defer",
        help="defer an open item with --reason, or --clear a deferral back to open",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--clear", action="store_true")
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_defer)

    p = sub.add_parser(
        "block",
        help="block an open item with --reason, or --clear a block back to open",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--clear", action="store_true")
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_block)

    p = sub.add_parser(
        "dep",
        help="declare (--depends-on) or display dependency/dependent edges on --id",
        parents=[root_parent],
    )
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument(
        "--depends-on",
        dest="depends_on",
        default=None,
        help="declare --id depends on (is blocked by, per --type) this item id",
    )
    p.add_argument(
        "--type", dest="type", default="blocks", help="dependency type (default: blocks)"
    )
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_dep)

    p = sub.add_parser(
        "notify", help="propagate resolved work back to reporters", parents=[root_parent]
    )
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_notify)

    p = sub.add_parser(
        "update",
        help="self-update this CLI to the latest version (uv tool upgrade)",
    )
    p.add_argument(
        "--reinstall",
        action="store_true",
        help="force a rebuild even if the git ref resolves to the same commit",
    )
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser(
        "serve",
        help="run the supervisor in the foreground (dolt child + reap/notify sweep loops)",
        parents=[root_parent],
    )
    p.add_argument("--dolt-host", default=SV.DEFAULT_DOLT_HOST)
    p.add_argument("--dolt-port", type=int, default=SV.DEFAULT_DOLT_PORT)
    p.add_argument(
        "--reap-interval",
        type=float,
        default=float(SV.DEFAULT_REAP_INTERVAL_SECONDS),
        help=f"seconds between reap sweeps (default {SV.DEFAULT_REAP_INTERVAL_SECONDS})",
    )
    p.add_argument(
        "--notify-interval",
        type=float,
        default=float(SV.DEFAULT_NOTIFY_INTERVAL_SECONDS),
        help=f"seconds between notify sweeps (default {SV.DEFAULT_NOTIFY_INTERVAL_SECONDS})",
    )
    p.add_argument(
        "--dolt-restart-backoff",
        type=float,
        default=SV.DEFAULT_DOLT_RESTART_BACKOFF_SECONDS,
        help="seconds to wait before restarting a crashed dolt child",
    )
    p.add_argument(
        "--dolt-restart-budget-count",
        type=int,
        default=SV.DEFAULT_DOLT_RESTART_BUDGET_COUNT,
        help=(
            "give up on dolt (exit non-zero) after this many unexpected exits within "
            f"--dolt-restart-budget-window (default {SV.DEFAULT_DOLT_RESTART_BUDGET_COUNT})"
        ),
    )
    p.add_argument(
        "--dolt-restart-budget-window",
        type=float,
        default=SV.DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS,
        help=(
            "trailing window, in seconds, over which --dolt-restart-budget-count is measured "
            f"(default {SV.DEFAULT_DOLT_RESTART_BUDGET_WINDOW_SECONDS:.0f})"
        ),
    )
    p.add_argument(
        "--web-port",
        type=int,
        default=None,
        help=(
            "run the web dashboard as a 4th concurrent task alongside dolt/reap/notify "
            "(an OPTIONAL, additive feature -- omitting this flag, the default, runs "
            "EXACTLY as before: three tasks, no uvicorn/fastapi import required)"
        ),
    )
    p.add_argument(
        "--web-host",
        default=None,
        help=(
            "web dashboard bind host (default: 127.0.0.1, loopback-only; a non-loopback "
            "value requires --web-public); ignored unless --web-port is given"
        ),
    )
    p.add_argument(
        "--web-public",
        action="store_true",
        help=(
            "bind the web dashboard to all interfaces (0.0.0.0) for LAN access -- required "
            "explicitly to widen the default loopback bind; authentication is still enforced "
            "regardless; ignored unless --web-port is given"
        ),
    )
    p.add_argument(
        "--web-auth-mode",
        choices=["auto", "pam", "password"],
        default="auto",
        help=(
            "'auto' (default) uses PAM when the `pam` module is importable, else a generated "
            "password file; 'pam'/'password' force one explicitly; ignored unless --web-port "
            "is given"
        ),
    )
    p.add_argument(
        "--web-session-ttl",
        type=int,
        default=12 * 3600,
        help=(
            "web dashboard session cookie lifetime in seconds (default 12h; 0 = no "
            "server-side expiry); ignored unless --web-port is given"
        ),
    )
    p.add_argument(
        "--web-tls-cert",
        default=None,
        help=(
            "path to a TLS certificate PEM file for the web dashboard (pairs with "
            "--web-tls-key); serves https instead of http. If omitted, auto-uses the "
            "certificate generated by `setup-tls`, if present. Ignored unless --web-port "
            "is given"
        ),
    )
    p.add_argument(
        "--web-tls-key",
        default=None,
        help="path to the TLS certificate's private key PEM file (pairs with --web-tls-cert)",
    )
    p.add_argument(
        "--web-http-port",
        type=int,
        default=None,
        help=(
            "companion plain-HTTP port for the trust-bootstrap listener (see webtrust.py): "
            "an unauthenticated /trust page + CA download/profile, so a new device can install "
            "this host's CA before its first HTTPS visit -- no cert warning, no login. Only "
            "runs when TLS is active; ignored otherwise. Defaults to https port + 1 when TLS "
            "is active and this is omitted. Ignored unless --web-port is given"
        ),
    )
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser(
        "setup-tls",
        help="generate a TLS certificate so `web`/`serve --web-port` can serve https",
    )
    p.add_argument(
        "--method",
        choices=["auto", "selfsigned", "ca", "tailscale"],
        default="auto",
        help=(
            "'auto' (default) tries Tailscale, then falls back to a self-signed cert. "
            "'selfsigned' forces a self-signed cert. 'ca' generates/reuses a persistent "
            "local CA and signs a short-lived leaf with it (install the CA once per "
            "client for browser-trusted HTTPS with no public domain). 'tailscale' "
            "requires Tailscale HTTPS certs to be enabled, or fails loud"
        ),
    )
    p.set_defaults(fn=cmd_setup_tls)

    p = sub.add_parser(
        "web",
        help=(
            "serve the web dashboard + full interaction UI (an ADDITIONAL client of the "
            "same shared dolt server -- never spawns/supervises/restarts anything)"
        ),
        parents=[root_parent],
    )
    p.add_argument(
        "--host",
        default=None,
        help=(
            "bind host (default: 127.0.0.1, loopback-only; a non-loopback value requires --public)"
        ),
    )
    p.add_argument(
        "--public",
        action="store_true",
        help=(
            "bind to all interfaces (0.0.0.0) for LAN access -- required explicitly to widen "
            "the default loopback bind; authentication is still enforced regardless"
        ),
    )
    p.add_argument("--port", type=int, default=8090)
    p.add_argument(
        "--auth-mode",
        choices=["auto", "pam", "password"],
        default="auto",
        help=(
            "'auto' (default) uses PAM when the `pam` module is importable, else a generated "
            "password file; 'pam'/'password' force one explicitly"
        ),
    )
    p.add_argument(
        "--session-ttl",
        type=int,
        default=12 * 3600,
        help="session cookie lifetime in seconds (default 12h; 0 = no server-side expiry)",
    )
    p.add_argument(
        "--tls-cert",
        default=None,
        help=(
            "path to a TLS certificate PEM file (pairs with --tls-key); serves https "
            "instead of http. If omitted, auto-uses the certificate generated by "
            "`setup-tls`, if present"
        ),
    )
    p.add_argument(
        "--tls-key",
        default=None,
        help="path to the TLS certificate's private key PEM file (pairs with --tls-cert)",
    )
    p.add_argument(
        "--http-port",
        type=int,
        default=None,
        help=(
            "companion plain-HTTP port for the trust-bootstrap listener (see webtrust.py): "
            "an unauthenticated /trust page + CA download/profile, so a new device can install "
            "this host's CA before its first HTTPS visit -- no cert warning, no login. Only "
            "runs when TLS is active; ignored otherwise. Defaults to https port + 1 when TLS "
            "is active and this is omitted"
        ),
    )
    p.set_defaults(fn=cmd_web)

    svc = sub.add_parser(
        "service", help="install/manage amplifier-work-tracker as a background OS service"
    )
    svc_sub = svc.add_subparsers(dest="service_cmd", required=True)

    p = svc_sub.add_parser(
        "install", help="install (or re-install) and start the service", parents=[root_parent]
    )
    p.add_argument("--dolt-host", default=None)
    p.add_argument("--dolt-port", type=int, default=None)
    p.add_argument(
        "--web-port",
        type=int,
        default=None,
        help=(
            "bake `--web-port` into the installed unit's ExecStart, running the web "
            "dashboard as a 4th concurrent task inside the service (omit for no change "
            "in behavior -- the default)"
        ),
    )
    p.add_argument(
        "--web-host",
        default=None,
        help="bake `--web-host` into the installed unit; ignored unless --web-port is given",
    )
    p.add_argument(
        "--web-public",
        action="store_true",
        help="bake `--web-public` into the installed unit; ignored unless --web-port is given",
    )
    p.add_argument(
        "--web-auth-mode",
        choices=["auto", "pam", "password"],
        default="auto",
        help=("bake `--web-auth-mode` into the installed unit; ignored unless --web-port is given"),
    )
    p.add_argument(
        "--web-session-ttl",
        type=int,
        default=12 * 3600,
        help=(
            "bake `--web-session-ttl` into the installed unit; ignored unless --web-port is given"
        ),
    )
    p.add_argument(
        "--web-tls-cert",
        default=None,
        help=(
            "bake `--web-tls-cert` into the installed unit (pairs with --web-tls-key); "
            "serves https instead of http. If omitted, auto-uses the certificate generated "
            "by `setup-tls`, if present. Ignored unless --web-port is given"
        ),
    )
    p.add_argument(
        "--web-tls-key",
        default=None,
        help="bake `--web-tls-key` into the installed unit (pairs with --web-tls-cert)",
    )
    p.add_argument(
        "--web-http-port",
        type=int,
        default=None,
        help=(
            "bake `--web-http-port` into the installed unit's ExecStart -- the companion "
            "plain-HTTP trust-bootstrap listener (see webtrust.py). Only runs when TLS is "
            "active; defaults to https port + 1 when TLS is active and this is omitted. "
            "Ignored unless --web-port is given"
        ),
    )
    p.set_defaults(fn=cmd_service_install)

    p = svc_sub.add_parser("uninstall", help="stop and remove the service (data is left untouched)")
    p.set_defaults(fn=cmd_service_uninstall)

    p = svc_sub.add_parser("start", help="start the installed service")
    p.set_defaults(fn=cmd_service_start)

    p = svc_sub.add_parser("stop", help="stop the service without uninstalling it")
    p.set_defaults(fn=cmd_service_stop)

    p = svc_sub.add_parser("restart", help="restart the service")
    p.set_defaults(fn=cmd_service_restart)

    p = svc_sub.add_parser("status", help="show whether the service is installed and running")
    p.set_defaults(fn=cmd_service_status)

    p = svc_sub.add_parser("logs", help="stream or print the service's logs")
    p.set_defaults(fn=cmd_service_logs)

    a = ap.parse_args()
    try:
        sys.exit(a.fn(a) or 0)
    except A.AssumptionViolated as e:
        die(f"UNSUPPORTED BEADS: {e}")
    except A.BeadsError as e:
        die(str(e))


if __name__ == "__main__":
    main()
