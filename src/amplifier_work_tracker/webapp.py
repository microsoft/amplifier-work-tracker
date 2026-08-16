"""Web dashboard + full interaction UI for amplifier-work-tracker.

Serves over the SAME shared dolt server the CLI and the background
`amplifier-work-tracker service` use -- this process is an additional
client, exactly what a multi-client dolt server is for. It never restarts,
reinstalls, or otherwise touches the systemd/launchd service (`service.py`),
never binds the port muxplex or any other running service owns, and never
spawns or supervises a dolt server itself (`supervisor.py` already owns
that job).

All bd/dolt knowledge stays in `amplifier_work_tracker.adapter` -- every
route below calls the same `Workspace`/`Beads` methods `cli.py` calls, and
nothing else. Where a view needed something the seam didn't expose
(per-project counts, aging/throughput figures, per-project "what changed
most recently"), that logic was added to the seam itself
(`adapter.project_summary`/`adapter.project_activity`), not duplicated
here -- see those functions' docstrings.

Auth is `webauth.py`, ported from muxplex's pattern (see that module's
docstring for exactly what was kept and what was deliberately changed).

Rendering is plain server-rendered HTML via small string-building helpers
below plus `webtheme.py` (fonts, CSS, chrome, age/duration formatting) --
no template engine, no static asset pipeline, no client-side JS framework.

Design notes (round 3 -- the J-editorial-dark visual system)
--------------------------------------------------------------
The first two rounds of this UI used a light, generic admin-panel style.
This revision ports the J-editorial-dark design candidate (see
`.amplifier/design-gauntlet/wt-dashboard-v2/candidates/J-editorial-dark/`,
that design's own MANIFEST.md), which won a 12-candidate bake-off spanning
three independent approaches and passed an independent visual review with
a verdict of SHIP. `webtheme.py`'s module docstring records exactly what
was ported verbatim and what was deliberately adapted for a real,
data-backed app instead of a static fixture-driven mockup.

The load-bearing property this port exists to deliver: the dashboard's
hero is the AGE of the oldest unclaimed item, never a count. `held == 0`
is true on most days -- a giant `0` trains a viewer to stop looking. An
age reads as neglect, which is the thing actually worth a glance. Queues
sort STALEST FIRST for the same reason: a count-encoded dashboard makes
the biggest queue the biggest object on screen, which is exactly the
wrong axis to make prominent. See `webtheme.py` and this module's
`_dashboard_sort_key`/`_hero_html` for the mechanism.

This revision also retires the reference design's biggest fixture-driven
compromise. Its MANIFEST recorded a dagger-footnoted caveat -- "cortex
only -- the other 11 queues record no completion timestamps" -- because
at the time it was built, `closed_at` was not reachable through this
project's own seam. It is now (`adapter.Item.created_at/updated_at/
closed_at`, `adapter.project_activity`): every project's throughput
(`resolved_24h`/`resolved_7d`) and every project's own oldest-unclaimed
age are real, for all of them, all the time. There is no dagger anywhere
in this file.
"""

from __future__ import annotations

import html
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from . import adapter as A
from . import webauth as WA
from . import webtheme as T

logger = logging.getLogger(__name__)

# Exact-path auth-exempt set -- never prefix matching. See webauth's module
# docstring / muxplex's own incident for why a path *starting with* or
# *ending in* something is not a safe basis for an auth exemption.
_AUTH_EXEMPT_PATHS = {"/login", "/auth/logout", "/healthz"}

SESSION_TTL_SECONDS = 12 * 3600


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforces authentication on every request except `_AUTH_EXEMPT_PATHS`.

    Deliberately no localhost bypass -- see `webauth`'s module docstring.
    Every data-bearing route requires either a valid session cookie or an
    `Authorization` header (Basic, checked against the same credential the
    login form uses; Bearer is not supported here -- there is no
    server-to-server federation use case for this UI, unlike muxplex's).
    """

    def __init__(self, app, auth: WA.AuthConfig):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)

        cookie = request.cookies.get(WA.SESSION_COOKIE_NAME)
        if cookie:
            identity = WA.verify_session_cookie(self.auth.secret, cookie, self.auth.ttl_seconds)
            if identity:
                request.state.identity = identity
                return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        basic = WA.decode_basic_auth(auth_header)
        if basic:
            username, password = basic
            identity = WA.check_credentials(self.auth.mode, username, password, self.auth)
            if identity:
                request.state.identity = identity
                return await call_next(request)
            return JSONResponse({"detail": "invalid credentials"}, status_code=401)

        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        requested = request.url.path
        if request.url.query:
            requested = f"{requested}?{request.url.query}"
        return RedirectResponse(url=WA.build_login_redirect_url(requested), status_code=307)


def _identity(request: Request) -> str:
    return getattr(request.state, "identity", "") or ""


# ---------------------------------------------------------------------------
# Error translation -- the ONE choke point every BeadsError passes through
# before it can reach a browser.
# ---------------------------------------------------------------------------


def _public_error_message(e: Exception) -> str:
    """Turn a `BeadsError` into safe, user-facing copy.

    Never echoes a raw exception message verbatim: adapter/Beads errors can
    legitimately contain a local filesystem path (`Workspace.project`'s "not
    found at <path>") or a CLI-only instruction ("amplifier-work-tracker new
    <name>") -- operationally useful in a terminal, meaningless and a minor
    information leak in a browser. Full detail still reaches server logs;
    it is simply never the thing rendered here.

    Deliberately narrow: only intercepts the two patterns actually observed
    to leak (a path, a CLI instruction) plus bd's own "no issue(s) found"
    phrasing for a missing item. Every OTHER BeadsError message (blocked-by,
    held-by, already-being-created, mismatched confirmation name, ...) is
    already safe and specific -- rewriting those too would trade a useful
    message for a vaguer one for no safety benefit.
    """
    msg = str(e)
    low = msg.lower()
    if "not found" in low or "no issue" in low:
        return (
            "That project or item doesn't exist. It may have been removed, or the name is mistyped."
        )
    if "still being created" in low or "already being created" in low:
        return "That project is still being created. Try again in a moment."
    return msg


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pluralize(count: int, noun: str, plural: str | None = None) -> str:
    """`f"{count} {noun-or-plural}"` with the correct form for `count` --
    "1 item", "0 items", "2 items", never a bare "1 items". `plural`
    defaults to `noun + "s"`; pass it explicitly for irregular nouns.

    Available for every count+noun render in this module's own helpers
    (none currently render one -- see this file's owning goal for the
    call sites elsewhere in the app, e.g. the project item-count badge
    and the live search-filter counter, that should adopt this)."""
    word = noun if count == 1 else (plural if plural is not None else f"{noun}s")
    return f"{count} {word}"


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware `datetime`.

    Accepts both the bare `bd`-style trailing-`Z` form (`_parse_bd_timestamp`
    in `adapter.py`) and whatever `datetime.isoformat()` itself produces for
    an already-parsed, timezone-aware value -- notably `+00:00` rather than
    `Z` for UTC. A strict `strptime(..., "%Y-%m-%dT%H:%M:%SZ")` accepted only
    the former, so round-tripping `item.created_at.isoformat()` (used
    throughout this module) silently failed to parse and rendered as
    "missing" -- the exact cause of resolved items showing "--" for
    CREATED/UPDATED/RESOLVED despite the timestamps being present all along.
    `datetime.fromisoformat` (Python 3.11+) accepts both forms directly; a
    naive result (no offset at all) is treated as UTC, matching this
    function's previous behavior."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# The single empty-value glyph for every helper below that renders a
# timestamp or age. One glyph everywhere -- rather than letting "--" and
# "\u2014" coexist depending on which branch happened to run -- is what
# keeps a single column (e.g. the dashboard's LAST ACTIVITY, rendered via
# `_abs_and_rel`) from showing two different placeholders for "no
# timestamp at all" vs. "a timestamp that failed to parse".
_EMPTY_GLYPH = "\u2014"


def _relative_time(ts: str | None) -> str:
    """Render an ISO-8601 timestamp as a short, coarse relative string
    ("just now", "12m ago", "3h ago", "5d ago"), or `_EMPTY_GLYPH` for
    missing/unparseable input."""
    dt = _parse_iso(ts)
    if dt is None:
        return _EMPTY_GLYPH
    seconds = int((datetime.now(UTC) - dt).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _abs_and_rel(ts: str | None) -> str:
    """`<span title="raw ISO timestamp">relative time</span>`, or a plain
    `_EMPTY_GLYPH` when there is nothing to show. Uses the same glyph
    `_relative_time` itself falls back to, so a missing timestamp and an
    unparseable one never render two different placeholders in the same
    column."""
    if not ts:
        return f'<span class="muted">{_EMPTY_GLYPH}</span>'
    return f'<span title="{_esc(ts)}">{_esc(_relative_time(ts))}</span>'


# GitHub's own noreply commit-identity format: `<numeric-id>+<username>@users.
# noreply.github.com` -- e.g. the Amplifier co-author trailer every automated
# commit/item carries. The ONE pattern actually observed leaking verbatim
# into "Reported by"/holder cells. Anything else (a real actor name, an
# agent session id like "agent-spark-1-106784") passes through unchanged.
_GH_NOREPLY_RE = re.compile(
    r"^\d+\+([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)@users\.noreply\.github\.com$"
)


def _humanize_identity(raw: str | None) -> str:
    """Reduce a raw actor/holder/owner identity string to a compact,
    human-scannable label. Only ever shortens a recognized machine-generated
    format; never invents or guesses at a name for an ordinary identity."""
    text = (raw or "").strip()
    if not text:
        return ""
    m = _GH_NOREPLY_RE.match(text)
    return m.group(1) if m else text


def _identity_html(raw: str | None) -> str:
    """`<span title="raw value">humanized label</span>` -- the readable form
    is what's shown, the exact raw string is always one hover away, and
    nothing is silently dropped. Returns "" for an empty/missing identity."""
    text = (raw or "").strip()
    if not text:
        return ""
    humanized = _humanize_identity(text)
    if humanized == text:
        return _esc(text)
    return f'<span title="{_esc(text)}">{_esc(humanized)}</span>'


_STATE_LABEL = {
    "open": "Open",
    "held": "Held",
    "resolved": "Resolved",
    "blocked": "Blocked",
    "deferred": "Deferred",
}
_STATE_CSS = {
    "open": "open",
    "held": "held",
    "resolved": "done",
    "blocked": "blkd",
    "deferred": "deferred",
}


def _item_state_html(status: str) -> str:
    cls = _STATE_CSS.get(status, "open")
    label = _STATE_LABEL.get(status, status.title())
    return f'<span class="st st-{cls}">{_esc(label)}</span>'


# ---------------------------------------------------------------------------
# page shell
# ---------------------------------------------------------------------------


def _identity_right(request: Request) -> str:
    """Top-bar right-hand chrome: a live dot, "live", and (when signed in)
    the identity plus a logout link. Built as a list of non-empty segments
    joined by `&middot;` rather than hardcoded inline separators, so an
    empty trailing segment (e.g. a future variant of this chrome that
    conditionally omits the logout link) can never leave a dangling
    "live &middot; operator &middot;" with nothing after the last dot."""
    dot_title = "Server-rendered from the shared queue database on every request"
    dot = f'<span class="dot on" title="{dot_title}"></span>'
    segments = ["live"]
    identity = _identity(request)
    if identity:
        segments.append(_esc(identity))
        segments.append('<a href="/auth/logout">Logout</a>')
    return f"{dot} " + " &middot; ".join(s for s in segments if s)


def _crumb(*parts: tuple[str, str]) -> str:
    """`parts` is (href, label) pairs; `href == ""` renders as plain text
    (the current page -- never a link to itself)."""
    out = [
        f'<a href="{_esc(href)}">{_esc(label)}</a>' if href else _esc(label)
        for href, label in parts
    ]
    return " / ".join(out)


def _page(
    request: Request,
    title: str,
    body: str,
    *,
    crumb_html: str = "",
    statusbar_html: str = "",
    js: str = "",
) -> HTMLResponse:
    top = T.top_bar(crumb_html=crumb_html, right_html=_identity_right(request))
    full_body = f'{top}<main class="wrap" id="main">{body}</main>{statusbar_html}'
    return HTMLResponse(T.page(f"{title} \u00b7 amplifier-work-tracker", full_body, js=js))


def _flash(request: Request) -> str:
    msg = request.query_params.get("msg")
    err = request.query_params.get("error")
    out = ""
    if msg:
        out += f'<div class="flash flash-msg">{_esc(msg)}</div>'
    if err:
        out += f'<div class="flash flash-error">{_esc(err)}</div>'
    return out


def _redirect(path: str, *, msg: str | None = None, error: str | None = None) -> RedirectResponse:
    q = []
    if msg:
        q.append(f"msg={quote(msg)}")
    if error:
        q.append(f"error={quote(error)}")
    url = path + ("?" + "&".join(q) if q else "")
    return RedirectResponse(url=url, status_code=303)


def _not_found_body(*, heading: str, back_href: str, back_label: str) -> str:
    return (
        f"<h1>{_esc(heading)}</h1>"
        '<div class="empty-state">'
        "<p>That project or item doesn't exist. It may have been removed, or the name/id "
        "is mistyped.</p>"
        "</div>"
        f'<p><a href="{_esc(back_href)}">&laquo; {_esc(back_label)}</a></p>'
    )


def _pagination_html(
    name: str, status: str | None, page: int, total_pages: int, result: A.ListResult
) -> str:
    """Real reachability control for a project's item table: with more than
    one page's worth of items, every one of them -- however many there are
    -- is reachable by clicking Next, not just the first `LIST_DEFAULT_LIMIT`.
    Absent entirely when everything already fits on one page.

    `result.total_count` is never a stale, unfiltered project-wide total:
    `adapter.Workspace.list_bounded` computes it from the SAME
    status-filtered query used to populate `result.items` (see that
    method's docstring), so when a caller applies `?status=`, the footer's
    "Items X-Y of N" and the page count both already reflect N as the
    filtered total, not the whole project. No separate filtered flag is
    needed from webapp-routes for that reason -- `result` already carries
    the honest number."""
    if total_pages <= 1:
        return ""

    def _href(p: int) -> str:
        q = f"page={p}"
        if status:
            q += f"&status={quote(status)}"
        return f"/projects/{_esc(name)}?{q}"

    prev = (
        f'<a href="{_href(page - 1)}">&laquo; Previous</a>'
        if page > 1
        else '<span class="muted">&laquo; Previous</span>'
    )
    nxt = (
        f'<a href="{_href(page + 1)}">Next &raquo;</a>'
        if page < total_pages
        else '<span class="muted">Next &raquo;</span>'
    )
    start_n = result.offset + 1 if result.returned_count else 0
    end_n = result.offset + result.returned_count
    return (
        '<div class="pagination">'
        f"<span>Items {start_n}&ndash;{end_n} of {result.total_count} "
        f"&middot; page {page} of {total_pages}</span>"
        f"<span>{prev} &middot; {nxt}</span>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# dashboard-specific rendering -- the hero, the heartbeat, the ledger
# ---------------------------------------------------------------------------


def _dashboard_sort_key(s: A.ProjectSummary) -> tuple[int, float, str]:
    """STALEST FIRST -- age is the sort key, never a count. Queues with no
    readable/ready age (unreadable projects, or genuinely empty queues)
    sort last, deterministically by name. See `webtheme.py`'s module
    docstring for why this is the single sharpest finding this whole port
    exists to deliver: a count-encoded dashboard makes the biggest queue
    the biggest object, which is the wrong axis to make prominent."""
    age = s.oldest_unclaimed_age_seconds if s.status == "ok" else None
    if age is not None:
        return (0, -age, s.name)
    return (1, 0.0, s.name)


def _global_oldest(summaries: list[A.ProjectSummary]) -> tuple[str, float] | None:
    candidates = [
        (s.name, s.oldest_unclaimed_age_seconds)
        for s in summaries
        if s.status == "ok" and s.oldest_unclaimed_age_seconds is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[1])


def _oldest_ready_item(bd: A.Beads) -> A.Item | None:
    """The single oldest ready (open, tagged `LANE_WORK`) item in one
    project -- used only for the hero's attribution line (which real item
    is the N-day-old one). One extra, project-scoped `bd list` call; never
    a workspace-wide fan-out. Returns `None` (never a guess) if the project
    can't be read or has no dated ready item."""
    try:
        items = bd.list(lane=A.LANE_WORK, status="open")
    except A.BeadsError:
        return None
    dated = [i for i in items if i.created_at is not None]
    if not dated:
        return None
    return min(dated, key=lambda i: i.created_at)  # type: ignore[arg-type,return-value]


def _hero_html(age_seconds: float | None, project_name: str | None, item: A.Item | None) -> str:
    """The dashboard's isolated hero. NOTHING sits beside it -- the void to
    its right is what makes the metric read as expensive; two earlier
    design cycles failed by crowding it with explanatory text (see
    `webtheme.py`'s module docstring)."""
    if age_seconds is None:
        empty_note = "No unclaimed work anywhere in this workspace right now."
        return f"""
<div class="hero solo">
  <span class="eyebrow">Oldest unclaimed work item</span>
  <div class="figrow"><span class="fig none" style="font-size:120px">\u2014</span></div>
  <div class="subtle" style="margin-top:20px">{empty_note}</div>
</div>"""
    value, unit = T.duration_words(age_seconds)
    attrib = ""
    if project_name and item is not None:
        since = item.created_at.strftime("%b %d") if item.created_at else "an unknown date"
        href = f"/projects/{_esc(project_name)}/items/{_esc(item.id)}"
        attrib = (
            f'<a class="attrib" href="{href}">{_esc(project_name)}<span class="id">'
            f'{_esc(item.id)}</span><span class="sep">/</span><span class="since">'
            f"Unclaimed since {_esc(since)}, no holder</span></a>"
        )
    elif project_name:
        href = f"/projects/{_esc(project_name)}"
        attrib = f'<a class="attrib" href="{href}">{_esc(project_name)}</a>'
    figrow = f'<span class="fig">{_esc(value)}</span><span class="figunit am">{_esc(unit)}</span>'
    return f"""
<div class="hero solo">
  <span class="eyebrow">Oldest unclaimed work item</span>
  <div class="figrow">{figrow}</div>
  {attrib}
</div>"""


_BUCKET_HEIGHT = {"0-1": 12, "2-3": 22, "4-6": 34, "7+": 44}
_BUCKET_BAND = {"0-1": "t0", "2-3": "t1", "4-6": "t2", "7+": "t3"}


def _aggregate_buckets(summaries: list[A.ProjectSummary]) -> dict[str, int]:
    totals = {label: 0 for label, _, _ in A.READY_AGE_BUCKETS}
    for s in summaries:
        if s.status == "ok" and s.ready_age_buckets:
            for k, v in s.ready_age_buckets.items():
                totals[k] = totals.get(k, 0) + v
    return totals


def _heartbeat_html(buckets: dict[str, int]) -> str:
    """The ready queue's age profile, one tick per real ready item across
    the whole workspace, banded into the same fixed real-world-day
    thresholds every other age reading in this app uses. A texture, not a
    chart -- it must never out-shout the hero."""
    total = sum(buckets.values())
    if total == 0:
        empty_note = "Nothing is ready to be claimed anywhere."
        return (
            '<div class="beat"><span class="eyebrow">Ready queue by age</span>'
            f'<div class="subtle" style="margin-top:14px">{empty_note}</div></div>'
        )
    ticks = "".join(
        f'<span class="tick {_BUCKET_BAND[label]}" style="height:{_BUCKET_HEIGHT[label]}px"></span>'
        for label, _, _ in A.READY_AGE_BUCKETS
        for _n in range(buckets.get(label, 0))
    )
    fresh = buckets.get("0-1", 0)
    stale = buckets.get("7+", 0)
    aria = f"Age profile of {total} unclaimed items across the workspace."
    legend = (
        f'<div class="legend"><div><span class="sw s0"></span>'
        f'<span class="n">{fresh}</span><span class="l">Arrived last day</span></div>'
        f'<div><span class="sw s3"></span><span class="n am">{stale}</span>'
        f'<span class="l">7d or older</span></div></div>'
    )
    return f"""
<div class="beat">
  <div class="bhead">
    <span class="eyebrow">Ready queue by age</span>
    {legend}
  </div>
  <div class="ticks" role="img" aria-label="{aria}">{ticks}</div>
  <div class="scale"><span>Fresher</span><span>one mark per item</span><span>Older</span></div>
</div>"""


def _ledger_html(held: int, blocked: int, resolved_24h: int, resolved_7d: int) -> str:
    """Status and throughput, real for every project (no instrumentation
    gap -- see this module's own docstring). Placement matters: this sits
    BELOW the hero, flanking the heartbeat, never beside the hero itself --
    see `webtheme.py`'s module docstring for why crowding the hero's right
    side is exactly the mistake two earlier design cycles made."""
    return f"""
<div class="ledger">
  <div class="grp">
    <span class="glbl">Status</span>
    <div class="stat"><span class="v">{held}</span><span class="k">Held right now</span></div>
    <div class="stat"><span class="v">{blocked}</span><span class="k">Blocked</span></div>
  </div>
  <div class="grp">
    <span class="glbl">Throughput</span>
    <div class="stat"><span class="v">{resolved_24h}</span>
      <span class="k">Resolved &middot; 24h</span></div>
    <div class="stat"><span class="v">{resolved_7d}</span>
      <span class="k">Resolved &middot; 7d</span></div>
  </div>
</div>"""


def _dashboard_row(s: A.ProjectSummary, scale_seconds: float) -> str:
    if s.status != "ok":
        key = f"{s.name} broken {s.status}".lower()
        return (
            f'<tr data-t="{_esc(key)}">'
            f'<td class="link-cell"><a href="/projects/{_esc(s.name)}">{_esc(s.name)}</a></td>'
            f'<td colspan="7"><span class="c">{T.state_html("bad", "Broken")} '
            f'<span class="muted">{_esc(s.status)}</span></span></td>'
            "</tr>"
        )
    age_cell = T.age_cell_html(s.oldest_unclaimed_age_seconds, scale_seconds)
    held_by_chips = "".join(f'<span class="chip">{_identity_html(h)}</span>' for h in s.held_by)
    if s.held:
        state = T.state_html("warn", f"{s.held} held")
    elif s.ready == 0:
        state = T.state_html("ok", "Nothing ready")
    else:
        state = T.state_html("ok", "Healthy")
    key = f"{s.name} {'held' if s.held else 'healthy'}".lower()
    ready_cls = "ink" if s.ready else "zero"
    held_cls = "ink" if s.held else "zero"
    blocked_cls = "ink" if s.blocked else "zero"
    return f"""<tr data-t="{_esc(key)}">
  <td class="link-cell"><a href="/projects/{_esc(s.name)}">{_esc(s.name)}</a></td>
  <td><span class="c">{age_cell}</span></td>
  <td class="r"><span class="c r"><span class="n {ready_cls}">{s.ready}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{s.total}</span></span></td>
  <td class="r"><span class="c r"><span class="n {held_cls}">{s.held}</span>
    {held_by_chips}</span></td>
  <td class="r"><span class="c r"><span class="n {blocked_cls}">{s.blocked}</span></span></td>
  <td class="gap"><span class="c">{state}</span></td>
  <td><span class="c">{_abs_and_rel(s.last_activity)}</span></td>
</tr>"""


def _dashboard_totals(summaries: list[A.ProjectSummary]) -> str:
    ok = [s for s in summaries if s.status == "ok"]
    t_ready = sum(s.ready or 0 for s in ok)
    t_total = sum(s.total or 0 for s in ok)
    t_held = sum(s.held or 0 for s in ok)
    t_blocked = sum(s.blocked or 0 for s in ok)
    return f"""<tfoot><tr>
  <td><span class="c"><span class="totk">All {len(summaries)} queues</span></span></td>
  <td><span class="c"></span></td>
  <td class="r"><span class="c r"><span class="n">{t_ready}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{t_total}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{t_held}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{t_blocked}</span></span></td>
  <td class="gap"><span class="c">
    <span class="totk">{len(ok)} of {len(summaries)} readable</span></span></td>
  <td></td>
</tr></tfoot>"""


def _create_project_form() -> str:
    return """
<div class="formsec">
  <span class="flegend">Create a project</span>
  <form method="post" action="/projects">
    <label for="name">Project name</label>
    <input type="text" id="name" name="name" pattern="[a-z][a-z0-9_]{1,30}" required
           placeholder="my_project">
    <p class="field-hint">Lowercase letters, digits, underscores; must start with a letter.</p>
    <button type="submit">Create</button>
  </form>
</div>"""


# ---------------------------------------------------------------------------
# project-view-specific rendering
# ---------------------------------------------------------------------------


def _project_hero_html(name: str, summary: A.ProjectSummary, oldest_item: A.Item | None) -> str:
    if summary.status != "ok":
        return (
            '<div class="hero">'
            '<span class="eyebrow" style="color:var(--crimson)">Unavailable</span>'
            '<div class="subtle" style="margin-top:16px;max-width:600px">'
            f"{_esc(summary.status)}</div></div>"
        )
    age = summary.oldest_unclaimed_age_seconds
    if age is None:
        fig = '<span class="fig none sm">\u2014</span><span class="figunit">No ready items</span>'
        said = (
            '<div class="said"><div class="subtle">'
            "Nothing is waiting to be claimed in this queue right now.</div></div>"
        )
    else:
        value, unit = T.duration_words(age)
        fig = f'<span class="fig sm">{_esc(value)}</span><span class="figunit">{_esc(unit)}</span>'
        if oldest_item is not None:
            since = (
                oldest_item.created_at.strftime("%b %d")
                if oldest_item.created_at
                else "an unknown date"
            )
            item_href = f"/projects/{_esc(name)}/items/{_esc(oldest_item.id)}"
            said = (
                f'<div class="said"><div class="who">{_esc(name)}'
                f'<span class="id">{_esc(oldest_item.id)}</span></div>'
                f'<a class="what" href="{item_href}">{_esc(oldest_item.title)}</a>'
                f'<div class="subtle" style="margin-top:8px">'
                f"Unclaimed since {_esc(since)}, no holder</div></div>"
            )
        else:
            said = ""
    tallies = f"""<div class="tallies">
      <div class="tally"><div class="v ink">{summary.ready}</div>
        <span class="k">Open</span></div>
      <div class="tally"><div class="v">{summary.blocked}</div>
        <span class="k">Blocked</span></div>
      <div class="tally"><div class="v">{summary.resolved}</div>
        <span class="k">Resolved</span></div>
      <div class="tally"><div class="v">{summary.held}</div><span class="k">Held</span></div>
    </div>"""
    throughput = f"""<div class="grp" style="margin-top:22px">
      <span class="glbl">Throughput</span>
      <div class="stat"><span class="v">{summary.resolved_24h}</span>
        <span class="k">Resolved &middot; 24h</span></div>
      <div class="stat"><span class="v">{summary.resolved_7d}</span>
        <span class="k">Resolved &middot; 7d</span></div>
    </div>"""
    beat_head = (
        f'<span class="eyebrow">Composition</span><span class="subtle">{summary.total} items</span>'
    )
    return f"""
<div class="hero">
  <div class="lead">
    <span class="eyebrow">Oldest unclaimed in this queue</span>
    <div class="figrow">{fig}</div>
    {said}
  </div>
  <div class="beat" style="min-width:260px;flex:1 1 260px">
    <div class="bhead">{beat_head}</div>
    {tallies}
    {throughput}
  </div>
</div>"""


def _item_lifecycle_seconds(i: A.Item) -> float | None:
    """The row's own age -- since created (open), since last touched
    (held/blocked/deferred), or since resolution (resolved). Staleness
    COLOUR is only meaningful for still-open items (see `_item_row`);
    every status still gets an honest duration value here."""
    now = datetime.now(UTC)
    basis = {
        "open": i.created_at,
        "held": i.updated_at,
        "resolved": i.closed_at,
    }.get(i.status, i.updated_at)
    if basis is None:
        return None
    return max(0.0, (now - basis).total_seconds())


def _item_row(name: str, i: A.Item, idx: int) -> str:
    seconds = _item_lifecycle_seconds(i)
    band = T.age_band_class(seconds) if i.status == "open" else "a0"
    value, unit = T.age_short(seconds)
    holder = _identity_html(i.holder) if i.holder else '<span class="muted">&mdash;</span>'
    href = f"/projects/{_esc(name)}/items/{_esc(i.id)}"
    key = f"{i.id} {i.title} {i.status} {i.holder or ''}".lower()
    age_html = f'<span class="age {band}">{_esc(value)}<span class="u">{_esc(unit)}</span></span>'
    return f"""<tr data-t="{_esc(key)}">
  <td><span class="c"><span class="idx">{idx:03d}</span></span></td>
  <td><span class="c"><span class="iid">{_esc(i.id)}</span></span></td>
  <td><span class="c">{_item_state_html(i.status)}</span></td>
  <td><span class="c">{age_html}</span></td>
  <td><span class="c"><span class="holder">{holder}</span></span></td>
  <td class="ti"><a href="{href}">{_esc(i.title)}</a></td>
</tr>"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(workspace: A.Workspace, auth: WA.AuthConfig) -> FastAPI:
    app = FastAPI(title="amplifier-work-tracker", docs_url=None, redoc_url=None)
    app.add_middleware(AuthMiddleware, auth=auth)

    # --------------------------------------------------------------- health

    @app.get("/healthz")
    async def healthz():  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    # ----------------------------------------------------------------- auth

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):  # type: ignore[no-untyped-def]
        next_value = WA.validate_next_path(request.query_params.get("next"))
        error = request.query_params.get("error")
        mode_hint = (
            f"Sign in as <code>{_esc(WA.running_user())}</code> with your system password (PAM)."
            if auth.mode == "pam"
            else "Enter the site password."
        )
        username_field = (
            '<label for="username">Username</label>'
            '<input type="text" id="username" name="username" '
            f'value="{_esc(WA.running_user())}" required>'
            if auth.mode == "pam"
            else '<input type="hidden" name="username" value="operator">'
        )
        error_html = f'<div class="flash flash-error">{_esc(error)}</div>' if error else ""
        heading_style = (
            "font-family:var(--sans);font-size:24px;font-weight:500;"
            "color:var(--ink);margin:20px 0 4px"
        )
        body = f"""
        <h1 style="{heading_style}">Sign in</h1>
        <p class="subtle">{mode_hint}</p>
        {error_html}
        <form method="post" action="/login" style="max-width:340px;margin-top:16px">
          <input type="hidden" name="next" value="{_esc(next_value)}">
          {username_field}
          <label for="password">Password</label>
          <input type="password" id="password" name="password" required autofocus>
          <button type="submit">Sign in</button>
        </form>
        """
        return _page(request, "Sign in", body)

    @app.post("/login")
    async def login_submit(  # type: ignore[no-untyped-def]
        request: Request,
        username: str = Form(""),
        password: str = Form(...),
        next: str = Form("/"),
    ):
        identity = WA.check_credentials(auth.mode, username, password, auth)
        safe_next = WA.validate_next_path(next)
        if not identity:
            login_url = WA.build_login_redirect_url(safe_next)
            sep = "&" if "?" in login_url else "?"
            return RedirectResponse(
                url=f"{login_url}{sep}error=incorrect+credentials", status_code=303
            )
        resp = RedirectResponse(url=safe_next, status_code=303)
        cookie_value = WA.create_session_cookie(auth.secret, identity)
        resp.set_cookie(
            WA.SESSION_COOKIE_NAME,
            cookie_value,
            max_age=auth.ttl_seconds if auth.ttl_seconds > 0 else None,
            httponly=True,
            samesite="lax",
        )
        return resp

    @app.get("/auth/logout")
    async def logout():  # type: ignore[no-untyped-def]
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(WA.SESSION_COOKIE_NAME)
        return resp

    # ------------------------------------------------------------ dashboard

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):  # type: ignore[no-untyped-def]
        names = workspace.names()
        summaries = [A.project_summary(workspace, n) for n in names]

        if not names:
            body = (
                f"{_flash(request)}"
                f'<section class="sec heroic">{_hero_html(None, None, None)}</section>'
                '<div class="hr bleed"></div>'
                '<section class="sec"><div class="empty-state"><p>No projects yet. '
                "Create one below to get started.</p></div></section>"
                f'<section class="sec">{_create_project_form()}</section>'
            )
            sb = T.statusbar('<span class="s"><span class="dot on"></span>No projects yet</span>')
            return _page(request, "Dashboard", body, statusbar_html=sb)

        ordered = sorted(summaries, key=_dashboard_sort_key)
        winner = _global_oldest(summaries)
        oldest_item = None
        winner_name = None
        winner_age = None
        if winner:
            winner_name, winner_age = winner
            oldest_item = _oldest_ready_item(workspace.project(winner_name))

        scale_seconds = winner_age or 1.0

        buckets = _aggregate_buckets(summaries)

        ok = [s for s in summaries if s.status == "ok"]
        held_total = sum(s.held or 0 for s in ok)
        blocked_total = sum(s.blocked or 0 for s in ok)
        resolved_24h_total = sum(s.resolved_24h or 0 for s in ok)
        resolved_7d_total = sum(s.resolved_7d or 0 for s in ok)

        heartbeat = _heartbeat_html(buckets)
        ledger = _ledger_html(held_total, blocked_total, resolved_24h_total, resolved_7d_total)

        rows = "".join(_dashboard_row(s, scale_seconds) for s in ordered)
        table = f"""<table class="tbl dense">
          <colgroup><col><col style="width:232px"><col style="width:70px">
            <col style="width:70px"><col style="width:70px"><col style="width:78px">
            <col style="width:150px"><col style="width:150px"></colgroup>
          <thead><tr>
            <th>Queue</th>
            <th class="axis">Oldest unclaimed{T.axis_ruler_html(scale_seconds)}</th>
            <th class="r">Ready</th><th class="r">Items</th><th class="r">Held</th>
            <th class="r">Blocked</th><th class="gap">Status</th><th>Last activity</th>
          </tr></thead>
          <tbody>{rows}</tbody>
          {_dashboard_totals(summaries)}
        </table>"""

        broken = [s for s in summaries if s.status != "ok"]
        broken_foot = ""
        if broken:
            names_str = ", ".join(s.name for s in broken)
            broken_foot = (
                '<div class="foot"><span class="fm">Broken</span>'
                f"<span>{_esc(names_str)} cannot be read. Excluded from every total above, so the "
                f"workspace figures read {sum(s.total or 0 for s in ok)} items across {len(ok)} "
                "readable queues.</span></div>"
            )

        body = f"""
        {_flash(request)}
        <section class="sec heroic">{_hero_html(winner_age, winner_name, oldest_item)}</section>
        <div class="hr bleed"></div>
        <section class="sec tight">
          <div class="context">{heartbeat}<div class="ledgercol">{ledger}</div></div>
        </section>
        <div class="hr bleed"></div>
        <section class="sec tight">
          <div class="controls">
            {T.search_field("Filter queues by name or state")}
            <span class="count" id="qc">{len(summaries)} QUEUES</span>
          </div>
          {table}
          {broken_foot}
        </section>
        <div class="hr bleed"></div>
        <section class="sec">{_create_project_form()}</section>
        """
        sb = T.statusbar(
            f'<span class="s"><span class="dot on"></span>Sweep <b>healthy</b></span>'
            f'<span class="s">Oldest unclaimed <b class="am">{T.duration_words(winner_age)[0]}'
            f" {T.duration_words(winner_age)[1].lower()}</b></span>"
            if winner_age is not None
            else '<span class="s"><span class="dot on"></span>Sweep <b>healthy</b></span>',
            f'<span class="s">Held <b>{held_total}</b></span><a href="/">Refresh</a>',
        )
        return _page(
            request,
            "Dashboard",
            body,
            statusbar_html=sb,
            js=T.search_js(len(summaries), "QUEUES", "tbody tr[data-t]"),
        )

    @app.post("/projects")
    async def create_project(name: str = Form(...)):  # type: ignore[no-untyped-def]
        try:
            workspace.create(name)
        except A.BeadsError as e:
            return _redirect("/", error=_public_error_message(e))
        return _redirect("/", msg=f"created project '{name}'")

    # -------------------------------------------------------- project view

    @app.get("/projects/{name}", response_class=HTMLResponse)
    async def project_view(request: Request, name: str):  # type: ignore[no-untyped-def]
        status = request.query_params.get("status") or None
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        crumb = _crumb(("/", "All projects"), ("", name))
        try:
            bd = workspace.project(name)
        except A.BeadsError:
            return _page(
                request,
                name,
                _not_found_body(heading=name, back_href="/", back_label="back to dashboard"),
                crumb_html=_crumb(("/", "All projects")),
            )
        page_size = A.LIST_DEFAULT_LIMIT
        try:
            result = bd.list_bounded(status=status, offset=(page - 1) * page_size)
            total_pages = (
                max(1, math.ceil(result.total_count / page_size)) if result.total_count else 1
            )
            if page > total_pages:
                # A stale/hand-edited `?page=` past the real last page --
                # land on the actual last page instead of a confusingly
                # empty one whose own URL claims there should be more.
                page = total_pages
                result = bd.list_bounded(status=status, offset=(page - 1) * page_size)
        except A.BeadsError as e:
            body = (
                f"{_flash(request)}<h1>{_esc(name)}</h1>"
                f'<div class="flash flash-error">{_esc(_public_error_message(e))}</div>'
            )
            return _page(request, name, body, crumb_html=crumb)

        summary = A.project_summary(workspace, name)
        oldest_item = None
        if summary.status == "ok" and summary.oldest_unclaimed_age_seconds is not None:
            oldest_item = _oldest_ready_item(bd)

        status_options = "".join(
            f'<option value="{_esc(s)}"{" selected" if s == status else ""}>{_esc(s)}</option>'
            for s in A.STATUSES
        )

        rows = "".join(
            _item_row(name, i, result.offset + n + 1) for n, i in enumerate(result.items)
        )
        pagination_html = _pagination_html(name, status, page, total_pages, result)
        if result.items:
            table = f"""<table class="tbl">
              <colgroup><col style="width:46px"><col style="width:64px"><col style="width:82px">
                <col style="width:70px"><col style="width:130px"><col></colgroup>
              <thead><tr>
                <th>#</th><th>Id</th><th>State</th><th>Age</th><th>Holder</th><th>Title</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>"""
        elif status:
            table = (
                '<div class="empty-state"><p>No items match status '
                f"<code>{_esc(status)}</code>.</p>"
                f'<p><a href="/projects/{_esc(name)}">clear filter</a></p></div>'
            )
        else:
            table = '<div class="empty-state"><p>No items yet. Add the first one below.</p></div>'

        body = f"""
        {_flash(request)}
        <section class="sec">{_project_hero_html(name, summary, oldest_item)}</section>
        <div class="hr bleed"></div>
        <section class="sec tight">
          <div class="controls">
            {T.search_field("Search titles, ids, holders and state")}
            <select name="__status_filter" style="max-width:180px;height:44px"
                    onchange="location.href='/projects/{_esc(name)}'+(this.value?'?status='+this.value:'')">
              <option value="">(all statuses)</option>
              {status_options}
            </select>
            <span class="count" id="qc">{result.total_count} ITEMS</span>
          </div>
          {table}
          {pagination_html}
        </section>
        <div class="hr bleed"></div>
        <section class="sec">
          <div class="formsec">
            <span class="flegend">Add item</span>
            <form method="post" action="/projects/{_esc(name)}/items">
              <label for="title">Title</label>
              <input type="text" id="title" name="title" required>
              <label for="description">Description</label>
              <textarea id="description" name="description" rows="2"></textarea>
              <label for="acceptance">Acceptance criteria</label>
              <textarea id="acceptance" name="acceptance" rows="2"></textarea>
              <button type="submit">Add</button>
            </form>
          </div>
          <div class="formsec">
            <span class="flegend">Claim next ready item</span>
            <form method="post" action="/projects/{_esc(name)}/claim">
              <input type="hidden" name="mode" value="next">
              <label for="lane">Lane</label>
              <input type="text" id="lane" name="lane" value="{_esc(A.LANE_WORK)}">
              <label for="claim_actor">Actor</label>
              <input type="text" id="claim_actor" name="actor"
                     value="{_esc(_identity(request))}" required>
              <p class="field-hint">Claims the next open item in this lane and takes you to it.
                To claim a specific item instead, open it and use the Claim button there.</p>
              <button type="submit">Claim next</button>
            </form>
          </div>
          <div class="formsec danger">
            <span class="flegend">Danger zone</span>
            <a class="btn danger" href="/projects/{_esc(name)}/remove">Remove this
              project&hellip;</a>
          </div>
        </section>
        """
        held_display = summary.held if summary.status == "ok" else "\u2014"
        sb = T.statusbar(
            '<span class="s"><span class="dot on"></span>Sweep <b>healthy</b></span>'
            f'<span class="s">Held <b>{held_display}</b></span>',
            f'<a href="/projects/{_esc(name)}">Refresh</a>',
        )
        return _page(
            request,
            name,
            body,
            crumb_html=crumb,
            statusbar_html=sb,
            js=T.search_js(result.total_count, "ITEMS", "tbody tr[data-t]"),
        )

    @app.post("/projects/{name}/items")
    async def add_item(  # type: ignore[no-untyped-def]
        name: str,
        title: str = Form(...),
        description: str = Form(""),
        acceptance: str = Form(""),
    ):
        try:
            new_id = workspace.project(name).create(
                title,
                kind="task",
                tags=[A.LANE_WORK],
                description=description or None,
                acceptance=acceptance or None,
            )
        except A.BeadsError as e:
            return _redirect(f"/projects/{name}", error=_public_error_message(e))
        return _redirect(f"/projects/{name}/items/{new_id}", msg=f"added {new_id}")

    @app.post("/projects/{name}/claim")
    async def claim(  # type: ignore[no-untyped-def]
        name: str,
        mode: Literal["next", "id"] = Form("next"),
        actor: str = Form(...),
        lane: str = Form(A.LANE_WORK),
        item_id: str = Form(""),
    ):
        try:
            bd = workspace.project(name)
            if mode == "id":
                if not item_id:
                    return _redirect(
                        f"/projects/{name}", error="directed claim requires an item id"
                    )
                item = bd.claim_item(item_id, actor=actor)
            else:
                item = bd.claim_next(lane=lane, actor=actor)
        except A.BeadsError as e:
            # A directed claim already knows which item it was trying for --
            # send the failure back to that item's own page instead of the
            # listing, so context isn't lost. "next" mode has no item id to
            # return to, so it falls back to the project listing.
            target = (
                f"/projects/{name}/items/{item_id}"
                if mode == "id" and item_id
                else f"/projects/{name}"
            )
            return _redirect(target, error=_public_error_message(e))
        if item is None:
            return _redirect(f"/projects/{name}", error=f"no ready work in lane '{lane}'")
        # Land on the claimed item's own page -- the whole point of claiming
        # something is to start reading/working it, and everything needed
        # for that (description, acceptance criteria, a resolve control) now
        # lives there, not back on the listing.
        return _redirect(
            f"/projects/{name}/items/{item.id}",
            msg=f"{actor} claimed {item.id} ({item.title})",
        )

    # --------------------------------------------------------- item detail

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
                    heading=item_id,
                    back_href=f"/projects/{name}",
                    back_label=f"back to {name}",
                ),
                crumb_html=_crumb(("/", "All projects"), (f"/projects/{name}", name)),
            )

        identity_val = _esc(_identity(request))

        # ------------------------------------------------ contextual action
        # Exactly one action control, chosen by the item's own status --
        # never rendered for a status it doesn't apply to.
        if item.status == "open":
            action_html = f"""
            <div class="formsec">
              <span class="flegend">Claim this item</span>
              <form method="post" action="/projects/{_esc(name)}/claim">
                <input type="hidden" name="mode" value="id">
                <input type="hidden" name="item_id" value="{_esc(item.id)}">
                <label for="claim_actor">Actor</label>
                <input type="text" id="claim_actor" name="actor" value="{identity_val}" required>
                <button type="submit">Claim</button>
              </form>
            </div>
            """
        elif item.status == "held":
            action_html = f"""
            <div class="formsec">
              <span class="flegend">Resolve</span>
              <form method="post" action="/projects/{_esc(name)}/items/{_esc(item.id)}/resolve">
                <label for="reason">Resolution reason</label>
                <textarea id="reason" name="reason" rows="3" required></textarea>
                <label for="resolve_actor">Actor</label>
                <input type="text" id="resolve_actor" name="actor" value="{identity_val}" required>
                <button type="submit">Resolve</button>
              </form>
            </div>
            """
        else:
            # resolved / blocked / deferred -- no action applies. Absent,
            # not disabled-and-rendered: nothing to interact with here.
            action_html = ""

        # ------------------------------------------------------------ links
        links_html = ""
        if item.links:
            depends_on = [ln for ln in item.links if ln.get("direction") == "from"]
            required_by = [ln for ln in item.links if ln.get("direction") == "to"]

            def _link_items(entries: list[dict]) -> str:
                out = ""
                for ln in entries:
                    ln_id = ln.get("id")
                    if not ln_id:
                        continue
                    ln_type = ln.get("type") or "related"
                    ln_href = f"/projects/{_esc(name)}/items/{_esc(ln_id)}"
                    out += (
                        f'<li><a href="{ln_href}">{_esc(ln_id)}</a> '
                        f'<span class="muted">({_esc(ln_type)})</span></li>'
                    )
                return out

            if depends_on:
                links_html += (
                    '<h2 class="eyebrow" style="display:block;margin-top:30px">Depends on</h2>'
                    f'<ul class="links-list">{_link_items(depends_on)}</ul>'
                )
            if required_by:
                links_html += (
                    '<h2 class="eyebrow" style="display:block;margin-top:30px">Required by</h2>'
                    f'<ul class="links-list">{_link_items(required_by)}</ul>'
                )

        resolution_html = ""
        if item.status == "resolved" and item.resolution:
            resolution_html = (
                '<span class="eyebrow am" style="display:block;margin-top:30px">Resolution</span>'
                f'<div class="content-block">{_esc(item.resolution)}</div>'
            )

        description_html = (
            _esc(item.description)
            if item.description
            else '<span class="muted">No description provided.</span>'
        )
        acceptance_html = (
            _esc(item.acceptance)
            if item.acceptance
            else '<span class="muted">No acceptance criteria provided.</span>'
        )

        facts = [
            ("Queue", f'<a href="/projects/{_esc(name)}">{_esc(name)}</a>'),
            ("Kind", _esc(item.kind or "--")),
            ("Priority", _esc(str(item.priority) if item.priority is not None else "--")),
        ]
        owner = item.raw.get("owner")
        if owner:
            facts.append(("Reported by", _identity_html(str(owner))))
        facts_kv = "".join(
            f'<div><span class="k">{_esc(k)}</span><span class="v">{v}</span></div>'
            for k, v in facts
        )

        time_kv_parts = [
            ("Created", _abs_and_rel(item.created_at.isoformat() if item.created_at else None)),
            ("Updated", _abs_and_rel(item.updated_at.isoformat() if item.updated_at else None)),
        ]
        if item.status == "resolved" and item.closed_at:
            time_kv_parts.append(("Resolved", _abs_and_rel(item.closed_at.isoformat())))
        time_kv = "".join(
            f'<div><span class="k">{_esc(k)}</span><span class="v serif">{v}</span></div>'
            for k, v in time_kv_parts
        )

        held_chip = (
            f'<span class="chip">held by {_identity_html(item.holder)}</span>'
            if item.holder
            else ""
        )

        body = f"""
        {_flash(request)}
        <section class="sec">
          <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
            <span class="muted">{_esc(item.id)}</span>
            {_item_state_html(item.status)}
            {held_chip}
          </div>
          <h1 style="font-family:var(--sans);font-size:26px;font-weight:500;line-height:1.32;
                     letter-spacing:-.013em;color:var(--ink);max-width:900px;margin:12px 0 22px">
            {_esc(item.title)}</h1>
          <div class="kv">{facts_kv}</div>
          <div class="kv" style="margin-top:10px">{time_kv}</div>
        </section>
        <div class="hr bleed"></div>
        <section class="sec">
          <span class="eyebrow">Description</span>
          <div class="content-block">{description_html}</div>

          <span class="eyebrow" style="display:block;margin-top:30px">Acceptance criteria</span>
          <div class="content-block">{acceptance_html}</div>

          {resolution_html}
          {links_html}
          {action_html}
        </section>
        """
        return _page(
            request,
            f"{item.id} - {item.title}",
            body,
            crumb_html=_crumb(("/", "All projects"), (f"/projects/{name}", name), ("", item.id)),
        )

    @app.post("/projects/{name}/items/{item_id}/resolve")
    async def resolve(  # type: ignore[no-untyped-def]
        name: str, item_id: str, reason: str = Form(...), actor: str = Form(...)
    ):
        try:
            item = workspace.project(name).resolve(item_id, reason, actor=actor)
        except A.BeadsError as e:
            return _redirect(f"/projects/{name}/items/{item_id}", error=_public_error_message(e))
        return _redirect(f"/projects/{name}/items/{item.id}", msg=f"resolved {item.id}")

    # ------------------------------------------------------------ removal

    @app.get("/projects/{name}/remove", response_class=HTMLResponse)
    async def remove_confirm(request: Request, name: str):  # type: ignore[no-untyped-def]
        remove_heading_style = (
            "font-family:var(--sans);font-size:24px;font-weight:500;"
            "color:var(--ink);margin:20px 0 14px"
        )
        body = f"""
        {_flash(request)}
        <h1 style="{remove_heading_style}">Remove project '{_esc(name)}'</h1>
        <p class="subtle" style="max-width:640px">This permanently deletes the project's local
          directory AND its shared-server database. It is refused if any item is currently
          <strong style="color:var(--ink)">held</strong>. This cannot be undone.</p>
        <form method="post" action="/projects/{_esc(name)}/remove" style="margin-top:18px">
          <label for="confirm_name">Type the project name
            (<code>{_esc(name)}</code>) to confirm</label>
          <input type="text" id="confirm_name" name="confirm_name" required autocomplete="off">
          <button type="submit" class="danger">Permanently remove</button>
        </form>
        <p style="margin-top:14px">
          <a href="/projects/{_esc(name)}">&laquo; cancel, back to project</a></p>
        """
        return _page(
            request,
            f"Remove {name}",
            body,
            crumb_html=_crumb(("/", "All projects"), (f"/projects/{name}", name), ("", "Remove")),
        )

    @app.post("/projects/{name}/remove")
    async def remove_project(name: str, confirm_name: str = Form(...)):  # type: ignore[no-untyped-def]
        if confirm_name != name:
            return _redirect(
                f"/projects/{name}/remove",
                error="typed name did not match -- nothing was removed",
            )
        try:
            workspace.remove(name, force=True)
        except A.BeadsError as e:
            # Surfaces Workspace.remove's own refusal message verbatim (e.g.
            # "N item(s) currently HELD") -- already safe/specific, so it is
            # NOT run through `_public_error_message` (see that function's
            # docstring for why that's a deliberate, narrow choice).
            return _redirect(f"/projects/{name}/remove", error=str(e))
        return _redirect("/", msg=f"removed project '{name}'")

    return app


# ---------------------------------------------------------------------------
# Uvicorn entry point -- what `cli.py`'s `cmd_web` calls.
# ---------------------------------------------------------------------------


@dataclass
class WebServerConfig:
    host: str
    port: int
    auth: WA.AuthConfig


def run(workspace: A.Workspace, config: WebServerConfig) -> int:
    import uvicorn

    app = create_app(workspace, config.auth)
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


__all__ = ["AuthMiddleware", "WebServerConfig", "create_app", "run"]
