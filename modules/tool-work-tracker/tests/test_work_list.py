"""`work_list` -- the read-only per-item view neither `work_status` nor any
other tool provides: id, title, status, holder, and (for closed items)
resolution.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves the tool round-trips through the real
storage layer, not just that our own Python agrees with itself.
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
PROJECT_PREFIX = "listproj"


@pytest.mark.asyncio
async def test_list_shows_mixed_states_with_holder_and_resolution(project):
    """The core scenario the real contention test surfaced a gap for: one
    project, some ready, some held, some closed -- all visible in one
    read-only call, with holder actually populated for the held item."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    open_added = await add_session.add(project, "list probe: open")
    held_added = await add_session.add(project, "list probe: held")
    closed_added = await add_session.add(project, "list probe: closed")
    open_id = open_added.output["added"]  # type: ignore[index]
    held_id = held_added.output["added"]  # type: ignore[index]
    closed_id = closed_added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=held_id)
    assert claimed.success is True

    resolve_session = WorkTrackerSession({"actor": _unique("resolver")})
    resolve_claim = await resolve_session.claim(project, item_id=closed_id)
    assert resolve_claim.success is True
    resolved = await resolve_session.resolve(closed_id, "closed via work_list test")
    assert resolved.success is True

    list_session = WorkTrackerSession({"actor": _unique("lister")})
    result = await list_session.list_items(project)
    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    by_id = {row["id"]: row for row in output["items"]}

    assert by_id[open_id]["status"] == "open"
    assert by_id[open_id]["holder"] is None
    assert by_id[open_id]["resolution"] is None

    assert by_id[held_id]["status"] == "held"
    assert by_id[held_id]["holder"] == claim_session._actor  # noqa: SLF001

    assert by_id[closed_id]["status"] == "resolved"
    assert by_id[closed_id]["resolution"] == "closed via work_list test"

    await claim_session.resolve(held_id, "test cleanup")


@pytest.mark.asyncio
async def test_list_status_filter_returns_only_matching_status(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    open_added = await add_session.add(project, "status-filter open")
    held_added = await add_session.add(project, "status-filter held")
    open_id = open_added.output["added"]  # type: ignore[index]
    held_id = held_added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=held_id)
    assert claimed.success is True

    list_session = WorkTrackerSession({"actor": _unique("lister")})
    result = await list_session.list_items(project, status="held")
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    ids = {row["id"] for row in output["items"]}
    assert held_id in ids
    assert open_id not in ids
    for row in output["items"]:
        assert row["status"] == "held"

    await claim_session.resolve(held_id, "test cleanup")


@pytest.mark.asyncio
async def test_list_rejects_unknown_status(project):
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.list_items(project, status="not-a-real-status")
    assert result.success is False
    assert "unknown status" in str(result.output)


@pytest.mark.asyncio
async def test_list_never_claims_mutates_or_touches_custody(project):
    """Strictly read-only: this session's own `_held` state must be
    untouched, and full project state before/after must be identical."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    await add_session.add(project, "no-mutation open")
    held_added = await add_session.add(project, "no-mutation held")
    held_id = held_added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=held_id)
    assert claimed.success is True

    bd = A.Workspace(claim_session._ws.root).project(project)  # noqa: SLF001

    def snapshot():
        items = bd.list(include_resolved=True)
        return {i.id: (i.status, i.holder, i.resolution) for i in items}

    before = snapshot()

    list_session = WorkTrackerSession({"actor": _unique("lister")})
    assert list_session._held is None  # noqa: SLF001
    await list_session.list_items(project)
    await list_session.list_items(project, status="held")
    await list_session.list_items(project, status="open", limit=1)
    assert list_session._held is None  # noqa: SLF001 -- list must never claim

    after = snapshot()
    assert before == after

    await claim_session.resolve(held_id, "test cleanup")


@pytest.mark.asyncio
async def test_list_on_empty_project_returns_empty_not_an_error(project):
    """Uses the shared `project` fixture -- a freshly created project has no
    items, which is exactly the state under test, and the fixture drops its
    database again afterward (this test used to mint its own `listempty*`
    project inline and leave the database behind forever)."""
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.list_items(project)
    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["items"] == []
    assert output["total_count"] == 0
    assert output["truncated"] is False


@pytest.mark.asyncio
async def test_list_reports_beads_errors_without_raising(tmp_path, monkeypatch):
    """A nonexistent project must come back as a failed ToolResult, never a
    raised exception -- consistent with every other work_* tool."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.list_items("does-not-exist")
    assert result.success is False
    assert "not found" in str(result.output)


@pytest.mark.asyncio
async def test_list_truncates_and_reports_it_explicitly(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    for n in range(4):
        await add_session.add(project, f"truncation probe {n}")

    list_session = WorkTrackerSession({"actor": _unique("lister")})
    result = await list_session.list_items(project, status="open", limit=2)
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["returned_count"] == 2
    assert output["total_count"] >= 4
    assert output["truncated"] is True
