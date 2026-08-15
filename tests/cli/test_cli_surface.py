"""Tier 3 -- the CLI surface itself: does every `amplifier-work-tracker`
subcommand exist, run, and exit non-zero on failure?

This tier exists specifically because of two shipped bugs (in this project's
predecessor):

  1. `heartbeat` / `reap` called `bd heartbeat` / `bd reclaim` -- commands
     present in the Beads *source* but absent from the v1.1.2 *release*.
     Neither had ever actually been run.
  2. `reap` printed `Error: unknown command "reclaim"` to stderr and still
     returned exit code 0.

Both bugs have the same shape: a command that fails silently, in the
direction of "nothing to see here." Every test below either exercises the
real subprocess exit code directly, or funnels through
`tests._util.assert_no_silent_failure`, which encodes that invariant
generically: if the combined stdout+stderr looks like an error, the exit
code MUST be non-zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from amplifier_work_tracker import adapter as A

from .. import _util

pytestmark = pytest.mark.cli

# Keep in sync with cli.py's `sub.add_parser(...)` calls.
SUBCOMMANDS = [
    "doctor",
    "new",
    "remove",
    "add",
    "instances",
    "list",
    "claim",
    "custody",
    "reap",
    "resolve",
    "notify",
]


# --------------------------------------------------------- existence checks


def test_help_lists_every_subcommand(run_cli):
    result = run_cli(["--help"])
    assert result.returncode == 0
    for cmd in SUBCOMMANDS:
        assert cmd in result.stdout, f"subcommand {cmd!r} missing from --help output"


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_each_subcommand_is_recognized_by_argparse(run_cli, cmd):
    result = run_cli([cmd, "--help"])
    assert result.returncode == 0, f"`amplifier-work-tracker {cmd} --help` failed: {result.stderr}"


def test_capabilities_probe_matches_the_installed_bd_binary():
    """Every `bd` subcommand `amplifier_work_tracker.adapter` actually
    invokes must exist in the installed binary -- this is the loud,
    fast-failing guard against ever again depending on a command the
    release doesn't ship (bug #1)."""
    caps = A.capabilities()
    core = ["ready", "create", "show", "list", "close", "update"]
    missing = [c for c in core if not caps.get(c)]
    assert not missing, (
        f"amplifier_work_tracker.adapter depends on bd subcommands absent "
        f"from the installed binary: {missing}. "
        f"Fix scope: amplifier_work_tracker/adapter.py only."
    )


# ------------------------------------------------------- run + exit codes


def test_new_rejects_dotted_name_with_nonzero_exit(run_cli):
    result = run_cli(["new", "bad.dotted.name"])
    assert result.returncode != 0
    assert "invalid project name" in result.stderr
    _util.assert_no_silent_failure(result)


def test_new_is_idempotent_on_a_valid_name(run_cli, unique_project_name):
    first = run_cli(["new", unique_project_name])
    assert first.returncode == 0, first.stderr
    second = run_cli(["new", unique_project_name])
    assert second.returncode == 0, second.stderr
    _util.assert_no_silent_failure(first)
    _util.assert_no_silent_failure(second)


def test_new_reports_created_not_adopted_for_a_genuinely_fresh_project(
    run_cli, unique_project_name
):
    result = run_cli(["new", unique_project_name])
    assert result.returncode == 0, result.stderr
    assert "created project" in result.stdout
    assert "ADOPTED" not in result.stdout
    _util.assert_no_silent_failure(result)


def test_new_reports_adoption_loudly_when_directory_gone_but_database_survives(
    run_cli, workspace, unique_project_name
):
    """CLI-level regression test for the resurrection bug: once the local
    directory is gone but the shared-server database survives, `new` must
    say ADOPTED (never bare "created") and name how many items came with
    it."""
    import shutil

    name = unique_project_name
    first = run_cli(["new", name])
    assert first.returncode == 0, first.stderr
    bd = workspace.project(name)
    bd.create("cli adoption probe item", tags=["lane:cli_adoption_probe"], priority=1)
    shutil.rmtree(workspace.path(name), ignore_errors=True)

    second = run_cli(["new", name])
    assert second.returncode == 0, second.stderr
    assert "ADOPTED" in second.stdout
    assert "created project" not in second.stdout
    assert "1 existing item" in second.stdout
    _util.assert_no_silent_failure(second)

    run_cli(["remove", name, "--yes"])


def test_remove_without_yes_exits_nonzero(run_cli, workspace, unique_project_name):
    name = unique_project_name
    created = run_cli(["new", name])
    assert created.returncode == 0, created.stderr

    result = run_cli(["remove", name])
    assert result.returncode != 0
    assert "--yes" in result.stderr
    _util.assert_no_silent_failure(result)

    # Nothing was touched by the refused attempt.
    assert workspace.path(name).exists()
    run_cli(["remove", name, "--yes"])


def test_remove_with_yes_drops_both_directory_and_database(run_cli, workspace, unique_project_name):
    """`.beads` and the database are ours to drop; the directory itself
    survives because `bd init` leaves its own tool-integration scaffolding
    (`.git`, `AGENTS.md`, ...) behind -- see the adapter-level test of the
    same name for the full explanation. This is the CLI-surface proof of
    the same contract."""
    name = unique_project_name
    created = run_cli(["new", name])
    assert created.returncode == 0, created.stderr

    result = run_cli(["remove", name, "--yes"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["beads_removed"] is True
    assert body["database_removed"] is True
    assert not (workspace.path(name) / ".beads").exists()
    assert body["leftover"], "bd's own scaffolding (.git etc) is expected to remain"
    _util.assert_no_silent_failure(result)

    import shutil

    shutil.rmtree(workspace.path(name), ignore_errors=True)


def test_remove_refuses_via_cli_while_an_item_is_held(
    run_cli, workspace, unique_project_name, unique_actor
):
    name = unique_project_name
    created = run_cli(["new", name])
    assert created.returncode == 0, created.stderr
    bd = workspace.project(name)
    item_id = bd.create("cli removal-refusal probe", tags=["lane:cli_removal_refusal"], priority=1)
    bd.claim_item(item_id, actor=unique_actor)

    result = run_cli(["remove", name, "--yes"])
    assert result.returncode != 0
    assert item_id in result.stderr
    assert "HELD" in result.stderr
    _util.assert_no_silent_failure(result)

    bd.release(item_id)
    run_cli(["remove", name, "--yes"])


def test_remove_of_nonexistent_project_gives_distinct_error(run_cli, unique_project_name):
    result = run_cli(["remove", unique_project_name, "--yes"])
    assert result.returncode != 0
    assert "not found" in result.stderr
    _util.assert_no_silent_failure(result)


def test_instances_on_a_fresh_empty_root_exits_zero(run_cli, tmp_path):
    empty_root_env = dict(os.environ)
    empty_root_env["AMPLIFIER_WORK_TRACKER_ROOT"] = str(tmp_path / "empty")
    result = run_cli(["instances"], env=empty_root_env)
    assert result.returncode == 0
    assert "no projects" in result.stdout
    _util.assert_no_silent_failure(result)


def test_instances_json_is_well_formed(run_cli, shared_project_name):
    result = run_cli(["instances", "--json"])
    assert result.returncode == 0
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    assert any(r["project"] == shared_project_name for r in rows)


def test_list_shows_mixed_states_with_id_title_status_holder_resolution(
    run_cli, workspace, shared_project_name, unique_lane, unique_actor
):
    """The literal acceptance criterion: one project with some ready, some
    held, some closed items -- `list --json` must show id/title/status/
    holder for all of them, and holder must actually be populated for the
    held item (the field `work_status` conspicuously lacks)."""
    bd = workspace.project(shared_project_name)
    open_id = bd.create("cli-list open", tags=[unique_lane], priority=1)
    held_id = bd.create("cli-list held", tags=[unique_lane], priority=1)
    closed_id = bd.create("cli-list closed", tags=[unique_lane], priority=1)
    bd.claim_item(held_id, actor=unique_actor)
    bd.resolve(closed_id, "cli-list resolution text", actor="cli-list-resolver")

    result = run_cli(["list", "--project", shared_project_name, "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    by_id = {row["id"]: row for row in body["items"]}

    assert by_id[open_id]["status"] == "open"
    assert by_id[open_id]["holder"] is None

    assert by_id[held_id]["status"] == "held"
    assert by_id[held_id]["holder"] == unique_actor

    assert by_id[closed_id]["status"] == "resolved"
    assert by_id[closed_id]["resolution"] == "cli-list resolution text"
    _util.assert_no_silent_failure(result)

    bd.resolve(held_id, "test cleanup", actor=unique_actor)


def test_list_status_filter_returns_only_matching_status(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    open_id = bd.create("cli-list-filter open", tags=[unique_lane], priority=1)
    held_id = bd.create("cli-list-filter held", tags=[unique_lane], priority=1)
    bd.claim_item(held_id, actor="cli-list-filter-actor")

    result = run_cli(["list", "--project", shared_project_name, "--status", "held", "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    ids = {row["id"] for row in body["items"]}
    assert held_id in ids
    assert open_id not in ids
    for row in body["items"]:
        assert row["status"] == "held"
    _util.assert_no_silent_failure(result)

    bd.resolve(held_id, "test cleanup", actor="cli-list-filter-actor")


def test_list_rejects_unknown_status_via_argparse_choices(run_cli, shared_project_name):
    result = run_cli(["list", "--project", shared_project_name, "--status", "bogus"])
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_list_never_mutates_project_state(
    run_cli, workspace, shared_project_name, unique_lane, unique_actor
):
    """Calling `list` must never claim, mutate, or touch custody -- full
    project state before and after must be identical."""
    bd = workspace.project(shared_project_name)
    bd.create("cli-list no-mutation open", tags=[unique_lane], priority=1)
    held_id = bd.create("cli-list no-mutation held", tags=[unique_lane], priority=1)
    bd.claim_item(held_id, actor=unique_actor)

    def snapshot():
        items = bd.list(include_resolved=True)
        return {i.id: (i.status, i.holder, i.resolution) for i in items}

    before = snapshot()
    result = run_cli(["list", "--project", shared_project_name, "--json"])
    assert result.returncode == 0, result.stderr
    result2 = run_cli(["list", "--project", shared_project_name, "--status", "held", "--json"])
    assert result2.returncode == 0, result2.stderr
    after = snapshot()

    assert before == after
    bd.resolve(held_id, "test cleanup", actor=unique_actor)


def test_list_on_a_project_with_no_matching_items_exits_zero_with_empty_list(
    run_cli, shared_project_name, unique_lane
):
    """An unused lane guarantees zero items for THIS status filter, without
    needing a brand-new project -- proving the empty case is a normal,
    non-error outcome, not a crash."""
    result = run_cli(["list", "--project", shared_project_name, "--status", "deferred", "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["items"] == []
    assert body["total_count"] == 0
    assert body["truncated"] is False
    _util.assert_no_silent_failure(result)


def test_list_on_nonexistent_project_gives_distinct_error(run_cli, unique_project_name):
    result = run_cli(["list", "--project", unique_project_name, "--json"])
    assert result.returncode != 0
    assert "not found" in result.stderr
    _util.assert_no_silent_failure(result)


def test_list_truncates_and_reports_it_explicitly(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    for n in range(4):
        bd.create(f"cli-list truncation probe {n}", tags=[unique_lane], priority=1)

    result = run_cli(
        ["list", "--project", shared_project_name, "--status", "open", "--limit", "2", "--json"]
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["returned_count"] == 2
    assert body["total_count"] >= 4
    assert body["truncated"] is True
    _util.assert_no_silent_failure(result)


def test_list_dash_dash_id_reads_full_body_without_claiming(
    run_cli, workspace, shared_project_name, unique_lane
):
    """The literal gap this feature closes: `list --id` must return the
    same acceptance/description/design body `claim` returns, for a
    specific item, WITHOUT claiming it -- and leave the item exactly as
    open/unheld as it found it."""
    bd = workspace.project(shared_project_name)
    item_id = bd.create(
        "cli directed-read probe",
        tags=[unique_lane],
        priority=1,
        description="a longer description of what needs doing" * 5,
        acceptance="Given X, When Y, Then Z",
    )

    result = run_cli(["list", "--project", shared_project_name, "--id", item_id, "--json"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["returned_count"] == 1
    assert body["total_count"] == 1
    assert body["truncated"] is False
    row = body["items"][0]
    assert row["id"] == item_id
    assert row["status"] == "open"
    assert row["holder"] is None
    assert "Given X, When Y, Then Z" == row["acceptance"]
    assert row["description"].startswith("a longer description")
    _util.assert_no_silent_failure(result)

    # Never claimed: still open, unheld.
    back = bd.get(item_id)
    assert back.status == "open"
    assert back.holder is None


def test_list_dash_dash_id_human_readable_output_includes_body_fields(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    item_id = bd.create(
        "cli directed-read human probe",
        tags=[unique_lane],
        priority=1,
        description="human-readable description marker XYZZY",
        acceptance="human-readable acceptance marker PLUGH",
    )

    result = run_cli(["list", "--project", shared_project_name, "--id", item_id])
    assert result.returncode == 0, result.stderr
    assert item_id in result.stdout
    assert "human-readable description marker XYZZY" in result.stdout
    assert "human-readable acceptance marker PLUGH" in result.stdout
    _util.assert_no_silent_failure(result)


def test_list_dash_dash_id_on_nonexistent_item_gives_distinct_error(run_cli, shared_project_name):
    result = run_cli(
        [
            "list",
            "--project",
            shared_project_name,
            "--id",
            f"{shared_project_name}-doesnotexist999",
        ]
    )
    assert result.returncode != 0
    assert "not found" in result.stderr
    _util.assert_no_silent_failure(result)


def test_list_dash_dash_id_with_id_from_a_different_project_gives_distinct_wrong_project_error(
    run_cli, workspace, shared_project_name, unique_project_name, unique_lane
):
    """A valid id, just not in THIS project -- must read distinctly from a
    plain not-found (bd's own error text is identical for both)."""
    other_name = unique_project_name
    created = run_cli(["new", other_name])
    assert created.returncode == 0, created.stderr
    other_bd = workspace.project(other_name)
    other_item_id = other_bd.create("wrong-project probe", tags=[unique_lane], priority=1)

    result = run_cli(["list", "--project", shared_project_name, "--id", other_item_id])
    assert result.returncode != 0
    assert "does not look like it belongs to project" in result.stderr
    assert shared_project_name in result.stderr
    _util.assert_no_silent_failure(result)


def test_list_dash_dash_id_never_mutates_the_item(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    item_id = bd.create("cli directed-read no-mutation probe", tags=[unique_lane], priority=1)

    def snapshot():
        i = bd.get(item_id)
        return (i.status, i.holder, i.meta)

    before = snapshot()
    for _ in range(3):
        result = run_cli(["list", "--project", shared_project_name, "--id", item_id, "--json"])
        assert result.returncode == 0, result.stderr
    after = snapshot()
    assert before == after


def test_list_dash_dash_id_ignores_status_and_limit(
    run_cli, workspace, shared_project_name, unique_lane
):
    """`--status`/`--limit` must not interfere with a directed `--id` read
    -- the item is returned regardless of its actual status matching (or
    not) whatever `--status` happens to also be passed."""
    bd = workspace.project(shared_project_name)
    item_id = bd.create("cli directed-read ignores-filters probe", tags=[unique_lane], priority=1)

    result = run_cli(
        [
            "list",
            "--project",
            shared_project_name,
            "--id",
            item_id,
            "--status",
            "resolved",
            "--limit",
            "1",
            "--json",
        ]
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["items"][0]["id"] == item_id


def test_add_creates_a_claimable_item_without_needing_lane_vocabulary(
    run_cli, shared_project_name, unique_actor
):
    """The literal acceptance criterion from the task: `add` creates a
    claimable item end-to-end -- add -> claim returns it. The caller never
    names `lane:eng` anywhere in this test."""
    add_result = run_cli(
        [
            "add",
            "--project",
            shared_project_name,
            "Add health check endpoint",
            "--description",
            "Implement a /health endpoint",
            "--acceptance",
            "GET /health returns 200",
        ]
    )
    assert add_result.returncode == 0, add_result.stderr
    added = json.loads(add_result.stdout)
    assert added["added"]
    assert added["project"] == shared_project_name
    _util.assert_no_silent_failure(add_result)

    claim_result = run_cli(
        [
            "claim",
            "--project",
            shared_project_name,
            "--actor",
            unique_actor,
            "--lane",
            added["lane"],
        ]
    )
    assert claim_result.returncode == 0, claim_result.stderr
    claimed = json.loads(claim_result.stdout)
    assert claimed["claimed"] == added["added"]


def test_claim_on_empty_queue_exits_3_and_prints_no_error(
    run_cli, shared_project_name, unique_actor, unique_lane
):
    """Exit code 3 on an empty queue is documented as a NORMAL outcome (see
    the `claiming-work-safely` skill / `awareness.md`), not an error -- must
    not be confused with a real failure, and must not print error-looking
    text."""
    result = run_cli(
        ["claim", "--project", shared_project_name, "--actor", unique_actor, "--lane", unique_lane]
    )
    assert result.returncode == 3
    assert json.loads(result.stdout) == {"claimed": None, "reason": "no ready work in lane"}
    assert result.stderr == ""


def test_claim_dash_dash_id_directs_a_claim_to_a_specific_item(
    run_cli, workspace, shared_project_name, unique_actor, unique_lane
):
    """The CLI counterpart to the directed-claim adapter tests: `claim
    --id` must claim the NAMED item, not whatever would have sorted first
    in the queue."""
    bd = workspace.project(shared_project_name)
    decoy_id = bd.create("cli directed-claim decoy", tags=[unique_lane], priority=1)
    target_id = bd.create("cli directed-claim target", tags=[unique_lane], priority=1)

    result = run_cli(
        [
            "claim",
            "--project",
            shared_project_name,
            "--actor",
            unique_actor,
            "--id",
            target_id,
        ]
    )
    assert result.returncode == 0, result.stderr
    claimed = json.loads(result.stdout)
    assert claimed["claimed"] == target_id
    _util.assert_no_silent_failure(result)

    # The decoy must be untouched.
    decoy_back = bd.get(decoy_id)
    assert decoy_back.status == "open"


def test_claim_dash_dash_id_on_an_already_held_item_exits_nonzero_naming_the_holder(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    item_id = bd.create("cli directed-claim already-held probe", tags=[unique_lane], priority=1)
    holder = f"cli-holder-{unique_lane[5:]}"
    bd.claim_item(item_id, actor=holder)

    result = run_cli(
        [
            "claim",
            "--project",
            shared_project_name,
            "--actor",
            f"cli-loser-{unique_lane[5:]}",
            "--id",
            item_id,
        ]
    )
    assert result.returncode != 0
    assert holder in result.stderr
    _util.assert_no_silent_failure(result)


def test_claim_dash_dash_id_on_nonexistent_id_exits_nonzero_with_distinct_error(
    run_cli, shared_project_name, unique_actor
):
    result = run_cli(
        [
            "claim",
            "--project",
            shared_project_name,
            "--actor",
            unique_actor,
            "--id",
            "definitely-not-a-real-id-98765",
        ]
    )
    assert result.returncode != 0
    assert "not found" in result.stderr
    _util.assert_no_silent_failure(result)


def test_claim_then_resolve_then_notify_full_cli_flow(
    run_cli, workspace, shared_project_name, unique_actor, unique_lane
):
    """Exercises the real CLI surface end-to-end (as opposed to
    tests/integration, which exercises the library) -- claim, resolve, and
    notify must each actually run and exit 0 on a real item."""
    bd = workspace.project(shared_project_name)
    # The report must NOT share the lane we claim from. Intake and work are
    # different lanes by design; tagging both with `unique_lane` made the
    # report claimable, and `claim` then returned whichever sorted first --
    # green locally, red in CI. Give the report its own intake lane.
    report_id = bd.create("cli-flow report", tags=[A.LANE_INTAKE, f"{unique_lane}-intake"])
    issue_id = bd.create(
        "cli-flow issue", tags=[A.LANE_WORK, unique_lane], discovered_from=[report_id]
    )

    claim_result = run_cli(
        ["claim", "--project", shared_project_name, "--actor", unique_actor, "--lane", unique_lane]
    )
    assert claim_result.returncode == 0, claim_result.stderr
    claimed = json.loads(claim_result.stdout)
    assert claimed["claimed"] == issue_id
    _util.assert_no_silent_failure(claim_result)

    resolve_result = run_cli(
        [
            "resolve",
            "--project",
            shared_project_name,
            "--id",
            issue_id,
            "--actor",
            unique_actor,
            "--reason",
            "Fixed: cli flow proof",
        ]
    )
    assert resolve_result.returncode == 0, resolve_result.stderr
    _util.assert_no_silent_failure(resolve_result)

    notify_result = run_cli(["notify", "--project", shared_project_name])
    assert notify_result.returncode == 0, notify_result.stderr
    flipped = json.loads(notify_result.stdout)
    assert report_id in [f["report"] for f in flipped["flipped"]]
    _util.assert_no_silent_failure(notify_result)


def test_resolve_by_a_reclaimed_stale_holder_exits_nonzero(
    run_cli, workspace, shared_project_name, unique_lane
):
    """CLI-level regression test for the fencing bug (#6): if a claim was
    taken over while an agent was away, that agent's `resolve` must fail
    loudly through the real CLI, not just at the adapter layer."""
    bd = workspace.project(shared_project_name)
    bd.create("fencing cli probe", tags=[A.LANE_WORK, unique_lane], priority=1)
    holder_a = f"stale-a-{unique_lane[5:]}"
    holder_b = f"fresh-b-{unique_lane[5:]}"

    item = bd.claim_next(lane=unique_lane, actor=holder_a)
    assert item is not None
    bd.release(item.id)
    taken = bd.claim_next(lane=unique_lane, actor=holder_b)
    assert taken is not None and taken.id == item.id

    result = run_cli(
        [
            "resolve",
            "--project",
            shared_project_name,
            "--id",
            item.id,
            "--actor",
            holder_a,
            "--reason",
            "should not be allowed",
        ]
    )
    assert result.returncode != 0
    assert "reclaimed while you were away" in result.stderr
    _util.assert_no_silent_failure(result)


def test_reap_on_a_clean_queue_exits_zero_with_no_error_text(run_cli, shared_project_name):
    """Happy-path companion to the historical reap bug: on a project with
    nothing to reclaim, `reap` must exit 0 and print no error text at
    all -- not `Error: unknown command "reclaim"` with exit 0."""
    result = run_cli(["reap", "--project", shared_project_name])
    assert result.returncode == 0, result.stderr
    assert "error" not in (result.stdout + result.stderr).lower()
    body = json.loads(result.stdout)
    assert "reclaimed" in body
    _util.assert_no_silent_failure(result)


def test_reap_reclaims_an_item_with_forged_stale_custody(
    run_cli, workspace, shared_project_name, unique_lane
):
    """Forces staleness via `--ttl-seconds -1` (age is never negative, so
    this is always stale) rather than sleeping for real -- deterministic
    and fast."""
    bd = workspace.project(shared_project_name)
    bd.create("reap probe", tags=[unique_lane], priority=1)
    actor = f"reapme-{unique_lane[5:]}"
    item = bd.claim_next(lane=unique_lane, actor=actor)
    assert item is not None
    bd.take_custody(item.id, holder=actor, pid=os.getpid(), host="test-host")

    result = run_cli(["reap", "--project", shared_project_name, "--ttl-seconds", "-1"])
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    reclaimed_ids = [r["id"] for r in body["reclaimed"]]
    assert item.id in reclaimed_ids
    _util.assert_no_silent_failure(result)

    back = bd.get(item.id)
    assert back.status == "open"


def test_custody_exits_nonzero_when_watched_pid_is_already_dead(
    run_cli, workspace, shared_project_name, unique_lane
):
    bd = workspace.project(shared_project_name)
    bd.create("custody dead-pid probe", tags=[unique_lane], priority=1)
    actor = f"deadpid-{unique_lane[5:]}"
    item = bd.claim_next(lane=unique_lane, actor=actor)
    assert item is not None

    # A pid essentially guaranteed not to exist right now.
    dead_pid = 2**31 - 1

    result = run_cli(
        [
            "custody",
            "--project",
            shared_project_name,
            "--actor",
            actor,
            "--id",
            item.id,
            "--pid",
            str(dead_pid),
        ]
    )
    assert result.returncode != 0
    assert "not a live process" in result.stderr
    _util.assert_no_silent_failure(result)


def test_custody_establishes_and_exits_cleanly_when_watched_pid_dies(
    run_cli, workspace, shared_project_name, unique_lane, workspace_root
):
    """Happy path for `custody`: establishes, then exits 0 on its own the
    moment the watched process disappears -- no separate supervisor
    lifecycle to leak."""
    bd = workspace.project(shared_project_name)
    bd.create("custody happy-path probe", tags=[unique_lane], priority=1)
    actor = f"custody-{unique_lane[5:]}"
    item = bd.claim_next(lane=unique_lane, actor=actor)
    assert item is not None

    watched = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(2)"],
    )
    env = dict(os.environ)
    env["AMPLIFIER_WORK_TRACKER_ROOT"] = str(workspace_root)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "amplifier_work_tracker.cli",
            "custody",
            "--project",
            shared_project_name,
            "--actor",
            actor,
            "--id",
            item.id,
            "--pid",
            str(watched.pid),
            "--interval",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    watched.wait(timeout=10)
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 0, stderr
    assert "established" in stdout
    assert "pid_exited" in stdout


# --------------------------------------------- bd-entirely-missing failures


@pytest.mark.parametrize(
    "args",
    [
        ["doctor", "--quick"],
        ["new", "whatever-name-does-not-matter"],
        ["instances"],
    ],
)
def test_commands_fail_loudly_when_bd_binary_is_entirely_absent(
    run_cli, env_without_bd, args, tmp_path
):
    """If `bd` is missing from PATH altogether, every command that shells
    out to it must fail with a non-zero exit -- never silently succeed."""
    env = dict(env_without_bd)
    env["AMPLIFIER_WORK_TRACKER_ROOT"] = str(tmp_path / "no-bd-root")
    result = run_cli(args, env=env)
    assert result.returncode != 0, (
        f"amplifier-work-tracker {args} exited 0 with `bd` entirely absent from PATH -- "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_doctor_quick_succeeds_against_the_real_installed_bd(run_cli):
    result = run_cli(["doctor", "--quick"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All" in result.stdout
    _util.assert_no_silent_failure(result)
