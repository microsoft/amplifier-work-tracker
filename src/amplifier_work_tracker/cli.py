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
import socket
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


def cmd_doctor(a):
    """Prove the installed Beads still behaves the way we depend on, and that
    our own service/dolt-reachability are in a state parallel agents can
    trust."""
    results = contract.run_all(quick=a.quick)
    service_check = _check_service_installed()
    results.append(service_check)
    results.append(_check_dolt_reachable(service_check))
    results.append(_check_sweeps_alive(_ws(a).root))
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
    _guard()
    try:
        path = _ws(a).create(a.name)
    except A.BeadsError as e:
        die(str(e))
    print(f"created project '{a.name}' at {path} (verified writable)")


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
    _guard()
    ws = _ws(a)
    names = ws.names()
    if not names:
        print("no projects")
        return
    rows = []
    for n in names:
        try:
            items = ws.project(n).list(include_resolved=True)
            rows.append(
                {
                    "project": n,
                    "total": len(items),
                    "ready": sum(1 for i in items if i.status == "open" and A.LANE_WORK in i.tags),
                    "held": sum(1 for i in items if i.status == "held"),
                    "intake": sum(
                        1 for i in items if i.status == "open" and A.LANE_INTAKE in i.tags
                    ),
                    "status": "ok",
                }
            )
        except A.BeadsError as e:
            # A.truncate_status -- see its docstring: a bare slice cap
            # severs the actionable hint mid-word (same bug as the
            # work_status tool's per-project error; fixed in one place).
            rows.append({"project": n, "status": A.truncate_status(f"ERROR: {e}")})
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"{'PROJECT':<20} {'TOTAL':>6} {'READY':>6} {'HELD':>5} {'INTAKE':>7}  STATUS")
    for r in rows:
        print(
            f"{r['project']:<20} {r.get('total', ''):>6} {r.get('ready', ''):>6} "
            f"{r.get('held', ''):>5} {r.get('intake', ''):>7}  {r['status']}"
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


def cmd_serve(a):
    """Run the supervisor in the foreground: dolt sql-server child + reap/notify sweeps.

    This is the systemd/launchd ExecStart target (see service.py) -- it is
    also perfectly runnable directly in a terminal for local testing or on a
    platform with no service manager at all.
    """
    root = A.Workspace(getattr(a, "root", None)).root
    return SV.serve(
        root,
        host=a.dolt_host,
        port=a.dolt_port,
        reap_interval=a.reap_interval,
        notify_interval=a.notify_interval,
        dolt_restart_backoff=a.dolt_restart_backoff,
    )


def cmd_service_install(a):
    try:
        info = S.service_install(
            A.Workspace(getattr(a, "root", None)).root, dolt_host=a.dolt_host, dolt_port=a.dolt_port
        )
    except S.ServiceUnsupportedError as e:
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
        "notify", help="propagate resolved work back to reporters", parents=[root_parent]
    )
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_notify)

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
    p.set_defaults(fn=cmd_serve)

    svc = sub.add_parser(
        "service", help="install/manage amplifier-work-tracker as a background OS service"
    )
    svc_sub = svc.add_subparsers(dest="service_cmd", required=True)

    p = svc_sub.add_parser(
        "install", help="install (or re-install) and start the service", parents=[root_parent]
    )
    p.add_argument("--dolt-host", default=None)
    p.add_argument("--dolt-port", type=int, default=None)
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
