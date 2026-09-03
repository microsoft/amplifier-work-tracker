"""`work_erratum` -- the agent-facing append-only correction for a
RESOLVED item's own record, distinct from `work_reopen` (which is for
when the WORK itself must be redone).

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests). work_tracker item pipeline-03c: an agent resolved
an item with a factually false reason, noticed in the same run, and had
no sanctioned way to correct the record without either destroying the
resolution's finality (`work_reopen`) or silently discarding the
correction (`work_resolve` against an already-closed item).
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkErratumTool, WorkTrackerSession

import amplifier_work_tracker.adapter as A

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py.
PROJECT_PREFIX = "erratumproj"


async def _closed_item(project: str, resolution: str) -> str:
    session = WorkTrackerSession({"actor": _unique("first")})
    added = await session.add(project, "erratum probe")
    item_id = added.output["added"]  # type: ignore[index]
    await session.claim(project, item_id=item_id)
    resolved = await session.resolve(item_id, resolution)
    assert resolved.success is True
    return item_id


@pytest.mark.asyncio
async def test_erratum_end_to_end_appends_and_never_touches_the_resolution(project):
    resolution = "VERDICT: the retention gate PASSES"
    item_id = await _closed_item(project, resolution)

    corrector = WorkTrackerSession({"actor": _unique("corrector")})
    result = await corrector.erratum(project, item_id, "the underlying data was mislabeled")

    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["id"] == item_id
    assert out["corrected"] is True
    assert len(out["errata"]) == 1
    assert out["errata"][0]["text"] == "the underlying data was mislabeled"
    assert "already_recorded" not in out

    bd = A.Workspace(corrector._ws.root).project(project)  # noqa: SLF001
    back = bd.get_readonly(item_id)
    assert (back.resolution or "").strip() == resolution
    assert back.status == "resolved"


@pytest.mark.asyncio
async def test_erratum_does_not_take_custody(project):
    """No held item required, and the corrector never ends up holding
    anything -- verified via BOTH the session's own local bookkeeping and
    the same `work_status`-style project roll-up an agent would check."""
    item_id = await _closed_item(project, "closed the first time")

    corrector = WorkTrackerSession({"actor": _unique("corrector")})
    assert corrector._held is None  # noqa: SLF001 -- before

    result = await corrector.erratum(project, item_id, "the reason recorded was misleading")
    assert result.success is True

    assert corrector._held is None  # noqa: SLF001 -- still nothing held afterward

    status = await corrector.status()
    assert status.success is True
    assert status.output["holding"] is None  # type: ignore[index]

    bd = A.Workspace(corrector._ws.root).project(project)  # noqa: SLF001
    assert bd.get_readonly(item_id).status == "resolved"
    assert bd.get_readonly(item_id).holder != corrector._actor  # noqa: SLF001


@pytest.mark.asyncio
async def test_erratum_same_text_re_append_is_idempotent(project):
    item_id = await _closed_item(project, "closed text")
    text = "the same correction, byte for byte"

    first_actor = WorkTrackerSession({"actor": _unique("alice")})
    first = await first_actor.erratum(project, item_id, text)
    assert first.success is True
    assert "already_recorded" not in first.output  # type: ignore[operator]

    second_actor = WorkTrackerSession({"actor": _unique("bob")})
    again = await second_actor.erratum(project, item_id, f"  {text}\r\n")
    assert again.success is True
    out: dict[str, Any] = again.output  # type: ignore[assignment]
    assert out["already_recorded"] is True
    assert len(out["errata"]) == 1, "a same-text re-append must add no second erratum"


@pytest.mark.asyncio
async def test_erratum_refuses_an_item_that_is_not_resolved_and_names_edit(project):
    session = WorkTrackerSession({"actor": _unique("s")})
    added = await session.add(project, "still open")
    item_id = added.output["added"]  # type: ignore[index]

    result = await session.erratum(project, item_id, "doesn't matter, refused first")
    assert result.success is False
    msg = str(result.output).lower()
    assert "'resolved'" in msg or "resolved" in msg
    assert "edit" in msg


@pytest.mark.asyncio
async def test_erratum_reports_beads_errors_without_raising(project):
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.erratum(project, "no-such-item-id-zzz", "text")
    assert result.success is False


@pytest.mark.asyncio
async def test_work_list_surfaces_errata_and_corrected(project):
    item_id = await _closed_item(project, "closed text")
    corrector = WorkTrackerSession({"actor": _unique("corrector")})
    await corrector.erratum(project, item_id, "the reason recorded was misleading")

    directed = await corrector.list_items(project, item_id=item_id)
    assert directed.success is True
    row = directed.output["items"][0]  # type: ignore[index]
    assert row["corrected"] is True
    assert len(row["errata"]) == 1
    assert row["errata"][0]["by"] == corrector._actor  # noqa: SLF001
    assert row["errata"][0]["text"] == "the reason recorded was misleading"

    lean = await corrector.list_items(project, status="resolved")
    assert lean.success is True
    lean_row = next(r for r in lean.output["items"] if r["id"] == item_id)  # type: ignore[index]
    assert lean_row["corrected"] is True
    assert "errata" not in lean_row


@pytest.mark.asyncio
async def test_work_erratum_tool_is_registered_with_the_expected_surface(project):
    session = WorkTrackerSession({"actor": _unique("s")})
    tool = WorkErratumTool(session)
    assert tool.name == "work_erratum"
    schema = tool.input_schema
    assert schema["required"] == ["project", "item_id", "text"]
