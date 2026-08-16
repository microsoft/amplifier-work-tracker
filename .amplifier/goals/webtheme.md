# Lane: webtheme  (model: opus-4.8)

## Outcome
The design system gains the one thing it never had — a real alarm/error vocabulary — and stops failing the accessibility floor. The editorial-dark aesthetic that won the bake-off stays; this hardens it where it breaks.

## You OWN
`src/amplifier_work_tracker/webtheme.py` — sole owner. CSS/tokens/palette only.

## Deliverables (from the design council, verbatim severity)
1. **Amber has ONE stable meaning.** Today amber is brand mark, hero baseline, name/ID emphasis, chart ticks, progress tips, AND the "Sweep healthy" good-news color — six contradictory jobs. Give amber a single referent, and introduce a DISTINCT token for "attention/broken/alarm" so the render lanes can mark a broken project. Do not spend your one accent on good news.
2. **Contrast floor.** RESOLVED status text measures <3:1 on ~240 of 264 rows (functionally invisible); the HELD indicator is hue-only at borderline AA. Raise every text token to ≥4.5:1 against its real composited background; make HELD legible by more than hue (weight/shape/label backup).
3. **Sparse-vs-dense layout.** A 2-item project renders the same fixed heavy hero/stats chrome as the 264-item one (~80% chrome/air). Provide the CSS affordances (compact variants / density classes) so render lanes can adapt small projects. You provide the mechanism; they apply it.
4. **One affordance grammar.** Three signifiers currently mean "clickable" (trailing chevron, bold-amber, lone underline). Consolidate to one documented convention in the tokens.

## Note
Reserve heavy layout re-architecture (fold/scroll #12/#14) — out of scope this batch. Provide the tokens; don't restructure the page.

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
