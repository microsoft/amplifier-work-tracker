"""Fixtures for the Tier-B kit: a real app on an ephemeral port, a pinned
chromium, and two named data scenarios.

Isolation, in four layers
-------------------------
1. **The dolt server.** `tests/conftest.py::isolated_dolt_server` is
   session-scoped and autouse, and this package sits under `tests/`, so every
   `bd` call made here already lands on a throwaway server on its own
   ephemeral port. The live service's :3308 is never reachable from this
   process. Inherited deliberately rather than re-implemented -- a second copy
   of that fixture is a second thing to keep correct.
2. **The workspace root.** Each scenario gets its OWN `A.Workspace` under its
   own tmp dir, because L0 Mission Control renders EVERY project in the
   workspace it was given. Sharing one root would let the alarm scenario's
   blocked item paint alarm pixels onto the calm scenario's L0 -- the calm
   sweep would then be measuring the wrong page and failing honestly for a
   dishonest reason.
3. **The port.** uvicorn binds `127.0.0.1:0`; the OS picks the port and we
   read it back off the live socket. No fixed port is ever named here, so no
   run can collide with the operator's real dashboard.
4. **The credential.** Password auth with a per-run random secret, and a real
   `POST /login` round-trip per browser context so the session cookie is the
   thing carrying it. Measured, not assumed: playwright's context-level
   `http_credentials` (even with `send="always"`) did NOT authenticate the
   navigation here -- the middleware answers an unauthenticated HTML request
   with a 307 to `/login` rather than a 401 challenge, and the page silently
   landed on the login form while still reporting HTTP 200. A kit that swept
   the login page's pixels and called it a calm L0 would pass forever, so
   `goto()` below asserts the URL it actually landed on. The cookie also
   authenticates the surface's own poller, which re-fetches with
   `fetch(..., credentials:'same-origin')` -- exactly the request Core 6's
   body-swap depends on.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="the Tier-B kit needs playwright (see `make venv`)")
pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
pytest.importorskip("uvicorn", reason="the 'web' extra is not installed")

import uvicorn  # noqa: E402
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright  # noqa: E402

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import custody as CU  # noqa: E402
from amplifier_work_tracker import webapp as W  # noqa: E402
from amplifier_work_tracker import webauth as WA  # noqa: E402
from tests.conftest import drop_project, unique_name  # noqa: E402

from ._artifacts import RunArtifacts

#: Every test in this package. Selected by `make test-conformance-b` /
#: the CI "Tier 7" step and DESELECTED by every other invocation -- see
#: pyproject's `addopts`.
pytestmark = pytest.mark.tier_b

#: Wall-clock ceiling for uvicorn opening its listening socket. Generous
#: rather than tight: a slow CI runner losing this race must not read as a
#: conformance failure.
_STARTUP_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class AppServer:
    """A live app, its base URL, and the credential to reach it with."""

    base_url: str
    username: str
    password: str
    workspace: A.Workspace
    project: str
    #: One representative item id per role, so a test can address L2 (item
    #: detail) without re-querying bd from inside the browser tier.
    items: dict[str, str]

    def url(self, level: str) -> str:
        """`"L0"`/`"L1"`/`"L2"` -> the path the contract names for that level."""
        if level == "L0":
            return "/"
        if level == "L1":
            return f"/projects/{self.project}"
        if level == "L2":
            return f"/projects/{self.project}/items/{self.items['detail']}"
        raise ValueError(f"unknown IA level {level!r}")


# --------------------------------------------------------------------- server


class _ThreadedServer:
    """uvicorn on a background thread, bound to an OS-chosen port.

    `port=0` then reading the bound port back off `server.servers[0]
    .sockets[0]` -- never a guessed or scanned port, so two scenarios (or two
    xdist workers) can never race for the same one.
    """

    def __init__(self, app) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> int:
        self._thread.start()
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._server.started and self._server.servers:
                sockets = self._server.servers[0].sockets
                if sockets:
                    return int(sockets[0].getsockname()[1])
            time.sleep(0.02)
        raise RuntimeError(
            f"the Tier-B app did not open a listening socket within {_STARTUP_TIMEOUT_S}s"
        )

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise RuntimeError("the Tier-B app server thread did not stop")


#: Ports the live operator service and its dolt server use on the box this
#: kit was built on. `port=0` already makes a collision impossible; this is
#: the assertion that says so out loud, because "the browser tier reached the
#: real dashboard" is the one failure mode here that would not look like a
#: test failure at all.
_LIVE_SERVICE_PORTS = frozenset({3308, 8088, 8090, 8091, 8095, 8096, 8097, 8099})


def _refuse_live_service_port(port: int) -> None:
    if port in _LIVE_SERVICE_PORTS:
        raise RuntimeError(f"refusing to serve the Tier-B app on live-service port {port}")


# ------------------------------------------------------------------ scenarios


def _build_app_server(
    root: Path, project_builder: Callable[[A.Beads], dict[str, str]]
) -> Iterator[AppServer]:
    """Create a one-project workspace under `root`, populate it, serve it."""
    workspace = A.Workspace(root)
    name = unique_name("tierb")
    workspace.create(name)
    try:
        bd = workspace.project(name)
        items = project_builder(bd)

        password = secrets.token_urlsafe(16)
        auth = WA.AuthConfig(
            mode="password",
            secret=secrets.token_urlsafe(32),
            ttl_seconds=3600,
            password=password,
        )
        server = _ThreadedServer(W.create_app(workspace, auth))
        port = server.start()
        _refuse_live_service_port(port)
        try:
            yield AppServer(
                base_url=f"http://127.0.0.1:{port}",
                username="operator",
                password=password,
                workspace=workspace,
                project=name,
                items=items,
            )
        finally:
            server.stop()
    finally:
        drop_project(workspace, name)


def _calm_data(bd: A.Beads) -> dict[str, str]:
    """ "Nothing held past TTL, nothing blocked" (Conformance 1's scenario).

    Deliberately NOT an empty project: an empty page is trivially free of
    alarm colour and would prove nothing. This is a working queue -- ready
    work, one healthily-held item whose custody was renewed a moment ago, and
    resolved throughput for the hero's velocity figure -- that simply has
    nothing wrong with it.
    """
    for i in range(4):
        bd.create(f"calm ready item {i}", tags=[A.LANE_WORK])
    holder = unique_name("actor")
    held = bd.create("calm held item, custody fresh", tags=[A.LANE_WORK])
    bd.claim_item(held, actor=holder)
    bd.take_custody(held, holder=holder, pid=os.getpid(), host=CU.local_host())
    for i in range(3):
        done = bd.create(f"calm resolved item {i}", tags=[A.LANE_WORK])
        bd.resolve(done, f"finished {i}", actor="tier-b-fixture")
    detail = bd.create(
        "calm detail item",
        tags=[A.LANE_WORK],
        description="A body an operator would actually read on L2.",
        acceptance="Given a calm queue, when L2 renders, then it carries this text.",
    )
    return {"detail": detail, "held": held}


def _alarm_data(bd: A.Beads) -> dict[str, str]:
    """The same fixture with something genuinely wrong (Conformance 2)."""
    ids = _calm_data(bd)
    blocked = bd.create("alarm blocked item", tags=[A.LANE_WORK])
    bd.block(blocked, "waiting on an upstream decision", actor="tier-b-fixture")
    ids["blocked"] = blocked
    return ids


@pytest.fixture(scope="session")
def calm_app(tmp_path_factory) -> Iterator[AppServer]:
    yield from _build_app_server(tmp_path_factory.mktemp("tierb_calm"), _calm_data)


@pytest.fixture(scope="session")
def alarm_app(tmp_path_factory) -> Iterator[AppServer]:
    yield from _build_app_server(tmp_path_factory.mktemp("tierb_alarm"), _alarm_data)


# -------------------------------------------------------------------- browser


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """The pinned chromium Freeze 2 requires.

    The pin is `playwright==1.60.0` in `pyproject.toml`; a playwright release
    ships exactly one chromium build, so the version string recorded in every
    artifact is reproducible from the manifest alone. If chromium is not
    installed the failure names `make playwright-install` rather than
    presenting as a mysterious protocol error.
    """
    with sync_playwright() as p:
        try:
            instance = p.chromium.launch(args=["--disable-gpu"])
        except Exception as exc:  # noqa: BLE001 -- re-raised with the remedy attached
            raise RuntimeError(
                f"could not launch the pinned chromium: {exc}. Run `make playwright-install`."
            ) from exc
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture(scope="session")
def browser_info(browser: Browser) -> dict[str, str]:
    """What every artifact records about the engine that produced it."""
    return {
        "name": "chromium",
        "version": browser.version,
        "playwright": version("playwright"),
    }


@pytest.fixture(scope="session")
def artifacts() -> Iterator[RunArtifacts]:
    """The per-run artifact directory every check writes its numbers into."""
    run = RunArtifacts.for_this_run(Path(__file__).parent / "_artifacts")
    yield run
    run.write_index()
    run.write_summary()


ContextFactory = Callable[..., BrowserContext]


@pytest.fixture(scope="session")
def context_factory(browser: Browser) -> Iterator[ContextFactory]:
    """`context_factory(app, width=...)` -> a logged-in browser context.

    The login is a real `POST /login` through the context's own request
    object, so the session cookie lands in the context's cookie jar and every
    subsequent navigation AND the surface's own `fetch`-based poller carry it.
    """
    opened: list[BrowserContext] = []

    def _make(app: AppServer, *, width: int = 1280, height: int = 900) -> BrowserContext:
        ctx = browser.new_context(viewport={"width": width, "height": height})
        opened.append(ctx)
        resp = ctx.request.post(
            f"{app.base_url}/login",
            form={"username": app.username, "password": app.password, "next": "/"},
            max_redirects=0,
        )
        if resp.status != 303:
            raise AssertionError(
                f"the Tier-B fixture could not log in: POST /login returned {resp.status}"
            )
        return ctx

    yield _make
    for ctx in opened:
        ctx.close()


def goto(page: Page, app: AppServer, path: str, *, theme: str) -> None:
    """Navigate, prove we are not on the login page, and settle on `theme`.

    Two read-backs, both load-bearing:

    * the landed URL, because an unauthenticated request to this surface is a
      307 to `/login` that still reports HTTP 200 at the end of the redirect
      chain -- a kit that swept the login page would report a beautifully calm
      L0 forever;
    * `data-theme`, because a silently-ignored theme switch would have both
      "themes" sweep identical pixels and pass twice.

    The theme is applied through the page's OWN `wtSetTheme` (webapp.py's
    `_OBSERVATORY_THEME_JS`, the function the visible toggle calls), never by
    writing the attribute directly, so the swept render is the one an operator
    actually gets.
    """
    page.goto(f"{app.base_url}{path}", wait_until="load")
    if "/login" in page.url:
        raise AssertionError(f"navigation to {path!r} landed on the login page ({page.url})")
    page.evaluate("t => wtSetTheme(t)", theme)
    applied = page.evaluate("document.documentElement.getAttribute('data-theme')")
    if applied != theme:
        raise AssertionError(f"theme {theme!r} did not take: data-theme is {applied!r}")
    page.wait_for_timeout(150)  # one paint after the token swap
