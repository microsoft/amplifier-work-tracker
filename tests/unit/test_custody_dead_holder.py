"""Tier 1 -- the DEAD-HOLDER reclaim path (`model_performance-oy4`).

WHAT THIS PINS, and why it is not just "another staleness test". Custody's
freshness rule infers liveness from silence: a hold is reclaim-eligible
`CUSTODY_TTL_SECONDS` (900s) after its last renewal, and the sweep that acts
on it runs on its own interval on top of that -- up to 20 minutes before a
dead lane's item returns to the queue. Meanwhile the custody record has
carried `pid` and `host` since it was designed, and nothing has ever read
them for a decision.

MEASURED, on the live queue, item `model_performance-h6v` (the forensic
timeline is committed at
`docs/lanes/oy4-dead-holder-reclaim/evidence/h6v-forensic-timeline.txt`):
its holder renewed on a metronome-regular 120s cadence through
2026-09-03T07:41:36Z and then stopped. Four successor `work_claim` attempts
-- 07:47, 07:50, 07:51 and 07:56Z -- were all refused, and every one of them
was refused CORRECTLY: the last landed 45 seconds inside the 900s TTL. The
item was finally freed by a hand-run `unclaim` at 07:57:51Z. Nothing was
broken; the TTL was doing exactly what it says, blind to the one fact that
settled the matter.

So these tests fix the ACCELERATION and, just as importantly, its three
fences. The fences are the whole safety argument: this path may only ever
fire on positive evidence of death, and every unknowable case must resolve
to NOT eligible, because a false positive here takes work away from a live
agent.
"""

from __future__ import annotations

import time

from amplifier_work_tracker import custody as C

HOST = "test-host"


def _ts(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _record(*, last_seen_ago: float, pid: int = 4242, host: str = HOST) -> dict:
    return {
        "holder": "agent-test-4242",
        "pid": pid,
        "host": host,
        "generation": 1,
        "started_at": _ts(last_seen_ago + 600),
        "last_seen": _ts(last_seen_ago),
        "declared_state": C.STATE_WORKING,
        "declared_since": _ts(last_seen_ago + 600),
    }


def _dead(_pid: int) -> bool:
    return False


def _alive(_pid: int) -> bool:
    return True


# --------------------------------------------------------------------------
# The acceleration itself.
# --------------------------------------------------------------------------


def test_dead_holder_is_reclaim_eligible_well_inside_the_ttl():
    """THE FAIL-BEFORE. 300s of silence against a 900s TTL: two thirds of the
    TTL still to run, so path 1 cannot fire and (before this change) nothing
    else could either. The holder's pid is not running on this very host --
    that is enough.
    """
    rec = _record(last_seen_ago=300)
    eligible, reason = C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_dead)
    assert eligible is True
    assert "holder process is dead" in reason
    assert "pid 4242" in reason
    # The reason must say the TTL was NOT what fired, or a reader will
    # mis-attribute the reclaim to ordinary staleness.
    assert "ttl 900s not yet reached" in reason


def test_dead_holder_reason_is_distinguishable_from_ordinary_staleness():
    """A reclaim's reason is read by humans triaging a stranded lane, and is
    what `reap_project` records. "Died" and "went quiet" are different
    diagnoses and must never print the same sentence.
    """
    dead = C.reclaim_eligible(_record(last_seen_ago=300), ttl=900, host=HOST, is_pid_alive=_dead)[1]
    stale = C.reclaim_eligible(_record(last_seen_ago=1200), ttl=900, host=HOST)[1]
    assert dead != stale
    assert stale.startswith("custody stale")
    assert dead.startswith("holder process is dead")


def test_ttl_staleness_still_wins_and_costs_no_pid_probe():
    """Path 1 is evaluated first, so an already-stale hold keeps its exact
    prior reason string -- and a probe that would explode is never called,
    proving the ordering rather than asserting it.
    """

    def _explode(_pid: int) -> bool:  # pragma: no cover - must never run
        raise AssertionError("pid probe consulted for an already-TTL-stale hold")

    eligible, reason = C.reclaim_eligible(
        _record(last_seen_ago=1200), ttl=900, host=HOST, is_pid_alive=_explode
    )
    assert eligible is True
    assert reason.startswith("custody stale -- last seen")


# --------------------------------------------------------------------------
# Fence 1: another host is unknowable, never dead.
# --------------------------------------------------------------------------


def test_holder_on_another_host_is_never_called_dead():
    """A pid means nothing across machines. The probe would answer for a
    LOCAL pid of the same number -- a coincidence that must never reclaim a
    live remote agent's work -- so the host check has to come first.
    """
    rec = _record(last_seen_ago=300, host="some-other-box")
    eligible, _ = C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_dead)
    assert eligible is False


def test_holder_with_no_host_recorded_is_never_called_dead():
    rec = _record(last_seen_ago=300, host="")
    assert C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_dead)[0] is False


# --------------------------------------------------------------------------
# Fence 2: a pid that is not a pid.
# --------------------------------------------------------------------------


def test_missing_or_zero_pid_is_never_called_dead():
    for pid in (0, -1):
        rec = _record(last_seen_ago=300, pid=pid)
        assert C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_dead)[0] is False


# --------------------------------------------------------------------------
# Fence 3: the corroboration window. This is the fence that protects an
# agent whose pid simply is not addressable from here (a container with its
# own pid namespace reporting the same hostname): such an agent keeps
# renewing, so it never enters the window where the probe is consulted at
# all.
# --------------------------------------------------------------------------


def test_a_recently_renewed_hold_is_never_probed_into_death():
    """One renewal interval of silence is normal operation, not death."""
    rec = _record(last_seen_ago=60)
    eligible, _ = C.reclaim_eligible(
        rec, ttl=900, host=HOST, dead_holder_min_silence=240, is_pid_alive=_dead
    )
    assert eligible is False


def test_the_corroboration_window_boundary_is_inclusive_from_min_silence():
    rec_just_under = _record(last_seen_ago=239)
    rec_just_over = _record(last_seen_ago=241)
    kw = {"ttl": 900, "host": HOST, "dead_holder_min_silence": 240, "is_pid_alive": _dead}
    assert C.reclaim_eligible(rec_just_under, **kw)[0] is False
    assert C.reclaim_eligible(rec_just_over, **kw)[0] is True


def test_default_corroboration_window_is_two_renewal_intervals():
    """The default must stay tied to the renewal cadence, not a magic number
    -- otherwise a deployment that changes the renewal interval silently
    changes how aggressive this path is.
    """
    assert C.DEAD_HOLDER_MIN_SILENCE_SECONDS == 2 * C.RENEW_INTERVAL_SECONDS
    assert C.DEAD_HOLDER_MIN_SILENCE_SECONDS < C.CUSTODY_TTL_SECONDS


# --------------------------------------------------------------------------
# A live holder is never touched -- the property everything above exists to
# protect.
# --------------------------------------------------------------------------


def test_a_live_holder_deep_inside_the_ttl_is_left_alone():
    rec = _record(last_seen_ago=300)
    assert C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_alive)[0] is False


def test_pid_reuse_errs_toward_leaving_the_hold_alone():
    """A recycled pid answers "alive", which merely falls back to the TTL.
    Imprecision only ever in the safe direction.
    """
    rec = _record(last_seen_ago=800)
    assert C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_alive)[0] is False


def test_awaiting_human_does_not_shield_a_dead_holder():
    """`declared_state` is reporting only -- it never buys exemption from
    staleness, and it must not buy exemption from death either.
    """
    rec = _record(last_seen_ago=300)
    rec["declared_state"] = C.STATE_AWAITING_HUMAN
    rec["declared_since"] = _ts(400)
    assert C.reclaim_eligible(rec, ttl=900, host=HOST, is_pid_alive=_dead)[0] is True


# --------------------------------------------------------------------------
# The probe itself.
# --------------------------------------------------------------------------


def test_pid_alive_reports_this_process_alive_and_a_nonexistent_pid_dead():
    import os

    assert C.pid_alive(os.getpid()) is True
    assert C.pid_alive(0) is False
    assert C.pid_alive(-5) is False


def test_local_host_matches_what_writers_store():
    import socket

    assert C.local_host() == socket.gethostname()


def test_holder_process_dead_returns_empty_reason_when_not_dead():
    """Every "not dead" answer must carry an empty reason, so a caller can
    never print a half-built explanation for a decision that did not fire.
    """
    dead, reason = C.holder_process_dead(
        _record(last_seen_ago=60), host=HOST, min_silence=240, is_pid_alive=_dead
    )
    assert (dead, reason) == (False, "")


def test_no_custody_record_is_not_a_dead_holder_claim():
    """`reclaim_eligible(None)` already reports "claimed but never renewed";
    the dead-holder helper must not also claim a process it never saw.
    """
    assert C.holder_process_dead(None) == (False, "")
