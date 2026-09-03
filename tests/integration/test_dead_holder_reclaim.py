"""Tier 2 -- a hold whose holder PROCESS IS DEAD is reclaimed automatically,
end to end, against real `bd` and a real dolt server (`model_performance-oy4`).

The unit tier (`tests/unit/test_custody_dead_holder.py`) pins the decision
and its three fences with an injected probe. This file pins the whole chain
with the REAL probe against a REAL exited process: custody record -> the
`held_stale` a reporting caller sees -> the sweep that acts on it -> and the
property that actually unblocks a relaunched lane, which is that its
successor can then claim the item instead of being refused indefinitely with
"already claimed by <dead agent id>".

Every "dead" pid here belongs to a subprocess this test started and reaped,
so the death is real rather than a number chosen for looking implausible.

Also pinned here, both found while root-causing oy4 and both silent misses
in the reaper itself:

  - `reap_project` used bd's DEFAULT list page (50 items, ordered
    `priority ASC, created_at DESC, id ASC`). A held item outside that page
    was invisible to the reaper permanently, and nothing reported the skip.
  - one item whose `release` raised aborted the reap of every remaining
    held item in that project -- deterministically, on every sweep, forever,
    while the sweep still reported itself completed.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C
from amplifier_work_tracker import supervisor as SV

pytestmark = pytest.mark.integration

HOST = socket.gethostname()

#: Silence used for every "dead holder" case below: comfortably past the
#: corroboration window (240s) and comfortably INSIDE the 900s TTL, so a
#: reclaim here can only have come from the liveness path -- never from
#: ordinary staleness. This gap is the whole point: before this change the
#: item sat unclaimable for the remaining ~10 minutes of its TTL plus up to
#: a full sweep interval on top.
SILENCE_INSIDE_TTL = 400


def _a_genuinely_dead_pid() -> int:
    """A pid that really did exist and really has exited. `wait()` reaps it,
    so it is not a zombie still addressable by `os.kill(pid, 0)`.
    """
    p = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    p.wait()
    assert not C.pid_alive(p.pid), (
        f"pid {p.pid} is still addressable after wait() -- the OS recycled it "
        f"mid-test; rerun (this is the documented pid-reuse imprecision, and it "
        f"errs toward NOT reclaiming)"
    )
    return p.pid


def _rewind_custody(bd: A.Beads, item_id: str, *, seconds_ago: int) -> dict:
    """Age an existing custody record's `last_seen` without sleeping. Writes
    through bd's own metadata merge, so the record read back is the one a
    real renewal would have left behind `seconds_ago` seconds ago.
    """
    rec = dict(bd.get(item_id).meta[C.CUSTODY_KEY])
    rec["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))
    bd._run(  # noqa: SLF001 -- deliberate: forging a past renewal is not a public verb
        ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: rec})],
        actor=rec["holder"],
    )
    return bd.get(item_id).meta[C.CUSTODY_KEY]


def _held_by_a_dead_holder(bd: A.Beads, *, title: str, actor: str, priority: int = 1) -> str:
    item_id = bd.create(title, priority=priority)
    bd.claim_item(item_id, actor=actor)
    bd.take_custody(item_id, holder=actor, pid=_a_genuinely_dead_pid(), host=HOST)
    _rewind_custody(bd, item_id, seconds_ago=SILENCE_INSIDE_TTL)
    return item_id


# --------------------------------------------------------------------------
# The flagship: dead holder -> stale -> reclaimed -> successor claims.
# --------------------------------------------------------------------------


def test_dead_holders_hold_is_reported_stale_inside_the_ttl(workspace, project_factory):
    """`work_stats`/`work_status` must SEE it. During the oy4 incident this
    field read `held_stale: 0` with a `held_stale_oldest_age_seconds: null`
    beside it, which is what told the successor session there was nothing to
    wait for.
    """
    name, bd = project_factory("deadhold")
    _held_by_a_dead_holder(bd, title="dead holder: reported stale", actor="dead-agent")

    summary = A.project_summary(workspace, name)
    assert summary.held == 1
    assert summary.held_stale == 1, (
        "a hold whose holder process is gone must be reported stale before its "
        "TTL expires -- otherwise a successor session has no signal at all"
    )
    assert summary.held_stale_oldest_age_seconds is not None
    assert summary.held_stale_oldest_age_seconds >= SILENCE_INSIDE_TTL - 60
    # And it is genuinely INSIDE the TTL -- so this is the liveness path,
    # not staleness arriving early.
    assert summary.held_stale_oldest_age_seconds < C.CUSTODY_TTL_SECONDS


def test_the_sweep_reclaims_a_dead_holders_hold_with_the_default_ttl(project_factory):
    """The real sweep entry point, with NO ttl override -- exactly what the
    background service calls every `DEFAULT_REAP_INTERVAL_SECONDS`.
    """
    _name, bd = project_factory("deadhold")
    item_id = _held_by_a_dead_holder(bd, title="dead holder: reaped", actor="dead-agent")

    result = SV.reap_project(bd)

    assert result["reclaimed_count"] == 1, result
    assert result["reclaimed"][0]["id"] == item_id
    assert result["reclaimed"][0]["was_holder"] == "dead-agent"
    assert "holder process is dead" in result["reclaimed"][0]["reason"]
    assert result["failed_count"] == 0

    after = bd.get(item_id)
    assert after.status == "open"
    assert after.holder is None


def test_a_successor_session_can_claim_the_item_after_the_reclaim(project_factory):
    """THE property that actually unblocks a relaunched lane. In the measured
    incident the successor could not `work_claim` (held by a dead agent),
    could not `work_release` (it did not hold it) and could not `work_file`
    (filing requires holding an item) -- so it could do nothing but wait for
    a human-equivalent intervention.
    """
    _name, bd = project_factory("deadhold")
    item_id = _held_by_a_dead_holder(bd, title="dead holder: successor", actor="dead-agent")

    # Before the reclaim, the successor is refused -- and refused by NAME,
    # which is the message the incident reported four times.
    with pytest.raises(A.BeadsError) as refused:
        bd.claim_item(item_id, actor="successor-agent")
    assert "dead-agent" in str(refused.value)

    assert SV.reap_project(bd)["reclaimed_count"] == 1

    back = bd.claim_item(item_id, actor="successor-agent")
    assert back.status == "held"
    assert back.holder == "successor-agent"


def test_a_live_holder_inside_the_ttl_is_never_reclaimed(project_factory):
    """The safety property, with the REAL probe: this test's own process is
    alive, so an identically-silent hold naming it must survive the sweep.
    Same silence, same TTL, same code path -- only liveness differs.
    """
    _name, bd = project_factory("livehold")
    item_id = bd.create("live holder must survive", priority=1)
    bd.claim_item(item_id, actor="live-agent")
    bd.take_custody(item_id, holder="live-agent", pid=__import__("os").getpid(), host=HOST)
    _rewind_custody(bd, item_id, seconds_ago=SILENCE_INSIDE_TTL)

    result = SV.reap_project(bd)

    assert result["reclaimed_count"] == 0, result
    assert bd.get(item_id).status == "held"
    assert bd.get(item_id).holder == "live-agent"


def test_a_holder_recorded_on_another_host_is_never_reclaimed(project_factory):
    """A dead pid number means nothing across machines: the same number may
    well be a live process here. Unknowable resolves to "leave it alone",
    and the TTL still covers it in the end.
    """
    _name, bd = project_factory("remotehold")
    item_id = bd.create("remote holder must survive", priority=1)
    bd.claim_item(item_id, actor="remote-agent")
    bd.take_custody(
        item_id, holder="remote-agent", pid=_a_genuinely_dead_pid(), host="some-other-box"
    )
    _rewind_custody(bd, item_id, seconds_ago=SILENCE_INSIDE_TTL)

    assert SV.reap_project(bd)["reclaimed_count"] == 0
    assert bd.get(item_id).status == "held"


# --------------------------------------------------------------------------
# Two silent misses in the reaper itself, found while root-causing oy4.
# --------------------------------------------------------------------------


def test_the_reaper_does_not_depend_on_bds_default_list_page(project_factory, monkeypatch):
    """`reap_project` used to read `bd.list(include_resolved=False)`, which
    applies bd's own default cap (`LIST_DEFAULT_LIMIT`, 50) ordered
    `priority ASC, created_at DESC, id ASC`. A held item outside that first
    page was invisible to the reaper permanently -- silently, with nothing
    anywhere reporting it had been skipped.

    The page size is shrunk here rather than creating 51 real items: it is
    the same constant, read by the same call, so this exercises the actual
    mechanism at a fraction of the cost. The stale hold is given the WORST
    priority so it sorts off the end of the page.
    """
    _name, bd = project_factory("pagedreap")
    item_id = _held_by_a_dead_holder(
        bd, title="stale hold, worst priority", actor="dead-agent", priority=4
    )
    for n in range(3):
        bd.create(f"filler {n}", priority=0)

    monkeypatch.setattr(A, "LIST_DEFAULT_LIMIT", 2)

    # FAIL-BEFORE, made explicit: the old read genuinely cannot see it.
    off_page = bd.list(include_resolved=False)
    assert item_id not in {i.id for i in off_page}, (
        "test setup is wrong -- the stale hold must be off the first page for "
        "this regression to mean anything"
    )

    assert SV.reap_project(bd)["reclaimed_count"] == 1
    assert bd.get(item_id).status == "open"


def test_one_unreleasable_item_does_not_shadow_the_rest_of_the_queue(project_factory, monkeypatch):
    """Before this, the loop in `reap_project` had no per-item guard: the
    first `release` that raised propagated out, `reap_sweep` caught it per
    project, and every remaining stale hold in that project went unreaped --
    on that sweep and on every sweep after it, since the failure is
    deterministic. The sweep still recorded itself completed.
    """
    _name, bd = project_factory("wedgedreap")
    wedged = _held_by_a_dead_holder(bd, title="wedged hold", actor="dead-agent-a")
    other = _held_by_a_dead_holder(bd, title="second stale hold", actor="dead-agent-b")

    real_release = A.Beads.release

    def _release(self, item_id):
        if item_id == wedged:
            raise A.BeadsError("simulated wedged release")
        return real_release(self, item_id)

    monkeypatch.setattr(A.Beads, "release", _release)

    result = SV.reap_project(bd)

    assert result["reclaimed_count"] == 1
    assert result["reclaimed"][0]["id"] == other
    assert result["failed_count"] == 1
    assert result["failed"][0]["id"] == wedged
    assert "simulated wedged release" in result["failed"][0]["error"]
    # The healthy item really was freed, not merely reported.
    assert bd.get(other).status == "open"
    # And the failure is visible to the sweep-level reporting the
    # `sweeps.reclaiming` doctor check reads -- never swallowed.
    assert SV.sweep_failures({"wedgedreap": result}) == ["wedgedreap"]
