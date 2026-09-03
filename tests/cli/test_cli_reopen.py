"""Tier 3 -- `amplifier-work-tracker reopen`, and `resolve`'s refusal on a
closed item, as a real subprocess.

The exit CODE is the assertion that matters here. A warning printed beside a
JSON payload does not survive piping, `--json` consumers, or an agent reading
only the structured result -- the exit code is the one channel every consumer
already checks, which is why a divergent resolve must FAIL rather than warn.

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


def test_reopen_then_correct_end_to_end(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    wrong = "the original, wrong resolution"
    right = "the corrected resolution"

    assert (
        run_cli(["resolve", "--project", project, "--id", item_id, "--reason", wrong]).returncode
        == 0
    )
    assert _row(run_cli, project, item_id)["status"] == "resolved"

    result = run_cli(
        [
            "reopen",
            "--project",
            project,
            "--id",
            item_id,
            "--reason",
            "the stored text is wrong",
            "--actor",
            unique_actor,
        ]
    )
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["reopened"] == item_id
    assert payload["status"] != "resolved"
    # The old text comes back to the caller, who is about to rewrite it.
    assert payload["previous_resolution"] == wrong
    assert payload["previous_closed_at"]
    # The accounting cost is stated, not hidden.
    assert payload["closed_at_cleared"] is True
    # --claim is OPT-IN on this surface (a shell claim strands custody).
    assert payload["claimed"] is False

    assert _row(run_cli, project, item_id)["status"] != "resolved"
    fixed = run_cli(["resolve", "--project", project, "--id", item_id, "--reason", right])
    assert fixed.returncode == 0, fixed.stderr
    assert _row(run_cli, project, item_id)["resolution"].strip() == right


def test_reopen_with_claim_flag_claims_the_item(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    assert (
        run_cli(["resolve", "--project", project, "--id", item_id, "--reason", "first"]).returncode
        == 0
    )

    result = run_cli(
        [
            "reopen",
            "--project",
            project,
            "--id",
            item_id,
            "--reason",
            "correcting",
            "--actor",
            unique_actor,
            "--claim",
        ]
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["claimed"] is True
    assert payload["holder"] == unique_actor
    assert _row(run_cli, project, item_id)["status"] == "held"


def test_reopen_refuses_an_item_that_is_not_resolved(run_cli, unique_project_name):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)

    result = run_cli(["reopen", "--project", project, "--id", item_id, "--reason", "why"])
    assert result.returncode != 0
    assert "nothing to reopen" in (result.stdout + result.stderr)
    assert _row(run_cli, project, item_id)["status"] == "open"


def test_resolve_on_a_closed_item_with_different_text_exits_nonzero_and_writes_nothing(
    run_cli, unique_project_name
):
    """The headline behaviour change. Before this, the command exited 0 and
    printed the OLD text under `"resolution"` as if the new one had landed."""
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    stored = "the original resolution"
    assert (
        run_cli(["resolve", "--project", project, "--id", item_id, "--reason", stored]).returncode
        == 0
    )

    result = run_cli(
        [
            "resolve",
            "--project",
            project,
            "--id",
            item_id,
            "--reason",
            "a completely different resolution",
        ]
    )
    assert result.returncode != 0, result.stdout
    combined = result.stdout + result.stderr
    assert "NOTHING WAS WRITTEN" in combined
    assert stored in combined
    assert "a completely different resolution" in combined
    assert f"reopen --project {project} --id {item_id}" in combined
    # Literally true: the record is untouched.
    assert _row(run_cli, project, item_id)["resolution"].strip() == stored


def test_resolve_with_identical_text_exits_zero_and_says_it_was_idempotent(
    run_cli, unique_project_name
):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    text = "the one true resolution"

    first = run_cli(["resolve", "--project", project, "--id", item_id, "--reason", text])
    assert first.returncode == 0, first.stderr
    assert "idempotent" not in json.loads(first.stdout)

    again = run_cli(["resolve", "--project", project, "--id", item_id, "--reason", text])
    assert again.returncode == 0, again.stderr
    _util.assert_no_silent_failure(again)
    assert json.loads(again.stdout)["idempotent"] is True
