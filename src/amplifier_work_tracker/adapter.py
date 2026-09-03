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

import csv
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
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

# Our public "related item" vocabulary (the `work_add`/`create` `related`
# param, and the CLI's/tool's `dep` verb), mapped to bd's own dependency-type
# strings (`bd dep add ... -t <type>`). "follow-up-of" reuses `discovered-
# from` rather than inventing a new bd-side type: bd already treats it as
# non-blocking (ASSUMPTION link.nonblocking) and it is semantically the same
# relationship -- "this item followed on from working on that one" -- that
# `work_file`'s own discovered-from linking already expresses. See
# docs/dependency-expression.md for the full recommendation on when to use
# which kind.
RELATION_KINDS = {
    "relates-to": "relates-to",
    "supersedes": "supersedes",
    "follow-up-of": LINK_DISCOVERED_FROM,
}

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
    # The dolt CLI enumerates its data directory and `lstat()`s every entry
    # on EVERY invocation -- including pure client mode (`--host/--port`
    # against an already-running shared server, where no local database is
    # even relevant). If an entry vanishes between `readdir` and `lstat`,
    # dolt aborts the whole query with this message. Measured (lane
    # model_performance-rpz, `probes/rpz-dolt-error-misreport/repro.sh`):
    # 6 failures in 25 attempts from a churning 40k-entry directory, 0 in
    # 25 from a pinned one. `_dolt_scan_dir` now REMOVES the cause; this
    # entry is the belt to that braces -- it is a filesystem-race
    # signature that can never appear in a legitimate bd domain result, so
    # riding through it can never turn a real failure into a false success.
    "failed to load database names",
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


_DOLT_SCAN_DIR: Path | None = None


def _dolt_scan_dir() -> Path:
    """A stable, empty, WE-OWN-IT directory for the `dolt` CLI to scan.

    THE fix for a measured intermittent failure, not a tidiness nicety.

    Mechanism (measured, lane `model_performance-rpz`, harness
    `probes/rpz-dolt-error-misreport/repro.sh`): the `dolt` CLI enumerates
    the entries of its data directory -- which, with no `--data-dir` given,
    is its INHERITED CURRENT WORKING DIRECTORY -- and `lstat()`s each one on
    EVERY invocation. This happens even in the pure client mode every
    `_dolt_*` helper here uses (`--host/--port` against the already-running
    shared server), where no local database is relevant at all. Two
    consequences, both measured on this host with the SAME query against the
    SAME server:

      - COST, proportional to entry count: 0.031s from a 2-entry directory,
        0.805s from `/tmp` (52,281 entries) -- 26x, paid on every one of the
        19 direct-SQL call sites in this module.
      - FAILURE: if any entry vanishes between `readdir` and `lstat`, dolt
        aborts the entire query with `failed to load database names: lstat
        <path>: no such file or directory`. Under a churning 40,000-entry
        directory: 6 failures in 25 attempts.

    `_dolt_sql`/`_dolt_sql_json` passed no `cwd=` to `_run_bounded`, so the
    directory dolt scanned was whatever directory the CALLING AGENT happened
    to be in -- `/tmp` in both field reports. That is the whole defect: a
    read failure whose probability is set by an unrelated process's litter.

    Both remedies were measured at 0/25 under identical load, and both are
    applied here (they are independent, and the second survives a future
    refactor that drops the first): `cwd=` this directory on the two hot
    helpers, and `--data-dir` this directory on every `dolt` invocation via
    `_dolt_conn_args`.

    Location: honours `AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR` (tests, and an
    operator with an opinion), else `$XDG_CACHE_HOME`/`~/.cache` under this
    tool's own name. Deliberately NOT the workspace root (it holds a
    directory per project, and grows), NOT `~/.beads/shared-server/dolt`
    (that is the live data directory, which churns as dolt writes), and NOT
    a per-call temp directory (a fresh `mkdtemp` per query would reintroduce
    a per-call cost and litter). Memoised: one `mkdir` per process, not one
    per query.

    Never raises. A home directory that cannot be written (read-only,
    unusual container) falls back to one process-lifetime temp directory
    rather than breaking every SQL read in the module -- degrading to
    today's behaviour is strictly better than a hard failure, and a temp
    directory of our own is still quiet and stable.
    """
    global _DOLT_SCAN_DIR
    override = os.environ.get("AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR")
    if override:
        # Not memoised: an override is what tests move around, and a cached
        # first value would silently outlive the monkeypatch that set it.
        d = Path(override)
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            pass
    if _DOLT_SCAN_DIR is not None and _DOLT_SCAN_DIR.is_dir():
        return _DOLT_SCAN_DIR
    cache_root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    candidate = Path(cache_root) / "amplifier-work-tracker" / "dolt-scan"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        candidate = Path(tempfile.mkdtemp(prefix="awt-dolt-scan-"))
    _DOLT_SCAN_DIR = candidate
    return candidate


def _dolt_conn_args() -> list[str]:
    """Global `dolt` CLI flags to reach the shared server directly over SQL,
    bypassing any per-project `.beads` directory entirely.

    `--data-dir` is here rather than only on the two hot helpers so EVERY
    `dolt` invocation in this module (the `sql -q` reads, `DROP DATABASE`,
    `SHOW CREATE`, the copy script) gets the pinned scan directory by
    construction -- see `_dolt_scan_dir` for the measured failure this
    removes, and why "remember to pass it at each call site" is exactly the
    discipline that failed here in the first place.

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

    return [
        "--data-dir",
        str(_dolt_scan_dir()),  # pinned scan directory -- see `_dolt_scan_dir`
        "--host",
        SV.DEFAULT_DOLT_HOST,
        "--port",
        str(SV.DEFAULT_DOLT_PORT),
        "--no-tls",
    ]


def _run_dolt_sql_bounded(args: list[str]) -> subprocess.CompletedProcess:
    """Run one direct-SQL `dolt` invocation, riding through a transient
    CONNECTION-transport blip the same bounded way `Beads._run` already does
    for `bd` subprocesses -- and, unlike every previous version of this code
    path, with the scan directory pinned (`cwd=_dolt_scan_dir()`).

    Why this exists at all: the retry classification lived ONLY in
    `Beads._run`, which wraps `bd`. The direct dolt-SQL path -- 19 call
    sites in this module, including the single-item read behind
    `get`/`get_readonly`/`claim_item` and the project read behind
    `project_summary` -- had NO retry of any kind. Adding a transient
    signature to `_RETRYABLE_CONNECTION` alone would land in a table this
    code path never consulted. Putting the loop HERE, rather than at each
    call site, is what makes all 19 benefit by construction.

    Same shape and the same budget as `Beads._run`'s connection leg
    (`_MAX_CONNECTION_RETRIES`, short capped backoff, few-second ceiling),
    for the same reason: a transient blip clears in well under a second,
    whereas a genuinely-unreachable server must fail FAST rather than
    hammer. On a spent budget this RETURNS the failed process unchanged --
    never a new exception type -- so every existing `p.returncode != 0`
    call site behaves exactly as before, just a couple of seconds later.

    `cwd=` and `--data-dir` (via `_dolt_conn_args`) are deliberately both
    applied: they are independent remedies, each measured at 0/25 failures
    under the load that produced 6/25 unpinned.
    """
    attempt = 0
    while True:
        p = _run_bounded(args, env=_bd_env(), cwd=_dolt_scan_dir())
        if p.returncode == 0 or attempt >= _MAX_CONNECTION_RETRIES:
            return p
        if not _connection_retryable((p.stdout or "") + (p.stderr or "")):
            return p
        backoff = min(_CONNECTION_RETRY_BACKOFF_CAP, 0.1 * (2**attempt))
        time.sleep(backoff * (0.5 + os.urandom(1)[0] / 255))
        attempt += 1


def _dolt_sql(query: str) -> subprocess.CompletedProcess:
    return _run_dolt_sql_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", query, "-r", "csv"],
    )


def _sql_literal(s: str) -> str:
    """Escape `s` for embedding as a single-quoted SQL string literal.

    Minimal defense-in-depth for values interpolated into a `_dolt_sql*`
    query that -- unlike a project `db` name (constrained by `NAME_RE`
    before it ever reaches a `_dolt_*` helper) -- carry no such upstream
    validation: `Beads.list()`'s `lane` and mapped `status` values. Doubles
    any embedded single quote (`'` -> `''`), the standard SQL escape, so a
    stray quote in a future caller's value cannot break out of the
    surrounding literal.
    """
    return s.replace("'", "''")


def _dolt_sql_json(query: str) -> subprocess.CompletedProcess:
    """Like `_dolt_sql`, but requests dolt's JSON result format (`-r json`)
    instead of CSV.

    Required for any query that projects a free-text `longtext` column --
    `title`/`description`/`close_reason`/`acceptance_criteria`/`design` --
    which can legitimately contain commas AND embedded newlines. A naive
    CSV-then-`splitlines()` parse (the trick `_summary_items_via_sql` gets
    away with, because its own projection is deliberately restricted to
    short scalar columns) would silently corrupt those fields: a comma
    inside a title would shift every column after it, and a newline inside
    a description would split one logical row into two. dolt's JSON output
    (an object with a top-level `rows` list of field-name-keyed dicts, see
    `_dolt_show_create`'s own use of the same format) carries each field as
    a single JSON string with no such ambiguity.
    """
    return _run_dolt_sql_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", query, "-r", "json"],
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


# Only the columns `project_summary`'s downstream derivation actually reads off
# each Item (status, tags, holder, the three timestamps -- plus id/priority/kind
# for faithful shape) -- deliberately NOT title/description/close_reason, which
# are free-text `longtext` that would need CSV-escaping and are never consulted
# by a summary. Keeping the projection to short scalar columns is what lets the
# CSV parse below stay simple AND keeps the read transaction tiny.
_SUMMARY_ITEM_COLUMNS = (
    "id",
    "status",
    "assignee",
    "priority",
    "issue_type",
    "created_at",
    "updated_at",
    "closed_at",
)


def _summary_items_via_sql(db: str) -> list[Item]:
    """Read `db`'s items as `Item`s straight off the shared dolt server over a
    READ-ONLY SQL SELECT -- the drop-in replacement for `bd list --all` that
    `project_summary` uses, existing purely to sidestep the serialization
    conflict that failing path suffered.

    Why this exists (the bug this fixes): `bd list --all` on a large project
    (cortex: 465 items) runs through `bd`, which does a read+WRITE transaction
    (it appends an interaction-log row per invocation). Materialising 465 rows
    keeps that read+write transaction open long enough that, under the normal
    concurrent write traffic of the shared single-writer dolt server (the
    reap/notify sweeps + parallel agent claims), its write set is reliably
    invalidated by a committed transaction from another client -- a dolt
    serialization failure (MySQL 1213/1205). `Beads._run` retries that up to
    `_MAX_RETRIES` (8) with exponential backoff and, for a 465-row read,
    exhausts the whole budget (~23s measured) before giving up. Small projects
    (attractor: 17 rows) almost never lose the race, so the failure LOOKED
    per-project-deterministic but is really a result-set-size x contention
    interaction. See work_tracker items pipeline-exz / pipeline-knu.

    Why a raw SELECT is the fix, not a bigger retry budget: a pure `SELECT`
    over the direct `_dolt_sql` path has NO write set, so it CANNOT
    serialization-conflict with a concurrent writer, at any project size --
    the conflict window is eliminated rather than merely widened-tolerance.
    `_dolt_sql` is also a one-shot autocommit connection, so it never holds a
    long transaction of its own.

    Faithfulness: verified empirically that `bd list --all` returns EXACTLY the
    `issues` table's rows, one-to-one, for both a small clean project
    (attractor: 17==17) and a large busy one (cortex: 465==465), with zero
    non-listable rows (wisp/event/ephemeral/template) present -- so no `bd`
    listing filter needs reproducing here; every `issues` row is an item. Each
    field is mapped through the SAME seams `Item.from_beads` uses -- status via
    `_map_status`, `assignee`->holder per `_FIELD_MAP`, labels from the
    `labels` table (bd's `labels` JSON field), timestamps as UTC via
    `_parse_dolt_timestamp` -- so the `Item`s this returns derive byte-identical
    counts/aging/throughput downstream. Only the summary-relevant fields are
    populated (see `_SUMMARY_ITEM_COLUMNS`); body text a summary never reads is
    left at its dataclass default, deliberately.

    `db` has already passed `NAME_RE` at every call site (it is a project name),
    so it carries no SQL-relevant character -- same guarantee `database_exists`
    and the other `_dolt_*` helpers rely on.
    """
    cols = ", ".join(f"`{c}`" for c in _SUMMARY_ITEM_COLUMNS)
    p = _dolt_sql(f"SELECT {cols} FROM `{db}`.`issues`")
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read items of database {db!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    lp = _dolt_sql(f"SELECT `issue_id`, `label` FROM `{db}`.`labels`")
    if lp.returncode != 0:
        raise _sql_failure(
            f"could not read labels of database {db!r} over SQL: "
            f"{_clean_bd_error(lp.stderr or lp.stdout)}",
            lp,
        )
    tags_by_id: dict[str, list[str]] = {}
    for row in csv.reader((lp.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < 2:
            continue
        tags_by_id.setdefault(row[0], []).append(row[1])
    items: list[Item] = []
    for row in csv.reader((p.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < len(_SUMMARY_ITEM_COLUMNS):
            continue
        rec = dict(zip(_SUMMARY_ITEM_COLUMNS, row, strict=False))
        iid = rec["id"]
        pr = rec["priority"].strip()
        items.append(
            Item(
                id=iid,
                status=_map_status(rec["status"]),
                holder=rec["assignee"] or None,
                kind=rec["issue_type"] or "task",
                priority=int(pr) if pr else None,
                tags=tags_by_id.get(iid, []),
                created_at=_parse_dolt_timestamp(rec["created_at"]),
                updated_at=_parse_dolt_timestamp(rec["updated_at"]),
                closed_at=_parse_dolt_timestamp(rec["closed_at"]),
            )
        )
    return items


# Full-field columns for `Beads.list()`'s read-only SQL replacement -- every
# field `Item.from_beads` (via `_FIELD_MAP`) can consume, MINUS `labels`
# (joined separately from the `labels` table, same as
# `_summary_items_via_sql`) and the three timestamp columns (projected
# separately in `_list_rows_via_sql`, reformatted to bd's own ISO-8601 `...Z`
# wire shape so `Item.from_beads`'s existing `_parse_bd_timestamp` parses
# them unchanged -- no second timestamp parser needed for this path).
_LIST_ITEM_SCALAR_COLUMNS = (
    "id",
    "title",
    "status",
    "assignee",
    "issue_type",
    "close_reason",
    "acceptance_criteria",
    "description",
    "design",
    "priority",
    "created_by",
    "metadata",
)


def _list_rows_via_sql(db: str, *, where_sql: str | None, limit: int) -> list[Item]:
    """Read `db`'s items as full-field `Item`s straight off the shared dolt
    server over a READ-ONLY SQL SELECT -- the drop-in replacement for
    `Beads.list()`'s `bd list [--all] [--status ...] [--label ...] [--limit
    ...]`, which suffers the identical serialization-conflict failure mode
    `_summary_items_via_sql` was built to sidestep (see that function's
    docstring for the full mechanism), but for EVERY caller of `list()` --
    not just `project_summary`. The web project-page list pane, the reap
    sweep, the gateway, and the CLI's own `list` subcommand all go through
    this same method, so all of them get the fix at once.

    Unlike `_summary_items_via_sql` (a narrow, summary-only projection of
    short scalar columns, safe to parse as CSV), this reads every field
    `Item.from_beads` maps -- including free-text `longtext` columns
    (title/description/close_reason/acceptance_criteria/design) that can
    contain commas and embedded newlines -- so the issues projection goes
    over `_dolt_sql_json` (`-r json`), never CSV. Labels stay on the CSV
    path (`_dolt_sql`), same as `_summary_items_via_sql`: label values are
    a short, controlled vocabulary (`lane:eng`-shaped slugs) that cannot
    contain a comma.

    `where_sql`, if given, is ANDed into the query's WHERE clause verbatim
    by the caller (`Beads.list()`) from values that have already been
    validated: a domain `status` has already been mapped through
    `_STATUS_MAP_REVERSE`, which only ever yields one of bd's own five
    fixed raw status strings, and `lane` is interpolated as a string
    literal the same way `_summary_items_via_sql`'s `db` and
    `_dolt_table_counts`'s `table` names already are (see those functions'
    notes on the same discipline). `limit` of `0` means unlimited (no
    `LIMIT` clause at all), matching bd's own `--limit 0` convention that
    `Beads.list()` already documents.

    Timestamps are projected via `DATE_FORMAT(..., '%Y-%m-%dT%H:%i:%sZ')`
    -- bd's OWN ISO-8601 wire shape (verified empirically: bd's `--json`
    reports `created_at` as `...Z` for the exact same row dolt stores in
    UTC) -- so `Item.from_beads`'s existing `_parse_bd_timestamp` parses
    them completely unchanged; a NULL `closed_at` formats to SQL NULL,
    which `Item.from_beads` already treats as "no closed_at". `metadata`
    comes back from dolt's JSON output as a STRING (e.g. `"{}"`), not a
    nested object the way bd's own `--json` nests it -- so it is decoded
    here at the seam, before reaching `Item.from_beads`, which expects
    `meta` to already be a dict.

    Ordering: ``ORDER BY `issues`.`priority` ASC, `issues`.`created_at`
    DESC, `issues`.`id` ASC``. bd's DEFAULT (no explicit `--sort`) order is
    NOT chronological -- verified empirically (against a fresh, controlled
    isolated-server project, disentangled from creation order by giving
    the FIRST-created item the WORST/highest priority number and the
    SECOND-created item the BEST/lowest): bd's plain `bd list` returns
    byte-identical output to explicit `bd list --sort priority`, and that
    order is priority-ascending, not creation-order. Every project used to
    validate the PREVIOUS (`created_at`-only) ordering hypothesis
    (production `attractor`, `cortex`, etc.) happens to carry a uniform
    `priority=2` on nearly every row, which is exactly why a `created_at`-
    only order looked correct there -- it silently degenerates to the
    correct order whenever priority is constant, and only diverges once
    two items in one project genuinely differ in priority (a case this
    repo's own test suite -- not production sampling -- is what surfaced
    it: see `tests/integration/test_list_via_sql_equivalence.py`).
    `created_at DESC` remains the verified secondary key WITHIN a tied
    priority (the common case, since most real items share one priority),
    and `id ASC` remains the verified tertiary tie-break within a tied
    `(priority, created_at)` pair (dolt's own natural, unordered table-scan
    order for the `issues` table already returns ascending primary-key
    order, which is what bd's own tie order for such rows turned out to
    be -- see the git history of this function for the earlier, narrower
    empirical check). All three columns are qualified with the `issues`
    table name specifically so `ORDER BY` resolves to the real
    columns, never a `DATE_FORMAT`-string alias of the same name in the
    SELECT list. `priority` is `int NOT NULL` in every real project
    checked (verified via `information_schema.COLUMNS`), so no NULL
    ordering case needs to be special-cased here.

    `db` has already passed `NAME_RE` at every call site (it is a project
    name), so it carries no SQL-relevant character -- same guarantee
    `_summary_items_via_sql` and the other `_dolt_*` helpers rely on.
    """
    scalar_cols = ", ".join(f"`{c}`" for c in _LIST_ITEM_SCALAR_COLUMNS)
    ts_cols = ", ".join(
        f"DATE_FORMAT(`issues`.`{c}`, '%Y-%m-%dT%H:%i:%sZ') AS `{c}`"
        for c in ("created_at", "updated_at", "closed_at")
    )
    query = f"SELECT {scalar_cols}, {ts_cols} FROM `{db}`.`issues`"
    if where_sql:
        query += f" WHERE {where_sql}"
    query += " ORDER BY `issues`.`priority` ASC, `issues`.`created_at` DESC, `issues`.`id` ASC"
    if limit:
        query += f" LIMIT {int(limit)}"
    p = _dolt_sql_json(query)
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read items of database {db!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    try:
        rows = json.loads(p.stdout or "{}").get("rows", [])
    except json.JSONDecodeError as e:
        raise BeadsError(f"could not parse items of database {db!r} over SQL: {e}") from e

    lp = _dolt_sql(f"SELECT `issue_id`, `label` FROM `{db}`.`labels`")
    if lp.returncode != 0:
        raise _sql_failure(
            f"could not read labels of database {db!r} over SQL: "
            f"{_clean_bd_error(lp.stderr or lp.stdout)}",
            lp,
        )
    tags_by_id: dict[str, list[str]] = {}
    for row in csv.reader((lp.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < 2:
            continue
        tags_by_id.setdefault(row[0], []).append(row[1])

    items: list[Item] = []
    for rec in rows:
        d = dict(rec)
        meta = d.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta) if meta.strip() else {}
            except json.JSONDecodeError:
                meta = {}
        d["metadata"] = meta if isinstance(meta, dict) else {}
        d["labels"] = tags_by_id.get(str(d.get("id", "")), [])
        # `priority` comes back from dolt's JSON output as a STRING (e.g.
        # `"2"`), unlike bd's own `--json`, which reports it as a real
        # number -- `Item.from_beads` copies it through verbatim (see
        # `_FIELD_MAP`), so left uncorrected every item's `priority` would
        # be a `str` where bd's is an `int`. Cast here, at the seam, the
        # same discipline `_summary_items_via_sql` already applies.
        pr = d.get("priority")
        d["priority"] = int(pr) if isinstance(pr, str) and pr.strip() else None
        # bd's own `--json` OMITS an optional free-text field entirely when
        # it is empty (verified empirically: an unset `close_reason` or
        # `design` never appears as a JSON key at all for such an item) --
        # so `Item.from_beads`'s `if their in d` guard never fires for it,
        # and the dataclass default (`None`) applies. A SQL row, by
        # contrast, always carries every requested column, with an unset
        # `longtext` rendered as an empty string rather than an absent key.
        # Dropping an empty-string value back down to an absent key here
        # reproduces bd's own omission exactly, rather than leaving a
        # `resolution=""`/`design=""` where bd would have left `None`.
        for optional_text_field in (
            "close_reason",
            "design",
            "acceptance_criteria",
            "description",
            "assignee",
        ):
            if d.get(optional_text_field) == "":
                del d[optional_text_field]
        items.append(Item.from_beads(d))
    # `corrected` -- ONE aggregated GROUP BY for the whole call, same shape
    # as the labels join two lines above (unscoped by `where_sql`/`limit`,
    # joined in Python by id) -- never a per-row query and never the
    # erratum TEXT itself (that stays off this path entirely; see
    # `_corrected_counts_via_sql`'s own docstring). `errata` is left at its
    # dataclass default (`[]`) here on purpose -- see `Item.errata`'s note
    # on why a many-row listing carries the cheap flag but not the list.
    if items:
        corrected_counts = _corrected_counts_via_sql(db)
        for it in items:
            it.corrected = corrected_counts.get(it.id, 0) > 0
    return items


# ---------------------------------------------------------------- errata
#
# An ERRATUM is an APPEND-ONLY correction to a RESOLVED item's own record --
# "the stored resolution text is wrong, but the work itself stands" -- never
# a rewrite of `resolution` (that would defeat the whole point: a reader
# could no longer trust a resolution's text to be what was actually written
# at close time). See `Beads.erratum` for the full write-side contract; the
# helpers below are the shared wire format + read-only SQL path both
# `Beads.erratum` (its own verify predicate) and every full item read
# (`_get_item_via_sql`, `Beads.get(with_links=True)`) use to surface it.
#
# Storage: reuses bd's own append-only COMMENT channel (`bd comment <id>
# "<text>"` -- the SAME mechanism `edit_item`'s audit trail already writes
# through), not a Beads schema change or a second storage location. Read
# back over the contention-free `_dolt_sql*` path against the `comments`
# table directly (verified schema: `id` char(36), `issue_id`, `author`
# varchar(255) NOT NULL, `text` longtext NOT NULL, `created_at` datetime) --
# never `bd comments <id> --json`, which (like `bd show`/`bd list`) is a
# read+WRITE transaction and can lose a serialization conflict.

ERRATUM_TAG = "ERRATUM"
_ERRATUM_PREFIX = f"{ERRATUM_TAG} "


def _erratum_now_iso() -> str:
    """This call's own UTC timestamp, in the one wire format every erratum
    carries -- `custody.now_iso()`'s exact format (`%Y-%m-%dT%H:%M:%SZ`),
    reused rather than re-invented so the codebase has ONE "UTC timestamp,
    no microseconds, no ambiguity" shape, not two. Deliberately NOT the
    comment's own `comments.created_at` column: that is dolt's server
    clock -- a real value, but not one this call controls the same way --
    and a caller-stamped `at` keeps the printed/parsed shape independent
    of that detail.
    """
    return C.now_iso()


def _format_erratum_comment(at: str, actor: str, text: str) -> str:
    """The exact wire shape an erratum is written as: one bd COMMENT,
    `ERRATUM <at> <actor>: <text>`. See `_parse_erratum_comment` for the
    read side and why the actor/text boundary is resolved from the
    comment's own `author` column, not from this string alone.
    """
    return f"{_ERRATUM_PREFIX}{at} {actor}: {text}"


def _parse_erratum_comment(author: str, text: str) -> Erratum | None:
    """Parse ONE bd comment row (`author`, `text`) as an `Erratum`, or
    `None` if `text` is not an erratum written by `_format_erratum_comment`
    -- a plain `comment()` call, `edit_item`'s "X edited: ..." audit note,
    `reopen`'s archived-resolution note are all real bd comments, never
    errata.

    `author` is bd's own attribution column (populated at write time from
    `--actor`/`BEADS_ACTOR`, the SAME identity `activity()`'s comment feed
    already reads off it) -- used here as the AUTHORITATIVE actor value to
    resolve the actor/text boundary in `text`, rather than a naive split
    on the first ": " (which would mis-split an actor whose own identity
    happens to contain a colon or a space -- a measured requirement, not a
    hypothetical). The timestamp token (the first whitespace-delimited
    word after the `ERRATUM ` tag) is assumed space-free -- true of
    `_erratum_now_iso`'s own ISO-8601 format, so a hand-written comment
    that merely starts with `ERRATUM <token> ...` for a DIFFERENT author
    still correctly fails to parse: the `<author>: ` prefix check below
    will not match.
    """
    if not text.startswith(_ERRATUM_PREFIX):
        return None
    rest = text[len(_ERRATUM_PREFIX) :]
    at, sep, tail = rest.partition(" ")
    if not sep or not at:
        return None
    lead = f"{author}: "
    if not tail.startswith(lead):
        return None
    return Erratum(at=at, by=author, text=tail[len(lead) :])


def _errata_via_sql(db: str, item_id: str) -> list[Erratum]:
    """Every ERRATUM comment on `item_id`, oldest -> newest, read straight
    off the shared dolt server over a READ-ONLY SQL SELECT against the
    `comments` table -- the same contention-free discipline
    `_get_item_via_sql` uses for the base item (see its docstring): `bd
    comments <id> --json` (the path `activity()` uses) is a read+WRITE
    transaction like `bd show`/`bd list`, so it CAN lose a serialization
    conflict; a pure SELECT here cannot, at any contention level.

    Ordered by the comment's own `created_at`/`id` (a uuid7, itself
    time-ordered) -- real bd-assigned insertion order, never a re-sort by
    each erratum's own embedded `at` (which is caller-supplied and, in a
    pathological case such as a corrected clock, need not match insertion
    order).

    `text LIKE 'ERRATUM %'` narrows the SELECT to plausible erratum rows
    before they ever reach `_parse_erratum_comment`; a row that still
    fails to parse there is silently excluded -- it is simply not an
    erratum, not a malformed one worth surfacing.

    Free-text `text` (can contain commas/newlines) goes over
    `_dolt_sql_json`, never CSV -- the same discipline `_list_rows_via_sql`
    already applies to every other free-text column.
    """
    p = _dolt_sql_json(
        "SELECT `author`, `text` FROM "
        f"`{db}`.`comments` WHERE `issue_id` = '{_sql_literal(item_id)}' "
        f"AND `text` LIKE '{_ERRATUM_PREFIX}%' "
        "ORDER BY `created_at` ASC, `id` ASC"
    )
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read errata of {item_id!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    try:
        rows = json.loads(p.stdout or "{}").get("rows", [])
    except json.JSONDecodeError as e:
        raise BeadsError(f"could not parse errata of {item_id!r} over SQL: {e}") from e
    out: list[Erratum] = []
    for rec in rows:
        parsed = _parse_erratum_comment(str(rec.get("author") or ""), str(rec.get("text") or ""))
        if parsed is not None:
            out.append(parsed)
    return out


def _corrected_counts_via_sql(db: str) -> dict[str, int]:
    """Every item id in `db` carrying at least one ERRATUM comment, mapped
    to its erratum COUNT -- one aggregated round trip for the WHOLE
    project, read the same way `_list_rows_via_sql`'s own labels join
    already is (`_dolt_sql`, CSV, unscoped by the caller's WHERE/LIMIT,
    joined in Python by id afterward). This is what keeps a many-row
    `list()`/`list_bounded()` listing's `corrected` flag cheap: one small
    GROUP BY per call, never a per-row query and never the erratum TEXT
    itself (ids and counts are short scalars, safe for the CSV path --
    same reasoning `_summary_items_via_sql`'s own column projection note
    gives for staying off free text).
    """
    p = _dolt_sql(
        f"SELECT `issue_id`, COUNT(*) AS `n` FROM `{db}`.`comments` "
        f"WHERE `text` LIKE '{_ERRATUM_PREFIX}%' GROUP BY `issue_id`"
    )
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read erratum counts of database {db!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    counts: dict[str, int] = {}
    for row in csv.reader((p.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < 2:
            continue
        counts[row[0]] = int(row[1])
    return counts


def _get_item_via_sql(db: str, item_id: str) -> Item | None:
    """Read exactly ONE item as a full-field `Item`, straight off the shared
    dolt server over a READ-ONLY SQL SELECT -- the drop-in replacement for
    `bd show <id>`'s core-item read that `Beads.get()` uses, for the same
    reason `_list_rows_via_sql` replaces `bd list`.

    Why this exists: `bd show` -- like `bd list` -- does a read+WRITE
    transaction (verified empirically: same interaction-log-row-per-
    invocation mechanism `_list_rows_via_sql`'s docstring documents for `bd
    list`), so it CAN lose a dolt serialization conflict (MySQL 1213/1205)
    against the shared server's concurrent write traffic, however briefly
    -- `Beads._run` then burns retries on a call that need never have had a
    write set at all. `get()`/`get_readonly()` are the MOST-called single-
    item read in this codebase (every fencing check in `claim_item`/
    `resolve`, every readback in `update`/`resolve`, `get_custody`, the
    CLI's `show`, the web item-detail page's base fields) -- routing this
    one path through a pure `SELECT` removes the write set from all of them
    at once. A pure SELECT has no write set and cannot conflict, at any
    contention level -- see `_list_rows_via_sql`'s docstring for the full
    mechanism this shares.

    Thin wrapper over `_list_rows_via_sql`: same column set, same field
    mapping (`Item.from_beads` via `_FIELD_MAP`), same free-text/metadata/
    priority/timestamp faithfulness guarantees already proven equivalent to
    bd for the multi-row case -- an `id =` filter with `limit=1` is exactly
    that same query, narrowed to one row. Returns `None` (not an error)
    when no such row exists -- callers translate that into their own "not
    found" wording (see `Beads.get`/`get_readonly`), the same shape `bd
    show`'s own "no issues found" produced before.

    Deliberately does NOT attempt to reproduce `bd show --include-
    dependents`'s dependency/dependent graph here -- that enrichment
    (`Item.links`) stays sourced from bd in `Beads.get(with_links=True)`.
    Only the base item fields move to SQL; see that method's docstring for
    why splitting the two is the right scope for this fix.

    `item_id` is interpolated via `_sql_literal` (the same discipline
    `Beads.list()`'s `lane`/`status` values already use): unlike a project
    `db` name (constrained by `NAME_RE` before it ever reaches here), an
    item id arrives as caller-supplied text with no upstream format
    validation, so it is escaped rather than assumed safe.
    """
    rows = _list_rows_via_sql(db, where_sql=f"`issues`.`id` = '{_sql_literal(item_id)}'", limit=1)
    if not rows:
        return None
    it = rows[0]
    # A single-item read can afford the full erratum TEXT, not merely a
    # count -- see `_errata_via_sql`. `.corrected` is recomputed here
    # directly from the full list (rather than trusting the cheap
    # aggregate `_list_rows_via_sql` already set above), so the two can
    # never disagree for this one item.
    it.errata = _errata_via_sql(db, item_id)
    it.corrected = bool(it.errata)
    return it


def _ids_via_sql(db: str, where_sql: str) -> set[str]:
    """The set of item ids in `db` matching `where_sql`, over a READ-ONLY
    SQL SELECT -- the contention-free path (see `_get_item_via_sql`), so
    this can never itself lose a serialization conflict.

    Exists for the ONE verification shape a plain read-back-by-id cannot
    serve: a write whose own output names the item it touched, when that
    output was LOST because the wrapper reported a conflict-family failure.
    `create` (the new id is printed on stdout) and `claim_next` (bd chooses
    which item to claim) are exactly those two. Snapshotting the matching
    id set BEFORE the write and re-reading it after turns "did it land?"
    into a set difference, with an honest three-way answer:

      - exactly one new id  -> the write landed; that is the item.
      - no new id           -> the write genuinely did not land.
      - more than one new id -> AMBIGUOUS (a concurrent writer produced an
        indistinguishable row in the same window). Callers treat this as
        "not verified" and re-raise the original failure, never as success
        -- guessing which of two rows was ours is exactly the silent
        mis-attribution this whole discipline exists to prevent.

    Only the `id` column is projected, so the CSV path (`_dolt_sql`) is
    safe here: ids are short scalar primary keys that cannot contain a
    comma or newline -- the same reason `_list_rows_via_sql` keeps its
    labels projection on CSV while sending free text through JSON.

    `db` has already passed `NAME_RE` at every call site (it is a project
    name); `where_sql` is composed by the caller from `_sql_literal`-
    escaped values, the same discipline `Beads.list()` already uses.
    """
    p = _dolt_sql(f"SELECT `id` FROM `{db}`.`issues` WHERE {where_sql}")
    if p.returncode != 0:
        raise BeadsError(
            f"could not read item ids of database {db!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}"
        )
    return {ln.strip() for ln in (p.stdout or "").splitlines()[1:] if ln.strip()}  # drop CSV header


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


#: Tables holding rows keyed to exactly one item via `issue_id` (a plain FK to
#: `issues`.`id`, `ON DELETE CASCADE`) -- everything `move_item` copies/deletes
#: alongside the item's own `issues` row, EXCEPT `dependencies`, which has a
#: second possible FK (`depends_on_issue_id`) and is handled separately (see
#: `move_item`'s docstring on cross-project edges). Deliberately excludes the
#: parallel `wisp_*` tables and every OTHER per-database table (`config`,
#: `issue_counter`, `metadata`, `schema_migrations`, `federation_peers`,
#: `routes`, `local_metadata`, `repo_mtimes`, `child_counters`) -- a normal
#: work item is not a wisp, and those tables describe the DATABASE, not any
#: one item within it.
_ITEM_CHILD_TABLES = (
    "labels",
    "comments",
    "events",
    "issue_snapshots",
    "interactions",
    "compaction_snapshots",
)


def _item_row_counts(db: str, item_id: str) -> dict[str, int]:
    """Row count, in `db`, of `issues` (by `id`) and each of
    `_ITEM_CHILD_TABLES` (by `issue_id`) for exactly `item_id` -- one round
    trip via `UNION ALL`, the same shape `_dolt_table_counts` uses to prove
    `copy_database` complete, scoped here to a single item rather than a
    whole table. `move_item` uses this BEFORE it copies anything (the
    source-of-truth counts to verify the copy against), AFTER copying (to
    verify `dst` landed everything), and once more after deleting from
    `src` (to prove no residue survives there).
    """
    lit = _sql_literal(item_id)
    parts = [f"SELECT 'issues' AS t, COUNT(*) AS n FROM `{db}`.`issues` WHERE `id` = '{lit}'"]
    parts += [
        f"SELECT '{t}' AS t, COUNT(*) AS n FROM `{db}`.`{t}` WHERE `issue_id` = '{lit}'"
        for t in _ITEM_CHILD_TABLES
    ]
    query = " UNION ALL ".join(parts)
    p = _dolt_sql(query)
    if p.returncode != 0:
        raise BeadsError(
            f"could not count item {item_id!r}'s rows in database {db!r}: "
            f"{_clean_bd_error(p.stderr or p.stdout)}"
        )
    counts: dict[str, int] = {}
    for line in (p.stdout or "").splitlines()[1:]:  # drop CSV header
        if not line.strip():
            continue
        name, _, n = line.partition(",")
        counts[name.strip()] = int(n.strip())
    return counts


def _delete_item_rows_best_effort(
    db: str, item_id: str, *, dep_ids: list[str] | None = None
) -> None:
    """Best-effort cleanup of one item's rows in `db`, swallowing any
    BeadsError -- `move_item`'s rollback path when the copy-into-`dst`
    phase fails, or its completeness verification fails. Mirrors
    `_drop_database_best_effort`: a cleanup failure must never mask the
    ORIGINAL error already being raised.

    Deletes in child-before-parent order (`dependencies` rows named by
    `dep_ids` first, then every other `_ITEM_CHILD_TABLES` row, then the
    `issues` row itself last) rather than relying on `ON DELETE CASCADE` --
    this runs under `foreign_key_checks=0`, and whether dolt still honors
    cascade actions in that mode is unverified, so the explicit order is
    what actually guarantees no orphaned child row survives regardless.
    """
    lit = _sql_literal(item_id)
    statements: list[str] = []
    if dep_ids:
        ids_sql = ", ".join(f"'{_sql_literal(d)}'" for d in dep_ids)
        statements.append(f"DELETE FROM `{db}`.`dependencies` WHERE `id` IN ({ids_sql})")
    statements += [
        f"DELETE FROM `{db}`.`{t}` WHERE `issue_id` = '{lit}'" for t in _ITEM_CHILD_TABLES
    ]
    statements.append(f"DELETE FROM `{db}`.`issues` WHERE `id` = '{lit}'")
    script = "SET foreign_key_checks=0;\n" + ";\n".join(statements) + ";"
    p = _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", script],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )
    if p.returncode != 0:
        # Same reasoning as the dirty-schema heal in `Workspace.create`: the
        # caller's operation continues, so this warning must describe the
        # failed cleanup rather than republish dolt's announcement onto a
        # stderr that will accompany exit 0.
        logger.warning(
            "best-effort cleanup of partially-moved item %r in %r failed: %s",
            item_id,
            db,
            _quote_handled_output(p.stderr or p.stdout),
        )


@dataclass
class MoveReport:
    """Outcome of `move_item` -- what actually happened, honestly, so a
    caller never has to guess at what a bare `None` return would hide.
    """

    item_id: str
    src: str
    dst: str
    #: Dependency edges that existed in `src` and touched this item, but
    #: whose OTHER endpoint is a different issue that is NOT moving --
    #: these cannot be expressed once the two ends live in different
    #: databases, so they were dropped rather than moved or left dangling.
    #: Each entry is `{"id", "issue_id", "depends_on_issue_id", "type"}`,
    #: straight off the `dependencies` row that was dropped.
    dropped_dependency_edges: list[dict] = field(default_factory=list)


def move_item(src: str, dst: str, item_id: str) -> MoveReport:
    """Move ONE item -- and every row keyed to it across the issues-family
    tables (`labels`, `comments`, `events`, `issue_snapshots`,
    `interactions`, `compaction_snapshots`, `dependencies`) -- from database
    `src` to database `dst` on the shared dolt server.

    The item's id is preserved EXACTLY, never re-minted: ids are plain
    varchar primary keys, project-prefixed by convention but not validated
    against any prefix on read, and a database's own `issue_counter`/
    `config` rows only govern minting NEW ids -- they never validate an
    existing one. A foreign-prefixed id living in another database (e.g.
    `work_tracker_v2-3r2` inside `work_tracker`) is valid and collision-safe
    by construction; this is exactly why `copy_database`/`rename` also
    preserve ids verbatim rather than rewriting them (see that function's
    docstring for the same reasoning applied at whole-database grain).

    Refuses (no mutation) when:
      - `src` and `dst` are the same project;
      - `src` or `dst` is not a valid project name (`NAME_RE`) -- both are
        interpolated into backtick-quoted identifiers below, the same
        guarantee every other `_dolt_*` helper relies on (see
        `database_exists`'s docstring);
      - `src` or `dst` does not exist on the shared dolt server;
      - `item_id` does not exist in `src`;
      - the item is currently HELD -- an agent may be actively working it.
        This mirrors `Workspace.rename`/`Workspace.remove`'s safety property
        (refuse while HELD, no override), applied here at the single-item
        grain rather than a whole project;
      - an item with this id already exists in `dst`. Should not normally
        happen (ids are project-prefixed), but checked rather than assumed
        -- a silent overwrite of someone else's item would be unforgivable.

    Cross-project dependency edges: a `dependencies` row FKs to `issues`
    either via `issue_id` (the owning side, always) and optionally via
    `depends_on_issue_id` (an issue<->issue edge -- the other two possible
    targets, `depends_on_wisp_id`/`depends_on_external`, are opaque
    references with no FK of their own). Every edge touching `item_id` is
    inspected:

      - `depends_on_issue_id` is NULL (the edge targets a wisp/external ref,
        not another issue) -- moves along with the item unchanged; it can
        only have matched via `issue_id = item_id`, so it belongs entirely
        to the moving item and does not reference anything staying behind.
      - `depends_on_issue_id` is set and BOTH endpoints are `item_id` (a
        self-referential edge) -- moves along with the item unchanged, for
        the same reason.
      - Otherwise, the OTHER endpoint is a different issue that stays in
        `src` -- this edge cannot be expressed once the two ends live in
        different databases, so it is DROPPED: never copied to `dst`, and
        removed from `src` too (the id it names on the moving side is gone
        from `src` either way). Named in
        `MoveReport.dropped_dependency_edges` so the caller can see exactly
        what did not survive, rather than a silent, invisible data loss.

    Atomic from the caller's view, mirroring `copy_database`/`rename`:
    every row is copied into `dst` and the copy is VERIFIED complete (real
    row counts against `src`'s counts taken before anything moved, not just
    a non-erroring exit) BEFORE anything is deleted from `src`. If the copy
    or the verification fails, the partial rows already written to `dst`
    are deleted and the error is raised -- `src` is left completely
    untouched. Only once `dst` is proven complete does `src` lose its copy;
    the delete-from-`src` phase is itself verified the same way (a final
    `_item_row_counts` read on `src` proving zero residue).
    """
    if not NAME_RE.match(src):
        raise BeadsError(f"invalid project name {src!r}: must match {NAME_RE.pattern}")
    if not NAME_RE.match(dst):
        raise BeadsError(f"invalid project name {dst!r}: must match {NAME_RE.pattern}")
    if src == dst:
        raise BeadsError(
            f"cannot move item {item_id!r}: source and destination are the same project ({src!r})"
        )
    if not database_exists(src):
        raise BeadsError(
            f"cannot move {item_id!r}: source project {src!r} does not exist on the shared "
            f"dolt server"
        )
    if not database_exists(dst):
        raise BeadsError(
            f"cannot move {item_id!r}: destination project {dst!r} does not exist on the shared "
            f"dolt server"
        )

    lit = _sql_literal(item_id)

    src_items = _list_rows_via_sql(src, where_sql=f"`issues`.`id` = '{lit}'", limit=1)
    if not src_items:
        raise BeadsError(f"cannot move {item_id!r}: no such item in project {src!r}")
    item = src_items[0]
    if item.status == "held":
        raise BeadsError(
            f"refusing to move {item_id!r}: currently HELD by {item.holder!r}. An agent may be "
            f"actively working it. Resolve or reap the item first, then move again."
        )

    dst_items = _list_rows_via_sql(dst, where_sql=f"`issues`.`id` = '{lit}'", limit=1)
    if dst_items:
        raise BeadsError(
            f"cannot move {item_id!r} to {dst!r}: an item with this id already exists there. "
            f"ids are project-prefixed and should never collide across projects -- investigate "
            f"before forcing anything."
        )

    dep_p = _dolt_sql(
        f"SELECT `id`, `issue_id`, `depends_on_issue_id`, `type` FROM `{src}`.`dependencies` "
        f"WHERE `issue_id` = '{lit}' OR `depends_on_issue_id` = '{lit}'"
    )
    if dep_p.returncode != 0:
        raise BeadsError(
            f"could not read dependency edges for {item_id!r} in {src!r}: "
            f"{_clean_bd_error(dep_p.stderr or dep_p.stdout)}"
        )
    movable_dep_ids: list[str] = []
    dropped: list[dict] = []
    for row in csv.reader((dep_p.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < 4:
            continue
        dep_id, issue_id_val, depends_on_val, dtype = row[0], row[1], row[2] or None, row[3]
        if not depends_on_val or (issue_id_val == item_id and depends_on_val == item_id):
            movable_dep_ids.append(dep_id)
        else:
            dropped.append(
                {
                    "id": dep_id,
                    "issue_id": issue_id_val,
                    "depends_on_issue_id": depends_on_val,
                    "type": dtype,
                }
            )

    src_counts = _item_row_counts(src, item_id)

    insert_statements = [
        f"INSERT INTO `{dst}`.`issues` SELECT * FROM `{src}`.`issues` WHERE `id` = '{lit}'"
    ]
    insert_statements += [
        f"INSERT INTO `{dst}`.`{t}` SELECT * FROM `{src}`.`{t}` WHERE `issue_id` = '{lit}'"
        for t in _ITEM_CHILD_TABLES
    ]
    if movable_dep_ids:
        ids_sql = ", ".join(f"'{_sql_literal(d)}'" for d in movable_dep_ids)
        insert_statements.append(
            f"INSERT INTO `{dst}`.`dependencies` SELECT * FROM `{src}`.`dependencies` "
            f"WHERE `id` IN ({ids_sql})"
        )
    script = "SET foreign_key_checks=0;\n" + ";\n".join(insert_statements) + ";"

    p = _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", script],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )
    if p.returncode != 0:
        _delete_item_rows_best_effort(dst, item_id, dep_ids=movable_dep_ids)
        raise BeadsError(
            f"moving {item_id!r} from {src!r} to {dst!r} failed while copying: "
            f"{_clean_bd_error(p.stderr or p.stdout)}. {dst!r} was left untouched (any partial "
            f"rows were cleaned up); {src!r} is untouched."
        )

    dst_counts = _item_row_counts(dst, item_id)
    mismatches = [
        t for t in ("issues", *_ITEM_CHILD_TABLES) if src_counts.get(t) != dst_counts.get(t)
    ]

    dep_count_p = _dolt_sql(
        f"SELECT COUNT(*) FROM `{dst}`.`dependencies` WHERE `issue_id` = '{lit}' "
        f"OR `depends_on_issue_id` = '{lit}'"
    )
    if dep_count_p.returncode != 0:
        _delete_item_rows_best_effort(dst, item_id, dep_ids=movable_dep_ids)
        raise BeadsError(
            f"moving {item_id!r} from {src!r} to {dst!r}: could not verify dependency rows landed "
            f"in {dst!r}: {_clean_bd_error(dep_count_p.stderr or dep_count_p.stdout)}. The partial "
            f"copy was removed from {dst!r}; {src!r} is untouched."
        )
    dep_lines = [ln for ln in (dep_count_p.stdout or "").splitlines() if ln.strip()][1:]
    dst_dep_count = int(dep_lines[0]) if dep_lines else 0

    if mismatches or dst_dep_count != len(movable_dep_ids):
        _delete_item_rows_best_effort(dst, item_id, dep_ids=movable_dep_ids)
        raise BeadsError(
            f"moving {item_id!r} from {src!r} to {dst!r} left an incomplete copy in {dst!r} "
            f"(mismatched table row counts: {mismatches or 'none'}; dependency rows "
            f"{dst_dep_count}/{len(movable_dep_ids)}). The incomplete copy was removed from "
            f"{dst!r}; {src!r} is untouched."
        )

    delete_statements = [
        f"DELETE FROM `{src}`.`dependencies` WHERE `issue_id` = '{lit}' "
        f"OR `depends_on_issue_id` = '{lit}'"
    ]
    delete_statements += [
        f"DELETE FROM `{src}`.`{t}` WHERE `issue_id` = '{lit}'" for t in _ITEM_CHILD_TABLES
    ]
    delete_statements.append(f"DELETE FROM `{src}`.`issues` WHERE `id` = '{lit}'")
    script = "SET foreign_key_checks=0;\n" + ";\n".join(delete_statements) + ";"
    p = _run_bounded(
        ["dolt", *_dolt_conn_args(), "sql", "-q", script],
        env=_bd_env(),  # non-interactive: see `_bd_env`'s docstring
    )
    if p.returncode != 0:
        raise BeadsError(
            f"moved {item_id!r} into {dst!r} successfully, but removing it from {src!r} "
            f"afterward failed: {_clean_bd_error(p.stderr or p.stdout)}. The item now exists in "
            f"BOTH {src!r} and {dst!r} -- this must be resolved by hand (drop it from {src!r}) "
            f"before either project is used for this id again."
        )

    final_src_counts = _item_row_counts(src, item_id)
    if any(final_src_counts.values()):
        raise BeadsError(
            f"moved {item_id!r} into {dst!r}, but {src!r} still has residue rows after the "
            f"delete reported success: {final_src_counts}. Investigate before using this id in "
            f"either project again."
        )

    return MoveReport(item_id=item_id, src=src, dst=dst, dropped_dependency_edges=dropped)


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


class BeadsUnavailableError(BeadsError):
    """The INFRASTRUCTURE could not be read -- so the answer is UNKNOWN, not
    negative. Distinct from every other `BeadsError`, which reports a real
    domain outcome bd actually computed.

    This exists because the two were indistinguishable, and the system said
    the wrong one out loud. Measured (lane `model_performance-rpz`): under a
    transient dolt read failure, `claim --id` on an item that EXISTS
    reported "item not found" in 9 of 12 attempts; `list --id` on an item
    the calling session HELD reported a bare "item 'X' not found in project
    'Y'" -- cause discarded entirely -- in 2 of 8; `instances` printed a
    healthy project as `ERROR` with null counts in 5 of 10, interleaved with
    correct `ok` rows seconds either side.

    A SUBSTRING is not the fix. Callers must not have to grep an error
    message to learn whether absence was observed or merely assumed, so the
    distinction is carried in the TYPE: `except BeadsUnavailableError` comes
    before `except BeadsError` at each of the three sites that used to
    flatten (`Beads.claim_item`, `Beads.get_readonly`, `project_summary`),
    and the transient case is re-raised untouched, cause intact.

    What this deliberately does NOT do: widen. A genuinely absent item on a
    healthy database still reports plain absence, in exactly the same words
    as before -- see the `read.unavailable_not_absent` contract check, which
    fences BOTH directions. Replacing "it does not exist" with "it might not
    exist" everywhere would be a second lie, not a fix.

    Raised only where a `dolt`/`bd` read failed at the TRANSPORT layer --
    classified by `_connection_retryable`, the same conservative predicate
    that decides what is safe to retry, applied in `_sql_failure`.
    """


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


def _parse_dolt_timestamp(v: object) -> datetime | None:
    """Parse a `datetime` column as dolt's SQL CSV renders it -- `YYYY-MM-DD
    HH:MM:SS`, a NAIVE wall-clock with no zone marker -- into the SAME
    timezone-aware UTC `datetime` `_parse_bd_timestamp` would have produced
    for the identical instant.

    Why a second parser: `project_summary` reads its items straight off the
    shared dolt server now (see `_summary_items_via_sql`), not through `bd`,
    so timestamps arrive in dolt's bare SQL shape rather than bd's ISO-8601
    `...Z`. bd stores these columns in UTC (verified: bd's own `--json`
    reports `created_at` as `...Z` for the exact same row dolt renders bare),
    so the correct reconstruction is "parse the wall-clock, stamp it UTC" --
    NOT `fromisoformat` alone, which would yield a naive datetime and then
    raise the moment `project_activity` subtracts it from an aware `now`.

    Returns `None` for empty/NULL (dolt renders a NULL `closed_at` as an
    empty CSV field) or anything unparseable -- never a fabricated instant,
    the same discipline as `_parse_bd_timestamp`.
    """
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        parsed = datetime.fromisoformat(v.strip())
    except ValueError:
        logger.debug("could not parse dolt timestamp %r", v)
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


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


# --------------------------------------------------------------------------
# Workspace-bootstrap metadata. An item's markdown description may carry a
# fenced ```yaml block naming the repos to check out and the context files a
# lane needs before it can start work. We parse that out at the seam, so
# every read surface (`work_claim`, `work_list --id`) sees the same
# structured `repos`/`context` lists instead of each re-scraping the prose.
# --------------------------------------------------------------------------

# One fenced ```yaml block, first match wins. Tolerant of `yml`, of trailing
# spaces after the language tag, and of CRLF line endings; case-insensitive
# on the language tag only.
_BOOTSTRAP_FENCE_RE = re.compile(
    r"```[ \t]*ya?ml[ \t]*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

_BOOTSTRAP_KEYS = ("repos", "context")


def _clean_scalar(s: str) -> str:
    """Trim one list-item/inline scalar down to its value: surrounding
    whitespace gone, and one layer of matching single/double quotes removed
    if present. Deliberately minimal -- this is a fixed, shallow shape (a
    flat list of repo slugs / context paths), never arbitrary YAML."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1]
    return s.strip()


def _parse_inline_list(rest: str) -> list[str]:
    """A value that sits on the same line as its key: either flow style
    (`[a, b, c]`) or a single bare scalar (`just-one`). An empty `[]` yields
    an empty list."""
    rest = rest.strip()
    if rest.startswith("[") and rest.endswith("]"):
        inner = rest[1:-1]
        return [_clean_scalar(p) for p in inner.split(",") if p.strip()]
    cleaned = _clean_scalar(rest)
    return [cleaned] if cleaned else []


def _parse_yaml_list_key(body: str, key: str) -> list[str]:
    """Pull one top-level list-valued key out of a small YAML block, with a
    stdlib-only parser (no PyYAML dependency for a shape this fixed).

    Handles the two spellings a human actually writes:
      - block style -- `key:` on its own line, then `- item` lines beneath it;
      - inline flow style -- `key: [a, b]` (or a lone `key: value` scalar).

    Only an UNINDENTED occurrence of the key counts, so a `- context` list
    item or a deeper nested key is never mistaken for the anchor. The block
    list ends at the first non-blank line that is not a `- ` item (e.g. the
    next top-level key). Absent key -> empty list, never an error.
    """
    lines = body.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        i += 1
        # Top-level key only: no leading indentation.
        if line[:1] in (" ", "\t"):
            continue
        stripped = line.strip()
        if not stripped.startswith(f"{key}:"):
            continue
        rest = stripped[len(key) + 1 :].strip()
        if rest:
            return _parse_inline_list(rest)
        items: list[str] = []
        while i < n:
            follow = lines[i]
            fstripped = follow.strip()
            if fstripped == "":
                i += 1
                continue
            if fstripped.startswith("- ") or fstripped == "-":
                items.append(_clean_scalar(fstripped[1:]))
                i += 1
                continue
            break
        return items
    return []


def parse_bootstrap_metadata(description: str | None) -> dict:
    """Extract workspace-bootstrap metadata from an item's markdown
    description: the `repos:` and `context:` lists inside a fenced ```yaml
    block.

    Always returns both keys, always as lists -- `{"repos": [...],
    "context": [...]}`. An item with NO such block (the overwhelming common
    case) yields two empty lists and never raises: full backward
    compatibility with every pre-existing item. Only the FIRST fenced yaml
    block is consulted.
    """
    if not description:
        return {"repos": [], "context": []}
    m = _BOOTSTRAP_FENCE_RE.search(description)
    if not m:
        return {"repos": [], "context": []}
    body = m.group(1)
    return {key: _parse_yaml_list_key(body, key) for key in _BOOTSTRAP_KEYS}


@dataclass(frozen=True)
class Erratum:
    """One APPEND-ONLY correction recorded against a resolved item's own
    record -- never a rewrite of `Item.resolution` itself. `at` is this
    erratum's own UTC timestamp (`_erratum_now_iso`'s format,
    `%Y-%m-%dT%H:%M:%SZ` -- the same shape `custody.now_iso()` uses), `by`
    the actor who recorded it (bd's own comment `author` column, read back
    as authoritative -- see `_parse_erratum_comment`), `text` the
    correction body. See `Beads.erratum` for the full write-side contract.
    """

    at: str
    by: str
    text: str


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
    repos: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    priority: int | None = None
    links: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    created_by: str | None = None
    # Append-only corrections to `resolution` -- see `Erratum`/`Beads.erratum`.
    # `errata` is populated FULLY only by a single-item read (`_get_item_via_sql`,
    # `Beads.get(with_links=True)`); a many-row `list()`/`list_bounded()` listing
    # leaves it `[]` (see `_list_rows_via_sql`'s docstring) and populates only
    # the cheap, aggregate-derived `corrected` flag below. `corrected` is
    # therefore NOT always exactly `bool(errata)` -- on a lean list row it is
    # True/False from the aggregate count with `errata` left empty; on a full
    # single-item read it is recomputed as `bool(errata)` directly, so the two
    # can never disagree for that one item.
    errata: list[Erratum] = field(default_factory=list)
    corrected: bool = False
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
        # Workspace-bootstrap metadata, parsed once here at the seam from the
        # item's own description -- an item with no fenced ```yaml block gets
        # two empty lists and behaves exactly as before (see
        # `parse_bootstrap_metadata`).
        bootstrap = parse_bootstrap_metadata(out.get("description"))
        out["repos"] = bootstrap["repos"]
        out["context"] = bootstrap["context"]
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
            # Cheap on every row (a boolean, never the erratum TEXT) -- see
            # `Item.errata`'s own note on why a lean listing carries this
            # flag but not the errata list itself.
            "corrected": self.corrected,
        }
        if full:
            row["acceptance"] = self.acceptance
            row["description"] = self.description
            row["design"] = self.design
            # Workspace-bootstrap metadata parsed from the description (see
            # `parse_bootstrap_metadata`) -- always present as lists on a full
            # read, empty for an item that carries no fenced ```yaml block.
            row["repos"] = self.repos
            row["context"] = self.context
            row["created_at"] = self.created_at.isoformat() if self.created_at else None
            row["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
            row["closed_at"] = self.closed_at.isoformat() if self.closed_at else None
            row["created_by"] = self.created_by
            # Full errata -- oldest -> newest, exactly `Beads.erratum`'s
            # append order -- only on a directed single-item read (see
            # `Item.errata`'s own note; a lean list row never carries this).
            row["errata"] = [{"at": e.at, "by": e.by, "text": e.text} for e in self.errata]
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
    links -- i.e. actually blocking a claim.

    Read straight from the raw `show` payload's `dependencies` field, which
    IS present without `--include-dependents` (that flag only gates the
    REVERSE direction -- ASSUMPTION show.dependents). Only ever populated
    when `item` came from `bd show` itself (`Beads.get(with_links=True)`,
    or the frozen pre-fix reconstruction in
    `tests/integration/test_get_via_sql_equivalence.py`) -- an `Item` read
    via `_get_item_via_sql` (the default, `with_links=False` path) carries
    no `dependencies` key in `raw` at all, so this always returns `[]` for
    one of those. `claim_item` -- the one caller that needs this check --
    uses `_forward_active_blockers_via_sql` instead, precisely so its
    blocker-refusal check never depends on `bd show` having been called.
    """
    deps = item.raw.get("dependencies") or []
    return [
        d
        for d in deps
        if isinstance(d, dict) and _is_active_blocker(d.get("dependency_type"), d.get("status"))
    ]


def _forward_active_blockers_via_sql(db: str, item_id: str) -> list[dict]:
    """Which of `item_id`'s forward `blocks`-type dependencies are still
    open, read via a READ-ONLY SQL SELECT -- the `claim_item`-only
    equivalent of `_active_blockers` (which reads `Item.raw["dependencies"]`,
    a field only bd's own `show` JSON populates), so a directed claim's
    refusal-check read can never itself lose a serialization conflict --
    same motivation as `_get_item_via_sql` replacing `bd show` for the base
    item read; see that function's docstring for the shared mechanism.

    Joins the `dependencies` table (`issue_id`, `depends_on_issue_id`,
    `type`) to `issues` on the TARGET side to learn each blocker's own
    current `status` -- exactly what `_is_active_blocker` (reused
    unchanged) needs to decide whether an edge still blocks. An INNER JOIN
    naturally excludes any edge whose `depends_on_issue_id` is NULL (a
    wisp/external ref, not a real issue -- see `copy_database`'s own note
    on the same distinction): a `blocks`-type edge is issue-to-issue only
    in practice, so this can never silently drop a real blocker.

    Returns dicts shaped `{"id", "status"}` -- the same two fields
    `claim_item`'s own error message reads off each blocker
    (`b["id"]`/`b.get("status")`); `dependency_type` is consulted here,
    at the seam, and not carried through (nothing downstream needs it once
    the "active blocker" filter has already been applied).
    """
    p = _dolt_sql_json(
        "SELECT `dep`.`type` AS `dependency_type`, `tgt`.`id` AS `id`, "
        "`tgt`.`status` AS `status` "
        f"FROM `{db}`.`dependencies` `dep` "
        f"JOIN `{db}`.`issues` `tgt` ON `tgt`.`id` = `dep`.`depends_on_issue_id` "
        f"WHERE `dep`.`issue_id` = '{_sql_literal(item_id)}'"
    )
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read dependencies of {item_id!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    try:
        rows = json.loads(p.stdout or "{}").get("rows", [])
    except json.JSONDecodeError as e:
        raise BeadsError(f"could not parse dependencies of {item_id!r} over SQL: {e}") from e
    return [
        {"id": r.get("id"), "status": r.get("status")}
        for r in rows
        if isinstance(r, dict) and _is_active_blocker(r.get("dependency_type"), r.get("status"))
    ]


def _forward_dependency_links_via_sql(db: str, item_id: str) -> list[dict]:
    """`item_id`'s forward (`direction: "from"`) dependency edges -- i.e.
    what THIS item depends on / is blocked by / supersedes / etc -- read via
    a READ-ONLY SQL SELECT, in the exact `Item.links` entry shape `Beads.get`'s
    own `_link()` helper produces for its `with_links=True` path (`id`/
    `direction`/`type`/`title`/`status`/`holder`/`created_by`/`blocking`).

    Why this exists: forward edges are meant to be present on EVERY `get()`
    regardless of `with_links` -- bd's own `dependencies` field needs no
    `--include-dependents` flag, so this was always the pre-existing
    behavior back when the base-item read went through `bd show` directly
    (see `Beads.get`'s docstring, and `tests/integration/test_dependency.py`'s
    `test_get_readonly_with_links_displays_the_same_edge`, which pins the
    invariant explicitly). Moving the base-item read to `_get_item_via_sql`
    (a pure SELECT against `issues` alone) dropped that invariant, since
    that helper deliberately does not touch the `dependencies` table at all
    -- this function restores it, over the same contention-safe mechanism
    (a pure SELECT has no write set and cannot serialization-conflict, at
    any project size; see `_get_item_via_sql`'s docstring for the shared
    reasoning). Only the REVERSE direction (`dependents`, gated by bd's own
    `--include-dependents`) stays on `bd show` in `Beads.get`'s
    `with_links=True` branch -- seeing everything that points AT this item
    is a comparatively rare, heavier need (bd's own `--help` warns it "may
    be slow on hub beads"), unlike this item's OWN handful of forward
    edges, which is cheap and needed unconditionally.

    Joins `dependencies` to `issues` on the TARGET side (`depends_on_issue_id`)
    to pull the referenced item's own title/status/holder/created_by --
    exactly the fields `Beads.get`'s `_link()` populates for a `direction:
    "from"` entry (bd's own asymmetry: only the forward direction embeds
    the FULL referenced item; see that method's docstring). An INNER JOIN
    naturally excludes an edge whose `depends_on_issue_id` is NULL (a
    wisp/external ref, not a real issue -- same exclusion
    `_forward_active_blockers_via_sql` already relies on), so a real
    issue-to-issue edge can never be silently dropped.

    `status` is translated through `_map_status` (our vocabulary, not bd's
    raw one) -- the same translation `_link()` applies -- and `blocking`
    is computed via the SAME `_is_active_blocker` check `claim_item`'s own
    refusal read uses, so the two can never disagree on what "still
    blocking" means.
    """
    p = _dolt_sql_json(
        "SELECT `dep`.`type` AS `dependency_type`, `tgt`.`id` AS `id`, "
        "`tgt`.`title` AS `title`, `tgt`.`status` AS `status`, "
        "`tgt`.`assignee` AS `assignee`, `tgt`.`created_by` AS `created_by` "
        f"FROM `{db}`.`dependencies` `dep` "
        f"JOIN `{db}`.`issues` `tgt` ON `tgt`.`id` = `dep`.`depends_on_issue_id` "
        f"WHERE `dep`.`issue_id` = '{_sql_literal(item_id)}'"
    )
    if p.returncode != 0:
        raise _sql_failure(
            f"could not read forward dependency links of {item_id!r} over SQL: "
            f"{_clean_bd_error(p.stderr or p.stdout)}",
            p,
        )
    try:
        rows = json.loads(p.stdout or "{}").get("rows", [])
    except json.JSONDecodeError as e:
        raise BeadsError(
            f"could not parse forward dependency links of {item_id!r} over SQL: {e}"
        ) from e
    links: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        dep_type = r.get("dependency_type")
        raw_status = r.get("status")
        links.append(
            {
                "id": r.get("id"),
                "direction": "from",
                "type": dep_type,
                "title": r.get("title"),
                "status": _map_status(raw_status) if raw_status else None,
                "holder": r.get("assignee"),
                "created_by": r.get("created_by"),
                "blocking": _is_active_blocker(dep_type, raw_status),
            }
        )
    return links


def _sql_failure(message: str, p: subprocess.CompletedProcess) -> BeadsError:
    """Build the right exception for a failed direct-SQL `dolt` read.

    ONE classifier, so the six SQL read sites cannot drift into six
    different opinions about what a transport failure looks like. Returns a
    `BeadsUnavailableError` (infrastructure unreachable -- the answer is
    UNKNOWN) when `p`'s own output carries a transport signature, else a
    plain `BeadsError` (a real, computed failure).

    Reuses `_connection_retryable` verbatim rather than inventing a second
    signature list: "safe to retry" and "this was infrastructure, not an
    answer" are the same judgement, and a second list would be a second
    place for it to go stale. Conservative by construction -- a signature
    that can never appear in a legitimate bd domain result -- so this can
    never soften a genuine failure into "maybe transient".
    """
    if _connection_retryable((p.stdout or "") + (p.stderr or "")):
        return BeadsUnavailableError(message)
    return BeadsError(message)


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


# --------------------------------------------------------------------------
# Quoting foreign output on a HANDLED path.
#
# `logger.warning` and above reach a plain CLI invocation's stderr with no
# handler configured at all -- Python's "handler of last resort", the same
# mechanism `_clean_bd_error` documents above. So a warning that interpolates
# a subprocess's stderr verbatim republishes THAT program's error
# ANNOUNCEMENT as if it were this command's own.
#
# Measured, `model_performance-kxk`: `doctor --quick` detected a dirty schema
# migration, dropped, retried, succeeded, printed `All 35 assumptions hold`
# and exited 0 -- with this on stderr:
#
#   project 'contract...': bd init hit a dirty schema migration -- dropping
#     and retrying once: [mysql] ... busy buffer
#   Error: failed to open Dolt store: failed to initialize schema: ...
#
# That second line is NOT bd's stderr escaping around us. It is inside our
# own warning: `blob.strip()[:300]` is a MULTI-LINE blob, and the quoted text
# in the recorded evidence is exactly 300 characters long -- it stops
# mid-sentence at "run 'bd dolt commit' to", the slice boundary. We printed
# it, on a path where nothing ultimately failed.
#
# From outside, an error announcement alongside exit 0 is indistinguishable
# from the silent-failure shape `tests/_util.assert_no_silent_failure` exists
# to forbid, so a HEALED run can fail a CLI-tier test intermittently, with a
# real-looking message. That is the worst kind of flake.
#
# The fix is NOT to go quiet. The recovery must stay visible and the cause is
# worth reading. It is to quote bd's text as DESCRIPTION rather than
# republish it as ANNOUNCEMENT -- the exact distinction `model_performance-wp6`
# drew (802c204) when it stopped the predicate matching prose. Two narrow
# transformations:
#
#   1. Flatten to one line. A multi-line quoted blob puts `Error:` at the
#      start of a line of OUR stderr, which is precisely where it reads as
#      ours rather than as quoted material.
#   2. Attribute each announcement to bd instead of asserting it: `Error:`
#      becomes `[bd Error]`. The word survives (still greppable), the detail
#      survives (still readable); only the impersonation ends.
#
# The rules below deliberately cover EVERY shape in
# `tests/_util._ERROR_ANNOUNCEMENT_RES`, not just the one observed -- a
# handled path must not republish any of them. Product code cannot import a
# test helper, so `tests/unit/test_handled_output_is_not_an_announcement.py`
# closes the loop from the other side: it runs the real test-side predicate
# over this function's output, and goes red if a shape is ever added there
# without being defused here.
# --------------------------------------------------------------------------
_HANDLED_OUTPUT_DEFUSALS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JSON error field first: `"error":` must not be reshaped by the
    # colon-announcement rule below, which would leave the JSON key mangled.
    (re.compile(r'("error")\s*:', re.IGNORECASE), r"\1 ="),
    (re.compile(r"\b(error|fatal|panic)\s*:", re.IGNORECASE), r"[bd \1]"),
    (re.compile(r"\b(error)(\s+running\b)", re.IGNORECASE), r"[bd \1]\2"),
    (re.compile(r"\bunknown\s+command\b", re.IGNORECASE), "unknown-command"),
    (re.compile(r"(Traceback \(most recent call last\))\s*:"), r"\1"),
)


def _quote_handled_output(blob: str | None, *, limit: int = STATUS_ERROR_MAX) -> str:
    """Render another program's output for quoting inside a log line on a
    path this module HANDLED -- see the block comment above for the measured
    leak this exists to stop.

    Distinct from `_clean_bd_error`, and the two must not be merged.
    `_clean_bd_error` builds the text of a `BeadsError` -- a real failure,
    on its way to a non-zero exit, which SHOULD announce loudly. This one is
    for the opposite case: a condition that was detected and recovered from,
    where the announcement would be a lie.

    Returns one line, with every error-announcement shape attributed to its
    source rather than asserted, truncated at a word boundary.
    """
    one_line = " ".join((blob or "").split())
    if not one_line:
        return "(bd reported no detail)"
    for pattern, replacement in _HANDLED_OUTPUT_DEFUSALS:
        one_line = pattern.sub(replacement, one_line)
    return truncate_status(one_line, limit)


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


@dataclass
class ReleaseOutcome:
    """Result of `Beads.release` -- distinguishes a genuine release (item
    handed back to the queue, status now `open`) from the sanctioned
    wedge-recovery no-op branch (item was ALREADY resolved/closed; nothing
    was written -- see `release`'s own docstring, work_tracker item
    pipeline-yym). Every existing caller ignores `release`'s return value,
    so this is an additive, non-breaking change to its signature.
    """

    item_id: str
    already_closed: bool


# ---------------------------------------------------------------- resolution
#
# The resolution TEXT -- not merely the item's status -- is what `resolve`
# compares to decide whether its own write landed. Comparing status alone
# was the measured defect (work_tracker item model_performance-uma, spec
# `w3-uma-work-tracker-reopen/SPEC.md`): a `resolve` against an ALREADY
# closed item exited 0 and echoed the OLD stored text back as if it were
# the text just written, so a correction was silently discarded and the
# caller was told it had landed.

RESOLUTION_ECHO_LIMIT = 400


def _norm_resolution(text: str | None) -> str:
    """Normalize a resolution for comparison: line endings unified, outer
    whitespace stripped. NOTHING ELSE.

    Case is significant and internal whitespace is significant, both
    deliberately -- those are real edits to what a human will read, and a
    normalization that swallowed them would re-open exactly the silent-
    discard hole this comparison exists to close. Only the two differences
    a transport can introduce on its own (CRLF, a trailing newline) are
    normalized away.
    """
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _resolution_landed(stored: str | None, sent: str) -> bool:
    """Is `stored` (what the item actually carries) the same resolution as
    `sent` (what this caller asked to write), after `_norm_resolution`?"""
    return _norm_resolution(stored) == _norm_resolution(sent)


def _echo_resolution(text: str | None, *, limit: int = RESOLUTION_ECHO_LIMIT) -> str:
    """One resolution rendered for a side-by-side error message -- never
    silently truncated: an elided text says so, with its real length."""
    s = text or ""
    if not s.strip():
        return "(none -- blank)"
    if len(s) <= limit:
        return s
    return f"{s[:limit]}... [truncated, {len(s)} chars]"


def _divergent_resolution_error(
    item_id: str,
    *,
    project: str,
    stored: str | None,
    sent: str,
    contended: bool = False,
) -> BeadsError:
    """The refusal a caller gets for resolving an already-closed item with
    text that is NOT what the item stores.

    Every requirement on this message was earned by a measured failure:

      1. BOTH texts, side by side. The only way this defect was ever
         caught was a human diffing the echoed text against what was sent.
         Do that diff for the caller.
      2. The words "NOTHING WAS WRITTEN", literally. Under the contention
         contract (`cli.py`'s module docstring) an agent's default reading
         of a failure is "the transaction aborted" -- which here is true,
         and must not be second-guessed into a blind retry that would
         re-send the same discarded text.
      3. The remedy as a RUNNABLE command, on both surfaces (CLI and
         tool), because the caller's next question is always "then how do
         I correct it?" and the answer (`reopen`) is new.
    """
    lead = (
        f"refusing to resolve {item_id}: it is already resolved, and the resolution "
        f"stored on the item is NOT the text you sent. NOTHING WAS WRITTEN."
    )
    if contended:
        lead = (
            f"refusing to report success for resolve {item_id}: the write raised under "
            f"contention, and the readback shows the item resolved with a resolution that "
            f"is NOT the text you sent. YOUR TEXT WAS NOT WRITTEN."
        )
    return BeadsError(
        f"{lead}\n\n"
        f"  stored (unchanged): {_echo_resolution(stored)}\n"
        f"  you sent:           {_echo_resolution(sent)}\n\n"
        f"To correct the official record, reopen it first:\n"
        f"  amplifier-work-tracker reopen --project {project} --id {item_id} "
        f"--reason '<why the stored text is wrong>'\n"
        f"  (agents: work_reopen(project={project!r}, item_id={item_id!r}, reason=...))"
    )


# The raw bd status a `_set_status_with_reason` call is asking for, mapped to
# the VERB the caller actually typed -- so a refusal reads "refusing to defer
# <id>", the words that are on their screen, not "refusing to deferred <id>".
_STATUS_CHANGE_VERB = {"deferred": "defer", "blocked": "block"}


def _status_change_on_resolved_error(
    item_id: str,
    *,
    project: str,
    verb: str,
    stored: str | None,
    closed_at: datetime | None,
) -> BeadsError:
    """The refusal a caller gets for `defer`/`block` on an item that is
    already RESOLVED.

    MEASURED (bd 1.1.2, work_tracker item model_performance-2nx,
    2026-09-03): `bd update --status deferred` (or `blocked`) against a
    closed issue succeeds, exit 0, AND blanks `close_reason` -- so the
    OFFICIAL, ALREADY-PUBLISHED resolution text is destroyed with no
    warning, no archive, and no trace of what it used to say. That is
    strictly worse than the defect `resolve`'s divergent-text refusal
    closes: that one discarded the text you SENT; this one discards the
    text already STORED. `release` has gone to deliberate lengths to make
    reopening a closed item "structurally impossible from this path" --
    while these two did exactly that, destructively, one verb away.

    The message carries the same three things `_divergent_resolution_error`
    earned, for the same measured reasons:

      1. The TEXT AT RISK, echoed. A caller who cannot see what would be
         destroyed cannot judge whether they meant to destroy it.
      2. The words "NOTHING WAS WRITTEN", literally -- under the contention
         contract (`cli.py`'s module docstring) an agent's default reading
         of a failure is "the transaction aborted", which here is true and
         must not be second-guessed into a blind retry.
      3. The remedy as a RUNNABLE command on both surfaces. `reopen` is the
         SAFE door to the same place: it archives the previous resolution
         and `closed_at` into an attributed comment BEFORE transitioning.
         This refusal closes the unsafe door without closing that one.
    """
    return BeadsError(
        f"refusing to {verb} {item_id}: it is already resolved, and {verb} would move it "
        f"out of resolved and DESTROY the resolution stored on it. NOTHING WAS WRITTEN.\n\n"
        f"  status:             resolved\n"
        f"  stored (unchanged): {_echo_resolution(stored)}\n"
        f"  closed_at:          {closed_at.isoformat() if closed_at else '(none)'}\n\n"
        f"If you genuinely mean to reopen it, use `reopen` -- it archives the resolution "
        f"above (and closed_at) into an attributed comment FIRST:\n"
        f"  amplifier-work-tracker reopen --project {project} --id {item_id} "
        f"--reason '<why the stored text is wrong>'\n"
        f"  (agents: work_reopen(project={project!r}, item_id={item_id!r}, reason=...))"
    )


@dataclass(frozen=True)
class ResolveOutcome:
    """Result of `Beads.resolve_outcome` -- the item as it stands after a
    verified close, plus whether this call actually WROTE that resolution
    or merely found its own identical text already stored.

    `idempotent` exists because those two are byte-identical today and the
    difference matters when reconciling a contended run: a caller that
    re-ran `resolve` after an ambiguous failure needs to tell "my write
    landed earlier" from "my write landed just now". See `resolve_outcome`
    for the full rule.
    """

    item: Item
    idempotent: bool = False


@dataclass(frozen=True)
class ReopenOutcome:
    """Result of `Beads.reopen` -- the reopened item, plus the record the
    reopen destroyed.

    `previous_resolution` is carried out in the RESULT, not merely filed
    in the item's comment history, because the caller is about to write
    the replacement and the most common correction is a targeted edit of
    the old text; making them go find it invites a rewrite that loses
    detail. `previous_closed_at` is surfaced for the opposite reason -- it
    is a real cost, not a footnote: `bd reopen` clears `closed_at`, so a
    corrected item stops counting toward the day it was genuinely resolved
    and re-lands on the correction date (see `_velocity_raw_daily`).
    """

    item: Item
    previous_resolution: str | None
    previous_closed_at: datetime | None
    reopen_reason: str
    actor: str


@dataclass(frozen=True)
class ErratumOutcome:
    """Result of `Beads.erratum` -- the item as it stands after the append
    (its `errata`/`corrected` reflect the write, or the prior state on the
    idempotent path), plus whether this call actually WROTE a new erratum
    or found a byte-identical one already recorded by any actor (mirrors
    `ResolveOutcome.idempotent`'s own same-text rule, applied to errata
    rather than the resolution field itself).
    """

    item: Item
    already_recorded: bool = False


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
            # `p.returncode != 0` gate here mirrors the connection-retryable
            # check immediately above -- ADDED for work_tracker item
            # pipeline-yym. `_retryable` is a pure TEXT predicate (see its
            # own tests) with no opinion on exit status; without this gate,
            # a SUCCESSFUL invocation (returncode 0) whose own combined
            # stdout/stderr merely *mentions* one of the retryable
            # substrings -- e.g. bd logging that it recovered internally
            # from a transient serialization conflict before reporting
            # success -- was retried anyway. If a later attempt in the same
            # loop echoes equivalent text (an idempotent `bd close` against
            # an item that a PRIOR attempt already closed does exactly
            # this), the loop can exhaust `_MAX_RETRIES` and raise
            # `BeadsError` while quoting its own most recent SUCCESS
            # confirmation -- the measured incident (2026-09-01,
            # cortex-cro0): the wrapper reported "still conflicting after 8
            # retries" with a "Last:" detail that was itself a successful
            # close confirmation for the same item. See `resolve`'s
            # verify-by-read-back fix for the safety net that catches this
            # class of failure even when it is not this exact mechanism.
            if p.returncode != 0 and _retryable(blob):
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

    # ------------------------------------------------- verified write (one home)

    @staticmethod
    def _landed(verify: Callable[[], bool]) -> bool:
        """`verify()`, but never raising and never True-by-accident.

        Used ONLY on a write's FAILURE path, where the question is "did the
        write land anyway?". A verification that cannot itself run (the
        read errored, the item vanished, dolt hiccuped) answers "no
        evidence it landed" -- which re-raises the ORIGINAL error rather
        than masking it behind a second, unrelated one. Deliberately NOT
        used on the success path: there, a verification that cannot run is
        a real failure to prove the write, and must surface as such.
        """
        try:
            return bool(verify())
        except Exception:
            return False

    def _verified_write(
        self,
        run: Callable[[], subprocess.CompletedProcess],
        verify: Callable[[], bool],
        *,
        what: str,
    ) -> subprocess.CompletedProcess | None:
        """Perform ONE `bd` write and PROVE it landed by reading the item
        back through the contention-free path. The single home for the
        "exit code is not proof" discipline every item-level write verb in
        this class shares -- generalized from the shape PR #63 gave a
        conflicted `resolve`/`release`, so no verb has to reinvent (or
        forget) it.

        `run` performs the write and returns its `CompletedProcess` (it may
        also stash whatever it parsed off stdout for `verify` to use -- see
        `create`/`claim_next`). `verify` answers ONE question against a
        fresh, contention-free read: is the intended state actually there?
        `what` names the operation for error text (e.g. `"release wt-3"`).

        Three paths, none of which trusts an exit code on its own:

          - `run` RAISES `BeadsError` -- `_run`'s serialization-retry
            budget is exhausted. Exhaustion does NOT prove the write never
            landed: the measured incident (work_tracker item pipeline-yym,
            2026-09-01) was a close that HAD landed on an earlier attempt
            while the wrapper still raised, quoting its own success
            confirmation. Verify; if the state is there, report success
            (returning `None`, since bd's own output for that attempt is
            gone). Otherwise re-raise the original, untouched.
          - `run` RETURNS a non-zero exit whose output names a
            conflict/connection-transport failure -- same reasoning, same
            treatment. A genuine domain error (bd refused, item not found,
            already closed) is NOT verified away: it raises with bd's own
            message, exactly as before.
          - `run` RETURNS success -- verify anyway. A `bd` write that exits
            0 without changing anything is indistinguishable from one that
            did, until something reads it back. A phantom success raises.

        Returns the `CompletedProcess` when the write itself reported
        success (callers that need its stdout use it), or `None` when the
        write reported failure but the read-back proved it landed.
        """
        try:
            p = run()
        except BeadsError:
            if self._landed(verify):
                return None
            raise
        if p.returncode != 0:
            blob = (p.stdout or "") + (p.stderr or "")
            if (_retryable(blob) or _connection_retryable(blob)) and self._landed(verify):
                return None
            raise BeadsError(f"{what}: {_clean_bd_error(p.stderr or p.stdout)}")
        if not verify():
            raise BeadsError(
                f"{what} reported success but the write did not land -- exit code is "
                f"not proof (checked by contention-free read-back)."
            )
        return p

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
        related: list[tuple[str, str]] | None = None,
        actor: str | None = None,
    ) -> str:
        """Create a new item. `related` is an optional list of `(id,
        relation_kind)` pairs -- our vocabulary for a loose cross-reference
        recorded structurally, the SAME dependency-edge mechanism
        `add_dependency`/`get(with_links=True)` already write/read, not a
        separate, second linking system. `relation_kind` is one of
        `RELATION_KINDS` ("relates-to", "supersedes", "follow-up-of" --
        mapped to bd's own dependency-type vocabulary via that constant);
        an unrecognized kind refuses the WHOLE create (raised before any
        `bd` call), rather than creating the item and silently dropping an
        edge nobody could later discover was requested. Passed through
        bd's own `--deps` flag alongside `discovered_from`, so both land in
        the SAME atomic `bd create` call -- no separate, unverified
        follow-up write.

        Verified by read-back on BOTH paths (`_verified_write`), which for
        a create needs two different keys because the obvious one is not
        always available:

          - SUCCESS path: bd prints the new id on stdout; the item is read
            back BY THAT ID through the contention-free SQL path and its
            title checked. A `bd create` that exits 0 having written
            nothing therefore raises instead of returning a dangling id.
          - CONFLICT path: the wrapper raised, so bd's stdout -- and with
            it the only stable key -- is gone. Falls back to the id-set
            difference over this exact title (`_ids_via_sql`, snapshotted
            BEFORE the write): exactly one new row means the create landed
            and names it; none means it genuinely did not; more than one
            is ambiguous and re-raises rather than guessing which row was
            ours. This is the only verb here whose conflict-path proof is
            weaker than a keyed read-back, and the ambiguity is resolved
            conservatively -- never by picking a row.
        """
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
        deps: list[str] = []
        if discovered_from:
            deps += [f"{LINK_DISCOVERED_FROM}:{i}" for i in discovered_from]
        if related:
            for other_id, relation_kind in related:
                dep_type = RELATION_KINDS.get(relation_kind)
                if dep_type is None:
                    raise BeadsError(
                        f"create: unknown relation kind {relation_kind!r} for related id "
                        f"{other_id!r} -- must be one of {sorted(RELATION_KINDS)}"
                    )
                deps.append(f"{dep_type}:{other_id}")
        if deps:
            args += ["--deps", ",".join(deps)]
        args += ["--silent"]
        title_where = f"`title` = '{_sql_literal(title)}'"
        before = _ids_via_sql(self.project_name, title_where)
        created: list[str] = []

        def _do_create() -> subprocess.CompletedProcess:
            p = self._run(args, actor=actor)
            out = (p.stdout or "").strip()
            if p.returncode == 0 and out:
                new_id = out.splitlines()[-1].strip()
                if new_id:
                    created.append(new_id)
            return p

        def _verify() -> bool:
            if created:  # bd named the id -- confirm it independently
                back = _get_item_via_sql(self.project_name, created[0])
                return back is not None and back.title == title
            new = _ids_via_sql(self.project_name, title_where) - before
            if len(new) != 1:  # zero == did not land; >1 == ambiguous, never guess
                return False
            created.append(next(iter(new)))
            return True

        self._verified_write(_do_create, _verify, what=f"create {title!r}")
        if not created:  # unreachable via _verified_write, guarded rather than assumed
            raise BeadsError(f"create {title!r}: reported success but no id could be resolved")
        return created[0]

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
        change would otherwise look identical to a silent no-op. Routed
        through `_verified_write`, so the SAME read-back also decides a
        conflict-family failure: a wrapper that gave up on an update that
        had already landed reports success, not a false failure.
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
        seen: list[Item] = []

        def _verify() -> bool:
            back = self.get(item_id)
            if (
                (title is not None and back.title != title)
                or (description is not None and back.description != description)
                or (acceptance is not None and back.acceptance != acceptance)
                or (design is not None and back.design != design)
            ):
                return False
            seen.append(back)
            return True

        self._verified_write(
            lambda: self._run(args, actor=actor), _verify, what=f"update {item_id}"
        )
        return seen[-1]

    def comment(self, item_id: str, text: str, *, actor: str | None = None) -> None:
        """Append a comment to an item -- bd's own audit-trail mechanism
        (`bd comment <id> "<text>"`; the read side, `bd comments <id>
        --json`, already backs `activity`). Attributed via bd's own
        `--actor` audit trail, same identity `resolve`/`claim` carry.

        Used by `edit_item` to record who changed what on a content edit,
        and available standalone for any other audit-trail note a caller
        wants attached to an item without touching its own fields.

        Verified by read-back like every other write here, but by COUNT
        rather than presence: an item may legitimately already carry a
        comment with this exact text (two identical edits), so "a matching
        comment exists" would report success for a write that never
        happened. The count of exactly-matching comments taken before the
        write must have increased.
        """

        def _matching() -> int:
            got = self._json(["comments", item_id])
            rows = got if isinstance(got, list) else []
            return sum(1 for c in rows if isinstance(c, dict) and c.get("text") == text)

        before = _matching()
        self._verified_write(
            lambda: self._run(["comment", item_id, text], actor=actor),
            lambda: _matching() > before,
            what=f"comment {item_id}",
        )

    def edit_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        acceptance: str | None = None,
        design: str | None = None,
        actor: str | None = None,
    ) -> Item:
        """Amend an existing item's free-text fields IN PLACE, leaving an
        audit-trail comment recording WHO changed WHAT -- the sanctioned
        way to correct or refine an item's own content after filing,
        WITHOUT resolving it. For the "this item is fully replaced by a
        different one" case (which DOES close the original), see
        `supersede` instead -- that is a structural merge, not a content
        edit, and this method deliberately does not attempt it.

        Delegates the actual field write + verified-readback discipline to
        `update` -- this method's only reason to exist on top of it is the
        attribution trail: `update` alone leaves no record of who changed
        what, or when, beyond bd's own uncurated dolt-commit history.
        Refuses (raises `BeadsError`, no write attempted) if every field is
        `None` -- there is nothing to edit and nothing to attribute.

        The audit comment names only the fields that actually changed (by
        name, not value -- an item's `description` can be arbitrarily large
        free text, and a comment repeating it in full would double the
        item's total text on every edit), e.g. `"jdoe edited: title,
        description"`. A comment failure (bd flaked between the verified
        field write and the comment call) is surfaced as a `BeadsError`
        too -- the field write already landed and verified, but a caller
        must not be told the edit succeeded silently missing its own audit
        trail.
        """
        changed = [
            name
            for name, value in (
                ("title", title),
                ("description", description),
                ("acceptance", acceptance),
                ("design", design),
            )
            if value is not None
        ]
        if not changed:
            raise BeadsError(f"edit {item_id}: no field given -- nothing to change")
        back = self.update(
            item_id,
            title=title,
            description=description,
            acceptance=acceptance,
            design=design,
            actor=actor,
        )
        who = actor or self._actor or "unknown"
        self.comment(item_id, f"{who} edited: {', '.join(changed)}", actor=actor)
        return back

    def supersede(self, item_id: str, replacement_id: str, *, actor: str | None = None) -> Item:
        """Mark `item_id` as superseded by `replacement_id` -- bd's own
        `supersede` command closes the original AUTOMATICALLY with a
        structural reference to the replacement, verified here by
        readback (never merely a non-erroring exit). This is the "true
        merge" case `edit_item` deliberately does not handle: the original
        is genuinely done, replaced wholesale by a different item, and its
        own resolution should say so structurally -- never a fake
        `resolve(..., reason="merged into X")` that loses the replacement's
        actual, machine-readable id.

        Surfaces bd's own error (unchanged) if `replacement_id` does not
        exist or `item_id` is already closed -- no override.

        The readback uses `with_links=True` (verified empirically against
        the real bd binary: `bd supersede` records the replacement as a
        genuine `supersedes`-type dependency edge from `item_id` to
        `replacement_id` -- there is no `close_reason`/resolution text at
        all -- so `replacement_id` is only readable back off `Item.links`/
        `Item.raw["dependencies"]`, never off `Item.resolution`). This is
        the SAME `bd show --include-dependents` path `add_dependency`
        already uses for its own write-verification readback: a single
        one-item bd call for a write method's own post-write proof is the
        established pattern here, not a hot repeated-read path, so it is
        not a candidate for the `_get_item_via_sql` contention fix (see
        `Beads.get`'s docstring for why `with_links=True` deliberately
        stays on bd).
        """
        seen: list[Item] = []

        def _verify() -> bool:
            back = self.get(item_id, with_links=True)
            if back.status != "resolved":
                return False
            if not any(
                link.get("id") == replacement_id and link.get("direction") == "from"
                for link in back.links
            ):
                return False
            seen.append(back)
            return True

        self._verified_write(
            lambda: self._run(["supersede", item_id, "--with", replacement_id], actor=actor),
            _verify,
            what=f"supersede {item_id} with {replacement_id}",
        )
        return seen[-1]

    def claim_next(self, *, lane: str = LANE_WORK, actor: str) -> Item | None:
        """THE claim. Single atomic operation, never read-then-write.

        ASSUMPTION claim.atomic / claim.subcommand / claim.actor_env.
        Identity travels in BEADS_ACTOR because this subcommand rejects an
        explicit assignee flag.

        VERIFIED BY READ-BACK (`_verified_write`), and the returned `Item`
        is the READ-BACK, never the claiming process's own stdout -- a
        claim is the highest-stakes custody write here (its caller
        immediately starts custody on the strength of it), so "bd said so"
        is not enough. Three outcomes, kept distinct:

          - bd claimed an item: it is read back through the contention-free
            SQL path and must show THIS actor holding it.
          - bd found nothing ready: an empty queue is a normal terminal
            outcome, not a failed write -- `None`, no verification needed.
          - the wrapper reported a conflict-family failure: bd's stdout is
            gone, so which item (if any) it claimed is unknown. Decided by
            the id-set difference over items assigned to this actor,
            snapshotted BEFORE the write (`_ids_via_sql`): exactly one new
            hold means the claim landed and names it; none means it did
            not; more than one is ambiguous and re-raises rather than
            guessing.
        """
        held_where = f"`assignee` = '{_sql_literal(actor)}'"
        held_before = _ids_via_sql(self.project_name, held_where)
        claimed: list[str] = []
        nothing_ready: list[bool] = []

        def _do_claim() -> subprocess.CompletedProcess:
            p = self._run(["ready", "--label", lane, "--claim", "--json"], actor=actor)
            if p.returncode != 0:
                return p
            out = (p.stdout or "").strip()
            try:
                data = json.loads(out) if out else None
            except json.JSONDecodeError as e:
                raise BeadsError(f"`bd ready --claim` returned non-JSON: {out[:200]}") from e
            if isinstance(data, dict) and data.get("error"):
                raise BeadsError(f"`bd ready --claim`: {data['error']}")
            items = data if isinstance(data, list) else ([data] if data else [])
            ids = [i["id"] for i in items if isinstance(i, dict) and i.get("id")]
            if ids:
                claimed.append(str(ids[0]))
            else:
                nothing_ready.append(True)
            return p

        def _verify() -> bool:
            if nothing_ready:  # empty queue -- nothing was written, nothing to verify
                return True
            if not claimed:
                new = _ids_via_sql(self.project_name, held_where) - held_before
                if len(new) != 1:  # zero == did not land; >1 == ambiguous, never guess
                    return False
                claimed.append(next(iter(new)))
            back = _get_item_via_sql(self.project_name, claimed[0])
            return back is not None and back.status == "held" and back.holder == actor

        self._verified_write(_do_claim, _verify, what=f"claim next {lane!r} as {actor!r}")
        return self.get(claimed[0]) if claimed else None

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
        and refuse before ever calling bd's --claim, naming the blocker(s).
        No override flag: if a named blocker doesn't actually apply,
        resolve it or remove the dependency link, then claim again.

        The blocker check itself reads via `_forward_active_blockers_via_sql`
        -- a READ-ONLY SQL query, not `_active_blockers` (which reads
        `Item.raw["dependencies"]`, a field only `bd show`'s own JSON ever
        populates, and `get()`'s base-item path no longer calls `bd show`
        at all -- see `Beads.get`'s docstring). This is strictly safer than
        the previous `bd show`-backed check: a directed claim's own
        refusal-check read can no longer itself lose a serialization
        conflict either.

        VERIFIED BY READ-BACK (`_verified_write`) on both paths, and the
        returned `Item` is the read-back rather than the claiming process's
        own stdout: bd must show THIS actor holding the item afterward, or
        this raises. A conflict-family failure is decided the same way --
        the item id is known here (unlike `claim_next`), so the proof is a
        plain keyed read, with no set-difference fallback needed. A DOMAIN
        refusal (bd says someone else holds it, or it does not exist) is
        NOT verified away: it raises with bd's own wording, unchanged.
        """
        try:
            self.get(item_id)  # existence check only -- raises if missing
        except BeadsUnavailableError:
            # The existence check could not be PERFORMED -- the database was
            # unreachable, so nothing was learned about whether this item
            # exists. Re-raised untouched: relabelling it "item not found"
            # is the fourth outcome this docstring promises never to
            # conflate with the first, and it lied in 9 of 12 measured
            # attempts against an item that existed. See
            # `BeadsUnavailableError`.
            raise
        except BeadsError as e:
            raise BeadsError(f"cannot claim {item_id}: item not found ({e})") from e

        blockers = _forward_active_blockers_via_sql(self.project_name, item_id)
        if blockers:
            names = ", ".join(f"{b['id']} ({b.get('status', 'unknown')})" for b in blockers)
            raise BeadsError(
                f"refusing to claim {item_id}: blocked by open dependency/dependencies "
                f"{names}. Resolve the blocker(s), or remove the dependency link, then "
                f"claim again -- directed claims never bypass blockers."
            )

        def _do_claim() -> subprocess.CompletedProcess:
            p = self._run(["update", item_id, "--claim", "--json"], actor=actor)
            if p.returncode != 0:
                blob = (p.stdout or "") + (p.stderr or "")
                if _retryable(blob) or _connection_retryable(blob):
                    return p  # let `_verified_write` decide it by read-back
                # A DOMAIN refusal (already held by someone else, not found)
                # -- surfaced with bd's own wording, unverified and
                # unchanged, exactly as before.
                msg = (p.stderr or p.stdout or "").strip()
                raise BeadsError(f"claim {item_id} as {actor!r} failed: {msg[:300]}")
            return p

        def _verify() -> bool:
            back = _get_item_via_sql(self.project_name, item_id)
            return back is not None and back.status == "held" and back.holder == actor

        self._verified_write(_do_claim, _verify, what=f"claim {item_id} as {actor!r}")
        return self.get(item_id)

    def get(self, item_id: str, *, with_links: bool = False) -> Item:
        """Read one item, with its FORWARD dependency graph always attached
        as `Item.links` (`direction: "from"` entries -- what THIS item
        depends on / is blocked by / supersedes / etc), plus its REVERSE
        graph (`direction: "to"`, what depends on THIS item) when
        `with_links=True`.

        The base item -- every field `with_links=False` (the overwhelming
        majority of callers: every fencing check in `claim_item`/`resolve`,
        every readback in `update`/`resolve`, `get_custody`, the CLI's
        `show`, `get_readonly`) ever sees -- is read via `_get_item_via_sql`,
        a READ-ONLY SQL SELECT, NOT `bd show`. `bd show`, like `bd list`,
        does a read+WRITE transaction (an interaction-log row per
        invocation), so it CAN lose a dolt serialization conflict against
        the shared server's concurrent write traffic; a pure SELECT has no
        write set and cannot conflict, at any contention level -- see
        `_get_item_via_sql`'s and `_list_rows_via_sql`'s docstrings for the
        full mechanism this shares with the `list()`/`project_summary`
        fixes. Raises `BeadsError` if no such row exists -- the same "not
        found" shape `bd show` produced before, so `get_readonly`'s
        wrong-project-prefix-vs-genuinely-missing disambiguation (which
        only inspects `item_id`/`project_name`, never this message's text)
        is unaffected.

        Forward (`"from"`) links are populated via
        `_forward_dependency_links_via_sql` regardless of `with_links` --
        another pure SELECT, so this never reintroduces the serialization-
        conflict exposure the base-item read was just fixed to avoid. This
        restores an invariant that predates the SQL-based base-item read:
        bd's own `dependencies` field needs no `--include-dependents` flag,
        so a plain `bd show` always populated forward edges too -- see
        `tests/integration/test_dependency.py`'s
        `test_get_readonly_with_links_displays_the_same_edge`, which pins
        this explicitly, and `_forward_dependency_links_via_sql`'s own
        docstring for the full reasoning.

        `with_links=True` ADDITIONALLY asks bd for the REVERSE
        (`dependents`) side of the graph -- that enrichment is DELIBERATELY
        left on `bd show --include-dependents`, not reproduced over SQL
        here: it is a smaller, one-item read (not the 465-row case that
        motivated the `list()`/`project_summary` fixes), and reproducing
        bd's own dependents cross-reference (title/status only, holder/
        created_by always `None`, its own lean-by-design asymmetry
        documented below) over SQL would mean re-deriving bd's exact
        `--include-dependents` semantics a second time for comparatively
        little contention-safety benefit. See work_tracker item
        pipeline-bug for the full contention hardening this method's
        base-item change is part of.

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
        if not with_links:
            it = _get_item_via_sql(self.project_name, item_id)
            if it is None:
                raise BeadsError(f"show {item_id}: no issues found matching the provided IDs")
            it.links = _forward_dependency_links_via_sql(self.project_name, item_id)
            return it

        d = self._json(["show", item_id, "--include-dependents"])
        d = d[0] if isinstance(d, list) else d
        if not isinstance(d, dict):
            raise BeadsError(f"show {item_id} returned no object")
        it = Item.from_beads(d)
        # `bd show`'s own JSON carries no errata field at all -- read them
        # the same read-only SQL way `_get_item_via_sql` does for its own
        # branch, so a `with_links=True` read (this branch) never disagrees
        # with a `with_links=False` one about whether an item is corrected.
        it.errata = _errata_via_sql(self.project_name, item_id)
        it.corrected = bool(it.errata)

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

    def get_readonly(self, item_id: str, *, with_links: bool = False) -> Item:
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

        `with_links=True` additionally populates `Item.links` (see `get`'s
        own docstring for the shape) -- the dependency-graph DISPLAY this
        read pairs with `add_dependency`'s WRITE side. Default `False`
        matches every existing caller's behavior unchanged.

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
            return self.get(item_id, with_links=with_links)
        except BeadsUnavailableError:
            # WORST of the three flattening sites, and the reason this one
            # is fenced first. Both branches below assert ABSENCE, and the
            # second discarded the cause outright -- a bare "item 'X' not
            # found in project 'Y'" with no parenthetical, nothing an agent
            # or a human could tell apart from real absence. Measured
            # against an item the calling session HELD: 2 of 8 attempts
            # denied its existence. This is also the exact path
            # `context/awareness.md` hazard #6 tells agents to TRUST as the
            # safe recovery after an ambiguous write ("re-read the item
            # first ... a read-only path that cannot itself conflict"), so
            # a lie here is a lie told to a caller who was following our
            # own instructions. Re-raised untouched, cause intact.
            raise
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

        `status`, when given, takes priority over `include_resolved`: an
        explicit status shows closed items without needing "all resolved"
        at all (ASSUMPTION list.status_filter_includes_closed, verified
        empirically against bd 1.1.2 -- `bd list --status closed --json`
        returns closed items with no `--all` present, and the SQL path
        below reproduces that: an explicit `status` filters on it alone,
        `include_resolved` never additionally applies). This means a
        caller asking for `status="resolved"` sees resolved items
        regardless of `include_resolved`.

        `limit`, when given, behaves like bd's own `--limit`/`-n` (0 means
        unlimited). `None` leaves the same default (50) bd itself defaults
        to in place -- unchanged behavior for every existing caller that
        never specified `limit`. Callers that need the TRUE total count
        (not just a default-capped view) should pass `limit=0` explicitly
        -- see `list_bounded`, which does exactly that.

        Reads via a read-only SQL SELECT (`_list_rows_via_sql`), not `bd
        list [--all]`, for the same reason `project_summary` does (see
        `_summary_items_via_sql`'s docstring for the full mechanism): `bd
        list` does a read+WRITE transaction (it appends an interaction-log
        row per invocation), and on a large project (cortex: 465 items)
        materialising that many rows keeps the transaction open long
        enough to reliably lose a dolt serialization conflict against the
        shared single-writer server's concurrent write traffic -- `_run`
        retries up to `_MAX_RETRIES` (8) with exponential backoff and, for
        cortex, exhausts the whole ~23s budget before giving up. A pure
        SELECT over the direct `_dolt_sql*` path has no write set, so it
        cannot serialization-conflict at any project size. Every caller of
        `list()` -- the web project-page list pane, the reap sweep, the
        gateway, and the CLI's own `list` subcommand -- gets this fix at
        once, since they all go through this one method. See work_tracker
        items pipeline-exz / pipeline-knu.

        WHERE-clause construction replicates bd's own filter semantics
        exactly (verified empirically against bd 1.1.2, and pinned by an
        equivalence test comparing this path's output to bd's for every
        working project on the shared server): with neither `status` nor
        `include_resolved` given, bd's plain `bd list` excludes only
        `status='closed'` (measured: attractor's default list returns
        exactly its non-closed rows -- `open` + `in_progress`/held --
        never `blocked`/`deferred` excluded) -- reproduced here as
        ``status <> 'closed'``. `lane` filters via a `labels` subquery
        (bd's own `--label` does the equivalent join). Ordering
        (``created_at DESC, id ASC``) is `_list_rows_via_sql`'s own
        concern -- see that function's docstring for why the `id ASC`
        tie-break reproduces bd's tied-timestamp order exactly.
        """
        where_parts: list[str] = []
        if status is not None:
            raw = _STATUS_MAP_REVERSE.get(status)
            if raw is None:
                raise BeadsError(
                    f"unknown status {status!r}: must be one of {sorted(_STATUS_MAP_REVERSE)}"
                )
            where_parts.append(f"`issues`.`status` = '{_sql_literal(raw)}'")
        elif not include_resolved:
            # ASSUMPTION list.includes_closed -- mirrored: an omitted status
            # AND include_resolved=False excludes only closed items, never
            # blocked/deferred/held, matching bd's own plain `bd list`.
            where_parts.append("`issues`.`status` <> 'closed'")
        if lane:
            where_parts.append(
                f"`issues`.`id` IN (SELECT `issue_id` FROM `{self.project_name}`.`labels` "
                f"WHERE `label` = '{_sql_literal(lane)}')"
            )
        where_sql = " AND ".join(where_parts)
        effective_limit = LIST_DEFAULT_LIMIT if limit is None else limit
        return _list_rows_via_sql(self.project_name, where_sql=where_sql, limit=effective_limit)

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
        """Close an item and VERIFY the write landed -- the `Item`-returning
        projection of `resolve_outcome`, which every existing caller already
        uses and which is unchanged for them.

        A pure one-line projection ON PURPOSE: two entry points to one
        operation can only stay honest if one of them cannot hold logic of
        its own to drift with. Callers that need to distinguish "I wrote
        this resolution just now" from "this identical resolution was
        already stored" (the CLI, `work_resolve`) call `resolve_outcome`
        directly for its `idempotent` flag.
        """
        return self.resolve_outcome(item_id, reason, actor=actor).item

    def resolve_outcome(
        self, item_id: str, reason: str, *, actor: str | None = None
    ) -> ResolveOutcome:
        """Close an item and VERIFY the write landed. Exit code is not proof.

        WHAT "LANDED" MEANS: the item stores the TEXT THIS CALL SENT --
        not merely that the item is closed. Comparing status alone was the
        measured defect (work_tracker item model_performance-uma): a
        resolve against an already-closed item exited 0 and echoed the OLD
        text back as if it were the new one, silently discarding a
        correction. `resolve` is checked against `_resolution_landed` at
        BOTH places it decides that question -- the normal post-write
        readback AND the contended path below -- because a caller on the
        contended path is precisely the one least able to reason about
        what actually happened.

        THE RULE, on a target that is ALREADY resolved (checked BEFORE any
        write, so "NOTHING WAS WRITTEN" is literally true):

          - text IDENTICAL (after `_norm_resolution`) -> success,
            `idempotent=True`, no write attempted. This carve-out is
            required, not a softening: the shipped contention contract
            sells resolve's no-op as RETRY SAFETY, and a retry re-sends
            the identical string. A blanket error would fail a legitimate
            retry of a write that did land, and tell its caller their
            resolve failed when it succeeded.
          - text DIFFERS -> `BeadsError` (`_divergent_resolution_error`),
            nothing written, the remedy (`reopen`) named as a runnable
            command. Correcting a published record is a deliberate,
            audited transition -- never an invisible side effect of a call
            the caller believes is idempotent.

        Resolving an OPEN item is unchanged, byte for byte.

        FENCED in every state a caller can no longer legitimately close
        from -- but the fence is keyed on WHO the custody record names,
        never on the item's status alone. Both halves matter, and each one
        was, at some point, a measured bug:

        HALF ONE -- an integrator's plain resolve must stay a single call.
        Resolving an item nobody currently holds (open/blocked/deferred/
        resolved), even one filed or last held by someone else entirely,
        needs no fence and no override. The fence used to fire on custody
        metadata ALONE, so a STALE record from a hold that ended long ago
        kept naming a "current holder" who held nothing, refusing an
        integrator's close of someone else's already-unheld report
        (work_tracker item 79t, PR #51). Anyone who is not the session that
        record names is exactly as unfenced as before.

        HALF TWO -- the stale holder itself is refused in EVERY
        post-reclaim state, including the released-but-not-yet-re-claimed
        one (contract `custody-coordination.v1` Core 7; ledger row
        CCV1-009; work_tracker item pipeline-dn4). 79t's fix reached for
        the item's status as its discriminator (`status == "held"`), which
        reinstated the very bug the fence exists to close: `reap` does not
        leave a reclaimed item `held` -- `supervisor.reap_project` calls
        `release`, which puts it back to `open` and clears bd's assignee --
        so the one state the fence is FOR was the one state it skipped, and
        the stale holder's close landed with exit 0 and no refusal
        anywhere. Status was never the right question; custody identity is.

        Hence the three checks below, in the order they can be answered:

          - held, with a custody record: that record is authoritative over
            bd's own assignee, because a reclaim CLEARS the assignee rather
            than reassigning it -- "no current holder" and "never held at
            all" look identical in bd, and only the custody record can tell
            them apart. Refuse unless BOTH name this caller.
          - held, no custody record: fall back to bd's assignee alone --
            enough to catch a live takeover by another session.
          - NOT held, but the custody record still names this caller: this
            session's hold ended without this session closing the item --
            reclaimed by `reap`, or handed back by `release`, which are
            indistinguishable by construction (see `agent_stats`, which
            documents why). Either way it does not hold the item now, and
            its close is refused.

        A custody record is deliberately left in place across a reclaim, so
        it can still answer "who held this last" -- that is what makes the
        third check possible at all. The `current.holder != who` guard on
        it is what keeps a holder's own already-landed close re-attemptable
        (a resolved item retains its assignee, so a wedged session
        confirming its own close is never mistaken for a reclaimed one --
        see this method's verify-by-read-back branch below).

        Every refusal names the real holder and the recovery: re-claim the
        item, or wait for `reap` to reclaim a stale hold.
        """
        who = actor or self._actor
        # ONE pre-write read serves every precondition below -- the
        # custody fence, THEN the already-resolved rule -- so both are
        # decided before the `bd close` write is even attempted (see the
        # "NOTHING WAS WRITTEN" promise above). Deliberately tolerant of a
        # read failure when no actor is given, so an item that does not
        # exist still surfaces through bd's own `close` error exactly as
        # before -- this method must not newly re-diagnose "not found".
        try:
            current: Item | None = self.get(item_id)
        except BeadsError:
            if who:
                raise
            current = None
        if who and current is not None:
            cust = current.meta.get(C.CUSTODY_KEY) if isinstance(current.meta, dict) else None
            cust_holder = cust.get("holder") if isinstance(cust, dict) else None
            if current.status == "held":
                if cust_holder:
                    if current.holder != who or cust_holder != who:
                        raise FencedError(
                            f"refusing to close {item_id}: current holder is "
                            f"{current.holder!r} (custody holder {cust_holder!r}), "
                            f"not {who!r}. Your claim was reclaimed while you were away."
                        )
                elif current.holder and current.holder != who:
                    raise FencedError(
                        f"refusing to close {item_id}: it is held by {current.holder!r}, "
                        f"not {who!r}. Your claim was reclaimed while you were away."
                    )
            elif cust_holder == who and current.holder != who:
                raise FencedError(
                    f"refusing to close {item_id}: not held by this session -- custody "
                    f"names {who!r} as its last holder, but the item is now "
                    f"{current.status!r} with no current holder. Your claim was "
                    f"reclaimed (or released) while you were away. Re-claim it first, "
                    f"then resolve."
                )
        if current is not None and current.status == "resolved":
            # Decided BEFORE any write -- that ordering is what makes the
            # refusal's own "NOTHING WAS WRITTEN" promise literally true.
            if _resolution_landed(current.resolution, reason):
                return ResolveOutcome(item=current, idempotent=True)
            raise _divergent_resolution_error(
                item_id,
                project=self.project_name,
                stored=current.resolution,
                sent=reason,
            )
        try:
            p = self._run(["close", item_id, "--reason", reason], actor=actor)
        except BeadsError:
            # `_run` raises ONLY when its own serialization-retry budget is
            # exhausted -- i.e. the WRAPPER gave up, not necessarily that
            # the close never landed. Measured incident (work_tracker item
            # pipeline-yym, 2026-09-01, cortex-cro0): the close had landed
            # on an earlier attempt inside that same retry loop, yet the
            # wrapper still raised, and the exception's own "Last:" detail
            # quoted the close's own success confirmation. Verify via a
            # fresh, contention-free read-back (never itself susceptible to
            # this hazard -- see `get`'s docstring) before trusting the
            # wrapper's failure: if the item is genuinely resolved, report
            # success rather than propagate a false failure that would
            # otherwise wedge the caller's custody state forever.
            #
            # "Genuinely resolved" means resolved WITH THIS CALL'S TEXT.
            # Status alone is the wrong proxy here for the same reason it
            # is wrong at the post-write readback below -- and this is the
            # site it is easiest to leave half-fixed. A closed item whose
            # stored resolution is somebody else's text means our write did
            # NOT land, however closed the item looks.
            back = self._read_back_or_none(item_id)
            if back is not None and back.status == "resolved":
                if _resolution_landed(back.resolution, reason):
                    return ResolveOutcome(item=back, idempotent=False)
                raise _divergent_resolution_error(
                    item_id,
                    project=self.project_name,
                    stored=back.resolution,
                    sent=reason,
                    contended=True,
                ) from None
            raise
        if p.returncode != 0:
            raise BeadsError(f"close {item_id}: {_clean_bd_error(p.stderr or p.stdout)}")
        back = self.get(item_id)
        if back.status != "resolved":
            raise BeadsError(
                f"close {item_id} reported success but readback shows status="
                f"{back.status!r} -- refusing to report success"
            )
        if not _resolution_landed(back.resolution, reason):
            raise _divergent_resolution_error(
                item_id,
                project=self.project_name,
                stored=back.resolution,
                sent=reason,
                contended=True,
            )
        return ResolveOutcome(item=back, idempotent=False)

    def reopen(self, item_id: str, reason: str, *, actor: str | None = None) -> ReopenOutcome:
        """Return a RESOLVED item to the queue so its official record can be
        corrected -- the remedy `resolve`'s divergent-text refusal names, and
        the only sanctioned way to change a published resolution.

        Deliberately NOT idempotent: reopening an already-open item RAISES
        rather than no-ops. This program's recurring defect is an operation
        that looks like it worked, and "reopen succeeded" on an item that
        was already open tells the caller something false about what they
        just did -- the mirror image of `resolve`'s own rule above.

        ARCHIVE FIRST, then transition. The comment carrying the verbatim
        previous resolution is written BEFORE `bd reopen` runs, and that
        ordering is load-bearing rather than stylistic: bd 1.1.2's
        treatment of `close_reason` across a reopen is UNDOCUMENTED and
        unverified upstream, so the wrapper's guarantee must not depend on
        it. What this method promises is therefore true whatever bd does:

            after a successful reopen, the previous resolution text is
            durably recorded in the item's attributed comment history.

        (`contract.py`'s `reopen.close_reason_disposition` separately PINS
        the behaviour measured against the live binary, so a future bd
        change breaks `doctor` loudly instead of quietly altering what a
        reopened item carries.)

        THE COST, surfaced rather than hidden: `bd reopen` clears
        `closed_at` (see `_velocity_raw_daily`), so a corrected item stops
        counting toward the day it was genuinely resolved and re-lands on
        the correction date -- every throughput roll-up moves by one item
        per correction. `ReopenOutcome.previous_closed_at` carries what was
        destroyed. That cost is exactly why this stays an explicit verb
        instead of being folded into `resolve` as an invisible side effect.

        Does NOT claim the item, but DOES clear the stale assignee bd leaves
        behind (see below) so the item is genuinely claimable again. A
        reopened item lands back in the ready queue, where parallel agents
        are polling -- so the caller almost always wants to claim it
        immediately (see `work_reopen`'s `claim` parameter, and the CLI's
        opt-in `--claim`). That is the CALLER's decision to make, because a
        claim from an interactive shell strands custody nobody is renewing.

        VERIFIED BY READ-BACK on BOTH paths (`_verified_write`), like every
        other item-level write verb here (ledger row CCV1-015) -- `resolve`
        is the one deliberate exception, pinned by CCV1-009. Two writes,
        two verified calls: the `bd reopen` itself (predicate: the item is
        no longer `resolved`) and, only when needed, the stale-assignee
        clear (predicate: `holder` is empty). Before this, the assignee
        clear was a bare unverified `_run` call with no conflict recovery
        at all -- a `bd update` that raised under contention here would have
        failed the whole call even though the reopen had already landed,
        and a caller could not safely retry (a second `reopen` on an
        already-reopened item raises "nothing to reopen"). The "reported
        success but still resolved" phantom case is detected in the WRITE
        step itself (not the generic verify failure) so it keeps its own
        precise wording; the genuine conflict-family failure -- the
        wrapper's exhausted-retry raise -- is what `_verified_write`'s
        `_landed(verify)` fallback decides by fresh read-back.
        """
        who = actor or self._actor or "unknown"
        if not (reason or "").strip():
            raise BeadsError(
                f"reopen {item_id}: --reason is required and must not be empty -- "
                f"a reopen destroys a record's finality and its closed_at; an "
                f"unexplained one is not auditable"
            )
        cur = self.get(item_id)
        if cur.status != "resolved":
            raise BeadsError(
                f"refusing to reopen {item_id}: status is {cur.status!r}, not 'resolved' "
                f"-- nothing to reopen"
            )
        previous_resolution = cur.resolution
        previous_closed_at = cur.closed_at
        archived_text = (
            previous_resolution if (previous_resolution or "").strip() else "(none -- was blank)"
        )
        self.comment(
            item_id,
            (
                f"{who} reopened this item to correct the record.\n"
                f"REASON: {reason}\n"
                f"PREVIOUS RESOLUTION (superseded, verbatim):\n"
                f"{archived_text}\n"
                f"PREVIOUS closed_at: "
                f"{previous_closed_at.isoformat() if previous_closed_at else '(none)'}"
            ),
            actor=actor,
        )
        seen: list[Item] = []

        def _do_reopen() -> subprocess.CompletedProcess:
            p = self._run(["reopen", item_id, "--reason", reason], actor=actor)
            if p.returncode == 0:
                # Checked here, not left to `_verified_write`'s generic
                # verify failure, so a genuine phantom success keeps this
                # verb's own precise wording ("refusing to report success").
                probe = self.get(item_id)
                if probe.status == "resolved":
                    raise BeadsError(
                        f"reopen {item_id} reported success but readback still shows "
                        f"status='resolved' -- refusing to report success"
                    )
                seen.append(probe)
            return p

        def _verify() -> bool:
            back = self._read_back_or_none(item_id)
            if back is None or back.status == "resolved":
                return False
            seen.append(back)
            return True

        self._verified_write(_do_reopen, _verify, what=f"reopen {item_id}")
        back = seen[-1]
        if back.holder:
            # MEASURED (bd 1.1.2, 2026-09-02): `bd reopen` flips status back
            # to open and clears closed_at, but LEAVES THE OLD ASSIGNEE IN
            # PLACE. The item then looks open while still being "claimed by"
            # whoever closed it -- and a directed claim by anyone else is
            # refused outright ("issue already claimed by <old holder>"), so
            # the correction path this verb exists to open is closed again by
            # a stale name. `release` already clears the assignee for exactly
            # this reason (`update --status open --assignee ""`); a reopen
            # that did not would hand back an item nobody can take.
            cleared: list[Item] = []

            def _verify_cleared() -> bool:
                b = self._read_back_or_none(item_id)
                if b is None or b.holder:
                    return False
                cleared.append(b)
                return True

            try:
                self._verified_write(
                    lambda: self._run(["update", item_id, "--assignee", ""], actor=actor),
                    _verify_cleared,
                    what=f"reopen {item_id}: clear stale assignee",
                )
            except BeadsError as e:
                raise BeadsError(
                    f"{e} -- the reopen itself LANDED (status={back.status!r}), but the "
                    f"stale assignee could not be cleared, so nobody else can claim it to "
                    f"correct it. Clear it with `amplifier-work-tracker unclaim --project "
                    f"{self.project_name} --id {item_id}`, then claim it."
                ) from e
            back = cleared[-1]
        return ReopenOutcome(
            item=back,
            previous_resolution=previous_resolution,
            previous_closed_at=previous_closed_at,
            reopen_reason=reason,
            actor=who,
        )

    def erratum(self, item_id: str, *, actor: str, text: str) -> ErratumOutcome:
        """Append an ERRATUM to a RESOLVED item's own record: the record is
        wrong, but the work itself stands. The opposite case -- the WORK
        must be redone -- is `reopen`, not this. Unlike every other
        lifecycle verb here, `erratum` never touches `status`, `closed_at`,
        `resolution`, or the holder, and requires no claim at all: any
        actor, at any time, may append one. See the module's `Erratum` /
        `_format_erratum_comment` for the storage shape (one append-only
        bd COMMENT), reusing the SAME channel `edit_item`'s audit trail
        already writes through -- no Beads schema change.

        FOUR distinct, loud preconditions, checked in this order -- never
        one generic refusal standing in for all of them:

          1. `actor` must be non-empty (this verb has no `self._actor`
             fallback the way `comment`/`edit_item` do -- an erratum's
             attribution is never left to guesswork).
          2. `item_id` must exist -- surfaced via `self.get`'s own error
             ("no issues found matching the provided IDs").
          3. The item must be RESOLVED. An OPEN item's wrong record is a
             content edit, not a correction to a PUBLISHED fact -- the
             error names `edit`/`work_edit` as the remedy instead.
          4. `text` must be non-empty after stripping.

        Then the idempotency rule: a BYTE-IDENTICAL erratum (same text,
        after the same CRLF/outer-whitespace normalization `resolve`'s own
        same-text rule already uses) already recorded by ANY actor is an
        idempotent no-op SUCCESS (`already_recorded=True`, nothing
        written) -- mirrors `resolve_outcome`'s own same-text rule,
        applied to errata rather than to the resolution field.

        VERIFIED BY READ-BACK (`_verified_write`) on BOTH paths, like every
        other item-level write verb here (ledger row CCV1-015). The
        predicate is COUNT-based -- an ERRATUM comment matching THIS
        actor+text now exists -- the same discipline `comment()`'s own
        verify uses, and for the same reason: two errata with identical
        text from the SAME actor is a real, legitimate case (a second,
        unrelated resolution later turns out wrong the same way), so "a
        matching erratum exists" by itself cannot prove THIS call's write
        landed.
        """
        who = (actor or "").strip()
        if not who:
            raise BeadsError(f"erratum {item_id}: --actor is required and must not be empty")
        cur = self.get(item_id)  # existence check -- raises "not found" if missing
        if cur.status != "resolved":
            raise BeadsError(
                f"refusing to add an erratum to {item_id}: status is {cur.status!r}, not "
                f"'resolved' -- a correction to an OPEN item's record is a content edit, "
                f"not an erratum. Use `edit`/`work_edit` instead."
            )
        if not (text or "").strip():
            raise BeadsError(f"erratum {item_id}: text is required and must not be empty")

        norm_text = _norm_resolution(text)  # same generic CRLF/whitespace rule `resolve` uses
        for existing in cur.errata:
            if _norm_resolution(existing.text) == norm_text:
                return ErratumOutcome(item=cur, already_recorded=True)

        at = _erratum_now_iso()
        formatted = _format_erratum_comment(at, who, text)

        def _matching() -> int:
            return sum(
                1
                for e in _errata_via_sql(self.project_name, item_id)
                if e.by == who and _norm_resolution(e.text) == norm_text
            )

        before = _matching()
        self._verified_write(
            lambda: self._run(["comment", item_id, formatted], actor=who),
            lambda: _matching() > before,
            what=f"erratum {item_id}",
        )
        return ErratumOutcome(item=self.get(item_id), already_recorded=False)

    def _read_back_or_none(self, item_id: str) -> Item | None:
        """Contention-free read-back (see `get`'s docstring -- never `bd
        show`), used ONLY to verify a write that a wrapper transaction
        reported as failed. Never raises: a lookup failure here must not
        mask the ORIGINAL error -- the caller re-raises that when this
        returns `None`.
        """
        try:
            return self.get(item_id)
        except BeadsError:
            return None

    def release(self, item_id: str) -> ReleaseOutcome:
        """Hand a held item back to the queue -- or, if it turns out to
        already be resolved/closed, report that instead of writing
        anything.

        Sanctioned wedge-recovery branch (work_tracker item pipeline-yym):
        checked BEFORE any write, via a contention-free read-back. A caller
        (typically `work_release`) may be asked to release an item that a
        PRIOR resolve/close already landed, despite that resolve reporting
        a spurious wrapper failure (see `resolve`'s own verify-by-read-back
        fix for the identical root cause) -- leaving a session wedged,
        believing it still holds an item bd already considers closed. This
        method must never be the thing that reopens an already-closed item,
        so the status check happens first and, when the item is already
        `resolved`, this returns `already_closed=True` having performed NO
        write to the item at all -- asserting on status before any
        status-mutating write is what makes reopening a closed item
        structurally impossible from this path, not merely unlikely.

        VERIFIED BY READ-BACK on BOTH paths (`_verified_write`). PR #63 gave
        this method a read-back on the CONFLICT path only; the SUCCESS path
        still returned straight off `p.returncode == 0`, which is the one
        thing this module says everywhere else is not proof. It matters
        more here than almost anywhere: `release` is what BOTH `work_release`
        AND every reap reclaim call, so a `bd update` that exited 0 without
        actually clearing the hold left an item still HELD while the sweep
        reported it reclaimed -- a hold nobody is renewing and nobody can
        claim. The read-back now demands the item is genuinely no longer
        `held` before this returns at all (ledger row CCV1-012).
        """
        current = self.get(item_id)
        if current.status == "resolved":
            return ReleaseOutcome(item_id=item_id, already_closed=True)
        seen: list[Item] = []

        def _verify() -> bool:
            back = self._read_back_or_none(item_id)
            if back is None or back.status == "held":
                return False
            seen.append(back)
            return True

        self._verified_write(
            lambda: self._run(["update", item_id, "--status", "open", "--assignee", ""]),
            _verify,
            what=f"release {item_id}",
        )
        return ReleaseOutcome(item_id=item_id, already_closed=(seen[-1].status == "resolved"))

    # -------------------------------------------------------- defer / block
    #
    # Both set the item's own top-level `status` -- `_STATUS_MAP` already
    # knows the raw bd values `deferred`/`blocked` and maps them straight
    # through (see that map's own comment: an unrecognized status passes
    # through rather than being coerced, and these two are recognized).
    # This is a DIFFERENT mechanism from bd's own `update --defer <date>`
    # flag (a scheduling hide-until-date on an otherwise-open item) --
    # these instead move the item's status itself, which is what makes
    # `bd ready`/`claim_next` skip it (bd's status-category system treats
    # `blocked`/`deferred` as non-`active`, so neither appears in `bd
    # ready`) and what makes it render with an honest status in list
    # output, rather than merely hidden with no explanation.
    #
    # The reason is stored in metadata (`metadata.roundtrip` is an already-
    # proven assumption: arbitrary JSON metadata survives a write/read
    # cycle, and `bd update --metadata` merges at the top level rather than
    # replacing wholesale) under a status-specific key, so a defer reason
    # and a block reason never collide, and undefer/unblock only ever
    # clear the key for the status they own.

    _DEFER_REASON_KEY = "defer_reason"
    _BLOCK_REASON_KEY = "block_reason"

    def _set_status_with_reason(
        self, item_id: str, *, status: str, reason: str, reason_key: str, actor: str | None
    ) -> Item:
        if not reason or not reason.strip():
            raise BeadsError(f"{status} {item_id}: a reason is required")
        # ---- model_performance-2nx: refuse BEFORE any write ----
        # REFUSE ON A RESOLVED ITEM -- checked BEFORE any write, which is what
        # makes the refusal's own "NOTHING WAS WRITTEN" promise literally
        # true (the same ordering `resolve` and `release` both rely on).
        #
        # MEASURED (model_performance-2nx): without this, `defer`/`block` on a
        # closed item exited 0, moved it out of resolved, and BLANKED its
        # stored resolution -- an unaudited, destructive reopen of the
        # official record, one verb away from a `release` that refuses the
        # same transition on purpose.
        #
        # Deliberately tolerant of a read failure (mirrors `resolve`'s own
        # pre-write read): an item that does not exist must keep surfacing
        # through bd's own `update` error below exactly as before -- this
        # guard must not newly re-diagnose "not found".
        try:
            current: Item | None = self.get(item_id)
        except BeadsError:
            current = None
        if current is not None and current.status == "resolved":
            raise _status_change_on_resolved_error(
                item_id,
                project=self.project_name,
                verb=_STATUS_CHANGE_VERB.get(status, status),
                stored=current.resolution,
                closed_at=current.closed_at,
            )
        # ---- #68: verified write (read-back confirms status AND reason) ----
        args = [
            "update",
            item_id,
            "--status",
            status,
            "--metadata",
            json.dumps({reason_key: reason}),
        ]
        seen: list[Item] = []

        def _verify() -> bool:
            back = self.get(item_id)
            if back.status != _map_status(status):
                return False
            if back.meta.get(reason_key) != reason:
                return False
            seen.append(back)
            return True

        self._verified_write(
            lambda: self._run(args, actor=actor), _verify, what=f"{status} {item_id}"
        )
        return seen[-1]

    def _clear_status_with_reason(
        self, item_id: str, *, from_status: str, reason_key: str, actor: str | None
    ) -> Item:
        current = self.get(item_id)
        if current.status != _map_status(from_status):
            raise BeadsError(
                f"cannot un-{from_status} {item_id}: it is {current.status!r}, not "
                f"{_map_status(from_status)!r}"
            )
        args = [
            "update",
            item_id,
            "--status",
            "open",
            "--unset-metadata",
            reason_key,
        ]
        seen: list[Item] = []

        def _verify() -> bool:
            back = self.get(item_id)
            if back.status != "open" or reason_key in back.meta:
                return False
            seen.append(back)
            return True

        self._verified_write(
            lambda: self._run(args, actor=actor), _verify, what=f"un-{from_status} {item_id}"
        )
        return seen[-1]

    def defer(self, item_id: str, reason: str, *, actor: str | None = None) -> Item:
        """Defer an open item with a reason -- it leaves `bd ready`/
        `claim_next` (bd's own status-category system excludes non-active
        statuses from `bd ready`), but stays visible in `list()`'s own
        default view (which only ever excludes `closed`, never
        `blocked`/`deferred` -- see that method's docstring) AND via an
        explicit `--status deferred` read, with its reason attached. Move
        it back to the queue with `undefer`.

        REFUSES on an item that is already RESOLVED, writing nothing --
        see `_set_status_with_reason`'s own guard and
        `_status_change_on_resolved_error`. Deferring a closed item used to
        succeed and BLANK its stored resolution; `reopen` is the sanctioned
        (archiving) way to bring a closed item back.
        """
        return self._set_status_with_reason(
            item_id,
            status="deferred",
            reason=reason,
            reason_key=self._DEFER_REASON_KEY,
            actor=actor,
        )

    def undefer(self, item_id: str, *, actor: str | None = None) -> Item:
        """Move a deferred item back to `open` (ready to be claimed again),
        clearing its defer reason. Refuses if the item is not currently
        deferred -- there is nothing to undo.
        """
        return self._clear_status_with_reason(
            item_id, from_status="deferred", reason_key=self._DEFER_REASON_KEY, actor=actor
        )

    def block(self, item_id: str, reason: str, *, actor: str | None = None) -> Item:
        """Block an open item with a reason -- same visibility contract as
        `defer` (leaves `bd ready`/`claim_next`, stays visible in `list()`'s
        default view and on an explicit status read, reason attached).
        Deliberately
        distinct from the DEPENDENCY-based blocker chain (`add_dependency`
        / `claim_item`'s blocker refusal): this is a direct, reasoned
        status change with no other issue involved, for "this can't
        proceed right now" situations that are not really "issue B must
        close first." Move it back to the queue with `unblock`.

        REFUSES on an item that is already RESOLVED, writing nothing -- same
        guard, same reason as `defer` above. `reopen` is the sanctioned
        (archiving) way to bring a closed item back.
        """
        return self._set_status_with_reason(
            item_id,
            status="blocked",
            reason=reason,
            reason_key=self._BLOCK_REASON_KEY,
            actor=actor,
        )

    def unblock(self, item_id: str, *, actor: str | None = None) -> Item:
        """Move a blocked item back to `open`, clearing its block reason.
        Refuses if the item is not currently blocked -- there is nothing
        to undo.
        """
        return self._clear_status_with_reason(
            item_id, from_status="blocked", reason_key=self._BLOCK_REASON_KEY, actor=actor
        )

    def add_dependency(
        self,
        item_id: str,
        depends_on_id: str,
        *,
        dep_type: str = "blocks",
        actor: str | None = None,
    ) -> None:
        """Declare `item_id` depends on (per `dep_type`) `depends_on_id` --
        the CREATE side of the dependency graph `claim_item` already
        ENFORCES (its blocker refusal reads exactly this edge back via
        `_active_blockers`) and `get(with_links=True)` already DISPLAYS
        (as `Item.links`). This method is what WRITES the edge those two
        read -- before it existed, the only way to create one was the
        forbidden raw `bd dep add` shell-out.

        `dep_type` is bd's own vocabulary (`blocks` -- the default, and the
        only type `claim_item` treats as an active blocker --, plus
        `tracks`/`related`/`parent-child`/`discovered-from`/`until`/
        `caused-by`/`validates`/`relates-to`/`supersedes`). Verified by
        readback: `get(item_id, with_links=True)` must show the new edge,
        never merely a non-erroring exit.
        """

        def _verify() -> bool:
            back = self.get(item_id, with_links=True)
            return any(
                link.get("id") == depends_on_id and link.get("direction") == "from"
                for link in back.links
            )

        self._verified_write(
            lambda: self._run(["dep", "add", item_id, depends_on_id, "-t", dep_type], actor=actor),
            _verify,
            what=f"dep add {item_id} -> {depends_on_id} ({dep_type})",
        )

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

        Verified by read-back on BOTH paths (`_verified_write`): the stored
        custody record must equal the one written. A FALSE failure here is
        not cosmetic -- it produces exactly the held-without-custody state
        (an item assigned to a holder that nothing is renewing), which is
        why an exhausted-retry raise is decided by reading the record back
        rather than believed.
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
        self._verified_write(
            lambda: self._run(
                ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: record})],
                actor=holder,
            ),
            lambda: self.get_custody(item_id) == record,
            what=f"take_custody {item_id}",
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

        Verified by read-back on BOTH paths (`_verified_write`). Renewal is
        ONE-STRIKE by design (the caller stops renewing for good on any
        failure), so a false failure here dooms a live, healthy hold -- the
        conflict path must be settled by reading the record back, never by
        the wrapper's verdict. This is also the write behind the tool's
        `declare`: a phantom success would report a `declared_state` no
        reader ever sees.
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
        self._verified_write(
            lambda: self._run(
                ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: updated})],
                actor=holder,
            ),
            lambda: self.get_custody(item_id) == updated,
            what=f"renew_custody {item_id}",
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
                    # `_quote_handled_output`, never a bare slice of `blob`:
                    # this line goes to a plain CLI's stderr, and the retry
                    # below is expected to SUCCEED. Republishing bd's own
                    # `Error:` here is what made a healed run look like a
                    # silent failure (`model_performance-kxk`).
                    logger.warning(
                        "project %r: bd init hit a dirty schema migration -- dropping "
                        "and retrying once: %s",
                        name,
                        _quote_handled_output(blob),
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

    def move_item(self, src: str, dst: str, item_id: str) -> MoveReport:
        """Move one item from project `src` to project `dst` -- the
        single-item counterpart to `rename`/`remove`'s whole-project
        operations, exposed here purely for call-site symmetry
        (`workspace.move_item(...)` reads the same way as
        `workspace.rename(...)`/`workspace.remove(...)`).

        Delegates entirely to the free `move_item` function; adds no
        validation or behavior of its own. Unlike `rename`/`remove`, this
        needs no awareness of either project's local `.beads` directory --
        `move_item` operates purely on the shared dolt server's databases,
        which is the only place an item's rows actually live -- so a plain
        delegation is the whole implementation. See `move_item`'s own
        docstring for the full contract (refusals, HELD-item safety,
        cross-project dependency handling, atomicity).
        """
        return move_item(src, dst, item_id)


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

#: Prefix for the FOURTH state, added because `instances` had no vocabulary
#: between `ok` and `ERROR`: the database is fine, WE could not reach it.
#: `"ERROR: ..."` asserts the project's data is unreadable; measured (lane
#: `model_performance-rpz`), a healthy project printed exactly that in 5 of
#: 10 attempts, interleaved with correct `ok` rows for the same project
#: seconds either side. That is a claim about the project; this is a claim
#: about the connection, and they must not share a word.
#:
#: A PREFIX rather than a bare token, matching the existing `"ERROR: "`
#: convention, because the diagnostic text after it is the actionable part.
#: `is_unavailable_status` is the one place that recognises it -- callers
#: must not re-derive the test with their own `startswith`.
STATUS_UNAVAILABLE_PREFIX = "UNAVAILABLE: "


def is_unavailable_status(status: str | None) -> bool:
    """True if `status` is a `ProjectSummary.status` reporting that the
    database could not be REACHED (as opposed to read and found broken).

    One home for the test so the CLI table, the JSON rows, and the web
    dashboard cannot drift into three different opinions about which
    strings mean "unknown" -- the same reason `truncate_status` is shared.
    """
    return bool(status) and str(status).startswith(STATUS_UNAVAILABLE_PREFIX)


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
    database exists but could not be read at all; or a truncated
    `"UNAVAILABLE: ..."` string (`STATUS_UNAVAILABLE_PREFIX`,
    `is_unavailable_status`) when the database could not be REACHED, which
    is a claim about the connection and not about the project. In EVERY
    non-`ok` case
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
      2. A database that could not be REACHED reports
         `status="UNAVAILABLE: ..."` (truncated) -- distinct from both `ok`
         and `ERROR`, because it is a claim about the connection, not about
         the project. Measured (lane `model_performance-rpz`): under a
         transient dolt read failure a healthy project printed as `ERROR`
         with null counts in 5 of 10 attempts, interleaved with correct
         `ok` rows for that same project. `_dolt_sql*` now retries a
         transport blip first (`_run_dolt_sql_bounded`), so this state is
         reached only PAST that bounded budget.
      3. A database that IS reachable but cannot be read reports
         `status="ERROR: ..."` (truncated), again with every field
         `None`/empty.
      4. Otherwise `STATUS_OK`, with real counts.

    On the healthy path, fetches items exactly ONCE
    (`ws.project(name).list(include_resolved=True)`) and derives every field
    -- counts, `project_activity`'s aging/throughput figures, and the
    ready-age histogram -- from that single in-memory list. No field here
    costs a second `bd` call.

    Exception: `held_stale`/`held_stale_oldest_age_seconds`. Real custody
    freshness lives in each item's `metadata` column, which
    `_summary_items_via_sql`'s narrow scalar projection deliberately never
    selects (see that function's own docstring on why -- free-text
    `longtext` columns would need CSV-escaping and cost more than a summary
    should). Before this fix, that meant every item from THIS path carried
    an empty `meta`, so `_held_stale_count`/`_held_stale_oldest_age_seconds`
    silently derived their answer from an absent custody record for EVERY
    held item regardless of its real state -- a `project_summary` "silently
    always-wrong" ledger row (work_tracker item pipeline-jbf). The fix:
    these two fields alone are derived from a SECOND, targeted read scoped
    to held items only (typically far fewer than the project's full item
    count) -- `_held_items_via_sql`, the exact same custody source
    `project_agents` already reads correctly -- rather than adding the
    free-text `metadata` column to this function's own CSV-parsed read
    (which would reintroduce the CSV-escaping hazard `_summary_items_via_sql`
    exists to avoid). Skipped entirely when nothing is held (no extra round
    trip for the common case); degrades to `None` (unknown -- never a
    fabricated number) if that second read itself fails, the same "honest
    unknown" discipline `reminder_snapshot`'s `custody_stale` already
    applies.
    """
    state = ws.creation_state(name)
    if state == "creating":
        return ProjectSummary(name=name, status=STATUS_CREATING)
    if state == "abandoned":
        return ProjectSummary(name=name, status=STATUS_BROKEN)
    try:
        items = _summary_items_via_sql(name)
    except BeadsUnavailableError as e:
        # The database was UNREACHABLE -- we learned nothing about this
        # project. Reporting `ERROR:` here asserts its data is unreadable,
        # which was false in 5 of 10 measured attempts against a healthy
        # project. See `STATUS_UNAVAILABLE_PREFIX`. Ordered before the
        # `BeadsError` arm because it is a subclass.
        return ProjectSummary(name=name, status=truncate_status(f"{STATUS_UNAVAILABLE_PREFIX}{e}"))
    except BeadsError as e:
        return ProjectSummary(name=name, status=truncate_status(f"ERROR: {e}"))
    held_items = [i for i in items if i.status == "held"]
    blocked_items = [i for i in items if i.status == "blocked"]
    activity = project_activity(items)
    held_stale: int | None
    held_stale_oldest_age_seconds: float | None
    if held_items:
        try:
            full_held_items = _held_items_via_sql(name)
        except BeadsError:
            held_stale = None
            held_stale_oldest_age_seconds = None
        else:
            held_stale = _held_stale_count(full_held_items)
            held_stale_oldest_age_seconds = _held_stale_oldest_age_seconds(full_held_items)
    else:
        held_stale = 0
        held_stale_oldest_age_seconds = None
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
        held_stale_oldest_age_seconds=held_stale_oldest_age_seconds,
    )


# ==========================================================================
# --- wt-v4 observability aggregates (lane obs-data) ---
#
# Data layer for the "Observatory" re-design (see
# `.amplifier/design-gauntlet/wt-v4-observatory/BRIEF.md` in the workspace
# root, and `GAUNTLET-SYNTHESIS.md` alongside it): velocity/burn charts,
# a "reopened after resolve" quality signal, a fleet-wide "agents now"
# roster, a minimal per-agent stats panel, and the ranked cross-project
# attention queue. Every read here goes over the same contention-free
# `_dolt_sql`/`_dolt_sql_json` path the rest of this module already
# established (see `_summary_items_via_sql`'s docstring for the full
# serialization-conflict mechanism this sidesteps) -- nothing here shells
# out to `bd list`/`bd show`, so the dashboard can poll this as
# aggressively as it wants without ever contending with a concurrent
# agent's write.
#
# TIMEZONE GOTCHA (read this before touching any query below): `issues`'s
# `created_at`/`updated_at`/`closed_at` are written by bd's own application
# code as UTC wall-clock (`_parse_dolt_timestamp`'s docstring already
# documents this) -- but `events.created_at` is populated by dolt's own
# `DEFAULT CURRENT_TIMESTAMP`, which is evaluated in the *server process's
# system timezone*, not UTC (verified empirically against the isolated
# test server: `@@system_time_zone` reported `PDT`, and a freshly-inserted
# event's `created_at` matched the server's own `NOW()`, NOT its
# `UTC_TIMESTAMP()`, by exactly the local UTC offset). So every query below
# that filters `issues` timestamps compares against `UTC_TIMESTAMP()`, and
# every query that filters `events.created_at` compares against `NOW()` --
# using the wrong function for a given table would silently skew every
# window by the host's UTC offset. This is self-consistent (both sides of
# each comparison share one clock) and correct regardless of what
# timezone the real production dolt server happens to run in.
# ==========================================================================

#: How many trailing days a ready item must sit before it enters the
#: attention queue's "aging" tier. A module constant, not a buried literal,
#: per the gauntlet's explicit requirement that ranking thresholds be
#: server-adjustable (see `GAUNTLET-SYNTHESIS.md`'s "Attention-queue ranking
#: weights" note: the ranking is a stated hypothesis, not a fixed law).
ATTENTION_AGING_DAYS = 7

#: Fallback per-project cap on how many attention-queue rows are collected
#: from any ONE tier before the caller's own overall `limit` is applied --
#: keeps one noisy project from starving every other project's rows out of
#: a bounded fleet-wide query. Generous enough to never matter in practice.
_ATTENTION_PER_PROJECT_CAP = 200


def _velocity_raw_daily(db: str, days: int) -> dict[str, dict[str, int]]:
    """Per-calendar-day `{"created": n, "resolved": n}` counts for `db`,
    covering the trailing `days` UTC calendar days (today back through
    `days - 1` days ago) -- the shared fetch behind both `velocity_series`
    (asked for `days`) and `velocity_windows` (asked for `days * 2`, so one
    fetch covers both the current and previous window).

    Exactly 2 SQL round trips regardless of `days` or project size: one
    `GROUP BY DATE(created_at)` over `issues` for creations, one `GROUP BY
    DATE(closed_at)` for resolutions. No per-day query -- see this
    function's own callers for why that matters at cortex scale (465
    items): trivial either way, but the pattern is what stays cheap as
    projects grow.

    "Resolved" mirrors `_daily_resolved_counts`'s own definition exactly
    (`status = 'closed' AND closed_at IS NOT NULL`) for the same honest
    reason: `bd reopen` CLEARS `closed_at` back to NULL (verified
    empirically), so an item resolved and later reopened stops counting
    toward any day's resolved bucket at all, including the day it was
    genuinely resolved on. This is a pre-existing, documented convention
    inherited from `_daily_resolved_counts`, not a new gap introduced here.

    Unlike `_daily_resolved_counts` (which buckets by rolling 24h periods
    counted backward from `now`), this buckets by true UTC CALENDAR date
    via SQL `DATE(...)` -- what a "resolved/day" chart with actual date
    labels on its axis needs, not a rolling window. The two functions
    answer different questions and are not expected to agree bucket-for-
    bucket.

    Returns a dict keyed by `YYYY-MM-DD` (only for dates with at least one
    real creation or resolution -- callers zero-fill the rest, see
    `velocity_series`), never a fabricated entry for a quiet day.
    """
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_sql = _sql_literal(f"{start.isoformat()} 00:00:00")

    out: dict[str, dict[str, int]] = {}

    created_p = _dolt_sql_json(
        f"SELECT DATE(`created_at`) AS d, COUNT(*) AS n FROM `{db}`.`issues` "
        f"WHERE `created_at` >= '{start_sql}' GROUP BY DATE(`created_at`)"
    )
    if created_p.returncode != 0:
        raise BeadsError(
            f"could not compute created-per-day counts for database {db!r}: "
            f"{_clean_bd_error(created_p.stderr or created_p.stdout)}"
        )
    for row in json.loads(created_p.stdout or "{}").get("rows", []):
        d = str(row.get("d") or "")
        if d:
            out.setdefault(d, {"created": 0, "resolved": 0})["created"] = int(row.get("n") or 0)

    resolved_p = _dolt_sql_json(
        f"SELECT DATE(`closed_at`) AS d, COUNT(*) AS n FROM `{db}`.`issues` "
        f"WHERE `status` = 'closed' AND `closed_at` >= '{start_sql}' "
        f"GROUP BY DATE(`closed_at`)"
    )
    if resolved_p.returncode != 0:
        raise BeadsError(
            f"could not compute resolved-per-day counts for database {db!r}: "
            f"{_clean_bd_error(resolved_p.stderr or resolved_p.stdout)}"
        )
    for row in json.loads(resolved_p.stdout or "{}").get("rows", []):
        d = str(row.get("d") or "")
        if d:
            out.setdefault(d, {"created": 0, "resolved": 0})["resolved"] = int(row.get("n") or 0)

    return out


def velocity_series(db: str, days: int = 7) -> list[dict]:
    """Per-day `{"date", "created", "resolved"}` for `db`'s trailing `days`
    UTC calendar days, oldest first -- the real data source for a velocity/
    burn chart's day-by-day bars (created-vs-resolved overlay), NOT an
    aggregate window total (see `velocity_windows` for that).

    Every day in the window is present -- a day with no real activity is a
    genuine `{"created": 0, "resolved": 0}`, never a missing entry (the
    same "zero-fill, never drop" discipline `_ready_age_buckets` already
    applies to its own histogram). Cheap at any project size: exactly 2 SQL
    round trips via `_velocity_raw_daily`, no per-day query.

    Raises `BeadsError` if `db` cannot be read at all (surfaced, never
    silently swallowed into an all-zero series that would misrepresent an
    unreadable project as a genuinely quiet one).
    """
    raw = _velocity_raw_daily(db, days)
    today = datetime.now(UTC).date()
    out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        counts = raw.get(ds, {"created": 0, "resolved": 0})
        out.append({"date": ds, "created": counts["created"], "resolved": counts["resolved"]})
    return out


def _pct_delta(curr: int, prev: int) -> float | None:
    """Percentage change from `prev` to `curr`, rounded to one decimal --
    `None` (never a fabricated +inf%% or an arbitrary 100%%) when `prev` is
    zero, since no meaningful percentage change is computable off a zero
    baseline. Matches this module's standing "never fabricate a reading"
    convention (see `_held_stale_oldest_age_seconds`'s docstring for the
    same discipline applied to a different field).
    """
    if prev == 0:
        return None
    return round((curr - prev) / prev * 100.0, 1)


def velocity_windows(db: str, days: int = 7) -> dict:
    """Window totals for `db`'s trailing `days`-day period AND the
    immediately-previous period of equal length -- what powers a "WoW:
    ↑12%% vs previous 7d" delta line, which a per-day series alone cannot
    answer (that needs two SUMS, not a list of daily bars).

    Returns:
        ``{"current": {"created": int, "resolved": int},
           "previous": {"created": int, "resolved": int},
           "delta_pct": {"created": float | None, "resolved": float | None}}``

    `delta_pct` is `current` measured against `previous` via `_pct_delta`
    (`None` when the previous window was genuinely zero -- see that
    function's docstring).

    Cheap regardless of `days`: ONE call to `_velocity_raw_daily` covering
    `days * 2` calendar days (2 SQL round trips total, the same fetch
    `velocity_series` would make for a window twice as wide), split in
    half in Python -- never a third/fourth query just to get the previous
    window's totals.
    """
    raw = _velocity_raw_daily(db, days * 2)
    today = datetime.now(UTC).date()
    current = {"created": 0, "resolved": 0}
    previous = {"created": 0, "resolved": 0}
    for i in range(days * 2 - 1, -1, -1):
        d = today - timedelta(days=i)
        counts = raw.get(d.isoformat(), {"created": 0, "resolved": 0})
        bucket = current if i < days else previous
        bucket["created"] += counts["created"]
        bucket["resolved"] += counts["resolved"]
    return {
        "current": current,
        "previous": previous,
        "delta_pct": {
            "created": _pct_delta(current["created"], previous["created"]),
            "resolved": _pct_delta(current["resolved"], previous["resolved"]),
        },
    }


def velocity_series_and_windows(db: str, days: int = 7) -> tuple[list[dict], dict]:
    """`velocity_series(db, days)` and `velocity_windows(db, days)`,
    together, sharing ONE `_velocity_raw_daily` fetch instead of two
    independent ones.

    `velocity_windows` already fetches `days * 2` calendar days of raw
    daily counts (current window + previous window); that range is a
    strict superset of the `days`-day range `velocity_series` alone would
    fetch, and both derive from the exact same `{date: {created,
    resolved}}` dict. Calling them separately (as L0's per-project fan-out
    used to) does the identical `_velocity_raw_daily(db, days)` +
    `_velocity_raw_daily(db, days * 2)` work TWICE over an overlapping
    date range -- 4 SQL round trips per project for data 2 round trips
    already fully cover. This function fetches once, at the `days * 2`
    width, and derives both outputs from it -- HALF the round trips, byte-
    for-byte the same two return values `velocity_series`/`velocity_windows`
    would have produced from their own independent fetches (same zero-fill
    discipline, same bucket boundaries, same `_pct_delta` math -- this is a
    fetch-sharing optimization, not a behavior change).

    Returns ``(series, windows)`` -- see `velocity_series`/`velocity_windows`
    for each element's own shape. Raises `BeadsError` if `db` cannot be
    read at all, same as both functions this replaces for a caller that
    needs both.
    """
    raw = _velocity_raw_daily(db, days * 2)
    today = datetime.now(UTC).date()

    series: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        counts = raw.get(ds, {"created": 0, "resolved": 0})
        series.append({"date": ds, "created": counts["created"], "resolved": counts["resolved"]})

    current = {"created": 0, "resolved": 0}
    previous = {"created": 0, "resolved": 0}
    for i in range(days * 2 - 1, -1, -1):
        d = today - timedelta(days=i)
        counts = raw.get(d.isoformat(), {"created": 0, "resolved": 0})
        bucket = current if i < days else previous
        bucket["created"] += counts["created"]
        bucket["resolved"] += counts["resolved"]
    windows = {
        "current": current,
        "previous": previous,
        "delta_pct": {
            "created": _pct_delta(current["created"], previous["created"]),
            "resolved": _pct_delta(current["resolved"], previous["resolved"]),
        },
    }
    return series, windows


def reopened_count(db: str, days: int = 7) -> int:
    """How many `events` rows in `db` record an item being reopened after
    a prior close, within the trailing `days` days -- the real, exact
    "reopened after resolve" quality signal the gauntlet's punchlist asked
    for (see `GAUNTLET-SYNTHESIS.md` item 11), not an approximated proxy.

    WHAT THIS ACTUALLY MEASURES (the honest answer from empirical
    investigation against a real bd binary + isolated dolt server): bd
    itself writes a row with `event_type = 'reopened'` to the project's
    `events` table every time a previously-closed issue transitions back
    to open -- verified for BOTH the dedicated `bd reopen <id>` command AND
    the less-explicit `bd update <id> --status open` path bd's own
    `reopen --help` text warns is "less explicit" (its warning is about
    audit-trail clarity, not about which events get recorded -- both paths
    were verified, empirically, to emit the identical `event_type =
    'reopened'` row). This is a first-class recorded fact, not a derived
    proxy: no fallback to a `closed_at IS NOT NULL` heuristic was needed
    (and would not have worked anyway -- `bd reopen`/`--status open` both
    CLEAR `closed_at` back to NULL on reopen, verified empirically, so a
    reopened item retains no trace of its prior close on the `issues` row
    itself; the `events` table is the only place this fact survives).

    Window filtering compares `events.created_at` against `NOW()`, not
    `UTC_TIMESTAMP()` -- see this block's own module-level TIMEZONE GOTCHA
    comment for why: `events.created_at` is populated by dolt's own local-
    system-timezone `CURRENT_TIMESTAMP`, so `NOW()` (the same clock) is the
    only comparison that stays correct regardless of what timezone the
    real dolt server process happens to run in.

    A single SQL round trip, `_dolt_sql` (CSV, not JSON) -- the query
    projects one scalar count, no free-text column involved.
    """
    p = _dolt_sql(
        f"SELECT COUNT(*) FROM `{db}`.`events` WHERE `event_type` = 'reopened' "
        f"AND `created_at` >= NOW() - INTERVAL {int(days)} DAY"
    )
    if p.returncode != 0:
        raise BeadsError(
            f"could not count reopened events for database {db!r}: "
            f"{_clean_bd_error(p.stderr or p.stdout)}"
        )
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][1:]  # drop CSV header
    return int(lines[0].strip()) if lines else 0


def _agent_row(project: str, item: Item) -> dict:
    """One `project_agents`/`agents_snapshot` roster row for a single held
    `item` -- custody freshness reused VERBATIM from `custody.reclaim_eligible`
    (never re-derived, so this can never disagree with what `reap_project`
    would actually reclaim), same discipline `_held_stale_count`/
    `_held_stale_oldest_age_seconds` already apply for the aggregate counts
    this is the per-item counterpart of.
    """
    meta = item.meta.get(C.CUSTODY_KEY) if isinstance(item.meta, dict) else None
    stale, _reason = C.reclaim_eligible(meta)
    age: float | None = None
    if isinstance(meta, dict) and meta.get("last_seen"):
        age = C.age_seconds(meta["last_seen"])
    # A stale hold with NO custody record at all (dict-less -- "claimed but
    # never renewed") is eligible per `reclaim_eligible` but un-ageable: no
    # `last_seen` exists to measure an overage from. `None`, never a
    # fabricated 0-second (or infinite) overage -- same discipline
    # `_held_stale_oldest_age_seconds` already applies.
    overage = (age - C.CUSTODY_TTL_SECONDS) if (stale and age is not None) else None
    return {
        "agent": item.holder,
        "project": project,
        "item_id": item.id,
        "item_title": item.title,
        "priority": item.priority,
        "held_seconds_or_last_renewal_age": age,
        "stale": stale,
        "seconds_over_ttl_if_stale": overage,
    }


def _agent_row_sort_key(row: dict) -> tuple[int, float]:
    """Stale rows first (worst overage first -- an un-measurable "no
    custody record" overage sorts as worst-case, never merely "unknown,
    sort last": a completely untracked hold is at least as concerning as a
    long-measured one). Fresh rows follow, freshest (smallest renewal age)
    first.
    """
    if row["stale"]:
        overage = row["seconds_over_ttl_if_stale"]
        return (0, -(overage if overage is not None else float("inf")))
    age = row["held_seconds_or_last_renewal_age"]
    return (1, age if age is not None else float("inf"))


def _held_items_via_sql(db: str) -> list[Item]:
    """Currently-held items, WITH real custody metadata -- unlike
    `_summary_items_via_sql`'s narrow scalar projection (which deliberately
    excludes `metadata`, see that function's own docstring), this reads
    every field `Item.from_beads` maps, including `metadata`, but scoped to
    held items ONLY (`_list_rows_via_sql`'s own `where_sql`) so the cost
    stays bounded to however many items are actually held, not the whole
    project. The shared custody-correct source `project_agents` and
    `project_summary`'s `held_stale`/`held_stale_oldest_age_seconds` fields
    both need (work_tracker item pipeline-jbf) -- one definition, so the
    two can never independently drift on what "held, with real custody"
    means.
    """
    return _list_rows_via_sql(
        db, where_sql=f"`issues`.`status` = '{_STATUS_MAP_REVERSE['held']}'", limit=0
    )


def project_agents(db: str) -> list[dict]:
    """The "who holds what" roster for ONE project -- every currently-held
    item's holder, with custody freshness -- the data behind L1's per-
    project Agents panel (see `BRIEF.md`'s L1 section) and the per-project
    building block `agents_snapshot` composes fleet-wide for L0's "Agents
    now" roster.

    Reuses `Beads.list()`'s own read-only SQL path (`_list_rows_via_sql`,
    filtered to bd's raw `in_progress` status -- our domain `\"held\"`) so
    this costs exactly one contention-free SQL round trip per project;
    items with no holder (should not occur for `in_progress`, but guarded
    rather than assumed) are skipped rather than emitted with a `None`
    agent.

    Sorted stale-first, then by freshness -- see `_agent_row_sort_key`.

    Raises `BeadsError` if `db` cannot be read at all -- a single project's
    read failure is this function's caller's concern (see
    `agents_snapshot`, which tolerates exactly this for a FLEET-wide
    roster); this function itself never silently substitutes an empty list
    for a real read failure.
    """
    items = _held_items_via_sql(db)
    rows = [_agent_row(db, item) for item in items if item.holder]
    rows.sort(key=_agent_row_sort_key)
    return rows


def agents_snapshot(ws: Workspace) -> list[dict]:
    """The fleet-wide "Agents now" roster (see `BRIEF.md`'s L0 section) --
    every project's `project_agents` rows, merged and re-sorted stale-first-
    then-by-freshness across the WHOLE fleet, not just within one project.

    A project mid-creation or left broken by an unfinished `new` (see
    `Workspace.creation_state`, the same check `project_summary` runs
    first) contributes nothing -- skipped, same as it has no items to
    report. A project that fails to read for any OTHER reason (a genuine
    `BeadsError`) is likewise skipped rather than aborting the whole
    fleet's roster: one broken project must never hide every other
    project's agents. This is the one place in this block that swallows a
    read failure -- see `project_agents`'s own docstring for why it, taken
    alone, does not.

    The actual fetch-and-merge is split into this sequential per-project
    loop plus `agents_snapshot_from_rows` (the pure merge/sort, no I/O) so
    a caller that gathers each project's `project_agents` rows itself --
    e.g. in parallel, or reusing rows already fetched for another purpose
    such as the attention queue's stale-custody tier, see
    `stale_attention_rows` -- can skip this function's sequential fetch
    entirely and call `agents_snapshot_from_rows` directly.
    """
    by_project: dict[str, list[dict]] = {}
    for project in ws.names():
        if ws.creation_state(project) in ("creating", "abandoned"):
            continue
        try:
            by_project[project] = project_agents(project)
        except BeadsError:
            continue
    return agents_snapshot_from_rows(by_project)


def agents_snapshot_from_rows(agent_rows_by_project: dict[str, list[dict]]) -> list[dict]:
    """The merge/sort half of `agents_snapshot`, factored out so a caller
    that gathers each project's `project_agents` rows itself (e.g. in
    parallel, or reusing rows already fetched for another purpose) can
    reuse the exact same fleet-wide stale-first-then-by-freshness ordering
    without re-fetching anything. Pure -- no I/O, never raises.

    `agent_rows_by_project` need only contain entries for projects that
    contributed rows (or were successfully read) -- a project omitted
    entirely is equivalent to one `agents_snapshot` itself would have
    skipped.
    """
    rows: list[dict] = []
    for project_rows in agent_rows_by_project.values():
        rows.extend(project_rows)
    rows.sort(key=_agent_row_sort_key)
    return rows


def agent_stats(db_or_ws: str | Workspace, agent: str, days: int = 7) -> dict:
    """Minimal per-agent history -- the data behind a small "agent as door"
    panel (see `GAUNTLET-SYNTHESIS.md`'s explicit-defer note: a full agent-
    detail IA page is future work, this is deliberately not that).

    `db_or_ws` is EITHER a single project's database name (scope to that
    one project -- the L1 agents-panel use case) OR a `Workspace` (scope to
    every project it knows about -- the L0 fleet-wide "Agents now" roster's
    use case, since one agent can hold work in more than one project).
    Aggregated identically either way: sum across whichever project set
    applies. A project that fails to read (or one mid-creation/broken, when
    given a `Workspace`) contributes nothing, same tolerance
    `agents_snapshot` already applies -- one broken project must not blank
    out an agent's stats from every OTHER project they work in.

    Returns:
        ``{"agent": str, "days": int, "resolved": int, "held": int,
           "stale_incidents": int}``

      - `resolved`: items whose raw `assignee` is `agent` and whose current
        `status` is `closed` (bd retains `assignee` through a close --
        verified empirically), with `closed_at` inside the trailing `days`
        days (`UTC_TIMESTAMP()`-relative, per this block's TIMEZONE GOTCHA
        -- `issues.closed_at` is UTC, unlike `events.created_at`).
      - `held`: items whose raw `assignee` is `agent` and current `status`
        is `in_progress`, right now (not window-scoped -- "currently held"
        is a snapshot, not a per-day count).
      - `stale_incidents`: a CHEAP, HONEST PROXY, not an exact "reclaimed
        for staleness" count -- see below.

    `stale_incidents`, honestly: bd's `events` table records a generic
    `event_type = 'status_changed'` row for BOTH a stale-custody reclaim
    (`reap_project`'s `bd.release`) and a voluntary hand-back (the
    `work_release` tool's own use of the same `release` method) -- the two
    are NOT distinguishable from `events` alone (both are written by
    whatever actor's `Beads` handle happened to call `release`, which is
    not reliably a fixed, filterable "reaper identity" -- verified
    empirically that `release`'s own event carries no field naming WHY the
    release happened). So this counts every `status_changed` event in the
    window whose `old_value` shows `agent` as the assignee transitioning to
    an unassigned, reopened-to-`open` state -- i.e. every "item was handed
    back while `agent` held it" event, a strict SUPERSET of true stale-
    reclaims that also includes voluntary releases. Named `stale_incidents`
    per this function's requested contract, but a caller surfacing this
    number should read it as "times work was taken back from this agent",
    not a guaranteed staleness-only count. Cheap: one `JSON_EXTRACT`-based
    SQL round trip per project (verified working against dolt), no
    per-event fetch.
    """
    if isinstance(db_or_ws, Workspace):
        ws = db_or_ws
        dbs = [
            name for name in ws.names() if ws.creation_state(name) not in ("creating", "abandoned")
        ]
    else:
        dbs = [db_or_ws]

    resolved = 0
    held = 0
    stale_incidents = 0
    agent_lit = _sql_literal(agent)
    for db in dbs:
        try:
            rp = _dolt_sql(
                f"SELECT COUNT(*) FROM `{db}`.`issues` WHERE `status` = 'closed' "
                f"AND `assignee` = '{agent_lit}' "
                f"AND `closed_at` >= UTC_TIMESTAMP() - INTERVAL {int(days)} DAY"
            )
            if rp.returncode != 0:
                continue
            lines = [ln for ln in (rp.stdout or "").splitlines() if ln.strip()][1:]
            resolved += int(lines[0].strip()) if lines else 0

            hp = _dolt_sql(
                f"SELECT COUNT(*) FROM `{db}`.`issues` WHERE `status` = 'in_progress' "
                f"AND `assignee` = '{agent_lit}'"
            )
            if hp.returncode == 0:
                lines = [ln for ln in (hp.stdout or "").splitlines() if ln.strip()][1:]
                held += int(lines[0].strip()) if lines else 0

            sp = _dolt_sql(
                f"SELECT COUNT(*) FROM `{db}`.`events` WHERE `event_type` = 'status_changed' "
                f"AND `created_at` >= NOW() - INTERVAL {int(days)} DAY "
                f"AND JSON_EXTRACT(`old_value`, '$.assignee') = '{agent_lit}' "
                f"AND JSON_EXTRACT(`new_value`, '$.status') = 'open'"
            )
            if sp.returncode == 0:
                lines = [ln for ln in (sp.stdout or "").splitlines() if ln.strip()][1:]
                stale_incidents += int(lines[0].strip()) if lines else 0
        except BeadsError:
            continue

    return {
        "agent": agent,
        "days": days,
        "resolved": resolved,
        "held": held,
        "stale_incidents": stale_incidents,
    }


def stale_attention_rows(project: str, agent_rows: list[dict]) -> list[dict]:
    """The pure transform half of the stale-custody attention tier: turns
    an already-fetched `project_agents(project)` result into this
    project's stale-custody attention rows. No I/O, never raises -- a
    caller that has (or gathers, e.g. in parallel) `agent_rows` itself,
    such as L0's own fan-out which reuses these exact rows for the
    fleet-wide "Agents now" roster too (see `agents_snapshot_from_rows`),
    can call this directly instead of going through `_attention_stale_rows`
    and paying for a second `project_agents` fetch of the same project.

    Reuses `project_agents`'s own `stale`/`priority` fields (already the
    exact `reclaim_eligible`-backed freshness computation) so "stale" --
    and priority -- can never disagree between the Agents panel and the
    attention queue.
    """
    out = []
    for row in agent_rows[:_ATTENTION_PER_PROJECT_CAP]:
        if not row["stale"]:
            continue
        age = row["held_seconds_or_last_renewal_age"]
        age_detail = f"{age:.0f}s past TTL" if age is not None else "no custody record at all"
        out.append(
            {
                "rank_reason": "stale-custody",
                "project": project,
                "item_id": row["item_id"],
                "title": row["item_title"],
                "priority": row["priority"],
                "detail": f"held by {row['agent']}, {age_detail}",
                "_sort": -(row["seconds_over_ttl_if_stale"] or float("inf")),
            }
        )
    return out


def _attention_stale_rows(ws: Workspace, project: str) -> list[dict]:
    """This project's stale-custody attention rows -- fetches
    `project_agents(project)` itself, then delegates the transform to
    `stale_attention_rows` (see that function's docstring for why the
    fetch and the transform are split).
    """
    try:
        agent_rows = project_agents(project)
    except BeadsError:
        return []
    return stale_attention_rows(project, agent_rows)


def attention_blocked_rows(project: str) -> list[dict]:
    """This project's blocked-with-a-still-active-blocker attention rows.
    Deliberately the OPPOSITE selection from `_blocked_stale_count`: that
    field counts blocked items with NO active blocker left (needs only an
    unblock); the attention queue's "blocked" tier is for items genuinely
    still waiting on something, which is what a person can actually act on
    by chasing the blocker named in `detail`.

    Reads full item bodies via `Beads.list`'s own SQL path
    (`_list_rows_via_sql`), scoped to `status = 'blocked'` only -- cheap
    even at cortex scale, since blocked items are a small minority. Which
    blockers are still active is then read PER blocked item via
    `_forward_active_blockers_via_sql` -- NOT `_active_blockers(item)`,
    which reads `item.raw["dependencies"]`, a field only `bd show`
    populates (see that function's own docstring): an item sourced from
    `_list_rows_via_sql` carries no such key at all, so `_active_blockers`
    would silently see every blocked item as blocker-free. One extra query
    per blocked item is the honest cost of a correct answer here -- still
    cheap, since blocked items are a small minority of any real project.
    """
    try:
        items = _list_rows_via_sql(
            project, where_sql=f"`issues`.`status` = '{_STATUS_MAP_REVERSE['blocked']}'", limit=0
        )
    except BeadsError:
        return []
    out = []
    for item in items[:_ATTENTION_PER_PROJECT_CAP]:
        try:
            blockers = _forward_active_blockers_via_sql(project, item.id)
        except BeadsError:
            continue
        if not blockers:
            continue  # stale blocker chain -- needs only an unblock, not chasing; see docstring
        names = ", ".join(b.get("id", "?") for b in blockers)
        out.append(
            {
                "rank_reason": "blocked",
                "project": project,
                "item_id": item.id,
                "title": item.title,
                "priority": item.priority,
                "detail": f"blocked by {names}",
                "_sort": 0.0,
            }
        )
    return out


def attention_aging_rows(project: str) -> list[dict]:
    """This project's ready items aged past `ATTENTION_AGING_DAYS`, oldest
    first -- the third and lowest-urgency attention tier (see `BRIEF.md`'s
    "ranked attention: stale custody > blocked > oldest ready").
    """
    try:
        items = _list_rows_via_sql(
            project,
            where_sql=(
                f"`issues`.`status` = 'open' AND `issues`.`id` IN "
                f"(SELECT `issue_id` FROM `{project}`.`labels` WHERE `label` = "
                f"'{_sql_literal(LANE_WORK)}')"
            ),
            limit=0,
        )
    except BeadsError:
        return []
    now = datetime.now(UTC)
    out = []
    for item in items:
        if item.created_at is None:
            continue
        age_days = (now - item.created_at).total_seconds() / 86400.0
        if age_days < ATTENTION_AGING_DAYS:
            continue
        out.append(
            {
                "rank_reason": "aging",
                "project": project,
                "item_id": item.id,
                "title": item.title,
                "priority": item.priority,
                "detail": f"ready {age_days:.1f}d",
                "_sort": -age_days,  # oldest (largest age_days) first
            }
        )
    out.sort(key=lambda r: r["_sort"])
    return out[:_ATTENTION_PER_PROJECT_CAP]


def attention_items(ws: Workspace, limit: int = 50) -> list[dict]:
    """The ranked, cross-project "what needs me?" queue (see `BRIEF.md`'s
    four-questions framing and `GAUNTLET-SYNTHESIS.md`'s explicit-defer
    note: the ranking below is a stated HYPOTHESIS, adjustable server-side,
    not a fixed law).

    Three tiers, in order, each internally sorted worst/oldest first:
      1. ``"stale-custody"`` -- held items whose custody has lapsed (or
         never existed), from `_attention_stale_rows`.
      2. ``"blocked"`` -- items genuinely still waiting on an active
         blocker, from `attention_blocked_rows`.
      3. ``"aging"`` -- ready items older than `ATTENTION_AGING_DAYS`, from
         `attention_aging_rows`.

    Each entry: ``{"rank_reason", "project", "item_id", "title",
    "priority", "detail"}``. `priority` is `None` for a stale-custody row
    (that tier is sourced from `project_agents`, which does not carry
    priority -- adding it would mean a second, heavier item fetch per
    project purely for a field this tier's own urgency does not depend on;
    the other two tiers, already reading full items, carry it for free).

    A project mid-creation/broken or unreadable for any other reason
    contributes nothing to any tier (each per-tier helper degrades
    independently) -- one broken project never blanks out the whole
    queue's visibility into every other project, same tolerance
    `agents_snapshot` already applies.

    `limit` caps the FINAL merged, tier-ordered list -- never applied
    per-project or per-tier first (which could starve a tier's later
    entries in favor of an unrelated project's).

    The actual fetch-and-merge is split into this sequential per-project
    loop plus `attention_items_from_rows` (the pure merge/sort/cap, no
    I/O) so a caller that gathers each project's per-tier rows itself
    (e.g. in parallel, or reusing rows already fetched for another
    purpose -- see `stale_attention_rows`) can skip this function's
    sequential fetch entirely.
    """
    projects = [
        name for name in ws.names() if ws.creation_state(name) not in ("creating", "abandoned")
    ]

    stale_by_project: dict[str, list[dict]] = {}
    blocked_by_project: dict[str, list[dict]] = {}
    aging_by_project: dict[str, list[dict]] = {}
    for project in projects:
        stale_by_project[project] = _attention_stale_rows(ws, project)
        blocked_by_project[project] = attention_blocked_rows(project)
        aging_by_project[project] = attention_aging_rows(project)

    return attention_items_from_rows(
        stale_by_project, blocked_by_project, aging_by_project, limit=limit
    )


def attention_items_from_rows(
    stale_by_project: dict[str, list[dict]],
    blocked_by_project: dict[str, list[dict]],
    aging_by_project: dict[str, list[dict]],
    limit: int = 50,
) -> list[dict]:
    """The merge/sort/cap half of `attention_items`, factored out so a
    caller that gathers each project's per-tier rows itself (e.g. in
    parallel) can reuse the exact same tier-ordering and limit logic
    without re-fetching anything. Pure -- no I/O, never raises.

    Each `*_by_project` dict need only contain entries for projects that
    were successfully read -- a project omitted entirely from one (or
    all) of them is equivalent to one `attention_items` itself would have
    contributed nothing from for that tier.
    """
    stale = [r for rows in stale_by_project.values() for r in rows]
    blocked = [r for rows in blocked_by_project.values() for r in rows]
    aging = [r for rows in aging_by_project.values() for r in rows]

    stale.sort(key=lambda r: r["_sort"])
    blocked.sort(key=lambda r: r["_sort"])
    aging.sort(key=lambda r: r["_sort"])

    merged = stale + blocked + aging
    for row in merged:
        del row["_sort"]
    return merged[: int(limit)] if limit else merged


# ---------------------------------------------------------------------------
# lane:obs-pages -- the ONE new adapter function Lane C (obs-pages) is
# permitted to add per its build spec, for L0 Mission Control's cross-project
# "Activity feed" section (BRIEF.md / GAUNTLET-SYNTHESIS.md item 14).
# ---------------------------------------------------------------------------

# Real, EMPIRICALLY VERIFIED `events.event_type` values (probed live against
# bd 1.1.2 + an isolated dolt server -- create/claim/resolve/block/defer/
# release, then `SELECT * FROM events`): 'created', 'claimed', 'closed',
# 'reopened' (documented by `reopened_count`), and a catch-all
# 'status_changed' for every OTHER transition (block, defer, release/
# reclaim, a plain `--status` edit) -- there is no dedicated 'blocked'
# event_type. Only these four are fetched; a 'status_changed' row is kept
# for the feed ONLY when its own `new_value` JSON shows the transition
# landed on `blocked` (see `_feed_kind` below) -- defer/release/reclaim
# transitions are real events but do not map onto this feed's fixed
# claim/resolve/block/file vocabulary (`widgets.ActivityFeedItem.kind`), so
# they are excluded rather than mis-labeled.
_FEED_EVENT_TYPES = ("created", "claimed", "closed", "status_changed")


def _feed_kind(event_type: str | None, new_value: str | None) -> str | None:
    """Map one raw `events` row onto the feed's fixed `claim`/`resolve`/
    `block`/`file` vocabulary, or `None` if this row doesn't correspond to
    one of those four (see `_FEED_EVENT_TYPES`'s docstring)."""
    if event_type == "created":
        return "file"
    if event_type == "claimed":
        return "claim"
    if event_type == "closed":
        return "resolve"
    if event_type == "status_changed":
        try:
            parsed = json.loads(new_value) if new_value else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict) and parsed.get("status") == "blocked":
            return "block"
    return None


def recent_activity_feed(ws: Workspace, *, hours: int = 12, limit: int = 50) -> list[dict]:
    """Cross-project, reverse-chronological activity feed for L0 Mission
    Control's "Activity feed" section -- every readable project's `events`
    rows (claim/resolve/block/file only, see `_feed_kind`) within the
    trailing `hours` hours, merged and capped to `limit`.

    ONE SQL round trip regardless of project count: every readable
    project's `events`-joined-`issues` query is combined into a single
    `UNION ALL` (verified working against a real isolated dolt server --
    dolt/MySQL execute a cross-database `UNION ALL` over fully-qualified
    `` `db`.`table` `` references in one query, same as every other
    fully-qualified reference already used throughout this module), with
    the final `ORDER BY ... LIMIT` applied to the WHOLE union -- never
    per-project, which could let one noisy project crowd out every other
    project's rows before the merge even happened.

    TIMEZONE GOTCHA (see this block's own module-level comment): compares
    `events.created_at` against `NOW()`, not `UTC_TIMESTAMP()` -- that
    column is written in the server's own local system timezone, not UTC.

    A project mid-creation/broken contributes nothing (skipped up front,
    same as every other aggregate in this block); an empty workspace
    (`ws.names()` -> `[]`, or every project excluded) returns `[]` rather
    than sending a syntactically invalid zero-armed `UNION ALL`.

    Returns dicts shaped for `widgets.ActivityFeedItem` construction by the
    caller: ``{"kind", "actor", "project", "item_id", "title",
    "created_at"}`` -- `created_at` as the raw dolt string (local-tz, per
    the gotcha above); the caller (webapp.py) is responsible for turning it
    into a "Nm ago"-style label and for escaping/composing the final
    `ActivityFeedItem`.
    """
    projects = [
        name for name in ws.names() if ws.creation_state(name) not in ("creating", "abandoned")
    ]
    if not projects:
        return []

    types_sql = ", ".join(f"'{t}'" for t in _FEED_EVENT_TYPES)
    selects = []
    for db in projects:
        db_lit = _sql_literal(db)
        selects.append(
            f"SELECT '{db_lit}' AS project, `e`.`event_type` AS event_type, "
            "`e`.`actor` AS actor, `e`.`issue_id` AS issue_id, `i`.`title` AS title, "
            "`e`.`new_value` AS new_value, `e`.`created_at` AS created_at "
            f"FROM `{db}`.`events` `e` JOIN `{db}`.`issues` `i` ON `i`.`id` = `e`.`issue_id` "
            f"WHERE `e`.`created_at` >= NOW() - INTERVAL {int(hours)} HOUR "
            f"AND `e`.`event_type` IN ({types_sql})"
        )
    query = " UNION ALL ".join(selects) + f" ORDER BY `created_at` DESC LIMIT {int(limit) * 4}"
    # `limit * 4` over-fetches past the caller's own cap because up to 3 of
    # every 4 `status_changed` rows get filtered out by `_feed_kind` AFTER
    # the SQL runs (defer/release/reclaim are real rows this query cannot
    # exclude at the SQL layer without duplicating `_feed_kind`'s own JSON
    # parse in SQL) -- a generous, cheap margin so a busy window doesn't
    # under-fill the final, honestly-capped list.
    p = _dolt_sql_json(query)
    if p.returncode != 0:
        detail = _clean_bd_error(p.stderr or p.stdout)
        raise BeadsError(f"could not read the cross-project activity feed: {detail}")
    rows = json.loads(p.stdout or "{}").get("rows", [])
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        kind = _feed_kind(r.get("event_type"), r.get("new_value"))
        if kind is None:
            continue
        out.append(
            {
                "kind": kind,
                "actor": r.get("actor") or "unknown",
                "project": r.get("project") or "",
                "item_id": r.get("issue_id") or "",
                "title": r.get("title") or "",
                "created_at": r.get("created_at"),
            }
        )
        if len(out) >= limit:
            break
    return out


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
