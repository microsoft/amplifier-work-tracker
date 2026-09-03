"""Sweep heartbeats -- proof the supervisor's reap/notify loops are actually
COMPLETING sweeps, not merely that the systemd/launchd unit is alive.

Why this exists: `reap_loop`/`notify_loop` (see supervisor.py) log ONLY on
crash (`logger.exception(...)`). Silence in the journal is therefore
ambiguous between "healthy, nothing to report" and "the loop task died
without anyone noticing" -- and `systemctl is-active` cannot tell them apart
either, because it reports the unit, not the asyncio task running inside it.
That ambiguity is exactly the silent-failure class this whole project exists
to eliminate -- discovered sitting in our own supervisor after a server
reboot, where nothing proved the sweeps had resumed.

Deliberately NOT a bd concern: this state lives on disk under the workspace
root, never in a bd item's metadata. Heartbeat freshness is supervisor/service
plumbing, not domain data any agent or reporter should see -- see AGENTS.md's
"adapter seam" and the constraint this module was built under.

Two write calls, one per loop, called from supervisor.py:

  - `record_loop_started`  -- once, when the loop task begins (before its
    first sweep). Unconditionally OVERWRITES any prior record for that loop,
    which is what keeps a heartbeat left behind by a previous, now-dead
    process from masquerading as evidence the CURRENT process is healthy:
    the instant a new loop starts, `last_completed` resets to None and
    `pid`/`loop_started_at` point at THIS run.
  - `record_sweep_completed` -- after a sweep finishes without raising.
    Proves the sweep actually ran, not just that the task was created.

One read entry point, consumed by `cli._check_sweeps_alive`:

  - `evaluate_freshness` -- pure decision function (given a record, a clock,
    and an injectable pid-liveness probe) with no I/O of its own, so it is
    exhaustively unit-testable without real processes or real sleeps.
"""

from __future__ import annotations

import calendar
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REAP = "reap"
NOTIFY = "notify"
LOOPS = (REAP, NOTIFY)

HEARTBEAT_FILENAME = ".sweeps-heartbeat.json"

# How many missed intervals before a heartbeat is judged stale. >1 so a
# single slow sweep or a scheduling hiccup never false-positives; not so
# large that a genuinely dead loop goes unnoticed for hours.
DEFAULT_STALE_MULTIPLE = 3.0

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_iso() -> str:
    """UTC timestamp in the one format every field in this module uses."""
    return time.strftime(_ISO_FMT, time.gmtime())


def _parse_iso(ts: str) -> float:
    """Epoch seconds for a now_iso()-shaped string. calendar.timegm, not
    time.mktime -- the latter assumes local time and would silently skew
    every freshness check by the host's UTC offset. Same convention as
    amplifier_work_tracker.custody._parse_iso -- kept independent rather than
    imported, since this module must stay bd-agnostic and importable with no
    dependency on the custody/adapter stack at all.
    """
    return float(calendar.timegm(time.strptime(ts, _ISO_FMT)))


def _age_seconds(ts: str | None, *, now: float) -> float:
    """Seconds elapsed since an ISO-8601 UTC timestamp, or +inf if *ts* is
    missing/unparseable. Never negative -- clock skew should not manufacture
    a negative age that would make a barely-written record look ancient.
    """
    if not ts:
        return float("inf")
    try:
        return max(0.0, now - _parse_iso(ts))
    except ValueError:
        return float("inf")


def heartbeat_path(root: Path | str) -> Path:
    """Where the heartbeat file lives for a given workspace root. One file,
    both loops -- small enough that a shared file is simpler than one per
    loop, and both are written from the same process.
    """
    return Path(root) / HEARTBEAT_FILENAME


@dataclass
class LoopHeartbeat:
    """One loop's persisted state. `last_completed=None` means this run's
    loop has started but has not yet finished a sweep -- distinct from "no
    record at all" (never started), and distinct from "completed, but long
    ago" (stale). See `evaluate_freshness` for how the three are told apart.

    The last three fields carry the OUTCOME of the most recent sweep, not
    merely the fact that one finished (`model_performance-oy4`). Without
    them, `reap_loop` recorded a completed sweep whether the sweep reclaimed
    everything it should have or errored out on every single project --
    `reap_sweep` catches per-project exceptions into its return value and
    that return value was discarded. So `doctor` could report the sweeps
    healthy while nothing was being reclaimed at all, which is precisely the
    "installed" vs "actually working" gap this whole module exists to close,
    reappearing one level up. `evaluate_reclaiming` reads them.

    `failed_projects` absent (rather than empty) distinguishes "a supervisor
    older than this change wrote this record" from "a sweep ran and nothing
    failed" -- see `evaluate_reclaiming`, which must never report the first
    as if it were the second.
    """

    pid: int
    loop_started_at: str
    last_completed: str | None = None
    projects: int | None = None
    reclaimed: int | None = None
    failed_projects: list[str] = field(default_factory=list)


def _read_all(path: Path) -> dict:
    """Never raises -- a missing or corrupt heartbeat file reads as empty,
    the same as "no loop has ever started," which is the correct fallback:
    the file is diagnostic-only and must never be able to crash the
    supervisor that writes it or the doctor check that reads it.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(path: Path, data: dict) -> None:
    """Write-to-temp-then-rename so a crash mid-write can never leave a
    truncated/corrupt heartbeat file behind for the next read (or the next
    process's own record_loop_started) to trip over.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".sweeps-heartbeat-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def record_loop_started(path: Path, loop: str, *, pid: int) -> None:
    """Stamp *loop* as started by *pid*, right now -- called once, before
    the loop's first sleep/sweep. See module docstring for why this
    unconditional overwrite is what neutralizes a previous run's heartbeat.
    """
    data = _read_all(path)
    data[loop] = asdict(LoopHeartbeat(pid=pid, loop_started_at=now_iso(), last_completed=None))
    _atomic_write(path, data)


def record_sweep_completed(
    path: Path,
    loop: str,
    *,
    pid: int,
    projects: int | None = None,
    reclaimed: int | None = None,
    failed_projects: list[str] | None = None,
) -> None:
    """Stamp *loop* as having just completed a sweep. Called AFTER the sweep
    returns without raising -- this is what proves the sweep actually ran,
    not merely that the task exists and is sleeping. Preserves
    `loop_started_at` from `record_loop_started` if present; `pid` is
    refreshed defensively (should already match).

    `projects` / `reclaimed` / `failed_projects` carry the sweep's OUTCOME
    (`model_performance-oy4`). A sweep in which every project raised still
    "completes" -- `reap_sweep` catches per-project exceptions -- so without
    these, a completed-sweep stamp proves only that the loop is turning, not
    that it is doing anything. `failed_projects` is written as `[]` (empty,
    present) by any caller that passes it, which is what lets
    `evaluate_reclaiming` tell "nothing failed" from "an older supervisor
    wrote this record and cannot tell you".
    """
    data = _read_all(path)
    existing = data.get(loop)
    loop_started_at = now_iso()
    if isinstance(existing, dict):
        prior_started = existing.get("loop_started_at")
        if isinstance(prior_started, str) and prior_started:
            loop_started_at = prior_started
    record = asdict(
        LoopHeartbeat(
            pid=pid,
            loop_started_at=loop_started_at,
            last_completed=now_iso(),
            projects=projects,
            reclaimed=reclaimed,
            failed_projects=list(failed_projects) if failed_projects is not None else [],
        )
    )
    if failed_projects is None and projects is None and reclaimed is None:
        # Caller reported no outcome at all (e.g. the notify loop, which has
        # no reclaim semantics). Do not write an EMPTY `failed_projects`,
        # which `evaluate_reclaiming` would read as a positive "nothing
        # failed" claim this caller never made.
        record.pop("failed_projects", None)
    data[loop] = record
    _atomic_write(path, data)


def read_loop_heartbeat(path: Path, loop: str) -> dict | None:
    """The raw persisted record for *loop*, or None if it has never started."""
    rec = _read_all(path).get(loop)
    return rec if isinstance(rec, dict) else None


def pid_alive(pid: int) -> bool:
    """Best-effort: is *pid* a live process on this host? Never raises.

    This is what stops a heartbeat left behind by a crashed process from
    reading as fresh purely on timestamp math: a `last_completed` from 30
    seconds ago LOOKS fresh by any reasonable threshold, but if the pid that
    wrote it is gone, that "freshness" belongs to a process that no longer
    exists (e.g. it crashed moments after its own most recent successful
    sweep, or systemd is mid-RestartSec-backoff). `os.kill(pid, 0)` sends no
    signal -- it only asks the kernel whether the pid is addressable.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    except OSError:
        return False
    return True


def evaluate_freshness(
    record: dict | None,
    *,
    loop: str,
    interval: float,
    now: float | None = None,
    stale_multiple: float = DEFAULT_STALE_MULTIPLE,
    is_pid_alive=pid_alive,
) -> tuple[bool, str]:
    """Decide whether *loop*'s heartbeat proves it is alive. Pure: every
    input is a plain value or an injectable function -- no file I/O, no real
    clock, no real process probing unless the defaults are used. This is
    what makes every scenario in the acceptance criteria (fresh, stale,
    startup window, dead-pid-left-behind) exhaustively testable without a
    real service.

    Returns (ok, detail) -- detail always names the loop, and a failure
    always carries the fix (see IMPLEMENTATION_PHILOSOPHY's "error
    visibility" principle and this repo's existing convention of a failure
    message that carries its own remedy).
    """
    threshold = interval * stale_multiple
    n = now if now is not None else time.time()
    restart_hint = "restart the service (`amplifier-work-tracker service restart`)"

    if record is None:
        return False, (
            f"no heartbeat ever recorded for the {loop} sweep loop -- it may never have "
            f"started, or the heartbeat file was removed; {restart_hint}"
        )

    pid = record.get("pid")
    if isinstance(pid, int) and not is_pid_alive(pid):
        last = record.get("last_completed") or record.get("loop_started_at")
        age = _age_seconds(last, now=n)
        age_desc = "unknown" if age == float("inf") else f"{age:.0f}s ago"
        return False, (
            f"{loop} sweep heartbeat belongs to pid {pid}, which is no longer running "
            f"(last activity {age_desc}) -- a stale heartbeat from a dead process is not "
            f"proof the current one is healthy; {restart_hint}"
        )

    last_completed = record.get("last_completed")
    if last_completed:
        age = _age_seconds(last_completed, now=n)
        if age <= threshold:
            return True, f"{loop} sweep completed {age:.0f}s ago (threshold {threshold:.0f}s)"
        return False, (
            f"{loop} sweep has not completed in {age:.0f}s (threshold {threshold:.0f}s) -- "
            f"the loop appears to have died silently without crashing loudly; {restart_hint}"
        )

    # No sweep has completed yet under this pid -- only acceptable while
    # still inside the startup window (loop just started, first interval
    # hasn't elapsed yet).
    started_at = record.get("loop_started_at")
    age = _age_seconds(started_at, now=n)
    if age <= threshold:
        return True, (
            f"{loop} sweep loop started {age:.0f}s ago, first sweep still pending "
            f"(within startup window {threshold:.0f}s)"
        )
    return False, (
        f"{loop} sweep loop started {age:.0f}s ago and has never completed a sweep "
        f"(startup window {threshold:.0f}s exceeded) -- {restart_hint}"
    )


def evaluate_reclaiming(record: dict | None, *, loop: str = REAP) -> tuple[bool, str]:
    """Is *loop* actually DOING its work, not merely turning?

    `evaluate_freshness` answers "is the loop alive". This answers the
    strictly stronger question `model_performance-oy4` was filed against:
    `work_tracker_status` reported `running_healthy` while (it appeared)
    nothing was being reclaimed, and nothing anywhere could tell those two
    states apart. `reap_sweep` catches every per-project exception into its
    return value, so a sweep that failed on EVERY project still returns
    normally and still stamps a completed heartbeat.

    Returns (ok, detail). Pure -- a dict in, a verdict out.

    Three cases, and the third is the one that must not be fudged:
      - failures recorded -> NOT ok, naming every failed project.
      - `failed_projects` present and empty -> ok, with the counts.
      - `failed_projects` ABSENT -> ok, but the detail says plainly that the
        running supervisor predates outcome reporting and cannot answer.
        Reported rather than assumed: claiming "0 failed" from a record that
        never carried the field would be inventing the very reassurance this
        function exists to stop being invented.
    """
    if record is None:
        return True, (
            f"skipped -- no {loop} heartbeat recorded yet (see the {loop} sweep "
            f"liveness check, which reports that directly)"
        )
    if "failed_projects" not in record:
        return True, (
            f"unknown -- the running supervisor predates per-sweep outcome reporting, "
            f"so its {loop} heartbeat cannot say whether any project failed; restart the "
            f"service (`amplifier-work-tracker service restart`) to start recording it"
        )
    failed = record.get("failed_projects") or []
    projects = record.get("projects")
    reclaimed = record.get("reclaimed")
    scope = f"{projects} project(s)" if isinstance(projects, int) else "an unknown project count"
    got = f"{reclaimed} reclaimed" if isinstance(reclaimed, int) else "reclaim count unknown"
    if failed:
        names = ", ".join(str(f) for f in failed[:10])
        more = f" (+{len(failed) - 10} more)" if len(failed) > 10 else ""
        return False, (
            f"the last {loop} sweep swept {scope} and FAILED on {len(failed)}: {names}{more} "
            f"-- the loop is alive but is not reclaiming in those projects, so a stale hold "
            f"there will never be released; check the service log "
            f"(`journalctl --user -u amplifier-work-tracker`) for the per-project error"
        )
    return True, f"last {loop} sweep: {scope}, 0 failed, {got}"


__all__ = [
    "DEFAULT_STALE_MULTIPLE",
    "HEARTBEAT_FILENAME",
    "LOOPS",
    "LoopHeartbeat",
    "NOTIFY",
    "REAP",
    "evaluate_freshness",
    "evaluate_reclaiming",
    "heartbeat_path",
    "now_iso",
    "pid_alive",
    "read_loop_heartbeat",
    "record_loop_started",
    "record_sweep_completed",
]
