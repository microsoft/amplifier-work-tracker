"""`work_move` -- migrate a work item from one project's queue to another,
preserving its id, with no held item required.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves `add` -> `move` -> a real read on both
projects actually round-trips through the real storage layer, not just that
our own Python agrees with itself.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

import amplifier_work_tracker.adapter as A

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py -- the SOURCE
#: project for every test here. The destination is `dst_project`, below.
PROJECT_PREFIX = "movesrc"


@pytest.fixture
def dst_project(project):
    """A second project under the SAME workspace root as `project` (the
    move destination) -- created and dropped independently, since the
    shared `project` fixture only manages one name. Depends on `project`
    (not just its side effects) so the workspace root is guaranteed already
    repointed before this creates anything.
    """
    ws = A.Workspace()  # picks up AMPLIFIER_WORK_TRACKER_ROOT, set by `project`
    name = _unique("movedst")
    ws.create(name)
    try:
        yield name
    finally:
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(ws.path(name), ignore_errors=True)


@pytest.mark.asyncio
async def test_move_moves_item_between_projects_with_no_held_item_required(project, dst_project):
    """The core gap this tool closes: before work_move existed, there was no
    sanctioned way (for an agent or a human) to migrate a work item between
    projects at all.
    """
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "migrate me", acceptance="given/when/then")
    assert added.success is True
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    move_session = WorkTrackerSession({"actor": _unique("mover")})
    result = await move_session.move(item_id, project, dst_project)

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["moved"] == item_id
    assert output["from"] == project
    assert output["to"] == dst_project
    assert output["dropped_dependency_edges"] == []

    # Cross-check with a REAL read on both projects: gone from src, present
    # in dst with the SAME id and body.
    ws = A.Workspace(move_session._ws.root)  # noqa: SLF001 -- test introspection only
    with pytest.raises(A.BeadsError):
        ws.project(project).get(item_id)
    moved = ws.project(dst_project).get(item_id)
    assert moved.id == item_id
    assert moved.acceptance == "given/when/then"


@pytest.mark.asyncio
async def test_move_does_not_require_a_held_item_in_this_session(project, dst_project):
    """Unlike work_file/work_resolve/work_release, work_move must succeed
    even when the CALLING session is holding nothing at all -- it is not a
    custody operation.
    """
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "no session hold needed")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    fresh_session = WorkTrackerSession({"actor": _unique("mover")})
    assert fresh_session._held is None  # noqa: SLF001 -- confirms nothing held before the call
    result = await fresh_session.move(item_id, project, dst_project)
    assert result.success is True
    assert fresh_session._held is None  # noqa: SLF001 -- still nothing held afterward


@pytest.mark.asyncio
async def test_move_refuses_while_item_is_held_by_another_session(project, dst_project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "held item")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    holder_session = WorkTrackerSession({"actor": _unique("holder")})
    claimed = await holder_session.claim(project, item_id=item_id)
    assert claimed.success is True

    move_session = WorkTrackerSession({"actor": _unique("mover")})
    result = await move_session.move(item_id, project, dst_project)

    assert result.success is False
    assert "HELD" in str(result.output)

    # Untouched: still readable (and held) in the source project.
    ws = A.Workspace(move_session._ws.root)  # noqa: SLF001 -- test introspection only
    assert ws.project(project).get(item_id).status == "held"


@pytest.mark.asyncio
async def test_move_reports_beads_errors_without_raising(project):
    """A nonexistent destination project must come back as a failed
    ToolResult, never a raised exception -- consistent with every other
    work_* tool's error handling (see `_guard.py`'s module docstring).
    """
    session = WorkTrackerSession({"actor": _unique("actor")})
    added = await session.add(project, "x")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    result = await session.move(item_id, project, "does_not_exist_anywhere_xyz")
    assert result.success is False
    assert "does not exist" in str(result.output)
