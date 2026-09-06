"""Reap-recovery: proves `WorkTrackerSession` does NOT self-poison after its
claim is reclaimed while it was away.

Bug this guards against: `resolve()` / `declare()` cleared `self._held`
ONLY on the success path. On the `except A.BeadsError` branch -- the
"your claim was reclaimed" case -- they returned failure WITHOUT clearing
`self._held` and without stopping the custody thread. Consequence: claim X
-> X reaped while idle -> `work_resolve(X)` correctly refuses -> `work_declare`
and `work_claim` for ANY item are refused for the rest of that process's
life. No tool call clears it; only a fresh process recovers. `_renew_loop`
had the identical gap on its own scheduled cadence, and mutated
`held.generation` / `held.lost_reason` without holding `self._lock` at all.

Real `bd`/dolt end-to-end (skipped if `bd` is not on PATH, matching this
module's other tests) -- proves the fix against the real storage layer's
reap/fence behavior, not just this module's own beliefs about it.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from amplifier_module_tool_work_tracker import WorkTrackerSession, _Held

import amplifier_work_tracker.adapter as A
import amplifier_work_tracker.supervisor as SV

pytestmark = pytest.mark.skipif(
    shutil.which("bd") is None, reason="real `bd` binary not present in this environment"
)


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


#: Consumed by the shared `project` fixture in conftest.py, which creates
#: the project AND drops its shared-server database again on teardown.
PROJECT_PREFIX = "reapproj"


def _force_reap(session: WorkTrackerSession, project_name: str) -> dict[str, Any]:
    """Reap with ttl_seconds=0 -- everything currently held is immediately
    stale, regardless of how recently custody was actually taken. Avoids a
    real sleep to manufacture staleness."""
    bd = session._project(project_name)  # noqa: SLF001 -- test-only reach
    return SV.reap_project(bd, ttl_seconds=0)


@pytest.mark.asyncio
async def test_explicit_resolve_refusal_after_reap_clears_held_and_allows_new_claim(project):
    """Trigger path 1: the explicit `work_resolve` refusal. Claim -> force
    reap -> resolve refuses (fenced) -> but the SAME session's next
    `work_claim` must still succeed, in the same process.

    Was `xfail(strict=True)` for ledger row CCV1-009 (`work_item_pipeline-dn4`)
    while `Beads.resolve`'s fence ran only under `if current.status == "held"`
    and a reaped item is `open`, so the stale holder's close landed. That
    PRODUCT defect is fixed -- the fence is now keyed on custody IDENTITY,
    not item status, and CCV1-009 reads CONFORMS -- so the marker was
    XPASSing (strict) and failing this suite. Removed rather than re-aimed:
    the behaviour it described no longer exists. The same refusal is pinned
    as a discriminating good/bad pair in `test_conformance_fixtures.py`
    (contract Fixture 2) and at the adapter layer in
    `tests/integration/test_post_reclaim_fence.py`."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    first = await add_session.add(project, "first reap-recovery item", acceptance="n/a")
    assert first.success is True

    session = WorkTrackerSession({"actor": _unique("resolver")})
    claimed = await session.claim(project)
    assert claimed.success is True
    item_id = claimed.output["claimed"]  # type: ignore[index]

    reaped = _force_reap(session, project)
    assert reaped["reclaimed_count"] == 1

    resolved = await session.resolve(item_id, "trying to close after being reclaimed")
    assert resolved.success is False
    assert "reclaimed" in str(resolved.output).lower()

    # The fix: session state must not stay poisoned.
    assert session._held is None  # noqa: SLF001

    second = await add_session.add(project, "second reap-recovery item", acceptance="n/a")
    assert second.success is True
    second_id = second.output["added"]  # type: ignore[index]

    reclaimed = await session.claim(project)
    assert reclaimed.success is True
    assert reclaimed.output["claimed"] == second_id  # type: ignore[index]


@pytest.mark.asyncio
async def test_post_reap_refusal_originates_below_the_session_latch(project):
    """MECHANISM PIN for the test directly above -- ledger rows CCV1-009
    (Core 7) and CCV1-023 (Freeze 3), work item `model_performance-c0e`.

    The test above asserts THAT the post-reap resolve is refused. It does
    not assert WHERE the refusal comes from, and the ledger once recorded
    the wrong answer: CCV1-023's seeded note said this fixture "asserts the
    TOOL-layer refusal (which passes via the session latch)". The session
    latch is not a fence -- after a reap it still names the item, so it
    passes the call straight THROUGH. The refusal is the ADAPTER's
    custody-identity fence (`resolve_outcome`'s `elif cust_holder == who
    and current.holder != who`, PR #68 / b3fac1e).

    Prose cannot hold that distinction still, so this pins it executably.
    Each assertion below fails under a different regression:

      1. the latch still names the item at the moment of the refused call
         -- if the refusal ever moves UP into the latch, this is the first
         thing that has to change, and it changes here first;
      2. the ADAPTER refuses on its own, with no `WorkTrackerSession` in
         the picture at all -- delete the fence branch and this raises
         nothing (measured: the close then LANDS, `success=True`);
      3. the refusal the tool surfaces is the fence's wording, not the
         latch's -- a latch-sourced refusal would say "did not claim";
      4. the other half of Core 7, at the same site: an integrator's plain
         close of that same unheld item still succeeds in one call. A fence
         keyed on "the item is unheld" rather than on custody IDENTITY
         would pass 1-3 and fail here.
    """
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "mechanism-pin item", acceptance="n/a")
    assert added.success is True

    session = WorkTrackerSession({"actor": _unique("stale")})
    claimed = await session.claim(project)
    assert claimed.success is True
    item_id = claimed.output["claimed"]  # type: ignore[index]

    assert _force_reap(session, project)["reclaimed_count"] == 1

    # 1. The latch is NOT the fence: it still names this very item, so
    #    `resolve`'s own `held.item_id != item_id` gate cannot refuse.
    held = session._held  # noqa: SLF001 -- test-only reach
    assert held is not None, "the latch was cleared before the resolve was even attempted"
    assert held.item_id == item_id
    stale_actor = held.actor

    bd = session._project(project)  # noqa: SLF001
    after_reap = bd.get(item_id)
    assert after_reap.status == "open"
    assert after_reap.holder is None

    # 2. The adapter refuses by itself -- no session, no latch.
    with pytest.raises(A.FencedError) as exc:
        bd.resolve(item_id, "closing after the reap, straight at the adapter", actor=stale_actor)
    assert "not held by this session" in str(exc.value)
    assert bd.get(item_id).status == "open", "the fenced call must not have written anything"

    # 3. What the tool surfaces is the FENCE's text, not the latch's.
    refused = await session.resolve(item_id, "trying to close after being reclaimed")
    assert refused.success is False
    message = str(refused.output)
    assert "custody names" in message, (
        f"the refusal no longer carries the adapter fence's wording: {message!r}"
    )
    assert "did not claim" not in message, (
        "the refusal is now the SESSION LATCH's -- the mechanism this row's note "
        f"says is not the one operating: {message!r}"
    )

    # 4. Core 7's other half, same item, same state: everyone who is not the
    #    stale holder is exactly as unfenced as before.
    integrator = bd.resolve(item_id, "closed out by the integrator", actor=_unique("integrator"))
    assert integrator.status == "resolved"


@pytest.mark.asyncio
async def test_explicit_declare_refusal_after_reap_clears_held_and_allows_new_claim(project):
    """Same trigger path, via `work_declare` instead of `work_resolve` --
    both refusal sites had the identical self-poisoning gap."""
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    first = await add_session.add(project, "declare reap item", acceptance="n/a")
    assert first.success is True

    session = WorkTrackerSession({"actor": _unique("declarer")})
    claimed = await session.claim(project)
    assert claimed.success is True

    reaped = _force_reap(session, project)
    assert reaped["reclaimed_count"] == 1

    declared = await session.declare("working")
    assert declared.success is False
    assert (
        "reclaimed" in str(declared.output).lower() or "reassigned" in str(declared.output).lower()
    )

    assert session._held is None  # noqa: SLF001

    second = await add_session.add(project, "declare reap item 2", acceptance="n/a")
    second_id = second.output["added"]  # type: ignore[index]
    reclaimed = await session.claim(project)
    assert reclaimed.success is True
    assert reclaimed.output["claimed"] == second_id  # type: ignore[index]


@pytest.mark.asyncio
async def test_background_renew_loop_detects_reap_and_clears_held_state(project):
    """Trigger path 2: the background `_renew_loop` detecting the loss on
    its own scheduled cadence -- the "held an item long enough to be reaped,
    did nothing else" path this bundle exists to survive.

    Establishes custody exactly like `claim()` does, but WITHOUT starting
    the real background thread, so this test can drive `_renew_loop`
    directly and deterministically instead of racing a real timer interval.
    A fake `stop` event (`.wait()` False once, then True) makes the loop
    execute its body exactly once -- the real method, the real exception
    handling, no mocking of `adapter`/`bd` itself.
    """
    actor = _unique("bgactor")
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "bg reap item", acceptance="n/a")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": actor})
    bd = session._project(project)  # noqa: SLF001
    item = bd.claim_next(lane=A.LANE_WORK, actor=actor)
    assert item is not None and item.id == item_id
    rec = bd.take_custody(item.id, holder=actor, pid=12345, host="test-host")

    held = _Held(project=project, item_id=item.id, actor=actor, generation=rec["generation"])
    session._held = held  # noqa: SLF001

    reaped = _force_reap(session, project)
    assert reaped["reclaimed_count"] == 1

    class _RunOnceThenStop:
        """Fakes `threading.Event`'s `.wait()` shape: False the first call
        (so the loop body runs once), True thereafter (so it exits).
        `.is_set()` mirrors the same never-externally-stopped state --
        `_renew_loop`'s own "stopped while waiting for the lock" check
        needs it (see work_tracker item pipeline-yym part 3)."""

        def __init__(self) -> None:
            self._calls = 0

        def wait(self, timeout: float | None = None) -> bool:
            self._calls += 1
            return self._calls > 1

        def set(self) -> None:  # noqa: A003 -- matches threading.Event's API
            pass

        def is_set(self) -> bool:
            return False

    held.stop = _RunOnceThenStop()  # type: ignore[assignment]  # noqa: SLF001
    session._renew_loop(held)  # noqa: SLF001

    assert held.lost_reason is not None
    assert "reclaimed" in held.lost_reason.lower() or "reassigned" in held.lost_reason.lower()
    # The fix: the loop's own detection must clear session state too, not
    # just the explicit resolve()/declare() refusal paths.
    assert session._held is None  # noqa: SLF001

    second = await add_session.add(project, "bg reap item 2", acceptance="n/a")
    second_id = second.output["added"]  # type: ignore[index]
    reclaimed = await session.claim(project)
    assert reclaimed.success is True
    assert reclaimed.output["claimed"] == second_id  # type: ignore[index]


@pytest.mark.asyncio
async def test_background_renew_loop_generic_failure_does_not_clear_held(project, monkeypatch):
    """Contrast case: a plain (non-fenced) `BeadsError` from `renew_custody`
    must NOT clear `self._held` -- bd still considers this session the
    holder, so `work_resolve` must still be reachable via its own live
    fence check even though background renewal gave up."""
    actor = _unique("genericactor")
    add_session = WorkTrackerSession({"actor": _unique("adder")})
    added = await add_session.add(project, "generic failure item", acceptance="n/a")
    item_id = added.output["added"]  # type: ignore[index]

    session = WorkTrackerSession({"actor": actor})
    bd = session._project(project)  # noqa: SLF001
    item = bd.claim_next(lane=A.LANE_WORK, actor=actor)
    assert item is not None and item.id == item_id
    rec = bd.take_custody(item.id, holder=actor, pid=12345, host="test-host")

    held = _Held(project=project, item_id=item.id, actor=actor, generation=rec["generation"])
    session._held = held  # noqa: SLF001

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise A.BeadsError("simulated transient renew_custody failure")

    # `_renew_loop` builds its OWN `Beads` instance internally (`self._project(...)`
    # is called fresh each time), so patching the `bd` instance above would not
    # reach it -- patch at the class level instead.
    monkeypatch.setattr(A.Beads, "renew_custody", _boom)

    class _RunOnceThenStop:
        def __init__(self) -> None:
            self._calls = 0

        def wait(self, timeout: float | None = None) -> bool:
            self._calls += 1
            return self._calls > 1

        def set(self) -> None:
            pass

        def is_set(self) -> bool:
            return False

    held.stop = _RunOnceThenStop()  # type: ignore[assignment]  # noqa: SLF001
    session._renew_loop(held)  # noqa: SLF001

    assert held.lost_reason == "simulated transient renew_custody failure"
    # Not fenced -- session must still believe it holds the item.
    assert session._held is held  # noqa: SLF001

    resolved = await session.resolve(item_id, "closing despite a transient renew hiccup")
    assert resolved.success is True
