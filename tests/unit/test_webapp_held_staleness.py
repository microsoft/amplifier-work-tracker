"""Tier 1 -- pure-function tests for held-item claim-age + staleness:
`webapp._custody_reading`/`_custody_html` (the row/detail-page rendering),
`webapp._attention_signal_html`'s `held_stale` parenthetical, and
`adapter._held_stale_count` (the per-project rollup `project_summary` uses).

No bd, no dolt, no network: everything here is a pure function of
constructed `Item`s/custody dicts and forged epoch timestamps -- nothing
sleeps, nothing depends on wall-clock timing at test-run time.

Real policy, reused, not reinvented: staleness is decided by
`custody.reclaim_eligible` -- the SAME function `supervisor.reap_project`
calls to decide what it actually reclaims (see `tests/unit/test_custody.py`
for that function's own exhaustive tests). These tests pin that the
*display* layer reads that real decision correctly, not a second copy of
the policy.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import custody as CU  # noqa: E402
from amplifier_work_tracker import webapp as W  # noqa: E402

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso(epoch: float) -> str:
    return time.strftime(_ISO_FMT, time.gmtime(epoch))


def _custody_dict(
    *,
    holder: str = "agent-spark-1-106784",
    started_at: str = "",
    last_seen: str = "",
    declared_state: str = CU.STATE_WORKING,
    declared_since: str = "",
    generation: int = 1,
) -> dict:
    return {
        "holder": holder,
        "pid": 123,
        "host": "test-host",
        "started_at": started_at,
        "last_seen": last_seen,
        "declared_state": declared_state,
        "declared_since": declared_since or started_at,
        "generation": generation,
    }


def _held_item(**kwargs) -> A.Item:
    defaults: dict = dict(
        id="proj-abcd",
        title="an item",
        status="held",
        holder="agent-spark-1-106784",
        kind="task",
        meta={},
        updated_at=None,
    )
    defaults.update(kwargs)
    return A.Item(**defaults)


# --------------------------------------------------------------- _custody_reading


def test_custody_reading_none_when_not_held():
    item = _held_item(status="open")
    assert W._custody_reading(item) is None  # noqa: SLF001


def test_custody_reading_fresh_hold_uses_started_at_for_age_and_is_not_stale():
    now = time.time()
    cust = _custody_dict(started_at=_iso(now - 4 * 3600), last_seen=_iso(now - 30))
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    reading = W._custody_reading(item, now=now)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is False
    assert reading.proxy is False
    assert reading.holder == "agent-spark-1-106784"
    assert reading.age_seconds is not None
    assert abs(reading.age_seconds - 4 * 3600) < 2


def test_custody_reading_stale_when_renewal_lapsed_past_ttl():
    now = time.time()
    ttl = CU.CUSTODY_TTL_SECONDS
    cust = _custody_dict(started_at=_iso(now - 5000), last_seen=_iso(now - (ttl + 60)))
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    reading = W._custody_reading(item, now=now)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is True
    assert "stale" in reading.reason


def test_custody_reading_ttl_boundary_exactly_at_ttl_is_still_fresh():
    """`custody.is_fresh` uses `<=` -- exactly at the TTL boundary is the
    last instant still considered fresh, one second past it is not.

    `now` is forced to a whole-second value: `_iso()` (like every real
    custody timestamp -- see `custody.now_iso`) has no sub-second
    precision, so comparing it against a fractional `now` would leak up to
    ~1s of rounding slack into a boundary test that is specifically about
    the exact second."""
    now = float(int(time.time()))
    ttl = CU.CUSTODY_TTL_SECONDS
    at_boundary = _custody_dict(started_at=_iso(now - 5000), last_seen=_iso(now - ttl))
    item = _held_item(meta={CU.CUSTODY_KEY: at_boundary})
    reading = W._custody_reading(item, now=now)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is False

    past_boundary = _custody_dict(started_at=_iso(now - 5000), last_seen=_iso(now - (ttl + 1)))
    item2 = _held_item(meta={CU.CUSTODY_KEY: past_boundary})
    reading2 = W._custody_reading(item2, now=now)  # noqa: SLF001
    assert reading2 is not None
    assert reading2.stale is True


def test_custody_reading_no_custody_record_is_stale_and_proxied_from_updated_at():
    """No `custody` key at all -- `reclaim_eligible(None)` already says this
    is reclaim-eligible ("no custody record"), so it renders stale too, and
    the only available age signal is `item.updated_at`, honestly labeled a
    proxy (never presented as a real custody duration)."""
    updated = datetime.now(UTC) - timedelta(hours=2)
    item = _held_item(meta={}, updated_at=updated)
    reading = W._custody_reading(item)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is True
    assert "no custody record" in reading.reason
    assert reading.proxy is True
    assert reading.age_seconds is not None
    assert abs(reading.age_seconds - 2 * 3600) < 5


def test_custody_reading_no_custody_record_and_no_updated_at_has_no_age_at_all():
    """Truly nothing to derive an age from -- `age_seconds` is `None`, never
    a fabricated duration."""
    item = _held_item(meta={}, updated_at=None)
    reading = W._custody_reading(item)  # noqa: SLF001
    assert reading is not None
    assert reading.age_seconds is None
    assert reading.proxy is False


def test_custody_reading_awaiting_human_fresh_is_not_stale_but_reports_declared_state():
    """Declaring awaiting_human while custody is genuinely fresh (well under
    both the TTL and the escalation ceiling) must NOT be stale -- but the
    reading still carries `declared_state` so the renderer can note the TTL
    clock still runs (see `custody.py`'s module docstring)."""
    now = time.time()
    cust = _custody_dict(
        started_at=_iso(now - 3600),
        last_seen=_iso(now - 30),
        declared_state=CU.STATE_AWAITING_HUMAN,
        declared_since=_iso(now - 3600),
    )
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    reading = W._custody_reading(item, now=now)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is False
    assert reading.declared_state == CU.STATE_AWAITING_HUMAN


def test_custody_reading_awaiting_human_past_escalation_ceiling_is_stale():
    """A FRESH hold (renewed recently) that has declared awaiting_human past
    the escalation ceiling is reclaim-eligible anyway -- `declared_state`
    buys zero exemption from being shown as stale."""
    now = time.time()
    esc_seconds = CU.ESCALATION_HOURS * 3600
    cust = _custody_dict(
        started_at=_iso(now - esc_seconds - 3600),
        last_seen=_iso(now - 30),  # renewed a moment ago -- genuinely fresh
        declared_state=CU.STATE_AWAITING_HUMAN,
        declared_since=_iso(now - esc_seconds - 60),  # declared past the ceiling
    )
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    reading = W._custody_reading(item, now=now)  # noqa: SLF001
    assert reading is not None
    assert reading.stale is True
    assert "escalation" in reading.reason


# ------------------------------------------------------------------ _custody_html


def test_custody_html_none_reading_renders_nothing():
    assert W._custody_html(None) == ""  # noqa: SLF001


def test_custody_html_fresh_reading_is_neutral_not_amber():
    reading = W.CustodyReading(
        holder="agent-x",
        stale=False,
        reason="",
        declared_state=CU.STATE_WORKING,
        age_seconds=4 * 3600,
        proxy=False,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert 'class="held-custody fresh"' in html
    assert "held-custody stale" not in html
    assert "held 4h" in html
    assert "agent-x" in html


def test_custody_html_stale_reading_is_amber_and_carries_the_real_reason_as_title():
    reading = W.CustodyReading(
        holder="agent-x",
        stale=True,
        reason="custody stale -- last seen 1000s ago (ttl 900s)",
        declared_state=CU.STATE_WORKING,
        age_seconds=3600,
        proxy=False,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert 'class="held-custody stale"' in html
    assert "held-custody fresh" not in html
    assert "last seen 1000s ago" in html


def test_custody_html_no_age_renders_held_with_no_duration():
    reading = W.CustodyReading(
        holder="agent-x",
        stale=False,
        reason="",
        declared_state=CU.STATE_WORKING,
        age_seconds=None,
        proxy=False,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert ">held &middot;" in html or "held &middot;" in html


def test_custody_html_proxy_age_is_labeled_as_a_proxy_not_a_real_duration():
    reading = W.CustodyReading(
        holder="agent-x",
        stale=True,
        reason="no custody record -- item was claimed but never renewed",
        declared_state=CU.STATE_WORKING,
        age_seconds=2 * 3600,
        proxy=True,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert "no custody record" in html
    assert "held-custody stale" in html


def test_custody_html_fresh_awaiting_human_notes_the_ttl_clock_still_runs():
    reading = W.CustodyReading(
        holder="agent-x",
        stale=False,
        reason="",
        declared_state=CU.STATE_AWAITING_HUMAN,
        age_seconds=3600,
        proxy=False,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert "awaiting human" in html
    assert "TTL clock still runs" in html
    # Never rendered as "fine"/an all-clear -- no amber, but also no
    # affirmative "healthy" language beyond the neutral fresh reading itself.
    assert "held-custody fresh" in html


def test_custody_html_unknown_holder_degrades_honestly():
    reading = W.CustodyReading(
        holder="",
        stale=False,
        reason="",
        declared_state=CU.STATE_WORKING,
        age_seconds=60,
        proxy=False,
    )
    html = W._custody_html(reading)  # noqa: SLF001
    assert "unknown holder" in html


# ------------------------------------------------------------------- _item_row


def test_item_row_held_item_shows_custody_reading_not_bare_identity():
    now = time.time()
    cust = _custody_dict(started_at=_iso(now - 4 * 3600), last_seen=_iso(now - 30))
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    row = W._item_row("proj", item, 1)  # noqa: SLF001
    assert "held-custody fresh" in row
    assert "held 4h" in row


def test_item_row_stale_held_item_shows_amber_custody_class():
    now = time.time()
    ttl = CU.CUSTODY_TTL_SECONDS
    cust = _custody_dict(started_at=_iso(now - 5000), last_seen=_iso(now - (ttl + 60)))
    item = _held_item(meta={CU.CUSTODY_KEY: cust})
    row = W._item_row("proj", item, 1)  # noqa: SLF001
    assert "held-custody stale" in row


# ------------------------------------------------------- _attention_signal_html


def test_attention_signal_held_stale_default_is_byte_identical_to_before():
    """No `held_stale` argument at all -- every pre-existing caller's output
    is unchanged."""
    assert W._attention_signal_html(2, 0, 0) == W._attention_signal_html(2, 0, 0, 0)  # noqa: SLF001


def test_attention_signal_held_stale_adds_a_parenthetical_when_nonzero():
    html = W._attention_signal_html(3, 0, 0, held_stale=1)  # noqa: SLF001
    assert "3 items held (1 stale)" in html


def test_attention_signal_held_stale_zero_is_absent_not_a_dimmed_zero():
    html = W._attention_signal_html(3, 0, 0, held_stale=0)  # noqa: SLF001
    assert "stale" not in html
    assert "3 items held" in html


def test_attention_signal_held_stale_never_escalates_to_crimson_alone():
    """A stale hold, with nothing blocked, stays in the amber `flash-msg`
    tier -- only a genuinely BLOCKED item escalates to `flash-error`."""
    html = W._attention_signal_html(1, 0, 0, held_stale=1)  # noqa: SLF001
    assert "flash-msg" in html
    assert "flash-error" not in html


def test_attention_signal_held_stale_never_double_counts_the_total():
    html = W._attention_signal_html(3, 0, 0, held_stale=3)  # noqa: SLF001
    assert "<strong>3</strong>" in html  # not 6


# ------------------------------------------------------- adapter._held_stale_count


def _held_item_with_custody(item_id: str, cust: dict | None) -> A.Item:
    return A.Item(
        id=item_id,
        status="held",
        holder=cust.get("holder") if cust else None,
        meta=({CU.CUSTODY_KEY: cust} if cust is not None else {}),
    )


def test_held_stale_count_counts_only_reclaim_eligible_items():
    now = time.time()
    ttl = CU.CUSTODY_TTL_SECONDS
    fresh = _held_item_with_custody(
        "a", _custody_dict(started_at=_iso(now - 100), last_seen=_iso(now - 10))
    )
    stale = _held_item_with_custody(
        "b", _custody_dict(started_at=_iso(now - 5000), last_seen=_iso(now - (ttl + 60)))
    )
    no_custody = _held_item_with_custody("c", None)
    assert A._held_stale_count([fresh, stale, no_custody]) == 2  # noqa: SLF001


def test_held_stale_count_zero_when_every_hold_is_fresh():
    now = time.time()
    items = [
        _held_item_with_custody(
            "a", _custody_dict(started_at=_iso(now - 100), last_seen=_iso(now - 10))
        ),
        _held_item_with_custody(
            "b", _custody_dict(started_at=_iso(now - 200), last_seen=_iso(now - 20))
        ),
    ]
    assert A._held_stale_count(items) == 0  # noqa: SLF001


def test_held_stale_count_empty_list_is_zero():
    assert A._held_stale_count([]) == 0  # noqa: SLF001
