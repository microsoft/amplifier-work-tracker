# Custody and Coordination Contract — v1

**Status:** FROZEN

**Scope:** This contract governs the custody and coordination seam of amplifier-work-tracker. It defines how claimed work items are held exclusively by a single actor, how custody is signaled and renewed, and how claims are guarded against stale holders. Other concerns — dashboard rendering, dolt-ops internals, project semantics, work-item filtering, and scheduling heuristics — are explicitly out of scope.

---

## Core Clauses

These clauses are the frozen invariants of the custody and coordination seam. Each is backed by machine-checkable code, tests, or explicit NOT-ASSERTABLE reasoning.

**TTL**, used without further qualification throughout this contract, means the *custody* TTL: the greatest age a custody signal may reach without renewal before the hold becomes reclaim-eligible. Its value is `CUSTODY_TTL_SECONDS` in `src/amplifier_work_tracker/custody.py` — **900 seconds (15 minutes)** by default, overridable per deployment by the `AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS` environment variable. It is defined here once; Core 2, Core 5 and Core 6 use the term without restating it.

**Machine check** lines below name the assertion that actually carries the clause. Five clauses carry a runnable `doctor` check by name; the rest are carried by a ledger row in `ledger/rows.yaml` and the probe or tests that row cites (see §Checks).

### Core 1: Claim is atomic; loss is loud

A claim is a single atomic operation with no two-step read-then-claim path. A directed claim (claiming a specific item by ID) is not a lesser claim; it atomically establishes custody or refuses loudly, naming the blocker: already-held-by-another, not-found, or open-dependency-blocking.

**Machine check:** `claim.atomic` (claim via queue) / `claim.directed_atomic` (directed claim by ID) — both real entries in `doctor`'s registry (`src/amplifier_work_tracker/contract.py`), and both must pass. `doctor --quick` skips them because they are the two slowest checks by a wide margin, not for any Freeze Bar dependency; the Freeze Bar conditions are in §Freeze Bar below. Ledger row `CCV1-001`, which cites `tests/integration/test_directed_claim.py`.

---

### Core 2: Custody is a liveness signal, not a timer

Only an unrenewed custody signal costs a claim. Total hold duration never disqualifies a claim. A fresh renewal keeps a claim valid indefinitely.

**Machine check:** `custody.fresh_survives` — a real entry in `doctor`'s registry (`src/amplifier_work_tracker/contract.py`); ledger row `CCV1-002`. A claim held continuously with active renewal never expires, even if total hold duration exceeds the TTL.

---

### Core 3: `work_claim` and custody are one operation from the caller's point of view

A claim that cannot establish custody must not leave the work item in a held state with no custody record.

**Machine check:** ledger row `CCV1-003` — probe `ledger/checks/test_custody_rows.py::test_row_ccv1_003` (the compensating shape), behaviour in `modules/tool-work-tracker/tests/test_custody_atomic.py` (if `claim()` succeeds and `take_custody()` fails, the item must be released automatically, not left held-without-custody).

---

### Core 4: Custody renewal is one-strike; failure ends renewal

Any renewal failure permanently ends renewal. An agent that fails to renew once discovers it via the passive signal `holding.custody_lost` and must recover in-process.

**Machine check:** ledger rows `CCV1-004` (the code shape) and `CCV1-005` (the agent-facing prose that states it) — probes `ledger/checks/test_custody_rows.py::test_row_ccv1_004` and `::test_row_ccv1_005`, behaviour in `modules/tool-work-tracker/tests/test_reap_recovery.py::test_background_renew_loop_generic_failure_does_not_clear_held` — a renewal failure (exception on `renew()` or write failure) must not be retried internally; the agent must detect and handle it.

---

### Core 5: `declared_state` is reporting only; `awaiting_human` is not exempt

Setting `declared_state` to `awaiting_human` suppresses a proactive notification but does not exempt the item from reclaim eligibility. The only reclaim exemption is an active, recent renewal.

The suppression itself ships: `should_notify` in `src/amplifier_work_tracker/custody.py` is consulted by the notify sweep in `src/amplifier_work_tracker/supervisor.py`. What is Backlogged is a *different* signal — Backlog 1's agent-facing lost-custody notification — not this one.

**Machine check:** `custody.idle_not_exempt` — a real entry in `doctor`'s registry (`src/amplifier_work_tracker/contract.py`); ledger row `CCV1-006`, which cites `tests/unit/test_custody.py`. An item with `declared_state == "awaiting_human"` and no renewal for > TTL is reclaimed by the sweep.

---

### Core 6: TTL is enforced by a required, scheduled, observable sweep

A stale custody (older than TTL without renewal) is reclaimed by an out-of-band sweep (`reap` service, scheduled job). **The TTL is not self-enforcing**: without the sweep running, the TTL is aspirational. An item held by a dead agent stays held indefinitely until the sweep runs.

The operator must run the sweep (e.g., via `reap` service or scheduled job). The agent must know the sweep exists and is scheduled.

**Machine check:** ledger rows `CCV1-007` (the sweep reclaims stale holds and keeps fresh ones — cites `tests/unit/test_supervisor.py`) and `CCV1-008` (the TTL is not self-enforcing). Observability of the sweep is **not** Backlogged: it shipped as `doctor`'s `sweeps.alive` check (`src/amplifier_work_tracker/cli.py`, registered in `src/amplifier_work_tracker/contract.py`), which asks whether the loops are completing sweeps rather than merely whether the unit is active, and which `CCV1-007` already credits.

---

### Core 7: A close is fenced against a stale holder in all post-reclaim states

A close operation is guarded against a holder that no longer holds the item. This includes the released-but-not-yet-re-claimed state (after reclaim has moved the item to open status, but custody has not yet been reassigned).

**Machine check:** ledger row `CCV1-009` — probe `ledger/checks/test_custody_rows.py::test_row_ccv1_009` (the fence's shape), behaviour in `tests/integration/test_post_reclaim_fence.py` (both fence halves, red on the pre-fix code) and `modules/tool-work-tracker/tests/test_reap_recovery.py::test_post_reap_refusal_originates_below_the_session_latch` (which layer refuses) — a call to `close(item_id)` from a holder that has been reclaimed must refuse with error "item_id: not held by this session" or similar. `doctor`'s `resolve.fenced` is deliberately not named here: it stages a takeover, so it never reaches the released-but-not-yet-re-claimed state this clause explicitly covers.

---

### Core 8: In-process recovery from reclaim is discoverable and actionable

A session that loses custody via reclaim discovers the loss and recovers in-process. The loss is discoverable via a passive check (e.g., `work_status` returning `holding.custody_lost: true`) and actionable without manual intervention or session restart.

**Machine check:** ledger row `CCV1-010` — cites `tests/integration/test_phantom_conflict_recovery.py::test_release_on_an_already_resolved_item_writes_nothing_and_reports_already_closed`, with the tool-seam half in Conformance 3's fixtures (`modules/tool-work-tracker/tests/test_conformance_fixtures.py`) — a session with a lost custody can call a tool and discover it; recovery is possible without human intervention.

---

### Core 9: Renewal and takeover are fenced on holder and generation

A holder cannot renew custody after the item has been moved to a different holder (via reclaim or explicit claim). A zombie holder (a session that held the item, lost custody, and later wakes up) cannot re-claim or renew. Generation is monotonically increasing and serves as the fence.

**Machine check:** `custody.fenced` — a real entry in `doctor`'s registry (`src/amplifier_work_tracker/contract.py`); ledger row `CCV1-011`, probe `ledger/checks/test_custody_rows.py::test_row_ccv1_011`. An attempt to renew or reclaim an item whose holder or generation has changed must fail with "reclaimed" or "no longer held" error.

---

### Core 10: Every custody write verifies itself by reading back before reporting success

Exit code is not proof. Every write that changes custody state must read the item back and verify the change landed before reporting success.

**Machine check:** ledger rows `CCV1-012` (`release`'s success path) and `CCV1-013` (both claim paths) — probes `ledger/checks/test_custody_rows.py::test_row_ccv1_012` and `::test_row_ccv1_013`, behaviour in `tests/integration/test_write_readback.py` — an operation like `release()` must confirm the item status changed before returning success.

---

### Core 11: A reported write failure must not contradict the actual state

If a write is reported as failed (exception raised, error returned), the item state must not have changed as if the write succeeded. Conversely, if a write succeeded, it must not later be reported as failed.

**Machine check:** ledger rows `CCV1-014` (measured — cites `tests/integration/test_phantom_conflict_recovery.py`), `CCV1-015` (every item-level write verb routes through the verifying helper) and `CCV1-016` (both prose surfaces say so) — probes `ledger/checks/test_custody_rows.py::test_row_ccv1_015` and `::test_row_ccv1_016`, behaviour also in `tests/integration/test_write_readback.py` — a reported conflict error must be accompanied by a readback that confirms the conflict; a success must not later be contradicted by discovering the write did not land.

---

### Core 12: A session holds at most one item at a time

Claiming a second item before resolving, releasing, or abandoning the first is refused.

**Machine check:** ledger row `CCV1-017` — probe `ledger/checks/test_custody_rows.py::test_row_ccv1_017` (the refusal's shape), behaviour in Conformance 4's fixtures (`modules/tool-work-tracker/tests/test_conformance_fixtures.py`) — an attempt to claim a second item while already holding one must fail with "already holding" error.

---

### Core 13: Every custody interaction goes through the `work_*` tool seam

All capability to mutate, claim, release, or resolve items is exposed through the tool seam (`work_claim`, `work_resolve`, `work_release`, `work_declare`, `work_status`, `work_edit`, etc.). A capability reachable only via raw `bd` CLI or internal API is a missing verb — the missing verb is the bug.

**Machine check:** NOT-ASSERTABLE. Enforced by code review and skill documentation. No automated check verifies an agent did not shell out to raw `bd`.

**Reviewed at cadence:** PR audit and skill training, and at each `ledger/reconcile-report.md` re-check.

---

### Core 14: Claim refusals are specific and actionable

When a claim is refused, the error names the specific blocker: already held by (actor), not found, or blocked by (open dependency). A refusal must never be "claim refused" without attribution.

**Machine check:** ledger row `CCV1-020` — cites `tests/integration/test_directed_claim.py` (four named refusal tests: already held, not found, blocked by an open dependency, and the claim succeeding once the blocker closes) — error messages on claim refusal must name the blocker.

---

### NOT-ASSERTABLE 1: No raw-bd escapes without code review

The ability to interact with custody/items is intentionally constrained to the `work_*` tool seam. An agent that shells out to `bd` directly (instead of using `work_*` tools) violates this invariant. However, no mechanical check can verify that an agent did not do this; the constraint is enforced socially through code review, skill documentation, and process.

**Reviewed at cadence:** Per-session log audit, PR review, skill training, and at each `ledger/reconcile-report.md` re-check.

---

## Backlogged Clauses

These are candidate clauses with named promotion triggers. Each becomes a Core clause (and possibly a major-version contract bump if it affects existing implementations) once its trigger condition is met.

### Backlog 1: Proactive lost-custody notification

**Proposal:** Add a signal (e.g., return code, flag in tool response, SSE event) that immediately notifies an agent when its custody is reclaimed, without waiting for a passive poll.

**Trigger:** an agent reports that it discovered a lost custody too late — that is, the passive `holding.custody_lost` poll was not enough — and the owner then takes the delivery-mechanism decision: in-band (return code / tool response flag) or out-of-band (SSE event / subscription).

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

**Status 2026-09-06 (owner's word: *discharge*):** the D-6 recovery need is already met by an existing verb, so Freeze 2 is discharged rather than deferred — see Freeze 2. `work_release` / `Beads.release` carries a pre-write `already_closed` branch (`src/amplifier_work_tracker/adapter.py`) that reads the item back contention-free BEFORE any write and, when it is already resolved, returns `already_closed=True` having written nothing at all. This clause stays Backlogged only for a *further*, distinct verb (e.g. `work_custody_clear`) beyond that branch; nothing about it blocks the Freeze Bar.

---

## Conformance

### Conformance Kit

The following fixtures discriminate between correct and incorrect implementations. All must be included in the test suite and pass before Freeze Bar.

### Conformance 1: Conflicted-but-landed close (from Incident B, D-5)

**Scenario:** A close operation is issued. The write lands (the item status changes to closed), but a serialization/conflict error is encountered afterward (e.g., during WAL sync or post-write validation).

**Good behavior:** The error is raised, but a readback confirms the close landed. The tool correctly returns success (or re-tries the readback on failure).

**Bad behavior (pre-fix):** The error is raised, and no readback is performed. The error message claims the close failed, but the state check would reveal it succeeded. The API contract is violated (reported failure ≠ actual state).

**Test location:** `modules/tool-work-tracker/tests/test_phantom_conflict_recovery.py` (tool seam) and `tests/integration/test_phantom_conflict_recovery.py` (adapter layer).

**Verification:** Call `work_resolve(id)`, capture the exception, then call `work_list(item_id=id)` to verify the item is actually closed.

---

### Conformance 2: Post-reclaim close fence (from D-2)

**Scenario:** An item is claimed by Session A. The reclaim sweep runs and moves the item to open status, stripping the custody. Session A, unaware of the reclaim, calls `work_resolve(id)` to close the item.

**Good behavior:** The close is refused with an error like "item not held by this session" or "custody lost; reclaim detected."

**Bad behavior (pre-fix):** The close succeeds, even though the holder has been reclaimed and no longer holds the item. The item is closed by a stale holder.

**Test location:** `modules/tool-work-tracker/tests/test_conformance_fixtures.py` (tool seam) and `tests/integration/test_post_reclaim_fence.py` (adapter layer).

**Verification:** Claim item → trigger reclaim manually → call `work_resolve()` → verify refusal.

---

### Conformance 3: In-process recovery after reclaim (from Core 8)

**Scenario:** A session holds an item, the reclaim sweep runs and strips custody, and the session calls a tool (e.g., `work_status`) to check status.

**Good behavior:** The tool reveals `holding.custody_lost: true` (or similar signal). The session can then call the recovery verb — `work_release`, whose `Beads.release` pre-write `already_closed` branch drops a wedged hold without writing to the item — without manual intervention or restart.

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

This section names no `check_*()` function; the repository's `check_*` functions (`src/amplifier_work_tracker/contract.py`) are `doctor`'s checks, listed below — not pytest tests in `ledger/checks/`. Each clause above is carried by a ledger row in `ledger/rows.yaml`, asserted by that row's probe in `ledger/checks/test_custody_rows.py` or by the tests that row cites, and run by `make test` (which collects `ledger/checks` alongside every tier) and by CI. Each clause's own **Machine check:** line names the row that carries it.

Five clauses additionally carry a runnable `doctor` check, registered in `src/amplifier_work_tracker/contract.py` and surfaced by `src/amplifier_work_tracker/cli.py`. These are checks an operator runs against a live deployment, not pytest tests:

- `claim.atomic` / `claim.directed_atomic` — Core 1 (claim is atomic, in both modes)
- `custody.fresh_survives` — Core 2 (liveness over elapsed time)
- `custody.idle_not_exempt` — Core 5 (`awaiting_human` is not an exemption)
- `custody.fenced` — Core 9 (renewal and takeover fenced on holder and generation)
- `sweeps.alive` — Core 6 (the reap/notify loops are completing sweeps)

---

## Reserved

The following identifiers and fields are reserved for future use or explicitly excluded from current scope:

- **`custody.pid`** / **`custody.host`** — recorded for forensic and debugging purposes (to identify the last holder). Explicitly NOT used as a liveness input. These fields are not consulted by `reclaim_eligible()` and do not participate in reclaim decisions.

- **Custody delegation or transfer** — explicitly not supported in v1. A claim is owned by its holder and cannot be transferred; re-claiming requires the sweep or a new claim.

---

## Residual Issues

Conformance status for every named issue (D-1 through D-6) -- resolved, open, or Backlogged -- lives in `ledger/rows.yaml` (per-row disposition) and `ledger/reconcile-report.md` (the reconcile narrative); it is not duplicated here.

---

## Freeze Bar

Before this contract moves from DRAFT to FROZEN, all of the following conditions must be satisfied:

### Freeze 1: Residual issues resolved or Backlogged

All three residual issues (D-1, D-2, D-5) resolved or moved to Backlogged with owner approval. Each maps to the ledger row that carries it, so this condition is readable from the repository alone: **D-1 → `CCV1-003`** (a claim whose custody step fails now compensates — the item goes back to ready), **D-2 → `CCV1-009`** (the post-reclaim close fence, keyed on custody identity rather than status), **D-5 → `CCV1-014`** (a conflicted-but-landed write is decided by read-back, not by the wrapper's verdict). Their conformance status lives in `ledger/rows.yaml`, not here.

---

### Freeze 2: D-6 recovery verb designed and implemented

D-6 recovery verb designed and implemented (or Backlogged with explicit approval to defer).

**Discharged 2026-09-06** — the owner's word was *discharge*, not defer, because the verb already exists and is tested. It is `work_release` / `Beads.release`'s pre-write `already_closed` branch (`src/amplifier_work_tracker/adapter.py`): it reads the item back contention-free BEFORE any write and, when the item is already resolved, returns `already_closed=True` having performed no write to the item at all — which is what makes reopening a closed item structurally impossible from this path rather than merely unlikely. Tested and green: `tests/integration/test_phantom_conflict_recovery.py::test_release_on_an_already_resolved_item_writes_nothing_and_reports_already_closed` (adapter layer) and Conformance 3's `test_fixture3_release_of_an_already_closed_held_item_clears_the_latch` in `modules/tool-work-tracker/tests/test_conformance_fixtures.py` (tool seam). Backlog 3 remains Backlogged only for a further, distinct verb beyond this branch.

---

### Freeze 3: All four Conformance fixtures implemented, passing, and executable

All four Conformance fixtures implemented, passing, and executable via `make test`.

---

### Freeze 4: All check functions implemented and passing

All check functions (custody, claim, readback, fence, single-hold) implemented and passing.

---

### Freeze 5: Test suite importable and run as part of CI

Test suite (`modules/tool-work-tracker/tests/`) is importable and run as part of CI. That is the suite whose absence made this a Freeze blocker — it once ran in nothing, because the tool module was not installed into the venv — and it is the suite `CCV1-022` reads this clause as naming.

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

- **2026-09-06 — FROZEN.** Owner ratification and signature (Freeze 9): owner's literal words "your recommendations are good, go for all". Status moves DRAFT → FROZEN; from here this file changes only by a sibling proposal (custody-coordination.v2-candidate.md) with evidence; hooks-candidate-guard refuses in-place edits.
- **2026-09-06 — DRAFT true-up, owner-ratified ("go for all"):** the Freeze 8 external review's nine pre-lock fixes and six nits, applied to this text and nothing else. RC-1: the nine **Machine check:** lines that named ids existing nowhere in the repository (`claim.custody_indivisible`, `custody.one_strike`, `sweep.required_and_scheduled`, `fence.close_post_reclaim`, `recovery.discoverable`, `write.readback_verified`, `write.honest_failure`, `session.single_hold`, `claim.error_specificity`) now name the assertion that actually carries the clause — its ledger row plus the probe or tests that row cites; the five lines that DO name a real `doctor` check say so, and gain their row. RC-2: §Checks reworded to what exists — ledger rows, their probes, and the five real `doctor` checks — dropping the three `check_*()` names that were never in the repository and the false claim that the two real ones live in `ledger/checks/`. RC-3: Freeze 1 maps D-1 → `CCV1-003`, D-2 → `CCV1-009`, D-5 → `CCV1-014` inline, so the condition is readable from the repository alone. RC-6: Core 1's parenthetical corrected — `doctor --quick` skips those two checks because they are the two slowest, not for a Freeze Bar dependency, and the section is §Freeze Bar (there is no §Freeze Blockers). RC-7: Core 5's "(Backlogged feature)" struck — `should_notify` ships and is consulted by the notify sweep; what is Backlogged is Backlog 1's *different*, agent-facing signal. RC-8: Core 6's check line points at `CCV1-007`/`CCV1-008` and records that sweep observability shipped as `doctor`'s `sweeps.alive`. RC-9: TTL is defined once, in the Core Clauses preamble, with its value (`CUSTODY_TTL_SECONDS`, 900s/15min by default, env-overridable). Nits: Freeze 5's glob `tests/test_*.py`, which matched no file, replaced by the real suite `modules/tool-work-tracker/tests/`; Conformance 1 and 2's "Bad behavior (current)" → "(pre-fix)" (neither is current; both were fixed and are measured green); Conformance 1's Test location given the same two-path form Conformance 2 already has, naming the tool-seam file as well as the adapter one; `custody.generation` removed from Reserved, because Core 9 makes it normative; both **Reviewed at cadence:** lines gain a standing trigger, "at each `ledger/reconcile-report.md` re-check"; Backlog 1's trigger made observable ("an agent reports that it discovered a lost custody too late"). Status remains DRAFT at this entry. RC-10 (Freeze 8 pass 2, same ratification): §Checks' first sentence, which the RC-2 rewording had made false ("no `check_*()` function namespace" — 44 exist, as `doctor` checks), corrected to say what the `check_*` functions are and are not.
- **2026-09-06 — Freeze 2 discharged, owner's word "discharge":** the D-6 recovery verb is not new and does not need designing — it is `work_release` / `Beads.release`'s pre-write `already_closed` branch, which reads the item back contention-free BEFORE any write and, on an already-resolved item, returns `already_closed=True` having written nothing, making a reopen structurally impossible from that path. Tested green at both layers: `tests/integration/test_phantom_conflict_recovery.py::test_release_on_an_already_resolved_item_writes_nothing_and_reports_already_closed` and Conformance 3's `test_fixture3_release_of_an_already_closed_held_item_clears_the_latch`. Freeze 2 and Conformance 3 now name it; Backlog 3 stays Backlogged only for a further, distinct verb beyond that branch. This closes the review's finding that neither of Freeze 2's two routes had its evidence.
- **2026-09-06 — Freeze 8 record:** PR review of this contract by an external reviewer (an independent session, not the author), verdict **REQUEST CHANGES** — nine findings to fix before lock and six nits, all text-only, no code. The reviewer ran the machinery independently and green: `pytest ledger/checks -q` 60 passed, `make ledger-mutate` 69/69 proven with no unproven mutation, and the ten Conformance-fixture tests passed. The fixes are the two entries above; this is pass 2 on the PR.
- **2026-09-03 — DRAFT amendment, owner-ratified ("ok, yes, proceed"):** struck all Current-state annotations (conformance status lives in the ledger only — pillar 1); numbered Conformance 1–4 and Freeze 1–N for bare-id ledger citation (LEDGER-FORMAT §2); corrected the four Test-location lines to the real paths. Status remains DRAFT.
- **2026-09-01 — DRAFT.** First draft, derived from Phase 0 evidence and Call 8 ratified decisions. Includes 14 Core clauses (with 5 VIOLATION rows and 1 partial CONFORMS), 3 Backlogged clauses, 4 Conformance fixtures, Reserved section, and 6 Residual Issues (D-1 through D-6) awaiting Phase 2 resolution. Freeze Bar blockers named. Awaiting owner review at ENCODE gate.

