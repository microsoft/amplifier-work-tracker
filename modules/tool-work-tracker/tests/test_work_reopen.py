"""`work_reopen` -- the agent-facing correction path for a published
resolution, and `work_resolve`'s refusal to overwrite one silently.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests).

The scenario these exist for (work_tracker item model_performance-uma):
an agent closes an item with text that later turns out to be wrong. Before
this, its only recourse was `work_resolve` again -- which exited 0, echoed
the OLD text back, and wrote nothing. Seven wrong resolutions shipped that
way, and the correction backlog they created is what this verb unblocks.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkReopenTool, WorkTrackerSession

import amplifier_work_tracker.adapter as A

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "reopenproj"


async def _closed_item(project: str, resolution: str) -> tuple[str, WorkTrackerSession]:
    """An item that has been claimed and resolved -- i.e. a published
    record, exactly the state a correction has to start from."""
    session = WorkTrackerSession({"actor": _unique("first")})
    added = await session.add(project, "reopen probe")
    item_id = added.output["added"]  # type: ignore[index]
    await session.claim(project, item_id=item_id)
    resolved = await session.resolve(item_id, resolution)
    assert resolved.success is True
    return item_id, session


@pytest.mark.asyncio
async def test_reopen_claim_resolve_corrects_the_published_record(project):
    wrong = "VERDICT: the retention gate PASSES"
    right = "CORRECTED: uncomputable -- arm B has zero valid runs"
    item_id, _ = await _closed_item(project, wrong)

    corrector = WorkTrackerSession({"actor": _unique("corrector")})
    result = await corrector.reopen(project, item_id, "the stored verdict is wrong")
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]

    assert out["reopened"] == item_id
    assert out["status"] != "resolved"
    assert out["previous_resolution"] == wrong
    assert out["previous_closed_at"]
    assert out["closed_at_cleared"] is True
    # claim defaults ON: a reopened item lands in the queue parallel lanes
    # poll, so a bare reopen races another agent for the item you reopened
    # in order to correct.
    assert out["claimed"] is True, out.get("claim_error")
    assert corrector._held is not None  # noqa: SLF001

    fixed = await corrector.resolve(item_id, right)
    assert fixed.success is True
    bd = A.Workspace(corrector._ws.root).project(project)  # noqa: SLF001
    back = bd.get(item_id)
    assert (back.resolution or "").strip() == right


@pytest.mark.asyncio
async def test_reopen_archives_the_previous_record_where_bd_cannot_destroy_it(project):
    """bd 1.1.2 CLEARS close_reason on reopen (measured) -- so the wrapper's
    archive comment is the only thing standing between a correction and the
    destruction of the record it corrects."""
    wrong = "the original text that bd itself will throw away"
    item_id, _ = await _closed_item(project, wrong)

    corrector = WorkTrackerSession({"actor": _unique("corrector")})
    await corrector.reopen(project, item_id, "correcting", claim=False)

    bd = A.Workspace(corrector._ws.root).project(project)  # noqa: SLF001
    comments = [e.detail or e.summary for e in bd.activity(item_id) if e.kind == "comment"]
    archived = "\n".join(c or "" for c in comments)
    assert wrong in archived
    assert "PREVIOUS closed_at:" in archived


@pytest.mark.asyncio
async def test_claim_leg_degrades_without_dropping_an_existing_hold(project):
    """THE ANSWER to the open question this item flagged: a session holds at
    most ONE item (see `_Held`). So `claim=True` from a session that already
    holds different work cannot be honoured -- and must not be honoured by
    dropping the caller's existing custody.

    The reopen still STANDS; the caller is told the claim leg failed and
    why. Rolling the reopen back is not an option either: that would mean a
    second close with invented text, which is the disease.
    """
    item_id, _ = await _closed_item(project, "closed once")

    busy = WorkTrackerSession({"actor": _unique("busy")})
    other = await busy.add(project, "other work")
    other_id = other.output["added"]  # type: ignore[index]
    await busy.claim(project, item_id=other_id)
    assert busy._held is not None  # noqa: SLF001
    held_before = busy._held  # noqa: SLF001

    result = await busy.reopen(project, item_id, "correcting while holding other work")
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]

    assert out["reopened"] == item_id
    assert out["claimed"] is False
    assert "already holding" in out["claim_error"]
    assert "claim it" in out["next_step"]

    # The existing hold is untouched -- never sacrificed to make room.
    assert busy._held is held_before  # noqa: SLF001
    assert not held_before.stop.is_set()

    # And the reopen genuinely landed.
    bd = A.Workspace(busy._ws.root).project(project)  # noqa: SLF001
    assert bd.get(item_id).status != "resolved"

    await busy.resolve(other_id, "test cleanup")


@pytest.mark.asyncio
async def test_reopen_refuses_an_item_that_is_not_resolved(project):
    session = WorkTrackerSession({"actor": _unique("s")})
    added = await session.add(project, "still open")
    item_id = added.output["added"]  # type: ignore[index]

    result = await session.reopen(project, item_id, "why")
    assert result.success is False
    assert "nothing to reopen" in str(result.output)


@pytest.mark.asyncio
async def test_reopen_refuses_an_empty_reason(project):
    item_id, _ = await _closed_item(project, "closed")
    session = WorkTrackerSession({"actor": _unique("s")})
    result = await session.reopen(project, item_id, "   ")
    assert result.success is False
    assert "reason is required" in str(result.output)


@pytest.mark.asyncio
async def test_work_resolve_refuses_divergent_text_on_a_closed_item(project):
    """The silent-discard defect, at the tool surface an agent actually
    calls: a correction sent through `work_resolve` must FAIL, not be
    swallowed and reported as success."""
    stored = "the original resolution"
    item_id, first = await _closed_item(project, stored)

    # A fresh session re-claims nothing -- resolve refuses on custody first
    # for an unheld item, so drive the underlying seam the tool uses.
    bd = A.Workspace(first._ws.root).project(project)  # noqa: SLF001
    with pytest.raises(A.BeadsError) as e:
        bd.resolve(item_id, "a completely different resolution")
    assert "NOTHING WAS WRITTEN" in str(e.value)
    assert "work_reopen(" in str(e.value)
    assert (bd.get(item_id).resolution or "").strip() == stored


@pytest.mark.asyncio
async def test_work_reopen_tool_is_registered_with_the_expected_surface(project):
    session = WorkTrackerSession({"actor": _unique("s")})
    tool = WorkReopenTool(session)
    assert tool.name == "work_reopen"
    schema = tool.input_schema
    # project + item_id, NOT work_resolve's bare `id`: by definition the
    # caller does not hold a closed item.
    assert schema["required"] == ["project", "item_id", "reason"]
    assert schema["properties"]["claim"]["default"] is True
