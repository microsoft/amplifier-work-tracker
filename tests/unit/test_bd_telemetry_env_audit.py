"""Static audit: every subprocess invocation of the `bd` binary anywhere in
`src/amplifier_work_tracker` must route its environment through
`adapter._bd_env` -- directly, via `Beads._env` (which itself delegates to
`_bd_env`), or via a local variable that was itself assigned from one of
those.

Why this exists: round 1 of the telemetry-disable fix touched `Beads._run`
(via `_env`) and missed the bare `bd init` subprocess in
`Workspace.create` -- proof that "remember to pass env= at every call site"
does not hold up as a discipline. `bd`'s first-use telemetry-consent prompt
reads from stdin and blocks forever when there is no tty (true of every
agent session), so a missed call site is a HANG, not a degraded experience.
This test exists so the next missed call site is a test failure here, not a
stuck DTU session three fixes from now.

Static, not dynamic: we walk the AST looking for
`subprocess.run(["bd", ...], ...)` (and Popen/call/check_output/check_call)
shapes, PLUS `_run_bounded(["bd", ...], ...)` / `A._run_bounded(...)` --
the one seam every `bd`/`dolt`/`git` subprocess call in this module now
goes through (see its docstring: it wraps `subprocess.Popen` for
process-group-safe timeout handling) -- and check each one for an `env=`
keyword that traces back to a call to `_bd_env` / `Beads._env`. We check
source shape, not runtime behaviour, because exercising every call site
here would need a real (or stubbed) `bd` on PATH for each one and would
still miss call sites whose branch never executes on this machine. A
textual audit catches "a new bd subprocess call forgot env=" regardless of
what's installed.

Scope note: the "safe names" pass below is FILE-scoped, not scope-aware --
if the identifier `env` is assigned from `_bd_env(...)` ANYWHERE in a file,
every `env=env` in that file is accepted. That is looser than real Python
scoping, but sufficient for this codebase's straightforward, single-purpose
functions; nothing here reuses the name `env` for anything unrelated to a
`bd` subprocess call.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "amplifier_work_tracker"

_SUBPROCESS_METHODS = {"run", "Popen", "call", "check_output", "check_call"}
_ENV_HELPER_ATTRS = {"_bd_env", "_env"}
_BOUNDED_RUNNER_NAME = "_run_bounded"


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == _BOUNDED_RUNNER_NAME:
        return True  # e.g. `A._run_bounded(...)` from contract.py
    if isinstance(func, ast.Name) and func.id == _BOUNDED_RUNNER_NAME:
        return True  # bare `_run_bounded(...)` from within adapter.py itself
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _SUBPROCESS_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _is_bd_argv(node: ast.expr | None) -> bool:
    """True if `node` is a list/tuple literal whose first element is the
    string literal "bd" -- i.e. this call invokes `bd` itself, not `git`,
    `systemctl`, or anything else that also happens to run as a subprocess
    in this package."""
    if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value == "bd"


def _calls_env_helper(expr: ast.expr) -> bool:
    """True if `expr` is (or contains) a call to `_bd_env` / `Beads._env`,
    however it's spelled: `_bd_env(...)`, `A._bd_env(...)`,
    `self._env(...)`."""
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name) and fn.id in _ENV_HELPER_ATTRS:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr in _ENV_HELPER_ATTRS:
                return True
    return False


def _safe_names_in_file(tree: ast.Module) -> set[str]:
    """Every identifier that is ever assigned a value built from the
    telemetry-env helper, anywhere in the file (see module docstring's
    "Scope note" for why this is intentionally file-scoped, not
    scope-aware)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _calls_env_helper(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _violations_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    safe_names = _safe_names_in_file(tree)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
            continue
        if not node.args or not _is_bd_argv(node.args[0]):
            continue
        env_kw = next((kw for kw in node.keywords if kw.arg == "env"), None)
        ok = env_kw is not None and (
            _calls_env_helper(env_kw.value)
            or (isinstance(env_kw.value, ast.Name) and env_kw.value.id in safe_names)
        )
        if not ok:
            violations.append(f"{path.name}:{node.lineno}")
    return violations


def test_every_bd_subprocess_call_routes_through_the_telemetry_env_helper():
    assert SRC.is_dir(), f"expected package source at {SRC}"
    violations: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        violations += _violations_in_file(path)
    assert not violations, (
        "bd subprocess call(s) found whose env= does not route through "
        "adapter._bd_env / Beads._env -- BD_NON_INTERACTIVE (the verified, "
        "real non-interactive switch -- see _bd_env's docstring for why "
        "BD_TELEMETRY_DISABLE was replaced, it does not exist in the bd "
        "binary) would not reach them, risking a hang on bd's first-use "
        "consent prompt in any tty-less (agent) session: " + ", ".join(violations)
    )


def test_helper_itself_is_found_by_the_audit_in_at_least_one_real_call_site():
    """Guard against the audit silently checking zero call sites (e.g. if
    the source layout changes and `SRC.glob` stops matching anything) --
    a test that always passes because it finds nothing to complain about
    is worse than no test at all."""
    checked_bd_calls = 0
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and _is_subprocess_call(node)
                and node.args
                and _is_bd_argv(node.args[0])
            ):
                checked_bd_calls += 1
    assert checked_bd_calls >= 5, (
        f"expected to find several bd subprocess call sites to audit, found "
        f"{checked_bd_calls} -- did the source layout change?"
    )
