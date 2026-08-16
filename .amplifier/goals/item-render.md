# Lane: item-render  (model: sonnet)

## Outcome
An item's detail body is actually readable: markdown renders, code/tables keep alignment, line length is comfortable, and "editable-looking" static fields stop lying.

## You OWN
`src/amplifier_work_tracker/webapp.py` — item-specific MODULE-LEVEL helpers ONLY: `_item_row`, and any NEW helper you add for item-body rendering (e.g. a markdown renderer). Do NOT edit `create_app()`, dashboard helpers, shell helpers, or webtheme.

## Deliverables
1. **Render markdown** in item description/resolution: `**bold**`, backtick `code`, headings become real HTML — not literal asterisks/backticks. Keep it dependency-light (a small, safe renderer; escape untrusted content).
2. **Preserve ASCII tables/code alignment**: content shown with `white-space: pre-wrap` must be in a MONOSPACE face, not proportional Archivo (which destroys column alignment). Provide the class/markup; if the actual font token lives in webtheme, residual-note it.
3. **Fix the `_item_row` concat** ("cortexcortex-i2u" no-separator) if it appears in your helper.
4. Item-body reading measure ≤ ~90 chars/line (the detail page is ~190 today). If the cap must be a CSS token, residual-note it for webtheme; do what you can in markup.
5. Metadata fields (KIND/PRIORITY/REPORTED BY) that are inert must not look editable — give them non-interactive styling/markup distinct from real links.

## Residual protocol
Route wiring (calling your new markdown helper from the item-detail route) belongs to webapp-routes — record it as a residual with the exact call site.

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
