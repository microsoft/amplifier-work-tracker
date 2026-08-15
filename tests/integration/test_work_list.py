"""`Beads.list_bounded` -- the read-only per-item view neither `work_status`
nor the pre-existing `list()` provided: id, title, status, holder, and (for
closed items) resolution, all in one call, with an honest total/truncation
report.

Motivated directly by a real three-agent contention test: every agent could
see project-level counts via `work_status`, but none had a sanctioned way to
see WHICH items existed, WHO held one, or what a closed item's resolution
was -- forcing a raw `bd list --all --json` shell-out to verify the run.
These tests prove the gap is closed against the real `bd`/dolt storage layer,
not just that our own Python agrees with itself.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_list_bounded_reports_id_title_status_for_an_open_item(shared_bd, unique_lane):
    item_id = shared_bd.create("work_list open probe", tags=[unique_lane], priority=1)

    result = shared_bd.list_bounded()
    by_id = {i.id: i for i in result.items}
    assert item_id in by_id
    assert by_id[item_id].title == "work_list open probe"
    assert by_id[item_id].status == "open"
    assert by_id[item_id].holder is None
    assert by_id[item_id].resolution is None


def test_list_bounded_populates_holder_for_a_held_item(shared_bd, unique_lane, unique_actor):
    """The field `work_status` most conspicuously lacks -- proven by
    claiming an item and showing the holder actually appears."""
    shared_bd.create("work_list held probe", tags=[unique_lane], priority=1)
    claimed = shared_bd.claim_next(lane=unique_lane, actor=unique_actor)
    assert claimed is not None

    result = shared_bd.list_bounded(status="held")
    by_id = {i.id: i for i in result.items}
    assert claimed.id in by_id
    assert by_id[claimed.id].holder == unique_actor
    assert by_id[claimed.id].status == "held"

    shared_bd.resolve(claimed.id, "test cleanup", actor=unique_actor)


def test_list_bounded_shows_closed_items_and_their_resolution(shared_bd, unique_lane):
    """The other half of the gap: what happened to items an agent did NOT
    claim must be visible, not just open ones."""
    item_id = shared_bd.create("work_list resolution probe", tags=[unique_lane], priority=1)
    claimed = shared_bd.claim_next(lane=unique_lane, actor="resolution-prober")
    assert claimed is not None and claimed.id == item_id
    shared_bd.resolve(item_id, "fixed via resolution probe test", actor="resolution-prober")

    result = shared_bd.list_bounded(status="resolved")
    by_id = {i.id: i for i in result.items}
    assert item_id in by_id
    assert by_id[item_id].status == "resolved"
    assert by_id[item_id].resolution == "fixed via resolution probe test"


def test_list_bounded_mixed_states_in_one_project(shared_bd, unique_lane, unique_actor):
    """One project, three items in three different states -- exactly the
    scenario the real contention test needed a read-only view for."""
    open_id = shared_bd.create("mixed: open", tags=[unique_lane], priority=1)
    held_id = shared_bd.create("mixed: held", tags=[unique_lane], priority=1)
    closed_id = shared_bd.create("mixed: closed", tags=[unique_lane], priority=1)

    claimed = shared_bd.claim_item(held_id, actor=unique_actor)
    assert claimed.id == held_id
    shared_bd.resolve(closed_id, "mixed-state resolution", actor="mixed-resolver")

    result = shared_bd.list_bounded()
    by_id = {i.id: i for i in result.items}
    assert by_id[open_id].status == "open"
    assert by_id[open_id].holder is None
    assert by_id[held_id].status == "held"
    assert by_id[held_id].holder == unique_actor
    assert by_id[closed_id].status == "resolved"
    assert by_id[closed_id].resolution == "mixed-state resolution"

    shared_bd.resolve(held_id, "test cleanup", actor=unique_actor)


@pytest.mark.parametrize("status", list(A.STATUSES))
def test_list_bounded_status_filter_returns_only_matching_status(status, shared_bd, unique_lane):
    open_id = shared_bd.create(f"status-filter open ({status})", tags=[unique_lane], priority=1)
    held_id = shared_bd.create(f"status-filter held ({status})", tags=[unique_lane], priority=1)
    shared_bd.claim_item(held_id, actor="status-filter-actor")

    result = shared_bd.list_bounded(status=status)
    ids = {i.id for i in result.items}
    for i in result.items:
        assert i.status == status

    if status == "open":
        assert open_id in ids
        assert held_id not in ids
    elif status == "held":
        assert held_id in ids
        assert open_id not in ids

    shared_bd.resolve(held_id, "test cleanup", actor="status-filter-actor")


def test_list_bounded_calling_it_does_not_mutate_anything(shared_bd, unique_lane, unique_actor):
    """Strictly read-only: full project state before and after must be
    identical (same items, same statuses, same holders)."""
    shared_bd.create("no-mutation probe 1", tags=[unique_lane], priority=1)
    held_id = shared_bd.create("no-mutation probe 2", tags=[unique_lane], priority=1)
    shared_bd.claim_item(held_id, actor=unique_actor)

    def snapshot():
        items = shared_bd.list(include_resolved=True)
        return {
            i.id: (i.status, i.holder, i.resolution, i.title, tuple(sorted(i.tags))) for i in items
        }

    before = snapshot()
    shared_bd.list_bounded()
    shared_bd.list_bounded(status="held")
    shared_bd.list_bounded(status="open", limit=1)
    after = snapshot()

    assert before == after

    shared_bd.resolve(held_id, "test cleanup", actor=unique_actor)


def test_list_bounded_truncates_and_reports_honestly(shared_bd, unique_lane):
    """`limit` smaller than the true total must cap the returned rows while
    reporting the true `total_count` and `truncated=True` -- never a silent
    partial result presented as complete."""
    ids = [
        shared_bd.create(f"truncation probe {n}", tags=[unique_lane], priority=1) for n in range(5)
    ]

    result = shared_bd.list_bounded(status="open", limit=2)
    assert result.returned_count == 2
    assert result.total_count >= 5
    assert result.truncated is True
    assert result.limit == 2

    unbounded = shared_bd.list_bounded(status="open", limit=A.LIST_MAX_LIMIT)
    unbounded_ids = {i.id for i in unbounded.items}
    for i in ids:
        assert i in unbounded_ids


def test_list_bounded_on_empty_project_returns_empty_not_an_error(workspace, project_factory):
    name, bd = project_factory("wlempty")
    result = bd.list_bounded()
    assert result.items == []
    assert result.total_count == 0
    assert result.returned_count == 0
    assert result.truncated is False


def test_list_bounded_on_nonexistent_project_raises_distinct_not_found(
    workspace, unique_project_name
):
    try:
        workspace.project(unique_project_name).list_bounded()
        raise AssertionError("expected BeadsError for a nonexistent project")
    except A.BeadsError as e:
        assert "not found" in str(e)


def test_list_bounded_rows_are_lean_by_default_no_body_fields(shared_bd, unique_lane):
    """The default list payload must stay lean -- no acceptance/description/
    design, not even as an explicit null -- so a bulk listing of many items
    never balloons the response with bodies nobody asked for."""
    item_id = shared_bd.create(
        "work_list leanness probe",
        tags=[unique_lane],
        priority=1,
        description="a description nobody asked to see in the default list",
        acceptance="acceptance text that should stay out of the lean row",
    )
    result = shared_bd.list_bounded()
    by_id = {i.id: i for i in result.items}
    assert item_id in by_id
    row = by_id[item_id].summary()
    assert "acceptance" not in row
    assert "description" not in row
    assert "design" not in row


# ------------------------------------------------------------ get_readonly


def test_get_readonly_reads_the_real_full_body_without_claiming(shared_bd, unique_lane):
    """The core scenario the other agent session hit: read acceptance and
    description for a real item, against the real bd/dolt storage layer,
    without claiming it -- and it must stay open/unheld afterward."""
    item_id = shared_bd.create(
        "get_readonly full-body probe",
        tags=[unique_lane],
        priority=1,
        description="a real description that should come back intact",
        acceptance="Given a probe, When read, Then the body is visible",
    )

    item = shared_bd.get_readonly(item_id)
    assert item.id == item_id
    assert item.status == "open"
    assert item.holder is None
    assert item.description == "a real description that should come back intact"
    assert item.acceptance == "Given a probe, When read, Then the body is visible"

    # Never claimed.
    back = shared_bd.get(item_id)
    assert back.status == "open"
    assert back.holder is None


def test_get_readonly_on_resolved_item_shows_resolution_too(shared_bd, unique_lane):
    item_id = shared_bd.create("get_readonly resolved probe", tags=[unique_lane], priority=1)
    claimed = shared_bd.claim_item(item_id, actor="get-readonly-resolver")
    assert claimed.id == item_id
    shared_bd.resolve(item_id, "get_readonly resolution text", actor="get-readonly-resolver")

    item = shared_bd.get_readonly(item_id)
    assert item.status == "resolved"
    assert item.resolution == "get_readonly resolution text"


def test_get_readonly_never_mutates_the_item(shared_bd, unique_lane):
    item_id = shared_bd.create("get_readonly no-mutation probe", tags=[unique_lane], priority=1)

    def snapshot():
        i = shared_bd.get(item_id)
        return (i.status, i.holder, i.meta)

    before = snapshot()
    for _ in range(3):
        shared_bd.get_readonly(item_id)
    after = snapshot()
    assert before == after


def test_get_readonly_on_nonexistent_item_in_this_project_raises_not_found(
    shared_project_name, shared_bd
):
    fake_id = f"{shared_project_name}-doesnotexist999"
    try:
        shared_bd.get_readonly(fake_id)
        raise AssertionError("expected BeadsError for a nonexistent item")
    except A.BeadsError as e:
        assert "not found in project" in str(e)
        assert "does not look like it belongs" not in str(e)


def test_get_readonly_on_id_from_a_different_project_raises_distinct_wrong_project_error(
    shared_bd, project_factory, unique_lane
):
    """A VALID id, just belonging to a different project -- bd's own error
    text is identical to a plain not-found, so this must be distinguished
    by us, not bd."""
    other_name, other_bd = project_factory("wrongprojread")
    other_item_id = other_bd.create("wrong-project source item", tags=[unique_lane], priority=1)

    try:
        shared_bd.get_readonly(other_item_id)
        raise AssertionError("expected BeadsError naming the wrong-project mismatch")
    except A.BeadsError as e:
        assert "does not look like it belongs to project" in str(e)
