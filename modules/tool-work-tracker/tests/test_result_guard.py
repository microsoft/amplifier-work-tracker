"""The 2026-08-15 audit finding: 401 `work_*` tool calls in one week, ZERO
recorded `result_success = false` -- including calls that a resolved blob
proved genuinely failed. Domain-level failures (`adapter.BeadsError` and
friends) were already caught by each tool's own `except` clauses and turned
into an honest `ToolResult(success=False, ...)`, but nothing caught the
UNEXPECTED case: an exception a tool's own code did not anticipate (a
malformed `bd` response, a missing binary, a plain bug) escaped `execute()`
uncaught, leaving whatever calls it to guess whether that was a success.

These tests prove two things, both required for the fix to count as done:

  1. `_guard.guarded` itself: wraps ANY exception into an honest
     `ToolResult(success=False, ...)` instead of letting it propagate, but
     never touches a call that already returns a normal `ToolResult`, and
     never swallows `asyncio.CancelledError` (which must keep propagating --
     that is task cancellation, not a tool failure).

  2. Every one of the module's nine `work_*`/`work_tracker_*` tools actually
     has this net applied to its own `execute()` -- proven both
     structurally (every Tool class's `execute` is the wrapped function) and
     behaviorally (a forced, REAL, unexpected exception through two
     representative tools' real call paths comes back as `success=False`,
     never as a raised exception the test itself has to catch).

Before this fix: every behavioral test below FAILS -- not with a clean
assertion failure, but by letting the injected exception escape `execute()`
uncaught (pytest reports it as a raised, unhandled exception). That is the
literal bug this PR closes: a caller one layer up cannot rely on getting a
`ToolResult` back at all, let alone a truthful one.
"""

from __future__ import annotations

import asyncio

import pytest
from amplifier_core import ToolResult
from amplifier_module_tool_work_tracker import (
    WorkAddTool,
    WorkClaimTool,
    WorkDeclareTool,
    WorkFileTool,
    WorkListTool,
    WorkResolveTool,
    WorkStatusTool,
    WorkTrackerSession,
)
from amplifier_module_tool_work_tracker._guard import guarded
from amplifier_module_tool_work_tracker.service_tools import (
    WorkTrackerInstallTool,
    WorkTrackerStatusTool,
)

import amplifier_work_tracker.adapter as A

ALL_TOOL_CLASSES = [
    WorkClaimTool,
    WorkDeclareTool,
    WorkResolveTool,
    WorkStatusTool,
    WorkFileTool,
    WorkAddTool,
    WorkListTool,
    WorkTrackerStatusTool,
    WorkTrackerInstallTool,
]


def _unique(prefix: str) -> str:
    import uuid

    return f"{prefix}{uuid.uuid4().hex[:10]}"


# --------------------------------------------------------------- unit: guarded


@pytest.mark.asyncio
async def test_guarded_turns_an_unexpected_exception_into_an_honest_failure():
    class _Boom:
        name = "fake_tool"

        @guarded
        async def execute(self, input):
            raise RuntimeError("something nobody anticipated")

    result = await _Boom().execute({})
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "fake_tool" in str(result.output)
    assert "something nobody anticipated" in str(result.output)


@pytest.mark.asyncio
async def test_guarded_passes_through_a_normal_result_untouched():
    class _Fine:
        name = "fake_tool"

        @guarded
        async def execute(self, input):
            return ToolResult(success=True, output={"ok": True})

    result = await _Fine().execute({})
    assert result.success is True
    assert result.output == {"ok": True}


@pytest.mark.asyncio
async def test_guarded_never_swallows_a_real_failed_toolresult():
    """A tool that deliberately returns success=False (the normal,
    already-correct path) must be passed through exactly as-is -- the guard
    is a net for exceptions, not a rewrite of results tools already got
    right."""

    class _AlreadyHonest:
        name = "fake_tool"

        @guarded
        async def execute(self, input):
            return ToolResult(success=False, output="a domain-level failure, handled normally")

    result = await _AlreadyHonest().execute({})
    assert result.success is False
    assert result.output == "a domain-level failure, handled normally"


@pytest.mark.asyncio
async def test_guarded_does_not_swallow_cancellation():
    """asyncio.CancelledError is a BaseException, not an Exception -- task
    cancellation must keep propagating, never get rewritten into a failed
    ToolResult."""

    class _Cancelled:
        name = "fake_tool"

        @guarded
        async def execute(self, input):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _Cancelled().execute({})


# ------------------------------------------------ structural: every tool wrapped


def test_every_tool_classs_execute_is_guarded():
    """If a new work_* tool is ever added without the guard, this fails
    immediately naming the offender -- rather than silently reintroducing
    the exact gap this PR closes."""
    unguarded = [
        cls.__name__ for cls in ALL_TOOL_CLASSES if not hasattr(cls.execute, "__wrapped__")
    ]
    assert unguarded == [], f"tool classes missing @guarded on execute(): {unguarded}"


# ------------------------------------------- behavioral: real tools, real paths


@pytest.mark.asyncio
async def test_work_add_reports_an_unexpected_non_beads_error_honestly(tmp_path, monkeypatch):
    """Force a REAL, unexpected (non-BeadsError) exception through work_add's
    actual call path -- exactly the class of failure a malformed `bd`
    response or an unrelated bug in our own code would produce. Before the
    fix: this exception propagates out of `execute()` uncaught (the test
    itself fails with an unhandled RuntimeError, not a clean assertion).

    `Workspace.project()` only requires a `.beads` DIRECTORY to exist (see
    `adapter.py`'s `names()`/`project()`) -- fabricating that bare directory
    (never a real `bd init`) is enough for `_project()` to succeed and hand
    back a real `Beads` instance, so the injected exception below is the
    ONLY thing standing between this call and a normal return.
    """
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))
    (root / "projects" / "does-not-matter" / ".beads").mkdir(parents=True)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated unanticipated adapter failure")

    monkeypatch.setattr(A.Beads, "create", _boom)

    session = WorkTrackerSession({"actor": _unique("actor")})
    tool = WorkAddTool(session)
    result = await tool.execute({"project": "does-not-matter", "title": "some title"})

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "simulated unanticipated adapter failure" in str(result.output)


@pytest.mark.asyncio
async def test_work_claim_reports_an_unexpected_non_beads_error_honestly(tmp_path, monkeypatch):
    """Same class of gap, through work_claim's queue-claim path this time --
    the tool the original outage report was specifically about the
    neighbor of (work_add)."""
    root = tmp_path / "root"
    monkeypatch.setenv("AMPLIFIER_WORK_TRACKER_ROOT", str(root))
    (root / "projects" / "does-not-matter" / ".beads").mkdir(parents=True)

    def _boom(*args, **kwargs):
        raise TypeError("simulated malformed bd response")

    monkeypatch.setattr(A.Beads, "claim_next", _boom)

    session = WorkTrackerSession({"actor": _unique("actor")})
    tool = WorkClaimTool(session)
    result = await tool.execute({"project": "does-not-matter"})

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "simulated malformed bd response" in str(result.output)
