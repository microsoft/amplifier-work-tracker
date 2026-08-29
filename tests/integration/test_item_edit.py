"""Tier 2 -- `Beads.edit_item` / `Beads.comment` / `Beads.supersede`, against
the real `bd` binary and a real (isolated) shared dolt server.

`edit_item` is content editing (title/description/acceptance/design) IN
PLACE, with an audit-trail comment naming who changed what. `supersede` is
the structural "this item is fully replaced by a different one" merge,
which CLOSES the original via bd's own `supersede` command -- never a fake
`resolve(..., reason=...)` that loses the replacement's real id.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_edit_item_changes_fields_and_leaves_audit_comment(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create(
        "edit probe: original title",
        tags=[unique_lane],
        description="original description",
        acceptance="original acceptance",
    )

    back = shared_bd.edit_item(
        item_id,
        title="edit probe: new title",
        description="new description",
        actor="editor-actor",
    )

    assert back.title == "edit probe: new title"
    assert back.description == "new description"
    # Acceptance was not touched -- untouched fields stay untouched.
    assert back.acceptance == "original acceptance"

    comments = shared_bd._json(["comments", item_id]) or []  # noqa: SLF001 -- test introspection
    assert comments
    texts = [c.get("text", "") for c in comments if isinstance(c, dict)]
    assert any("editor-actor edited: title, description" in t for t in texts)


def test_edit_item_refuses_with_no_fields(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("edit probe: no-op", tags=[unique_lane])
    with pytest.raises(A.BeadsError) as exc:
        shared_bd.edit_item(item_id)
    assert "nothing to change" in str(exc.value)


def test_edit_item_only_names_fields_that_actually_changed(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create(
        "edit probe: partial", tags=[unique_lane], description="d", acceptance="a"
    )
    shared_bd.edit_item(item_id, acceptance="new acceptance only", actor="partial-editor")
    comments = shared_bd._json(["comments", item_id]) or []  # noqa: SLF001 -- test introspection
    texts = [c.get("text", "") for c in comments if isinstance(c, dict)]
    joined = " ".join(texts)
    assert "acceptance" in joined
    assert "title" not in joined
    assert "description" not in joined


def test_comment_appends_and_is_readable(shared_bd: A.Beads, unique_lane):
    item_id = shared_bd.create("comment probe", tags=[unique_lane])
    shared_bd.comment(item_id, "a standalone audit note", actor="note-actor")
    comments = shared_bd._json(["comments", item_id]) or []  # noqa: SLF001 -- test introspection
    texts = [c.get("text", "") for c in comments if isinstance(c, dict)]
    assert "a standalone audit note" in texts


def test_supersede_closes_original_with_structural_reference(shared_bd: A.Beads, unique_lane):
    old_id = shared_bd.create("supersede probe: old", tags=[unique_lane])
    new_id = shared_bd.create("supersede probe: new", tags=[unique_lane])

    back = shared_bd.supersede(old_id, new_id, actor="merger")

    assert back.id == old_id
    assert back.status == "resolved"
    # bd records the replacement structurally -- readable back off the item
    # (either in its resolution text or its raw payload), never merely "we
    # trust the exit code."
    resolution_blob = (back.resolution or "") + str(back.raw)
    assert new_id in resolution_blob


def test_supersede_refuses_when_replacement_missing(shared_bd: A.Beads, unique_lane):
    old_id = shared_bd.create("supersede probe: orphan", tags=[unique_lane])
    with pytest.raises(A.BeadsError):
        shared_bd.supersede(old_id, "no-such-replacement-id-zzz")
    # Untouched -- a failed supersede must not close the item anyway.
    assert shared_bd.get(old_id).status != "resolved"
