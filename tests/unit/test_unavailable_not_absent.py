"""Tier 1 -- an infrastructure read failure must never be reported as absence.

The reporting half of lane `model_performance-8zv`. Measured before the fix
(lane `model_performance-rpz`, harness
`probes/rpz-dolt-error-misreport/repro.sh`), under a transient dolt read
failure on a healthy database:

  - `claim --id` on an item that EXISTS said "item not found" .... 9 of 12
  - `list --id` on an item the session HELD said a bare
    "item 'X' not found in project 'Y'", cause discarded ......... 2 of 8
  - `instances` printed a healthy project as ERROR, null counts .. 5 of 10

`list --id` is the worst of the three: it is the exact path this project's
own `context/awareness.md` hazard #6 tells agents to TRUST as the safe
recovery after an ambiguous write.

Both directions are fenced here. Every "the infrastructure failed" test has a
paired "the database is healthy and the item really is absent" test asserting
the message is UNCHANGED, byte for byte, from what it says today -- because a
fix that makes every "not found" say "maybe transient" has replaced one lie
with another.

The failure is injected at `_dolt_sql`/`_dolt_sql_json`, which is also PAST
`_run_dolt_sql_bounded`'s retry budget -- the condition the deliverable names.
No `bd`, no dolt server, no network.
"""

from __future__ import annotations

import subprocess

import pytest

from amplifier_work_tracker import adapter as A

TRANSPORT_FAILURE = (
    "failed to load database names: lstat /tmp/churn_22301.sig: no such file or directory"
)

PROJECT = "probeproj"
REAL_ID = f"{PROJECT}-abcd"
ABSENT_ID = f"{PROJECT}-nosuchid"


@pytest.fixture
def probe_workspace(tmp_path):
    """A workspace whose project directory exists (so `creation_state` is
    `None` -- not creating, not abandoned) and whose database reads are
    entirely under this test's control."""
    (tmp_path / PROJECT / ".beads").mkdir(parents=True)
    return A.Workspace(tmp_path)


@pytest.fixture
def bd(probe_workspace):
    return A.Beads(probe_workspace.path(PROJECT) / ".beads", actor="probe")


def _unreachable(monkeypatch):
    """Every direct-SQL read fails the way dolt really fails when it loses
    the race against its own scanned directory."""

    def fail(*_a, **_k):
        return subprocess.CompletedProcess(["dolt"], 1, "", TRANSPORT_FAILURE)

    monkeypatch.setattr(A, "_dolt_sql", fail)
    monkeypatch.setattr(A, "_dolt_sql_json", fail)


def _healthy_but_empty(monkeypatch):
    """A perfectly reachable database that genuinely holds no such item."""

    def csv_ok(*_a, **_k):
        return subprocess.CompletedProcess(["dolt"], 0, "issue_id,label\n", "")

    def json_ok(*_a, **_k):
        return subprocess.CompletedProcess(["dolt"], 0, '{"rows": []}', "")

    monkeypatch.setattr(A, "_dolt_sql", csv_ok)
    monkeypatch.setattr(A, "_dolt_sql_json", json_ok)


# ===================================================== get_readonly / list --id


def test_get_readonly_under_transport_failure_does_not_claim_absence(bd, monkeypatch):
    """WORST of the three sites: line-for-line, this branch used to discard
    the cause entirely and emit a bare "not found" for an item that exists."""
    _unreachable(monkeypatch)
    with pytest.raises(A.BeadsUnavailableError) as ei:
        bd.get_readonly(REAL_ID)
    msg = str(ei.value)
    assert "not found" not in msg.lower()
    assert "failed to load database names" in msg, "the underlying cause was discarded again"


def test_get_readonly_transport_failure_is_a_distinct_TYPE(bd, monkeypatch):
    """Structural, not a substring: a caller must not have to grep an error
    message to learn whether absence was observed or merely assumed."""
    _unreachable(monkeypatch)
    with pytest.raises(A.BeadsError) as ei:
        bd.get_readonly(REAL_ID)
    assert isinstance(ei.value, A.BeadsUnavailableError)


def test_get_readonly_genuine_absence_is_UNCHANGED(bd, monkeypatch):
    """THE no-blurring guardrail. Healthy database, item genuinely absent --
    the wording must be exactly what it is today, with no hedge."""
    _healthy_but_empty(monkeypatch)
    with pytest.raises(A.BeadsError) as ei:
        bd.get_readonly(ABSENT_ID)
    assert not isinstance(ei.value, A.BeadsUnavailableError)
    assert str(ei.value) == f"item {ABSENT_ID!r} not found in project {PROJECT!r}"


def test_get_readonly_wrong_project_prefix_is_UNCHANGED(bd, monkeypatch):
    """The other healthy-database branch of the same method, likewise
    untouched."""
    _healthy_but_empty(monkeypatch)
    with pytest.raises(A.BeadsError) as ei:
        bd.get_readonly("someotherproject-abcd")
    assert not isinstance(ei.value, A.BeadsUnavailableError)
    assert "does not look like it belongs to project" in str(ei.value)


# =========================================================== claim_item / claim


def test_claim_item_under_transport_failure_does_not_say_item_not_found(bd, monkeypatch):
    """`claim_item`'s own docstring promises three outcomes "deliberately
    never conflated". Infrastructure-unavailable is a fourth, and it was
    folded into the first in 9 of 12 measured attempts."""
    _unreachable(monkeypatch)
    with pytest.raises(A.BeadsUnavailableError) as ei:
        bd.claim_item(REAL_ID, actor="probe")
    msg = str(ei.value)
    assert "item not found" not in msg.lower()
    assert "failed to load database names" in msg


def test_claim_item_genuine_absence_is_UNCHANGED(bd, monkeypatch):
    """No-blurring guardrail, claim side."""
    _healthy_but_empty(monkeypatch)
    with pytest.raises(A.BeadsError) as ei:
        bd.claim_item(ABSENT_ID, actor="probe")
    assert not isinstance(ei.value, A.BeadsUnavailableError)
    assert str(ei.value).startswith(f"cannot claim {ABSENT_ID}: item not found (")


# ======================================================= project_summary / instances


def test_project_summary_under_transport_failure_is_UNAVAILABLE_not_ERROR(
    probe_workspace, monkeypatch
):
    """`ERROR:` asserts the project's data is unreadable. All that was
    actually known is that our own read did not arrive -- and the project was
    healthy, reporting `ok` seconds either side, in 5 of 10 attempts."""
    _unreachable(monkeypatch)
    s = A.project_summary(probe_workspace, PROJECT)
    assert A.is_unavailable_status(s.status)
    assert not s.status.startswith("ERROR:")
    assert s.status != A.STATUS_OK
    assert "failed to load database names" in s.status
    assert s.total is None, "an unreachable project must never report counts"


def test_project_summary_unavailable_is_distinct_from_every_other_status(
    probe_workspace, monkeypatch
):
    """Distinct from BOTH `ok` and `ERROR`, and from the two creation
    states -- the vocabulary `instances` did not have."""
    _unreachable(monkeypatch)
    s = A.project_summary(probe_workspace, PROJECT)
    assert s.status not in (A.STATUS_OK, A.STATUS_CREATING, A.STATUS_BROKEN)
    assert not A.is_unavailable_status(A.STATUS_OK)
    assert not A.is_unavailable_status("ERROR: could not read items")


def test_project_summary_real_read_failure_still_reports_ERROR(probe_workspace, monkeypatch):
    """No-blurring guardrail, summary side: a database that IS reachable but
    cannot be read is still an honest `ERROR`, not softened to 'unknown'."""

    def domain_failure(*_a, **_k):
        return subprocess.CompletedProcess(
            ["dolt"], 1, "", "Error 1049: Unknown database 'probeproj'"
        )

    monkeypatch.setattr(A, "_dolt_sql", domain_failure)
    monkeypatch.setattr(A, "_dolt_sql_json", domain_failure)
    s = A.project_summary(probe_workspace, PROJECT)
    assert s.status.startswith("ERROR:")
    assert not A.is_unavailable_status(s.status)


def test_project_summary_healthy_is_UNCHANGED(probe_workspace, monkeypatch):
    """And a reachable, readable, empty project is still plainly `ok`."""
    _healthy_but_empty(monkeypatch)
    s = A.project_summary(probe_workspace, PROJECT)
    assert s.status == A.STATUS_OK
    assert s.total == 0
