"""Tier 3 -- the `amplifier-work-tracker move` subcommand as a real
subprocess: does it move one item end-to-end, cross-check via a real `list`
on both projects, and fail LOUDLY (non-zero, no silent-success) on its
refusal gates?

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
def move_pair(workspace):
    """`(src, dst)` unique project names, with teardown of BOTH from the
    server and disk regardless of which end up existing after a given test.
    """
    src = f"csrc{uuid.uuid4().hex[:12]}"
    dst = f"cdst{uuid.uuid4().hex[:12]}"
    yield src, dst
    for name in (src, dst):
        try:
            A.drop_database(name)
        finally:
            shutil.rmtree(workspace.path(name), ignore_errors=True)


def test_move_end_to_end_via_cli(run_cli, move_pair):
    src, dst = move_pair
    assert run_cli(["new", src]).returncode == 0
    assert run_cli(["new", dst]).returncode == 0
    add = run_cli(["add", "--project", src, "an item"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    result = run_cli(["move", "--item", item_id, "--from", src, "--to", dst])
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["moved"] == item_id
    assert payload["from"] == src
    assert payload["to"] == dst
    assert payload["dropped_dependency_edges"] == []

    # Cross-check with a REAL `list` on the destination: the item is there
    # with its original id.
    listed = run_cli(["list", "--project", dst, "--json"])
    assert listed.returncode == 0, listed.stderr
    ids = [row["id"] for row in json.loads(listed.stdout)["items"]]
    assert ids == [item_id]

    # And gone from the source -- an empty (not erroring) list.
    src_listed = run_cli(["list", "--project", src, "--json"])
    assert src_listed.returncode == 0, src_listed.stderr
    assert json.loads(src_listed.stdout)["items"] == []


def test_move_missing_item_fails_loudly(run_cli, move_pair):
    src, dst = move_pair
    assert run_cli(["new", src]).returncode == 0
    assert run_cli(["new", dst]).returncode == 0

    result = run_cli(["move", "--item", "no-such-item", "--from", src, "--to", dst])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "no such item" in (result.stdout + result.stderr)


def test_move_held_item_fails_loudly(run_cli, move_pair):
    src, dst = move_pair
    assert run_cli(["new", src]).returncode == 0
    assert run_cli(["new", dst]).returncode == 0
    add = run_cli(["add", "--project", src, "held item"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]
    claim = run_cli(["claim", "--project", src, "--actor", "cli-tester", "--id", item_id])
    assert claim.returncode == 0, claim.stderr

    result = run_cli(["move", "--item", item_id, "--from", src, "--to", dst])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "HELD" in (result.stdout + result.stderr)

    # Non-destructive: still listable (and held) in the source.
    still_there = run_cli(["list", "--project", src, "--json"])
    assert still_there.returncode == 0, still_there.stderr
    rows = json.loads(still_there.stdout)["items"]
    assert [row["id"] for row in rows] == [item_id]
    assert rows[0]["status"] == "held"


def test_move_missing_destination_fails_loudly(run_cli, move_pair):
    src, dst = move_pair
    assert run_cli(["new", src]).returncode == 0
    add = run_cli(["add", "--project", src, "an item"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    result = run_cli(["move", "--item", item_id, "--from", src, "--to", dst])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "does not exist" in (result.stdout + result.stderr)

    # Untouched -- still in the source.
    still_there = run_cli(["list", "--project", src, "--json"])
    assert still_there.returncode == 0, still_there.stderr
    assert [row["id"] for row in json.loads(still_there.stdout)["items"]] == [item_id]
