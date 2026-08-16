"""Tier 3 -- the `amplifier-work-tracker rename` subcommand as a real
subprocess: does it rename end-to-end, cross-check via a real `list` on the
new name, and fail LOUDLY (non-zero, no silent-success) on its refusal gates?

See tests/cli/test_cli_surface.py's module docstring for why this tier
exists at all (two shipped commands that failed while exiting 0). Every
assertion here either checks the real exit code or funnels through
`_util.assert_no_silent_failure`.
"""

from __future__ import annotations

import json
import shutil
import uuid

import pytest

from amplifier_work_tracker import adapter as A

from .. import _util

pytestmark = pytest.mark.cli


@pytest.fixture
def rename_pair(workspace):
    """`(old, new)` unique names with teardown of BOTH from server and disk."""
    old = f"cold{uuid.uuid4().hex[:12]}"
    new = f"cnew{uuid.uuid4().hex[:12]}"
    yield old, new
    for name in (old, new):
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(workspace.path(name), ignore_errors=True)


def test_rename_end_to_end_via_cli(run_cli, rename_pair):
    old, new = rename_pair
    assert run_cli(["new", old]).returncode == 0
    add = run_cli(["add", "--project", old, "an item"])
    assert add.returncode == 0, add.stderr
    added_id = json.loads(add.stdout)["added"]

    result = run_cli(["rename", old, new])
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["renamed"] == old
    assert payload["to"] == new
    assert payload["items"] == 1
    assert payload["old_database_dropped"] is True

    # Cross-check with a REAL `list` on the new name: the item survived with
    # its original id, and the new project is readable.
    listed = run_cli(["list", "--project", new, "--json"])
    assert listed.returncode == 0, listed.stderr
    ids = [row["id"] for row in json.loads(listed.stdout)["items"]]
    assert ids == [added_id]

    # The old name is gone -- listing it must fail loudly, not return empty.
    gone = run_cli(["list", "--project", old, "--json"])
    assert gone.returncode != 0
    _util.assert_no_silent_failure(gone)


def test_rename_to_taken_name_fails_loudly(run_cli, rename_pair):
    old, new = rename_pair
    assert run_cli(["new", old]).returncode == 0
    assert run_cli(["new", new]).returncode == 0

    result = run_cli(["rename", old, new])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "already exists" in (result.stdout + result.stderr)

    # Non-destructive: both still list successfully.
    assert run_cli(["list", "--project", old, "--json"]).returncode == 0
    assert run_cli(["list", "--project", new, "--json"]).returncode == 0


def test_rename_missing_source_fails_loudly(run_cli, rename_pair):
    old, new = rename_pair
    result = run_cli(["rename", old, new])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "not found" in (result.stdout + result.stderr)
