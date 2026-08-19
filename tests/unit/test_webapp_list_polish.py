"""Tier 1 -- pure-function tests for the project-view list-polish helpers:
the status-tab counter row (`_status_tab_counts`/`_status_tabs_html`), the
consistent relative-age helper (`_item_age_html`), and the per-row priority
bar + status icon (`_priority_bar_html`/`_status_icon_html`, wired into
`_item_row`). See `tests/unit/test_dashboard_ledger.py` for the sibling
suite covering the workspace-level composition bar/legend/attention signal
these reuse.

No bd, no dolt, no network: everything here is a pure function of
constructed `ProjectSummary`/`Item`/plain values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    )
    defaults.update(kwargs)
    return A.ProjectSummary(name=name, **defaults)


def _item(item_id: str = "proj-abcd", **kwargs) -> A.Item:
    defaults: dict[str, Any] = dict(
        title="an item",
        status="open",
        kind="task",
        priority=None,
        holder=None,
        created_at=None,
        updated_at=None,
        closed_at=None,
        description=None,
        acceptance=None,
        resolution=None,
        raw={},
    )
    defaults.update(kwargs)
    return A.Item(id=item_id, **defaults)


# ------------------------------------------------------- _status_tab_counts


def test_status_tab_counts_mirrors_the_real_project_summary():
    """No second, independently-derived count -- every field comes straight
    from the SAME `ProjectSummary` the project page already computed."""
    s = _summary("proj", total=32, ready=30, held=1, blocked=1, deferred=0, resolved=0)
    counts = W._status_tab_counts(s)  # noqa: SLF001
    assert counts == {"all": 32, "ready": 30, "held": 1, "blocked": 1, "deferred": 0, "resolved": 0}


def test_status_tab_counts_all_zero_for_a_broken_or_creating_project():
    """A project that isn't `STATUS_OK` has no real counts to show --
    every tab reads 0, never a fabricated reading for an unreadable
    project (see `ProjectSummary`'s own docstring)."""
    s = A.ProjectSummary(name="broken", status=A.STATUS_BROKEN)
    counts = W._status_tab_counts(s)  # noqa: SLF001
    assert counts == {"all": 0, "ready": 0, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}


def test_status_tab_counts_none_fields_become_zero_not_none():
    s = _summary(
        "proj", total=None, ready=None, held=None, blocked=None, deferred=None, resolved=None
    )
    counts = W._status_tab_counts(s)  # noqa: SLF001
    assert all(v == 0 for v in counts.values())


# -------------------------------------------------------- _status_tabs_html


def test_status_tabs_html_shows_all_six_tabs_with_real_counts():
    counts = {"all": 32, "ready": 30, "held": 1, "blocked": 1, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    for label in ("All", "Ready", "Held", "Blocked", "Deferred", "Resolved"):
        assert f">{label}<" in html
    assert ">32<" in html
    assert ">30<" in html


def test_status_tabs_html_zero_count_is_dimmed_not_hidden():
    """The 'lamp present, switched off' convention: a zero count still
    renders its tab and its real '0', just in the dimmed `.tcount.z`
    tone -- never omitted."""
    counts = {"all": 5, "ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert ">Held<" in html
    assert ">Blocked<" in html
    assert '<span class="tcount z">0</span>' in html


def test_status_tabs_html_held_turns_amber_when_nonzero():
    counts = {"all": 5, "ready": 3, "held": 2, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert '<span class="tcount am">2</span>' in html


def test_status_tabs_html_blocked_turns_crimson_when_nonzero():
    counts = {"all": 5, "ready": 3, "held": 0, "blocked": 1, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert '<span class="tcount cr">1</span>' in html


def test_status_tabs_html_ready_and_resolved_never_get_an_alarm_class_even_when_large():
    """A healthy, large ready backlog is not something to alarm-colour --
    only held/blocked ever carry `.am`/`.cr`."""
    counts = {"all": 500, "ready": 480, "held": 0, "blocked": 0, "deferred": 0, "resolved": 20}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert '<span class="tcount">480</span>' in html
    assert '<span class="tcount">20</span>' in html
    assert "tcount am" not in html
    assert "tcount cr" not in html


def test_status_tabs_html_active_tab_is_marked():
    counts = {"all": 5, "ready": 3, "held": 1, "blocked": 0, "deferred": 0, "resolved": 1}
    html = W._status_tabs_html("proj", "held", "", counts)  # noqa: SLF001
    assert '<a class="tab active" href="/projects/proj?status=held">' in html
    # every other tab is present but not active
    assert '<a class="tab" href="/projects/proj?status=blocked">' in html


def test_status_tabs_html_all_tab_is_active_when_no_status_filter():
    counts = {"all": 5, "ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert '<a class="tab active" href="/projects/proj">' in html


def test_status_tabs_html_clicking_a_tab_filters_via_status_query_param():
    """Each tab is a plain server-linked `?status=` href -- the same query
    param the existing route already reads, so clicking one is an
    ordinary navigation with no new client-side filtering logic."""
    counts = {"all": 5, "ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", None, "", counts)  # noqa: SLF001
    assert 'href="/projects/proj?status=open"' in html  # Ready
    assert 'href="/projects/proj?status=resolved"' in html  # Resolved


def test_status_tabs_html_carries_an_active_search_through():  # noqa: D103
    counts = {"all": 5, "ready": 5, "held": 0, "blocked": 0, "deferred": 0, "resolved": 0}
    html = W._status_tabs_html("proj", "held", "urgent thing", counts)  # noqa: SLF001
    assert 'href="/projects/proj?status=held&q=urgent%20thing"' in html


# --------------------------------------------------------------- _tab_href


def test_tab_href_all_tab_with_no_search_has_no_query_string():
    assert W._tab_href("proj", None, "") == "/projects/proj"  # noqa: SLF001


def test_tab_href_all_tab_with_a_search_carries_only_q():
    assert W._tab_href("proj", None, "foo") == "/projects/proj?q=foo"  # noqa: SLF001


# ------------------------------------------------------------ _item_age_html


def test_item_age_html_none_renders_the_shared_empty_glyph():
    assert "\u2014" in W._item_age_html(None)  # noqa: SLF001


def test_item_age_html_fresh_item_reads_now_not_0m():
    dt = datetime.now(UTC) - timedelta(seconds=5)
    html = W._item_age_html(dt)  # noqa: SLF001
    assert ">now<" in html
    assert "0m" not in html


def test_item_age_html_uses_the_same_compact_units_as_the_row_age_column():
    hours_ago = datetime.now(UTC) - timedelta(hours=3)
    html = W._item_age_html(hours_ago)  # noqa: SLF001
    assert ">3h<" in html


def test_item_age_html_days_matches_age_short():
    days_ago = datetime.now(UTC) - timedelta(days=5)
    html = W._item_age_html(days_ago)  # noqa: SLF001
    assert ">5d<" in html


def test_item_age_html_carries_the_real_iso_timestamp_as_a_title():
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    html = W._item_age_html(dt)  # noqa: SLF001
    assert f'title="{dt.isoformat()}"' in html


def test_item_age_html_never_escalates_to_the_amber_alarm_tier():
    """v3 firewall polish: `_item_age_html` renders HISTORY (Created/
    Updated/Resolved, activity-timeline event ages) -- amber-as-neglect
    is reserved for a genuinely ready/unclaimed item's own Age column
    (`_item_row`, status-gated) and the ready-queue-by-age widget, never
    for a calm fact about the past. A history reading this old would
    have escalated to `age_band_class`'s amber 'a3' tier verbatim before
    this fix; it must now cap at the neutral '--ink' 'a2' tier instead."""
    old = datetime.now(UTC) - timedelta(days=10)
    html = W._item_age_html(old)  # noqa: SLF001
    assert 'class="age a2"' in html
    assert "a3" not in html


def test_item_age_html_moderately_old_still_reads_a2():
    """An age that would only reach the 'a2' tier anyway (4-6 days) is
    unaffected by the cap -- confirms the cap is a ceiling, not a
    blanket downgrade of the whole band scale."""
    moderately_old = datetime.now(UTC) - timedelta(days=5)
    html = W._item_age_html(moderately_old)  # noqa: SLF001
    assert 'class="age a2"' in html


# ------------------------------------------------------- _priority_bar_html


@pytest.mark.parametrize(
    "priority,chip_class",
    [
        (0, "p0"),
        (1, "p1"),
        (2, "p2"),
        (3, "p3"),
        (4, "p4"),
    ],
)
def test_priority_bar_html_maps_each_bd_priority_to_its_ramp_step(priority, chip_class):
    """v3 fidelity pass (goal wtv3/components, B3/B4): a `P{n}` glass mono
    CHIP -- ported from the approved gallery's own `.priority-chip` -- not
    a coloured bar. Severity still rides the neutral text ramp (each
    `.priority-chip.p{n}` class, defined in webtheme.py's CSS, dims by
    weight/opacity, never a reserved status hue)."""
    html = W._priority_bar_html(priority)  # noqa: SLF001
    assert f'class="priority-chip {chip_class}"' in html
    assert f">P{priority}<" in html


def test_priority_bar_html_none_degrades_honestly_to_the_faint_neutral():
    """No real priority to show -- render the honest `P?` chip, never a
    guessed rank, and say so via the title."""
    html = W._priority_bar_html(None)  # noqa: SLF001
    assert 'class="priority-chip punk"' in html
    assert 'title="priority unknown"' in html


def test_priority_bar_html_out_of_range_value_also_degrades_honestly():
    html = W._priority_bar_html(99)  # noqa: SLF001
    assert 'class="priority-chip punk"' in html
    assert 'title="priority unknown"' in html


def test_priority_bar_html_never_uses_the_reserved_amber_or_crimson_hues():
    """Amber/crimson are each reserved for exactly one job elsewhere
    (age/attention, blocked/escalation) -- the priority ramp must never
    borrow either, at any priority value."""
    for p in (0, 1, 2, 3, 4, None):
        html = W._priority_bar_html(p)  # noqa: SLF001
        assert "--amber" not in html
        assert "--crimson" not in html


# --------------------------------------------------------- _status_icon_html


@pytest.mark.parametrize(
    "status,css_class",
    [
        ("open", "st-open"),
        ("held", "st-held"),
        ("blocked", "st-blkd"),
        ("deferred", "st-deferred"),
        ("resolved", "st-done"),
    ],
)
def test_status_icon_html_reuses_the_same_colour_class_as_the_text_badge(status, css_class):
    """An icon and its row's text status badge must never disagree in
    colour -- both come from the SAME `_STATE_CSS` mapping."""
    html = W._status_icon_html(status)  # noqa: SLF001
    assert css_class in html
    assert "<svg" in html


# ------------------------------------------------------- _item_row (gutter)


def test_item_row_includes_a_priority_bar_and_status_icon_gutter_cell():
    item = _item("proj-abcd", priority=0, status="held")
    row = W._item_row("proj", item, 1)  # noqa: SLF001
    assert 'class="c gutter"' in row
    # v3 fidelity pass (goal wtv3/components, B3/B4): a `P{n}` glass mono
    # CHIP, ported from the approved gallery's `.priority-chip` -- not a
    # coloured bar. Severity still rides the neutral text ramp, never a
    # reserved status hue (`p0` is the boldest/brightest chip variant).
    assert 'class="priority-chip p0"' in row
    assert "st-held" in row


def test_item_row_gutter_degrades_honestly_when_priority_is_missing():
    item = _item("proj-abcd", priority=None, status="open")
    row = W._item_row("proj", item, 1)  # noqa: SLF001
    assert 'class="priority-chip punk"' in row
    assert 'title="priority unknown"' in row
    assert "st-open" in row
