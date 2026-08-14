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
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import custody as C

logger = logging.getLogger(__name__)

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
    "claim.directed_atomic": (
        "Concurrent `update <id> --claim` on the SAME item yields at most one winner"
    ),
    "claim.subcommand": "`ready --claim` exists and does not accept --assignee",
    "claim.actor_env": "Claim identity comes from the BEADS_ACTOR environment variable",
    "link.nonblocking": "A `discovered-from` link does not block the linked item",
    "list.includes_closed": "Listing with the all-flag includes closed items",
    "list.status_filter_includes_closed": (
        "Filtering `list` by an explicit --status shows closed items without needing --all"
    ),
    "show.dependents": "Reverse links require an explicit include-dependents flag",
    "read.no_mutation": "`bd show` never mutates the item it reads, no matter how many times",
    "resolution.readable": "An item's resolution text is readable after it is closed",
    "metadata.roundtrip": "Arbitrary JSON metadata survives a write/read cycle",
    "project.name_rules": "Project names with dots produce an unusable database",
    "conflict.retryable": "Write conflicts surface as retryable serialization errors",
    "timestamps.readable": (
        "created_at/updated_at/closed_at survive from bd's own `show --json` into "
        "our Item, parsed as real datetimes -- not merely present on the raw payload"
    ),
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

# Reverse of the above -- our vocabulary back to Beads' `--status` values, for
# filtering `list()`. A bijection (every value in _STATUS_MAP is distinct), so
# this is exact, not an approximation.
_STATUS_MAP_REVERSE = {ours: theirs for theirs, ours in _STATUS_MAP.items()}

# Public -- the valid `status` values for `list()`/`list_bounded()`, for
# callers (the CLI's `--status` choices, the `work_list` tool's input schema)
# that need the vocabulary without reaching into the private reverse map.
STATUSES = tuple(sorted(_STATUS_MAP_REVERSE))

# Bounds for `Beads.list_bounded` -- shared by the CLI and the agent tool so
# neither reinvents (or silently disagrees on) the default/max. See its
# docstring: the cap is always reported explicitly, never silent.
LIST_DEFAULT_LIMIT = 50
LIST_MAX_LIMIT = 500

LANE_INTAKE = "lane:intake"
LANE_WORK = "lane:eng"
LINK_DISCOVERED_FROM = "discovered-from"

# Dolt raises these when two writers touch one row. Beads manufactures the
# collision deliberately so claims serialize. Retrying is the documented,
# expected response -- not a fallback masking a failure.
_RETRYABLE = ("1213", "1205", "serialization failure", "try restarting transaction")
_MAX_RETRIES = 8
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

# --------------------------------------------------------------------------
# Subprocess timeouts -- every `bd`/`dolt`/`git` call this module makes goes
# through `_run_bounded` (below), never a bare `subprocess.run` with no
# `timeout`. Measured outage, 2026-08-15: `amplifier-work-tracker doctor`
# hung past its caller's own EXTERNAL timeout and left two `bd` processes
# running afterward as orphans, because nothing in this module bounded its
# own subprocess calls -- the only thing standing between "slow" and
# "hangs forever" was whatever killed the CALLER, which cannot also clean
# up a grandchild process `bd` itself spawned (see `_run_bounded`'s
# docstring for why a bare `subprocess.run(timeout=...)` is not enough).
#
# `_BD_INIT_TIMEOUT_SECONDS` is deliberately much larger than
# `_DEFAULT_BD_TIMEOUT_SECONDS`: a real, eventually-SUCCESSFUL `bd init`
# was measured taking up to 178s (attaching to / spawning the shared dolt
# server under load) -- bounding it at the same figure as a plain `bd
# list`/`bd show` would turn real (if unwelcome) slowness into a false
# failure. `tests/conftest.py`'s own `run_cli` fixture already treats 240s
# as the outer bound of a legitimate CLI invocation; reused here rather
# than inventing a second figure.
_DEFAULT_BD_TIMEOUT_SECONDS = 60.0
_BD_INIT_TIMEOUT_SECONDS = 240.0
_GIT_TIMEOUT_SECONDS = 30.0


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Terminate *proc* and every process in its OWN process group -- reaches
    grandchildren a bare `proc.kill()` leaves orphaned (e.g. a dolt
    sql-server `bd --shared-server` spawned as ITS OWN child). Requires the
    process to have been started with `start_new_session=True` (see
    `_run_bounded`) so it has a process group distinct from ours to kill.

    Best-effort: a group that is already gone (`ProcessLookupError`) is not
    a failure -- the process may have exited on its own between the
    timeout firing and this call running.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_bounded(
    args: list[str],
    *,
    env: dict | None = None,
    cwd: Path | str | None = None,
    timeout: float = _DEFAULT_BD_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run *args* with a hard wall-clock bound, and -- unlike a bare
    `subprocess.run(..., timeout=...)` -- make sure nothing the child
    spawned survives the timeout as an orphan.

    This is THE call site for every `bd`/`dolt`/`git` subprocess invocation
    in this module (and, via `contract._run_bounded` re-exported access, in
    the contract suite too) -- see this module's own docstring on why a
    single seam matters, and the timeout-constants comment above for the
    outage this closes.

    A bare `subprocess.run(timeout=...)` only SIGKILLs the immediate child
    on timeout; any process THAT child spawned (e.g. `bd --shared-server`
    spawning its own `dolt sql-server`) is reparented to init and keeps
    running. Launching in a new session (`start_new_session=True`, its own
    POSIX process group) and killing the whole group on timeout is what
    actually reaches them.

    On timeout, returns a `CompletedProcess` with `returncode=124` (the
    conventional shell `timeout` exit code) and an explanatory message
    folded into `stderr` -- this never raises, so every existing call
    site's `p.returncode != 0` / `(p.stderr or p.stdout)` handling treats a
    hang exactly like any other bd failure, with no second exception type
    for callers to catch.
    """
    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group -- see `_kill_process_group`
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            # The group is now dead (or dying) -- this drains the pipes and
            # reaps the process rather than leaving a zombie; a second
            # short timeout guards against a straggler that ignored SIGKILL
            # somehow, in which case we still return rather than hang here.
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        note = f"timed out after {timeout:.0f}s: {' '.join(args)}"
        logger.warning(note)
        return subprocess.CompletedProcess(args, 124, stdout or "", f"{stderr or ''}\n{note}")


def _bd_env(extra: dict | None = None) -> dict:
    """Base environment for EVERY subprocess invocation of `bd`, anywhere in
    this package -- not just calls routed through `Beads._run`.

    ASSUMPTION (unwritten, but load-bearing): `bd`'s first-use telemetry
    consent prompt reads from stdin and blocks forever when there is no tty
    -- true of every agent session. A single call site that forgets this
    env var is a hang, not a degraded experience. Round 1 of this fix
    covered `Beads._run` (via `Beads._env`) and missed the bare `bd init`
    subprocess in `Workspace.create` -- proof that "remember to set it at
    each call site" does not hold up. Every function in this module that
    shells out to `bd` must build its env through this one function, so the
    guarantee holds by construction rather than by discipline.

    Round 2 correction -- verify the mechanism, not just the discipline:
    round 1 set `BD_TELEMETRY_DISABLE=1`, which reads like a real bd
    control but is NOT ONE. Empirically confirmed against the installed
    v1.1.2 binary (`strings $(which bd) | grep TELEMETRY` and a live `bd
    init --shared-server` run with a fresh config): `BD_TELEMETRY_DISABLE`,
    `BD_TELEMETRY`, `BEADS_TELEMETRY`, `BD_TELEMETRY_ENABLED`,
    `DO_NOT_TRACK`, and `BD_NO_TELEMETRY` are all ABSENT from the binary --
    setting any of them is a pure no-op. Setting only `BD_TELEMETRY_DISABLE`
    against a fresh config and `--shared-server` reproduces the real hang:
    `bd` still prints its interactive telemetry-consent notice and blocks
    on stdin. `BD_NON_INTERACTIVE` IS present in the binary and IS what the
    contract test / a real DTU session used to get past this successfully
    (`export BD_NON_INTERACTIVE=1 && bd init ...`) -- verified: with this
    var set and stdin closed, `bd init` completes with no prompt and no
    hang, every time.

    IMPORTANT: `BD_NON_INTERACTIVE` alone does NOT decline telemetry --
    it only prevents the interactive prompt from blocking. Verified: after
    `bd init` under `BD_NON_INTERACTIVE=1`, `~/.config/bd/config.yaml`
    still shows `metrics: {disabled: false}`. Actually declining telemetry
    is a separate, verified mechanism -- see `_disable_telemetry_once`.
    """
    e = dict(os.environ)
    e["BD_NON_INTERACTIVE"] = "1"
    if extra:
        e.update(extra)
    return e


_TELEMETRY_OFF_ATTEMPTED = False


def _disable_telemetry_once() -> None:
    """Actually decline bd's anonymous telemetry -- once per process,
    best-effort, never raising.

    `_bd_env`'s `BD_NON_INTERACTIVE=1` only prevents the first-use
    telemetry-consent prompt from blocking; it does NOT turn telemetry off
    (verified -- see `_bd_env`'s docstring). The real, verified mechanism
    is `bd metrics off`: it writes `metrics.disabled: true` to bd's GLOBAL
    config (`~/.config/bd/config.yaml`), needs no project/`.beads` context
    to run, is idempotent, and -- verified empirically -- once run, a
    later `bd init` in a brand-new project prints no telemetry notice at
    all and leaves `disabled: true` in place. Calling this before the
    first `bd init` this process ever performs is what makes "telemetry
    must not be enabled" actually true, not just "the prompt didn't hang."

    Never raises: telemetry preference is a courtesy setting, not
    something that should block project creation if `bd` is missing,
    broken, or this is a read-only environment. A failure here is silently
    swallowed -- worst case, telemetry stays at bd's own default.
    """
    global _TELEMETRY_OFF_ATTEMPTED
    if _TELEMETRY_OFF_ATTEMPTED:
        return
    _TELEMETRY_OFF_ATTEMPTED = True
    try:
        _run_bounded(["bd", "metrics", "off"], env=_bd_env(), timeout=10)
    except Exception:  # noqa: BLE001 -- best-effort courtesy setting, never fatal
        pass


def _bd_init_server_args() -> list[str]:
    """Which `bd init` server flags `Workspace.create` should pass: ATTACH to
    an already-healthy shared dolt server if one is responding on the
    conventional host:port, or fall back to `--shared-server` (bd spawns and
    owns its own) when nothing is there yet.

    Why this exists: `--shared-server` has no "attach if one is already
    running" mode of its own -- it unconditionally tries to SPAWN a dolt
    server at the fixed `~/.beads/shared-server` location. When our own
    supervisor (see supervisor.py) already started that exact server --
    which is the entire point of `amplifier-work-tracker service
    install`/`serve` -- a second `bd init --shared-server` collides.
    Measured in a DTU run: `bd init failed: ... cannot start dolt server on
    port 3308: port 3308 is busy but cannot identify the process` -- three
    of eight tool failures in that run were this exact collision, and the
    only escape the agent found was a hand-written raw `bd init --server
    --server-port 3308 --external --role maintainer` (`--server` mode DOES
    accept an already-running, externally-managed server; `--shared-server`
    does not). This function supplies that escape by construction instead of
    forcing every caller to rediscover it by hand.

    `--server --server-host <host> --server-port <port> --external` targets
    the EXACT SAME conventional location/port `--shared-server` would have
    used (see supervisor.DEFAULT_DOLT_HOST/DEFAULT_DOLT_PORT) -- this is
    "the same shared server, attached instead of respawned," not a second,
    incompatible one. `--role maintainer` is not passed explicitly: bd's own
    non-interactive mode already defaults to it (see `_bd_env`'s
    `BD_NON_INTERACTIVE=1`), so duplicating it here would just be a second
    place for that default to drift from bd's.

    Deferred import of `supervisor` here (not at module level): supervisor
    already imports this module (`adapter`), so an unconditional top-level
    `from . import supervisor` here would be circular.
    """
    from . import supervisor as SV  # local: see docstring -- avoids a circular import

    host, port = SV.DEFAULT_DOLT_HOST, SV.DEFAULT_DOLT_PORT
    if SV.port_holder_responds(host, port):
        return ["--server", "--server-host", host, "--server-port", str(port), "--external"]
    return ["--shared-server"]


def _dolt_conn_args() -> list[str]:
    """Global `dolt` CLI flags to reach the shared server directly over SQL,
    bypassing any per-project `.beads` directory entirely.

    This is the ONLY way to make a project's shared-server database actually
    disappear: `bd` has no command for it. Verified empirically against the
    installed bd 1.1.2 binary before writing this -- `bd delete` removes
    *issues*, not databases, and `bd dolt` only manages server lifecycle and
    config, never drops one. `dolt sql --host <host> --port <port>` (global
    flags, placed BEFORE the `sql` subcommand -- `dolt sql --host` itself
    errors `unknown option`) connects to the ALREADY-RUNNING shared server
    exactly like `bd` itself does, rather than opening a second, unrelated
    local repo. Deferred import of `supervisor`, same reason as
    `_bd_init_server_args`: avoids a circular import (supervisor imports
    this module already).
    """
    from . import supervisor as SV

    return ["--host", SV.DEFAULT_DOLT_HOST, "--port", str(SV.DEFAULT_DOLT_PORT), "--no-tls"]


def _dolt_sql(query: str) -> subprocess.CompletedProcess:
    return _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", query, "-r", "csv"],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )


def database_exists(name: str) -> bool:
    """Does a database named `name` exist on the shared dolt server --
    independent of whether ANY project directory / `.beads` dir exists for
    it locally.

    Read via `information_schema.SCHEMATA` rather than parsing `show
    databases` table output (a name substring could otherwise false-match
    another database), and via the direct network SQL path rather than a
    project-scoped `bd` call -- this must work even when
    `Workspace.path(name)/.beads` is missing entirely, which is exactly the
    orphaned-database case this function exists to detect (see
    `Workspace.remove` and the `new`/adoption-honesty fix in `Workspace.create`).

    `name` is not interpolated into anything that could be mistaken for SQL
    outside a string literal, and every caller has already passed `name`
    through `NAME_RE` (`^[a-z][a-z0-9_]{1,30}$`) before reaching here, so it
    cannot contain a quote, backtick, or other SQL-relevant character.
    """
    p = _dolt_sql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}'")
    if p.returncode != 0:
        raise BeadsError(
            f"could not check whether database {name!r} exists on the shared dolt "
            f"server: {_clean_bd_error(p.stderr or p.stdout)}"
        )
    rows = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][1:]  # drop CSV header
    return name in rows


def drop_database(name: str) -> bool:
    """Drop `name`'s database from the shared dolt server via a direct SQL
    connection (`bd` has no command for this -- see `_dolt_conn_args`).

    Returns True if a database existed and was dropped, False if it did not
    exist at all (not an error -- e.g. called on a project whose database
    was already removed by a previous, partially-completed attempt). Any
    OTHER failure raises rather than being swallowed as a false "nothing to
    drop": a caller relying on this to make data actually disappear must
    never see a silent no-op reported as success.
    """
    p = _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", f"DROP DATABASE `{name}`"],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )
    blob = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return True
    if "database not found" in blob.lower():
        return False
    raise BeadsError(f"drop_database {name!r} failed: {_clean_bd_error(blob)}")


class BeadsError(Exception):
    """A Beads operation failed. Never caught to degrade -- only to report."""


class AssumptionViolated(BeadsError):
    """The installed Beads no longer behaves the way we depend on."""


class FencedError(BeadsError):
    """This holder is no longer the current owner -- reclaimed by `reap`,
    or taken over by another session -- as opposed to a generic operational
    failure (a `bd`/dolt command failing, a readback mismatch). Callers that
    track local claim/custody state (see
    `amplifier_module_tool_work_tracker.WorkTrackerSession`) must treat this
    specifically as "release local state, the item is no longer ours" --
    and must NOT do the same for a plain `BeadsError`, where bd still
    considers us the holder and the operation may simply be retried.
    Raised only from `Beads.resolve` and `Beads.renew_custody`'s fence
    checks; every other Beads failure stays a plain `BeadsError`.
    """


def _parse_bd_timestamp(v: object) -> datetime | None:
    """Parse one of bd's own timestamp strings (`created_at`/`updated_at`/
    `closed_at`) into a real, timezone-aware `datetime` -- the one place
    that knows bd's exact wire shape (ISO 8601 with a trailing `Z`), so
    nothing above this module ever re-parses (or mis-parses) a raw string.

    Returns `None` for anything that isn't a non-empty string, or that
    fails to parse -- a malformed/absent timestamp is treated as "we don't
    know", never coerced into a fabricated time. `datetime.fromisoformat`
    (Python 3.11+) accepts the trailing `Z` directly; no manual `+00:00`
    substitution needed.
    """
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        logger.debug("could not parse bd timestamp %r", v)
        return None


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
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    created_by: str | None = None
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
        # Timestamps are parsed here, at the seam, into real `datetime`
        # objects -- never handed upward as raw strings for every caller
        # to re-parse (and potentially mis-parse) on its own. bd emits
        # these as ISO 8601 with a trailing "Z"; `_parse_bd_timestamp`
        # is the one place that knows that shape.
        out["created_at"] = _parse_bd_timestamp(d.get("created_at"))
        out["updated_at"] = _parse_bd_timestamp(d.get("updated_at"))
        out["closed_at"] = _parse_bd_timestamp(d.get("closed_at"))
        out["created_by"] = d.get("created_by") or None
        return cls(**{k: v for k, v in out.items() if k in cls.__dataclass_fields__}, raw=d)

    def summary(self, *, full: bool = False) -> dict:
        """The read-only view of this item shared by every list/read
        surface -- `Beads.list_bounded`'s lean rows (`work_list`/the CLI's
        `list`) and a single directed read (`work_list`'s `item_id`, the
        CLI's `list --id`) alike, so the two never drift into slightly
        different shapes.

        `full=False` (the default, and every existing list caller's
        behavior, unchanged) keeps the payload lean -- id/title/status/
        holder/resolution only. `full=True` adds the same body fields
        `work_claim`/the CLI's `claim` already hand back on a successful
        claim (acceptance/description/design) -- a directed READ should be
        able to show everything a claim would have told you, without
        taking the item. See `Beads.get_readonly` for the read primitive
        this is paired with.

        Timestamps (`created_at`/`updated_at`/`closed_at`/`created_by`)
        are `full`-only, deliberately -- see `project_activity` for the
        cheaper, project-level alternative (oldest-unclaimed age, recent
        throughput) the lean list surface uses instead. Adding three ISO
        strings per row to a 200+ item default listing would bloat the
        exact payload this method's docstring already promises to keep
        lean; a single directed read has no such concern.
        """
        row: dict = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "holder": self.holder,
            "resolution": self.resolution,
        }
        if full:
            row["acceptance"] = self.acceptance
            row["description"] = self.description
            row["design"] = self.design
            row["created_at"] = self.created_at.isoformat() if self.created_at else None
            row["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
            row["closed_at"] = self.closed_at.isoformat() if self.closed_at else None
            row["created_by"] = self.created_by
        return row


def _active_blockers(item: Item) -> list[dict]:
    """Which of `item`'s forward dependencies are still-open `blocks`-type
    links -- i.e. actually blocking `claim_item`.

    Read straight from the raw `show` payload's `dependencies` field, which
    IS present without `--include-dependents` (that flag only gates the
    REVERSE direction -- ASSUMPTION show.dependents). A raw bd status of
    anything other than `closed` counts as active: a blocker that is
    itself `blocked` or `deferred` still blocks; only a resolved (closed)
    one clears the way.
    """
    deps = item.raw.get("dependencies") or []
    return [
        d
        for d in deps
        if isinstance(d, dict)
        and d.get("dependency_type") == "blocks"
        and d.get("status") != "closed"
    ]


def _retryable(blob: str) -> bool:
    low = blob.lower()
    return any(t.lower() in low for t in _RETRYABLE)


STATUS_ERROR_MAX = 300  # see `truncate_status` -- was 120/70 at two call sites, severing hints


def truncate_status(text: str, limit: int = STATUS_ERROR_MAX) -> str:
    """Truncate a diagnostic status string for display, never mid-word.

    One home for this so the multiple per-project status surfaces (the
    `work_status` tool's per-project error, the `instances` CLI's per-project
    error) don't each reinvent -- and mis-invent -- the same truncation.
    Measured bug this replaces: a bare `text[:120]` (and, separately,
    `text[:70]`) sliced mid-word, severing the actionable half of the
    message -- e.g. "...or 'bd in" instead of "...or 'bd init' to create a
    new database". The cap itself is also raised (120/70 -> 300): these are
    diagnostic hints meant to be acted on, not a log line competing for
    terminal width.

    Cuts at the last whitespace boundary at or before `limit` and appends an
    explicit `...[truncated]` marker so it's obvious to a reader (human or
    agent) that more text existed, rather than looking like a complete,
    oddly-worded message. Falls back to a hard cut at `limit` only if no
    whitespace boundary exists in range (e.g. one very long unbroken token).
    """
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return text[:cut] + " ...[truncated]"


# Substrings that mean "this text came straight from bd/dolt/git internals
# and must never reach a caller verbatim" -- matched case-insensitively, as
# substrings rather than whole messages, so future bd wording changes around
# the same commands are still caught. Measured outage, 2026-08-15: an agent
# (correctly, per the bundle's own rules) forbidden from running `bd`/`git
# config`/`dolt` directly was handed exactly those commands as "the fix" --
# `create failed: ...git config beads.role maintainer...`, `bd init failed:
# ...run 'bd dolt commit' to commit the working set...` -- and had to
# consciously override its own error-following instinct to stay compliant.
_LEAKING_BD_INTERNALS_PATTERNS = (
    "git config beads.role",
    "bd dolt commit",
    "bd dolt ",
    "beads.role not configured",
    "gh#",
    "no beads configuration found",
    "using default database name",
    "run 'bd ",  # e.g. "run 'bd init'", "run 'bd where'" -- an instruction
    # to run bd directly, in bd's own quoting style
    "bd where",
    "beads_dir",  # e.g. "set BEADS_DIR to point to your .beads directory"
    "no beads database found",
)

# The signature bd emits when `bd init` targets a database left mid schema
# migration by a PREVIOUS, interrupted `bd init` -- never seen from normal
# item operations, only from init against dirty tables. See
# `Workspace.create`'s dirty-schema self-heal.
_DIRTY_SCHEMA_MIGRATION_PATTERNS = ("dirty tables", "pending schema migration")


def _looks_like_leaking_bd_internals(blob: str) -> bool:
    low = blob.lower()
    return any(pattern in low for pattern in _LEAKING_BD_INTERNALS_PATTERNS)


def _looks_like_dirty_schema_migration(blob: str) -> bool:
    low = blob.lower()
    return any(pattern in low for pattern in _DIRTY_SCHEMA_MIGRATION_PATTERNS)


def _clean_bd_error(blob: str | None, *, limit: int = STATUS_ERROR_MAX) -> str:
    """Render a bd/dolt failure blob as text safe to hand to a caller --
    every `BeadsError` message built from `(p.stderr or p.stdout)` in this
    module goes through here, not a bare slice.

    Two independent problems, both measured in the 2026-08-15 outage:

      1. bd/dolt sometimes emit remediation instructions in THEIR OWN
         vocabulary (`git config beads.role ...`, `bd dolt commit`, a
         `GH#nnnn` reference, a fallback-database warning) -- see
         `_LEAKING_BD_INTERNALS_PATTERNS`'s docstring for the measured
         cost. Detected here and replaced with guidance in OUR vocabulary
         instead. The raw text is never thrown away -- it goes to
         `logger.warning` -- only kept out of the caller's instruction path.
      2. A bare slice can cut mid-word, leaving a meaningless fragment
         (measured: `Error: database`). `truncate_status` already solves
         this (word-boundary cut, explicit `...[truncated]` marker) --
         reused here rather than reinvented.
    """
    raw = (blob or "").strip()
    if not raw:
        return "(bd reported no detail)"
    if _looks_like_leaking_bd_internals(raw):
        # DEBUG, deliberately -- not warning/info. Python's own "handler of
        # last resort" prints WARNING-and-above to stderr with NO handler
        # configured at all (true for every plain CLI invocation; only
        # `serve()` calls `_configure_logging()`). Logging the raw blob at
        # warning-or-above would put it right back in a normal command's
        # stderr -- exactly the instruction path this function exists to
        # keep it out of. DEBUG is preserved (never destroyed) for anyone
        # who explicitly configures logging to capture it, without being
        # visible by default.
        logger.debug("sanitized a bd/dolt failure that leaked internal vocabulary: %s", raw)
        return (
            "the underlying store reported an internal configuration problem (full "
            "detail is in this process's logs). This is never fixed by running a `bd`, "
            "`git config`, or `dolt` command directly -- retry the amplifier-work-tracker "
            "command, and if it keeps failing, run `amplifier-work-tracker doctor` and "
            "escalate with that output attached"
        )
    return truncate_status(raw, limit)


@dataclass
class ListResult:
    """What `Beads.list_bounded` actually returned, and how it relates to
    the true total -- see that method's docstring for why `truncated` is a
    measured fact, not an inference from bd's own default page size."""

    items: list[Item]
    total_count: int
    returned_count: int
    truncated: bool
    limit: int
    requested_limit: int | None


def project_activity(items: list[Item]) -> dict:
    """Time-based aggregates for one project's items -- the shared
    computation behind the CLI's `instances` command and the `work_status`
    tool's per-project roll-up, so neither reinvents (or silently
    disagrees on) what "oldest unclaimed" or "resolved recently" mean.
    One home for logic two callers both need, same rationale as
    `list_bounded`.

    Exists because per-item timestamps in a *list* would bloat exactly the
    payload `Item.summary()`'s lean default is designed to avoid (see its
    docstring) -- a 200+ item project would carry three extra ISO strings
    per row for a question ("how's this queue trending?") that only needs
    a handful of numbers computed once across the whole project. This is
    that computation.

    Every field below follows the same "skip, don't fail" convention as
    the rest of this module's dependency-ordered checks (see
    `cli._check_dolt_reachable`'s docstring for the same idea applied to
    doctor): an item missing the timestamp a given metric needs is simply
    excluded from it, never coerced into a fake reading and never raised
    on. `oldest_unclaimed_age_seconds` is `None` (not `0`) when there is
    no ready item with a readable `created_at` -- the same "could not
    read" vs "read as empty" distinction the rest of this codebase
    already draws for aggregate fields. `resolved_24h`/`resolved_7d` are
    real zeros when the project genuinely has no matching resolutions --
    a count of zero is a legitimate, meaningful answer, unlike an age with
    nothing to measure from.

    Returns:
        A dict with:
          - `oldest_unclaimed_age_seconds` (float | None): age of the
            longest-waiting ready item (`status == "open"` and tagged
            `LANE_WORK`), or `None` if there is no such item with a
            readable `created_at`.
          - `resolved_24h` / `resolved_7d` (int): count of items whose
            `status == "resolved"` and `closed_at` falls within the last
            24 hours / 7 days of now.
          - `last_activity` (str | None): the most recent `updated_at`
            across every item, as an ISO 8601 string, or `None` if no
            item has a readable `updated_at`.
    """
    now = datetime.now(UTC)
    ready_ages = [
        (now - i.created_at).total_seconds()
        for i in items
        if i.status == "open" and LANE_WORK in i.tags and i.created_at is not None
    ]
    resolved_24h = sum(
        1
        for i in items
        if i.status == "resolved"
        and i.closed_at is not None
        and (now - i.closed_at) <= timedelta(hours=24)
    )
    resolved_7d = sum(
        1
        for i in items
        if i.status == "resolved"
        and i.closed_at is not None
        and (now - i.closed_at) <= timedelta(days=7)
    )
    updated_ats = [i.updated_at for i in items if i.updated_at is not None]
    return {
        "oldest_unclaimed_age_seconds": max(ready_ages) if ready_ages else None,
        "resolved_24h": resolved_24h,
        "resolved_7d": resolved_7d,
        "last_activity": max(updated_ats).isoformat() if updated_ats else None,
    }


class Beads:
    """A handle on one Beads project. Construct via Workspace.project()."""

    def __init__(self, beads_dir: Path, actor: str | None = None):
        self._dir = Path(beads_dir)
        self._actor = actor

    # ---------------------------------------------------------------- plumbing

    def _env(self, actor: str | None = None) -> dict:
        # Telemetry-disable is handled by `_bd_env` -- unconditionally, not
        # merely inherited -- so every `bd` call site in this module (this
        # one included) gets it the same way. See `_bd_env`'s docstring.
        e = _bd_env({"BEADS_DIR": str(self._dir)})
        a = actor or self._actor
        if a:
            e["BEADS_ACTOR"] = a
        return e

    def _run(self, args: list[str], actor: str | None = None) -> subprocess.CompletedProcess:
        last = None
        for attempt in range(_MAX_RETRIES):
            p = _run_bounded(["bd", *args], env=self._env(actor))
            last = p
            if _retryable((p.stdout or "") + (p.stderr or "")):
                time.sleep(0.15 * (2**attempt) * (0.5 + os.urandom(1)[0] / 255))
                continue
            return p
        raise BeadsError(
            f"`bd {' '.join(args[:2])}` still conflicting after {_MAX_RETRIES} retries. "
            f"Contention too high; refusing to keep hammering. "
            f"Last: {_clean_bd_error((last.stderr or last.stdout) if last else '', limit=200)}"
        )

    def _json(self, args: list[str], actor: str | None = None):
        p = self._run([*args, "--json"], actor=actor)
        out = (p.stdout or "").strip()
        if not out:
            if p.returncode != 0:
                raise BeadsError(f"`bd {' '.join(args[:2])}`: {_clean_bd_error(p.stderr)}")
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
            raise BeadsError(f"create failed: {_clean_bd_error(p.stderr or p.stdout)}")
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

    def claim_item(self, item_id: str, *, actor: str) -> Item:
        """Directed claim: atomically claim a SPECIFIC item by id.

        Not a lesser claim than `claim_next` -- same atomic primitive
        (`bd update --claim`, ASSUMPTION claim.directed_atomic), same
        caller-side responsibility to start custody afterward. The
        difference is only which item: a human or planning session naming
        one directly, versus pulling the next off the queue.

        Three distinct outcomes, deliberately never conflated:
          - success: this actor is now the holder (status in_progress).
          - already held by someone else: raises, naming the real holder --
            by surfacing bd's own message (it already says exactly this)
            rather than inventing a different one.
          - item does not exist: raises, phrased with "not found" so it
            reads distinctly from "someone else has it" at a glance.

        Blocker-aware refusal is OURS, not bd's. Measured empirically
        against bd 1.1.2: `bd update <id> --claim` claims a blocked item
        exactly as readily as a free one -- unlike `bd ready --claim`,
        which is blocker-aware by construction (its own --help: "open
        issues with no active blockers"). Claiming work whose prerequisite
        isn't done produces wasted or conflicting work, so we check first
        and refuse before ever calling bd's --claim, naming the blocker(s)
        bd's own `show` already told us about. No override flag: if a
        named blocker doesn't actually apply, resolve it or remove the
        dependency link, then claim again.
        """
        try:
            current = self.get(item_id)
        except BeadsError as e:
            raise BeadsError(f"cannot claim {item_id}: item not found ({e})") from e

        blockers = _active_blockers(current)
        if blockers:
            names = ", ".join(f"{b['id']} ({b.get('status', 'unknown')})" for b in blockers)
            raise BeadsError(
                f"refusing to claim {item_id}: blocked by open dependency/dependencies "
                f"{names}. Resolve the blocker(s), or remove the dependency link, then "
                f"claim again -- directed claims never bypass blockers."
            )

        p = self._run(["update", item_id, "--claim", "--json"], actor=actor)
        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "").strip()
            raise BeadsError(f"claim {item_id} as {actor!r} failed: {msg[:300]}")
        out = (p.stdout or "").strip()
        try:
            data = json.loads(out) if out else None
        except json.JSONDecodeError as e:
            raise BeadsError(f"claim {item_id}: bd returned non-JSON: {out[:200]}") from e
        items = data if isinstance(data, list) else ([data] if data else [])
        items = [i for i in items if isinstance(i, dict) and i.get("id")]
        if not items:
            raise BeadsError(f"claim {item_id}: bd reported success but returned no item")
        return Item.from_beads(items[0])

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

    @property
    def project_name(self) -> str:
        """This project's name, inferred from its `.beads` directory's
        parent (`Workspace.path(name) / ".beads"` -- see `Workspace.project`).
        Used only to shape a READ-path error message (`get_readonly`); never
        passed to `bd` itself, and never a substitute for the real identity
        that lives in `self._dir`.
        """
        return self._dir.parent.name

    def get_readonly(self, item_id: str) -> Item:
        """Read one item's full record -- WITHOUT claiming, mutating, or
        touching custody. This is `bd show` and nothing else: no `--claim`,
        no `--update`, no assignee change, no custody metadata write. See
        ASSUMPTION/check `read.no_mutation` in `amplifier_work_tracker.contract`
        for the live proof that repeated reads leave status/holder/metadata
        untouched.

        Exists because `work_claim`/`bd update --claim` was, until now, the
        ONLY path that returned an item's `description`/`acceptance`/`design`
        -- forcing an agent that merely wants to understand what an item is
        asking for to first take ownership of it. See this project's
        `context/awareness.md` and the `claiming-work-safely` skill for the
        agent-facing framing of that gap.

        Distinguishes two failure shapes bd's own error text does not (both
        read as the IDENTICAL "no issues found matching the provided IDs"):
          - `item_id` does not even carry this project's own id prefix
            (Beads mints ids as `<project>-<slug>`, e.g. `cortex-wbcp`) --
            e.g. a `cortex-*` id looked up against `wiki_weaver`. Reported as
            a wrong-project mismatch, since that is overwhelmingly the more
            likely mistake, and bd's identical wording for both cases would
            otherwise hide an easy-to-make error.
          - `item_id` DOES carry this project's prefix but truly does not
            exist here.
        """
        try:
            return self.get(item_id)
        except BeadsError as e:
            prefix = f"{self.project_name}-"
            if not item_id.startswith(prefix):
                raise BeadsError(
                    f"item {item_id!r} does not look like it belongs to project "
                    f"{self.project_name!r} (its ids start with {prefix!r}) -- "
                    f"check the project name and the id, then try again"
                ) from e
            raise BeadsError(f"item {item_id!r} not found in project {self.project_name!r}") from e

    def list(
        self,
        *,
        lane: str | None = None,
        include_resolved: bool = False,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[Item]:
        """List items, optionally filtered by lane and/or OUR domain status
        ("open", "held", "resolved", "blocked", "deferred"), optionally capped.

        `status`, when given, takes priority over `include_resolved`: passing
        an explicit `--status` to bd shows closed items without needing
        `--all` at all (ASSUMPTION list.status_filter_includes_closed,
        verified empirically against bd 1.1.2 -- `bd list --status closed
        --json` returns closed items with no `--all` present). This means a
        caller asking for `status="resolved"` sees resolved items regardless
        of `include_resolved`.

        `limit`, when given, is passed straight through as bd's own
        `--limit`/`-n` (0 means unlimited to bd). `None` leaves bd's own
        default (50) in place -- unchanged behavior for every existing
        caller that never specified `limit`. Callers that need the TRUE
        total count (not just bd's own default-capped view) should pass
        `limit=0` explicitly -- see `list_bounded`, which does exactly that.
        """
        args = ["list"]
        if status is not None:
            raw = _STATUS_MAP_REVERSE.get(status)
            if raw is None:
                raise BeadsError(
                    f"unknown status {status!r}: must be one of {sorted(_STATUS_MAP_REVERSE)}"
                )
            args += ["--status", raw]
        elif include_resolved:
            # ASSUMPTION list.includes_closed -- without this a resolved report
            # vanishes exactly when its answer is ready.
            args += ["--all"]
        if lane:
            args += ["--label", lane]
        if limit is not None:
            args += ["--limit", str(limit)]
        data = self._json(args) or []
        return [Item.from_beads(d) for d in data if isinstance(d, dict)]

    def list_bounded(self, *, status: str | None = None, limit: int | None = None) -> ListResult:
        """Read-only, explicitly-capped item listing for human/agent
        consumption -- the shared implementation behind both the CLI's
        `list` subcommand and the `work_list` tool, so neither reinvents
        (or silently disagrees on) the capping policy.

        Always fetches the FULL matching set first (`limit=0` -- bd's own
        "unlimited") to learn the true total, THEN caps in Python. This is
        what makes `truncated` a fact rather than a guess: a caller that
        only ever saw bd's own default-50-item page would have no way to
        know whether 50 was the true total or a silent truncation.

        `limit=None` uses `LIST_DEFAULT_LIMIT`; any requested limit is
        clamped to `[1, LIST_MAX_LIMIT]` -- silently for the lower bound (a
        request for 0 or negative items is nonsensical, not meaningful
        input worth reporting on), but ALWAYS reported via
        `ListResult.requested_limit` vs `ListResult.limit` when the upper
        bound clamps, so a caller asking for more than the max learns that
        distinctly from asking for exactly 500 -- a cap must never be silent.
        """
        effective = LIST_DEFAULT_LIMIT if limit is None else max(1, min(limit, LIST_MAX_LIMIT))
        items = self.list(status=status, include_resolved=(status is None), limit=0)
        capped = items[:effective]
        return ListResult(
            items=capped,
            total_count=len(items),
            returned_count=len(capped),
            truncated=len(capped) < len(items),
            limit=effective,
            requested_limit=limit,
        )

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
                    raise FencedError(
                        f"refusing to close {item_id}: current holder is "
                        f"{current.holder!r} (custody holder {cust.get('holder')!r}), "
                        f"not {who!r}. Your claim was reclaimed while you were away."
                    )
            elif current.status == "held" and current.holder and current.holder != who:
                raise FencedError(
                    f"refusing to close {item_id}: it is held by {current.holder!r}, "
                    f"not {who!r}. Your claim was reclaimed while you were away."
                )
        p = self._run(["close", item_id, "--reason", reason], actor=actor)
        if p.returncode != 0:
            raise BeadsError(f"close {item_id}: {_clean_bd_error(p.stderr or p.stdout)}")
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
            detail = _clean_bd_error(p.stderr or p.stdout, limit=200)
            raise BeadsError(f"release {item_id}: {detail}")

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
            detail = _clean_bd_error(p.stderr or p.stdout, limit=200)
            raise BeadsError(f"take_custody {item_id}: {detail}")
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
            raise FencedError(
                f"refusing to renew custody on {item_id}: current holder is "
                f"{current.get('holder')!r} generation {current.get('generation')}, "
                f"caller is {holder!r} generation {generation}. Your custody "
                f"was taken over while you were away."
            )
        if it.holder != holder:
            raise FencedError(
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
            detail = _clean_bd_error(p.stderr or p.stdout, limit=200)
            raise BeadsError(f"renew_custody {item_id}: {detail}")
        back = self.get_custody(item_id)
        if back != updated:
            raise BeadsError(
                f"renew_custody {item_id} reported success but readback shows "
                f"{back!r} -- refusing to report success"
            )
        return updated


@dataclass
class RemovalReport:
    """What `Workspace.remove` actually did, in both locations a project
    can live -- see `Workspace.remove`'s docstring for the full contract."""

    name: str
    directory: Path
    had_beads_dir: bool
    had_database: bool
    beads_removed: bool
    database_removed: bool
    directory_removed: bool
    leftover: list[str] = field(default_factory=list)


def _read_lock_pid(lock: Path) -> int | None:
    """The pid recorded in a `.create.lock` file, or None if it cannot be
    read as one (missing, empty, non-numeric) -- treated as dead by
    `_pid_alive`, since an unreadable lock cannot be protecting anything.
    """
    try:
        return int(lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool:
    """Is `pid` a live process?

    Deliberately NOT shared with `cli._pid_alive` (which does the same
    eight lines) -- per IMPLEMENTATION_PHILOSOPHY's "conventions via
    instructions, not code": this is a trivial, stdlib-shaped check, and
    `cli.py` already imports FROM this module, so importing back would be
    circular. Keep both in sync by inspection, not by coupling.
    """
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just isn't ours to signal -- still alive
    return True


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
            raise BeadsError(
                f"project {name!r} not found at {d}. Create it first: "
                f"amplifier-work-tracker new {name}"
            )
        return Beads(d, actor=actor)

    def creation_state(self, name: str) -> str | None:
        """Is `name` currently mid-creation, or left over from one that
        never finished?

        Returns:
          - ``"creating"``  -- a `.create.lock` names a PID that is still
            alive; a `create()` call for this name is genuinely in progress
            elsewhere right now.
          - ``"abandoned"`` -- a `.create.lock` names a PID that is no
            longer alive; `create()` self-heals this automatically on its
            very next call (see `_heal_abandoned`).
          - ``None``        -- no lock at all; nothing in progress.

        Read-only and side-effect-free -- used by `cmd_instances` so a
        project caught mid-creation, or broken by one that never finished,
        is reported as such instead of a blind "ok" that only reflects
        whether `list()` happened to return without raising. Measured
        outage, 2026-08-15: `instances` reported a half-created project as
        `ok` (`TOTAL 0 READY 0 HELD 0 INTAKE 0  ok`) while its
        `.create.lock` sat right there, unconsulted.
        """
        lock = self.path(name) / ".create.lock"
        if not lock.exists():
            return None
        return "creating" if _pid_alive(_read_lock_pid(lock)) else "abandoned"

    def _heal_abandoned(self, name: str, beads_dir: Path, lock: Path) -> None:
        """Best-effort cleanup of a `create()` attempt that never finished
        -- a `.create.lock` naming a pid that is no longer alive.

        Drops the server-side database, if any (`drop_database` treats
        "does not exist" as a normal no-op, never an error -- see its
        docstring), then removes the local `.beads` directory and the
        stale lock. This is what lets the very next `create()` call for
        this name -- including the SAME call that detected the abandoned
        state -- start from a genuinely clean slate instead of perpetually
        hitting the stale lock, or a dirty half-migrated database.

        Safe by construction: a `.create.lock` is written ONLY by
        `create()`, and removed ONLY by that same call's own `finally`
        block on any normal completion (success, or a raised
        `BeadsError`). The only way one survives is the process dying
        abnormally (SIGKILL, host crash) mid-creation -- unambiguous
        evidence this name's database, if any, never got past THIS
        attempt, so it is always safe to discard.

        Raises (refuses to proceed) if the drop itself fails for a reason
        other than "does not exist" -- e.g. the shared dolt server is
        unreachable -- rather than silently treating an unverifiable state
        as healed.
        """
        try:
            drop_database(name)
        except BeadsError as e:
            raise BeadsError(
                f"project {name!r} has an abandoned creation attempt at {beads_dir} "
                f"(a previous `new` never finished), and healing it failed while "
                f"checking the shared server: {e}. Refusing to guess -- verify the "
                f"shared dolt server is reachable (`amplifier-work-tracker doctor`) "
                f"before retrying."
            ) from e
        shutil.rmtree(beads_dir, ignore_errors=True)
        lock.unlink(missing_ok=True)

    def create(self, name: str) -> Path:
        """Create a project -- atomically, from the caller's point of
        view: a `create()` interrupted partway (killed, host crash) must
        never leave a permanently-unusable project behind. Name rules and
        post-init verification are ours.

        ASSUMPTION project.name_rules -- a dotted name yields an unusable
        database while `bd init` still reports success, so we reject early
        and then prove the database actually answers before saying it
        worked.

        Measured outage, 2026-08-15: an external timeout killed `new` mid
        `bd init`. The process died before its own `finally:
        lock.unlink()` could run, so the lock outlived it -- every later
        `new` of the same name refused, PERMANENTLY, until an operator
        noticed and cleaned up by hand (and even then, the server-side
        residue outlived a manual `rm -rf` of the local directory, burning
        the name a second way). Three self-healing steps close this, each
        pinned to a specific part of that outage:

          1. A `.create.lock` naming a DEAD pid heals automatically rather
             than refusing forever -- see `creation_state`/
             `_heal_abandoned`.
          2. A `.beads` directory that answers to no lock at all, but does
             not actually answer, gets a few short retries before being
             treated as broken residue -- so a transient dolt hiccup on an
             otherwise-healthy, long-running project is never mistaken for
             abandoned residue and dropped (see
             `_RESIDUE_CHECK_RETRIES`).
          3. A `bd init` failing on bd's own dirty-schema-migration
             signature ("pending schema migrations alter pre-existing
             dirty tables") is recovered by dropping that residue and
             retrying exactly once, rather than permanently burning the
             name -- this is the exact failure measured AFTER a manual
             `rm -rf` of the local directory: the server-side half
             survived and kept the name unusable even though the local
             half was gone.

        In every case, `d.mkdir` and a fresh `bd init` run at the end of
        this SAME call -- healing and creating happen together, not across
        two separate invocations.
        """
        if not NAME_RE.match(name):
            raise BeadsError(
                f"invalid project name {name!r}: must match {NAME_RE.pattern}. "
                f"Dots are rejected deliberately -- they produce a database that "
                f"reports successful creation and then fails every later command."
            )
        d = self.path(name)
        beads_dir = d / ".beads"
        lock = d / ".create.lock"

        if beads_dir.is_dir():
            state = self.creation_state(name)
            if state == "creating":
                pid = _read_lock_pid(lock)
                raise BeadsError(
                    f"project {name!r} is already being created (lock: {lock}, pid {pid})"
                )
            if state == "abandoned":
                logger.warning(
                    "project %r: healing an abandoned creation attempt (lock %s named "
                    "a dead pid) before retrying",
                    name,
                    lock,
                )
                self._heal_abandoned(name, beads_dir, lock)
                # fall through -- a fresh create completes below, same call
            else:
                # No lock at all -- unchanged from before this fix. A
                # directory existing is not evidence of anything by
                # itself: a failed `bd init` with no surviving lock (rare,
                # but possible -- e.g. the lock file lost independently of
                # `.beads`) leaves residue that must be reported, not
                # silently accepted OR silently dropped. Unlike the
                # dead-pid-lock case above, there is no unambiguous local
                # signal here that this residue is safely discardable, so
                # this stays a refusal with actionable next steps --
                # see test_workspace_create_refuses_to_report_success_on_dead_residue.
                try:
                    self.project(name).list()
                    return d
                except BeadsError as e:
                    # Deliberately phrased as `cd <dir> && rm -r <name>`,
                    # never a bare `rm -rf <abs-path>` -- the literal text
                    # `rm -rf /` trips Amplifier's own bash safety profile
                    # as a SUBSTRING match regardless of whether the path
                    # is actually root (measured cost in a DTU run: 2
                    # wasted tool calls). See prereqs.py's install-command
                    # docstrings for the same fix applied elsewhere.
                    raise BeadsError(
                        f"project {name!r} has stale residue at {beads_dir}: the "
                        f"directory exists but the database does not answer ({e}). A "
                        f"previous create attempt likely failed partway through, and no "
                        f"creation lock survived to self-heal automatically. Remove it "
                        f"and retry: `cd {d} && rm -r .beads` (keeps anything else in "
                        f"{d}), or `cd {d.parent} && rm -r {d.name}` to remove the whole "
                        f"project directory if it holds nothing else you need. This call "
                        f"refuses to silently treat dead residue as a successful project."
                    ) from e

        d.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError as e:
            raise BeadsError(f"project {name!r} is already being created (lock: {lock})") from e
        try:
            if not (d / ".git").is_dir():
                _run_bounded(["git", "init", "-q"], cwd=d, timeout=_GIT_TIMEOUT_SECONDS)
                _run_bounded(
                    ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                    cwd=d,
                    timeout=_GIT_TIMEOUT_SECONDS,
                )
            _disable_telemetry_once()  # see docstring -- BD_NON_INTERACTIVE alone does not do this
            init_args = ["bd", "init", "--prefix", name, *_bd_init_server_args()]
            p = _run_bounded(init_args, cwd=d, env=_bd_env(), timeout=_BD_INIT_TIMEOUT_SECONDS)
            if p.returncode != 0:
                blob = p.stderr or p.stdout or ""
                if _looks_like_dirty_schema_migration(blob):
                    # Narrow, bounded auto-recovery: this exact signature
                    # only arises from a PREVIOUS `bd init` interrupted mid
                    # schema migration -- never from normal item
                    # operations. Drop the residue and retry exactly once
                    # rather than permanently burning this name.
                    logger.warning(
                        "project %r: bd init hit a dirty schema migration -- dropping "
                        "and retrying once: %s",
                        name,
                        blob.strip()[:300],
                    )
                    try:
                        drop_database(name)
                    except BeadsError:
                        pass  # best-effort; the retry below surfaces any real failure
                    p = _run_bounded(
                        init_args, cwd=d, env=_bd_env(), timeout=_BD_INIT_TIMEOUT_SECONDS
                    )
                if p.returncode != 0:
                    raise BeadsError(f"bd init failed: {_clean_bd_error(p.stderr or p.stdout)}")
            self.project(name).list()  # prove it actually answers
            return d
        finally:
            lock.unlink(missing_ok=True)

    def remove(self, name: str, *, force: bool = False) -> RemovalReport:
        """Remove a project: its local `.beads` directory AND its
        shared-server database. This is the counterpart `create` never had
        -- measured cost of that gap on a live box: an operator had to
        `rm -rf` a project directory by hand, orphaning its database, and a
        later `create` of the same name silently resurrected the old data
        (see the `adopted` field on `create`'s caller, `cmd_new`).

        Two independent locations, handled honestly:
          - a project can have a `.beads` directory with no matching
            database (should not normally happen, but reported rather than
            assumed away)
          - a project can have a database with NO `.beads` directory --
            exactly the orphan this command exists to reach. When this is
            the case, this call re-attaches just long enough to check for
            HELD items honestly (reusing the exact same "does an existing
            database answer" path `create` uses), then removes everything
            it created to do so -- a refusal leaves the same state this
            call found, not a half-attached directory.

        Refuses (no override) if any item is currently HELD: an agent may
        be actively working it, and this is the safety property that
        matters most for a destructive, irreversible operation. Refuses
        entirely unless `force=True` (the CLI's `--yes`) -- a second,
        independent gate on top of the caller's own confirmation prompt.

        Never blindly deletes the whole project directory: only `.beads`
        (ours) is removed from a directory that existed before this call.
        Anything else in it (`.git`, source, notes a human put there) is
        left in place and reported via `RemovalReport.leftover` so a human
        can decide what to do with it -- deleting someone's git repo
        because they wanted to drop a work queue would be unforgivable.
        """
        if not force:
            raise BeadsError(
                f"refusing to remove project {name!r} without explicit confirmation "
                f"-- pass force=True (CLI: --yes). This is destructive and irreversible."
            )
        if not NAME_RE.match(name):
            raise BeadsError(f"invalid project name {name!r}: must match {NAME_RE.pattern}")

        d = self.path(name)
        beads_dir = d / ".beads"
        had_beads_dir = beads_dir.is_dir()
        had_database = database_exists(name)

        if not had_beads_dir and not had_database:
            raise BeadsError(
                f"project {name!r} not found: no {beads_dir} directory and no "
                f"database named {name!r} on the shared dolt server. Nothing to remove."
            )

        # Orphan case: the database outlived its directory. Re-attach (the
        # same path `create` uses to discover an existing database) just
        # long enough to check for HELD items -- never drop a database we
        # have not looked inside. `d` did not exist before this call, so
        # everything under it is ours to remove afterward either way.
        reattached_scratch = not had_beads_dir and had_database
        if reattached_scratch:
            self.create(name)

        held: list[Item] = []
        if beads_dir.is_dir():
            items = self.project(name).list(include_resolved=False)
            held = [i for i in items if i.status == "held"]

        if held:
            if reattached_scratch:
                # Leave the same state this call found: no directory.
                shutil.rmtree(d, ignore_errors=True)
            names = ", ".join(f"{i.id} (held by {i.holder!r})" for i in held)
            raise BeadsError(
                f"refusing to remove project {name!r}: {len(held)} item(s) currently "
                f"HELD -- {names}. An agent may be actively working this queue. "
                f"Resolve or reap the item(s) first, then remove again."
            )

        database_removed = drop_database(name) if had_database else False

        beads_removed = False
        directory_removed = False
        leftover: list[str] = []
        if reattached_scratch:
            # Entirely our own scaffold, created moments ago -- safe to
            # remove wholesale, unlike a directory that pre-dates this call.
            shutil.rmtree(d, ignore_errors=True)
            beads_removed = True
            directory_removed = True
        elif had_beads_dir:
            shutil.rmtree(beads_dir, ignore_errors=True)
            beads_removed = True
            remaining = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
            if remaining:
                leftover = remaining
            else:
                d.rmdir()
                directory_removed = True

        return RemovalReport(
            name=name,
            directory=d,
            had_beads_dir=had_beads_dir,
            had_database=had_database,
            beads_removed=beads_removed,
            database_removed=database_removed,
            directory_removed=directory_removed,
            leftover=leftover,
        )


@dataclass
class ProjectSummary:
    """One project's item counts, in OUR vocabulary -- the shared computation
    behind the CLI's `instances` command and the web dashboard (see
    `webapp.py`), so neither reinvents (or silently disagrees on) what
    "ready"/"held"/"intake" mean. Same rationale as `list_bounded`: one home
    for logic two callers both need.

    `status` is `"ok"` when the counts above were computed successfully, or
    a truncated `"ERROR: ..."` string (see `truncate_status`) when the
    project's database could not be read at all -- in which case every
    field below is `None`/empty, not zero, so a caller can never mistake
    "could not read" for "read as empty."

    `blocked`, `held_by`, and `last_activity` exist so a dashboard can show
    signals that actually VARY with real data instead of a constant that
    never changes (a design-review finding: a badge that always reads the
    same value carries no information -- see webapp.py's dashboard route
    for how these are used). `held_by` is the sorted, deduplicated list of
    current holders -- who to go ask, not just how many. `last_activity` is
    the most recent `updated_at` across every item (our own domain concept;
    not a Beads field itself), so a genuinely idle project reads differently
    from one with agents actively moving through it right now.
    """

    name: str
    status: str
    total: int | None = None
    ready: int | None = None
    held: int | None = None
    intake: int | None = None
    blocked: int | None = None
    held_by: list[str] = field(default_factory=list)
    last_activity: str | None = None


def project_summary(ws: Workspace, name: str) -> ProjectSummary:
    """Compute one project's `ProjectSummary` against the live `bd` project.

    Never raises -- a project whose database cannot be read reports
    `status="ERROR: ..."` (truncated) with the count fields left `None`,
    exactly like `cli.cmd_instances`'s prior per-project error handling.
    """
    try:
        items = ws.project(name).list(include_resolved=True)
    except BeadsError as e:
        return ProjectSummary(name=name, status=truncate_status(f"ERROR: {e}"))
    held_items = [i for i in items if i.status == "held"]
    updated_ats = [ts for i in items if (ts := i.raw.get("updated_at"))]
    return ProjectSummary(
        name=name,
        status="ok",
        total=len(items),
        ready=sum(1 for i in items if i.status == "open" and LANE_WORK in i.tags),
        held=len(held_items),
        intake=sum(1 for i in items if i.status == "open" and LANE_INTAKE in i.tags),
        blocked=sum(1 for i in items if i.status == "blocked"),
        held_by=sorted({i.holder for i in held_items if i.holder}),
        last_activity=max(updated_ats) if updated_ats else None,
    )


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
            r = _run_bounded(["bd", cmd, "--help"], env=_bd_env())
            blob = (r.stdout or "") + (r.stderr or "")
            _CAPS[cmd] = "unknown command" not in blob
    return dict(_CAPS)


def version() -> tuple[int, int, int]:
    p = _run_bounded(["bd", "--version"], env=_bd_env())
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", p.stdout or "")
    if not m:
        detail = _clean_bd_error(p.stdout or p.stderr, limit=120)
        raise BeadsError(f"cannot read bd version: {detail}")
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
