"""Puts the repo's `src/` on sys.path so `amplifier_work_tracker` resolves
the same way it does at runtime (foundation's `activate_bundle_package()`
installs the bundle root package editable and adds its `src/` to
`sys.path` before this module's `mount()` ever runs -- see
`docs/BUNDLE_GUIDE.md`, "Bundle with Root Python Package"). Not part of
this module's own installed dependencies (deliberately -- see
`pyproject.toml`'s comment), so local test runs need the same adjustment.

Also home to `make_project`, the shared create-and-drop fixture body for
this suite's real-`bd` tests. Each of those tests creates a project, and a
project lives in two places: a `tmp_path` directory pytest cleans up for
free, and a database on the shared dolt server that nothing cleans up
unless we do. Skipping the second half is what left 38 `reapproj*`, 18
`addproj*` and 5 `listproj*` orphaned databases on a live box -- see
`tests/conftest.py`'s module docstring in the repo root for the measured
cost, and `scripts/sweep_test_residue.py` for removing residue an older
run already left behind.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import amplifier_work_tracker.adapter as A  # noqa: E402 - must follow the sys.path insert above

#: Default prefix for `project`-fixture names. A test module overrides it by
#: setting its own module-level `PROJECT_PREFIX`, which keeps the per-suite
#: names distinguishable on a shared server without triplicating the fixture.
DEFAULT_PROJECT_PREFIX = "modproj"


@pytest.fixture
def project(request, tmp_path, monkeypatch):
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
