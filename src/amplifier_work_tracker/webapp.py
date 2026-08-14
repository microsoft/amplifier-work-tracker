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
(per-project counts, per-project "what changed most recently"), that logic
was added to the seam itself (`adapter.project_summary`), not duplicated
here -- see that function's docstring.

Auth is `webauth.py`, ported from muxplex's pattern (see that module's
docstring for exactly what was kept and what was deliberately changed).

Rendering is plain server-rendered HTML via small string-building helpers
below -- no template engine, no static asset pipeline, no client-side JS
framework. There is exactly one page style (`_STYLE`, inlined once) and no
external files to package/serve, which sidesteps an entire class of "which
paths are exempt from auth" hazard muxplex's own static-asset exemption had
to work around (see its `_is_real_static_asset` docstring).

Design notes (round 2 -- the redesign this docstring describes)
-----------------------------------------------------------------
The first cut of this UI shipped with no way to drill into an item's body
(description/acceptance criteria/resolution were write-only -- visible only
in the create form, unreachable forever after), a resolve form rendered
live on every single row of a 179-item table regardless of that row's
status, a "Health" column that could only ever read "ok", and a directed-
claim control that revealed no input field when selected. A design council
and a product council (13 lenses total) both converged on the same root
cause independently: the app taught a navigation grammar with its dashboard
project links (blue/underlined = "this leads somewhere") and then silently
withdrew that promise at the item level, where cells looked identical but
did nothing.

This revision:
  - Adds a real item detail page (`GET /projects/{name}/items/{item_id}`)
    -- the ONLY place description/acceptance/resolution/timestamps/links
    live. Every ID and title cell in every table is now a real link to it.
  - Removes the per-row resolve form entirely. Resolving (and, symmetrically,
    claiming a specific item) is a contextual action that lives only on
    that item's own detail page, and only when the item's status makes it
    applicable -- never rendered, not merely hidden, on a row.
  - Removes the "Health: ok" column (a signal that can't vary carries no
    information) and the dead claim-by-id radio toggle (directed claim
    still exists -- it now lives as a real "Claim this item" button on the
    item's own detail page, where there is always an unambiguous id).
  - Replaces the removed signals with ones that can actually vary:
    `blocked` count, who currently holds an item (`held_by`), and
    `last_activity` (most recent `updated_at` across a project's items) --
    see `adapter.ProjectSummary`.
  - Routes every BeadsError that can reach a browser through
    `_public_error_message` -- a raw adapter exception can contain a local
    filesystem path or a CLI-only instruction, neither of which belongs in
    front of someone using the web UI.
"""

from __future__ import annotations

import html
import logging
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


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _relative_time(ts: str | None) -> str:
    """Render an ISO-8601 UTC timestamp as a short, coarse relative string
    ("just now", "12m ago", "3h ago", "5d ago"), or "--" for missing/
    unparseable input.

    This is the mechanism that lets a dashboard/table cell carry a signal
    that actually varies over time instead of a value that is always the
    same -- see the module docstring and `adapter.ProjectSummary`.
    """
    dt = _parse_iso(ts)
    if dt is None:
        return "--"
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
    "--" when there is nothing to show. The absolute value is always
    available (as a tooltip) for anyone who wants exact precision; the
    relative value is what's readable at a glance."""
    if not ts:
        return '<span class="muted">--</span>'
    return f'<span title="{_esc(ts)}">{_esc(_relative_time(ts))}</span>'


def _now_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


_STATUS_LABELS = {
    "open": "open",
    "held": "held",
    "resolved": "resolved",
    "blocked": "blocked",
    "deferred": "deferred",
}


def _status_badge(status: str) -> str:
    cls = f"badge-{status}" if status in _STATUS_LABELS else "badge-unknown"
    label = _STATUS_LABELS.get(status, status)
    return f'<span class="badge {cls}">{_esc(label)}</span>'


# ---------------------------------------------------------------------------
# Rendering -- plain string building. `_esc` is the one choke point every
# user-controlled value must pass through before landing in HTML.
# ---------------------------------------------------------------------------

_STYLE = """
<style>
  :root {
    color-scheme: light dark;
    --ink: #1a2027; --ink-muted: #4b5563; --border: #d3d9e0;
    --surface: #f6f7f9; --accent: #2451b8; --accent-ink: #16326e;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 0; line-height: 1.45; color: var(--ink); background: #fff;
  }
  header {
    background: #16202b; color: #fff; padding: 0.7rem 1.25rem; display: flex;
    justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
  }
  header a.brand { color: #fff; text-decoration: none; font-weight: 700; letter-spacing: 0.01em; }
  header .identity {
    font-size: 0.85rem; opacity: 0.9; display: flex; align-items: center; gap: 0.5rem;
  }
  header .identity a { color: #cfe0ff; }
  .live-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: #35d07f; animation: livepulse 2s ease-in-out infinite;
  }
  @keyframes livepulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(53,208,127,0.5); }
    50% { opacity: 0.6; box-shadow: 0 0 0 4px rgba(53,208,127,0); }
  }
  main { padding: 1.25rem; max-width: 1150px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin: 0.2rem 0 0.6rem; }
  h2 { font-size: 1.1rem; margin: 1.4rem 0 0.5rem; }
  .subtle-heading { color: var(--ink-muted); font-size: 0.85rem; margin: -0.4rem 0 1rem; }
  a { color: var(--accent); }
  a.nav-link, a.crumb {
    color: var(--accent); text-decoration: underline; text-decoration-color: rgba(36,81,184,0.35);
  }
  a.nav-link:hover, a.crumb:hover { text-decoration-color: var(--accent); }
  .crumb-row { margin: 0 0 0.75rem; font-size: 0.9rem; }
  table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1rem; }
  th, td {
    border: 1px solid var(--border); padding: 0.5rem 0.6rem; text-align: left;
    font-size: 0.92rem; vertical-align: top;
  }
  th { background: var(--surface); font-weight: 600; }
  tr:nth-child(even) { background: rgba(0,0,0,0.02); }
  .item-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85rem; }
  .badge {
    display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.78rem;
    font-weight: 600; white-space: nowrap;
  }
  .badge-open { background: #e0e7ff; color: #2d2a8f; }
  .badge-held { background: #fef3c7; color: #7a4a00; }
  .badge-resolved { background: #d1fae5; color: #065f28; }
  .badge-blocked { background: #fee2e2; color: #8f1414; }
  .badge-deferred { background: #e5e7eb; color: #33383f; }
  .badge-unknown { background: #e5e7eb; color: #33383f; }
  .badge-error { background: #fee2e2; color: #7a1212; }
  .chip {
    display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.78rem;
    background: #eef1f5; color: var(--ink); border: 1px solid var(--border);
    margin: 0 0.15rem 0.15rem 0;
  }
  .stat-num { font-weight: 700; }
  .stat-num.zero { font-weight: 400; color: var(--ink-muted); }
  .stat-num.attn { color: #8f4a00; }
  form.inline { display: inline; }
  fieldset {
    border: 1px solid var(--border); border-radius: 8px; margin: 1rem 0; padding: 0.9rem 1.1rem;
  }
  fieldset.danger-zone { border-color: #e3b3b3; background: #fff8f8; }
  legend { font-weight: 600; padding: 0 0.4rem; }
  label { display: block; margin: 0.5rem 0 0.2rem; font-size: 0.88rem; font-weight: 500; }
  .field-hint { font-size: 0.8rem; color: var(--ink-muted); margin: 0.1rem 0 0.3rem; }
  input[type=text], input[type=password], textarea, select {
    width: 100%; max-width: 480px; padding: 0.5rem 0.6rem; box-sizing: border-box;
    font-family: inherit; font-size: 0.94rem; min-height: 44px; border: 1px solid var(--border);
    border-radius: 6px; background: #fff; color: var(--ink);
  }
  textarea { min-height: 5.5rem; }
  input::placeholder, textarea::placeholder { color: var(--ink-muted); opacity: 1; }
  button, input[type=submit], a.btn {
    padding: 0.5rem 1.1rem; margin-top: 0.6rem; cursor: pointer; min-height: 44px;
    border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: #fff;
    font-size: 0.94rem; font-weight: 600; display: inline-flex; align-items: center;
    justify-content: center; text-decoration: none;
  }
  button:hover, input[type=submit]:hover, a.btn:hover { background: var(--accent-ink); }
  button.secondary, a.btn.secondary {
    background: #fff; color: var(--accent); border-color: var(--accent);
  }
  button.danger, input.danger, a.btn.danger {
    background: #b3261e; border-color: #b3261e; color: #fff;
  }
  button.danger:hover, a.btn.danger:hover { background: #8f1e18; }
  .flash { padding: 0.7rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.92rem; }
  .flash-msg { background: #d1fae5; color: #065f28; }
  .flash-error { background: #fee2e2; color: #7a1212; }
  .muted { color: var(--ink-muted); font-size: 0.88rem; }
  .empty-state {
    border: 1px dashed var(--border); border-radius: 8px; padding: 1.5rem; text-align: left;
    color: var(--ink-muted); margin: 0.75rem 0 1.25rem; background: var(--surface);
  }
  .content-block {
    white-space: pre-wrap; word-break: break-word; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 0.9rem 1rem;
    font-size: 0.94rem; margin: 0.3rem 0 1rem;
  }
  .meta-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 0.6rem 1rem; margin: 0.75rem 0 1.25rem; font-size: 0.9rem;
  }
  .meta-grid dt {
    color: var(--ink-muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em;
  }
  .meta-grid dd { margin: 0.05rem 0 0; }
  .item-header { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; }
  code {
    background: var(--surface); padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.9em;
  }
  .links-list { margin: 0.2rem 0 1rem; padding-left: 1.2rem; font-size: 0.9rem; }
</style>
"""


def _page(request: Request, title: str, body: str) -> HTMLResponse:
    identity = _esc(_identity(request))
    live_title = "Server-rendered from the shared queue database on every request"
    live = f'<span class="live-dot" title="{live_title}"></span> live'
    logout_link = '<a href="/auth/logout" style="color:#cfe0ff">logout</a>'
    brand = '<a class="brand" href="/">amplifier-work-tracker</a>'
    header = (
        f"<header><div>{brand}</div>"
        f'<div class="identity">{live} &middot; {identity} &middot; {logout_link}</div>'
        "</header>"
        if identity
        else f'<header><div>{brand}</div><div class="identity">{live}</div></header>'
    )
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)} - amplifier-work-tracker</title>{_STYLE}</head>"
        f"<body>{header}<main>{body}</main></body></html>"
    )
    return HTMLResponse(html_doc)


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


def _crumbs(*links: tuple[str, str]) -> str:
    """`links` is a sequence of (href, label) pairs, rendered as
    `label &raquo; label &raquo; ...` -- the same `.crumb` link style used
    everywhere else something is navigable, so the grammar stays one thing
    at every level (dashboard, project, item)."""
    parts = [f'<a class="crumb" href="{_esc(href)}">{_esc(label)}</a>' for href, label in links]
    return f'<div class="crumb-row">{" &raquo; ".join(parts)}</div>'


def _not_found_body(request: Request, *, heading: str, back_href: str, back_label: str) -> str:
    return (
        f"{_flash(request)}"
        f"<h1>{_esc(heading)}</h1>"
        '<div class="empty-state">'
        "<p>That project or item doesn't exist. It may have been removed, or the name/id "
        "is mistyped.</p>"
        "</div>"
        f'<p><a class="nav-link" href="{_esc(back_href)}">&laquo; {_esc(back_label)}</a></p>'
    )


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
        body = f"""
        <h1>Sign in</h1>
        <p class="muted">{mode_hint}</p>
        {error_html}
        <form method="post" action="/login" style="max-width:320px">
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
        rows = ""
        for name in names:
            s = A.project_summary(workspace, name)
            if s.status == "ok":
                held_cell = (
                    (
                        f'<span class="stat-num attn">{s.held}</span> '
                        + "".join(f'<span class="chip">{_esc(h)}</span>' for h in s.held_by)
                    )
                    if s.held
                    else '<span class="stat-num zero">0</span>'
                )
                blocked_cell = (
                    f'<span class="stat-num attn">{s.blocked}</span>'
                    if s.blocked
                    else '<span class="stat-num zero">0</span>'
                )
                ready_cls = "stat-num" if s.ready else "stat-num zero"
                cells = (
                    f'<td><span class="{ready_cls}">{s.ready}</span> '
                    f'<span class="muted">/ {s.total} total</span></td>'
                    f"<td>{held_cell}</td>"
                    f"<td>{blocked_cell}</td>"
                    f"<td>{_abs_and_rel(s.last_activity)}</td>"
                )
            else:
                cells = (
                    f'<td colspan="3"><span class="badge badge-error">unavailable</span> '
                    f'<span class="muted">{_esc(s.status)}</span></td><td>--</td>'
                )
            rows += (
                f'<tr><td><a class="nav-link" href="/projects/{_esc(name)}">{_esc(name)}</a></td>'
                f"{cells}</tr>"
            )
        table = (
            "<table><thead><tr><th>Project</th><th>Ready</th>"
            "<th>Held</th><th>Blocked</th><th>Last activity</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if names
            else (
                '<div class="empty-state"><p>No projects yet. '
                "Create one below to get started.</p></div>"
            )
        )
        body = f"""
        {_flash(request)}
        <h1>Projects</h1>
        <p class="subtle-heading">As of {_esc(_now_utc_str())} &middot;
           <a class="nav-link" href="/">refresh</a></p>
        {table}
        <fieldset>
          <legend>Create a project</legend>
          <form method="post" action="/projects">
            <label for="name">Project name</label>
            <input type="text" id="name" name="name" pattern="[a-z][a-z0-9_]{{1,30}}" required
                   placeholder="my_project">
            <p class="field-hint">Lowercase letters, digits, underscores; must start with a
              letter.</p>
            <button type="submit">Create</button>
          </form>
        </fieldset>
        """
        return _page(request, "Dashboard", body)

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
            bd = workspace.project(name)
        except A.BeadsError:
            return _page(
                request,
                name,
                _not_found_body(
                    request, heading=name, back_href="/", back_label="back to dashboard"
                ),
            )
        try:
            result = bd.list_bounded(status=status, limit=None)
        except A.BeadsError as e:
            return _page(
                request,
                name,
                f"{_flash(request)}<h1>{_esc(name)}</h1>"
                f'<div class="flash flash-error">{_esc(_public_error_message(e))}</div>'
                f'<p><a class="nav-link" href="/">&laquo; back to dashboard</a></p>',
            )

        summary = A.project_summary(workspace, name)
        summary_chips = ""
        if summary.status == "ok":
            summary_chips = (
                f'<p class="subtle-heading">{summary.ready} ready &middot; '
                f"{summary.held} held &middot; {summary.blocked} blocked &middot; "
                f"{summary.total} total &middot; last activity "
                f"{_abs_and_rel(summary.last_activity)}</p>"
            )

        status_options = "".join(
            f'<option value="{_esc(s)}"{" selected" if s == status else ""}>{_esc(s)}</option>'
            for s in A.STATUSES
        )

        def _item_row(i: A.Item) -> str:
            item_href = f"/projects/{_esc(name)}/items/{_esc(i.id)}"
            if i.holder:
                holder_cell = f'<span class="chip">{_esc(i.holder)}</span>'
            else:
                holder_cell = '<span class="muted">&mdash;</span>'
            return (
                f'<tr><td class="item-id"><a class="nav-link" href="{item_href}">'
                f"{_esc(i.id)}</a></td>"
                f'<td><a class="nav-link" href="{item_href}">{_esc(i.title)}</a></td>'
                f"<td>{_status_badge(i.status)}</td>"
                f"<td>{holder_cell}</td>"
                f"<td>{_abs_and_rel(i.raw.get('updated_at'))}</td>"
                "</tr>"
            )

        rows = "".join(_item_row(i) for i in result.items)
        truncated_note = (
            f'<p class="muted">showing {result.returned_count} of {result.total_count} '
            f"(pass a smaller filter or raise --limit up to {A.LIST_MAX_LIMIT})</p>"
            if result.truncated
            else ""
        )
        if result.items:
            table = (
                "<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Holder</th>"
                "<th>Updated</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
        elif status:
            table = (
                '<div class="empty-state"><p>No items match status '
                f"<code>{_esc(status)}</code>.</p>"
                f'<p><a class="nav-link" href="/projects/{_esc(name)}">clear filter</a></p></div>'
            )
        else:
            table = '<div class="empty-state"><p>No items yet. Add the first one below.</p></div>'
        body = f"""
        {_crumbs(("/", "All projects"))}
        {_flash(request)}
        <h1>{_esc(name)}</h1>
        {summary_chips}
        <form method="get" action="/projects/{_esc(name)}">
          <label for="status">Filter by status</label>
          <select id="status" name="status" onchange="this.form.submit()" style="max-width:220px">
            <option value="">(all)</option>
            {status_options}
          </select>
        </form>
        {table}
        {truncated_note}

        <fieldset>
          <legend>Add item</legend>
          <form method="post" action="/projects/{_esc(name)}/items">
            <label for="title">Title</label>
            <input type="text" id="title" name="title" required>
            <label for="description">Description</label>
            <textarea id="description" name="description" rows="2"></textarea>
            <label for="acceptance">Acceptance criteria</label>
            <textarea id="acceptance" name="acceptance" rows="2"></textarea>
            <button type="submit">Add</button>
          </form>
        </fieldset>

        <fieldset>
          <legend>Claim next ready item</legend>
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
        </fieldset>

        <fieldset class="danger-zone">
          <legend>Danger zone</legend>
          <a class="btn danger" href="/projects/{_esc(name)}/remove">Remove this project&hellip;</a>
        </fieldset>
        """
        return _page(request, name, body)

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
                    request,
                    heading=item_id,
                    back_href=f"/projects/{name}",
                    back_label=f"back to {name}",
                ),
            )

        identity_val = _esc(_identity(request))

        # ------------------------------------------------ contextual action
        # Exactly one action control, chosen by the item's own status --
        # never rendered for a status it doesn't apply to (see module
        # docstring: this replaced a resolve form rendered on every row of
        # every table regardless of status).
        if item.status == "open":
            action_html = f"""
            <fieldset>
              <legend>Claim this item</legend>
              <form method="post" action="/projects/{_esc(name)}/claim">
                <input type="hidden" name="mode" value="id">
                <input type="hidden" name="item_id" value="{_esc(item.id)}">
                <label for="claim_actor">Actor</label>
                <input type="text" id="claim_actor" name="actor" value="{identity_val}" required>
                <button type="submit">Claim</button>
              </form>
            </fieldset>
            """
        elif item.status == "held":
            action_html = f"""
            <fieldset>
              <legend>Resolve</legend>
              <form method="post" action="/projects/{_esc(name)}/items/{_esc(item.id)}/resolve">
                <label for="reason">Resolution reason</label>
                <textarea id="reason" name="reason" rows="3" required></textarea>
                <label for="resolve_actor">Actor</label>
                <input type="text" id="resolve_actor" name="actor" value="{identity_val}" required>
                <button type="submit">Resolve</button>
              </form>
            </fieldset>
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
                        f'<li><a class="nav-link" href="{ln_href}">{_esc(ln_id)}</a> '
                        f'<span class="muted">({_esc(ln_type)})</span></li>'
                    )
                return out

            if depends_on:
                links_html += (
                    '<h2>Depends on</h2><ul class="links-list">' + _link_items(depends_on) + "</ul>"
                )
            if required_by:
                links_html += (
                    '<h2>Required by</h2><ul class="links-list">'
                    + _link_items(required_by)
                    + "</ul>"
                )

        resolution_html = ""
        if item.status == "resolved" and item.resolution:
            resolution_html = (
                f'<h2>Resolution</h2><div class="content-block">{_esc(item.resolution)}</div>'
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

        meta_items = [
            ("Kind", item.kind or "--"),
            ("Priority", str(item.priority) if item.priority is not None else "--"),
        ]
        owner = item.raw.get("owner")
        if owner:
            meta_items.append(("Reported by", str(owner)))
        meta_grid = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in meta_items)

        body = f"""
        {_crumbs(("/", "All projects"), (f"/projects/{_esc(name)}", name))}
        {_flash(request)}
        <div class="item-header">
          <span class="item-id muted">{_esc(item.id)}</span>
          {_status_badge(item.status)}
          {f'<span class="chip">held by {_esc(item.holder)}</span>' if item.holder else ""}
        </div>
        <h1>{_esc(item.title)}</h1>
        <dl class="meta-grid">
          {meta_grid}
          <dt>Created</dt><dd>{_abs_and_rel(item.raw.get("created_at"))}</dd>
          <dt>Updated</dt><dd>{_abs_and_rel(item.raw.get("updated_at"))}</dd>
        </dl>

        <h2>Description</h2>
        <div class="content-block">{description_html}</div>

        <h2>Acceptance criteria</h2>
        <div class="content-block">{acceptance_html}</div>

        {resolution_html}
        {links_html}
        {action_html}
        """
        return _page(request, f"{item.id} - {item.title}", body)

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
        body = f"""
        {_crumbs(("/", "All projects"), (f"/projects/{_esc(name)}", name))}
        {_flash(request)}
        <h1>Remove project '{_esc(name)}'</h1>
        <p>This permanently deletes the project's local directory AND its shared-server
        database. It is refused if any item is currently <strong>held</strong>.
        This cannot be undone.</p>
        <form method="post" action="/projects/{_esc(name)}/remove">
          <label for="confirm_name">Type the project name
            (<code>{_esc(name)}</code>) to confirm</label>
          <input type="text" id="confirm_name" name="confirm_name" required autocomplete="off">
          <button type="submit" class="danger">Permanently remove</button>
        </form>
        <p><a class="nav-link" href="/projects/{_esc(name)}">&laquo; cancel, back to project</a></p>
        """
        return _page(request, f"Remove {name}", body)

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
