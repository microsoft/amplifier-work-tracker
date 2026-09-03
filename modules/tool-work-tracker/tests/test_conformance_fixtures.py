"""Conformance Fixtures 2, 3 and 4 of `contracts/custody-coordination.v1.md`
(§Conformance Kit) -- the Freeze Bar's "All four Conformance fixtures
implemented, passing, and executable via `make test`" (ledger row CCV1-023,
work item `pipeline-qmj`).

Each fixture in the contract is written as a GOOD/BAD pair: a named correct
behaviour and the named incorrect behaviour it must be told apart from. A
test that only exercises the good half discriminates nothing -- it passes
just as happily against the broken implementation. So every fixture below
pins BOTH halves, and says which is which.

WHY THIS FILE LIVES IN THE MODULE SUITE
---------------------------------------
All three fixtures are written in the contract against the AGENT SEAM --
"call `work_resolve(id)`", "call `work_status()`", "claim -> claim again".
That seam is `WorkTrackerSession`, which lives in this module, so this is
the only suite that can exercise the fixtures as the contract states them.
`modules/tool-work-tracker/tests` runs in `make test` and in CI as its own
pytest invocation (ledger row CCV1-022, Makefile target `test-module`,
`.github/workflows/ci.yml`).

The contract's own "Test location" lines for these three fixtures name
paths that do not exist (`tests/test_reap_recovery.py:67-72`,
`tests/test_recovery.py`, `tests/test_single_hold.py`) -- stale pointers
recorded as drift by ledger row CCV1-023. This file is the real location;
the contract text is not edited from here.

WHAT IS DELIBERATELY NOT DUPLICATED
-----------------------------------
- Fixture 1 (conflicted-but-landed close) already exists, and passes, at
  `tests/integration/test_phantom_conflict_recovery.py`. Not re-stated here.
- Fixture 2's ADAPTER-layer half is pinned in full at
  `tests/integration/test_post_reclaim_fence.py` (row CCV1-009). This file
  pins the TOOL-layer half the contract actually describes, plus the one
  adapter call the tool seam has no verb for (an integrator's close of an
  item nobody holds -- PR #51, item `pipeline-79t`).

Real `bd`/dolt end-to-end against this suite's isolated per-session dolt
server (skipped if `bd` is not on PATH, matching this module's other tests).
"""

from __future__ import annotations

import dataclasses
import shutil
import threading
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession

import amplifier_work_tracker.adapter as A
import amplifier_work_tracker.supervisor as SV

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)

#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its isolated-server database again on teardown.
PROJECT_PREFIX = "cfixproj"


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _bd(session: WorkTrackerSession, project_name: str) -> A.Beads:
    """The adapter handle for `project_name`, as the session itself builds
    it. Used only where a fixture must reach BELOW the tool seam -- to drive
    the real reap sweep, or to act as a different actor than this session."""
    return session._project(project_name)  # noqa: SLF001 -- test-only reach


def _force_reap(session: WorkTrackerSession, project_name: str) -> dict[str, Any]:
    """The REAL sweep, with `ttl_seconds=0` so every current hold is stale
    immediately -- no real sleep needed to manufacture staleness, and the
    post-reclaim state is produced by the code that produces it in
    production rather than by a test's imitation of it."""
    return SV.reap_project(_bd(session, project_name), ttl_seconds=0)


def _snapshot(session: WorkTrackerSession, project_name: str, item_id: str) -> dict[str, Any]:
    """The item's entire record, read through the contention-free read-only
    path (`get_readonly` -> a pure SELECT, which cannot itself mutate or
    lose a serialization conflict). Compared field-for-field before and
    after a recovery call to prove that call wrote NOTHING."""
    return dataclasses.asdict(_bd(session, project_name).get_readonly(item_id))


class _RunOnceThenStop:
    """Fakes `threading.Event`'s `.wait()`/`.is_set()` shape so `_renew_loop`
    executes its body exactly once and then exits -- the real method, the
    real exception handling, no mocking of `adapter`/`bd` itself, and no
    racing a real 120s timer interval."""

    def __init__(self) -> None:
        self._calls = 0

    def wait(self, timeout: float | None = None) -> bool:  # noqa: ARG002 -- Event's signature
        self._calls += 1
        return self._calls > 1

    def set(self) -> None:  # noqa: A003 -- matches threading.Event's API
        pass

    def is_set(self) -> bool:
        return False


async def _claim_one(project_name: str, title: str) -> tuple[WorkTrackerSession, str]:
    """Add an item as one session and claim it through the tool seam as
    another -- the ordinary shape every fixture below starts from."""
    adder = WorkTrackerSession({"actor": _unique("adder")})
    added = await adder.add(project_name, title, acceptance="n/a")
    assert added.success is True
    item_id: str = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": _unique("holder")})
    claimed = await session.claim(project_name, item_id=item_id)
    assert claimed.success is True
    assert claimed.output["claimed"] == item_id  # type: ignore[index]
    return session, item_id


# ===========================================================================
# Fixture 2 -- Post-reclaim close fence (contract §Conformance, from D-2)
#
#   Scenario:  item claimed by Session A; the reclaim sweep moves it to open
#              and strips custody; Session A, unaware, calls work_resolve().
#   GOOD:      the close is refused -- "not held by this session" / reclaim.
#   BAD:       the close succeeds; the item is closed by a stale holder.
#
# The fence fix has landed on this branch (`fix: fence a post-reclaim close
# on custody identity, not item status`, ledger row CCV1-009 -> CONFORMS),
# so the refusal is asserted DIRECTLY -- no xfail.
# ===========================================================================


@pytest.mark.asyncio
async def test_fixture2_bad_half_stale_holders_resolve_is_refused_after_a_real_reap(project):
    """BAD half. The discriminator: against the pre-fix implementation this
    close LANDED (the fence ran only under `if current.status == "held"`,
    and a reaped item is `open`), so the two assertions that fail there are
    the refusal itself and the item still being `open` afterwards.
    """
    session, item_id = await _claim_one(project, "fixture 2: stale holder's close")

    reaped = _force_reap(session, project)
    assert reaped["reclaimed_count"] == 1
    assert reaped["reclaimed"][0]["id"] == item_id

    # The state under test: released, not yet re-claimed, custody record
    # still naming the holder that no longer holds anything.
    before = _bd(session, project).get_readonly(item_id)
    assert before.status == "open"
    assert before.holder is None

    refused = await session.resolve(item_id, "closing work reclaimed while I was away")
    assert refused.success is False
    assert "reclaimed" in str(refused.output).lower()

    # The refusal must not have closed it anyway.
    after = _bd(session, project).get_readonly(item_id)
    assert after.status == "open"
    assert after.resolution is None


@pytest.mark.asyncio
async def test_fixture2_good_half_a_live_holders_resolve_still_succeeds(project):
    """GOOD half 1. The fence must never refuse the session that genuinely
    holds the item -- a fence that refuses everyone passes the BAD half
    above for the wrong reason, which is exactly what this pins.
    """
    session, item_id = await _claim_one(project, "fixture 2: live holder's close")

    resolved = await session.resolve(item_id, "finished the work I actually hold")
    assert resolved.success is True
    assert resolved.output["resolved"] == item_id  # type: ignore[index]
    assert _bd(session, project).get_readonly(item_id).status == "resolved"


@pytest.mark.asyncio
async def test_fixture2_good_half_integrator_close_of_a_reclaimed_item_still_succeeds(project):
    """GOOD half 2. PR #51 (item `pipeline-79t`): closing out an item nobody
    currently holds stays a SINGLE call for anyone who is not the stale
    holder -- including after a real reap, which is when unfinished reports
    most need closing out.

    Reaches below the tool seam on purpose: `work_resolve` requires holding
    the item, so an integrator's close has no tool verb. The discriminator
    between the two halves is the custody record's `holder`, not the item's
    status, and this is the half that proves the fence was keyed on identity
    rather than made universal.
    """
    session, item_id = await _claim_one(project, "fixture 2: integrator's close")
    assert _force_reap(session, project)["reclaimed_count"] == 1

    bd = _bd(session, project)
    rec = bd.get(item_id).meta.get(A.C.CUSTODY_KEY)
    assert isinstance(rec, dict) and rec["holder"] != "integrator"

    back = bd.resolve(item_id, "closed out by the integrator", actor="integrator")
    assert back.status == "resolved"


# ===========================================================================
# Fixture 3 -- In-process recovery after reclaim (contract §Conformance,
#              from Core 8)
#
#   Scenario:  a session holds an item; custody is lost or the item is
#              closed out from under it; the session calls a tool.
#   GOOD:      the loss is visible, and a recovery path clears the latch
#              WITHOUT manual intervention or a restart.
#   BAD:       the session is left ambiguous -- it believes it holds the
#              item, every tool refuses, and there is no recovery path.
#
# The contract's Backlogged §"Recovery verb" names the specific hazard the
# recovery path must not have: "`work_release` on a resolved item would
# reopen it". `adapter.Beads.release` checks status BEFORE any write and
# performs no write at all when the item is already resolved, so the
# byte-identical assertion below is the fixture's real discriminator.
# ===========================================================================


@pytest.mark.asyncio
async def test_fixture3_release_of_an_already_closed_held_item_clears_the_latch(project):
    """GOOD half, and the fixture's core case: a wedged session -- one whose
    close already LANDED while it still believes it holds the item -- clears
    its own latch in-process via `work_release`, gets the sanctioned
    `already_closed` outcome, and can claim again immediately.

    The wedge is produced the way it really arises: the close lands at the
    adapter (as this very holder, so no fence fires) without the tool seam
    ever learning about it -- the phantom-conflict shape PR #63 fixed the
    reporting half of. `session._held` therefore still names the item.
    """
    session, item_id = await _claim_one(project, "fixture 3: wedged session")

    held = session._held  # noqa: SLF001
    assert held is not None
    _bd(session, project).resolve(
        item_id, "close landed; the wrapper never saw it", actor=held.actor
    )

    # Wedged exactly as the incident describes: bd says resolved, the
    # session still believes it holds the item.
    assert session._held is not None  # noqa: SLF001
    before = _snapshot(session, project, item_id)
    assert before["status"] == "resolved"

    recovered = await session.unclaim(item_id)
    assert recovered.success is True
    out: dict[str, Any] = recovered.output  # type: ignore[assignment]
    assert out["released"] == item_id
    assert "already closed" in out["custody"]

    # BAD half: the recovery call must not have REOPENED (or otherwise
    # touched) the closed item. Not "still resolved" -- byte-identical, so a
    # write that happened to land on the same status is caught too.
    assert _snapshot(session, project, item_id) == before

    # Latch cleared in-process: no restart, no manual intervention.
    assert session._held is None  # noqa: SLF001
    assert held.stop.is_set()

    adder = WorkTrackerSession({"actor": _unique("adder")})
    nxt = await adder.add(project, "fixture 3: work after recovery", acceptance="n/a")
    again = await session.claim(project)
    assert again.success is True
    assert again.output["claimed"] == nxt.output["added"]  # type: ignore[index]
    await session.resolve(nxt.output["added"], "test cleanup")  # type: ignore[index]


@pytest.mark.asyncio
async def test_fixture3_work_status_reports_custody_lost_while_the_hold_is_retained(project):
    """GOOD half: the passive signal the contract's Core 4 names --
    `holding.custody_lost` -- is actually visible at the tool seam, so a
    session can DISCOVER a renewal failure without any tool refusing it
    first.

    Driven through the real `_renew_loop` (one deterministic pass) against a
    renewal that fails without fencing: bd still considers this session the
    holder, so the hold is deliberately RETAINED and the loss is reported
    rather than acted on. This is the state in which `custody_lost` is
    non-null; see the fenced counterpart below for the other outcome.
    """
    session, item_id = await _claim_one(project, "fixture 3: custody_lost signal")
    held = session._held  # noqa: SLF001
    assert held is not None
    held.stop.set()  # stop the real background thread; drive the loop by hand

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise A.BeadsError("simulated transient renew_custody failure")

    # `_renew_loop` builds its own `Beads` instance internally, so the patch
    # must be at the class level to reach it.
    original = A.Beads.renew_custody
    A.Beads.renew_custody = _boom  # type: ignore[method-assign, assignment]
    try:
        held.stop = _RunOnceThenStop()  # type: ignore[assignment]
        session._renew_loop(held)  # noqa: SLF001
    finally:
        A.Beads.renew_custody = original  # type: ignore[method-assign]

    reported = await session.status()
    holding = reported.output["holding"]  # type: ignore[index]
    assert holding is not None, (
        "BAD half: the hold vanished from work_status, so a session that lost "
        "renewal has no way to see WHICH item it is still holding"
    )
    assert holding["id"] == item_id
    assert holding["custody_lost"] == "simulated transient renew_custody failure"

    held.stop = threading.Event()  # restore a real Event for cleanup
    assert (await session.resolve(item_id, "test cleanup")).success is True


@pytest.mark.asyncio
async def test_fixture3_a_fenced_reclaim_clears_the_latch_with_no_manual_step(project):
    """GOOD half, the other outcome: when the renewal failure IS a fence --
    the reclaim sweep genuinely took the item away -- the recovery happens
    without the session having to ask for it. The latch is dropped by the
    loop itself, so `work_status` honestly reports no hold and the next
    `work_claim` succeeds.

    BAD half (the self-poisoning bug this pins): leaving `self._held` set
    here refused `work_claim`/`work_declare`/`work_resolve` for ANY item for
    the rest of the process's life, with no tool call able to clear it --
    precisely the "no recovery path" the contract's Fixture 3 names.
    """
    session, item_id = await _claim_one(project, "fixture 3: fenced reclaim")
    held = session._held  # noqa: SLF001
    assert held is not None
    held.stop.set()  # stop the real background thread; drive the loop by hand

    assert _force_reap(session, project)["reclaimed_count"] == 1

    held.stop = _RunOnceThenStop()  # type: ignore[assignment]
    session._renew_loop(held)  # noqa: SLF001

    assert held.lost_reason is not None
    assert "reclaimed" in held.lost_reason.lower() or "reassigned" in held.lost_reason.lower()
    assert session._held is None  # noqa: SLF001

    reported = await session.status()
    assert reported.output["holding"] is None  # type: ignore[index]

    # The item itself was returned to the queue by the sweep, not closed.
    assert _bd(session, project).get_readonly(item_id).status == "open"

    again = await session.claim(project, item_id=item_id)
    assert again.success is True
    await session.resolve(item_id, "test cleanup")


# ===========================================================================
# Fixture 4 -- Single-hold constraint (contract §Conformance, from Core 12)
#
#   Scenario:  a session holds item A and attempts to claim item B without
#              releasing A.
#   GOOD:      the claim is refused -- "already holding item A".
#   BAD:       the claim succeeds and the session now holds two items.
#
# Both claim modes are pinned: a directed claim is not a lesser claim
# (Core 1), so it must be refused on exactly the same terms as a queue claim.
# ===========================================================================


@pytest.mark.asyncio
async def test_fixture4_a_directed_second_claim_is_refused_while_holding(project):
    """BAD half's discriminator, directed mode. Two facts must hold: the
    call is refused naming the item already held, AND item B is genuinely
    untouched -- an implementation that refuses AFTER claiming B would pass
    a refusal-only assertion while holding two items.
    """
    session, a_id = await _claim_one(project, "fixture 4: item A (directed)")

    adder = WorkTrackerSession({"actor": _unique("adder")})
    b = await adder.add(project, "fixture 4: item B (directed)", acceptance="n/a")
    b_id: str = b.output["added"]  # type: ignore[index]

    refused = await session.claim(project, item_id=b_id)
    assert refused.success is False
    assert "already holding" in str(refused.output)
    assert a_id in str(refused.output), "the refusal must name WHICH item is held"

    # Still exactly one hold, and B was never claimed.
    assert session._held is not None  # noqa: SLF001
    assert session._held.item_id == a_id  # noqa: SLF001
    b_after = _bd(session, project).get_readonly(b_id)
    assert b_after.status == "open"
    assert b_after.holder is None

    await session.resolve(a_id, "test cleanup")


@pytest.mark.asyncio
async def test_fixture4_a_queue_second_claim_is_refused_while_holding(project):
    """Same refusal, queue mode -- the default `work_claim(project)` path
    with no `item_id`. Pinned separately because the two modes take
    different branches inside `claim()` after the shared single-hold gate,
    and a regression could easily reinstate one without the other.
    """
    session, a_id = await _claim_one(project, "fixture 4: item A (queue)")

    adder = WorkTrackerSession({"actor": _unique("adder")})
    b = await adder.add(project, "fixture 4: item B (queue)", acceptance="n/a")
    b_id: str = b.output["added"]  # type: ignore[index]

    refused = await session.claim(project)
    assert refused.success is False
    assert "already holding" in str(refused.output)

    assert session._held is not None  # noqa: SLF001
    assert session._held.item_id == a_id  # noqa: SLF001
    assert _bd(session, project).get_readonly(b_id).holder is None

    await session.resolve(a_id, "test cleanup")


@pytest.mark.asyncio
async def test_fixture4_the_second_claim_succeeds_once_the_first_is_resolved(project):
    """GOOD half. The constraint is one hold AT A TIME, not one hold per
    session for all time -- a refusal that never lifts would satisfy every
    assertion above while making the session useless after one item.
    """
    session, a_id = await _claim_one(project, "fixture 4: resolve then claim (A)")

    adder = WorkTrackerSession({"actor": _unique("adder")})
    b = await adder.add(project, "fixture 4: resolve then claim (B)", acceptance="n/a")
    b_id: str = b.output["added"]  # type: ignore[index]

    assert (await session.resolve(a_id, "done with A")).success is True
    second = await session.claim(project, item_id=b_id)
    assert second.success is True
    assert second.output["claimed"] == b_id  # type: ignore[index]

    await session.resolve(b_id, "test cleanup")


@pytest.mark.asyncio
async def test_fixture4_the_second_claim_succeeds_once_the_first_is_released(project):
    """GOOD half, via the other exit from a hold: `work_release` sets no
    resolution, so the constraint must lift there too. Pinned separately
    because `resolve` and `unclaim` clear `self._held` at different sites.
    """
    session, a_id = await _claim_one(project, "fixture 4: release then claim (A)")

    adder = WorkTrackerSession({"actor": _unique("adder")})
    b = await adder.add(project, "fixture 4: release then claim (B)", acceptance="n/a")
    b_id: str = b.output["added"]  # type: ignore[index]

    assert (await session.unclaim(a_id)).success is True
    second = await session.claim(project, item_id=b_id)
    assert second.success is True
    assert second.output["claimed"] == b_id  # type: ignore[index]

    # A really did go back to the queue, with no resolution set.
    a_after = _bd(session, project).get_readonly(a_id)
    assert a_after.status == "open"
    assert a_after.resolution is None

    await session.resolve(b_id, "test cleanup")
