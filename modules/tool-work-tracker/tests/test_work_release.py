"""`work_release` -- voluntary unclaim. Returns a HELD item to open/ready,
stops custody renewal, sets NO resolution, and refuses if this session does
not hold the named item. The inverse of `work_claim`, a sibling of
`work_resolve` that closes nothing.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests).
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
PROJECT_PREFIX = "releaseproj"


@pytest.mark.asyncio
async def test_release_returns_held_item_to_the_queue_and_stops_custody(project):
    """The core scenario: claim an item, release it, and it goes straight
    back to open/ready -- reclaimable immediately, with NO resolution set,
    and this session's local hold cleared."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "release probe")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    claimed = await session.claim(project, item_id=item_id)
    assert claimed.success is True
    assert session._held is not None  # noqa: SLF001
    held = session._held  # noqa: SLF001

    result = await session.unclaim(item_id)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["released"] == item_id

    # Local state cleared and the renewal thread signalled to stop.
    assert session._held is None  # noqa: SLF001
    assert held.stop.is_set()

    # Back to open/ready in the real store, with no resolution.
    bd = A.Workspace(session._ws.root).project(project)  # noqa: SLF001
    back = bd.get(item_id)
    assert back.status == "open"
    assert back.holder is None
    assert back.resolution is None


@pytest.mark.asyncio
async def test_released_item_can_be_claimed_again_immediately(project):
    """No reclaim-timeout wait: a released item is claimable the very next
    moment, including by the same session."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "re-claim probe")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    assert (await session.claim(project, item_id=item_id)).success is True
    assert (await session.unclaim(item_id)).success is True

    reclaim = await session.claim(project, item_id=item_id)
    assert reclaim.success is True
    assert reclaim.output["claimed"] == item_id  # type: ignore[index]

    await session.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_release_refuses_when_not_holding_anything(project):
    """A session holding nothing must not be able to release an item -- and
    must mutate nothing when it refuses."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "not-held probe")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("nonholder")})
    assert session._held is None  # noqa: SLF001
    result = await session.unclaim(item_id)
    assert result.success is False
    assert "not currently holding" in str(result.output)

    # Untouched: still a plain open item, never claimed by the refusal.
    bd = A.Workspace(session._ws.root).project(project)  # noqa: SLF001
    back = bd.get(item_id)
    assert back.status == "open"
    assert back.holder is None


@pytest.mark.asyncio
async def test_release_refuses_a_different_item_than_the_one_held(project):
    """Holding item A, a release of item B must refuse and leave A held."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    a = await add_session.add(project, "held item A")
    b = await add_session.add(project, "other item B")
    a_id = a.output["added"]  # type: ignore[index]
    b_id = b.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    assert (await session.claim(project, item_id=a_id)).success is True

    result = await session.unclaim(b_id)
    assert result.success is False
    assert "not currently holding" in str(result.output)
    # Still holding A.
    assert session._held is not None  # noqa: SLF001
    assert session._held.item_id == a_id  # noqa: SLF001

    await session.resolve(a_id, "test cleanup")
