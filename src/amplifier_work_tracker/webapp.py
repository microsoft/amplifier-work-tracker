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
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from . import adapter as A
from . import custody as CU
from . import webauth as WA
from . import webpwa as PWA
from . import webtheme as T
from . import webtls as WT
from . import widgets as WD

logger = logging.getLogger(__name__)

# Exact-path auth-exempt set -- never prefix matching. See webauth's module
# docstring / muxplex's own incident for why a path *starting with* or
# *ending in* something is not a safe basis for an auth exemption.
#
# The PWA asset paths are exempt for the same reason muxplex exempts its
# own manifest/service-worker/icons: a browser must be able to fetch them
# (to show the install prompt, register the service worker, and paint the
# home-screen icon) before -- and independent of -- any login. The favicon
# and Open Graph card are exempt for the same shape of reason -- a browser
# tab / link-preview scraper fetches them unauthenticated too. None of
# these bytes are sensitive; the dashboard content itself stays behind PAM.
_AUTH_EXEMPT_PATHS = {
    "/login",
    "/auth/logout",
    "/healthz",
    "/manifest.json",
    "/sw.js",
    "/pwa-192.png",
    "/pwa-512.png",
    "/apple-touch-icon.png",
    "/favicon.ico",
    "/favicon-32.png",
    "/og-dark.png",
}

SESSION_TTL_SECONDS = 12 * 3600

# The overview and project-view pages sit on a monitor for hours, unattended --
# see webapp.py's module docstring's own framing and this repo's dashboard-monitor
# goal. Auto-refresh is what turns a calm 0/0/0 -> a real alarm into something
# that surfaces on its own instead of waiting for someone to click Refresh.
# 20s: frequent enough that a held/blocked item shows up "soon" on a screen
# nobody is actively watching, infrequent enough that it is not a meaningful
# load on the shared dolt server (this route already does a handful of `bd`
# reads per request; every real project on every tick, sized for a human
# glancing at a second monitor, not a tight polling loop).
#
# Deliberately NEVER passed to the item-detail edit page's `_page(...)` call
# (or any page with a live, unsaved form the auto-refresh's own in-flight-typing
# guard cannot see across a page it never loads on) -- see `_page`'s own
# docstring and T.auto_refresh_js's for the guard mechanism.
_AUTO_REFRESH_MS = 20_000


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


def _item_age_html(dt: datetime | None, *, alarm_eligible: bool = False) -> str:
    """Render `dt` (an already-parsed `Item` timestamp) with the SAME
    compact age vocabulary the item table's own Age column uses
    (`T.age_short`/`T.age_band_class`) -- one age format across the whole
    app, not the coarser "12m ago" phrasing `_relative_time` produces for
    a second, independent reading of the same kind of value. `None` gets
    the same empty-value glyph every other age reading in this module
    falls back to; a real timestamp is always one hover away via `title`,
    exactly like `_abs_and_rel`.

    Values under a minute read as "now" (matching the ready-queue/Beads-
    dashboard convention of a fresh item reading as immediate, not "0m")
    -- the one case `age_short` itself renders as `(\"0\", \"m\")`, reinterpreted
    here rather than changed in the shared helper, which every row in the
    item table also calls and must keep reading "0m" nowhere else.

    `age_band_class`'s top "a3" tier is the amber "this has been
    neglected" alarm -- legitimate ONLY for a genuinely ready/unclaimed
    item's own age (the browse row's Age column, gated by the caller;
    see webbrowse.py's `_row_html`, and the ready-queue-by-age widget),
    never for HISTORY (item-detail's Created/Updated/Resolved, the
    browse detail pane's own copy of the same, the activity timeline's
    per-event age). `alarm_eligible` defaults to False -- every history
    call site simply omits it -- and caps the band at "a2" (`--ink`, the
    same neutral tier a merely-old-but-not-yet-alarming reading already
    uses): a 9-day-old "Created" stamp on a calm, long-finished item is
    a fact, not an alarm, and must never render amber, per the
    firewall's "amber = alarm only" rule. Pass `alarm_eligible=True` only
    from a call site rendering a genuinely ready/unclaimed item's OWN
    age, where escalating to amber is the intended neglect signal."""
    if dt is None:
        return f'<span class="muted">{_EMPTY_GLYPH}</span>'
    seconds = max(0.0, (datetime.now(UTC) - dt).total_seconds())
    band = T.age_band_class(seconds)
    if band == "a3" and not alarm_eligible:
        band = "a2"  # history never escalates to the amber alarm tier
    value, unit = T.age_short(seconds)
    label = "now" if (value, unit) == ("0", "m") else f"{value}{unit}"
    return f'<span class="age {band}" title="{_esc(dt.isoformat())}">{_esc(label)}</span>'


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


# ---------------------------------------------------------------------------
# held-item custody reading -- claim-age + staleness, on real data only.
#
# `Item.meta["custody"]` (see `custody.py`) is OUR OWN liveness record, not
# bd's. `started_at` is when custody was first taken (a real claim-time
# signal -- what "held 4h" actually measures); `last_seen` is when it was
# last RENEWED, and is what decides staleness. Both come straight off the
# item this route already fetched -- no second `bd` call, no polling.
#
# Staleness is never re-derived here: `custody.reclaim_eligible` is called
# VERBATIM, the exact function `supervisor.reap_project` uses to decide what
# it actually reclaims. This is read/display only -- it never releases
# anything, renews anything, or otherwise touches the real reap policy; it
# just shows, honestly, what that policy would currently decide. Two paths
# make a hold "stale" for display, and both mean the same thing they mean to
# the real reaper: the renewal genuinely lapsed, or a *fresh* `awaiting_human`
# hold rode past the escalation ceiling (see `custody.reclaim_eligible`'s own
# docstring) -- `declared_state` never buys exemption from either, here or
# there.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustodyReading:
    """What this dashboard actually knows about one held item's custody --
    never fabricated. `age_seconds` is `None` only when there is truly no
    timestamp to show one from (no custody record AND no `updated_at`);
    `proxy=True` means `age_seconds` is `item.updated_at` (last bd write),
    NOT a true claim/renewal time -- see `_custody_reading`'s docstring for
    when that degradation happens and why it is named rather than hidden."""

    holder: str
    stale: bool
    reason: str
    declared_state: str
    age_seconds: float | None
    proxy: bool


def _custody_reading(item: A.Item, *, now: float | None = None) -> CustodyReading | None:
    """The one place a held item's custody record is turned into a display
    reading. Returns `None` for anything not currently `held` -- there is no
    custody signal to show for an open/blocked/deferred/resolved item, same
    guard `_item_row`'s holder cell already uses and for the same reason
    (bd's `assignee` outlives the hold; `status == "held"` is the only
    honest gate on "is this a CURRENT holder").

    Two real-data shapes, both handled honestly:
      - A real `custody` record exists (the normal path -- `work_claim`
        establishes one atomically). `age_seconds` is `started_at`'s age --
        total hold duration, a true signal. Staleness comes from
        `custody.reclaim_eligible` on the record's own `last_seen`.
      - No custody record at all (the item was claimed by something that
        bypassed `work_claim`/the CLI's custody-establishing path -- see the
        `claiming-work-safely` skill's "never touch bd directly" rule).
        `custody.reclaim_eligible(None)` already says this is reclaim-
        eligible NOW ("no custody record"), so it is rendered stale here
        too -- never silently "fine" just because we have less data. There
        is no true claim-time signal in this shape, so `age_seconds` falls
        back to `item.updated_at` (bd's own last-write time) with
        `proxy=True` -- an honestly-labeled proxy, never presented as if it
        were a real custody duration.
    """
    if item.status != "held":
        return None
    cust = item.meta.get(CU.CUSTODY_KEY) if isinstance(item.meta, dict) else None
    eligible, reason = CU.reclaim_eligible(cust, now=now)
    if isinstance(cust, dict) and cust.get("holder"):
        declared = str(cust.get("declared_state") or CU.STATE_WORKING)
        started = str(cust.get("started_at") or "")
        age_seconds = CU.age_seconds(started, now=now) if started else None
        proxy = False
    else:
        declared = CU.STATE_WORKING
        proxy = item.updated_at is not None
        age_seconds = (
            max(0.0, (now if now is not None else time.time()) - item.updated_at.timestamp())
            if item.updated_at is not None
            else None
        )
    return CustodyReading(
        holder=item.holder or "",
        stale=eligible,
        reason=reason,
        declared_state=declared,
        age_seconds=age_seconds,
        proxy=proxy,
    )


def _custody_html(reading: CustodyReading | None) -> str:
    """The compact `held <age> &middot; <holder>` reading (e.g. `held 4h
    &middot; agent-spark-1-106784`), amber and flagged only when the real
    reclaim policy (`custody.reclaim_eligible`, called by `_custody_reading`)
    says this hold is currently stale -- a fresh, actively-renewed hold
    stays neutral, exactly like any other quiet fact in this app (see
    webtheme.py's SIGNAL COLOURS comment: amber is spent on attention, never
    on good news). Returns "" for a non-held item (`reading is None`).

    An `awaiting_human`-declared hold that is still FRESH is rendered
    honestly, not as "paused" or "fine": the label carries a quiet note,
    on hover, that the TTL clock still runs -- `declared_state` suppresses
    the notification, never the staleness check (see `custody.py`'s module
    docstring)."""
    if reading is None:
        return ""
    holder_html = (
        _identity_html(reading.holder)
        if reading.holder
        else '<span class="muted">unknown holder</span>'
    )
    if reading.age_seconds is None:
        age_label = "held"
    else:
        value, unit = T.age_short(reading.age_seconds)
        age_label = "held now" if (value, unit) == ("0", "m") else f"held {value}{unit}"
    if reading.proxy:
        age_label += " (last update, no custody record)"
    label = f"{age_label} &middot; {holder_html}"
    if reading.stale:
        title = _esc(reading.reason or "custody is stale")
        return f'<span class="held-custody stale" title="{title}">{label}</span>'
    extra = ""
    if reading.declared_state == CU.STATE_AWAITING_HUMAN:
        note = "Suppresses the attention notification only -- the custody TTL clock still runs."
        extra = f' <span class="muted" title="{_esc(note)}">awaiting human</span>'
    return f'<span class="held-custody fresh">{label}</span>{extra}'


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
        # Subtle, not shouting -- a plain chrome link alongside Logout, same
        # visual weight, reachable from every authenticated page. `/setup`
        # itself is authenticated (see create_app), so this never appears
        # for a signed-out visitor who couldn't follow it anyway.
        segments.append('<a href="/setup">Setup</a>')
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


def _nav_actions_html(project: str | None) -> str:
    """The nav's right-hand action cluster (goal wtv3/components, B1): a
    search icon-button, a notifications ("bell") icon-button, and a
    "+ New" gradient-pill primary action -- see `T.top_bar`'s own
    `actions_html` slot and webtheme.py's `.nav-actions`/`.icon-btn` CSS.

    Search: a real, functional affordance, not decoration -- it focuses
    the on-page `#q` field (the SAME element `search_js`/`list_controls_js`
    already bind the `/` keyboard shortcut to on pages that have one; a
    harmless no-op via `?.focus()` on a page that doesn't).

    Bell: links to `/setup`, this app's one real notifications-adjacent
    settings surface (TLS/trust bootstrap plus, per PR #36, the ntfy
    alarm-push channel) -- never a fabricated notification centre this
    app doesn't have.

    "+ New": context-aware, never a button pointed at a form that isn't
    on the page it's rendered on. `project` given -> "+ New item",
    scrolling/linking to THAT project's own `#add-item` anchor
    (`project_view`'s real `POST /projects/{name}/items` form). `project
    is None` (the dashboard, or any project-less page) -> "+ New
    project", linking to the dashboard's own `#create-project` anchor.
    """
    search_btn = (
        '<button type="button" class="icon-btn" title="Search (press /)" '
        'aria-label="Search" onclick="var q=document.getElementById(\'q\');'
        'if(q){q.focus();}">' + T.ICONS["search"] + "</button>"
    )
    bell_btn = (
        '<a class="icon-btn" href="/setup" title="Notifications setup" '
        'aria-label="Notifications setup">' + T.ICONS["bell"] + "</a>"
    )
    if project:
        new_href = f"/projects/{quote(project)}#add-item"
        new_label = "New item"
    else:
        new_href = "/#create-project"
        new_label = "New project"
    new_btn = f'<a class="btn btn-new" href="{new_href}">+ {new_label}</a>'
    return search_btn + bell_btn + new_btn


def _page(
    request: Request,
    title: str,
    body: str,
    *,
    crumb_html: str = "",
    statusbar_html: str = "",
    js: str = "",
    auto_refresh_ms: int | None = None,
    sidebar_html: str = "",
    nav_project: str | None = None,
) -> HTMLResponse:
    """The one page shell every route renders through.

    `auto_refresh_ms`, when given, appends `T.auto_refresh_js` to the
    page's script -- a self-polling monitor that keeps the OVERVIEW and
    PROJECT-VIEW pages current without anyone touching Refresh (see
    `_AUTO_REFRESH_MS`'s own comment for why and for how often).

    Every caller decides for itself whether to pass it; there is no
    workspace-wide default here. In particular `item_detail` NEVER passes
    it -- that page is a live, unsaved-edit form (title/description/
    acceptance/design inputs), and no in-flight-typing guard is worth
    trusting over simply never shipping the poller to a page a silent
    DOM replacement could clobber. Omitting the parameter (its default,
    `None`) is itself the guard for every other non-monitor page (login,
    the remove confirmation form, item detail) -- the safest guard is not
    emitting the mechanism at all, not a client-side check.

    `sidebar_html`, when given (only the dashboard and `project_view`
    pass it -- see `_sidebar_html`), wraps `<main>` in `.pagegrid` so the
    project-navigation column sits beside the content instead of above
    it. Every other route keeps the plain, unwrapped `<main class="wrap">`
    it always had -- omitting the parameter (its default, `""`) is itself
    the "no sidebar" case, the same convention `auto_refresh_ms` already
    uses above.

    `nav_project`, when given, is the current project's name -- used to
    build the nav's "+ New item" action (see `_nav_actions_html`) pointing
    at THAT project's own add-item form. Omitted (its default, `None`) on
    project-less pages (the dashboard, login, setup, ...), where the nav
    instead offers "+ New project" against the dashboard's own create form.
    """
    top = T.top_bar(
        crumb_html=crumb_html,
        right_html=_identity_right(request),
        actions_html=_nav_actions_html(nav_project),
    )
    main = f'<main class="wrap" id="main">{body}</main>'
    if sidebar_html:
        main = f'<div class="pagegrid">{sidebar_html}{main}</div>'
    full_body = f"{top}{main}{statusbar_html}"
    combined_js = js + (T.auto_refresh_js(auto_refresh_ms) if auto_refresh_ms else "")
    return HTMLResponse(T.page(f"{title} \u00b7 amplifier-work-tracker", full_body, js=combined_js))


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
# sidebar navigation -- present on both the overview and every project page
# (see `_page`'s `sidebar_html` param). Every count below is read straight
# from the SAME `A.ProjectSummary` the dashboard's own ledger table and the
# per-project status tabs already compute -- never a second, independently
# derived number (the same discipline `_status_tab_counts` documents).
# ---------------------------------------------------------------------------


def _sidebar_open_total(s: A.ProjectSummary | None) -> tuple[int, int] | None:
    """(`open`, `total`) for one project, or `None` when it is unreadable
    (broken/mid-creation, or simply absent from the summaries this caller
    passed in) -- never a fabricated `0/0` standing in for a real project
    whose counts could not be read, matching `_status_tab_counts`'s own
    "no real counts, don't invent any" convention for the same shape of
    project. `open` is everything not yet resolved (`total - resolved`),
    the same set `_impairment_label`'s healthy branch already implies."""
    if s is None or s.status != A.STATUS_OK:
        return None
    total = s.total or 0
    resolved = s.resolved or 0
    return max(0, total - resolved), total


def _sidebar_alarm_class(s: A.ProjectSummary | None) -> str:
    """`\" alarm-cr\"`, `\" alarm-am\"`, or `\"\"` -- the SAME blocked-outranks-
    held escalation ordering `_TAB_ALARM_CLASS`/`_dashboard_row` already use,
    reused here rather than re-derived so a project's sidebar marker can
    never disagree with its own status tabs about which of the two fired."""
    if s is None or s.status != A.STATUS_OK:
        return ""
    if s.blocked:
        return " alarm-cr"
    if s.held:
        return " alarm-am"
    return ""


def _sidebar_html(names: list[str], summaries: list[A.ProjectSummary], current: str | None) -> str:
    """The left navigation column: a global \"All projects &mdash; N open\"
    roll-up (links to `/`) atop an alphabetical list of every project, each
    row showing its real `open/total` counts plus a subtle alarm marker
    when it has anything held or blocked right now. `current` (the project
    name being viewed, or `None` on the dashboard) marks exactly one row
    -- or the roll-up itself -- as the current page, never both.

    Collapses to a native checkbox-driven disclosure at narrow widths via
    CSS alone (see webtheme.py's `.sidebar` media query) -- nothing here
    needs to know the viewport; the same markup renders both states.
    """
    by_name = {s.name: s for s in summaries}
    total_open = sum(
        ot[0] for n in names if (ot := _sidebar_open_total(by_name.get(n))) is not None
    )
    rows = []
    for n in sorted(names):
        s = by_name.get(n)
        ot = _sidebar_open_total(s)
        badge = f"{ot[0]}/{ot[1]}" if ot is not None else "\u2014"
        # Spell the denominator out on hover so the `open/total` badge can
        # never be misread as another of the overview's counts (goal item 4:
        # one vocabulary). The label stays the compact `open/total` a scan
        # wants; the title carries the units.
        badge_title = f"{ot[0]} open of {ot[1]} items" if ot is not None else "counts unavailable"
        current_cls = " current" if n == current else ""
        aria = ' aria-current="page"' if n == current else ""
        rows.append(
            f'<li><a class="sb-row{current_cls}{_sidebar_alarm_class(s)}" '
            f'href="/projects/{_esc(n)}"{aria}>'
            '<span class="sb-dot"></span>'
            f'<span class="sb-name">{_esc(n)}</span>'
            f'<span class="sb-badge" title="{_esc(badge_title)}">{_esc(badge)}</span>'
            "</a></li>"
        )
    rollup_cls = " current" if current is None else ""
    rollup_aria = ' aria-current="page"' if current is None else ""
    n_projects = len(names)
    toggle_label = f"Projects ({n_projects})" if n_projects else "Projects"
    return f"""<nav class="sidebar" id="sidebar" aria-label="Projects">
  <input type="checkbox" id="sb-toggle" class="sb-toggle-input">
  <label for="sb-toggle" class="sb-toggle-label">{_esc(toggle_label)}</label>
  <div class="sb-body">
    <a class="sb-rollup{rollup_cls}" href="/"{rollup_aria}>
      <span class="eyebrow">All projects</span>
      <span class="sb-em">&mdash; <b>{total_open}</b> open</span>
    </a>
    <ul class="sb-list">{"".join(rows)}</ul>
  </div>
</nav>"""


# ---------------------------------------------------------------------------
# dashboard-specific rendering -- the A-Ledger overview: a restrained
# ready-count hero, the full-width "workspace by state" composition bar,
# the (unchanged) ready-queue-by-age heartbeat, throughput, and a
# per-project composition table.
#
# This retires the previous round's age-led hero (see git history for
# `_hero_html`/`_ledger_html` if that design is ever wanted again). Ready
# COUNT is the question an operator asks dozens of times a day -- "how
# much is waiting on me?" -- and answers it in one glance; three quiet
# 27px secondary readings (concentration / waiting 7d+ / custody) answer
# "is any of it rotting?" without competing with the hero for attention.
# Age is demoted to a supporting stat, never absent -- see
# `_secondary_readings_html`'s "Waiting 7d+" reading and the (unchanged)
# `_heartbeat_html` ready-queue-by-age histogram below.
# ---------------------------------------------------------------------------


def _dashboard_sort_key(s: A.ProjectSummary) -> tuple[int, float, str]:
    """READY-COUNT DESCENDING -- ready is the axis this overview is built
    around (see this module's own docstring above), so the queue table
    orders by it: the biggest ready backlog is the one most worth seeing
    first. Broken/creating queues sort FIRST regardless of count -- an
    alarm row must never be pushed below the fold by a healthy queue with
    a bigger ready number."""
    if s.status != "ok":
        return (0, 0.0, s.name)
    return (1, -float(s.ready or 0), s.name)


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


def _ledger_hero_html(ready_total: int | None, n_projects: int, burn_days: float | None) -> str:
    """The overview's restrained ready-count hero -- READY TO CLAIM, at
    `--fig-size-ledger` (62px), a deliberate 3.8x demotion from the
    previous round's 236px oldest-unclaimed-AGE hero. Ready COUNT answers
    "how much is waiting on me" in one glance; age is demoted to a
    supporting stat (see `_secondary_readings_html`'s "Waiting 7d+"), never
    absent.

    `ready_total is None` means "could not be measured" -- every project in
    the workspace is unreadable -- and renders an honest dash, never a
    fabricated 0. `n_projects == 0` (no projects exist at all) is a
    genuinely different, and genuinely honest, 0: rendered as the real
    number, with its own under-line."""
    if ready_total is None:
        return """
<div class="lead">
  <span class="eyebrow">Ready to claim</span>
  <div class="figrow"><span class="fig ledger none">\u2014</span></div>
  <div class="under">No queue could be read right now &mdash; see the banner above.</div>
</div>"""
    if n_projects == 0:
        under = "No projects yet."
    else:
        rate_clause = (
            f" &middot; <b>{burn_days:g}</b> days of work at today's measured rate"
            if burn_days is not None
            else " &middot; no measured throughput today"
        )
        queue_word = _pluralize(n_projects, "queue").split(" ", 1)[1]
        under = f"across <b>{n_projects}</b> {queue_word}{rate_clause}"
    return f"""
<div class="lead">
  <span class="eyebrow">Ready to claim</span>
  <div class="figrow"><span class="fig ledger">{ready_total}</span>\
<span class="figunit">items</span></div>
  <div class="under">{under}</div>
</div>"""


def _secondary_readings_html(
    concentration: tuple[str, int, float] | None,
    waiting7d_count: int,
    waiting7d_pct: float | None,
    oldest_waiting_days: int | None,
    oldest_waiting_href: str | None,
    held_total: int,
    blocked_total: int,
    *,
    workspace_last_activity: str | None = None,
    rendered_at: datetime | None = None,
) -> str:
    """The hero's quiet 27px readings (`.hstats`, pushed right via
    `margin-left:auto`, own font scale -- never competing with the hero):
    CONCENTRATION (the single biggest ready queue, so a workspace-wide
    total never hides one queue quietly drowning), WAITING 7D+ (the one
    age reading that survives the hero's demotion, amber only here --
    never on a good number), CUSTODY (held/blocked, real for every
    project, no instrumentation gap), and -- when both `workspace_last_activity`
    and `rendered_at` are supplied (A5; every pre-existing caller omits
    them and keeps the original three-tile output byte-for-byte) -- LAST
    ACTIVITY: a clear "Nh/Nm ago" reading that turns amber once it clears
    the SAME `_STALL_HOURS` threshold the verdict's own absence-alarm
    already uses, so this tile and the verdict line can never disagree
    about what counts as stale.

    Every argument is a real, already-honestly-computed value from the
    route -- `None` where a reading genuinely cannot be formed (no ready
    items anywhere to concentrate), never a fabricated placeholder."""
    if concentration is None:
        conc_n, conc_sub = "\u2014", "nothing ready to concentrate"
    else:
        name, n, pct = concentration
        conc_n = str(n)
        conc_sub = (
            f'in <a href="/projects/{_esc(name)}">{_esc(name)}</a><br>{pct:.0f}% of the ready queue'
        )

    waiting_cls = "n am" if waiting7d_count else "n"
    if waiting7d_count == 0:
        waiting_sub = "nothing has waited a week"
    else:
        oldest_clause = ""
        if oldest_waiting_days is not None and oldest_waiting_href:
            oldest_clause = f', oldest <a href="{oldest_waiting_href}">{oldest_waiting_days}d</a>'
        pct_clause = f"{waiting7d_pct:.0f}% of the ready queue" if waiting7d_pct is not None else ""
        waiting_sub = f"{_pluralize(waiting7d_count, 'item')}{oldest_clause}<br>{pct_clause}"

    if held_total == 0 and blocked_total == 0:
        custody_note = "nothing is stuck"
    elif blocked_total:
        custody_note = f"{_pluralize(blocked_total, 'item')} blocked, needs a look"
    else:
        custody_note = "in progress"
    custody_sub = f"held &middot; {blocked_total} blocked<br>{custody_note}"

    # A5 -- Last activity: only rendered when the route supplies BOTH the
    # timestamp and the render instant to measure it against (every other
    # caller omits both and keeps the original three-tile output verbatim).
    activity_tile = ""
    if rendered_at is not None:
        hours = _hours_since(workspace_last_activity, rendered_at)
        if hours is None:
            act_cls, act_n, act_sub = "n", "\u2014", "no recorded activity yet"
        else:
            stale = hours >= _STALL_HOURS
            act_cls = "n am" if stale else "n"
            act_n = _relative_time(workspace_last_activity)
            act_sub = (
                f"idle {int(hours)}h &middot; past the {int(_STALL_HOURS)}h stall floor"
                if stale
                else "within the normal working window"
            )
        activity_tile = (
            '<div class="s"><span class="k">Last activity</span>'
            f'<span class="{act_cls}">{act_n}</span>'
            f'<span class="sub">{act_sub}</span></div>'
        )

    return f"""
<div class="hstats">
  <div class="s"><span class="k">Concentration</span>
    <span class="n">{conc_n}</span>
    <span class="sub">{conc_sub}</span></div>
  <div class="s"><span class="k">Waiting 7d+</span>
    <span class="{waiting_cls}">{waiting7d_count}</span>
    <span class="sub">{waiting_sub}</span></div>
  <div class="s"><span class="k">Custody</span>
    <span class="n">{held_total}</span>
    <span class="sub">{custody_sub}</span></div>
  {activity_tile}
</div>"""


_STATE_ORDER = ("ready", "held", "blocked", "deferred", "resolved")
_STATE_FILL = {
    "ready": "var(--st-ready)",
    "held": "var(--amber)",  # same hue as `.state.warnv` elsewhere -- held
    # is ATTENTION, not alarm, not good news; never a second, competing hue.
    "blocked": "var(--crimson)",  # same hue as `.st-blkd` -- escalation.
    "deferred": "var(--st-deferred)",
    "resolved": "var(--st-resolved)",
}

# The three states that must never render as a mere hairline once they go
# non-zero -- see `_state_bar_html`'s own comment for why the hue alone
# (already correct: held/blocked already reuse the app's amber/crimson
# escalation hues) is not enough on a workspace with hundreds of items.
_ALARM_STATES = frozenset({"held", "blocked", "deferred"})
# A real alarm segment's floor width -- bigger than the calm seam's 3px
# (`--st-empty`, see webtheme.py), small enough it never dominates a
# genuinely large count (flex-grow still wins once the real proportional
# width would exceed this floor; this only ever WIDENS a would-be sliver).
_ALARM_MIN_PX = 16


def _state_counts(s: A.ProjectSummary) -> dict[str, int]:
    """The fixed five-slot state breakdown for one project, `0` (never
    `None`) for every field -- callers must only pass an `ok` summary."""
    return {
        "ready": s.ready or 0,
        "held": s.held or 0,
        "blocked": s.blocked or 0,
        "deferred": s.deferred or 0,
        "resolved": s.resolved or 0,
    }


def _state_bar_html(counts: dict[str, int]) -> str:
    """The 'hard-drive-storage-split-by-type' composition bar, fixed
    five-slot order, always -- shared by the full-width workspace bar and
    every table row's mini bar (`.comp .sbar` / `.tbl td.mb .sbar` set the
    height only; this draws the same object either way, so the two can
    never visually disagree). A zero-count state renders as a 3px
    `--st-empty` seam rather than nothing, so the eye learns the five slots
    and a segment appearing for the first time (a queue's first-ever HELD
    item) is instantly legible -- see webtheme.py's module comment for why
    a hollow outline was rejected in favour of a solid, dimmed seam, and
    for why the seam's fill is its own token rather than a reuse of the
    app's generic `--rule-hi` divider colour (too close to the fills a
    seam is most often rendered directly beside).

    ALARM floor -- a non-zero held/blocked/deferred segment (`_ALARM_STATES`)
    additionally carries a `min-width:{_ALARM_MIN_PX}px` alongside its
    proportional `flex-grow`. Colour alone (held/blocked already reuse the
    app's amber/crimson escalation hues verbatim) is not enough on a
    workspace with hundreds of items: a real single HELD item among them
    would otherwise be allocated a sub-pixel sliver of flex-grow and
    render as a functionally invisible hairline -- the opposite of "catches
    your eye from across the room." The floor only ever WIDENS a
    would-be-tiny segment; a genuinely large count still gets its full
    proportional width once that exceeds the floor. Ready/resolved never
    get this floor -- they are not alarm states, and in a real workspace
    they are rarely tiny enough to need one."""
    parts = []
    for key in _STATE_ORDER:
        n = counts[key]
        if n > 0:
            style = f"flex:{n} 1 0;background:{_STATE_FILL[key]}"
            if key in _ALARM_STATES:
                style += f";min-width:{_ALARM_MIN_PX}px"
            parts.append(f'<i style="{style}"></i>')
        else:
            parts.append('<span class="seam"></span>')
    return f'<div class="sbar">{"".join(parts)}</div>'


def _state_legend_html(counts: dict[str, int]) -> str:
    """The workspace bar's legend -- swatch + count + label per state, in
    the SAME fixed order the bar draws them. A zero count still shows its
    real number (a zero IS a reading, never whispered to invisibility),
    just in the quieter `.n.z` tone -- the "alarm lamp present and
    switched off" convention: every state keeps its slot, visibly, even
    at zero. The swatch uses the SAME `--st-empty` token the bar's own
    zero-count seam uses (`_state_bar_html`), never `--rule-hi` -- one
    shared "this slot is off" colour for both, not two that could drift
    apart."""
    items = []
    for key in _STATE_ORDER:
        n = counts[key]
        swatch = _STATE_FILL[key] if n else "var(--st-empty)"
        cls = "n" if n else "n z"
        items.append(
            f'<div class="li"><span class="sw" style="background:{swatch}"></span>'
            f'<span class="{cls}">{n}</span><span class="l">{key}</span></div>'
        )
    return f'<div class="legend">{"".join(items)}</div>'


def _workspace_composition_html(counts: dict[str, int], total: int) -> str:
    """ "Workspace by state" -- the full-width centrepiece the user asked
    for verbatim: "like a hard-drive-storage-split-by-type bar". Zero-value
    states (held/blocked/deferred at 0, the common case on a calm
    workspace) still render as a visible seam + a dimmed legend swatch --
    never absent, never a giant celebratory "0"."""
    pct_resolved = round(counts["resolved"] / total * 100) if total else 0
    bar = _state_bar_html(counts)
    legend = _state_legend_html(counts)
    item_word = _pluralize(total, "item").split(" ", 1)[1]
    return f"""
<div class="comp">
  <div class="chead">
    <span class="eyebrow">Workspace by state</span>
    <span class="rt">empty states keep their slot as a seam &middot; {total} {item_word} \
&middot; <b>{pct_resolved}%</b> resolved</span>
  </div>
  {bar}
  {legend}
</div>"""


def _attention_signal_html(held: int, blocked: int, deferred: int, held_stale: int = 0) -> str:
    """A per-project attention banner: "N items need attention", rendered ONLY
    when the project actually has something to flag (`held + blocked +
    deferred > 0`) -- absent entirely, not a dimmed zero, when calm.

    Still used by the per-PROJECT page (`project_view`) as its own attention
    banner. The OVERVIEW no longer renders this; it uses the ranked
    needs-you queue + verdict line below instead (goal wtv2/overview), which
    ranks across projects rather than summing one project's raw counts.

    Reuses the app's existing `.flash` vocabulary -- `flash-error` (crimson)
    when anything is BLOCKED (the more severe case, same escalation ordering
    `_dashboard_row` uses), `flash-msg` (amber) when only held/deferred are
    nonzero. Both are already measured against `--ground` for contrast, so
    this needs no new contrast check of its own.

    `held_stale` (default 0) is the SUBSET of `held` currently reclaim-
    eligible per `custody.reclaim_eligible` -- never additive to the total,
    since a stale hold is still one held item. Rendered as a parenthetical
    on the "held" clause only when nonzero ("3 items held (1 stale)"), never
    a dimmed "(0 stale)". Stays within the SAME amber tier as a plain held
    clause -- a stale hold does not escalate to crimson; only a genuinely
    BLOCKED item does.
    """
    total = held + blocked + deferred
    if total <= 0:
        return ""
    parts = []
    if blocked:
        parts.append(f"{_pluralize(blocked, 'item')} blocked")
    if held:
        held_clause = f"{_pluralize(held, 'item')} held"
        if held_stale:
            held_clause += f" ({_pluralize(held_stale, 'stale', 'stale')})"
        parts.append(held_clause)
    if deferred:
        parts.append(f"{_pluralize(deferred, 'item')} deferred")
    cls = "flash-error" if blocked else "flash-msg"
    return (
        f'<div class="flash {cls}" role="alert">'
        f"<strong>{total}</strong> {_pluralize(total, 'item')} need attention "
        f"&mdash; {', '.join(parts)}.</div>"
    )


# ---------------------------------------------------------------------------
# The "needs-you" overview: a verdict line, a RANKED cross-project attention
# queue, and a dispatch affordance -- the answer to "is anything wrong, and
# what first?" rather than "how many items exist." Everything below reads
# ONLY the counts `project_summary` already computed (custody-TTL breach via
# `held_stale`, stale blocker via `blocked_stale`, genuine blocked, aged
# waiting via `ready_age_buckets["7+"]`) -- no second `bd` call, no second
# derivation of a number rendered elsewhere on the page.
#
# Design firewall (goal wtv2/overview): the two reserved status hues are the
# ONLY colors that carry meaning -- amber = ALARM, crimson = BLOCKED. A calm
# screen shows neither. State is never color-only: every condition pairs its
# hue with an icon/shape + text (via `T.state_html`, kind "warn"=amber /
# "bad"=crimson). The verdict line is flat data-ink, neutral when calm; the
# gloss license does NOT travel to it.
# ---------------------------------------------------------------------------

# How long the workspace may show no measurable movement before "calm" is
# reclassified as "stalled" -- a first-class absence alarm, so a dead/idle
# fleet never renders as a serene "all clear." Overridable for tests/tuning.
_STALL_HOURS = float(os.environ.get("AMPLIFIER_WORK_TRACKER_STALL_HOURS", "12"))

# The four attention conditions, in the goal's ranked order of urgency:
# custody-TTL breach > stale blocker > genuine blocked > age. Lower priority
# integer = more urgent = sorts first. Each carries the reserved status hue
# it renders in ("warn" = amber alarm, "bad" = crimson blocked).
_COND_CUSTODY = 0
_COND_STALE_BLOCKER = 1
_COND_BLOCKED = 2
_COND_AGED = 3
_COND_KIND = {
    _COND_CUSTODY: "warn",
    _COND_STALE_BLOCKER: "bad",
    _COND_BLOCKED: "bad",
    _COND_AGED: "warn",
}
_COND_LABEL = {
    _COND_CUSTODY: "custody lapsed",
    _COND_STALE_BLOCKER: "needlessly blocked",
    _COND_BLOCKED: "blocked",
    _COND_AGED: "waiting 7d+",
}


@dataclass(frozen=True)
class _Condition:
    """One live attention condition on one project: which of the four kinds,
    how many items, and how long it has been true (`since_seconds`, `None`
    when no honest duration exists for this kind)."""

    cond: int
    count: int
    since_seconds: float | None


@dataclass(frozen=True)
class _Attention:
    """One project that currently needs a human, with every live condition on
    it (already sorted most-urgent-first). `primary` is that first condition
    -- it drives the row's rank, left-bar hue, and lead icon. `has_blocked`
    records whether any crimson (blocked) condition is present, so the fleet
    verdict can escalate to crimson on real evidence."""

    project: str
    conditions: tuple[_Condition, ...]

    @property
    def primary(self) -> _Condition:
        return self.conditions[0]

    @property
    def total(self) -> int:
        return sum(c.count for c in self.conditions)

    @property
    def has_blocked(self) -> bool:
        return any(c.cond in (_COND_STALE_BLOCKER, _COND_BLOCKED) for c in self.conditions)


def _attention_for(s: A.ProjectSummary) -> _Attention | None:
    """Build one project's `_Attention`, or `None` when nothing needs a human
    there. Reads only the fields `project_summary` already computed; a
    non-`ok` project has `None` counts and so surfaces no condition here
    (broken/creating projects are flagged by the impairment banner, a
    different, louder channel). Conditions are returned most-urgent-first."""
    if s.status != A.STATUS_OK:
        return None
    custody = s.held_stale or 0
    sblock = s.blocked_stale or 0
    gblock = max(0, (s.blocked or 0) - sblock)
    aged = (s.ready_age_buckets or {}).get("7+", 0)
    conds: list[_Condition] = []
    if custody:
        conds.append(_Condition(_COND_CUSTODY, custody, s.held_stale_oldest_age_seconds))
    if sblock:
        conds.append(_Condition(_COND_STALE_BLOCKER, sblock, None))
    if gblock:
        conds.append(_Condition(_COND_BLOCKED, gblock, None))
    if aged:
        conds.append(_Condition(_COND_AGED, aged, s.oldest_unclaimed_age_seconds))
    if not conds:
        return None
    conds.sort(key=lambda c: c.cond)
    return _Attention(project=s.name, conditions=tuple(conds))


def _attention_entries(summaries: list[A.ProjectSummary]) -> list[_Attention]:
    """The ranked cross-project needs-you queue. Ordered by the goal's real-
    urgency ranking -- each project by its most-urgent condition (custody-TTL
    breach > stale blocker > blocked > age), ties broken by how much is
    stuck, then by how long, then by name -- so the "N projects in alarm at
    once" moment is an ORDERED queue, never a flat undifferentiated list."""
    entries = [a for s in summaries if (a := _attention_for(s)) is not None]
    entries.sort(
        key=lambda a: (
            a.primary.cond,
            -a.total,
            -(a.primary.since_seconds or 0.0),
            a.project,
        )
    )
    return entries


def _dur_label(seconds: float) -> str:
    """A compact age like `5d` / `3h` / `12m`, in the SAME vocabulary the
    item table's Age column uses (`T.age_short`); sub-minute reads `now`."""
    value, unit = T.age_short(max(0.0, seconds))
    return "now" if (value, unit) == ("0", "m") else f"{value}{unit}"


def _since_iso(rendered_at: datetime, seconds: float | None) -> str | None:
    """The ISO instant a condition became true, `rendered_at - seconds` --
    the machine-readable `data-since` anchor that makes time-to-notice
    computable. `None` (never a fabricated stamp) when the condition carries
    no honest duration."""
    if seconds is None:
        return None
    return (rendered_at - timedelta(seconds=seconds)).isoformat()


def _condition_chip(c: _Condition, rendered_at: datetime) -> str:
    """One condition rendered as an icon+shape+text marker (`T.state_html`, so
    it is legible beyond hue alone) plus its count, and -- when the condition
    carries an honest duration -- a quiet `for {age}` with a `data-since`
    time-to-notice anchor."""
    label = f"{_COND_LABEL[c.cond]} \u00b7 {c.count}"
    marker = T.state_html(_COND_KIND[c.cond], label)
    since_iso = _since_iso(rendered_at, c.since_seconds)
    dur = ""
    if c.since_seconds is not None and since_iso is not None:
        word = "oldest" if c.cond == _COND_AGED else "for"
        dur = (
            f'<span class="nfor" data-since="{_esc(since_iso)}">'
            f"{word} {_esc(_dur_label(c.since_seconds))}</span>"
        )
    return f'<span class="ncond">{marker}{dur}</span>'


def _needs_you_html(entries: list[_Attention], rendered_at: datetime) -> str:
    """The ranked needs-you queue: one glass-chrome row per project (flat-ink
    content), left bar + lead icon in the primary condition's reserved hue,
    every live condition shown as its own coloured marker, and a dispatch
    verb (`\u2192 open {project}`) pointing where to send the next agent.
    Absent entirely when nothing needs a human -- the verdict/absence line
    above carries the calm state, so there is no empty "0 rows" table here."""
    if not entries:
        return ""
    rows = []
    for a in entries:
        p = a.primary
        sev = "cr" if p.cond in (_COND_STALE_BLOCKER, _COND_BLOCKED) else "am"
        lead = T.state_html(_COND_KIND[p.cond], "")
        chips = "".join(_condition_chip(c, rendered_at) for c in a.conditions)
        rows.append(
            f'<li class="needs-row sev-{sev}">'
            f'<span class="nlead">{lead}</span>'
            f'<a class="nproj" href="/projects/{_esc(a.project)}">{_esc(a.project)}</a>'
            f'<span class="nconds">{chips}</span>'
            f'<a class="ndispatch" href="/projects/{_esc(a.project)}">'
            f"\u2192 open {_esc(a.project)}</a>"
            "</li>"
        )
    return (
        '<div class="needs">'
        '<div class="nhead"><span class="eyebrow">Needs you \u2014 ranked</span>'
        '<span class="nsub">most urgent first \u00b7 custody &gt; blocked &gt; aging</span></div>'
        f'<ul class="needs-list">{"".join(rows)}</ul>'
        "</div>"
    )


def _hours_since(ts: str | None, now: datetime) -> float | None:
    """Hours since an ISO timestamp, or `None` when there is nothing to
    measure from -- the honest gap `project_activity`/`_relative_time`
    already draw, reused here so an absence alarm never fabricates a
    duration."""
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600.0


# Verdict levels -> the ONE sentence's meaning + reserved hue. `clear` is
# neutral flat ink (no status hue at all); `idle`/`alarm` are amber; `blocked`
# is crimson. A calm fleet is `clear`; a fleet with NOTHING running while work
# waits is `idle` (a first-class absence alarm, never a serene "all clear").
_VERDICT_CLEAR = "clear"
_VERDICT_IDLE = "idle"
_VERDICT_ALARM = "alarm"
_VERDICT_BLOCKED = "blocked"


def _verdict(
    entries: list[_Attention],
    *,
    ready_total: int,
    held_total: int,
    resolved_24h_total: int,
    n_measurable: int,
    workspace_last_activity: str | None,
    now: datetime,
) -> tuple[str, str, str]:
    """The one-sentence verdict: `(level, keyword, detail)`.

    A verdict, not a statistic. When something needs a human it says how many
    projects and why; when nothing does, it distinguishes a genuinely calm
    fleet from a DEAD one -- `held == 0` while work waits is `FLEET IDLE`
    (amber), never `ALL CLEAR`. Zero throughput today and no movement in
    `_STALL_HOURS` are first-class absence alarms too, so an idle or stalled
    fleet can never wear a serene all-clear.
    """
    if entries:
        level = _VERDICT_BLOCKED if any(a.has_blocked for a in entries) else _VERDICT_ALARM
        n = len(entries)
        keyword = "1 NEEDS YOU" if n == 1 else f"{n} NEED YOU"
        totals = {c: 0 for c in _COND_LABEL}
        for a in entries:
            for cond in a.conditions:
                totals[cond.cond] += cond.count
        parts = [f"{totals[cond]} {_COND_LABEL[cond]}" for cond in sorted(totals) if totals[cond]]
        return level, keyword, " \u00b7 ".join(parts)

    # -- no project needs a human: is the fleet calm, or dead? --
    hours_idle = _hours_since(workspace_last_activity, now)
    no_recent = hours_idle is not None and hours_idle >= _STALL_HOURS
    zero_throughput = n_measurable > 0 and resolved_24h_total == 0

    if ready_total > 0 and held_total == 0:
        detail = f"{_pluralize(ready_total, 'item')} ready, nothing in progress"
        if zero_throughput:
            detail += " \u00b7 0 resolved today"
        elif no_recent:
            detail += f" \u00b7 last movement {_relative_time(workspace_last_activity)}"
        return _VERDICT_IDLE, "FLEET IDLE", detail

    if ready_total > 0 and no_recent:
        hh = int(hours_idle) if hours_idle is not None else 0
        detail = f"no movement in {hh}h \u00b7 {_pluralize(ready_total, 'item')} ready"
        if zero_throughput:
            detail += " \u00b7 0 resolved today"
        return _VERDICT_IDLE, "STALLED", detail

    if ready_total == 0 and held_total == 0:
        return _VERDICT_CLEAR, "ALL CLEAR", "no open work anywhere"
    parts = []
    if held_total:
        parts.append(f"{_pluralize(held_total, 'item')} in progress")
    if ready_total:
        parts.append(f"{ready_total} ready")
    return _VERDICT_CLEAR, "ALL CLEAR", ", ".join(parts) + " \u2014 nothing stuck"


def _verdict_html(level: str, keyword: str, detail: str, now: datetime) -> str:
    """The verdict line, FLAT data-ink -- no glass, no gradient (the gloss
    license does not travel here). Neutral when calm; the reserved hue
    (amber `idle`/`alarm`, crimson `blocked`) appears ONLY when the alarm is
    real, on the icon + keyword + a hairline accent. The `data-rendered-at`
    stamp + visible "as of" is the time-to-notice/act anchor (goal item 5):
    every duration on this page is measured against this one instant."""
    kind = {
        _VERDICT_CLEAR: "ok",
        _VERDICT_IDLE: "warn",
        _VERDICT_ALARM: "warn",
        _VERDICT_BLOCKED: "bad",
    }.get(level, "ok")
    icon = T.state_html(kind, "")
    as_of = now.strftime("%H:%M UTC")
    return (
        f'<section class="sec tight verdict-sec">'
        f'<div class="verdict v-{_esc(level)}" role="status">'
        f'<span class="vicon">{icon}</span>'
        f'<span class="vword">{_esc(keyword)}</span>'
        f'<span class="vdetail">{_esc(detail)}</span>'
        f'<span class="vasof" data-rendered-at="{_esc(now.isoformat())}">as of {_esc(as_of)}</span>'
        "</div></section>"
    )


def _dispatch_pick(summaries: list[A.ProjectSummary]) -> A.ProjectSummary | None:
    """Which project most warrants the NEXT agent -- surfaced from inputs the
    app already computes: aged backlog (`ready_age_buckets["7+"]`), ready
    depth, and oldest-waiting age (concentration + waiting-7d+ + ready-by-age,
    the goal's named inputs). Prefers a queue whose work is rotting (7d+
    items) and deep, oldest-first. `None` when nothing is ready anywhere --
    there is nothing to dispatch. No drag-to-change-state kanban: this reads
    the queue, it never mutates custody."""
    ranked = [s for s in summaries if s.status == A.STATUS_OK and (s.ready or 0) > 0]
    if not ranked:
        return None
    return max(
        ranked,
        key=lambda s: (
            (s.ready_age_buckets or {}).get("7+", 0),
            s.ready or 0,
            s.oldest_unclaimed_age_seconds or 0.0,
        ),
    )


def _dispatch_html(summaries: list[A.ProjectSummary]) -> str:
    """The dispatch affordance: "where do I point the next agent?" plus the
    verb. Reads the ready queue only (never mutates), so it composes with
    machine-owned custody instead of fighting it. Absent when nothing is
    ready to pick up."""
    pick = _dispatch_pick(summaries)
    if pick is None:
        return ""
    ready = pick.ready or 0
    bits = [f"{_pluralize(ready, 'item')} ready"]
    aged = (pick.ready_age_buckets or {}).get("7+", 0)
    if aged:
        bits.append(f"{aged} waiting 7d+")
    if pick.oldest_unclaimed_age_seconds:
        bits.append(f"oldest {_dur_label(pick.oldest_unclaimed_age_seconds)}")
    detail = " \u00b7 ".join(bits)
    return (
        '<div class="dispatch">'
        '<span class="eyebrow">Dispatch next</span>'
        f'<span class="dtext">Point the next agent at '
        f'<a href="/projects/{_esc(pick.name)}">{_esc(pick.name)}</a> \u2014 {detail}</span>'
        f'<a class="dbtn" href="/projects/{_esc(pick.name)}">\u2192 claim next in '
        f"{_esc(pick.name)}</a>"
        "</div>"
    )


# `value` is the `?status=` query value each tab links to (`None` for ALL --
# no status param at all); `key` looks up this tab's count below. Ready's
# `key` reads "ready" (matching `ProjectSummary.ready`) even though the
# real filter value underneath is bd's "open" -- the tab is labelled the
# way a person reads the queue, not the way bd spells the status.
_STATUS_TABS: tuple[tuple[str | None, str, str], ...] = (
    (None, "all", "All"),
    ("open", "ready", "Ready"),
    ("held", "held", "Held"),
    ("blocked", "blocked", "Blocked"),
    ("deferred", "deferred", "Deferred"),
    ("resolved", "resolved", "Resolved"),
)

# Only HELD and BLOCKED turn their reserved escalation colour when
# non-zero -- the SAME amber/crimson hues `_STATE_FILL`/`.st-held`/
# `.st-blkd` already use for these two statuses elsewhere in this app.
# Ready/Resolved/Deferred/All stay neutral no matter their count: a large,
# healthy ready backlog is not something to alarm-colour.
_TAB_ALARM_CLASS = {"held": "am", "blocked": "cr"}


def _status_tab_counts(summary: A.ProjectSummary) -> dict[str, int]:
    """Real per-project counts keyed by `_STATUS_TABS`' tab keys -- reuses
    the EXACT fields `project_summary` already computed for this page; no
    second, independently-derived count is taken anywhere in this
    function. Every field is `0` (never fabricated) when the project
    itself is unreadable (mid-creation/broken) -- see `ProjectSummary`'s
    own docstring for why those states carry `None` counts."""
    if summary.status != A.STATUS_OK:
        return dict.fromkeys(("all", "ready", "held", "blocked", "deferred", "resolved"), 0)
    return {
        "all": summary.total or 0,
        "ready": summary.ready or 0,
        "held": summary.held or 0,
        "blocked": summary.blocked or 0,
        "deferred": summary.deferred or 0,
        "resolved": summary.resolved or 0,
    }


def _tab_href(name: str, value: str | None, q: str) -> str:
    """`?status=`/`q=` for one status tab -- an active search carries
    through unchanged, the same way the existing pagination/clear-search
    links already preserve it."""
    parts = []
    if value:
        parts.append(f"status={quote(value)}")
    if q:
        parts.append(f"q={quote(q)}")
    return f"/projects/{_esc(name)}" + (f"?{'&'.join(parts)}" if parts else "")


def _status_tabs_html(name: str, status: str | None, q: str, counts: dict[str, int]) -> str:
    """The per-project status-tab counter row: one server-linked tab per
    status plus ALL, each showing this project's REAL count. A zero count
    stays visible, dimmed (`.tcount.z`) -- the same "lamp present, switched
    off" convention `_state_legend_html` already uses -- so the full set
    of statuses is legible even on a project with nothing held/blocked/
    deferred right now, rather than a shorter row that silently omits them.

    Every tab is a plain `<a href="?status=...">`; clicking one is an
    ordinary navigation the existing route already handles (`status =
    request.query_params.get("status")`) -- no new client-side filtering
    logic anywhere, and the existing free-text search composes with it
    via `_tab_href`'s carried-through `q`.
    """
    tabs = []
    for value, key, label in _STATUS_TABS:
        n = counts[key]
        href = _tab_href(name, value, q)
        active = " active" if status == value else ""
        cls = "tcount" if n else "tcount z"
        if n and key in _TAB_ALARM_CLASS:
            cls += f" {_TAB_ALARM_CLASS[key]}"
        # B6 (goal wtv3/components): the "Blocked" tab pairs a crimson DOT
        # with the word -- ported from the approved gallery's own
        # `.tab-blocked .dot` (design-system.html #badges-tabs) -- so
        # blocked is never identified by the count badge's colour alone.
        dot = '<span class="tab-dot" aria-hidden="true"></span>' if key == "blocked" else ""
        tabs.append(
            f'<a class="tab{active}" href="{href}">{dot}{_esc(label)}'
            f'<span class="{cls}">{n}</span></a>'
        )
    return f'<nav class="tabs" aria-label="Filter items by status">{"".join(tabs)}</nav>'


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
    """The ready queue's age profile: one tick per real ready item across
    the whole workspace, grouped under the SAME fixed real-world-day bands
    (`READY_AGE_BUCKETS`) every other age reading in this app uses -- now
    with a printed day-range axis and a per-band count beneath each group,
    so a tick's horizontal position carries a real unit an operator can
    read, not just an unlabelled 'fresher -> older'. Still a texture, kept
    short enough it never out-shouts the hero."""
    total = sum(buckets.values())
    if total == 0:
        empty_note = "Nothing is ready to be claimed anywhere."
        return (
            '<div class="beat"><span class="eyebrow">Ready queue by age</span>'
            f'<div class="subtle" style="margin-top:14px">{empty_note}</div></div>'
        )
    seg_base = (
        "flex:1 1 0;min-width:0;display:flex;align-items:flex-end;gap:2px;"
        "overflow:hidden;padding:0 8px"
    )
    ax_base = (
        "flex:1 1 0;min-width:0;display:flex;flex-direction:column;"
        "align-items:center;gap:3px;padding:0 8px"
    )
    divider = ";border-left:1px solid var(--rule)"
    segments = []
    axis = []
    for idx, (label, lo, hi) in enumerate(A.READY_AGE_BUCKETS):
        n = buckets.get(label, 0)
        band = _BUCKET_BAND[label]
        height = _BUCKET_HEIGHT[label]
        # readable day-range for this band -- the axis unit the old
        # "FRESHER -> OLDER" strip lacked: "0-1d", "2-3d", "4-6d", "7d+".
        if hi is None:
            day = f"{lo}d+"
        elif lo == 0:
            day = f"0\u2013{hi}d"
        else:
            day = f"{lo}\u2013{hi}d"
        ticks = "".join(
            f'<span class="tick {band}" style="height:{height}px;flex:0 0 3px"></span>'
            for _n in range(n)
        )
        seg_style = seg_base + (divider if idx else "")
        ax_style = ax_base + (divider if idx else "")
        num_color = "var(--amber)" if (hi is None and n) else "var(--mid)"
        segments.append(f'<span style="{seg_style}">{ticks}</span>')
        axis.append(
            f'<span style="{ax_style}">'
            '<span style="font-family:var(--sans);font-size:10px;font-weight:500;'
            "letter-spacing:.1em;text-transform:uppercase;color:var(--dim);"
            f'white-space:nowrap">{_esc(day)}</span>'
            '<span style="font-family:var(--sans);font-size:14px;font-weight:500;'
            f'line-height:1;color:{num_color}">{n}</span></span>'
        )
    fresh = buckets.get("0-1", 0)
    stale = buckets.get("7+", 0)
    aria = (
        f"Age profile of {total} unclaimed items across the workspace: "
        + ", ".join(
            f"{buckets.get(label, 0)} aged "
            + (f"{lo} or more days" if hi is None else f"{lo} to {hi} days")
            for label, lo, hi in A.READY_AGE_BUCKETS
        )
        + "."
    )
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
  <div class="ticks" role="img" aria-label="{aria}">{"".join(segments)}</div>
  <div style="display:flex;margin-top:8px">{"".join(axis)}</div>
</div>"""


def _throughput_sparkline_html(daily_counts: list[int]) -> str:
    """The trailing-N-day resolutions sparkline (A1) -- a chrome cyan trend
    LINE, never the sole carrier of a reading (the flat today/prior-6d
    figures below it already say the real numbers; this is the shape
    supporting them, matching the approved mockup's top-right trend card).

    `var(--brand-cyan)` here is CHROME/brand, not a status hue -- the
    firewall reserves amber/crimson for alarm/blocked meaning only; a trend
    line's colour carries no status of its own, same discipline as the
    activity timeline's cyan \"agent\" dot (actor/decoration, not severity).
    Returns \"\" for fewer than 2 points -- a single point has no trend to
    draw, and an empty/`None` list means \"not enough history yet\", not a
    fabricated flat line at zero."""
    n = len(daily_counts)
    if n < 2:
        return ""
    width, height = 220, 40
    max_v = max(daily_counts) or 1
    step = width / (n - 1)
    pts = []
    for i, c in enumerate(daily_counts):
        x = round(i * step, 1)
        y = round(height - 3 - (c / max_v) * (height - 6), 1)
        pts.append(f"{x},{y}")
    path = " ".join(pts)
    total = sum(daily_counts)
    aria = f"Resolutions per day over the last {n} days, totalling {total}."
    return (
        f'<div class="spark-wrap"><svg class="spark" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" role="img" aria-label="{_esc(aria)}">'
        f'<polyline points="{path}" fill="none" stroke="var(--brand-cyan)" '
        'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg></div>'
    )


def _throughput_html(
    today: int,
    prior_rate: float | None,
    delta_pct: int | None,
    resolved_7d: int,
    older_than_7d: int,
    n_measurable: int,
    n_with_resolutions: int,
    daily_counts: list[int] | None = None,
) -> str:
    """Resolved today vs the prior-6-day average, with a trend indicator --
    the OVERVIEW's top-row companion to the hero (`.herorow`), matching the
    approved blend-2 mockup's hero-left / trend-right layout.

    `daily_counts` (oldest -> newest, `adapter.DAILY_THROUGHPUT_WINDOW`
    days) draws the sparkline (A1); `None`/`[]` (the default -- every
    existing caller that predates the sparkline keeps working unchanged)
    simply omits it, never a fabricated flat line.

    Honesty gap this renders rather than hides: `project_activity` reports
    `None` (not a fabricated 0) for a project that has resolved items but
    records no `closed_at` on any of them -- such projects are excluded
    from every figure here (see the route's own comment for the exact
    partition), and `n_measurable`/`n_with_resolutions` say so explicitly
    in the footnote rather than silently rolling them into a workspace
    total that would then be a lie."""
    max_v = max(today, prior_rate or 0.0, 1.0)
    track = 220
    today_w = max(3, round(track * today / max_v))
    prior_w = max(3, round(track * (prior_rate or 0.0) / max_v)) if prior_rate else 0
    if delta_pct is None:
        trend = "no prior rate to compare against"
    else:
        sign = "+" if delta_pct >= 0 else ""
        trend = f"<b>{sign}{delta_pct}%</b> against the prior-6-day rate"
    queue_word = _pluralize(n_with_resolutions, "queue").split(" ", 1)[1]
    coverage = (
        f"Throughput reflects {n_measurable} of {n_with_resolutions} "
        f"{queue_word} that record completion timestamps."
        if n_with_resolutions > n_measurable
        else ""
    )
    sparkline = _throughput_sparkline_html(daily_counts) if daily_counts else ""
    return f"""
<div class="thru">
  <div class="bh"><span class="eyebrow">Throughput</span></div>
  {sparkline}
  <div class="trow"><span class="tn">{today}</span><span class="tl">today</span>
    <span class="tb" style="width:{today_w}px"></span></div>
  <div class="trow prev"><span class="tn">{round(prior_rate) if prior_rate else 0}</span>
    <span class="tl">prior 6 d</span>
    <span class="tb" style="width:{prior_w}px"></span></div>
  <div class="tfoot">resolved per day &middot; {trend}<br>
    {resolved_7d} resolved in 7 days &middot; {older_than_7d} older than that</div>
  {f'<div class="tfoot">{coverage}</div>' if coverage else ""}
</div>"""


# ---------------------------------------------------------------------------
# Dashboard widget registry (see widgets.py + docs/widget-contract.md)
#
# The panels below register through the INTERNAL widget contract instead of
# being hand-called in sequence inside `dashboard()`. Each adapter reads only
# the reduced figures the route already computed once into a shared
# `WD.DashboardContext`, and returns the SAME fragment its builder produced
# inline before -- the registry routes rendering, it never restyles. This is
# the proof the contract fits the real v2 panels (aggregate-shaped AND
# summary-ranking-shaped), and the seam a second author or a hosted instance
# extends by calling `DASHBOARD_WIDGETS.register(...)`.
# ---------------------------------------------------------------------------


def _per_project_overview_html(summaries: list[A.ProjectSummary]) -> str:
    """A6 -- \"it's not clear how to get an overview of each project\": one
    compact glass card per READABLE project (name, ready/total, its own
    state-mix mini bar, relative last-activity, click-through) -- distinct
    from the ranked needs-you queue (which surfaces only projects that
    currently need a human) and the detailed queue table further down (a
    dense, every-column list built for scanning/filtering, not skimming).

    Broken/creating projects are surfaced elsewhere (the sidebar, the queue
    table's own unmissable alarm row) -- this widget reads `ok` summaries
    only, the SAME convention `needs-you` already uses, so a caller never
    has to guess which project-list flavour a given panel expects.

    Sorted ready-descending, ties by name -- the same "what needs the most
    claiming" ordering the queue table's own sort key uses, so a reader
    never has to learn a second ranking for the same data. Returns ""
    when there are no readable projects at all (nothing to overview)."""
    if not summaries:
        return ""
    ordered = sorted(summaries, key=lambda s: (-(s.ready or 0), s.name))
    cards = []
    for s in ordered:
        counts = _state_counts(s)
        total = s.total or 0
        age = _relative_time(s.last_activity) if s.last_activity else "no activity recorded"
        cards.append(
            # `data-t` (goal wtv3/finish, task 2): the same client-filter
            # vocabulary every other filterable list in this app uses
            # (`search_js` toggles `.hidden` on anything matching this
            # attribute) -- filterable by project name, this widget's own
            # sole identifying text.
            f'<a class="projcard" data-t="{_esc(s.name.lower())}" href="/projects/{_esc(s.name)}">'
            f'<div class="pname">{_esc(s.name)}</div>'
            '<div class="pfigs">'
            f'<span class="pn">{counts["ready"]}</span><span class="pl">ready</span>'
            f'<span class="pn pn-dim">/ {total}</span><span class="pl">total</span>'
            "</div>"
            f"{_state_bar_html(counts)}"
            f'<div class="page">{_esc(age)}</div>'
            "</a>"
        )
    # Filter bar (goal wtv3/finish, task 2): this grid had NO filter/search
    # affordance at all -- the queue table further down the page has one
    # (`T.search_field` + `T.search_js`), so a workspace with many projects
    # had an inconsistent, glass-less gap here. Reuses the SAME `.controls`/
    # `.field` glass chrome (never a new token or a bespoke look), with its
    # own field id (`pq`) and counter id (`ppc`) so it filters independently
    # of the queue table's own `#q`/`#qc` -- see `search_js`'s `count_id`
    # param. No `/` kbd hint (`shortcut=None`): the document-level `/`
    # shortcut binds to whichever search field's `search_js` call runs
    # first (the queue table's), so printing that hint here would promise a
    # shortcut this field doesn't answer to.
    filter_bar = (
        '<div class="controls">'
        f"{T.search_field('Filter projects by name', 'pq', shortcut=None)}"
        f'<span class="count" id="ppc">{_pluralize(len(ordered), "project")}</span>'
        "</div>"
    )
    return f"""
<div class="projoverview">
  <div class="chead"><span class="eyebrow">Per-project overview</span></div>
  {filter_bar}
  <div class="projgrid">{"".join(cards)}</div>
</div>"""


DASHBOARD_WIDGETS = WD.WidgetRegistry()

DASHBOARD_WIDGETS.register(
    WD.Widget(
        id="workspace-composition",
        title="Workspace by state",
        size=WD.WidgetSize.FULL,
        needs=(
            "ready_total",
            "held_total",
            "blocked_total",
            "deferred_total",
            "resolved_total",
            "reconciled_items",
        ),
        description="The hard-drive-split composition bar: items by state, resolved share.",
        render=lambda c: _workspace_composition_html(
            {
                "ready": c.ready_total,
                "held": c.held_total,
                "blocked": c.blocked_total,
                "deferred": c.deferred_total,
                "resolved": c.resolved_total,
            },
            c.reconciled_items,
        ),
    )
)

DASHBOARD_WIDGETS.register(
    WD.Widget(
        id="ready-queue-by-age",
        title="Ready queue by age",
        size=WD.WidgetSize.HALF,
        needs=("buckets",),
        description="Age histogram of unclaimed work across the workspace.",
        render=lambda c: _heartbeat_html(dict(c.buckets)),
    )
)

DASHBOARD_WIDGETS.register(
    WD.Widget(
        id="throughput",
        title="Throughput",
        size=WD.WidgetSize.FULL,
        needs=(
            "resolved_24h_total",
            "prior6d_rate",
            "delta_pct",
            "resolved_7d_total",
            "older_than_7d",
            "n_measurable_with_resolutions",
            "n_with_resolutions",
            "resolved_daily_totals",
        ),
        description="Resolved today vs the prior-6-day rate, with a trailing sparkline.",
        render=lambda c: _throughput_html(
            c.resolved_24h_total,
            c.prior6d_rate,
            c.delta_pct,
            c.resolved_7d_total,
            c.older_than_7d,
            c.n_measurable_with_resolutions,
            c.n_with_resolutions,
            list(c.resolved_daily_totals),
        ),
    )
)

DASHBOARD_WIDGETS.register(
    WD.Widget(
        id="per-project-overview",
        title="Per-project overview",
        size=WD.WidgetSize.FULL,
        needs=("ok",),
        description="A6 -- one compact card per readable project (ready/total, state mix, age).",
        render=lambda c: _per_project_overview_html(list(c.ok)),
    )
)

DASHBOARD_WIDGETS.register(
    WD.Widget(
        id="needs-you",
        title="Needs you \u2014 ranked",
        size=WD.WidgetSize.FULL,
        needs=("ok", "rendered_at"),
        description="The ranked cross-project attention queue (custody > blocked > aging).",
        render=lambda c: _needs_you_html(_attention_entries(list(c.ok)), c.rendered_at),
    )
)


def _dashboard_context(
    *,
    summaries: list[A.ProjectSummary],
    ok: list[A.ProjectSummary],
    rendered_at: datetime,
    buckets: dict[str, int],
    reconciled_items: int,
    ready_total: int,
    held_total: int,
    blocked_total: int,
    deferred_total: int,
    resolved_total: int,
    resolved_24h_total: int,
    resolved_7d_total: int,
    prior6d_rate: float,
    delta_pct: int | None,
    older_than_7d: int,
    n_measurable_with_resolutions: int,
    n_with_resolutions: int,
    resolved_daily_totals: tuple[int, ...] = (),
    workspace_last_activity: str | None = None,
) -> WD.DashboardContext:
    """Freeze the route's already-computed figures into the one read-only bag
    every registered widget renders from. A thin adapter -- it copies, it does
    not recompute -- so the widgets see exactly the values the inline calls saw."""
    return WD.DashboardContext(
        summaries=tuple(summaries),
        ok=tuple(ok),
        rendered_at=rendered_at,
        buckets=dict(buckets),
        reconciled_items=reconciled_items,
        ready_total=ready_total,
        held_total=held_total,
        blocked_total=blocked_total,
        deferred_total=deferred_total,
        resolved_total=resolved_total,
        resolved_24h_total=resolved_24h_total,
        resolved_7d_total=resolved_7d_total,
        prior6d_rate=prior6d_rate,
        delta_pct=delta_pct,
        older_than_7d=older_than_7d,
        n_measurable_with_resolutions=n_measurable_with_resolutions,
        n_with_resolutions=n_with_resolutions,
        resolved_daily_totals=resolved_daily_totals,
        workspace_last_activity=workspace_last_activity,
    )


def _dashboard_row(s: A.ProjectSummary) -> str:
    """One queue row of the bottom QUEUE table: name, a micro composition
    bar, TOTAL / READY / RESOLVED / DONE%. `Resolved` is the project's
    lifetime resolved count (`ProjectSummary.resolved`) -- always real,
    never time-windowed, so this column carries no honesty gap the way a
    24h/7d figure would for a project with no `closed_at` data."""
    if s.status != "ok":
        # A broken/creating queue must be unmissable, never a quiet grey row
        # lost among healthy ones. `class="alarm"` is the shared escalation
        # hook webtheme owns; the inline treatment here makes it read as an
        # alarm without depending on a dedicated token landing first.
        st = s.status
        creating = st.lower().startswith(("creating", "provisioning"))
        if creating:
            kind, word, accent = "warn", "Provisioning", "var(--amber)"
            tint = "var(--alarm-surface)"
            detail = "Being created \u2014 counts appear once its database is ready."
        else:
            kind, word, accent = "bad", "Broken", "var(--crimson)"
            tint = "var(--blocked-surface)"
            detail = st  # e.g. "ERROR: ..." (already truncated by the adapter)
        # keep the reading width sane: one legible line, full text on hover
        shown = detail if len(detail) <= 120 else detail[:119] + "\u2026"
        key = f"{s.name} {'provisioning' if creating else 'broken'} {st}".lower()
        row_style = f"background:{tint};box-shadow:inset 4px 0 0 {accent}"
        return (
            f'<tr class="alarm" data-t="{_esc(key)}" style="{row_style}">'
            f'<td class="link-cell"><a href="/projects/{_esc(s.name)}">{_esc(s.name)}</a></td>'
            f'<td colspan="5"><span class="c">{T.state_html(kind, word)} '
            f'<span class="muted" title="{_esc(st)}" style="overflow-wrap:anywhere">'
            f"{_esc(shown)}</span></span></td>"
            "</tr>"
        )
    counts = _state_counts(s)
    total = s.total or 0
    resolved = counts["resolved"]
    mini_bar = _state_bar_html(counts)
    pct_done = f"{round(resolved / total * 100)}%" if total else "\u2014"
    resolved_shown = str(resolved) if resolved else "\u2014"
    resolved_cls = "n hi" if resolved else "n z"
    pct_cls = "r n hi" if resolved else "r n z"

    # Alarm escalation -- this project's own row must be tellable apart from
    # a calm, all-ready-or-resolved queue at a glance, not only via its own
    # (now correctly weighted, see `_state_bar_html`) mini composition bar,
    # which a viewer scanning the table might not zoom in on. Same
    # escalation ordering as everywhere else in this file (blocked outranks
    # held/deferred in the accent chosen) -- never a competing hue, and a
    # visibly quieter tint (.08 alpha) than the broken-row treatment above
    # (.12 alpha), since "this queue has a stuck item" is real attention,
    # not "this queue's backend cannot be read."
    alarm_active = bool(counts["held"] or counts["blocked"] or counts["deferred"])
    row_style = ""
    if alarm_active:
        accent = "var(--crimson)" if counts["blocked"] else "var(--amber)"
        tint = "var(--blocked-surface)" if counts["blocked"] else "var(--alarm-surface)"
        row_style = f' style="background:{tint};box-shadow:inset 4px 0 0 {accent}"'

    key_bits = [s.name]
    key_bits += [state for state in ("held", "blocked", "deferred") if counts[state]]
    if not alarm_active:
        key_bits.append("healthy")
    key = " ".join(key_bits).lower()
    return f"""<tr data-t="{_esc(key)}"{row_style}>
  <td class="link-cell"><a href="/projects/{_esc(s.name)}">{_esc(s.name)}</a></td>
  <td class="mb">{mini_bar}</td>
  <td class="r"><span class="c r"><span class="n">{total}</span></span></td>
  <td class="r"><span class="c r"><span class="n {"ink" if counts["ready"] else "zero"}">\
{counts["ready"]}</span></span></td>
  <td class="r"><span class="c r"><span class="{resolved_cls}">{resolved_shown}</span></span></td>
  <td class="r"><span class="c r"><span class="{pct_cls}">{pct_done}</span></span></td>
</tr>"""


def _dashboard_totals(summaries: list[A.ProjectSummary]) -> str:
    ok = [s for s in summaries if s.status == "ok"]
    t_ready = sum(s.ready or 0 for s in ok)
    t_total = sum(s.total or 0 for s in ok)
    t_resolved = sum(s.resolved or 0 for s in ok)
    counts = {
        "ready": t_ready,
        "held": sum(s.held or 0 for s in ok),
        "blocked": sum(s.blocked or 0 for s in ok),
        "deferred": sum(s.deferred or 0 for s in ok),
        "resolved": t_resolved,
    }
    mini_bar = _state_bar_html(counts)
    pct_done = f"{round(t_resolved / t_total * 100)}%" if t_total else "\u2014"
    all_label = _pluralize(len(summaries), "queue")
    return f"""<tfoot><tr>
  <td><span class="c"><span class="totk">All {all_label}</span></span></td>
  <td class="mb">{mini_bar}</td>
  <td class="r"><span class="c r"><span class="n">{t_total}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{t_ready}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{t_resolved}</span></span></td>
  <td class="r"><span class="c r"><span class="n">{pct_done}</span></span></td>
</tr></tfoot>"""


def _units_legend_html() -> str:
    """One shared vocabulary for every count on the overview (goal item 4), so
    TOTAL / READY / RESOLVED / DONE% and the sidebar's `open/total` badge can
    never be read as different, colliding denominators. A queue is a project;
    every count is ITEMS unless marked `%`. Rendered as flat data-ink under
    the queue table -- a glossary, not a control."""
    return (
        '<div class="units" aria-label="What the counts mean">'
        "<b>Queue</b> = one project &middot; every count is <b>items</b> &middot; "
        "<b>Ready</b> claimable &middot; <b>Held</b> in progress &middot; "
        "<b>Blocked</b> waiting on a dependency &middot; <b>Resolved</b> done &middot; "
        "<b>Done&nbsp;%</b> = resolved &divide; total"
        "</div>"
    )


def _create_project_form() -> str:
    """The workspace's project-creation flow (goal wtv3/finish, task 3).

    Was previously an always-visible `.formsec` (a bare top-border strip --
    no glass, no card -- the one genuinely unstyled widget on the
    dashboard) rendered TWICE (once in the empty-workspace branch, once at
    the foot of the main body). Now a single, collapsed glass DISCLOSURE:
    calm by default (a small pill trigger, not a permanent form sitting
    under a polished dashboard), expanding to a proper glass card that
    matches the rest of the app's chrome (`.wtb-pane`/`.projcard`'s own
    `--glass-fill`/`--glass-hairline-soft`/`--glass-shadow-float` tokens --
    no new tokens defined here).

    The nav's existing "+ New project" action (`_nav_actions_html`) already
    links to `/#create-project` -- unchanged by this rewrite. `<details>`
    is a real fragment-navigation TARGET in every evergreen browser (Chrome,
    Firefox, Safari all auto-open a `<details>` that is the target of the
    current URL fragment, a standard platform behavior, not a bespoke
    hack) -- so putting `id="create-project"` on the `<details>` itself
    keeps that affordance working with no JS of its own. The only OTHER
    caller (`dashboard`'s empty-workspace branch) now renders this same
    function instead of its own inline copy, so there is exactly one
    render site, never two competing `id="create-project"` elements on the
    same page.
    """
    return """
<details class="createproj" id="create-project">
  <summary class="cp-trigger">+ Create a project</summary>
  <div class="cp-card">
    <form method="post" action="/projects">
      <label for="name">Project name</label>
      <input type="text" id="name" name="name" pattern="[a-z][a-z0-9_]{1,30}" required
             placeholder="my_project">
      <p class="field-hint">Lowercase letters, digits, underscores; must start with a letter.</p>
      <button type="submit">Create</button>
    </form>
  </div>
</details>"""


# ---------------------------------------------------------------------------
# project-view-specific rendering
# ---------------------------------------------------------------------------


def _project_hero_html(name: str, summary: A.ProjectSummary, oldest_item: A.Item | None) -> str:
    if summary.status != "ok":
        # Same alarm vocabulary as the dashboard's broken row: a bordered,
        # tinted block that cannot be mistaken for a healthy hero. `alarm`
        # is webtheme's escalation hook (residual: `--alarm` token +
        # `.hero.alarm` styling); inline crimson/amber makes it read now.
        st = summary.status
        creating = st.lower().startswith(("creating", "provisioning"))
        if creating:
            label, accent, tint = "Provisioning", "var(--amber)", "var(--alarm-surface)"
            body = (
                "This project is still being created. Its counts appear once its database is ready."
            )
        else:
            label, accent, tint = "Unavailable", "var(--crimson)", "var(--blocked-surface)"
            body = st
        return (
            '<div class="hero alarm" style="display:block">'
            f'<div style="border-left:4px solid {accent};background:{tint};'
            'padding:20px 24px;max-width:640px">'
            f'<span class="eyebrow" style="color:{accent}">{label}</span>'
            '<div class="subtle" style="margin-top:12px;overflow-wrap:anywhere">'
            f"{_esc(body)}</div></div></div>"
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
                '<div class="said" style="max-width:560px">'
                # `.who` is an unstyled div, so name and id butted together
                # ("cortex" + "cortex-i2u" -> "cortexcortex-i2u"). Lay it out
                # as a baseline flex row with a real gap, and give the id the
                # same dim secondary treatment the hero attribution uses.
                '<div class="who" style="display:flex;gap:8px;align-items:baseline;'
                f'flex-wrap:wrap">{_esc(name)}'
                '<span class="id" style="color:var(--dim);font-weight:400;'
                f'letter-spacing:.04em">{_esc(oldest_item.id)}</span></div>'
                f'<a class="what" href="{item_href}" style="display:inline-block;'
                f'max-width:100%;overflow-wrap:anywhere">{_esc(oldest_item.title)}</a>'
                '<div class="subtle" style="margin-top:8px">'
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


# bd's priority scale (`bd priority --help`): 0=Critical .. 4=Backlog,
# default 2=Medium. Rendered as a `P{n}` glass mono CHIP (goal wtv3/
# components, B3/B4) -- ported from the approved gallery's own
# `.priority-chip` (design-system.html #rows) -- not a coloured bar:
# severity is encoded as BRIGHTNESS/weight on this app's existing neutral
# text ramp (`_PRIORITY_CHIP_CLASS`) rather than a new hue -- --amber and
# --crimson are each already reserved for exactly one job elsewhere
# (age/attention, and blocked/escalation; see webtheme.py's SIGNAL
# COLOURS comment), and a static severity tag is neither of those. This
# app's real bd range (0-4) is one wider than the gallery's own P0-P2
# demo; P3/P4 extend the SAME dimming ramp (see webtheme.py's
# `.priority-chip.p3,.p4`) rather than inventing a fourth visual language.
_PRIORITY_CHIP_CLASS = {0: "p0", 1: "p1", 2: "p2", 3: "p3", 4: "p4"}
_PRIORITY_LABEL = {
    0: "P0 \u2013 critical",
    1: "P1 \u2013 high",
    2: "P2 \u2013 medium",
    3: "P3 \u2013 low",
    4: "P4 \u2013 backlog",
}


def _priority_bar_html(priority: int | None) -> str:
    """The row's leading priority chip (`P{n}`, e.g. `P0`). An
    unrecognized/missing priority (`None`, or any value outside bd's
    documented 0-4 range) degrades HONESTLY to a bare `P?`, titled
    \"priority unknown\" -- never a guessed rank. Name kept from the prior
    (bar-shaped) implementation -- every existing call site (this
    module's `_item_row`, webbrowse.py's `_row_html`) still calls
    `_priority_bar_html`; only the markup it returns changed, to the
    approved gallery's chip."""
    if priority is not None and priority in _PRIORITY_CHIP_CLASS:
        cls = _PRIORITY_CHIP_CLASS[priority]
        label = f"P{priority}"
        title = _PRIORITY_LABEL[priority]
    else:
        cls = "punk"
        label = "P?"
        title = "priority unknown"
    return f'<span class="priority-chip {cls}" title="{_esc(title)}">{_esc(label)}</span>'


# Which `ICONS` glyph each status renders in the row gutter -- see
# webtheme.py's `ICONS` dict for the shapes themselves.
_STATUS_ICON_KEY = {
    "open": "ready",
    "held": "held",
    "blocked": "blocked",
    "deferred": "deferred",
    "resolved": "resolved",
}


def _status_icon_html(status: str) -> str:
    """The row's small per-status glyph -- reuses the EXACT `st-*` colour
    classes `_item_state_html`'s text badge already uses (`_STATE_CSS`),
    so an icon and its row's status text can never disagree in colour."""
    cls = _STATE_CSS.get(status, "open")
    icon_key = _STATUS_ICON_KEY.get(status, "ready")
    icon = T.ICONS.get(icon_key, T.ICONS["ready"])
    label = _STATE_LABEL.get(status, status.title())
    return f'<span class="stico st-{cls}" title="{_esc(label)}">{icon}</span>'


def _item_row(name: str, i: A.Item, idx: int) -> str:
    seconds = _item_lifecycle_seconds(i)
    band = T.age_band_class(seconds) if i.status == "open" else "a0"
    value, unit = T.age_short(seconds)
    # `i.holder` is bd's `assignee` field, which is NOT cleared when an item
    # resolves -- it is left in place as "who last held this," a real and
    # useful historical fact, but NOT a current custody holder. Rendering it
    # unconditionally here made a resolved (or blocked/deferred) row look
    # like it had an active holder while the project's own `held` stat (which
    # counts `status == "held"` only) correctly read 0 -- the exact
    # contradiction reported against this table. A holder chip appears here
    # ONLY when the item is genuinely held right now; every other status
    # shows the same honest dash a never-held item does.
    #
    # When it IS genuinely held, the cell upgrades from a bare identity to
    # the claim-age + staleness reading (`held 4h &middot; holder`, amber
    # only when `custody.reclaim_eligible` says this hold is stale right
    # now) -- see `_custody_reading`/`_custody_html`.
    holder = _custody_html(_custody_reading(i)) or (
        _identity_html(i.holder)
        if (i.holder and i.status == "held")
        else '<span class="muted">&mdash;</span>'
    )
    href = f"/projects/{_esc(name)}/items/{_esc(i.id)}"
    key = f"{i.id} {i.title} {i.status} {i.holder or ''}".lower()
    age_html = f'<span class="age {band}">{_esc(value)}<span class="u">{_esc(unit)}</span></span>'
    # On a project page every id shares the same `<project>-` prefix, so the
    # prefix is pure redundancy -- and when the project name is long
    # (`amplifier_feedback-quj`) it pushes the UNIQUE suffix out of the fixed
    # Id column and gets ellipsis-truncated away, hiding the only part that
    # distinguishes one row from another. Show the suffix as the primary token;
    # keep the full id one hover (and copy) away via `title`. Fall back to the
    # full id if it doesn't carry this project's prefix.
    _prefix = f"{name}-"
    id_shown = i.id[len(_prefix) :] if i.id.startswith(_prefix) else i.id
    # Two dimensions in ~20px, no new WIDE column: a priority bar (colour)
    # and a status icon (shape), both in the row's leading gutter cell --
    # see `_priority_bar_html`/`_status_icon_html`.
    gutter = _priority_bar_html(i.priority) + _status_icon_html(i.status)
    return f"""<tr data-t="{_esc(key)}">
  <td><span class="c gutter">{gutter}</span></td>
  <td><span class="c"><span class="idx">{idx:03d}</span></span></td>
  <td><span class="c"><span class="iid" title="{_esc(i.id)}">{_esc(id_shown)}</span></span></td>
  <td><span class="c">{_item_state_html(i.status)}</span></td>
  <td><span class="c">{age_html}</span></td>
  <td><span class="c"><span class="holder">{holder}</span></span></td>
  <td class="ti"><a href="{href}">{_esc(i.title)}</a></td>
</tr>"""
    # NOTE (goal: item-render, deliverable 3): the described "cortexcortex-i2u"
    # no-separator id/title concat bug is NOT reproducible in this row as
    # currently written -- `i.id` and `i.title` are rendered in separate
    # `<td>` cells above, never concatenated into one string, and every
    # f-string join in this function (`href`, `key`) already inserts a
    # literal separator ("/", " ") between fields. Verified by reading
    # every field access in this function; no change made because there is
    # nothing here to fix.


# ---------------------------------------------------------------------------
# item body rendering -- markdown-lite + monospace/aligned content blocks
# ---------------------------------------------------------------------------
#
# All THREE deliverables below (markdown rendering, monospace alignment,
# ~90ch reading measure) are satisfied entirely with inline styles emitted
# by these helpers -- none require a webtheme.py change. The item-detail
# ROUTE (in `create_app()`, owned by the webapp-routes lane) still needs to
# call `_content_block_html`/`_fact_value_html` instead of its current
# `_esc(...)` calls -- see this module's residual notes (recorded in
# DONE.json) for the exact call sites.

_FENCED_CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^\n*]+?)\*\*")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)
_CODEBLOCK_TOKEN_RE = re.compile(r"\x00CODEBLOCK(\d+)\x00")


def _render_item_markdown(text: str) -> str:
    """A small, dependency-free markdown-lite renderer for item
    description/acceptance/resolution bodies: fenced ``` code blocks,
    inline `code`, **bold**, and '#'-style headings become real HTML.
    Everything else -- including any HTML the author typed -- passes
    through as literal, already-escaped text; the surrounding
    `.content-block`'s `white-space: pre-wrap` (see `_content_block_html`)
    preserves blank lines and indentation exactly as typed, so this never
    needs to emit its own paragraph or `<br>` markup.

    Escapes FIRST (`_esc`, the same helper every other renderer in this
    module uses), so no substitution below can ever introduce live HTML
    from untrusted input -- only the fixed tag strings this function
    writes itself land unescaped in the result."""
    escaped = _esc(text)

    code_blocks: list[str] = []

    def _stash_code_block(m: re.Match[str]) -> str:
        # The regex's content group always includes the newline right
        # before the closing fence (that's how the opening fence's own
        # trailing newline is excluded) -- drop exactly one, so a
        # ```\ncode\n``` block doesn't render with a trailing blank line.
        content = m.group(1)
        if content.endswith("\n"):
            content = content[:-1]
        code_blocks.append(f"<pre><code>{content}</code></pre>")
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    without_blocks = _FENCED_CODE_RE.sub(_stash_code_block, escaped)

    def _heading(m: re.Match[str]) -> str:
        # h1-h3 are reserved for the page's own title/section chrome -- an
        # item body heading is always a SUBORDINATE heading (h4-h6),
        # however many '#'s the author used.
        level = min(len(m.group(1)) + 3, 6)
        return f"<h{level}>{m.group(2)}</h{level}>"

    with_headings = _HEADING_RE.sub(_heading, without_blocks)
    with_code = _INLINE_CODE_RE.sub(r"<code>\1</code>", with_headings)
    with_bold = _BOLD_RE.sub(r"<strong>\1</strong>", with_code)

    def _restore_code_block(m: re.Match[str]) -> str:
        return code_blocks[int(m.group(1))]

    return _CODEBLOCK_TOKEN_RE.sub(_restore_code_block, with_bold)


# `var(--mono, <fallback>)` reads webtheme.py's token if one is ever added
# there, but works TODAY via the fallback -- no webtheme.py edit required
# for this deliverable. (Residual-noted anyway: promoting this to a real
# `--mono` custom property in webtheme.py would let every future monospace
# need reuse one token instead of repeating this stack.)
_CONTENT_MONO_STACK = (
    "var(--mono,ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace)"
)


def _content_block_html(text: str | None, *, empty_message: str) -> str:
    """The full `.content-block` for an item's description/acceptance/
    resolution body -- markdown-lite rendered (`_render_item_markdown`), a
    monospace font stack (so pasted ASCII tables and code keep their
    column alignment: the shared `.content-block` rule in webtheme.py sets
    `white-space: pre-wrap` but not a monospace font, which silently
    destroys alignment under the proportional `--sans` face), and a ~90
    character reading measure (the raw container is otherwise full-width
    of the page's `.wrap`, which reads at ~190 characters/line on a wide
    viewport). All three constraints are applied here, inline, on the
    element THIS helper returns -- not as new webtheme.py classes.

    Returns the same muted "No X provided." placeholder the item-detail
    route already renders today for an empty/missing body, so swapping the
    route's `_esc(...)` call for this one is a drop-in replacement."""
    if not text:
        return f'<div class="content-block"><span class="muted">{_esc(empty_message)}</span></div>'
    rendered = _render_item_markdown(text)
    style = f"font-family:{_CONTENT_MONO_STACK};max-width:90ch"
    return f'<div class="content-block" style="{style}">{rendered}</div>'


def _fact_value_html(value: str) -> str:
    """A static (non-interactive) fact value for the item-detail page's
    KIND/PRIORITY-style fields: explicitly non-clickable (`cursor:default`,
    no underline/href), so it never reads as a disguised link or an
    editable field sitting next to the page's genuinely interactive `.kv`
    values (the Queue link, the identity spans)."""
    return f'<span class="fact-static" style="cursor:default">{_esc(value)}</span>'


# ---------------------------------------------------------------------------
# item-detail blocker chain -- Beadbox-inspired enrichment #7.
#
# Built entirely from `Item.links` (`adapter.Beads.get`'s enriched
# id/direction/type/title/status/holder/created_by/blocking dicts -- see
# that method's own docstring for exactly which fields are real per
# direction). No new `bd` calls here: `with_links=True` (already the
# item-detail route's own read) is the only fetch this needs.
# ---------------------------------------------------------------------------


def _link_ref_html(name: str, link: dict) -> str:
    """`<a href=".../items/ID">ID — Title</a>` for one link entry, or ""
    if the entry carries no id at all (defensive -- every real bd payload
    has one)."""
    ln_id = link.get("id")
    if not ln_id:
        return ""
    href = f"/projects/{_esc(name)}/items/{_esc(ln_id)}"
    title = link.get("title") or ""
    suffix = f" &mdash; {_esc(title)}" if title else ""
    return f'<a href="{href}">{_esc(ln_id)}</a>{suffix}'


def _blocker_owner_html(link: dict) -> str:
    """Who holds/owns the upstream work behind one blocked-by entry:
    \"held by <holder>\" while it is genuinely held right now, else
    \"reported by <created_by>\" (the task's own fallback rule). \"\" when
    neither is known -- honest, not fabricated (the `to`-direction's own
    lean payload never carries `holder`/`created_by` at all; see
    `Beads.get`'s docstring)."""
    if link.get("status") == "held" and link.get("holder"):
        return f"held by {_identity_html(link['holder'])}"
    created_by = link.get("created_by")
    if created_by:
        return f"reported by {_identity_html(created_by)}"
    return ""


def _blocked_by_list_html(name: str, links: list[dict]) -> str:
    """The `Blocked by` chain: one BANNER per still-live dependency (goal
    wtv3/components, B7) -- ported from the approved gallery's own
    `.blocker-banner` (design-system.html #list-detail): a crimson
    surface+border+ink card, octagon-x icon, while the `blocks` dependency
    is still open (`link[\"blocking\"]` -- the SAME check `claim_item` uses
    to refuse a claim, so this can never show a chain as clear when a
    claim would actually still be refused); a NEUTRAL glass card with a
    check-circle icon once the upstream item resolves -- \"crimson
    unresolved -> neutral resolved check\", the exact stakeholder call
    DESIGN-SYSTEM.md sec 2a records, never a second colour on the cleared
    state. Each banner ALSO carries the pre-existing `blocker-item
    unsatisfied`/`satisfied` classes verbatim (this repo's own tests --
    `tests/unit/test_webapp_item_render.py`, `tests/integration/
    test_web.py` -- assert on those substrings directly) so the visual
    upgrade never disturbs that contract."""
    banners = ""
    for ln in links:
        ref = _link_ref_html(name, ln)
        if not ref:
            continue
        status = ln.get("status") or "unknown"
        owner = _blocker_owner_html(ln)
        owner_part = f' <span class="muted">{owner}</span>' if owner else ""
        if ln.get("blocking"):
            banners += (
                '<div class="blocker-item unsatisfied blocker-banner unresolved">'
                f'<span class="icon">{T.ICONS["octagon-x"]}</span>'
                '<div><div class="btitle">Blocked by unresolved dependency</div>'
                f'<div class="blink">{ref} '
                f'<span class="st st-blkd">{_esc(status)}</span>{owner_part}</div></div>'
                "</div>"
            )
        else:
            banners += (
                '<div class="blocker-item satisfied blocker-banner resolved">'
                f'<span class="icon">{T.ICONS["check-circle"]}</span>'
                '<div><div class="btitle">Blocker resolved</div>'
                '<div class="blink"><span class="check" aria-hidden="true">&#10003;</span> '
                f'{ref} <span class="muted">({_esc(status)})</span></div></div>'
                "</div>"
            )
    if not banners:
        return ""
    return (
        '<h2 class="eyebrow am" style="display:block;margin-top:30px">Blocked by</h2>'
        f'<div class="blocker-chain">{banners}</div>'
    )


def _cheap_ref_list_html(name: str, heading: str, links: list[dict]) -> str:
    """A plain, neutral id/title/status list -- used for the inverse
    `Blocks` direction and the `Other links` fallback bucket. Never
    crimson: these describe what THIS item affects or relates to, not
    an escalation about THIS item's own state (that's `Blocked by`'s
    job, above)."""
    rows = ""
    for ln in links:
        ref = _link_ref_html(name, ln)
        if not ref:
            continue
        status = ln.get("status")
        status_part = f' <span class="muted">({_esc(status)})</span>' if status else ""
        rows += f"<li>{ref}{status_part}</li>"
    if not rows:
        return ""
    return (
        f'<h2 class="eyebrow" style="display:block;margin-top:30px">{_esc(heading)}</h2>'
        f'<ul class="links-list">{rows}</ul>'
    )


def _discovered_note_html(name: str, links: list[dict], *, label: str) -> str:
    """A single informational line for a `discovered-from` provenance link
    -- never crimson (ASSUMPTION link.nonblocking: a discovered-from link
    never blocks its target, so it never earns the escalation hue)."""
    refs = [_link_ref_html(name, ln) for ln in links]
    refs = [r for r in refs if r]
    if not refs:
        return ""
    return f'<p class="muted" style="margin-top:10px">{_esc(label)} {", ".join(refs)}</p>'


def _dependency_sections_html(name: str, links: list[dict]) -> str:
    """All of the item-detail page's dependency-graph sections, in order:
    Blocked by (escalation), Discovered from (provenance, this item's own
    origin), Blocks (cheap inverse), Discovered (cheap inverse -- items
    found while working this one), then a Other links fallback for any
    dependency type this page has no special treatment for (`related`,
    `parent-child`, `tracks`, ...) so nothing bd reports is silently
    dropped."""
    if not links:
        return ""
    from_links = [ln for ln in links if ln.get("direction") == "from"]
    to_links = [ln for ln in links if ln.get("direction") == "to"]

    blocked_by = [ln for ln in from_links if ln.get("type") == "blocks"]
    discovered_from = [ln for ln in from_links if ln.get("type") == A.LINK_DISCOVERED_FROM]
    other_from = [
        ln for ln in from_links if ln.get("type") not in ("blocks", A.LINK_DISCOVERED_FROM)
    ]

    blocks = [ln for ln in to_links if ln.get("type") == "blocks"]
    discovered_here = [ln for ln in to_links if ln.get("type") == A.LINK_DISCOVERED_FROM]
    other_to = [ln for ln in to_links if ln.get("type") not in ("blocks", A.LINK_DISCOVERED_FROM)]

    out = _blocked_by_list_html(name, blocked_by)
    out += _discovered_note_html(name, discovered_from, label="Discovered while working")
    out += _cheap_ref_list_html(name, "Blocks", blocks)
    out += _discovered_note_html(
        name, discovered_here, label="Discovered while this item was being worked:"
    )
    other = other_from + other_to
    out += _cheap_ref_list_html(name, "Other links", other)
    return out


# ---------------------------------------------------------------------------
# item-detail activity feed -- Beadbox-inspired enrichment #11.
#
# Built entirely from `adapter.Beads.activity` (real `bd history` diffed
# transitions + real `bd comments`, nothing synthesized -- see that
# method's own docstring). Purely a rendering layer: every fact shown here
# already exists on the `ActivityEvent` it's given.
# ---------------------------------------------------------------------------


def _activity_actor_class(ev: A.ActivityEvent) -> str:
    """Classify one activity event into the TIMELINE's dot-ring colour
    (goal wtv3/components, B8) -- ported from the approved gallery's own
    `.tl-item.actor-*` (design-system.html #list-detail; DESIGN-SYSTEM.md
    sec 2a). Implements only what `ActivityEvent` can actually
    substantiate:

      - \"blocked\"  -- a real transition into bd's own blocked status (the
        summary text `adapter._history_events` itself generates for it,
        e.g. \"Status: blocked\" / \"Status changed: X \\u2192 blocked\") --
        the reserved crimson, the SAME hue everywhere blocked appears,
        never a third meaning.
      - \"resolved\" -- `ev.kind == \"resolved\"`: per DESIGN-SYSTEM.md sec
        2a, \"calm / resolved ... is NEUTRAL ... not cyan, not green, not
        any hue\" -- rendered with the calm check-circle glyph, no colour.
      - \"neutral\"  -- everything else (created, claimed, a non-blocked
        status change, a comment).

    DEFERRED, on purpose, with this reason: the gallery's own cyan=
    \"agent action\" / purple=\"AI insight\" actor split.  `ActivityEvent`
    carries only an `actor` IDENTITY STRING (whoever bd recorded as
    assignee/created_by/comment author) -- no field anywhere in this data
    model marks an actor as \"an AI agent\" versus \"a human\" (see
    .amplifier/wt-v3-discrepancies.md's own note: \"there is NO agent
    entity -- custody is a PID-bound token\"). Guessing agent-vs-human
    from an identity string's spelling would be exactly the kind of
    fabricated signal this codebase's own doctrine forbids elsewhere (see
    `_blocker_owner_html`'s \"honest, not fabricated\" discipline). When a
    real, substantiated signal exists (e.g. a future
    `ActivityEvent.actor_kind` populated from bd), the cyan/purple split
    can be added here without touching any call site."""
    if ev.kind == "resolved":
        return "resolved"
    if ev.kind == "status" and "blocked" in ev.summary.lower():
        return "blocked"
    return "neutral"


# Which B12 glyph each timeline dot shows -- shape-redundant with its own
# ring colour, never colour alone (same discipline `_STATUS_ICON_KEY` uses).
_TIMELINE_ICON_KEY = {
    "neutral": "plus-file",
    "resolved": "check-circle",
    "blocked": "octagon-x",
}


def _activity_event_html(ev: A.ActivityEvent) -> str:
    actor_cls = _activity_actor_class(ev)
    icon = T.ICONS[_TIMELINE_ICON_KEY[actor_cls]]
    age_html = _item_age_html(ev.at)
    actor_html = f' <span class="muted">{_identity_html(ev.actor)}</span>' if ev.actor else ""
    detail_html = f'<div class="adetail">{_esc(ev.detail)}</div>' if ev.detail else ""
    return (
        f'<div class="tl-item actor-{actor_cls}">'
        f'<span class="tl-dot"><span class="icon">{icon}</span></span>'
        '<div class="tl-body">'
        f'<span class="tl-title">{_esc(ev.summary)}</span>'
        f'<span class="tl-time">{age_html}</span>'
        f"{actor_html}{detail_html}"
        "</div></div>"
    )


def _activity_feed_html(events: list) -> str:
    """The full `Activity` section: a reverse-chronological TIMELINE (goal
    wtv3/components, B8) of everything bd itself can substantiate about
    this item -- ported from the approved gallery's own `.timeline`
    (design-system.html #list-detail). `events` is already reverse-
    chronological (`Beads.activity` sorts it) -- this function only
    renders, never reorders. Returns \"\" for an empty list (a brand-new
    item with no history yet is not an error)."""
    if not events:
        return ""
    rows = "".join(_activity_event_html(ev) for ev in events)
    return (
        '<h2 class="eyebrow" style="display:block;margin-top:30px">Activity</h2>'
        f'<div class="timeline">{rows}</div>'
    )


# ---------------------------------------------------------------------------
# /setup -- TLS certificate status + method options for whoever deploys this.
#
# Follow-on to PR #24 (TLS/HTTPS support, ported from muxplex): that work
# gave `setup-tls` a real `--method` chain (auto/selfsigned/ca/tailscale)
# but no in-app surface for a deployer to discover or act on it short of a
# terminal. This section renders that surface -- read-only status plus,
# where the host genuinely supports it, a real in-process generate action
# (see `create_app`'s `/setup/tls` route) -- entirely from `webtls.py`'s
# existing functions; it adds no new certificate-generation LOGIC of its
# own, only a browser-reachable front end for logic that already exists.
#
# Deliberately does NOT offer an `mkcert` option: despite this task's own
# framing suggesting one (and a `detect_mkcert()` probe), neither exists
# anywhere in this codebase -- `cli.py`'s own `setup-tls --method` choices
# are exactly `auto`/`selfsigned`/`ca`/`tailscale` (see `cmd_setup_tls`).
# Presenting a fourth option this repo cannot actually act on would be
# worse than omitting it silently would be -- see this module's `docs/
# ISSUE_HANDLING.md`-inherited "never fabricate a satisfied requirement"
# principle. The three real methods are presented below, ordered the way
# the task asked (trusted-with-no-client-step first, down to
# works-everywhere-with-a-warning last).
# ---------------------------------------------------------------------------

# A certificate inside this window is flagged in the status card (amber),
# not just a bare date -- an operator glancing at /setup should not have to
# do date arithmetic to notice a Tailscale cert (90-day validity) about to
# lapse. 30 days comfortably covers a human's next login even for a
# once-a-month spot-check.
_CERT_EXPIRY_WARN_DAYS = 30


def _tls_status_html(request: Request) -> str:
    """The TLS STATUS card: derives the active scheme from THIS REQUEST
    (`request.url.scheme`, what the ASGI server actually received -- never
    assumed from whether a cert happens to exist on disk), then -- if a
    cert/key pair exists at the well-known `webtls.default_cert_path()` /
    `default_key_path()` -- reports its issuer classification, SAN
    coverage, and expiry (flagged if within `_CERT_EXPIRY_WARN_DAYS` or
    already past).

    A cert can exist on disk while the request nonetheless arrived over
    plain HTTP (freshly generated via `/setup/tls` below, but the running
    uvicorn process cannot hot-swap its own TLS material -- see that
    route's docstring): that mismatch is surfaced explicitly rather than
    silently preferring one signal over the other.
    """
    scheme = request.url.scheme
    cert_path = WT.default_cert_path()
    key_path = WT.default_key_path()
    info = WT.get_cert_info(cert_path) if cert_path.exists() and key_path.exists() else None

    if info is None:
        return (
            '<div class="formsec">'
            '<span class="flegend">TLS status</span>'
            '<p class="subtle" style="margin-top:10px">Serving over '
            '<b style="color:var(--ink)">HTTP</b> &mdash; not a secure origin. Installing this '
            "dashboard as an app (&ldquo;Add to Home Screen&rdquo;) needs HTTPS. Pick a method "
            "below, generate a certificate, then restart the service to serve it.</p>"
            "</div>"
        )

    ca_cert_path = WT.default_ca_cert_path()
    ca_signed = ca_cert_path.exists() and WT.is_signed_by_ca(cert_path, ca_cert_path)
    if info["self_signed"]:
        issuer_label = "Self-signed"
    elif ca_signed:
        issuer_label = "Local CA &mdash; browser-trusted once the CA is installed (see below)"
    else:
        issuer_label = f"External CA ({_esc(info['issuer_common_name'] or 'unknown issuer')})"

    days_left = (info["expires"] - datetime.now(UTC)).total_seconds() / 86400
    if days_left < 0:
        expiry_cls, expiry_note = "am", " &mdash; EXPIRED"
    elif days_left < _CERT_EXPIRY_WARN_DAYS:
        expiry_cls, expiry_note = "am", f" &mdash; expires in {int(days_left)}d"
    else:
        expiry_cls, expiry_note = "", ""

    scheme_cls = "" if scheme == "https" else "am"
    stale_note = (
        ""
        if scheme == "https"
        else (
            '<p class="subtle" style="color:var(--amber);margin-top:8px">A certificate exists '
            "on disk, but this server is currently serving plain HTTP &mdash; a running server "
            "cannot hot-swap its own TLS material. Restart the service to pick it up.</p>"
        )
    )
    hostnames_str = ", ".join(_esc(h) for h in info["hostnames"])
    expires_str = _esc(info["expires"].strftime("%Y-%m-%d"))
    scheme_html = f'<span class="v {scheme_cls}">{_esc(scheme.upper())}</span>'
    expires_html = f'<span class="v {expiry_cls}">{expires_str}{expiry_note}</span>'

    return f"""
    <div class="formsec">
      <span class="flegend">TLS status</span>
      <div class="kv" style="margin-top:10px">
        <div><span class="k">Scheme</span>{scheme_html}</div>
        <div><span class="k">Issuer</span><span class="v">{issuer_label}</span></div>
        <div><span class="k">Expires</span>{expires_html}</div>
      </div>
      <p class="subtle" style="margin-top:10px">Covers <span class="mono">{hostnames_str}</span></p>
      {stale_note}
    </div>
    """


def _setup_method_row(
    *,
    method: str,
    title: str,
    description: str,
    when_to_pick: str,
    availability_html: str,
    command: str,
    disabled: bool,
    disabled_reason: str = "",
    recommended: bool = False,
) -> str:
    """One METHOD OPTIONS row: what it gives you, when to pick it, whether
    it's actually usable on THIS host right now, the exact CLI equivalent
    (copy-pasteable, matching `cmd_setup_tls`'s own flags verbatim), and a
    real generate button wired to `POST /setup/tls`.

    `disabled` grays the button out (with `disabled_reason` as its title
    tooltip) instead of omitting it -- an operator should see every method
    that EXISTS, and understand why one isn't available right now, rather
    than have it vanish silently. The POST route refuses an unavailable
    method the same way regardless of whether this button was disabled
    (see that route's docstring) -- disabling here is a UI courtesy, not
    the enforcement point.

    `recommended` renders a small amber "Recommended" badge next to the
    title -- amber spent on ATTENTION, per `webtheme.py`'s own token
    convention, and used nowhere else on this row. The caller
    (`_setup_method_options_html`) derives which single method (if any)
    earns it from live host state via `_setup_recommended_method`; this
    function never decides that itself, it only renders the decision.
    """
    btn = (
        f'<button type="submit" class="secondary" disabled '
        f'style="opacity:.4;cursor:not-allowed" title="{_esc(disabled_reason)}">Generate</button>'
        if disabled
        else '<button type="submit" class="secondary">Generate</button>'
    )
    badge = (
        ' <span style="color:var(--amber);font-weight:700;text-transform:none;'
        'letter-spacing:normal">&bull; Recommended</span>'
        if recommended
        else ""
    )
    return f"""
    <div class="formsec">
      <span class="flegend">{_esc(title)}{badge}</span>
      <p class="subtle" style="margin-top:8px">{description}</p>
      <p class="subtle" style="margin-top:6px">
        <b style="color:var(--ink)">When to pick this:</b> {when_to_pick}</p>
      <p class="subtle" style="margin-top:6px">{availability_html}</p>
      <p class="subtle" style="margin-top:8px">CLI equivalent: <code>{_esc(command)}</code></p>
      <form method="post" action="/setup/tls" style="margin-top:10px">
        <input type="hidden" name="method" value="{_esc(method)}">
        {btn}
      </form>
    </div>
    """


def _setup_recommended_method(*, tailscale_available: bool) -> str:
    """Which method earns the "Recommended" badge, derived from LIVE host
    state -- never hardcoded, never cached across renders.

    Tailscale when this host can actually reach a tailnet: zero install on
    any device, browser-trusted with no warning, the best case for
    personal use. Local CA otherwise: the next-best option, since it is
    *always* available and covers this host's LAN IP (which a Tailscale
    cert, scoped to the tailnet name only, never will) -- the one-time
    per-device install cost is real, but the `/trust` bootstrap page (see
    `_setup_trust_bootstrap_url`) makes paying it painless.

    Self-signed is never recommended: every host always has a strictly
    better option available (Local CA is unconditionally available -- see
    `_setup_method_options_html`), so badging it would misrepresent a real
    trade-off as a coin flip. Reflects this task's core, hard constraint
    honestly: a public certificate authority can only vouch for a name it
    can verify, never a bare LAN IP or a private hostname -- so the
    "zero-friction" option (Tailscale) is only ever available when this
    host is actually reachable that way.
    """
    return "tailscale" if tailscale_available else "ca"


def _setup_friction_spectrum_html(*, recommended: str) -> str:
    """The FRICTION SPECTRUM: a short, scannable guide -- rendered above
    the method rows below -- to which TLS method fits how a device
    actually reaches this server. States the one hard constraint plainly
    up front (a publicly-trusted certificate can only be issued for a name
    a public CA can verify -- never a bare LAN IP or a private hostname)
    so the trade-offs below read as consequences of that constraint, not
    arbitrary preferences.

    `recommended` (from `_setup_recommended_method`) marks exactly one
    entry "recommended for personal use" inline -- never self-signed, see
    that function's docstring for why.
    """

    def _mark(method: str) -> str:
        return (
            ' <span style="color:var(--amber);font-weight:700">&mdash; recommended for '
            "personal use</span>"
            if recommended == method
            else ""
        )

    return f"""
    <div class="formsec">
      <span class="flegend">Which method fits how you reach this server?</span>
      <p class="subtle" style="margin-top:8px">A publicly-trusted certificate can only be
        issued for a name a public certificate authority can verify &mdash; never a bare LAN
        IP or a private hostname. That is a hard constraint, not a preference, and it is what
        decides the right method below:</p>
      <p class="subtle" style="margin-top:12px">
        <b style="color:var(--ink)">Tailscale name</b>{_mark("tailscale")} &mdash;
        browser-trusted, zero install, works from any device already on your tailnet. Covers
        only the tailnet name, never the bare LAN IP.</p>
      <p class="subtle" style="margin-top:8px">
        <b style="color:var(--ink)">Local CA</b>{_mark("ca")} &mdash; covers the LAN IP,
        hostname, and tailnet name together, but needs a one-time CA install per device
        &mdash; painless via the <span class="mono">/trust</span> page (see below once one is
        configured).</p>
      <p class="subtle" style="margin-top:8px">
        <b style="color:var(--ink)">Self-signed</b> &mdash; works anywhere, on any device,
        with a browser warning every single visit. Best for a quick check, not a device
        you'll return to.</p>
    </div>
    """


def _setup_trust_bootstrap_url(request: Request) -> tuple[str, bool]:
    """The `/trust` bootstrap URL for THIS host, for cross-linking from the
    Local CA section -- see `webtrust.py`'s module docstring for what that
    page is and why it exists (installing the CA over plain HTTP, before
    ever hitting an HTTPS warning).

    Prefers the REAL configured companion port, threaded onto
    `request.app.state.web_http_port` by `create_app`'s caller (`run()` /
    `supervisor.py`'s serve loop) from `resolve_web_config`'s own
    `http_port` -- the exact port the trust-bootstrap listener is actually
    bound to on this deployment. Falls back to the documented default
    pattern (https port + 1 -- the same default `_resolve_http_bootstrap_
    port` itself applies when `--web-http-port` is omitted) when that real
    value isn't known at render time (e.g. an app built without threading
    it through, as most of this module's own tests do).

    Returns `(url, is_real)` so the caller can be honest about which case
    produced it -- never silently presenting a guessed port as certain.
    """
    hostname = request.url.hostname or "this-host"
    configured = getattr(request.app.state, "web_http_port", None)
    if isinstance(configured, int):
        return f"http://{hostname}:{configured}/trust", True
    https_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return f"http://{hostname}:{https_port + 1}/trust", False


def _setup_method_options_html() -> str:
    """METHOD OPTIONS: Tailscale (browser-trusted, tailnet name only) ->
    local CA (trusted after installing the CA once per device; covers LAN
    IP + hostname + tailnet -- best default for a LAN deployment) ->
    self-signed (works everywhere, browser warning) -- the friction
    ordering itself never changes. What DOES change, live, is which one
    is badged "Recommended" (see `_setup_recommended_method`) -- fixed
    friction ranking, floating recommendation, rather than reshuffling the
    rows underneath whoever is reading them. Availability is PROBED live
    on every render (`WT.detect_tailscale()`), never assumed or cached --
    Tailscale's own connection state can change between one page load and
    the next.
    """
    tailscale_info = WT.detect_tailscale()
    recommended = _setup_recommended_method(tailscale_available=tailscale_info is not None)
    if tailscale_info:
        ts_availability = (
            '<span style="color:var(--ink)">Available</span> &mdash; tailnet host '
            f'<span class="mono">{_esc(tailscale_info["hostname"])}</span>'
        )
        ts_disabled, ts_reason = False, ""
    else:
        ts_availability = (
            '<span class="muted">Not available on this host</span> &mdash; Tailscale is not '
            "installed, or this host is not connected to a tailnet"
        )
        ts_disabled = True
        ts_reason = "Tailscale is not installed or not connected on this host"

    rows = [
        _setup_method_row(
            method="tailscale",
            # A plain apostrophe, not the `&rsquo;` named entity -- this
            # title is passed through `_esc()` (see `_setup_method_row`),
            # which escapes literal `&` and would otherwise turn a named
            # entity into visible garbage (`&amp;rsquo;`) rather than a
            # curly quote. `_esc()` renders a plain `'` as the numeric
            # reference `&#x27;`, which every browser resolves correctly.
            title="Tailscale (Let's Encrypt)",
            description=(
                "A real, publicly-trusted certificate for this host's tailnet name, issued via "
                "Tailscale's own certificate service. No browser warning, on any device, anywhere."
            ),
            when_to_pick=(
                "you and every user are already on the same tailnet, and a clean install "
                "experience matters (e.g. installing this dashboard on a phone)."
            ),
            availability_html=ts_availability,
            command="amplifier-work-tracker setup-tls --method tailscale",
            disabled=ts_disabled,
            disabled_reason=ts_reason,
            recommended=(recommended == "tailscale"),
        ),
        _setup_method_row(
            method="ca",
            title="Local CA",
            description=(
                "Generates (or reuses) a persistent local certificate authority and signs a "
                "leaf certificate covering this host's hostname, LAN IP, and tailnet name (if "
                "any). Trusted after the CA is installed once on each client device -- painless "
                "via the /trust bootstrap page (no browser warning, no login -- see the "
                "download and per-OS install steps below once one is active)."
            ),
            when_to_pick=(
                "you're serving more than one user/device on your LAN and want a clean install "
                "without depending on Tailscale."
            ),
            availability_html='<span style="color:var(--ink)">Always available</span>',
            command="amplifier-work-tracker setup-tls --method ca",
            disabled=False,
            recommended=(recommended == "ca"),
        ),
        _setup_method_row(
            method="selfsigned",
            title="Self-signed",
            description=(
                "A single self-signed certificate covering this host's hostname, LAN IP, and "
                "tailnet name (if any). Works everywhere, on every device, with no install step."
            ),
            when_to_pick=(
                "you just want HTTPS quickly and can tolerate (or click through) a one-time "
                "browser security warning on each device."
            ),
            availability_html='<span style="color:var(--ink)">Always available</span>',
            command="amplifier-work-tracker setup-tls --method selfsigned",
            disabled=False,
            recommended=False,
        ),
    ]
    return _setup_friction_spectrum_html(recommended=recommended) + "".join(rows)


def _setup_ca_download_html(request: Request) -> str:
    """CA download + per-OS install instructions -- rendered ONLY when a
    local CA is actually configured on this host (`WT.default_ca_cert_path
    ().exists()`); otherwise there is nothing to install and this section
    is simply absent, never a dead link.

    The install commands are copied verbatim from `cli.py`'s own
    `cmd_setup_tls` (`--method ca` branch) so the terminal and the browser
    never give a deployer two different sets of instructions for the same
    action.

    Leads with a cross-link to the plain-HTTP `/trust` bootstrap page
    (`webtrust.py`) -- the guided, no-warning, no-login install flow for a
    NEW device -- before the manual per-OS commands below, since it is the
    easier path whenever it applies. `request` is needed only to build
    that URL (`_setup_trust_bootstrap_url`); every other line here is
    unchanged from before this cross-link existed.
    """
    if not WT.default_ca_cert_path().exists():
        return ""
    trust_url, is_real = _setup_trust_bootstrap_url(request)
    trust_caveat = (
        ""
        if is_real
        else (
            ' <span class="muted">(the default companion-port pattern &mdash; confirm the '
            "exact port if this deployment set <code>--web-http-port</code> explicitly)</span>"
        )
    )
    return f"""
    <div class="formsec">
      <span class="flegend">Install the local CA</span>
      <p class="subtle" style="margin-top:8px">A local CA is configured on this host. Install it
        once on each client device to eliminate the browser warning for the Local CA certificate
        above. The leaf certificate rotates yearly without re-trusting anything -- the CA is the
        one thing you install.</p>
      <p class="subtle" style="margin-top:12px"><b style="color:var(--ink)">Adding a new
        device?</b> Skip the manual steps below &mdash; open <code>{_esc(trust_url)}</code> on
        that device and follow its guided install.{trust_caveat} It needs no login and no
        browser warning to reach; everything else on that port simply redirects here.</p>
      <p style="margin-top:10px"><a class="btn secondary" href="/setup/ca.crt">Download CA
        certificate</a></p>
      <p class="subtle" style="margin-top:16px">
        <b style="color:var(--ink)">Windows</b> (PowerShell, no admin needed):</p>
      <p class="subtle"><code>Import-Certificate -FilePath &lt;path-to-ca.crt&gt;
        -CertStoreLocation Cert:\\CurrentUser\\Root</code></p>
      <p class="subtle" style="margin-top:12px"><b style="color:var(--ink)">macOS</b>:</p>
      <p class="subtle"><code>sudo security add-trusted-cert -d -r trustRoot -k
        /Library/Keychains/System.keychain &lt;path-to-ca.crt&gt;</code></p>
      <p class="subtle" style="margin-top:12px">
        <b style="color:var(--ink)">Linux</b> (system-wide):</p>
      <p class="subtle"><code>sudo cp &lt;path-to-ca.crt&gt;
        /usr/local/share/ca-certificates/ &amp;&amp; sudo update-ca-certificates</code></p>
      <p class="subtle" style="margin-top:12px"><b style="color:var(--ink)">iOS</b>: open the
        downloaded file to install the profile, then enable full trust for it under
        Settings &rsaquo; General &rsaquo; About &rsaquo; Certificate Trust Settings.</p>
    </div>
    """


def _setup_body(request: Request) -> str:
    heading_style = (
        "font-family:var(--sans);font-size:24px;font-weight:500;color:var(--ink);margin:20px 0 4px"
    )
    return f"""
    {_flash(request)}
    <h1 style="{heading_style}">Setup</h1>
    <p class="subtle">TLS/HTTPS configuration for this deployment.</p>
    {_tls_status_html(request)}
    {_setup_method_options_html()}
    {_setup_ca_download_html(request)}
    """


# The only three methods `webtls.py`/`cli.py`'s `setup-tls --method` can
# actually act on -- see this section's own module-level comment for why
# there is deliberately no fourth (`mkcert`) entry. `POST /setup/tls`
# refuses anything else with a 400, never a silent no-op.
_SETUP_TLS_METHODS = frozenset({"tailscale", "ca", "selfsigned"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    workspace: A.Workspace, auth: WA.AuthConfig, *, web_http_port: int | None = None
) -> FastAPI:
    """Build the dashboard app.

    `web_http_port`, when given, is the port the companion plain-HTTP
    trust-bootstrap listener (`webtrust.create_trust_app`) is ACTUALLY
    bound to for this deployment -- the same value `resolve_web_config`
    computed as `WebServerConfig.http_port` and that `run()` / the
    integrated `serve --web-port` loop (`supervisor.py`) hand to
    `webtrust.create_trust_app(https_port=...)` for the real listener.
    Threaded onto `app.state.web_http_port` so `/setup`'s Local CA section
    can cross-link the REAL `/trust` URL (see `_setup_trust_bootstrap_url`)
    instead of only the documented https-port+1 pattern. `None` (the
    default -- e.g. this app built directly, as most of this module's own
    tests do) means that real value isn't known here; the render falls
    back to the pattern honestly rather than guessing.
    """
    app = FastAPI(title="amplifier-work-tracker", docs_url=None, redoc_url=None)
    app.add_middleware(AuthMiddleware, auth=auth)
    app.state.web_http_port = web_http_port

    # -----------------------------------------------------------------------
    # webapp-routes lane helpers -- route-owned, defined INSIDE create_app so
    # they never collide with the module-level render helpers owned by the
    # dashboard-render / item-render / shell-nits lanes. They call those
    # helpers and the adapter seam; they never rewrite a helper body.
    # -----------------------------------------------------------------------

    def _impairment_label(name: str, summary: A.ProjectSummary) -> str | None:
        """A short, human-facing condition for a project that must NEVER be
        allowed to read as a healthy, empty queue -- the stop-ship signal.

        Returns one of "Being created", "Creation unfinished", "Broken", or
        ``None`` when the project is genuinely OK.

        A project caught mid-creation (or left broken by a creation that
        never finished) can still answer ``list()`` with an empty result and
        so land as ``status == "ok"`` with every count zero -- pixel-identical
        to a healthy but empty queue (measured outage, 2026-08-15; see
        `adapter.Workspace.creation_state`). That is exactly the confusion
        this signal exists to prevent.

        Intended data source: a broken/creating field on `A.ProjectSummary`
        produced by the adapter-data lane. Until that merges in this
        worktree we derive the minimal signal directly from
        `Workspace.creation_state` (read-only, side-effect free) plus the
        summary's own read-error status. See DONE.json residuals.
        """
        state = workspace.creation_state(name)
        if state == "creating":
            return "Being created"
        if state == "abandoned":
            return "Creation unfinished"
        if summary.status != "ok":
            return "Broken"
        return None

    def _impairment_banner(pairs: list[tuple[str, str]]) -> str:
        """An unmissable, top-of-page alert naming every impaired project and
        its condition, so a backend-broken or mid-creation project can never
        be mistaken for a healthy empty queue wherever it is listed."""
        if not pairs:
            return ""
        rows = "".join(
            f'<li><a href="/projects/{_esc(n)}">{_esc(n)}</a> '
            f"&mdash; <strong>{_esc(cond)}</strong></li>"
            for n, cond in pairs
        )
        noun = "project is" if len(pairs) == 1 else "projects are"
        return (
            '<div class="flash flash-error" role="alert">'
            f"Heads up &mdash; {len(pairs)} {noun} not healthy and must not be "
            "read as an empty queue:"
            f'<ul style="margin:8px 0 0;padding-left:22px">{rows}</ul>'
            "</div>"
        )

    def _item_search_key(i: A.Item) -> str:
        """The same searchable text `_item_row` encodes into each row's
        `data-t` attribute -- kept deliberately in sync so a server-side
        search and the row it matches agree on what is searchable. (If
        `_item_row`'s key changes, this must follow -- see DONE.json
        residual proposing one shared key helper.)"""
        return f"{i.id} {i.title} {i.status} {i.holder or ''}".lower()

    def _filtered_pagination(
        name: str,
        status: str | None,
        q: str,
        page: int,
        total_pages: int,
        result: A.ListResult,
    ) -> str:
        """Filter-aware pagination footer: identical layout to
        `_pagination_html`, but every page href also carries the active `q`
        so paging a filtered view never silently drops the filter. Used only
        when a search is active; the unfiltered path reuses `_pagination_html`
        verbatim. This nested copy exists only because that helper -- owned by
        the shell-nits lane -- has no `q` parameter yet (see DONE.json
        residual proposing it take one so this can be deleted)."""
        if total_pages <= 1:
            return ""

        def _href(p: int) -> str:
            parts = [f"page={p}"]
            if status:
                parts.append(f"status={quote(status)}")
            parts.append(f"q={quote(q)}")
            return f"/projects/{_esc(name)}?{'&'.join(parts)}"

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

    # --------------------------------------------------------------- health

    @app.get("/healthz")
    async def healthz():  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    # ---------------------------------------------------------------- pwa
    #
    # Manifest, service worker, and icons -- see webpwa.py's module
    # docstring for what these are and why the service worker caches
    # nothing. All five are auth-exempt (see `_AUTH_EXEMPT_PATHS` above)
    # and served `Cache-Control: no-cache` -- every one of them must
    # revalidate on every fetch, same policy muxplex applies to its whole
    # PWA surface, for the same reason (a stale service worker or a stale
    # manifest is exactly the class of bug a monitoring dashboard cannot
    # afford).

    @app.get("/manifest.json")
    async def pwa_manifest():  # type: ignore[no-untyped-def]
        return Response(
            PWA.MANIFEST_JSON,
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js")
    async def pwa_service_worker():  # type: ignore[no-untyped-def]
        return Response(
            PWA.SERVICE_WORKER_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/pwa-192.png")
    async def pwa_icon_192():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("pwa-192.png"),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/pwa-512.png")
    async def pwa_icon_512():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("pwa-512.png"),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/apple-touch-icon.png")
    async def pwa_apple_touch_icon():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("apple-touch-icon.png"),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    # Favicons -- same rationale/policy as the five PWA routes above (auth-
    # exempt, no-cache): a browser fetches the tab icon before/independent
    # of any login. `favicon.ico` bundles 16/32/48 in one multi-resolution
    # file (`<link rel="icon" href="/favicon.ico" sizes="any">`);
    # `favicon-32.png` is the modern PNG variant browsers prefer when both
    # are offered (`<link rel="icon" type="image/png" href="/favicon-32.png">`).
    # See `scripts/gen_pwa_icons.py` for how both are generated from the
    # same brand source as the PWA icons.

    @app.get("/favicon.ico")
    async def favicon_ico():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("favicon.ico"),
            media_type="image/x-icon",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon-32.png")
    async def favicon_32():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("favicon-32.png"),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    # Open Graph / social-preview card -- optional, but cheap: lets a link
    # to this dashboard render a real preview image (chat apps, Slack,
    # issue trackers) instead of a blank/generic card. Same auth-exempt +
    # no-cache policy; scrapers fetch it unauthenticated, same as the PWA
    # assets above.

    @app.get("/og-dark.png")
    async def og_card():  # type: ignore[no-untyped-def]
        return Response(
            PWA.icon_bytes("og-dark.png"),
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

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

    # ---------------------------------------------------------------- setup
    #
    # Authenticated deployer-facing TLS status + method options -- see this
    # module's own "/setup" section (above, module-level render helpers) for
    # the full design rationale. Deliberately NOT in `_AUTH_EXEMPT_PATHS`:
    # unlike the PWA assets, none of this needs to be reachable before login
    # -- it exists for whoever is already operating this deployment.

    @app.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request):  # type: ignore[no-untyped-def]
        return _page(
            request,
            "Setup",
            _setup_body(request),
            crumb_html=_crumb(("/", "All projects"), ("", "Setup")),
        )

    @app.get("/setup/ca.crt")
    async def setup_ca_download():  # type: ignore[no-untyped-def]
        """Serve the local CA certificate generated by `--method ca`, if one
        exists on this host. Authenticated like the rest of `/setup` (not
        auth-exempt) -- the bytes aren't secret (a CA cert is public by
        design), but gating it behind the same session as the rest of this
        page is the simplest correct answer and costs nothing real."""
        ca_path = WT.default_ca_cert_path()
        if not ca_path.exists():
            return JSONResponse(
                {"detail": "no local CA certificate is configured on this host"}, status_code=404
            )
        return Response(
            ca_path.read_bytes(),
            media_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="amplifier-work-tracker-ca.crt"'},
        )

    @app.post("/setup/tls")
    async def setup_generate_tls(method: str = Form(...)):  # type: ignore[no-untyped-def]
        """Generate a TLS certificate at the well-known default path,
        IN-PROCESS via `webtls.py`'s own generation functions -- never by
        shelling out to the `setup-tls` CLI (this process already has
        everything that command has: the same functions, the same default
        paths).

        Refuses (400, JSON, never a silent no-op) for an unknown method or
        one that is not actually available on this host right now (e.g.
        `tailscale` requested but not connected) -- the SAME refusal
        whether or not `/setup`'s own button for that method happened to be
        rendered disabled; that rendering is a UI courtesy, this is the
        real gate.

        On success, redirects back to `/setup` with a flash summarizing the
        new certificate (method, SAN coverage, expiry) and, honestly, that
        a restart is required -- this running uvicorn process cannot
        hot-swap the TLS material it already bound to at startup. The
        freshly-rendered TLS STATUS card on that reload reads the new file
        straight off disk, so the file-level change is visible immediately
        even though the live scheme will not flip until the service is
        actually restarted.
        """
        if method not in _SETUP_TLS_METHODS:
            return JSONResponse({"detail": f"unknown TLS method '{method}'"}, status_code=400)

        cert_path = WT.default_cert_path()
        key_path = WT.default_key_path()

        if method == "tailscale":
            tailscale_info = WT.detect_tailscale()
            if tailscale_info is None:
                return JSONResponse(
                    {
                        "detail": (
                            "Tailscale is not installed or not connected on this host -- "
                            "cannot generate a Tailscale certificate."
                        )
                    },
                    status_code=400,
                )
            result = WT.generate_tailscale(cert_path, key_path, tailscale_info["hostname"])
            if result is None:
                return JSONResponse(
                    {"detail": "Tailscale certificate generation failed -- see server logs."},
                    status_code=400,
                )
        elif method == "ca":
            ca_cert_path = WT.default_ca_cert_path()
            ca_key_path = WT.default_ca_key_path()
            WT.generate_local_ca(ca_cert_path, ca_key_path)
            leaf_hostnames, leaf_ips = WT.default_leaf_sans()
            result = WT.generate_leaf_signed_by_ca(
                ca_cert_path,
                ca_key_path,
                cert_path,
                key_path,
                hostnames=leaf_hostnames,
                ip_addresses=leaf_ips,
            )
        else:  # "selfsigned" -- the only remaining member of _SETUP_TLS_METHODS
            leaf_hostnames, leaf_ips = WT.default_leaf_sans()
            result = WT.generate_self_signed(
                cert_path, key_path, hostnames=leaf_hostnames, ip_addresses=leaf_ips
            )

        hostnames_str = ", ".join(result["hostnames"])
        expires = result["expires"]
        expires_str = expires.strftime("%Y-%m-%d") if hasattr(expires, "strftime") else str(expires)
        msg = (
            f"Generated a {method} certificate (covers {hostnames_str}; expires {expires_str}). "
            "Restart the service to serve it: amplifier-work-tracker service restart"
        )
        return _redirect("/setup", msg=msg)

    # ------------------------------------------------------------ dashboard

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):  # type: ignore[no-untyped-def]
        names = workspace.names()
        summaries = [A.project_summary(workspace, n) for n in names]

        if not names:
            body = (
                f"{_flash(request)}"
                '<section class="sec heroic"><div class="hero">'
                f"{_ledger_hero_html(0, 0, None)}</div></section>"
                '<div class="hr bleed"></div>'
                '<section class="sec"><div class="empty-state"><p>No projects yet. '
                "Create one below to get started.</p></div></section>"
                f'<section class="sec">{_create_project_form()}</section>'
            )
            sb = T.statusbar('<span class="s"><span class="dot on"></span>No projects yet</span>')
            return _page(
                request,
                "Dashboard",
                body,
                statusbar_html=sb,
                auto_refresh_ms=_AUTO_REFRESH_MS,
                sidebar_html=_sidebar_html([], [], None),
            )

        ordered = sorted(summaries, key=_dashboard_sort_key)
        buckets = _aggregate_buckets(summaries)

        ok = [s for s in summaries if s.status == "ok"]
        broken = [s for s in summaries if s.status != "ok"]

        # F1 -- one reconciled workspace roll-up, so no two figures on the
        # page are computed two different ways and left free to disagree.
        # Every total below covers the readable queues only (a queue whose
        # database cannot be read contributes no honest number).
        readable_count = len(ok)
        reconciled_items = sum(s.total or 0 for s in ok)
        ready_total = sum(s.ready or 0 for s in ok)
        held_total = sum(s.held or 0 for s in ok)
        blocked_total = sum(s.blocked or 0 for s in ok)
        deferred_total = sum(s.deferred or 0 for s in ok)
        resolved_total = sum(s.resolved or 0 for s in ok)
        _activity_stamps = [s.last_activity for s in ok if s.last_activity]
        workspace_last_activity = max(_activity_stamps) if _activity_stamps else None

        impaired = [(s.name, lbl) for s in summaries if (lbl := _impairment_label(s.name, s))]
        impaired_banner = _impairment_banner(impaired)

        # F2 -- concentration: the single biggest ready queue, so a
        # workspace-wide READY total never hides one queue quietly
        # drowning under the rest. `None` (never an arbitrary 0-ready
        # "winner") when nothing is ready anywhere.
        ranked = [s for s in ok if (s.ready or 0) > 0]
        concentration = None
        if ranked and ready_total:
            top = max(ranked, key=lambda s: s.ready or 0)
            concentration = (top.name, top.ready or 0, (top.ready or 0) / ready_total * 100)

        # F3 -- waiting 7d+, straight from the SAME `ready_age_buckets`
        # roll-up `_heartbeat_html`'s histogram draws from (`buckets["7+"]`),
        # so this reading and the histogram's own oldest band can never
        # disagree. `_global_oldest`/`_oldest_ready_item` (unchanged) supply
        # the one real item "oldest Nd" attributes to and links.
        n7d = buckets.get("7+", 0)
        pct7d = (n7d / ready_total * 100) if ready_total else None
        winner = _global_oldest(summaries)
        oldest_days: int | None = None
        oldest_href: str | None = None
        if winner and n7d:
            winner_name, winner_age = winner
            oldest_days = int(winner_age // 86400)
            oldest_item = _oldest_ready_item(workspace.project(winner_name))
            item_path = f"/items/{_esc(oldest_item.id)}" if oldest_item is not None else ""
            oldest_href = f"/projects/{_esc(winner_name)}{item_path}"

        # F4 -- throughput, partitioned into measurable (a real 0, or a
        # dated resolution) vs unmeasurable (has resolved items but no
        # `closed_at` on any of them -- `project_activity`'s own honest-None
        # case). Excluding the unmeasurable set is what keeps
        # `resolved_24h_total`/`resolved_7d_total` real instead of a silent
        # under-count wearing a workspace-wide figure's clothes.
        measurable = [s for s in ok if s.resolved_24h is not None]
        resolved_24h_total = sum(s.resolved_24h or 0 for s in measurable)
        resolved_7d_total = sum(s.resolved_7d or 0 for s in measurable)
        resolved_measurable_total = sum(s.resolved or 0 for s in measurable)
        older_than_7d = max(0, resolved_measurable_total - resolved_7d_total)
        prior6d_total = max(0, resolved_7d_total - resolved_24h_total)
        prior6d_rate = prior6d_total / 6.0
        delta_pct = (
            round((resolved_24h_total / prior6d_rate - 1) * 100) if prior6d_rate > 0 else None
        )
        n_with_resolutions = sum(1 for s in ok if (s.resolved or 0) > 0)
        n_measurable_with_resolutions = sum(1 for s in measurable if (s.resolved or 0) > 0)

        # A1 -- workspace-wide daily resolutions (oldest -> newest), summed
        # ONLY across the SAME `measurable` set F4 already partitioned out --
        # a project with resolved items but no `closed_at` contributes to
        # neither the aggregate throughput figures nor this histogram, one
        # partition, never two that could quietly disagree.
        resolved_daily_totals = [0] * A.DAILY_THROUGHPUT_WINDOW
        for s in measurable:
            for i, n in enumerate(s.resolved_daily or ()):
                if i < len(resolved_daily_totals):
                    resolved_daily_totals[i] += n

        burn_days = round(ready_total / resolved_24h_total, 1) if resolved_24h_total > 0 else None

        # The needs-you overview -- one render instant (`rendered_at`) anchors
        # every duration and the time-to-notice/act stamp. The verdict reads
        # the throughput/activity figures above so a DEAD/IDLE fleet cannot
        # wear a serene "all clear."
        rendered_at = datetime.now(UTC)
        # One read-only bag of the figures above, rendered from by every
        # registered dashboard widget (see the registry block above / widgets.py).
        ctx = _dashboard_context(
            summaries=summaries,
            ok=ok,
            rendered_at=rendered_at,
            buckets=buckets,
            reconciled_items=reconciled_items,
            ready_total=ready_total,
            held_total=held_total,
            blocked_total=blocked_total,
            deferred_total=deferred_total,
            resolved_total=resolved_total,
            resolved_24h_total=resolved_24h_total,
            resolved_7d_total=resolved_7d_total,
            prior6d_rate=prior6d_rate,
            delta_pct=delta_pct,
            older_than_7d=older_than_7d,
            n_measurable_with_resolutions=n_measurable_with_resolutions,
            n_with_resolutions=n_with_resolutions,
            resolved_daily_totals=tuple(resolved_daily_totals),
            workspace_last_activity=workspace_last_activity,
        )
        attention_entries = _attention_entries(ok)
        verdict_level, verdict_word, verdict_detail = _verdict(
            attention_entries,
            ready_total=ready_total,
            held_total=held_total,
            resolved_24h_total=resolved_24h_total,
            n_measurable=len(measurable),
            workspace_last_activity=workspace_last_activity,
            now=rendered_at,
        )
        verdict = _verdict_html(verdict_level, verdict_word, verdict_detail, rendered_at)
        needs_you = DASHBOARD_WIDGETS.render("needs-you", ctx)
        dispatch = _dispatch_html(ok)
        needs_section = (
            '<div class="hr bleed"></div>'
            f'<section class="sec tight nsec">{needs_you}{dispatch}</section>'
            if (needs_you or dispatch)
            else ""
        )

        hero = _ledger_hero_html(ready_total if readable_count else None, len(names), burn_days)
        secondary = _secondary_readings_html(
            concentration,
            n7d,
            pct7d,
            oldest_days,
            oldest_href,
            held_total,
            blocked_total,
            workspace_last_activity=workspace_last_activity,
            rendered_at=rendered_at,
        )
        composition = DASHBOARD_WIDGETS.render("workspace-composition", ctx)
        heartbeat = DASHBOARD_WIDGETS.render("ready-queue-by-age", ctx)
        throughput = DASHBOARD_WIDGETS.render("throughput", ctx)
        per_project = DASHBOARD_WIDGETS.render("per-project-overview", ctx)

        rows = "".join(_dashboard_row(s) for s in ordered)
        # `.tbl-scroll` is inert on desktop (a plain full-width block, no visual
        # change) and, below 600px, gives the fixed-colgroup queue table its OWN
        # horizontal scroll instead of overflowing the whole page -- the same
        # mechanism the project page's item table already uses (webtheme.py's
        # <=600px block). Without it the ~540px colgroup forced a body-wide
        # horizontal overflow at phone width, breaking the shipped mobile reflow.
        table = f"""<div class="tbl-scroll"><table class="tbl dense">
          <colgroup><col><col style="width:250px"><col style="width:70px">
            <col style="width:70px"><col style="width:80px"><col style="width:70px"></colgroup>
          <thead><tr>
            <th>Queue</th><th>Composition</th>
            <th class="r">Total</th><th class="r">Ready</th>
            <th class="r">Resolved</th><th class="r">Done&nbsp;%</th>
          </tr></thead>
          <tbody>{rows}</tbody>
          {_dashboard_totals(summaries)}
        </table></div>"""

        broken_foot = ""
        if broken:
            names_str = ", ".join(s.name for s in broken)
            n_broken = len(broken)
            broken_foot = (
                '<div class="foot"><span class="fm">Reconciled</span>'
                f"<span>Every total above covers the {readable_count} readable "
                f"queue{'s' if readable_count != 1 else ''} only "
                f"({reconciled_items} items). {n_broken} "
                f"queue{'s' if n_broken != 1 else ''} ({_esc(names_str)}) "
                "could not be read and are excluded from those totals.</span></div>"
            )

        # Layout (A7/C1): nav -> verdict -> HERO ROW (hero+secondary on the
        # left, throughput's sparkline on the right, matching the approved
        # blend-2 mockup's top row) -> WIDGET BAND (workspace-by-state,
        # ready-queue-by-age, per-project overview) -> the ranked needs-you
        # queue -> the detailed queue table. Verdict/absence-alarm/dispatch
        # are unchanged content, only repositioned lower (`needs_section`
        # now follows the widget band instead of leading it).
        body = f"""
        {_flash(request)}
        {impaired_banner}
        {verdict}
        <div class="hr bleed"></div>
        <section class="sec heroic">
          <div class="herorow">
            <div class="hero">{hero}{secondary}</div>
            <div class="hero-side">{throughput}</div>
          </div>
        </section>
        <div class="hr bleed"></div>
        <section class="sec tight">{composition}</section>
        <div class="hr bleed"></div>
        <section class="sec tight"><div class="context">{heartbeat}</div></section>
        <div class="hr bleed"></div>
        <section class="sec tight">{per_project}</section>
        {needs_section}
        <div class="hr bleed"></div>
        <section class="sec tight">
          <div class="controls">
            {T.search_field("Filter queues by name or state")}
            <span class="count" id="qc">{len(summaries)} QUEUES</span>
            {T.density_toggle_html()}
          </div>
          {table}
          {_units_legend_html()}
          {broken_foot}
        </section>
        <div class="hr bleed"></div>
        <section class="sec">{_create_project_form()}</section>
        """
        sb_left = ['<span class="s"><span class="dot on"></span>Sweep <b>healthy</b></span>']
        if oldest_days is not None:
            sb_left.append(
                f'<span class="s">Oldest waiting <b class="am">{oldest_days}d</b></span>'
            )
        if workspace_last_activity:
            sb_left.append(
                f'<span class="s">Last activity {_abs_and_rel(workspace_last_activity)}</span>'
            )
        sb = T.statusbar(
            "".join(sb_left),
            f'<span class="s">Held <b>{held_total}</b></span><a href="/">Refresh</a>',
        )
        return _page(
            request,
            "Dashboard",
            body,
            statusbar_html=sb,
            js=(
                T.search_js(len(summaries), "QUEUES", "tbody tr[data-t]")
                # Per-project-overview's own independent filter (goal
                # wtv3/finish, task 2) -- separate field/counter ids so it
                # never clobbers the queue table's `#q`/`#qc` above.
                + T.search_js(len(ok), "PROJECTS", ".projcard", "pq", "ppc")
                + T.list_controls_js()
            ),
            auto_refresh_ms=_AUTO_REFRESH_MS,
            sidebar_html=_sidebar_html(names, summaries, None),
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
        # D2 -- search tells the truth. `q` filters SERVER-side over the full
        # matching set (see the q-branch below), so the count and pagination
        # reflect real matches across the whole project, not just whatever
        # rows happened to be on the current page's DOM.
        q = (request.query_params.get("q") or "").strip()
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        # goal wtv3/project-page: which item the split-pane's right side
        # shows, exactly like webbrowse.py's own `?item=` (see that module's
        # docstring for the fresh-read-every-request contract this mirrors).
        selected_id = request.query_params.get("item") or None
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
        # Unfiltered project total for the current status filter -- the honest
        # denominator behind an "N OF M ITEMS" count when a search is active.
        project_total = None
        try:
            if q:
                # Server-side search: fetch the FULL matching set (bd's own
                # unlimited, exactly as list_bounded does internally), filter
                # it against the same searchable text every row exposes, THEN
                # window/paginate the FILTERED set. This is what makes the
                # count and pagination reflect real matches across the whole
                # project instead of the current page's 50 DOM rows.
                all_items = bd.list(status=status, include_resolved=(status is None), limit=0)
                project_total = len(all_items)
                needle = q.lower()
                matched = [i for i in all_items if needle in _item_search_key(i)]
                total = len(matched)
                total_pages = max(1, math.ceil(total / page_size)) if total else 1
                page = min(page, total_pages)
                offset = (page - 1) * page_size
                window = matched[offset : offset + page_size]
                result = A.ListResult(
                    items=window,
                    total_count=total,
                    returned_count=len(window),
                    truncated=(offset + len(window)) < total,
                    limit=page_size,
                    requested_limit=None,
                    offset=offset,
                )
            else:
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

        # Sidebar needs every project's summary, not just this one -- reuse
        # `summary` (already computed, above) for the current project rather
        # than reading it from `bd` a second time.
        sidebar_names = workspace.names()
        sidebar_summaries = [
            summary if n == name else A.project_summary(workspace, n) for n in sidebar_names
        ]

        # D1 -- a broken/mid-creation project must be unmissable on its own
        # page too, not just on the dashboard.
        impaired_label = _impairment_label(name, summary)
        impaired_banner = _impairment_banner([(name, impaired_label)] if impaired_label else [])

        # Per-project analogue of the dashboard's own attention signal --
        # same function, same "absent when calm, never a dimmed zero"
        # convention (see `_attention_signal_html`'s docstring). `None`-safe
        # counts only ever come from a healthy (`STATUS_OK`) summary; a
        # broken/mid-creation project already gets `impaired_banner` above
        # and has no real held/blocked/deferred counts to show here.
        attention_banner = (
            _attention_signal_html(
                summary.held or 0,
                summary.blocked or 0,
                summary.deferred or 0,
                summary.held_stale or 0,
            )
            if summary.status == A.STATUS_OK
            else ""
        )

        # D5 -- the status-tab counter row: real per-project counts, reused
        # verbatim from the same `summary` this route already computed
        # above (never a second, independently-derived count).
        tab_counts = _status_tab_counts(summary)
        tabs_html = _status_tabs_html(name, status, q, tab_counts)

        pagination_html = (
            _filtered_pagination(name, status, q, page, total_pages, result)
            if q
            else _pagination_html(name, status, page, total_pages, result)
        )

        # ------------------------------------------------------ split pane
        # goal wtv3/project-page: the item list + a read-only detail pane,
        # reusing webbrowse.py's shared split-pane machinery VERBATIM (the
        # same squircle row cards, gutter, rim-glow panes, and detail-pane
        # renderer the already-shipped `/browse` view uses) rather than a
        # second, drift-prone copy -- see `webbrowse.render_browse_body`'s
        # own docstring, which documents exactly these generalization hooks.
        # This route supplies what `/browse` deliberately has none of: the
        # status-tab `?status=` filter, the free-text `?q=` search, and
        # pagination (this project's own scale concern; `/browse` shows the
        # whole project unpaginated, a fine trade for a project small enough
        # that "everything, unpaginated" is itself the point).
        def _item_href(item: A.Item) -> str:
            """Preserve the active status/q/page filter across a row
            selection -- the SAME `?status=`/`?q=` carry-through
            `_tab_href`/pagination hrefs already do for their own links."""
            parts = []
            if page > 1:
                parts.append(f"page={page}")
            if status:
                parts.append(f"status={quote(status)}")
            if q:
                parts.append(f"q={quote(q)}")
            parts.append(f"item={quote(item.id)}")
            return f"/projects/{_esc(name)}?{'&'.join(parts)}"

        def _item_held_html(item: A.Item) -> str:
            """The row's own held/custody reading (goal wtv3/project-page,
            task 2) -- the SAME "genuinely held right now" gate and
            `_custody_html`/`_custody_reading` reading the retired table
            row (`_item_row`) used, so a held item's staleness is visible
            in the list without selecting it (see
            `test_full_write_flow_create_add_resolve_remove`'s "holder
            column shows the real, current holder" contract)."""
            custody_html = _custody_html(_custody_reading(item))
            if custody_html:
                return custody_html
            if item.holder and item.status == "held":
                return f"held by {_identity_html(item.holder)}"
            return ""

        selected_item: A.Item | None = None
        activity: list[A.ActivityEvent] = []
        detail_error: str | None = None
        if selected_id:
            # Fresh read every request -- same contract webbrowse.py's own
            # `browse()` route documents: an auto-refresh tick (this page
            # carries `auto_refresh_ms` below) or a redirect landing here
            # must never render a stale model.
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

        # D2 -- a real server-side search control. It is a GET form so the URL
        # carries the query, a hidden `status` input submits WITH it
        # (preserving the tab row's active filter -- see `_status_tabs_html`
        # above, which is now the sole status-filter control), and the count
        # below is the honest server figure -- not a client-side recount over
        # only the current page's rows. The count reads "matches OF
        # project-total" while searching, else the plain project total.
        search_hint = "Search titles, ids, holders and state"
        # The visible placeholder carries a quiet "  /" shortcut hint (see
        # webtheme.py's `search_field`, whose `.hint` overlay does the same
        # for the dashboard); `aria-label` stays the plain hint text -- a
        # screen reader announcing "...state slash" would be noise.
        search_placeholder = f"{search_hint}  /"
        clear_search = ""
        if q:
            clear_href = f"/projects/{_esc(name)}" + (f"?status={quote(status)}" if status else "")
            clear_search = f'<a class="clear-search" href="{clear_href}">clear</a>'
        qc_text = (
            f"{result.total_count} OF {project_total} ITEMS" if q else f"{result.total_count} ITEMS"
        )
        typed_cls = " typed" if q else ""
        status_hidden = (
            f'<input type="hidden" name="status" value="{_esc(status)}">' if status else ""
        )
        controls = f"""<form method="get" action="/projects/{_esc(name)}" class="controls">
            {status_hidden}
            <div class="field{typed_cls}" id="field">
              <span class="mag">{T.ICONS["mag"]}</span>
              <input id="q" name="q" type="search" autocomplete="off" spellcheck="false"
                     value="{_esc(q)}" placeholder="{_esc(search_placeholder)}"
                     aria-label="{_esc(search_hint)}">
            </div>
            <button type="submit">Search</button>
            {clear_search}
            <span class="count" id="qc">{qc_text}</span>
            {T.density_toggle_html()}
          </form>"""

        if result.items:
            empty_html = None
        elif q:
            # A search that matched nothing -- name the search (and any active
            # status), and offer a real one-click way back to the full list.
            clear_href = f"/projects/{_esc(name)}" + (f"?status={quote(status)}" if status else "")
            with_status = f" with status <code>{_esc(status)}</code>" if status else ""
            empty_html = (
                '<div class="empty-state"><p>No items match '
                f"<code>{_esc(q)}</code>{with_status}.</p>"
                f'<p><a href="{clear_href}">clear search</a></p></div>'
            )
        elif status:
            empty_html = (
                '<div class="empty-state"><p>No items match status '
                f"<code>{_esc(status)}</code>.</p>"
                f'<p><a href="/projects/{_esc(name)}">clear filter</a></p></div>'
            )
        else:
            empty_html = (
                '<div class="empty-state"><p>No items yet. Add the first one below.</p></div>'
            )

        split_html = webbrowse.render_browse_body(
            name,
            result.items,
            selected_item,
            activity,
            selected_id=selected_id,
            detail_error=detail_error,
            list_header_extra=f"{tabs_html}{controls}",
            list_footer_html=pagination_html,
            href_builder=_item_href,
            row_extra_builder=_item_held_html,
            empty_html=empty_html,
        )

        body = f"""
        {_flash(request)}
        {impaired_banner}
        {attention_banner}
        <section class="sec">{_project_hero_html(name, summary, oldest_item)}</section>
        <div class="hr bleed"></div>
        <section class="sec tight">
          {split_html}
        </section>
        <div class="hr bleed"></div>
        <section class="sec" id="add-item">
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
          <div class="formsec danger">
            <span class="flegend">Danger zone</span>
            <button type="button" id="rename-trigger" class="btn danger"
                    aria-expanded="false" aria-controls="rename-form">Rename this
              project&hellip;</button>
            <form method="post" action="/projects/{_esc(name)}/rename" id="rename-form"
                  style="margin-bottom:20px" hidden>
              <label for="new_name">New project name</label>
              <input type="text" id="new_name" name="new_name" autocomplete="off"
                     pattern="[a-z][a-z0-9_]{{1,30}}" required placeholder="new_project_name">
              <p class="field-hint">Lowercase letters, digits, underscores; must start with a
                letter. The item id prefix and every existing item's id stay exactly as they
                are -- only the project's name changes.</p>
              <div class="form-actions">
                <button type="submit" class="btn danger">Save</button>
                <button type="button" id="rename-cancel" class="btn secondary">Cancel</button>
              </div>
            </form>
            <script>{T.rename_disclosure_js()}</script>
            <a class="btn danger" href="/projects/{_esc(name)}/remove">Remove this
              project&hellip;</a>
          </div>
        </section>
        """
        held_display = summary.held if summary.status == "ok" else "\u2014"
        sb = T.statusbar(
            '<span class="s"><span class="dot on"></span>Sweep <b>healthy</b></span>'
            f'<span class="s">Held <b>{held_display}</b></span>',
            f'<a href="/projects/{_esc(name)}/browse">Browse</a> '
            f'<a href="/projects/{_esc(name)}">Refresh</a>',
        )
        # `browse_js()` -- the SAME progressive-enhancement row-selection +
        # scroll-preservation script `/browse` itself ships (see its own
        # docstring): this page reuses the identical `#browse-list`/
        # `#browse-detail` ids `render_browse_body` renders, so a plain
        # click still works with JS off, and JS-on selection swaps ONLY
        # the detail pane. `list_controls_js` -- density + `j`/`k`/`Enter`/
        # `Esc` row navigation, now generalized (see its own docstring) to
        # also cover `a.wtb-row[data-t]`, not just the item table.
        return _page(
            request,
            name,
            body,
            crumb_html=crumb,
            statusbar_html=sb,
            js=webbrowse.browse_js() + T.list_controls_js(),
            sidebar_html=_sidebar_html(sidebar_names, sidebar_summaries, name),
            auto_refresh_ms=_AUTO_REFRESH_MS,
            nav_project=name,
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

    # There is deliberately no `/projects/{name}/claim` route. Claiming is an
    # agent action taken through the `work_claim` tool (the atomic
    # claim/custody primitive) -- see this module's docstring. The route and
    # its two forms (project-level "claim next", item-level "Claim this
    # item") were removed together, rather than left as dead-but-reachable
    # endpoints, so there is no browser-facing way to race an agent's claim.

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
        #
        # There is deliberately no "Claim" control here (or anywhere else in
        # this web UI): claiming is an agent action taken through the
        # `work_claim` tool, which enforces the atomic claim/custody
        # machinery this browser has no business racing against. An open
        # item therefore has no action control at all on this page -- it is
        # readable, editable (see the form below), but not claimable from a
        # browser.
        if item.status == "held":
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
        links_html = _dependency_sections_html(name, item.links)

        # --------------------------------------------------------- activity
        # A page enrichment, not load-bearing: `Beads.activity` already
        # degrades honestly (comments-only, or empty) if `bd history`
        # itself errors -- never let a fetch failure here take down the
        # rest of this page (title/description/acceptance/design/status).
        try:
            activity_events = bd.activity(item.id)
        except A.BeadsError as e:
            logger.warning("item_detail %s/%s: activity feed unavailable: %s", name, item.id, e)
            activity_events = []
        activity_html = _activity_feed_html(activity_events)

        resolution_html = ""
        if item.status == "resolved" and item.resolution:
            resolution_html = (
                '<span class="eyebrow am" style="display:block;margin-top:30px">Resolution</span>'
                f'<div class="content-block">{_esc(item.resolution)}</div>'
            )

        # Read-only facts use `_fact_value_html` -- explicitly non-interactive
        # (`cursor:default`, no border/background) so they read as inert data
        # sitting beside the genuinely editable title/body fields below, not
        # as more form fields. "Queue" and "Reported by" keep their own
        # existing treatment (a real link; a humanized identity span) --
        # neither looks like an input either, so the distinction holds for
        # them too.
        facts = [
            ("Queue", f'<a href="/projects/{_esc(name)}">{_esc(name)}</a>'),
            ("Kind", _fact_value_html(item.kind or "--")),
            (
                "Priority",
                _fact_value_html(str(item.priority) if item.priority is not None else "--"),
            ),
        ]
        owner = item.raw.get("owner")
        if owner:
            facts.append(("Reported by", _identity_html(str(owner))))
        facts_kv = "".join(
            f'<div><span class="k">{_esc(k)}</span><span class="v">{v}</span></div>'
            for k, v in facts
        )

        # D2/#2 -- the SAME compact relative-age vocabulary the item table's
        # own Age column uses (`_item_age_html`), not a second, coarser
        # "12m ago" format for the same kind of value -- see that helper's
        # docstring.
        time_kv_parts = [
            ("Created", _item_age_html(item.created_at)),
            ("Updated", _item_age_html(item.updated_at)),
        ]
        if item.status == "resolved" and item.closed_at:
            time_kv_parts.append(("Resolved", _item_age_html(item.closed_at)))
        time_kv = "".join(
            f'<div><span class="k">{_esc(k)}</span><span class="v serif">{v}</span></div>'
            for k, v in time_kv_parts
        )

        # Same rule as `_item_row`'s Holder column: `item.holder` (bd's
        # `assignee`) survives resolution as a historical "who last held
        # this" fact -- real, but not a current custody holder. A "held by"
        # chip next to a RESOLVED/blocked/deferred status badge read as a
        # live contradiction (this project's `held` stat says 0). Only show
        # it when the item is genuinely held right now -- and, when it is,
        # show the SAME claim-age + staleness reading the row does (see
        # `_custody_reading`/`_custody_html`), not a bare identity, so the
        # detail page and the table row can never disagree about whether
        # this hold is stale.
        custody_html = _custody_html(_custody_reading(item))
        held_chip = (
            f'<span class="chip">{custody_html}</span>'
            if custody_html
            else (
                f'<span class="chip">held by {_identity_html(item.holder)}</span>'
                if (item.holder and item.status == "held")
                else ""
            )
        )

        # Title is styled to read at the same visual weight the old plain
        # `<h1>` had (26px/500), but AS an input -- the shared input rule's
        # visible border + `--raise` background is what signals "editable"
        # here, deliberately distinct from the plain, borderless
        # `_fact_value_html`/`.kv` text beside it (Kind, Priority, Status,
        # Holder, timestamps -- all lifecycle/read-only, never in this form).
        #
        # v3 firewall polish (task 3): a single-line `<input>` clips a long
        # title on the right with no way to see the rest -- an `<input>`
        # never wraps, it only scrolls its own box sideways. A `<textarea>`
        # posts under the SAME `name="title"` field the `/update` route
        # already reads (Form(...) does not care whether the tag was
        # `<input>` or `<textarea>`), so the Save form's contract is
        # unchanged; only the tag -- and therefore the wrapping behaviour --
        # changes. `resize:vertical` lets a reader manually reveal more of
        # a title long enough to still clip at 2 rows, without breaking the
        # form; `white-space:pre-wrap`+`overflow-wrap:anywhere` guarantee
        # the full value is always reachable (wrap first, break mid-word
        # only if a single unbroken run is itself wider than the field).
        title_input_style = (
            "font-family:var(--sans);font-size:20px;font-weight:500;"
            "letter-spacing:-.008em;color:var(--ink);max-width:900px;min-height:52px;"
            "resize:vertical;white-space:pre-wrap;overflow-wrap:anywhere"
        )
        textarea_style = "max-width:80ch;min-height:7rem"
        body = f"""
        {_flash(request)}
        <section class="sec">
        <div class="itemcard">
          <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
            <span class="muted">{_esc(item.id)}</span>
            {_item_state_html(item.status)}
            {held_chip}
          </div>
          <form method="post" action="/projects/{_esc(name)}/items/{_esc(item.id)}/update"
                style="margin-top:18px">
            <label for="title">Title</label>
            <textarea id="title" name="title" required rows="3"
                      style="{title_input_style}">{_esc(item.title)}</textarea>

            <div class="kv" style="margin-top:18px">{facts_kv}</div>
            <div class="kv" style="margin-top:10px">{time_kv}</div>

            <label for="description" class="eyebrow" style="display:block;margin:30px 0 0">
              Description</label>
            <textarea id="description" name="description" rows="6"
                      placeholder="No description provided."
                      style="{textarea_style}">{_esc(item.description or "")}</textarea>

            <label for="acceptance" class="eyebrow" style="display:block;margin:20px 0 0">
              Acceptance criteria</label>
            <textarea id="acceptance" name="acceptance" rows="4"
                      placeholder="No acceptance criteria provided."
                      style="{textarea_style}">{_esc(item.acceptance or "")}</textarea>

            <label for="design" class="eyebrow" style="display:block;margin:20px 0 0">
              Design notes</label>
            <textarea id="design" name="design" rows="4"
                      placeholder="No design notes provided."
                      style="{textarea_style}">{_esc(item.design or "")}</textarea>

            <p class="field-hint">Title, description, acceptance criteria and design notes are
              editable here and persist on Save. Status, holder and the timestamps above are
              lifecycle facts, not free-edit -- they change only through claim/resolve.</p>
            <button type="submit">Save changes</button>
          </form>

          {resolution_html}
          {links_html}
          {activity_html}
          {action_html}
        </div>
        </section>
        """
        return _page(
            request,
            f"{item.id} - {item.title}",
            body,
            crumb_html=_crumb(("/", "All projects"), (f"/projects/{name}", name), ("", item.id)),
            nav_project=name,
        )

    @app.post("/projects/{name}/items/{item_id}/update")
    async def update_item(  # type: ignore[no-untyped-def]
        name: str,
        item_id: str,
        title: str = Form(...),
        description: str = Form(""),
        acceptance: str = Form(""),
        design: str = Form(""),
    ):
        """The item-detail edit form's save action -- title/description/
        acceptance/design only. Status, holder, and every timestamp are
        rendered read-only on that page and have no field here at all: this
        route cannot touch lifecycle state, only content, mirroring
        `Beads.update`'s own narrow scope (see its docstring).

        A blank textarea is NOT how a caller clears a field -- see
        `Beads.update`'s docstring for why `None`/"leave unchanged" is this
        seam's convention, matching `add_item`'s own `description or None`
        just above. A field that already has a value and is submitted empty
        (e.g. a stray form reset) is therefore left as it was, never wiped.
        """
        try:
            item = workspace.project(name).update(
                item_id,
                title=title,
                description=description or None,
                acceptance=acceptance or None,
                design=design or None,
            )
        except A.BeadsError as e:
            return _redirect(f"/projects/{name}/items/{item_id}", error=_public_error_message(e))
        return _redirect(f"/projects/{name}/items/{item.id}", msg=f"saved {item.id}")

    @app.post("/projects/{name}/items/{item_id}/resolve")
    async def resolve(  # type: ignore[no-untyped-def]
        name: str, item_id: str, reason: str = Form(...), actor: str = Form(...)
    ):
        try:
            item = workspace.project(name).resolve(item_id, reason, actor=actor)
        except A.BeadsError as e:
            return _redirect(f"/projects/{name}/items/{item_id}", error=_public_error_message(e))
        return _redirect(f"/projects/{name}/items/{item.id}", msg=f"resolved {item.id}")

    # ------------------------------------------------------------ rename

    @app.post("/projects/{name}/rename")
    async def rename_project(name: str, new_name: str = Form(...)):  # type: ignore[no-untyped-def]
        """The Danger Zone's Rename control -- a thin wrapper over the same
        `Workspace.rename` the CLI's `rename` subcommand calls (see its
        docstring for the full contract: directory + shared-server database
        + bd's local metadata renamed together, atomically, refused while any
        item is HELD). `new_name` validation (the `NAME_RE` pattern, the
        "already taken" / "currently HELD" refusals) all happen inside
        `Workspace.rename` itself -- this route does not duplicate any of
        it, only translates the result into a redirect."""
        try:
            report = workspace.rename(name, new_name)
        except A.BeadsError as e:
            # `Workspace.rename`'s own refusal messages (invalid name, name
            # taken, HELD items, split state) are already safe and specific
            # -- surfaced verbatim, same treatment `remove_project` gives
            # `Workspace.remove`'s refusals, and for the same reason.
            return _redirect(f"/projects/{name}", error=str(e))
        return _redirect(
            f"/projects/{report.new}",
            msg=f"renamed project '{report.old}' to '{report.new}' ({report.item_count} items)",
        )

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

    from amplifier_work_tracker import webbrowse

    webbrowse.register(app, workspace)

    return app


# ---------------------------------------------------------------------------
# Uvicorn entry point -- what `cli.py`'s `cmd_web` calls.
# ---------------------------------------------------------------------------


@dataclass
class WebServerConfig:
    host: str
    port: int
    auth: WA.AuthConfig
    # Both set (never just one -- see resolve_web_config) means "serve
    # https"; both None (the default -- no TLS configured/found) means
    # "serve http", exactly as before TLS support existed.
    tls_cert: str | None = None
    tls_key: str | None = None
    # Set only when TLS is active AND a companion plain-HTTP trust-bootstrap
    # listener should run alongside it -- see `_resolve_http_bootstrap_port`
    # and `webtrust.py`'s module docstring for what that listener is and why
    # it exists. None (the default) means "no companion listener", exactly
    # like `tls_cert`/`tls_key` being None means "no TLS".
    http_port: int | None = None


def run(workspace: A.Workspace, config: WebServerConfig) -> int:
    """Run the dashboard, and -- when `config.http_port` is set -- the
    plain-HTTP trust-bootstrap listener (`webtrust.create_trust_app`)
    alongside it, on its own companion port.

    `uvicorn.run(...)` (the pre-existing, single-server call) is kept
    byte-for-byte for the common case (`http_port is None`) so nothing about
    ordinary http-only or https-only serving changes. Only when a companion
    listener is actually configured does this switch to running both
    `uvicorn.Server`s concurrently under one `asyncio.run` -- the same
    `uvicorn.Config` + `uvicorn.Server(...).serve()` shape
    `supervisor.web_server_loop` already uses for the integrated `serve
    --web-port` path, so the two callers never diverge on how a second
    listener is actually run.
    """
    import uvicorn

    app = create_app(workspace, config.auth, web_http_port=config.http_port)
    ssl_kwargs: dict = {}
    if config.tls_cert and config.tls_key:
        ssl_kwargs = {"ssl_certfile": config.tls_cert, "ssl_keyfile": config.tls_key}

    http_port = config.http_port
    if http_port is None:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info", **ssl_kwargs)
        return 0

    import asyncio

    from . import webtrust as WTR

    trust_app = WTR.create_trust_app(https_port=config.port, tls_cert_path=config.tls_cert)

    async def _run_both() -> None:
        primary = uvicorn.Server(
            uvicorn.Config(app, host=config.host, port=config.port, log_level="info", **ssl_kwargs)
        )
        trust = uvicorn.Server(
            uvicorn.Config(trust_app, host=config.host, port=http_port, log_level="info")
        )
        await asyncio.gather(primary.serve(), trust.serve())

    asyncio.run(_run_both())
    return 0


# ---------------------------------------------------------------------------
# Shared host/auth-mode resolution -- the ONE place `cmd_web` (cli.py) and
# the integrated `serve --web-port` path (supervisor.py's `web_server_loop`)
# both resolve their --host/--public/--auth-mode/--session-ttl inputs into a
# runnable `WebServerConfig`, so the two callers can never drift on what the
# non-loopback safety gate or the auth-mode defaulting actually mean.
#
# Lives here (not in cli.py) because it is genuinely shared, not because
# `cmd_web` is somehow secondary -- `resolve_web_config` has no argparse or
# CLI-exit dependency of its own, which is exactly what lets both a CLI
# command (which wants to `die()`) and an in-process supervisor task (which
# wants to raise loudly, never `sys.exit`) call the identical logic and
# handle the failure their own way.
# ---------------------------------------------------------------------------


class WebConfigError(RuntimeError):
    """Raised for a rejected host/auth-mode combination -- a non-loopback
    host requested without `public=True`, or an explicit `auth_mode` that
    cannot be satisfied (e.g. "pam" requested but the `pam` module isn't
    importable).

    Never exits the process itself -- this module has no CLI-exit
    dependency. `cli.py`'s `cmd_web` catches this and calls `die()`;
    `supervisor.py`'s integrated `--web-port` path re-raises it as
    `WebServerStartupError` so it fails loud through the exact same path a
    real bind failure does.
    """


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _resolve_tls(tls_cert: str | None, tls_key: str | None) -> tuple[str | None, str | None]:
    """Resolve `--tls-cert`/`--tls-key` (or `--web-tls-cert`/`--web-tls-key`)
    into the pair uvicorn should actually be given, or `(None, None)` for
    plain http -- shared by `resolve_web_config` so `web` and `serve
    --web-port` can never diverge on what "TLS is configured" means.

    Resolution order, fail-loud throughout (never a silent fallback to
    http for an operator-supplied path -- see `WebConfigError`'s own
    docstring on this function's caller):

      1. Both given explicitly: validated (both exist, both readable) and
         returned as-is. Either missing or unreadable -> `WebConfigError`
         naming the exact path(s) and `setup-tls` as the fix.
      2. Exactly one given: `WebConfigError` -- `--tls-cert`/`--tls-key`
         (or their `--web-*` equivalents) are a pair, never independent.
      3. Neither given: auto-detect the `setup-tls`-generated defaults
         (`webtls.default_cert_path()`/`default_key_path()`). Both present
         on disk -> use them (TLS on). Otherwise -> `(None, None)` (TLS
         off), identical to every `web`/`serve` invocation before TLS
         support existed.
    """
    import os

    if tls_cert is not None or tls_key is not None:
        if tls_cert is None or tls_key is None:
            raise WebConfigError(
                "--tls-cert and --tls-key must both be given together "
                f"(got --tls-cert={tls_cert!r} --tls-key={tls_key!r})"
            )
        cert_p = Path(tls_cert)
        key_p = Path(tls_key)
        missing = [str(p) for p in (cert_p, key_p) if not p.is_file()]
        if missing:
            raise WebConfigError(
                f"TLS cert/key not found: {', '.join(missing)}. Run "
                f"'amplifier-work-tracker setup-tls' to generate a certificate, or "
                f"check the paths given to --tls-cert/--tls-key."
            )
        unreadable = [str(p) for p in (cert_p, key_p) if not os.access(p, os.R_OK)]
        if unreadable:
            raise WebConfigError(
                f"TLS cert/key not readable: {', '.join(unreadable)}. Check file permissions."
            )
        return str(cert_p), str(key_p)

    default_cert = WT.default_cert_path()
    default_key = WT.default_key_path()
    if default_cert.is_file() and default_key.is_file():
        return str(default_cert), str(default_key)
    return None, None


def _resolve_http_bootstrap_port(
    http_port: int | None, *, tls_cert: str | None, port: int
) -> int | None:
    """Resolve `--http-port`/`--web-http-port` into the port the plain-HTTP
    trust-bootstrap listener (`webtrust.create_trust_app`) should actually
    bind, or `None` for "no companion listener" -- shared by
    `resolve_web_config` so `web` and `serve --web-port` can never diverge
    on when the bootstrap listener runs or which port it lands on.

    Gated strictly on TLS being active: with no TLS, the dashboard is
    already plain HTTP -- there is nothing to bootstrap trust FOR, so the
    listener is unnecessary regardless of what `http_port` was given (an
    explicit value is silently a no-op in that case; `resolve_web_config`
    still surfaces this in its returned messages so it is never a silent
    surprise).

    Resolution order, once TLS IS active:
      1. `http_port` given explicitly: used as-is, UNLESS it collides with
         the https `port` itself -- `WebConfigError` naming both ports (a
         real bind failure a caller could easily mistake for something
         else, so it is caught here instead).
      2. `http_port` omitted (`None`, the default): `port + 1`. Deliberately
         a small, predictable, adjacent offset -- not a "reserved" range or
         a fixed constant -- so a deployment that already chose its https
         port to avoid conflicts on this host gets a companion port that is
         very likely free too, one above it. An operator who needs a
         specific port passes `--http-port`/`--web-http-port` explicitly;
         a real collision at bind time still fails loud (uvicorn's own
         `OSError` -> `WebServerStartupError`/`SystemExit`), this is only a
         sane default, never a guarantee.
    """
    if tls_cert is None:
        return None
    if http_port is None:
        return port + 1
    if http_port == port:
        raise WebConfigError(
            f"--http-port/--web-http-port ({http_port}) must not be the same as the "
            f"https port ({port}) -- the trust-bootstrap listener and the dashboard "
            f"need their own ports."
        )
    return http_port


def resolve_web_config(
    *,
    host: str | None,
    public: bool,
    port: int,
    auth_mode: str,
    session_ttl: int,
    tls_cert: str | None = None,
    tls_key: str | None = None,
    http_port: int | None = None,
) -> tuple[WebServerConfig, list[str]]:
    """Resolve `--host`/`--public`/`--port`/`--auth-mode`/`--session-ttl`/
    `--tls-cert`/`--tls-key`/`--http-port` into a runnable `WebServerConfig`,
    applying the SAME non-loopback safety gate, auth-mode defaulting, TLS
    resolution, and trust-bootstrap-port resolution `cmd_web` has always
    applied -- factored out here so `serve --web-port` cannot silently
    diverge from `web`'s own rules.

    Returns `(config, messages)`. `messages` is an ordered list of
    human-readable startup lines (the password reveal or PAM sign-in
    instructions, a non-loopback-bind warning, a TLS-enabled note, and a
    trust-bootstrap note, each when applicable) -- returned rather than
    printed/logged here, since one caller wants `print(..., file=sys.stderr)`
    (`cmd_web`) and the other wants `logger.info` (the supervisor's
    `web_server_loop`).

    Raises `WebConfigError` -- never exits the process -- for a
    non-loopback `host` without `public=True`, an `auth_mode` that cannot
    be satisfied, a `tls_cert`/`tls_key` pair that is incomplete, missing,
    or unreadable (see `_resolve_tls`), or an `http_port` colliding with
    `port` (see `_resolve_http_bootstrap_port`) -- NEVER a silent fallback
    to http for an operator-supplied TLS path, matching this module's
    fail-loud contract everywhere else (`WebServerStartupError`, etc.).
    """
    if host is not None and host not in _LOOPBACK_HOSTS and not public:
        raise WebConfigError(
            f"refusing to bind non-loopback host {host!r} without --public/public=True. "
            f"This is an explicit safety gate, not a limitation of the auth itself "
            f"(auth is enforced regardless of bind address) -- pass --public to "
            f"confirm you intend this to be reachable beyond localhost."
        )
    effective_host = host if host is not None else ("0.0.0.0" if public else "127.0.0.1")  # noqa: S104

    try:
        mode = WA.resolve_auth_mode(auth_mode)
    except RuntimeError as e:
        raise WebConfigError(str(e)) from e

    messages: list[str] = []
    password = ""
    if mode == "password":
        password = WA.load_password() or WA.generate_and_save_password()
        messages.append(
            f"auth mode=password. Password file: {WA.password_path()} (0600). "
            f"Current password: {password}"
        )
    else:
        messages.append(
            f"auth mode=pam. Sign in as {WA.running_user()!r} with your system password."
        )

    secret = WA.load_or_create_secret()
    auth_config = WA.AuthConfig(
        mode=mode, secret=secret, ttl_seconds=session_ttl, password=password
    )

    if effective_host != "127.0.0.1":
        messages.append(
            "bound to a non-loopback address -- reachable from the LAN. Authentication is "
            "enforced for every request; there is no localhost bypass in this server "
            "(see webauth.py's module docstring)."
        )

    resolved_tls_cert, resolved_tls_key = _resolve_tls(tls_cert, tls_key)
    if resolved_tls_cert:
        messages.append(f"TLS enabled -- serving https (cert: {resolved_tls_cert}).")

    resolved_http_port = _resolve_http_bootstrap_port(
        http_port, tls_cert=resolved_tls_cert, port=port
    )
    if resolved_http_port is not None:
        messages.append(
            f"Trust bootstrap listening on http://{effective_host}:{resolved_http_port}/trust "
            "-- plain HTTP, no login, so a new device can install this host's CA before its "
            "first HTTPS visit. Serves ONLY the CA download/profile + a redirect to https."
        )
    elif http_port is not None:
        messages.append(
            f"--http-port/--web-http-port {http_port} given but TLS is not active -- ignored. "
            "There is nothing to bootstrap trust for when already serving plain http."
        )

    return (
        WebServerConfig(
            host=effective_host,
            port=port,
            auth=auth_config,
            tls_cert=resolved_tls_cert,
            tls_key=resolved_tls_key,
            http_port=resolved_http_port,
        ),
        messages,
    )


__all__ = [
    "AuthMiddleware",
    "WebConfigError",
    "WebServerConfig",
    "create_app",
    "resolve_web_config",
    "run",
]
