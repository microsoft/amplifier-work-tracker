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


def cmd_doctor(a):
    """Prove the installed Beads still behaves the way we depend on."""
    results = contract.run_all(quick=a.quick)
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
            rows.append({"project": n, "status": f"ERROR: {e}"[:70]})
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
    _guard()
    try:
        item = _ws(a).project(a.project).claim_next(lane=a.lane, actor=a.actor)
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


def main():
    ap = argparse.ArgumentParser(
        prog="amplifier-work-tracker",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", help="workspace root (default: $AMPLIFIER_WORK_TRACKER_ROOT)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="verify our assumptions against the live bd")
    p.add_argument(
        "--quick", action="store_true", help="skip the concurrency check (fast, but proves less)"
    )
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("new", help="create a named project")
    p.add_argument("name")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("instances", help="list projects")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_instances)

    p = sub.add_parser("claim", help="safely claim one ready item")
    p.add_argument("--project", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--lane", default=A.LANE_WORK)
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser(
        "custody",
        help=(
            "establish custody of a claimed item and renew it on a timer; "
            "exits the moment the watched --pid disappears"
        ),
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

    p = sub.add_parser("resolve", help="close an item with a user-readable reason")
    p.add_argument("--project", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--actor", default="agent")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("notify", help="propagate resolved work back to reporters")
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_notify)

    a = ap.parse_args()
    try:
        sys.exit(a.fn(a) or 0)
    except A.AssumptionViolated as e:
        die(f"UNSUPPORTED BEADS: {e}")
    except A.BeadsError as e:
        die(str(e))


if __name__ == "__main__":
    main()
