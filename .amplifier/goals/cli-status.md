# Lane: cli-status  (model: sonnet)

## Outcome
`amplifier-work-tracker` surfaces a full status breakdown (open / blocked / deferred / resolved) — in both the cheap summary and a per-project detail view. (work_item_pipeline-i7f)

## You OWN
`src/amplifier_work_tracker/cli.py` — the `instances` / status-display code paths and any new `status`/`show` detail subcommand. Do NOT edit the `rename` subcommand (cli-rename) or webapp/webtheme.

## Deliverables
1. **Cheap summary gains the breakdown**: `instances` (table + `--json`) shows counts per state (open/blocked/deferred/resolved), not just total/ready/held. Read from the adapter summary; if the summary lacks a field you need, residual-note it for adapter-data rather than recomputing in the CLI.
2. **A per-project detail view**: a subcommand (e.g. `status --project <p>` or extend `list`) that shows the full breakdown for one project, human-readable and `--json`.
3. Real cross-check: run against the live READ-ONLY :3308 server for a real project (e.g. cortex) and confirm the breakdown numbers match a manual count. Reads only — never mutate a real project.
4. Tests against an isolated dolt server; no regressions to existing cli tests.

## Note
If adapter-data hasn't landed a needed field in your worktree, compute the minimum from data you can already read and residual-note the cleaner source. Prefer reading the summary over re-deriving.

---
## Exit condition (load-bearing — keep verbatim)
> Complete when **either** every deliverable below reaches a terminal state, **or** it is
> conclusively demonstrated the remainder cannot, naming the blocker for each.
> Items ending FAIL or BLOCKED are residuals, not failures of the goal.

## Terminal states
Mark each deliverable exactly one of: PASS / FAIL-<reason> / BLOCKED-<reason> / PENDING-HUMAN-<what>.

## Where you work
- Work ONLY in THIS worktree. Do NOT touch the main checkout or sibling worktrees.
- Base: feat/web-ui @ 8b4d880ef9b6f90fb26b5da393260e64d5823870.
- Commit early, push always. Never merge to main or feat/web-ui — the orchestrator merges. Commit only to your own lane branch.

## Host + safety limits (real)
- The shared dolt server on 127.0.0.1:3308 is LIVE, shared with other agents, and READ-ONLY to you.
- Tests use isolated fixtures / an isolated dolt server on a DIFFERENT port. NEVER run the suite against :3308.
- Do NOT restart the amplifier-work-tracker systemd service. Do NOT touch ports 8088 / 8090 / 8091 / 8095.
- Baseline: 365 test functions. "No regressions" = that count does not drop and nothing passing now fails.
- Gate: ruff check + ruff format --check + pyright clean on files you touch.

## Time bound
Exceeding your wall-clock bound is a terminal BUDGET state. Stop at the next safe commit, mark remaining BLOCKED-budget. Do not rush or skip a commit.

## File ownership — the rule that keeps 9 lanes from colliding
Crossing into another lane's files/functions is a DEFECT, not a courtesy. Need an edit outside your ownership? Record it in DONE.json residuals[] (exact file/function/change/for_lane) and STOP there. Do NOT edit it.

## Trust yourself
You have the expertise. The deliverables are intent, not a script — solve them well. Verify your own work end-to-end before marking PASS: a test passing is not proof a user's path works. Inspect real state; don't guess.

## Final act — write DONE.json in this worktree root (already gitignored)
Write it LAST:
```json
{"lane":"<LANE>","session_id":"<your own amplifier session id>","verdict":"COMPLETE|BLOCKED|PARTIAL",
 "branch":"<branch>","head":"<git rev-parse HEAD>","pushed":true,
 "items":[{"id":"<deliverable>","state":"PASS|FAIL-x|BLOCKED-x|PENDING-HUMAN-x","note":"..."}],
 "residuals":[{"file":"...","function":"...","change":"...","for_lane":"..."}],
 "pending_human":[],"suite":{"passed":0,"failed":0,"baseline":365}}
```
verdict is exactly COMPLETE / BLOCKED / PARTIAL. Without this file, an exited session looks killed.
