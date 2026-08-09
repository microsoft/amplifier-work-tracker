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
"""

from __future__ import annotations

import calendar
import os
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


def reclaim_eligible(
    custody: dict | Custody | None,
    *,
    ttl: int = CUSTODY_TTL_SECONDS,
    escalation_hours: float = ESCALATION_HOURS,
    now: float | None = None,
) -> tuple[bool, str]:
    """The whole reclaim decision, and nothing else decides it.

    Two paths to eligible, and only two:
      1. STALE -- custody was never renewed, or the renewal window lapsed.
         Total hold duration is irrelevant; only recency of the last renewal
         matters, so a healthily-renewed 12-hour hold is never touched.
      2. ESCALATION CEILING -- fresh, declaring awaiting_human, but has held
         that declaration past `escalation_hours`. A terminal state, not a
         lock: one unresponsive human cannot immobilize an item forever.

    `declared_state` affects ONLY path 2, and only as a ceiling stacked on
    top of freshness -- never as a way to buy exemption from staleness. An
    item declaring awaiting_human with STALE custody is reclaimed via path 1,
    same as any other stale item.
    """
    c = _coerce(custody)
    if c is None:
        return True, "no custody record -- item was claimed but never renewed"
    if not is_fresh(c, ttl=ttl, now=now):
        age = age_seconds(c.last_seen, now=now)
        return True, f"custody stale -- last seen {age:.0f}s ago (ttl {ttl}s)"
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
