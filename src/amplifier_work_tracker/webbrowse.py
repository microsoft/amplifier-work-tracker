"""Split-pane BROWSE view: a scrollable work-item list (left) beside the
selected item's read-only detail (right).

This is a NEW, self-contained module. It OWNS this file only. It reuses
`webapp.py` / `webtheme.py` / `adapter.py` by IMPORT and never edits them
(another lane owns those). Mounting is a one-liner -- `register(app, workspace)`
-- so the only residual the orchestrator applies to `webapp.py` is that single
call plus one nav link (see DONE.json).

Design firewall (already shipped in the app; enforced here by referencing the
existing tokens, never redefining them):

  * Glass/gradient live on CHROME only (the two panes, the selected-row rim);
    data-ink stays flat and legible.
  * amber (`--amber`) = alarm and crimson (`--crimson`) = blocked are the ONLY
    status colors. cyan/purple (`--brand-*`, `--glass-fill-row-selected`) mean
    interaction/selection, NEVER status.
  * State is never color-only: a row carries a per-status GLYPH (distinct shape
    per status) with a text `title`; the detail pane carries the full text badge.
  * All color/space/type values come from `webtheme.py`'s `:root` custom
    properties by `var(...)`. This module defines no new tokens.

Correctness contract (goal item #2): the view survives its OWN ~20s
auto-refresh full-body swap AND any post-mutation redirect that lands on it,
without a stale-model error and without losing the reader's selection or scroll
position:

  * Selection lives in the URL (`?item=<id>`), so `webtheme.auto_refresh_js`'s
    re-fetch of the same URL re-renders the same selection server-side.
  * Every request reads the item FRESH from bd, so an auto-refresh (or a
    redirect landing here) never renders a stale model; a vanished/renamed
    selection degrades to a graceful "not found" detail pane, never a 500.
  * Scroll position for both panes (and the page) is preserved across the
    body swap via `window`-scoped variables restored by `browse_js` -- which
    the auto-refresh swap re-executes on every tick (see its docstring).
  * Selecting a row is progressively enhanced: the `<a>` works as a plain
    navigation with JS off; with JS on, `browse_js` swaps ONLY the detail
    pane (leaving the list DOM -- and its scroll -- untouched) and updates the
    URL so the next auto-refresh keeps the selection.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker.webapp import (
    _AUTO_REFRESH_MS,
    _activity_feed_html,
    _content_block_html,
    _crumb,
    _custody_html,
    _custody_reading,
    _dependency_sections_html,
    _esc,
    _fact_value_html,
    _flash,
    _identity_html,
    _item_age_html,
    _item_state_html,
    _not_found_body,
    _page,
    _priority_bar_html,
    _status_icon_html,
)

# ---------------------------------------------------------------------------
# Namespaced CSS. Every rule references an EXISTING `webtheme.py` token via
# `var(...)`; nothing here defines or overrides a token. The `.wtb-` prefix
# keeps this view's structural rules from colliding with any existing class.
# ---------------------------------------------------------------------------
_BROWSE_CSS = r"""
.wtb-grid{display:flex;gap:26px;align-items:stretch;margin-top:8px;
  height:calc(100vh - 176px);min-height:440px}
/* Glass lives on the pane CHROME only -- the data inside each pane stays flat. */
.wtb-pane{background:var(--glass-fill);border:1px solid var(--glass-hairline-soft);
  border-radius:var(--radius-lg);box-shadow:var(--glass-shadow);
  display:flex;flex-direction:column;min-height:0}
.wtb-list{flex:0 0 clamp(300px,32%,440px)}
.wtb-detail{flex:1 1 auto;min-width:0}
.wtb-pane-head{flex:0 0 auto;display:flex;align-items:baseline;justify-content:space-between;
  gap:10px;padding:15px 20px 12px;border-bottom:1px solid var(--rule)}
.wtb-count{font-family:var(--serif);font-size:13px;color:var(--dim);
  font-variant-numeric:tabular-nums}
.wtb-scroll{flex:1 1 auto;overflow-y:auto;overscroll-behavior:contain}
.wtb-list .wtb-scroll{padding:6px}
.wtb-detail .wtb-scroll{padding:22px 26px 40px}

/* -- list rows -- */
.wtb-rows{display:flex;flex-direction:column;gap:1px}
a.wtb-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:11px;
  align-items:center;padding:9px 12px;border-radius:var(--radius-sm);position:relative;
  text-decoration:none;color:var(--mid);min-height:var(--u)}
a.wtb-row:hover{background:var(--glass-fill-row-hover);color:var(--ink)}
/* cyan wash = SELECTION (interaction), never a status color -- the same token
   the rest of the app uses for a selected row. */
a.wtb-row.selected{background:var(--glass-fill-row-selected);color:var(--ink)}
a.wtb-row.selected::before{content:"";position:absolute;left:-1px;top:8px;bottom:8px;
  width:2px;border-radius:1px;background:var(--brand-gradient-rim)}
.wtb-gutter{display:inline-flex;align-items:center;gap:6px}
.wtb-main{display:flex;flex-direction:column;gap:3px;min-width:0}
.wtb-title{font-family:var(--sans);font-size:13.5px;font-weight:500;color:var(--ink);
  letter-spacing:-.004em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wtb-id{font-family:var(--mono);font-size:11px;color:var(--dim);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wtb-age{font-family:var(--serif);font-size:12px;color:var(--dim);
  font-variant-numeric:tabular-nums;white-space:nowrap;justify-self:end}

/* -- detail pane -- */
.wtb-idline{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.wtb-idline .muted{font-family:var(--mono);font-size:12px}
.wtb-dt{font-family:var(--sans);font-size:20px;font-weight:500;letter-spacing:-.008em;
  color:var(--ink);margin:14px 0 0;max-width:72ch}
.wtb-open{margin-left:auto;font-family:var(--sans);font-size:12px;
  color:var(--brand-cyan-ink);text-decoration:none;border-bottom:1px solid var(--link-underline)}
.wtb-open:hover{color:var(--brand-cyan-ink)}
.wtb-label{display:block;margin:28px 0 8px;font-family:var(--sans);font-size:10px;
  font-weight:500;letter-spacing:.26em;text-transform:uppercase;color:var(--mid);line-height:1.5}
.wtb-label.am{color:var(--amber)}
.wtb-empty{display:flex;height:100%;min-height:220px;align-items:center;justify-content:center;
  text-align:center;color:var(--dim);padding:36px;max-width:46ch;margin:0 auto}

/* Narrow viewports: stack the panes and let the page scroll. Height/overflow
   are relaxed so neither pane is a cramped fixed box on a phone. No JS toggle
   -- a pure media-query reflow, so nothing here can fight the body swap. */
@media (max-width:860px){
  .wtb-grid{flex-direction:column;height:auto;gap:16px}
  .wtb-list{flex:none;width:auto}
  .wtb-list .wtb-scroll{max-height:46vh}
  .wtb-detail{overflow:visible}
  .wtb-detail .wtb-scroll{overflow:visible}
}
"""


def browse_js() -> str:
    """Client script for the browse view. `_page` appends
    `webtheme.auto_refresh_js` after this, in the SAME `<script>` element, and
    the auto-refresh body swap re-executes every `<script>` in the replaced
    body -- so this runs on first load AND again after each 20s swap. That
    re-run is exactly what restores scroll and keeps the selection highlight
    after the DOM has been replaced.

    Two jobs:

    1. Scroll survival. `window` survives the body swap (only
       `document.body.innerHTML` is replaced), so per-pane scroll offsets and
       the page scroll are stashed on `window` and restored here after the
       swap. The window-level scroll listener is bound once (guard flag);
       per-pane listeners re-bind harmlessly onto the fresh pane elements each
       run (the old elements, and their listeners, are discarded with the old
       body).

    2. Progressive-enhancement selection. A plain click on a row `<a>` fetches
       the same URL, swaps ONLY `#browse-detail` (leaving the list DOM and its
       scroll untouched), moves the `.selected` highlight, and updates the URL
       via `replaceState` so the next auto-refresh re-fetch keeps the
       selection. Modifier/middle clicks fall through to normal open-in-new-tab
       behavior; any fetch failure falls back to a full navigation.
    """
    return r"""
(function(){
  var W = window;
  function byId(id){ return document.getElementById(id); }

  // -- 1. scroll survival across the auto-refresh body swap --
  if (!W.__wtBrowseWinBound) {
    W.__wtBrowseWinBound = true;
    W.addEventListener('scroll', function(){ W.__wtBrowseWinScroll = W.scrollY; }, {passive:true});
  }
  var listEl = byId('browse-list');
  if (listEl) {
    listEl.addEventListener('scroll', function(){
      W.__wtBrowseListScroll = listEl.scrollTop;
    }, {passive:true});
    if (W.__wtBrowseListScroll != null) listEl.scrollTop = W.__wtBrowseListScroll;
  }
  var detailEl = byId('browse-detail');
  if (detailEl) {
    detailEl.addEventListener('scroll', function(){
      W.__wtBrowseDetailScroll = detailEl.scrollTop;
    }, {passive:true});
    if (W.__wtBrowseDetailScroll != null) detailEl.scrollTop = W.__wtBrowseDetailScroll;
  }
  if (W.__wtBrowseWinScroll != null) W.scrollTo(0, W.__wtBrowseWinScroll);

  // -- 2. select a row without a full reload (keeps list scroll) --
  if (listEl) {
    listEl.addEventListener('click', function(ev){
      var a = ev.target && ev.target.closest ? ev.target.closest('a.wtb-row') : null;
      if (!a) return;
      if (ev.defaultPrevented) return;
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button === 1) return;
      ev.preventDefault();
      var url = a.getAttribute('href');
      fetch(url, {credentials:'same-origin', headers:{'X-Requested-With':'wt-browse-select'}})
        .then(function(r){ return r.ok ? r.text() : null; })
        .then(function(html){
          if (!html) { W.location.href = url; return; }
          var parsed = new DOMParser().parseFromString(html, 'text/html');
          var fresh = parsed.getElementById('browse-detail');
          var cur = byId('browse-detail');
          if (fresh && cur) {
            cur.innerHTML = fresh.innerHTML;
            cur.scrollTop = 0;
            W.__wtBrowseDetailScroll = 0;
          }
          var prev = listEl.querySelectorAll('a.wtb-row.selected');
          for (var i = 0; i < prev.length; i++) {
            prev[i].classList.remove('selected');
            prev[i].removeAttribute('aria-current');
          }
          a.classList.add('selected');
          a.setAttribute('aria-current', 'true');
          if (W.history && W.history.replaceState) W.history.replaceState(null, '', url);
        })
        .catch(function(){ W.location.href = url; });
    });
  }
})();
"""


def _row_html(name: str, item: A.Item, *, selected: bool) -> str:
    """One list row: priority tick + status glyph (gutter), title, mono id, and
    relative age. The whole row is the selection link (`?item=<id>`)."""
    prefix = f"{name}-"
    id_shown = item.id[len(prefix) :] if item.id.startswith(prefix) else item.id
    # Same searchable key vocabulary the item table's own rows use, so a future
    # `data-t` client filter (or a test) can match on id/title/status/holder.
    key = f"{item.id} {item.title} {item.status} {item.holder or ''}".lower()
    gutter = _priority_bar_html(item.priority) + _status_icon_html(item.status)
    title = _esc(item.title) or "&mdash;"
    age = _item_age_html(item.created_at)
    href = f"/projects/{_esc(name)}/browse?item={quote(item.id)}"
    sel_cls = " selected" if selected else ""
    aria = ' aria-current="true"' if selected else ""
    return (
        f'<a class="wtb-row{sel_cls}" role="listitem" href="{href}" '
        f'data-t="{_esc(key)}"{aria}>'
        f'<span class="wtb-gutter">{gutter}</span>'
        f'<span class="wtb-main">'
        f'<span class="wtb-title">{title}</span>'
        f'<span class="wtb-id" title="{_esc(item.id)}">{_esc(id_shown)}</span>'
        f"</span>"
        f'<span class="wtb-age">{age}</span>'
        f"</a>"
    )


def render_list_html(name: str, items: list[A.Item], selected_id: str | None) -> str:
    """The left pane's scrollable list body."""
    if not items:
        return '<div class="wtb-empty"><p>No work items in this project yet.</p></div>'
    rows = "".join(_row_html(name, i, selected=(i.id == selected_id)) for i in items)
    return f'<div class="wtb-rows" role="list">{rows}</div>'


def render_detail_html(
    name: str,
    item: A.Item | None,
    activity: list[A.ActivityEvent],
    *,
    detail_error: str | None = None,
) -> str:
    """The right pane's read-only detail for the selected item.

    Read-only ON PURPOSE: this view enables `auto_refresh_ms`, and the app's
    own convention (see `webapp._page`'s docstring) is to never ship the
    self-polling body-swap to a page carrying a live, unsaved edit form. The
    editable form stays on the canonical item page, reachable here via the
    "Open full item" link.
    """
    if item is None:
        if detail_error:
            return (
                '<div class="wtb-empty"><p><strong>'
                f"{_esc(detail_error)}</strong> could not be found. It may have been "
                "removed or renamed. Select another item from the list.</p></div>"
            )
        return (
            '<div class="wtb-empty"><p>Select a work item from the list to see its '
            "fields, blocker chain, and activity timeline.</p></div>"
        )

    # Holder chip -- only when GENUINELY held right now (bd's assignee survives
    # resolution as history, not current custody), with the same claim-age +
    # staleness reading the table row and item page use.
    custody_html = _custody_html(_custody_reading(item))
    if custody_html:
        held_chip = f'<span class="chip">{custody_html}</span>'
    elif item.holder and item.status == "held":
        held_chip = f'<span class="chip">held by {_identity_html(item.holder)}</span>'
    else:
        held_chip = ""

    facts = [
        ("Queue", f'<a class="prose-link" href="/projects/{_esc(name)}">{_esc(name)}</a>'),
        ("Kind", _fact_value_html(item.kind or "--")),
        ("Priority", _fact_value_html(str(item.priority) if item.priority is not None else "--")),
    ]
    owner = item.raw.get("owner")
    if owner:
        facts.append(("Reported by", _identity_html(str(owner))))
    facts_kv = "".join(
        f'<div><span class="k">{_esc(k)}</span><span class="v">{v}</span></div>' for k, v in facts
    )

    time_parts = [
        ("Created", _item_age_html(item.created_at)),
        ("Updated", _item_age_html(item.updated_at)),
    ]
    if item.status == "resolved" and item.closed_at:
        time_parts.append(("Resolved", _item_age_html(item.closed_at)))
    time_kv = "".join(
        f'<div><span class="k">{_esc(k)}</span><span class="v serif">{v}</span></div>'
        for k, v in time_parts
    )

    description = _content_block_html(item.description, empty_message="No description provided.")
    acceptance = _content_block_html(
        item.acceptance, empty_message="No acceptance criteria provided."
    )
    design = _content_block_html(item.design, empty_message="No design notes provided.")

    resolution_html = ""
    if item.status == "resolved" and item.resolution:
        resolution_html = (
            '<span class="wtb-label am">Resolution</span>'
            f'<div class="content-block">{_esc(item.resolution)}</div>'
        )

    links_html = _dependency_sections_html(name, item.links)
    activity_html = _activity_feed_html(activity)
    open_href = f"/projects/{_esc(name)}/items/{quote(item.id)}"

    return (
        '<div class="wtb-idline">'
        f'<span class="muted">{_esc(item.id)}</span>'
        f"{_item_state_html(item.status)}"
        f"{held_chip}"
        f'<a class="wtb-open" href="{open_href}">Open full item &rarr;</a>'
        "</div>"
        f'<h2 class="wtb-dt">{_esc(item.title)}</h2>'
        f'<div class="kv" style="margin-top:16px">{facts_kv}</div>'
        f'<div class="kv" style="margin-top:10px">{time_kv}</div>'
        f'<span class="wtb-label">Description</span>{description}'
        f'<span class="wtb-label">Acceptance criteria</span>{acceptance}'
        f'<span class="wtb-label">Design notes</span>{design}'
        f"{resolution_html}"
        f"{links_html}"
        f"{activity_html}"
    )


def render_browse_body(
    name: str,
    items: list[A.Item],
    selected_item: A.Item | None,
    activity: list[A.ActivityEvent],
    *,
    selected_id: str | None = None,
    detail_error: str | None = None,
    flash_html: str = "",
) -> str:
    """The full split-pane body: `<style>` + list pane + detail pane.

    The two `id="browse-list"` / `id="browse-detail"` scroll containers are the
    stable hooks `browse_js` keys its scroll-preservation and detail-swap on --
    keep those ids if the markup changes.
    """
    list_html = render_list_html(name, items, selected_id)
    detail_html = render_detail_html(name, selected_item, activity, detail_error=detail_error)
    return (
        f"<style>{_BROWSE_CSS}</style>"
        f"{flash_html}"
        '<div class="wtb-grid">'
        '<section class="wtb-pane wtb-list" aria-label="Work items">'
        '<div class="wtb-pane-head"><span class="eyebrow">Items</span>'
        f'<span class="wtb-count">{len(items)}</span></div>'
        f'<div class="wtb-scroll" id="browse-list">{list_html}</div>'
        "</section>"
        '<section class="wtb-pane wtb-detail" aria-label="Item detail">'
        f'<div class="wtb-scroll" id="browse-detail">{detail_html}</div>'
        "</section>"
        "</div>"
    )


def register(app: FastAPI, workspace: A.Workspace) -> None:
    """Mount the browse route onto an existing FastAPI app.

    Matches `webapp.create_app`'s idiom exactly: the handler closes over
    `workspace` (rather than using `Depends`/`app.state`). Call this once inside
    `create_app`, after `workspace` is in scope -- that single call is the only
    residual this module needs applied to `webapp.py`.
    """

    @app.get("/projects/{name}/browse", response_class=HTMLResponse)
    async def browse(request: Request, name: str) -> HTMLResponse:
        selected_id = request.query_params.get("item") or None
        try:
            bd = workspace.project(name)
        except A.BeadsError:
            return _page(
                request,
                f"{name} \u00b7 browse",
                _not_found_body(heading=name, back_href="/", back_label="all projects"),
                crumb_html=_crumb(("/", "All projects"), ("", name)),
            )

        # Fresh read every request -- so an auto-refresh tick (or a redirect
        # landing here) never renders a stale model.
        try:
            items = bd.list(include_resolved=True, limit=0)
        except A.BeadsError:
            items = []

        selected_item: A.Item | None = None
        activity: list[A.ActivityEvent] = []
        detail_error: str | None = None
        if selected_id:
            try:
                selected_item = bd.get(selected_id, with_links=True)
            except A.BeadsError:
                selected_item = None
                detail_error = selected_id
            if selected_item is not None:
                try:
                    activity = bd.activity(selected_item.id)
                except A.BeadsError:
                    activity = []

        body = render_browse_body(
            name,
            items,
            selected_item,
            activity,
            selected_id=selected_id,
            detail_error=detail_error,
            flash_html=_flash(request),
        )
        crumb = _crumb(("/", "All projects"), (f"/projects/{name}", name), ("", "browse"))
        return _page(
            request,
            f"{name} \u00b7 browse",
            body,
            crumb_html=crumb,
            js=browse_js(),
            auto_refresh_ms=_AUTO_REFRESH_MS,
        )
