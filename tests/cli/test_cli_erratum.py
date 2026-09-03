"""Tier 3 -- `amplifier-work-tracker erratum` as a real subprocess: happy
path, refusal on an OPEN item, `list --id`'s rendering of the resolution +
errata, and the plain `list` table's corrected marker.

See tests/cli/test_cli_surface.py's module docstring for why this tier
exists at all (two shipped commands that failed while exiting 0).
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


def test_erratum_happy_path_end_to_end(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    resolution = "the original, published verdict"
    assert (
        run_cli(
            ["resolve", "--project", project, "--id", item_id, "--reason", resolution]
        ).returncode
        == 0
    )

    result = run_cli(
        [
            "erratum",
            "--project",
            project,
            "--id",
            item_id,
            "--actor",
            unique_actor,
            "the recorded reason was misleading",
        ]
    )
    assert result.returncode == 0, result.stderr
    _util.assert_no_silent_failure(result)
    payload = json.loads(result.stdout)
    assert payload["id"] == item_id
    assert payload["corrected"] is True
    assert payload["errata"] == [
        {
            "at": payload["errata"][0]["at"],
            "by": unique_actor,
            "text": "the recorded reason was misleading",
        }
    ]
    assert "already_recorded" not in payload

    # The resolution FIELD itself is untouched, and the item is still
    # resolved -- an erratum never rewrites what was actually published.
    row = _row(run_cli, project, item_id)
    assert row["resolution"].strip() == resolution
    assert row["status"] == "resolved"
    assert row["corrected"] is True


def test_erratum_same_text_re_append_is_idempotent(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    assert (
        run_cli(["resolve", "--project", project, "--id", item_id, "--reason", "closed"]).returncode
        == 0
    )
    text = "the same correction, byte for byte"

    first = run_cli(
        ["erratum", "--project", project, "--id", item_id, "--actor", unique_actor, text]
    )
    assert first.returncode == 0, first.stderr
    assert "already_recorded" not in json.loads(first.stdout)

    again = run_cli(
        ["erratum", "--project", project, "--id", item_id, "--actor", "a-different-actor", text]
    )
    assert again.returncode == 0, again.stderr
    _util.assert_no_silent_failure(again)
    payload = json.loads(again.stdout)
    assert payload["already_recorded"] is True
    assert len(payload["errata"]) == 1


def test_erratum_refuses_an_item_that_is_not_resolved(run_cli, unique_project_name, unique_actor):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)

    result = run_cli(
        [
            "erratum",
            "--project",
            project,
            "--id",
            item_id,
            "--actor",
            unique_actor,
            "doesn't matter",
        ]
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "'resolved'" in combined
    assert "edit" in combined.lower()
    row = _row(run_cli, project, item_id)
    assert row["corrected"] is False


def test_list_id_renders_resolution_then_errata_with_corrected_marker(
    run_cli, unique_project_name, unique_actor
):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    item_id = _add_item(run_cli, project)
    resolution = "closed out"
    assert (
        run_cli(
            ["resolve", "--project", project, "--id", item_id, "--reason", resolution]
        ).returncode
        == 0
    )
    assert (
        run_cli(
            [
                "erratum",
                "--project",
                project,
                "--id",
                item_id,
                "--actor",
                unique_actor,
                "the reason was wrong",
            ]
        ).returncode
        == 0
    )

    result = run_cli(["list", "--project", project, "--id", item_id])
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "RESOLUTION: [corrected]" in out
    assert resolution in out
    assert "ERRATUM " in out
    assert unique_actor in out
    assert "the reason was wrong" in out


def test_list_table_marks_corrected_items_with_a_one_token_suffix(
    run_cli, unique_project_name, unique_actor
):
    project = unique_project_name
    assert run_cli(["new", project]).returncode == 0
    plain_id = _add_item(run_cli, project, "plain item")
    corrected_id = _add_item(run_cli, project, "corrected item")
    for iid in (plain_id, corrected_id):
        assert (
            run_cli(["resolve", "--project", project, "--id", iid, "--reason", "done"]).returncode
            == 0
        )
    assert (
        run_cli(
            [
                "erratum",
                "--project",
                project,
                "--id",
                corrected_id,
                "--actor",
                unique_actor,
                "wrong reason",
            ]
        ).returncode
        == 0
    )

    result = run_cli(["list", "--project", project])
    assert result.returncode == 0, result.stderr
    lines = {ln.split()[0]: ln for ln in result.stdout.splitlines() if ln.strip()}
    assert plain_id in lines
    assert corrected_id in lines
    assert "resolved*" in lines[corrected_id]
    assert "resolved*" not in lines[plain_id]
    assert "corrected via erratum" in result.stdout
