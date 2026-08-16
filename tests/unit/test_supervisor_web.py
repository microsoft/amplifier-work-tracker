"""Tier 1 -- the `serve --web-port` integration: folding the web dashboard
into `_async_serve` as a 4th concurrent task (see supervisor.py's
`web_server_loop`, `WebIntegrationConfig`, `WebServerStartupError`,
`import_web_modules`).

Real uvicorn + a real `webapp.create_app` FastAPI app are used against an
EMPTY, isolated `tmp_path` workspace root -- no real `bd`, no shared dolt
server (:3308 or otherwise), no real project. `A.Workspace.names()` returns
`[]` for a root with no `projects/` directory, so `reap_loop`/`notify_loop`
(exercised indirectly, and directly in `test_supervisor.py`) never need a
real project to sweep zero of them successfully. This keeps the whole file
fast and dolt-independent, matching this repo's Tier 1 contract (no bd, no
network -- see this module's own docstring convention in
`test_supervisor.py`).

Everything here binds real, ephemeral TCP ports (never :3308, never a
fixed port) via `_free_port()`, and every task this file starts is proven
to actually stop (`asyncio.wait_for(..., timeout=...)`) before the test
returns -- no orphaned uvicorn/dolt-adjacent background tasks survive a
test in this file.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import urllib.error
import urllib.request

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")
pytest.importorskip("uvicorn", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import supervisor as SV  # noqa: E402

_TEST_PASSWORD = "not-a-real-secret-test-fixture"  # noqa: S105 -- test fixture, not a credential


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str, timeout: float = 1.0):
    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 -- fixed http://127.0.0.1 test URL


async def _wait_until_reachable(url: str, *, attempts: int = 50, delay: float = 0.05) -> None:
    """Poll `url` until it answers or the attempt budget is exhausted --
    uvicorn's real listening socket takes a moment to open after
    `server._serve()` is scheduled, and this is a real network bind, not a
    mock, so a bounded retry loop (never a bare `sleep` guess) is the
    correct way to synchronize with it.

    Runs the (blocking) HTTP call via `asyncio.to_thread` -- calling it
    directly would block THIS SAME event loop that the uvicorn server under
    test also runs on, starving it of the chance to ever accept/answer the
    connection and turning every attempt into a guaranteed self-inflicted
    timeout.
    """
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            await asyncio.to_thread(_get, url)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
            await asyncio.sleep(delay)
    raise AssertionError(f"{url} never became reachable: {last_err}")


# --------------------------------------------------------- import_web_modules


def test_import_web_modules_returns_the_webapp_module():
    webapp = SV.import_web_modules()
    assert hasattr(webapp, "create_app")
    assert hasattr(webapp, "resolve_web_config")


def test_import_web_modules_wraps_import_error_with_actionable_hint(monkeypatch):
    """Simulate the 'web' extra being uninstalled.

    Blocking `sys.modules["amplifier_work_tracker.webapp"]` alone is not
    enough: an earlier test in this file already imported it successfully,
    so the parent package's `webapp` ATTRIBUTE is already set, and `from .
    import webapp`'s `IMPORT_FROM` opcode resolves via `getattr(package,
    "webapp")` before ever consulting `sys.modules` again. Removing the
    attribute too forces a genuine re-import attempt, which then hits the
    blocked `sys.modules` entry and raises the real `ImportError` this test
    means to exercise.
    """
    import amplifier_work_tracker as pkg

    monkeypatch.setitem(sys.modules, "amplifier_work_tracker.webapp", None)
    monkeypatch.delattr(pkg, "webapp", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        SV.import_web_modules()
    assert "the 'web' extra" in str(excinfo.value)
    assert "pip install 'amplifier-work-tracker[web]'" in str(excinfo.value)


# --------------------------------------------------------------- stop watcher


class _FakeUvicornServer:
    def __init__(self):
        self.should_exit = False


def test_web_stop_watcher_mirrors_stop_event_into_should_exit():
    server = _FakeUvicornServer()
    stop_event = asyncio.Event()

    async def run():
        task = asyncio.create_task(SV._web_stop_watcher(server, stop_event))
        await asyncio.sleep(0)  # let the watcher start awaiting stop_event
        assert server.should_exit is False
        stop_event.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())
    assert server.should_exit is True


# ------------------------------------------------------------- web_server_loop


def test_web_server_loop_serves_a_reachable_dashboard_and_drains_on_stop_event(tmp_path):
    """The core acceptance case: bring up the dashboard via the integrated
    path, prove it answers real HTTP, then prove `stop_event.set()` alone
    (no OS signal -- matching how the OTHER three tasks are already tested
    in test_supervisor.py) drains it cleanly within a bounded timeout."""
    ws = A.Workspace(tmp_path / "root")
    port = _free_port()
    web = SV.WebIntegrationConfig(
        host=None,
        public=False,
        port=port,
        auth_mode="password",
        session_ttl=3600,
    )
    stop_event = asyncio.Event()

    async def run():
        task = asyncio.create_task(SV.web_server_loop(ws, web, stop_event=stop_event))
        try:
            await _wait_until_reachable(f"http://127.0.0.1:{port}/healthz")
            # Routed through `to_thread` for the same reason as
            # `_wait_until_reachable` -- a direct, blocking call here would
            # starve the SAME event loop the server-under-test task runs on.
            resp = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/healthz")
            assert resp.status == 200
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())


def test_web_server_loop_raises_web_server_startup_error_for_rejected_config(tmp_path):
    """A non-loopback host without public=True is `webapp.WebConfigError` --
    must surface here as `WebServerStartupError`, the SAME exception a real
    bind failure raises, so `_async_serve`'s except clause handles both
    uniformly."""
    ws = A.Workspace(tmp_path / "root")
    web = SV.WebIntegrationConfig(
        host="0.0.0.0",  # noqa: S104 -- deliberately rejected input, never actually bound
        public=False,
        port=_free_port(),
        auth_mode="password",
        session_ttl=3600,
    )
    stop_event = asyncio.Event()

    async def run():
        with pytest.raises(SV.WebServerStartupError) as excinfo:
            await SV.web_server_loop(ws, web, stop_event=stop_event)
        assert "--public" in str(excinfo.value) or "public" in str(excinfo.value)

    asyncio.run(run())


def test_web_server_loop_raises_web_server_startup_error_on_bind_failure(tmp_path):
    """A real port-already-in-use bind failure -- uvicorn's own
    `sys.exit(STARTUP_FAILURE)` from inside `Server.startup()` -- must
    surface as `WebServerStartupError`, never a bare `SystemExit` escaping
    the task (which asyncio.gather would otherwise propagate as an opaque
    failure) and never a silent continue-without-the-dashboard."""
    ws = A.Workspace(tmp_path / "root")
    port = _free_port()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupier:
        occupier.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupier.bind(("127.0.0.1", port))
        occupier.listen(1)

        web = SV.WebIntegrationConfig(
            host=None, public=False, port=port, auth_mode="password", session_ttl=3600
        )
        stop_event = asyncio.Event()

        async def run():
            with pytest.raises(SV.WebServerStartupError) as excinfo:
                await asyncio.wait_for(
                    SV.web_server_loop(ws, web, stop_event=stop_event), timeout=10
                )
            assert str(port) in str(excinfo.value)

        asyncio.run(run())


# ------------------------------------------------------- _async_serve wiring
#
# `dolt_supervisor_loop` is monkeypatched to a trivial "set stop_event and
# return" stub -- never a real `dolt` binary, never the shared :3308 server.
# `reap_loop`/`notify_loop` run for REAL against the isolated, empty
# `tmp_path` root (zero projects to sweep, see this module's own docstring)
# so this test also proves they are unaffected by the web task's presence.


async def _instant_stop_dolt_loop(*, host, port, data_dir, pid_file, stop_event, state, **kwargs):
    state["proc"] = None
    stop_event.set()


def test_async_serve_without_web_never_touches_web_modules(monkeypatch, tmp_path):
    """`serve`'s existing three-task contract, unchanged: omitting `web`
    must not import or invoke ANYTHING web-related."""
    monkeypatch.setattr(SV, "dolt_supervisor_loop", _instant_stop_dolt_loop)

    def _poison_import():
        raise AssertionError("import_web_modules must not be called when web=None")

    async def _poison_loop(*a, **k):
        raise AssertionError("web_server_loop must not be called when web=None")

    monkeypatch.setattr(SV, "import_web_modules", _poison_import)
    monkeypatch.setattr(SV, "web_server_loop", _poison_loop)

    result = asyncio.run(
        SV._async_serve(
            tmp_path / "root",
            host="127.0.0.1",
            port=_free_port(),
            reap_interval=0.05,
            notify_interval=0.05,
            dolt_restart_backoff=0.0,
            web=None,
        )
    )
    assert result == 0


def test_async_serve_with_web_runs_all_four_tasks(monkeypatch, tmp_path):
    """`web` given -> the REAL `web_server_loop` runs alongside the (faked)
    dolt task and the REAL reap/notify loops, and the whole thing completes
    cleanly (return 0) once the dolt task's stop_event fires."""
    monkeypatch.setattr(SV, "dolt_supervisor_loop", _instant_stop_dolt_loop)

    web = SV.WebIntegrationConfig(
        host=None,
        public=False,
        port=_free_port(),
        auth_mode="password",
        session_ttl=3600,
    )

    result = asyncio.run(
        SV._async_serve(
            tmp_path / "root",
            host="127.0.0.1",
            port=_free_port(),
            reap_interval=0.05,
            notify_interval=0.05,
            dolt_restart_backoff=0.0,
            web=web,
        )
    )
    assert result == 0
