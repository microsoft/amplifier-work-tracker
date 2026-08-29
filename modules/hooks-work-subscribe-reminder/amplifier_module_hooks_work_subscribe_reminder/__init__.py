"""Work-tracker subscription status reminder hook (amplifier-bxq).

Injects a COMPACT, cadence-gated status reminder for every work-tracker
project the current session is subscribed to: ready/held counts, whether
this session currently holds anything, and -- only when it does -- whether
that held item's custody is presently reclaim-eligible ("stale"). Shaped
exactly like the existing `hooks-todo-reminder` / `hooks-status-context`
system-reminder injections: same `<system-reminder source="...">` wrapper,
`ephemeral=True` (never stored in history), `suppress_output=True` (never
shown to the human), and an explicit "don't mention this to the user" note.

This module contains NO Beads/dolt knowledge of its own and imports nothing
from `amplifier_work_tracker` or `amplifier_module_tool_work_tracker`. Every
fact it reports comes from ONE source: the `work_tracker.reminder_snapshot`
CAPABILITY (`coordinator.get_capability`) that `amplifier_module_tool_work_
tracker.mount()` registers -- a bound async method on that module's
`WorkTrackerSession` (see its docstring). This is a deliberate "one home for
the domain logic" choice (see LANGUAGE_PHILOSOPHY.md / MODULAR_DESIGN_
PHILOSOPHY.md's "bricks and studs"): if tool-work-tracker is not mounted in
this session, `get_capability` returns `None` and this hook is a silent
no-op -- never a second, independently-recomputed status, and never an
error either (a session that doesn't use work-tracker at all should never
see this hook do anything, successfully or otherwise).

Fatigue avoidance ("must NOT fire every turn"): unlike `hooks-todo-reminder`
(which re-injects on every `provider:request` whenever a todo list exists)
this hook tracks a fingerprint of the last-injected snapshot and only
re-injects when that fingerprint actually CHANGES, or after `cadence_requests`
provider requests have passed since the last injection (default 20) --
whichever comes first. The cadence is a floor, not a ceiling: it exists so a
session that has held the exact same state for a long time still gets an
occasional re-affirmation (e.g. after a compaction rewrote its context), not
so it gets nagged every turn.
"""

from __future__ import annotations

# Amplifier module metadata
__amplifier_module_type__ = "hook"

import logging
from typing import Any

from amplifier_core import HookResult, ModuleCoordinator

logger = logging.getLogger(__name__)

_CAPABILITY_NAME = "work_tracker.reminder_snapshot"
_DEFAULT_CADENCE_REQUESTS = 20


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    """Mount the work-tracker subscription reminder hook.

    Args:
        coordinator: Module coordinator (used to read the
            `work_tracker.reminder_snapshot` capability at request time --
            never cached here, since the capability is only guaranteed to
            be registered once tool-work-tracker's own `mount()` has run,
            and mount order between sibling modules is not guaranteed).
        config: Optional configuration
            - inject_role: Role for context injection ("user" or "system",
              default: "user")
            - priority: Hook priority (default: 10, matches
              hooks-todo-reminder's priority so the two compact reminders
              order predictably relative to each other)
            - cadence_requests: Provider requests between forced
              re-injections when nothing has changed (default 20). See
              module docstring's "Fatigue avoidance" section.

    Returns:
        None (no cleanup needed -- this hook holds no resources of its own
        beyond a couple of small in-memory fields on the hook instance).
    """
    config = config or {}
    hook = WorkSubscribeReminderHook(coordinator, config)
    hook.register(coordinator.hooks)
    logger.info("Mounted hooks-work-subscribe-reminder")
    return


class WorkSubscribeReminderHook:
    """Hook that injects work-tracker subscription status before each LLM
    request -- but only on change or cadence (see module docstring).
    """

    def __init__(self, coordinator: ModuleCoordinator, config: dict[str, Any]):
        self.coordinator = coordinator
        self.inject_role = config.get("inject_role", "user")
        self.priority = config.get("priority", 10)
        self.cadence_requests = int(config.get("cadence_requests", _DEFAULT_CADENCE_REQUESTS))

        # Per-session state: what we last injected, and how many
        # provider:request cycles have passed since then. Both start "empty"
        # so the FIRST request that has anything to report always injects
        # (there is nothing to compare against yet).
        self._last_fingerprint: tuple[Any, ...] | None = None
        self._requests_since_injection = 0

    def register(self, hooks: Any) -> None:
        """Register on PROVIDER_REQUEST -- fires right before each LLM call,
        same event the two existing reminder hooks use.
        """
        hooks.register(
            "provider:request",
            self.on_provider_request,
            priority=self.priority,
            name="hooks-work-subscribe-reminder",
        )

    async def on_provider_request(self, event: str, data: dict[str, Any]) -> HookResult:
        snapshot_fn = self.coordinator.get_capability(_CAPABILITY_NAME)
        if snapshot_fn is None:
            # tool-work-tracker isn't mounted in this session -- silent no-op,
            # not an error. See module docstring's "one home for the domain
            # logic" note.
            return HookResult(action="continue")

        try:
            snapshot = await snapshot_fn()
        except Exception:
            # A reminder must never break a turn. Whatever the underlying
            # cause (transient dolt/bd read failure, etc.), the worst
            # outcome here is a missed reminder, not a failed LLM call.
            logger.debug("hooks-work-subscribe-reminder: reminder_snapshot() raised", exc_info=True)
            return HookResult(action="continue")

        subscriptions = snapshot.get("subscriptions") or []
        holding = snapshot.get("holding")
        if not subscriptions and not holding:
            # Nothing subscribed and nothing held -- genuinely nothing to
            # report. Reset cadence state so a LATER subscribe starts the
            # "always inject on first real state" behavior fresh, rather
            # than immediately hitting a stale non-None fingerprint.
            self._last_fingerprint = None
            self._requests_since_injection = 0
            return HookResult(action="continue")

        fingerprint = self._fingerprint(subscriptions, holding)
        self._requests_since_injection += 1
        if (
            fingerprint == self._last_fingerprint
            and self._requests_since_injection < self.cadence_requests
        ):
            return HookResult(action="continue")

        text = self._format(subscriptions, holding)
        self._last_fingerprint = fingerprint
        self._requests_since_injection = 0

        behavioral_note = (
            "\n\nDO NOT mention this reminder to the user. Process this silently "
            "and continue your work."
        )
        return HookResult(
            action="inject_context",
            context_injection=(
                f'<system-reminder source="hooks-work-subscribe-reminder">\n'
                f"{text}{behavioral_note}\n</system-reminder>"
            ),
            context_injection_role=self.inject_role,
            ephemeral=True,
            append_to_last_tool_result=True,
            suppress_output=True,
        )

    @staticmethod
    def _fingerprint(
        subscriptions: list[dict[str, Any]], holding: dict[str, Any] | None
    ) -> tuple[Any, ...]:
        """A hashable snapshot of exactly the fields `_format` renders, so
        "did anything change" can never disagree with "did anything the
        agent can actually see change." Any field NOT in this tuple (e.g.
        `last_activity`, aging buckets) is deliberately excluded: including
        it would make the reminder fire on data too fine-grained for a
        human/agent-facing compact status line to care about.
        """
        project_fp = tuple(
            (p.get("project"), p.get("status"), p.get("ready"), p.get("held"))
            for p in subscriptions
        )
        holding_fp = (
            (holding.get("project"), holding.get("id"), holding.get("custody_stale"))
            if holding
            else None
        )
        return (project_fp, holding_fp)

    @staticmethod
    def _format(subscriptions: list[dict[str, Any]], holding: dict[str, Any] | None) -> str:
        lines = ["Work-tracker subscription status:"]
        for p in subscriptions:
            project = p.get("project", "?")
            status = p.get("status")
            if status != "ok":
                lines.append(f"- {project}: {status}")
                continue
            lines.append(f"- {project}: ready={p.get('ready')} held={p.get('held')}")
        if holding:
            stale = holding.get("custody_stale")
            if stale is True:
                stale_text = "custody STALE -- may be reclaimed at any time"
            elif stale is False:
                stale_text = "custody fresh"
            else:
                stale_text = "custody state unknown (read failed)"
            lines.append(
                f"You currently hold {holding.get('id')} in {holding.get('project')} "
                f"({stale_text})."
            )
        else:
            lines.append("You are not currently holding any work-tracker item.")
        return "\n".join(lines)
