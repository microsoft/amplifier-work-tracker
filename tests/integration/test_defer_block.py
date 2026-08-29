"""Tier 2 -- `Beads.defer`/`undefer`/`block`/`unblock`, against the real `bd`
binary and a real (isolated) shared dolt server.

Both set the item's own top-level `status` to a raw bd value `_STATUS_MAP`
already recognizes (`deferred`/`blocked`) -- which is what makes bd's own
status-category system exclude the item from `bd ready` (and therefore
`claim_next`), while an explicit status filter still shows it, reason
attached.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_defer_moves_status_and_stores_reason(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("defer probe: basic", tags=[unique_lane], priority=1)

    back = shared_bd.defer(item_id, "waiting on upstream design review", actor="deferrer")

    assert back.status == "deferred"
    assert back.meta.get(A.Beads._DEFER_REASON_KEY) == "waiting on upstream design review"  # noqa: SLF001


def test_deferred_item_stays_visible_in_default_list_and_by_explicit_status(
    shared_bd: A.Beads, unique_lane
):
    """`list()`'s own default view only ever excludes `closed` (see its
    docstring) -- deferred/blocked items remain visible there, AND via an
    explicit status filter. Only `bd ready`/`claim_next` skip them (see
    `test_deferred_item_is_skipped_by_claim_next`, below)."""
    item_id = shared_bd.create("defer probe: visibility", tags=[unique_lane], priority=1)
    shared_bd.defer(item_id, "not now", actor="deferrer")

    default_ids = {i.id for i in shared_bd.list(lane=unique_lane)}
    assert item_id in default_ids

    deferred_ids = {i.id for i in shared_bd.list(lane=unique_lane, status="deferred")}
    assert item_id in deferred_ids


def test_deferred_item_is_skipped_by_claim_next(shared_bd: A.Beads, unique_lane, unique_actor):
    item_id = shared_bd.create("defer probe: claim_next skip", tags=[unique_lane], priority=0)
    shared_bd.defer(item_id, "not ready yet", actor="deferrer")

    claimed = shared_bd.claim_next(lane=unique_lane, actor=unique_actor)
    assert claimed is None or claimed.id != item_id


def test_undefer_moves_item_back_to_open_and_clears_reason(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("defer probe: undefer", tags=[unique_lane], priority=1)
    shared_bd.defer(item_id, "temporary", actor="deferrer")

    back = shared_bd.undefer(item_id, actor="undeferrer")

    assert back.status == "open"
    assert not back.meta.get(A.Beads._DEFER_REASON_KEY)  # noqa: SLF001


def test_undefer_refuses_when_not_deferred(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("defer probe: not deferred", tags=[unique_lane])
    with pytest.raises(A.BeadsError) as exc:
        shared_bd.undefer(item_id)
    assert "not" in str(exc.value).lower()


def test_defer_refuses_without_a_reason(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("defer probe: no reason", tags=[unique_lane])
    with pytest.raises(A.BeadsError):
        shared_bd.defer(item_id, "")


def test_block_moves_status_and_stores_reason(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("block probe: basic", tags=[unique_lane], priority=1)

    back = shared_bd.block(item_id, "needs a security review first", actor="blocker")

    assert back.status == "blocked"
    assert back.meta.get(A.Beads._BLOCK_REASON_KEY) == "needs a security review first"  # noqa: SLF001


def test_blocked_item_is_skipped_by_claim_next(shared_bd: A.Beads, unique_lane, unique_actor):
    item_id = shared_bd.create("block probe: claim_next skip", tags=[unique_lane], priority=0)
    shared_bd.block(item_id, "waiting on a decision", actor="blocker")

    claimed = shared_bd.claim_next(lane=unique_lane, actor=unique_actor)
    assert claimed is None or claimed.id != item_id


def test_unblock_moves_item_back_to_open_and_clears_reason(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("block probe: unblock", tags=[unique_lane], priority=1)
    shared_bd.block(item_id, "temporary", actor="blocker")

    back = shared_bd.unblock(item_id, actor="unblocker")

    assert back.status == "open"
    assert not back.meta.get(A.Beads._BLOCK_REASON_KEY)  # noqa: SLF001


def test_unblock_refuses_when_not_blocked(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("block probe: not blocked", tags=[unique_lane])
    with pytest.raises(A.BeadsError):
        shared_bd.unblock(item_id)


def test_defer_and_block_reasons_never_collide(shared_bd: A.Beads, unique_lane):
    """Defer then block (moving through open in between) must never leave a
    stale reason from the OTHER status lingering in metadata."""
    item_id = shared_bd.create("defer/block probe: no collision", tags=[unique_lane])
    shared_bd.defer(item_id, "defer reason", actor="a")
    shared_bd.undefer(item_id, actor="a")
    back = shared_bd.block(item_id, "block reason", actor="a")
    assert back.meta.get(A.Beads._BLOCK_REASON_KEY) == "block reason"  # noqa: SLF001
    assert not back.meta.get(A.Beads._DEFER_REASON_KEY)  # noqa: SLF001
