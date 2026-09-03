"""Tier 3 -- the real CLI surface, end to end, under a REAL unreachable server.

The three verbs named in lane `model_performance-8zv`, exercised as a coding
agent actually runs them: a real `amplifier-work-tracker` subprocess, a real
`dolt` binary, a real item that really exists -- and a dolt port that is
genuinely closed, so the transport failure is real rather than injected and
lands PAST `_run_dolt_sql_bounded`'s retry budget.

Measured before the fix (lane `model_performance-rpz`), under a transient
dolt read failure:

    claim --id <existing>  -> "item not found"                     9 of 12
    list  --id <existing>  -> "item 'X' not found in project 'Y'"  2 of 8
                              (cause discarded entirely)
    instances              -> healthy project printed as ERROR     5 of 10

Every unreachable-server assertion below is paired with a healthy-server one
asserting today's absence wording is UNCHANGED. That pairing is the point:
a fix that makes every "not found" say "maybe transient" has replaced one lie
with another, and would pass the first half of this file while failing the
second.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.cli


def _closed_port() -> int:
    """A TCP port with nothing listening on it -- bind, read, release."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def unreachable_env():
    """The real environment, with the dolt port pointed at a closed one.

    Not a mock: `dolt` really runs, really fails to connect, and the CLI
    really burns its bounded transport-retry budget before reporting. This
    is the condition every deliverable in this lane is phrased against
    ("past the retry budget").
    """
    env = dict(os.environ)
    env["AMPLIFIER_WORK_TRACKER_DOLT_PORT"] = str(_closed_port())
    return env


@pytest.fixture
def live_item(workspace, unique_project_name, unique_lane):
    """A project and an item that genuinely EXIST on the healthy server."""
    name = unique_project_name
    workspace.create(name)
    bd = workspace.project(name)
    item_id = bd.create("unavailable-vs-absent CLI probe", tags=[unique_lane], priority=1)
    return name, item_id


# ============================================== list --id  (get_readonly)


def test_list_id_on_an_existing_item_does_not_deny_it_when_the_db_is_unreachable(
    run_cli, live_item, unreachable_env
):
    """The worst of the three: `list --id` is the exact path
    `context/awareness.md` hazard #6 tells agents to trust as the safe
    recovery after an ambiguous write. It used to answer a bare "not found"
    -- cause discarded -- for an item the caller HELD."""
    name, item_id = live_item
    r = run_cli(["list", "--project", name, "--id", item_id], env=unreachable_env)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0, "an unreachable database must not report success"
    assert "not found in project" not in out, out
    assert "connection refused" in out.lower() or "unreachable" in out.lower(), (
        f"the underlying cause was discarded: {out!r}"
    )


def test_list_id_on_a_genuinely_absent_item_is_UNCHANGED(run_cli, live_item):
    """No-blurring guardrail. Healthy server, item genuinely absent -- the
    same words as before, with no 'maybe transient' hedge."""
    name, _ = live_item
    absent = f"{name}-nosuchid"
    r = run_cli(["list", "--project", name, "--id", absent])
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0
    assert f"item '{absent}' not found in project '{name}'" in out, out
    assert "unavailable" not in out.lower(), out


# ================================================= claim --id  (claim_item)


def test_claim_id_on_an_existing_item_does_not_say_item_not_found_when_unreachable(
    run_cli, live_item, unreachable_env
):
    """`claim_item`'s docstring promises three outcomes "deliberately never
    conflated"; infrastructure-unavailable is a fourth, and it was folded
    into the first."""
    name, item_id = live_item
    r = run_cli(
        ["claim", "--project", name, "--actor", "probe-unavail", "--id", item_id],
        env=unreachable_env,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0
    assert "item not found" not in out.lower(), out
    assert "connection refused" in out.lower() or "unreachable" in out.lower(), out


def test_claim_id_on_a_genuinely_absent_item_is_UNCHANGED(run_cli, live_item):
    """No-blurring guardrail, claim side."""
    name, _ = live_item
    absent = f"{name}-nosuchid"
    r = run_cli(["claim", "--project", name, "--actor", "probe-absent", "--id", absent])
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0
    assert f"cannot claim {absent}: item not found" in out, out


# ======================================================== instances


def test_instances_reports_UNAVAILABLE_not_ERROR_when_the_db_is_unreachable(
    run_cli, live_item, unreachable_env
):
    """`ERROR` asserts the project's data is unreadable. A distinct status --
    neither `ok` nor `ERROR` -- is what this table was missing."""
    name, _ = live_item
    r = run_cli(["instances", "--json"], env=unreachable_env)
    rows = json.loads(r.stdout)
    row = next(row for row in rows if row["project"] == name)
    status = row["status"]
    assert A.is_unavailable_status(status), status
    assert not status.startswith("ERROR:"), status
    assert status != A.STATUS_OK
    assert "total" not in row or row.get("total") is None


def test_instances_on_a_healthy_server_is_UNCHANGED(run_cli, live_item):
    """No-blurring guardrail, summary side: a reachable project still reads
    plainly `ok`, with real counts."""
    name, _ = live_item
    r = run_cli(["instances", "--json"])
    rows = json.loads(r.stdout)
    row = next(row for row in rows if row["project"] == name)
    assert row["status"] == A.STATUS_OK
    assert row["total"] is not None
