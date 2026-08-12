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
trusting parallel agents against a queue. It must report **19/19
assumptions hold**; anything less means Beads' behavior moved out from
under an assumption we depend on (or, for `sweeps.alive`, that the
reap/notify sweep loops have stopped completing sweeps).

## Test scope

Root CI (`.github/workflows/ci.yml`) runs `tests/unit`, `tests/integration`
(marker `integration`), and `tests/cli` (marker `cli`) -- see the Makefile
for the per-tier targets. **`modules/tool-work-tracker/tests/` is a separate
package with its own suite and is NOT exercised by root CI** -- a green root
CI run does not cover it; run it directly if you touch that module.

## What "done" looks like

Full suite green, `doctor` 19/19, `ruff check` / `ruff format --check` /
`pyright` clean. For any change to the bundle's zero-state install path
(service bootstrap, `work_tracker_install`, prereqs), the acceptance gate is
a fresh Digital Twin Universe run from a genuinely empty machine (no `bd`,
no `dolt`, no state) showing **zero raw `bd` calls** in the transcript --
only bundle tools. That bar, and the four-run trajectory that reached it,
is recorded in the PR #2 description and its commit history
(`fd7d371`..`e322c6d`); there is no separate proof doc in this repo. Re-run
it before merging any change that touches that path.
