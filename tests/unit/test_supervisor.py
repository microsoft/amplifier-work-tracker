"""Tier 1 -- supervisor.py pure logic: port-holder discrimination and the
reap/notify sweep aggregation. No bd, no network, no real sleeps.

Port classification is tested exhaustively over its three plain inputs
(holders, responds, owned_pid) -- see `classify_port_holders`'s docstring
for why it takes no sockets/subprocesses/pids directly. Sweep aggregation is
tested against a fake in-memory workspace/project pair so it never needs a
real `bd` binary, mirroring the forged-clock style already used by
`test_custody.py` for `reap`'s underlying eligibility math.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from amplifier_work_tracker import custody as C
from amplifier_work_tracker import heartbeat as HB
from amplifier_work_tracker import supervisor as SV

# --------------------------------------------------------- classify_port_holders


def test_no_holders_means_proceed():
    action, reason = SV.classify_port_holders(holders=[], responds=False, owned_pid=None)
    assert action == "proceed"
    assert "free" in reason


def test_holders_not_responding_means_kill_stale():
    """The exact muxplex restart-race case: an old process still holds the
    port but no longer answers -- safe to reclaim."""
    action, reason = SV.classify_port_holders(holders=[123], responds=False, owned_pid=None)
    assert action == "kill_stale"
    assert "123" in reason


def test_holders_not_responding_ignores_owned_pid():
    """Even if the non-responding holder IS our own recorded pid, a hung
    process is still hung -- staleness is about responsiveness, not identity."""
    action, _ = SV.classify_port_holders(holders=[123], responds=False, owned_pid=123)
    assert action == "kill_stale"


def test_healthy_and_owned_means_refuse_ours():
    action, reason = SV.classify_port_holders(holders=[555], responds=True, owned_pid=555)
    assert action == "refuse_ours"
    assert "555" in reason


def test_healthy_and_owned_pid_present_among_multiple_holders():
    action, _ = SV.classify_port_holders(holders=[1, 555, 2], responds=True, owned_pid=555)
    assert action == "refuse_ours"


def test_healthy_but_not_owned_means_refuse_foreign():
    action, reason = SV.classify_port_holders(holders=[999], responds=True, owned_pid=None)
    assert action == "refuse_foreign"
    assert "999" in reason


def test_healthy_owned_pid_recorded_but_holder_is_someone_else():
    """A stale pid-file record (e.g. surviving a reboot where pids were
    reused) must NOT be trusted just because a record exists -- only an
    actual match against a live holder counts as 'ours'."""
    action, _ = SV.classify_port_holders(holders=[42], responds=True, owned_pid=555)
    assert action == "refuse_foreign"


def test_classification_is_exhaustive_and_returns_only_known_actions():
    known = {"proceed", "kill_stale", "refuse_ours", "refuse_foreign"}
    cases = [
        {"holders": [], "responds": False, "owned_pid": None},
        {
            "holders": [],
            "responds": True,
            "owned_pid": None,
        },  # responds is meaningless with no holders
        {"holders": [1], "responds": False, "owned_pid": 1},
        {"holders": [1], "responds": True, "owned_pid": 1},
        {"holders": [1], "responds": True, "owned_pid": None},
        {"holders": [1, 2], "responds": True, "owned_pid": 2},
    ]
    for case in cases:
        action, reason = SV.classify_port_holders(**case)
        assert action in known
        assert isinstance(reason, str) and reason


def test_ensure_port_available_proceeds_silently_when_free(monkeypatch, tmp_path):
    monkeypatch.setattr(SV, "get_port_holder_pids", lambda port: [])
    # Should not raise, and should not even need to probe responsiveness.
    SV.ensure_port_available("127.0.0.1", 1, tmp_path / "pid")


def test_ensure_port_available_kills_stale_holder(monkeypatch, tmp_path):
    killed: list[int] = []
    monkeypatch.setattr(SV, "get_port_holder_pids", lambda port: [4242])
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port, timeout=2.0: False)
    monkeypatch.setattr(SV.time, "sleep", lambda s: None)

    def fake_kill(pid, sig):
        killed.append(pid)

    monkeypatch.setattr(SV.os, "kill", fake_kill)
    SV.ensure_port_available("127.0.0.1", 1, tmp_path / "pid")
    assert killed == [4242]


def test_ensure_port_available_refuses_ours_without_killing(monkeypatch, tmp_path):
    pid_file = tmp_path / "pid"
    pid_file.write_text("777", encoding="utf-8")
    killed: list[int] = []
    monkeypatch.setattr(SV, "get_port_holder_pids", lambda port: [777])
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port, timeout=2.0: True)
    monkeypatch.setattr(SV.os, "kill", lambda pid, sig: killed.append(pid))
    try:
        SV.ensure_port_available("127.0.0.1", 1, pid_file)
        raise AssertionError("expected PortConflictError")
    except SV.PortConflictError as e:
        assert "duplicate" in str(e)
    assert killed == []


def test_ensure_port_available_refuses_foreign_without_killing(monkeypatch, tmp_path):
    killed: list[int] = []
    monkeypatch.setattr(SV, "get_port_holder_pids", lambda port: [999])
    monkeypatch.setattr(SV, "port_holder_responds", lambda host, port, timeout=2.0: True)
    monkeypatch.setattr(SV.os, "kill", lambda pid, sig: killed.append(pid))
    try:
        SV.ensure_port_available("127.0.0.1", 1, tmp_path / "pid")
        raise AssertionError("expected PortConflictError")
    except SV.PortConflictError as e:
        assert "not spawned by us" in str(e)
    assert killed == []


def test_ensure_port_available_force_kills_unconditionally(monkeypatch, tmp_path):
    killed: list[int] = []
    monkeypatch.setattr(SV, "get_port_holder_pids", lambda port: [1, 2])
    monkeypatch.setattr(SV.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(SV.time, "sleep", lambda s: None)
    SV.ensure_port_available("127.0.0.1", 1, tmp_path / "pid", force=True)
    assert killed == [1, 2]


def test_read_owned_pid_missing_file_is_none(tmp_path):
    assert SV.read_owned_pid(tmp_path / "nope") is None


def test_read_owned_pid_garbage_contents_is_none(tmp_path):
    p = tmp_path / "pid"
    p.write_text("not-a-pid", encoding="utf-8")
    assert SV.read_owned_pid(p) is None


def test_read_owned_pid_reads_back_written_value(tmp_path):
    p = tmp_path / "pid"
    p.write_text("4242\n", encoding="utf-8")
    assert SV.read_owned_pid(p) == 4242


# --------------------------------------------- _record_exit_and_over_budget
#
# Pure decision logic (see the function's own docstring for why it's split
# out this way) -- no asyncio, no real clock, exhaustively testable, mirror
# of this module's own `classify_port_holders` convention.


def test_budget_not_exceeded_below_the_count():
    recent: list[float] = []
    for t in (0.0, 1.0):
        over = SV._record_exit_and_over_budget(recent, now=t, budget_count=3, window=60.0)
    assert over is False
    assert len(recent) == 2


def test_budget_exceeded_at_the_count_within_the_window():
    recent: list[float] = []
    over = False
    for t in (0.0, 1.0, 2.0):
        over = SV._record_exit_and_over_budget(recent, now=t, budget_count=3, window=60.0)
    assert over is True
    assert len(recent) == 3


def test_budget_never_exceeded_when_exits_are_spaced_beyond_the_window():
    """The exact 'resets by time simply passing' behaviour: three exits, each
    further apart than the window, must never accumulate -- only ever one
    entry survives the trim by the time the next is recorded."""
    recent: list[float] = []
    results = [
        SV._record_exit_and_over_budget(recent, now=t, budget_count=3, window=60.0)
        for t in (0.0, 100.0, 200.0)
    ]
    assert results == [False, False, False]
    assert len(recent) == 1


def test_budget_trims_old_entries_before_counting():
    """Two old exits (aged out) plus one new one must count as ONE against
    the budget, not three -- the trim must run before the length check."""
    recent = [0.0, 1.0]
    over = SV._record_exit_and_over_budget(recent, now=1000.0, budget_count=2, window=60.0)
    assert over is False
    assert recent == [1000.0]


# --------------------------------------------------------- dolt_supervisor_loop
#
# Real asyncio (matching the reap_loop/notify_loop tests below), but `dolt`
# itself is faked -- never a real subprocess -- via a `spawn_dolt` double
# that returns a plain object with a `.pid` and a synchronous `.wait()`.


class _FakeDoltProc:
    def __init__(self, pid: int, returncode: int):
        self.pid = pid
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


def test_dolt_supervisor_loop_gives_up_loudly_after_budget_exhausted(monkeypatch, tmp_path):
    """Regression pin for the 2026-08-14 outage's deeper bug: a dolt child
    that keeps dying in a tight loop must eventually raise, loudly, rather
    than being restarted forever in silence."""
    monkeypatch.setattr(SV, "ensure_port_available", lambda *a, **k: None)
    calls = {"n": 0}

    def fake_spawn(host, port, data_dir):
        calls["n"] += 1
        return _FakeDoltProc(pid=1000 + calls["n"], returncode=-9)  # SIGKILL, per the incident

    monkeypatch.setattr(SV, "spawn_dolt", fake_spawn)
    stop_event = asyncio.Event()
    state: dict[str, Any] = {"proc": None}

    async def run():
        await SV.dolt_supervisor_loop(
            host="127.0.0.1",
            port=1,
            data_dir=tmp_path,
            pid_file=tmp_path / "dolt.pid",
            stop_event=stop_event,
            state=state,
            restart_backoff=0.0,
            restart_budget_count=3,
            restart_budget_window=60.0,
        )

    with pytest.raises(SV.DoltSupervisionExhaustedError) as excinfo:
        asyncio.run(run())
    assert calls["n"] == 3
    assert "3" in str(excinfo.value)
    assert state["proc"] is None  # cleaned up, not left dangling on the way out


def test_dolt_supervisor_loop_stops_cleanly_without_raising_when_stop_requested(
    monkeypatch, tmp_path
):
    """A dolt exit that happens to coincide with a real shutdown request must
    NOT be treated as 'unexpected' -- no exception, clean return."""
    monkeypatch.setattr(SV, "ensure_port_available", lambda *a, **k: None)
    stop_event = asyncio.Event()
    state: dict[str, Any] = {"proc": None}

    def fake_spawn(host, port, data_dir):
        stop_event.set()  # simulate: shutdown requested while dolt is running
        return _FakeDoltProc(pid=1234, returncode=0)

    monkeypatch.setattr(SV, "spawn_dolt", fake_spawn)

    async def run():
        await SV.dolt_supervisor_loop(
            host="127.0.0.1",
            port=1,
            data_dir=tmp_path,
            pid_file=tmp_path / "dolt.pid",
            stop_event=stop_event,
            state=state,
            restart_backoff=0.0,
            restart_budget_count=1,
            restart_budget_window=60.0,
        )

    asyncio.run(run())  # must not raise


# ------------------------------------------------------------- reap/notify sweeps
#
# Fakes, not a real `bd` -- reap_sweep/notify_sweep only need
# Workspace.names()/project() and Beads.list()/get()/resolve()/release() to
# exist with the right shapes; every timestamp is forged (never a real
# sleep), matching test_custody.py's own convention.


def _ts(seconds_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


class _FakeItem:
    def __init__(
        self, id: str, *, status: str, holder: str | None, meta: dict[str, Any] | None = None
    ):
        self.id = id
        self.status = status
        self.holder = holder
        self.meta = meta or {}
        self.tags: list[str] = []
        self.links: list[dict[str, Any]] = []
        self.resolution: str | None = None


class _FakeBeads:
    """A minimal double for A.Beads: enough surface for reap_project/notify_project."""

    def __init__(self, items: dict[str, _FakeItem]):
        self.items = items
        self.released: list[str] = []
        self.resolved: list[tuple[str, str, str]] = []

    def list(self, *, lane: str | None = None, include_resolved: bool = False):
        out = list(self.items.values())
        if not include_resolved:
            out = [i for i in out if i.status != "resolved"]
        return out

    def get(self, item_id: str, *, with_links: bool = False):
        return self.items[item_id]

    def release(self, item_id: str) -> None:
        self.released.append(item_id)
        self.items[item_id].status = "open"

    def resolve(self, item_id: str, reason: str, *, actor: str | None = None):
        self.resolved.append((item_id, reason, actor or ""))
        self.items[item_id].status = "resolved"
        self.items[item_id].resolution = reason
        return self.items[item_id]


class _FakeWorkspace:
    def __init__(self, projects: dict[str, _FakeBeads]):
        self._projects = projects

    def names(self) -> list[str]:
        return sorted(self._projects)

    def project(self, name: str):
        return self._projects[name]


def test_reap_project_reclaims_stale_and_keeps_fresh():
    stale_item = _FakeItem(
        "w-1",
        status="held",
        holder="agent-a",
        meta={
            C.CUSTODY_KEY: {
                "holder": "agent-a",
                "last_seen": _ts(3600),
                "declared_state": "working",
            }
        },
    )
    fresh_item = _FakeItem(
        "w-2",
        status="held",
        holder="agent-b",
        meta={
            C.CUSTODY_KEY: {"holder": "agent-b", "last_seen": _ts(5), "declared_state": "working"}
        },
    )
    bd = _FakeBeads({"w-1": stale_item, "w-2": fresh_item})
    result = SV.reap_project(bd, ttl_seconds=900)  # type: ignore[arg-type]
    assert result["reclaimed_count"] == 1
    assert result["reclaimed"][0]["id"] == "w-1"
    assert bd.released == ["w-1"]
    assert [k["id"] for k in result["kept"]] == ["w-2"]


def test_reap_sweep_isolates_a_broken_project_from_the_others():
    good_bd = _FakeBeads(
        {
            "w-1": _FakeItem(
                "w-1",
                status="held",
                holder="agent-a",
                meta={
                    C.CUSTODY_KEY: {
                        "holder": "agent-a",
                        "last_seen": _ts(3600),
                        "declared_state": "working",
                    }
                },
            )
        }
    )

    class _ExplodingBeads(_FakeBeads):
        def list(self, *, lane: str | None = None, include_resolved: bool = False):
            raise RuntimeError("simulated bd outage")

    ws = _FakeWorkspace({"broken": _ExplodingBeads({}), "good": good_bd})
    results = SV.reap_sweep(ws, ttl_seconds=900)  # type: ignore[arg-type]
    assert "error" in results["broken"]
    assert results["good"]["reclaimed_count"] == 1


def test_notify_project_flips_only_linked_unresolved_reports():
    report = _FakeItem("r-1", status="open", holder=None)
    work = _FakeItem("w-1", status="resolved", holder="agent-a")
    work.resolution = "fixed the thing"
    work.links = [{"id": "r-1", "direction": "from", "type": "discovered-from"}]
    bd = _FakeBeads({"r-1": report, "w-1": work})
    result = SV.notify_project(bd)  # type: ignore[arg-type]
    assert result["count"] == 1
    assert result["flipped"][0] == {"report": "r-1", "by": "w-1"}
    assert report.status == "resolved"
    assert bd.resolved[0][1] == "Resolved by w-1: fixed the thing"


def test_notify_sweep_isolates_a_broken_project_from_the_others():
    report = _FakeItem("r-1", status="open", holder=None)
    work = _FakeItem("w-1", status="resolved", holder="agent-a")
    work.links = [{"id": "r-1", "direction": "from", "type": "discovered-from"}]
    good_bd = _FakeBeads({"r-1": report, "w-1": work})

    class _ExplodingBeads(_FakeBeads):
        def list(self, *, lane: str | None = None, include_resolved: bool = False):
            raise RuntimeError("simulated bd outage")

    ws = _FakeWorkspace({"broken": _ExplodingBeads({}), "good": good_bd})
    results = SV.notify_sweep(ws)  # type: ignore[arg-type]
    assert "error" in results["broken"]
    assert results["good"]["count"] == 1


# ------------------------------------------------------- reap_loop/notify_loop
#
# Real asyncio, but never a real 300s-scale interval -- these use very short
# intervals (fractions of a second) purely to let the loop body actually run
# a couple of iterations within a fast test, never to simulate production
# timing. Proves the loop wiring itself (not just heartbeat.py in isolation)
# calls record_loop_started/record_sweep_completed at the right moments.


def test_reap_loop_records_start_before_its_first_sweep_completes(tmp_path):
    ws = _FakeWorkspace({})
    stop_event = asyncio.Event()
    hb_path = HB.heartbeat_path(tmp_path)

    async def run():
        task = asyncio.create_task(
            SV.reap_loop(ws, interval=100, stop_event=stop_event, heartbeat_path=hb_path)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)  # let the coroutine run up to its first await
        rec = HB.read_loop_heartbeat(hb_path, HB.REAP)
        assert rec is not None
        assert rec["last_completed"] is None
        stop_event.set()
        await task

    asyncio.run(run())


def test_reap_loop_records_completion_after_a_sweep(tmp_path):
    ws = _FakeWorkspace({})
    stop_event = asyncio.Event()
    hb_path = HB.heartbeat_path(tmp_path)

    async def run():
        task = asyncio.create_task(
            SV.reap_loop(ws, interval=0.01, stop_event=stop_event, heartbeat_path=hb_path)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.1)  # several intervals' worth
        stop_event.set()
        await task

    asyncio.run(run())
    rec = HB.read_loop_heartbeat(hb_path, HB.REAP)
    assert rec is not None
    assert rec["last_completed"] is not None


def test_notify_loop_records_completion_after_a_sweep(tmp_path):
    ws = _FakeWorkspace({})
    stop_event = asyncio.Event()
    hb_path = HB.heartbeat_path(tmp_path)

    async def run():
        task = asyncio.create_task(
            SV.notify_loop(ws, interval=0.01, stop_event=stop_event, heartbeat_path=hb_path)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.1)
        stop_event.set()
        await task

    asyncio.run(run())
    rec = HB.read_loop_heartbeat(hb_path, HB.NOTIFY)
    assert rec is not None
    assert rec["last_completed"] is not None


def test_reap_and_notify_loops_use_independent_heartbeat_records(tmp_path):
    """Run both loops against the SAME heartbeat file concurrently -- proves
    they don't clobber each other's record (each writes only its own key)."""
    ws = _FakeWorkspace({})
    stop_event = asyncio.Event()
    hb_path = HB.heartbeat_path(tmp_path)

    async def run():
        reap_task = asyncio.create_task(
            SV.reap_loop(ws, interval=0.01, stop_event=stop_event, heartbeat_path=hb_path)  # type: ignore[arg-type]
        )
        notify_task = asyncio.create_task(
            SV.notify_loop(ws, interval=0.01, stop_event=stop_event, heartbeat_path=hb_path)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.1)
        stop_event.set()
        await asyncio.gather(reap_task, notify_task)

    asyncio.run(run())
    reap_rec = HB.read_loop_heartbeat(hb_path, HB.REAP)
    notify_rec = HB.read_loop_heartbeat(hb_path, HB.NOTIFY)
    assert reap_rec is not None and reap_rec["last_completed"] is not None
    assert notify_rec is not None and notify_rec["last_completed"] is not None
