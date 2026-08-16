"""Puts the repo's `src/` on sys.path so `amplifier_work_tracker` resolves
the same way it does at runtime (foundation's `activate_bundle_package()`
installs the bundle root package editable and adds its `src/` to
`sys.path` before this module's `mount()` ever runs -- see
`docs/BUNDLE_GUIDE.md`, "Bundle with Root Python Package"). Not part of
this module's own installed dependencies (deliberately -- see
`pyproject.toml`'s comment), so local test runs need the same adjustment.
Also puts the repo's `tests/` on sys.path for the same reason -- this
suite is a genuinely separate pytest run (its own `pyproject.toml`, its
own `testpaths`) and cannot reach the root suite's `tests` package via a
normal import, but it needs `tests/_dolt_isolation.py`, which is NOT
package-relative to either suite for exactly that reason.

Also home to `make_project`, the shared create-and-drop fixture body for
this suite's real-`bd` tests. Each of those tests creates a project, and a
project lives in two places: a `tmp_path` directory pytest cleans up for
free, and a database on the dolt server that nothing cleans up unless we
do. Skipping the second half is what left 38 `reapproj*`, 18 `addproj*`
and 5 `listproj*` orphaned databases on a live box -- see
`tests/conftest.py`'s module docstring in the repo root for the measured
cost, and `scripts/sweep_test_residue.py` for removing residue an older
run already left behind.

That cost is what `isolated_dolt_server` below closes structurally: this
suite's projects no longer land on the shared, permanent server at all --
see `tests/_dolt_isolation.py`'s module docstring for the full story. The
per-test `project` fixture's own drop-both-halves teardown stays -- it is
still what keeps the isolated server's disk/RSS bounded across a long
run -- but it is no longer the only thing standing between a killed test
and a permanent leak.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import uuid
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_TESTS = Path(__file__).resolve().parents[3] / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _dolt_isolation as DI  # noqa: E402 - same

import amplifier_work_tracker.adapter as A  # noqa: E402 - must follow the sys.path insert above
import amplifier_work_tracker.supervisor as SV  # noqa: E402 - same

#: Default prefix for `project`-fixture names. A test module overrides it by
#: setting its own module-level `PROJECT_PREFIX`, which keeps the per-suite
#: names distinguishable on a shared server without triplicating the fixture.
DEFAULT_PROJECT_PREFIX = "modproj"


@pytest.fixture(scope="session", autouse=True)
def isolated_dolt_server(tmp_path_factory):
    """This suite's own copy of the root suite's fixture of the same name --
    see `tests/conftest.py`'s copy for the full rationale (this is a
    genuinely separate pytest run with its own fixture namespace, so the
    fixture ITSELF cannot be shared, only the isolation logic it calls
    into, via `_dolt_isolation`).
    """
    data_dir = tmp_path_factory.mktemp("isolated_dolt")
    server = DI.start(data_dir)

    mp = pytest.MonkeyPatch()
    mp.setattr(SV, "DEFAULT_DOLT_HOST", server.host)
    mp.setattr(SV, "DEFAULT_DOLT_PORT", server.port)
    mp.setenv("AMPLIFIER_WORK_TRACKER_DOLT_HOST", server.host)
    mp.setenv("AMPLIFIER_WORK_TRACKER_DOLT_PORT", str(server.port))

    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):  # noqa: ARG001 - required signal-handler signature
        DI.stop(server)
        signal.signal(signal.SIGTERM, previous_sigterm)
        os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        yield server
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        mp.undo()
        DI.stop(server)


@pytest.fixture(scope="session", autouse=True)
def assert_isolated_server_clean(isolated_dolt_server):
    """This suite's own copy of the root suite's fixture of the same name.

    On this isolated, per-session server every non-system database is test
    residue by construction, so any survivor at session end -- regardless
    of whether the `project` fixture that made it ran its own teardown --
    is a real leak. Dropped and reported loudly rather than left silent.
    """
    yield
    host, port = isolated_dolt_server.host, isolated_dolt_server.port
    leaked = DI.list_test_databases(host, port)
    if not leaked:
        return
    failed: list[str] = []
    for name in leaked:
        try:
            A.drop_database(name)
        except A.BeadsError as e:  # noqa: PERF203 - per-database, one failure must not hide the rest
            failed.append(f"{name} ({e})")
    detail = f"failed to drop: {', '.join(failed)}" if failed else "all dropped now"
    raise AssertionError(
        f"{len(leaked)} database(s) survived on the isolated test server "
        f"({host}:{port}) with no fixture accounting for them: "
        f"{', '.join(leaked)}. {detail}. A fixture somewhere created a "
        f"project without routing through the `project` fixture's "
        f"drop-both-halves teardown -- find it and fix it."
    )


@pytest.fixture
def project(request, tmp_path, monkeypatch, isolated_dolt_server):
    """A real `bd` project on an isolated workspace root -- created, yielded,
    then dropped in BOTH the places a project lives.

    Removal goes through `adapter.drop_database`: this repo's own removal
    primitive, the same one `Workspace.remove` calls, never raw SQL from a
    test. It goes to the primitive rather than to `Workspace.remove`
    because `remove` refuses (correctly, and with no override) while an
    item is HELD, and tests here deliberately leave items held to exercise
    reap/fence behaviour. `drop_database` raises on any failure other than
    "the database was never there", so a teardown that could not actually
    remove data fails loudly rather than passing for one that did.

    Depends on `isolated_dolt_server` explicitly (autouse would eventually
    get there too, but a real `bd init` here must never race its startup).
    """
    prefix = getattr(request.module, "PROJECT_PREFIX", DEFAULT_PROJECT_PREFIX)
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))
    name = f"{prefix}{uuid.uuid4().hex[:10]}"
    ws = A.Workspace(root)
    try:
        ws.create(name)
        yield name
    finally:
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(ws.path(name), ignore_errors=True)
