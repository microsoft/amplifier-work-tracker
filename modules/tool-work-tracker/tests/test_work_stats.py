"""`work_stats` -- the full per-status breakdown for ONE named project in a
single call, delegating to `adapter.project_summary` (the same computation
the CLI's `instances`/`status` commands and the web dashboard render).

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves the tool round-trips through the real
storage layer, not just that our own Python agrees with itself.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

import amplifier_work_tracker.adapter as A

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "statsproj"


@pytest.mark.asyncio
async def test_stats_reports_full_breakdown_for_one_project(project):
    """The core scenario: one project with a ready item and a held item,
    reported as the full per-status breakdown -- not just ready/held, but
    the whole ProjectSummary shape."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    await add_session.add(project, "stats probe: ready")
    held_added = await add_session.add(project, "stats probe: held")
    held_id = held_added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=held_id)
    assert claimed.success is True

    stats_session = WorkTrackerSession({"actor": _unique("stats")})
    result = await stats_session.stats(project)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]

    assert out["project"] == project
    assert out["status"] == A.STATUS_OK
    assert out["total"] == 2
    assert out["ready"] == 1
    assert out["held"] == 1
    # The full breakdown fields the leaner status() never carried before
    # must all be present (a per-status roll-up, not just ready/held).
    for key in (
        "intake",
        "blocked",
        "resolved",
        "deferred",
        "held_stale",
        "held_by",
        "oldest_unclaimed_age_seconds",
        "resolved_24h",
        "resolved_7d",
        "ready_age_buckets",
    ):
        assert key in out
    assert out["held_by"] == [claim_session._actor]  # noqa: SLF001

    await claim_session.resolve(held_id, "test cleanup")


@pytest.mark.asyncio
async def test_stats_empty_project_is_success_with_zeroes(project):
    stats_session = WorkTrackerSession({"actor": _unique("stats")})
    result = await stats_session.stats(project)
    assert result.success is True
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert out["status"] == A.STATUS_OK
    assert out["total"] == 0
    assert out["ready"] == 0
    assert out["held"] == 0


@pytest.mark.asyncio
async def test_stats_never_claims_or_mutates(project):
    """Read-only: this session's own `_held` stays None, and full project
    state before/after is identical."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    held_added = await add_session.add(project, "stats no-mutation held")
    held_id = held_added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    assert (await claim_session.claim(project, item_id=held_id)).success is True

    bd = A.Workspace(claim_session._ws.root).project(project)  # noqa: SLF001

    def snapshot():
        items = bd.list(include_resolved=True)
        return {i.id: (i.status, i.holder) for i in items}

    before = snapshot()
    stats_session = WorkTrackerSession({"actor": _unique("stats")})
    await stats_session.stats(project)
    assert stats_session._held is None  # noqa: SLF001
    after = snapshot()
    assert before == after

    await claim_session.resolve(held_id, "test cleanup")


@pytest.mark.asyncio
async def test_stats_on_unreadable_project_reports_failure(tmp_path, monkeypatch):
    """A genuine read error (a bare `.beads/` dir, never a real database)
    must flip the envelope to success=False with an ERROR status -- the
    same honesty contract work_status keeps. This path never touches the
    shared dolt server."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))
    broken = "brokenstatsproj"
    (root / "projects" / broken / ".beads").mkdir(parents=True)

    session = WorkTrackerSession({"actor": _unique("stats")})
    result = await session.stats(broken)
    out: dict[str, Any] = result.output  # type: ignore[assignment]
    assert "ERROR" in out["status"]
    assert result.success is False
