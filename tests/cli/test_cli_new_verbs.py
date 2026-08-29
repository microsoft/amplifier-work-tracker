"""Tier 3 -- the `edit`/`defer`/`block`/`dep` subcommands as real
subprocesses: does each exist, run, and exit non-zero on failure?

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
def cli_project(run_cli, workspace):
    name = f"cliv{uuid.uuid4().hex[:12]}"
    assert run_cli(["new", name]).returncode == 0
    yield name
    try:
        A.drop_database(name)
    finally:
        shutil.rmtree(workspace.path(name), ignore_errors=True)


def test_edit_amends_fields_via_cli(run_cli, cli_project):
    add = run_cli(["add", "--project", cli_project, "original title"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    result = run_cli(["edit", "--project", cli_project, "--id", item_id, "--title", "new title"])
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["edited"] == item_id
    assert payload["title"] == "new title"


def test_edit_merge_into_supersedes_via_cli(run_cli, cli_project):
    old = run_cli(["add", "--project", cli_project, "old item"])
    assert old.returncode == 0, old.stderr
    old_id = json.loads(old.stdout)["added"]
    new = run_cli(["add", "--project", cli_project, "new item"])
    assert new.returncode == 0, new.stderr
    new_id = json.loads(new.stdout)["added"]

    result = run_cli(["edit", "--project", cli_project, "--id", old_id, "--merge-into", new_id])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["superseded"] == old_id
    assert payload["with"] == new_id
    assert payload["status"] == "resolved"


def test_edit_refuses_combining_merge_into_with_fields(run_cli, cli_project):
    add = run_cli(["add", "--project", cli_project, "combo probe"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    result = run_cli(
        [
            "edit",
            "--project",
            cli_project,
            "--id",
            item_id,
            "--title",
            "x",
            "--merge-into",
            "some-other-id",
        ]
    )
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)


def test_defer_then_clear_via_cli(run_cli, cli_project):
    add = run_cli(["add", "--project", cli_project, "defer me"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    deferred = run_cli(["defer", "--project", cli_project, "--id", item_id, "--reason", "not now"])
    assert deferred.returncode == 0, deferred.stderr
    assert json.loads(deferred.stdout)["status"] == "deferred"

    cleared = run_cli(["defer", "--project", cli_project, "--id", item_id, "--clear"])
    assert cleared.returncode == 0, cleared.stderr
    assert json.loads(cleared.stdout)["status"] == "open"


def test_defer_without_reason_fails_loudly(run_cli, cli_project):
    add = run_cli(["add", "--project", cli_project, "no reason probe"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    result = run_cli(["defer", "--project", cli_project, "--id", item_id])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)


def test_block_then_clear_via_cli(run_cli, cli_project):
    add = run_cli(["add", "--project", cli_project, "block me"])
    assert add.returncode == 0, add.stderr
    item_id = json.loads(add.stdout)["added"]

    blocked = run_cli(
        ["block", "--project", cli_project, "--id", item_id, "--reason", "needs review"]
    )
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout)["status"] == "blocked"

    cleared = run_cli(["block", "--project", cli_project, "--id", item_id, "--clear"])
    assert cleared.returncode == 0, cleared.stderr
    assert json.loads(cleared.stdout)["status"] == "open"


def test_dep_declares_and_displays_edge_via_cli(run_cli, cli_project):
    blocker = run_cli(["add", "--project", cli_project, "blocker item"])
    assert blocker.returncode == 0, blocker.stderr
    blocker_id = json.loads(blocker.stdout)["added"]
    blocked = run_cli(["add", "--project", cli_project, "blocked item"])
    assert blocked.returncode == 0, blocked.stderr
    blocked_id = json.loads(blocked.stdout)["added"]

    result = run_cli(
        ["dep", "--project", cli_project, "--id", blocked_id, "--depends-on", blocker_id]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == blocked_id
    assert any(link["id"] == blocker_id for link in payload["links"])

    display_only = run_cli(["dep", "--project", cli_project, "--id", blocked_id])
    assert display_only.returncode == 0, display_only.stderr
    assert any(link["id"] == blocker_id for link in json.loads(display_only.stdout)["links"])


def test_dep_missing_item_fails_loudly(run_cli, cli_project):
    result = run_cli(
        ["dep", "--project", cli_project, "--id", "no-such-id", "--depends-on", "also-missing"]
    )
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
