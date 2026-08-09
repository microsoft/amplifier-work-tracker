"""Tier 1 -- custody math, pure logic, no bd, no network, no real waiting.

Every timestamp here is forged (via time.gmtime(time.time() - N)) rather
than produced by actually sleeping -- that is what keeps this whole tier
under a second while still exercising the exact freshness/escalation math
`amplifier-work-tracker reap` depends on.
"""

from __future__ import annotations

import time

from amplifier_work_tracker import custody as C


def _ts(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _record(
    *,
    last_seen_ago: float,
    declared_state: str = C.STATE_WORKING,
    declared_since_ago: float | None = None,
) -> dict:
    return {
        "holder": "someone",
        "pid": 1,
        "host": "h",
        "generation": 1,
        "started_at": _ts(declared_since_ago if declared_since_ago is not None else last_seen_ago),
        "declared_since": _ts(
            declared_since_ago if declared_since_ago is not None else last_seen_ago
        ),
        "last_seen": _ts(last_seen_ago),
        "declared_state": declared_state,
    }


# --------------------------------------------------------------- age_seconds


def test_age_seconds_of_a_fresh_timestamp_is_small():
    assert C.age_seconds(_ts(1)) < 5


def test_age_seconds_never_negative_on_clock_skew():
    """A timestamp minted slightly in the future (writer/reader clock skew)
    must never produce a negative age -- that would make a barely-written
    record look impossibly ancient or a barely-stale one look fresher than
    it is."""
    future = _ts(-3600)  # "3600 seconds ago" with a negative offset = future
    assert C.age_seconds(future) == 0.0


def test_age_seconds_of_empty_timestamp_is_infinite():
    assert C.age_seconds("") == float("inf")


# ------------------------------------------------------------------ is_fresh


def test_is_fresh_true_within_ttl():
    assert C.is_fresh(_record(last_seen_ago=10), ttl=900) is True


def test_is_fresh_false_beyond_ttl():
    assert C.is_fresh(_record(last_seen_ago=1000), ttl=900) is False


def test_is_fresh_none_record_is_not_fresh():
    assert C.is_fresh(None) is False


def test_is_fresh_ignores_declared_state():
    """Freshness is ONLY about last_seen recency -- declared_state must
    never factor into it."""
    working = _record(last_seen_ago=10, declared_state=C.STATE_WORKING)
    idle = _record(last_seen_ago=10, declared_state=C.STATE_AWAITING_HUMAN)
    assert C.is_fresh(working, ttl=900) == C.is_fresh(idle, ttl=900) is True


# ------------------------------------------------------------ reclaim_eligible


def test_reclaim_eligible_no_record_at_all():
    eligible, reason = C.reclaim_eligible(None)
    assert eligible is True
    assert "no custody record" in reason


def test_reclaim_eligible_fresh_survives_a_long_total_hold():
    """The whole point of custody: a claim renewed recently must never be
    reclaimed no matter how long the TOTAL hold has been -- a 20-hour hold
    with a fresh renewal 10 seconds ago is healthy, not stale."""
    rec = _record(last_seen_ago=10, declared_since_ago=20 * 3600)
    eligible, reason = C.reclaim_eligible(rec, ttl=900)
    assert eligible is False, reason


def test_reclaim_eligible_stale_after_ttl_lapses():
    rec = _record(last_seen_ago=3600)
    eligible, reason = C.reclaim_eligible(rec, ttl=900)
    assert eligible is True
    assert "stale" in reason


def test_reclaim_eligible_escalation_ceiling_exceeded():
    """Fresh custody signal, but has declared awaiting_human for longer
    than the escalation ceiling -- must become reclaim-eligible regardless
    of freshness. One unresponsive human must not immobilize an item
    forever."""
    rec = _record(
        last_seen_ago=5,
        declared_state=C.STATE_AWAITING_HUMAN,
        declared_since_ago=25 * 3600,
    )
    eligible, reason = C.reclaim_eligible(rec, ttl=900, escalation_hours=24)
    assert eligible is True
    assert "escalation ceiling" in reason


def test_reclaim_eligible_awaiting_human_below_ceiling_is_not_eligible():
    rec = _record(
        last_seen_ago=5,
        declared_state=C.STATE_AWAITING_HUMAN,
        declared_since_ago=1 * 3600,
    )
    eligible, _ = C.reclaim_eligible(rec, ttl=900, escalation_hours=24)
    assert eligible is False


def test_reclaim_eligible_idle_declaration_never_exempts_from_staleness():
    """The critical negative case: declaring awaiting_human and then going
    stale must be reclaimed via the STALE path exactly like any other
    item -- narration must never buy exemption from the liveness check."""
    rec = _record(last_seen_ago=3600, declared_state=C.STATE_AWAITING_HUMAN)
    eligible, reason = C.reclaim_eligible(rec, ttl=900, escalation_hours=24)
    assert eligible is True
    assert "stale" in reason


# ------------------------------------------------------------- should_notify


def test_should_notify_working_state():
    assert C.should_notify(_record(last_seen_ago=5, declared_state=C.STATE_WORKING)) is True


def test_should_notify_awaiting_human_is_suppressed():
    assert C.should_notify(_record(last_seen_ago=5, declared_state=C.STATE_AWAITING_HUMAN)) is False


def test_should_notify_none_record():
    assert C.should_notify(None) is False


def test_should_notify_is_never_consulted_by_reclaim_eligible():
    """Documented separation of concerns: `should_notify` must never affect
    the reclaim decision -- it is reporting-only. A fresh, awaiting_human
    record notifies=False but is still not reclaim-eligible."""
    rec = _record(last_seen_ago=5, declared_state=C.STATE_AWAITING_HUMAN)
    assert C.should_notify(rec) is False
    eligible, _ = C.reclaim_eligible(rec, ttl=900)
    assert eligible is False


# ------------------------------------------------------------------- Custody


def test_custody_roundtrip_through_dict():
    rec = _record(last_seen_ago=1)
    c = C.Custody.from_dict(rec)
    assert c.holder == "someone"
    assert c.pid == 1
    assert c.declared_state == C.STATE_WORKING
    assert c.to_dict()["holder"] == "someone"


def test_now_iso_matches_expected_format():
    ts = C.now_iso()
    # Must parse back cleanly through the same format string used to write it.
    time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
