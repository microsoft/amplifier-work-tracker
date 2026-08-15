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
- Server-side state is cleaned up too, not just the local directory. A
  project lives in two independent places: a directory under the tmp root
  above, and a database on the shared dolt server (bd's shared-server
  topology stores it under ``~/.beads/shared-server/dolt/<name>``). This
  file used to document dropping the second half as an accepted trade-off
  -- correctly, at the time: there was no removal primitive. There is one
  now (``adapter.drop_database`` / ``Workspace.remove``, added in PR #6),
  so the trade-off is no longer accepted, because the cost was measured
  and it is not small. On a live box: 163 databases for 5 real projects,
  157 of them test residue. dolt holds every database open -- dropping the
  residue took the server from 1.15 GB RSS / 313 MB on disk to 0.12 GB /
  18 MB. Unique names stop runs colliding; they do not stop the pile
  growing on every CI run.

  Every fixture here that creates a project therefore drops it again (see
  ``drop_project``), and ``assert_no_leaked_projects`` fails the session if
  any created project outlives the run. Unique naming is still what makes
  the suite parallel-safe; teardown is what makes it leave nothing behind.
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


# ---------------------------------------------------------------------------
# Teardown -- every project this suite creates is dropped again.
# ---------------------------------------------------------------------------

# Names handed out by the project-creating fixtures below, minus the ones
# already dropped. Process-local by construction, so this stays correct
# under pytest-xdist: each worker only ever accounts for its own names and
# never observes (or asserts on) another worker's databases.
_OUTSTANDING: set[str] = set()


def drop_project(workspace: A.Workspace, name: str) -> None:
    """Teardown counterpart to creating a project: drop its database from
    the shared dolt server, then its local directory.

    Uses ``adapter.drop_database`` -- the repo's own removal primitive, the
    same one ``Workspace.remove`` calls -- rather than raw SQL from a test.
    It goes to the primitive rather than to ``Workspace.remove`` on purpose:
    ``remove`` refuses (correctly, and with no override) while any item is
    HELD, and several tests here deliberately leave an item held to prove
    exactly that refusal. Teardown's job is to leave nothing behind, not to
    re-test the safety gate -- ``Workspace.remove`` is exercised properly by
    ``tests/integration/test_project_removal.py`` and the CLI ``remove``
    tests, which is where that belongs.

    Fails loud: ``drop_database`` returns False for a database that was
    never there (fine -- e.g. a test whose ``create`` was expected to be
    rejected) and raises for any other failure, so a teardown that cannot
    actually remove data never passes for one that did.
    """
    try:
        A.drop_database(name)
    finally:
        # Dropped from the ledger even if the drop raised: the failure is
        # already propagating loudly, and leaving the name outstanding would
        # bury it under a second, less specific session-end error.
        _OUTSTANDING.discard(name)
        shutil.rmtree(workspace.path(name), ignore_errors=True)


def _track(name: str) -> str:
    _OUTSTANDING.add(name)
    return name


@pytest.fixture(scope="session", autouse=True)
def assert_no_leaked_projects(workspace):
    """The regression guard for this whole file: if any project a fixture
    handed out is still on the shared dolt server when the session ends,
    drop it and FAIL, naming every one.

    Without this, a future fixture that forgets its teardown reintroduces
    the leak silently -- which is precisely how the suite accumulated 157
    orphaned databases on a live box before anyone noticed.
    """
    yield
    leaked = sorted(_OUTSTANDING)
    if not leaked:
        return
    for name in leaked:
        with contextlib.suppress(A.BeadsError):
            A.drop_database(name)
        shutil.rmtree(workspace.path(name), ignore_errors=True)
    raise AssertionError(
        f"{len(leaked)} project(s) created by this test session were never dropped: "
        f"{', '.join(leaked)}. They have been dropped now, but a fixture is "
        f"missing its teardown -- every project a fixture creates must call "
        f"`drop_project`."
    )


@pytest.fixture
def unique_project_name(workspace):
    """A unique project name, plus the teardown for whatever ends up
    created under it.

    Teardown lives here rather than at the end of each test body so it
    still runs when a test fails partway -- the case that leaks. Tests are
    free to create nothing at all under the name (several assert that
    creation is refused); dropping a database that never existed is a
    no-op, not an error.
    """
    name = _track(unique_name("proj"))
    yield name
    drop_project(workspace, name)


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
def shared_project_name(workspace):
    """One real bd project, created once (``bd init`` takes several seconds
    against the shared dolt server) and reused by every integration test
    that just needs *a* project to work in. Isolation between tests comes
    from unique lane tags / ids within it, not from separate projects.

    Dropped at the end of the session -- items held by tests that never
    released them do not block this, see ``drop_project``."""
    name = _track(unique_name("shared"))
    workspace.create(name)
    yield name
    drop_project(workspace, name)


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

    created: list[str] = []

    def _make(prefix: str = "proj") -> tuple[str, A.Beads]:
        name = _track(unique_name(prefix))
        created.append(name)  # recorded BEFORE create: a create that fails
        # partway can still leave a database behind, and that is exactly the
        # residue teardown must reach.
        workspace.create(name)
        return name, workspace.project(name)

    yield _make

    for name in created:
        drop_project(workspace, name)


@pytest.fixture(scope="module")
def probe():
    """A disposable throwaway project, via ``amplifier_work_tracker.contract.Probe``
    -- reused directly here (rather than reimplemented) so integration tests
    exercise the exact same probing machinery ``amplifier-work-tracker doctor``
    does. ``Probe`` drops its own database on exit, so this needs no teardown
    of its own (and ``test_probe_leaves_no_database_behind`` proves it)."""
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
