# Lane: dashboard-render  (model: opus-4.8)

## Outcome
The dashboard render helpers draw the true state cleanly — including the broken-project treatment and a real age-chart axis — without touching routes.

## You OWN
`src/amplifier_work_tracker/webapp.py` — these MODULE-LEVEL helper function bodies ONLY:
`_hero_html`, `_dashboard_row`, `_dashboard_totals`, `_heartbeat_html`, `_ledger_html`, `_global_oldest`, `_dashboard_sort_key`, `_project_hero_html`, `_aggregate_buckets`.
Do NOT edit `create_app()` (webapp-routes owns routes+imports), item helpers (item-render), or shell helpers (shell-nits).

## Deliverables
1. **A broken-project treatment.** Render `_dashboard_row` / `_project_hero_html` so a broken/creating project (status the route passes you) is visually distinct and unmissable — use webtheme's new alarm token. If the token isn't in your worktree yet, use a clearly-named placeholder class and residual-note it for webtheme.
2. **Age-chart axis carries real units.** `_heartbeat_html`'s "READY QUEUE BY AGE" is currently uniform ticks with a "FRESHER→OLDER" axis and no time units. Give it a real, readable scale (day markers) OR replace it with something an operator can actually read. No decorative-only chart.
3. **Fix the concat + display bugs in your helpers:** the "cortexcortex-i2u" no-separator concat in `_project_hero_html`; any bar/label mismatch you render; the held-badge that wraps a machine id across 3 lines (make it legible/truncate-with-title).
4. Reading width / measure for anything long you render stays sane.

## Residual protocol
If a fix needs a route to pass different data, record it as a residual for webapp-routes.

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
