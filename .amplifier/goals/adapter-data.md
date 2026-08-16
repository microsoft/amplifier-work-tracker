# Lane: adapter-data  (model: opus-4.8)

## Outcome
Every number the dashboard shows is TRUE, computed once in the data layer. Today the UI shows numbers that disagree with each other and a backend-broken project that looks healthy — because the data layer doesn't distinguish or compute these states.

## You OWN
`src/amplifier_work_tracker/adapter.py` — EXISTING data/summary functions only (ProjectSummary, project_summary, project_activity, oldest-unclaimed/ready/held computation, resolved_24h/7d, timestamp parsing). You do NOT add a rename function (that's cli-rename's).

## Deliverables
1. **Broken-state is a real, distinct data value.** A project whose backend reports broken/creating (see `creation_state`) must surface as a distinct status on ProjectSummary — NOT collapsed into a healthy "0 items / ok". The render lanes will draw it; your job is to make the data say it.
2. **Reconcile the two totals.** The dashboard shows READY=104 in one place and "76 unclaimed" in another for the same concept. Define these precisely (ready vs unclaimed vs held), compute each unambiguously, and expose both with names that make the difference legible. If they are genuinely the same set, make them one number.
3. **Resolved throughput is real** (`resolved_24h`, `resolved_7d`) from `closed_at`, correct including honest zeros; None (never fake 0) where a project records no timestamps.
4. **A project-level "last activity" timestamp** exists on the summary (most recent updated_at/closed_at across items), so the render lane can stop showing an empty column.

## Notes
- Timestamps already exist on items (PR #14: created_at/updated_at/closed_at). Use them; don't re-plumb.
- Add/extend a contract assumption in `contract.py` if you add a data invariant worth pinning (doctor count may rise). Optional, not required.

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
