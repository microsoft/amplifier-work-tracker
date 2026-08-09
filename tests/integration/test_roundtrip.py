"""Tier 2 -- the golden path: create -> claim -> resolve, and the notifier
propagating a real resolution back to a report, read back through the real
Gateway (not just at the adapter layer).

Uses the shared session project (`shared_bd`) with a unique lane per test so
tests never interfere with each other regardless of execution order.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def test_create_claim_resolve_roundtrip(shared_bd: A.Beads, unique_lane, unique_actor):
    item_id = shared_bd.create(
        "roundtrip probe",
        tags=[unique_lane],
        description="does the thing",
        acceptance="Given/When/Then",
        priority=1,
    )

    # Not yet claimed: shows up as open in the lane.
    listed = [i.id for i in shared_bd.list(lane=unique_lane)]
    assert item_id in listed

    claimed = shared_bd.claim_next(lane=unique_lane, actor=unique_actor)
    assert claimed is not None
    assert claimed.id == item_id
    assert claimed.holder == unique_actor
    assert claimed.status == "held"
    assert claimed.acceptance == "Given/When/Then"

    resolved = shared_bd.resolve(item_id, "Fixed: root-caused and shipped", actor=unique_actor)
    assert resolved.status == "resolved"
    assert resolved.resolution == "Fixed: root-caused and shipped"

    # Readback via a fresh `get()` -- not just the return value of resolve().
    back = shared_bd.get(item_id)
    assert back.status == "resolved"
    assert back.resolution == "Fixed: root-caused and shipped"


def test_claim_returns_none_on_an_empty_lane(shared_bd: A.Beads, unique_lane, unique_actor):
    assert shared_bd.claim_next(lane=unique_lane, actor=unique_actor) is None


def test_notifier_flips_linked_report_and_reporter_reads_back_the_resolution(
    workspace_root,
    shared_project_name,
    shared_bd: A.Beads,
    unique_lane,
    unique_actor,
    gateway_server,
):
    """The reason to build any of this: a report gets linked to engineering
    work, the work gets resolved, `amplifier-work-tracker notify` propagates
    that back, and the reporter's own read path (the Gateway, not a raw `bd
    show`) shows the real resolution text."""
    reporter_id = f"reporter-{unique_actor}"

    report_id = shared_bd.create(
        "user says: it forgot my name",
        tags=[A.LANE_INTAKE, unique_lane],
        meta={"reporter_id": reporter_id, "verbatim": "it forgot my name"},
        actor=reporter_id,
    )
    issue_id = shared_bd.create(
        "fix: profile not rehydrated on reconnect",
        tags=[A.LANE_WORK, unique_lane],
        acceptance="Given a reconnect, the profile is rehydrated",
        discovered_from=[report_id],
    )

    claimed = shared_bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    # The shared project may have other lane:eng items from other tests
    # running concurrently -- claim until we get ours (bounded, since the
    # queue only shrinks).
    seen = []
    while claimed is not None and claimed.id != issue_id:
        seen.append(claimed.id)
        claimed = shared_bd.claim_next(lane=A.LANE_WORK, actor=unique_actor)
    assert claimed is not None and claimed.id == issue_id, (
        f"never claimed {issue_id}; claimed instead: {seen}"
    )

    reason = "Resolved by profile-rehydrate-fix: profile block rehydrated on reconnect"
    shared_bd.resolve(issue_id, reason, actor=unique_actor)

    # Beads does not propagate this on its own -- run the real notifier CLI.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "amplifier_work_tracker.cli",
            "notify",
            "--project",
            shared_project_name,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "AMPLIFIER_WORK_TRACKER_ROOT": str(workspace_root)},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    flipped = json.loads(proc.stdout)
    flipped_ids = [f["report"] for f in flipped["flipped"]]
    assert report_id in flipped_ids

    # Adapter-level readback.
    report_back = shared_bd.get(report_id)
    assert report_back.status == "resolved"
    assert "profile block rehydrated on reconnect" in (report_back.resolution or "")

    # Reporter-level readback: the actual path Alice's product agent uses.
    token = gateway_server.mint(reporter_id, shared_project_name)
    status, body = gateway_server.request("GET", f"/reports/{report_id}", token=token)
    assert status == 200
    assert body["status"] == "resolved"
    assert len(body["work"]) == 1
    assert body["work"][0]["issue_id"] == issue_id
    assert "profile block rehydrated on reconnect" in body["work"][0]["resolution"]
