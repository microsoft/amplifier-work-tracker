"""Tier 2 -- `Beads.defer`/`undefer`/`block`/`unblock`, against the real `bd`
binary and a real (isolated) shared dolt server.

Both set the item's own top-level `status` to a raw bd value `_STATUS_MAP`
already recognizes (`deferred`/`blocked`) -- which is what makes bd's own
status-category system exclude the item from `bd ready` (and therefore
`claim_next`), while an explicit status filter still shows it, reason
attached.

THE SECOND HALF OF THIS FILE IS A REGRESSION FENCE (model_performance-2nx).
Measured against the parent commit, bd 1.1.2, 2026-09-03: `defer` (and
`block`) on an ALREADY-RESOLVED item exited 0, moved it out of resolved, and
BLANKED its stored resolution -- destroying the official, already-published
record with no warning, no confirmation, no archive and no trace of what it
used to say. The remaining verbs (`--clear` -> `claim` -> `resolve`) then
rewrote that record end to end using nothing but sanctioned calls, which is
how two prior lanes' "a closed resolution is unwritable through every
sanctioned path" claim was false.

The tests below assert BOTH doors, deliberately in one file:

  * the UNSAFE one is closed  -- defer/block refuse, and (the property that
    actually protects a record) the stored resolution is unchanged;
  * the SAFE one is still open -- `reopen` still succeeds on the same item
    and still archives the previous resolution + closed_at FIRST.

A guard that shut both would be a regression of its own.
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


# --------------------------------------------------------------------------
# model_performance-2nx -- the unsafe door: defer/block on a RESOLVED item.
# --------------------------------------------------------------------------

ORIGINAL = "ORIGINAL TEXT -- the official, already-published resolution"


def _resolved(bd: A.Beads, lane: str, title: str) -> str:
    """A freshly created, RESOLVED item carrying `ORIGINAL` as its official
    record -- exactly the state the destructive loop starts from."""
    item_id = bd.create(title, tags=[lane], priority=1)
    bd.claim_item(item_id, actor="closer")
    bd.resolve(item_id, ORIGINAL, actor="closer")
    assert bd.get(item_id).resolution == ORIGINAL
    return item_id


@pytest.mark.parametrize("verb", ["defer", "block"])
def test_defer_block_on_a_resolved_item_refuse_and_the_resolution_survives(
    shared_bd: A.Beads, unique_lane, verb: str
):
    """All four properties of the refusal, in one test, for BOTH verbs.

    Property 3 -- "resolution unchanged" -- is the one that actually
    matters and the one no other assertion implies: the measured defect is
    a call that CHANGES the record, so a guard that raised AFTER writing
    would satisfy 1, 2 and 4 and still have destroyed the text.
    """
    item_id = _resolved(shared_bd, unique_lane, f"2nx probe: {verb} on resolved")

    with pytest.raises(A.BeadsError) as exc:
        getattr(shared_bd, verb)(item_id, "probe: should never land", actor="prober")

    # (1) it FAILED -- the call raised rather than reporting success.
    message = str(exc.value)
    # (2) the item is still resolved.
    back = shared_bd.get(item_id)
    assert back.status == "resolved", f"{verb} moved a resolved item to {back.status!r}"
    # (3) THE ONE THAT MATTERS: its resolution is byte-for-byte unchanged.
    assert back.resolution == ORIGINAL, (
        f"{verb} refused but the official record changed anyway ({back.resolution!r}) "
        f"-- 'NOTHING WAS WRITTEN' is not true"
    )
    assert back.closed_at is not None
    # (4) the message names the item, its status, and the `reopen` remedy.
    assert item_id in message
    assert "resolved" in message
    assert "reopen" in message
    assert "NOTHING WAS WRITTEN" in message
    # And it shows the caller the text that was at risk, so they can judge
    # whether they meant to destroy it.
    assert ORIGINAL in message


def test_the_destructive_loop_now_stops_at_its_first_verb(shared_bd: A.Beads, unique_lane):
    """The item's own measurement, replayed: resolve -> defer -> block ->
    `--clear` -> claim -> resolve. Before the guard every step exited 0 and
    the record was rewritten. Now it stops at step one, and every later verb
    finds nothing to work with because the item never left `resolved`."""
    item_id = _resolved(shared_bd, unique_lane, "2nx probe: the whole loop")

    with pytest.raises(A.BeadsError):
        shared_bd.defer(item_id, "probe")
    with pytest.raises(A.BeadsError):
        shared_bd.block(item_id, "probe")
    # `--clear` has nothing to clear: the item is resolved, not blocked.
    with pytest.raises(A.BeadsError):
        shared_bd.unblock(item_id)
    with pytest.raises(A.BeadsError):
        shared_bd.undefer(item_id)

    back = shared_bd.get(item_id)
    assert back.status == "resolved"
    assert back.resolution == ORIGINAL


def test_reopen_still_succeeds_on_the_same_item_and_still_archives_first(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    """The SAFE door stays open. Closing the unsafe path must not close the
    sanctioned one -- and `reopen`'s archive-first guarantee (the whole
    reason it is the sanctioned one) must still hold on an item that
    `defer`/`block` have just been refused on."""
    item_id = _resolved(shared_bd, unique_lane, "2nx probe: safe door")
    with pytest.raises(A.BeadsError):
        shared_bd.defer(item_id, "probe")

    outcome = shared_bd.reopen(item_id, "the stored text is wrong", actor=unique_actor)

    assert outcome.item.status != "resolved"
    assert outcome.previous_resolution == ORIGINAL
    assert outcome.previous_closed_at is not None
    # ARCHIVED, verbatim, in the item's attributed comment history -- the
    # promise that makes a reopen a correction rather than a deletion.
    archived = [e.detail or e.summary for e in shared_bd.activity(item_id) if e.kind == "comment"]
    assert any(ORIGINAL in (a or "") for a in archived), archived
    # And the item is genuinely back in the queue: claimable, correctable.
    taken = shared_bd.claim_item(item_id, actor=unique_actor)
    assert taken.id == item_id
    corrected = shared_bd.resolve(item_id, "CORRECTED TEXT", actor=unique_actor)
    assert corrected.resolution == "CORRECTED TEXT"


# --------------------------------------------------------------------------
# ... and the ordinary workflow every lane uses is UNTOUCHED. A guard that
# refused too much would break defer/block for their actual purpose, which is
# a worse outcome than the defect it fixes.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["defer", "block"])
def test_defer_block_on_an_open_item_are_unaffected(shared_bd: A.Beads, unique_lane, verb: str):
    item_id = shared_bd.create(f"2nx probe: open {verb}", tags=[unique_lane], priority=1)
    back = getattr(shared_bd, verb)(item_id, "a perfectly ordinary reason", actor="prober")
    assert back.status == ("deferred" if verb == "defer" else "blocked")


@pytest.mark.parametrize("verb", ["defer", "block"])
def test_defer_block_on_a_held_item_are_unaffected(
    shared_bd: A.Beads, unique_lane, unique_actor, verb: str
):
    item_id = shared_bd.create(f"2nx probe: held {verb}", tags=[unique_lane], priority=1)
    shared_bd.claim_item(item_id, actor=unique_actor)
    assert shared_bd.get(item_id).status == "held"

    back = getattr(shared_bd, verb)(item_id, "paused mid-flight", actor=unique_actor)
    assert back.status == ("deferred" if verb == "defer" else "blocked")


@pytest.mark.parametrize("verb", ["defer", "block"])
def test_defer_block_on_an_already_deferred_or_blocked_item_are_unaffected(
    shared_bd: A.Beads, unique_lane, verb: str
):
    """Re-stating a non-resolved status, and crossing between the two
    non-resolved ones, both still work exactly as they did."""
    item_id = shared_bd.create(f"2nx probe: restate {verb}", tags=[unique_lane], priority=1)
    shared_bd.defer(item_id, "first", actor="prober")
    assert shared_bd.get(item_id).status == "deferred"

    back = getattr(shared_bd, verb)(item_id, "second", actor="prober")
    assert back.status == ("deferred" if verb == "defer" else "blocked")
