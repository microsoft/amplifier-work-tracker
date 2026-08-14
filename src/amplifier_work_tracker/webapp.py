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
(per-project counts), that logic was added to the seam itself
(`adapter.project_summary`), not duplicated here -- see that function's
docstring.

Auth is `webauth.py`, ported from muxplex's pattern (see that module's
docstring for exactly what was kept and what was deliberately changed).

Rendering is plain server-rendered HTML via small string-building helpers
below -- no template engine, no static asset pipeline, no client-side JS
framework. There is exactly one page style (`_STYLE`, inlined once) and no
external files to package/serve, which sidesteps an entire class of "which
paths are exempt from auth" hazard muxplex's own static-asset exemption had
to work around (see its `_is_real_static_asset` docstring).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
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
# Rendering -- plain string building. `_esc` is the one choke point every
# user-controlled value must pass through before landing in HTML.
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_STYLE = """
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 0; line-height: 1.4; }
  header { background: #1f2933; color: #fff; padding: 0.75rem 1.25rem; display: flex;
           justify-content: space-between; align-items: center; }
  header a { color: #fff; text-decoration: none; font-weight: 600; }
  header .identity { font-size: 0.85rem; opacity: 0.85; }
  main { padding: 1.25rem; max-width: 1100px; margin: 0 auto; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.92rem; }
  th { background: #f0f2f5; }
  tr:nth-child(even) { background: rgba(0,0,0,0.03); }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.8rem; }
  .badge-ok { background: #d7f5dd; color: #14611c; }
  .badge-error { background: #fbdada; color: #8a1414; }
  .badge-held { background: #fff2cc; color: #7a5b00; }
  form.inline { display: inline; }
  fieldset { border: 1px solid #ccc; border-radius: 6px; margin: 1rem 0; padding: 0.75rem 1rem; }
  legend { font-weight: 600; padding: 0 0.4rem; }
  label { display: block; margin: 0.4rem 0 0.15rem; font-size: 0.88rem; }
  input[type=text], input[type=password], textarea, select {
    width: 100%; max-width: 480px; padding: 0.35rem; box-sizing: border-box;
    font-family: inherit; font-size: 0.92rem;
  }
  button, input[type=submit] {
    padding: 0.35rem 0.9rem; margin-top: 0.5rem; cursor: pointer;
  }
  button.danger, input.danger {
    background: #c0392b; color: #fff; border: none; border-radius: 4px;
  }
  .flash { padding: 0.6rem 1rem; border-radius: 4px; margin-bottom: 1rem; }
  .flash-msg { background: #d7f5dd; color: #14611c; }
  .flash-error { background: #fbdada; color: #8a1414; }
  .muted { color: #666; font-size: 0.85rem; }
  code { background: #f0f2f5; padding: 0.1rem 0.3rem; border-radius: 3px; }
</style>
"""


def _page(request: Request, title: str, body: str) -> HTMLResponse:
    identity = _esc(_identity(request))
    logout_link = '<a href="/auth/logout" style="color:#ffd">logout</a>'
    header = (
        '<header><div><a href="/">amplifier-work-tracker</a></div>'
        f'<div class="identity">{identity} &middot; {logout_link}</div>'
        "</header>"
        if identity
        else '<header><div><a href="/">amplifier-work-tracker</a></div></header>'
    )
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
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
                badge = '<span class="badge badge-ok">ok</span>'
                held_badge = (
                    f' <span class="badge badge-held">{s.held} held</span>' if s.held else ""
                )
                counts = f"<td>{s.total}</td><td>{s.ready}</td><td>{s.held}</td><td>{s.intake}</td>"
            else:
                badge = '<span class="badge badge-error">error</span>'
                held_badge = ""
                counts = "<td>-</td><td>-</td><td>-</td><td>-</td>"
            rows += (
                f'<tr><td><a href="/projects/{_esc(name)}">{_esc(name)}</a></td>'
                f"{counts}<td>{badge}{held_badge} "
                f'<span class="muted">{_esc(s.status if s.status != "ok" else "")}</span></td></tr>'
            )
        table = (
            "<table><thead><tr><th>Project</th><th>Total</th><th>Ready</th>"
            "<th>Held</th><th>Intake</th><th>Health</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if names
            else "<p>No projects yet.</p>"
        )
        body = f"""
        {_flash(request)}
        <h1>Projects</h1>
        {table}
        <fieldset>
          <legend>Create a project</legend>
          <form method="post" action="/projects">
            <label for="name">Project name</label>
            <input type="text" id="name" name="name" pattern="[a-z][a-z0-9_]{{1,30}}" required
                   placeholder="lowercase, starts with a letter, e.g. my_project">
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
            return _redirect("/", error=str(e))
        return _redirect("/", msg=f"created project '{name}'")

    # -------------------------------------------------------- project view

    @app.get("/projects/{name}", response_class=HTMLResponse)
    async def project_view(request: Request, name: str):  # type: ignore[no-untyped-def]
        status = request.query_params.get("status") or None
        try:
            bd = workspace.project(name)
            result = bd.list_bounded(status=status, limit=None)
        except A.BeadsError as e:
            return _page(
                request,
                name,
                f"{_flash(request)}<h1>{_esc(name)}</h1>"
                f'<div class="flash flash-error">{_esc(e)}</div>'
                f'<p><a href="/">&laquo; back to dashboard</a></p>',
            )

        status_options = "".join(
            f'<option value="{_esc(s)}"{" selected" if s == status else ""}>{_esc(s)}</option>'
            for s in A.STATUSES
        )
        identity_val = _esc(_identity(request))
        rows = "".join(
            f"<tr><td>{_esc(i.id)}</td><td>{_esc(i.title)}</td><td>{_esc(i.status)}</td>"
            f"<td>{_esc(i.holder)}</td><td>{_esc(i.resolution)}</td>"
            "<td>"
            f'<form class="inline" method="post" '
            f'action="/projects/{_esc(name)}/items/{_esc(i.id)}/resolve">'
            '<input type="text" name="reason" placeholder="resolution reason" required>'
            f'<input type="text" name="actor" placeholder="actor" value="{identity_val}" required>'
            '<button type="submit">Resolve</button></form>'
            "</td></tr>"
            for i in result.items
        )
        truncated_note = (
            f'<p class="muted">showing {result.returned_count} of {result.total_count} '
            f"(pass a smaller filter or raise --limit up to {A.LIST_MAX_LIMIT})</p>"
            if result.truncated
            else ""
        )
        table = (
            "<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Holder</th>"
            "<th>Resolution</th><th>Resolve</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if result.items
            else "<p>No items match.</p>"
        )
        body = f"""
        {_flash(request)}
        <p><a href="/">&laquo; back to dashboard</a></p>
        <h1>{_esc(name)}</h1>
        <form method="get" action="/projects/{_esc(name)}">
          <label for="status">Filter by status</label>
          <select id="status" name="status" onchange="this.form.submit()">
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
          <legend>Claim</legend>
          <form method="post" action="/projects/{_esc(name)}/claim">
            <label><input type="radio" name="mode" value="next" checked
                          onclick="document.getElementById('claim_id_field').style.display='none'">
                   Next ready item in a lane</label>
            <label><input type="radio" name="mode" value="id"
                          onclick="document.getElementById('claim_id_field').style.display='block'">
                   Specific item by id (directed claim)</label>
            <label for="lane">Lane</label>
            <input type="text" id="lane" name="lane" value="{_esc(A.LANE_WORK)}">
            <div id="claim_id_field" style="display:none">
              <label for="item_id">Item id</label>
              <input type="text" id="item_id" name="item_id">
            </div>
            <label for="claim_actor">Actor</label>
            <input type="text" id="claim_actor" name="actor"
                   value="{_esc(_identity(request))}" required>
            <button type="submit">Claim</button>
          </form>
        </fieldset>

        <p><a href="/projects/{_esc(name)}/remove">Remove this project&hellip;</a></p>
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
            return _redirect(f"/projects/{name}", error=str(e))
        return _redirect(f"/projects/{name}", msg=f"added {new_id}")

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
            return _redirect(f"/projects/{name}", error=str(e))
        if item is None:
            return _redirect(f"/projects/{name}", error=f"no ready work in lane '{lane}'")
        return _redirect(f"/projects/{name}", msg=f"{actor} claimed {item.id} ({item.title})")

    @app.post("/projects/{name}/items/{item_id}/resolve")
    async def resolve(  # type: ignore[no-untyped-def]
        name: str, item_id: str, reason: str = Form(...), actor: str = Form(...)
    ):
        try:
            item = workspace.project(name).resolve(item_id, reason, actor=actor)
        except A.BeadsError as e:
            return _redirect(f"/projects/{name}", error=str(e))
        return _redirect(f"/projects/{name}", msg=f"resolved {item.id}")

    # ------------------------------------------------------------ removal

    @app.get("/projects/{name}/remove", response_class=HTMLResponse)
    async def remove_confirm(request: Request, name: str):  # type: ignore[no-untyped-def]
        body = f"""
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
        <p><a href="/projects/{_esc(name)}">&laquo; cancel, back to project</a></p>
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
            # "N item(s) currently HELD") -- never re-implemented here.
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
