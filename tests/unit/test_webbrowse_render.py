"""Tier 1 (pure, no bd/dolt) tests for wt-v4 Observatory's L1/L2 render
helpers in ``amplifier_work_tracker.webbrowse``.

These construct ``adapter.Item`` values directly and call the module-level
render helpers -- no adapter/bd calls, no fixtures, no ``integration`` marker.

Retired: the v3 split-pane browse view's own render helpers (``_row_html``,
``render_list_html``, ``render_detail_html``, ``render_browse_body``,
``browse_js``, ``_BROWSE_CSS``) no longer exist -- see ``webbrowse.py``'s
module docstring. This file's former coverage of them is superseded below.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import webbrowse as B


def _item(item_id: str = "proj-abcd", **over: object) -> A.Item:
    """Build an ``A.Item`` with sensible defaults; any field can be
    overridden by keyword."""
    item = A.Item(
        id=item_id,
        title="an item",
        status="open",
        kind="task",
        priority=2,
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )
    for key, value in over.items():
        setattr(item, key, value)
    return item


# --------------------------------------------------------------------- item rows


def test_item_row_links_directly_to_l2_and_strips_project_prefix():
    row = B._item_row_html("proj", _item("proj-abcd", title="Do the thing"))
    assert 'href="/projects/proj/items/proj-abcd"' in row
    assert ">abcd<" in row
    assert "Do the thing" in row


def test_item_row_status_chip_differs_by_status():
    open_row = B._item_row_html("proj", _item("proj-a", status="open"))
    blocked_row = B._item_row_html("proj", _item("proj-b", status="blocked"))
    assert "st-ready" in open_row
    assert "st-blocked" in blocked_row
    assert open_row != blocked_row


def test_item_row_holder_shows_blocked_by_id_when_blocked():
    row = B._item_row_html(
        "proj",
        _item(
            "proj-a",
            status="blocked",
            links=[{"type": "blocks", "id": "proj-upstream", "blocking": True}],
        ),
    )
    assert "blocked by proj-upstream" in row


def test_item_row_holder_absent_for_resolved_item_with_leftover_holder():
    """A resolved item's `.holder` cell shows the leftover assignee as plain
    text -- but the row's STATUS chip is st-resolved, never st-held."""
    row = B._item_row_html("proj", _item("proj-a", status="resolved", holder="agent:alice"))
    assert 'class="status-chip st-resolved">RESOLVED</span>' in row


def test_item_row_shows_a_corrected_badge_when_the_item_carries_an_erratum():
    row = B._item_row_html("proj", _item("proj-a", status="resolved", corrected=True))
    assert "corrected" in row


def test_item_row_omits_the_corrected_badge_when_the_item_has_no_erratum():
    row = B._item_row_html("proj", _item("proj-a", status="resolved", corrected=False))
    assert "corrected" not in row


# --------------------------------------------------------------------- status tabs


def test_status_tabs_render_all_seven_with_real_counts():
    counts = {
        "all": 5,
        "ready": 2,
        "held": 1,
        "blocked": 0,
        "deferred": 0,
        "intake": 1,
        "resolved": 1,
    }
    html = B._status_tabs_html("proj", "all", counts)
    assert 'class="status-tabs"' in html
    for label in ("All", "Ready", "Held", "Blocked", "Deferred", "Intake", "Resolved"):
        assert f">{label}" in html or f"{label} " in html
    assert '<span style="opacity:.7">2</span>' in html


def test_status_tabs_marks_the_active_one():
    counts: dict[str, int] = dict.fromkeys(
        ("all", "ready", "held", "blocked", "deferred", "intake", "resolved"), 0
    )
    html = B._status_tabs_html("proj", "blocked", counts)
    assert 'class="status-tab tab-blocked is-active"' in html


def test_status_tab_counts_zero_for_impaired_summary():
    summary = A.ProjectSummary(name="proj", status="broken")
    counts = B._status_tab_counts(summary)
    assert all(v == 0 for v in counts.values())


# --------------------------------------------------------------------- agent panel rows


def test_agent_panel_groups_by_agent_stalest_first():
    rows = [
        {
            "agent": "alice",
            "item_id": "proj-a",
            "stale": True,
            "seconds_over_ttl_if_stale": 100.0,
            "held_seconds_or_last_renewal_age": None,
        },
        {
            "agent": "alice",
            "item_id": "proj-b",
            "stale": False,
            "seconds_over_ttl_if_stale": None,
            "held_seconds_or_last_renewal_age": 30.0,
        },
        {
            "agent": "bob",
            "item_id": "proj-c",
            "stale": False,
            "seconds_over_ttl_if_stale": None,
            "held_seconds_or_last_renewal_age": 60.0,
        },
    ]
    panel_rows = B._agent_panel_rows("proj", rows)
    by_agent = {r["agent_id"]: r for r in panel_rows}
    assert by_agent["alice"]["held_count"] == 2
    assert by_agent["alice"]["recent_kind"] == "stalest"
    assert by_agent["alice"]["is_stale"] is True
    assert by_agent["bob"]["held_count"] == 1
    assert by_agent["bob"]["recent_kind"] == "latest"


# --------------------------------------------------------------------- ready-age histogram


def test_ready_age_histogram_data_flags_the_7_plus_bucket():
    summary = A.ProjectSummary(
        name="proj", status="ok", ready=5, ready_age_buckets={"0-1": 2, "2-3": 1, "4-6": 0, "7+": 2}
    )
    data = B._ready_age_histogram_data(summary, reopened=1, window="7d")
    assert data["ready_total"] == 5
    labels = [b["label"] for b in data["buckets"]]
    assert labels == ["0-1d", "2-3d", "4-6d", "7+d"]
    watch = [b for b in data["buckets"] if b["is_watch"]]
    assert len(watch) == 1
    assert watch[0]["count"] == 2
    flagged_note = data.get("flagged_note", "")
    # Copy trimmed to one short middle-dot-joined line (visual-polish
    # punchlist item 11) -- was "7+ day bucket flagged -- N items aging
    # past the point they'd surface in the global attention queue.
    # Reopened after resolve, {window}: N."
    assert "aging 7+d" in flagged_note
    assert "1 reopened after resolve (7d)" in flagged_note


def test_ready_age_histogram_omits_flag_note_when_nothing_aging():
    summary = A.ProjectSummary(
        name="proj", status="ok", ready=3, ready_age_buckets={"0-1": 3, "2-3": 0, "4-6": 0, "7+": 0}
    )
    data = B._ready_age_histogram_data(summary, reopened=0, window="7d")
    flagged_note = data.get("flagged_note", "")
    assert "aging 7+d" not in flagged_note
    assert "0 reopened after resolve (7d)" in flagged_note
