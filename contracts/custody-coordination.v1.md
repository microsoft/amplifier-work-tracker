# Custody and Coordination Contract — v1

**Status:** DRAFT

**Scope:** This contract governs the custody and coordination seam of amplifier-work-tracker. It defines how claimed work items are held exclusively by a single actor, how custody is signaled and renewed, and how claims are guarded against stale holders. Other concerns — dashboard rendering, dolt-ops internals, project semantics, work-item filtering, and scheduling heuristics — are explicitly out of scope.

---

## Core Clauses

These clauses are the frozen invariants of the custody and coordination seam. Each is backed by machine-checkable code, tests, or explicit NOT-ASSERTABLE reasoning.

### Core 1: Claim is atomic; loss is loud

A claim is a single atomic operation with no two-step read-then-claim path. A directed claim (claiming a specific item by ID) is not a lesser claim; it atomically establishes custody or refuses loudly, naming the blocker: already-held-by-another, not-found, or open-dependency-blocking.

**Machine check:** `claim.atomic` (claim via queue) / `claim.directed_atomic` (directed claim by ID) — both must pass; skipped under `--quick` in CI due to Freeze Bar dependencies (see §Freeze Blockers).

---

### Core 2: Custody is a liveness signal, not a timer

Only an unrenewed custody signal costs a claim. Total hold duration never disqualifies a claim. A fresh renewal keeps a claim valid indefinitely.

**Machine check:** `custody.fresh_survives` — a claim held continuously with active renewal never expires, even if total hold duration exceeds the TTL.

---

### Core 3: `work_claim` and custody are one operation from the caller's point of view

A claim that cannot establish custody must not leave the work item in a held state with no custody record.

**Machine check:** `claim.custody_indivisible` (if `claim()` succeeds and `take_custody()` fails, the item must be released automatically, not left held-without-custody).

---

### Core 4: Custody renewal is one-strike; failure ends renewal

Any renewal failure permanently ends renewal. An agent that fails to renew once discovers it via the passive signal `holding.custody_lost` and must recover in-process.

**Machine check:** `custody.one_strike` — a renewal failure (exception on `renew()` or write failure) must not be retried internally; the agent must detect and handle it.

---

### Core 5: `declared_state` is reporting only; `awaiting_human` is not exempt

Setting `declared_state` to `awaiting_human` suppresses a proactive notification (Backlogged feature) but does not exempt the item from reclaim eligibility. The only reclaim exemption is an active, recent renewal.

**Machine check:** `custody.idle_not_exempt` — an item with `declared_state == "awaiting_human"` and no renewal for > TTL is reclaimed by the sweep.

---

### Core 6: TTL is enforced by a required, scheduled, observable sweep

A stale custody (older than TTL without renewal) is reclaimed by an out-of-band sweep (`reap` service, scheduled job). **The TTL is not self-enforcing**: without the sweep running, the TTL is aspirational. An item held by a dead agent stays held indefinitely until the sweep runs.

The operator must run the sweep (e.g., via `reap` service or scheduled job). The agent must know the sweep exists and is scheduled.

**Machine check:** `sweep.required_and_scheduled` (Backlogged: observability of sweep scheduling).

---

### Core 7: A close is fenced against a stale holder in all post-reclaim states

A close operation is guarded against a holder that no longer holds the item. This includes the released-but-not-yet-re-claimed state (after reclaim has moved the item to open status, but custody has not yet been reassigned).

**Machine check:** `fence.close_post_reclaim` — a call to `close(item_id)` from a holder that has been reclaimed must refuse with error "item_id: not held by this session" or similar.

---

### Core 8: In-process recovery from reclaim is discoverable and actionable

A session that loses custody via reclaim discovers the loss and recovers in-process. The loss is discoverable via a passive check (e.g., `work_status` returning `holding.custody_lost: true`) and actionable without manual intervention or session restart.

**Machine check:** `recovery.discoverable` — a session with a lost custody can call a tool and discover it; recovery is possible without human intervention.

---

### Core 9: Renewal and takeover are fenced on holder and generation

A holder cannot renew custody after the item has been moved to a different holder (via reclaim or explicit claim). A zombie holder (a session that held the item, lost custody, and later wakes up) cannot re-claim or renew. Generation is monotonically increasing and serves as the fence.

**Machine check:** `custody.fenced` — an attempt to renew or reclaim an item whose holder or generation has changed must fail with "reclaimed" or "no longer held" error.

---

### Core 10: Every custody write verifies itself by reading back before reporting success

Exit code is not proof. Every write that changes custody state must read the item back and verify the change landed before reporting success.

**Machine check:** `write.readback_verified` — an operation like `release()` must confirm the item status changed before returning success.

---

### Core 11: A reported write failure must not contradict the actual state

If a write is reported as failed (exception raised, error returned), the item state must not have changed as if the write succeeded. Conversely, if a write succeeded, it must not later be reported as failed.

**Machine check:** `write.honest_failure` — a reported conflict error must be accompanied by a readback that confirms the conflict; a success must not later be contradicted by discovering the write did not land.

---

### Core 12: A session holds at most one item at a time

Claiming a second item before resolving, releasing, or abandoning the first is refused.

**Machine check:** `session.single_hold` — an attempt to claim a second item while already holding one must fail with "already holding" error.

---

### Core 13: Every custody interaction goes through the `work_*` tool seam

All capability to mutate, claim, release, or resolve items is exposed through the tool seam (`work_claim`, `work_resolve`, `work_release`, `work_declare`, `work_status`, `work_edit`, etc.). A capability reachable only via raw `bd` CLI or internal API is a missing verb — the missing verb is the bug.

**Machine check:** NOT-ASSERTABLE. Enforced by code review and skill documentation. No automated check verifies an agent did not shell out to raw `bd`.

**Reviewed at cadence:** PR audit and skill training.

---

### Core 14: Claim refusals are specific and actionable

When a claim is refused, the error names the specific blocker: already held by (actor), not found, or blocked by (open dependency). A refusal must never be "claim refused" without attribution.

**Machine check:** `claim.error_specificity` — error messages on claim refusal must name the blocker.

---

### NOT-ASSERTABLE 1: No raw-bd escapes without code review

The ability to interact with custody/items is intentionally constrained to the `work_*` tool seam. An agent that shells out to `bd` directly (instead of using `work_*` tools) violates this invariant. However, no mechanical check can verify that an agent did not do this; the constraint is enforced socially through code review, skill documentation, and process.

**Reviewed at cadence:** Per-session log audit, PR review, skill training.

---

## Backlogged Clauses

These are candidate clauses with named promotion triggers. Each becomes a Core clause (and possibly a major-version contract bump if it affects existing implementations) once its trigger condition is met.

### Backlog 1: Proactive lost-custody notification

**Proposal:** Add a signal (e.g., return code, flag in tool response, SSE event) that immediately notifies an agent when its custody is reclaimed, without waiting for a passive poll.

**Trigger:** "Delivery-mechanism design decision by owner" — choose whether the signal is in-band (return code / tool response flag) or out-of-band (SSE event / subscription).

**Rationale:** Passive detection has latency; immediate notification would reduce silent-stall risk. The mechanism is specified; the policy (signal type, integration point) requires owner decision.

---

### Backlog 2: Self-enforcing TTL via persistent heart-beating

**Proposal:** Replace the out-of-band sweep with an in-process heart-beating mechanism that self-enforces the TTL within the agent session, without requiring a separate scheduled job.

**Trigger:** "A second reclaim-consumer (beyond the service) that cannot run the sweep" — e.g., a language binding, embedded executor, or tool that holds items without running the full service.

**Rationale:** Current design assumes a separate sweep service. Supporting embedded or in-process usage would require the agent to self-enforce the TTL via local timeout logic.

---

### Backlog 3: Custody recovery verb for non-fenced write failures

**Proposal:** Add a verb (e.g., `work_custody_clear` or extended semantics on `work_release`) to recover from a custody-less-but-held state (D-6 scenario).

**Trigger:** "An incident where a session needs to drop custody without resolving or releasing the item" — the D-6 case: a session writes to a resolved item (a no-op or error), loses custody as a side-effect (e.g., due to a conflict), and cannot recover without either reopening the item (dangerous) or escalating.

**Rationale:** The D-6 incident identified a genuine recovery need. The verb (or revised semantics) requires design and approval before moving to Core.

---

## Conformance

### Conformance Kit

The following fixtures discriminate between correct and incorrect implementations. All must be included in the test suite and pass before Freeze Bar.

### Conformance 1: Conflicted-but-landed close (from Incident B, D-5)

**Scenario:** A close operation is issued. The write lands (the item status changes to closed), but a serialization/conflict error is encountered afterward (e.g., during WAL sync or post-write validation).

**Good behavior:** The error is raised, but a readback confirms the close landed. The tool correctly returns success (or re-tries the readback on failure).

**Bad behavior (current):** The error is raised, and no readback is performed. The error message claims the close failed, but the state check would reveal it succeeded. The API contract is violated (reported failure ≠ actual state).

**Test location:** `tests/integration/test_phantom_conflict_recovery.py`.

**Verification:** Call `work_resolve(id)`, capture the exception, then call `work_list(item_id=id)` to verify the item is actually closed.

---

### Conformance 2: Post-reclaim close fence (from D-2)

**Scenario:** An item is claimed by Session A. The reclaim sweep runs and moves the item to open status, stripping the custody. Session A, unaware of the reclaim, calls `work_resolve(id)` to close the item.

**Good behavior:** The close is refused with an error like "item not held by this session" or "custody lost; reclaim detected."

**Bad behavior (current):** The close succeeds, even though the holder has been reclaimed and no longer holds the item. The item is closed by a stale holder.

**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py` (tool seam) and `tests/integration/test_post_reclaim_fence.py` (adapter layer).

**Verification:** Claim item → trigger reclaim manually → call `work_resolve()` → verify refusal.

---

### Conformance 3: In-process recovery after reclaim (from Core 8)

**Scenario:** A session holds an item, the reclaim sweep runs and strips custody, and the session calls a tool (e.g., `work_status`) to check status.

**Good behavior:** The tool reveals `holding.custody_lost: true` (or similar signal). The session can then call a recovery verb (to be designed) without manual intervention or restart.

**Bad behavior:** The session is left in an ambiguous state; it believes it holds the item but tools refuse to use it; there is no recovery path.

**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py`.

**Verification:** Claim → trigger reclaim → `work_status()` → verify loss is detected and recovery path exists.

---

### Conformance 4: Single-hold constraint (from Core 12)

**Scenario:** A session holds item A. It attempts to claim item B without releasing item A.

**Good behavior:** The claim is refused with error "already holding item A."

**Bad behavior:** The claim succeeds, and the session now holds two items (violating Core 12).

**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py`.

**Verification:** Claim → claim again → verify second claim is refused.

---

### Checks

All checks are implemented as test functions in `ledger/checks/` or as pytest fixtures. They are run by `make test` in the repo and must pass before Freeze.

- `check_claim_atomic()` — Core 1 (claim is atomic)
- `check_custody_fresh_survives()` — Core 2 (liveness over elapsed time)
- `check_readback_verified()` — Core 10 (writes verify before success)
- `check_fenced_close()` — Core 7 (close fence against stale holder)
- `check_single_hold()` — Core 12 (session holds at most one item)

---

## Reserved

The following identifiers and fields are reserved for future use or explicitly excluded from current scope:

- **`custody.pid`** / **`custody.host`** — recorded for forensic and debugging purposes (to identify the last holder). Explicitly NOT used as a liveness input. These fields are not consulted by `reclaim_eligible()` and do not participate in reclaim decisions.

- **`custody.generation`** — currently used as a monotonic fence to prevent stale-holder re-claims. Reserved for potential lifecycle management, rotation, or zombie-detection enhancements in future versions.

- **Custody delegation or transfer** — explicitly not supported in v1. A claim is owned by its holder and cannot be transferred; re-claiming requires the sweep or a new claim.

---

## Residual Issues

Conformance status for every named issue (D-1 through D-6) -- resolved, open, or Backlogged -- lives in `ledger/rows.yaml` (per-row disposition) and `ledger/reconcile-report.md` (the reconcile narrative); it is not duplicated here.

---

## Freeze Bar

Before this contract moves from DRAFT to FROZEN, all of the following conditions must be satisfied:

### Freeze 1: Residual issues resolved or Backlogged

All three residual issues (D-1, D-2, D-5) resolved or moved to Backlogged with owner approval.

---

### Freeze 2: D-6 recovery verb designed and implemented

D-6 recovery verb designed and implemented (or Backlogged with explicit approval to defer).

---

### Freeze 3: All four Conformance fixtures implemented, passing, and executable

All four Conformance fixtures implemented, passing, and executable via `make test`.

---

### Freeze 4: All check functions implemented and passing

All check functions (custody, claim, readback, fence, single-hold) implemented and passing.

---

### Freeze 5: Test suite importable and run as part of CI

Test suite (`tests/test_*.py`) is importable and run as part of CI.

---

### Freeze 6: Every Core clause verified against actual code

Every Core clause quoted in this contract verified against actual code (via grep/LSP, not re-paraphrased).

---

### Freeze 7: Every quote a contiguous, whitespace-collapsed substring

Every quote is a contiguous, whitespace-collapsed substring of the actual code or test comment.

---

### Freeze 8: PR review by an external reviewer

PR review of this contract by external reviewer (not author).

---

### Freeze 9: Owner ratification and signature

Owner ratification and signature ("FROZEN" stamp in dated changelog entry).

---

## Changelog

- **2026-09-03 — DRAFT amendment, owner-ratified ("ok, yes, proceed"):** struck all Current-state annotations (conformance status lives in the ledger only — pillar 1); numbered Conformance 1–4 and Freeze 1–N for bare-id ledger citation (LEDGER-FORMAT §2); corrected the four Test-location lines to the real paths. Status remains DRAFT.
- **2026-09-01 — DRAFT.** First draft, derived from Phase 0 evidence and Call 8 ratified decisions. Includes 14 Core clauses (with 5 VIOLATION rows and 1 partial CONFORMS), 3 Backlogged clauses, 4 Conformance fixtures, Reserved section, and 6 Residual Issues (D-1 through D-6) awaiting Phase 2 resolution. Freeze Bar blockers named. Awaiting owner review at ENCODE gate.

