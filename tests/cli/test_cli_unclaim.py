"""Tier 3 -- the `amplifier-work-tracker unclaim` subcommand as a real
subprocess: does it release a held item back to the ready queue WITHOUT a
resolution end-to-end, cross-check via a real `list`, prove the item is
re-claimable, and fail LOUDLY (non-zero, no silent-success) on its refusal
gates (item not held, item not found)?

Mirrors tests/cli/test_cli_rename.py's discipline: every assertion either
checks the real exit code or funnels through `_util.assert_no_silent_failure`.
See tests/cli/test_cli_surface.py's module docstring for why this tier exists
at all (two shipped commands that failed while exiting 0).
"""

from __future__ import annotations

import json

import pytest

from .. import _util

pytestmark = pytest.mark.cli


def _add_item(run_cli, project: str, title: str = "an item") -> str:
    add = run_cli(["add", "--project", project, title])
    assert add.returncode == 0, add.stderr
    return json.loads(add.stdout)["added"]


def _row(run_cli, project: str, item_id: str) -> dict:
    listed = run_cli(["list", "--project", project, "--json"])
    assert listed.returncode == 0, listed.stderr
    return next(r for r in json.loads(listed.stdout)["items"] if r["id"] == item_id)


def test_unclaim_releases_held_item_end_to_end(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)

    claimed = run_cli(["claim", "--project", project, "--actor", unique_actor])
    assert claimed.returncode == 0, claimed.stderr
    assert json.loads(claimed.stdout)["claimed"] == item_id
    assert _row(run_cli, project, item_id)["status"] == "held"

    result = run_cli(["unclaim", "--project", project, "--id", item_id])
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["unclaimed"] == item_id
    assert payload["status"] != "held"

    # Cross-check with a REAL `list`: the item is no longer held and carries
    # NO resolution -- it was reopened, not closed.
    row = _row(run_cli, project, item_id)
    assert row["status"] != "held"
    assert not row.get("resolution")

    # And it is genuinely back on the queue: a DIFFERENT actor can claim it.
    reclaim = run_cli(["claim", "--project", project, "--actor", unique_actor + "b"])
    assert reclaim.returncode == 0, reclaim.stderr
    assert json.loads(reclaim.stdout)["claimed"] == item_id


def test_unclaim_sets_no_resolution_unlike_resolve(run_cli, unique_project_name, unique_actor):
    """The property that makes `unclaim` distinct from `resolve`: it must NOT
    close the item or attach a reason. Contrast with a real `resolve`, which
    does both.
    """
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    assert run_cli(["claim", "--project", project, "--actor", unique_actor]).returncode == 0

    result = run_cli(["unclaim", "--project", project, "--id", item_id])
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)

    row = _row(run_cli, project, item_id)
    assert row["status"] == "open"
    assert not row.get("resolution")


def test_unclaim_not_held_fails_loudly_and_mutates_nothing(
    run_cli, unique_project_name, unique_actor
):
    """An open (never-claimed) item cannot be unclaimed -- there is nothing to
    release. It must fail loudly and leave the item exactly as it was, never a
    silent no-op.
    """
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)

    before = _row(run_cli, project, item_id)
    assert before["status"] == "open"

    result = run_cli(["unclaim", "--project", project, "--id", item_id])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
    assert "not held" in (result.stdout + result.stderr)

    # Non-destructive: the item is untouched and still claimable.
    after = _row(run_cli, project, item_id)
    assert after["status"] == "open"
    assert run_cli(["claim", "--project", project, "--actor", unique_actor]).returncode == 0


def test_unclaim_missing_item_fails_loudly(run_cli, unique_project_name):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0

    result = run_cli(["unclaim", "--project", project, "--id", "wt-does-not-exist"])
    assert result.returncode != 0
    _util.assert_no_silent_failure(result)
