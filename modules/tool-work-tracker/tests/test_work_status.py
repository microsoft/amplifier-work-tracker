"""`work_status` -- the multi-project aggregate. Part of the same
2026-08-15 envelope-honesty fix as `test_result_guard.py`, but a distinct
gap: NOT an uncaught exception, but a real, caught `A.BeadsError` that got
recorded as a string inside one project's entry while the overall
`ToolResult` still reported `success=True`. That is the invisible-failure
pattern in miniature -- the error was visible in the text, just not in the
one field any automated caller actually checks.

`Workspace.names()` only requires a `.beads` DIRECTORY to exist (see
`adapter.py`) -- it never runs `bd init`. So a "broken" project below is
fabricated as a bare `.beads/` directory with nothing inside it, never a
real `bd`-initialized database. `bd list --json` against that genuinely
fails (confirmed manually: exit 0, but non-JSON `Error: no beads database
found...` on stdout, which `adapter._json` turns into a real BeadsError) --
this is a REAL failure through the REAL code path, not a mocked-away
assertion, and it never touches the shared dolt server at all.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_status_reports_success_when_there_is_nothing_to_report(tmp_path, monkeypatch):
    """The legitimate empty case -- no projects at all -- must stay
    success=True. This is 'the operation succeeded and the answer is
    empty', not a failure, and must never regress alongside the fix
    below."""
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(tmp_path / "root"))
    session = WorkTrackerSession({"actor": _unique("actor")})

    result = await session.status()

    assert result.success is True
    output: dict[str, Any] = result.output  # type: ignore[assignment]
    assert output["projects"] == []


@pytest.mark.asyncio
async def test_status_reports_failure_when_a_project_cannot_be_listed(tmp_path, monkeypatch):
    """THE fix under test: a real BeadsError while listing one project must
    flip the OVERALL envelope to success=False. Before the fix, this same
    scenario returned success=True with the error merely embedded as text
    -- machine-invisible, exactly the audited bug."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))

    broken_name = "brokenproj"
    (root / "projects" / broken_name / ".beads").mkdir(parents=True)

    session = WorkTrackerSession({"actor": _unique("actor")})
    result = await session.status()

    output: dict[str, Any] = result.output  # type: ignore[assignment]
    entry = next(p for p in output["projects"] if p["project"] == broken_name)
    assert "ERROR" in entry["status"]

    # The actual regression this test guards: the error must not be
    # invisible to the outer envelope.
    assert result.success is False


@pytest.mark.asyncio
async def test_status_still_reports_every_healthy_project_alongside_a_broken_one(
    tmp_path, monkeypatch
):
    """Preserve the existing information density: one broken project must
    not hide the healthy ones -- `success=False` is the honest SIGNAL, not
    a reason to drop data the caller can still use."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))

    healthy_session = WorkTrackerSession({"actor": _unique("actor")})
    healthy_name = _unique("healthyproj")
    from amplifier_work_tracker import adapter as A

    A.Workspace(root).create(healthy_name)
    try:
        broken_name = "brokenproj2"
        (root / "projects" / broken_name / ".beads").mkdir(parents=True)

        result = await healthy_session.status()
        output: dict[str, Any] = result.output  # type: ignore[assignment]
        by_name = {p["project"]: p for p in output["projects"]}

        assert by_name[healthy_name]["total"] == 0
        assert "ERROR" in by_name[broken_name]["status"]
        assert result.success is False
    finally:
        A.drop_database(healthy_name)
        shutil.rmtree(A.Workspace(root).path(healthy_name), ignore_errors=True)


@pytest.mark.asyncio
async def test_status_row_carries_the_full_per_status_breakdown(tmp_path, monkeypatch):
    """i7f-status: each project row is now the full `project_summary`
    breakdown -- per-status counts (ready/held/intake/blocked/deferred/
    resolved) plus aging/throughput -- not just the old total/ready/held.
    Skipped when `bd` is absent (the module-level pytestmark)."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))

    from amplifier_work_tracker import adapter as A

    name = _unique("breakdownproj")
    ws = A.Workspace(root)
    ws.create(name)
    try:
        session = WorkTrackerSession({"actor": _unique("actor")})
        add = WorkTrackerSession({"actor": _unique("adder")})
        await add.add(name, "ready one")
        held_added = await add.add(name, "held one")
        held_id = held_added.output["added"]  # type: ignore[index]
        claimer = WorkTrackerSession({"actor": _unique("claimer")})
        assert (await claimer.claim(name, item_id=held_id)).success is True

        result = await session.status()
        assert result.success is True
        output: dict[str, Any] = result.output  # type: ignore[assignment]
        row = next(p for p in output["projects"] if p["project"] == name)

        assert row["status"] == A.STATUS_OK
        assert row["total"] == 2
        assert row["ready"] == 1
        assert row["held"] == 1
        # The full breakdown fields that the hand-rolled ready/held counts
        # never carried.
        for key in ("intake", "blocked", "resolved", "deferred", "held_stale", "held_by"):
            assert key in row
        assert row["held_by"] == [claimer._actor]  # noqa: SLF001

        await claimer.resolve(held_id, "test cleanup")
    finally:
        A.drop_database(name)
        shutil.rmtree(ws.path(name), ignore_errors=True)


@pytest.mark.asyncio
async def test_claim_on_an_empty_queue_still_reports_success_with_claimed_null(
    tmp_path, monkeypatch
):
    """The load-bearing contract that must NOT regress alongside this fix:
    an empty queue is a normal terminal outcome, not a failure -- it must
    keep reporting success=True with claimed: None, telling the agent to
    stop rather than invent work."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))

    from amplifier_work_tracker import adapter as A

    name = _unique("emptyqproj")
    A.Workspace(root).create(name)
    try:
        session = WorkTrackerSession({"actor": _unique("actor")})
        result = await session.claim(name)

        assert result.success is True
        output: dict[str, Any] = result.output  # type: ignore[assignment]
        assert output["claimed"] is None
    finally:
        A.drop_database(name)
        shutil.rmtree(A.Workspace(root).path(name), ignore_errors=True)
