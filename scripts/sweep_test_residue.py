#!/usr/bin/env python3
"""One-time sweep of orphaned TEST databases left on a shared dolt server.

This is an operator tool for cleaning up residue that older runs already
left behind. It is deliberately NOT wired into the test suite, `doctor`,
CI, or any install path: the suite now drops what it creates (see
`tests/conftest.py` and `contract.Probe`), so nothing should ever need to
run this twice on the same machine. A destructive command that runs itself
automatically is how you lose data you meant to keep.

What it removes, and nothing else
---------------------------------
Only names matching the exact patterns in `RESIDUE_PATTERNS` below -- each
one a fixture prefix from this repo's own suites followed by the
uuid4/timestamp suffix that fixture appends. A real project name
(`amplifier`, `cortex`, `beads_global`, anything a human chose) cannot
match: every pattern requires a machine-generated suffix of a fixed shape.
Anything that does not match is reported as PROTECTED and left alone.

Safety
------
- Dry run by default. `--confirmed` is required to drop anything.
- Every database it would drop is named in full before it drops any.
- Every database it will NOT touch is named too, so a surprise is visible
  before it becomes a deletion.
- `--held-check` (default on) refuses to drop any residue database that
  still has HELD items, in case a name collided with something real.
- Dropping goes through `adapter.drop_database`, this repo's own removal
  primitive -- never raw SQL from this script.

Usage
-----
    python scripts/sweep_test_residue.py                  # dry run, shows the plan
    python scripts/sweep_test_residue.py --confirmed      # actually drop
    python scripts/sweep_test_residue.py --patterns       # show what counts as residue
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from amplifier_work_tracker import adapter as A  # noqa: E402 - follows the sys.path insert above
from amplifier_work_tracker import supervisor as SV  # noqa: E402 - same

#: A residue name is a fixture prefix plus a machine-generated suffix. Both
#: halves are required -- `^contract` alone would match a human's project
#: called `contracts`, and a bare prefix list would match far too much.
#:
#: | pattern            | minted by                                            |
#: |--------------------|------------------------------------------------------|
#: | contract<ts><pid>  | `contract.Probe` -- one per `doctor` run             |
#: | ...<ts><pid>rm     | `contract.check_project_removal`'s removal probe     |
#: | shared<hex12>      | `tests/conftest.py::shared_project_name`             |
#: | proj<hex12>        | `tests/conftest.py::unique_project_name` / factory   |
#: | existingok<hex12>  | `tests/unit/test_adapter_mapping.py`                 |
#: | residue<hex12>     | `tests/integration/test_no_database_residue.py`      |
#: | neverwas<hex12>    | same                                                 |
#: | wlempty<hex12>     | `tests/integration/test_work_list.py`                |
#: | listproj<hex10>    | `modules/tool-work-tracker/tests/test_work_list.py`  |
#: | listempty<hex10>   | same (pre-fix; the test now reuses `project`)        |
#: | addproj<hex10>     | `modules/tool-work-tracker/tests/test_work_add.py`   |
#: | reapproj<hex10>    | `.../test_reap_recovery.py`                          |
#: | modproj<hex10>     | `.../conftest.py` default prefix                     |
RESIDUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^contract\d{10,}(rm)?$"),
    re.compile(
        r"^(shared|proj|existingok|residue|neverwas|wlempty)[0-9a-f]{12}$",
    ),
    re.compile(
        r"^(listproj|listempty|addproj|reapproj|modproj)[0-9a-f]{10}$",
    ),
)


def is_residue(name: str) -> bool:
    return any(p.match(name) for p in RESIDUE_PATTERNS)


def list_databases(host: str, port: int) -> list[str]:
    """Every database on the server, via the same information_schema read
    `adapter.database_exists` uses (never a `show databases` substring
    match, which could false-match a neighbouring name)."""
    import subprocess

    p = subprocess.run(
        [
            "dolt",
            "--host",
            host,
            "--port",
            str(port),
            "--no-tls",
            "sql",
            "-q",
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA",
            "-r",
            "csv",
        ],
        capture_output=True,
        text=True,
        env=A._bd_env(),  # noqa: SLF001 - non-interactive env, see its docstring
        check=False,
    )
    if p.returncode != 0:
        raise SystemExit(
            f"could not list databases on {host}:{port}: "
            f"{(p.stderr or p.stdout).strip()[:500]}\n"
            f"Is the shared dolt server running? "
            f"(`amplifier-work-tracker doctor` reports on it.)"
        )
    rows = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    return sorted(rows[1:])  # drop the CSV header


def held_items(name: str, root: Path) -> list[str]:
    """Item ids currently HELD in `name`, or [] if that cannot be
    determined without attaching to the database.

    A residue database has no local `.beads` directory (that is what makes
    it residue), and attaching one just to look would mean running a real
    `bd init` against a database we are about to drop. So this only
    reports for databases the operator happens to also have locally --
    which is the case that could plausibly be real work.
    """
    ws = A.Workspace(root)
    if not (ws.path(name) / ".beads").is_dir():
        return []
    try:
        return [i.id for i in ws.project(name).list(include_resolved=False) if i.status == "held"]
    except A.BeadsError:
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Drop orphaned test-residue databases from a shared dolt server.",
        epilog="Dry run unless --confirmed is passed.",
    )
    ap.add_argument("--host", default=SV.DEFAULT_DOLT_HOST, help="dolt host (default: %(default)s)")
    ap.add_argument(
        "--port", type=int, default=SV.DEFAULT_DOLT_PORT, help="dolt port (default: %(default)s)"
    )
    ap.add_argument(
        "--confirmed",
        action="store_true",
        help="actually drop the databases listed by a dry run. Without this, nothing is dropped.",
    )
    ap.add_argument(
        "--no-held-check",
        action="store_true",
        help="skip the HELD-items check (only sensible if a check is wrongly blocking a sweep)",
    )
    ap.add_argument(
        "--patterns",
        action="store_true",
        help="print the residue patterns and exit, without contacting any server",
    )
    args = ap.parse_args(argv)

    if args.patterns:
        print("A database is treated as test residue only if it matches one of:")
        for p in RESIDUE_PATTERNS:
            print(f"  {p.pattern}")
        print("\nEverything else is PROTECTED and never dropped.")
        return 0

    root = Path(
        os.environ.get("AMPLIFIER_WORK_TRACKER_ROOT", Path.home() / ".amplifier-work-tracker")
    )

    # The env vars the adapter itself reads must agree with the flags, or
    # this would list one server and drop from another.
    os.environ["AMPLIFIER_WORK_TRACKER_DOLT_HOST"] = args.host
    os.environ["AMPLIFIER_WORK_TRACKER_DOLT_PORT"] = str(args.port)
    SV.DEFAULT_DOLT_HOST = args.host
    SV.DEFAULT_DOLT_PORT = args.port

    everything = list_databases(args.host, args.port)
    residue = [n for n in everything if is_residue(n)]
    protected = [n for n in everything if not is_residue(n)]

    print(f"server:    {args.host}:{args.port}")
    print(f"databases: {len(everything)} total -- {len(residue)} residue, {len(protected)} kept\n")

    print(f"PROTECTED ({len(protected)}) -- never touched by this script:")
    for n in protected:
        print(f"  keep  {n}")

    blocked: list[tuple[str, list[str]]] = []
    if not args.no_held_check:
        for n in residue:
            held = held_items(n, root)
            if held:
                blocked.append((n, held))
    blocked_names = {n for n, _ in blocked}
    droppable = [n for n in residue if n not in blocked_names]

    if blocked:
        print(f"\nREFUSED ({len(blocked)}) -- matched a residue pattern but has HELD items:")
        for n, held in blocked:
            print(f"  skip  {n}  (held: {', '.join(held)})")

    print(f"\nRESIDUE ({len(droppable)}) -- {'dropping' if args.confirmed else 'would drop'}:")
    for n in droppable:
        print(f"  drop  {n}")

    if not droppable:
        print("  (none)")
        return 0

    if not args.confirmed:
        print(
            f"\nDRY RUN -- nothing was dropped. Re-run with --confirmed to drop "
            f"the {len(droppable)} database(s) listed above."
        )
        return 0

    dropped, missing, failed = 0, 0, []
    for n in droppable:
        try:
            if A.drop_database(n):
                dropped += 1
            else:
                missing += 1  # vanished between the listing and the drop
        except A.BeadsError as e:  # noqa: PERF203 - per-database, one failure must not hide the rest
            failed.append((n, str(e)))

    print(f"\ndropped {dropped}, already gone {missing}, failed {len(failed)}")
    if failed:
        for n, err in failed:
            print(f"  FAILED {n}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
