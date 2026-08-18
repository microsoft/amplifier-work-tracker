"""Tier 2 -- real `bd` round-trips for the item-detail blocker chain and
activity feed: `Beads.get(with_links=True)`'s enriched dependency/dependent
fields, and `Beads.activity`'s history+comments merge.

Uses the shared session project (`shared_bd`) with a unique lane per test,
same isolation model as test_roundtrip.py / test_directed_claim.py.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


# --------------------------------------------------- Beads.get -- blocker chain


def test_get_with_links_reports_full_blocker_detail(shared_bd: A.Beads, unique_lane, unique_actor):
    """The `from` direction (this item's own dependencies) must carry the
    FULL upstream item: title, our-vocabulary status, holder, reporter."""
    blocker_id = shared_bd.create("blocker chain probe: blocker", tags=[unique_lane])
    blocked_id = shared_bd.create("blocker chain probe: blocked", tags=[unique_lane])
    r = shared_bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001 -- test setup
    assert r.returncode == 0, r.stderr

    shared_bd.claim_item(blocker_id, actor=unique_actor)

    blocked = shared_bd.get(blocked_id, with_links=True)
    from_links = [ln for ln in blocked.links if ln["direction"] == "from"]
    (link,) = [ln for ln in from_links if ln["id"] == blocker_id]
    assert link["type"] == "blocks"
    assert link["title"] == "blocker chain probe: blocker"
    assert link["status"] == "held"  # our vocabulary, not bd's "in_progress"
    assert link["holder"] == unique_actor
    assert link["blocking"] is True


def test_get_with_links_blocking_clears_once_blocker_resolved(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    blocker_id = shared_bd.create("blocker chain probe: clears blocker", tags=[unique_lane])
    blocked_id = shared_bd.create("blocker chain probe: clears blocked", tags=[unique_lane])
    r = shared_bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001
    assert r.returncode == 0, r.stderr

    before = shared_bd.get(blocked_id, with_links=True)
    (link_before,) = [ln for ln in before.links if ln["id"] == blocker_id]
    assert link_before["blocking"] is True
    assert link_before["status"] != "resolved"

    shared_bd.claim_item(blocker_id, actor=unique_actor)
    shared_bd.resolve(blocker_id, "cleared for the chain test", actor=unique_actor)

    after = shared_bd.get(blocked_id, with_links=True)
    (link_after,) = [ln for ln in after.links if ln["id"] == blocker_id]
    assert link_after["status"] == "resolved"
    assert link_after["blocking"] is False


def test_get_with_links_reports_discovered_from_both_directions(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    origin_id = shared_bd.create("blocker chain probe: origin", tags=[unique_lane])
    found_id = shared_bd.create(
        "blocker chain probe: discovered",
        tags=[unique_lane],
        discovered_from=[origin_id],
    )

    found = shared_bd.get(found_id, with_links=True)
    (from_link,) = [
        ln
        for ln in found.links
        if ln["direction"] == "from" and ln["type"] == A.LINK_DISCOVERED_FROM
    ]
    assert from_link["id"] == origin_id
    assert from_link["title"] == "blocker chain probe: origin"
    # A discovered-from link never blocks (ASSUMPTION link.nonblocking).
    assert from_link["blocking"] is False

    origin = shared_bd.get(origin_id, with_links=True)
    (to_link,) = [
        ln
        for ln in origin.links
        if ln["direction"] == "to" and ln["type"] == A.LINK_DISCOVERED_FROM
    ]
    assert to_link["id"] == found_id


def test_get_with_links_blocks_inverse_is_present_but_lean(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    """The cheap inverse (`to`-direction `blocks`) carries id/title/status
    but bd's own lean dependents payload never includes holder/created_by
    -- honest degrade, not a fetch-per-dependent N+1 (see `Beads.get`)."""
    blocker_id = shared_bd.create("blocker chain probe: inverse blocker", tags=[unique_lane])
    blocked_id = shared_bd.create("blocker chain probe: inverse blocked", tags=[unique_lane])
    r = shared_bd._run(["dep", blocker_id, "--blocks", blocked_id])  # noqa: SLF001
    assert r.returncode == 0, r.stderr

    blocker = shared_bd.get(blocker_id, with_links=True)
    (to_link,) = [ln for ln in blocker.links if ln["direction"] == "to" and ln["id"] == blocked_id]
    assert to_link["type"] == "blocks"
    assert to_link["title"] == "blocker chain probe: inverse blocked"
    assert to_link["holder"] is None
    assert to_link["created_by"] is None


# --------------------------------------------------------------- Beads.activity


def test_activity_reports_created_claimed_commented_and_resolved(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    item_id = shared_bd.create("activity probe: full lifecycle", tags=[unique_lane])
    shared_bd.claim_item(item_id, actor=unique_actor)
    # `--actor` explicitly, rather than relying on bd's own fallback (BEADS_ACTOR ->
    # git user.name -> $USER) -- this environment's git user.name is NOT
    # `unique_actor`, so the comment's real author must be pinned explicitly for
    # this test to assert on a known identity.
    r = shared_bd._run(  # noqa: SLF001 -- test setup
        ["comment", item_id, "working on it", "--actor", unique_actor]
    )
    assert r.returncode == 0, r.stderr
    shared_bd.resolve(item_id, "shipped it", actor=unique_actor)

    events = shared_bd.activity(item_id)
    kinds = [e.kind for e in events]
    assert "created" in kinds
    assert "status" in kinds  # the claim transition
    assert "comment" in kinds
    assert "resolved" in kinds

    # Reverse-chronological: resolved (last real thing that happened) first.
    assert events[0].kind == "resolved"
    assert events[0].detail == "shipped it"

    comment_events = [e for e in events if e.kind == "comment"]
    assert comment_events[0].detail == "working on it"
    assert comment_events[0].actor == unique_actor


def test_activity_on_a_fresh_item_is_just_created(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("activity probe: fresh item", tags=[unique_lane])
    events = shared_bd.activity(item_id)
    assert len(events) == 1
    assert events[0].kind == "created"


def test_activity_is_read_only_and_does_not_touch_status_or_holder(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("activity probe: read-only", tags=[unique_lane])
    before = shared_bd.get(item_id)
    shared_bd.activity(item_id)
    shared_bd.activity(item_id)  # repeated reads -- never mutating
    after = shared_bd.get(item_id)
    assert after.status == before.status == "open"
    assert after.holder is None
