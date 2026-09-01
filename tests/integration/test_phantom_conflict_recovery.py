"""Tier 2 -- verify-by-read-back on a conflicted close/release, and the
sanctioned wedge-recovery branch on `release` -- work_tracker item
pipeline-yym.

Real incident (2026-09-01, session agent-spark-1-2022903, item cortex-cro0):
`work_resolve` failed FIVE spaced attempts over ~2.5h, each reporting
"`bd close cortex-cro0` still conflicting after 8 retries ... Last: <a
successful close confirmation for the same item>" -- the close had actually
landed on an earlier attempt inside `Beads._run`'s own retry loop, but the
wrapper still raised. The session's local custody latch stayed set forever,
blocking `work_claim` for the rest of that session's life.

These tests simulate the conflict via monkeypatch/injection against the
real isolated dolt server (per the work item's own instruction: "make the
close succeed against the isolated dolt, then force the wrapper to report a
conflict -- do NOT try to reproduce real dolt contention"). `Beads._run` is
patched to perform the REAL write first (so the item genuinely lands in the
isolated store), then raise the exact `BeadsError` shape `_run` raises when
its serialization-retry budget is exhausted -- never faked contention
timing, never a mocked dolt.
"""

from __future__ import annotations

import pytest

from amplifier_work_tracker import adapter as A

pytestmark = pytest.mark.integration


def _conflict_after_real_write(monkeypatch, *, on_first_arg: str):
    """Monkeypatch `A.Beads._run` so that the FIRST call whose `args[0] ==
    on_first_arg` really executes (via the true, unpatched `_run`), then
    raises `_run`'s own exhausted-retries `BeadsError` regardless of the
    real outcome -- reproducing "the write landed, but the wrapper still
    reported a persistent conflict" without needing to manufacture actual
    dolt contention. Returns a `calls` list recording every intercepted
    call's args, for assertions on how many times this fired.
    """
    real_run = A.Beads._run
    calls: list[list[str]] = []

    def fake_run(self, args, actor=None):  # noqa: ANN001 -- matches Beads._run's own signature
        if args and args[0] == on_first_arg:
            calls.append(list(args))
            result = real_run(self, args, actor=actor)
            raise A.BeadsError(
                f"`bd {' '.join(args[:2])}` still conflicting after 8 retries. "
                f"Contention too high; refusing to keep hammering. "
                f"Last: {(result.stdout or result.stderr or '').strip()}"
            )
        return real_run(self, args, actor=actor)

    monkeypatch.setattr(A.Beads, "_run", fake_run)
    return calls


# --------------------------------------------------------- resolve() verify


def test_resolve_verifies_by_readback_when_wrapper_reports_conflict_after_a_landed_close(
    shared_bd, unique_lane, monkeypatch
):
    """The exact incident: `bd close` lands for real, but `Beads._run`
    raises its own exhausted-retries `BeadsError` anyway. `resolve` must
    verify via a fresh, contention-free read-back and report SUCCESS --
    never propagate the wrapper's false failure."""
    item_id = shared_bd.create("phantom conflict close", tags=[unique_lane])
    actor = f"phantom-actor-{unique_lane}"
    shared_bd.claim_item(item_id, actor=actor)

    calls = _conflict_after_real_write(monkeypatch, on_first_arg="close")

    resolved = shared_bd.resolve(item_id, "phantom conflict cleanup", actor=actor)

    assert len(calls) == 1, "the close path must have been exercised exactly once"
    assert resolved.status == "resolved"
    assert resolved.resolution == "phantom conflict cleanup"

    # Independent confirmation via the (unpatched-for-reads) contention-free
    # path -- `get`/`get_readonly` never go through `Beads._run` at all.
    assert shared_bd.get_readonly(item_id).status == "resolved"


def test_resolve_still_raises_when_readback_shows_the_close_genuinely_did_not_land(
    shared_bd, unique_lane, monkeypatch
):
    """Contrast case: if `_run` raises AND the item is genuinely still
    open (the close never landed at all), `resolve` must still raise --
    verify-by-read-back is a safety net for a landed write, never a way to
    silently swallow a real failure."""
    item_id = shared_bd.create("phantom conflict genuine failure", tags=[unique_lane])
    actor = f"phantom-actor-genuine-{unique_lane}"
    shared_bd.claim_item(item_id, actor=actor)

    real_run = A.Beads._run

    # Only the `close` call needs patching -- claim already happened above,
    # and the fencing read inside `resolve` doesn't call `_run` at all (see
    # `Beads.get`'s docstring). This never performs the real close at all,
    # unlike `_conflict_after_real_write` -- the item genuinely stays open.
    def fake_run_close_only(self, args, actor=None):  # noqa: ANN001
        if args and args[0] == "close":
            raise A.BeadsError(
                "`bd close` still conflicting after 8 retries. Contention too "
                "high; refusing to keep hammering. Last: (no successful attempt)"
            )
        return real_run(self, args, actor=actor)

    monkeypatch.setattr(A.Beads, "_run", fake_run_close_only)

    with pytest.raises(A.BeadsError, match="still conflicting"):
        shared_bd.resolve(item_id, "should not land", actor=actor)

    monkeypatch.undo()
    assert shared_bd.get_readonly(item_id).status == "held"
    shared_bd.resolve(item_id, "genuine cleanup", actor=actor)


# --------------------------------------------------------- release() verify


def test_release_verifies_by_readback_when_wrapper_reports_conflict_after_a_landed_release(
    shared_bd, unique_lane, monkeypatch
):
    """Same hazard shape, for `release`'s `bd update --status open` write."""
    item_id = shared_bd.create("phantom conflict release", tags=[unique_lane])
    actor = f"phantom-release-actor-{unique_lane}"
    shared_bd.claim_item(item_id, actor=actor)

    calls = _conflict_after_real_write(monkeypatch, on_first_arg="update")

    outcome = shared_bd.release(item_id)

    assert len(calls) == 1
    assert outcome.already_closed is False
    assert shared_bd.get_readonly(item_id).status == "open"


# ------------------------------------------------- sanctioned wedge recovery


def test_release_on_an_already_resolved_item_writes_nothing_and_reports_already_closed(
    shared_bd, unique_lane
):
    """The sanctioned wedge-recovery branch: an item that is ALREADY
    resolved (e.g. a prior resolve landed despite reporting a spurious
    failure) must never be reopened by `release` -- checked BEFORE any
    write, via a contention-free read-back, and NO write attempted at all."""
    item_id = shared_bd.create("wedge recovery probe", tags=[unique_lane])
    actor = f"wedge-actor-{unique_lane}"
    shared_bd.claim_item(item_id, actor=actor)
    shared_bd.resolve(item_id, "already closed before release was attempted", actor=actor)
    assert shared_bd.get_readonly(item_id).status == "resolved"

    outcome = shared_bd.release(item_id)

    assert outcome.already_closed is True
    # Structurally impossible to have reopened it: still resolved.
    back = shared_bd.get_readonly(item_id)
    assert back.status == "resolved"
    assert back.resolution == "already closed before release was attempted"
