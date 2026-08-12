"""Tier 1 -- `Workspace.remove`'s fast-fail guards that need no real `bd`/dolt
at all: the confirmation gate and name validation both run BEFORE any I/O,
exactly like `Workspace.create`'s dotted-name guard (see
test_adapter_mapping.py's `test_workspace_create_rejects_dotted_name_before_touching_disk`).
"""

from __future__ import annotations

from amplifier_work_tracker import adapter as A


def test_remove_without_force_refuses_before_touching_disk(tmp_path):
    ws = A.Workspace(tmp_path)
    try:
        ws.remove("whatever")
        raise AssertionError("expected BeadsError when force is not passed")
    except A.BeadsError as e:
        assert "force" in str(e) or "confirmation" in str(e)
    # No directory should have been created or touched.
    assert not (tmp_path / "projects" / "whatever").exists()


def test_remove_with_force_false_explicitly_still_refuses(tmp_path):
    ws = A.Workspace(tmp_path)
    try:
        ws.remove("whatever", force=False)
        raise AssertionError("expected BeadsError when force=False")
    except A.BeadsError as e:
        assert "force" in str(e) or "confirmation" in str(e)


def test_remove_rejects_invalid_name_before_touching_disk(tmp_path):
    ws = A.Workspace(tmp_path)
    try:
        ws.remove("bad.dotted.name", force=True)
        raise AssertionError("expected BeadsError for an invalid project name")
    except A.BeadsError as e:
        assert "invalid project name" in str(e)
    assert not (tmp_path / "projects" / "bad.dotted.name").exists()
