"""`work_add` -- the sanctioned path for filing a project's FIRST work item
(or any later one) with no held item required.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves `add` -> `claim` actually round-trips
through the real storage layer, not just that our own Python agrees with
itself.
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


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "addproj"


@pytest.mark.asyncio
async def test_add_files_a_claimable_item_with_no_held_item_required(project):
    """The core gap this tool closes: work_file refuses without a held
    item; work_add must NOT."""
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.add(
        project, "Add health check endpoint", acceptance="GET /health -> 200"
    )

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["added"]
    assert output["project"] == project
    assert output["lane"] == A.LANE_WORK


@pytest.mark.asyncio
async def test_added_item_applies_the_engineering_lane_label_itself(project):
    """The caller must never need to know `lane:eng` exists -- proven by
    reading the item back and asserting the tag landed without us naming it
    anywhere in the call."""
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.add(project, "some new task")
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    new_id = output["added"]

    item = A.Workspace(session._ws.root).project(project).get(new_id)  # noqa: SLF001
    assert A.LANE_WORK in item.tags


@pytest.mark.asyncio
async def test_add_then_claim_end_to_end(project):
    """The literal acceptance criterion from the task: add creates a
    claimable item end-to-end -- add -> claim returns it."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(
        project,
        "Add health check endpoint",
        description="Implement /health",
        acceptance="200 OK",
    )
    assert added.success is True
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    new_id = added_output["added"]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project)
    assert claimed.success is True
    claimed_output: dict[str, Any] = claimed.output  # type: ignore[assignment]
    assert claimed_output["claimed"] == new_id
    assert claimed_output["acceptance"] == "200 OK"


@pytest.mark.asyncio
async def test_add_with_related_records_a_visible_edge(project):
    """work_tracker item 9e4: `related` on `work_add` records a real
    dependency edge in the same atomic create call."""
    session = WorkTrackerSession({"actor": _unique("actor")})
    other = await session.add(project, "the other item")
    other_output: dict[str, Any] = other.output  # type: ignore[assignment]
    other_id = other_output["added"]

    result = await session.add(
        project,
        "the new item",
        related=[{"id": other_id, "kind": "relates-to"}],
    )
    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    new_id = output["added"]

    item = A.Workspace(session._ws.root).project(project).get(new_id, with_links=True)  # noqa: SLF001
    assert any(link["id"] == other_id and link["type"] == "relates-to" for link in item.links)


@pytest.mark.asyncio
async def test_add_reports_beads_errors_without_raising(tmp_path, monkeypatch):
    """A nonexistent project must come back as a failed ToolResult, never a
    raised exception -- consistent with every other work_* tool's error
    handling."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.add("does-not-exist", "some title")
    assert result.success is False
    assert "not found" in str(result.output)
