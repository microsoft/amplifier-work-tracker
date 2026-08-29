"""Tier 2 -- `Beads.resolve`'s custody-based fence, gated on the item being
ACTUALLY currently held (work_tracker item 79t).

Before this fix, the fence fired on custody metadata ALONE, with no check
that the item was still `held` at all -- so a STALE custody record from a
hold that ended long ago (released, reaped, or simply never re-claimed)
kept naming a "current holder" who no longer held anything, refusing a
plain integrator resolve of someone else's already-unheld report. These
tests pin both halves of the fix: an unheld item resolves in a single call
regardless of stale custody metadata, and an ACTIVELY held item still
refuses, naming the real holder.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_resolve_succeeds_single_call_on_unheld_item_with_stale_custody(
    shared_bd: A.Beads, unique_lane
):
    """The exact regression: claim, take custody, release (clears bd's
    assignee but leaves the custody record in metadata pointing at the old
    holder) -- then a DIFFERENT actor resolves it. Must be a single call,
    no fence, since the item is not currently held by anyone.
    """
    item_id = shared_bd.create("resolve-fence probe: stale custody", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor="original-holder")
    shared_bd.take_custody(item_id, holder="original-holder", pid=1, host="test-host")
    shared_bd.release(item_id)

    # Sanity: the item really is unheld, but the stale custody record
    # survives the release (this is the condition that used to wrongly fence).
    unheld = shared_bd.get(item_id)
    assert unheld.status == "open"
    assert unheld.holder is None
    assert unheld.meta.get(A.C.CUSTODY_KEY, {}).get("holder") == "original-holder"

    back = shared_bd.resolve(item_id, "closed by a different session entirely", actor="integrator")
    assert back.status == "resolved"


def test_resolve_succeeds_on_item_filed_by_someone_else_never_held(shared_bd: A.Beads, unique_lane):
    """An item that was never claimed at all (no custody record ever
    written) resolves in a single call regardless of who filed it."""
    item_id = shared_bd.create(
        "resolve-fence probe: never held", tags=[unique_lane], actor="reporter"
    )
    back = shared_bd.resolve(item_id, "resolved without ever being claimed", actor="integrator")
    assert back.status == "resolved"


def test_resolve_still_refuses_and_names_holder_when_actively_held_by_someone_else(
    shared_bd: A.Beads, unique_lane
):
    """The other half of the fix: this refusal must NOT have been weakened.
    An item genuinely held right now by a live other session still fences,
    naming the real holder."""
    item_id = shared_bd.create("resolve-fence probe: actively held", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor="live-holder")

    with pytest.raises(A.FencedError) as exc:
        shared_bd.resolve(item_id, "trying to close someone else's held work", actor="intruder")
    assert "live-holder" in str(exc.value)

    # Untouched -- the refusal must not have closed it anyway.
    assert shared_bd.get(item_id).status == "held"
    shared_bd.release(item_id)


def test_resolve_still_refuses_with_custody_takeover_mismatch_while_held(
    shared_bd: A.Beads, unique_lane
):
    """A held item whose custody record names a DIFFERENT holder than bd's
    own current assignee (a takeover mid-flight) still fences -- this is
    the original custody-mismatch scenario the fence was built for, and it
    must survive gating on status=='held' unchanged."""
    item_id = shared_bd.create(
        "resolve-fence probe: custody mismatch while held", tags=[unique_lane], priority=1
    )
    shared_bd.claim_item(item_id, actor="holder-a")
    shared_bd.take_custody(item_id, holder="holder-a", pid=1, host="test-host")

    with pytest.raises(A.FencedError):
        shared_bd.resolve(item_id, "wrong actor entirely", actor="holder-b")

    assert shared_bd.get(item_id).status == "held"
    shared_bd.release(item_id)
