"""Tier 1 -- the A-Ledger overview's pure render helpers in `webapp.py`:
the workspace/row composition bar + legend, the ready-count hero, the
secondary readings (concentration / waiting 7d+ / custody), throughput,
the queue-table row/totals, and the ready-descending sort key.

Everything here is a pure function of constructed `ProjectSummary`/plain
values -- none of it needs `bd`, a dolt server, or a running FastAPI app.
`pytest.importorskip` guards the module import exactly like
`tests/integration/test_web.py` does, since `webapp.py` imports `fastapi`
at module scope.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webapp as W  # noqa: E402


def _summary(name: str, **kwargs) -> A.ProjectSummary:
    defaults: dict[str, Any] = dict(
        status=A.STATUS_OK,
        total=0,
        ready=0,
        held=0,
        intake=0,
        blocked=0,
        resolved=0,
        deferred=0,
        resolved_24h=0,
        resolved_7d=0,
        ready_age_buckets={"0-1": 0, "2-3": 0, "4-6": 0, "7+": 0, A.UNKNOWN_READY_AGE: 0},
    )
    defaults.update(kwargs)
    return A.ProjectSummary(name=name, **defaults)


# --------------------------------------------------------------- state bar


def test_state_bar_zero_state_renders_as_seam_not_absent():
    """The 'alarm lamp present and switched off' convention: a zero-count
    state is a visible 2px seam, never nothing at all."""
    counts = {"ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 3}
    html = W._state_bar_html(counts)  # noqa: SLF001 -- pinning a private invariant
    assert html.count('<span class="seam">') == 3  # held, blocked, deferred
    assert html.count("<i ") == 2  # ready, resolved
    assert "flex:5 1 0" in html
    assert "flex:3 1 0" in html


def test_state_bar_fixed_slot_order_is_always_the_same():
    """Five slots, ready/held/blocked/deferred/resolved, always -- so the
    eye learns the order and a segment appearing for the first time is
    legible."""
    counts = {"ready": 1, "held": 2, "blocked": 3, "deferred": 4, "resolved": 5}
    html = W._state_bar_html(counts)  # noqa: SLF001
    order = [html.index(f"flex:{n} 1 0") for n in (1, 2, 3, 4, 5)]
    assert order == sorted(order)


def test_state_legend_zero_count_shows_real_number_not_hidden():
    """A zero IS a reading -- shown as the real number 0, in the quieter
    `.n.z` tone, never whispered to invisibility or omitted."""
    counts = {"ready": 10, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._state_legend_html(counts)  # noqa: SLF001
    assert '<span class="n z">0</span><span class="l">held</span>' in html
    assert '<span class="n z">0</span><span class="l">blocked</span>' in html
    assert '<span class="n">10</span><span class="l">ready</span>' in html


def test_state_legend_nonzero_states_use_their_dedicated_fill():
    counts = {"ready": 1, "held": 1, "blocked": 1, "deferred": 1, "resolved": 1}
    html = W._state_legend_html(counts)  # noqa: SLF001
    assert "var(--st-ready)" in html
    assert "var(--amber)" in html  # held reuses the app-wide attention hue
    assert "var(--crimson)" in html  # blocked reuses the app-wide escalation hue


# ------------------------------------------------------- alarm floor width


def test_state_bar_calm_zero_alarm_states_have_no_min_width_floor():
    """A calm workspace's seams are plain 3px seams -- the alarm floor is
    never applied to a zero-count state (only to a REAL non-zero
    held/blocked/deferred segment)."""
    counts = {"ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 3}
    html = W._state_bar_html(counts)  # noqa: SLF001
    assert "min-width" not in html


def test_state_bar_tiny_held_count_among_huge_total_still_gets_alarm_floor():
    """The exact failure mode this deliverable exists to fix: 1 held item
    out of a huge total must not render as a proportional (and therefore
    near-invisible) sliver -- it must carry the alarm floor width."""
    counts = {"ready": 998, "held": 1, "blocked": 0, "deferred": 0, "resolved": 1}
    html = W._state_bar_html(counts)  # noqa: SLF001
    assert f"flex:1 1 0;background:var(--amber);min-width:{W._ALARM_MIN_PX}px" in html  # noqa: SLF001
    # the calm ready/resolved segments never get the floor -- they are not
    # alarm states and routinely carry large real counts of their own.
    assert "flex:998 1 0;background:var(--st-ready)" in html
    assert "min-width" not in html.split("var(--st-ready)")[1].split("<i")[0]


def test_state_bar_blocked_and_deferred_also_get_the_alarm_floor():
    counts = {"ready": 1, "held": 0, "blocked": 2, "deferred": 3, "resolved": 0}
    html = W._state_bar_html(counts)  # noqa: SLF001
    assert f"flex:2 1 0;background:var(--crimson);min-width:{W._ALARM_MIN_PX}px" in html  # noqa: SLF001
    assert f"flex:3 1 0;background:var(--st-deferred);min-width:{W._ALARM_MIN_PX}px" in html  # noqa: SLF001


# ------------------------------------------------------------- sort order


def test_dashboard_sort_key_orders_ready_descending():
    a = _summary("low", ready=2)
    b = _summary("high", ready=9)
    c = _summary("mid", ready=5)
    ordered = sorted([a, b, c], key=W._dashboard_sort_key)  # noqa: SLF001
    assert [s.name for s in ordered] == ["high", "mid", "low"]


def test_dashboard_sort_key_ties_break_by_name():
    a = _summary("zeta", ready=1)
    b = _summary("alpha", ready=1)
    ordered = sorted([a, b], key=W._dashboard_sort_key)  # noqa: SLF001
    assert [s.name for s in ordered] == ["alpha", "zeta"]


def test_dashboard_sort_key_broken_queues_sort_first_regardless_of_count():
    """An alarm row must never be pushed below the fold by a healthy
    queue with a bigger ready number."""
    healthy = _summary("bigqueue", ready=1000)
    broken = A.ProjectSummary(name="brokenqueue", status="ERROR: unreadable")
    ordered = sorted([healthy, broken], key=W._dashboard_sort_key)  # noqa: SLF001
    assert ordered[0].name == "brokenqueue"


# --------------------------------------------------------------- the hero


def test_ledger_hero_unreadable_workspace_renders_honest_dash():
    html = W._ledger_hero_html(None, 3, None)  # noqa: SLF001
    assert "\u2014" in html
    assert "No queue could be read right now" in html
    assert "3" not in html  # never fabricates a count from n_projects


def test_ledger_hero_zero_projects_says_so_plainly():
    html = W._ledger_hero_html(0, 0, None)  # noqa: SLF001
    assert ">0<" in html
    assert "No projects yet." in html


def test_ledger_hero_normal_case_shows_count_and_burn_rate():
    html = W._ledger_hero_html(107, 11, 2.4)  # noqa: SLF001
    assert ">107<" in html
    assert "<b>11</b>" in html
    assert "<b>2.4</b>" in html
    assert "measured rate" in html


def test_ledger_hero_no_throughput_is_an_honest_gap_not_a_fabricated_rate():
    html = W._ledger_hero_html(50, 5, None)  # noqa: SLF001
    assert "no measured throughput today" in html
    assert "days of work" not in html


# ---------------------------------------------------------- secondary readings


def test_secondary_readings_no_ready_items_is_honest_dash_for_concentration():
    html = W._secondary_readings_html(None, 0, None, None, None, 0, 0)  # noqa: SLF001
    assert "nothing ready to concentrate" in html
    assert "nothing has waited a week" in html
    assert "nothing is stuck" in html


def test_secondary_readings_concentration_links_to_the_project():
    html = W._secondary_readings_html(  # noqa: SLF001
        ("amplifier_windows", 32, 29.9), 0, None, None, None, 0, 0
    )
    assert '<a href="/projects/amplifier_windows">' in html
    assert ">32<" in html
    assert "30%" in html


def test_secondary_readings_waiting_7d_uses_amber_only_when_nonzero():
    zero_html = W._secondary_readings_html(None, 0, None, None, None, 0, 0)  # noqa: SLF001
    nonzero_html = W._secondary_readings_html(  # noqa: SLF001
        None, 17, 15.9, 9, "/projects/x/items/y", 0, 0
    )
    assert 'class="n am"' not in zero_html
    assert 'class="n am"' in nonzero_html
    assert '<a href="/projects/x/items/y">9d</a>' in nonzero_html


def test_secondary_readings_custody_reports_blocked_needing_attention():
    html = W._secondary_readings_html(None, 0, None, None, None, 2, 1)  # noqa: SLF001
    assert ">2<" in html  # held figure
    assert "1 blocked" in html
    assert "nothing is stuck" not in html


# --------------------------------------------------------------- throughput


def test_throughput_no_prior_rate_is_honest_not_a_fabricated_delta():
    html = W._throughput_html(0, 0.0, None, 0, 0, 0, 0)  # noqa: SLF001
    assert "no prior rate to compare" in html


def test_throughput_reports_trend_percentage_when_measurable():
    html = W._throughput_html(45, 31.33, 44, 233, 14, 5, 5)  # noqa: SLF001
    assert "+44%" in html
    assert "233 resolved in 7 days" in html
    assert "14 older than that" in html


def test_throughput_names_coverage_gap_when_some_queues_unmeasurable():
    html = W._throughput_html(10, 5.0, 100, 20, 2, 3, 5)  # noqa: SLF001
    assert "Throughput reflects 3 of 5" in html
    assert "record completion timestamps" in html


def test_throughput_no_coverage_footnote_when_fully_measurable():
    html = W._throughput_html(10, 5.0, 100, 20, 2, 5, 5)  # noqa: SLF001
    assert "Throughput reflects" not in html


# ---------------------------------------------------- workspace composition


def test_workspace_composition_computes_percent_resolved():
    counts = {"ready": 107, "held": 0, "blocked": 0, "deferred": 0, "resolved": 294}
    html = W._workspace_composition_html(counts, 401)  # noqa: SLF001
    assert "73%" in html
    assert "401" in html
    assert "Workspace by state" in html


def test_workspace_composition_zero_total_never_divides_by_zero():
    counts = {"ready": 0, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._workspace_composition_html(counts, 0)  # noqa: SLF001
    assert "0%" in html


# --------------------------------------------------------------- queue rows


def test_dashboard_row_broken_project_is_unmissable_alarm_row():
    s = A.ProjectSummary(name="brokenq", status="ERROR: database unreachable")
    html = W._dashboard_row(s)  # noqa: SLF001
    assert 'class="alarm"' in html
    assert 'colspan="5"' in html
    assert "Broken" in html


def test_dashboard_row_zero_resolved_shows_dash_not_fabricated_zero_percent():
    s = _summary("freshq", total=15, ready=15, resolved=0)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert "\u2014" in html  # the resolved-column dash convention


def test_dashboard_row_real_resolved_shows_count_and_percent():
    s = _summary("cortex", total=266, ready=19, resolved=247)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert ">247<" in html
    assert "93%" in html


def test_dashboard_row_calm_project_has_no_alarm_styling():
    """A healthy queue (no held/blocked/deferred) gets a plain row -- no
    left-edge accent, no tint -- so the flag below is a real signal, not
    background noise on every row."""
    s = _summary("calmq", total=10, ready=10)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert "box-shadow" not in html
    assert "healthy" in html  # data-t search key still names the calm state


def test_dashboard_row_held_item_flags_the_row_amber():
    s = _summary("heldq", total=5, ready=4, held=1)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert "box-shadow:inset 4px 0 0 var(--amber)" in html
    assert "held" in html.split('data-t="')[1].split('"')[0]


def test_dashboard_row_blocked_item_flags_the_row_crimson_outranking_held():
    """Blocked outranks held in the accent chosen -- same escalation
    ordering used everywhere else in this file (`_secondary_readings_html`,
    `_state_bar_html`'s own hue assignment)."""
    s = _summary("stuckq", total=5, ready=3, held=1, blocked=1)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert "box-shadow:inset 4px 0 0 var(--crimson)" in html
    assert "var(--amber)" not in html.split("box-shadow")[0][-40:]


def test_dashboard_row_deferred_item_also_flags_the_row():
    s = _summary("deferredq", total=5, ready=4, deferred=1)
    html = W._dashboard_row(s)  # noqa: SLF001
    assert "box-shadow:inset 4px 0 0 var(--amber)" in html
    assert "deferred" in html.split('data-t="')[1].split('"')[0]


def test_dashboard_totals_sums_every_readable_project():
    a = _summary("a", total=10, ready=5, resolved=5)
    b = _summary("b", total=20, ready=15, resolved=5)
    broken = A.ProjectSummary(name="c", status="ERROR: x")
    html = W._dashboard_totals([a, b, broken])  # noqa: SLF001
    assert ">30<" in html  # total
    assert ">20<" in html  # ready
    assert ">10<" in html  # resolved


# ------------------------------------------------- top-level attention signal


def test_attention_signal_absent_entirely_when_calm():
    """Calm (0/0/0) renders NOTHING -- not a dimmed zero, not hidden via
    CSS, genuinely absent -- unlike the composition bar's always-present
    seams. A permanent 'need attention' banner reading 0 would itself
    become the thing a trained eye learns to ignore."""
    assert W._attention_signal_html(0, 0, 0) == ""  # noqa: SLF001


def test_attention_signal_present_and_amber_when_only_held():
    html = W._attention_signal_html(2, 0, 0)  # noqa: SLF001
    assert html != ""
    assert "flash-msg" in html
    assert "flash-error" not in html
    assert ">2<" in html
    assert "2 items held" in html


def test_attention_signal_crimson_when_anything_is_blocked():
    """Blocked outranks held/deferred for the banner's accent -- the same
    escalation ordering used throughout this file."""
    html = W._attention_signal_html(1, 1, 1)  # noqa: SLF001
    assert "flash-error" in html
    assert "flash-msg" not in html
    assert ">3<" in html
    assert "1 item blocked" in html
    assert "1 item held" in html
    assert "1 item deferred" in html
