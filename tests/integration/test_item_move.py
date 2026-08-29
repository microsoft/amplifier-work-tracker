"""Tier 2 -- `Workspace.move_item` / `adapter.move_item`, against the real
`bd` binary and a real (isolated) shared dolt server.

`move_item` is the single-item counterpart to `Workspace.rename`: it moves
one item -- and every row keyed to it across the issues-family tables -- from
one project's database to another's, preserving the item's id exactly. These
tests prove the happy path (id preserved, body/labels preserved, item fully
gone from the source), every refusal gate, and the cross-project dependency
edge drop/preserve behavior.
"""

from __future__ import annotations

import csv
import uuid

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _dep_rows(db: str, item_id: str) -> list[tuple[str, str, str | None, str]]:
    """Raw `(id, issue_id, depends_on_issue_id, type)` dependency rows in
    `db` touching `item_id`, read directly over SQL -- test-only
    introspection mirroring the query `move_item` itself runs.
    """
    p = A._dolt_sql(  # noqa: SLF001 -- test introspection only
        f"SELECT `id`, `issue_id`, `depends_on_issue_id`, `type` FROM `{db}`.`dependencies` "
        f"WHERE `issue_id` = '{item_id}' OR `depends_on_issue_id` = '{item_id}'"
    )
    assert p.returncode == 0, p.stderr
    rows: list[tuple[str, str, str | None, str]] = []
    for row in csv.reader((p.stdout or "").splitlines()[1:]):  # drop CSV header
        if len(row) < 4:
            continue
        rows.append((row[0], row[1], row[2] or None, row[3]))
    return rows


def test_move_moves_item_preserves_id_and_body(workspace, project_factory):
    """The flagship scenario: an item with a full body and a label is moved
    end-to-end. It is fully gone from `src`, and lands in `dst` with its
    original id, title, description, acceptance criteria, and labels intact.
    """
    src_name, src_bd = project_factory("msrc")
    dst_name, dst_bd = project_factory("mdst")
    item_id = src_bd.create(
        "move me", tags=[A.LANE_WORK], description="the body", acceptance="given/when/then"
    )

    report = workspace.move_item(src_name, dst_name, item_id)

    assert report.item_id == item_id
    assert report.src == src_name
    assert report.dst == dst_name
    assert report.dropped_dependency_edges == []

    # Gone from src -- a real "not found", not a stale read.
    with pytest.raises(A.BeadsError):
        src_bd.get(item_id)

    # Present in dst with the SAME id and full body.
    moved = dst_bd.get(item_id)
    assert moved.id == item_id
    assert moved.title == "move me"
    assert moved.description == "the body"
    assert moved.acceptance == "given/when/then"
    assert A.LANE_WORK in moved.tags

    # dst is fully writable afterward (a real project, not a half-attached one).
    other_id = dst_bd.create("after-move", tags=[A.LANE_WORK])
    assert sorted(i.id for i in dst_bd.list(include_resolved=True)) == sorted([item_id, other_id])


def test_move_refuses_while_item_is_held(workspace, project_factory, unique_actor):
    src_name, src_bd = project_factory("msrc")
    dst_name, _ = project_factory("mdst")
    item_id = src_bd.create("held item", tags=[A.LANE_WORK], priority=1)
    src_bd.claim_item(item_id, actor=unique_actor)

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(src_name, dst_name, item_id)
    msg = str(ei.value)
    assert item_id in msg
    assert unique_actor in msg
    assert "HELD" in msg

    # Untouched: still held in src, never created in dst.
    assert src_bd.get(item_id).status == "held"
    with pytest.raises(A.BeadsError):
        workspace.project(dst_name).get(item_id)

    src_bd.release(item_id)


def test_move_refuses_when_item_missing(workspace, project_factory):
    src_name, _ = project_factory("msrc")
    dst_name, _ = project_factory("mdst")

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(src_name, dst_name, "no-such-item-id-at-all")
    assert "no such item" in str(ei.value)


def test_move_twice_raises_cleanly_the_second_time(workspace, project_factory):
    """Moving an id that was already moved out of `src` (and so no longer
    exists there) must fail the same clean 'not found' way as any other
    missing item -- never a confusing partial-state error.
    """
    src_name, src_bd = project_factory("msrc")
    dst_name, _ = project_factory("mdst")
    item_id = src_bd.create("move once", tags=[A.LANE_WORK])

    workspace.move_item(src_name, dst_name, item_id)

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(src_name, dst_name, item_id)
    assert "no such item" in str(ei.value)


def test_move_refuses_when_src_missing(workspace, project_factory):
    dst_name, _ = project_factory("mdst")
    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item("nonexistent_src_project_zzz", dst_name, "some-id")
    assert "does not exist" in str(ei.value)


def test_move_refuses_when_dst_missing(workspace, project_factory):
    src_name, src_bd = project_factory("msrc")
    item_id = src_bd.create("stays put", tags=[A.LANE_WORK])

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(src_name, "nonexistent_dst_project_zzz", item_id)
    assert "does not exist" in str(ei.value)

    # Untouched -- a failed destination check must not touch the source.
    assert src_bd.get(item_id).id == item_id


def test_move_refuses_when_src_equals_dst(workspace, project_factory):
    name, bd = project_factory("mself")
    item_id = bd.create("x", tags=[A.LANE_WORK])

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(name, name, item_id)
    assert "same project" in str(ei.value)
    assert bd.get(item_id).id == item_id


def test_move_rejects_invalid_project_names(workspace, project_factory):
    src_name, src_bd = project_factory("msrc")
    item_id = src_bd.create("x", tags=[A.LANE_WORK])

    for bad in ("has.dot", "has-hyphen", "Uppercase"):
        with pytest.raises(A.BeadsError) as ei:
            workspace.move_item(src_name, bad, item_id)
        assert A.NAME_RE.pattern in str(ei.value)
        assert not A.database_exists(bad)

    # Untouched by every rejected attempt.
    assert src_bd.get(item_id).id == item_id


def test_move_refuses_when_item_already_exists_at_destination(workspace, project_factory):
    """ids are project-prefixed and should never collide across projects in
    practice, but the refusal is checked rather than assumed -- forced here
    via a hand-crafted duplicate row, since `bd`'s own id minting cannot
    reproduce a real collision.
    """
    src_name, src_bd = project_factory("msrc")
    dst_name, _ = project_factory("mdst")
    item_id = src_bd.create("dup me", tags=[A.LANE_WORK])

    p = A._dolt_sql(  # noqa: SLF001 -- test setup: force the collision this refusal guards against
        f"INSERT INTO `{dst_name}`.`issues` SELECT * FROM `{src_name}`.`issues` "
        f"WHERE `id` = '{item_id}'"
    )
    assert p.returncode == 0, p.stderr

    with pytest.raises(A.BeadsError) as ei:
        workspace.move_item(src_name, dst_name, item_id)
    assert "already exists" in str(ei.value)

    # src is untouched -- the refusal happened before any mutation there.
    assert src_bd.get(item_id).id == item_id


def test_move_drops_cross_project_dependency_edge(workspace, project_factory):
    """An item blocked by (or blocking) another item that is NOT also
    moving cannot keep that edge once the two live in different databases
    -- it is dropped from both sides and named in
    `dropped_dependency_edges`, not silently left dangling.
    """
    src_name, src_bd = project_factory("msrc")
    dst_name, dst_bd = project_factory("mdst")
    moving_id = src_bd.create("moving", tags=[A.LANE_WORK])
    staying_id = src_bd.create("staying", tags=[A.LANE_WORK])

    # `moving` is blocked by `staying`: issue_id=moving_id, depends_on_issue_id=staying_id.
    r = src_bd._run(["dep", staying_id, "--blocks", moving_id])  # noqa: SLF001 -- test setup
    assert r.returncode == 0, r.stderr
    assert len(_dep_rows(src_name, moving_id)) == 1

    report = workspace.move_item(src_name, dst_name, moving_id)

    assert len(report.dropped_dependency_edges) == 1
    dropped = report.dropped_dependency_edges[0]
    assert dropped["issue_id"] == moving_id
    assert dropped["depends_on_issue_id"] == staying_id
    assert dropped["type"] == "blocks"

    # Dropped everywhere -- not left in src, not copied to dst.
    assert _dep_rows(src_name, moving_id) == []
    assert _dep_rows(dst_name, moving_id) == []

    # Both items are otherwise intact -- the moving item moved, the staying
    # item is untouched apart from losing the one edge that can no longer
    # be expressed.
    assert dst_bd.get(moving_id).id == moving_id
    assert src_bd.get(staying_id).id == staying_id


def test_move_preserves_dependency_edge_to_non_issue_target(workspace, project_factory):
    """A dependency row whose target is NOT another issue (e.g. an external
    reference, via `depends_on_external`) belongs entirely to the moving
    item -- it is not a cross-project edge, so it moves along with the item
    rather than being dropped.
    """
    src_name, src_bd = project_factory("msrc")
    dst_name, _ = project_factory("mdst")
    moving_id = src_bd.create("moving", tags=[A.LANE_WORK])

    dep_id = str(uuid.uuid4())
    p = A._dolt_sql(  # noqa: SLF001 -- test setup: bd's own CLI has no external-ref dep command
        f"INSERT INTO `{src_name}`.`dependencies` "
        f"(`id`, `issue_id`, `type`, `created_by`, `depends_on_external`) "
        f"VALUES ('{dep_id}', '{moving_id}', 'blocks', 'test', 'https://example.com/ISSUE-1')"
    )
    assert p.returncode == 0, p.stderr

    report = workspace.move_item(src_name, dst_name, moving_id)

    assert report.dropped_dependency_edges == []
    assert _dep_rows(src_name, moving_id) == []
    moved_deps = _dep_rows(dst_name, moving_id)
    assert len(moved_deps) == 1
    assert moved_deps[0][0] == dep_id
