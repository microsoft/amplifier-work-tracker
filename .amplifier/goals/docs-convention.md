# Lane: docs-convention  (model: sonnet)

## Outcome
A written, usable convention for authoring work items that a COLD isolated session can pick up and execute without the author present. (work_item_pipeline-h3a)

## You OWN
`docs/` — a new doc (e.g. `docs/work-item-authoring-convention.md`). Sole owner. Touch NO source files.

## Deliverables
1. A convention doc that names, with rationale: what a work item MUST carry for a cold session to execute it (title, outcome/acceptance in given/when/then, ownership/scope, terminal states, evidence expected, host/safety limits, disjunctive exit).
2. Resolve the real tension explicitly: **cheap-capture** (a human files a one-line problem fast) vs **rich-handoff** (a cold agent needs enough to start). Propose how one convention serves both (e.g. a thin intake that a triage step enriches). Argue the position; don't just list options.
3. Address the acceptance-vs-goalify vocabulary mismatch (reconcile / translate-at-conversion / argue-neither) and the description/design asymmetry.
4. Ground it: reference at least one REAL existing item (read-only via `amplifier-work-tracker list --project <p> --id <id>`) as a worked example of the convention applied — good and bad.
5. State where the convention should live and why.

## Note
This is a research+writing lane. "Done" = a doc a real cold session could follow, validated against ≥1 real item, not reasoning alone. If you conclude no single convention can serve both consumers, that's a valid terminal outcome — name the specific conflict.

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
