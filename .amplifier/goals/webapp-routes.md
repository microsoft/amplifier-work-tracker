# Lane: webapp-routes  (model: opus-4.8)

## Outcome
The routes wire true data into the page and stop lying. This is the entangled spine — you are the SOLE owner of route bodies, so all route-level wiring flows through you.

## You OWN
`src/amplifier_work_tracker/webapp.py` — the `create_app()` function body (all @app routes) AND the module top-of-file imports. You do NOT edit module-level render-helper bodies (`_hero_html`, `_dashboard_row`, `_item_row`, `_page`, `_pagination_html`, etc.) — those belong to dashboard-render / item-render / shell-nits. You CALL them and pass them data; you don't rewrite them.

## Deliverables
1. **Broken-state visible end-to-end.** Read the new broken/creating status from adapter-data's summary and render a distinct, unmissable treatment (a banner / row state) so a backend-broken project is NEVER pixel-identical to a healthy empty one. This is the stop-ship fix. If adapter-data's field isn't merged yet in your worktree, compute the minimal signal yourself from `creation_state` and leave a residual noting the intended data source.
2. **Search tells the truth.** Today "2 OF 264" is a client-side filter over only the 50 DOM rows on the current page — it under-reports. Make the count reflect the true match set across the project (server-side filter, or fetch-all-then-filter), and make the pagination footer filter-aware (no "Items 1–50 of 264 · page 1 of 6" under a 2-row filtered view).
3. **The bar and its label agree.** Where a route passes an age/scale to a helper, ensure the value it passes matches the label (the "81px bar labelled 4d" and "clamped-at-max shown as a lower number" bugs are data-into-render mismatches — fix what you pass).
4. Wire adapter-data's reconciled totals + last-activity into the dashboard route so the two-totals contradiction disappears on the page.

## Residual protocol
If a helper body needs changing to display your data, record it as a residual for dashboard-render / item-render / shell-nits — do NOT edit the helper yourself.

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
