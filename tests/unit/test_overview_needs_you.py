"""Tier 1 -- the redefined "needs-you" overview (goal wtv2/overview): the
ranked cross-project attention queue, the one-sentence verdict + absence
alarm, the dispatch affordance, and the shared count vocabulary, plus the two
new zero-extra-bd-cost adapter signals that power them (`blocked_stale`,
`held_stale_oldest_age_seconds`).

Everything here is a pure function of constructed `Item`/`ProjectSummary`
values -- none of it needs `bd`, a dolt server, or a running FastAPI app.
`pytest.importorskip` guards the `webapp` import exactly like
`tests/unit/test_dashboard_ledger.py` does, since `webapp.py` imports
`fastapi` at module scope.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import webapp as W  # noqa: E402


def _summary(name: str, **kwargs: Any) -> A.ProjectSummary:
    defaults: dict[str, Any] = dict(
        status=A.STATUS_OK,
        total=0,
        ready=0,
        held=0,
        intake=0,
        blocked=0,
        resolved=0,
        deferred=0,
        held_stale=0,
        blocked_stale=0,
        held_stale_oldest_age_seconds=None,
        oldest_unclaimed_age_seconds=None,
        resolved_24h=0,
        resolved_7d=0,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 0, A.UNKNOWN_READY_AGE: 0},
    )
    defaults.update(kwargs)
    return A.ProjectSummary(name=name, **defaults)


def _aged(
    name: str, seven_plus: int, oldest_days: float = 9.0, ready: int | None = None
) -> A.ProjectSummary:
    ready = seven_plus if ready is None else ready
    return _summary(
        name,
        ready=ready,
        oldest_unclaimed_age_seconds=oldest_days * 86400,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": seven_plus, A.UNKNOWN_READY_AGE: 0},
    )


def _iso_ago(*, hours: float = 0, seconds: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours, seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ---------------------------------------------------------------------------
# adapter signals: blocked_stale + held_stale_oldest_age_seconds
# ---------------------------------------------------------------------------


def test_blocked_stale_counts_only_needlessly_blocked() -> None:
    # No active blocker left (deps empty) -> needlessly blocked -> stale.
    stale = A.Item(id="a", status="blocked", raw={"dependencies": []})
    # A live blocks-edge that is not yet closed -> genuinely blocked, NOT stale.
    genuine = A.Item(
        id="b",
        status="blocked",
        raw={"dependencies": [{"dependency_type": "blocks", "status": "open"}]},
    )
    # An unrelated (discovered-from) edge does not block -> stale.
    unrelated = A.Item(
        id="c",
        status="blocked",
        raw={"dependencies": [{"dependency_type": "discovered-from", "status": "open"}]},
    )
    assert A._blocked_stale_count([stale, genuine, unrelated]) == 2  # noqa: SLF001


def test_blocked_stale_is_safe_when_upstream_status_unreadable() -> None:
    # A blocks-edge whose status could not be read counts as still active
    # (never called stale on missing data) -- the safe default.
    missing = A.Item(
        id="a", status="blocked", raw={"dependencies": [{"dependency_type": "blocks"}]}
    )
    assert A._blocked_stale_count([missing]) == 0  # noqa: SLF001


def test_held_stale_oldest_age_uses_worst_breach_with_a_record() -> None:
    def held(last_seen: str) -> A.Item:
        return A.Item(
            id="h",
            status="held",
            holder="x",
            meta={C.CUSTODY_KEY: {"holder": "x", "pid": 1, "host": "h", "last_seen": last_seen}},
        )

    recent_stale = held(_iso_ago(hours=1))  # > 900s ttl -> stale
    worst_stale = held(_iso_ago(hours=3))  # older -> the reported age
    age = A._held_stale_oldest_age_seconds([recent_stale, worst_stale])  # noqa: SLF001
    assert age is not None
    assert age > 3 * 3600 - 120  # ~3h, the worst breach


def test_held_stale_oldest_age_none_when_nothing_stale() -> None:
    fresh = A.Item(
        id="h",
        status="held",
        holder="x",
        meta={
            C.CUSTODY_KEY: {"holder": "x", "pid": 1, "host": "h", "last_seen": _iso_ago(seconds=1)}
        },
    )
    assert A._held_stale_oldest_age_seconds([fresh]) is None  # noqa: SLF001


def test_held_stale_oldest_age_none_when_only_recordless_holds() -> None:
    # A hold with no custody record is reclaim-eligible but un-ageable: no
    # honest duration, so None rather than a fabricated 0.
    recordless = A.Item(id="h", status="held", holder="x", meta={})
    assert A._held_stale_oldest_age_seconds([recordless]) is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# ranked needs-you queue ordering (item 1)
# ---------------------------------------------------------------------------


def test_attention_for_none_when_calm_or_unreadable() -> None:
    assert W._attention_for(_summary("calm", ready=9, resolved=3)) is None  # noqa: SLF001
    broken = A.ProjectSummary(name="broke", status="ERROR: unreadable")
    assert W._attention_for(broken) is None  # noqa: SLF001


def test_attention_entries_rank_custody_over_blocker_over_age() -> None:
    custody = _summary("z_custody", held=2, held_stale=2, held_stale_oldest_age_seconds=3600)
    sblock = _summary("a_sblock", blocked=1, blocked_stale=1)
    aged = _aged("m_aged", 5)
    entries = W._attention_entries([aged, sblock, custody])  # noqa: SLF001
    assert [e.project for e in entries] == ["z_custody", "a_sblock", "m_aged"]
    assert entries[0].primary.cond == W._COND_CUSTODY  # noqa: SLF001
    assert entries[1].primary.cond == W._COND_STALE_BLOCKER  # noqa: SLF001
    assert entries[2].primary.cond == W._COND_AGED  # noqa: SLF001


def test_attention_entry_carries_all_live_conditions_sorted() -> None:
    both = _summary(
        "multi",
        held=1,
        held_stale=1,
        blocked=2,
        blocked_stale=1,  # 1 stale-blocker + 1 genuine blocked
        ready=3,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 3, A.UNKNOWN_READY_AGE: 0},
    )
    (entry,) = W._attention_entries([both])  # noqa: SLF001
    assert [c.cond for c in entry.conditions] == [
        W._COND_CUSTODY,  # noqa: SLF001
        W._COND_STALE_BLOCKER,  # noqa: SLF001
        W._COND_BLOCKED,  # noqa: SLF001
        W._COND_AGED,  # noqa: SLF001
    ]
    assert entry.has_blocked is True


def test_attention_entries_break_ties_by_count() -> None:
    small = _aged("small", 2)
    big = _aged("big", 9)
    entries = W._attention_entries([small, big])  # noqa: SLF001
    assert [e.project for e in entries] == ["big", "small"]


# ---------------------------------------------------------------------------
# verdict + absence alarm (items 2, 3)
# ---------------------------------------------------------------------------


def _verdict(entries, **kw):  # type: ignore[no-untyped-def]
    base: dict[str, Any] = dict(
        ready_total=0,
        held_total=0,
        resolved_24h_total=0,
        n_measurable=0,
        workspace_last_activity=_iso_ago(seconds=30),
        now=datetime.now(UTC),
    )
    base.update(kw)
    return W._verdict(entries, **base)  # noqa: SLF001


def test_verdict_idle_when_nothing_running_but_work_waits() -> None:
    # THE absence alarm: held == 0 while ready > 0 must NOT read all-clear.
    level, word, detail = _verdict([], ready_total=40, held_total=0)
    assert level == W._VERDICT_IDLE  # noqa: SLF001
    assert word == "FLEET IDLE"
    assert "ALL CLEAR" not in word
    assert "nothing in progress" in detail


def test_verdict_idle_notes_zero_throughput_today() -> None:
    _, _, detail = _verdict([], ready_total=10, held_total=0, resolved_24h_total=0, n_measurable=5)
    assert "0 resolved today" in detail


def test_verdict_stalled_when_no_movement_and_holds_exist() -> None:
    # Agents hold work but the fleet hasn't moved in over _STALL_HOURS.
    level, word, detail = _verdict(
        [],
        ready_total=5,
        held_total=2,
        workspace_last_activity=_iso_ago(hours=W._STALL_HOURS + 8),  # noqa: SLF001
    )
    assert level == W._VERDICT_IDLE  # noqa: SLF001
    assert word == "STALLED"
    assert "no movement" in detail


def test_verdict_all_clear_only_when_genuinely_calm() -> None:
    # Agents actively working, recent activity, nothing stuck -> ALL CLEAR.
    level, word, detail = _verdict([], ready_total=4, held_total=3)
    assert level == W._VERDICT_CLEAR  # noqa: SLF001
    assert word == "ALL CLEAR"
    assert "nothing stuck" in detail


def test_verdict_all_clear_no_open_work() -> None:
    level, word, detail = _verdict([], ready_total=0, held_total=0)
    assert (level, word) == (W._VERDICT_CLEAR, "ALL CLEAR")  # noqa: SLF001
    assert detail == "no open work anywhere"


def test_verdict_alarm_amber_for_custody_only_fleet() -> None:
    custody = _summary("p", held=1, held_stale=1, held_stale_oldest_age_seconds=3600)
    entries = W._attention_entries([custody])  # noqa: SLF001
    level, word, detail = _verdict(entries, held_total=1)
    assert level == W._VERDICT_ALARM  # noqa: SLF001
    assert word == "1 NEEDS YOU"
    assert "custody lapsed" in detail


def test_verdict_blocked_crimson_and_plural_keyword() -> None:
    a = _summary("a", blocked=1, blocked_stale=1)
    b = _aged("b", 3)
    entries = W._attention_entries([a, b])  # noqa: SLF001
    level, word, detail = _verdict(entries, ready_total=3)
    assert level == W._VERDICT_BLOCKED  # noqa: SLF001
    assert word == "2 NEED YOU"
    assert "needlessly blocked" in detail and "waiting 7d+" in detail


# ---------------------------------------------------------------------------
# verdict HTML: flat data-ink, hue only when real, time anchor (items 3, 5)
# ---------------------------------------------------------------------------


def test_verdict_html_calm_uses_no_status_hue() -> None:
    now = datetime.now(UTC)
    html = W._verdict_html(W._VERDICT_CLEAR, "ALL CLEAR", "nothing stuck", now)  # noqa: SLF001
    assert "v-clear" in html
    assert "--alarm" not in html
    assert "--blocked" not in html
    # time-to-notice/act anchor is always present.
    assert "data-rendered-at=" in html
    assert "as of" in html


def test_verdict_html_alarm_carries_amber_not_crimson() -> None:
    now = datetime.now(UTC)
    html = W._verdict_html(W._VERDICT_IDLE, "FLEET IDLE", "40 items ready", now)  # noqa: SLF001
    assert "v-idle" in html


def test_verdict_html_is_flat_never_glass() -> None:
    now = datetime.now(UTC)
    html = W._verdict_html(W._VERDICT_BLOCKED, "1 NEEDS YOU", "1 blocked", now)  # noqa: SLF001
    # The gloss license does not travel to the verdict: no glass/gradient/blur.
    assert "glass" not in html
    assert "gradient" not in html
    assert "blur" not in html


# ---------------------------------------------------------------------------
# needs-you queue HTML: severity, data-since, dispatch verb (items 1, 5, 6)
# ---------------------------------------------------------------------------


def test_needs_you_html_absent_when_no_entries() -> None:
    assert W._needs_you_html([], datetime.now(UTC)) == ""  # noqa: SLF001


def test_needs_you_html_marks_severity_and_since_and_dispatch() -> None:
    now = datetime.now(UTC)
    custody = _summary("cust", held=2, held_stale=2, held_stale_oldest_age_seconds=5 * 3600)
    blocker = _summary("blk", blocked=1, blocked_stale=1)
    entries = W._attention_entries([custody, blocker])  # noqa: SLF001
    html = W._needs_you_html(entries, now)  # noqa: SLF001
    assert "sev-am" in html  # custody -> amber
    assert "sev-cr" in html  # stale-blocker -> crimson
    assert "data-since=" in html  # custody carries an honest duration
    assert "\u2192 open cust" in html  # dispatch verb per row
    assert "custody lapsed \u00b7 2" in html
    # ranked order: custody row appears before the blocker row.
    assert html.index("cust") < html.index("blk")


def test_needs_you_blocked_condition_has_no_fabricated_since() -> None:
    now = datetime.now(UTC)
    blocker = _summary("blk", blocked=2, blocked_stale=2)
    (entry,) = W._attention_entries([blocker])  # noqa: SLF001
    html = W._needs_you_html([entry], now)  # noqa: SLF001
    # A blocked condition carries no honest duration -> no data-since anywhere.
    assert "data-since=" not in html


# ---------------------------------------------------------------------------
# dispatch affordance (item 6)
# ---------------------------------------------------------------------------


def test_dispatch_pick_prefers_aged_then_deep_queue() -> None:
    shallow_fresh = _summary("fresh", ready=50)
    deep_aged = _aged("aged", 5, oldest_days=9, ready=20)
    pick = W._dispatch_pick([shallow_fresh, deep_aged])  # noqa: SLF001
    assert pick is not None and pick.name == "aged"


def test_dispatch_html_absent_when_nothing_ready() -> None:
    assert W._dispatch_html([_summary("x", ready=0, resolved=5)]) == ""  # noqa: SLF001


def test_dispatch_html_names_project_and_verb() -> None:
    html = W._dispatch_html([_aged("target", 4, ready=12)])  # noqa: SLF001
    assert "Point the next agent at" in html
    assert "claim next in target" in html
    assert "12 items ready" in html


# ---------------------------------------------------------------------------
# denominator vocabulary (item 4)
# ---------------------------------------------------------------------------


def test_units_legend_defines_one_vocabulary() -> None:
    html = W._units_legend_html()  # noqa: SLF001
    for term in ("Queue", "Ready", "Held", "Blocked", "Resolved", "Done"):
        assert term in html
    assert "resolved" in html and "total" in html


def test_sidebar_badge_spells_out_denominator() -> None:
    s = _summary("proj", total=16, resolved=0)
    html = W._sidebar_html(["proj"], [s], None)  # noqa: SLF001
    assert 'title="16 open of 16 items"' in html
