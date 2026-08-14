"""Executable assumptions -- our early-warning system for Beads changing.

Every behaviour amplifier-work-tracker depends on is asserted here against the
LIVE binary in a throwaway project. This is the whole loose-coupling strategy:
we do not try to predict how Beads will change, we make it impossible for a
change to reach production silently.

Run `amplifier-work-tracker doctor` after any `bd` upgrade, and in CI. A
failure names the exact assumption id, so the fix is scoped to
`amplifier_work_tracker/adapter.py` and nothing else.

The most important check is `claim.atomic`, and it is genuinely adversarial:
it spawns real concurrent processes and counts winners. A read-only inspection
would have passed on a build we measured double-claiming 5 times out of 6.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import adapter as A
from . import custody as C


@dataclass
class Result:
    id: str
    ok: bool
    detail: str

    @property
    def mark(self) -> str:
        return "PASS" if self.ok else "FAIL"


def _probe_name() -> str:
    return f"contract{int(time.time())}{os.getpid() % 1000}"


class Probe:
    """A disposable project used only to interrogate the live binary.

    "Disposable" means BOTH halves of a project, not just the local one.
    A project lives in two independent places -- a directory under
    `self.root`, and a database on the shared dolt server -- and removing
    only the first is what made every `doctor` run leak a permanent
    `contract<ts><pid>` database. Measured on a live box: 47 orphaned
    `contract*` databases from doctor runs alone, in a server holding 5
    real projects. dolt keeps every database open, so the cost is paid
    continuously in RSS, not just in disk.

    Databases a *check* derives from this probe's name (rather than
    creating through `self.ws`) must be handed to `register_database` so
    they are dropped here too -- see `check_project_removal`, whose own
    best-effort cleanup was measured leaking 4 `<name>rm` databases.
    """

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="awtcontract_"))
        self.ws = A.Workspace(self.root)
        self.name = _probe_name()
        self.bd: A.Beads | None = None
        # Databases to drop on exit, in creation order. The probe's own
        # database is registered by `__enter__` only after `create`
        # succeeds -- a `create` that failed partway may still have left a
        # database behind, which is exactly why `drop_database` treats
        # "not found" as a no-op rather than an error.
        self._databases: list[str] = []
        self.leaked: list[str] = []

    def register_database(self, name: str) -> None:
        """Also drop `name` when this probe exits (idempotent)."""
        if name not in self._databases:
            self._databases.append(name)

    def __enter__(self):
        self.register_database(self.name)
        self.ws.create(self.name)
        self.bd = self.ws.project(self.name)
        return self

    def __exit__(self, *exc):
        """Drop every database this probe is responsible for, then the
        temp directory.

        A failure here is reported loudly on stderr, naming each database
        that survived and how to remove it -- never swallowed. It is
        deliberately not raised: `__exit__` raising would replace a real
        `doctor` verdict (or a real test failure) with a teardown
        traceback, which is a worse failure mode than a named leak the
        operator can act on. `self.leaked` carries the same list for any
        caller that wants to assert on it.
        """
        for name in self._databases:
            try:
                A.drop_database(name)
            except A.BeadsError as e:  # noqa: PERF203 - per-database, so one failure cannot hide the rest
                self.leaked.append(name)
                print(
                    f"WARNING: contract probe could not drop its database {name!r}: {e}\n"
                    f"         It is now orphaned on the shared dolt server, which holds "
                    f"every database open. Remove it with: "
                    f"python scripts/sweep_test_residue.py --confirmed",
                    file=sys.stderr,
                )
        shutil.rmtree(self.root, ignore_errors=True)
        return False


# ------------------------------------------------------------------ checks


def check_version() -> Result:
    try:
        v, warn = A.check_version()
        return Result(
            "version",
            True,
            f"bd {'.'.join(map(str, v))}" + (f" -- {warn}" if warn else ""),
        )
    except A.BeadsError as e:
        return Result("version", False, str(e))


def check_claim_subcommand(p: Probe) -> Result:
    """`ready --claim` must exist, and must reject an explicit assignee."""
    # Non-interactive by construction -- see `adapter._bd_env`'s docstring:
    # every `bd` call site in this package must build its env through it.
    env = A._bd_env({"BEADS_DIR": str(p.ws.path(p.name) / ".beads")})
    r = subprocess.run(
        ["bd", "ready", "--help"], capture_output=True, text=True, env=env, check=False
    )
    if "--claim" not in (r.stdout or ""):
        return Result(
            "claim.subcommand",
            False,
            "`bd ready` has no --claim flag; the safe claim path is gone",
        )
    r2 = subprocess.run(
        ["bd", "ready", "--claim", "--assignee", "x", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    blob = (r2.stdout or "") + (r2.stderr or "")
    if "cannot be combined" not in blob:
        return Result(
            "claim.subcommand",
            True,
            "--claim present; note: --assignee no longer rejected "
            "(adapter passes identity via BEADS_ACTOR regardless)",
        )
    return Result("claim.subcommand", True, "--claim present, rejects --assignee as expected")


def check_claim_atomic(p: Probe, workers: int = 12, trials: int = 5) -> Result:
    """The one that matters. Real concurrent processes, count the winners.

    A double-claim is silent: several agents each get a success and only one is
    really the holder. Static inspection cannot catch it; contention can.
    """
    assert p.bd
    beads_dir = str(p.ws.path(p.name) / ".beads")
    lane = "lane:contract"
    bad = []
    for t in range(trials):
        p.bd.create(f"atomic probe {t}", tags=[lane], priority=1)

        def one(n: int):
            env = A._bd_env({"BEADS_DIR": beads_dir, "BEADS_ACTOR": f"probe{n}"})
            r = None
            for attempt in range(8):
                r = subprocess.run(
                    ["bd", "ready", "--label", lane, "--claim", "--json"],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                blob = (r.stdout or "") + (r.stderr or "")
                if any(s.lower() in blob.lower() for s in A._RETRYABLE):
                    time.sleep(0.1 * (2**attempt))
                    continue
                break
            if r is None:
                return None
            try:
                data = json.loads((r.stdout or "").strip() or "null")
            except json.JSONDecodeError:
                return None
            items = data if isinstance(data, list) else ([data] if data else [])
            ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id")]
            return ids[0] if ids else None

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            got = [f.result() for f in [ex.submit(one, n) for n in range(workers)]]
        claimed = [g for g in got if g]
        if len(claimed) != len(set(claimed)):
            dupes = {c for c in claimed if claimed.count(c) > 1}
            bad.append(f"trial {t}: same item to multiple agents: {sorted(dupes)}")
    if bad:
        return Result(
            "claim.atomic",
            False,
            f"{len(bad)}/{trials} trials double-claimed -- "
            f"parallel agents WILL corrupt each other. " + "; ".join(bad[:2]),
        )
    return Result(
        "claim.atomic",
        True,
        f"{trials} trials x {workers} concurrent claimers, no double-claims",
    )


def check_claim_directed_atomic(p: Probe, workers: int = 12, trials: int = 5) -> Result:
    """Directed-claim counterpart to `check_claim_atomic`: `bd update <id>
    --claim` against the SAME item, from many concurrent processes, must
    yield exactly one winner. Losers must fail loudly (non-zero exit)
    rather than a second party silently believing it also holds the item.

    This is the check that pins the empirical finding this feature was
    built on: `bd update <id> --claim` (the directed-claim primitive) is,
    itself, a real compare-and-swap on bd 1.1.2 -- unlike the two-step
    `bd ready` -> pick -> `bd update --claim` race `claim_next` exists to
    avoid. Same command, very different safety property depending on
    whether the id was chosen by many racing readers or supplied directly.
    """
    assert p.bd
    beads_dir = str(p.ws.path(p.name) / ".beads")
    lane = "lane:directed_contract"
    bad = []
    for t in range(trials):
        item_id = p.bd.create(f"directed atomic probe {t}", tags=[lane], priority=1)

        def one(n: int, item_id: str = item_id):
            env = A._bd_env({"BEADS_DIR": beads_dir, "BEADS_ACTOR": f"dprobe{n}"})
            r = None
            for attempt in range(8):
                r = subprocess.run(
                    ["bd", "update", item_id, "--claim", "--json"],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                blob = (r.stdout or "") + (r.stderr or "")
                if any(s.lower() in blob.lower() for s in A._RETRYABLE):
                    time.sleep(0.1 * (2**attempt))
                    continue
                break
            if r is None or r.returncode != 0:
                return None
            try:
                data = json.loads((r.stdout or "").strip() or "null")
            except json.JSONDecodeError:
                return None
            items = data if isinstance(data, list) else ([data] if data else [])
            ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id")]
            return ids[0] if ids else None

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            got = [f.result() for f in [ex.submit(one, n) for n in range(workers)]]
        winners = [g for g in got if g]
        if len(winners) != 1:
            bad.append(f"trial {t}: {len(winners)} winners for {item_id} (expected exactly 1)")
    if bad:
        return Result(
            "claim.directed_atomic",
            False,
            f"{len(bad)}/{trials} trials did not yield exactly one winner -- "
            f"directed claims WILL double-claim under contention. " + "; ".join(bad[:2]),
        )
    return Result(
        "claim.directed_atomic",
        True,
        f"{trials} trials x {workers} concurrent directed claimers on the SAME "
        f"item, exactly one winner each time",
    )


def check_link_nonblocking(p: Probe) -> Result:
    """A `discovered-from` link must not block the item that carries it."""
    assert p.bd
    src = p.bd.create("probe report", tags=["lane:probe_src"])
    work = p.bd.create("probe work", tags=["lane:probe_work"], discovered_from=[src])
    ready = [i.id for i in p.bd.list(lane="lane:probe_work")]
    if work not in ready:
        return Result(
            "link.nonblocking",
            False,
            f"{work} is linked to an open source and no longer appears "
            f"ready -- discovered-from has become blocking, which would "
            f"stall every triaged item",
        )
    return Result("link.nonblocking", True, "discovered-from is non-blocking")


def check_list_includes_closed(p: Probe) -> Result:
    assert p.bd
    i = p.bd.create("probe closeable", tags=["lane:probe_closed"])
    p.bd.resolve(i, "probe resolution text")
    without = [x.id for x in p.bd.list(lane="lane:probe_closed")]
    with_all = [x.id for x in p.bd.list(lane="lane:probe_closed", include_resolved=True)]
    if i in without:
        return Result(
            "list.includes_closed",
            True,
            "closed items now appear by default (adapter's --all is harmless)",
        )
    if i not in with_all:
        return Result(
            "list.includes_closed",
            False,
            "closed items are invisible even with the all-flag -- reporters "
            "would never see their answered reports",
        )
    return Result("list.includes_closed", True, "all-flag required and working")


def check_list_status_filter_includes_closed(p: Probe) -> Result:
    """`Beads.list_bounded` (and `list(status=...)`) depends on an explicit
    `--status` filter showing closed items WITHOUT also needing `--all` --
    verified empirically against bd 1.1.2 (`bd list --status closed --json`
    returns the closed item with no `--all` present). If a future bd
    reverts to requiring `--all` alongside `--status`, `work_list`/the CLI's
    `list` subcommand would silently under-report resolved items -- this
    check exists so that regression fails loudly here instead.
    """
    assert p.bd
    i = p.bd.create("probe status-filter closed", tags=["lane:probe_status_filter"])
    p.bd.resolve(i, "probe resolution for status filter")
    via_status = [x.id for x in p.bd.list(lane="lane:probe_status_filter", status="resolved")]
    if i not in via_status:
        return Result(
            "list.status_filter_includes_closed",
            False,
            "`bd list --status closed` (no --all) did not include a closed item -- "
            "work_list's status='resolved' filter would silently return nothing",
        )
    return Result(
        "list.status_filter_includes_closed",
        True,
        "an explicit --status filter shows closed items without --all",
    )


def check_show_dependents(p: Probe) -> Result:
    """Reverse traversal is how a reporter learns their report was fixed."""
    assert p.bd
    src = p.bd.create("probe rev src", tags=["lane:probe_rev"])
    work = p.bd.create("probe rev work", tags=["lane:probe_rev"], discovered_from=[src])
    linked = p.bd.get(src, with_links=True)
    to_ids = [x["id"] for x in linked.links if x["direction"] == "to"]
    if work not in to_ids:
        return Result(
            "show.dependents",
            False,
            "reverse links are not returned even with the include flag -- "
            "the report-to-fix path is broken",
        )
    bare = p.bd.get(src, with_links=True)
    return Result("show.dependents", True, f"reverse link visible ({len(bare.links)} links)")


def check_resolution_readable(p: Probe) -> Result:
    assert p.bd
    i = p.bd.create("probe resolution", tags=["lane:probe_res"])
    text = "probe fix text 12345"
    p.bd.resolve(i, text)
    back = p.bd.get(i)
    if (back.resolution or "").find("12345") < 0:
        return Result(
            "resolution.readable",
            False,
            f"resolution text not readable after close (got "
            f"{back.resolution!r}) -- users would be told 'fixed' with no detail",
        )
    return Result("resolution.readable", True, "resolution text round-trips")


def check_metadata_roundtrip(p: Probe) -> Result:
    assert p.bd
    meta = {"reporter_id": "probe_user", "nested": {"a": 1}, "unicode": "café ☕"}
    i = p.bd.create("probe meta", tags=["lane:probe_meta"], meta=meta)
    back = p.bd.get(i)
    if back.meta.get("reporter_id") != "probe_user" or back.meta.get("unicode") != "café ☕":
        return Result(
            "metadata.roundtrip",
            False,
            f"metadata did not survive: {back.meta!r} -- reporter identity "
            f"and captured context would be lost",
        )
    return Result("metadata.roundtrip", True, "arbitrary JSON metadata round-trips")


def check_name_rules(p: Probe) -> Result:
    """Confirm the dotted-name hazard still exists (or has been fixed upstream)."""
    root = Path(tempfile.mkdtemp(prefix="awtname_"))
    try:
        d = root / "dotted.name"
        d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "i"],
            cwd=d,
            capture_output=True,
            check=False,
        )
        init = subprocess.run(
            ["bd", "init", "--prefix", "dotted.name", "--shared-server"],
            cwd=d,
            capture_output=True,
            text=True,
            env=A._bd_env(),
            check=False,
        )
        use = subprocess.run(
            ["bd", "list", "--json"],
            capture_output=True,
            text=True,
            env=A._bd_env({"BEADS_DIR": str(d / ".beads")}),
            check=False,
        )
        broken = "invalid database name" in ((use.stdout or "") + (use.stderr or ""))
        if init.returncode == 0 and broken:
            return Result(
                "project.name_rules",
                True,
                "dotted names still init-then-fail; our validator is still needed",
            )
        if init.returncode != 0:
            return Result(
                "project.name_rules",
                True,
                "dotted names now rejected by bd itself; our validator is redundant but harmless",
            )
        return Result(
            "project.name_rules",
            True,
            "dotted names appear usable now; validator may be relaxed",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def check_capabilities(p: Probe) -> Result:
    """Every bd subcommand OUR code calls must actually EXIST in this build.

    This check exists because it did not: we once shipped
    `amplifier-work-tracker heartbeat` and `amplifier-work-tracker reap` calling
    `bd heartbeat` / `bd reclaim` -- commands that are present in the Beads repo
    source but ABSENT from the v1.1.2 release. Neither had ever been executed.
    Reading source is not the same as probing the binary you actually run.

    We no longer call `bd heartbeat` / `bd reclaim` at all -- liveness for
    held claims is entirely ours now (see amplifier_work_tracker.custody),
    because bd's own leases are node-local (dolt_ignored) and never
    replicate. So this check only asserts the core commands we DO call;
    heartbeat/reclaim presence is informational only, never a failure.
    """
    caps = A.capabilities()
    core = ["ready", "create", "show", "list", "close", "update"]
    missing_core = [c for c in core if not caps.get(c)]
    if missing_core:
        return Result(
            "capabilities",
            False,
            f"core commands missing from this bd build: {missing_core}",
        )
    note = ""
    if caps.get("heartbeat") or caps.get("reclaim"):
        note = (
            " (this bd build now offers heartbeat/reclaim natively -- still "
            "unused by design; liveness stays on amplifier_work_tracker.custody)"
        )
    return Result("capabilities", True, "all required bd commands present" + note)


def check_resolve_fenced(p: Probe) -> Result:
    """A stale holder must NOT be able to close work it no longer owns.

    The zombie case: agent A claims, A's claim is taken over by B (reclaim, or
    an operator reassignment), then A wakes up and closes. Without a fence,
    every party gets exit 0 and the work is silently closed by a non-holder.
    """
    assert p.bd
    lane = "lane:fence"
    p.bd.create("fence probe", tags=[lane], priority=1)
    item = p.bd.claim_next(lane=lane, actor="holder_a")
    if item is None:
        return Result("resolve.fenced", False, "could not claim the probe item")
    # Simulate takeover: B becomes the holder.
    p.bd.release(item.id)
    taken = p.bd.claim_next(lane=lane, actor="holder_b")
    if taken is None or taken.id != item.id:
        return Result("resolve.fenced", False, "could not stage the takeover")
    try:
        p.bd.resolve(item.id, "stale holder should not be able to write this", actor="holder_a")
    except A.BeadsError:
        return Result("resolve.fenced", True, "stale holder refused, as required")
    return Result(
        "resolve.fenced",
        False,
        "STALE HOLDER WAS ALLOWED TO CLOSE work held by another agent "
        "-- silent lost update; parallel agents will overwrite each other",
    )


def check_custody_fresh_survives(p: Probe) -> Result:
    """A custody signal renewed recently must NOT be reclaimed, no matter how
    long the TOTAL hold has been -- simulated by forging started_at 20 hours
    into the past while last_seen stays fresh, rather than waiting 15 minutes
    for a real one to age.
    """
    long_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 20 * 3600))
    forged = {
        "holder": "someone",
        "pid": 1,
        "host": "h",
        "generation": 1,
        "started_at": long_ago,
        "declared_since": long_ago,
        "last_seen": C.now_iso(),
        "declared_state": C.STATE_WORKING,
    }
    eligible, reason = C.reclaim_eligible(forged, ttl=C.CUSTODY_TTL_SECONDS)
    if eligible:
        return Result(
            "custody.fresh_survives",
            False,
            f"a 20h-old hold with a fresh renewal was judged reclaimable: {reason}",
        )
    return Result(
        "custody.fresh_survives",
        True,
        "a fresh renewal survives regardless of total hold duration",
    )


def check_custody_stale_reclaimed(p: Probe) -> Result:
    """A custody signal that stopped being renewed must become reclaimable --
    simulated with a forged last_seen an hour in the past, not a real wait.
    """
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    forged = {
        "holder": "someone",
        "pid": 1,
        "host": "h",
        "generation": 1,
        "started_at": stale,
        "declared_since": stale,
        "last_seen": stale,
        "declared_state": C.STATE_WORKING,
    }
    eligible, reason = C.reclaim_eligible(forged, ttl=C.CUSTODY_TTL_SECONDS)
    if not eligible:
        return Result(
            "custody.stale_reclaimed",
            False,
            "a custody signal stale for an hour was NOT judged reclaimable",
        )
    return Result("custody.stale_reclaimed", True, f"stale custody is reclaimed: {reason}")


def check_custody_idle_not_exempt(p: Probe) -> Result:
    """Declaring awaiting_human must NOT buy immortality: if the custody
    signal itself goes stale, it is reclaimed exactly like a 'working' one.
    This is the check that proves reclaim never trusts the agent's own
    narration -- only whether it is still renewing.
    """
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    forged = {
        "holder": "someone",
        "pid": 1,
        "host": "h",
        "generation": 1,
        "started_at": stale,
        "declared_since": stale,
        "last_seen": stale,
        "declared_state": C.STATE_AWAITING_HUMAN,
    }
    eligible, reason = C.reclaim_eligible(forged, ttl=C.CUSTODY_TTL_SECONDS)
    if not eligible:
        return Result(
            "custody.idle_not_exempt",
            False,
            "an item declaring awaiting_human with STALE custody "
            "was NOT reclaimed -- narration is buying immortality",
        )
    return Result(
        "custody.idle_not_exempt",
        True,
        f"awaiting_human with stale custody is still reclaimed: {reason}",
    )


def check_custody_fenced(p: Probe) -> Result:
    """After a takeover, the OLD holder's custody renewal AND resolve must
    both be refused. Same zombie shape as resolve.fenced, one layer deeper:
    this is our own custody layer's fence, not just bd's assignee fence.
    """
    assert p.bd
    lane = "lane:custody_fence"
    p.bd.create("custody fence probe", tags=[lane], priority=1)
    item = p.bd.claim_next(lane=lane, actor="cf_holder_a")
    if item is None:
        return Result("custody.fenced", False, "could not claim the probe item")
    rec_a = p.bd.take_custody(item.id, holder="cf_holder_a", pid=1, host="h")
    # Takeover: release, then a different actor claims it.
    p.bd.release(item.id)
    taken = p.bd.claim_next(lane=lane, actor="cf_holder_b")
    if taken is None or taken.id != item.id:
        return Result("custody.fenced", False, "could not stage the takeover")
    rec_b = p.bd.take_custody(item.id, holder="cf_holder_b", pid=2, host="h")
    if rec_b["generation"] <= rec_a["generation"]:
        return Result(
            "custody.fenced",
            False,
            f"generation did not increase on takeover: "
            f"{rec_a['generation']} -> {rec_b['generation']}",
        )
    try:
        p.bd.renew_custody(item.id, holder="cf_holder_a", generation=rec_a["generation"], pid=1)
        return Result(
            "custody.fenced",
            False,
            "STALE HOLDER'S CUSTODY RENEWAL WAS ALLOWED after a takeover",
        )
    except A.BeadsError:
        pass
    try:
        p.bd.resolve(
            item.id,
            "stale holder should not be able to close this",
            actor="cf_holder_a",
        )
        return Result(
            "custody.fenced",
            False,
            "STALE HOLDER WAS ALLOWED TO RESOLVE after a custody takeover",
        )
    except A.BeadsError:
        pass
    return Result(
        "custody.fenced",
        True,
        "old holder's renew and resolve are both refused after takeover",
    )


def check_project_removal(p: Probe) -> Result:
    """`Workspace.remove` must make BOTH the `.beads` directory and the
    shared-server database actually disappear, and a subsequent
    `Workspace.create` of the same name must come back genuinely empty --
    not a silent resurrection of the just-removed data.

    This is the assumption that pins the exact bug measured on a live box:
    no removal command existed, an operator `rm -rf`'d a project directory
    by hand, orphaning its database, and a later `new` of the same name
    silently reattached to it and reported "created" -- with someone
    else's items in it. If a future `bd`/dolt change makes `DROP DATABASE`
    (see `A.drop_database`) stop actually dropping data, or makes
    `bd init` behave differently against a pre-existing database, this
    check fails loudly rather than the corruption reappearing silently.

    Uses `p.ws` (the same Workspace/root the rest of the contract suite
    already proved reachable) with its own uniquely-named probe project,
    so it never interferes with -- or depends on run order relative to --
    any other check.
    """
    name = f"{p.name}rm"
    # Registered BEFORE the first create: from here on this database is the
    # probe's to drop no matter which branch below returns, including the
    # best-effort final cleanup failing (measured leaking 4 `<name>rm`
    # databases on a live box) or a check raising partway through.
    p.register_database(name)
    try:
        p.ws.create(name)
    except A.BeadsError as e:
        return Result("project.removal", False, f"could not set up removal probe project: {e}")
    p.ws.project(name).create("removal probe item", tags=["lane:removal_probe"], priority=1)

    try:
        report = p.ws.remove(name, force=True)
    except A.BeadsError as e:
        return Result("project.removal", False, f"remove() failed on a removable project: {e}")
    if not report.database_removed:
        return Result(
            "project.removal",
            False,
            "remove() did not report the database as removed on a project that had one",
        )
    if A.database_exists(name):
        return Result(
            "project.removal",
            False,
            f"database {name!r} still answers on the shared server after remove() -- "
            f"removal is not actually dropping it",
        )

    try:
        p.ws.create(name)
        items = p.ws.project(name).list(include_resolved=True)
    except A.BeadsError as e:
        return Result("project.removal", False, f"re-create after removal failed: {e}")
    if items:
        return Result(
            "project.removal",
            False,
            f"re-created project {name!r} came back with {len(items)} item(s) -- "
            f"removal left the database behind and create() silently adopted it",
        )

    try:
        p.ws.remove(name, force=True)
    except A.BeadsError:
        pass  # best-effort final cleanup; the assumption itself already passed or failed above
    return Result(
        "project.removal",
        True,
        "remove() drops both the directory and database; re-create afterward is genuinely empty",
    )


CHECKS = [
    ("capabilities", check_capabilities),
    ("resolve.fenced", check_resolve_fenced),
    ("claim.subcommand", check_claim_subcommand),
    ("claim.atomic", check_claim_atomic),
    ("claim.directed_atomic", check_claim_directed_atomic),
    ("link.nonblocking", check_link_nonblocking),
    ("list.includes_closed", check_list_includes_closed),
    ("list.status_filter_includes_closed", check_list_status_filter_includes_closed),
    ("show.dependents", check_show_dependents),
    ("resolution.readable", check_resolution_readable),
    ("metadata.roundtrip", check_metadata_roundtrip),
    ("project.name_rules", check_name_rules),
    ("custody.fresh_survives", check_custody_fresh_survives),
    ("custody.stale_reclaimed", check_custody_stale_reclaimed),
    ("custody.idle_not_exempt", check_custody_idle_not_exempt),
    ("custody.fenced", check_custody_fenced),
    ("project.removal", check_project_removal),
]


def run_all(quick: bool = False) -> list[Result]:
    results = [check_version()]
    if not results[0].ok:
        return results
    # The adversarial concurrency checks -- real concurrent processes, several
    # trials each. `--quick` skips both: they are the two slowest checks by a
    # wide margin (many subprocess round-trips per trial), and skipping only
    # one of them (the original `claim.atomic`) left `--quick` nearly as slow
    # as a full run once `claim.directed_atomic` was added alongside it.
    _SLOW_CONCURRENCY_CHECKS = {"claim.atomic", "claim.directed_atomic"}
    with Probe() as p:
        for name, fn in CHECKS:
            if quick and name in _SLOW_CONCURRENCY_CHECKS:
                results.append(
                    Result(
                        name,
                        True,
                        "skipped (--quick); run full doctor before trusting parallel agents",
                    )
                )
                continue
            try:
                results.append(fn(p))
            except Exception as e:  # noqa: BLE001 - a check that cannot run IS a failure
                results.append(Result(name, False, f"check could not complete: {e}"))
    return results
