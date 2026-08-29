"""`work_edit` -- amend an item's own content in place (attributed via an
audit comment), or mark it superseded by a different item via `merge_into`.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests).
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


PROJECT_PREFIX = "editproj"


@pytest.mark.asyncio
async def test_edit_amends_fields_with_no_held_item_required(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "original title", description="original description")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    edit_session = WorkTrackerSession({"actor": _unique("editor")})
    assert edit_session._held is None  # noqa: SLF001
    result = await edit_session.edit(project, item_id, title="new title")

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["edited"] == item_id
    assert output["title"] == "new title"
    assert output["description"] == "original description"
    assert edit_session._held is None  # noqa: SLF001 -- still nothing held afterward


@pytest.mark.asyncio
async def test_edit_refuses_combining_merge_into_with_field_edits(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "combo probe")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    edit_session = WorkTrackerSession({"actor": _unique("editor")})
    result = await edit_session.edit(project, item_id, title="x", merge_into="some-other-id")
    assert result.success is False
    assert "cannot be combined" in str(result.output)


@pytest.mark.asyncio
async def test_edit_merge_into_supersedes_and_closes_the_item(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    old = await add_session.add(project, "old item")
    old_output: dict[str, Any] = old.output  # type: ignore[assignment]
    old_id = old_output["added"]
    new = await add_session.add(project, "new item")
    new_output: dict[str, Any] = new.output  # type: ignore[assignment]
    new_id = new_output["added"]

    edit_session = WorkTrackerSession({"actor": _unique("merger")})
    result = await edit_session.edit(project, old_id, merge_into=new_id)

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["superseded"] == old_id
    assert output["with"] == new_id
    assert output["status"] == "resolved"


@pytest.mark.asyncio
async def test_edit_reports_beads_errors_without_raising(project):
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.edit(project, "no-such-item-id-zzz", title="x")
    assert result.success is False
