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
SUBCOMMANDS = ["doctor", "new", "instances", "claim", "custody", "reap", "resolve", "notify"]


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


def test_claim_on_empty_queue_exits_3_and_prints_no_error(
    run_cli, shared_project_name, unique_actor, unique_lane
):
    """Exit code 3 on an empty queue is documented as a NORMAL outcome
    (AGENT_PROTOCOL.md rule #4), not an error -- must not be confused with
    a real failure, and must not print error-looking text."""
    result = run_cli(
        ["claim", "--project", shared_project_name, "--actor", unique_actor, "--lane", unique_lane]
    )
    assert result.returncode == 3
    assert json.loads(result.stdout) == {"claimed": None, "reason": "no ready work in lane"}
    assert result.stderr == ""


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
