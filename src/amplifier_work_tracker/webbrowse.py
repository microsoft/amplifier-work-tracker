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

from collections.abc import Callable
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker.webapp import (
    _AUTO_REFRESH_MS,
    _activity_feed_html,
    _content_block_html,
    _crumb,
    _dependency_sections_html,
    _esc,
    _flash,
    _item_age_html,
    _item_facts_kv_html,
    _item_held_chip_html,
    _item_state_html,
    _item_time_kv_html,
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
/* Glass lives on the pane CHROME only -- the data inside each pane stays flat.
   `backdrop-filter` + the rim-glow pseudo (below) port the same gallery
   materials/lighting the overview panels use (visual-fidelity pass); the
   pane's OWN background/border/radius/shadow are unchanged. */
.wtb-pane{background:var(--glass-fill);border:1px solid var(--glass-hairline-soft);
  border-radius:var(--radius-lg);box-shadow:var(--glass-shadow-float);
  backdrop-filter:blur(var(--glass-blur));-webkit-backdrop-filter:blur(var(--glass-blur));
  display:flex;flex-direction:column;min-height:0;position:relative}
/* gradient rim-glow -- chrome only, carries no status meaning; see
   webtheme.py's own `.hero::before` etc for the identical mask-composite
   technique (kept local here per this module's own no-shared-token-file
   convention rather than importing a mixin). */
.wtb-pane::before{
  content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;
  background:var(--brand-gradient-rim);
  -webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;
  opacity:.5;pointer-events:none;
}
.wtb-list{flex:0 0 clamp(300px,32%,440px)}
.wtb-detail{flex:1 1 auto;min-width:0}
.wtb-pane-head{flex:0 0 auto;display:flex;align-items:baseline;justify-content:space-between;
  gap:10px;padding:15px 20px 12px;border-bottom:1px solid var(--rule)}
.wtb-count{font-family:var(--serif);font-size:13px;color:var(--dim);
  font-variant-numeric:tabular-nums}
.wtb-scroll{flex:1 1 auto;overflow-y:auto;overscroll-behavior:contain}
.wtb-list .wtb-scroll{padding:6px}
.wtb-detail .wtb-scroll{padding:22px 26px 40px}
/* Visible scroll affordance (goal wtv3/finish, task 5): `.wtb-scroll` was
   already mechanically `overflow-y:auto` (long content DOES scroll), but
   on several platforms an unstyled scrollbar renders as an invisible
   overlay -- nothing hints that a long description/timeline continues
   below the fold, so it reads as clipped even though it isn't. Styling
   `::-webkit-scrollbar` also has the side effect of switching Chromium
   away from that invisible-overlay default to a real, always-rendered
   (while scrollable) thumb -- the fix and the affordance are the same
   change. `--dim` (not `--glass-hairline*`) is deliberate: measured via a
   real render, `--glass-hairline`'s rgba alpha (.14/.08 -- tuned for a
   barely-there PANEL border, sitting beside a brighter rim-glow edge) was
   verified functionally present (scrollbar-gutter reserved, `scrollbar-
   color` applied) but too faint to read as a scrollbar at all against the
   dark glass fill -- exactly the invisible-affordance defect this task
   exists to fix, just moved from "no scrollbar" to "a scrollbar no one
   can see". `--dim` is the SAME already-used, contrast-verified ink token
   `.wtb-count`/`.wtb-age` on this very page already render small print in
   -- no new token defined here, just a more legible existing one.
   `scrollbar-gutter:stable` reserves the thumb's width up front so its
   appearance never shifts the content underneath by a few pixels once a
   pane becomes scrollable. */
/* C7 (craft punch list): `--dim` still read as barely-there against the
   glass panel fill -- the SAME invisible-affordance defect this rule's own
   comment above already fixed once, just not far enough. `--mid` (one
   step up the same ink ramp, still <=4.5:1-verified in both schemes) is
   the next real, legible stop -- hover moves to the strongest step
   (`--ink`) so the thumb clearly brightens under the pointer. */
.wtb-scroll{scrollbar-width:thin;scrollbar-color:var(--mid) transparent;
  scrollbar-gutter:stable}
.wtb-scroll::-webkit-scrollbar{width:8px}
.wtb-scroll::-webkit-scrollbar-track{background:transparent}
.wtb-scroll::-webkit-scrollbar-thumb{background:var(--mid);
  border-radius:4px;border:2px solid transparent;background-clip:padding-box}
.wtb-scroll::-webkit-scrollbar-thumb:hover{background:var(--ink)}

/* -- column headers (goal wtv3/components, C2) -- the blend-3 mockup's
   left-pane column set: Priority . Status . Item ID . Task title .
   Relative age. Purely a label row over the SAME implicit grid `a.wtb-row`
   lays out (gutter . main . age) -- "Pri"/"St" label the gutter's two
   icons, "Item" the id+title stack, "Age" the trailing age. */
/* C9 (craft punch list): this grid declares 3 tracks (gutter . main . age),
   mirroring `a.wtb-row`'s own 3-column grid -- but the markup below used to
   emit 4 flat sibling <span>s ("Pri","St","Item","Age"), so CSS grid
   auto-placement wrapped the 4th ("Age") onto a new implicit row at column
   1, instead of landing over the row's actual right-aligned Age column.
   Nesting "Pri"+"St" inside ONE wrapping span (matching `:first-child`'s
   existing `display:flex` rule below, which was written for exactly that
   nesting) restores 3 real top-level items -- gutter/main/age -- so "Age"
   lands in the grid's 3rd (auto-width, right-hand) track like the data
   rows' own `.wtb-age`, and `text-align:right` on it now means something. */
.wtb-col-headers{display:grid;grid-template-columns:auto minmax(0,1fr) auto;
  column-gap:11px;padding:0 12px 6px;font-family:var(--sans);font-size:9.5px;
  font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}
.wtb-col-headers span:first-child{display:flex;gap:14px}
.wtb-col-headers span:last-child{text-align:right}

/* -- list-pane header/footer EXTRA slots (goal wtv3/project-page) -- optional,
   only rendered when a caller passes them (`render_browse_body`'s
   `list_header_extra`/`list_footer_html`), so this route's own `/browse`
   output is byte-identical when it doesn't. `.wtb-list-extra` sits between
   the "Items N" head and the column headers -- `project_view` renders its
   status tabs + search field there, reusing those UNCHANGED shared classes
   (`.tabs`/`.controls`/`.field`), never a second copy. `.wtb-pane-foot` sits
   BELOW the scrollable list (outside `.wtb-scroll`), so a control placed
   there (e.g. `project_view`'s existing pagination) never scrolls out of
   view with the rows above it. */
/* D3 (consistency pass): this narrow list-pane header previously mixed
   THREE different vertical rhythms for what should read as one toolbar --
   `.tabs`'s own row-wrap gap (.25rem), a forced 0 between the tabs block
   and the search controls below it, and `.controls`'s own 14px gap for
   its own wrapped sub-rows (the field row vs. the button/count/toggle
   row it wraps to at this column's ~300-440px width). `display:flex;
   flex-direction:column;gap:12px` makes ONE value -- not three -- the
   single source of truth for "space between toolbar blocks"; the tabs'
   own inter-pill gap and `.controls`'s own inter-field gap are a
   different, smaller-scale spacing concern and are left alone. */
.wtb-list-extra{padding:0 20px 14px;display:flex;flex-direction:column;gap:12px}
.wtb-list-extra .tabs{margin:0}
.wtb-list-extra .controls{padding:0}
/* D3 fixup (consistency pass, round 2): the round-1 `gap:12px` only fixed the
   spacing BETWEEN the tabs/search/controls blocks -- it never touched the two
   things that actually read as "untidy" inside this narrow (~300-440px) list
   pane:
     (a) the search input still SHARED its row with the Search button whenever
         the pane happened to be wide enough for `.field`'s min-width (240px)
         + the button to both fit -- leaving the input at ~60-70% width with
         the button (and a chunk of dead space) beside it. Measured live at a
         real project width. The desktop base rule (`.field{flex:1;
         max-width:520px}`) is written for a WIDE full-page controls bar, not
         a skinny column. Here we force the field to own its whole row
         (`flex-basis:100%`, cap removed) so the button/count/toggle always
         wrap cleanly beneath it -- the SAME thing the global <=600px rule
         already does for phones, applied to this narrow pane at every width.
     (b) `.controls`' own inter-row gap was still its desktop 14px while the
         blocks around it use 12px -- one value now, so the whole toolbar
         reads on a single vertical rhythm.
   Also tighten the status-tab pills (smaller pad + gap) so 6 tabs read as one
   compact block instead of sprawling across three ragged lines. */
/* The search field owns its OWN full-width row, with the Search button + count
   + density toggle wrapping onto ONE compact row beneath it. `column-gap` for
   inter-item spacing, a small `row-gap` for the wrap -- NOT the 12px block gap,
   which (via an `::after` full-height spacer) made the header tall enough to
   push the button past the fixed-height pane's bottom edge. The field spans the
   row via `flex-basis:100%`; a zero-height full-basis `::after` forces the wrap
   without adding its own row height. */
.wtb-list-extra .controls{column-gap:12px;row-gap:8px}
.wtb-list-extra .controls .field{flex:1 1 100%;min-width:0;max-width:none;order:0}
.wtb-list-extra .controls::after{content:"";flex:1 1 100%;height:0;margin:0;order:1}
.wtb-list-extra .controls>:not(.field){order:2;flex:0 0 auto}
.wtb-list-extra .tabs{gap:6px}
.wtb-list-extra .tabs .tab{padding:6px 12px}
.wtb-pane-foot{flex:0 0 auto;padding:10px 20px;border-top:1px solid var(--rule)}
.wtb-pane-foot .pagination{margin:0}

/* -- optional third row-line: a held/custody reading (goal wtv3/project-page,
   task 2 -- "held custody / staleness readings...brought to standard"). Reuses
   the SAME `.held-custody`/`.stale`/`.fresh` tokens the item-detail pane and
   the (retired) table row already render via `_custody_html` -- no new
   status vocabulary, just a smaller stacked line under the title/id. Absent
   for every non-held row (see `_row_html`'s `extra_html=""` default). */
.wtb-holder{display:block;margin-top:1px;font-family:var(--sans);font-size:11px;
  color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* -- density toggle (goal wtv3/project-page): the SAME `body.density-compact`
   class `webtheme.list_controls_js` already toggles workspace-wide -- this
   view just supplies its OWN compact values for its OWN squircle-row
   geometry (webtheme.py's `.tbl` rules do not apply to `a.wtb-row`, a
   different element entirely). */
body.density-compact .wtb-row{padding:5px 12px;min-height:0}
body.density-compact .wtb-rows{gap:3px}
body.density-compact .wtb-title{font-size:12.5px}
body.density-compact .wtb-id,body.density-compact .wtb-age{font-size:10px}
body.density-compact .wtb-pane-head{padding:10px 16px 8px}

/* -- keyboard-nav highlight (goal wtv3/project-page): `webtheme.
   list_controls_js`'s shared `j`/`k`/`Enter` row navigation now also
   targets `a.wtb-row[data-t]` (see that function's own comment) and toggles
   the SAME `.kbd-sel` class the item table's `tr.kbd-sel` already uses.
   Only the box-shadow ring is added here (not a background override): a
   selected row's own `.selected` background wash must still show through
   when both classes land on the same row at once. */
a.wtb-row.kbd-sel{box-shadow:inset 0 0 0 1px var(--rule-hi)}

/* -- list rows -- squircle glass cards (visual-fidelity pass, gap 4): each
   row is its own rounded glass-fill card with real spacing between rows,
   the same "row-list" language the needs-you queue and the design system
   gallery both use, rather than a flush 1px-gap flat list. */
.wtb-rows{display:flex;flex-direction:column;gap:6px}
a.wtb-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:11px;
  align-items:center;padding:9px 12px;border-radius:var(--radius-md);position:relative;
  background:var(--glass-fill);border:1px solid var(--glass-hairline-soft);
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


def _row_html(
    name: str,
    item: A.Item,
    *,
    selected: bool,
    href: str | None = None,
    extra_html: str = "",
) -> str:
    """One list row: priority tick + status glyph (gutter), title, mono id, and
    relative age. The whole row is the selection link (`?item=<id>` by default).

    `href` lets a caller (e.g. `project_view`'s split-pane, goal wtv3/
    project-page) point the row at its OWN selection URL -- preserving
    query params this module knows nothing about (`?status=`/`?q=`/`?page=`)
    -- instead of this route's own `/browse?item=`. `extra_html`, when
    given, renders as a third stacked line inside `.wtb-main` (e.g. a held/
    custody reading) -- both default to the exact prior behavior so the
    `/browse` route itself is byte-for-byte unchanged.
    """
    prefix = f"{name}-"
    id_shown = item.id[len(prefix) :] if item.id.startswith(prefix) else item.id
    # Same searchable key vocabulary the item table's own rows use, so a future
    # `data-t` client filter (or a test) can match on id/title/status/holder.
    key = f"{item.id} {item.title} {item.status} {item.holder or ''}".lower()
    gutter = _priority_bar_html(item.priority) + _status_icon_html(item.status)
    title = _esc(item.title) or "&mdash;"
    # v3 firewall polish: this IS the item-table Age column (the old,
    # now-dead `_item_row`/.tbl component's replacement) -- amber-as-
    # neglect is legitimate here ONLY for a genuinely ready/unclaimed
    # item (matches `_item_row`'s own historical `if i.status == "open"
    # else "a0"` gate); a held/blocked/deferred/resolved row's age is a
    # calm fact, never an alarm.
    age = _item_age_html(item.created_at, alarm_eligible=(item.status == "open"))
    row_href = href if href is not None else f"/projects/{_esc(name)}/browse?item={quote(item.id)}"
    sel_cls = " selected" if selected else ""
    aria = ' aria-current="true"' if selected else ""
    extra = f'<span class="wtb-holder">{extra_html}</span>' if extra_html else ""
    return (
        f'<a class="wtb-row{sel_cls}" role="listitem" href="{row_href}" '
        f'data-t="{_esc(key)}"{aria}>'
        f'<span class="wtb-gutter">{gutter}</span>'
        f'<span class="wtb-main">'
        f'<span class="wtb-title">{title}</span>'
        f'<span class="wtb-id" title="{_esc(item.id)}">{_esc(id_shown)}</span>'
        f"{extra}"
        f"</span>"
        f'<span class="wtb-age">{age}</span>'
        f"</a>"
    )


def render_list_html(
    name: str,
    items: list[A.Item],
    selected_id: str | None,
    *,
    href_builder: Callable[[A.Item], str] | None = None,
    row_extra_builder: Callable[[A.Item], str] | None = None,
    empty_html: str | None = None,
) -> str:
    """The left pane's scrollable list body.

    `href_builder`/`row_extra_builder`/`empty_html` are the same optional
    generalization hooks `render_browse_body` documents -- all default to
    `None`, which reproduces this route's original, unparameterized output
    exactly.
    """
    if not items:
        if empty_html is not None:
            return empty_html
        return '<div class="wtb-empty"><p>No work items in this project yet.</p></div>'
    rows = "".join(
        _row_html(
            name,
            i,
            selected=(i.id == selected_id),
            href=href_builder(i) if href_builder else None,
            extra_html=row_extra_builder(i) if row_extra_builder else "",
        )
        for i in items
    )
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

    # D5 (consistency pass): facts/timestamps/held-chip are now the SAME
    # shared builders the standalone item-detail page calls
    # (`_item_facts_kv_html`/`_item_time_kv_html`/`_item_held_chip_html`,
    # defined in webapp.py) -- one computation, not two independently-
    # drifting copies of the same three things.
    held_chip = _item_held_chip_html(item)
    facts_kv = _item_facts_kv_html(name, item)
    time_kv = _item_time_kv_html(item)

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
    list_header_extra: str = "",
    list_footer_html: str = "",
    href_builder: Callable[[A.Item], str] | None = None,
    row_extra_builder: Callable[[A.Item], str] | None = None,
    empty_html: str | None = None,
) -> str:
    """The full split-pane body: `<style>` + list pane + detail pane.

    This is the SHARED split-pane machinery -- goal wtv3/project-page reuses
    it verbatim for `project_view`'s own list+detail layout rather than a
    second, drift-prone copy (see that route's own comment for why reuse
    won over recreate). Every new parameter below is optional and defaults
    to exactly the prior behavior, so this route's OWN `/browse` output is
    byte-for-byte unchanged when called with none of them:

      * `list_header_extra` -- extra markup rendered inside the list pane's
        head, below the "Items N" count and above the column headers (e.g.
        `project_view`'s status tabs + search field). Wrapped in its own
        `.wtb-list-extra` div so it gets sensible spacing without a caller
        needing to know this pane's own padding.
      * `list_footer_html` -- extra markup rendered BELOW the scrollable
        list (e.g. `project_view`'s existing pagination control) -- outside
        `.wtb-scroll`, so it never scrolls out of view. Wrapped in
        `.wtb-pane-foot`, absent entirely when not given (so `class=
        "pagination"` truly never appears when there is nothing to
        paginate, matching the pre-existing pagination-reachability
        contract).
      * `href_builder`/`row_extra_builder`/`empty_html` -- threaded straight
        through to `render_list_html` (see its own docstring).

    The two `id="browse-list"` / `id="browse-detail"` scroll containers are the
    stable hooks `browse_js` keys its scroll-preservation and detail-swap on --
    keep those ids if the markup changes.
    """
    list_html = render_list_html(
        name,
        items,
        selected_id,
        href_builder=href_builder,
        row_extra_builder=row_extra_builder,
        empty_html=empty_html,
    )
    detail_html = render_detail_html(name, selected_item, activity, detail_error=detail_error)
    header_extra = (
        f'<div class="wtb-list-extra">{list_header_extra}</div>' if list_header_extra else ""
    )
    footer = f'<div class="wtb-pane-foot">{list_footer_html}</div>' if list_footer_html else ""
    return (
        f"<style>{_BROWSE_CSS}</style>"
        f"{flash_html}"
        '<div class="wtb-grid">'
        '<section class="wtb-pane wtb-list" aria-label="Work items">'
        '<div class="wtb-pane-head"><span class="eyebrow">Items</span>'
        f'<span class="wtb-count">{len(items)}</span></div>'
        f"{header_extra}"
        # C2 (goal wtv3/components): the blend-3 mockup's exact left-pane
        # column set -- Priority . Status . Item ID . Task title . Relative
        # age -- ported from the approved gallery's own `.col-headers`
        # (design-system.html #list-detail). Purely a labelling row over
        # the SAME grid `a.wtb-row` already lays out; no new data.
        '<div class="wtb-col-headers" aria-hidden="true">'
        "<span>Pri</span><span>St</span><span>Item</span><span>Age</span>"
        "</div>"
        f'<div class="wtb-scroll" id="browse-list">{list_html}</div>'
        f"{footer}"
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
            nav_project=name,
        )
