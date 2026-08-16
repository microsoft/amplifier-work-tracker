# Lane: shell-nits  (model: sonnet)

## Outcome
The small, everywhere-visible text/label defects that make the app read as unfinished are gone — cleanly, in the shared shell/nav helpers.

## You OWN
`src/amplifier_work_tracker/webapp.py` — these MODULE-LEVEL helper bodies ONLY:
`_page`, `_pagination_html`, `_item_state_html`, `_crumb`, `_flash`, `_identity_right`, `_not_found_body`, `_humanize_identity`, `_relative_time`, `_abs_and_rel`, `_parse_iso`.
Do NOT edit `create_app()` (webapp-routes), dashboard helpers (dashboard-render), item helpers (item-render), or webtheme.

## Deliverables
1. **Dangling separator**: the header renders `live · operator ·` with nothing after the trailing middot. Fix in `_page`/`_identity_right` — no trailing separator when the last segment is empty.
2. **Pluralization**: "1 items" / "1 ITEMS" must read "1 item". Add/apply a tiny pluralize helper wherever a count+noun is rendered in your helpers.
3. **Resolved-item dates**: a resolved item shows CREATED/UPDATED/RESOLVED as "--". Timestamps now exist on items (created_at/updated_at/closed_at). Render them via `_abs_and_rel`/`_relative_time` instead of "--".
4. **Last-activity glyph consistency**: the dashboard LAST ACTIVITY column mixes "--" and "—". Pick ONE empty-glyph and use it everywhere in your helpers. (Populating it with real data is adapter-data + dashboard-render's job; you just fix the placeholder consistency where your helpers render it.)
5. **"0M" / age labeling**: where a held item's age renders "0M" with no context, label what it measures (or render a clearer zero). Keep it in your time-format helpers.
6. **Pagination footer** must not claim a stale total; if webapp-routes passes a filtered flag/count, honor it. If the signal isn't passed, residual-note the exact param needed for webapp-routes.

## Residual protocol
Anything needing a route change → residual for webapp-routes.

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
