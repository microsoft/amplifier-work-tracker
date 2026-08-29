"""`hooks-work-subscribe-reminder` -- pure unit tests against a stub
coordinator/capability. No Beads, no dolt, no network: this hook has no
domain knowledge of its own (see module docstring), so its whole
contract -- fingerprint/cadence gating and rendered text -- can be proven
against a fake `work_tracker.reminder_snapshot` capability alone.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from amplifier_core import HookResult
from amplifier_module_hooks_work_subscribe_reminder import WorkSubscribeReminderHook


class _StubCoordinator:
    """Just enough of `ModuleCoordinator` for this hook: a capability
    registry the hook reads via `get_capability`. Deliberately NOT a
    `ModuleCoordinator` subclass (that's a Rust-backed concrete class, not a
    Protocol) -- `_make_hook` below is the one place that bridges the two
    for the type checker, via an explicit `cast`, so every test just uses
    the plain duck-typed stub.
    """

    def __init__(self):
        self._capabilities: dict[str, object] = {}

    def register_capability(self, name: str, value: object) -> None:
        self._capabilities[name] = value

    def get_capability(self, name: str):
        return self._capabilities.get(name)


def _make_hook(
    coordinator: _StubCoordinator, config: dict[str, Any] | None = None
) -> WorkSubscribeReminderHook:
    return WorkSubscribeReminderHook(cast(Any, coordinator), config or {})


def _injected(result: HookResult) -> str:
    """Narrow `HookResult.context_injection` (typed `str | None`) to `str`
    for an already-asserted `action == "inject_context"` result -- that
    invariant isn't encoded in `HookResult`'s own type, so every caller
    must narrow it explicitly rather than each repeating an `assert
    ... is not None`.
    """
    assert result.context_injection is not None
    return result.context_injection


def _snapshot(subscriptions=None, holding=None):
    async def _fn():
        return {"subscriptions": subscriptions or [], "holding": holding}

    return _fn


@pytest.mark.asyncio
async def test_no_capability_registered_is_a_silent_noop():
    coordinator = _StubCoordinator()  # nothing registered
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_no_subscriptions_and_not_holding_is_a_noop():
    coordinator = _StubCoordinator()
    coordinator.register_capability("work_tracker.reminder_snapshot", _snapshot())
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_snapshot_raising_is_swallowed_never_breaks_the_turn():
    async def _raises():
        raise RuntimeError("boom")

    coordinator = _StubCoordinator()
    coordinator.register_capability("work_tracker.reminder_snapshot", _raises)
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "continue"


@pytest.mark.asyncio
async def test_first_call_with_real_state_always_injects():
    coordinator = _StubCoordinator()
    coordinator.register_capability(
        "work_tracker.reminder_snapshot",
        _snapshot(subscriptions=[{"project": "acme", "status": "ok", "ready": 3, "held": 1}]),
    )
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "inject_context"
    assert result.ephemeral is True
    assert result.suppress_output is True
    assert result.append_to_last_tool_result is True
    assert "hooks-work-subscribe-reminder" in _injected(result)
    assert "acme" in _injected(result)
    assert "ready=3" in _injected(result)
    assert "held=1" in _injected(result)


@pytest.mark.asyncio
async def test_unchanged_state_does_not_reinject_before_cadence():
    subs = [{"project": "acme", "status": "ok", "ready": 3, "held": 1}]
    coordinator = _StubCoordinator()
    coordinator.register_capability("work_tracker.reminder_snapshot", _snapshot(subscriptions=subs))
    hook = _make_hook(coordinator, {"cadence_requests": 5})

    first = await hook.on_provider_request("provider:request", {})
    assert first.action == "inject_context"

    for _ in range(3):
        again = await hook.on_provider_request("provider:request", {})
        assert again.action == "continue"


@pytest.mark.asyncio
async def test_cadence_forces_reinjection_even_with_unchanged_state():
    subs = [{"project": "acme", "status": "ok", "ready": 3, "held": 1}]
    coordinator = _StubCoordinator()
    coordinator.register_capability("work_tracker.reminder_snapshot", _snapshot(subscriptions=subs))
    hook = _make_hook(coordinator, {"cadence_requests": 3})

    first = await hook.on_provider_request("provider:request", {})
    assert first.action == "inject_context"

    second = await hook.on_provider_request("provider:request", {})
    assert second.action == "continue"
    third = await hook.on_provider_request("provider:request", {})
    assert third.action == "continue"
    # Third call since the last injection reaches the cadence ceiling.
    fourth = await hook.on_provider_request("provider:request", {})
    assert fourth.action == "inject_context"


@pytest.mark.asyncio
async def test_change_in_ready_count_forces_reinjection_before_cadence():
    coordinator = _StubCoordinator()
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        ready = 3 if calls["n"] == 1 else 4  # changes on the second call
        return {
            "subscriptions": [{"project": "acme", "status": "ok", "ready": ready, "held": 1}],
            "holding": None,
        }

    coordinator.register_capability("work_tracker.reminder_snapshot", _fn)
    hook = _make_hook(coordinator, {"cadence_requests": 100})

    first = await hook.on_provider_request("provider:request", {})
    assert first.action == "inject_context"
    assert "ready=3" in _injected(first)

    second = await hook.on_provider_request("provider:request", {})
    assert second.action == "inject_context"
    assert "ready=4" in _injected(second)


@pytest.mark.asyncio
async def test_holding_fresh_custody_is_rendered():
    coordinator = _StubCoordinator()
    coordinator.register_capability(
        "work_tracker.reminder_snapshot",
        _snapshot(holding={"project": "acme", "id": "acme-1", "custody_stale": False}),
    )
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "inject_context"
    assert "acme-1" in _injected(result)
    assert "custody fresh" in _injected(result)


@pytest.mark.asyncio
async def test_holding_stale_custody_is_rendered_and_flagged():
    coordinator = _StubCoordinator()
    coordinator.register_capability(
        "work_tracker.reminder_snapshot",
        _snapshot(holding={"project": "acme", "id": "acme-1", "custody_stale": True}),
    )
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "inject_context"
    assert "STALE" in _injected(result)


@pytest.mark.asyncio
async def test_holding_unknown_custody_is_rendered_honestly():
    coordinator = _StubCoordinator()
    coordinator.register_capability(
        "work_tracker.reminder_snapshot",
        _snapshot(holding={"project": "acme", "id": "acme-1", "custody_stale": None}),
    )
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "inject_context"
    assert "unknown" in _injected(result)


@pytest.mark.asyncio
async def test_non_error_project_status_reported_as_is():
    coordinator = _StubCoordinator()
    coordinator.register_capability(
        "work_tracker.reminder_snapshot",
        _snapshot(subscriptions=[{"project": "broken", "status": "creating"}]),
    )
    hook = _make_hook(coordinator)
    result = await hook.on_provider_request("provider:request", {})
    assert result.action == "inject_context"
    assert "broken: creating" in _injected(result)


@pytest.mark.asyncio
async def test_state_becoming_empty_resets_cadence_for_next_real_state():
    coordinator = _StubCoordinator()
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        if calls["n"] == 2:
            return {"subscriptions": [], "holding": None}
        return {
            "subscriptions": [{"project": "acme", "status": "ok", "ready": 1, "held": 0}],
            "holding": None,
        }

    coordinator.register_capability("work_tracker.reminder_snapshot", _fn)
    hook = _make_hook(coordinator, {"cadence_requests": 100})

    first = await hook.on_provider_request("provider:request", {})
    assert first.action == "inject_context"

    empty = await hook.on_provider_request("provider:request", {})
    assert empty.action == "continue"

    # State reappears identical to what was injected before the gap -- must
    # inject again immediately (cadence state was reset by the empty gap),
    # not wait out the full cadence window.
    third = await hook.on_provider_request("provider:request", {})
    assert third.action == "inject_context"
