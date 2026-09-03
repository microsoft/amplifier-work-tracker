"""`work_defer` / `work_block` -- reasoned status transitions that leave
`work_claim`'s queue and default list views, with no held item required.

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


PROJECT_PREFIX = "deferproj"


@pytest.mark.asyncio
async def test_defer_sets_status_and_reason_with_no_held_item_required(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "defer me")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    defer_session = WorkTrackerSession({"actor": _unique("deferrer")})
    assert defer_session._held is None  # noqa: SLF001
    result = await defer_session.defer(project, item_id, reason="waiting on design")

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["id"] == item_id
    assert output["status"] == "deferred"
    assert defer_session._held is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_defer_requires_a_reason_unless_clearing(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "no reason probe")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.defer(project, item_id)
    assert result.success is False
    assert "reason is required" in str(result.output)


@pytest.mark.asyncio
async def test_defer_clear_moves_item_back_to_open(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "undefer probe")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    session = WorkTrackerSession({"actor": _unique("actor")})
    await session.defer(project, item_id, reason="temporary")
    result = await session.defer(project, item_id, clear=True)

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["status"] == "open"


@pytest.mark.asyncio
async def test_deferred_item_is_skipped_by_work_claim(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "deferred, skip me")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    defer_session = WorkTrackerSession({"actor": _unique("deferrer")})
    await defer_session.defer(project, item_id, reason="not now")

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=item_id)
    # A directed claim on a deferred item is still refused by bd's own
    # ready/claim machinery being blocker-of-visibility, not this feature's
    # concern -- what THIS test pins is that the QUEUE claim never surfaces it.
    queue_claimed = await claim_session.claim(project)
    assert queue_claimed.success is True
    queue_output: dict[str, Any] = queue_claimed.output  # type: ignore[assignment]
    assert queue_output.get("claimed") != item_id
    del claimed  # directed-claim behavior is out of scope for this test


@pytest.mark.asyncio
async def test_block_sets_status_and_reason_with_no_held_item_required(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "block me")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    block_session = WorkTrackerSession({"actor": _unique("blocker")})
    assert block_session._held is None  # noqa: SLF001
    result = await block_session.block(project, item_id, reason="needs security review")

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["id"] == item_id
    assert output["status"] == "blocked"
    assert block_session._held is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_block_clear_moves_item_back_to_open(project):
    add_session = WorkTrackerSession({"actor": _unique("actor")})
    added = await add_session.add(project, "unblock probe")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]

    session = WorkTrackerSession({"actor": _unique("actor")})
    await session.block(project, item_id, reason="temporary")
    result = await session.block(project, item_id, clear=True)

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["status"] == "open"


@pytest.mark.asyncio
async def test_defer_reports_beads_errors_without_raising(project):
    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.defer(project, "no-such-item-id-zzz", reason="x")
    assert result.success is False


# --------------------------------------------------------------------------
# model_performance-2nx -- the agent-facing half of the same door.
#
# `work_defer`/`work_block` are the surface an AGENT reaches for, and an
# agent reads `success`, not an exit code. Before the guard, both returned
# success=True on an already-resolved item, having blanked its published
# resolution -- so the tool told the model the operation worked while the
# official record was destroyed.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["defer", "block"])
@pytest.mark.asyncio
async def test_defer_block_on_a_resolved_item_report_failure_and_keep_the_resolution(
    project, verb: str
):
    original = "ORIGINAL TEXT -- the official record"
    actor = _unique("actor")
    session = WorkTrackerSession({"actor": actor})
    added = await session.add(project, f"{verb} on resolved probe")
    added_output: dict[str, Any] = added.output  # type: ignore[assignment]
    item_id = added_output["added"]
    await session.claim(project, item_id=item_id)
    resolved = await session.resolve(item_id, original)
    assert resolved.success is True, resolved.output

    result = await getattr(session, verb)(project, item_id, reason="probe")

    assert result.success is False, result.output
    text = str(result.output)
    assert "resolved" in text
    assert "reopen" in text
    assert "NOTHING WAS WRITTEN" in text

    listed = await session.list_items(project, item_id=item_id)
    row: dict[str, Any] = listed.output  # type: ignore[assignment]
    item = row["items"][0]
    assert item["status"] == "resolved"
    assert item["resolution"] == original
