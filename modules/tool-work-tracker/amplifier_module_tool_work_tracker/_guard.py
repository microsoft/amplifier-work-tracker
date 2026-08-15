"""Last-resort honesty net for every `work_*`/`work_tracker_*` tool's
`execute()`.

Measured 2026-08-08 -> 2026-08-15 by a context-intelligence audit of the
session graph: 401 `work_*` tool calls that week, ZERO recorded
`result_success = false` -- including calls a resolved blob proved genuinely
failed. Domain-level failures (`adapter.BeadsError` and its `FencedError`
subclass) were already caught by each tool's own `except` clauses and
returned as an honest `ToolResult(success=False, ...)`. What was NOT
covered: an exception nobody anticipated -- a malformed `bd` JSON response
producing a `KeyError`, a missing binary producing `FileNotFoundError`, a
plain bug in our own code -- escaping `execute()` uncaught. Whatever calls a
tool's `execute()` may or may not turn an uncaught exception into an honest
`success=False` result; that boundary lives outside this module (in
amplifier-core, or in whatever wraps tool dispatch for observability) and we
do not control it. What we DO control is never handing that boundary an
exception to guess about in the first place.

`@guarded` is that guarantee: it wraps a tool's `execute(input)` so it always
returns a `ToolResult`, never raises. A call that already returns a
`ToolResult` (success or failure) passes through completely untouched --
this is a net for exceptions, not a rewrite of results tools already get
right. `asyncio.CancelledError` (a `BaseException`, not an `Exception`) is
deliberately NOT caught -- task cancellation must keep propagating; it is
not a tool failure to report.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from amplifier_core import ToolResult

# `self` is deliberately typed `Any`, not a TypeVar: every concrete Tool
# class has its own unrelated type, and the decorator never inspects
# anything about `self` beyond an optional `.name` attribute (see
# `_wrapped` below) -- there is no meaningful relationship to a return type
# for a type-checker to verify by binding a single-use TypeVar here.
_Execute = Callable[[Any, dict[str, Any]], Awaitable[ToolResult]]


def guarded(execute: _Execute) -> _Execute:
    """Decorator for a Tool class's `async def execute(self, input)`.

    Catches any `Exception` the wrapped call does not itself handle and
    converts it into `ToolResult(success=False, ...)` naming the tool and
    the underlying error -- so the outer envelope a caller (human,
    automated retry, or observability layer) inspects is never dishonestly
    silent about a real failure. Sets `__wrapped__` (via
    `functools.wraps`), which this module's own test suite uses to prove
    structurally that every tool actually has this applied.
    """

    @functools.wraps(execute)
    async def _wrapped(self: Any, input: dict[str, Any]) -> ToolResult:
        try:
            return await execute(self, input)
        except Exception as e:  # noqa: BLE001 -- last-resort net, see module docstring
            tool_name = getattr(self, "name", type(self).__name__)
            return ToolResult(
                success=False,
                output=f"{tool_name} failed unexpectedly: {type(e).__name__}: {e}",
            )

    return _wrapped
