"""`work_subscribe` / `work_unsubscribe` / `work_subscriptions` +
`WorkTrackerSession.reminder_snapshot` (amplifier-bxq, lane:gb-subscribe).

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves subscriptions actually reflect live project
state via `adapter.project_summary`, not just that our own Python agrees
with itself.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

import amplifier_work_tracker.adapter as A
import amplifier_work_tracker.custody as C

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "subproj"


@pytest.mark.asyncio
async def test_subscribe_is_idempotent_and_validates_project(project):
    session = WorkTrackerSession({"actor": _unique("sub")})

    first = await session.subscribe(project)
    assert first.success is True
    out: dict[str, Any] = first.output  # type: ignore[assignment]
    assert out["subscribed"] == project
    assert out["already_subscribed"] is False
    assert out["subscriptions"] == [project]

    second = await session.subscribe(project)
    assert second.success is True
    out2: dict[str, Any] = second.output  # type: ignore[assignment]
    assert out2["already_subscribed"] is True
    assert out2["subscriptions"] == [project]  # still no duplicate


@pytest.mark.asyncio
async def test_subscribe_refuses_unknown_project():
    session = WorkTrackerSession({"actor": _unique("sub")})
    result = await session.subscribe("no-such-project-at-all")
    assert result.success is False


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent(project):
    session = WorkTrackerSession({"actor": _unique("sub")})
    await session.subscribe(project)

    removed = await session.unsubscribe(project)
    assert removed.success is True
    out: dict[str, Any] = removed.output  # type: ignore[assignment]
    assert out["was_subscribed"] is True
    assert out["subscriptions"] == []

    # Unsubscribing again (never subscribed) is a no-op, still success.
    removed_again = await session.unsubscribe(project)
    assert removed_again.success is True
    out2: dict[str, Any] = removed_again.output  # type: ignore[assignment]
    assert out2["was_subscribed"] is False


@pytest.mark.asyncio
async def test_subscriptions_lists_current_state(project):
    session = WorkTrackerSession({"actor": _unique("sub")})
    empty = await session.subscriptions()
    assert empty.output == {"subscriptions": []}  # type: ignore[comparison-overlap]

    await session.subscribe(project)
    listed = await session.subscriptions()
    assert listed.output == {"subscriptions": [project]}  # type: ignore[comparison-overlap]


@pytest.mark.asyncio
async def test_claim_auto_subscribes_to_its_project(project):
    """work_claim's documented default: claiming from a project subscribes
    this session to it automatically, with no separate work_subscribe call.
    """
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "auto-subscribe probe")
    item_id = added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    assert (await claim_session.subscriptions()).output == {"subscriptions": []}  # type: ignore[comparison-overlap]

    claimed = await claim_session.claim(project, item_id=item_id)
    assert claimed.success is True

    subs = await claim_session.subscriptions()
    assert subs.output == {"subscriptions": [project]}  # type: ignore[comparison-overlap]

    await claim_session.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_reminder_snapshot_reports_subscribed_project_counts(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    await add_session.add(project, "reminder probe: ready")

    session = WorkTrackerSession({"actor": _unique("sub")})
    await session.subscribe(project)

    snapshot = await session.reminder_snapshot()
    assert snapshot["holding"] is None
    projects = snapshot["subscriptions"]
    assert len(projects) == 1
    row = projects[0]
    assert row["project"] == project
    assert row["status"] == A.STATUS_OK
    assert row["ready"] == 1
    assert row["held"] == 0


@pytest.mark.asyncio
async def test_reminder_snapshot_empty_when_no_subscriptions():
    session = WorkTrackerSession({"actor": _unique("sub")})
    snapshot = await session.reminder_snapshot()
    assert snapshot == {"subscriptions": [], "holding": None}


@pytest.mark.asyncio
async def test_reminder_snapshot_reports_holding_and_fresh_custody(project):
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "reminder probe: held")
    item_id = added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=item_id)
    assert claimed.success is True

    snapshot = await claim_session.reminder_snapshot()
    holding = snapshot["holding"]
    assert holding is not None
    assert holding["project"] == project
    assert holding["id"] == item_id
    # Just claimed -- custody was just established, so it must be fresh.
    assert holding["custody_stale"] is False

    await claim_session.resolve(item_id, "test cleanup")


def _backdate_custody(bd: A.Beads, item_id: str, holder: str, *, last_seen: str) -> None:
    """Test-only reach into the real custody record to manufacture
    staleness with no sleep: reads the current record (written by
    `take_custody`), overwrites ONLY `last_seen` with an ancient
    timestamp, and writes it back via the exact same low-level `bd
    update --metadata` mechanism `adapter.Beads.renew_custody` itself
    uses (see that method) -- never a monkeypatch of `CUSTODY_TTL_SECONDS`,
    which would NOT work here: `reclaim_eligible`'s `ttl` parameter default
    is bound at module-import time, so patching the module attribute
    afterward has no effect on a call that (like `reminder_snapshot`'s)
    never passes `ttl=` explicitly.
    """
    current = bd.get_custody(item_id)
    assert current is not None
    updated = dict(current)
    updated["last_seen"] = last_seen
    p = bd._run(  # noqa: SLF001 -- test-only reach, mirrors adapter.py's own internal pattern
        ["update", item_id, "--metadata", __import__("json").dumps({C.CUSTODY_KEY: updated})],
        actor=holder,
    )
    assert p.returncode == 0, p.stderr


@pytest.mark.asyncio
async def test_reminder_snapshot_reports_custody_stale_true_past_ttl(project):
    """Backdates the held item's own custody `last_seen` well past
    `CUSTODY_TTL_SECONDS` to prove `reminder_snapshot` surfaces staleness
    truthfully via the real `custody.reclaim_eligible` check (never a
    fabricated value). See `_backdate_custody` for why this -- not a TTL
    monkeypatch -- is the correct way to manufacture staleness here.
    """
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "reminder probe: stale")
    item_id = added.output["added"]  # type: ignore[index]

    claim_session = WorkTrackerSession({"actor": _unique("claimer")})
    claimed = await claim_session.claim(project, item_id=item_id)
    assert claimed.success is True

    bd = claim_session._project(project)  # noqa: SLF001 -- test-only reach
    ancient = "2000-01-01T00:00:00Z"
    assert C.age_seconds(ancient) > C.CUSTODY_TTL_SECONDS
    _backdate_custody(bd, item_id, claim_session._actor, last_seen=ancient)  # noqa: SLF001

    snapshot = await claim_session.reminder_snapshot()
    holding = snapshot["holding"]
    assert holding is not None
    assert holding["custody_stale"] is True

    await claim_session.resolve(item_id, "test cleanup")


@pytest.mark.asyncio
async def test_reminder_snapshot_never_mutates_or_touches_custody(project):
    """Read-only, like `stats`/`status`: repeated calls must never change
    project state.
    """
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    await add_session.add(project, "reminder probe: no mutation")

    session = WorkTrackerSession({"actor": _unique("sub")})
    await session.subscribe(project)

    bd = A.Workspace(session._ws.root).project(project)  # noqa: SLF001

    def snapshot_state():
        items = bd.list(include_resolved=True)
        return {i.id: (i.status, i.holder) for i in items}

    before = snapshot_state()
    await session.reminder_snapshot()
    await session.reminder_snapshot()
    after = snapshot_state()
    assert before == after
