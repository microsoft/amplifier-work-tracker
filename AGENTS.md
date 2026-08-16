# AGENTS.md

For contributors changing this repo. (For agents *using* the bundle at
runtime, see `bundle.md`, `skills/`, and `agents/` instead -- this file is
the other audience: the one editing the code.)

## `main` is protected

Direct pushes are rejected -- work goes through a PR, and merges are
**squash only** (linear history required). Full ruleset:
[`.github/branch-protection-ruleset.json`](.github/branch-protection-ruleset.json),
maintainer notes in [`CONTRIBUTING.md`](CONTRIBUTING.md). One point worth
repeating here: `required_approving_review_count` is `0`, not 1-with-a-bypass,
because a bypass actor bypasses the *entire* ruleset -- including required
status checks -- which would let the bypasser skip CI too. With 0 and no
bypass actors, the gate (PR, CI green, linear history, no force-push) applies
to everyone, including a solo maintainer merging their own PR.

## The adapter seam

All `bd`-specific knowledge -- CLI shape, field names, exit-code quirks --
lives in `src/amplifier_work_tracker/adapter.py` and nowhere else. If
`doctor` reports a violated assumption, the fix scope is that one file.
Nothing above the seam should ever need to change for a Beads upgrade.

## `doctor` is the gate, not a suggestion

Run `amplifier-work-tracker doctor` after any `bd` upgrade and before
trusting parallel agents against a queue. It must report **26/26
assumptions hold**; anything less means Beads' behavior moved out from
under an assumption we depend on (or, for `sweeps.alive`, that the
reap/notify sweep loops have stopped completing sweeps, or, for
`project.removal`, that `remove`/`new` no longer honestly handle a
database that outlives its project directory, or, for
`service.restart_policy`, that the installed unit's Restart= line has
regressed away from `always` -- see the 2026-08-14 outage note in
supervisor.py's `DoltSupervisionExhaustedError`).

## Test scope

Root CI (`.github/workflows/ci.yml`) runs `tests/unit`, `tests/integration`
(marker `integration`), and `tests/cli` (marker `cli`) -- see the Makefile
for the per-tier targets. **`modules/tool-work-tracker/tests/` is a separate
package with its own suite and is NOT exercised by root CI** -- a green root
CI run does not cover it; run it directly if you touch that module.

## Tests run against an ISOLATED dolt server, never the shared one

Both suites (`tests/conftest.py` and
`modules/tool-work-tracker/tests/conftest.py`) spin up a throwaway `dolt
sql-server` on its own ephemeral port for the whole session (autouse,
session-scoped `isolated_dolt_server` fixture; the shared logic lives in
`tests/_dolt_isolation.py`) and repoint every dolt host/port pointer this
repo reads at it. **A test run can no longer create a database on the
shared, permanent server at `~/.beads/shared-server:3308` -- structurally,
not by teardown discipline.**

Why this exists: fixture-level teardown (below) is Python code that runs
*after* a test/fixture body, so a `kill -9`, an impatient `timeout` wrapper
escalating to SIGKILL, or a hard crash skips it entirely and leaves that
run's databases on the shared server forever. Measured on a live box: 202
residue databases, enough on their own to make `bd init` (a `CREATE
DATABASE` under the hood) time out at 240s server-wide -- for real
projects too. Isolation closes that gap: a killed run leaves at worst an
orphaned `dolt sql-server` process and a `/tmp` directory, never growth on
the server every real project also lives on.

A session-scoped `assert_isolated_server_clean` fixture in both suites is
the final backstop: at session end it queries the isolated server directly
(not any fixture's bookkeeping) and fails loudly, naming and dropping
anything left -- on this per-session server, every non-system database is
test residue by construction, so this catches a leak even from a fixture
that never went through any of the safe helpers below at all.

## A project lives in two places -- clean up both

Creating a project creates a directory *and* a database on the dolt server
it was pointed at (the isolated one, per the section above). A `tmp_path`
root only cleans up the first one. Skipping the second was measured on a
live box at **163 databases for 5 real projects**: 157 of them residue, 47
from `doctor` runs alone. dolt holds every database open, so the bill
arrives continuously -- dropping the residue took that server from 1.15 GB
RSS / 313 MB on disk to 0.12 GB / 18 MB. Isolation (above) means that bill
can no longer land on the *shared* server, but it still matters within a
session: an untidy fixture bloats the isolated server's own disk/RSS for
the rest of a long run, and (per the safety net above) still fails the
session.

Unique names (see `tests/conftest.py`) are what keep concurrent runs from
colliding. They are not cleanup. So:

- **Any fixture that creates a project must drop it again.** Root suite:
  `drop_project` in `tests/conftest.py`. Module suite: the shared `project`
  fixture in `modules/tool-work-tracker/tests/conftest.py` (set
  `PROJECT_PREFIX` in your test module to name it).
- **Teardown belongs in the fixture, not at the end of the test body** --
  the end of a test body does not run when the test fails, and a failing
  test is exactly when residue gets left behind.
- Removal goes through `adapter.drop_database` / `Workspace.remove`, never
  raw SQL. Teardown uses the former because `remove` refuses (correctly)
  while an item is HELD, and several tests deliberately hold one.
- `tests/integration/test_no_database_residue.py` pins this, and the
  session-scoped `assert_no_leaked_projects` fixture fails the run if any
  project a fixture handed out is still there at the end.

For residue an older run already left on a server (e.g. the shared
production one, from a run that predates the isolation fix above):

```bash
python scripts/sweep_test_residue.py                 # dry run: names every database, drops none
python scripts/sweep_test_residue.py --confirmed     # actually drop them
python scripts/sweep_test_residue.py --patterns      # what counts as residue
```

It only matches fixture-minted names (a prefix from this repo's suites plus
a machine-generated suffix), reports everything else as PROTECTED, and
refuses any database that still has HELD items. It is deliberately not
wired into CI, `doctor`, or any install path -- a destructive command that
runs itself is how you lose data you meant to keep.

## What "done" looks like

Full suite green, `doctor` 26/26, `ruff check` / `ruff format --check` /
`pyright` clean. For any change to the bundle's zero-state install path
(service bootstrap, `work_tracker_install`, prereqs), the acceptance gate is
a fresh Digital Twin Universe run from a genuinely empty machine (no `bd`,
no `dolt`, no state) showing **zero raw `bd` calls** in the transcript --
only bundle tools. That bar, and the four-run trajectory that reached it,
is recorded in the PR #2 description and its commit history
(`fd7d371`..`e322c6d`); there is no separate proof doc in this repo. Re-run
it before merging any change that touches that path.
