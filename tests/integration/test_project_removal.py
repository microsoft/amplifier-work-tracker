"""Tier 2 -- `Workspace.remove` and the `new`-adoption-honesty fix, against
the real `bd` binary and shared dolt server.

Every project name here is unique (`unique_project_name` / a locally-scoped
generator), never a fixed literal -- see conftest.py's module docstring for
why. `remove` is genuinely destructive, so unlike most of this suite, tests
here do NOT share `shared_project_name`; each test creates and destroys its
own project.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_remove_of_nonexistent_project_gives_a_distinct_error(workspace, unique_project_name):
    try:
        workspace.remove(unique_project_name, force=True)
        raise AssertionError("expected BeadsError for a project that was never created")
    except A.BeadsError as e:
        assert "not found" in str(e)


def test_remove_drops_both_the_directory_and_the_database(workspace, unique_project_name):
    """`create()` itself (via `bd init`) leaves tool-integration scaffolding
    behind -- `.git`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`, `.claude/`,
    `.codex/` -- alongside `.beads`, even for a project nobody has touched
    yet. `remove` must drop `.beads` and the database, and report every one
    of those as leftover rather than guessing any of it is safe to delete
    -- exactly the same caution it applies to genuine user content."""
    name = unique_project_name
    workspace.create(name)
    assert A.database_exists(name), "sanity: the database must exist right after create()"
    d = workspace.path(name)

    report = workspace.remove(name, force=True)

    assert report.had_beads_dir is True
    assert report.had_database is True
    assert report.beads_removed is True
    assert report.database_removed is True
    assert not A.database_exists(name), "the database must actually be dropped from the server"
    assert not (d / ".beads").exists(), ".beads is ours -- must be gone"
    assert d.exists(), "bd's own scaffolding means the directory is never truly empty"
    assert ".git" in report.leftover

    import shutil

    shutil.rmtree(d, ignore_errors=True)


def test_remove_refuses_while_an_item_is_held_naming_holder_and_item(
    workspace, unique_project_name, unique_actor
):
    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)
    item_id = bd.create("removal-refusal probe", tags=["lane:removal_refusal"], priority=1)
    bd.claim_item(item_id, actor=unique_actor)

    try:
        workspace.remove(name, force=True)
        raise AssertionError("expected refusal while an item is HELD")
    except A.BeadsError as e:
        msg = str(e)
        assert item_id in msg
        assert unique_actor in msg
        assert "HELD" in msg

    # Refusal must be non-destructive: both locations are untouched.
    assert workspace.path(name).exists()
    assert A.database_exists(name)
    back = bd.get(item_id)
    assert back.status == "held"

    # Cleanup for real, now that nothing is held.
    bd.release(item_id)
    workspace.remove(name, force=True)


def test_remove_leaves_non_beads_content_intact_and_reports_it(workspace, unique_project_name):
    name = unique_project_name
    workspace.create(name)
    d = workspace.path(name)
    notes = d / "notes-a-human-put-here.md"
    notes.write_text("do not delete me\n", encoding="utf-8")

    report = workspace.remove(name, force=True)

    assert report.beads_removed is True
    assert report.database_removed is True
    assert report.directory_removed is False
    assert "notes-a-human-put-here.md" in report.leftover
    assert d.exists(), "the project directory itself must survive"
    assert notes.exists() and notes.read_text(encoding="utf-8") == "do not delete me\n"
    assert not (d / ".beads").exists(), "only .beads is ours to remove"

    # Cleanup the leftover directory ourselves (test hygiene, not part of the
    # behavior under test -- remove() correctly refused to touch it).
    import shutil

    shutil.rmtree(d, ignore_errors=True)


def test_remove_of_orphaned_database_after_directory_already_deleted(
    workspace, unique_project_name
):
    """The flagship scenario this feature exists for: the directory is
    already gone (as if by a manual `rm -rf`), but the shared-server
    database is still there. `remove` must reach it, verify it is safe
    (no HELD items), and drop it -- not merely fail because there is no
    local directory to key off of.
    """
    import shutil

    name = unique_project_name
    workspace.create(name)
    assert A.database_exists(name)
    shutil.rmtree(workspace.path(name), ignore_errors=True)
    assert not workspace.path(name).exists()
    assert A.database_exists(name), "sanity: the database outlives the directory"

    report = workspace.remove(name, force=True)

    assert report.had_beads_dir is False
    assert report.had_database is True
    assert report.database_removed is True
    assert not A.database_exists(name)
    assert not workspace.path(name).exists()


def test_remove_of_orphaned_database_with_a_held_item_still_refuses(
    workspace, unique_project_name, unique_actor
):
    """Same orphan shape, but an item was HELD at the moment the directory
    vanished. `remove` must still refuse -- and leave the same state it
    found (no directory), not a half-attached scratch directory.
    """
    import shutil

    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)
    item_id = bd.create("orphan-held probe", tags=["lane:orphan_held"], priority=1)
    bd.claim_item(item_id, actor=unique_actor)
    shutil.rmtree(workspace.path(name), ignore_errors=True)
    assert not workspace.path(name).exists()

    try:
        workspace.remove(name, force=True)
        raise AssertionError("expected refusal: an item was HELD in the orphaned database")
    except A.BeadsError as e:
        assert "HELD" in str(e)
        assert item_id in str(e)

    # Refusal must not leave a half-attached scratch directory behind.
    assert not workspace.path(name).exists()
    assert A.database_exists(name), "the database itself must be untouched by a refusal"

    # Cleanup for real: re-attach exactly like remove() itself did, then
    # release and remove for good.
    workspace.create(name)
    bd2 = workspace.project(name)
    bd2.release(item_id)
    workspace.remove(name, force=True)


def test_new_after_directory_deleted_reattaches_and_workspace_create_reports_it(
    workspace, unique_project_name
):
    """`Workspace.create`'s own contract: it does not fail or silently
    fabricate a fresh empty project when the directory is gone but the
    database survives -- it attaches. The CLI-level "say so loudly, don't
    print 'created'" behavior is exercised separately at the CLI tier
    (see tests/cli -- `cmd_new` is what decides the wording); this proves
    the adapter-level facts that decision is based on: the database
    existed beforehand, and the item that was in it is still there after.
    """
    import shutil

    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)
    bd.create("adoption probe item", tags=["lane:adoption_probe"], priority=1)
    shutil.rmtree(workspace.path(name), ignore_errors=True)

    pre_existing = A.database_exists(name)
    assert pre_existing is True

    workspace.create(name)  # re-attaches; must not raise
    items = workspace.project(name).list(include_resolved=True)
    assert len(items) == 1, (
        "the pre-existing item must still be there -- this is an adoption, not a fresh project"
    )

    workspace.remove(name, force=True)
