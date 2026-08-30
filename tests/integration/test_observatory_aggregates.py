"""Tier 2 -- wt-v4 "Observatory" data aggregates (lane obs-data), against the
real `bd` binary and a real (isolated) shared dolt server.

Covers every function in adapter.py's "wt-v4 observability aggregates" block:
`velocity_series`/`velocity_windows`, `reopened_count`, `project_agents`/
`agents_snapshot`, `agent_stats`, `attention_items`. All of them read over the
existing contention-free `_dolt_sql`/`_dolt_sql_json` path (see that block's
own module-level comment for why), so these tests exercise the real shared
dolt server, not a mock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from amplifier_work_tracker import adapter as A
from amplifier_work_tracker import custody as C

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test-only introspection/setup helpers -- raw SQL against the isolated
# server, mirroring `test_item_move.py`'s own `_dep_rows` pattern (direct
# `_dolt_sql`/`_dolt_sql_json` for setup a test needs that no public seam
# exposes, e.g. backdating a timestamp bd itself always sets to "now").
# ---------------------------------------------------------------------------


def _backdate_issue(
    db: str,
    item_id: str,
    *,
    created_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> None:
    """Rewrite `item_id`'s `created_at`/`closed_at` directly, so velocity
    tests can exercise multiple calendar days without waiting real days.
    Both columns are UTC naive wall-clock (see `_parse_dolt_timestamp`'s
    docstring) -- `strftime` without a zone marker reproduces that shape.
    """
    sets = []
    if created_at is not None:
        sets.append(f"`created_at` = '{created_at.strftime('%Y-%m-%d %H:%M:%S')}'")
    if closed_at is not None:
        sets.append(f"`closed_at` = '{closed_at.strftime('%Y-%m-%d %H:%M:%S')}'")
    if not sets:
        return
    p = A._dolt_sql(  # noqa: SLF001 -- test setup only, see module docstring
        f"UPDATE `{db}`.`issues` SET {', '.join(sets)} WHERE `id` = '{item_id}'"
    )
    assert p.returncode == 0, p.stderr


def _backdate_event(db: str, item_id: str, event_type: str, *, days_ago: int) -> None:
    """Rewrite the `created_at` of `item_id`'s most recent `event_type` event
    to `days_ago` days before the SERVER'S OWN clock (`NOW()`, not a Python
    timestamp) -- `events.created_at` is populated by dolt's own
    `DEFAULT CURRENT_TIMESTAMP`, evaluated in the server's SYSTEM timezone,
    not UTC (see `reopened_count`'s docstring for the full empirical finding).
    Using `NOW() - INTERVAL` here, the same clock domain the column itself
    is written in, is what keeps this test correct regardless of what
    timezone the test host happens to run in.
    """
    p = A._dolt_sql(  # noqa: SLF001 -- test setup only, see module docstring
        f"UPDATE `{db}`.`events` SET `created_at` = NOW() - INTERVAL {int(days_ago)} DAY "
        f"WHERE `issue_id` = '{item_id}' AND `event_type` = '{event_type}' "
        f"ORDER BY `id` DESC LIMIT 1"
    )
    assert p.returncode == 0, p.stderr


def _set_custody(
    bd: A.Beads,
    item_id: str,
    *,
    holder: str,
    last_seen: str,
    generation: int = 1,
    declared_state: str = C.STATE_WORKING,
) -> None:
    """Write a custody record directly with an arbitrary `last_seen` --
    `take_custody`/`renew_custody` always stamp `last_seen` as "now", so a
    stale-custody fixture needs this direct write instead (mirrors the exact
    `bd update --metadata` mechanism those methods themselves use).
    """
    record = {
        "holder": holder,
        "pid": 1234,
        "host": "test-host",
        "started_at": last_seen,
        "last_seen": last_seen,
        "declared_state": declared_state,
        "declared_since": last_seen,
        "generation": generation,
    }
    p = bd._run(  # noqa: SLF001 -- test setup only, see module docstring
        ["update", item_id, "--metadata", json.dumps({C.CUSTODY_KEY: record})],
        actor=holder,
    )
    assert p.returncode == 0, p.stderr


# ---------------------------------------------------------------------------
# velocity_series / velocity_windows
# ---------------------------------------------------------------------------


def test_velocity_series_zero_fills_and_buckets_by_calendar_day(workspace, project_factory):
    name, bd = project_factory("velser")
    now = datetime.now(UTC)
    today = now.date()

    bd.create(title="today 1", kind="task")
    bd.create(title="today 2", kind="task")

    two_days_ago_id = bd.create(title="two days ago", kind="task")
    _backdate_issue(name, two_days_ago_id, created_at=now - timedelta(days=2))
    bd.claim_item(two_days_ago_id, actor="a")
    bd.resolve(two_days_ago_id, "done", actor="a")
    _backdate_issue(name, two_days_ago_id, closed_at=now - timedelta(days=2))

    series = A.velocity_series(name, days=7)

    assert len(series) == 7
    assert series[-1]["date"] == today.isoformat()
    assert series[-1]["created"] == 2
    assert series[-1]["resolved"] == 0

    by_date = {row["date"]: row for row in series}
    two_days_ago = (today - timedelta(days=2)).isoformat()
    assert by_date[two_days_ago]["created"] == 1
    assert by_date[two_days_ago]["resolved"] == 1

    # A day with zero real activity is a genuine zero, not a missing entry.
    three_days_ago = (today - timedelta(days=3)).isoformat()
    assert by_date[three_days_ago] == {"date": three_days_ago, "created": 0, "resolved": 0}

    # Every day in the window is present, oldest first.
    expected_dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    assert [row["date"] for row in series] == expected_dates


def test_velocity_series_reports_real_zero_for_wholly_quiet_project(workspace, project_factory):
    name, _bd = project_factory("velquiet")
    series = A.velocity_series(name, days=5)
    assert len(series) == 5
    assert all(row["created"] == 0 and row["resolved"] == 0 for row in series)


def test_velocity_windows_current_vs_previous_and_delta(workspace, project_factory):
    name, bd = project_factory("velwin")
    now = datetime.now(UTC)

    for i in range(3):
        bd.create(title=f"cur {i}", kind="task")

    prev_id = bd.create(title="prev", kind="task")
    _backdate_issue(name, prev_id, created_at=now - timedelta(days=10))

    windows = A.velocity_windows(name, days=7)

    assert windows["current"]["created"] == 3
    assert windows["previous"]["created"] == 1
    assert windows["delta_pct"]["created"] == pytest.approx(200.0)


def test_velocity_windows_delta_pct_none_when_previous_is_zero(workspace, project_factory):
    name, bd = project_factory("velwinzero")
    bd.create(title="only in current window", kind="task")
    windows = A.velocity_windows(name, days=7)
    assert windows["current"]["created"] == 1
    assert windows["previous"]["created"] == 0
    # Can't compute a meaningful percentage change off a zero baseline --
    # honestly None, never a fabricated +inf%% or 100%%.
    assert windows["delta_pct"]["created"] is None


# ---------------------------------------------------------------------------
# reopened_count
# ---------------------------------------------------------------------------


def test_reopened_count_counts_real_reopen_events(workspace, project_factory):
    name, bd = project_factory("reopn")
    item_id = bd.create(title="will reopen", kind="task")
    bd.claim_item(item_id, actor="a")
    bd.resolve(item_id, "done", actor="a")
    p = bd._run(["reopen", item_id, "--reason", "found bug"], actor="a")  # noqa: SLF001
    assert p.returncode == 0

    assert A.reopened_count(name, days=7) == 1


def test_reopened_count_zero_for_project_with_no_reopens(workspace, project_factory):
    name, bd = project_factory("noreopn")
    item_id = bd.create(title="never reopened", kind="task")
    bd.claim_item(item_id, actor="a")
    bd.resolve(item_id, "done", actor="a")
    assert A.reopened_count(name, days=7) == 0


def test_reopened_count_also_counts_reopen_via_plain_status_update(workspace, project_factory):
    """bd's own `reopen --help` text warns `bd update --status open` is less
    explicit than `bd reopen` -- verified empirically (see this module's
    investigation) that it STILL emits the identical `event_type='reopened'`
    row, so this path is counted too, not just the dedicated verb.
    """
    name, bd = project_factory("reopnalt")
    item_id = bd.create(title="alt reopen path", kind="task")
    bd.claim_item(item_id, actor="a")
    bd.resolve(item_id, "done", actor="a")
    p = bd._run(["update", item_id, "--status", "open"], actor="a")  # noqa: SLF001
    assert p.returncode == 0

    assert A.reopened_count(name, days=7) == 1


def test_reopened_count_respects_window_boundary(workspace, project_factory):
    name, bd = project_factory("reopnwin")
    item_id = bd.create(title="old reopen", kind="task")
    bd.claim_item(item_id, actor="a")
    bd.resolve(item_id, "done", actor="a")
    p = bd._run(["reopen", item_id, "--reason", "old bug"], actor="a")  # noqa: SLF001
    assert p.returncode == 0
    _backdate_event(name, item_id, "reopened", days_ago=30)

    assert A.reopened_count(name, days=7) == 0
    assert A.reopened_count(name, days=60) == 1


# ---------------------------------------------------------------------------
# project_agents / agents_snapshot
# ---------------------------------------------------------------------------


def test_project_agents_reports_fresh_holder(workspace, project_factory):
    name, bd = project_factory("agfresh")
    item_id = bd.create(title="fresh hold", kind="task")
    bd.claim_item(item_id, actor="agent-fresh")
    bd.take_custody(item_id, holder="agent-fresh", pid=111, host="h1")

    rows = A.project_agents(name)

    assert len(rows) == 1
    row = rows[0]
    assert row["agent"] == "agent-fresh"
    assert row["project"] == name
    assert row["item_id"] == item_id
    assert row["item_title"] == "fresh hold"
    assert row["stale"] is False
    assert row["seconds_over_ttl_if_stale"] is None
    assert row["held_seconds_or_last_renewal_age"] is not None
    assert row["held_seconds_or_last_renewal_age"] < 5.0


def test_project_agents_reports_stale_holder_with_overage(workspace, project_factory):
    name, bd = project_factory("agstale")
    item_id = bd.create(title="stale hold", kind="task")
    bd.claim_item(item_id, actor="agent-stale")
    old_last_seen = C.now_iso()  # written below with an already-old instant
    stale_seen = (datetime.now(UTC) - timedelta(seconds=C.CUSTODY_TTL_SECONDS + 500)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _set_custody(bd, item_id, holder="agent-stale", last_seen=stale_seen)

    rows = A.project_agents(name)

    assert len(rows) == 1
    row = rows[0]
    assert row["stale"] is True
    assert row["seconds_over_ttl_if_stale"] == pytest.approx(500.0, abs=5.0)
    assert row["held_seconds_or_last_renewal_age"] == pytest.approx(
        C.CUSTODY_TTL_SECONDS + 500, abs=5.0
    )
    del old_last_seen  # unused placeholder for readability above


def test_project_agents_no_custody_record_counts_as_stale_unmeasurable(workspace, project_factory):
    """A held item with NO custody record at all (claimed by something that
    bypassed the custody path) is reclaim-eligible per `custody.reclaim_eligible`
    -- counted stale here too, with an un-ageable (`None`) duration, never a
    fabricated 0.
    """
    name, bd = project_factory("agnocust")
    item_id = bd.create(title="no custody", kind="task")
    bd.claim_item(item_id, actor="agent-nocust")

    rows = A.project_agents(name)

    assert len(rows) == 1
    row = rows[0]
    assert row["stale"] is True
    assert row["held_seconds_or_last_renewal_age"] is None
    assert row["seconds_over_ttl_if_stale"] is None


def test_project_agents_excludes_unheld_items(workspace, project_factory):
    name, bd = project_factory("agunheld")
    bd.create(title="just ready", kind="task")
    assert A.project_agents(name) == []


def test_project_agents_sorts_stale_first_then_by_freshness(workspace, project_factory):
    name, bd = project_factory("agsort")

    fresh_id = bd.create(title="fresh", kind="task")
    bd.claim_item(fresh_id, actor="agent-fresh")
    bd.take_custody(fresh_id, holder="agent-fresh", pid=1, host="h")

    stale_small_id = bd.create(title="stale small overage", kind="task")
    bd.claim_item(stale_small_id, actor="agent-stale-small")
    small_seen = (datetime.now(UTC) - timedelta(seconds=C.CUSTODY_TTL_SECONDS + 100)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _set_custody(bd, stale_small_id, holder="agent-stale-small", last_seen=small_seen)

    stale_big_id = bd.create(title="stale big overage", kind="task")
    bd.claim_item(stale_big_id, actor="agent-stale-big")
    big_seen = (datetime.now(UTC) - timedelta(seconds=C.CUSTODY_TTL_SECONDS + 9000)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _set_custody(bd, stale_big_id, holder="agent-stale-big", last_seen=big_seen)

    rows = A.project_agents(name)
    agents_in_order = [row["agent"] for row in rows]

    assert agents_in_order == ["agent-stale-big", "agent-stale-small", "agent-fresh"]


def test_agents_snapshot_spans_every_project(workspace, project_factory):
    name_a, bd_a = project_factory("fleeta")
    name_b, bd_b = project_factory("fleetb")

    item_a = bd_a.create(title="a item", kind="task")
    bd_a.claim_item(item_a, actor="agent-a")
    bd_a.take_custody(item_a, holder="agent-a", pid=1, host="h")

    item_b = bd_b.create(title="b item", kind="task")
    bd_b.claim_item(item_b, actor="agent-b")
    bd_b.take_custody(item_b, holder="agent-b", pid=1, host="h")

    rows = A.agents_snapshot(workspace)
    by_project = {(r["project"], r["agent"]) for r in rows}

    assert (name_a, "agent-a") in by_project
    assert (name_b, "agent-b") in by_project


# ---------------------------------------------------------------------------
# agent_stats
# ---------------------------------------------------------------------------


def test_agent_stats_single_project_counts_resolved_and_held(workspace, project_factory):
    name, bd = project_factory("astats")

    resolved_id = bd.create(title="resolved by agent", kind="task")
    bd.claim_item(resolved_id, actor="agent-z")
    bd.resolve(resolved_id, "done", actor="agent-z")

    held_id = bd.create(title="held by agent", kind="task")
    bd.claim_item(held_id, actor="agent-z")

    stats = A.agent_stats(name, "agent-z", days=7)

    assert stats["agent"] == "agent-z"
    assert stats["resolved"] == 1
    assert stats["held"] == 1


def test_agent_stats_resolved_respects_window(workspace, project_factory):
    name, bd = project_factory("astatswin")
    old_id = bd.create(title="resolved long ago", kind="task")
    bd.claim_item(old_id, actor="agent-w")
    bd.resolve(old_id, "done", actor="agent-w")
    now = datetime.now(UTC)
    _backdate_issue(name, old_id, closed_at=now - timedelta(days=30))

    assert A.agent_stats(name, "agent-w", days=7)["resolved"] == 0
    assert A.agent_stats(name, "agent-w", days=60)["resolved"] == 1


def test_agent_stats_across_whole_workspace(workspace, project_factory):
    name_a, bd_a = project_factory("astatswsa")
    name_b, bd_b = project_factory("astatswsb")

    id_a = bd_a.create(title="a", kind="task")
    bd_a.claim_item(id_a, actor="agent-multi")
    bd_a.resolve(id_a, "done", actor="agent-multi")

    id_b = bd_b.create(title="b", kind="task")
    bd_b.claim_item(id_b, actor="agent-multi")

    stats = A.agent_stats(workspace, "agent-multi", days=7)

    assert stats["resolved"] == 1
    assert stats["held"] == 1


def test_agent_stats_zero_for_unknown_agent(workspace, project_factory):
    name, bd = project_factory("astatsunknown")
    bd.create(title="nobody's item", kind="task")
    stats = A.agent_stats(name, "nobody-at-all", days=7)
    assert stats == {
        "agent": "nobody-at-all",
        "days": 7,
        "resolved": 0,
        "held": 0,
        "stale_incidents": 0,
    }


# ---------------------------------------------------------------------------
# attention_items
# ---------------------------------------------------------------------------


def test_attention_items_ranks_stale_custody_first(workspace, project_factory):
    name, bd = project_factory("attnstale")
    item_id = bd.create(title="stale one", kind="task", priority=1)
    bd.claim_item(item_id, actor="agent-attn")
    stale_seen = (datetime.now(UTC) - timedelta(seconds=C.CUSTODY_TTL_SECONDS + 1000)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _set_custody(bd, item_id, holder="agent-attn", last_seen=stale_seen)

    rows = A.attention_items(workspace, limit=50)
    matches = [r for r in rows if r["item_id"] == item_id]

    assert len(matches) == 1
    row = matches[0]
    assert row["rank_reason"] == "stale-custody"
    assert row["project"] == name
    assert row["priority"] == 1
    assert "agent-attn" in row["detail"]


def test_attention_items_ranks_blocked_second(workspace, project_factory):
    name, bd = project_factory("attnblocked")
    blocker_id = bd.create(title="blocker", kind="task")
    blocked_id = bd.create(title="blocked one", kind="task")
    bd.add_dependency(blocked_id, blocker_id, dep_type="blocks")
    bd.block(blocked_id, "waiting on blocker", actor="agent-attn2")

    rows = A.attention_items(workspace, limit=50)
    matches = [r for r in rows if r["item_id"] == blocked_id]

    assert len(matches) == 1
    assert matches[0]["rank_reason"] == "blocked"
    assert matches[0]["project"] == name


def test_attention_items_ranks_aging_ready_third_oldest_first(workspace, project_factory):
    name, bd = project_factory("attnaging")
    now = datetime.now(UTC)

    old_id = bd.create(title="old ready", kind="task", tags=[A.LANE_WORK])
    _backdate_issue(name, old_id, created_at=now - timedelta(days=10))

    older_id = bd.create(title="older ready", kind="task", tags=[A.LANE_WORK])
    _backdate_issue(name, older_id, created_at=now - timedelta(days=20))

    fresh_id = bd.create(title="fresh ready", kind="task", tags=[A.LANE_WORK])
    del fresh_id  # too young to be "aging" -- must not appear

    rows = A.attention_items(workspace, limit=50)
    aging_ids = [r["item_id"] for r in rows if r["rank_reason"] == "aging"]

    assert older_id in aging_ids
    assert old_id in aging_ids
    # oldest first among the aging group
    assert aging_ids.index(older_id) < aging_ids.index(old_id)


def test_attention_items_ordering_across_reasons_and_limit(workspace, project_factory):
    name, bd = project_factory("attnorder")
    now = datetime.now(UTC)

    stale_id = bd.create(title="stale", kind="task")
    bd.claim_item(stale_id, actor="agent-o")
    stale_seen = (datetime.now(UTC) - timedelta(seconds=C.CUSTODY_TTL_SECONDS + 1000)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _set_custody(bd, stale_id, holder="agent-o", last_seen=stale_seen)

    blocker_id = bd.create(title="blocker2", kind="task")
    blocked_id = bd.create(title="blocked", kind="task")
    bd.add_dependency(blocked_id, blocker_id, dep_type="blocks")
    bd.block(blocked_id, "waiting", actor="agent-o")

    aging_id = bd.create(title="aging", kind="task", tags=[A.LANE_WORK])
    _backdate_issue(name, aging_id, created_at=now - timedelta(days=10))

    rows = A.attention_items(workspace, limit=50)
    reasons_in_order = [r["rank_reason"] for r in rows if r["project"] == name]

    # every stale-custody entry precedes every blocked entry, which precedes
    # every aging entry -- exact tier ordering, regardless of interleaving
    # from other test projects sharing the workspace.
    first_blocked = reasons_in_order.index("blocked")
    first_aging = reasons_in_order.index("aging")
    assert reasons_in_order[0] == "stale-custody"
    assert first_blocked < first_aging

    limited = A.attention_items(workspace, limit=1)
    assert len(limited) == 1


def test_attention_items_aging_threshold_is_a_module_constant():
    assert isinstance(A.ATTENTION_AGING_DAYS, int)
    assert A.ATTENTION_AGING_DAYS > 0
