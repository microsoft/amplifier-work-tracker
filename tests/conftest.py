"""Shared fixtures for the amplifier-work-tracker test suite.

Isolation model
---------------
- ``AMPLIFIER_WORK_TRACKER_ROOT`` is repointed at a session-scoped tmp
  directory for the whole test session, so tests never touch the developer's
  real ``~/.amplifier-work-tracker``.
- Every project/lane/actor name is derived from ``uuid4`` (see
  ``unique_name``), never a fixed literal, so tests are independent,
  parallel-safe, and carry no ordering assumptions -- this also makes the
  suite safe under pytest-xdist, since each worker process mints its own
  unique names and never collides with another worker's.
- Known, accepted trade-off: bd's shared-server topology stores each
  project's actual Dolt database under
  ``~/.beads/shared-server/dolt/<name>`` -- that is server-side state
  amplifier-work-tracker does not control. Neither ``bd`` nor
  ``amplifier_work_tracker.contract``'s own ``Probe`` (which this suite
  reuses) has a "drop database" primitive, and adding one here would require
  a non-stdlib MySQL/Dolt client, which the brief for this suite rules out.
  Because every name is unique, test runs never collide with or overwrite
  each other's server-side data -- they just leave small, uniquely-named
  entries in the shared server, exactly the way
  ``amplifier_work_tracker.contract``'s ``Probe`` already does today. The
  developer-facing state this suite is responsible for keeping clean
  (``~/.amplifier-work-tracker``, and whatever ``AMPLIFIER_WORK_TRACKER_ROOT``
  the CLI reads) *is* fully isolated per test session via the tmp directory
  below.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import contract
from amplifier_work_tracker import gateway as G

# ---------------------------------------------------------------------------
# Skip integration/cli tests loudly (not one confusing failure per test) if
# the real `bd` binary isn't on PATH at all.
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    if shutil.which("bd") is not None:
        return
    skip = pytest.mark.skip(reason="`bd` binary not found on PATH")
    for item in items:
        if "integration" in item.keywords or "cli" in item.keywords:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Names -- always unique, never a fixed literal.
# ---------------------------------------------------------------------------


def unique_name(prefix: str = "t") -> str:
    """A project/actor-style name matching ``amplifier_work_tracker.adapter.NAME_RE``,
    always unique. ``NAME_RE`` requires a lowercase-letter start and only
    ``[a-z0-9_]`` after that, so the prefix must itself comply."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def unique_project_name() -> str:
    return unique_name("proj")


@pytest.fixture
def unique_actor() -> str:
    return unique_name("actor")


@pytest.fixture
def unique_lane() -> str:
    return f"lane:{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Workspace root -- one tmp directory for the whole session.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def workspace_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("amplifier_work_tracker_root")
    mp = pytest.MonkeyPatch()
    mp.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))
    yield root
    mp.undo()


@pytest.fixture(scope="session")
def workspace(workspace_root) -> A.Workspace:
    return A.Workspace(workspace_root)


@pytest.fixture(scope="session")
def shared_project_name(workspace) -> str:
    """One real bd project, created once (``bd init`` takes several seconds
    against the shared dolt server) and reused by every integration test
    that just needs *a* project to work in. Isolation between tests comes
    from unique lane tags / ids within it, not from separate projects."""
    name = unique_name("shared")
    workspace.create(name)
    return name


@pytest.fixture(scope="session")
def shared_bd(workspace, shared_project_name) -> A.Beads:
    return workspace.project(shared_project_name)


@pytest.fixture
def project_factory(workspace):
    """Callable -> a brand-new ``(name, Beads)`` pair, each a real ``bd
    init`` (slow, several seconds). Prefer ``shared_bd``/``shared_project_name``
    unless the test genuinely needs its own project (e.g. testing
    ``amplifier-work-tracker new`` / ``instances`` themselves, which observe
    project creation directly)."""

    def _make(prefix: str = "proj") -> tuple[str, A.Beads]:
        name = unique_name(prefix)
        workspace.create(name)
        return name, workspace.project(name)

    return _make


@pytest.fixture(scope="module")
def probe():
    """A disposable throwaway project, via ``amplifier_work_tracker.contract.Probe``
    -- reused directly here (rather than reimplemented) so integration tests
    exercise the exact same probing machinery ``amplifier-work-tracker doctor``
    does."""
    with contract.Probe() as p:
        yield p


# ---------------------------------------------------------------------------
# Gateway -- start/stop a real GatewayServer on an ephemeral port.
# ---------------------------------------------------------------------------


@dataclass
class GatewayHandle:
    base_url: str
    tokens_path: Path
    server: G.GatewayServer

    def mint(self, reporter_id: str, project: str) -> str:
        """Mint a token via the real ``gateway.make_token`` admin path
        (exercising the actual production code, not a reimplementation),
        then sync the freshly-written tokens file into the live server's
        in-memory table so it is usable immediately without a restart."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            G.make_token(self.tokens_path, reporter_id, project)
        m = re.search(r"token \(shown once -- store it now\): (\S+)", buf.getvalue())
        assert m, f"could not parse minted token from: {buf.getvalue()!r}"
        # The tokens file is rewritten as a cumulative superset on every
        # mint (see gateway.make_token), so a plain update (no clear) is
        # correct and keeps previously-minted tokens for other reporters.
        self.server.tokens.update(json.loads(self.tokens_path.read_text(encoding="utf-8")))
        return m.group(1)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if token is not None:
            req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8")
            try:
                return e.code, json.loads(payload)
            except json.JSONDecodeError:
                return e.code, {"raw": payload}


@pytest.fixture
def gateway_server(tmp_path, workspace):
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text("{}", encoding="utf-8")
    server = G.GatewayServer(("127.0.0.1", 0), G.GatewayHandler, tokens={}, workspace=workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    handle = GatewayHandle(base_url=f"http://{host}:{port}", tokens_path=tokens_path, server=server)
    yield handle
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# CLI -- invoke the real `amplifier-work-tracker` CLI as a subprocess.
# ---------------------------------------------------------------------------


@pytest.fixture
def run_cli(workspace_root):
    """Invoke the real CLI as a subprocess (``python -m
    amplifier_work_tracker.cli``, exactly what the installed
    ``amplifier-work-tracker`` console script also runs) -- the actual CLI
    surface a coding agent would run -- pre-pointed at the isolated
    workspace root."""

    def _run(
        args: list[str], env: dict | None = None, timeout: float = 240
    ) -> subprocess.CompletedProcess:
        full_env = dict(os.environ if env is None else env)
        full_env.setdefault("AMPLIFIER_WORK_TRACKER_ROOT", str(workspace_root))
        return subprocess.run(
            [sys.executable, "-m", "amplifier_work_tracker.cli", *args],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=timeout,
            check=False,
        )

    return _run


@pytest.fixture
def env_without_bd():
    """A copy of the environment with every PATH entry that provides `bd`
    removed -- used to prove commands fail loudly (non-zero exit) when bd
    is entirely absent, instead of silently doing nothing or exiting 0."""
    bd_path = shutil.which("bd")
    env = dict(os.environ)
    if bd_path:
        bd_dir = str(Path(bd_path).parent)
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p != bd_dir]
        env["PATH"] = os.pathsep.join(parts)
    assert shutil.which("bd", path=env.get("PATH", "")) is None, (
        "failed to strip bd from PATH for the failure-injection fixture -- "
        "is `bd` installed in more than one PATH directory?"
    )
    return env
