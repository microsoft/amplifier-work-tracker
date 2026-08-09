"""The ONLY module in amplifier-work-tracker that knows Beads exists.

Everything above this file speaks our vocabulary (Report, WorkItem, claim,
resolve). Everything below is `bd` CLI invocations and Beads' JSON field
names. When Beads changes, this file changes and nothing else does.

Coupling budget -- every assumption we make about Beads is declared here as a
named ASSUMPTION and verified live by `amplifier_work_tracker.contract`. Nothing
else in the codebase is allowed to encode a Beads behaviour. If you find
yourself typing "bd " anywhere outside this file, stop: the seam is leaking.

Why a seam at all: Beads is moving fast (repo HEAD is >1100 commits past the
latest tag, and the claim/lease code is mid-rewrite upstream). We want its
improvements without its churn reaching our domain logic.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import custody as C

# --------------------------------------------------------------------------
# Version window. We refuse outside it rather than guess.
# --------------------------------------------------------------------------

MIN_VERSION = (1, 1, 2)  # `bd ready --claim` first usable; below this the
# only claim path available double-claims.
MAX_TESTED = (1, 1, 2)  # Highest version our contract suite has passed on.
# Above this we WARN (not fail) -- new Beads is
# allowed, but `amplifier-work-tracker doctor` is how you clear it.

# --------------------------------------------------------------------------
# Declared assumptions. `amplifier_work_tracker.contract` proves each of these
# against the live binary. The ids are stable so a failure names exactly what
# broke.
# --------------------------------------------------------------------------

ASSUMPTIONS = {
    "claim.atomic": "Concurrent `ready --claim` yields at most one winner per item",
    "claim.subcommand": "`ready --claim` exists and does not accept --assignee",
    "claim.actor_env": "Claim identity comes from the BEADS_ACTOR environment variable",
    "link.nonblocking": "A `discovered-from` link does not block the linked item",
    "list.includes_closed": "Listing with the all-flag includes closed items",
    "show.dependents": "Reverse links require an explicit include-dependents flag",
    "resolution.readable": "An item's resolution text is readable after it is closed",
    "metadata.roundtrip": "Arbitrary JSON metadata survives a write/read cycle",
    "project.name_rules": "Project names with dots produce an unusable database",
    "conflict.retryable": "Write conflicts surface as retryable serialization errors",
}

# --------------------------------------------------------------------------
# Field mapping. Beads' names on the left, ours on the right. One place.
# --------------------------------------------------------------------------

_FIELD_MAP = {
    "id": "id",
    "title": "title",
    "status": "status",
    "assignee": "holder",
    "issue_type": "kind",
    "close_reason": "resolution",
    "acceptance_criteria": "acceptance",
    "description": "description",
    "design": "design",
    "labels": "tags",
    "metadata": "meta",
    "priority": "priority",
}

# Our domain statuses, mapped from Beads'. Unknown values pass through rather
# than being coerced -- a new Beads status must not silently look like an old one.
_STATUS_MAP = {
    "open": "open",
    "in_progress": "held",
    "closed": "resolved",
    "blocked": "blocked",
    "deferred": "deferred",
}

LANE_INTAKE = "lane:intake"
LANE_WORK = "lane:eng"
LINK_DISCOVERED_FROM = "discovered-from"

# Dolt raises these when two writers touch one row. Beads manufactures the
# collision deliberately so claims serialize. Retrying is the documented,
# expected response -- not a fallback masking a failure.
_RETRYABLE = ("1213", "1205", "serialization failure", "try restarting transaction")
_MAX_RETRIES = 8
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class BeadsError(Exception):
    """A Beads operation failed. Never caught to degrade -- only to report."""


class AssumptionViolated(BeadsError):
    """The installed Beads no longer behaves the way we depend on."""


@dataclass
class Item:
    """One unit of work or one user report, in OUR vocabulary."""

    id: str
    title: str = ""
    status: str = "open"
    holder: str | None = None
    kind: str = "task"
    resolution: str | None = None
    acceptance: str | None = None
    description: str | None = None
    design: str | None = None
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    priority: int | None = None
    links: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_beads(cls, d: dict) -> Item:
        out = {}
        for their, ours in _FIELD_MAP.items():
            if their in d:
                out[ours] = d[their]
        out["status"] = _STATUS_MAP.get(d.get("status", ""), d.get("status", "unknown"))
        out.setdefault("tags", [])
        out.setdefault("meta", {})
        out["tags"] = out.get("tags") or []
        out["meta"] = out.get("meta") or {}
        out["id"] = d.get("id", "")
        return cls(**{k: v for k, v in out.items() if k in cls.__dataclass_fields__}, raw=d)


def _retryable(blob: str) -> bool:
    low = blob.lower()
    return any(t.lower() in low for t in _RETRYABLE)


class Beads:
    """A handle on one Beads project. Construct via Workspace.project()."""

    def __init__(self, beads_dir: Path, actor: str | None = None):
        self._dir = Path(beads_dir)
        self._actor = actor

    # ---------------------------------------------------------------- plumbing

    def _env(self, actor: str | None = None) -> dict:
        e = dict(os.environ)
        e["BEADS_DIR"] = str(self._dir)
        a = actor or self._actor
        if a:
            e["BEADS_ACTOR"] = a
        return e

    def _run(self, args: list[str], actor: str | None = None) -> subprocess.CompletedProcess:
        last = None
        for attempt in range(_MAX_RETRIES):
            p = subprocess.run(
                ["bd", *args],
                capture_output=True,
                text=True,
                env=self._env(actor),
                check=False,
            )
            last = p
            if _retryable((p.stdout or "") + (p.stderr or "")):
                time.sleep(0.15 * (2**attempt) * (0.5 + os.urandom(1)[0] / 255))
                continue
            return p
        raise BeadsError(
            f"`bd {' '.join(args[:2])}` still conflicting after {_MAX_RETRIES} retries. "
            f"Contention too high; refusing to keep hammering. "
            f"Last: {((last.stderr or last.stdout) if last else '')[:200]}"
        )

    def _json(self, args: list[str], actor: str | None = None):
        p = self._run([*args, "--json"], actor=actor)
        out = (p.stdout or "").strip()
        if not out:
            if p.returncode != 0:
                raise BeadsError(f"`bd {' '.join(args[:2])}`: {(p.stderr or '').strip()[:300]}")
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise BeadsError(f"`bd {' '.join(args[:2])}` returned non-JSON: {out[:200]}") from e
        if isinstance(data, dict) and data.get("error"):
            raise BeadsError(f"`bd {' '.join(args[:2])}`: {data['error']}")
        return data

    # ---------------------------------------------------------------- domain ops

    def create(
        self,
        title: str,
        *,
        kind: str = "task",
        priority: int = 2,
        tags: list[str] | None = None,
        meta: dict | None = None,
        description: str | None = None,
        acceptance: str | None = None,
        design: str | None = None,
        discovered_from: list[str] | None = None,
        actor: str | None = None,
    ) -> str:
        args = ["create", title, "-t", kind, "-p", str(priority)]
        if tags:
            args += ["-l", ",".join(tags)]
        if meta:
            args += ["--metadata", json.dumps(meta)]
        if description:
            args += ["--description", description]
        if acceptance:
            args += ["--acceptance", acceptance]
        if design:
            args += ["--design", design]
        if discovered_from:
            args += [
                "--deps",
                ",".join(f"{LINK_DISCOVERED_FROM}:{i}" for i in discovered_from),
            ]
        args += ["--silent"]
        p = self._run(args, actor=actor)
        new_id = (p.stdout or "").strip().splitlines()[-1].strip() if p.stdout else ""
        if p.returncode != 0 or not new_id:
            raise BeadsError(f"create failed: {(p.stderr or p.stdout).strip()[:300]}")
        return new_id

    def claim_next(self, *, lane: str = LANE_WORK, actor: str) -> Item | None:
        """THE claim. Single atomic operation, never read-then-write.

        ASSUMPTION claim.atomic / claim.subcommand / claim.actor_env.
        Identity travels in BEADS_ACTOR because this subcommand rejects an
        explicit assignee flag.
        """
        data = self._json(["ready", "--label", lane, "--claim"], actor=actor)
        items = data if isinstance(data, list) else ([data] if data else [])
        items = [i for i in items if isinstance(i, dict) and i.get("id")]
        return Item.from_beads(items[0]) if items else None

    def get(self, item_id: str, *, with_links: bool = False) -> Item:
        args = ["show", item_id]
        if with_links:
            # ASSUMPTION show.dependents -- reverse links are omitted by default.
            args += ["--include-dependents"]
        d = self._json(args)
        d = d[0] if isinstance(d, list) else d
        if not isinstance(d, dict):
            raise BeadsError(f"show {item_id} returned no object")
        it = Item.from_beads(d)
        it.links = [
            {"id": x.get("id"), "direction": "from", "type": x.get("dependency_type")}
            for x in (d.get("dependencies") or [])
        ] + [
            {"id": x.get("id"), "direction": "to", "type": x.get("dependency_type")}
            for x in (d.get("dependents") or [])
        ]
        return it

    def list(self, *, lane: str | None = None, include_resolved: bool = False) -> list[Item]:
        args = ["list"]
        if include_resolved:
            # ASSUMPTION list.includes_closed -- without this a resolved report
            # vanishes exactly when its answer is ready.
            args += ["--all"]
        if lane:
            args += ["--label", lane]
        data = self._json(args) or []
        return [Item.from_beads(d) for d in data if isinstance(d, dict)]

    def resolve(self, item_id: str, reason: str, *, actor: str | None = None) -> Item:
        """Close an item and VERIFY the write landed. Exit code is not proof.

        FENCED: refuses if we are not the current holder. Without this a zombie
        agent whose claim was reclaimed can still close work it no longer owns,
        and every party gets exit 0 -- the same silent shape as the double-claim
        we banned the two-step path for.

        Two fence sources, checked together, because they cover different
        gaps: bd's own assignee catches a live takeover by another holder
        (assignee is now someone else). It does NOT catch our own
        custody-based reclaim, because reclaiming an item clears bd's
        assignee back to empty rather than reassigning it -- measured: a
        stale holder's resolve on a released-but-not-yet-reclaimed item sailed
        through with exit 0 because "no current holder" looked the same as
        "never held at all." A custody record, once it exists, is left in
        place across a reclaim precisely so it can still answer "who held
        this last" -- so when one exists, it is authoritative over bd's own
        (now-cleared) assignee field.
        """
        who = actor or self._actor
        if who:
            current = self.get(item_id)
            cust = current.meta.get(C.CUSTODY_KEY) if isinstance(current.meta, dict) else None
            if isinstance(cust, dict) and cust.get("holder"):
                if current.holder != who or cust.get("holder") != who:
                    raise BeadsError(
                        f"refusing to close {item_id}: current holder is "
                        f"{current.holder!r} (custody holder {cust.get('holder')!r}), "
                        f"not {who!r}. Your claim was reclaimed while you were away."
                    )
            elif current.status == "held" and current.holder and current.holder != who:
                raise BeadsError(
                    f"refusing to close {item_id}: it is held by {current.holder!r}, "
                    f"not {who!r}. Your claim was reclaimed while you were away."
                )
        p = self._run(["close", item_id, "--reason", reason], actor=actor)
        if p.returncode != 0:
            raise BeadsError(f"close {item_id}: {(p.stderr or p.stdout).strip()[:300]}")
        back = self.get(item_id)
        if back.status != "resolved":
            raise BeadsError(
                f"close {item_id} reported success but readback shows status="
                f"{back.status!r} -- refusing to report success"
            )
        return back

    def release(self, item_id: str) -> None:
        """Hand a held item back to the queue."""
        p = self._run(["update", item_id, "--status", "open", "--assignee", ""])
        if p.returncode != 0:
            raise BeadsError(f"release {item_id}: {(p.stderr or p.stdout).strip()[:200]}")

    # ------------------------------------------------------------------ custody
    #
    # Liveness for a held item is entirely ours (see amplifier_work_tracker.custody
    # for why: bd's leases are node-local and never replicate, and `bd
    # heartbeat` / `bd reclaim` do not exist in this release). The record lives
    # under the item's own `metadata["custody"]` key, so it replicates with the
    # item. `bd update --metadata` merges at the top level (verified
    # empirically: writing one key leaves sibling metadata keys untouched),
    # which is what lets us replace the whole custody record atomically without
    # disturbing unrelated metadata like `reporter_id`.

    def get_custody(self, item_id: str) -> dict | None:
        """Read the current custody record, or None if the item has none."""
        d = self.get(item_id).meta.get(C.CUSTODY_KEY)
        return d if isinstance(d, dict) else None

    def take_custody(
        self,
        item_id: str,
        *,
        holder: str,
        pid: int,
        host: str,
        declared_state: str = C.STATE_WORKING,
    ) -> dict:
        """Establish (or re-establish) custody of an item you already hold.

        Generation always increases past whatever was there before, so a
        resurrected zombie's old generation number can never match again once
        someone else has taken custody.

        FENCED: refuses unless `holder` is currently bd's own assignee for
        this item -- you cannot take custody of work you do not actually hold.
        """
        it = self.get(item_id)
        if it.holder != holder:
            raise BeadsError(
                f"cannot take custody of {item_id}: bd assignee is "
                f"{it.holder!r}, not {holder!r}. Claim it first "
                f"(`bd ready --claim`)."
            )
        prior = it.meta.get(C.CUSTODY_KEY)
        gen = (int(prior.get("generation", 0)) + 1) if isinstance(prior, dict) else 1
        now = C.now_iso()
        record = {
            "holder": holder,
            "pid": int(pid),
            "host": host,
            "started_at": now,
            "last_seen": now,
            "declared_state": declared_state,
            "declared_since": now,
            "generation": gen,
        }
        p = self._run(
            ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: record})],
            actor=holder,
        )
        if p.returncode != 0:
            raise BeadsError(f"take_custody {item_id}: {(p.stderr or p.stdout).strip()[:200]}")
        back = self.get_custody(item_id)
        if back != record:
            raise BeadsError(
                f"take_custody {item_id} reported success but readback shows "
                f"{back!r} -- refusing to report success"
            )
        return record

    def renew_custody(
        self,
        item_id: str,
        *,
        holder: str,
        generation: int,
        pid: int,
        declared_state: str | None = None,
    ) -> dict:
        """Extend last_seen on an existing custody record.

        FENCED on holder+generation, and -- in defense-in-depth -- on bd's own
        assignee too. A claim that was taken over while you were away must
        not be renewable by you; without this, a zombie's renewal would keep
        an item that no longer belongs to it looking alive forever.
        """
        it = self.get(item_id)
        current = it.meta.get(C.CUSTODY_KEY)
        if not isinstance(current, dict):
            raise BeadsError(
                f"cannot renew custody on {item_id}: no custody record exists "
                f"-- call take_custody first"
            )
        if current.get("holder") != holder or int(current.get("generation", -1)) != generation:
            raise BeadsError(
                f"refusing to renew custody on {item_id}: current holder is "
                f"{current.get('holder')!r} generation {current.get('generation')}, "
                f"caller is {holder!r} generation {generation}. Your custody "
                f"was taken over while you were away."
            )
        if it.holder != holder:
            raise BeadsError(
                f"refusing to renew custody on {item_id}: bd assignee is "
                f"{it.holder!r}, not {holder!r} -- claim was reassigned"
            )
        updated = dict(current)
        updated["last_seen"] = C.now_iso()
        updated["pid"] = int(pid)
        if declared_state and declared_state != current.get("declared_state"):
            updated["declared_state"] = declared_state
            updated["declared_since"] = updated["last_seen"]
        p = self._run(
            ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: updated})],
            actor=holder,
        )
        if p.returncode != 0:
            raise BeadsError(f"renew_custody {item_id}: {(p.stderr or p.stdout).strip()[:200]}")
        back = self.get_custody(item_id)
        if back != updated:
            raise BeadsError(
                f"renew_custody {item_id} reported success but readback shows "
                f"{back!r} -- refusing to report success"
            )
        return updated


class Workspace:
    """Many named projects, one shared server.

    We do NOT manage ports or server processes. Beads already hosts N named
    databases on one shared server; reproducing that would be duplicated
    machinery we'd then have to keep in sync with theirs.
    """

    def __init__(self, root: Path | None = None):
        default_root = Path.home() / ".amplifier-work-tracker"
        self.root = Path(root or os.environ.get("AMPLIFIER_WORK_TRACKER_ROOT", default_root))
        self.projects_dir = self.root / "projects"

    def names(self) -> list[str]:
        if not self.projects_dir.is_dir():
            return []
        return sorted(p.name for p in self.projects_dir.iterdir() if (p / ".beads").is_dir())

    def path(self, name: str) -> Path:
        return self.projects_dir / name

    def project(self, name: str, actor: str | None = None) -> Beads:
        d = self.path(name) / ".beads"
        if not d.is_dir():
            raise BeadsError(f"project {name!r} not found at {d}. Create it first.")
        return Beads(d, actor=actor)

    def create(self, name: str) -> Path:
        """Create a project. Name rules and post-init verification are ours.

        ASSUMPTION project.name_rules -- a dotted name yields an unusable
        database while `bd init` still reports success, so we reject early and
        then prove the database actually answers before saying it worked.
        """
        if not NAME_RE.match(name):
            raise BeadsError(
                f"invalid project name {name!r}: must match {NAME_RE.pattern}. "
                f"Dots are rejected deliberately -- they produce a database that "
                f"reports successful creation and then fails every later command."
            )
        d = self.path(name)
        if (d / ".beads").is_dir():
            return d
        d.mkdir(parents=True, exist_ok=True)
        lock = d / ".create.lock"
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError as e:
            raise BeadsError(f"project {name!r} is already being created (lock: {lock})") from e
        try:
            if not (d / ".git").is_dir():
                subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True, check=False)
                subprocess.run(
                    ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                    cwd=d,
                    capture_output=True,
                    check=False,
                )
            p = subprocess.run(
                ["bd", "init", "--prefix", name, "--shared-server"],
                cwd=d,
                capture_output=True,
                text=True,
                check=False,
            )
            if p.returncode != 0:
                raise BeadsError(f"bd init failed: {(p.stderr or p.stdout)[:300]}")
            self.project(name).list()  # prove it actually answers
            return d
        finally:
            lock.unlink(missing_ok=True)


_CAPS: dict[str, bool] | None = None


def capabilities() -> dict[str, bool]:
    """Which bd subcommands actually exist in the installed binary.

    Learned the hard way: `bd heartbeat` and `bd reclaim` appear in the Beads
    repo source but are ABSENT from the v1.1.2 release. Code written against
    the source tree calls commands that do not exist. We probe instead of
    assuming, and callers must check before depending on a primitive.
    """
    global _CAPS
    if _CAPS is None:
        _CAPS = {}
        for cmd in (
            "ready",
            "create",
            "show",
            "list",
            "close",
            "update",
            "heartbeat",
            "reclaim",
            "gate",
            "dep",
        ):
            r = subprocess.run(["bd", cmd, "--help"], capture_output=True, text=True, check=False)
            blob = (r.stdout or "") + (r.stderr or "")
            _CAPS[cmd] = "unknown command" not in blob
    return dict(_CAPS)


def version() -> tuple[int, int, int]:
    p = subprocess.run(["bd", "--version"], capture_output=True, text=True, check=False)
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", p.stdout or "")
    if not m:
        raise BeadsError(f"cannot read bd version: {(p.stdout or p.stderr)[:120]}")
    return tuple(int(x) for x in m.groups())  # type: ignore


def check_version() -> tuple[tuple[int, int, int], str | None]:
    """Return (version, warning). Raises below the floor, warns above tested."""
    v = version()
    if v < MIN_VERSION:
        raise AssumptionViolated(
            f"bd {'.'.join(map(str, v))} is below the supported floor "
            f"{'.'.join(map(str, MIN_VERSION))}. Older builds lack `ready --claim`, "
            f"leaving only a claim path that double-claims under contention."
        )
    if v > MAX_TESTED:
        return v, (
            f"bd {'.'.join(map(str, v))} is newer than the last version our "
            f"contract suite passed on ({'.'.join(map(str, MAX_TESTED))}). "
            f"Run `amplifier-work-tracker doctor` to re-verify our assumptions."
        )
    return v, None
