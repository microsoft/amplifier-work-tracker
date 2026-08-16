"""Tier 3 -- CLI status-breakdown surface: `instances`' cheap per-status
counts and the `status` subcommand's per-project detail view.

Both read paths share one computation (`adapter.project_summary`), so these
tests assert the SAME breakdown is visible two ways: the multi-project
`instances --json` table, and the single-project `status --project <p>
--json` detail view. A manual count from `bd list --status <s>`-equivalent
state (built directly via `workspace.project(...)`) is the ground truth
each assertion is checked against -- never a re-derivation of the CLI's own
counting logic.
"""

from __future__ import annotations

import json
import os

import pytest

from amplifier_work_tracker import adapter as A

from .. import _util

pytestmark = pytest.mark.cli


def _set_status(bd, item_id: str, status: str) -> None:
    """Force an item to a specific Beads status directly, bypassing the
    adapter's own vocabulary (which has no generic setter) -- test setup
    only, exactly like the existing `dep --blocks` pattern in
    tests/integration/test_directed_claim.py."""
    bd._run(["update", item_id, "--status", status])  # noqa: SLF001


def test_status_breakdown_matches_manual_count(
    run_cli, workspace, unique_project_name, unique_lane, unique_actor
):
    """The literal acceptance criterion: one project with one item in each
    of open/held/blocked/deferred/resolved must show the correct count for
    each state in `status --project <p> --json`, cross-checked against a
    manual count built directly from `workspace.project(...)`."""
    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)

    # "ready" specifically requires LANE_WORK -- `unique_lane` is a random
    # lane on purpose everywhere else, but the one item meant to count as
    # ready must carry the real work lane.
    open_id = bd.create("status open", tags=[A.LANE_WORK], priority=1)
    held_id = bd.create("status held", tags=[unique_lane], priority=1)
    blocked_id = bd.create("status blocked", tags=[unique_lane], priority=1)
    deferred_id = bd.create("status deferred", tags=[unique_lane], priority=1)
    resolved_id = bd.create("status resolved", tags=[unique_lane], priority=1)

    bd.claim_item(held_id, actor=unique_actor)
    _set_status(bd, blocked_id, "blocked")
    _set_status(bd, deferred_id, "deferred")
    bd.resolve(resolved_id, "status test cleanup", actor=unique_actor)

    # Manual ground truth, from the same live project, computed independently
    # of anything cmd_status/cmd_instances do internally.
    items = bd.list(include_resolved=True)
    manual = {
        "total": len(items),
        "ready": sum(1 for i in items if i.status == "open" and A.LANE_WORK in i.tags),
        "held": sum(1 for i in items if i.status == "held"),
        "blocked": sum(1 for i in items if i.status == "blocked"),
        "deferred": sum(1 for i in items if i.status == "deferred"),
        "resolved": sum(1 for i in items if i.status == "resolved"),
    }
    assert manual == {
        "total": 5,
        "ready": 1,
        "held": 1,
        "blocked": 1,
        "deferred": 1,
        "resolved": 1,
    }, f"test setup itself doesn't match intent: {manual}"

    result = run_cli(["status", "--project", name, "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "ok"
    assert body["total"] == manual["total"]
    assert body["ready"] == manual["ready"]
    assert body["held"] == manual["held"]
    assert body["blocked"] == manual["blocked"]
    assert body["deferred"] == manual["deferred"]
    assert body["resolved"] == manual["resolved"]
    assert body["held_by"] == [unique_actor]
    _util.assert_no_silent_failure(result)

    # The human-readable rendering must show every count too, not just JSON.
    text_result = run_cli(["status", "--project", name])
    assert text_result.returncode == 0, text_result.stderr
    assert f"TOTAL:     {manual['total']}" in text_result.stdout
    assert f"BLOCKED:   {manual['blocked']}" in text_result.stdout
    assert f"DEFERRED:  {manual['deferred']}" in text_result.stdout
    assert f"RESOLVED:  {manual['resolved']}" in text_result.stdout
    _util.assert_no_silent_failure(text_result)

    bd.release(held_id)
    bd.resolve(held_id, "status test cleanup", actor=unique_actor)
    bd.resolve(open_id, "status test cleanup", actor=unique_actor)
    bd.resolve(blocked_id, "status test cleanup", actor=unique_actor)
    bd.resolve(deferred_id, "status test cleanup", actor=unique_actor)


def test_instances_json_gains_blocked_deferred_resolved_counts(
    run_cli, workspace, unique_project_name, unique_lane, unique_actor
):
    """`instances --json` (the cheap, multi-project summary) must show the
    SAME blocked/deferred/resolved counts `status` shows for the same
    project -- the two paths share one computation and must never
    disagree."""
    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)

    blocked_id = bd.create("instances blocked", tags=[unique_lane], priority=1)
    deferred_id = bd.create("instances deferred", tags=[unique_lane], priority=1)
    resolved_id = bd.create("instances resolved", tags=[unique_lane], priority=1)
    _set_status(bd, blocked_id, "blocked")
    _set_status(bd, deferred_id, "deferred")
    bd.resolve(resolved_id, "instances test cleanup", actor=unique_actor)

    instances_result = run_cli(["instances", "--json"])
    assert instances_result.returncode == 0, instances_result.stderr
    rows = {r["project"]: r for r in json.loads(instances_result.stdout)}
    assert name in rows
    row = rows[name]
    assert row["blocked"] == 1
    assert row["deferred"] == 1
    assert row["resolved"] == 1
    _util.assert_no_silent_failure(instances_result)

    status_result = run_cli(["status", "--project", name, "--json"])
    assert status_result.returncode == 0, status_result.stderr
    detail = json.loads(status_result.stdout)
    assert detail["blocked"] == row["blocked"]
    assert detail["deferred"] == row["deferred"]
    assert detail["resolved"] == row["resolved"]
    _util.assert_no_silent_failure(status_result)

    # instances' human-readable table must show the same breakdown columns.
    instances_text = run_cli(["instances"])
    assert instances_text.returncode == 0, instances_text.stderr
    assert "BLOCK" in instances_text.stdout
    assert "DEFER" in instances_text.stdout
    assert "RESOLV" in instances_text.stdout
    _util.assert_no_silent_failure(instances_text)

    bd.resolve(blocked_id, "instances test cleanup", actor=unique_actor)
    bd.resolve(deferred_id, "instances test cleanup", actor=unique_actor)


def test_status_on_unknown_project_gives_distinct_error(run_cli, unique_project_name):
    """`status` on a project that was never created must fail loudly, not
    report a misleadingly healthy empty breakdown -- a directed single-
    project read, like `list --project`, not a multi-project listing."""
    result = run_cli(["status", "--project", unique_project_name])
    assert result.returncode != 0
    assert "not found" in result.stderr
    _util.assert_no_silent_failure(result)


def test_status_never_mutates_project_state(
    run_cli, workspace, unique_project_name, unique_lane, unique_actor
):
    """`status` is read-only -- full project state before and after must be
    identical, exactly like the existing `list` no-mutation guard."""
    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)
    bd.create("status no-mutation open", tags=[unique_lane], priority=1)
    held_id = bd.create("status no-mutation held", tags=[unique_lane], priority=1)
    bd.claim_item(held_id, actor=unique_actor)

    def snapshot():
        items = bd.list(include_resolved=True)
        return {i.id: (i.status, i.holder, i.resolution) for i in items}

    before = snapshot()
    result = run_cli(["status", "--project", name, "--json"])
    assert result.returncode == 0, result.stderr
    after = snapshot()

    assert before == after
    bd.resolve(held_id, "status no-mutation cleanup", actor=unique_actor)


def test_status_on_project_stuck_creating_reports_creating_not_a_healthy_zero(
    run_cli, workspace, unique_project_name
):
    """Mirrors `cmd_instances`'s own regression guard (2026-08-15 outage):
    a project caught mid-`new` must report `creating`, never a healthy-
    looking zeroed breakdown.

    `status` runs as a real subprocess (see `run_cli`), so the "creating"
    state must be simulated with a REAL `.create.lock` file on disk --
    monkeypatching `Workspace.creation_state` in this test process would
    have no effect on the subprocess. The lock names this test process's
    own pid, which is alive for the duration of the test, exactly matching
    what `Workspace.creation_state` reads (see `adapter._read_lock_pid`/
    `_pid_alive`).
    """
    name = unique_project_name
    project_dir = workspace.path(name)
    project_dir.mkdir(parents=True)
    (project_dir / ".create.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = run_cli(["status", "--project", name, "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["project"] == name
    assert "creating" in body["status"]
    assert "total" not in body
    _util.assert_no_silent_failure(result)
