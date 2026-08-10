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

import time
from typing import Any

from amplifier_work_tracker import custody as C
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
