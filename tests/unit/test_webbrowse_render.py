"""Tier 1 (pure, no bd/dolt) tests for the split-pane browse view render
helpers in ``amplifier_work_tracker.webbrowse``.

These construct ``adapter.Item`` values directly and call the module-level
render helpers -- no adapter/bd calls, no fixtures, no ``integration`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import webbrowse as B


def _item(item_id: str = "proj-abcd", **over: object) -> A.Item:
    """Build an ``A.Item`` with sensible defaults; any field can be overridden
    by keyword. Overrides are applied via ``setattr`` (the dataclass is
    mutable) so this stays type-clean without a `**dict` spread."""
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


# --------------------------------------------------------------------------- rows / list


def test_row_links_to_browse_selection_and_strips_project_prefix():
    row = B._row_html("proj", _item("proj-abcd", title="Do the thing"), selected=False)
    # selection navigates to the browse route with ?item=<full id> (not the item page)
    assert 'href="/projects/proj/browse?item=proj-abcd"' in row
    # the redundant "proj-" prefix is stripped from the shown id, full id kept in title=
    assert ">abcd<" in row
    assert 'title="proj-abcd"' in row
    assert "Do the thing" in row
    # a searchable key is present for a future client filter
    assert 'data-t="proj-abcd do the thing open ' in row
    # NOT selected -> no selected class / aria-current
    assert "wtb-row selected" not in row
    assert "aria-current" not in row


def test_selected_row_carries_selection_affordance():
    row = B._row_html("proj", _item("proj-abcd"), selected=True)
    assert "wtb-row selected" in row
    assert 'aria-current="true"' in row


def test_row_status_glyph_is_shape_not_color_only():
    # Two different statuses must render two different glyphs (shape-encoded
    # state), so state is never conveyed by color alone.
    open_row = B._row_html("proj", _item("proj-a", status="open"), selected=False)
    blocked_row = B._row_html("proj", _item("proj-b", status="blocked"), selected=False)
    assert "stico" in open_row and "stico" in blocked_row
    assert open_row != blocked_row


def test_row_age_escalates_to_amber_only_for_a_genuinely_ready_stale_item():
    """v3 firewall polish: this row's own Age column is the item-table
    Age column's live replacement (`_item_row`/.tbl is dead code) --
    amber-as-neglect must render for a genuinely ready/unclaimed item
    whose age crosses the alarm threshold, exactly like the old gated
    `_item_row` did."""
    old = datetime.now(UTC) - timedelta(days=10)
    row = B._row_html("proj", _item("proj-a", status="open", created_at=old), selected=False)
    assert 'class="age a3"' in row


@pytest.mark.parametrize("status", ["held", "blocked", "deferred", "resolved"])
def test_row_age_never_escalates_to_amber_for_a_non_ready_status(status):
    """A held/blocked/deferred/resolved item's row age is a calm fact,
    never an alarm -- even when it is just as old as a neglected ready
    item would be."""
    old = datetime.now(UTC) - timedelta(days=10)
    row = B._row_html("proj", _item("proj-a", status=status, created_at=old), selected=False)
    assert 'class="age a2"' in row
    assert "a3" not in row


def test_list_renders_one_row_per_item():
    items = [_item("proj-a", title="A"), _item("proj-b", title="B"), _item("proj-c", title="C")]
    html = B.render_list_html("proj", items, selected_id="proj-b")
    assert html.count("wtb-row") >= 3
    assert "A" in html and "B" in html and "C" in html
    # exactly the selected id row is marked selected
    assert html.count("wtb-row selected") == 1
    assert "?item=proj-b" in html


def test_empty_list_is_graceful():
    html = B.render_list_html("proj", [], selected_id=None)
    assert "No work items" in html
    assert "wtb-row" not in html


# --------------------------------------------------------------------------- detail pane


def test_detail_empty_state_prompts_selection():
    html = B.render_detail_html("proj", None, [])
    assert "Select a work item" in html
    assert "wtb-empty" in html


def test_detail_not_found_is_graceful():
    html = B.render_detail_html("proj", None, [], detail_error="proj-ghost")
    assert "proj-ghost" in html
    assert "could not be found" in html


def test_detail_renders_fields_state_and_open_link():
    item = _item(
        "proj-abcd",
        title="Fix the widget",
        status="held",
        holder="agent:alice",
        description="A **bold** description.",
        acceptance="Given X when Y then Z.",
        design="Some design notes.",
    )
    html = B.render_detail_html("proj", item, [])
    assert "Fix the widget" in html
    assert "proj-abcd" in html
    # status badge present (the app's own state-badge markup)
    assert "st-" in html
    # read-only facts + content blocks reused from webapp helpers
    assert "Description" in html and "Acceptance criteria" in html and "Design notes" in html
    assert "content-block" in html
    # markdown-lite from the reused helper turned **bold** into <strong>
    assert "<strong>bold</strong>" in html
    # canonical editable item page is reachable
    assert 'href="/projects/proj/items/proj-abcd"' in html
    # read-only: this pane ships NO edit form/inputs (auto-refresh-safe)
    assert "<form" not in html
    assert "<textarea" not in html


def test_detail_resolution_only_when_resolved():
    resolved = _item(
        "proj-r",
        status="resolved",
        resolution="Fixed by doing the thing.",
        closed_at=datetime(2026, 8, 3, 9, 0, tzinfo=UTC),
    )
    html = B.render_detail_html("proj", resolved, [])
    assert "Fixed by doing the thing." in html
    assert "Resolved" in html  # timestamp row appears for a resolved item

    open_item = _item("proj-o", status="open")
    assert "Resolution" not in B.render_detail_html("proj", open_item, [])


# --------------------------------------------------------------------------- full body / js / css


def test_body_has_stable_scroll_container_ids():
    items = [_item("proj-a")]
    body = B.render_browse_body("proj", items, None, [])
    # browse_js keys scroll preservation + detail swap on these exact ids
    assert 'id="browse-list"' in body
    assert 'id="browse-detail"' in body
    assert "<style>" in body
    # both panes present
    assert "wtb-list" in body and "wtb-detail" in body


def test_body_flash_is_passed_through():
    body = B.render_browse_body("proj", [], None, [], flash_html='<div class="flash">hi</div>')
    assert '<div class="flash">hi</div>' in body


def test_browse_js_preserves_scroll_and_selects_client_side():
    js = B.browse_js()
    # window-scoped scroll state survives the auto-refresh body swap
    assert "__wtBrowseListScroll" in js
    assert "__wtBrowseDetailScroll" in js
    assert "__wtBrowseWinScroll" in js
    # client-side selection swaps only the detail pane and updates the URL
    assert "browse-detail" in js
    assert "replaceState" in js
    assert "fetch(" in js


def test_css_uses_selection_token_not_a_status_hue():
    css = B._BROWSE_CSS
    # selection = cyan wash via the shared token, never a raw status color
    assert "var(--glass-fill-row-selected)" in css
    # the firewall's reserved status hues are never hardcoded here
    for status_hex in ("#f59e0b", "#ef4444", "#92400e", "#991b1b"):
        assert status_hex not in css
    # glass lives on chrome; the selected-row rim uses the brand gradient token
    assert "var(--brand-gradient-rim)" in css
    # responsive: a narrow-width breakpoint exists (430px must be exercised)
    assert "max-width:860px" in css
