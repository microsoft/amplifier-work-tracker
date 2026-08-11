"""Tier 2 -- `Beads.claim_item`: the directed (claim-by-id) counterpart to
`claim_next`. Every outcome it can produce, proven against the real `bd`
binary: success (custody-ready, same as the queue path), already-held-by-
someone-else (names the holder), not-found (distinct from held), and
blocked-by-an-open-dependency (our own refusal -- bd itself is NOT
blocker-aware on this path, measured empirically; see adapter.claim_item's
docstring).

Uses the shared session project (`shared_bd`) with a unique lane per test,
same isolation model as test_roundtrip.py.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_claim_item_succeeds_on_a_free_item(shared_bd: A.Beads, unique_lane, unique_actor):
    item_id = shared_bd.create(
        "directed claim probe: free item",
        tags=[unique_lane],
        acceptance="Given/When/Then",
        priority=1,
    )

    claimed = shared_bd.claim_item(item_id, actor=unique_actor)
    assert claimed.id == item_id
    assert claimed.holder == unique_actor
    assert claimed.status == "held"
    assert claimed.acceptance == "Given/When/Then"

    # Same custody path as the queue claim: take_custody must accept it.
    rec = shared_bd.take_custody(item_id, holder=unique_actor, pid=1, host="test-host")
    assert rec["holder"] == unique_actor
    assert rec["generation"] == 1


def test_claim_item_is_idempotent_for_the_same_actor(shared_bd: A.Beads, unique_lane, unique_actor):
    """Matches bd's own documented behavior (`bd update --help`: "idempotent
    if already claimed by you") -- re-claiming your own held item succeeds,
    it does not raise."""
    item_id = shared_bd.create("directed claim probe: idempotent", tags=[unique_lane], priority=1)
    first = shared_bd.claim_item(item_id, actor=unique_actor)
    second = shared_bd.claim_item(item_id, actor=unique_actor)
    assert first.id == second.id == item_id
    assert second.holder == unique_actor


def test_claim_item_refuses_when_already_held_by_someone_else(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    item_id = shared_bd.create("directed claim probe: already held", tags=[unique_lane], priority=1)
    other_actor = f"other-{unique_actor}"
    shared_bd.claim_item(item_id, actor=other_actor)

    with pytest.raises(A.BeadsError) as exc:
        shared_bd.claim_item(item_id, actor=unique_actor)
    # Names the REAL holder, using bd's own message -- not a reinvented one.
    assert other_actor in str(exc.value)


def test_claim_item_refuses_on_nonexistent_id(shared_bd: A.Beads, unique_actor):
    with pytest.raises(A.BeadsError) as exc:
        shared_bd.claim_item("definitely-not-a-real-id-12345", actor=unique_actor)
    # Distinct wording from the "already held" case -- a caller (or a human
    # reading the error) must be able to tell the two apart at a glance.
    assert "not found" in str(exc.value)
    assert "already" not in str(exc.value)


def test_claim_item_refuses_when_blocked_by_an_open_dependency(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    """bd's directed-claim primitive is NOT blocker-aware on its own
    (measured: `bd update <id> --claim` claims a blocked item exactly as
    readily as a free one) -- this refusal is ours, checked before ever
    calling bd's --claim."""
    blocker_id = shared_bd.create("directed claim probe: blocker", tags=[unique_lane], priority=1)
    blocked_id = shared_bd.create("directed claim probe: blocked", tags=[unique_lane], priority=1)
    r = shared_bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001 -- test setup only
    assert r.returncode == 0, r.stderr

    with pytest.raises(A.BeadsError) as exc:
        shared_bd.claim_item(blocked_id, actor=unique_actor)
    assert blocker_id in str(exc.value)
    assert "blocked" in str(exc.value).lower()

    # And it must NOT have been claimed -- the refusal happens before bd's
    # --claim is ever invoked.
    back = shared_bd.get(blocked_id)
    assert back.status == "open"
    assert back.holder is None


def test_claim_item_succeeds_once_the_blocker_is_closed(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    """The other half of the blocker check: once the blocker resolves, the
    same item that was refused a moment ago must now be claimable."""
    blocker_id = shared_bd.create(
        "directed claim probe: blocker (to be closed)", tags=[unique_lane], priority=1
    )
    blocked_id = shared_bd.create(
        "directed claim probe: blocked (to become free)", tags=[unique_lane], priority=1
    )
    r = shared_bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001
    assert r.returncode == 0, r.stderr

    with pytest.raises(A.BeadsError):
        shared_bd.claim_item(blocked_id, actor=unique_actor)

    shared_bd.resolve(blocker_id, "blocker resolved for test")
    claimed = shared_bd.claim_item(blocked_id, actor=unique_actor)
    assert claimed.id == blocked_id
    assert claimed.holder == unique_actor


def test_claim_next_queue_path_is_unaffected_by_claim_item_existing(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    """Regression guard: adding `claim_item` must not change `claim_next`'s
    behavior at all -- same queue semantics, same None-on-empty-lane."""
    item_id = shared_bd.create("queue-path regression probe", tags=[unique_lane], priority=1)
    claimed = shared_bd.claim_next(lane=unique_lane, actor=unique_actor)
    assert claimed is not None
    assert claimed.id == item_id
    assert claimed.holder == unique_actor
    assert claimed.status == "held"
    # Queue is now empty for this lane.
    assert shared_bd.claim_next(lane=unique_lane, actor=unique_actor) is None
