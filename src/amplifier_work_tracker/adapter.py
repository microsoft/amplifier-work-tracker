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
import uuid
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


def _map_status(raw: str | None) -> str:
    """Translate one raw bd status string into our vocabulary -- the same
    rule `Item.from_beads` applies to an item's own top-level `status`,
    factored out so the item-detail blocker chain's dependency/dependent
    entries (`Beads.get`'s enriched `links`) translate status the exact
    same way, never a second, drifting copy of `_STATUS_MAP.get(...)`.
    An unrecognized raw value passes through rather than being coerced --
    see `_STATUS_MAP`'s own comment."""
    raw = raw or ""
    return _STATUS_MAP.get(raw, raw or "unknown")


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

# Transient dolt/mysql CONNECTION-transport failures -- a different category
# from the serialization conflicts above, and from any bd DOMAIN error: the
# dolt server was momentarily unreachable, the socket dropped, or a pooled
# connection went bad. Retrying is the correct, expected response for these
# for exactly the same reason it is for a serialization conflict -- a real
# agent (not just the test suite) hitting a momentary dolt blip on ANY bd
# call should ride through it, not fail hard. `bd` today has no internal
# reconnect for this: it surfaces a connection drop as a plain non-zero exit,
# and `_run`'s serialization-only retry above passed that straight through.
#
# Matched conservatively against transport-layer signatures that can never
# appear in a legitimate bd domain result (a validation/not-found/logic
# error), so this can never turn a genuine failure into a false success --
# a persistent outage still exhausts the bounded retries below and surfaces
# the same non-zero result as before, just a couple of seconds later.
# "dolt server unreachable" + "connection refused" are bd 1.1.2's OWN
# captured wording for an unreachable server (measured directly, see
# fix/flaky-tests); the rest are the standard Go database/sql +
# go-sql-driver/mysql transient-connection strings dolt surfaces beneath bd.
_RETRYABLE_CONNECTION = (
    "dolt server unreachable",
    "connection refused",
    "connection reset",
    "broken pipe",
    "bad connection",
    "invalid connection",
    "i/o timeout",
    "server has gone away",
)
# Connection retries are bounded MUCH tighter than serialization retries: a
# transient blip clears in well under a second, whereas a genuinely-down
# server must fail FAST (a couple of seconds), not after 8 exponential
# backoffs (~40s) of hammering a server that isn't coming back. A few
# attempts, short capped backoff -- a few-second ceiling in total.
_MAX_CONNECTION_RETRIES = 4
_CONNECTION_RETRY_BACKOFF_CAP = 0.5

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


def _dolt_tables(db: str) -> tuple[list[str], list[str]]:
    """`(base_tables, views)` in database `db` on the shared dolt server,
    each sorted, read from `information_schema.TABLES` over the same direct
    SQL path `database_exists`/`drop_database` use.

    Views are returned separately because a faithful copy must create the
    base tables (and their foreign keys) before the views that select from
    them. `db` has already passed `NAME_RE`, so it carries no SQL-relevant
    character (see `database_exists`'s note on the same guarantee).
    """
    p = _dolt_sql(
        "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA='{db}' ORDER BY TABLE_TYPE, TABLE_NAME"
    )
    if p.returncode != 0:
        raise BeadsError(
            f"could not list tables of database {db!r} on the shared dolt server: "
            f"{_clean_bd_error(p.stderr or p.stdout)}"
        )
    base: list[str] = []
    views: list[str] = []
    for line in (p.stdout or "").splitlines()[1:]:  # drop CSV header
        if not line.strip():
            continue
        name, _, ttype = line.partition(",")  # table names carry no comma
        (views if ttype.strip() == "VIEW" else base).append(name.strip())
    return base, views


def _dolt_show_create(name: str, *, db: str, kind: str) -> str:
    """The `CREATE TABLE`/`CREATE VIEW` DDL for `db`.`name`, read via dolt's
    JSON result format so the multi-line DDL survives intact (CSV mangles
    embedded newlines and quotes). `kind` is ``"table"`` or ``"view"``.

    `--use-db <db>` (a global flag, placed before the `sql` subcommand like
    the other `_dolt_conn_args` flags) scopes `SHOW CREATE` to the source
    database, so the returned DDL names the object bare (no schema prefix)
    and can be replayed verbatim against the destination database.
    """
    verb = "TABLE" if kind == "table" else "VIEW"
    key = "Create Table" if kind == "table" else "Create View"
    p = _run_bounded(
        [
            "dolt",
            *_dolt_conn_args(),
            "--use-db",
            db,
            "sql",
            "-q",
            f"SHOW CREATE {verb} `{name}`",
            "-r",
            "json",
        ],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )
    if p.returncode != 0:
        raise BeadsError(
            f"could not read the schema of {db}.{name}: {_clean_bd_error(p.stderr or p.stdout)}"
        )
    try:
        rows = json.loads(p.stdout or "{}")["rows"]
        return str(rows[0][key])
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        raise BeadsError(f"could not parse the schema of {db}.{name}: {e}") from e


def _dolt_table_counts(db: str, tables: list[str]) -> dict[str, int]:
    """Row count of each of `tables` in database `db`, in one SQL round trip
    (a `UNION ALL` of per-table `COUNT(*)`), used to prove a copy is complete
    rather than merely non-erroring.
    """
    if not tables:
        return {}
    query = " UNION ALL ".join(
        f"SELECT '{t}' AS t, COUNT(*) AS n FROM `{db}`.`{t}`" for t in tables
    )
    p = _dolt_sql(query)
    if p.returncode != 0:
        raise BeadsError(
            f"could not count rows in database {db!r}: {_clean_bd_error(p.stderr or p.stdout)}"
        )
    counts: dict[str, int] = {}
    for line in (p.stdout or "").splitlines()[1:]:  # drop CSV header
        if not line.strip():
            continue
        name, _, n = line.partition(",")
        counts[name.strip()] = int(n.strip())
    return counts


def copy_database(src: str, dst: str) -> None:
    """Create database `dst` as a faithful copy of `src` on the shared dolt
    server: identical schema (every base table, view, and foreign key) and
    every row, verified complete before returning.

    Why a full copy rather than a rename: dolt 2.2.3 has no `RENAME DATABASE`
    / `ALTER DATABASE ... RENAME` (both are parse errors) and no server-side
    database-copy primitive -- `dolt dump` refuses outright in a remote/server
    context ("has not yet been migrated to function in a remote context").
    A schema+data copy over the ordinary SQL connection is the mechanism.
    Two behaviours, both verified live against the installed binary, make it
    a single statement: cross-database `INSERT ... SELECT` works, and a
    session-scoped `SET foreign_key_checks=0` lets the base tables be created
    and loaded in any order despite their foreign keys to `issues`/`wisps`.
    Running the whole script through one `dolt sql -q` keeps it in one
    session, so that `SET` and the `USE` both persist across its statements.

    Item ids and the issue prefix are preserved EXACTLY: the `issues`,
    `config`, `dependencies`, ... rows are copied verbatim, so no id is
    rewritten and no `discovered-from` link is broken. A renamed project's
    existing items keep their original ids, and new items continue on the
    original prefix (bd reads it from the copied `config` row).

    Atomic from the caller's view: on ANY failure -- schema read, the copy
    script, or the completeness check -- the partial `dst` (which may have
    been created with some-but-not-all tables before a failing statement) is
    dropped before raising, so the only outcomes are "`dst` is a complete
    copy" or "`dst` does not exist." `src` is never touched.
    """
    base, views = _dolt_tables(src)
    if not base and not views:
        raise BeadsError(
            f"cannot copy database {src!r}: it has no tables -- it is not a usable bd project."
        )
    statements = ["SET foreign_key_checks=0", f"CREATE DATABASE `{dst}`", f"USE `{dst}`"]
    statements += [_dolt_show_create(t, db=src, kind="table") for t in base]
    statements += [_dolt_show_create(v, db=src, kind="view") for v in views]
    statements += [f"INSERT INTO `{dst}`.`{t}` SELECT * FROM `{src}`.`{t}`" for t in base]
    script = ";\n".join(statements) + ";"

    # A large project's copy can be as slow as a real `bd init` (both are
    # bounded by the shared dolt server under load), so use the same larger
    # budget rather than the default per-call one.
    p = _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", script],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
        timeout=_BD_INIT_TIMEOUT_SECONDS,
    )
    if p.returncode != 0:
        _drop_database_best_effort(dst)
        raise BeadsError(
            f"copying database {src!r} to {dst!r} failed: {_clean_bd_error(p.stderr or p.stdout)}"
        )

    # Prove the copy is complete, not merely non-erroring: every base table's
    # row count in `dst` must equal `src`. A mismatch is treated as a failed
    # copy -- drop `dst` and raise, never leave a half-populated database.
    src_counts = _dolt_table_counts(src, base)
    dst_counts = _dolt_table_counts(dst, base)
    mismatches = [t for t in base if src_counts.get(t) != dst_counts.get(t)]
    if mismatches:
        example = mismatches[0]
        _drop_database_best_effort(dst)
        raise BeadsError(
            f"copying database {src!r} to {dst!r} left an incomplete copy: "
            f"{len(mismatches)} table(s) have a different row count (e.g. {example!r}: "
            f"{src_counts.get(example)} rows in the source, "
            f"{dst_counts.get(example)} in the copy). "
            f"The incomplete copy was dropped; {src!r} is untouched."
        )


def _drop_database_best_effort(name: str) -> None:
    """Drop `name`, swallowing any BeadsError -- for cleanup paths where a
    drop failure must not mask the ORIGINAL error being handled (a failed
    copy, a rolled-back rename). `drop_database` itself is the fail-loud
    version; this is only for use inside an `except`/rollback.
    """
    try:
        drop_database(name)
    except BeadsError:
        logger.warning("best-effort drop of database %r failed during cleanup", name)


def _repoint_beads_metadata(beads_dir: Path, db_name: str) -> None:
    """Point a project's local bd metadata at shared-server database
    `db_name`. bd records which database a `.beads` directory maps to in
    `.beads/metadata.json` (`dolt_database`); after a rename that single
    field is the one thing that must change for `bd` to resolve the renamed
    database (verified empirically: updating only this field, plus moving the
    directory and the database, makes `bd list`/`bd create` work against the
    new name). Every other key -- host, port, project id -- is unchanged.
    """
    meta_path = beads_dir / "metadata.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BeadsError(
            f"could not read bd metadata at {meta_path} to repoint it at database {db_name!r}: {e}"
        ) from e
    meta["dolt_database"] = db_name
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


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


def _uuid7_timestamp(v: object) -> datetime | None:
    """The millisecond-precision creation instant embedded in a UUIDv7
    identifier (RFC 9562: the first 48 bits are a big-endian Unix-epoch
    millisecond count) -- or `None` if *v* isn't a parseable UUIDv7.

    Why this exists: `bd comments --json`'s own `created_at` is truncated
    to whole SECONDS (the same precision gap `_history_events` works
    around for `created_at`/`closed_at` via `CommitDate` -- see its
    docstring), and empirically it isn't even a clean floor of the real
    time -- measured against bd 1.1.2, a comment created at 44.523s was
    reported `created_at` of the NEXT whole second (45), landing it AFTER
    a resolve whose `CommitDate` was 44.79s, i.e. inverting the real
    order. That is the residual this closes: in `Beads.activity`'s
    combined, reverse-chronological feed a comment that genuinely happened
    BEFORE a resolve would sort as if it happened after, because its
    coarse `created_at` rounded up past the resolve's millisecond
    `CommitDate`.

    bd's comment `id` is independently a UUIDv7 (verified against bd
    1.1.2's real output), and its embedded millisecond timestamp landed
    inside the true request/response window in every trial -- a real,
    precise clock reading `created_at` does not reliably give us. This is
    a bd-specific assumption (comment ids happen to be UUIDv7), so it
    lives here, in the one module allowed to know bd's exact shapes -- see
    AGENTS.md's "adapter seam." Falls back to `None` (never raises, never
    guesses) for anything that isn't a valid version-7 UUID, so an id
    shape change in a future bd release degrades to the coarser
    `created_at` rather than breaking.
    """
    if not isinstance(v, str):
        return None
    try:
        parsed = uuid.UUID(v)
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.version != 7:
        return None
    ms = int.from_bytes(parsed.bytes[0:6], "big")
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
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
        out["status"] = _map_status(d.get("status"))
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


def _is_active_blocker(dependency_type: str | None, raw_status: str | None) -> bool:
    """Does one raw bd dependency edge (`dependency_type`/`status` straight
    off `show --json`'s `dependencies`/`dependents` fields, BEFORE our
    status-vocabulary translation) count as a still-open `blocks`-type
    dependency -- i.e. actually blocking `claim_item`, and what the
    item-detail page's blocker chain (`Beads.get`'s enriched `links`)
    paints crimson?

    A raw bd status of anything other than `closed` counts as active: a
    blocker that is itself `blocked` or `deferred` still blocks; only a
    resolved (closed) one clears the way. Factored out of `_active_blockers`
    so the claim-refusal check and the item-detail blocker chain can never
    silently disagree on what \"still blocking\" means.
    """
    return dependency_type == "blocks" and raw_status != "closed"


def _active_blockers(item: Item) -> list[dict]:
    """Which of `item`'s forward dependencies are still-open `blocks`-type
    links -- i.e. actually blocking `claim_item`.

    Read straight from the raw `show` payload's `dependencies` field, which
    IS present without `--include-dependents` (that flag only gates the
    REVERSE direction -- ASSUMPTION show.dependents).
    """
    deps = item.raw.get("dependencies") or []
    return [
        d
        for d in deps
        if isinstance(d, dict) and _is_active_blocker(d.get("dependency_type"), d.get("status"))
    ]


def _retryable(blob: str) -> bool:
    low = blob.lower()
    return any(t.lower() in low for t in _RETRYABLE)


def _connection_retryable(blob: str) -> bool:
    """True if *blob* (a bd call's combined stdout+stderr) names a transient
    dolt/mysql CONNECTION-transport failure -- see `_RETRYABLE_CONNECTION`'s
    note for why these, and only these, are safe to ride through with a
    bounded retry. Deliberately distinct from `_retryable` (serialization
    conflicts) so the two retry budgets in `Beads._run` stay independent.
    """
    low = blob.lower()
    return any(t in low for t in _RETRYABLE_CONNECTION)


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
    measured fact, not an inference from bd's own default page size.

    `offset` is the (clamped-to-nonnegative) window start this result was
    sliced from -- `0` for every existing caller that never passed one, so
    this field's addition changes nothing for the CLI's `list` subcommand
    or the `work_list` tool. It exists so a caller doing real pagination
    (the web UI's project item table) can compute "is there a previous
    page" (`offset > 0`) without reinventing the window math this class
    already tracks."""

    items: list[Item]
    total_count: int
    returned_count: int
    truncated: bool
    limit: int
    requested_limit: int | None
    offset: int = 0


# Bound on how many `bd history` commits `Beads.activity` will ever read for
# one item -- the same defensive-bound discipline `LIST_MAX_LIMIT` applies
# to `list_bounded`, sized generously (an item touched this many times is
# already an extreme outlier) rather than tuned to any measured case.
HISTORY_LIMIT = 200


@dataclass(frozen=True)
class ActivityEvent:
    """One entry in an item's real activity timeline (`Beads.activity`) --
    every field here is substantiated by bd itself (a real `bd history`
    status/custody transition, or a real `bd comments` entry), never
    synthesized. See `Beads.activity`'s docstring for exactly what bd
    exposes and the honest gap where it doesn't.

    `kind` is one of `\"created\" | \"status\" | \"comment\" | \"resolved\"` --
    the item-detail activity feed (webapp.py's `_activity_feed_html`)
    switches on it for icon/wording only; every kind renders through the
    same list.
    """

    kind: str
    at: datetime
    actor: str | None
    summary: str
    detail: str | None = None


def _history_signature(issue: dict) -> tuple[object, object]:
    """The `(status, assignee)` pair that decides whether two consecutive
    `bd history` entries represent a REAL transition, or just another dolt
    commit that happened to touch this item's repo without changing the
    item itself (see `_history_events`'s docstring for why that happens)."""
    return (issue.get("status"), issue.get("assignee"))


def _history_events(history: list) -> list[ActivityEvent]:
    """Turn bd's own per-commit `bd history --json` payload into genuine
    lifecycle events -- never a fabricated row for a commit where nothing
    about the item actually changed.

    `bd history` is NOT a clean domain-event log: it is one entry per dolt
    commit that touched this item's repo, each carrying a FULL snapshot of
    the issue as of that commit (empirically verified against bd 1.1.2 --
    see this module's own investigation notes / the PR that added this).
    Adding a comment, for instance, produces a new commit -- and therefore
    a new history entry -- even though the issue's own status/assignee are
    unchanged at that commit. Consecutive entries with an IDENTICAL
    `(status, assignee)` signature are exactly that noise and are collapsed
    into a single event here, using only the OLDEST entry of each run (so a
    later, duplicate commit for the same real state is never mistaken for
    a second occurrence of the same event).

    Entries are read oldest-first so \"the first entry we see\" always means
    \"the oldest\" (bd itself returns newest-first). The three event shapes
    this produces:

      - The very first entry becomes a `\"created\"` event, attributed from
        the issue's own `created_by` (a real field on every entry, not
        inferred).
      - A transition INTO our `\"held\"` status with a real assignee becomes
        a `\"status\"` event summarized `\"Claimed\"`, attributed to that
        assignee -- the best signal bd gives for \"who\"; not literally
        proof this exact identity ran the claim command, but the item's own
        real recorded assignee at that snapshot (same convention already
        established elsewhere in this app for holder-persists-after-
        resolution).
      - A transition INTO our `\"resolved\"` status becomes a `\"resolved\"`
        event, `detail` carrying that snapshot's own `close_reason`.
      - Any other transition (open<->blocked/deferred, a reassignment that
        doesn't change status, a held item released back to open, etc.)
        becomes a generic `\"status\"` event naming the before/after states
        in OUR vocabulary.

    Every event's `at` is `CommitDate` -- the commit's own timestamp,
    guaranteed present here (see the skip below) and carrying millisecond
    precision -- never `created_at`/`closed_at`. Those domain fields are
    real but bd truncates them to whole SECONDS, while a fast lifecycle
    (create, claim, comment, resolve) routinely completes within a single
    wall-clock second. Two whole-second-truncated fields landing on the
    same second are a genuine tie, and `Beads.activity`'s sort breaks ties
    by `list.sort`'s stability -- i.e. by INSERTION order, not real time --
    which let `created` (always inserted first) occasionally sort as newer
    than `resolved` (inserted last), even though `resolved` always
    corresponds to a strictly later dolt commit. `CommitDate` is monotonic
    per commit and has no such precision gap, so using it removes the tie
    at its root rather than papering over one occurrence of it (see
    fix/flaky-tests for the reproduction: a build using created_at/closed_at
    here failed this ordering on ~17/40 runs against a real server).

    A history entry with no `CommitDate` at all is skipped (nothing to sort
    or timestamp it by) rather than guessed at.
    """
    entries = [
        e
        for e in history
        if isinstance(e, dict) and isinstance(e.get("Issue"), dict) and e.get("CommitDate")
    ]
    entries.sort(key=lambda e: e["CommitDate"])

    events: list[ActivityEvent] = []
    prev_sig: tuple[object, object] | None = None
    for entry in entries:
        issue = entry["Issue"]
        sig = _history_signature(issue)
        if sig == prev_sig:
            continue  # same real state as the previous entry -- comment/no-op commit
        at = _parse_bd_timestamp(entry.get("CommitDate"))
        if at is None:
            prev_sig = sig
            continue
        our_status = _map_status(issue.get("status"))
        assignee = issue.get("assignee")
        if prev_sig is None:
            events.append(
                ActivityEvent(
                    kind="created",
                    at=at,
                    actor=issue.get("created_by"),
                    summary="Created",
                )
            )
        elif our_status == "resolved":
            events.append(
                ActivityEvent(
                    kind="resolved",
                    at=at,
                    actor=assignee,
                    summary="Resolved",
                    detail=issue.get("close_reason"),
                )
            )
        elif our_status == "held" and assignee:
            events.append(ActivityEvent(kind="status", at=at, actor=assignee, summary="Claimed"))
        else:
            prev_status = _map_status(prev_sig[0]) if isinstance(prev_sig[0], str) else None
            summary = (
                f"Status changed: {prev_status} \u2192 {our_status}"
                if prev_status
                else f"Status: {our_status}"
            )
            events.append(ActivityEvent(kind="status", at=at, actor=assignee, summary=summary))
        prev_sig = sig
    return events


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
          - `resolved_daily` (list[int] | None): see `_daily_resolved_counts`.
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
    # Throughput is counted only from resolutions that actually carry a
    # readable `closed_at`. A genuine 0 -- a project with no resolutions, or
    # with dated resolutions but none inside the window -- is a real,
    # meaningful answer and stays 0. But a project that HAS resolved items
    # while recording NO `closed_at` on any of them cannot be measured at
    # all: reporting 0 there would be a fabricated zero, so both figures are
    # `None` instead -- the same "could not read" vs "read as empty"
    # distinction `oldest_unclaimed_age_seconds` already draws.
    resolved_closed_ats = [
        i.closed_at for i in items if i.status == "resolved" and i.closed_at is not None
    ]
    any_resolved = any(i.status == "resolved" for i in items)
    resolved_24h: int | None
    resolved_7d: int | None
    if any_resolved and not resolved_closed_ats:
        resolved_24h = None
        resolved_7d = None
    else:
        resolved_24h = sum(1 for t in resolved_closed_ats if (now - t) <= timedelta(hours=24))
        resolved_7d = sum(1 for t in resolved_closed_ats if (now - t) <= timedelta(days=7))
    # "Last activity" is the most recent timestamp of ANY kind across every
    # item -- `updated_at`, `closed_at`, or `created_at` -- so the column
    # reflects real movement even for an item bd happened to record only a
    # creation or close time for. `updated_at` is normally the most recent of
    # the three, but taking the max across all of them is honest regardless of
    # which fields a given item carries, and never leaves the column empty
    # when the project plainly has activity.
    activity_times = [
        t for i in items for t in (i.updated_at, i.closed_at, i.created_at) if t is not None
    ]
    return {
        "oldest_unclaimed_age_seconds": max(ready_ages) if ready_ages else None,
        "resolved_24h": resolved_24h,
        "resolved_7d": resolved_7d,
        "resolved_daily": _daily_resolved_counts(items, now=now),
        "last_activity": max(activity_times).isoformat() if activity_times else None,
    }


#: How many trailing days the throughput sparkline (`_daily_resolved_counts`)
#: covers -- long enough to show a real trend line, short enough that a
#: quiet project's sparkline is still mostly-empty rather than a wall of zeros.
DAILY_THROUGHPUT_WINDOW = 14


def _daily_resolved_counts(
    items: list[Item], *, days: int = DAILY_THROUGHPUT_WINDOW, now: datetime | None = None
) -> list[int] | None:
    """Resolutions per calendar day for the trailing `days` days, oldest to
    newest -- the per-day breakdown `resolved_24h`/`resolved_7d` (aggregate
    windows only) cannot supply, and the throughput sparkline's real data
    source. Never a fabricated shape: this is a real histogram of the SAME
    `closed_at` timestamps `resolved_24h`/`resolved_7d` already read, just
    bucketed by day instead of summed into one window.

    Same honesty gap as `resolved_24h`/`resolved_7d`: a project that has
    resolved items but records NO `closed_at` on any of them cannot be
    measured at all, so this returns `None` (never a fabricated all-zero
    list) in that case -- a caller summing this across projects must
    exclude such a project the same way it already excludes it from
    `resolved_24h`/`resolved_7d`. A project with no resolutions in the
    window, or none at all, is a real all-zero list (a genuine reading,
    not a gap).
    """
    now = now or datetime.now(UTC)
    resolved_closed_ats = [
        i.closed_at for i in items if i.status == "resolved" and i.closed_at is not None
    ]
    any_resolved = any(i.status == "resolved" for i in items)
    if any_resolved and not resolved_closed_ats:
        return None
    counts = [0] * days
    for t in resolved_closed_ats:
        age_days = (now - t).total_seconds() / 86400.0
        # bucket 0 == oldest day in the window, bucket `days-1` == today;
        # a negative age (small clock skew) still lands in "today", never
        # dropped, matching `_ready_age_bucket_label`'s own skew guard.
        idx = days - 1 if age_days < 0 else days - 1 - int(age_days)
        if 0 <= idx < days:
            counts[idx] += 1
    return counts


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
        """Run one `bd` subprocess, riding through two distinct classes of
        transient, retryable failure (see the module-level `_RETRYABLE` /
        `_RETRYABLE_CONNECTION` notes for why each is a real, expected blip
        rather than a masked failure):

          - Dolt SERIALIZATION conflicts (Beads manufactures these so claims
            serialize): up to `_MAX_RETRIES` attempts, exponential backoff,
            then RAISE `BeadsError` -- unchanged, load-bearing behavior.
          - Dolt CONNECTION-transport blips (server momentarily unreachable,
            socket dropped): a much tighter bounded retry (`_MAX_CONNECTION_
            RETRIES`, short capped backoff, few-second ceiling), then RETURN
            the failed process as-is -- so a genuinely-down server surfaces
            exactly the same non-zero result callers already handle today,
            never a new exception type, just a couple of seconds later.

        The two budgets are independent counters: a connection blip must not
        silently eat the serialization-retry budget (or vice versa), and the
        connection path must fail FAST on a persistent outage rather than
        inheriting the serialization path's ~40s exponential ceiling.
        """
        last = None
        serialization_attempt = 0
        connection_attempt = 0
        while True:
            p = _run_bounded(["bd", *args], env=self._env(actor))
            last = p
            blob = (p.stdout or "") + (p.stderr or "")
            if p.returncode != 0 and _connection_retryable(blob):
                if connection_attempt >= _MAX_CONNECTION_RETRIES:
                    return p  # transient-connection budget spent -- surface it, as before
                backoff = min(_CONNECTION_RETRY_BACKOFF_CAP, 0.1 * (2**connection_attempt))
                time.sleep(backoff * (0.5 + os.urandom(1)[0] / 255))
                connection_attempt += 1
                continue
            if _retryable(blob):
                if serialization_attempt >= _MAX_RETRIES - 1:
                    break
                time.sleep(0.15 * (2**serialization_attempt) * (0.5 + os.urandom(1)[0] / 255))
                serialization_attempt += 1
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

    def update(
        self,
        item_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        acceptance: str | None = None,
        design: str | None = None,
        actor: str | None = None,
    ) -> Item:
        """Edit an item's own free-text fields -- title, description,
        acceptance criteria, design notes -- via `bd update`'s matching
        flags. Deliberately narrow: this is content editing, not lifecycle
        (status/holder/claim/resolve all have their own dedicated,
        FENCED methods above and are never touched here).

        Every argument is `None`-means-"leave unchanged" (bd's own
        semantics for these flags: passing none of them is a no-op update,
        and passing one only touches that one field) -- there is no way to
        CLEAR a field to empty through this method, only to set it to new
        non-empty text, matching `create`'s own optional-field convention
        and the web form this backs (which always submits every field, so
        "leave unchanged" in practice only matters for a caller that
        doesn't).

        Verifies the write landed by reading the item back, the same
        discipline `resolve` applies ("exit code is not proof") -- a
        successful `bd update` exit with a title that didn't actually
        change would otherwise look identical to a silent no-op.
        """
        args = ["update", item_id]
        if title is not None:
            args += ["--title", title]
        if description is not None:
            args += ["--description", description]
        if acceptance is not None:
            args += ["--acceptance", acceptance]
        if design is not None:
            args += ["--design", design]
        if len(args) == 2:  # nothing to change -- avoid a no-op `bd update` call/verify
            return self.get(item_id)
        p = self._run(args, actor=actor)
        if p.returncode != 0:
            raise BeadsError(f"update {item_id}: {_clean_bd_error(p.stderr or p.stdout)}")
        back = self.get(item_id)
        if (
            (title is not None and back.title != title)
            or (description is not None and back.description != description)
            or (acceptance is not None and back.acceptance != acceptance)
            or (design is not None and back.design != design)
        ):
            raise BeadsError(
                f"update {item_id} reported success but the change did not land -- "
                f"exit code is not proof; see this method's docstring."
            )
        return back

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
        """Read one item, optionally with its dependency graph attached as
        `Item.links`.

        Each link entry carries `id`/`direction`/`type` (unchanged from
        before -- `supervisor.notify_project`/`cli.cmd_notify`/`gateway`/
        `contract` all key off exactly these three fields and nothing
        else) PLUS `title`/`status`/`holder`/`created_by`/`blocking`, added
        for the item-detail page's blocker chain (see webapp.py's
        `_blocker_sections_html`). The two directions carry different
        depth of real data -- this is bd's own asymmetry, not a choice
        made here:

          - `direction: "from"` (this item's own `dependencies` -- what it
            depends on / is blocked by) embeds the FULL referenced item, so
            `title`/`status`/`holder`/`created_by` are real and populated.
          - `direction: "to"` (`dependents` -- what depends on THIS item,
            only present with `--include-dependents`, ASSUMPTION
            show.dependents) is bd's own deliberately lean cross-reference
            for exactly this flag (its own `--help` warns it \"may be slow
            on hub beads\"): `title`/`status` are real, but `holder`/
            `created_by` are always `None` here -- bd's dependents payload
            never includes `assignee`/`created_by` at all, and its
            `created_at`/`updated_at` are zero-value placeholders (verified
            empirically against bd 1.1.2), so those two are never even
            attempted. Honest degrade, not a fetch-per-dependent N+1 --
            see this method's own docstring reference above.

        `blocking` is `True` only for a `direction: \"from\"` entry that is
        a still-open `blocks`-type dependency (`_is_active_blocker`, the
        SAME check `claim_item` uses to refuse a claim) -- what the
        item-detail page paints crimson. Computed for `to`-direction
        entries too (same helper, same fields), for symmetry; nothing in
        this app currently colors that direction.
        """
        args = ["show", item_id]
        if with_links:
            # ASSUMPTION show.dependents -- reverse links are omitted by default.
            args += ["--include-dependents"]
        d = self._json(args)
        d = d[0] if isinstance(d, list) else d
        if not isinstance(d, dict):
            raise BeadsError(f"show {item_id} returned no object")
        it = Item.from_beads(d)

        def _link(x: dict, direction: str) -> dict:
            raw_status = x.get("status")
            return {
                "id": x.get("id"),
                "direction": direction,
                "type": x.get("dependency_type"),
                "title": x.get("title"),
                "status": _map_status(raw_status) if raw_status else None,
                "holder": x.get("assignee"),
                "created_by": x.get("created_by"),
                "blocking": _is_active_blocker(x.get("dependency_type"), raw_status),
            }

        it.links = [_link(x, "from") for x in (d.get("dependencies") or [])] + [
            _link(x, "to") for x in (d.get("dependents") or [])
        ]
        return it

    def activity(self, item_id: str, *, limit: int = HISTORY_LIMIT) -> list[ActivityEvent]:
        """The real, reverse-chronological activity timeline for one item --
        for the item-detail page's activity feed (webapp.py's
        `_activity_feed_html`).

        Two bd reads, both real:
          - `bd history <id> --json` -- every commit that touched this
            item's repo, each a full snapshot of the issue at that commit.
            Diffed into genuine transitions by `_history_events` (see its
            own docstring for exactly how, and why a naive one-row-per-
            commit rendering would be dishonest).
          - `bd comments <id> --json` -- real comments, author/text/
            timestamp straight from bd, one event each.

        Read-only: never claims, mutates, or touches custody -- same
        contract as `get_readonly`, just a different bd subcommand pair.

        Degrades honestly rather than failing the whole item-detail page:
        if `bd history` (or `bd comments`) itself errors -- an unexpected
        bd failure, not a normal \"nothing happened yet\" empty result --
        that source is simply omitted from the timeline (logged, not
        raised) and whatever the other source has is still returned. An
        activity feed is a page enrichment, not a load-bearing read; a
        transient bd hiccup on it must never take down title/description/
        acceptance/design/status, which this same page also renders.
        """
        events: list[ActivityEvent] = []
        try:
            hist = self._json(["history", item_id, "--limit", str(limit)])
            if isinstance(hist, list):
                events += _history_events(hist)
        except BeadsError:
            logger.warning(
                "activity(%s): `bd history` unavailable, degrading to comments only", item_id
            )

        try:
            comments = self._json(["comments", item_id])
            if isinstance(comments, list):
                for c in comments:
                    if not isinstance(c, dict):
                        continue
                    at = _uuid7_timestamp(c.get("id")) or _parse_bd_timestamp(c.get("created_at"))
                    if at is None:
                        continue
                    events.append(
                        ActivityEvent(
                            kind="comment",
                            at=at,
                            actor=c.get("author"),
                            summary="Comment",
                            detail=c.get("text"),
                        )
                    )
        except BeadsError:
            logger.warning("activity(%s): `bd comments` unavailable", item_id)

        events.sort(key=lambda e: e.at, reverse=True)
        return events

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

    def list_bounded(
        self, *, status: str | None = None, limit: int | None = None, offset: int = 0
    ) -> ListResult:
        """Read-only, explicitly-capped item listing for human/agent
        consumption -- the shared implementation behind both the CLI's
        `list` subcommand and the `work_list` tool, so neither reinvents
        (or silently disagrees on) the capping policy.

        Always fetches the FULL matching set first (`limit=0` -- bd's own
        "unlimited") to learn the true total, THEN windows/caps in Python.
        This is what makes `truncated` a fact rather than a guess: a caller
        that only ever saw bd's own default-50-item page would have no way
        to know whether 50 was the true total or a silent truncation.

        `limit=None` uses `LIST_DEFAULT_LIMIT`; any requested limit is
        clamped to `[1, LIST_MAX_LIMIT]` -- silently for the lower bound (a
        request for 0 or negative items is nonsensical, not meaningful
        input worth reporting on), but ALWAYS reported via
        `ListResult.requested_limit` vs `ListResult.limit` when the upper
        bound clamps, so a caller asking for more than the max learns that
        distinctly from asking for exactly 500 -- a cap must never be silent.

        `offset` (default 0, clamped to nonnegative) shifts the returned
        window without changing the page size -- real pagination, not a
        second cap. This is additive: every existing caller that never
        passed `offset` sees byte-identical behavior (window starts at 0,
        exactly as before). It exists because a project with more items
        than one page's worth was previously only reachable up to
        `LIST_DEFAULT_LIMIT`/`LIST_MAX_LIMIT` items -- there was no way to
        ask for the NEXT window at all, only a bigger one. See the web
        UI's project-listing route for the actual pagination controls this
        makes possible.
        """
        effective = LIST_DEFAULT_LIMIT if limit is None else max(1, min(limit, LIST_MAX_LIMIT))
        start = max(0, offset)
        items = self.list(status=status, include_resolved=(status is None), limit=0)
        capped = items[start : start + effective]
        return ListResult(
            items=capped,
            total_count=len(items),
            returned_count=len(capped),
            truncated=(start + len(capped)) < len(items),
            limit=effective,
            requested_limit=limit,
            offset=start,
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


@dataclass
class RenameReport:
    """What `Workspace.rename` actually did -- see its docstring for the full
    contract. `item_count` is the number of items in the renamed project
    (proven readable under the new name before the rename committed);
    `old_database_dropped` records that the source database was removed, so a
    caller can see no orphan was left behind.
    """

    old: str
    new: str
    directory: Path
    item_count: int
    old_database_dropped: bool


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

    def rename(self, old: str, new: str) -> RenameReport:
        """Rename a project safely: its on-disk directory, its shared-server
        database, and bd's local metadata, together -- atomic from the
        caller's view, mirroring `create`'s self-heal discipline.

        The class of bug this closes: a naive rename that moves only the
        directory leaves the database still named `old` on the shared server
        -- exactly the kind of server-side residue that "burned" a name
        before (see `create`/`remove`'s docstrings). This renames BOTH, and
        rolls back completely on any failure rather than leaving a
        half-renamed project or an orphan database.

        Refuses (no override, before any mutation) when:
          - `new` is not a valid project name (same `NAME_RE` as `create` --
            dots/hyphens rejected, since a dotted database name is unusable);
          - `old` and `new` are the same name;
          - `new` is already taken -- a directory OR a database of that name
            exists (same residue caution `create` applies);
          - `old` does not exist, or is in a split state (a directory without
            its database, or vice versa) that cannot be renamed safely;
          - any item in `old` is currently HELD -- an agent may be actively
            working it, the same safety property `remove` enforces.

        Mechanism (see `copy_database`): dolt has no `RENAME DATABASE`, so the
        database is renamed by copying `old` to `new` (full schema + data,
        verified complete), then dropping `old` once `new` is proven live.
        Item ids and the issue prefix are preserved exactly -- existing items
        keep their ids, new items continue on the original prefix.

        Rollback: the source database is dropped only at the very end, after
        the copy, the directory move, the metadata repoint, and a real
        `bd list` under the new name have all succeeded. A failure anywhere
        before that restores the original state -- the directory is moved
        back, its metadata is restored, and the copied `new` database is
        dropped -- so `old` is left exactly as it was found.
        """
        if not NAME_RE.match(new):
            raise BeadsError(
                f"invalid new project name {new!r}: must match {NAME_RE.pattern}. "
                f"Dots and hyphens are rejected deliberately -- they produce a database "
                f"that reports success and then fails every later command."
            )
        if old == new:
            raise BeadsError(f"cannot rename project {old!r} to itself")
        if not NAME_RE.match(old):
            raise BeadsError(f"invalid project name {old!r}: must match {NAME_RE.pattern}")

        old_dir = self.path(old)
        new_dir = self.path(new)
        old_has_dir = (old_dir / ".beads").is_dir()
        old_has_db = database_exists(old)

        if not old_has_dir and not old_has_db:
            raise BeadsError(
                f"project {old!r} not found: no {old_dir / '.beads'} directory and no "
                f"database named {old!r} on the shared dolt server. Nothing to rename."
            )
        if not old_has_dir or not old_has_db:
            raise BeadsError(
                f"project {old!r} is in a split state -- directory "
                f"{'present' if old_has_dir else 'missing'}, database "
                f"{'present' if old_has_db else 'missing'} -- and cannot be safely renamed. "
                f"Resolve it first: `amplifier-work-tracker remove {old} --yes` (which handles "
                f"both halves), then re-create."
            )
        if (new_dir / ".beads").is_dir() or database_exists(new):
            raise BeadsError(
                f"cannot rename {old!r} to {new!r}: a project or database named {new!r} "
                f"already exists. Choose a different name, or remove {new!r} first "
                f"(`amplifier-work-tracker remove {new} --yes`)."
            )

        held = [i for i in self.project(old).list(include_resolved=False) if i.status == "held"]
        if held:
            names = ", ".join(f"{i.id} (held by {i.holder!r})" for i in held)
            raise BeadsError(
                f"refusing to rename project {old!r}: {len(held)} item(s) currently HELD -- "
                f"{names}. An agent may be actively working this queue. Resolve or reap the "
                f"item(s) first, then rename again."
            )

        # --- mutate, with full rollback until the final commit (dropping old) ---
        db_copied = False
        moved = False
        repointed = False
        try:
            copy_database(old, new)  # creates `new`; self-cleans its own partial residue on failure
            db_copied = True
            shutil.move(str(old_dir), str(new_dir))
            moved = True
            _repoint_beads_metadata(new_dir / ".beads", new)
            repointed = True
            item_count = len(self.project(new).list(include_resolved=True))  # prove it answers
        except BaseException:
            # Restore the original state, in reverse order, best-effort. Each
            # step is guarded so a secondary failure never masks the original.
            if moved:
                try:
                    shutil.move(str(new_dir), str(old_dir))
                except Exception:  # noqa: BLE001 -- best-effort rollback; original error re-raised below
                    logger.warning("rollback: could not move %s back to %s", new_dir, old_dir)
            if repointed:
                # After the move-back the directory is at old_dir again; put
                # its metadata back to `old` so the untouched `old` database
                # still resolves.
                try:
                    _repoint_beads_metadata(old_dir / ".beads", old)
                except Exception:  # noqa: BLE001 -- best-effort rollback
                    logger.warning("rollback: could not restore metadata for %s", old)
            if db_copied:
                _drop_database_best_effort(new)
            raise

        old_database_dropped = drop_database(old)
        return RenameReport(
            old=old,
            new=new,
            directory=new_dir,
            item_count=item_count,
            old_database_dropped=old_database_dropped,
        )


#: Real-world day age bands for `ready_age_buckets` -- see that field's
#: docstring. Fixed, not rescaled to the workspace's current max: "arrived
#: today" and "waited a week" should mean the same thing on a calm day and
#: a bad one.
#:
#: Each entry is `(label, lo, hi)` interpreted as the HALF-OPEN day range
#: `[lo, hi)` (the last band's `hi` is `None` -- unbounded above). Read this
#: way the bands TILE the whole timeline with no gaps, so a floor-day
#: reading of every label is exact: "0-1" == days 0-1 == `[0, 2)`, "2-3" ==
#: `[2, 4)`, "4-6" == `[4, 7)`, "7+" == `[7, ..)`. The earlier bounds
#: (`("0-1", 0, 1)` ... with an INCLUSIVE `d <= hi` test) left holes between
#: the bands: an item aged 1.5, 3.5 or 6.5 days matched NO band and was
#: silently dropped from the histogram. Measured on the live workspace that
#: dropped 26 of 104 ready items -- exactly the gap between the dashboard's
#: "READY" total and its heartbeat's "unclaimed items" total. See
#: `_ready_age_bucket_label` for the tiling that closes it.
READY_AGE_BUCKETS = (("0-1", 0, 2), ("2-3", 2, 4), ("4-6", 4, 7), ("7+", 7, None))

#: Bucket key for ready items with no readable `created_at`. Kept DISTINCT
#: from every age band so an undated item is never fabricated an age, yet is
#: still counted -- this is what lets `sum(ready_age_buckets.values())`
#: equal `ready` for EVERY project, undated items included (see
#: `_ready_age_buckets`). Normally 0 (the live workspace dates every ready
#: item); it exists so a single malformed item can never silently
#: reintroduce the two-totals discrepancy.
UNKNOWN_READY_AGE = "unknown"

# Health values for `ProjectSummary.status`. A project is `STATUS_OK` only
# when its database was actually read; each other value names a DISTINCT
# unhealthy state so a dashboard can never collapse "still being created" or
# "broken by a create that never finished" into a healthy "0 items / ok"
# (measured outage, 2026-08-15: `instances` reported a half-created project
# as `ok` while its `.create.lock` sat right there, unconsulted). An
# UNREADABLE database keeps the pre-existing `"ERROR: ..."` convention -- a
# truncated diagnostic string, distinct from all three tokens below -- rather
# than a fixed token, because there the diagnostic text is the actionable
# part. Callers should treat "healthy" as `status == STATUS_OK`, never as
# "not an error string".
STATUS_OK = "ok"
STATUS_CREATING = "creating"  # a `new` for this project is in progress right now
STATUS_BROKEN = "broken"  # a previous `new` never finished; heals on the next `new`


@dataclass
class ProjectSummary:
    """One project's item counts, in OUR vocabulary -- the shared computation
    behind the CLI's `instances` command and the web dashboard (see
    `webapp.py`), so neither reinvents (or silently disagrees on) what
    "ready"/"held"/"intake"/"blocked" mean, or what "oldest unclaimed"/
    "resolved recently" mean (that half comes straight from
    `project_activity`, folded in below rather than recomputed a second way).

    `status` is one of: `STATUS_OK` (`"ok"`) when the counts below were
    computed successfully; `STATUS_CREATING`/`STATUS_BROKEN` when the project
    is mid-creation or was left broken by a `new` that never finished (read
    from `Workspace.creation_state`, consulted BEFORE any item read so a
    half-created project is never mistaken for a healthy empty one); or a
    truncated `"ERROR: ..."` string (see `truncate_status`) when the
    database exists but could not be read at all. In EVERY non-`ok` case
    every field below is `None`/empty, not zero, so a caller can never
    mistake "not healthy" for "read as empty."

    `ready` vs "unclaimed" vs `held`: in this system an OPEN work-lane item
    IS an unclaimed, ready-to-claim work item -- there is no third state
    between "open" and "held", so "ready" and "unclaimed" are the SAME set,
    reported as the ONE number `ready` (not two subtly different ones). `held`
    is the disjoint set of items currently claimed and in progress. This is
    the reconciliation of a dashboard that once showed "READY" and "unclaimed
    items" as two different totals for that one set -- see `ready_age_buckets`
    below and `_ready_age_buckets` for why they had drifted.

    `blocked`, `held_by`, and `last_activity` exist so a dashboard can show
    signals that actually VARY with real data instead of a constant that
    never changes (a design-review finding: a badge that always reads the
    same value carries no information -- see webapp.py's dashboard route
    for how these are used). `held_by` is the sorted, deduplicated list of
    current holders -- who to go ask, not just how many.

    `held_stale` is the subset of `held` whose custody signal is currently
    RECLAIM-ELIGIBLE -- computed via `custody.reclaim_eligible` verbatim,
    the EXACT function `supervisor.reap_project` calls to decide what it
    actually reclaims. This is a read-only reuse of that same policy, at
    zero extra `bd` cost (derived from the SAME `held_items` this function
    already builds from its one `list()` call) -- never a second,
    independently-guessed staleness rule that could drift from what the
    real reaper does. A subset of `held`, not additive to it: a stale hold
    is still a held item, just one whose renewal has lapsed (or that has
    no custody record at all -- see `custody.reclaim_eligible`'s own
    "no custody record" path, which counts as stale here too).

    `last_activity` is `project_activity`'s field verbatim -- the most recent
    activity timestamp of ANY kind (`updated_at`/`closed_at`/`created_at`)
    across every item, as an ISO string. There used to be a SECOND,
    independent computation of "last activity" here, over the raw
    `updated_at` strings rather than the parsed `Item` datetimes
    `project_activity` uses. Two homes for one concept is exactly what
    `list_bounded`'s own docstring warns against; this is that reconciliation,
    now that both live in the same module and can share one computation.

    `oldest_unclaimed_age_seconds`, `resolved_24h`, `resolved_7d` are
    `project_activity`'s other three fields, folded in here so a caller that
    wants "this project's health" gets the counts AND the aging/throughput
    figures from one function call -- see `project_activity`'s own docstring
    for exactly what each means, why a `None` age is never coerced to 0, and
    why throughput is `None` (not 0) for a project that records resolutions
    but no `closed_at` timestamps.

    `ready_age_buckets` is a real-world-day histogram of ready items' ages
    (see `READY_AGE_BUCKETS`) whose values sum to EXACTLY `ready` -- every
    ready item lands in one band, and any undated one in the `UNKNOWN_READY_AGE`
    bucket, so a dashboard-wide heartbeat built by summing these across every
    project can never disagree with the summed `ready` total again (the
    "READY 104 / unclaimed 76" split this reconciles). Derived from the SAME
    `items` list this function already read; `None` when the project's
    database could not be read (same "unreadable, not empty" convention as
    every other field here).

    `blocked_stale` is the subset of `blocked` that is NEEDLESSLY blocked --
    an item whose status is `blocked` yet which has NO still-active `blocks`
    dependency left (`_active_blockers` is empty: every upstream blocker is
    already resolved, or none was ever recorded). This is the "stale blocker
    chain" signal a ranked attention queue treats as MORE urgent than a
    genuinely-blocked item: it needs nothing but an unblock. Derived from the
    SAME `items` list (each item's `raw["dependencies"]` carries the edge
    type + upstream status `bd list` already returns), at zero extra `bd`
    cost. A subset of `blocked`, never additive to it. Safe by construction:
    a `blocks` edge whose upstream status could not be read counts as still
    active (`_is_active_blocker`), so an item is only ever called stale on
    real evidence, never on missing data.

    `held_stale_oldest_age_seconds` instruments HOW LONG the worst custody
    breach has gone unattended: the maximum "seconds since last renewal"
    (`custody.age_seconds(last_seen)`) among the `held_stale` holds that
    actually carry a custody record. `None` when nothing is stale, or when
    the only stale holds have no custody record at all (the "claimed but
    never renewed" path -- reclaim-eligible, but with no `last_seen` to age
    from, so no honest duration exists). This is the time-to-notice anchor
    for the top-tier alarm: a custody breach's age is the clock a human's
    notice is measured against.
    """

    name: str
    status: str
    total: int | None = None
    ready: int | None = None
    held: int | None = None
    intake: int | None = None
    blocked: int | None = None
    resolved: int | None = None
    deferred: int | None = None
    held_stale: int | None = None
    held_by: list[str] = field(default_factory=list)
    last_activity: str | None = None
    oldest_unclaimed_age_seconds: float | None = None
    resolved_24h: int | None = None
    resolved_7d: int | None = None
    ready_age_buckets: dict[str, int] | None = None
    blocked_stale: int | None = None
    held_stale_oldest_age_seconds: float | None = None
    resolved_daily: list[int] | None = None


def _ready_age_bucket_label(days: float) -> str:
    """Which age band a ready item aged `days` days falls in.

    The bands are half-open `[lo, hi)` and tile the whole timeline (see
    `READY_AGE_BUCKETS`): the first band absorbs anything below its upper
    bound -- including a NEGATIVE age from a small clock skew -- and the last
    band (`hi is None`) absorbs everything from its lower bound up. So every
    real `days` value maps to exactly ONE band; no item can fall between two
    bands the way the previous inclusive `[lo, hi]` bounds allowed.
    """
    for label, _lo, hi in READY_AGE_BUCKETS:
        if hi is None or days < hi:
            return label
    return READY_AGE_BUCKETS[-1][0]  # unreachable: the last band's hi is None


def _held_stale_count(held_items: list[Item]) -> int:
    """How many of `held_items` (already filtered to `status == "held"`) are
    currently RECLAIM-ELIGIBLE, per `custody.reclaim_eligible` -- called
    verbatim, never re-derived, so this can never disagree with what
    `supervisor.reap_project` would actually reclaim right now. A pure
    function of already-fetched items (same "derive from the one list this
    caller already read" discipline as `_ready_age_buckets`/
    `project_activity` below), so `project_summary` costs no second `bd`
    call to learn it.

    `i.meta.get(custody.CUSTODY_KEY)` is `None` for an item that was never
    given a custody record at all (e.g. claimed by something that bypassed
    `work_claim`/the CLI's custody path) -- `reclaim_eligible(None)` already
    reports that shape as eligible ("no custody record"), so it is counted
    stale here too, not silently skipped for lack of data.
    """
    return sum(
        1
        for i in held_items
        if C.reclaim_eligible(i.meta.get(C.CUSTODY_KEY) if isinstance(i.meta, dict) else None)[0]
    )


def _held_stale_oldest_age_seconds(held_items: list[Item]) -> float | None:
    """The longest time-since-last-renewal among the reclaim-eligible holds
    that carry a custody record -- the age of the WORST custody breach, in
    seconds. `None` when nothing is stale, or when every stale hold lacks a
    custody record entirely (the "claimed but never renewed" path: eligible,
    but with no `last_seen` to age from -- no honest duration exists, so we
    report none rather than fabricate one).

    A pure function of the already-fetched `held_items` (same discipline as
    `_held_stale_count`, computed from the SAME list), so it costs no second
    `bd` call. This is the time-to-notice anchor for a ranked attention
    queue's top tier: a custody breach's age is the clock a human's notice
    is measured against.
    """
    ages: list[float] = []
    for i in held_items:
        meta = i.meta.get(C.CUSTODY_KEY) if isinstance(i.meta, dict) else None
        if not C.reclaim_eligible(meta)[0]:
            continue
        # Only a record with a real `last_seen` can be aged. A stale hold with
        # no custody record at all (dict-less) is eligible but un-ageable --
        # skipped here, never coerced to a fabricated 0-second breach.
        if isinstance(meta, dict) and meta.get("last_seen"):
            ages.append(C.age_seconds(meta["last_seen"]))
    return max(ages) if ages else None


def _blocked_stale_count(blocked_items: list[Item]) -> int:
    """How many of `blocked_items` (already filtered to `status == "blocked"`)
    are NEEDLESSLY blocked -- blocked in status yet with NO still-active
    `blocks` dependency left (`_active_blockers` empty: every upstream
    blocker already resolved, or none was ever recorded). These are the
    "stale blocker chain" a ranked attention queue treats as MORE urgent
    than a genuinely-blocked item, because they need nothing but an unblock.

    Derived from the SAME `items` list `project_summary` already read (each
    item's `raw["dependencies"]` carries the edge type + upstream status
    `bd list` returns), so it costs no second `bd` call. Safe by
    construction: `_is_active_blocker` counts a `blocks` edge whose upstream
    status is anything but `closed` (a missing/unreadable status included) as
    still active, so an item is only ever called stale on real evidence that
    its blockers are cleared -- never on absent data.
    """
    return sum(1 for i in blocked_items if not _active_blockers(i))


def _ready_age_buckets(items: list[Item]) -> dict[str, int]:
    """Age histogram of ready items whose values sum to EXACTLY `ready`.

    "Ready" here is the same set counted by `ProjectSummary.ready`: an open,
    work-lane item -- i.e. an unclaimed work item. Every one of them lands in
    exactly one bucket, so `sum(_ready_age_buckets(items).values())` always
    equals that `ready` count. Two mechanisms guarantee it:

      - the age bands tile the timeline with no gaps (see
        `_ready_age_bucket_label`), so no DATED item is ever dropped; and
      - an UNDATED ready item (no readable `created_at`) is counted in the
        distinct `UNKNOWN_READY_AGE` bucket rather than vanishing.

    That invariant is the whole point: it is what stops the dashboard from
    ever again showing one number for "READY" and a smaller one for the same
    "unclaimed items" set, computed two slightly different ways.
    """
    now = datetime.now(UTC)
    ready = [i for i in items if i.status == "open" and LANE_WORK in i.tags]
    out: dict[str, int] = {label: 0 for label, _, _ in READY_AGE_BUCKETS}
    out[UNKNOWN_READY_AGE] = 0
    for i in ready:
        if i.created_at is None:
            out[UNKNOWN_READY_AGE] += 1
            continue
        out[_ready_age_bucket_label((now - i.created_at).total_seconds() / 86400)] += 1
    return out


def project_summary(ws: Workspace, name: str) -> ProjectSummary:
    """Compute one project's `ProjectSummary` against the live `bd` project.

    Never raises. A project's health is decided in this order, so an
    unhealthy one is never mistaken for a healthy empty one:

      1. `Workspace.creation_state` is consulted FIRST, before any item read.
         A project mid-creation reports `STATUS_CREATING`; one left broken by
         a `new` that never finished reports `STATUS_BROKEN` -- in both cases
         with every count left `None`. This is the fix for a measured outage
         where a half-created project (its `.create.lock` sitting right there)
         reported a healthy `ok` with 0 items. `webapp.py` calls this function
         directly, so putting the check HERE -- not only in `cli.cmd_instances`
         -- is what makes the web dashboard honest too.
      2. A database that then cannot be read reports `status="ERROR: ..."`
         (truncated), again with every field `None`/empty.
      3. Otherwise `STATUS_OK`, with real counts.

    On the healthy path, fetches items exactly ONCE
    (`ws.project(name).list(include_resolved=True)`) and derives every field
    -- counts, `project_activity`'s aging/throughput figures, and the
    ready-age histogram -- from that single in-memory list. No field here
    costs a second `bd` call.
    """
    state = ws.creation_state(name)
    if state == "creating":
        return ProjectSummary(name=name, status=STATUS_CREATING)
    if state == "abandoned":
        return ProjectSummary(name=name, status=STATUS_BROKEN)
    try:
        items = ws.project(name).list(include_resolved=True)
    except BeadsError as e:
        return ProjectSummary(name=name, status=truncate_status(f"ERROR: {e}"))
    held_items = [i for i in items if i.status == "held"]
    blocked_items = [i for i in items if i.status == "blocked"]
    activity = project_activity(items)
    held_stale = _held_stale_count(held_items)
    return ProjectSummary(
        name=name,
        status=STATUS_OK,
        total=len(items),
        ready=sum(1 for i in items if i.status == "open" and LANE_WORK in i.tags),
        held=len(held_items),
        intake=sum(1 for i in items if i.status == "open" and LANE_INTAKE in i.tags),
        blocked=sum(1 for i in items if i.status == "blocked"),
        resolved=sum(1 for i in items if i.status == "resolved"),
        deferred=sum(1 for i in items if i.status == "deferred"),
        held_stale=held_stale,
        held_by=sorted({i.holder for i in held_items if i.holder}),
        last_activity=activity["last_activity"],
        oldest_unclaimed_age_seconds=activity["oldest_unclaimed_age_seconds"],
        resolved_24h=activity["resolved_24h"],
        resolved_7d=activity["resolved_7d"],
        resolved_daily=activity["resolved_daily"],
        ready_age_buckets=_ready_age_buckets(items),
        blocked_stale=_blocked_stale_count(blocked_items),
        held_stale_oldest_age_seconds=_held_stale_oldest_age_seconds(held_items),
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
