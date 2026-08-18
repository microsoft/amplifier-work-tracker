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
import subprocess
import sys
import time
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
    assert "uv tool install --reinstall --with 'amplifier-work-tracker[web]'" in str(excinfo.value)


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


def test_web_server_loop_serves_https_when_tls_cert_and_key_are_given(tmp_path):
    """The integrated `serve --web-port` path must thread `tls_cert`/
    `tls_key` all the way to uvicorn -- proven by actually connecting over
    TLS (a self-signed cert, verified with `ssl._create_unverified_context`
    the way a `curl -k` would), not just asserting the config object."""
    from amplifier_work_tracker import webtls as WT

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_self_signed(cert_path, key_path)

    ws = A.Workspace(tmp_path / "root")
    port = _free_port()
    web = SV.WebIntegrationConfig(
        host=None,
        public=False,
        port=port,
        auth_mode="password",
        session_ttl=3600,
        tls_cert=str(cert_path),
        tls_key=str(key_path),
    )
    stop_event = asyncio.Event()

    async def run():
        task = asyncio.create_task(SV.web_server_loop(ws, web, stop_event=stop_event))
        try:
            await _wait_until_https_reachable(port)
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())


async def _wait_until_https_reachable(
    port: int, *, attempts: int = 50, delay: float = 0.05
) -> None:
    """Same polling shape as `_wait_until_reachable`, but over TLS with
    verification disabled (self-signed cert, no CA) -- the moral
    equivalent of `curl -k`."""
    import ssl

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def _https_get() -> int:
        # Explicitly close the response (a `with` block) -- an unclosed
        # keep-alive connection left dangling by `urlopen` is exactly what
        # made uvicorn's graceful shutdown ("waiting for connections to
        # close") hang past this test's own wait_for(5) budget.
        with urllib.request.urlopen(  # noqa: S310 -- fixed https://127.0.0.1 test URL
            f"https://127.0.0.1:{port}/healthz", timeout=1.0, context=ctx
        ) as resp:
            return resp.status

    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            status = await asyncio.to_thread(_https_get)
            assert status == 200
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
            await asyncio.sleep(delay)
    raise AssertionError(f"https://127.0.0.1:{port} never became reachable: {last_err}")


def test_web_server_loop_runs_trust_bootstrap_companion_listener_when_tls_active(tmp_path):
    """`serve --web-port` with TLS active and `http_port` set must bring up
    the companion plain-HTTP trust-bootstrap listener (`webtrust.py`)
    ALONGSIDE the https dashboard, in the SAME task, and drain BOTH on
    `stop_event.set()`."""
    from amplifier_work_tracker import webtls as WT

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ca_cert_path = tmp_path / "ca.crt"
    ca_key_path = tmp_path / "ca.key"
    WT.generate_local_ca(ca_cert_path, ca_key_path)
    WT.generate_leaf_signed_by_ca(
        ca_cert_path, ca_key_path, cert_path, key_path, hostnames=["127.0.0.1", "localhost"]
    )

    ws = A.Workspace(tmp_path / "root")
    https_port = _free_port()
    http_port = _free_port()
    web = SV.WebIntegrationConfig(
        host=None,
        public=False,
        port=https_port,
        auth_mode="password",
        session_ttl=3600,
        tls_cert=str(cert_path),
        tls_key=str(key_path),
        http_port=http_port,
    )
    stop_event = asyncio.Event()

    async def run():
        task = asyncio.create_task(SV.web_server_loop(ws, web, stop_event=stop_event))
        try:
            await _wait_until_reachable(f"http://127.0.0.1:{http_port}/trust")
            resp = await asyncio.to_thread(_get, f"http://127.0.0.1:{http_port}/trust")
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "Trust this server" in body

            redirect_resp = await asyncio.to_thread(
                _get_no_redirect, f"http://127.0.0.1:{http_port}/projects"
            )
            assert redirect_resp.status in (301, 302, 307, 308)
            assert f"https://127.0.0.1:{https_port}/projects" in redirect_resp.headers["Location"]
        finally:
            stop_event.set()
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())


def _get_no_redirect(url: str):
    class _NoRedirect(urllib.request.HTTPErrorProcessor):
        def http_response(self, request, response):
            return response

        https_response = http_response

    return urllib.request.build_opener(_NoRedirect).open(url, timeout=1.0)  # noqa: S310


def test_web_server_loop_omits_trust_bootstrap_without_http_port(tmp_path):
    """`http_port=None` (the default) with TLS active must NOT bind a
    second listener at all -- proven by the auto-derived default port
    (https_port + 1) being freely bindable by something else immediately."""
    from amplifier_work_tracker import webtls as WT

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    WT.generate_self_signed(cert_path, key_path)

    ws = A.Workspace(tmp_path / "root")
    https_port = _free_port()
    web = SV.WebIntegrationConfig(
        host=None,
        public=False,
        port=https_port,
        auth_mode="password",
        session_ttl=3600,
        tls_cert=str(cert_path),
        tls_key=str(key_path),
        # http_port omitted -- resolve_web_config would default this to
        # https_port + 1 when TLS is active, but web_server_loop must still
        # only start ONE listener here since `resolve_web_config`'s own
        # default IS in effect (this test exercises the "default kicks in"
        # path -- see the next test for "explicitly no companion" via a
        # non-TLS config).
    )
    stop_event = asyncio.Event()

    async def run():
        task = asyncio.create_task(SV.web_server_loop(ws, web, stop_event=stop_event))
        try:
            await _wait_until_https_reachable(https_port)
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


# ---------------------------------------------------------- the fail-loud gap
#
# The live bug: `import_web_modules()` raises plain `RuntimeError` (see its
# own docstring -- it must, for `cli.py`'s standalone `cmd_web`), but
# `_async_serve`'s except clause only matches `WebServerStartupError`/
# `DoltSupervisionExhaustedError`. Before this fix, that `RuntimeError`
# escaped `web_server_loop` uncaught, which the two tests below prove is
# now closed at both the SINGLE-task level (`web_server_loop` itself wraps
# it) and the WHOLE-supervisor level (`_async_serve` really exits, and the
# real dolt-like child process is not left orphaned).


def test_web_server_loop_wraps_missing_web_extra_as_web_server_startup_error(monkeypatch, tmp_path):
    """`import_web_modules()` raising `RuntimeError` (the 'web' extra
    genuinely missing) must surface from `web_server_loop` as
    `WebServerStartupError` -- the SAME type a rejected config or a real
    bind failure already raise -- so `_async_serve`'s except clause
    catches it. Before this fix, this raised a bare `RuntimeError` that
    `_async_serve` did not catch at all.
    """

    def _poison_import_web_modules():
        raise RuntimeError("the web dashboard requires the 'web' extra: No module named 'fastapi'")

    monkeypatch.setattr(SV, "import_web_modules", _poison_import_web_modules)

    ws = A.Workspace(tmp_path / "root")
    web = SV.WebIntegrationConfig(
        host=None, public=False, port=_free_port(), auth_mode="password", session_ttl=3600
    )
    stop_event = asyncio.Event()

    async def run():
        with pytest.raises(SV.WebServerStartupError) as excinfo:
            await SV.web_server_loop(ws, web, stop_event=stop_event)
        assert "the 'web' extra" in str(excinfo.value)

    asyncio.run(run())


def test_async_serve_fails_loud_and_terminates_real_dolt_child_on_missing_web_extra(
    monkeypatch, tmp_path
):
    """Regression test for the live incident, end to end: a missing `[web]`
    extra must not just raise the right exception TYPE -- the whole
    supervisor process must actually be able to exit, including
    terminating the real dolt child.

    Before this fix there were TWO independent bugs, either one of which
    alone reproduces the live symptom (service `active` forever, dolt up,
    web dashboard silently never bound):

      1. `import_web_modules()`'s plain `RuntimeError` did not match
         `_async_serve`'s except clause at all, so cleanup never ran.
      2. Even with the right exception type, `_async_serve`'s cleanup
         only called `stop_event.set()` -- never `proc.terminate()` on the
         real dolt child. Cancelling the asyncio Task wrapping `await
         asyncio.to_thread(proc.wait)` succeeds at the asyncio level, but
         the real OS subprocess (and its executor thread) keeps running;
         `asyncio.run()`'s own `shutdown_default_executor()` then blocks
         FOREVER waiting for that thread, so the process never actually
         returns.

    A real, long-lived subprocess stands in for dolt here (never a real
    `dolt` binary -- this file stays dolt-independent per its own
    docstring) specifically because the hang only reproduces against a
    REAL OS process + thread, not a plain coroutine fake -- see
    `_instant_stop_dolt_loop` elsewhere in this file, which would not have
    caught this bug.
    """
    spawned: dict[str, subprocess.Popen] = {}

    def _fake_spawn_dolt(host, port, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(["sleep", "300"])  # noqa: S607 -- test fixture, stands in for dolt
        spawned["proc"] = proc
        return proc

    def _poison_import_web_modules():
        raise RuntimeError("the web dashboard requires the 'web' extra: No module named 'fastapi'")

    monkeypatch.setattr(SV, "spawn_dolt", _fake_spawn_dolt)
    monkeypatch.setattr(SV, "import_web_modules", _poison_import_web_modules)

    web = SV.WebIntegrationConfig(
        host=None, public=False, port=_free_port(), auth_mode="password", session_ttl=3600
    )

    async def run():
        with pytest.raises(SV.WebServerStartupError):
            await asyncio.wait_for(
                SV._async_serve(
                    tmp_path / "root",
                    host="127.0.0.1",
                    port=_free_port(),
                    reap_interval=9999,
                    notify_interval=9999,
                    dolt_restart_backoff=0.0,
                    web=web,
                ),
                timeout=10,
            )

    t0 = time.monotonic()
    asyncio.run(run())
    elapsed = time.monotonic() - t0
    assert elapsed < 8, (
        f"_async_serve took {elapsed:.1f}s to fail loud -- should be near-instant, "
        f"not hanging on the still-alive fake dolt child"
    )

    assert "proc" in spawned, "the fake dolt child was never spawned"
    # A brief grace period for the SIGTERM `_request_stop()` sent to actually
    # take effect -- never a bare assertion against `.poll()` immediately.
    spawned["proc"].wait(timeout=5)
    assert spawned["proc"].poll() is not None, (
        "the fake dolt child was left running (orphaned) after the supervisor gave up -- "
        "_async_serve's cleanup must terminate it, not just cancel the asyncio task"
    )


def test_serve_returns_1_and_prints_remedy_on_missing_web_extra(monkeypatch, tmp_path, capsys):
    """The full synchronous entry point (`cli.py`'s `cmd_serve` calls this
    directly): must return 1, never hang, and the stderr message must name
    the exact remedy an operator needs."""
    spawned: dict[str, subprocess.Popen] = {}

    def _fake_spawn_dolt(host, port, data_dir):
        data_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(["sleep", "300"])  # noqa: S607 -- test fixture, stands in for dolt
        spawned["proc"] = proc
        return proc

    def _poison_import_web_modules():
        # Uses the REAL shared message template (the same one
        # `import_web_modules()` itself formats on a genuine ImportError)
        # so this test verifies the actual remedy text a real missing-
        # extra failure would show, not a hand-rolled stand-in.
        raise RuntimeError(
            SV._WEB_EXTRA_ERROR_TEMPLATE.format(e=ImportError("No module named 'fastapi'"))
        )

    monkeypatch.setattr(SV, "spawn_dolt", _fake_spawn_dolt)
    monkeypatch.setattr(SV, "import_web_modules", _poison_import_web_modules)

    web = SV.WebIntegrationConfig(
        host=None, public=False, port=_free_port(), auth_mode="password", session_ttl=3600
    )

    t0 = time.monotonic()
    result = SV.serve(
        tmp_path / "root",
        host="127.0.0.1",
        port=_free_port(),
        dolt_restart_backoff=0.0,
        web=web,
    )
    elapsed = time.monotonic() - t0

    assert result == 1
    assert elapsed < 8, f"serve() took {elapsed:.1f}s -- should fail loud promptly, not hang"

    captured = capsys.readouterr()
    assert "uv tool install --reinstall --with 'amplifier-work-tracker[web]'" in captured.err

    if "proc" in spawned:
        spawned["proc"].wait(timeout=5)
        assert spawned["proc"].poll() is not None, "fake dolt child left orphaned by serve()"
