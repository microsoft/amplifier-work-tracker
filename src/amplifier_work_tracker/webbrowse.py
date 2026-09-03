"""wt-v4 "Observatory" L1 (Project Observatory) and L2 (Item Detail) --
see `.amplifier/design-gauntlet/wt-v4-observatory/{mock-L1-project,
mock-L2-item}.html` for the approved mockups these routes match, and
`GAUNTLET-SYNTHESIS.md` for the build-phase requirements list.

This module OWNS the `/projects/{name}` and `/projects/{name}/items/{item_id}`
GET routes (mounted by `register`, called from `webapp.create_app` AFTER
every OTHER route is registered -- see that function's own call site). It
reuses `webapp.py`/`webtheme.py`/`adapter.py`/`widgets.py`/`chartsvg.py` by
IMPORT and never edits them (`webapp.py`'s own mutation/POST routes --
add/update/resolve/rename/remove -- are untouched and still live there).

Retired: the v3 split-pane BROWSE view (`/projects/{name}/browse`, and its
supporting `_row_html`/`render_list_html`/`render_detail_html`/
`render_browse_body`/`browse_js`) is superseded by this module's own L1
items list + L2 detail page -- the OLD route now REDIRECTS (302) to its L1/
L2 equivalent rather than 404ing (see `register`'s `browse_redirect`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import chartsvg as CH
from amplifier_work_tracker import webtheme as T
from amplifier_work_tracker import widgets as WD
from amplifier_work_tracker.webapp import (
    _AUTO_REFRESH_MS,
    _OBSERVATORY_THEME_JS,
    _activity_feed_html,
    _agent_freshness_label,
    _compound_duration,
    _crumb,
    _dependency_sections_html,
    _esc,
    _flash,
    _identity,
    _item_age_html,
    _item_facts_kv_html,
    _item_held_chip_html,
    _item_time_kv_html,
    _not_found_body,
    _observatory_help_and_theme_html,
    _observatory_icon_sprite_html,
    _observatory_nav_extras_html,
    _page,
    _pluralize,
    _priority_bar_html,
    _public_error_message,
    _relative_time,
    _short_item_id,
    _velocity_chart_shell_html,
    _window_days,
)

#: Python 3.11 forbids a backslash escape (`"\u2014"`) inside an f-string's
#: `{...}` expression part (that syntax needs 3.12) -- a real constraint of
#: this repo's supported interpreter, not a style choice. Every "no real
#: value, show an honest dash" spot inside an f-string template below uses
#: this pre-built constant instead of an inline escaped literal.
_EM_DASH = "\u2014"

# ---------------------------------------------------------------------------
# status tabs -- real `?status=` links (GAUNTLET-SYNTHESIS.md item 6), never
# client-side JS state. Order matches the mockup's own tab row and the
# donut/legend's fixed status order.
# ---------------------------------------------------------------------------

_STATUS_TABS: tuple[tuple[str, str], ...] = (
    ("all", "All"),
    ("ready", "Ready"),
    ("held", "Held"),
    ("blocked", "Blocked"),
    ("deferred", "Deferred"),
    ("intake", "Intake"),
    ("resolved", "Resolved"),
)

# Our domain status value each tab's `?status=` should filter `bd.list` by --
# "all"/"ready"/"intake" don't map onto a single raw bd status the way
# held/blocked/deferred/resolved do (see `adapter._STATUS_MAP_REVERSE`):
# "ready"/"intake" are both bd's raw `open` status, distinguished only by
# lane tag, and "all" means no filter at all.
_TAB_STATUS_FILTER: dict[str, str | None] = {
    "all": None,
    "ready": "open",
    "held": "held",
    "blocked": "blocked",
    "deferred": "deferred",
    "intake": "open",
    "resolved": "resolved",
}


def _status_tab_counts(summary: A.ProjectSummary) -> dict[str, int]:
    if summary.status != A.STATUS_OK:
        return dict.fromkeys((k for k, _ in _STATUS_TABS), 0)
    return {
        "all": summary.total or 0,
        "ready": summary.ready or 0,
        "held": summary.held or 0,
        "blocked": summary.blocked or 0,
        "deferred": summary.deferred or 0,
        "intake": summary.intake or 0,
        "resolved": summary.resolved or 0,
    }


def _status_tabs_html(name: str, status: str, counts: dict[str, int]) -> str:
    tabs = []
    for key, label in _STATUS_TABS:
        active = " is-active" if key == status else ""
        blocked_cls = " tab-blocked" if key == "blocked" else ""
        dot = '<span class="dot"></span> ' if key == "blocked" else ""
        title = (
            ' title="Newly filed, not yet triaged into ready or deferred"'
            if key == "intake"
            else ""
        )
        tabs.append(
            f'<a href="/projects/{quote(name)}?status={quote(key)}" '
            f'class="status-tab{blocked_cls}{active}"{title}>{dot}{_esc(label)} '
            f'<span style="opacity:.7">{counts.get(key, 0)}</span></a>'
        )
    return f'<div class="status-tabs">{"".join(tabs)}</div>'


# ---------------------------------------------------------------------------
# items list -- L1's own `.item-row` grid (status chip, priority chip,
# name+id, holder, age, chevron) -- links straight to L2, no split-pane
# selection state.
# ---------------------------------------------------------------------------

_ITEM_STATUS_CHIP_CLASS: dict[str, str] = {
    "open": "st-ready",
    "held": "st-held",
    "blocked": "st-blocked",
    "deferred": "st-deferred",
    "resolved": "st-resolved",
}
_ITEM_STATUS_CHIP_LABEL: dict[str, str] = {
    "open": "READY",
    "held": "HELD",
    "blocked": "BLOCKED",
    "deferred": "DEFERRED",
    "resolved": "RESOLVED",
}


def _item_row_html(name: str, item: A.Item) -> str:
    status_cls = _ITEM_STATUS_CHIP_CLASS.get(item.status, "st-ready")
    status_label = _ITEM_STATUS_CHIP_LABEL.get(item.status, item.status.upper())
    priority_chip = _priority_bar_html(item.priority)
    short_id = _short_item_id(name, item.id)
    holder_html = "unclaimed"
    if item.status == "held" and item.holder:
        holder_html = _esc(item.holder)
    elif item.status == "blocked":
        active = [b for b in item.links if b.get("type") == "blocks" and b.get("blocking")]
        holder_html = f"blocked by {_esc(active[0]['id'])}" if active else "blocked, no owner"
    elif item.holder:
        holder_html = _esc(item.holder)
    else:
        holder_html = "\u2014"
    now = datetime.now(UTC)
    basis = {"open": item.created_at, "held": item.updated_at, "resolved": item.closed_at}.get(
        item.status, item.updated_at
    )
    age_label = _compound_duration((now - basis).total_seconds()) if basis else "\u2014"
    href = f"/projects/{quote(name)}/items/{quote(item.id)}"
    # A resolved item whose record carries at least one erratum (see
    # `Beads.erratum`) -- the resolution stands, but a reader must know
    # not to take it at pure face value without checking the detail page.
    corrected_chip = (
        '<span class="chip" title="resolution corrected via erratum -- see detail">corrected</span>'
        if item.corrected
        else ""
    )
    return (
        f'<a href="{_esc(href)}" class="item-row">'
        f'<span class="status-chip {status_cls}">{_esc(status_label)}</span>'
        f"{priority_chip}"
        f'<span class="name"><span class="id">{_esc(short_id)}</span>{_esc(item.title)}'
        f"{corrected_chip}</span>"
        f'<span class="holder">{holder_html}</span>'
        f'<span class="age">{_esc(age_label)}</span>'
        '<span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span>'
        "</a>"
    )


# ---------------------------------------------------------------------------
# agents panel -- group `A.project_agents`' one-row-per-held-item rows by
# agent (that function is already sorted stale-first-then-freshness, so the
# FIRST row seen for a given agent is either its stalest hold or -- if it
# has no stale hold at all -- its freshest).
# ---------------------------------------------------------------------------


def _agent_panel_rows(name: str, rows: list[dict]) -> list[WD.AgentPanelRow]:
    held_counts: dict[str, int] = {}
    first_row: dict[str, dict] = {}
    for r in rows:
        agent = r["agent"]
        held_counts[agent] = held_counts.get(agent, 0) + 1
        first_row.setdefault(agent, r)
    out: list[WD.AgentPanelRow] = []
    for agent, r in first_row.items():
        out.append(
            WD.AgentPanelRow(
                agent_id=agent,
                held_count=held_counts[agent],
                recent_kind="stalest" if r["stale"] else "latest",
                recent_item_id=_short_item_id(name, r["item_id"]),
                freshness_label=_agent_freshness_label(r),
                is_stale=r["stale"],
                href=f"/projects/{quote(name)}/items/{quote(r['item_id'])}",
            )
        )
    return out


# ---------------------------------------------------------------------------
# ready-age histogram
# ---------------------------------------------------------------------------

_READY_AGE_LABELS: dict[str, str] = {"0-1": "0-1d", "2-3": "2-3d", "4-6": "4-6d", "7+": "7+d"}


def _ready_age_histogram_data(
    summary: A.ProjectSummary, reopened: int, window: str
) -> WD.ReadyAgeHistogramData:
    buckets_raw = summary.ready_age_buckets or {}
    buckets = [
        CH.AgeBucket(label=label, count=buckets_raw.get(key, 0), is_watch=(key == "7+"))
        for key, label in _READY_AGE_LABELS.items()
    ]
    ready_total = summary.ready or 0
    aging = buckets_raw.get("7+", 0)
    # Copy trimmed to ONE short line (visual-polish punchlist item 11): the
    # prior two full sentences ("7+ day bucket flagged -- N items aging
    # past the point they'd surface in the global attention queue.
    # Reopened after resolve, {window}: N.") read as a dense paragraph
    # under the chart. A middle-dot-joined clause pair keeps both real
    # signals (aging count, reopened-after-resolve count) without the
    # verbose framing -- the "aging" concept is already explained by the
    # watch-tier legend line directly above this note.
    parts = []
    if aging:
        parts.append(f"{_pluralize(aging, 'item')} aging 7+d")
    parts.append(f"{reopened} reopened after resolve ({window})")
    return WD.ReadyAgeHistogramData(
        buckets=buckets,
        ready_total=ready_total,
        aria_label=f"Ready item age histogram, {len(buckets)} buckets",
        flagged_note=" \u00b7 ".join(parts) + ".",
    )


def register(app: FastAPI, workspace: A.Workspace) -> None:
    """Mount L1 (`/projects/{name}`) and L2
    (`/projects/{name}/items/{item_id}`) onto an existing FastAPI app, plus
    a redirect for the retired `/projects/{name}/browse` split-pane view.
    Matches `webapp.create_app`'s idiom exactly: handlers close over
    `workspace`. Called ONCE, at the end of `create_app`, AFTER every other
    route -- this is what lets these two paths win the route match (no
    other handler in `webapp.py` registers them anymore)."""

    @app.get("/projects/{name}/browse", response_class=HTMLResponse)
    async def browse_redirect(request: Request, name: str):  # type: ignore[no-untyped-def]
        """The retired v3 split-pane view. `?item=` (its own selection
        param) redirects straight to that item's L2 page; otherwise to L1."""
        item = request.query_params.get("item")
        if item:
            return RedirectResponse(
                url=f"/projects/{quote(name)}/items/{quote(item)}", status_code=302
            )
        return RedirectResponse(url=f"/projects/{quote(name)}", status_code=302)

    # ----------------------------------------------------------- L1: project

    @app.get("/projects/{name}", response_class=HTMLResponse)
    async def project_view(request: Request, name: str):  # type: ignore[no-untyped-def]
        try:
            bd = workspace.project(name)
        except A.BeadsError:
            return _page(
                request,
                name,
                _not_found_body(heading=name, back_href="/", back_label="Mission Control"),
                crumb_html=_crumb(("/", "Mission Control")),
                body_class="wt-observatory",
                extra_nav_html=_observatory_help_and_theme_html(),
            )

        summary = A.project_summary(workspace, name)
        crumb = _crumb(("/", "Mission Control"), ("", name))
        if summary.status != A.STATUS_OK:
            heading = {
                A.STATUS_CREATING: "This project is still being created.",
                A.STATUS_BROKEN: "This project's creation never finished.",
            }.get(summary.status, summary.status)
            if A.is_unavailable_status(summary.status):
                # Say what is actually known: the read did not arrive. The
                # bare status text alone reads like a verdict on the project.
                heading = (
                    "This project's database could not be reached just now "
                    f"\u2014 its data is unknown, not broken. {summary.status}"
                )
            body = (
                f"{_observatory_icon_sprite_html()}"
                '<div class="container">'
                f"{_flash(request)}"
                f'<div class="glass-panel strong hero is-alarm"><div class="verdict">'
                f'<span class="icon"><svg><use href="#i-alert-triangle"/></svg></span> '
                f"{_esc(heading)}</div></div></div>"
            )
            return _page(
                request,
                name,
                body,
                crumb_html=crumb,
                body_class="wt-observatory",
                extra_nav_html=_observatory_help_and_theme_html(),
                nav_project=name,
            )

        window, days = _window_days(request.query_params.get("window"))
        status = request.query_params.get("status") or "all"
        q = (request.query_params.get("q") or "").strip()

        try:
            status_filter = _TAB_STATUS_FILTER.get(status)
            all_matching = bd.list(status=status_filter, include_resolved=True, limit=0)
            if status == "ready":
                all_matching = [i for i in all_matching if A.LANE_WORK in i.tags]
            elif status == "intake":
                all_matching = [i for i in all_matching if A.LANE_INTAKE in i.tags]
        except A.BeadsError as e:
            body = (
                f"{_flash(request)}<h1>{_esc(name)}</h1>"
                f'<div class="flash flash-error">{_esc(_public_error_message(e))}</div>'
            )
            return _page(request, name, body, crumb_html=crumb, nav_project=name)

        if q:
            needle = q.lower()
            all_matching = [
                i
                for i in all_matching
                if needle in f"{i.id} {i.title} {i.status} {i.holder or ''}".lower()
            ]
        all_matching.sort(key=lambda i: i.updated_at or i.created_at or datetime.min, reverse=True)
        page_size = A.LIST_DEFAULT_LIMIT
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        total_pages = max(1, -(-len(all_matching) // page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        shown = all_matching[offset : offset + page_size]

        agent_rows_raw = A.project_agents(name)
        agents_active_count = len({r["agent"] for r in agent_rows_raw})

        velocity_days = A.velocity_series(name, days=days)
        velocity_windows_data = A.velocity_windows(name, days=days)
        reopened = A.reopened_count(name, days=days)

        # NOT `summary.held_stale`: `project_summary`'s items come from
        # `_summary_items_via_sql`, whose own column projection
        # (`_SUMMARY_ITEM_COLUMNS`) never selects `metadata` -- so
        # `held_stale` always reads every held item as stale (no custody
        # record found), regardless of real freshness. `agent_rows_raw`
        # (`A.project_agents`, already fetched above for the agents panel)
        # reads via `_list_rows_via_sql`, which DOES select `metadata`, so
        # its own `stale` flag (`custody.reclaim_eligible` against the
        # REAL record) is the trustworthy source for this count.
        stale_count = sum(1 for r in agent_rows_raw if r["stale"])
        blocked_count = summary.blocked or 0
        aging_count = (summary.ready_age_buckets or {}).get("7+", 0)
        reasons: list[str] = []
        if stale_count:
            reasons.append(f"{_pluralize(stale_count, 'claim')} sitting past custody TTL")
        if blocked_count:
            reasons.append(f"{_pluralize(blocked_count, 'item')} blocked")
        if aging_count:
            reasons.append(f"{_pluralize(aging_count, 'ready item')} aging past 6 days")

        cur = velocity_windows_data["current"]
        verdict = WD.verdict_line(
            WD.VerdictLineData(
                scope="project",
                attention_count=stale_count + blocked_count + aging_count,
                reasons=reasons,
                agents_active=agents_active_count,
                resolved_count=cur["resolved"],
                resolved_period_label=window,
                created_count=cur["created"],
            )
        )
        oldest_ready_label = (
            f"{int((summary.oldest_unclaimed_age_seconds or 0) // 86400)}d"
            if summary.oldest_unclaimed_age_seconds is not None
            else "\u2014"
        )
        hero_html = WD.render_verdict_hero(
            WD.VerdictHeroData(
                state=verdict["state"],
                eyebrow=f"Project verdict \u00b7 {name}",
                headline=verdict["headline"],
                detail_html=verdict["detail_html"],
                meta_row=[
                    WD.MetaCell(k="Total items", v=str(summary.total or 0)),
                    WD.MetaCell(k="Resolved 24h", v=str(summary.resolved_24h or 0)),
                    WD.MetaCell(k="Oldest ready", v=oldest_ready_label),
                    WD.MetaCell(
                        k="Last activity",
                        v=_relative_time(summary.last_activity)
                        if summary.last_activity
                        else _EM_DASH,
                    ),
                ],
            )
        )

        status_donut_html = WD.render_status_breakdown(
            WD.StatusBreakdownData(
                counts=CH.StatusCounts(
                    resolved=summary.resolved or 0,
                    ready=summary.ready or 0,
                    held=summary.held or 0,
                    intake=summary.intake or 0,
                    deferred=summary.deferred or 0,
                    blocked=summary.blocked or 0,
                ),
                total=summary.total or 0,
                aria_label=f"Status mix donut, {summary.total or 0} total items",
            )
        )
        ready_age_html = WD.render_ready_age_histogram(
            _ready_age_histogram_data(summary, reopened, window)
        )
        velocity_html = _velocity_chart_shell_html(
            # Raw text, NOT pre-escaped: `_velocity_chart_shell_html` HTML-escapes
            # `title` itself (once) when it renders the `<h3>` -- pre-encoding the
            # "&" here as `&amp;` made that single escaping pass double-encode it
            # to `&amp;amp;` (DOM-measured defect: heading rendered literally as
            # "Velocity &amp; burn -- cortex"). One escaping layer, at the sink.
            title=f"Velocity & burn \u2014 {name}",
            base_href=f"/projects/{quote(name)}",
            window=window,
            days_data=velocity_days,
            windows=velocity_windows_data,
            reopened=reopened,
            aria_label=f"{name} resolved vs created per day, last {days} days",
        )
        agents_panel_html = WD.render_agents_panel(
            WD.AgentsPanelData(
                rows=_agent_panel_rows(name, agent_rows_raw),
                active_count=agents_active_count,
                held_count=summary.held or 0,
            )
        )

        items_html = "".join(_item_row_html(name, i) for i in shown)

        def _page_href(p: int) -> str:
            parts = [f"status={quote(status)}"]
            if q:
                parts.append(f"q={quote(q)}")
            parts.append(f"page={p}")
            return f"/projects/{quote(name)}?{'&'.join(parts)}"

        pagination_html = ""
        if total_pages > 1:
            links = []
            if page > 1:
                links.append(f'<a href="{_page_href(page - 1)}">&laquo; Prev</a>')
            links.append(f"Page {page} of {total_pages}")
            if page < total_pages:
                links.append(f'<a href="{_page_href(page + 1)}">Next &raquo;</a>')
            sep = " \u00b7 "
            pagination_html = f'<div class="pagination">{sep.join(links)}</div>'

        truncation = (
            f'<div class="truncation-note">Showing {len(shown)} of {len(all_matching)} items'
            f" \u00b7 filter or page for more</div>{pagination_html}"
            if len(all_matching) > len(shown) or pagination_html
            else ""
        )
        empty_html = (
            '<div class="empty-state" style="padding:2rem 0;text-align:center;'
            'color:var(--ink-tertiary)">No items match this filter.</div>'
            if not shown
            else ""
        )
        tabs_html = _status_tabs_html(name, status, _status_tab_counts(summary))
        search_value = f' value="{_esc(q)}"' if q else ""
        manage_html = f"""
        <details class="actions-drawer">
          <summary>
            <span class="icon"><svg><use href="#i-edit"/></svg></span>
            Manage project
            <span class="count">add item \u00b7 rename \u00b7 remove</span>
            <span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span>
          </summary>
          <div style="padding:0 var(--space-5) var(--space-5)">
            <form method="post" action="/projects/{quote(name)}/items" id="add-item">
              <label for="title">Title</label>
              <input type="text" id="title" name="title" required>
              <label for="description">Description</label>
              <textarea id="description" name="description" rows="2"></textarea>
              <label for="acceptance">Acceptance criteria</label>
              <textarea id="acceptance" name="acceptance" rows="2"></textarea>
              <button type="submit">Add</button>
            </form>
            <div style="margin-top:var(--space-5)">
              <button type="button" id="rename-trigger" class="btn danger"
                      aria-expanded="false" aria-controls="rename-form">Rename this
                project&hellip;</button>
              <form method="post" action="/projects/{quote(name)}/rename" id="rename-form"
                    style="margin-top:var(--space-3)" hidden>
                <label for="new_name">New project name</label>
                <input type="text" id="new_name" name="new_name" autocomplete="off"
                       pattern="[a-z][a-z0-9_]{{1,30}}" required placeholder="new_project_name">
                <div class="form-actions">
                  <button type="submit" class="btn danger">Save</button>
                  <button type="button" id="rename-cancel" class="btn secondary">Cancel</button>
                </div>
              </form>
              <script>{T.rename_disclosure_js()}</script>
              <a class="btn danger" href="/projects/{quote(name)}/remove"
                 style="margin-top:var(--space-3);display:inline-block">Remove this
                project&hellip;</a>
            </div>
          </div>
        </details>
        """

        body = f"""
        {_observatory_icon_sprite_html()}
        <div class="container">
        {_flash(request)}
        <div class="breadcrumb">{crumb}</div>
        <div class="section">{hero_html}</div>
        <div class="two-up section">
          <div class="glass-panel chart-card">
            <div class="chart-head"><h3>Status breakdown</h3></div>
            {status_donut_html}
          </div>
          <div class="glass-panel chart-card">
            <div class="chart-head"><h3>Ready-age</h3>
              <span class="note">{summary.ready or 0} ready items</span></div>
            {ready_age_html}
          </div>
        </div>
        <div class="two-up section">
          <div class="glass-panel chart-card">{velocity_html}</div>
          <div class="glass-panel chart-card">
            <div class="chart-head"><h3>Agents on {_esc(name)}</h3>
              <span class="note">{agents_active_count} active \u00b7 {summary.held or 0} held</span>
            </div>
            {agents_panel_html}
          </div>
        </div>
        <div class="section">
          <div class="section-title"><h2>Items</h2>
            <span class="note">{summary.total or 0} total</span></div>
          <div class="glass-panel chart-card">
            <div class="items-toolbar">
              {tabs_html}
              <form method="get" action="/projects/{quote(name)}" class="search-input"
                    style="min-width:180px;max-width:220px">
                <input type="hidden" name="status" value="{_esc(status)}">
                <span class="icon"><svg><use href="#i-search"/></svg></span>
                <input type="search" name="q" placeholder="Filter\u2026" aria-label="Filter items"
                       autocomplete="off"{search_value}>
              </form>
            </div>
            <div class="items-col-head"><span>Status</span><span>Pri</span><span>Item</span>
              <span>Holder</span><span>Age</span><span></span></div>
            {items_html}
            {empty_html}
            {truncation}
          </div>
        </div>
        <div class="section">{manage_html}</div>
        </div>
        """
        return _page(
            request,
            name,
            body,
            crumb_html=crumb,
            body_class="wt-observatory",
            extra_nav_html=_observatory_nav_extras_html(),
            js=_OBSERVATORY_THEME_JS,
            auto_refresh_ms=_AUTO_REFRESH_MS,
            nav_project=name,
        )

    # -------------------------------------------------------- L2: item detail

    @app.get("/projects/{name}/items/{item_id}", response_class=HTMLResponse)
    async def item_detail(request: Request, name: str, item_id: str):  # type: ignore[no-untyped-def]
        try:
            bd = workspace.project(name)
            item = bd.get(item_id, with_links=True)
        except A.BeadsError:
            return _page(
                request,
                item_id,
                _not_found_body(
                    heading=item_id, back_href=f"/projects/{name}", back_label=f"back to {name}"
                ),
                crumb_html=_crumb(("/", "Mission Control"), (f"/projects/{name}", name)),
                body_class="wt-observatory",
                extra_nav_html=_observatory_help_and_theme_html(),
                nav_project=name,
            )

        identity_val = _esc(_identity(request))

        try:
            activity_events = bd.activity(item.id)
        except A.BeadsError:
            activity_events = []
        activity_html = _activity_feed_html(activity_events)

        resolution_html = ""
        if item.status == "resolved" and item.resolution:
            # `item.corrected`/`item.errata` come from `bd.get(with_links=True)`
            # above (see `Beads.get`'s own errata-enrichment note) -- the
            # resolution TEXT is rendered completely unchanged; a correction
            # is an ADDITIONAL, clearly-marked block below it, never a
            # rewrite of what was actually published.
            corrected_badge = (
                '<span class="chip" style="margin-left:8px" '
                'title="the resolution below has been corrected -- see Errata">'
                "corrected</span>"
                if item.corrected
                else ""
            )
            errata_html = ""
            if item.errata:
                rows = "".join(
                    f'<div style="margin-top:6px"><span class="v mono">{_esc(e.at)}'
                    f' \u00b7 {_esc(e.by)}</span><div class="blink">{_esc(e.text)}</div></div>'
                    for e in item.errata
                )
                errata_html = (
                    '<div style="margin-top:var(--space-3)">'
                    '<div class="btitle">Errata</div>'
                    f"{rows}</div>"
                )
            resolution_html = (
                '<div class="blocker-banner resolved">'
                '<span class="icon"><svg><use href="#i-check-circle"/></svg></span>'
                f'<div><div class="btitle">Resolution{corrected_badge}</div>'
                f'<div class="blink">{_esc(item.resolution)}</div>'
                f"{errata_html}</div></div>"
            )

        links_html = _dependency_sections_html(name, item.links)
        # DOM-measured defect: the dependency-graph section only ever
        # appeared when `item.links` had something to say -- an item with
        # no open blockers (the common case) showed NOTHING here at all,
        # never the mockup's own neutral "No open blockers" reassurance
        # (`mock-L2-item.html`'s `.blocker-banner.resolved`). Computed
        # directly from `item.links` (the SAME `blocking` flag
        # `_blocked_by_list_html`/`claim_item` use) rather than string-
        # sniffing `links_html`'s own output, so this can never disagree
        # with what `_dependency_sections_html` decided to render: when
        # there IS an unsatisfied blocker, `links_html` already carries its
        # own crimson "Blocked by" banner and this stays "" (never a
        # second, contradictory banner).
        has_unsatisfied_blocker = any(
            ln.get("direction") == "from" and ln.get("type") == "blocks" and ln.get("blocking")
            for ln in (item.links or [])
        )
        blocker_status_html = (
            ""
            if has_unsatisfied_blocker
            else (
                '<div class="blocker-banner resolved">'
                '<span class="icon"><svg><use href="#i-check-circle"/></svg></span>'
                '<div><div class="btitle">No open blockers</div>'
                '<div class="blink" style="text-decoration:none;opacity:.85">'
                "This item has no unresolved blocking dependencies.</div></div>"
                "</div>"
            )
        )
        facts_kv = _item_facts_kv_html(name, item)
        time_kv = _item_time_kv_html(item)
        held_chip = _item_held_chip_html(item)
        # "Held by"/"Custody" fields are only meaningful (and only rendered)
        # while the item is genuinely held -- `item.holder` is bd's raw
        # `assignee`, which persists as a real historical fact past a
        # resolve/defer/block (see `_item_row_html`'s identical discipline);
        # rendering them unconditionally would make a resolved item look
        # like it still had an active holder.
        holder_field_html = ""
        custody_field_html = ""
        if item.status == "held" and item.holder:
            holder_field_html = (
                '<div class="field"><span class="k">Held by</span>'
                f'<span class="v mono">{_esc(item.holder)}</span></div>'
            )
            custody_field_html = (
                '<div class="field"><span class="k" title="Which agent currently holds '
                'this item, and whether that claim is still inside its TTL">Custody</span>'
                f'<span class="v mono">{held_chip or _EM_DASH}</span></div>'
            )

        confirm_resolve = request.query_params.get("confirm_resolve") == "1" and (
            item.status == "held"
        )

        # Edit -- ALWAYS available (title/description/acceptance/design are
        # editable regardless of status; only Resolve is status-gated,
        # below). Same fields, same POST route (`/update`) as before this
        # fix -- only WHERE it renders moved: it used to sit as a bare,
        # always-expanded form floating in the page body; the approved
        # mockup (`mock-L2-item.html`'s collapsed `.actions-drawer`) puts
        # every mutating action -- including Edit -- behind one collapsed
        # drawer, read-first by default.
        edit_section_html = f"""
        <div class="drawer-section">
          <h4>Edit</h4>
          <form method="post" action="/projects/{quote(name)}/items/{quote(item.id)}/update"
                class="prose" style="margin-top:var(--space-2)">
            <label for="title" class="eyebrow">Title</label>
            <textarea id="title" name="title" required rows="2"
                      style="width:100%;max-width:900px;font-family:var(--font-sans);
                      font-size:1rem;color:var(--ink-primary);background:var(--glass-fill);
                      border:1px solid var(--glass-hairline-soft);border-radius:var(--radius-sm);
                      padding:.5rem .75rem">{_esc(item.title)}</textarea>
            <h4>Description</h4>
            <textarea name="description" rows="6" placeholder="No description provided."
                      style="width:100%;max-width:900px;font-family:var(--font-sans);
                      font-size:.9375rem;color:var(--ink-primary);background:var(--glass-fill);
                      border:1px solid var(--glass-hairline-soft);border-radius:var(--radius-sm);
                      padding:.75rem 1rem">{_esc(item.description or "")}</textarea>
            <h4>Acceptance criteria</h4>
            <textarea name="acceptance" rows="4" placeholder="No acceptance criteria provided."
                      style="width:100%;max-width:900px;font-family:var(--font-sans);
                      font-size:.9375rem;color:var(--ink-primary);background:var(--glass-fill);
                      border:1px solid var(--glass-hairline-soft);border-radius:var(--radius-sm);
                      padding:.75rem 1rem">{_esc(item.acceptance or "")}</textarea>
            <h4>Design notes</h4>
            <textarea name="design" rows="4" placeholder="No design notes provided."
                      style="width:100%;max-width:900px;font-family:var(--font-sans);
                      font-size:.9375rem;color:var(--ink-primary);background:var(--glass-fill);
                      border:1px solid var(--glass-hairline-soft);border-radius:var(--radius-sm);
                      padding:.75rem 1rem">{_esc(item.design or "")}</textarea>
            <p class="field-hint" style="color:var(--ink-tertiary);font-size:.8125rem">
              Title/description/acceptance/design are editable here and persist on Save.
              Status, holder and timestamps are lifecycle facts -- they change only
              through claim/resolve.</p>
            <button type="submit" class="action-btn" style="margin-top:.3rem">Save changes</button>
          </form>
        </div>
        """

        action_labels = ["edit"]
        resolve_section_html = ""
        if item.status == "held":
            action_labels.append("resolve")
            resolve_section_html = (
                '<div class="drawer-section"><h4>Resolve</h4>'
                '<a href="?confirm_resolve=1" class="action-btn">'
                '<span class="icon"><svg><use href="#i-check-circle"/></svg></span> Resolve</a>'
                "</div>"
            )
        actions_count = " \u00b7 ".join(action_labels)

        if confirm_resolve:
            # Resolve is a terminal action (it closes the item) -- its
            # confirm sub-state takes over the WHOLE drawer (matching the
            # mockup's own state-demo: a flat, always-open confirm card,
            # not a second nested collapsible), rather than showing Edit
            # and the confirm dialog side by side.
            actions_html = f"""
            <div class="actions-drawer" open>
              <div style="padding:var(--space-4) var(--space-5);display:flex;
                   align-items:center;gap:var(--space-3);font-weight:600;
                   color:var(--ink-primary);font-size:.875rem">
                <span class="icon" style="color:var(--ink-tertiary)">
                  <svg><use href="#i-check-circle"/></svg></span> Resolve {_esc(item.id)}?
              </div>
              <div style="padding:0 var(--space-5) var(--space-4);color:var(--ink-tertiary);
                   font-size:.8125rem">This closes the item. This cannot be undone.</div>
              <form method="post"
                    action="/projects/{quote(name)}/items/{quote(item.id)}/resolve"
                    style="padding:0 var(--space-5) var(--space-5);display:flex;
                    flex-direction:column;gap:var(--space-3);
                    border-top:1px solid var(--glass-hairline-soft);padding-top:var(--space-4)">
                <input type="hidden" name="confirm" value="yes">
                <label for="reason">Resolution reason</label>
                <textarea id="reason" name="reason" rows="2" required></textarea>
                <label for="resolve_actor">Actor</label>
                <input type="text" id="resolve_actor" name="actor"
                       value="{identity_val}" required>
                <div style="display:flex;gap:var(--space-3)">
                  <button type="submit" class="action-btn" style="background:
                      var(--brand-gradient-solid);color:var(--ink-on-solid);border-color:transparent">
                    <span class="icon"><svg><use href="#i-check-circle"/></svg></span> Confirm
                  </button>
                  <a href="/projects/{quote(name)}/items/{quote(item.id)}" class="action-btn">
                    <span class="icon"><svg><use href="#i-octagon-x"/></svg></span> Cancel</a>
                </div>
              </form>
            </div>
            """
        else:
            actions_html = f"""
            <details class="actions-drawer">
              <summary>
                <span class="icon"><svg><use href="#i-edit"/></svg></span>
                Actions
                <span class="count">{actions_count}</span>
                <span class="icon sm chev"><svg><use href="#i-chevron"/></svg></span>
              </summary>
              <div class="drawer-body">
                {edit_section_html}
                {resolve_section_html}
              </div>
            </details>
            """

        body = f"""
        {_observatory_icon_sprite_html()}
        <div class="container">
        {_flash(request)}
        <div class="breadcrumb">
          {_crumb(("/", "Mission Control"), (f"/projects/{name}", name), ("", item.id))}
        </div>
        <div class="glass-panel strong detail-card">
          <div class="detail-head">
            <div class="detail-title">
              <span class="id">{_esc(item.id)}</span> {_esc(item.title)}
              <span class="status-chip">
                <span class="icon sm" style="margin-right:4px">
                  <svg><use href="#i-bot"/></svg></span>{_esc(item.status.upper())}</span>
            </div>
          </div>
          <div class="detail-meta-row">
            {"".join(f'<span class="tag-chip">{_esc(t)}</span>' for t in item.tags)}
          </div>
          <div style="height:var(--space-5)"></div>
          <div class="field-grid">
            <div class="field"><span class="k">Project</span>
              <span class="v"><a href="/projects/{quote(name)}"
                style="color:inherit;text-decoration:none;border-bottom:1px dashed
                var(--ink-tertiary)">{_esc(name)}</a></span></div>
            {holder_field_html}
            {custody_field_html}
            <div class="field"><span class="k">Created</span>
              <span class="v mono">{_item_age_html(item.created_at)}</span></div>
          </div>
          <div class="kv" style="margin-top:10px">{facts_kv}</div>
          <div class="kv" style="margin-top:10px">{time_kv}</div>
          {resolution_html}
          {blocker_status_html}
          {links_html}
          {actions_html}
          <div class="section" style="margin-top:var(--space-6)">
            <div class="section-title"><h2>Activity</h2></div>
            {activity_html}
          </div>
        </div>
        </div>
        """
        return _page(
            request,
            f"{item.id} - {item.title}",
            body,
            crumb_html=_crumb(("/", "Mission Control"), (f"/projects/{name}", name), ("", item.id)),
            body_class="wt-observatory",
            extra_nav_html=_observatory_help_and_theme_html(),
            js=_OBSERVATORY_THEME_JS,
            nav_project=name,
        )
