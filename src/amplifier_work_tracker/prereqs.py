"""Prerequisite checks for the `bd` and `dolt` BINARIES themselves.

These are not part of this package -- they are prerequisites for it. Every
other module in this repo (`service.py`, `supervisor.py`,
`amplifier_module_tool_work_tracker.service_tools`) assumes both are already
on PATH and usable. That assumption is false on a genuinely fresh machine: a
user who installs only the work-tracker behavior bundle and asks a session to
"use work-tracker for a new task" may have neither binary, and nothing above
this module currently says so -- `work_tracker_status` would misreport (or a
downstream `bd`/`dolt` invocation would fail with a raw, unexplained
FileNotFoundError) before ever reaching actionable advice.

This module answers exactly three questions, in dependency order (mirroring
cli.py's `cmd_doctor` / `_check_dolt_reachable`, which already skips
downstream checks once an upstream one fails rather than piling on
unrelated red):

  1. Is `bd` on PATH at all?
  2. If so, does its version meet `adapter.MIN_VERSION`? Below the floor,
     `ready --claim` -- the ONLY atomic claim path -- does not exist, so
     only a claim path that double-claims under contention is available.
  3. Is `dolt` on PATH at all?

`check()` returns the first of these that fails, and nothing else -- exactly
one `PrereqResult`, or `None` when both prerequisites are satisfied. Callers
(`amplifier_module_tool_work_tracker.service_tools.classify_state`) must
call this FIRST and skip their own service/port checks entirely when it
returns non-None: there is no point classifying "is the service running"
when there is no `bd` to run `bd init` against in the first place.

Deliberately NEVER downloads or installs anything itself. Both reference
projects this bundle is modeled on (amplifier-browser-bridge, muxplex)
refuse ambient side effects for exactly this class of action -- see
`service_tools.py`'s module docstring for the same rule applied to
`work_tracker_install`. This module only *reports*: the exact state, and the
exact command a human or agent can choose to run. Report, never act.

Install command provenance -- keep this in sync, never let it drift
----------------------------------------------------------------------
The commands this module prints are NOT invented here. They mirror
`.github/workflows/ci.yml`'s "Install bd (pinned)" / "Install dolt (pinned)"
steps line for line (same release repos, same asset-name patterns, same
extraction shape) -- that workflow is the executable proof these commands
actually work, run on every push. The one deliberate difference: CI installs
to `/usr/local/bin` via `sudo install` because it owns the runner; this
module has no business assuming sudo on someone's machine, so it installs to
`~/.local/bin` instead (already the OS-appropriate PATH-only convenience
directory `service.py`'s `_resolve_bin_tokens` already prefers).

`tests/unit/test_prereqs.py::test_ci_workflow_pins_match_our_constants`
parses `ci.yml`'s `BD_VERSION` / `DOLT_VERSION` env block with a plain regex
(no YAML dependency needed for two `KEY: "value"` lines) and asserts it
equals what this module emits -- that test is what makes "cannot drift" true
rather than aspirational. `BD_VERSION` itself is never duplicated as a
separate string here: it is derived from `adapter.MIN_VERSION`, the same
constant CI's own comment already says must be bumped in lockstep.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from typing import Literal

from . import adapter as A

PrereqState = Literal["bd_missing", "bd_too_old", "dolt_missing"]

# Keep in sync with .github/workflows/ci.yml's DOLT_VERSION env var -- see
# test_prereqs.py::test_ci_workflow_pins_match_our_constants, which fails
# loudly the moment these diverge. bd's own pinned version is NOT duplicated
# here -- it is derived from adapter.MIN_VERSION below, so there is exactly
# one Python constant to bump.
DOLT_INSTALL_VERSION = "2.2.3"

_BEADS_RELEASES = "https://github.com/gastownhall/beads/releases"
_DOLT_RELEASES = "https://github.com/dolthub/dolt/releases"


@dataclass
class PrereqResult:
    """One failed prerequisite: which one, and the exact command to fix it."""

    state: PrereqState
    fix: str


def bd_install_version() -> str:
    """The bd version this module installs -- always `adapter.MIN_VERSION`,
    never a second, independently-drifting string."""
    return ".".join(str(p) for p in A.MIN_VERSION)


def _os_arch() -> tuple[str, str]:
    """(os, arch) in the vocabulary bd/dolt release asset names use.

    Never guessed silently: an OS/arch this function does not recognize
    raises `RuntimeError` naming exactly what was unrecognized, rather than
    emitting a command that will 404 for a platform this module has no
    evidence works.
    """
    system = platform.system().lower()  # 'linux', 'darwin', 'windows'
    machine = platform.machine().lower()  # 'x86_64', 'amd64', 'arm64', 'aarch64'

    if system == "linux":
        os_name = "linux"
    elif system == "darwin":
        os_name = "darwin"
    else:
        raise RuntimeError(
            f"no known bd/dolt release asset for platform {system!r} -- install both manually: "
            f"{_BEADS_RELEASES} and {_DOLT_RELEASES}"
        )

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        raise RuntimeError(
            f"no known bd/dolt release asset for architecture {machine!r} -- install both "
            f"manually: {_BEADS_RELEASES} and {_DOLT_RELEASES}"
        )

    return os_name, arch


def bd_install_command() -> str:
    """The exact command to install the pinned `bd` build to `~/.local/bin`.

    Mirrors ci.yml's "Install bd (pinned)" step (same release repo, same
    `beads_<ver>_<os>_<arch>.tar.gz` asset pattern, same extract-then-install
    shape) with one deliberate difference: `~/.local/bin` + no sudo, since
    this runs on someone's machine, not a CI runner this workflow owns.

    Raises `RuntimeError` (never returns a command) if this OS/arch has no
    known published asset -- e.g. beads does not publish a darwin_amd64
    build today, only linux_amd64, linux_arm64, and darwin_arm64.
    """
    os_name, arch = _os_arch()
    version = bd_install_version()
    if os_name == "darwin" and arch == "amd64":
        raise RuntimeError(
            f"beads does not publish a darwin_amd64 release asset -- only linux_amd64, "
            f"linux_arm64, and darwin_arm64 today. Check {_BEADS_RELEASES} for what's available, "
            f"or build from source."
        )
    asset = f"beads_{version}_{os_name}_{arch}.tar.gz"
    url = f"{_BEADS_RELEASES}/download/v{version}/{asset}"
    return (
        f"mkdir -p ~/.local/bin /tmp/bd-{version} && "
        f"curl -fsSL -o /tmp/{asset} '{url}' && "
        f"tar -xzf /tmp/{asset} -C /tmp/bd-{version} && "
        f"install -m 0755 /tmp/bd-{version}/bd ~/.local/bin/bd && "
        f"rm -rf /tmp/{asset} /tmp/bd-{version} && "
        f"bd --version"
    )


def dolt_install_command() -> str:
    """The exact command to install the pinned `dolt` build to `~/.local/bin`.

    Mirrors ci.yml's "Install dolt (pinned)" step (same release repo, same
    `dolt-<os>-<arch>.tar.gz` asset pattern with `--strip-components=1`,
    since dolt's tarball nests everything under one top-level directory
    unlike bd's flat layout) with the same sudo-free `~/.local/bin`
    adaptation as `bd_install_command`.
    """
    os_name, arch = _os_arch()
    version = DOLT_INSTALL_VERSION
    asset = f"dolt-{os_name}-{arch}.tar.gz"
    url = f"{_DOLT_RELEASES}/download/v{version}/{asset}"
    return (
        f"mkdir -p ~/.local/bin /tmp/dolt-{version} && "
        f"curl -fsSL -o /tmp/{asset} '{url}' && "
        f"tar -xzf /tmp/{asset} -C /tmp/dolt-{version} --strip-components=1 && "
        f"install -m 0755 /tmp/dolt-{version}/bin/dolt ~/.local/bin/dolt && "
        f"rm -rf /tmp/{asset} /tmp/dolt-{version} && "
        f"dolt version"
    )


def _safe_command(builder) -> str:
    """Run an install-command builder, falling back to its own RuntimeError
    message (which already names the release pages) if this OS/arch has no
    known asset -- callers of `check()` must always get SOME actionable
    text, never an unhandled exception from a status probe."""
    try:
        return builder()
    except RuntimeError as e:
        return str(e)


def check() -> PrereqResult | None:
    """Probe `bd` presence, `bd` version, then `dolt` presence, in that
    order, stopping at the first failure -- the same dependency-ordering
    rule `cli.py`'s `cmd_doctor` already applies to `service.installed` /
    `dolt.reachable` (once one fails, downstream checks would only restate
    the same root cause, so they are skipped rather than piling on).

    Returns `None` when both prerequisites are satisfied -- callers proceed
    to service/port classification. Never raises: a missing binary is the
    expected, common "fresh machine" case this function exists to name
    gracefully, not an error condition.
    """
    if shutil.which("bd") is None:
        return PrereqResult(
            "bd_missing", f"bd is not on PATH. Install it: {_safe_command(bd_install_command)}"
        )

    try:
        v = A.version()
    except A.BeadsError as e:
        return PrereqResult(
            "bd_too_old",
            f"bd is on PATH but its version could not be determined ({e}) -- reinstall the "
            f"pinned build: {_safe_command(bd_install_command)}",
        )
    if v < A.MIN_VERSION:
        floor = ".".join(str(p) for p in A.MIN_VERSION)
        have = ".".join(str(p) for p in v)
        return PrereqResult(
            "bd_too_old",
            f"bd {have} is below the supported floor {floor} -- this is not negotiable: below "
            f"it, `ready --claim` (the only ATOMIC claim path) does not exist at all, leaving "
            f"only a claim path measured to double-claim under real contention. Upgrade: "
            f"{_safe_command(bd_install_command)}",
        )

    if shutil.which("dolt") is None:
        return PrereqResult(
            "dolt_missing",
            f"dolt is not on PATH. Install it: {_safe_command(dolt_install_command)}",
        )

    return None


__all__ = [
    "DOLT_INSTALL_VERSION",
    "PrereqResult",
    "PrereqState",
    "bd_install_command",
    "bd_install_version",
    "check",
    "dolt_install_command",
]
