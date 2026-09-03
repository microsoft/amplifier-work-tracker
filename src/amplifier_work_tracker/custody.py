"""Custody -- our own liveness signal for long-held claims.

Beads' native leases are node-local (`dolt_ignored`, never replicated), and its
`heartbeat` / `reclaim` commands exist in the repo source but are ABSENT from
the v1.1.2 release we run against (verified by probing the binary: both answer
"unknown command"). So liveness for held work is entirely ours, carried as a
`custody` record inside the item's own metadata -- which DOES replicate with
the item, unlike bd's leases. See `amplifier_work_tracker.adapter.Beads.take_custody` /
`renew_custody` for the reads/writes; this module is the pure domain logic
those methods hand records to and receive decisions from. It knows nothing
about `bd` and calls no subprocess.

The workload this is built for: a long-running coding agent may work
autonomously for hours, then sit completely idle for hours awaiting a human's
answer or approval, then resume. A claim legitimately held 12+ hours, mostly
idle, is healthy -- a short lease is wrong, and "heartbeat forever" is also
wrong, because it keeps zombies alive too.

Two states only decide reclaim, deliberately:
  - custody FRESH  (renewed within CUSTODY_TTL_SECONDS) -> never reclaimed
  - custody STALE  (not renewed in time, or never renewed at all) -> reclaimed

`declared_state` ("working" | "awaiting_human") is a REPORTING field only. It
never buys exemption from staleness -- an agent that declares awaiting_human
and then dies must still go stale and be reclaimed like any other. Its only
effect on the reclaim decision is the escalation ceiling below, which is a
one-way door toward reclaim, never a hold against it.

DEAD HOLDERS (model_performance-oy4). Silence is a *proxy* for death, and a
slow one: the TTL cannot fire until a full CUSTODY_TTL_SECONDS after the last
renewal, and the sweep that acts on it runs on its own interval on top of
that. MEASURED on the live queue for item `model_performance-h6v`: its holder
renewed on a perfectly regular 120s cadence up to 2026-09-03T07:41:36Z and
then stopped dead; four successor `work_claim` attempts (07:47, 07:50, 07:51,
07:56Z) were all refused, and all four were refused CORRECTLY -- the last one
landed 45s inside the 900s TTL. The stranding was not a broken TTL, a wrong
field, or a dead sweep: it was the TTL doing exactly what it says while the
one fact that mattered -- the holder's process was gone -- sat unread in the
custody record's own `pid`/`host` fields.

So there is a THIRD path to reclaim-eligible, and it observes the holder
rather than inferring from its silence: a custody record naming a pid ON THIS
HOST that the kernel says is not running. It is fenced by three conditions so
it can only ever be an ACCELERATION of the TTL, never a way to take work from
a live agent:

  1. `host` must equal this host. A pid on another machine is unknowable
     from here -- never guessed.
  2. `pid` must be a real positive pid.
  3. The custody signal must already have been SILENT for at least
     `DEAD_HOLDER_MIN_SILENCE_SECONDS` (default: two renewal intervals). A
     live agent renews every RENEW_INTERVAL_SECONDS, so this is independent
     corroboration that the holder has ALREADY missed a renewal before any
     pid probe is allowed to decide anything -- which is what protects an
     agent whose pid is not addressable from here (a container in its own
     pid namespace that happens to report the same hostname): it keeps
     renewing, so it never enters the window where the probe is consulted.

Every failure of those conditions resolves to NOT eligible: unknowable is
never treated as dead. The probe is injectable for the same reason
`heartbeat.evaluate_freshness`'s is -- so every branch is testable with no
real processes and no real sleeps.
"""

from __future__ import annotations

import calendar
import os
import socket
import time
from dataclasses import asdict, dataclass

CUSTODY_KEY = "custody"

# Renewal window: no renewal within this many seconds -> stale.
# Overridable for testing/ops without a code change.
CUSTODY_TTL_SECONDS = int(os.environ.get("AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS", "900"))

# Hours a FRESH custody may sit declaring awaiting_human before it becomes
# reclaim-eligible regardless. A terminal ceiling, not a permanent lock --  one
# unresponsive human must never immobilize an item forever.
ESCALATION_HOURS = float(os.environ.get("AMPLIFIER_WORK_TRACKER_ESCALATION_HOURS", "24"))

# How often `amplifier-work-tracker custody` renews by default.
RENEW_INTERVAL_SECONDS = int(os.environ.get("AMPLIFIER_WORK_TRACKER_RENEW_INTERVAL_SECONDS", "120"))

# How long a custody signal must ALREADY have been silent before a holder-
# liveness probe is allowed to decide anything (see the module docstring's
# condition 3). Two renewal intervals: a live agent renews every
# RENEW_INTERVAL_SECONDS, so crossing this window means it has already missed
# a renewal outright -- independent corroboration, gathered without a probe,
# before any probe is consulted. Always well under CUSTODY_TTL_SECONDS, or
# this path would never accelerate anything.
DEAD_HOLDER_MIN_SILENCE_SECONDS = int(
    os.environ.get(
        "AMPLIFIER_WORK_TRACKER_DEAD_HOLDER_MIN_SILENCE_SECONDS",
        str(2 * RENEW_INTERVAL_SECONDS),
    )
)

STATE_WORKING = "working"
STATE_AWAITING_HUMAN = "awaiting_human"
VALID_STATES = (STATE_WORKING, STATE_AWAITING_HUMAN)

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_iso() -> str:
    """UTC timestamp in the one format every custody field uses."""
    return time.strftime(_ISO_FMT, time.gmtime())


def _parse_iso(ts: str) -> float:
    """Epoch seconds for a now_iso()-shaped string. calendar.timegm, not
    time.mktime -- the latter assumes local time and would silently skew every
    freshness check by the host's UTC offset."""
    return float(calendar.timegm(time.strptime(ts, _ISO_FMT)))


def age_seconds(ts: str, *, now: float | None = None) -> float:
    """Seconds elapsed since an ISO-8601 UTC timestamp produced by now_iso().

    Never negative -- clock skew between writer and reader should not manufacture
    a negative age that would make a barely-written record look ancient (or a
    barely-stale one look fresh).
    """
    if not ts:
        return float("inf")
    n = now if now is not None else time.time()
    return max(0.0, n - _parse_iso(ts))


@dataclass
class Custody:
    """One custody record, in our vocabulary. Mirrors exactly what lives under
    the item's `metadata["custody"]` key -- see amplifier_work_tracker.adapter for
    the read/write."""

    holder: str
    pid: int
    host: str
    started_at: str
    last_seen: str
    generation: int
    declared_state: str = STATE_WORKING
    declared_since: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Custody:
        return cls(
            holder=str(d.get("holder", "")),
            pid=int(d.get("pid", 0) or 0),
            host=str(d.get("host", "")),
            started_at=str(d.get("started_at", "")),
            last_seen=str(d.get("last_seen", "")),
            generation=int(d.get("generation", 0) or 0),
            declared_state=str(d.get("declared_state", STATE_WORKING)),
            declared_since=str(d.get("declared_since") or d.get("started_at", "")),
        )


def _coerce(custody: dict | Custody | None) -> Custody | None:
    if custody is None:
        return None
    return custody if isinstance(custody, Custody) else Custody.from_dict(custody)


def is_fresh(
    custody: dict | Custody | None,
    *,
    ttl: int = CUSTODY_TTL_SECONDS,
    now: float | None = None,
) -> bool:
    """Has the custody signal itself been renewed within the TTL?

    This is the ONLY freshness question, and `declared_state` never enters
    into it -- an agent that says "awaiting_human" and then dies must go stale
    exactly like one that never said anything at all.
    """
    c = _coerce(custody)
    if c is None or not c.last_seen:
        return False
    return age_seconds(c.last_seen, now=now) <= ttl


def local_host() -> str:
    """This host's name, in the SAME form every writer stores in a custody
    record's `host` field (`socket.gethostname()` -- see the tool module's
    `take_custody` call site and `cli.cmd_custody`). Compared as an exact
    string: a mismatch means "not knowable from here", never "dead".
    """
    return socket.gethostname()


def pid_alive(pid: int) -> bool:
    """Best-effort: is *pid* a live process on this host? Never raises.

    `os.kill(pid, 0)` sends no signal -- it only asks the kernel whether the
    pid is addressable. A pid owned by another user raises PermissionError,
    which PROVES it exists, so that answers True.

    Deliberately a mirror of `heartbeat.pid_alive` rather than an import of
    it, for the reason `heartbeat._parse_iso` already states about its own
    twin here: this module is the pure domain core and must stay importable
    with no dependency on the supervisor/service plumbing stack.

    PID REUSE is the one imprecision, and it is imprecise in the SAFE
    direction only: a recycled pid answers True, which merely falls back to
    the TTL. It can never manufacture a False for a live holder.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    except OSError:
        return False
    return True


def holder_process_dead(
    custody: dict | Custody | None,
    *,
    host: str | None = None,
    min_silence: int = DEAD_HOLDER_MIN_SILENCE_SECONDS,
    now: float | None = None,
    is_pid_alive=pid_alive,
) -> tuple[bool, str]:
    """Is this custody record's named holder PROVABLY not running?

    Returns (dead, reason). Every unknowable case returns False with an
    empty reason -- see the module docstring for the three fences and why
    each one resolves toward "not dead". This is the only place in the
    system that reads `Custody.pid` / `Custody.host` for a decision.
    """
    c = _coerce(custody)
    if c is None:
        return False, ""
    if c.pid <= 0:
        return False, ""
    this_host = host if host is not None else local_host()
    if not c.host or c.host != this_host:
        # A pid on another machine says nothing to this one. Never guessed.
        return False, ""
    silence = age_seconds(c.last_seen, now=now) if c.last_seen else float("inf")
    if silence < min_silence:
        # Renewed too recently to corroborate death -- a probe here would be
        # deciding on the probe alone. See module docstring, condition 3.
        return False, ""
    if is_pid_alive(c.pid):
        return False, ""
    return True, (
        f"holder process is dead -- pid {c.pid} on host {c.host!r} is not running, "
        f"and custody has been silent {silence:.0f}s "
        f"(corroboration window {min_silence}s)"
    )


def reclaim_eligible(
    custody: dict | Custody | None,
    *,
    ttl: int = CUSTODY_TTL_SECONDS,
    escalation_hours: float = ESCALATION_HOURS,
    now: float | None = None,
    host: str | None = None,
    dead_holder_min_silence: int = DEAD_HOLDER_MIN_SILENCE_SECONDS,
    is_pid_alive=pid_alive,
) -> tuple[bool, str]:
    """The whole reclaim decision, and nothing else decides it.

    Three paths to eligible, and only three:
      1. STALE -- custody was never renewed, or the renewal window lapsed.
         Total hold duration is irrelevant; only recency of the last renewal
         matters, so a healthily-renewed 12-hour hold is never touched.
      2. DEAD HOLDER -- the record names a pid on THIS host that the kernel
         says is not running, and custody has already been silent long
         enough to corroborate it (`holder_process_dead`). Strictly an
         ACCELERATION of path 1: it can only ever fire inside the TTL window
         path 1 would eventually cover anyway, and only on positive evidence
         of death. Added for `model_performance-oy4` -- see the module
         docstring for the measured stranding that motivated it.
      3. ESCALATION CEILING -- fresh, declaring awaiting_human, but has held
         that declaration past `escalation_hours`. A terminal state, not a
         lock: one unresponsive human cannot immobilize an item forever.

    `declared_state` affects ONLY path 3, and only as a ceiling stacked on
    top of freshness -- never as a way to buy exemption from staleness. An
    item declaring awaiting_human with STALE custody is reclaimed via path 1,
    same as any other stale item; one whose process has died is reclaimed via
    path 2, likewise regardless of what it declared.

    Path 1 is evaluated FIRST so an already-TTL-stale hold keeps its existing
    reason string verbatim (and costs no pid probe at all).
    """
    c = _coerce(custody)
    if c is None:
        return True, "no custody record -- item was claimed but never renewed"
    if not is_fresh(c, ttl=ttl, now=now):
        age = age_seconds(c.last_seen, now=now)
        return True, f"custody stale -- last seen {age:.0f}s ago (ttl {ttl}s)"
    dead, why = holder_process_dead(
        c,
        host=host,
        min_silence=dead_holder_min_silence,
        now=now,
        is_pid_alive=is_pid_alive,
    )
    if dead:
        return True, f"{why}; ttl {ttl}s not yet reached, but the holder is gone"
    if c.declared_state == STATE_AWAITING_HUMAN and c.declared_since:
        held_hours = age_seconds(c.declared_since, now=now) / 3600.0
        if held_hours >= escalation_hours:
            return True, (
                f"escalation ceiling exceeded -- {held_hours:.1f}h awaiting_human "
                f"(ceiling {escalation_hours}h); custody is fresh but no human "
                f"has responded in time"
            )
    return False, ""


def should_notify(custody: dict | Custody | None) -> bool:
    """Reporting only -- NEVER consulted by reclaim_eligible.

    A long, fresh hold declaring awaiting_human is healthy and silent: a
    human is expected to be the bottleneck. A long, fresh hold still
    declaring "working" is worth a human's attention even though it is not
    yet reclaim-eligible -- the idle flag suppresses notification, not
    reclaim, and this is the only place that distinction is allowed to live.
    """
    c = _coerce(custody)
    if c is None:
        return False
    return c.declared_state != STATE_AWAITING_HUMAN
