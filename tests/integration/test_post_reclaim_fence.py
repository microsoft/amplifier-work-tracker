"""Tier 2 -- Core 7 of `contracts/custody-coordination.v1.md`: a close is
fenced against a stale holder in EVERY post-reclaim state, including the
released-but-not-yet-re-claimed one (conformance ledger row CCV1-009,
work item `pipeline-dn4`).

The gap this file discriminates: `Beads.resolve`'s custody fence used to run
only under `if current.status == "held"`. A reap does NOT leave the item
`held` -- `supervisor.reap_project` calls `Beads.release`, which sets the
item back to `open` and clears bd's own assignee, while deliberately leaving
the custody record in metadata still naming the old holder. So the one state
the fence exists for -- "my claim was taken away while I was idle" -- was
precisely the state the fence skipped, and the stale holder's close landed
with exit 0 and no refusal anywhere.

BOTH halves are pinned here, because the two are easy to trade against each
other and the fix is only correct if it keeps both:

  - the STALE HOLDER's close of a reclaimed item is refused (the fence), and
  - an INTEGRATOR's close of that same unheld item still succeeds in a
    single call, no fence, no override (PR #51, work item `pipeline-79t`).

The discriminator between the two is the custody record's `holder`, not the
item's status: only the session the custody record still names is refused.
Everyone else is exactly as unfenced as they were before.

See also `test_resolve_fence.py`, which pins the integrator half against
a *manual* release; this file drives the REAL reap sweep as well, so the
released-but-not-re-claimed state is produced by the code that actually
produces it in production rather than by a test's imitation of it.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import supervisor as SV

pytestmark = pytest.mark.integration


def _custody_holder(bd: A.Beads, item_id: str) -> str | None:
    rec = bd.get(item_id).meta.get(A.C.CUSTODY_KEY)
    return rec.get("holder") if isinstance(rec, dict) else None


# --------------------------------------------------------------------------
# The fence half -- the stale holder is refused in the post-reclaim state.
# --------------------------------------------------------------------------


def test_stale_holder_close_is_refused_after_a_real_reap(project_factory):
    """The flagship case, driven through the REAL sweep.

    Claim -> take custody -> `supervisor.reap_project(ttl_seconds=0)` (every
    hold is instantly stale, so no real sleep is needed) -> the reclaimed
    holder tries to close. The item is `open` with no assignee and a custody
    record still naming the stale holder: the exact shape that used to skip
    the fence entirely.

    Its own project, not `shared_bd`, because `reap_project` sweeps a whole
    project -- pointed at the session-shared one it could reclaim another
    test's live hold.
    """
    _name, bd = project_factory("reapfence")
    item_id = bd.create("post-reclaim fence probe: real reap", priority=1)
    bd.claim_item(item_id, actor="stale-holder")
    bd.take_custody(item_id, holder="stale-holder", pid=1, host="test-host")

    reaped = SV.reap_project(bd, ttl_seconds=0)
    assert reaped["reclaimed_count"] == 1
    assert reaped["reclaimed"][0]["id"] == item_id

    # The state under test: released, not yet re-claimed, custody record left
    # in place naming the holder that no longer holds anything.
    after = bd.get(item_id)
    assert after.status == "open"
    assert after.holder is None
    assert _custody_holder(bd, item_id) == "stale-holder"

    with pytest.raises(A.FencedError) as exc:
        bd.resolve(
            item_id, "closing work that was reclaimed while I was away", actor="stale-holder"
        )
    message = str(exc.value).lower()
    assert "not held by this session" in message
    assert "reclaim" in message

    # The refusal must not have closed it anyway.
    assert bd.get(item_id).status == "open"


def test_stale_holder_close_is_refused_after_release_without_reclaim(shared_bd, unique_lane):
    """Same refusal, reached by the exact single call the reap sweep makes
    (`Beads.release` -- see `supervisor.reap_project`), so the fence is
    proven against the state itself rather than against one caller of it.
    A voluntary hand-back lands in the identical state and is likewise
    refused: after a release this session does not hold the item, and the
    two are indistinguishable by construction (a release records no reason
    for why it happened -- see `adapter.agent_stats`'s own docstring).
    """
    item_id = shared_bd.create("post-reclaim fence probe: released", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor="released-holder")
    shared_bd.take_custody(item_id, holder="released-holder", pid=1, host="test-host")
    shared_bd.release(item_id)

    with pytest.raises(A.FencedError) as exc:
        shared_bd.resolve(item_id, "closing after my hold ended", actor="released-holder")
    assert "released-holder" in str(exc.value)
    assert shared_bd.get(item_id).status == "open"


# --------------------------------------------------------------------------
# The integrator half -- PR #51's use case must keep working, unchanged.
# --------------------------------------------------------------------------


def test_integrator_close_of_a_reclaimed_item_still_succeeds(project_factory):
    """PR #51 (`pipeline-79t`): resolving an item nobody currently holds is
    a single call for anyone who is not the stale holder -- including after
    a real reap, which is when unfinished reports most need closing out.
    """
    _name, bd = project_factory("intfence")
    item_id = bd.create("post-reclaim fence probe: integrator", priority=1)
    bd.claim_item(item_id, actor="stale-holder")
    bd.take_custody(item_id, holder="stale-holder", pid=1, host="test-host")

    assert SV.reap_project(bd, ttl_seconds=0)["reclaimed_count"] == 1
    assert _custody_holder(bd, item_id) == "stale-holder"

    back = bd.resolve(item_id, "closed out by the integrator", actor="integrator")
    assert back.status == "resolved"


def test_current_holder_can_still_close_the_item_it_actually_holds(shared_bd, unique_lane):
    """The fence must never refuse the legitimate holder: claim, take
    custody, close -- one call, no fence, custody record naming this very
    session notwithstanding.
    """
    item_id = shared_bd.create(
        "post-reclaim fence probe: live holder", tags=[unique_lane], priority=1
    )
    shared_bd.claim_item(item_id, actor="live-holder")
    shared_bd.take_custody(item_id, holder="live-holder", pid=1, host="test-host")

    back = shared_bd.resolve(item_id, "finished the work I actually hold", actor="live-holder")
    assert back.status == "resolved"


def test_fence_does_not_fire_on_a_close_this_holder_already_landed(shared_bd, unique_lane):
    """Regression guard for the phantom-conflict recovery path (PR #63): a
    holder whose close ALREADY landed may re-attempt it -- that item is
    `resolved`, not `held`, and its custody record still names this very
    session. The new post-reclaim fence must not mistake "I already closed
    this" for "my claim was taken away", or a wedged session could never
    confirm its own landed close. bd itself may or may not accept a second
    close of a closed item; either is fine, a `FencedError` is not.
    """
    item_id = shared_bd.create("post-reclaim fence probe: rewrite", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor="retrying-holder")
    shared_bd.take_custody(item_id, holder="retrying-holder", pid=1, host="test-host")
    assert shared_bd.resolve(item_id, "landed the first time", actor="retrying-holder").status == (
        "resolved"
    )

    try:
        shared_bd.resolve(item_id, "landed the first time", actor="retrying-holder")
    except A.FencedError as e:  # pragma: no cover - only reached on regression
        pytest.fail(f"a holder's re-close of its own landed close was fenced: {e}")
    except A.BeadsError:
        pass  # bd declining to re-close an already-closed item is not a fence
    assert shared_bd.get(item_id).status == "resolved"
