# Lane: cli-rename  (model: opus-4.8)

## Outcome
`amplifier-work-tracker rename <old> <new>` renames a project safely — directory, dolt database, and any server-side residue — with the same atomicity discipline that `new` now has. (work_item_pipeline-m9v)

## You OWN
- `src/amplifier_work_tracker/cli.py` — a NEW `rename` subcommand only. Do NOT edit the `status`/`instances` code (that's cli-status).
- `src/amplifier_work_tracker/adapter.py` — a NEW `rename`/`Workspace.rename` function only. Do NOT edit existing summary/data functions (those are adapter-data's).

## Deliverables
1. `rename <old> <new>` validates the new name against the same regex `new` uses (lowercase/underscore, no dots/hyphens), refuses if <new> already exists, refuses if <old> is missing or currently held.
2. Renames BOTH the on-disk project dir AND the dolt database (the class of bug that burned names before: server-side residue surviving a dir move). Leave no orphan database and no half-renamed state — atomic or clean-fail, mirroring `Workspace.create`'s self-heal discipline.
3. A test proving: rename succeeds end-to-end against an isolated dolt server; the old name is gone; the new name is fully writable; items survive with correct ids-or-remapped-ids (document which). Cross-check with a real `list` on the new name.
4. Clear, sanitized errors (no raw bd/dolt text leaking — reuse `_clean_bd_error` if present).

## Note
This touches the DB-rename path which is genuinely risky. If dolt cannot rename a database in-place, document the mechanism you used (dump+load, or new+copy+drop) in the commit and in DONE.json.

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
