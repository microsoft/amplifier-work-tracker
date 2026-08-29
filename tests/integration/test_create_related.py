"""Tier 2 -- `Beads.create(related=...)` / `adapter.RELATION_KINDS`, against
the real `bd` binary and a real (isolated) shared dolt server.

`related` is our public "first-class link" vocabulary (work_tracker item
9e4): a list of `(id, relation_kind)` pairs recorded as real dependency
edges, via the SAME atomic `bd create --deps` mechanism `discovered_from`
already uses -- one create call, verified readable back via
`get(with_links=True)`.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_create_with_relates_to_records_a_visible_edge(shared_bd: A.Beads, unique_lane):
    other_id = shared_bd.create("related probe: other (relates-to)", tags=[unique_lane])

    new_id = shared_bd.create(
        "related probe: new item (relates-to)",
        tags=[unique_lane],
        related=[(other_id, "relates-to")],
    )

    item = shared_bd.get(new_id, with_links=True)
    match = next(link for link in item.links if link["id"] == other_id)
    assert match["type"] == "relates-to"
    assert match["blocking"] is False


def test_create_with_supersedes_records_a_visible_edge(shared_bd: A.Beads, unique_lane):
    other_id = shared_bd.create("related probe: other (supersedes)", tags=[unique_lane])

    new_id = shared_bd.create(
        "related probe: new item (supersedes)",
        tags=[unique_lane],
        related=[(other_id, "supersedes")],
    )

    item = shared_bd.get(new_id, with_links=True)
    match = next(link for link in item.links if link["id"] == other_id)
    assert match["type"] == "supersedes"


def test_create_with_follow_up_of_maps_to_discovered_from(shared_bd: A.Beads, unique_lane):
    other_id = shared_bd.create("related probe: other (follow-up-of)", tags=[unique_lane])

    new_id = shared_bd.create(
        "related probe: new item (follow-up-of)",
        tags=[unique_lane],
        related=[(other_id, "follow-up-of")],
    )

    item = shared_bd.get(new_id, with_links=True)
    match = next(link for link in item.links if link["id"] == other_id)
    assert match["type"] == A.LINK_DISCOVERED_FROM


def test_create_with_multiple_related_entries_records_all(shared_bd: A.Beads, unique_lane):
    a_id = shared_bd.create("related probe: multi a", tags=[unique_lane])
    b_id = shared_bd.create("related probe: multi b", tags=[unique_lane])

    new_id = shared_bd.create(
        "related probe: multi new",
        tags=[unique_lane],
        related=[(a_id, "relates-to"), (b_id, "supersedes")],
    )

    item = shared_bd.get(new_id, with_links=True)
    linked_ids = {link["id"] for link in item.links}
    assert {a_id, b_id} <= linked_ids


def test_create_refuses_whole_create_on_unknown_relation_kind(shared_bd: A.Beads, unique_lane):
    other_id = shared_bd.create("related probe: other (bad kind)", tags=[unique_lane])

    with pytest.raises(A.BeadsError) as exc:
        shared_bd.create(
            "related probe: should never exist",
            tags=[unique_lane],
            related=[(other_id, "not-a-real-kind")],
        )
    assert "unknown relation kind" in str(exc.value)

    # Nothing with this title was created -- refused before any bd call.
    existing = shared_bd.list(lane=unique_lane, include_resolved=True)
    assert not any(i.title == "related probe: should never exist" for i in existing)


def test_create_without_related_is_unchanged(shared_bd: A.Beads, unique_lane):
    new_id = shared_bd.create("related probe: no related at all", tags=[unique_lane])
    item = shared_bd.get(new_id, with_links=True)
    assert item.links == []
