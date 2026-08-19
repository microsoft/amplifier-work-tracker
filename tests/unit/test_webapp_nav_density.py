"""Tier 1 -- pure-function tests for the nav/density lane: the sidebar's
per-project counts/roll-up/alarm-marker/current-highlight
(`_sidebar_open_total`/`_sidebar_alarm_class`/`_sidebar_html`), the search
field's printed shortcut hint (`webtheme.search_field`), and the density
toggle / keyboard-nav script surface (`webtheme.density_toggle_html` /
`webtheme.list_controls_js`).

No bd, no dolt, no network: everything here is a pure function of
constructed `ProjectSummary` values or plain strings.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webapp as W  # noqa: E402
from amplifier_work_tracker import webtheme as T  # noqa: E402


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


# ------------------------------------------------------- _sidebar_open_total


def test_sidebar_open_total_is_total_minus_resolved():
    s = _summary("proj", total=10, resolved=3)
    assert W._sidebar_open_total(s) == (7, 10)  # noqa: SLF001


def test_sidebar_open_total_none_for_broken_project():
    s = A.ProjectSummary(name="broken", status=A.STATUS_BROKEN)
    assert W._sidebar_open_total(s) is None  # noqa: SLF001


def test_sidebar_open_total_none_for_missing_summary():
    assert W._sidebar_open_total(None) is None  # noqa: SLF001


def test_sidebar_open_total_never_goes_negative():
    """A pathological summary (resolved > total, shouldn't happen but must
    never surface as a negative open count)."""
    s = _summary("proj", total=2, resolved=5)
    result = W._sidebar_open_total(s)  # noqa: SLF001
    assert result is not None
    open_n, total_n = result
    assert open_n == 0
    assert total_n == 2


def test_sidebar_open_total_none_fields_become_zero():
    s = _summary("proj", total=None, resolved=None)
    assert W._sidebar_open_total(s) == (0, 0)  # noqa: SLF001


# ------------------------------------------------------- _sidebar_alarm_class


def test_sidebar_alarm_class_blank_when_calm():
    s = _summary("proj", held=0, blocked=0)
    assert W._sidebar_alarm_class(s) == ""  # noqa: SLF001


def test_sidebar_alarm_class_amber_when_held():
    s = _summary("proj", held=1, blocked=0)
    assert W._sidebar_alarm_class(s) == " alarm-am"  # noqa: SLF001


def test_sidebar_alarm_class_crimson_when_blocked():
    s = _summary("proj", held=0, blocked=1)
    assert W._sidebar_alarm_class(s) == " alarm-cr"  # noqa: SLF001


def test_sidebar_alarm_class_blocked_outranks_held():
    """Same escalation ordering as `_TAB_ALARM_CLASS`/`_dashboard_row`."""
    s = _summary("proj", held=3, blocked=1)
    assert W._sidebar_alarm_class(s) == " alarm-cr"  # noqa: SLF001


def test_sidebar_alarm_class_blank_for_broken_project():
    """A broken project has no real held/blocked counts to alarm on --
    handled by `impaired_banner` elsewhere, not a sidebar alarm dot."""
    s = A.ProjectSummary(name="broken", status=A.STATUS_BROKEN, held=99, blocked=99)
    assert W._sidebar_alarm_class(s) == ""  # noqa: SLF001


def test_sidebar_alarm_class_blank_for_missing_summary():
    assert W._sidebar_alarm_class(None) == ""  # noqa: SLF001


# -------------------------------------------------------------- _sidebar_html


def test_sidebar_html_lists_every_project_alphabetically():
    names = ["zeta", "alpha", "mid"]
    summaries = [_summary(n, total=1) for n in names]
    html = W._sidebar_html(names, summaries, None)  # noqa: SLF001
    assert html.index(">alpha<") < html.index(">mid<") < html.index(">zeta<")


def test_sidebar_html_rollup_shows_real_summed_open_total():
    """Never a fabricated number -- the sum of each readable project's own
    (total - resolved), never a re-derived count."""
    summaries = [
        _summary("a", total=10, resolved=4),  # open 6
        _summary("b", total=5, resolved=5),  # open 0
    ]
    html = W._sidebar_html(["a", "b"], summaries, None)  # noqa: SLF001
    assert "<b>6</b> open" in html


def test_sidebar_html_rollup_excludes_broken_projects_from_the_total():
    summaries = [
        _summary("a", total=10, resolved=0),  # open 10
        A.ProjectSummary(name="b", status=A.STATUS_BROKEN),
    ]
    html = W._sidebar_html(["a", "b"], summaries, None)  # noqa: SLF001
    assert "<b>10</b> open" in html


def test_sidebar_html_shows_open_over_total_badge_per_row():
    summaries = [_summary("proj", total=32, resolved=2)]
    html = W._sidebar_html(["proj"], summaries, None)  # noqa: SLF001
    # The badge stays the compact open/total a scan wants; the denominator is
    # spelled out on hover so it can never be misread as another count.
    assert ">30/32</span>" in html
    assert 'title="30 open of 32 items"' in html


def test_sidebar_html_broken_project_badge_is_an_honest_dash():
    summaries = [A.ProjectSummary(name="broken", status=A.STATUS_BROKEN)]
    html = W._sidebar_html(["broken"], summaries, None)  # noqa: SLF001
    assert ">\u2014</span>" in html
    assert 'title="counts unavailable"' in html


def test_sidebar_html_marks_current_project_row_not_the_rollup():
    summaries = [_summary("a", total=1), _summary("b", total=1)]
    html = W._sidebar_html(["a", "b"], summaries, "b")  # noqa: SLF001
    assert 'class="sb-row current"' in html or "current" in html
    # exactly one aria-current="page" on a project row, none on the rollup
    assert 'href="/projects/b" aria-current="page"' in html
    assert 'href="/" aria-current="page"' not in html


def test_sidebar_html_marks_rollup_current_on_the_dashboard():
    summaries = [_summary("a", total=1)]
    html = W._sidebar_html(["a"], summaries, None)  # noqa: SLF001
    assert 'href="/" aria-current="page"' in html
    assert 'href="/projects/a" aria-current="page"' not in html


def test_sidebar_html_alarm_marker_reaches_the_row_class():
    summaries = [_summary("a", held=2, blocked=0)]
    html = W._sidebar_html(["a"], summaries, None)  # noqa: SLF001
    assert "alarm-am" in html


def test_sidebar_html_calm_project_carries_no_alarm_class():
    summaries = [_summary("a", held=0, blocked=0)]
    html = W._sidebar_html(["a"], summaries, None)  # noqa: SLF001
    assert "alarm-am" not in html
    assert "alarm-cr" not in html


def test_sidebar_html_empty_workspace_renders_a_zero_rollup_and_no_rows():
    html = W._sidebar_html([], [], None)  # noqa: SLF001
    assert "<b>0</b> open" in html
    assert '<ul class="sb-list"></ul>' in html


def test_sidebar_html_escapes_project_names():
    summaries = [_summary("<script>", total=1)]
    html = W._sidebar_html(["<script>"], summaries, None)  # noqa: SLF001
    assert "<script>proj" not in html
    assert "&lt;script&gt;" in html


def test_sidebar_html_includes_the_narrow_width_checkbox_toggle():
    """The collapse mechanism is pure CSS/HTML -- a checkbox + label pair,
    no JS required (see webtheme.py's `.sidebar` media query)."""
    html = W._sidebar_html(["a"], [_summary("a", total=1)], None)  # noqa: SLF001
    assert 'id="sb-toggle"' in html
    assert 'for="sb-toggle"' in html


# --------------------------------------------------- search_field (webtheme)


def test_search_field_shows_a_slash_shortcut_hint_by_default():
    """v3 fidelity pass (goal wtv3/components, B10): a real `<kbd>` element,
    ported from the approved gallery's own `.search-input kbd`."""
    html = T.search_field("Filter queues by name or state")
    assert "<kbd>/</kbd>" in html


def test_search_field_aria_label_never_carries_the_shortcut_hint():
    """The printed hint is a sighted-user affordance; the accessible name
    stays the plain hint text -- no 'slash' noise for a screen reader."""
    html = T.search_field("Filter queues by name or state")
    assert 'aria-label="Filter queues by name or state"' in html


def test_search_field_shortcut_can_be_suppressed():
    html = T.search_field("Filter queues by name or state", shortcut="")
    assert "hint-key" not in html


# ------------------------------------------------- density_toggle_html/js


def test_density_toggle_html_default_is_unpressed():
    html = T.density_toggle_html()
    assert 'id="density-toggle"' in html
    assert 'aria-pressed="false"' in html
    assert 'type="button"' in html  # must never submit the search form it sits in


def test_list_controls_js_uses_the_dedicated_localstorage_key():
    js = T.list_controls_js()
    assert "wt-density" in js


def test_list_controls_js_has_its_own_dedicated_bind_once_guard():
    """A distinct flag from `auto_refresh_js`'s `__wtAutoRefreshStarted` and
    `search_js`'s `__wtSearchShortcutBound` -- this script's row-nav
    listener must survive an auto-refresh tick without double-binding."""
    js = T.list_controls_js()
    assert "window.__wtKeyNavBound" in js


def test_list_controls_js_guards_row_nav_keys_against_focused_fields():
    js = T.list_controls_js()
    assert "INPUT" in js
    assert "TEXTAREA" in js
    assert "SELECT" in js


def test_list_controls_js_respects_reduced_motion_for_scrolling():
    js = T.list_controls_js()
    assert "prefers-reduced-motion" in js


def test_list_controls_js_targets_the_shared_row_selector():
    """One selector for both the project item table and the dashboard
    queue table -- both render rows as `tr[data-t]`."""
    js = T.list_controls_js()
    assert "table.tbl tbody tr[data-t]" in js
