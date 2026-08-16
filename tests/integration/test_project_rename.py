"""Tier 2 -- `Workspace.rename`, against the real `bd` binary and a real
(isolated) shared dolt server.

`rename` is genuinely risky: it renames BOTH the on-disk directory AND the
shared-server database, and must leave no orphan database and no half-renamed
state. These tests prove the end-to-end success path (old gone, new fully
writable, items preserved) and every refusal gate, and each one cleans up
BOTH possible names (the source and the destination) so nothing leaks --
see conftest.py's module docstring for why server-side teardown matters.
"""

from __future__ import annotations

import shutil
import uuid

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


@pytest.fixture
def rename_pair(workspace):
    """A `(old, new)` pair of unique project names, plus teardown that drops
    BOTH from the shared dolt server and disk -- whichever of the two ends up
    existing after a given test. Mirrors `drop_project` in conftest.py
    (`drop_database` + `rmtree`), but for the two names a rename touches.
    """
    old = f"rold{uuid.uuid4().hex[:12]}"
    new = f"rnew{uuid.uuid4().hex[:12]}"
    yield old, new
    for name in (old, new):
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(workspace.path(name), ignore_errors=True)


def test_rename_moves_dir_and_database_and_preserves_items(workspace, rename_pair):
    """The flagship scenario: a healthy project is renamed end-to-end. After
    it, the old name is gone from BOTH locations, the new name exists in
    both, every item survives with its original id, and the renamed project
    is fully writable under the new name.
    """
    old, new = rename_pair
    workspace.create(old)
    bd_old = workspace.project(old)
    id1 = bd_old.create("first", tags=[A.LANE_WORK], description="one", acceptance="g/w/t")
    id2 = bd_old.create("second", tags=[A.LANE_WORK])
    before = sorted(i.id for i in bd_old.list(include_resolved=True))
    assert before == sorted([id1, id2])

    report = workspace.rename(old, new)

    # Report is honest about what happened.
    assert report.old == old
    assert report.new == new
    assert report.directory == workspace.path(new)
    assert report.item_count == 2
    assert report.old_database_dropped is True

    # Old name is gone from BOTH locations -- no orphan database, no residue.
    assert not (workspace.path(old) / ".beads").is_dir()
    assert not A.database_exists(old), "the old database must be dropped, not orphaned"

    # New name exists in both locations.
    assert (workspace.path(new) / ".beads").is_dir()
    assert A.database_exists(new)

    # Items survive with their ORIGINAL ids (preserved, not remapped) -- the
    # real cross-check on the new name.
    after = sorted(i.id for i in workspace.project(new).list(include_resolved=True))
    assert after == before, "every item must survive the rename with its original id"

    # The renamed project is fully WRITABLE under the new name.
    id3 = workspace.project(new).create("after-rename", tags=[A.LANE_WORK])
    reread = sorted(i.id for i in workspace.project(new).list(include_resolved=True))
    assert reread == sorted([*before, id3])


def test_rename_refuses_when_new_name_already_exists(workspace, rename_pair):
    """`new` already taken -> refuse, non-destructively: both projects stay
    exactly as they were.
    """
    old, new = rename_pair
    workspace.create(old)
    workspace.create(new)
    old_id = workspace.project(old).create("keep me", tags=[A.LANE_WORK])

    with pytest.raises(A.BeadsError) as ei:
        workspace.rename(old, new)
    assert "already exists" in str(ei.value)

    # Non-destructive: both databases and both item sets are untouched.
    assert A.database_exists(old)
    assert A.database_exists(new)
    assert [i.id for i in workspace.project(old).list()] == [old_id]

    workspace.remove(old, force=True)
    workspace.remove(new, force=True)


def test_rename_refuses_when_old_missing(workspace, rename_pair):
    """A source that does not exist -> a distinct 'not found' error, and no
    `new` database is created as a side effect.
    """
    old, new = rename_pair
    with pytest.raises(A.BeadsError) as ei:
        workspace.rename(old, new)
    assert "not found" in str(ei.value)
    assert not A.database_exists(new), "a failed rename must not create the destination"


def test_rename_refuses_while_an_item_is_held(workspace, rename_pair, unique_actor):
    """An item HELD in the source -> refuse (naming the holder and item), and
    leave both the source and the not-yet-created destination untouched.
    """
    old, new = rename_pair
    workspace.create(old)
    bd = workspace.project(old)
    item_id = bd.create("held probe", tags=[A.LANE_WORK], priority=1)
    bd.claim_item(item_id, actor=unique_actor)

    with pytest.raises(A.BeadsError) as ei:
        workspace.rename(old, new)
    msg = str(ei.value)
    assert item_id in msg
    assert unique_actor in msg
    assert "HELD" in msg

    # Source untouched; destination never created.
    assert A.database_exists(old)
    assert workspace.project(old).get(item_id).status == "held"
    assert not A.database_exists(new)
    assert not (workspace.path(new) / ".beads").is_dir()

    bd.release(item_id)


def test_rename_rejects_invalid_new_name(workspace, rename_pair):
    """A `new` name that violates NAME_RE (dots/hyphens) is rejected before
    any mutation, and the source is untouched.
    """
    old, _ = rename_pair
    workspace.create(old)
    for bad in ("has.dot", "has-hyphen", "Uppercase"):
        with pytest.raises(A.BeadsError) as ei:
            workspace.rename(old, bad)
        assert A.NAME_RE.pattern in str(ei.value)
        assert not A.database_exists(bad)
    assert A.database_exists(old), "the source must be untouched by a rejected rename"


def test_rename_to_itself_is_refused(workspace, rename_pair):
    old, _ = rename_pair
    workspace.create(old)
    with pytest.raises(A.BeadsError) as ei:
        workspace.rename(old, old)
    assert "itself" in str(ei.value)
    assert A.database_exists(old)
