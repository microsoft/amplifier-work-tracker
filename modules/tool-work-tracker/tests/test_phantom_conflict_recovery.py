"""Phantom-conflict / wedge-recovery -- work_tracker item pipeline-yym.

Tool-layer counterpart to `tests/integration/test_phantom_conflict_recovery.py`
in the root suite (which covers `Beads.resolve`/`Beads.release` directly).
These prove the SESSION-facing behavior: `unclaim` (`work_release`) recovers
a session wedged believing it still holds an item bd already considers
resolved, and the background renewal thread never races a foreground
resolve/release/declare/claim call on the same item.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests).
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession, _Held

import amplifier_work_tracker.adapter as A

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "phantomproj"


class _RunOnceThenStop:
    """Fakes `threading.Event`'s shape: `.wait()` False the first call (so
    a driven `_renew_loop` runs its body exactly once), True thereafter
    (so it exits); `.is_set()` mirrors the same state for the loop's own
    "already stopped while waiting for the lock" check."""

    def __init__(self) -> None:
        self._calls = 0

    def wait(self, timeout: float | None = None) -> bool:
        self._calls += 1
        return self._calls > 1

    def set(self) -> None:  # noqa: A003 -- matches threading.Event's API
        pass

    def is_set(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_unclaim_recovers_a_session_wedged_on_an_already_closed_item(project):
    """Simulate the exact incident's residual state: the session BELIEVES
    it still holds an item that is actually already resolved (e.g. because
    a prior resolve landed despite reporting a spurious wrapper failure --
    see the adapter-level fix for that hazard). `work_release` must clear
    the session's local latch WITHOUT attempting to reopen the item, and
    report the recovery distinctly from a real release.
    """
    actor = _unique("wedged")
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "wedge recovery probe", acceptance="n/a")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": actor})
    claimed = await session.claim(project, item_id=item_id)
    assert claimed.success is True

    # Close it OUT OF BAND -- bypassing session.resolve() entirely, so the
    # session's own local `_held` stays set, exactly the residual state a
    # phantom wrapper failure would have left behind.
    bd = session._project(project)  # noqa: SLF001
    bd.resolve(item_id, "closed out of band", actor=actor)
    assert bd.get_readonly(item_id).status == "resolved"
    assert session._held is not None  # noqa: SLF001 -- still (wrongly) believes it holds it

    result = await session.unclaim(item_id)

    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["released"] == item_id
    assert out["custody"] == "item already closed; custody cleared"
    assert session._held is None  # noqa: SLF001

    # Structurally impossible to have reopened it.
    back = bd.get_readonly(item_id)
    assert back.status == "resolved"
    assert back.resolution == "closed out of band"

    # And the session is unwedged: a new claim succeeds immediately.
    second = await add_session.add(project, "wedge recovery probe 2", acceptance="n/a")
    second_id = second.output["added"]  # type: ignore[index]
    reclaimed = await session.claim(project)
    assert reclaimed.success is True
    assert reclaimed.output["claimed"] == second_id  # type: ignore[index]
    await session.resolve(second_id, "test cleanup")


@pytest.mark.asyncio
async def test_renew_loop_holds_session_lock_during_its_bd_call(project, monkeypatch):
    """Part 3 of the phantom-failure investigation (the self-contention
    lead): the renewal thread's OWN bd write must be serialized against
    resolve/release/declare/claim's bd calls via the SAME session lock --
    proven directly by observing the lock is already held when
    `renew_custody` runs, driving `_renew_loop` exactly once (same pattern
    as `test_reap_recovery.py`'s background-loop tests).
    """
    actor = _unique("lockactor")
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "lock probe", acceptance="n/a")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": actor})
    bd = session._project(project)  # noqa: SLF001
    item = bd.claim_next(lane=A.LANE_WORK, actor=actor)
    assert item is not None and item.id == item_id
    rec = bd.take_custody(item.id, holder=actor, pid=12345, host="test-host")
    held = _Held(project=project, item_id=item.id, actor=actor, generation=rec["generation"])
    session._held = held  # noqa: SLF001

    observed: dict[str, bool | None] = {"locked": None}
    real_renew = A.Beads.renew_custody

    def _spy(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        observed["locked"] = session._lock.locked()  # noqa: SLF001
        return real_renew(self, *args, **kwargs)

    monkeypatch.setattr(A.Beads, "renew_custody", _spy)

    held.stop = _RunOnceThenStop()  # type: ignore[assignment]  # noqa: SLF001
    session._renew_loop(held)  # noqa: SLF001

    assert observed["locked"] is True, (
        "renew_custody ran without the session lock held -- the self-contention "
        "race (a renewal write overlapping a resolve/release/declare/claim write "
        "on the same item row) is no longer closed"
    )

    await session.resolve(item_id, "test cleanup")
