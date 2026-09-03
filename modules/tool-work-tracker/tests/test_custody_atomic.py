"""Claim/custody atomicity -- contract `Core 3`, ledger row CCV1-003,
work_tracker item pipeline-aih.

`work_claim` is ONE call but TWO writes: the bd claim, then `take_custody`.
The hole these tests close: when the second write failed, the tool returned
an honest-looking failure and walked away, leaving the item HELD by this
actor with NO custody record and no session tracking it -- invisible to
`work_release` (this session never set `self._held`, so it refuses), and
freed only by the next reap sweep, up to a custody TTL later and only where
a sweep runs at all.

Both branches of the compensation are covered, because the dangerous one is
the second:

  1. compensating release SUCCEEDS -- the item is back on the queue, no
     custody record, and another actor can claim it immediately;
  2. compensating release ITSELF FAILS -- the item really may still be held,
     and the message must say exactly that, name the id, and never imply a
     rollback that did not happen.

Real `bd`/dolt end-to-end against this suite's isolated server (skipped if
`bd` is not on PATH, matching this module's other tests): the point is what
the STORAGE layer holds afterwards, which no mock can prove.
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
#: the project AND drops its isolated-server database again on teardown.
PROJECT_PREFIX = "custatomproj"

_INJECTED_CUSTODY = "injected take_custody failure"
_INJECTED_RELEASE = "injected release failure"


def _explode_take_custody(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ARG001
    raise A.BeadsError(_INJECTED_CUSTODY)


def _explode_release(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ARG001
    raise A.BeadsError(_INJECTED_RELEASE)


async def _seed(project: str, title: str) -> str:
    """One ready `lane:eng` item, filed by an unrelated actor."""
    added = await WorkTrackerSession({"actor": _unique("seeder")}).add(
        project, title, acceptance="n/a"
    )
    assert added.success is True
    return added.output["added"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_failed_take_custody_releases_the_claim_back_to_ready(project):
    """The whole of Core 3 in one path: claim lands, custody cannot be
    established, and the item is BACK ON THE QUEUE before `work_claim`
    returns -- proven by reading the storage layer, not by trusting the
    tool's own report.
    """
    item_id = await _seed(project, "custody-atomicity probe")

    actor = _unique("atomicactor")
    session = WorkTrackerSession({"actor": actor})
    # A SCOPED monkeypatch, not the `monkeypatch` fixture: the shared
    # `project` fixture uses that same function-scoped instance to set
    # AMPLIFIER_WORK_TRACKER_ROOT, so an `undo()` mid-test would also unset
    # the workspace root out from under the rest of the test.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(A.Beads, "take_custody", _explode_take_custody)
        result = await session.claim(project)

    # (iii) the caller is told, loudly, BOTH facts -- and the tool's own
    # error channel is a failed ToolResult (see _guard.guarded), never a
    # raised exception a caller has to catch.
    assert result.success is False
    text: str = result.output  # type: ignore[assignment]
    assert "claim landed" in text
    assert "custody could not be established" in text
    assert "released back to ready" in text
    assert _INJECTED_CUSTODY in text, "the underlying reason must survive into the message"
    assert item_id in text

    # (i) the item is ready/open again, held by nobody -- read back through
    # the contention-free read path, from a session that did no writing.
    reader = WorkTrackerSession({"actor": _unique("reader")})._project(project)  # noqa: SLF001
    back = reader.get_readonly(item_id)
    assert back.status == "open", f"expected the claim to be undone, got status={back.status!r}"
    assert not back.holder, f"expected no holder, got {back.holder!r}"

    # (ii) and no custody record was left behind for it.
    assert reader.get_custody(item_id) is None

    # The failed claim also left NO local state to wedge this session.
    assert session._held is None  # noqa: SLF001

    # (iv) another actor can claim the very same item immediately -- no
    # reap sweep, no TTL wait. This is the fact that matters operationally.
    other = WorkTrackerSession({"actor": _unique("otheractor")})
    reclaimed = await other.claim(project, item_id=item_id)
    assert reclaimed.success is True, reclaimed.output
    out: dict[str, Any] = reclaimed.output  # type: ignore[assignment]
    assert out["claimed"] == item_id
    assert reader.get_custody(item_id) is not None

    await other.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_failed_take_custody_then_failed_release_says_the_item_may_still_be_held(
    project,
):
    """The branch that must never be silent: the compensating release ITSELF
    fails. The item genuinely IS still held, so the message must say so,
    name the id, and never claim a rollback that did not happen.
    """
    item_id = await _seed(project, "compensating-release failure probe")

    actor = _unique("stuckactor")
    session = WorkTrackerSession({"actor": actor})
    with pytest.MonkeyPatch.context() as mp:  # scoped -- see the test above
        mp.setattr(A.Beads, "take_custody", _explode_take_custody)
        mp.setattr(A.Beads, "release", _explode_release)
        result = await session.claim(project)

    assert result.success is False
    text: str = result.output  # type: ignore[assignment]
    assert "claim landed" in text
    assert "custody could not be established" in text
    assert "compensating release ALSO FAILED" in text
    assert "may STILL BE HELD" in text
    assert item_id in text, "an item that may still be held must be named by id"
    assert actor in text, "and so must the actor holding it"
    assert _INJECTED_CUSTODY in text
    assert _INJECTED_RELEASE in text
    # It must NOT claim a rollback that did not happen.
    assert "released back to ready" not in text

    # The message is honest: the item really is still held by this actor.
    reader = WorkTrackerSession({"actor": _unique("reader")})._project(project)  # noqa: SLF001
    back = reader.get_readonly(item_id)
    assert back.status == "held"
    assert back.holder == actor
    assert reader.get_custody(item_id) is None

    # And the operator-facing recovery the message points at really works.
    reader.release(item_id)
    assert reader.get_readonly(item_id).status == "open"
