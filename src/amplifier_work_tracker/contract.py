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
    r = A._run_bounded(["bd", "ready", "--help"], env=env)
    if "--claim" not in (r.stdout or ""):
        return Result(
            "claim.subcommand",
            False,
            "`bd ready` has no --claim flag; the safe claim path is gone",
        )
    r2 = A._run_bounded(["bd", "ready", "--claim", "--assignee", "x", "--json"], env=env)
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
                r = A._run_bounded(["bd", "ready", "--label", lane, "--claim", "--json"], env=env)
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
                r = A._run_bounded(["bd", "update", item_id, "--claim", "--json"], env=env)
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


def check_read_no_mutation(p: Probe) -> Result:
    """The read path (`Beads.get_readonly` -- the `work_list` tool's
    `item_id` directed read, and the CLI's `list --id`) is safe by
    construction only if `bd show` truly never mutates the item it reads.
    If a future bd release ever gave `show` a side effect (touching
    `updated_at`, auto-assigning on first view, migrating stored fields on
    read), every claim this feature makes -- "reading never claims, never
    takes custody, never changes status" -- would silently stop being true,
    and an agent choosing to read instead of claim would be quietly worse
    off for it.

    Reads the same item several times, through both `get` and
    `get_readonly` (including its not-found and wrong-project error
    branches -- these misses must be equally inert), and asserts status,
    holder, and the full metadata blob are identical before and after.
    """
    assert p.bd
    lane = "lane:read_probe"
    item_id = p.bd.create("read probe item", tags=[lane], priority=1)
    before = p.bd.get(item_id)
    for _ in range(3):
        p.bd.get(item_id)
        p.bd.get_readonly(item_id)
    try:
        p.bd.get_readonly(f"{p.name}-doesnotexist999")
    except A.BeadsError:
        pass
    try:
        p.bd.get_readonly("not-this-project-at-all-1")
    except A.BeadsError:
        pass
    after = p.bd.get(item_id)
    if before.status != after.status or before.holder != after.holder or before.meta != after.meta:
        return Result(
            "read.no_mutation",
            False,
            f"reading {item_id} repeatedly changed its state: status "
            f"{before.status!r} -> {after.status!r}, holder {before.holder!r} -> "
            f"{after.holder!r} -- `bd show` (or our wrapper around it) is no "
            f"longer side-effect-free; the read path can no longer be trusted "
            f"not to disturb an item it only looked at",
        )
    return Result(
        "read.no_mutation",
        True,
        "repeated reads (including not-found/wrong-project misses) leave status, "
        "holder, and metadata unchanged",
    )


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


def check_timestamps_readable(p: Probe) -> Result:
    """`created_at`/`updated_at`/`closed_at` must survive from bd's own
    `show --json` into our own `Item`, parsed as real datetimes -- not
    merely present on the raw payload. Pins the exact gap measured live:
    bd recorded all three on every item the whole time, but `Item.summary()`
    never read them, so a project's real aging/throughput data was
    unreachable through this seam even though bd had it all along.

    Checked in dependency order, same convention as the rest of this
    module's checks that build on an earlier operation succeeding
    (create, then close): if `create` itself is broken, `claim.atomic`/
    `resolution.readable` already fail loudly for that -- this check does
    not re-diagnose bd's basic write path, only whether OUR parsing of
    its timestamps holds up once a create/close genuinely happened.
    """
    assert p.bd
    i = p.bd.create("timestamp probe", tags=["lane:probe_ts"])
    created = p.bd.get(i)
    if created.created_at is None or created.updated_at is None:
        return Result(
            "timestamps.readable",
            False,
            f"created_at/updated_at missing (or unparseable) on freshly created "
            f"{i!r} -- bd's own `show --json` no longer includes them, or our "
            f"parsing broke: created_at={created.raw.get('created_at')!r}, "
            f"updated_at={created.raw.get('updated_at')!r}",
        )
    p.bd.resolve(i, "timestamp probe resolution")
    closed = p.bd.get(i)
    if closed.closed_at is None:
        return Result(
            "timestamps.readable",
            False,
            f"closed_at missing (or unparseable) after closing {i!r} -- "
            f"throughput cannot be computed: raw closed_at="
            f"{closed.raw.get('closed_at')!r}",
        )
    return Result(
        "timestamps.readable",
        True,
        "created_at/updated_at/closed_at all round-trip as real datetimes",
    )


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
        A._run_bounded(["git", "init", "-q"], cwd=d, timeout=A._GIT_TIMEOUT_SECONDS)
        A._run_bounded(
            ["git", "commit", "-q", "--allow-empty", "-m", "i"],
            cwd=d,
            timeout=A._GIT_TIMEOUT_SECONDS,
        )
        init = A._run_bounded(
            ["bd", "init", "--prefix", "dotted.name", "--shared-server"],
            cwd=d,
            env=A._bd_env(),
            timeout=A._BD_INIT_TIMEOUT_SECONDS,
        )
        use = A._run_bounded(
            ["bd", "list", "--json"], env=A._bd_env({"BEADS_DIR": str(d / ".beads")})
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


def check_release_reopens_unresolved(p: Probe) -> Result:
    """`release()` must hand a HELD item back to the ready queue WITHOUT a
    resolution -- the behaviour the CLI `unclaim` verb depends on, and the
    single property that keeps it distinct from `resolve`/`close`.

    Two things are asserted together, because either one silently defeats
    `unclaim` on its own:
      1. after release the item is back to a claimable state (not 'held',
         not 'resolved') carrying NO resolution -- if release started
         attaching a resolution, `unclaim` would become a disguised close;
      2. a DIFFERENT actor can then claim it -- proving it genuinely
         returned to the ready queue, not merely had a status field flipped.
    """
    assert p.bd
    lane = "lane:release"
    p.bd.create("release probe", tags=[lane], priority=1)
    item = p.bd.claim_next(lane=lane, actor="holder_a")
    if item is None:
        return Result("release.reopens_unresolved", False, "could not claim the probe item")
    if item.status != "held":
        return Result(
            "release.reopens_unresolved",
            False,
            f"claim did not yield a held item (status {item.status!r})",
        )

    p.bd.release(item.id)

    back = p.bd.get(item.id)
    if back.status in ("held", "resolved"):
        return Result(
            "release.reopens_unresolved",
            False,
            f"release left the item {back.status!r}, not returned to the ready queue",
        )
    if back.resolution:
        return Result(
            "release.reopens_unresolved",
            False,
            f"release attached a resolution ({back.resolution!r}) -- it must reopen "
            f"WITHOUT one; that is what makes unclaim different from resolve",
        )

    taken = p.bd.claim_next(lane=lane, actor="holder_b")
    if taken is None or taken.id != item.id:
        return Result(
            "release.reopens_unresolved",
            False,
            "a different actor could not re-claim the released item -- it did not "
            "genuinely return to the ready queue",
        )
    return Result(
        "release.reopens_unresolved",
        True,
        "release reopens a held item with no resolution, and it is re-claimable",
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


def check_create_atomic_self_heals(p: Probe) -> Result:
    """A `create()` call that finds an ABANDONED previous attempt (a
    `.create.lock` naming a pid that is no longer alive) must self-heal --
    drop any residue and complete a fresh, verified-writable create in the
    SAME call -- rather than refusing forever.

    Pins the exact outage measured 2026-08-15: an external timeout killed
    `new` mid `bd init`. The process died before its own `finally:
    lock.unlink()` could run, so the lock outlived it, and every later
    `new` of the same name refused, PERMANENTLY, until an operator noticed
    and cleaned up by hand.

    Fabricates the abandoned state directly -- a real `.beads` directory
    with a lock naming pid `0` (never a live process) -- rather than
    actually racing a real `bd init` kill: deterministic and fast, matching
    this suite's own convention for custody's fresh-vs-stale checks
    (`check_custody_fresh_survives`/`check_custody_stale_reclaimed` forge
    timestamps rather than waiting for real time to pass).
    """
    name = f"{p.name}atomic"
    # Registered before ANY real creation happens below: from here on this
    # database is the probe's to drop no matter which branch returns.
    p.register_database(name)
    d = p.ws.path(name)
    (d / ".beads").mkdir(parents=True, exist_ok=True)
    (d / ".create.lock").write_text("0", encoding="utf-8")  # pid 0 -- never live here

    try:
        path = p.ws.create(name)
    except A.BeadsError as e:
        return Result(
            "project.create_atomic",
            False,
            f"create() did not self-heal an abandoned lock -- refused instead of recovering: {e}",
        )
    try:
        items = p.ws.project(name).list()
    except A.BeadsError as e:
        return Result(
            "project.create_atomic",
            False,
            f"create() reported success after healing but the project does not "
            f"actually answer: {e}",
        )
    if items:
        return Result(
            "project.create_atomic",
            False,
            f"healed project came back with {len(items)} item(s) -- expected a "
            f"genuinely fresh, empty project",
        )
    return Result(
        "project.create_atomic",
        True,
        f"an abandoned creation lock (dead pid) is healed automatically and create() "
        f"completes fresh in the same call; path={path}",
    )


def check_creation_state_reporting(p: Probe) -> Result:
    """`Workspace.creation_state` -- what `instances` consults BEFORE ever
    attempting `list()`, so it never reports a mid-creation or abandoned
    project as a blind "ok" -- must distinguish all three states: nothing
    in progress (None), a live creation lock ("creating"), and a dead-pid
    lock ("abandoned").

    Pins the exact outage measured 2026-08-15: `instances` printed
    `autonomous_work_pipeline  0  0  0  0  ok` for a project whose creation
    had been interrupted -- the lock was sitting right there, unconsulted.
    """
    name = f"{p.name}state"
    d = p.ws.path(name)
    (d / ".beads").mkdir(parents=True, exist_ok=True)
    lock = d / ".create.lock"

    try:
        state = p.ws.creation_state(name)
        if state is not None:
            return Result(
                "project.creation_state_reporting",
                False,
                f"a `.beads` dir with no lock at all was reported as {state!r} -- "
                f"expected None (nothing in progress)",
            )

        lock.write_text(str(os.getpid()), encoding="utf-8")  # our OWN pid -- guaranteed alive
        state = p.ws.creation_state(name)
        if state != "creating":
            return Result(
                "project.creation_state_reporting",
                False,
                f"a lock naming a LIVE pid was not reported as 'creating': {state!r}",
            )

        lock.write_text("0", encoding="utf-8")  # pid 0 -- never live here
        state = p.ws.creation_state(name)
        if state != "abandoned":
            return Result(
                "project.creation_state_reporting",
                False,
                f"a lock naming a DEAD pid was not reported as 'abandoned': {state!r}",
            )
    finally:
        shutil.rmtree(d, ignore_errors=True)

    return Result(
        "project.creation_state_reporting",
        True,
        "creation_state distinguishes none/creating/abandoned correctly",
    )


def _reopen_probe_item(p: Probe, lane: str, resolution: str) -> str:
    """A freshly created, resolved item for the reopen checks to work on."""
    assert p.bd
    i = p.bd.create(f"reopen probe ({lane})", tags=[lane], priority=1)
    p.bd.resolve(i, resolution)
    return i


def check_reopen_reopens(p: Probe) -> Result:
    """A resolved item can be returned to the queue and CLAIMED again.

    Asserted together, because either half alone is defeated silently: the
    status flipping back is worthless if the item never re-enters the ready
    queue, and this is the whole mechanism by which a wrong published
    resolution becomes correctable at all. `resolution.readable` already
    asserted a resolution is READABLE; nothing asserted it was
    CORRECTABLE, and that gap is why seven wrong resolutions shipped.
    """
    assert p.bd
    lane = "lane:reopen"
    item_id = _reopen_probe_item(p, lane, "probe first-pass resolution")
    try:
        p.bd.reopen(item_id, "probe correction")
    except A.BeadsError as e:
        return Result("reopen.reopens", False, f"reopen raised: {e}")
    back = p.bd.get(item_id)
    if back.status == "resolved":
        return Result(
            "reopen.reopens",
            False,
            f"reopen left the item {back.status!r} -- a published resolution "
            f"cannot be corrected at all",
        )
    if back.holder:
        # MEASURED: `bd reopen` leaves the OLD assignee in place, which makes
        # a directed claim by anyone else refuse ("already claimed by ..."),
        # so `Beads.reopen` clears it. If this fires, that clearing broke.
        return Result(
            "reopen.reopens",
            False,
            f"a reopened item is still assigned to {back.holder!r} -- nobody else "
            f"can claim it, so the correction path is closed by a stale name",
        )
    # A DIRECTED claim by a DIFFERENT actor: the strongest form, and the one
    # that actually fails when the stale assignee survives.
    try:
        taken = p.bd.claim_item(item_id, actor="reopen_probe_holder")
    except A.BeadsError as e:
        return Result(
            "reopen.reopens",
            False,
            f"a reopened item could not be claimed by another actor ({e}) -- it did "
            f"not genuinely return to the queue",
        )
    if taken.id != item_id:
        return Result("reopen.reopens", False, "directed claim returned a different item")
    return Result(
        "reopen.reopens",
        True,
        "a resolved item reopens unassigned and is directly claimable again",
    )


def check_reopen_clears_closed_at(p: Probe) -> Result:
    """Pins the ACCOUNTING side effect every throughput number depends on.

    `bd reopen` clears `closed_at`, so a corrected item stops counting
    toward the day it was genuinely resolved and re-lands on the correction
    date (`_velocity_raw_daily`, `_daily_resolved_counts`). That cost is
    documented and surfaced (`closed_at_cleared`), not hidden -- and if bd
    ever stops doing it, every one of those functions' honest caveats
    becomes wrong, silently. This is the alarm for that.
    """
    assert p.bd
    item_id = _reopen_probe_item(p, "lane:reopen_closed_at", "probe resolution for closed_at")
    before = p.bd.get(item_id)
    if before.closed_at is None:
        return Result(
            "reopen.clears_closed_at", False, "resolve did not set closed_at -- cannot measure"
        )
    try:
        outcome = p.bd.reopen(item_id, "probe correction")
    except A.BeadsError as e:
        return Result("reopen.clears_closed_at", False, f"reopen raised: {e}")
    if outcome.item.closed_at is not None:
        return Result(
            "reopen.clears_closed_at",
            False,
            f"closed_at survived a reopen ({outcome.item.closed_at!r}) -- bd changed "
            f"the accounting side effect that velocity/throughput reporting and "
            f"reopen's own documented cost both assume",
        )
    return Result(
        "reopen.clears_closed_at",
        True,
        "reopen clears closed_at (the documented, surfaced accounting cost)",
    )


def check_reopen_close_reason_disposition(p: Probe) -> Result:
    """What bd does to `close_reason` across a reopen -- MEASURED, pinned.

    bd 1.1.2 (20e493e56), measured 2026-09-02: a reopen CLEARS
    `close_reason`. The previous resolution text is GONE from the issue
    row. bd documents nothing either way, which is exactly why
    `Beads.reopen` archives the previous resolution into the item's
    attributed comment history BEFORE transitioning -- had the wrapper
    trusted bd to keep it, every correction would have destroyed the record
    it was correcting.

    The job of this assumption is the ALARM, not a preferred answer: it
    asserts what was measured on the day it was written, so a bd change
    breaks `doctor` loudly instead of quietly altering what a reopened item
    carries. If it fails, re-measure, then update this check AND
    `reopen`'s docstring deliberately.
    """
    assert p.bd
    text = "probe resolution measured for close_reason disposition"
    item_id = _reopen_probe_item(p, "lane:reopen_disposition", text)
    try:
        outcome = p.bd.reopen(item_id, "probe correction")
    except A.BeadsError as e:
        return Result("reopen.close_reason_disposition", False, f"reopen raised: {e}")
    if (outcome.item.resolution or "").strip():
        return Result(
            "reopen.close_reason_disposition",
            False,
            f"MEASURED bd 1.1.2 behaviour was: reopen CLEARS close_reason. It now "
            f"PRESERVES it ({outcome.item.resolution!r}). Not a wrapper failure "
            f"(reopen archives the old text in the comment history regardless), but "
            f"re-measure and update this assumption deliberately",
        )
    archived = [e.detail or e.summary for e in p.bd.activity(item_id) if e.kind == "comment"]
    if not any(text in (a or "") for a in archived):
        return Result(
            "reopen.close_reason_disposition",
            False,
            "the previous resolution is neither on the item NOR in its comment "
            "history -- the record was destroyed by the correction",
        )
    return Result(
        "reopen.close_reason_disposition",
        True,
        "reopen clears close_reason (measured), and the wrapper's archive comment "
        "preserves the previous resolution regardless",
    )


def check_reopen_emits_event(p: Probe) -> Result:
    """bd's own `events` row is one of the three independent audit records
    a correction leaves. If it silently stops being written, `reopened_count`
    (the \"reopened after resolve\" quality signal) reports zero forever and
    nobody can tell a corrected record from a first-pass one."""
    assert p.bd
    item_id = _reopen_probe_item(p, "lane:reopen_event", "probe resolution for event")
    try:
        p.bd.reopen(item_id, "probe correction reason")
    except A.BeadsError as e:
        return Result("reopen.emits_event", False, f"reopen raised: {e}")
    q = A._dolt_sql(
        f"SELECT COUNT(*) FROM `{p.bd.project_name}`.`events` "
        f"WHERE `issue_id` = '{A._sql_literal(item_id)}' AND `event_type` = 'reopened'"
    )
    if q.returncode != 0:
        return Result("reopen.emits_event", False, f"could not read events: {q.stderr or q.stdout}")
    rows = [ln for ln in (q.stdout or "").splitlines() if ln.strip()][1:]
    count = int(rows[0].strip()) if rows and rows[0].strip().isdigit() else 0
    if count < 1:
        return Result(
            "reopen.emits_event",
            False,
            "bd wrote no `reopened` events row -- the audit trail for corrections "
            "has silently stopped being written",
        )
    return Result("reopen.emits_event", True, "bd records a `reopened` events row, attributed")


def check_resolve_divergent_text_refused(p: Probe) -> Result:
    """THE regression fence for this whole defect.

    Resolving an already-closed item with text that DIFFERS from what is
    stored must raise and write nothing. Before the fix it exited 0 and
    echoed the OLD text back as if the correction had landed -- silent data
    loss on the one field users actually read.
    """
    assert p.bd
    stored = "probe: the original, wrong resolution"
    i = p.bd.create("resolve divergence probe", tags=["lane:probe_divergent"])
    p.bd.resolve(i, stored)
    try:
        p.bd.resolve(i, "probe: a completely different resolution")
    except A.BeadsError:
        back = p.bd.get(i)
        if (back.resolution or "").strip() != stored:
            return Result(
                "resolve.divergent_text_refused",
                False,
                f"refused, but the stored resolution changed anyway "
                f"({back.resolution!r}) -- 'NOTHING WAS WRITTEN' is not true",
            )
        return Result(
            "resolve.divergent_text_refused",
            True,
            "resolving a closed item with different text refuses and writes nothing",
        )
    return Result(
        "resolve.divergent_text_refused",
        False,
        "A DIVERGENT RESOLVE ON A CLOSED ITEM SUCCEEDED -- the caller's correction "
        "was silently discarded and they were told it landed",
    )


def check_resolve_identical_text_idempotent(p: Probe) -> Result:
    """The retry-safety carve-out, fenced in the other direction.

    The shipped contention contract tells agents that re-running `resolve`
    after an ambiguous failure is safe. A retry re-sends the identical
    string, so identical text must stay a success -- otherwise the fix
    above would break the promise it was made under.
    """
    assert p.bd
    text = "probe: the one true resolution"
    i = p.bd.create("resolve idempotency probe", tags=["lane:probe_idempotent"])
    p.bd.resolve(i, text)
    try:
        outcome = p.bd.resolve_outcome(i, text)
    except A.BeadsError as e:
        return Result(
            "resolve.identical_text_idempotent",
            False,
            f"re-sending the IDENTICAL resolution text failed ({e}) -- the "
            f"contention contract's retry-safety promise is broken",
        )
    if not outcome.idempotent:
        return Result(
            "resolve.identical_text_idempotent",
            False,
            "the identical-text retry succeeded but was not reported as idempotent "
            "-- a caller reconciling a contended run cannot tell 'landed earlier' "
            "from 'landed just now'",
        )
    return Result(
        "resolve.identical_text_idempotent",
        True,
        "re-sending identical resolution text is an idempotent success",
    )


def _refuses_resolved(p: Probe, *, verb: str, call, lane: str) -> Result:
    """Shared body for `defer.refuses_resolved` / `block.refuses_resolved`.

    Asserts all four properties the refusal promises, in the order that
    matters -- the LAST one is the one that actually protects a record:

      1. the call raises (it does not report success),
      2. the item is still `resolved`,
      3. its stored resolution is UNCHANGED, byte for byte,
      4. the refusal names the status and points at `reopen`.

    Property 3 is not implied by property 1: the measured defect
    (model_performance-2nx) is precisely a call that CHANGES the record.
    A guard that raised after writing would pass 1, 2 and 4 and still have
    destroyed the resolution.
    """
    assert p.bd
    stored = f"probe: the published {verb} resolution"
    i = p.bd.create(f"{verb}-on-resolved probe", tags=[lane])
    p.bd.resolve(i, stored)
    aid = f"{verb}.refuses_resolved"
    try:
        call(p.bd, i)
    except A.BeadsError as e:
        back = p.bd.get(i)
        if back.status != "resolved":
            return Result(
                aid,
                False,
                f"refused, but the item is now {back.status!r} -- the transition it "
                f"refused happened anyway",
            )
        if (back.resolution or "").strip() != stored:
            return Result(
                aid,
                False,
                f"refused, but the stored resolution changed anyway "
                f"({back.resolution!r}) -- 'NOTHING WAS WRITTEN' is not true",
            )
        msg = str(e)
        if "resolved" not in msg or "reopen" not in msg:
            return Result(
                aid,
                False,
                f"refused and wrote nothing, but the message names neither the "
                f"item's status nor the `reopen` remedy: {msg[:200]!r}",
            )
        return Result(
            aid,
            True,
            f"{verb} on a resolved item refuses, writes nothing, and names `reopen`",
        )
    back = p.bd.get(i)
    return Result(
        aid,
        False,
        f"A {verb.upper()} ON A RESOLVED ITEM SUCCEEDED -- the item is now "
        f"{back.status!r} with resolution {back.resolution!r}; the official record "
        f"was rewritten with no warning and no archive",
    )


def check_defer_refuses_resolved(p: Probe) -> Result:
    """`defer` must not be an unaudited, destructive reopen.

    MEASURED before the guard (bd 1.1.2, 2026-09-03): `defer` on a resolved
    item exited 0, moved it to `deferred`, and left `resolution: None` --
    the already-published text gone, with no archive of what it said. The
    remaining loop (`--clear` -> claim -> resolve) then rewrote the record
    end to end using nothing but sanctioned verbs.

    This is the regression fence for that. See also
    `reopen.close_reason_disposition`, which pins the bd-side behaviour
    (a status change away from closed CLEARS `close_reason`) that makes
    this destructive rather than merely surprising.
    """
    return _refuses_resolved(
        p,
        verb="defer",
        call=lambda bd, i: bd.defer(i, "probe: should never land"),
        lane="lane:probe_defer_resolved",
    )


def check_block_refuses_resolved(p: Probe) -> Result:
    """The same fence on `block` -- asserted separately, on purpose.

    The two verbs share one implementation today, and a check of only one
    of them would pass forever if a future change gave `block` its own
    path. Both doors, both asserted.
    """
    return _refuses_resolved(
        p,
        verb="block",
        call=lambda bd, i: bd.block(i, "probe: should never land"),
        lane="lane:probe_block_resolved",
    )


_TRANSPORT_FAILURE_STDERR = (
    "failed to load database names: lstat /tmp/probe_vanished.sig: no such file or directory"
)


def check_unavailable_not_absent(p: Probe) -> Result:
    """An infrastructure read failure must NEVER surface as "not found".

    THE regression fence for lane `model_performance-8zv`. Measured before
    the fix (lane `model_performance-rpz`, harness
    `probes/rpz-dolt-error-misreport/repro.sh`): with the `dolt` client
    losing a race against its own churning working directory, `claim --id`
    on an item that EXISTS reported "item not found" in 9 of 12 attempts,
    and `list --id` on an item the calling session HELD reported a bare
    "item 'X' not found in project 'Y'" -- cause discarded entirely -- in 2
    of 8. An agent following this project's own contention contract
    (`context/awareness.md` hazard #6: re-read the item first) was told its
    held item did not exist.

    Fenced in BOTH directions, because half a fix is a different lie:

      1. UNDER a transport failure, on a REAL item: `get_readonly` and
         `claim_item` must raise `A.BeadsUnavailableError` and must not
         claim absence.
      2. On a HEALTHY database, a genuinely absent item must still report
         plain absence, in the same words as before -- no "maybe
         transient" hedge anywhere near it.

    The transport failure is INJECTED (`_dolt_sql`/`_dolt_sql_json`
    temporarily replaced with one that returns dolt's real wording at
    returncode 1) rather than provoked by churning a directory: this check
    runs inside `doctor` on operators' machines, and a check that
    manufactures a filesystem race to prove a point is a check that
    occasionally breaks something else. Injecting at the helper also puts
    the failure PAST `_run_dolt_sql_bounded`'s retry budget, which is the
    condition the deliverable actually names. Everything above the helper
    -- classification, the type, all three call sites -- is exercised for
    real. Restored in a `finally`, so a failure here cannot leave the
    process's SQL path patched.
    """
    assert p.bd
    real_id = p.bd.create("unavailable-vs-absent probe", tags=["lane:probe_unavailable"])
    absent_id = f"{p.name}-nosuchitem"

    # --- 2. HEALTHY database first: capture today's real absence wording,
    # so direction (2) is asserted against observed behaviour rather than a
    # string this check hard-codes and could drift from.
    try:
        p.bd.get_readonly(absent_id)
        return Result(
            "read.unavailable_not_absent",
            False,
            f"a genuinely absent item {absent_id!r} was READ successfully -- the probe "
            f"cannot distinguish anything if absence itself is not reported",
        )
    except A.BeadsUnavailableError as e:
        return Result(
            "read.unavailable_not_absent",
            False,
            f"a genuinely absent item on a HEALTHY database reported UNAVAILABLE ({e}) "
            f"-- real absence has been blurred into 'maybe transient', which replaces "
            f"one lie with another",
        )
    except A.BeadsError as e:
        healthy_absence = str(e)
    if "not found" not in healthy_absence.lower():
        return Result(
            "read.unavailable_not_absent",
            False,
            f"absence on a healthy database no longer reads as 'not found' "
            f"({healthy_absence!r}) -- the two conditions can no longer be told apart",
        )

    # --- 1. Now the transport failure, against an item that EXISTS.
    def _fail(*_a, **_k):
        return subprocess.CompletedProcess(["dolt"], 1, "", _TRANSPORT_FAILURE_STDERR)

    real_sql, real_sql_json = A._dolt_sql, A._dolt_sql_json
    A._dolt_sql, A._dolt_sql_json = _fail, _fail
    try:
        try:
            p.bd.get_readonly(real_id)
            return Result(
                "read.unavailable_not_absent",
                False,
                "an unreachable database returned an item anyway -- the injection did "
                "not reach the read path, so this check proves nothing",
            )
        except A.BeadsUnavailableError as e:
            if "not found" in str(e).lower():
                return Result(
                    "read.unavailable_not_absent",
                    False,
                    f"`get_readonly` raised the right TYPE but still says 'not found' "
                    f"({e}) -- a caller reading the message is still lied to",
                )
            if "failed to load database names" not in str(e):
                return Result(
                    "read.unavailable_not_absent",
                    False,
                    f"`get_readonly` discarded the underlying cause ({e}) -- this is the "
                    f"exact path the contention contract tells agents to trust",
                )
        except A.BeadsError as e:
            return Result(
                "read.unavailable_not_absent",
                False,
                f"AN INFRASTRUCTURE READ FAILURE SURFACED AS A PLAIN BeadsError ({e}) -- "
                f"`list --id` on an existing item denies its existence again",
            )

        try:
            p.bd.claim_item(real_id, actor="probe-unavailable")
            return Result(
                "read.unavailable_not_absent",
                False,
                "an unreachable database CLAIMED an item anyway -- the injection did not "
                "reach the claim path",
            )
        except A.BeadsUnavailableError as e:
            if "item not found" in str(e).lower():
                return Result(
                    "read.unavailable_not_absent",
                    False,
                    f"`claim_item` still reports 'item not found' under an infrastructure "
                    f"failure ({e})",
                )
        except A.BeadsError as e:
            return Result(
                "read.unavailable_not_absent",
                False,
                f"`claim_item` flattened an infrastructure failure into a plain "
                f"BeadsError ({e}) -- 9 of 12 measured attempts said 'item not found' "
                f"about an item that existed",
            )

        summary = A.project_summary(p.ws, p.name)
        if not A.is_unavailable_status(summary.status):
            return Result(
                "read.unavailable_not_absent",
                False,
                f"`project_summary` reported {summary.status!r} for an UNREACHABLE "
                f"database -- `instances` asserts the project's data is unreadable when "
                f"only the connection failed",
            )
    finally:
        A._dolt_sql, A._dolt_sql_json = real_sql, real_sql_json

    return Result(
        "read.unavailable_not_absent",
        True,
        "an infrastructure read failure raises BeadsUnavailableError with its cause "
        "intact on read/claim and reports UNAVAILABLE (not ERROR) per project, while "
        "genuine absence on a healthy database still reports plain 'not found'",
    )


CHECKS = [
    ("capabilities", check_capabilities),
    ("read.unavailable_not_absent", check_unavailable_not_absent),
    ("resolve.fenced", check_resolve_fenced),
    ("resolve.divergent_text_refused", check_resolve_divergent_text_refused),
    ("resolve.identical_text_idempotent", check_resolve_identical_text_idempotent),
    ("reopen.reopens", check_reopen_reopens),
    ("reopen.clears_closed_at", check_reopen_clears_closed_at),
    ("reopen.close_reason_disposition", check_reopen_close_reason_disposition),
    ("reopen.emits_event", check_reopen_emits_event),
    ("defer.refuses_resolved", check_defer_refuses_resolved),
    ("block.refuses_resolved", check_block_refuses_resolved),
    ("release.reopens_unresolved", check_release_reopens_unresolved),
    ("claim.subcommand", check_claim_subcommand),
    ("claim.atomic", check_claim_atomic),
    ("claim.directed_atomic", check_claim_directed_atomic),
    ("link.nonblocking", check_link_nonblocking),
    ("list.includes_closed", check_list_includes_closed),
    ("list.status_filter_includes_closed", check_list_status_filter_includes_closed),
    ("show.dependents", check_show_dependents),
    ("read.no_mutation", check_read_no_mutation),
    ("resolution.readable", check_resolution_readable),
    ("timestamps.readable", check_timestamps_readable),
    ("metadata.roundtrip", check_metadata_roundtrip),
    ("project.name_rules", check_name_rules),
    ("custody.fresh_survives", check_custody_fresh_survives),
    ("custody.stale_reclaimed", check_custody_stale_reclaimed),
    ("custody.idle_not_exempt", check_custody_idle_not_exempt),
    ("custody.fenced", check_custody_fenced),
    ("project.removal", check_project_removal),
    ("project.create_atomic", check_create_atomic_self_heals),
    ("project.creation_state_reporting", check_creation_state_reporting),
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
