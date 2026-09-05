"""Tier 1 -- every adapter listing call reachable from a read-only route
passes an explicit, finite limit.

`contracts/operator-surface.v1.md` Core 10, machine check
`antigoals.enforced`: "every adapter call reached from a view passes an
explicit limit". The surface polls its whole body every 20 seconds
(`webapp._AUTO_REFRESH_MS`), so an unbounded read on a GET handler is not a
one-off cost -- it is three full-table materialisations a minute, per open
tab. `adapter.Beads.list`'s own docstring records what that costs at size.

This is a STATIC audit of the route modules -- the same technique the
conformance ledger's own route audit uses (`ledger/checks/_support.py`'s
`route_audit`, which walks GET handlers looking for mutating verbs). It is
duplicated here rather than imported on purpose: the ledger kit is a
self-contained auditor of this repo against a contract, and the product
suite must not depend on it to gate a merge.

WHAT IT CANNOT SEE, stated rather than implied: it follows calls by NAME,
module-locally, four levels deep -- the same honest bound `route_audit`
records. A listing call reached through a callable passed in from another
module is not visible to it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="the 'web' extra is not installed")

from amplifier_work_tracker import adapter as A  # noqa: E402
from amplifier_work_tracker import webbrowse as B  # noqa: E402

_SRC = Path(A.__file__).resolve().parent

#: The modules that register HTTP routes.
_ROUTE_MODULES = (_SRC / "webapp.py", _SRC / "webbrowse.py", _SRC / "webtrust.py")

#: Every adapter read that ACCEPTS a `limit` -- the calls Core 10's check is
#: about. A scalar read (`get`, `project_summary`) has nothing to bound and is
#: not listed. Derived by hand from `adapter.py`'s signatures and re-checked
#: below, so a new bounded read cannot join the seam unnoticed.
_BOUNDED_READS = frozenset(
    {
        "list",
        "list_bounded",
        "activity",
        "attention_items",
        "attention_items_from_rows",
        "recent_activity_feed",
    }
)

#: Helpers that make a listing call but are NOT reached from any route -- dead
#: code, which the clause as written does not condemn. Each one is re-checked
#: below to still BE dead: the exemption expires the moment it gains a caller.
_UNREACHED_EXEMPTIONS = frozenset({("webapp.py", "_oldest_ready_item")})

#: How deep the name-following goes. Matches the ledger's own route audit.
_DEPTH = 4


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.setdefault(node.name, node)
    return out


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                names.add(f.attr)
            elif isinstance(f, ast.Name):
                names.add(f.id)
    return names


def _is_read_only_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        if dec.func.attr in {"get", "head"}:
            return True
        if dec.func.attr == "api_route":
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List):
                    return any(
                        isinstance(e, ast.Constant) and e.value in {"GET", "HEAD"}
                        for e in kw.value.elts
                    )
            return True
    return False


def _reachable_functions(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """`fn` plus every module-local helper it reaches, bounded at `_DEPTH`."""
    seen: set[str] = set()
    out = [fn]
    frontier = _called_names(fn)
    for _ in range(_DEPTH):
        nxt: set[str] = set()
        for name in frontier - seen:
            seen.add(name)
            helper = funcs.get(name)
            if helper is not None and helper is not fn:
                out.append(helper)
                nxt |= _called_names(helper)
        frontier = nxt - seen
        if not frontier:
            break
    return out


def _limit_value(call: ast.Call, module_globals: dict[str, object]) -> object:
    """The `limit=` a bounded read passes, resolved to an int where it can be.

    Three outcomes, and the difference between the last two is the whole
    point:

      * `None` -- no `limit` keyword at all. That is the failure the clause
        names: the call inherits whatever default the seam happens to carry,
        and nobody at the call site can see what it is.
      * an `int` -- resolved. `0` is bd's own "unlimited" and fails; anything
        positive passes.
      * `"?"` -- a `limit` IS passed, but from an expression this static
        audit cannot evaluate (a function parameter, say). That is still
        EXPLICIT at the call site, which is what Core 10 asks for; where the
        value comes from is the caller's business, and pretending otherwise
        would make the audit fail on correct code.
    """

    def evaluate(node: ast.expr) -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return module_globals.get(node.id, "?")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = module_globals.get(node.value.id)
            return getattr(owner, node.attr, "?") if owner is not None else "?"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub | ast.Mult):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(left, int) and isinstance(right, int):
                if isinstance(node.op, ast.Add):
                    return left + right
                return left - right if isinstance(node.op, ast.Sub) else left * right
            return "?"
        return "?"

    for kw in call.keywords:
        if kw.arg == "limit":
            return evaluate(kw.value)
    return None


def _module_globals(path: Path) -> dict[str, object]:
    import importlib

    module = importlib.import_module(f"amplifier_work_tracker.{path.stem}")
    return vars(module)


def _view_listing_calls() -> list[tuple[str, int, str, object]]:
    """(module, line, handler, limit) for every listing call reachable from a
    read-only route handler."""
    found: list[tuple[str, int, str, object]] = []
    for path in _ROUTE_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = _functions(tree)
        module_globals = _module_globals(path)
        for handler in (f for f in funcs.values() if _is_read_only_route(f)):
            for fn in _reachable_functions(handler, funcs):
                for node in ast.walk(fn):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in _BOUNDED_READS
                    ):
                        found.append(
                            (
                                path.name,
                                node.lineno,
                                handler.name,
                                _limit_value(node, module_globals),
                            )
                        )
    return found


def test_the_audit_actually_finds_the_l1_listing_call():
    """A guard on the audit itself: an audit that silently matches nothing
    would pass forever while proving nothing. The L1 project view IS a
    read-only route that lists items -- if this stops finding it, the
    traversal broke, not the code under audit.
    """
    calls = _view_listing_calls()
    assert any(m == "webbrowse.py" and h == "project_view" for m, _, h, _ in calls), (
        f"the route traversal no longer reaches `project_view`'s item listing -- "
        f"found instead: {calls}"
    )


def test_every_listing_call_reached_from_a_read_only_route_passes_a_finite_limit():
    """Core 10. `limit=0` is bd's own \"unlimited\" (`adapter.Beads.list`'s
    docstring says so outright), and an omitted `limit` leaves bd's default
    in place implicitly -- the clause asks for an EXPLICIT bound, so both are
    failures here.
    """
    offenders = [
        (module, line, handler, limit)
        for module, line, handler, limit in _view_listing_calls()
        if limit is None or (isinstance(limit, int) and limit <= 0)
    ]
    assert not offenders, (
        "a view-reached adapter read does not pass an explicit, finite limit "
        "(`None` = no `limit=` at all, so the call silently inherits the seam's "
        'default; `0` = bd\'s own "unlimited"):\n  '
        + "\n  ".join(f"{m}:{ln} in {h}() -> limit={lim!r}" for m, ln, h, lim in offenders)
        + "\n\nThis surface re-renders every 20 seconds; an unbounded read here runs "
        "three times a minute per open tab."
    )


def test_the_exempted_uncapped_helpers_are_still_reached_by_nothing():
    """The exemption list is not a permanent pardon.

    `_oldest_ready_item` calls `bd.list(...)` with no limit at all and is
    exempt above for ONE reason: nothing calls it, so it is not "reached from
    a view". The instant it gains a caller that reason evaporates -- and this
    test is what notices, rather than the audit quietly continuing to skip it.
    """
    for module_name, func_name in sorted(_UNREACHED_EXEMPTIONS):
        source = (_SRC / module_name).read_text(encoding="utf-8")
        occurrences = source.count(func_name)
        assert occurrences == 1, (
            f"{module_name}: `{func_name}` now appears {occurrences}x (its own "
            f"definition plus {occurrences - 1} reference(s)). It makes an UNCAPPED "
            f"adapter listing call and was exempt from the bound audit only because "
            f"it was dead code. Give it an explicit limit, or delete it."
        )


# ------------------------------------------------------- the bound itself


def test_the_l1_ceiling_is_the_repo_s_existing_max_limit_convention():
    """Not a number invented for this view: `LIST_MAX_LIMIT` is what the CLI's
    own `list --limit` clamps to, and it is a whole number of this view's
    pages (`LIST_DEFAULT_LIMIT`), so paging can reach every row the query
    returns.
    """
    assert B._L1_ITEM_QUERY_LIMIT == A.LIST_MAX_LIMIT  # noqa: SLF001
    assert B._L1_ITEM_QUERY_LIMIT % A.LIST_DEFAULT_LIMIT == 0  # noqa: SLF001


# ------------------------------------------------- the honest truncation note


def test_truncation_note_is_silent_when_the_page_shows_everything():
    assert B._truncation_note_html(shown=12, matched=12, capped=False) == ""  # noqa: SLF001


def test_truncation_note_reports_the_real_total_when_the_read_was_not_capped():
    note = B._truncation_note_html(shown=50, matched=137, capped=False)  # noqa: SLF001
    assert "Showing 50 of 137 items" in note
    assert "137+" not in note  # 137 is measured, not a floor


def test_truncation_note_says_at_least_and_names_the_cap_when_the_read_was_bounded():
    """The one thing this note must never do is present a bounded window as a
    measured total.
    """
    note = B._truncation_note_html(  # noqa: SLF001
        shown=50, matched=B._L1_ITEM_QUERY_LIMIT, capped=True
    )
    assert f"Showing 50 of {B._L1_ITEM_QUERY_LIMIT}+ items" in note  # noqa: SLF001
    assert f"read capped at {B._L1_ITEM_QUERY_LIMIT}" in note  # noqa: SLF001
    assert "narrow with search or a status tab" in note


def test_truncation_note_speaks_up_when_capped_even_if_the_page_fits():
    """A filter can cut a capped read down to a handful of rows. The page then
    shows everything it matched -- but it only ever LOOKED at 500 items, and
    saying nothing would imply otherwise.
    """
    note = B._truncation_note_html(shown=3, matched=3, capped=True)  # noqa: SLF001
    assert note != ""
    assert "Showing 3 of 3+ items" in note
