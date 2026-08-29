"""`work_dep` -- declare (write) or display (read) dependency/dependent
edges on an item, with no held item required.

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


PROJECT_PREFIX = "depproj"


@pytest.mark.asyncio
async def test_dep_declares_edge_and_returns_it(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    blocker = await add_session.add(project, "blocker item")
    blocker_output: dict[str, Any] = blocker.output  # type: ignore[assignment]
    blocker_id = blocker_output["added"]
    blocked = await add_session.add(project, "blocked item")
    blocked_output: dict[str, Any] = blocked.output  # type: ignore[assignment]
    blocked_id = blocked_output["added"]

    dep_session = WorkTrackerSession({"actor": _unique("declarer")})
    assert dep_session._held is None  # noqa: SLF001
    result = await dep_session.dep(project, blocked_id, depends_on=blocker_id)

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["id"] == blocked_id
    assert any(link["id"] == blocker_id for link in output["links"])
    assert dep_session._held is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_dep_without_depends_on_only_displays_existing_edges(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "solo item")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.dep(project, item_id)
    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["id"] == item_id
    assert output["links"] == []


@pytest.mark.asyncio
async def test_dep_blocks_type_makes_work_claim_refuse_naming_the_blocker(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    blocker = await add_session.add(project, "claim-blocker item")
    blocker_output: dict[str, Any] = blocker.output  # type: ignore[assignment]
    blocker_id = blocker_output["added"]
    blocked = await add_session.add(project, "claim-blocked item")
    blocked_output: dict[str, Any] = blocked.output  # type: ignore[assignment]
    blocked_id = blocked_output["added"]

    dep_session = WorkTrackerSession({"actor": _unique("declarer")})
    await dep_session.dep(project, blocked_id, depends_on=blocker_id)

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    result = await claim_session.claim(project, item_id=blocked_id)
    assert result.success is False
    assert blocker_id in str(result.output)


@pytest.mark.asyncio
async def test_dep_reports_beads_errors_without_raising(project):
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.dep(project, "no-such-item-id-zzz", depends_on="also-missing")
    assert result.success is False
