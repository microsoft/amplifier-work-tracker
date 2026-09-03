"""Tier 5 -- the AGENT SEAM half of `model_performance-oy4`: after a lane's
process dies holding a claim, its relaunched successor can `work_claim` the
same item again, automatically, with no human-equivalent intervention.

WHY THIS LIVES HERE AND NOT ONLY IN tests/integration. The adapter tier
proves the sweep reclaims a dead holder's hold. This tier proves the thing a
STRANDED LANE actually experiences: the measured incident's successor session
could not `work_claim` (held by a dead agent), could not `work_release` (it
does not hold it) and could not `work_file` (filing requires holding an
item), so its own goal condition -- "write BLOCKED.md and release the item"
-- was literally unreachable. Those are all `WorkTrackerSession` verbs, so
that dead end is only reproducible at this seam.

DELIBERATELY NOT `ttl_seconds=0`. Every other reap test in this suite forces
staleness that way (`_force_reap`), which is exactly the shortcut that lets a
dead-holder bug hide: with ttl 0 EVERY hold is stale, so nothing is being
asserted about a hold that is still comfortably inside its TTL. These reap
with the real default TTL and a real silence of 400s against 900s, so a
reclaim here can only have come from the holder-liveness path.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import uuid

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

import amplifier_work_tracker.adapter as A
import amplifier_work_tracker.custody as C
import amplifier_work_tracker.supervisor as SV

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)

#: Consumed by the shared `project` fixture in conftest.py.
PROJECT_PREFIX = "deadholdproj"

HOST = socket.gethostname()
SILENCE_INSIDE_TTL = 400


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _a_genuinely_dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    p.wait()
    assert not C.pid_alive(p.pid)
    return p.pid


def _rewind_custody(bd: A.Beads, item_id: str, *, seconds_ago: int) -> None:
    rec = dict(bd.get(item_id).meta[C.CUSTODY_KEY])
    rec["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))
    bd._run(  # noqa: SLF001 -- forging a past renewal is not a public verb
        ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: rec})], actor=rec["holder"]
    )


async def _item_held_by_a_dead_lane(project: str) -> tuple[str, str, A.Beads]:
    """Reproduce the incident's starting state: an item claimed and given
    custody by a lane whose process then died, its last renewal
    `SILENCE_INSIDE_TTL` seconds ago -- well inside the 900s TTL.
    """
    dead_actor = _unique("dead-lane-")
    adder = WorkTrackerSession({"actor": _unique("adder")})
    added = await adder.add(project, "work a dead lane was holding", acceptance="n/a")
    assert added.success is True
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": dead_actor})
    bd = session._project(project)  # noqa: SLF001 -- test-only reach, as elsewhere in this suite
    bd.claim_item(item_id, actor=dead_actor)
    bd.take_custody(item_id, holder=dead_actor, pid=_a_genuinely_dead_pid(), host=HOST)
    _rewind_custody(bd, item_id, seconds_ago=SILENCE_INSIDE_TTL)
    return item_id, dead_actor, bd


@pytest.mark.asyncio
async def test_successor_work_claim_is_refused_by_name_before_the_reclaim(project):
    """The measured symptom, reproduced at the seam: four attempts, four
    refusals, each naming an agent id whose process no longer exists.
    """
    item_id, dead_actor, _bd = await _item_held_by_a_dead_lane(project)

    successor = WorkTrackerSession({"actor": _unique("successor")})
    for _attempt in range(2):
        refused = await successor.claim(project, item_id=item_id)
        assert refused.success is False
        assert dead_actor in str(refused.output)


@pytest.mark.asyncio
async def test_successor_work_claim_succeeds_after_the_sweep_reclaims(project):
    """THE deliverable. One real sweep at the real default TTL, and the
    relaunched lane is working again -- no `unclaim`, no operator.
    """
    item_id, _dead_actor, bd = await _item_held_by_a_dead_lane(project)

    reaped = SV.reap_project(bd)  # default TTL -- no override
    assert reaped["reclaimed_count"] == 1, reaped
    assert "holder process is dead" in reaped["reclaimed"][0]["reason"]

    successor = WorkTrackerSession({"actor": _unique("successor")})
    claimed = await successor.claim(project, item_id=item_id)
    assert claimed.success is True
    assert claimed.output["claimed"] == item_id  # type: ignore[index]

    # And it is a REAL claim, with its own live custody -- not a half state.
    rec = bd.get(item_id).meta[C.CUSTODY_KEY]
    assert rec["holder"] == successor._actor  # noqa: SLF001
    assert C.reclaim_eligible(rec)[0] is False


@pytest.mark.asyncio
async def test_the_successor_can_then_resolve_the_item_it_reclaimed(project):
    """The incident's lane could not reach ANY terminal state. Once the
    reclaim happens the whole loop is available again, which is what makes a
    relaunched lane able to finish (or honestly release) its own work.
    """
    item_id, _dead_actor, bd = await _item_held_by_a_dead_lane(project)
    assert SV.reap_project(bd)["reclaimed_count"] == 1

    successor = WorkTrackerSession({"actor": _unique("successor")})
    assert (await successor.claim(project, item_id=item_id)).success is True
    resolved = await successor.resolve(item_id, "finished the work the dead lane started")
    assert resolved.success is True
    assert bd.get(item_id).status == "resolved"


@pytest.mark.asyncio
async def test_a_live_sessions_hold_survives_the_same_sweep(project):
    """The safety property at the seam: a session that is genuinely running
    -- this test process -- holds an item with the SAME silence against the
    SAME TTL, and the sweep must leave it strictly alone. Without this, the
    fix above would be indistinguishable from "reap everything sooner".
    """
    adder = WorkTrackerSession({"actor": _unique("adder")})
    added = await adder.add(project, "work a LIVE lane is holding", acceptance="n/a")
    item_id = added.output["added"]  # type: ignore[index]

    live = WorkTrackerSession({"actor": _unique("live-lane")})
    claimed = await live.claim(project, item_id=item_id)
    assert claimed.success is True

    bd = live._project(project)  # noqa: SLF001
    _rewind_custody(bd, item_id, seconds_ago=SILENCE_INSIDE_TTL)

    assert SV.reap_project(bd)["reclaimed_count"] == 0
    assert bd.get(item_id).status == "held"
    # The live session is still able to close its own work.
    assert (await live.resolve(item_id, "still mine, still working")).success is True
