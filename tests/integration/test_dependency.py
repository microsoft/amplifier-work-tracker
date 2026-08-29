"""Tier 2 -- `Beads.add_dependency` (the CREATE side) and
`Beads.get`/`get_readonly(with_links=True)` (the DISPLAY side) of the
dependency graph, against the real `bd` binary and a real (isolated)
shared dolt server.

`claim_item` already ENFORCES `blocks`-type dependencies (refuses, naming
the blocker) -- these tests prove the write path that creates the edge it
reads, and the read path that displays it, end to end: declare, see it,
get refused claiming past it, resolve the blocker, claim succeeds.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_add_dependency_creates_edge_visible_via_get_with_links(shared_bd: A.Beads, unique_lane):
    blocker_id = shared_bd.create("dep probe: blocker", tags=[unique_lane], priority=1)
    blocked_id = shared_bd.create("dep probe: blocked", tags=[unique_lane], priority=1)

    shared_bd.add_dependency(blocked_id, blocker_id, dep_type="blocks", actor="declarer")

    item = shared_bd.get(blocked_id, with_links=True)
    matches = [
        link
        for link in item.links
        if link["id"] == blocker_id and link["direction"] == "from" and link["type"] == "blocks"
    ]
    assert matches, item.links
    assert matches[0]["blocking"] is True


def test_get_readonly_with_links_displays_the_same_edge(shared_bd: A.Beads, unique_lane):
    blocker_id = shared_bd.create("dep probe: blocker (readonly)", tags=[unique_lane])
    blocked_id = shared_bd.create("dep probe: blocked (readonly)", tags=[unique_lane])
    shared_bd.add_dependency(blocked_id, blocker_id, dep_type="blocks", actor="declarer")

    item = shared_bd.get_readonly(blocked_id, with_links=True)
    assert any(link["id"] == blocker_id for link in item.links)

    # Forward ("from") edges are always present regardless of with_links
    # (bd's `dependencies` field needs no extra flag) -- unchanged, existing
    # `get()` behavior. `with_links` only additionally includes REVERSE
    # ("to"/dependents) edges, which require bd's `--include-dependents`.
    plain = shared_bd.get_readonly(blocked_id)
    assert any(link["id"] == blocker_id and link["direction"] == "from" for link in plain.links)

    blocker_plain = shared_bd.get_readonly(blocker_id)
    assert not any(link["direction"] == "to" for link in blocker_plain.links)

    blocker_with_links = shared_bd.get_readonly(blocker_id, with_links=True)
    assert any(
        link["id"] == blocked_id and link["direction"] == "to" for link in blocker_with_links.links
    )


def test_claim_refuses_naming_the_dependency_created_via_add_dependency(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    blocker_id = shared_bd.create("dep probe: claim blocker", tags=[unique_lane], priority=0)
    blocked_id = shared_bd.create("dep probe: claim blocked", tags=[unique_lane], priority=0)
    shared_bd.add_dependency(blocked_id, blocker_id, dep_type="blocks", actor="declarer")

    with pytest.raises(A.BeadsError) as exc:
        shared_bd.claim_item(blocked_id, actor=unique_actor)
    assert blocker_id in str(exc.value)


def test_resolving_the_blocker_makes_the_blocked_item_claimable(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    blocker_id = shared_bd.create("dep probe: resolve blocker", tags=[unique_lane], priority=0)
    blocked_id = shared_bd.create("dep probe: resolve blocked", tags=[unique_lane], priority=0)
    shared_bd.add_dependency(blocked_id, blocker_id, dep_type="blocks", actor="declarer")

    shared_bd.resolve(blocker_id, "unblocking now", actor="resolver")

    claimed = shared_bd.claim_item(blocked_id, actor=unique_actor)
    assert claimed.id == blocked_id


def test_add_dependency_with_non_blocking_type_is_not_a_claim_blocker(
    shared_bd: A.Beads, unique_lane, unique_actor
):
    other_id = shared_bd.create("dep probe: related (non-blocking)", tags=[unique_lane])
    item_id = shared_bd.create(
        "dep probe: item with non-blocking dep", tags=[unique_lane], priority=0
    )
    shared_bd.add_dependency(item_id, other_id, dep_type="relates-to", actor="declarer")

    item = shared_bd.get(item_id, with_links=True)
    match = next(link for link in item.links if link["id"] == other_id)
    assert match["blocking"] is False

    # relates-to never blocks the claim.
    claimed = shared_bd.claim_item(item_id, actor=unique_actor)
    assert claimed.id == item_id


def test_add_dependency_refuses_on_nonexistent_target(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("dep probe: bad target", tags=[unique_lane])
    with pytest.raises(A.BeadsError):
        shared_bd.add_dependency(item_id, "no-such-item-id-zzz", dep_type="blocks")
