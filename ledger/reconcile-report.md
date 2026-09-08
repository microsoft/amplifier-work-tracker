# Reconcile report — SEED

**Contract:** `contracts/custody-coordination.v1.md` (DRAFT, owner-ratified at the
ENCODE gate 2026-09-01)
**Mode:** SEED (first population of the ledger)
**Run:** 2026-09-01, branch `converge/seed-custody-ledger`, tree `b5b23ca`
(branched from `main` @ `b5b23ca`; the reference fix is PR #63, merge `94f0b46`)
**Ledger:** `ledger/rows.yaml` (24 rows) + `ledger/checks/` (24 executable checks)

---

## Re-review 2026-09-04 (VISION.md two-seam extension)

**Trigger:** `docs/VISION.md` changed, so `CCV1-000`'s pin failed. Under
`LEDGER-FORMAT.md` sec.4 that mandates a **full ledger re-review, never a silent
hash bump** — this section is that re-review's record.
**Run:** 2026-09-04, branch `converge/encode-operator-surface` (branched from
`main`), at the operator-surface ENCODE gate. Owner ratification of the DRAFT
text, literal: *"lgtm."*

**What changed.** `docs/VISION.md` was extended from a one-seam vision to the
one repo vision covering two seams: the Scope line now names the custody seam
**and** the operator surface, the `Governing contract:` line became
`Governing contracts:` and points additionally at
`contracts/operator-surface.v1.md`, and a new *The Operator Surface* section
(Principles 8–12), four anti-goals, and Changelog entries were added.
`contracts/operator-surface.v1.md` was added as a new DRAFT contract in the same
change. **`contracts/custody-coordination.v1.md` was not opened** — the boundary
between the two contracts is a one-way citation from the new contract into the
custody one.

**Hash, old → new** (`sha256`, whole-file bytes, computed exactly as
`ledger/checks/_support.py::sha256` does):

```
docs/VISION.md                        b7547519a2b05432652c28c5c4201e669ea8a79ce8621d8615dacadb2f55da4c
                                   -> f5eb400c79211d90980efec7b35120852a71efa78ace6106dacd25fb448d5013

contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
                                      (unchanged — re-verified byte-for-byte on this run, not assumed)
```

**Rows re-anchored: 0 — checked, not assumed.** All 24 rows were walked. Every
row that quotes contract text anchors into `contracts/custody-coordination.v1.md`
(24 `contract.file` cites), whose bytes did not move; `docs/VISION.md` appears in
the ledger **only** as a `CCV1-000` SYNC hash entry — no row quotes vision text,
so the two vision lines that did change (Scope, Governing contract) are cited by
no row and nothing needed re-anchoring or a notes correction. `pytest
ledger/checks -q` re-verifies every quote on every run: **26 passed**.

**Dispositions unchanged: 22 CONFORMS / 2 NOT-ASSERTABLE / 0 VIOLATION / 0 GAP**
— re-checked against the tree rather than assumed. This branch touches
documentation and the ledger only (`git diff origin/main --stat`:
`contracts/operator-surface.v1.md`, `docs/VISION.md`, `ledger/rows.yaml`,
`ledger/reconcile-report.md`), so no row's subject code moved; every probe was
re-run green and every probe's discriminating power re-confirmed by
`make ledger-mutate` — **15 / 15** mutations still flip their probe red, zero
unproven. §1's table stands as written.

**Not seeded here.** `contracts/operator-surface.v1.md` carries no ledger rows
yet and is deliberately absent from `CCV1-000`'s pin: it is a different contract
and will be SEEDED as its own row family (`OSV1-###`), with its own SYNC row, in
a following step.

---

## 1. Rows by disposition

**Re-reviewed 2026-09-03, after the DRAFT amendment** (owner-ratified,
"ok, yes, proceed": struck all Current-state annotations, numbered
Conformance 1-4 / Freeze 1-9, corrected the four Test-location lines --
see the contract's own Changelog and CCV1-000's notes). This table is the
CURRENT tally, computed from `rows.yaml` on this run; it supersedes §1a.

| Disposition | Count | Rows |
|---|---:|---|
| CONFORMS | 22 | CCV1-000, -001, -002, -003, -004, -005, -006, -007, -008, -009, -010, -011, -012, -013, -014, -015, -016, -017, -020, -021, -022, -023 |
| VIOLATION | 0 | — |
| GAP | 0 | — |
| NOT-ASSERTABLE | 2 | CCV1-018, -019 |
| OPEN-PINNED | 0 | — |
| EXCLUDED | 0 | — |

Zero `VIOLATION` and zero `GAP` rows remain -- every red row the SEED filed
(§1a) was fixed and flipped to `CONFORMS` across highway waves 1 and 2 (PR
#68, PR #71), each with its probe retargeted at the fixed shape in the same
change (`VIOLATION-MOVEMENT`, sec.11.1). This amendment's own full re-review
(mandatory on the CCV1-000 hash change) re-verified every row's quote against
the amended contract bytes, re-anchored none (none needed it -- see the
amendment's own notes on CCV1-000), and retargeted the two rows that cited
the contract's unnumbered `Freeze Bar` section to the bare numbered ids the
amendment created (CCV1-022 -> `Freeze 5`, CCV1-023 -> `Freeze 3`). No row's
disposition changed as a result of the amendment itself -- only the bytes
each row reads moved, and the SYNC row's pinned hash moved with them.

### 1a. SEED snapshot (2026-09-01) -- history, superseded by the table above

| Disposition | Count | Rows |
|---|---:|---|
| CONFORMS | 12 | CCV1-000, -001, -002, -004, -006, -007, -010, -011, -014, -017, -020, -021 |
| VIOLATION | 4 | CCV1-003, -009, -012, -022 |
| GAP | 6 | CCV1-005, -008, -013, -015, -016, -023 |
| NOT-ASSERTABLE | 2 | CCV1-018, -019 |
| OPEN-PINNED | 0 | — |
| EXCLUDED | 0 | — |

All 15 Core / NOT-ASSERTABLE clauses are cited by ≥ 1 row. Five clauses carry
more than one row — because the clause is green in code and red in prose (Core 4,
Core 6, Core 11), covers two distinct write paths (Core 10), or is a checklist
line with two independent failures (Freeze Bar). No row was written that a
contract clause does not back.

---

## 2. SYNC status

**2026-09-04 rehash** (operator-surface ENCODE gate, owner-ratified *"lgtm."* —
see the re-review section above): `CCV1-000` now pins

```
contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
docs/VISION.md                        f5eb400c79211d90980efec7b35120852a71efa78ace6106dacd25fb448d5013
```

The custody contract's hash is unchanged — the vision moved under the ledger, the
contract did not. This mismatch triggered the **mandatory full-ledger re-review**
recorded above: 24 rows walked, zero re-anchored (no row quotes `docs/VISION.md`
text), dispositions unchanged at 22 CONFORMS / 2 NOT-ASSERTABLE, probes green
(26) and still discriminating (`make ledger-mutate` 15/15).
`contracts/operator-surface.v1.md` is not pinned here — its own `OSV1-###` SYNC
row lands when that family is seeded.

**2026-09-03 rehash** (owner-ratified DRAFT amendment -- see the contract's own
Changelog): `CCV1-000` now pins

```
contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
docs/VISION.md                        b7547519a2b05432652c28c5c4201e669ea8a79ce8621d8615dacadb2f55da4c
```

`docs/VISION.md` was not touched -- its hash is unchanged. This mismatch
triggered the **mandatory full-ledger re-review** every hash change requires
(never a silent bump): every row's quote re-verified against the amended
contract bytes (`pytest ledger/checks`, all green), zero rows needed
re-anchoring (the amendment struck `**Current state:**` annotations and
renumbered/renamed sections the quotes themselves never anchored into), and
the two rows citing the contract's unnumbered `Freeze Bar` section were
retargeted to the bare numbered ids the amendment created (CCV1-022 ->
`Freeze 5`, CCV1-023 -> `Freeze 3`). See §1 for the re-reviewed disposition
tally (unchanged: still 22 CONFORMS / 2 NOT-ASSERTABLE / 0 VIOLATION / 0 GAP).

**SEED pin (2026-09-01), for history:**

```
contracts/custody-coordination.v1.md  00e65ca7eada5c8699823ddd2a0fa12b1f9c6027376db53de2366d640b813672
docs/VISION.md                        b7547519a2b05432652c28c5c4201e669ea8a79ce8621d8615dacadb2f55da4c
```

First pin — no prior hash to compare, so no re-review was triggered. Every
subsequent mismatch triggers a **mandatory full-ledger re-review, never a silent
hash bump**: quote verification only proves the text still exists, not that each
row still reads it correctly.

---

## 3. Coverage tripwires

Run with the ledger, every time (`ledger/checks/test_ledger_integrity.py`), all
green on this run:

| Tripwire | Result |
|---|---|
| Every Core clause cited by ≥ 1 row | PASS — 15/15, none uncited |
| Every row's quote verifies against contract bytes | PASS — 23/23 (whitespace-collapsed contiguous match) |
| Every assertion ref resolves | PASS — 15 probes (13 `probe` + 2 `absence`) found by name; 7 `indexed` rows' 21 cited tests found by static parse |
| Probe ↔ row bidirectional pairing | PASS — no orphan probes, no rows citing a missing probe |
| Every GAP/VIOLATION carries a live `work` ref | PASS — 10/10 |
| Every OPEN-PINNED / NOT-ASSERTABLE carries a justification | PASS — 2/2 |
| Row ids well-formed, unique, ordered | PASS |
| `DIVERGED` not used (illegal for a self-governed contract) | PASS |
| Every `indexed` row records `last_measured` | PASS — 7/7 |

---

## 4. What was actually run (a self-report is not proof)

Every CONFORMS row cited as *measured* below was measured on this run, on this
tree. Nothing is green here because a document said so.

```
$ ./.venv/bin/python -m pytest tests/unit -q
741 passed, 1 warning in 35.85s

$ ./.venv/bin/python -m pytest -m integration \
    tests/integration/test_phantom_conflict_recovery.py \
    tests/integration/test_resolve_fence.py \
    tests/integration/test_directed_claim.py -q
15 passed in 18.34s

$ ./.venv/bin/python -m pytest ledger/checks -q
24 passed in 0.06s

$ ./.venv/bin/python -m pytest tests ledger/checks -q      # the new `make test`
1 failed, 1147 passed, 3 skipped, 1 warning in 1004.35s     # see §8

$ ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
All checks passed! / 136 files already formatted

$ ./.venv/bin/pyright src tests
0 errors, 0 warnings, 0 informations
```

Integration tests run against the suite's own throwaway dolt server on an
ephemeral port (`tests/_dolt_isolation.py`). The live service, `:3308`, and the
owner's ports were never touched. The only writes to the live tracker were the
ten sanctioned `work_add` filings in §6.

**Mutation check on the red-row pins.** A probe that cannot fail is not a probe.
Five pins were mutation-tested by simulating the fix landing and confirming the
probe goes red, then restoring the tree (`24 passed` afterwards):

| Probe | Mutation simulated | Result |
|---|---|---|
| `test_row_ccv1_003` | claim releases on custody failure | RED ✓ |
| `test_row_ccv1_009` | the `status == "held"` gate removed | RED ✓ |
| `test_row_ccv1_012` | a read-back added to `release()` | RED ✓ |
| `test_row_ccv1_016` | the awareness.md sentence corrected | RED ✓ |
| `test_row_ccv1_022` | a `test-modules` target added to the Makefile | RED ✓ |

---

## 5. Drift found — in both directions

Drift is bidirectional. Moving away from a clause is drift; **silently moving
back toward it is also drift**, because it leaves main carrying a ledger that
lies. Both directions were found on this run.

### 5a. Implementation drifted from the contract (the ordinary direction)

Four VIOLATION rows and six GAP rows, all filed (§6). The load-bearing ones:

- **CCV1-009 / Core 7** — the close fence runs only under `if current.status ==
  "held":`. A reaped item is `open` with its assignee cleared, so a stale
  holder's close skips the fence. `adapter.py`'s own docstring names this exact
  shape as the previously *measured* bug the fence was built to close; the status
  gate added in PR #51 reinstated it. Neither doctor check covers it — both stage
  a *takeover*, so status is `held` when the fence is tested.
- **CCV1-003 / Core 3** — claim and custody are two writes with no rollback; a
  failed `take_custody` leaves the item held with no custody record.
- **CCV1-012 / Core 10** — `release()`'s success path still reports success off
  the exit code, and `release()` is what both `work_release` and every reclaim
  call.
- **CCV1-022 / Freeze Bar** — the tool module's test suite runs in nothing and
  cannot be imported. It holds the *only* mechanical assertions of post-reclaim
  custody behavior.

### 5b. The contract drifted from a fixed implementation (the reverse direction)

**The contract's own "Current state" annotations are partially STALE.** They were
drafted from pre-fix Phase-0 evidence; PR #63 (merge `94f0b46`, on main,
deployed) landed after. Measured on this tree, these lines no longer describe
reality:

| Contract says | Measured reality | Row |
|---|---|---|
| **Core 11: VIOLATION** — "a close operation raised a conflict error but the readback … revealed the close had landed. **Freeze Bar blocker.**" | **CONFORMS for resolve/release.** Fixed in three layers, all green this run: a returncode gate on `_run`'s retry loop (which removed the incident's actual trigger — a *successful* invocation whose output merely mentioned a retryable phrase was retried until the loop "exhausted" and raised while quoting its own success confirmation); verify-by-read-back on both verbs' conflict path; and the discriminating negative — a close that genuinely did *not* land still raises. | CCV1-014 |
| **Core 10: VIOLATION** — "The `release()` operation … has **no readback verification**." | **Half fixed, and the row is narrowed accordingly.** The conflict path *is* now verified (measured). The success path is not. The row stays VIOLATION for a strictly smaller reason than the contract states. | CCV1-012 |
| **Core 8: PARTIAL** — "Freeze Bar requires (a) a test covering both cases, (b) **a recovery verb** for non-fenced losses." | **(b) is satisfied without a new verb.** `release()` now checks status *before* any write and returns `already_closed` having written nothing, so the wedge-recovery path cannot reopen a closed item — the D-6 need is met by existing `work_release` semantics. Backlog 3 (`work_custody_clear`) is no longer Freeze-blocking on that ground. (a) remains unmet only because the tool-seam test is unrun (CCV1-022). | CCV1-010 |
| **Core 6: "Partially CONFORMS"** | **CONFORMS.** All three properties the clause names are covered and measured: required (the sweep is the only writer of reclaims), scheduled (`reap_loop`), observable (a heartbeat at startup and after every clean sweep, which is what lets `sweeps.alive` tell "quietly healthy" from "silently dead"). The clause's residual — that a sweep be scheduled in the CI/CD pipeline used for Freeze validation — is a Freeze-Bar question, carried by CCV1-022, not a property of this code. | CCV1-007 |
| **Fixture 1: "Test location: `tests/test_incident_b.py` (to be added)"** | **Already exists and passes**, at `tests/integration/test_phantom_conflict_recovery.py` (4 tests, measured). Only the pointer is stale. | CCV1-023 |
| **Fixture 2: "Test location: `tests/test_reap_recovery.py:67-72`"** | **No such path.** The real file is `modules/tool-work-tracker/tests/test_reap_recovery.py`, which runs in nothing. | CCV1-023 |
| **Residual D-3** (Incident C, `held_stale` always-wrong) | **Fixed in PR #63** and not carried as a clause — it is a dashboard/summary read-path concern, explicitly out of this contract's scope. | — (out of scope) |

**The contract text itself was left untouched.** Correcting it is an amendment,
made in the open by its owner — not something a reconcile run does quietly. The
drift is recorded here and pinned by the rows, which is what makes the amendment
a decision someone takes rather than a discrepancy someone eventually notices.

### 5c. Prose drifted from the contract (three sites, one newly created)

- `skills/claiming-work-safely/SKILL.md`: "you do not need to do anything to keep
  it fresh" — inverted for exactly the failure Core 4 names (CCV1-005).
- `context/awareness.md` + the same skill: "15 minutes without a renewal releases
  the item back to the queue" — states the TTL as self-enforcing, which Core 6
  explicitly denies (CCV1-008).
- `context/awareness.md`: "so the write genuinely did not happen" — **drift
  created by the fix itself.** This sentence was defensible before PR #63; it
  became wrong the moment the code started reading back a conflicted write
  *because a reported conflict can have landed*. It was not on the ratified
  lane-work list. It is exactly the class this ledger exists to catch: nobody
  regressed anything, and the repo still ended up telling agents something the
  code contradicts (CCV1-016).

---

## 6. Items filed

Ten items, one per red row, all into project `work_tracker`, all titled
`[ledger] …` and citing their row id, clause, measured evidence, and an
acceptance criterion that is the clause's machine check going green. The queue
was checked first (`work_list`): 32 items, all resolved, no open duplicates.

| Row | Disposition | Item | Title (abbreviated) |
|---|---|---|---|
| CCV1-003 | VIOLATION | `work_item_pipeline-aih` | failed take_custody leaves item held with no custody record |
| CCV1-005 | GAP | `work_item_pipeline-m7o` | skill says custody keeps itself fresh; renewal is one-strike |
| CCV1-008 | GAP | `work_item_pipeline-qjn` | prose states the TTL as self-enforcing |
| CCV1-009 | VIOLATION | `work_item_pipeline-dn4` | post-reclaim close unfenced (gate on `status == "held"`) |
| CCV1-012 | VIOLATION | `work_item_pipeline-1f2` | `release()` success path has no read-back |
| CCV1-013 | GAP | `work_item_pipeline-1gz` | claim path has no verify-by-read-back |
| CCV1-015 | GAP | `work_item_pipeline-2x3` | only resolve/release verify a conflicted write |
| CCV1-016 | GAP | `work_item_pipeline-ryp` | awareness.md still says a reported conflict did not land |
| CCV1-022 | VIOLATION | `work_item_pipeline-a7n` | modules/tool-work-tracker/tests runs in nothing |
| CCV1-023 | GAP | `work_item_pipeline-qmj` | Conformance Fixtures 2, 3, 4 not implemented-and-runnable |

Dependency edges recorded: `qmj` **blocks-on** `a7n` (the fixtures cannot be
"executable via `make test`" until the suite runs at all); `dn4` **relates-to**
`a7n`.

Nothing here paged a human. Every finding that needs an owner decision is a
filed row plus a filed item, taken asynchronously at the next wave's
priority/kill gate.

---

## 7. Freeze Bar status — FROZEN (re-issued 2026-09-06)

> **RE-ISSUED 2026-09-06.** The section below is the **SEED reading of
> 2026-09-01** and is **superseded**; it is kept verbatim under §7a because a
> narrative of record is not rewritten, only re-issued. It was the last section
> of this report still carrying the SEED "BLOCKED" reading, while §1 had already
> been re-issued and stamps its own §1a superseded — and the contract's Residual
> Issues section delegates residual status *to this report*, so Freeze 1 read
> FALSE at exactly the place the contract points. That was the Freeze 8 external
> review's finding 4, and this re-issue is its fix.
>
> **The reading as of 2026-09-06, on this tree:** every Freeze Bar condition is
> met and `contracts/custody-coordination.v1.md` is **FROZEN**. Condition by
> condition, with what changed since the SEED reading:
>
> | # | Checklist item | Status 2026-09-06 |
> |---|---|---|
> | 1 | D-1, D-2, D-5 resolved or Backlogged with owner approval | **MET.** All three resolved and CONFORMS: D-1 → `CCV1-003` (closed by `work_item_pipeline-aih` — a failed custody step now compensates), D-2 → `CCV1-009` (closed by `work_item_pipeline-dn4` — the fence is keyed on custody identity, not status), D-5 → `CCV1-014` (verify-by-read-back). The contract now states this mapping inline, so the condition is readable from the repository alone. |
> | 2 | D-6 recovery verb designed and implemented (or Backlogged with approval) | **MET — DISCHARGED, on the owner's word.** The SEED reading said "needs owner confirmation that this discharges the item rather than deferring it"; the owner's answer on 2026-09-06 was **discharge**. The verb is `work_release` / `Beads.release`'s pre-write `already_closed` branch, tested green at both layers (`tests/integration/test_phantom_conflict_recovery.py`, and Conformance 3's `test_fixture3_release_of_an_already_closed_held_item_clears_the_latch`). Backlog 3 stays Backlogged only for a further, distinct verb. |
> | 3 | All four Conformance fixtures implemented, passing, executable via `make test` | **MET.** Fixtures 2/3/4 landed (`work_item_pipeline-qmj`) in `modules/tool-work-tracker/tests/test_conformance_fixtures.py`; Fixture 1 is at `tests/integration/test_phantom_conflict_recovery.py` with its tool-seam counterpart, and the contract's Test-location line now names both. Measured this run: **10 passed**. `CCV1-023` CONFORMS. |
> | 4 | All check functions implemented and passing | **MET, and the clause now says what is true.** The SEED reading measured this against five `check_*()` names, three of which existed nowhere in the repository and two of which were doctor checks, not tests — the review's finding 2. §Checks was rewritten in the pre-lock true-up: each clause is carried by a ledger row and its probe or cited tests, run by `make test` and CI, with the five real `doctor` checks listed separately and honestly labelled. `pytest ledger/checks -q`: **60 passed**. |
> | 5 | Test suite importable and run as part of CI | **MET.** `CCV1-022` closed (`work_item_pipeline-a7n`, PR #68): the tool module is installed editable into the one venv, `make test` aggregates its suite, and CI runs it as its own Tier-5 step. The clause's dead glob `tests/test_*.py` was replaced by the real path in the pre-lock true-up. |
> | 6 | Every Core clause verified against actual code (grep/LSP, not paraphrase) | **MET.** Re-verified at the 2026-09-06 pre-lock re-check (§C2) and again at the true-up, where every **Machine check:** line was re-pointed at an artifact that actually exists. |
> | 7 | Every quote a contiguous, whitespace-collapsed substring | **MET and mechanized** — tripwire 2, all 24 CCV1 rows, green after the three re-anchors. |
> | 8 | PR review by an external reviewer (not the author) | **MET.** An independent session (not the author) reviewed the contract, ran the machinery itself green, and returned **REQUEST CHANGES** with nine findings and six nits. All are landed; the record is the contract's own `Freeze 8 record` Changelog entry. |
> | 9 | Owner ratification and signature ("FROZEN" stamp) | **MET.** Owner's literal words, 2026-09-06: *"Yep, your recommendations are good, go for all."* Status moved DRAFT → FROZEN in one write, with its dated Changelog entry. |
>
> **Net: zero blockers.** The four the SEED reading named — `CCV1-003`,
> `CCV1-009`, `CCV1-022`, `CCV1-023` — are all closed and CONFORMS, and the two
> process items (8, 9) are discharged. See §"Lock 2026-09-06 —
> custody-coordination.v1 FROZEN" below for the lock's own record.

---

### 7a. SEED reading, 2026-09-01 (history — superseded by §7 above)

Against the contract's own checklist:

| # | Checklist item | Status |
|---|---|---|
| 1 | D-1, D-2, D-5 resolved or Backlogged with owner approval | **BLOCKED.** D-5 is **resolved** (CCV1-014, measured). D-1 (CCV1-003) and D-2 (CCV1-009) are open, filed, unfixed. |
| 2 | D-6 recovery verb designed and implemented (or Backlogged with approval) | **MET, by a different route than the checklist assumes** — no new verb; `release()`'s no-write `already_closed` branch satisfies the need (CCV1-010). Needs owner confirmation that this discharges the item rather than deferring it. |
| 3 | All four Conformance fixtures implemented, passing, executable via `make test` | **BLOCKED.** Fixture 1 ✓ (measured, at a different path than the contract names). Fixtures 2, 3, 4 ✗ (CCV1-023). |
| 4 | All check functions implemented and passing | **PARTIAL.** `ledger/checks/` now exists and runs (CCV1-021). Of the five named checks, two are backed by tests executed here — `check_claim_atomic` (CCV1-001) and `check_custody_fresh_survives` (CCV1-002). The other three are pins on rows that are red or unfixtured: `check_readback_verified` (CCV1-012, VIOLATION), `check_fenced_close` (CCV1-009, VIOLATION), `check_single_hold` (CCV1-017, no behavioral fixture exists anywhere). Discharged fully only when CCV1-022 and CCV1-023 land. |
| 5 | Test suite importable and run as part of CI | **BLOCKED.** The tool module's suite is neither (CCV1-022). Verbatim: `import amplifier_module_tool_work_tracker` → `ModuleNotFoundError`. |
| 6 | Every Core clause verified against actual code (grep/LSP, not paraphrase) | **MET for this run** — every row was derived from a read of the cited code, and 12 rows are backed by tests executed here. |
| 7 | Every quote a contiguous, whitespace-collapsed substring | **MET and now mechanized** — tripwire 2, 23/23. |
| 8 | PR review by an external reviewer (not the author) | **NOT MET** — pending; this branch is unmerged and uncommitted by design. |
| 9 | Owner ratification and signature ("FROZEN" stamp) | **NOT MET** — pending items 1–8. |

**Net: 4 blockers to Freeze** — CCV1-003, CCV1-009, CCV1-022, CCV1-023 — plus
the two process items (8, 9). Two of the contract's own named blockers (D-5, and
D-4's conflict half) are **already discharged**; the contract does not yet say so.

---

## 8. Honest limits of this ledger

Stated plainly, because a ledger that overstates itself is worse than no ledger.

1. **Fifteen of the 24 rows assert STRUCTURE, not behavior** — source shape,
   prose wording, build wiring, or a content hash. They prove the code still has
   a given shape; never that the system still behaves a given way. `LEDGER-FORMAT.md` §8 names this limit; it is load-bearing
   here because the behavioral fixtures for Core 4, Core 7, Core 8 (tool half) and
   Core 12 all live in a suite that runs in nothing (CCV1-022). **Fixing CCV1-022
   is what lets four rows upgrade from pinned shape to measured behavior.** That is
   the single highest-value item in §6.
2. **Probes on red rows pin the known-wrong shape on purpose.** This keeps the kit
   green and makes drift immovable in both directions — a regression fails, and so
   does a silent fix. See §9 for the interpretive question this raises.
3. **An `indexed` cite proves a test exists, not that it still asserts the claim.**
   The tripwire verifies existence *statically* (parse, never import), so a cite
   can cross an environment boundary. Each indexed row therefore also records
   `last_measured` — the date its cited tests were actually executed and observed
   passing — and that field is itself enforced by a tripwire.
4. **One pre-existing test failure, unrelated to this change.**
   `tests/cli/test_cli_surface.py::test_doctor_quick_succeeds_against_the_real_installed_bd`
   fails on this host: `doctor --quick`'s `sweeps.alive` check reads the sweep
   heartbeat under the *isolated test workspace root*, where no sweep loop has ever
   run, so it correctly reports "no heartbeat ever recorded" and doctor exits
   non-zero. The real host's sweeps are healthy (`.sweeps-heartbeat.json`,
   `last_completed` 4 minutes before this run). Nothing this SEED changed is on
   that test's path (the changes are `ledger/`, `Makefile`, `ci.yml`,
   `pyproject.toml`). **No row and no item was filed for it — no contract clause
   backs it — and it is returned to the caller in §9 rather than decided here.**

---

## 9. Returned to the root — interpretive needs and adjudications

Stated, not guessed.

1. **Does the protocol sanction a VIOLATION row whose probe pins the
   currently-wrong behavior?** `LEDGER-FORMAT.md` §3 defines both-halves
   assertion for `DIVERGED` (external contracts) only. Applied here to
   self-governed VIOLATION/GAP rows it keeps the kit green and makes a silent
   re-alignment fail as loudly as a regression — but the alternative reading is
   that a red row should carry a *red* (or xfail) discriminating fixture, so the
   suite itself is honest about being non-conformant. **Implemented as the pin;
   flagged for a conformance ruling.** If the ruling goes the other way, the ten
   red rows' probes convert to xfail-marked fixtures — mechanical, ~1 lane hour.
   **ANSWERED 2026-09-01 (protocol-authority, Ruling-1): yes — the pin is
   conformant and PREFERRED over `xfail`,** subject to three conditions
   (notes on each pinning row · a named flip direction for "a VIOLATION was
   fixed" · complete, committed mutation evidence with the denominator
   stated). All three are discharged in §11; no probe converts to `xfail`.
2. **Format deviation: two rows carry an unnumbered clause id.** `Conformance:
   Checks` and `Freeze Bar` are contract sections the contract does not number,
   but `LEDGER-FORMAT.md` §2 requires "the bare numbered identifier exactly as the
   contract names it". Options: accept section-name clause ids, or amend the
   contract to number those sections. Recorded as data for `ledger-format.v1`
   per that document's own charter.
3. **Does `release()`'s no-write `already_closed` branch discharge Freeze Bar
   item 2 (the D-6 recovery verb), or merely defer it?** This is an owner call on
   the contract's own checklist, not a conformance reading. The ledger records the
   capability as present and measured (CCV1-010); it does not assume that closes
   the checklist item.
4. **The pre-existing tier-3 doctor failure (§8.4)** — real, reproducible, not
   clause-backed. Whether it gets an item is the caller's call, not mine. It
   matters for Freeze Bar item 5.
5. **Scope confirmation.** Residual D-3 (Incident C, `held_stale`) is treated as
   out of scope — dashboard/summary read path — per the contract's own Scope
   paragraph and the vision's. It is fixed anyway (PR #63), so nothing is lost;
   flagged only so the omission reads as a decision, not an oversight.

---

## 10. Files written

```
ledger/rows.yaml                          24 rows (SYNC + 23 clause rows)
ledger/checks/__init__.py                 package marker
ledger/checks/_support.py                 helpers: paths, whitespace-collapse matching,
                                          hashes, static test-name parsing
ledger/checks/test_custody_rows.py        15 per-row probes
ledger/checks/test_ledger_integrity.py     9 integrity + coverage tripwires
ledger/reconcile-report.md                this file
```

Modified, to make the contract's "run by `make test`" clause true rather than
aspirational (CCV1-021):

```
Makefile                 + `test-ledger` target; `test` now runs `tests ledger/checks`
.github/workflows/ci.yml  + "Tier 4 -- conformance ledger" step
pyproject.toml            + pyyaml to the `dev` extra (ledger/checks only; nothing in src/ imports yaml)
```

Nothing was committed or pushed; the orchestrator lands this branch via PR.

---

## 11. Format deviations — local extensions to `LEDGER-FORMAT.md`

Recorded here rather than applied silently, per that document's own charter:
these are **data for `ledger-format.v1`**, not a private dialect.

### 11.1 New flip direction: `VIOLATION-MOVEMENT`

`LEDGER-FORMAT.md` names four flip directions — `REGRESSION`,
`UN-DIVERGENCE`, `UNDECIDED-MOVEMENT`, `LEDGER-INTEGRITY`. **None of them
covers "a VIOLATION was fixed."** That is not a hypothetical gap: it is the
direction this repo's pinning probes exist to catch, and without a name for
it a lane that lands a fix sees a red check with no instruction attached.

| | |
|---|---|
| **Direction** | `VIOLATION-MOVEMENT` |
| **Applies to** | any `GAP` / `VIOLATION` row whose `assertion.kind` is `probe` or `absence` (`_support.is_pinning`) |
| **Meaning** | the pinning probe went red **because the behaviour moved TOWARD the contract** — a silent fix, which this ledger refuses to let pass unrecorded |
| **Action** | update the row to `CONFORMS` **and retarget the probe at the fixed shape in the SAME change**. Doing one without the other leaves main carrying a ledger that lies |
| **Not** | `REGRESSION` — nothing moved away from the contract, so the repo-fix/contract-amend response is the wrong one |
| **Defined in** | `ledger/checks/_support.py` (`FLIP_VIOLATION_MOVEMENT`, `FLIP_DIRECTIONS`, `LOCAL_FLIP_DIRECTIONS`, `expected_flip_direction`) |

`expected_flip_direction(row)` gives every row exactly one direction, so a red
ledger names its own meaning instead of leaving a reader to guess whether a
fix or a regression landed. `test_ledger_integrity.py` asserts every pinning
probe carries this direction.

**Grounding.** `LEDGER-FORMAT.md` §2 `assertion.kind: absence`; `PROTOCOL.md`
§3.3 "drift is bidirectional"; the protocol-authority's Ruling-1 (2026-09-01),
which held pin-the-wrong-shape **conformant and preferred over `xfail`**,
subject to the three conditions this section and §11.3 discharge.

### 11.2 Pinning-probe census (Ruling-1 condition 1)

**As of 2026-09-02, after the custody-ledger lanes merged: zero `VIOLATION`
rows remain.** Current census — 21 `CONFORMS`, 1 `GAP`, 2 `NOT-ASSERTABLE`.
The four rows that were `VIOLATION` at SEED (`CCV1-003`, `-009`, `-012`,
`-022`) were each fixed and flipped to `CONFORMS`, with their probes
retargeted at the fixed shape in the same change — i.e. `VIOLATION-MOVEMENT`
handled correctly four times before the direction had a name.

**One pinning row remains: `CCV1-023`** (`GAP`, `assertion.kind: absence`).
Its `notes` now carry the required statement verbatim — *"Probe pins the
current non-conformant behavior so a silent fix flips it red; a passing probe
here is NOT conformance — see disposition."* Condition 1 is therefore
discharged for the whole current pinning population (1 of 1).

> **Residual 1, named not fixed:** §1's disposition table is the **SEED**
> snapshot (2026-09-01) and no longer matches `rows.yaml`. Rewriting it is a
> reconcile run's job, not this lane's — flagged for the orchestrator.
>
> **DISCHARGED 2026-09-03** (mandatory full-ledger re-review triggered by the
> owner-ratified DRAFT amendment, CCV1-000): §1 now carries the current tally
> (22 CONFORMS / 2 NOT-ASSERTABLE / 0 VIOLATION / 0 GAP), re-reviewed and
> re-computed from `rows.yaml`, with the SEED table kept below it as §1a
> history rather than overwritten.
>
> **Residual 2 — a live `VIOLATION-MOVEMENT` event, unhandled:**
> `modules/tool-work-tracker/tests/test_reap_recovery.py::test_explicit_resolve_refusal_after_reap_clears_held_and_allows_new_claim`
> now fails `make test` with **`XPASS(strict)`**, its `xfail` reason still
> reading *"a post-reclaim close is not fenced … PRODUCT defect … not fixed
> here."* CCV1-009 **was** fixed (`work_item_pipeline-dn4`) and the row is
> `CONFORMS`, but that strict `xfail` marker — a pin in the modules suite
> rather than in this kit — was never retargeted in the same change. This is
> exactly the failure mode §11.1 names, and CCV1-022's own notes predicted it
> ("the day CCV1-009 is fixed, the xfail fails"). **Action:** drop the marker
> and let the test assert the fence directly. Out of this lane's scope
> (`modules/`), flagged for the orchestrator; it is the only `make test`
> failure on this tree that is not on the known pre-existing list.
>
> **DISCHARGED** by highway wave 2 (PR #71, `ea233a7`, closing CCV1-023 /
> `work_item_pipeline-qmj`): the marker was dropped and the test now asserts
> the fence directly (see `test_reap_recovery.py`'s own docstring). This
> amendment's re-review (2026-09-03) additionally corrected CCV1-009's and
> CCV1-022's ledger notes, which still described that xfail as present after
> PR #71 removed it — see those rows.

### 11.3 Mutation evidence (Ruling-1 condition 3)

`ledger/checks/mutation_harness.py`, run by `make ledger-mutate`. It runs
**every** probe against a counterfactual repo assembled in memory and requires
the probe to go RED. Injection over the check kit's own readers only — no
product-code edit, no subprocess, nothing written to the repo. The direction
pushed is derived from the ledger, not chosen per probe: a pinning row gets
the **fixed behaviour**, a green row gets the **known-wrong shape it forbids**,
the SYNC row gets a moved contract.

Measured 2026-09-02 on this tree:

```
pinning mutations       proven 3 / 3
pinning probes covered  proven 1 / 1
conformance mutations   proven 14 / 14
ALL mutations           proven 17 / 17
UNPROVEN, named with reason: (none)
```

Every probe in the kit is covered (15 probes; `CCV1-023` carries three
mutations, one per separable half of its pin). The harness exits non-zero on
any unproven mutation, and `test_ledger_integrity.py` runs it as tripwires 4
and 5, so a probe that quietly stops discriminating fails `make test` rather
than waiting for someone to remember this file.

**Negative control** (2026-09-02): replacing one mutation with a no-op that
changes nothing reports it `UNPROVEN — probe still PASSED under the
counterfactual`, drops the count to `pinning mutations proven 0 / 1`, and
exits 1. The harness can report a hole, so `proven 17 / 17` is a measurement
rather than a self-report.

**RE-MEASURED 2026-09-03** (mandatory full-ledger re-review, DRAFT amendment):

```
pinning mutations       proven 0 / 0
pinning probes covered  proven 0 / 0
conformance mutations   proven 15 / 15
ALL mutations           proven 15 / 15
UNPROVEN, named with reason: (none)
```

The denominator moved from 17 to 15, honestly: `CCV1-023`'s disposition had
already flipped `GAP` -> `CONFORMS` by the time this amendment started (its
three declared mutations, labelled `FIXED: ...`, were already being graded
as **conformance** probes rather than pinning ones by `is_pinning()`, which
keys off disposition -- the "1 pinning row remains" claim two paragraphs up
was itself SEED-era and superseded before this amendment touched anything).
The amendment's Part A corrected the contract's four stale Test-location
lines for real, which made those three mutations un-appliable (`anchor
occurs 0x`, `HarnessOutOfDate`) -- they modelled the drift getting fixed, and
the drift is now actually fixed. Retired per Ruling-1's own logic (a CONFORMS
probe is not a pinning probe) and replaced with ONE honest `REGRESSION`
mutation on `CCV1-023` (a stale Test-location line returning), keeping
`test_every_probe_has_a_declared_mutation` satisfied. Zero pinning rows/probes
remain in the kit, consistent with §1's current tally.

---

---

# SEED 2026-09-04 operator-surface.v1

**Contract:** `contracts/operator-surface.v1.md` (DRAFT, owner-ratified at the
ENCODE gate 2026-09-04, literal: *"lgtm."*)
**Mode:** SEED (first population of the `OSV1-###` family)
**Run:** 2026-09-04, branch `converge/seed-operator-surface`, branched from
`main` @ `4aaee50`
**Ledger:** 36 new rows appended to `ledger/rows.yaml` (now 60 rows over two
families) + `ledger/checks/test_operator_rows.py` (33 executable probes)
**Rulings applied:** `.amplifier/converge/ux-phase1-rulings.md` — Need 2 (the
exemption register and its census live in the ledger), Need 3 (the SYNC row
pins the custody contract too), Need 4 (Reserved 1 gets a NOT-ASSERTABLE row),
Ruling 6 (Tier-B must emit orchestrator-re-checkable artifacts).

**Every disposition below was MEASURED against the tree at `4aaee50`, not read
off the Phase-0 brief.** The brief was two days old and `main` had moved; where
this run confirmed it, that is said, and where it did not, that is said too.

---

## Re-review 2026-09-04 (operator-surface true-up #1)

**Trigger:** `contracts/operator-surface.v1.md` changed, so `OSV1-000`'s pin
failed. Under `LEDGER-FORMAT.md` sec.4 that mandates a **full ledger re-review,
never a silent hash bump** — this section is that re-review's record.
**Run:** 2026-09-04, branch `amend/operator-surface-trueup-1` (branched from
`main` @ `65f0e91`). Owner ratification of the amendment, literal:
*"yep, do it all."* Status stays **DRAFT** — nothing here stamps FROZEN.

### What changed in the contract — three parts, all owner-ratified

1. **Core 4's reach.** The clause was scoped to *"an inline `style=` attribute"*
   and now also reads *"or in a `<style>` block outside the token module
   (`webtheme.py`'s token block)"*; the `visual.single_source` machine check
   gained *"and zero literal colour/font/size declarations in any `<style>`
   block outside the token module"*. **Why:** `webtrust.py:256-302` hardcodes
   the retired palette (`--ground:#0D0D0C; --ink:#F2EEE6; --amber:#D9A253`)
   inside a `<style>` block that deliberately does not import the token CSS
   (`webtrust.py:249-253` says so in its own comment) — the exact defect the
   clause exists to prevent, and one the SEED reconcile could only
   **record-not-score** because the frozen text could not reach it (§6d, and
   `OSV1-005`'s seed notes, which returned the reading to the root).
2. **Core 10's machine check.** *"no view stores state only in the browser"*
   was **stricter than its own clause** (*"No client-side state that dies on
   refresh"*) and would have falsely condemned the density preference, which
   survives a refresh. Reworded to *"no view holds state that does not survive
   a refresh (state persisted in `localStorage` or on the server survives;
   state held only in page memory does not)"*. The clause body did not move.
3. **Freeze 7's self-failure.** The Changelog's quotation of `webapp.py:38-39`
   carried added `**` emphasis, so the contract failed **its own**
   contiguous-substring rule. The emphasis is struck; the quoted span is now
   byte-exact and is still a quotation (the `*"…"*` attribution markers sit
   outside the span). **`webapp.py` was not touched** — fixing a quote by
   editing the prose it cites is the wrong end, and the retargeted probe now
   asserts the source did not acquire the emphasis either.

Plus a dated Changelog entry recording all three.

### Hash, old → new

`sha256`, whole-file bytes, computed exactly as `ledger/checks/_support.py::sha256`
does:

```
contracts/operator-surface.v1.md      7566c75c0b013e6d11946cc7c6a3781b6d70a9a92f945ea988aac238c73103ab
                                   -> f40987524fb47351023700fbad97c9c43d9ddd46aeb2cefd0d3ec08cd71c3edb

contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
                                      (unchanged — re-verified byte-for-byte on this run, not assumed)
```

The custody contract was never opened: the boundary between the two contracts is
a one-way citation, and this amendment touched neither of the two clauses cited
across it.

### Rows re-anchored: 2 — checked, not assumed

Every one of the 35 quote-carrying `OSV1` rows was tested against **both** the
old text (`git show origin/main:contracts/operator-surface.v1.md`) and the new
one, whitespace-collapsed. Exactly two rows quoted text that moved; the other 33
verify byte-identically in both.

| Row | Clause | Old anchor | New anchor | Same clause? |
|---|---|---|---|---|
| `OSV1-005` | Core 4 | *"Literal colour, font, or size in an inline `style=` attribute is a violation; zero are tolerated."* | the widened first sentence, *"…, or in a `<style>` block outside the token module (`webtheme.py`'s token block), is a violation; zero are tolerated."* | yes — same sentence, widened |
| `OSV1-016` | Core 10 | *"no view stores state only in the browser"* | *"no view holds state that does not survive a refresh"* | yes — same machine check, same conjunct |

`OSV1-015` also cites Core 10 and was re-read explicitly: its quote (*"every
adapter call reached from a view passes an explicit limit"*) is a **different
conjunct** of the same check and is byte-identical before and after. No change.

### Disposition changed: 1

`OSV1-033` (Freeze 7) **GAP → CONFORMS**, direction `VIOLATION-MOVEMENT`. This is
the worked example of the flip direction this repo defines locally (§11.1): the
seed probe *pinned* the failing quote, part 3 above corrected it, the pin went
red — and the row moved and the pin was replaced by a real check **in the same
change**. A passing pin would not have been conformance; only the retargeted
probe is.

The retargeted `test_row_osv1_033` asserts, every run: (1) every `*"…"*`
attributed quotation anywhere in the contract either verifies verbatim against
`webapp.py` or is marked as a **speaker's** words by a `literal:` attribution
within the 40 characters before it; (2) the two `webapp.py:37-44` quotations are
still **present** and still verify — enumerated by name, so deleting one cannot
be how the row stays green; (3) `webapp.py` is the only in-repo file the
Changelog cites, so a new `file.py:LINE` citation fails loudly rather than
leaving the probe silently narrow; (4) the `**`-emphasised form is absent from
**both** the contract and `webapp.py`.

**Honest limit, unchanged by the flip:** the contract also quotes Brief A and
Brief B, which live outside this repo (Backlogged 2 quotes *"137 `style=`
occurrences, 134 of them outside `webtheme.py`"*). An in-repo check cannot
verify those and **reports** them as out-of-repo rather than silently passing
them. `CONFORMS` here means *every quotation citing an in-repo file verifies*,
not *every string in this contract has been checked*.

**Work item:** `work_item_pipeline-5r1` was filed at seed for exactly this
correction and is discharged by this change. It is **not** resolved from this
branch — the branch may not write to the live tracker — so it needs closing by
hand.

### The `<style>`-block census — new measurement engine

Part 1 made a defect scoreable, so the ledger had to acquire the instrument that
scores it. `_support.style_blocks_outside_token_module()` finds every `<style>`
block a `src/` module other than **the token module** embeds — resolving CSS
written straight into the tag *and* CSS interpolated from a module-level string
constant, by parsing (never importing). A block it cannot resolve **raises**
rather than being skipped: a census that silently loses a block would understate
the violation, which is the one direction a census must never fail in — the same
rule `inline_style_sites()` already carries.

`style_block_literal_sites()` then classifies each declaration with
**`classify_style` — the same function the inline census uses**, on purpose, so
the two halves of Core 4 are measured identically and one cannot quietly become
stricter than the other.

**Measured on this branch:** exactly **one** `<style>` block outside the token
module — `webtrust.py:256-302` (the `_CSS` constant, embedded at
`webtrust.py:374`) — carrying **40** literal colour/font/size declarations:

```
webtrust.py:258   --ground:#0D0D0C  --raise:#151513  --ink:#F2EEE6  --mid:#A6A199
webtrust.py:259   --quiet:#9C978F   --amber:#D9A253  --rule:#1F1F1D  --rule-hi:#333330
   ...the 8 retired-palette declarations the seed recorded but could not score
webtrust.py:263-300   32 further literal fonts and sizes in the same sheet
   (Georgia / 'Helvetica Neue' stacks, font-size:32px, padding:52px 24px 80px, …)
```

**Honest limit, shared with the inline census:** `classify_style` skips a size
declaration whose value mentions `var(`, so `border:1px solid var(--rule-hi)` is
**not** counted. That under-counts rather than over-counts — the safe direction
for a pin — and the rule is shared between both halves deliberately.

Two rows now measure both halves, **pinned separately** so fixing one is progress
recorded rather than a flip unearned:

* `OSV1-005` (Core 4, **VIOLATION**, unchanged) — 66 inline literal sites **and**
  40 `<style>`-block declarations, with the 8 retired-palette declarations
  asserted by name.
* `OSV1-032` (Freeze 6, **GAP**, unchanged) — Freeze 6's own text did not move
  and its quote still verifies, but the word *"site"* in its second half reads
  through Core 4. The probe now pins both halves, because the plausible failure
  is exactly: migrate all 66 inline sites, see a green inline census, and stamp
  a Freeze gate while a whole page-local stylesheet still hardcodes the retired
  palette.

**The palette itself was not fixed here** — that is `work_item_pipeline-np3`,
and this branch amends the contract and `ledger/` only.

### The density ruling — an open need closed

`OSV1-016`'s seed notes returned a reading to the root: the density toggle
persists `wt-density` in `localStorage`, which **satisfies** Core 10's prose
(*"no client-side state that dies on refresh"* — it survives) while being,
literally, state *"stored only in the browser"* — the machine check's words as
they then stood. Part 2 settles it by aligning the check to its own clause:

| Preference | Under the aligned wording | Evidence |
|---|---|---|
| **density** | **CONFORMANT** | `wt-density` persisted in `localStorage` — `webtheme.py:3859` declares the key, `:3866` reads it, `:3873` writes it. It survives a refresh |
| **theme** | **still a VIOLATION** | `wtSetTheme` (`webapp.py:3503-3508`) persists nothing — no cookie, no `localStorage`, no server round-trip — so it is held only in page memory and dies on the next load |

`OSV1-016` stays **VIOLATION**, pinned on theme only — exactly as the seed probe
was written, *deliberately*, so that a density decision taken later would not
arrive to find the probe already red about it. It now **also** asserts that
density still persists: a row whose notes rule on density must notice if density
stops persisting, rather than leaving a stale ruling in its notes.

### Tallies, before → after

| | Before (SEED) | After (this re-review) |
|---|---:|---:|
| `CONFORMS` | 8 | **9** |
| `VIOLATION` | 5 | 5 |
| `GAP` | 20 | **19** |
| `NOT-ASSERTABLE` | 3 | 3 |
| **Total rows** | 36 | 36 |
| Red rows carrying a work item | 25 | **24** |

**Core-clause sub-tally is unchanged: ten of nineteen Core-carrying rows are
still red** — `OSV1-033` carries Freeze 7, not a Core clause, so Freeze 5's gate
(`OSV1-031`, which asserts exactly 19 Core rows and exactly 10 red) did not move.

### Every other disposition re-verified — checked, not assumed

This branch touches the contract and `ledger/` only (`git diff origin/main
--stat`: `contracts/operator-surface.v1.md`, `ledger/rows.yaml`,
`ledger/reconcile-report.md`, `ledger/checks/_support.py`,
`ledger/checks/test_operator_rows.py`, `ledger/checks/mutation_harness.py`), so
**no row's subject code moved**. Both families' probes were re-run and both
halves of the ledger's honesty re-established:

```
pytest ledger/checks -q      60 passed
make ledger-mutate           proven 53 / 53   (pinning 29/29 · pinning probes covered 24/24 · conformance 24/24)
```

**The mutation denominator moved honestly, 52 → 53, and is not a rounding:**
`OSV1-005` gained a **second** mutation (webtrust.py's page-local `<style>`
block stops declaring its own retired palette — block census 40 → 32), because
the existing one proves the *inline* bucket discriminates and says nothing about
a block; and `OSV1-033`'s mutation was **replaced**, not deleted — the row left
the pinning group, so its `FIXED`-direction counterfactual (*strike the
emphasis*) became meaningless and a `REGRESSION`-direction one (*the emphasis
comes back*) took its place. Pinning-probe coverage therefore falls 25 → 24 and
conformance mutations rise 23 → 24, which is the same row moving between groups.

### Files written by this re-review

| File | Change |
|---|---|
| `contracts/operator-surface.v1.md` | the three owner-ratified parts + a Changelog entry. **Status stays DRAFT** |
| `ledger/rows.yaml` | `OSV1-000` rehashed + re-review notes; `OSV1-005`/`-016` re-anchored; `OSV1-033` flipped GAP → CONFORMS and its `work` ref dropped; notes updated on `-003`, `-005`, `-015`, `-016`, `-032`, `-033` |
| `ledger/checks/_support.py` | the `<style>`-block census engine (block resolution + per-declaration classification), `_CSS_COMMENT` hoisted to be shared |
| `ledger/checks/test_operator_rows.py` | `OSV1-005`/`-032` extended to the block half; `OSV1-016` asserts density persistence; `OSV1-033` retargeted from a pin to a real check |
| `ledger/checks/mutation_harness.py` | one mutation added (`OSV1-005` block half), one replaced (`OSV1-033`, pin → regression direction) |
| `ledger/reconcile-report.md` | this section |

**Not touched, by instruction and by protocol:** `src/`,
`contracts/custody-coordination.v1.md`, `docs/VISION.md`. No PR opened, nothing
merged, and the live service was never contacted.

---

## 1. Rows by disposition

> **SEED snapshot, 2026-09-04 @ `4aaee50`.** Superseded in one cell by the
> re-review above: `OSV1-033` is now `CONFORMS`, so the live tally is 9 CONFORMS
> / 5 VIOLATION / 19 GAP / 3 NOT-ASSERTABLE. Everything else below still stands
> as measured. Kept as written rather than rewritten — it is the record of what
> the seed actually found.

36 rows: one SYNC, 19 carrying Core 1–13, 7 carrying Conformance 1–7, 8
carrying Freeze 1–8, one carrying Reserved 1.

| Disposition | Count | Rows |
|---|---:|---|
| `CONFORMS` | 8 | OSV1-000 (SYNC), -002, -006, -007, -011, -013, -014, -017 |
| `VIOLATION` | 5 | OSV1-001, -005, -009, -015, -016 |
| `GAP` | 20 | OSV1-003, -004, -008, -010, -012, -020…-030, -031, -032, -033, -034 |
| `NOT-ASSERTABLE` | 3 | OSV1-018, -019, -035 |
| `OPEN-PINNED` | 0 | — |
| `EXCLUDED` | 0 | — |
| `DIVERGED` | 0 | illegal here — this team owns both contracts |

**Core-clause sub-tally (what Freeze 5 counts):** of the 19 Core-carrying rows,
7 CONFORMS · 2 NOT-ASSERTABLE · 5 VIOLATION · 5 GAP. **Ten of nineteen are red.**

### 1a. Row by row

| Row | Clause | Disposition | Probe | Evidence (measured 2026-09-04 @ 4aaee50) |
|---|---|---|---|---|
| OSV1-000 | SYNC | CONFORMS | `test_row_osv1_000` | pins `operator-surface.v1.md` `7566c75c…` **and** `custody-coordination.v1.md` `ec4b736f…` (Need 3). `docs/VISION.md` deliberately not double-pinned — `CCV1-000` owns it |
| OSV1-001 | Core 1 | **VIOLATION** | `test_row_osv1_001` | hero = `render_verdict_hero` (webapp.py:4602; widgets.py:637-663 emits eyebrow/verdict/detail, no `meta_row` from L0). Velocity is a chart at webapp.py:4647. KPI strip (webapp.py:4611-4641) carries agents/held/ready/blocked/resolved24h — **no needs-attention count anywhere** |
| OSV1-002 | Core 2 | CONFORMS | `test_row_osv1_002` | token block webtheme.py:109-284 declares exactly `--alarm` `#f59e0b` (:169), `--blocked` `#ef4444` (:172), `--watch` `#9aa8cc` (:186). `--amber`/`--crimson` are aliases *into* the set (:253-254). `--calm-ink` resolves to `--ink-secondary` (neutral) |
| OSV1-003 | Core 2 | GAP | `test_row_osv1_003` | kit not built: `tests/conformance/` absent; zero playwright/selenium/screenshot/axe-core in the repo. Specimen a sweep would catch: webpwa.py:121-122, webtrust.py:258-259 |
| OSV1-004 | Core 3 | GAP | `test_row_osv1_004` | kit not built (`test_tier_a.py` absent). Source shape is encouraging and not credited: webbrowse.py:139-152 maps five statuses to five WORDS; L2 chip renders `status.upper()` (:849-851) |
| OSV1-005 | Core 4 | **VIOLATION** | `test_row_osv1_005` | census re-run by the probe: 137 inline `style=` sites → **66 LITERAL** / 23 COMPUTED / 48 TOKEN. Worst: webpwa.py:121 `background:#0D0D0C;color:#F2EEE6;font:16px …` (retired palette) |
| OSV1-006 | Core 4 | CONFORMS | `test_row_osv1_006` | computed-geometry sites are **exactly** the 23-site register enumerated in the row. Grows → red; shrinks → row and register shrink together |
| OSV1-007 | Core 5 | CONFORMS | `test_row_osv1_007` | route audit re-run by the probe: 30 routes (webapp 23, webbrowse 3, webtrust 4), 22 read-only handlers, **0** reaching a mutating adapter call |
| OSV1-008 | Core 6 | GAP | `test_row_osv1_008` | kit not built. Source: `restoreState` restores exactly `openIds` + `scrollY`; pause CONTROL not restored (server re-renders `aria-pressed="false"`, webapp.py:3549); `aria-live` count = **0** |
| OSV1-009 | Core 7 | **VIOLATION** | `test_row_osv1_009` | luminance re-run by the probe: 54 text pairs, **6 below 4.5:1**, all `--ink-quiet` light (3.09 / 2.93 / 2.72:1 ×2 blocks). Token paints reading copy at chartsvg.py:294 ("No activity in this window") and :461 |
| OSV1-010 | Core 7 | GAP | `test_row_osv1_010` | kit not built; no browser driver in the repo. `--u:44px` and the six breakpoints exist for the sweep to measure |
| OSV1-011 | Core 7 | CONFORMS | `test_row_osv1_011` | exactly ONE `@media (prefers-reduced-motion:reduce)` block, webtheme.py:2162, selector `*,*::before,*::after`, resetting animation/transition/scroll — kernel-level, in the base sheet so it also governs `OBSERVATORY_CSS` |
| OSV1-012 | Core 8 | GAP | `test_row_osv1_012` | kit not built (needs an empty-vs-populated two-render comparison). Empty sentences exist: widgets.py:423,433; webapp.py:2275 (figure is an em-dash, not a `0`); chartsvg.py:295; webbrowse.py:498-503 |
| OSV1-013 | Core 9 | CONFORMS | `test_row_osv1_013` | `dependencies = []`; `web` extra is fastapi/uvicorn/itsdangerous/python-multipart/python-pam/six/cryptography/httpx — no framework, bundler or template engine. No package.json / webpack / vite / rollup / tsconfig |
| OSV1-014 | Core 10 | CONFORMS | `test_row_osv1_014` | no charting library and no drag-and-drop library in the manifest; charts are hand-rolled SVG in `chartsvg.py` |
| OSV1-015 | Core 10 | **VIOLATION** | `test_row_osv1_015` | webbrowse.py:339 `bd.list(status=…, include_resolved=True, limit=0)` in `project_view`; adapter.py:3958-3963 defines `limit=0` as unlimited. L1 polls every 20 s (webbrowse.py:605) |
| OSV1-016 | Core 10 | **VIOLATION** | `test_row_osv1_016` | `wtSetTheme` (webapp.py:3503-3508) sets `data-theme` and nothing else — no cookie, no localStorage; every page is server-rendered `data-theme="dark"` (webtheme.py:3423), so a chosen theme dies on refresh |
| OSV1-017 | Core 11 | CONFORMS | `test_row_osv1_017` | exactly one call site outside `webpush.py`: supervisor.py:156, inside the `if eligible:` branch **after** `bd.release`. Heartbeat push unwired (webpush.py:33-38) |
| OSV1-018 | Core 12 | NOT-ASSERTABLE | — (`kind: none`) | contract self-declares; cadence named in-clause (owner review at each ENCODE gate and before any Freeze stamp) |
| OSV1-019 | Core 13 | NOT-ASSERTABLE | — (`kind: none`) | contract self-declares; no time-to-notice/time-to-act instrument exists; promotion held by Backlogged 6 |
| OSV1-020 | Conformance 1 | GAP | `test_row_osv1_020` | `tests/conformance/` absent |
| OSV1-021 | Conformance 2 | GAP | `test_row_osv1_021` | both named paths absent — the one fixture spanning **both** tiers |
| OSV1-022 | Conformance 3 | GAP | `test_row_osv1_022` | browser kit absent; the swap really is `document.body.innerHTML = doc.body.innerHTML` |
| OSV1-023 | Conformance 4 | GAP | `test_row_osv1_023` | browser kit absent; 430/900/1280 breakpoints present for the sweep |
| OSV1-024 | Conformance 5 | GAP | `test_row_osv1_024` | Tier-A kit absent; its bad half **is** the shipped hero |
| OSV1-025 | Conformance 6 | GAP | `test_row_osv1_025` | Tier-A kit absent; must read this ledger's register, not fork a second census |
| OSV1-026 | Conformance 7 | GAP | `test_row_osv1_026` | Tier-A kit absent |
| OSV1-027 | Freeze 1 | GAP | `test_row_osv1_027` | kit path absent **and** no Makefile/CI target covers `tests/conformance` |
| OSV1-028 | Freeze 2 | GAP | `test_row_osv1_028` | path absent; zero browser-driver references anywhere in the repo |
| OSV1-029 | Freeze 3 | GAP | `test_row_osv1_029` | no Tier-B artifact exists for the orchestrator to re-check (vacuously unmet — rowed *because* vacuous) |
| OSV1-030 | Freeze 4 | GAP | `test_row_osv1_030` | neither kit exists, so no fixture has been demonstrated to discriminate |
| OSV1-031 | Freeze 5 | GAP | `test_row_osv1_031` | reads the ledger itself: 10 of 19 Core-carrying rows are red |
| OSV1-032 | Freeze 6 | GAP | `test_row_osv1_032` | enumerated half **already true** (23 registered); zero-literal half false (66 remain) |
| OSV1-033 | Freeze 7 | GAP | `test_row_osv1_033` | the Changelog quote `"…unclaimed item, **never a count**"` does **not** verify against `webapp.py:38-39` (added markdown emphasis); the other cited quote does |
| OSV1-034 | Freeze 8 | GAP | `test_row_osv1_034` | the Changelog has two entries; neither records a rendered-page look, and 430/900/1280 appear nowhere in it |
| OSV1-035 | Reserved 1 | NOT-ASSERTABLE | — (`kind: none`) | required by ruling Need 4; no probe can observe an external `--json` consumer appearing. Cadence: each ENCODE gate |

---

## 2. SYNC status

`OSV1-000` pins **two** files:

```
contracts/operator-surface.v1.md      7566c75c0b013e6d11946cc7c6a3781b6d70a9a92f945ea988aac238c73103ab
contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
```

The second pin is ruling Need 3's obligation, paid: the boundary between the two
contracts is a one-way citation (operator-surface cites
`contracts/custody-coordination.v1.md Core 8` / `Core 14` by bare id and
restates neither), so the price of leaving the custody contract untouched is
that **a custody amendment must re-review this family too**. `test_row_osv1_000`
asserts the pin set itself, not just the hashes — dropping the custody pin fails
loudly rather than silently narrowing the blast radius.

`docs/VISION.md` is **not** pinned here. It is already pinned by `CCV1-000`
(`f5eb400c…`), and pinning it twice would mean two rows racing to re-hash the
same bytes. Verified at seed: **zero OSV1 rows quote vision text**, so a vision
change re-reviews `CCV1` and reaches no `OSV1` row's reading.

The custody hash recorded here is byte-identical to `CCV1-000`'s, as it must be —
re-computed on this run, not copied.

---

## 3. Coverage tripwires

Run by `pytest ledger/checks`, now resolved **per family** through
`_support.FAMILIES` rather than against one hardcoded contract:

| Tripwire | Result |
|---|---|
| 1 — every Core clause of every contract cited by ≥1 row | **PASS.** Core 1–13 all cited (19 rows). `custody-coordination.v1`'s own coverage unchanged |
| 2 — every quote verifies against **its own** contract's bytes | **PASS.** 35 OSV1 quotes, 0 failures. A row filed under one family but quoting another contract now fails on its own assertion |
| 3a — every assertion ref resolves | **PASS.** 33 probes; each additionally checked to live in *its own family's* module |
| 3b — every probe belongs to a row | **PASS.** 33 = 33 across both modules, with a duplicate-name guard |
| 3c — every `GAP`/`VIOLATION` carries a live `work` ref | **PASS.** All 25 red rows carry one |
| 4 — every probe has a declared mutation | **PASS.** 33/33 |
| 5 — the harness runs and every mutation flips its probe red | **PASS.** 52/52 |

Clause ids: the tripwire now accepts both of this contract's numbering forms —
`### Core 1:` headings and `**Freeze 1:**` bold labels — because
`operator-surface.v1` numbers its Freeze Bar and Reserved namespaces inline.
Zero OSV1 rows needed the `unnumbered` escape hatch (`custody-coordination.v1`
still needs one, for `Conformance: Checks`).

---

## 4. What was actually run (a self-report is not proof)

Every number in this report came from a command executed on this branch. The
commands, and their real output:

```
pytest ledger/checks -q                          60 passed in 1.06s
pytest ledger/checks/test_operator_rows.py -q     33 passed in 0.23s
python -m ledger.checks.mutation_harness          proven 52 / 52, exit 0
ruff check ledger/                                All checks passed!
ruff format --check ledger/                       7 files already formatted
pytest tests/unit -q                              905 passed in 36.22s
```

`tests/unit` was run to show this change did not disturb the existing suite;
`grep -rn ledger tests/` returns nothing, so `tests/` is independent of
`ledger/` by construction, and the run confirms it.

**NOT run, and named rather than implied:** `make test-integration`,
`make test-cli` and `make test-module` need real `bd` plus a dolt server, and
this reconcile was under instruction never to touch the live service. Nothing in
this change reaches those tiers (the diff is `ledger/` only), but that is a
reasoned expectation, not a measurement.

**Timing note, honestly:** the ledger tier is now **1.06s**, up from 0.25s at 24
rows — it crossed the "sub-second" line the Makefile's own comment sets. 0.36s
of that is the mutation harness (tripwire 5) running 52 counterfactuals
in-process. It is still fast enough to be run every time, which is the property
that actually matters, but the target in the Makefile comment is now aspirational
rather than descriptive and should be restated or defended when a third family
lands.

---

## 5. Drift found — in both directions

### 5a. Implementation drifted from the contract (five VIOLATIONs)

The contract is one day old, so "drift" here is mostly the gap the contract was
written to name rather than movement since. Each is filed:

1. **OSV1-001 / Core 1** — the hero is a verdict; velocity is a chart two
   regions lower; the needs-attention count does not exist.
2. **OSV1-005 / Core 4** — 66 inline sites carry a literal colour, font or size
   against a clause that tolerates zero.
3. **OSV1-009 / Core 7** — six declared text pairs sit below the 4.5:1 floor,
   and the token responsible paints real reading copy.
4. **OSV1-015 / Core 10** — the L1 view runs an unbounded query three times a
   minute per open tab.
5. **OSV1-016 / Core 10** — the theme choice is client-side state that dies on
   refresh.

### 5b. The contract drifted from a fixed implementation (the reverse direction)

**One found, and it is Freeze 7 failing against itself (OSV1-033).** The
Changelog quotes `webapp.py:37-44` as *"…unclaimed item, **never a count**"*.
The source carries no markdown emphasis. Under `LEDGER-FORMAT.md` §2's matching
semantics — whitespace collapses, but words, markup and character order are
exact — the contract's own quote is not a contiguous substring of the file it
cites, which is precisely what Freeze 7 demands of every quote in the contract.
Nothing in the repo would have caught it: the ledger verifies *row* quotes
against *contract* bytes; this is the other direction and is unimplemented.

The fix is an **amendment, not an edit** (the contract is owner-ratified), and
it moves the contract's bytes, so it re-triggers `OSV1-000`'s mandatory
full-family re-review. Filed as `work_item_pipeline-5r1`.

### 5c. Silent-fix protection (the direction this ledger adds)

All 25 red rows carry **pinning** probes: they assert the currently-wrong shape,
so a *silent fix* fails exactly as loudly as a regression, with flip direction
`VIOLATION-MOVEMENT` (§11.1's local extension, unchanged). 29 pinning mutations
prove those pins discriminate — see §11.3 below.

---

## 6. The inline-style census and the exemption register

This is ruling Need 2's artifact: the register and its census live **in the
ledger**, never in the contract, so shrinking the register is a convergent
change needing no amendment and no SYNC re-hash. `test_row_osv1_005` and
`test_row_osv1_006` **re-run** the census every ledger run; the numbers below are
the engine's output, not a transcription.

### 6a. Census, per file

| File | LITERAL | COMPUTED | TOKEN | total |
|---|---:|---:|---:|---:|
| `chartsvg.py` | 1 | 3 | 5 | 9 |
| `webapp.py` | 44 | 13 | 20 | 77 |
| `webbrowse.py` | 15 | 0 | 15 | 30 |
| `webpwa.py` | 1 | 0 | 0 | 1 |
| `webtheme.py` | 0 | 3 | 0 | 3 |
| `webtrust.py` | 3 | 0 | 0 | 3 |
| `widgets.py` | 2 | 4 | 8 | 14 |
| **total** | **66** | **23** | **48** | **137** |

Parsed total equals the raw `style="` count (137) and the probe **asserts** that
equality — a parser that silently lost a site would understate the violation,
which is the one direction a census must never fail in. This also independently
re-confirms Brief A's headline number (137 total, 134 outside `webtheme.py`)
against `4aaee50`.

The parser splices Python string-literal concatenation boundaries first, so an
attribute split across adjacent literals reads as one attribute. A newline is
**mandatory** in that splice rule: `600"' if is_today else ""` puts a `"` beside
a `'` — an attribute-close beside a literal-close, not a concatenation — and
allowing same-line adjacency ran two real attributes together (caught and fixed
during this run; both artefacts are gone from the final numbers).

### 6b. Classification rule (encoded in `_support.classify_style`)

- **LITERAL** — a hex/`rgb()`/`hsl()` colour not routed through `var(--token)`,
  **or** a font property with a literal value, **or** a length literal
  (px/rem/em/%…) on a size or spacing property. LITERAL wins over COMPUTED: a
  declaration that interpolates an accent *and* hardcodes a padding is a
  violation, not an exemption.
- **COMPUTED** — the declaration carries an interpolated `{…}` placeholder.
- **TOKEN** — only `var(--token)` values and/or properties that are none of
  colour, font or size.

### 6c. The initial exemption register — 23 sites

Enumerated in full in `OSV1-006`'s notes and asserted as an exact set by
`test_row_osv1_006`:

```
chartsvg.py:268,464,488
webapp.py:1122,1144,1709,1711,1829,1832,2101,2142,2266,2572,3376,4393,4908
webtheme.py:4120,4139,4146
widgets.py:704,831,834,1110
```

An **increase** (a new inline computed site nobody registered) fails the probe
immediately. A **decrease** is convergent: shrink the register in the row and
let the ledger confirm. At **zero**, Backlogged 2's promotion trigger ("no
inline `style=` at all") fires — a named contract event, never a silent win.

### 6d. Two honest limits recorded in the rows, not hidden

1. Six registered sites interpolate a **colour**, not a geometry
   (webapp.py:2142/2266, chartsvg.py:268, widgets.py:704/834/1110). They pass
   Core 4's *literal* test because the value is computed, and several resolve to
   a token — but "a bar width, a chart offset" is the clause's own gloss of what
   the exemption is for. **Returned to the root** (§9, need 3).
2. `webtrust.py:258-259` declares a whole retired palette
   (`--ground:#0D0D0C; --ink:#F2EEE6; --amber:#D9A253`) inside a `<style>`
   **block**, not an inline attribute, so this run did **not** score it as a
   Core 4 violation — the clause's frozen text is scoped to inline `style=`.
   It is the same defect wearing a different tag, and it is the specimen
   Conformance 1's bad half reinstates. **Returned to the root** (§9, need 2).
   **SETTLED 2026-09-04** by the owner-ratified DRAFT true-up #1: Core 4 was
   widened to reach it, and the block is now COUNTED — 40 literal declarations
   in `webtrust.py:256-302`, of which these are 8. See the re-review section
   above.

---

## 7. Items filed

Ten items, all in project `work_tracker`, all lane `eng`, all filed by this
reconcile (checked first: no pre-existing item cited any `OSV1-###` row, so no
duplicates were created).

| Item | Row(s) it closes | One line |
|---|---|---|
| `work_item_pipeline-c1a` | **027** (Freeze 1); remedy for 004, 012, 021ᴬ, 024, 025, 026 | build the Tier-A conformance kit + Makefile target + CI step |
| `work_item_pipeline-qgo` | **028, 029, 030** (Freeze 2/3/4); remedy for 003, 008, 010, 020, 021ᴮ, 022, 023 | build the Tier-B browser kit — pinned chromium, isolated fixture, artifact-emitting, own CI tier. **The biggest item in this seed** |
| `work_item_pipeline-ujy` | **001** (Core 1) | rebuild the L0 hero as fleet velocity + the four counts |
| `work_item_pipeline-np3` | **005** (Core 4), **032** (Freeze 6) | migrate 66 literal inline sites to tokens; replace the retired palettes |
| `work_item_pipeline-sxh` | **009** (Core 7) | fix the below-floor `--ink-quiet` text pairs, or its reading-text call sites |
| `work_item_pipeline-8vv` | **015** (Core 10) | bound the L1 project view's query |
| `work_item_pipeline-dg3` | **016** (Core 10) | persist the theme choice across a refresh |
| `work_item_pipeline-umm` | **031** (Freeze 5) | the aggregate gate — holds until every red Core row closes |
| `work_item_pipeline-5r1` | **033** (Freeze 7) | mechanise contract-quote verification + propose the amendment that corrects the failing quote |
| `work_item_pipeline-eah` | **034** (Freeze 8) | emit the eighteen renderings for the owner's look; draft the Changelog entry the owner ratifies |

### 7a. Dependency edges

`work_item_pipeline-umm` (Freeze 5) is **blocked by** all five VIOLATION items:

```
umm  --blocks--> ujy   (Core 1 hero)
umm  --blocks--> np3   (Core 4 visual truth)
umm  --blocks--> sxh   (Core 7 contrast)
umm  --blocks--> 8vv   (Core 10 unbounded query)
umm  --blocks--> dg3   (Core 10 client-side state)
umm  --relates-to--> c1a, qgo
```

**An honest shortfall, not a design choice.** `umm` should be blocked by the two
kit items as well — five of its ten red rows have no other remedy. It is not:
`work_add`'s `related` parameter had already written `relates-to` edges to `c1a`
and `qgo` when the item was created, and `work_dep` refuses to convert an
existing edge type (it names the remedy: remove then re-add, which is a raw
storage-layer operation this reconcile would not reach around the tools to
perform). Consequence: `umm` is claim-time blocked by five of its seven real
blockers, and the other two are visible as `relates-to`. Recorded here rather
than left to be discovered.

Other edges written at creation: `qgo → c1a`, `ujy → c1a`, `np3 → c1a, qgo`,
`sxh → c1a, qgo`, `8vv → c1a`, `dg3 → c1a, qgo`, `eah → qgo` (all `relates-to`).

---

## 8. Freeze Bar status — FROZEN

**Current reading, 2026-09-05, at the lock**, measured on the branch
`converge/freeze-operator-surface-v1` off `main` @ `d039b32`. The full
condition-by-condition evidence is in the lock section below
(*Lock 2026-09-05 … §L4*); this supersedes the pre-lock reading kept as history
in §8b and the seed reading in §8a.

| Condition | Status |
|---|---|
| Freeze 1 — Tier-A kit exists and runs on every PR | **MET** (OSV1-027) — CI Tier 6; ran here, 41 passed / 1 named xfail |
| Freeze 2 — Tier-B kit, pinned chromium, isolated data, own CI tier | **MET** (OSV1-028) — CI Tier 7; `playwright==1.60.0` / chromium 148.0.7778.0 |
| Freeze 3 — every Tier-B check emits re-checkable artifacts | **MET** (OSV1-029) — the committed recording is re-read by the ledger, not trusted |
| Freeze 4 — every fixture discriminates, demonstrated by running it | **MET** (OSV1-030) — 14 arms, every bad half still biting |
| Freeze 5 — every Core CONFORMS or NOT-ASSERTABLE-with-cadence | **MET** (OSV1-031) — 19 Core rows: 17 CONFORMS + 2 NOT-ASSERTABLE, **0 red**; both cadences now carry a trigger that outlives this stamp (RC-3) |
| Freeze 6 — exemption register complete, no literal sites left | **MET** (OSV1-032) — 8 enumerated, set-equal to the live census; 0 literal, inline and `<style>`-block |
| Freeze 7 — every contract quote verifies against its cited file | **MET** (OSV1-033), with the recorded limit: in-repo quotes proven, out-of-repo brief citations reported unverifiable |
| Freeze 8 — owner's rendered-page look recorded in the Changelog | **MET — owner act, recorded** (OSV1-034, GAP → **CONFORMS**). The owner looked at the three contact sheets and said *"looked"*; the dated Changelog record is the trace. The contract says *"never a machine check"*, and the retargeted probe still only asserts the RECORD |
| Freeze 9 — external PR review | **MET — human act, out-of-repo record**; `.amplifier/converge/operator-surface-freeze9-review.md`, an independent reviewer (not the author), verdict REQUEST CHANGES → approve once RC-1/2/3 land. **No row**: the file lives outside this repository, exactly as Brief A and Brief B do, so no in-repo check can read it |
| Freeze 10 — owner FROZEN stamp | **MET — owner act, recorded**; the dated `2026-09-05 — FROZEN.` Changelog entry carrying the owner's literal words *"Ok, do the freeze"* and *"looked, ratify."* **No row**: a signature has no machine reading, and rowing one would be a fabricated attestation |

**Freeze 1–7 are met by measurement; 8 and 10 are owner acts, recorded; 9 is an
external reviewer's read, recorded.** The three that no check could ever close
were closed the only way they can be — by people — and each left a trace a
later reader can find.

The contract is **FROZEN**. Nothing in this ledger moved it there: the owner
did, in the Changelog. What this ledger did was refuse to let it be stamped
until the conditions actually held, and then re-review every row against the
bytes the stamp changed.

**From here, this contract changes only by a sibling proposal**
(`operator-surface.v2-candidate.md`), never by an in-place edit. Six lower
findings from the Freeze 9 review are deferred to exactly that route: Core 1's
"leads" sentence, Core 4's silence on register GROWTH, Core 5's audit being
narrower than "reaches", the `_oldest_ready_item` dead-function xfail, the
drifted `file:line` citations, and Backlogged triggers 4 and 6 being
unobservable.

### 8a. Seed reading, 2026-09-04 (history — superseded)

Kept verbatim rather than deleted: the point of a ratchet is that the earlier
reading stays readable beside the later one.

| Condition | Status |
|---|---|
| Freeze 1 — Tier-A kit exists and runs on every PR | **NOT MET** (OSV1-027) |
| Freeze 2 — Tier-B kit, pinned chromium, isolated data, own CI tier | **NOT MET** (OSV1-028) |
| Freeze 3 — every Tier-B check emits re-checkable artifacts | **NOT MET** (OSV1-029) |
| Freeze 4 — every fixture discriminates, demonstrated by running it | **NOT MET** (OSV1-030) |
| Freeze 5 — every Core CONFORMS or NOT-ASSERTABLE-with-cadence | **NOT MET** — 10 of 19 red (OSV1-031) |
| Freeze 6 — exemption register complete, no literal sites left | **HALF MET** — 23 enumerated; 66 literal remain (OSV1-032) |
| Freeze 7 — every contract quote verifies against its cited file | **NOT MET** — one quote fails (OSV1-033) |
| Freeze 8 — owner's rendered-page look recorded in the Changelog | **NOT MET** (OSV1-034) |
| Freeze 9 — external PR review | **no row** — see §9, need 5 |
| Freeze 10 — owner FROZEN stamp | **no row** — see §9, need 5 |

The contract stays **DRAFT**. Nothing in this seed moves it.

### 8b. Pre-lock reading, 2026-09-05 on `main` @ `7e43e73` (history — superseded)

Kept verbatim rather than deleted, for the same reason §8a is: this is what the
bar read on the last tree before the owner acted, and the difference between
this table and §8's is exactly the three human acts.

| Condition | Status |
|---|---|
| Freeze 1 — Tier-A kit exists and runs on every PR | **MET** (OSV1-027) — CI Tier 6; ran here, 41 passed / 1 named xfail |
| Freeze 2 — Tier-B kit, pinned chromium, isolated data, own CI tier | **MET** (OSV1-028) — CI Tier 7; `playwright==1.60.0` / chromium 148.0.7778.0; ran here ×2, 89 passed |
| Freeze 3 — every Tier-B check emits re-checkable artifacts | **MET** (OSV1-029) — recording regenerated here and re-read by the ledger |
| Freeze 4 — every fixture discriminates, demonstrated by running it | **MET** (OSV1-030) — 14 arms, every bad half still biting |
| Freeze 5 — every Core CONFORMS or NOT-ASSERTABLE-with-cadence | **MET** (OSV1-031) — 19 Core rows: 17 CONFORMS + 2 NOT-ASSERTABLE, **0 red** |
| Freeze 6 — exemption register complete, no literal sites left | **MET** (OSV1-032) — 8 enumerated, set-equal to the live census; 0 literal, inline and `<style>`-block |
| Freeze 7 — every contract quote verifies against its cited file | **MET** (OSV1-033), with the recorded limit: in-repo quotes proven, out-of-repo brief citations reported unverifiable |
| Freeze 8 — owner's rendered-page look recorded in the Changelog | **NOT MET — human only** (OSV1-034, `work_item_pipeline-eah` open). The contract says *"never a machine check"* |
| Freeze 9 — external PR review | **NOT MET — human only**; no row, no machine reading exists |
| Freeze 10 — owner FROZEN stamp | **NOT MET — human only**; no row |

**Everything a machine can check is green.** The three conditions outstanding
are, by the contract's own construction, acts of people: the owner's look, an
external reviewer's read, and the owner's stamp.

The contract stays **DRAFT**. Nothing in this ledger moves it, and nothing in
this ledger can.

---

## 9. Returned to the root — interpretive needs this reconcile did not decide

Per the reconciler's routing rule: where a call turns on a protocol or contract
reading that the contract text plus `LEDGER-FORMAT.md` do not settle, the need is
stated and returned. **None of the five below changes a disposition** — each was
filed on the half that is red under every candidate reading — but each changes
how much work a row implies, or whether a row should exist.

1. **Does the L0 KPI strip count as part of "the L0 hero region"?** (Core 1 /
   OSV1-001.) Measured: held, blocked and open-ready are present as KPI cards
   directly under the hero; needs-attention is absent everywhere; throughput is
   a chart two regions below. If the strip is part of the hero region, three of
   the four counts already exist and `ujy` is "add one count + move velocity
   up". If it is not, `ujy` is "rebuild the region". *Filed VIOLATION either
   way — the throughput half fails on both readings.*

2. **Does Core 4 reach a `<style>`-block palette, or only inline attributes?**
   Its frozen sentence says "in an inline `style=` attribute"; its title says
   "One source of visual truth". `webtrust.py:258-259` declares a full retired
   palette in a `<style>` block, deliberately not importing `webtheme.CSS`
   (webtrust.py:249-253). This run did **not** score it, and says so in
   OSV1-005's notes. If it should be scored, the census needs a second bucket
   and `np3` grows.
   **SETTLED 2026-09-04 — YES, it reaches.** Owner-ratified DRAFT true-up #1
   widened the clause to *"or in a `<style>` block outside the token module
   (`webtheme.py`'s token block)"*. The census did acquire the second engine,
   and `np3` did grow: 40 literal declarations in `webtrust.py:256-302` now
   count. See the re-review section above.

3. **Does a computed *colour* belong on a computed-*geometry* register?**
   (Core 4 / OSV1-006.) Six of the 23 registered sites interpolate a colour, not
   a geometry. They are listed, never hidden. If they do not belong, OSV1-006 is
   not CONFORMS and six sites move to `np3`'s migration list.

4. **Is the density preference "state stored only in the browser"?** (Core 10 /
   OSV1-016.) `localStorage['wt-density']` **satisfies** Core 10's prose (it
   survives a refresh) while being, literally, the thing the machine check's
   wording forbids. This run pinned **theme only** — red under both readings —
   precisely so a later density ruling is not pre-empted by an already-red probe.
   **SETTLED 2026-09-04 — NO, density CONFORMS.** Owner-ratified DRAFT true-up
   #1 aligned the machine check to its own clause (*"does not survive a
   refresh"*), so persistence in `localStorage` is conformance. Theme is still a
   violation and `OSV1-016` still pins it; the probe now also asserts density
   still persists. See the re-review section above.

5. **Do Freeze 9 and Freeze 10 want ledger rows?** This run rowed Freeze 1–8
   (each has an in-repo byte check) and rowed **no** row for Freeze 9 (external
   PR review) or Freeze 10 (owner FROZEN stamp): both are process events whose
   only in-repo artifact is a Changelog entry, and `assertion.kind: none` would
   force `NOT-ASSERTABLE`, which would be wrong — a `gh` query *can* assert
   Freeze 9, just not in-process. This is a **scope call this reconcile made**;
   if the family should cover all ten, two rows are missing and the coverage
   tripwire should be widened to demand them.

---

## 10. Honest limits of this ledger family

1. **Twenty of 36 rows are red because two files do not exist.** This family
   currently measures far less of the operator surface than it will once the
   kits land. It says so in every one of those rows rather than implying
   coverage it does not have.
2. **Every OSV1 probe is in-process.** No browser, no rendered page, no bd, no
   dolt. Where a clause needs a rendered page, the probe pins the kit's absence
   plus source-level evidence — and source shape is not behaviour. The rows say
   which is which.
3. **Flat token-pair math is necessary, not sufficient** (OSV1-009). The real
   surface puts glass panels with `backdrop-filter` blur over an ambient
   gradient, which lifts perceived background luminance — `webtheme.py:141-152`
   records exactly that. Closing OSV1-009 does not close OSV1-010.
4. **The route audit is static and module-local**, bounded at depth 4
   (OSV1-007). A mutation reached via a callable passed in from another module
   would not be seen. None exists today.
5. **Core 5's machine check is narrower than its prose.** `GET /auth/logout`
   clears a session cookie — session state, not work-tracker state, and it
   reaches no adapter call, so it passes the check as written. The clause's
   wider claim ("it writes only through explicit operator actions, which are
   POST") is not fully asserted by anything.
6. **OSV1-034 can only ever assert that a RECORD exists**, never that the owner
   looked. That gap is irreducible and is why Freeze 8 says "never a machine
   check".
7. **Freeze 7 cannot be fully mechanised in-repo** (OSV1-033). The contract
   cites Brief A and Brief B, which live outside this repo. An in-repo check
   must *report* out-of-repo citations, not silently pass them.
8. **`OSV1-032`'s zero-literal branch is not counterfactually simulable**
   in-memory — it would mean rewriting 66 real sites — so its mutation proves
   the enumerated half only. OSV1-005's own mutation is what proves the LITERAL
   bucket discriminates. Stated in the mutation's own label, so the harness
   report carries it.

---

## 11. Format deviations — additions to §11 for the second family

§11.1's local flip direction `VIOLATION-MOVEMENT` is unchanged and is used by
all 25 pinning rows of this family.

### 11.4 Two families in one `rows.yaml`

`LEDGER-FORMAT.md` §1 permits splitting by contract
(`rows-<seam>.yaml`). This repo keeps **one file with two families**: the
tripwires, the probe/row pairing and the mutation harness all read one parsed
list, and splitting would fork that machinery at two families for no gain. Each
family carries its own `<PREFIX>-000` SYNC row, first within its family; ids
sort so `CCV1` precedes `OSV1`. `rows.yaml`'s header states this.

**Consequence for §2's "SYNC row first" rule:** with two families the SYNC row
is first *within its family*, not first in the file. The integrity tripwire
asserts exactly that, per family. Data for `ledger-format.v1`.

### 11.5 Clause ids from bold labels as well as headings

`operator-surface.v1` numbers its Freeze Bar and Reserved namespaces as
`**Freeze 1:**` / `**Reserved 1:**` inline rather than as `###` headings. Both
are bare numbered identifiers in `LEDGER-FORMAT.md` §2's sense, so the clause-id
tripwire now accepts both forms. No paraphrase and no parenthetical decoration
is accepted in either. Data for `ledger-format.v1`.

### 11.6 Pinning-probe census for this family (Ruling-1 conditions)

| Condition | This family |
|---|---|
| 1 — the pin asserts the CURRENT wrong shape | 25/25 red rows |
| 2 — `notes` carry the "PINNING ROW … a passing probe here is NOT conformance" sentence | 25/25 |
| 3 — flip direction is `VIOLATION-MOVEMENT` | 25/25, asserted by `test_ledger_integrity` |
| 4 — each pinning probe has a fixed-behaviour mutation | 29 mutations over 25 pinning rows, all proven |

### 11.7 Mutation evidence, both families

`python -m ledger.checks.mutation_harness` on this branch:

```
pinning mutations       proven 29 / 29
pinning probes covered  proven 25 / 25
conformance mutations   proven 23 / 23
ALL mutations           proven 52 / 52

UNPROVEN, named with reason
  (none)
```

Two holes were found and closed **by the harness itself** during this run, which
is the harness doing its job rather than a clean first pass:

- `OSV1-005`'s first mutation tokenised only the retired *palette* at
  webpwa.py:121 and left `font:16px`/`padding:32px` — the site stayed LITERAL,
  the count stayed 66, and the probe still passed. Reported as
  *"probe still PASSED under the counterfactual — it does not discriminate"*.
  Fixed by mutating both halves of the site.
- `OSV1-023`'s first mutation anchored on `max-width:430px`, which occurs
  **twice** (two separate `@media` blocks), so `World.replace`'s uniqueness rule
  refused it. Reported as *"mutation could not be applied: anchor occurs 2x"*.
  Retargeted at `1280px`, the only one of the three swept widths declared once.

Harness mechanics extended for two families, all reported here rather than left
as silent behaviour: readers are patched in **every** probe module (not just the
family under test, so a probe reading through a sibling cannot see unmutated
source); `REPO_ROOT` is patched in every probe module that has one;
`_support.rows`' memoised parse is cleared on entry **and** exit, so the one
probe that reads the ledger itself (`OSV1-031`) sees a mutated ledger and no
mutated parse can leak into a later probe; and `World.touch()` was added for the
eleven rows whose counterfactual is simply "the kit file exists".

**On those eleven:** `touch` is a deliberately weak mutation and is labelled as
such in the harness's own docstring. It proves only that a pin notices its named
path appearing — which is exactly what those rows claim and no more. Four of
them (`OSV1-022`, `-023`, `-027`, `-029`) carry a **second** mutation against
their substantive half, so the weak one is never the only evidence.

---

## 12. Files written by this seed

| File | Change |
|---|---|
| `ledger/rows.yaml` | header rewritten for two families; **36 `OSV1-###` rows appended**. No `CCV1` row touched |
| `ledger/checks/test_operator_rows.py` | **new** — 33 probes |
| `ledger/checks/_support.py` | `Family`/`FAMILIES` table + clause-id helpers; paths for the operator modules; three measurement engines (inline-style census, token-pair luminance, route audit) |
| `ledger/checks/test_ledger_integrity.py` | every tripwire resolved per family; probe-module-ownership and duplicate-probe-name guards added |
| `ledger/checks/mutation_harness.py` | multi-module probe resolution and patching; `World.touch()`; ledger-cache clearing; **37 new mutations** |
| `ledger/reconcile-report.md` | this section |

**Not touched, by instruction and by protocol:** `contracts/operator-surface.v1.md`,
`contracts/custody-coordination.v1.md`, `docs/VISION.md`, and anything under
`src/`. No PR opened, nothing merged, and the live service was never contacted.

---

## Re-check 2026-09-05 — operator-surface.v1 after highway hw-operator-surface (waves 1–4)

Standing re-check of the `OSV1-###` family (and, because `pytest ledger/checks`
covers both families, the `CCV1-###` quotes and SYNC row too) against `main`
@ **`7e43e73`** — the head of the four-wave highway that landed PRs #82
(`aec9991`), #83 (`6c2e9fa`), #84 (`065da04`) and #85 (`7e43e73`).

**Every number below was measured on this tree by this re-check.** Nothing is
transcribed from a lane report, an orchestrator summary, or the row it appears
on. Where a figure could only be re-read rather than re-derived (the Tier-B
recording), the run that produced it was executed here, twice, and the result
compared byte for byte against the committed one.

**Outcome in one line:** **zero disposition changes**, zero drift in either
direction, hashes intact, tripwires green — and **Freeze 5 is met by
measurement**, leaving Freeze 8/9/10 (three human acts) as the only conditions
outstanding.

---

### R1. What was actually run (a self-report is not proof)

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed in 1.88s** | every row's quote verifies, every assertion ref resolves, the tripwires hold |
| `make ledger-mutate` | **ALL mutations proven 69 / 69**; `UNPROVEN … (none)` | every probe was watched going red against a counterfactual — none is asserting nothing |
| `make test-conformance-a` | **41 passed, 89 deselected, 1 xfailed in 31.30s** | the Tier-A kit runs on this tree; the one xfail is the named `OSV1-015` residual (§R7) |
| `.venv/bin/python -m pytest -m tier_b tests/conformance/operator_surface/browser -q` | **89 passed in 123.30s**, then **89 passed in 104.27s** | the Tier-B kit runs in a real pinned chromium against a live app, twice |
| `.venv/bin/python -m pytest ledger/checks -q` *against the second run's fresh recording* | **60 passed in 1.90s** | the ledger is green on numbers measured minutes earlier, not only on the committed ones |
| `.venv/bin/ruff check ledger` / `ruff format --check ledger` | `All checks passed!` / `7 files already formatted` | — |

**One named deviation from the instruction's command list.** Tier-B was invoked
as the `test-conformance-b` target's own pytest line rather than through `make
test-conformance-b`, because that target depends on `playwright-install`, which
runs `playwright install --with-deps chromium` — and `--with-deps` was excluded
by instruction (it installs system packages). The browser for the pinned
`playwright 1.60.0` was already present, so nothing was downloaded; the kit's own
`kit.pinned_browser` arm re-asserted the engine from inside the run
(`chromium 148.0.7778.0 / playwright 1.60.0`), and the ledger's `OSV1-028` probe
independently re-read that against `pyproject.toml`'s exact pin. The selection
(`-m tier_b`) and the path are byte-identical to the Makefile recipe.

**Not touched:** both contracts, `docs/VISION.md`, everything under `src/`, and
the live service (no dolt write outside the isolated test fixture, no
`amplifier-work-tracker service *`, none of the reserved ports — the Tier-B app
binds `127.0.0.1:0` and reads the bound port back off the live socket).

---

### R2. Rows by disposition — 36 `OSV1-###` rows, unchanged

| | Count | Change since 2026-09-04 re-review |
|---|---|---|
| CONFORMS | **32** | +23 |
| NOT-ASSERTABLE | **3** | 0 |
| GAP | **1** | −18 |
| VIOLATION | **0** | −5 |

**Core-carrying rows: 19 → 17 CONFORMS + 2 NOT-ASSERTABLE, 0 red.** The single
red row is `OSV1-034` (Freeze 8 — the owner's look), which is human-only by the
contract's own words and carries a live open queue item.

The `CCV1-###` family was re-verified in the same run and is unmoved: 24 rows,
22 CONFORMS / 2 NOT-ASSERTABLE / 0 red.

#### R2.1 Per-row table — id · clause · disposition · what measured it

| Row | Clause | Disposition | What measured it, on this tree |
|---|---|---|---|
| OSV1-000 | (SYNC) | CONFORMS | both contract files re-hashed here: `f4098752…` and `ec4b736f…`, both matching the pin |
| OSV1-001 | Core 1 | CONFORMS | Tier-A `hero.velocity_and_counts` good half, undeferred and passing over the rendered L0; probe re-reads the hero markup in `widgets.py` |
| OSV1-002 | Core 2 | CONFORMS | token-set census: exactly `{--alarm, --blocked, --watch}`, the two alias names resolving *into* the set |
| OSV1-003 | Core 2 | CONFORMS | Tier-B `calm.zero_alarm_pixels` re-read: calm L0 **and** L1 at 0 `--alarm` / 0 `--blocked` in both themes, against 264 `--blocked` px on the genuinely-alarming fixture |
| OSV1-004 | Core 3 | CONFORMS | Tier-A `state.not_colour_only` over rendered L0/L1/L2 of the alarm fixture (0 wordless), cross-read against Tier-B `state.not_colour_only` (`alarm/L1/dark`: 19 status elements, 0 wordless) |
| OSV1-005 | Core 4 | CONFORMS | the inline-style census **re-run in this session**: `LITERAL` **0**; `<style>` blocks outside the token module **0**, literal declarations in them **0** |
| OSV1-006 | Core 4 | CONFORMS | the `COMPUTED` census **re-run here**: 8 sites, set-equal to the register (§R4) |
| OSV1-007 | Core 5 | CONFORMS | the route audit **re-run here**: 30 routes, **0** GET handlers reaching a mutating adapter call |
| OSV1-008 | Core 6 | CONFORMS | Tier-B `swap.survives` re-read on calm L0 **and** L1: scroll, open-`<details>`, pause control and pause flag all preserved; ≥1 tagged live region survives by node identity; announcement present *and* preserved (vacuity guarded) |
| OSV1-009 | Core 7 | CONFORMS | the token-pair luminance engine **re-run here**: 54 text pairs, **0** below 4.5:1; 9 non-text pairs, **0** below 3:1, over all three declared token blocks |
| OSV1-010 | Core 7 | CONFORMS | Tier-B `perception.floors` re-read across all **18** renders: `text_below_floor` 0, `controls_below_44px` 0, `non_text_below_floor` 0, the one enumerated exemption at exactly 1 per L1 render |
| OSV1-011 | Core 7 | CONFORMS | Tier-B `perception.floors` re-read: `running_animations_under_reduced_motion` **0** across all 18 renders, plus the single kernel-level rule in `webtheme.py` |
| OSV1-012 | Core 8 | CONFORMS | Tier-A `calm.keeps_slot` good halves on L0 **and** L1, undeferred and passing against the all-empty fixture |
| OSV1-013 | Core 9 | CONFORMS | manifest + served-asset census: no framework, bundler, template engine or build step |
| OSV1-014 | Core 10 | CONFORMS | dependency-manifest census: no charting, no drag-and-drop library |
| OSV1-015 | Core 10 | CONFORMS | view-reachable `bd.list` census: every call reached from a view carries an explicit finite limit (residual, named: §R7) |
| OSV1-016 | Core 10 | CONFORMS | `THEME_STORAGE_KEY` persistence + the first-paint boot script, and the density preference alongside it |
| OSV1-017 | Core 11 | CONFORMS | push-channel call-site census: exactly one site, inside the reclaim path |
| OSV1-018 | Core 12 | NOT-ASSERTABLE | the contract itself declares "**Machine check:** none"; cadence named in-contract ("owner review of L0/L1/L2 at each ENCODE gate and before any Freeze stamp") |
| OSV1-019 | Core 13 | NOT-ASSERTABLE | same — an outcome measure with no number measured yet; cadence named in-contract |
| OSV1-020 | Conformance 1 | CONFORMS | the three bad halves re-read from the run: 10 531 `--alarm` px (injected chip), 16 681 `--retired_amber` px (reinstated palette), 264 `--blocked` px (real alarming fixture) |
| OSV1-021 | Conformance 2 | CONFORMS | both tiers' halves: Tier-A accessible-name half + Tier-B hue half; the bad half strips 19 chips and reports 11 wordless |
| OSV1-022 | Conformance 3 | CONFORMS | Tier-B `swap.survives` bad halves ran and failed as named (naive replacement: 0 surviving live regions, pause control lost) |
| OSV1-023 | Conformance 4 | CONFORMS | the sweep covers exactly L0/L1/L2 × 430/900/1280 × dark/light (18), and `bad-wide-element` moves the element-level reading while `scroll_width` does not |
| OSV1-024 | Conformance 5 | CONFORMS | kit fixture present with its bad halves, good half **undeferred**, and `OSV1-001` green (record defect in this row's prose: §R6, F1) |
| OSV1-025 | Conformance 6 | CONFORMS | kit fixture present, importing *this* ledger's register, good half **undeferred**, `OSV1-005` green (record defect in this row's prose and its probe docstring: §R6, F1) |
| OSV1-026 | Conformance 7 | CONFORMS | both good halves (L0 and L1) undeferred and passing; both bad halves still asserted |
| OSV1-027 | Freeze 1 | CONFORMS | kit exists at the contract's named path, wired to `make test-conformance-a` **and** CI Tier 6; the kit ran here (41 passed) |
| OSV1-028 | Freeze 2 | CONFORMS | `pyproject.toml`'s exact `playwright==1.60.0` pin re-read and compared against the recording's own engine block; CI Tier 7 present; the kit ran here (89 passed ×2) |
| OSV1-029 | Freeze 3 | CONFORMS | `LAST_RUN.json`'s envelope re-read, and the ledger re-read the **freshly regenerated** recording (60 passed) — never the browser tier's own pass/fail |
| OSV1-030 | Freeze 4 | CONFORMS | all 14 Conformance arms present in the recorded run, each bad-half headline still non-zero — demonstrated by running, not by existing |
| OSV1-031 | Freeze 5 | CONFORMS | the ledger tally itself: 19 Core rows, **0** red, NOT-ASSERTABLE set exactly `{OSV1-018, OSV1-019}` (§R3) |
| OSV1-032 | Freeze 6 | CONFORMS | register enumerated (8) **and** the literal census at 0 on both halves — inline and `<style>`-block |
| OSV1-033 | Freeze 7 | CONFORMS | every attributed in-repo quotation re-verified against the file it cites; out-of-repo brief citations *reported* as unverifiable, not silently passed |
| OSV1-034 | Freeze 8 | **GAP** | the contract's Changelog records no owner look at the rendered pages — `work_item_pipeline-eah`, confirmed **open** in the queue |
| OSV1-035 | Reserved 1 | NOT-ASSERTABLE | namespace held; ungoverned until an outside caller parses `--json` |

---

### R3. The tally that made Freeze 5 true

Freeze 5 asks that *"every Core clause reads CONFORMS in `ledger/`, or is
NOT-ASSERTABLE with its review cadence named here."* At SEED (2026-09-04,
`4aaee50`) **10 of the 19 Core-carrying rows were red**. They went green one at
a time, each flip carried by a real measurement and each retargeting its probe
in the *same* change (the `VIOLATION-MOVEMENT` rule), so no pin was ever left
asserting a shape the tree had already left:

| # | Row | Clause | Item | The measurement that flipped it |
|---|---|---|---|---|
| 1 | OSV1-001 | Core 1 | `…-ujy` | the rebuilt L0 hero: velocity over a **stated** window plus the four counts, in one hero region |
| 2 | OSV1-009 | Core 7 | `…-sxh` | token-pair math: 6 failing text pairs (all `--ink-quiet` in light, across both duplicated light blocks) → **0 of 54** |
| 3 | OSV1-004 | Core 3 | `…-c1a` | rendered L0/L1/L2 of the alarm fixture: **0** status-bearing elements without a word or accessible name |
| 4 | OSV1-015 | Core 10 | `…-8vv` | `webbrowse.py:339`'s `limit=0` (bd's "no limit") replaced by an explicit finite bound |
| 5 | OSV1-016 | Core 10 | `…-dg3` | the theme choice persisted to `localStorage` and resolved in `<head>` before first paint — it now survives a refresh |
| 6 | OSV1-005 | Core 4 | `…-np3` | the literal-style census: **66 → 0** inline sites, and the `<style>`-block half **40 → 0** |
| 7 | OSV1-003 | Core 2 | `…-a1o` | calm L1 `--blocked` pixels **97 → 0** in both themes, while the alarming fixture still paints 264 |
| 8 | OSV1-012 | Core 8 | `…-aad` | empty widgets: L0 1 problem + L1 2 problems → **0 / 0** against the same empty fixture |
| 9 | OSV1-008 | Core 6 | `…-v3m` | body-swap survivals: live region by node identity, pause control, `<details>`, scroll — **1 of 4 → 4 of 4**, on L0 and L1 |
| 10 | OSV1-010 | Core 7 | `…-96f` | rendered floors across 18 renders: **7 failing text nodes → 0** (worst pair 3.13:1 → 4.75:1); L0 controls under 44 px **26 of 34 → 0**; non-text below 3:1 **0** outside one enumerated exemption |

Re-verified here, not taken on the tally's word: **19** Core-carrying rows
exist; **0** carry `GAP` or `VIOLATION`; the NOT-ASSERTABLE set is exactly
`{OSV1-018 (Core 12), OSV1-019 (Core 13)}` — the two clauses the contract
*itself* declares unassertable, each with its cadence named in the contract at
`contracts/operator-surface.v1.md:157`.

`OSV1-031`'s own honest limit stands and is worth repeating: it counts
dispositions, so a dishonest disposition would pass *there* and fail in the row
that carries it. That is why §R2.1 names a measurement for all 19 rather than
citing the tally.

---

### R4. The exemption register — 8 sites, re-measured here

`style_sites_in("COMPUTED")` was re-run in this session and is **set-equal** to
`EXEMPTION_REGISTER` (23 → 8 at the wave-3/4 unions; it did not grow):

| Site | Expression | Purpose |
|---|---|---|
| `webapp.py:1127` | `flex:{n} 1 0` | state-bar segment ratio |
| `webapp.py:1823` | `width:{today_w}px` | throughput bar, today |
| `webapp.py:1826` | `width:{prior_w}px` | throughput bar, prior 6 d |
| `webtheme.py:4379` | `{style}` | axis ruler numeral offset |
| `webtheme.py:4398` | `left:{_grad_x(f):.1f}px` | graduation tick offset |
| `webtheme.py:4405` | `width:{px}px` | age bar length |
| `widgets.py:866` | `width:{pct}%` | status-mix segment (hatched) |
| `widgets.py:868` | `width:{pct}%` | status-mix segment |

Alongside it, re-measured here: `LITERAL` inline sites **0**; `<style>` blocks
outside the token module **0**; literal declarations inside such blocks **0**.
Freeze 6's two conjuncts — *enumerated* and *nothing literal remaining* — both
hold.

---

### R5. The Tier-B recording — provenance and re-measurement

The committed `tests/conformance/operator_surface/browser/LAST_RUN.json`
(sha256 `b1131d1f…`, `recorded_at 2026-09-05T23:46:45Z`) was produced by the
wave-4 union and re-recorded once on each union, as Freeze 3 requires. Its
provenance block:

```
"browser": {"name": "chromium", "version": "148.0.7778.0", "playwright": "1.60.0"}
"schema":  "operator-surface-tier-b/1"
```

**This re-check ran the kit twice more and diffed the result against the
committed file, leaf by leaf.**

| Run | Diff against the committed recording |
|---|---|
| 1 (123.30 s, 89 passed) | 4 × light-theme `calm.zero_alarm_pixels` `watch` buckets (5444→5333, 5237→5155, 5380→5355, 6323→6278); `perception.floors` `calm/L1/430/dark` `text_scored` 178→179; `recorded_at` |
| 2 (104.27 s, 89 passed) | the same 4 `watch` buckets (5444→5358, 5237→5189, 5380→5295, 6323→6329); `recorded_at`. **Nothing else.** |

**Every asserted field was byte-identical in both runs.** The two fields that
moved are both recorded-but-unasserted, and both were checked rather than
assumed:

- **The light-theme `--watch` pixel buckets** — the known ±~200 px wobble.
  Observed deltas here: −111/−82/−25/−45 (run 1) and −86/−48/−85/+6 (run 2), all
  inside that band. Grepped: no probe in `ledger/checks` and no assertion in the
  kit reads a `watch` bucket; the `calm.zero_alarm_pixels` arms assert `alarm`,
  `blocked` and `retired_amber` only.
- **`text_scored` 178 → 179 on `calm/L1/430/dark` (run 1 only)** — investigated,
  because "anything else that moved" is drift until shown otherwise. Diffing the
  full scored-element lists out of the two runs' own artifact directories, the
  entire difference is fixture identity (the per-run random project name and item
  ids) and relative-age text — **plus exactly one structural difference**: the
  freshness meta-row renders **one** text node while the fixture is under a
  minute old (`span.v` = `"just now"`) and **two** once it crosses a minute
  (`span.v` = `"1"` + `span.v-suffix` = `"m ago"`). Run 1 loaded that page ~60 s
  into a full session; the isolated single-test runs (178, three times) and run 2
  (178) loaded it sooner. Historical artifacts on disk show the same denominator
  at 177/177/178/178/179 across the day. It is a session-timing artifact of the
  fixture, not a product change: `text_below_floor` (the field the row asserts)
  was **0** in every run, and `text_scored` has exactly one write site in the kit
  and **zero** readers in `ledger/` or the kit's assertions.

**The committed recording was restored** (`git checkout --` back to
`b1131d1f…`) after the comparison. Re-recording is the union's act, not this
reconcile's; this run's job was to prove the committed numbers reproduce, and
they do.

---

### R6. Drift check — both directions, per row

Checked independently of the suite (a second script, not the ledger's own
helpers), then cross-checked by running the suite:

| Check | Result |
|---|---|
| (a) `contract.quote` byte-verifies (whitespace-collapsed contiguous substring) | **58 / 60 rows verify**; the 2 without a quote are the SYNC rows, which pin by hash instead — correct per `LEDGER-FORMAT.md` §4. No row carries a quote at top level (the malformed shape §2 names) |
| (b) disposition matches what the probe/kit measures **today** | **0 rows would change.** Every probe passes (60/60) *and* every probe was watched going red against its counterfactual (69/69) |
| (c) no CONFORMS row is a "file exists" claim | **0 existence-only probes.** Every probe that calls `_exists()` also asserts something measured; the four rows that could most cheaply fake it (`OSV1-024/-025/-026/-030`) each additionally assert *undeferred good halves* and the disposition of the row they depend on |
| (d) SYNC hashes | `operator-surface.v1.md` `f4098752…`, `custody-coordination.v1.md` `ec4b736f…`, `docs/VISION.md` `f5eb400c…` — **all three match**. No re-review triggered |
| Drift *toward* the contract (un-pinning) | none unaccounted for: the ten Core flips of §R3 each landed with a ratified item and a probe retargeted in the same change. `git diff dfd4b8f..7e43e73 -- contracts/ docs/VISION.md` is **empty** — the four waves moved `src/` and `tests/`, never the contract |
| Drift *away* (regression) | none. No row moved from CONFORMS |
| Red rows carrying a **live** queue ref | 1 of 1 — `OSV1-034` → `work_item_pipeline-eah`, confirmed **open** in `work_tracker` (checked against the tracker, not merely present in YAML) |

#### R6.1 Findings that are *not* disposition drift — reported, not absorbed

**F1 — two rows carry stale pinning prose above a CONFORMS disposition.**
`OSV1-024` and `OSV1-025` both still *open* their notes with "PINNING ROW — …
its GOOD half does not pass … A passing probe here is NOT conformance. Flip
direction VIOLATION-MOVEMENT", and only correct it several paragraphs later
("FLIPPED … 2026-09-05 … runs undeferred and PASSES"). `test_row_osv1_025`'s
docstring summary is stale in the same way ("its GOOD half is still deferred
against OSV1-005") two lines above an assertion that it is **not** deferred.
The dispositions and the assertions are right; the leading prose is wrong, and
it names the *opposite* flip direction from the one the retargeted probes run
in. Scanned the whole family: exactly these two rows and that one docstring.
**Not corrected in this branch** — a prose fix is neither a disposition change
nor drift the ratchet may absorb silently, and this branch's diff is scoped to
this report. Filed as **`work_item_pipeline-lvn`**; the need is returned in §R9.

**F2 — a green row's item is still open.** `OSV1-031` reads CONFORMS while
`work_item_pipeline-umm` ("[ledger] OSV1-031 (Freeze 5) GAP…") remains **open**
in `work_tracker`. Nothing in `LEDGER-FORMAT.md` is violated (a `work` ref is
required for red rows, not forbidden on green ones), but the queue and the
ledger now disagree about whether Freeze 5 is done. Closing another actor's
tracking item is not this reconciler's call — returned in §R9.

**F3 — cosmetic, recorded for completeness.** `OSV1-010` carries `work: null`
while its own notes name `work_item_pipeline-96f`; the three sibling wave-4
flips (`-003`, `-008`, `-012`) kept theirs on the field. Legal either way for a
green row; noted so a later reader does not read the absence as "no item ever
existed".

**Discharged here:** `work_item_pipeline-c1a`'s closing note recorded a residual
— *"reconcile-report.md's SEED narrative still describes pre-kit evidence for
these rows (rows.yaml itself is current)"*. §R2.1 above supersedes it: every one
of the 36 rows now carries the evidence that stands **on `7e43e73`**, beside the
seed narrative rather than in place of it.

---

### R7. Honest limits of this re-check

1. **The `--watch` wobble is real and unasserted.** Four light-theme pixel
   buckets move by up to ~200 px between runs (§R5). No row reads them. If a
   future row ever wants to, it needs a tolerance, not an equality.
2. **The Tier-B recording's denominators are session-timing dependent.**
   `text_scored` differs by one depending on whether the fixture has aged past a
   minute when the page loads (§R5). Asserted fields are stable; denominators
   recorded beside them are not, and should not be turned into pins without a
   frozen clock.
3. **The `.btn.danger` fix is not exercised by the recorded sweep.** The Manage
   drawer is shut on the calm page, so the at-rest sweep never paints that
   control. The lane verified it separately by forcing every `<details>` open;
   that one-off is **not** a committed arm. If a later change opens the drawer by
   default, the existing calm sweep is what catches it — until then this corner
   of `OSV1-003` rests on a measurement nobody re-runs.
4. **Core 12 and Core 13 are NOT-ASSERTABLE by the contract's own words**, not
   by this ledger's convenience. Two of the nineteen Core rows are therefore
   carried by owner review at a named cadence rather than by any check —
   including at the Freeze stamp itself. Freeze 5 admits this explicitly; a
   reader should not mistake "0 red Core rows" for "19 Core clauses under
   machine check". It is 17.
5. **`OSV1-015` carries a residual, and the Tier-A kit still reports it.**
   `test_antigoals_enforced` is `xfail`: `_oldest_ready_item` (`webapp.py:902`,
   the `bd.list` at `:909`) calls `bd.list` with no limit at all. Verified here —
   the function has **no caller in `src/`** (only tests reference it), and Core 10
   scores calls *"reached from a view"*, so the row is CONFORMS honestly; the
   kit's Core 10 reading is source-wide with no reachability analysis, so it
   still sees the call. Deleting the dead function (or teaching the check
   reachability) retires the marker.
6. **Freeze 7 is narrower than its own text.** In-repo quotations are proven
   byte-exact; the contract's citations of out-of-repo briefs are *reported* as
   unverifiable, not verified. `OSV1-033` records this.
7. **A tally gate cannot audit the rows it counts.** `OSV1-031` asserts an
   aggregate; the evidence lives in the nineteen rows under it (§R2.1).
8. **This re-check did not re-derive rows from the contract text.** The contract
   bytes did not move (§R6 (d)), so the seed's derivation stands. A contract
   amendment triggers the full re-review, never a hash bump.

---

### R8. Freeze Bar reading — Freeze 1–10 as written in the contract

Read against `contracts/operator-surface.v1.md:353-375`, condition by
condition, on this tree:

| Condition | Status today | Evidence |
|---|---|---|
| **Freeze 1** — Tier-A kit at the named path, runs on every PR | **MET** | kit present at `tests/conformance/operator_surface/test_tier_a.py`; CI Tier 6 step + `make test-conformance-a`; ran here, 41 passed / 1 named xfail |
| **Freeze 2** — Tier-B kit, pinned chromium, live app, isolated fixture data, own CI tier | **MET** | exact pin `playwright==1.60.0` in `pyproject.toml`, matching the recording's `chromium 148.0.7778.0`; app on `127.0.0.1:0` over the isolated dolt fixture; CI Tier 7; ran here twice, 89 passed each |
| **Freeze 3** — every Tier-B check emits artifacts the orchestrator re-checks; no rendered impression reported as a pass | **MET** | measure→write→read-back→assert throughout (writes ≤ read-backs, checked); `LAST_RUN.json` regenerated here and re-read by the ledger (60 passed); no assertion opens a screenshot |
| **Freeze 4** — every Conformance fixture discriminates, demonstrated by running it | **MET** | all 14 arms present in the recorded run with their bad-half headlines still non-zero; the kits ran here |
| **Freeze 5** — every Core clause CONFORMS, or NOT-ASSERTABLE with cadence named | **MET** | 19 Core rows: 17 CONFORMS + 2 NOT-ASSERTABLE (Core 12, Core 13), cadence named at `:157`; **0 red** (§R3) |
| **Freeze 6** — exemption register complete, no literal colour/font/size site remaining | **MET** | register 8 sites, set-equal to the live census; literal sites 0 inline and 0 in `<style>` blocks (§R4) |
| **Freeze 7** — every quote verified as a contiguous whitespace-collapsed substring of the file it cites | **MET, with the limit at §R7.6** | in-repo quotations verify; out-of-repo brief citations reported unverifiable |
| **Freeze 8** — the owner has looked at rendered L0/L1/L2 at 430/900/1280 in both themes, recorded in the Changelog | **NOT MET — human only** | `OSV1-034` GAP, `work_item_pipeline-eah` open. The contract says this is *"never a machine check"*; no check can close it |
| **Freeze 9** — PR review of the contract by an external reviewer, not its author | **NOT MET — human only** | no row (no machine reading exists); process act |
| **Freeze 10** — owner ratification and "FROZEN" stamp in a dated Changelog entry | **NOT MET — human only** | no row; process act |

**Plainly stated: everything a machine can check is green.** Freeze 1 through 7
are met by measurement on `7e43e73`, and the three that remain — 8, 9, 10 — are
by the contract's own construction acts of people, not of checks. The contract is
**READY FOR THE OWNER'S LOOK AND EXTERNAL REVIEW**.

It remains **DRAFT**. Nothing in this reconcile moves it, and nothing in this
reconcile *can*: the remaining conditions are the owner's look, an external
reviewer's read, and the owner's stamp.

---

### R9. Returned to the root — needs this re-check did not decide

1. **Who fixes the stale pinning prose on `OSV1-024`/`OSV1-025` and
   `test_row_osv1_025`'s docstring (F1), and on what branch?** The correction is
   inside `ledger/`, so it is a reconciler-shaped edit — but it is not a
   disposition change, and this branch's diff was scoped to the report by
   instruction. Filed as `work_item_pipeline-lvn`; a one-word ruling ("fold it
   into the next re-check" / "its own branch") settles it.
2. **Should the reconciler close `work_item_pipeline-umm` now that `OSV1-031`
   is green (F2)?** It is the Freeze-5 tracking item, the row it tracks is
   CONFORMS by measurement, and this report is the evidence — but the item was
   filed by, and is held in the workflow of, the highway that closed it. This
   reconciler files into the queue; it does not close other actors' items
   without a ruling.
3. **Does the `.btn.danger` corner (R7.3) warrant a committed arm?** Adding one
   means opening the drawer in a Tier-B fixture, which is a kit change, not a
   ledger change. Recorded as an honest limit rather than filed, because
   "should the sweep open the drawer" is a conformance-design call.

---

### R10. Files written by this re-check

| File | Change |
|---|---|
| `ledger/reconcile-report.md` | this section (`R1`–`R10`), the new §8 Freeze Bar reading with the seed reading kept as dated history, and a Changelog entry |

**No other file was written.** `ledger/rows.yaml` is byte-unchanged because no
disposition moved; both contracts, `docs/VISION.md` and everything under `src/`
were never opened for writing; `LAST_RUN.json` was regenerated by the two Tier-B
runs and then restored to its committed bytes. One item filed
(`work_item_pipeline-lvn`); no item closed; the live service was never contacted.

---

## Lock 2026-09-05 — operator-surface.v1 FROZEN

The mandatory full re-review that a SYNC-hash change triggers, run because the
contract moved: three owner-ratified pre-lock text fixes, the Freeze 8 record,
and the `**Status:** DRAFT` → `**Status:** FROZEN` stamp.

**Run:** 2026-09-05, branch `converge/freeze-operator-surface-v1`, branched from
`main` @ **`d039b32`**.
**Trigger:** `contracts/operator-surface.v1.md` changed, so `OSV1-000`'s pin
failed. Under `LEDGER-FORMAT.md` sec.4 that mandates a **full ledger re-review,
never a silent hash bump** — this section is that re-review's record.
**Owner's acts, in his own words:** *"looked, ratify."* (Freeze 8, and
ratification of the external reviewer's RC-1/RC-2/RC-3) and *"Ok, do the
freeze"* (Freeze 10).

**Outcome in one line:** **one row re-anchored, one disposition changed, zero
drift in either direction** — and the operator-surface family now carries **no
red row at all**.

---

### L1. What was actually run (a self-report is not proof)

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed** | every row's quote verifies against the NEW bytes, every assertion ref resolves, the tripwires hold |
| `make ledger-mutate` | **ALL mutations proven 69 / 69**; `UNPROVEN … (none)` | every probe was watched going red against a counterfactual — including `OSV1-034`'s retargeted one |
| `make test-conformance-a` | **41 passed, 89 deselected, 1 xfailed** | the Tier-A kit still runs green on this tree; the one xfail is the named `OSV1-015` residual, unchanged |
| `.venv/bin/ruff check ledger` / `ruff format --check ledger` | `All checks passed!` / `7 files already formatted` | — |

**Tier-B was deliberately NOT re-run, and that is stated rather than glossed.**
`git diff origin/main --name-only -- src tests` is **empty** on this branch: no
product byte and no kit byte moved, so the committed recording
(`browser/LAST_RUN.json`, chromium 148.0.7778.0 / playwright 1.60.0) is still a
recording *of this tree*, and every Tier-B-derived row re-reads exactly the
numbers it read at `d039b32`. Re-running the browser tier would have produced
the same numbers against the same code; it would not have made any row's
reading more true. What DID change is text a browser cannot see.

### L2. What changed in the contract — three fixes, one record, one stamp

The three fixes are the external reviewer's RC-1, RC-2 and RC-3 (Freeze 9,
`.amplifier/converge/operator-surface-freeze9-review.md`, verdict **REQUEST
CHANGES → approve once landed**), each ratified by the owner before the stamp.
All three are text; none required re-running a kit.

**RC-1 — Core 5 said something false, and a lock would have made it expensive.**

```
was:  No `GET` route mutates state. The surface may poll itself aggressively;
      it writes only through explicit operator actions, which are `POST`.
now:  No `GET` handler reaches a mutating adapter call; the surface may poll
      itself aggressively and writes work-tracker state only through explicit
      operator actions, which are `POST`. The one named exception:
      `GET /auth/logout` clears the session cookie.
```

`GET /auth/logout` issues `resp.delete_cookie(...)`. That is a state change on a
GET, so the clause promised strictly more than `reads.never_write` tests — and
the gap was recorded only in `OSV1-007`'s notes, which do not travel with a
locked clause. The clause now states what the check asserts, scopes the write
claim to *work-tracker* state, and names the exception. The machine-check
sentence was tightened so it no longer restates the clause verbatim; **what
`reads.never_write` asserts did not move** (the route audit is byte-identical,
and its measurement — 30 routes, 22 read-only, 0 reaching a mutating adapter
call — re-ran unchanged).

**RC-2 — two Conformance bad halves did not fail for the reason they named.**
Freeze 4 requires a bad half that "fails against the defect it names,
demonstrated by running it". Three halves named a defect the kit does not
measure:

| | was | now | why |
|---|---|---|---|
| **C1 Bad** | "reported as alarm-coloured pixels" | "reported as pixels of a hue outside the token set" (+ the reason) | measured `retired_amber: 16681`, `alarm: 0`. `#D9A253` is too far from `--alarm` to classify as one; the sweep counts it in a third bucket the contract never named |
| **C3 Bad** | "loses all four … offset zero, the disclosure closed, the pause flag cleared, and a fresh live region" | "the open disclosure closes and every tagged live region is replaced by a fresh node (chromium preserves scroll and the pause flag by itself; a reflowing replacement loses scroll too)" | measured `scroll_preserved: true`, `pause_flag_preserved: true`. Only the disclosure and live-region *node identity* actually move; the kit needed a second arm (`bad-naive-replacement-reflow`) to discriminate scroll at all |
| **C4 Good/Bad** | `scrollWidth == clientWidth` / "emits `scrollWidth > clientWidth`" | "no element's border box extends past `clientWidth`" / "that element extends past `clientWidth`" | `html`/`body` carry `overflow-x: clip`, so a 900px element at 430px moves `scrollWidth` not at all (`scroll_width_moved: false`) and the kit asserts `elements_beyond_viewport_moved`. The reviewer added the half the ledger had missed: the **Good** half inherited the same defect, since `scrollWidth == clientWidth` is satisfiable by *clipping* the overflow rather than preventing it |

**RC-3 — the two NOT-ASSERTABLE cadences expired at the stamp.** Freeze 5
admits a clause without a check only "with its review cadence named here", and
both named one — but both named *authoring-phase* events. Core 12: "at each
ENCODE gate and before any Freeze stamp". Core 13: "at each ENCODE gate". After
this stamp there is no further ENCODE gate and no further Freeze stamp, so the
only two Core clauses carried by a human would have had **no recurring
trigger**. Each now appends one that outlives the lock: *"and at each
`ledger/reconcile-report.md` re-check."*

**The Freeze 8 record and the FROZEN stamp.** Three dated Changelog entries were
added, newest first: the FROZEN stamp (Freeze 10, carrying the owner's literal
words and the proposal-only rule that now governs the file), the Freeze 8 record
(the owner's look, marked in the entry itself as *"ratification input, never a
machine check"*), and true-up #2 (the three fixes above). `**Status:** DRAFT`
became `**Status:** FROZEN`.

**Six lower findings were deliberately NOT taken here.** Core 1's "leads"
sentence, Core 4's silence on register *growth*, Core 5's audit being narrower
than "reaches", the `_oldest_ready_item` dead-function xfail, the drifted
`file:line` citations, and Backlogged triggers 4 and 6 being unobservable. Each
is a post-lock proposal against `operator-surface.v2-candidate.md`. The
reviewer explicitly did not block on them, and taking them at the stamp would
have meant landing unratified edits under an owner ratification that named
three.

### L3. Hash, rows re-anchored, disposition changed

**Hash, old → new** (`sha256`, whole-file bytes, computed exactly as
`ledger/checks/_support.py::sha256` does):

```
contracts/operator-surface.v1.md      f40987524fb47351023700fbad97c9c43d9ddd46aeb2cefd0d3ec08cd71c3edb
                                   -> a467be2adca763734fdfb5aace44108ebb21a3d7f5c1663bf82d5eb95ee54c52

contracts/custody-coordination.v1.md  ec4b736f8d6dca4ee3c29b6df8397a9d7b51d2eadd76965854e898924f529e1a
                                      (unchanged — re-verified byte-for-byte on this run, not assumed)
```

**Rows re-anchored: 1 — checked, not assumed.** All 36 `OSV1-###` rows were
walked; each of the 35 quote-carrying ones had its quote collapsed and tested
against BOTH the old (`origin/main`) and the new contract text.

| Row | Clause | Was | Now |
|---|---|---|---|
| `OSV1-007` | Core 5 | *"No GET route mutates state."* — the sentence RC-1 replaced | the clause's new normative sentences, ending *"GET /auth/logout clears the session cookie"*; same clause |

**The other 34 verify byte-identically in both texts** — and the three groups a
reader would expect to have broken are worth naming, because they did not:

* `OSV1-020` / `OSV1-022` / `OSV1-023` quote Conformance 1/3/4's
  `**Test location:**` lines, which RC-2 never touched; the probes anchoring on
  contract prose (`OSV1-020`'s good half, `OSV1-021`'s bad half) anchor on text
  RC-2 also left alone.
* `OSV1-018` / `OSV1-019` quote the Core 12/13 **machine-check** sentences, not
  the `**Reviewed at cadence:**` lines RC-3 edited.
* `OSV1-033` (Freeze 7) re-ran green against the three NEW Changelog entries:
  no new `file.py:LINE` citation was introduced, the two `webapp.py:37-44`
  quotations are still present and still verify, and no new `*"…"*` attributed
  quotation was added — the owner's words are recorded as plain quotations
  citing no file, which is what they are.

**Their NOTES were re-reviewed and corrected anyway.** A surviving quote is not
a re-review: `OSV1-020`, `OSV1-022` and `OSV1-023` all carried notes describing
clause text that moved, and `OSV1-018`/`OSV1-019` carried cadences that RC-3
extended. All five now say what the clause says.

**Two "honest limit" paragraphs are now IN the contract**, and their rows say so
rather than continuing to report a gap that no longer exists:

* `OSV1-007` honest limit 1 — the `GET /auth/logout` cookie clear. The clause
  now names it; **clause text and check agree as of true-up #2**. Honest limit
  2 (the static, module-local, depth-4 audit) is unchanged and still a limit.
* `OSV1-023` "A FUTURE AMENDMENT MAY WANT THIS" — the `scrollWidth` wording.
  The amendment was taken; **clause text and check agree as of true-up #2**.
  Both paragraphs are kept, not deleted: they are the measurement that earned
  the amendment.

**Disposition changed: 1.**

| Row | Was | Now | Direction |
|---|---|---|---|
| `OSV1-034` (Freeze 8) | **GAP** | **CONFORMS** | `VIOLATION-MOVEMENT` |

The pin asserted the ABSENCE of the record — "the Changelog mentions none of
430, 900, 1280". The owner looked at the eighteen captures from the pinned
browser run, presented as three per-level contact sheets, and said *"looked"*;
the owner-ratified stamp recorded it. **The pin went red the way a pin is meant
to, and the probe was retargeted in the same change**: it now asserts that the
Changelog carries a **dated** Freeze 8 record naming L0, L1, L2, 430, 900, 1280
and both themes, each element enumerated separately so a record that quietly
drops one fails rather than passing on a partial look. Its mutation flipped
direction with it — from the FIXED counterfactual ("a Changelog entry records
the look") to the REGRESSION one ("that record is deleted from a locked
Changelog") — so the denominator stayed 69/69 honestly rather than by rounding.

**The docstring's honest limit is kept verbatim, because the flip does not
soften it:** the probe asserts that a RECORD EXISTS, never that the owner
looked. Freeze 8 says *"never a machine check"* for exactly that reason.

**Tally, before → after:** 32 CONFORMS / 3 NOT-ASSERTABLE / 1 GAP / 0 VIOLATION
→ **33 / 3 / 0 / 0**. Freeze 5's Core sub-tally is unmoved (19 Core rows: 17
CONFORMS + 2 NOT-ASSERTABLE, 0 red) — `OSV1-034` is a Freeze row, not a Core
one. The `CCV1-###` family is untouched at 22 CONFORMS / 2 NOT-ASSERTABLE.

**No row was created for the FROZEN status, for Freeze 9, or for Freeze 10.**
FROZEN is a fact about the contract's lifecycle, not a clause. Freeze 9's record
lives outside this repository (`.amplifier/converge/`, where Brief A and Brief B
also live), so no in-repo check can read it. Freeze 10 is a signature, which has
no machine reading at all. Rowing any of the three would have meant inventing an
assertion — and `OSV1-035` was checked rather than assumed: it is **Reserved 1**
(`--json` shapes), not a Freeze row, and `OSV1-036` does not exist.

**Every other disposition re-verified against the tree, not assumed.** This
branch changes the contract and `ledger/` only, so no row's subject code moved;
every probe re-ran green and every probe's discriminating power was re-confirmed
(§L1).

### L4. Freeze Bar reading at the lock — Freeze 1–10 as written in the contract

Read condition by condition against `contracts/operator-surface.v1.md`'s own
Freeze Bar. The condition-by-condition table lives at **§8**; this lock is what
put it there, and the pre-lock reading it replaced is kept as §8b. In summary:
**1–7 met by measurement, 8 and 10 owner acts recorded in the Changelog, 9 an
external reviewer's read recorded in a file.** All ten are met.

The distinction §8 keeps and this section restates, because it is the whole
reason the bar has ten conditions and not seven: 8, 9 and 10 are **not** things
this ledger closed. It could not, and it says so. What it did was hold them open
— visibly, on a row and in a table — until people closed them.

### L5. Honest limits of this lock

1. **Freeze 9's record is out-of-repo.** `.amplifier/converge/operator-surface-freeze9-review.md`
   is not committed here, so no probe can verify it exists, that its author was
   independent, or that its verdict says what §8 reports. This is the same limit
   `OSV1-033` already reports for Brief A and Brief B, and it is reported rather
   than papered over with a row that would assert a path and call it a review.
2. **Freeze 8 remains a record, not an attestation.** Retargeting `OSV1-034`
   changed which byte fact is true, not what a byte fact can prove.
3. **Tier-B was not re-run on this branch** (§L1). Justified by an empty
   `src`/`tests` diff, not by convenience — but "the numbers would be the same"
   is an inference from that diff, not a fresh measurement.
4. **The six deferred findings are real defects in a now-locked text.** They are
   cheap to fix as proposals and were not blocked on by the reviewer, but the
   text is locked with them in it, and that cost was accepted knowingly rather
   than discovered later.
5. **`work_item_pipeline-eah` is discharged but not closed.** This branch may not
   write to the live tracker, so the item stays open in the queue and needs
   closing by hand; the row keeps its `work` ref rather than dropping it, so the
   open item is visible rather than orphaned. `work_item_pipeline-lvn` and
   `work_item_pipeline-umm` remain open from the previous re-check, untouched
   here.

### L6. Files written by this lock

| File | Change |
|---|---|
| `contracts/operator-surface.v1.md` | RC-1/RC-2/RC-3 text fixes, three Changelog entries, `**Status:** DRAFT` → `**Status:** FROZEN` |
| `ledger/rows.yaml` | `OSV1-000` rehashed + full-re-review notes; `OSV1-007` re-anchored; `OSV1-034` GAP → CONFORMS with a retargeted probe ref; notes trued up on `OSV1-007`, `-018`, `-019`, `-020`, `-022`, `-023`, `-034` |
| `ledger/checks/test_operator_rows.py` | `test_row_osv1_034` retargeted from the absence-pin to the record check, honest-limit docstring kept |
| `ledger/checks/mutation_harness.py` | `OSV1-034`'s mutation flipped from FIXED to REGRESSION direction |
| `ledger/reconcile-report.md` | this section (`L1`–`L6`), the new §8 FROZEN reading with the pre-lock reading kept as §8b, and a Changelog entry |

**No other file was written.** No `src/` byte, no `tests/` byte, no
`docs/VISION.md` byte and no `contracts/custody-coordination.v1.md` byte was
touched; `LAST_RUN.json` was neither regenerated nor edited; the live service
was never contacted. No item was filed and none closed.

## Amendment 2026-09-06 — operator-surface v2 applied

The mandatory full re-review that a SYNC-hash change triggers, run because the
FROZEN contract moved: the six owner-ratified corrections in
`contracts/operator-surface.v2-candidate.md`, plus one dated Changelog entry.

**Run:** 2026-09-06, branch `lane/apply-v2`, branched from `main` @ **`37fba54`**.
**Trigger:** `contracts/operator-surface.v1.md` changed, so `OSV1-000`'s pin
failed. Under `LEDGER-FORMAT.md` sec.4 that mandates a **full ledger re-review,
never a silent hash bump** — this section is that re-review's record.
**Owner's act, in his own word:** *"Ratified"* — the owner ratified the sibling
proposal as written, all six changes, no edits requested. The stamp is on the
proposal itself (`Ratified by owner — 2026-09-06, literal word "Ratified".`),
which is what let the write through: `hooks-candidate-guard` refuses an
in-place edit of a locked contract unless a sibling `*.vN-candidate.md` names
that contract in its `target:` field AND carries the ratified stamp. The
candidate was stamped FIRST, then the contract was edited. **The guard was
never bypassed** — no `bash`, no `sed -i`, no emergency-unlock token. This is
the escape hatch working exactly as designed.

**Outcome in one line:** **zero rows re-anchored, zero dispositions changed,
zero drift in either direction** — the amendment is six text corrections that
bring the contract into agreement with machinery that did not move.

---

### A1. What was actually run (a self-report is not proof)

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed** | every row's quote verifies against the NEW bytes, every assertion ref resolves, the tripwires hold, `OSV1-000`'s pin matches |
| `make ledger-mutate` | **ALL mutations proven 69 / 69**; `UNPROVEN … (none)` | every probe was watched going red against a counterfactual; the denominator did not move because no probe was retargeted and no row flipped |
| `make test-conformance-a` | **41 passed, 89 deselected, 1 xfailed** (0 failed, 0 xpassed) | the Tier-A kit still runs green; the one xfail is the named `OSV1-015` residual, unchanged |
| `.venv/bin/ruff check ledger` / `ruff format --check ledger` | `All checks passed!` / `7 files already formatted` | — |

**Tier-B was deliberately NOT re-run, for the same reason as the lock.**
`git diff origin/main --name-only -- src tests` is **empty** on this branch, so
the committed recording (`browser/LAST_RUN.json`, chromium 148.0.7778.0 /
playwright 1.60.0) is still a recording *of this tree*, and every Tier-B-derived
row re-reads exactly the numbers it read at `37fba54`. What changed is text a
browser cannot see.

### A2. What changed in the contract — six corrections, one Changelog entry

Every one is a defect an **independent review of the LOCKED text** found and
named (Freeze 9, `.amplifier/converge/operator-surface-freeze9-review.md`:
pass-1 findings 4, 6, 7, 8, 9 and pass-2 note 1) — not a preference. Five make
the contract say what the machinery already does; the sixth repairs triggers
that cannot fire. Each was verified as a byte-exact, uniquely-occurring
substring of the locked file before it was edited.

**Change 1 — Core 1 promised a judgment nothing asserted.** The clause's second
sentence ("Observability leads the page") is precisely the "leads" judgment
Core 12 declares undecidable by any check, and `hero.velocity_and_counts`
reaches presence only. The sentence is the owner's ratified intent, so it was
routed, not dropped:

```
was:  **Machine check:** `hero.velocity_and_counts` — … and each of the four
      named counts.
now:  … and each of the four named counts. The check reaches presence only;
      "leads" is not decided by it.
      + **Reviewed at cadence:** the "leads" sentence is the judgment Core 12
        names NOT-ASSERTABLE; it is carried by the same owner review of
        L0/L1/L2, at each `ledger/reconcile-report.md` re-check.
```

**Change 2 — Core 4 stated the rule for shrinking the exemption register and
was silent on growth.** The growth rule existed and was enforced, but lived only
in `OSV1-006`'s notes — the same defect class the reviewer used to block RC-1
before the lock ("a ledger note does not travel with a locked clause"). One
appended sentence: *"Growth is not convergent: a new inline computed-geometry
site absent from the register fails the check loudly, and adding it to the
register is a deliberate, recorded act, never a silent one."*

**Change 3 — Core 5's machine-check line under-described its own audit, twice.**
"asserting the clause's first sentence" names a sentence with two halves and
asserts only the first; and "reaches" became load-bearing in the clause at RC-1
while the audit's bound was stated nowhere. The line now names the predicate
inline and the bound: static, module-local, name-matched against the adapter's
write verbs, bounded at depth 4, `_support.py:746-800` — and says plainly it
does not reach the second promise. `OSV1-007`'s honest limit 2 now travels with
the contract. Re-measured here: **30 routes, 22 read-only, 0 reaching a
mutating adapter call**, and `route_audit()` does span lines 746–800 (`return
audited` is 800).

**Change 4 — "ENCODE gate" was used four times and defined nowhere,** which
fails the contract's own "a non-engineer could understand it" bar. Core 12's
cadence now defines it at first use — *"the authoring checkpoint at which the
owner reads and ratifies drafted contract text, the event this contract's
2026-09-04 Changelog entries record"* — and Core 13's points at that definition.
Both machine-check lines are untouched; both clauses stay NOT-ASSERTABLE.

**Change 5 — Core 2's evidence pointers had drifted +42 lines.** Freeze 7 binds
quotations, not pointers, so the contract did not lie by its own bar — but it
misled every reader who followed the citation. Re-anchored onto the same bytes,
verified at both ends against the contract's seed commit `4aaee50`:

| pointer | at `4aaee50` (when written) | at `37fba54` (today) |
|---|---|---|
| webtheme.py:169 | `  --alarm:#f59e0b;` | line 211, same bytes |
| webtheme.py:188 | `  --watch-ink-on-surface:#d6def2;` | line 230, same bytes |
| webtheme.py:1338 | `   marker + bold weight, never a bespoke third hue. */` | line 1430, same bytes |

**Change 6 — two Backlogged triggers could not fire, and one figure was three
orders of magnitude stale.** B4 fired on "the first reclaim the owner *missed*
on screen" — by construction unobservable; it now fires on the owner
**reporting** a reclaim they did not see. B6 fired on "the first
alarm-to-acknowledgement measurement exists", which nothing in this repo
produces and which Core 13 itself says has never been measured; it now fires on
an interval **recorded by any means**, including the owner timing one by hand.
Neither is easier in substance — both still need the real event — they are
simply now observable. B2's Brief A quotation was **not** overwritten: it is a
verbatim citation of an out-of-repo Phase-0 document, and rewriting the numbers
inside the quotation marks would turn a true citation into a fabricated one. It
is preserved byte-for-byte, dated *"at Phase 0"*, with this tree's measurement
added beside it: **0 literal, 8 computed-geometry sites on the register**.

### A3. The full re-review — 36 rows walked, 0 re-anchored

`OSV1-000` rehashed for the operator contract only:
`a467be2adca763734fdfb5aace44108ebb21a3d7f5c1663bf82d5eb95ee54c52` →
`a1f304b11b17e6864298e68ba050d8781112545d4ea45d1a4e35ccd88bdc4d2f`.
`contracts/custody-coordination.v1.md` re-hashed byte-for-byte on this run and
still `ec4b736f…` — the boundary is a one-way citation, so the custody text was
never opened.

**Zero rows re-anchored, and that was measured rather than trusted.** The
proposal predicted none; the check run here collapsed BOTH the old
(`origin/main`) and the new contract text and tested all **35** quote-carrying
rows against each. Every quote verifies byte-identically in **both** texts.
That is the shape of the amendment: each change edits a machine-check, cadence
or evidence line, or appends *after* the sentence a row quotes.

**Zero dispositions changed.** Tally **33 CONFORMS / 3 NOT-ASSERTABLE / 0 GAP /
0 VIOLATION**, unchanged. No clause changed tier, so Freeze 5's reading does
not move: 19 Core-carrying rows, 17 CONFORMS + 2 NOT-ASSERTABLE, zero red.

**A surviving quote is not a re-review, so twelve rows' notes were walked** and
each carries a dated `v2 amendment applied 2026-09-06:` line:

| row | clause | what the re-review found |
|---|---|---|
| `OSV1-001` | Core 1 | clause body byte-identical; the "leads" gap this row never covered is now routed to a named cadence |
| `OSV1-002` / `-003` | Core 2 | evidence pointers only; this row's own `webtheme.py:169/172/186` measurements stay correct **as of `4aaee50`**, and the same declarations now sit at `:211/:214/:228` |
| `OSV1-005` | Core 4 | quote is sentence 1, appended sentence follows sentence 3; census re-run — 55 inline sites, 47 TOKEN / 8 COMPUTED / 0 literal, 0 `<style>`-block literals |
| `OSV1-006` | Core 4 | **this row's INCREASE rule moved into the clause**; register unchanged at the same 8 expressions |
| `OSV1-007` | Core 5 | **honest limit 2 moved into the contract**; `route_audit()` and the probe untouched; 30/22/0 re-measured |
| `OSV1-018` | Core 12 | cadence gained the "ENCODE gate" definition, and now also carries Core 1's "leads" sentence |
| `OSV1-019` | Core 13 | cadence points at Core 12's definition; its promotion route (Backlogged 6) can now actually fire |
| `OSV1-031` | Freeze 5 | re-verified: no tier changed, both NOT-ASSERTABLE cadences still named and now more locatable |
| `OSV1-032` | Freeze 6 | both conjuncts re-measured; Backlogged 2's evidence now carries this row's current figure |
| `OSV1-033` | Freeze 7 | **the amendment's named trap, and it was avoided** — see A4 |
| `OSV1-035` | Reserved 1 | its cadence rests on "each ENCODE gate", a term that is now defined |

### A4. The trap that was named in advance, and how it was avoided

`test_row_osv1_033` asserts the **Changelog** cites exactly one in-repo file:
`cited == {"webapp.py"}`, where a citation is any backticked
`` `<file>.py:<line>` `` inside the `## Changelog` section. A ratifying entry
that wrote `` `webtheme.py:211-230` `` in backticks would have taken `OSV1-033`
red on a bookkeeping detail while nothing was actually wrong. The entry
therefore describes Change 5 in prose and carries no `file.py:LINE` citation at
all. Re-measured after the write, the Changelog's cited set is exactly
`{webapp.py}`; the two `webapp.py:37-44` quotations are untouched and still
verify. Core 2's re-anchored evidence line is outside the Changelog and carries
no backticks, so it was never in this probe's reach.

### A5. Honest limits and residuals of this amendment

1. **`__init__.py:711` is still a dead pointer.** Backlogged 4's own citation
   points into a file that is 9 lines long. It was deliberately left out of this
   amendment: repairing it needs a ruling on what it was meant to point at, and
   guessing a pointer is how the Change 5 defect was created in the first place.
   **Returned as a need.**
2. **The candidate's `**Status:**` line still reads `PROPOSED — awaiting the
   owner's word`** while the file now carries the owner's ratified stamp. The
   amendment brief scoped the candidate edit to the stamp line only, so that
   line was not touched. Named here rather than fixed silently.
3. **Two source-side findings remain open, both named in the proposal's "Not in
   this proposal" list:** deleting the dead `_oldest_ready_item` (which would
   retire `test_antigoals_enforced`'s `xfail(strict=True)` and restore Core 10's
   unbounded-query conjunct), and kit docstrings still quoting pre-RC-2 wording.
   Neither is contract text; neither was touched here.
4. **`DESIGN-SYSTEM.md`'s pointers on Core 2's evidence line were not
   re-measured.** That file is out-of-repo; nothing here can verify it, and this
   amendment does not pretend otherwise.

### A6. Files written by this amendment

| File | Change |
|---|---|
| `contracts/operator-surface.v2-candidate.md` | the owner's ratified stamp, on the file's own designated stamp line — nothing else |
| `contracts/operator-surface.v1.md` | the six ratified changes (nine hunks), each byte-exact from the candidate, plus one dated Changelog entry |
| `ledger/rows.yaml` | `OSV1-000` rehashed + full-re-review notes; dated `v2 amendment applied` lines on `OSV1-001`, `-002`, `-003`, `-005`, `-006`, `-007`, `-018`, `-019`, `-031`, `-032`, `-033`, `-035` |
| `ledger/reconcile-report.md` | this section (`A1`–`A6`) and a Changelog entry |

**No other file was written.** `ledger/checks/` was NOT touched — no row needed
re-anchoring, so no probe needed retargeting. No `src/` byte, no `tests/` byte,
no `docs/VISION.md` byte and no `contracts/custody-coordination.v1.md` byte was
touched; `LAST_RUN.json` was neither regenerated nor edited; the live service
was never contacted. No item was filed and none closed.

## 2026-09-06 zhv

- **Core 10's last residual is closed by deletion, not by argument.**
  `work_item_pipeline-zhv` deleted the dead `webapp._oldest_ready_item`
  (webapp.py:902–917, 16 lines, zero callers, an uncapped `bd.list`), so
  `OSV1-015` no longer holds CONFORMS partly by a reachability argument;
  `make test-conformance-a` went **41 passed / 1 xfailed → 42 passed / 0
  xfailed / 0 XPASS / 0 failed**, the Tier-A good half `test_antigoals_enforced`
  now runs undeferred, and **neither conformance kit carries a deferral**.
  Disposition unchanged (CONFORMS). `test_row_osv1_015`'s two exemption
  assertions are replaced by a stronger, name-free source-wide census
  (`all_listing_calls()`: every listing call in the three route modules carries
  an explicit finite limit — 4 of 4 measured); `OSV1-006`'s three webapp.py
  register pins re-measured −16 (1127/1823/1826 → 1111/1807/1810), same eight
  sites, register did not grow. Tier-B kit docstrings for Conformance 1 Bad,
  3 Bad and 4 Good+Bad re-quoted to the post-RC-2 contract text (docstrings
  only; no assertion changed). Residual, not fixed here and out of this lane's
  scope: `OSV1-030`'s notes still say Tier-A's `test_antigoals_enforced` is
  "the one remaining deferral in either kit" — true when written, false as of
  this line.

## Re-check 2026-09-06 — custody-coordination.v1 Freeze Bar reading

The pre-lock evidence run for `contracts/custody-coordination.v1.md` (Status
**DRAFT**). This section produces the evidence; it does **not** produce the lock.
The lock is the owner's word plus a separate one-write edit, exactly as
`operator-surface.v1`'s was.

**Run:** 2026-09-06, branch `lane/custody-freeze-prep`, branched from `main` @
**`86cd375`** (`HEAD` and `origin/main` identical at start of run).
**Trigger:** none — no hash moved. This is a **scheduled pre-lock re-check**, run
because the owner intends to lock the contract next and a lock must not rest on a
remembered audit.
**Ledger before:** 24 CCV1 rows = 22 CONFORMS / 2 NOT-ASSERTABLE / 0 GAP / 0 VIOLATION.
**Ledger after:** **unchanged** — 22 CONFORMS / 2 NOT-ASSERTABLE / 0 GAP / 0 VIOLATION.
**Dispositions changed: 0. Quotes re-anchored: 0. Rows edited: 1 (a title, `CCV1-009` — §C2).**

**Outcome in one line:** **everything a machine can check is green**, in both
directions; the three conditions still open are the two human ones (Freeze 8, Freeze 9)
and one owner word on Freeze 2 — plus seven **pre-lock candidates** in the contract's
own text (§C4), listed here and deliberately **not** fixed.

---

### C1. What was actually run (a self-report is not proof)

Every figure below was produced on this tree in this lane. Nothing is transcribed from
a previous section.

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed** in 2.20s (re-run after §C2's one-row edit: **60 passed** in 2.12s) | every row's quote verifies against the contract bytes, every assertion ref resolves, both `-000` SYNC pins match, the coverage tripwires hold |
| `make ledger-mutate` | **ALL mutations proven 69 / 69**; `UNPROVEN, named with reason (none)` | every probe was watched going red against a counterfactual — the probes still discriminate, they are not passing vacuously |
| `.venv/bin/python -m pytest modules/tool-work-tracker/tests -q` | **127 passed**, 0 failed, 0 xfailed, 0 skipped, in 629.55s (0:10:29) | Freeze 3 / 4 / 5's behavioural half at the **agent seam**: Conformance Fixtures 2, 3 and 4, against real `bd` + this suite's own isolated dolt server |
| `.venv/bin/python -m pytest -m integration tests/integration/test_phantom_conflict_recovery.py tests/integration/test_post_reclaim_fence.py tests/integration/test_resolve_fence.py tests/integration/test_directed_claim.py -q` | **20 passed** in 67.90s | Conformance Fixture 1 (4), the post-reclaim fence at the **adapter** (5), the integrator half (4), and the directed-claim atomicity + refusal-specificity cites (7) |
| `.venv/bin/python -m pytest tests/unit/test_custody.py tests/unit/test_custody_dead_holder.py tests/unit/test_supervisor.py -q` | **67 passed** in 0.41s | the liveness/TTL/sweep cites behind `CCV1-002`, `CCV1-006` and `CCV1-007` |
| `.venv/bin/ruff check ledger` / `ruff format --check ledger` | `All checks passed!` / `7 files already formatted` | — |

**Environment.** `bd` **1.1.2** (`20e493e56`) and `dolt` both on `PATH`, so nothing
skipped for a missing binary — a suite that skips is not a suite that passed. Every
`bd`-touching run used the per-session **isolated** dolt server
(`tests/_dolt_isolation.py`); the shared server at `:3308` was never contacted and no
live service was touched.

**Not re-run, and why.** `make test-conformance-a` / `-b` (the operator-surface kits)
and the remaining root tiers: `git diff origin/main --name-only -- src tests` is
**empty** on this branch. Nothing executable moved, so those recordings still describe
this tree; re-running them would spend a browser launch to re-read the same numbers.

---

### C2. Drift found — both directions, all 24 CCV1 rows

Four checks, run over every row, independently of the probes that also run them.

**(a) Every `contract.quote` byte-verifies. 23 / 23.** Each quote whitespace-collapsed
and tested as a contiguous substring of the collapsed
`contracts/custody-coordination.v1.md` (the SYNC row `CCV1-000` carries hashes, not a
quote). **Zero failures.** Recomputed in this lane with its own script, not merely
delegated to `test_every_row_quote_verifies_against_its_own_contract_bytes` — which
also passes.

**(b) Disposition matches what the probe MEASURES. 24 / 24, with one row's TITLE
corrected.** All 22 CONFORMS rows were walked against their probe or their cited tests;
each disposition is what the assertion actually establishes. The two NOT-ASSERTABLE rows
(`CCV1-018` Core 13, `CCV1-019` NOT-ASSERTABLE 1) carry justifications and the contract
itself declares both unassertable. **One real drift, and it was drift in the ledger, not
in the code:**

> **`CCV1-009` — title corrected.** The title read, verbatim, *"a post-reclaim close is
> not fenced -- the fence is gated on status held"*. That is the **VIOLATION this row was
> seeded with on 2026-09-01**, left standing after `work_item_pipeline-dn4` closed it and
> the disposition flipped to CONFORMS. The row's one-line summary therefore asserted the
> exact opposite of its own disposition, its own probe (`test_row_ccv1_009` asserts the
> identity-keyed fence **exists** outside the `status == "held"` gate) and its own measured
> fixtures. New title: *"a post-reclaim close IS fenced -- the fence is keyed on custody
> identity, not status"*. A dated paragraph recording the correction was appended to the
> row's notes.
>
> **Why nothing caught it:** no probe, no tripwire and no mutation reads `title` — `grep`
> for `title` in `ledger/checks/` returns **zero** hits. The ledger was green with the
> stale title, which is precisely why a human re-read was needed. **No disposition
> changed; no probe changed; the tally did not move.**
>
> The one other place the old wording survives — §11's *"Residual 2 — a live
> `VIOLATION-MOVEMENT` event, unhandled"* note, which quotes the strict `xfail` reason
> *"a post-reclaim close is not fenced … PRODUCT defect … not fixed here"* — is
> deliberately left as written: it is a dated record of what was true then, and the marker
> it describes was itself removed by PR #71 (`ea233a7`), which today's **0 xfailed** module
> run confirms.

**(c) No CONFORMS row is a "file exists" claim. Walked one by one.** Every one of the 15
probe-backed CONFORMS rows carries at least one substantive content assertion —
whitespace-collapsed source shape (`CCV1-003`, `-004`, `-011`, `-012`, `-013`, `-015`,
`-017`), agent-facing prose pinned in **both** directions, present *and* absent
(`CCV1-005`, `-008`, `-016`), Makefile/CI text (`CCV1-021`, `-022`), a content hash
(`CCV1-000`), or the fence's exact source shape plus its refusal wording (`CCV1-009`).
Two rows use an `.exists()` call as a **supplement** to those assertions (`CCV1-009`
part 3/4, `CCV1-022` part 4), never as the whole claim. The seven `indexed` rows cite
23 named test functions, every one of which resolves **and was executed green today**
(§C1).

> **One honest limit, named rather than hidden.** In `test_row_ccv1_023`, the half that
> covers **Conformance Fixture 1** is `fixture_1.exists()` and nothing more — no
> assertion about that file's contents. It is not a hollow row: the same file's contents
> are asserted by `CCV1-010` and `CCV1-014`, which index **four** named test functions
> inside it, all four run green today. But read alone, `CCV1-023`'s Fixture-1 half is an
> existence check. Fixtures 2, 3 and 4 in the same probe go further (per-fixture
> good/bad pair counts, plus an AST scan proving no half is `xfail`/`skip`).
> **Smallest fix, if the owner wants it closed:** give Fixture 1 the same treatment —
> assert it carries ≥ 2 separately-named tests. Not done here (it edits `ledger/checks/`,
> outside this lane's scope).

**(d) `CCV1-000` SYNC hash matches. Recomputed, not assumed.**

```
contracts/custody-coordination.v1.md  pinned ec4b736f8d6dca4e…  observed ec4b736f8d6dca4e…  MATCH
docs/VISION.md                        pinned f5eb400c79211d90…  observed f5eb400c79211d90…  MATCH
```

No hash moved, so **no full-ledger re-review was triggered** by §4 of `LEDGER-FORMAT.md`.
This section is a scheduled re-check, which is a weaker trigger and says so.

**Drift toward the contract, silently: none found.** No row reads red while the code has
quietly been fixed — there are no red rows left in this family to be silently fixed. The
only remaining drift of that shape was `CCV1-009`'s title, above, which is the mirror
case: a row reading red in *prose* while its disposition, probe and fixtures all read
green.

---

### C3. Freeze Bar reading — Freeze 1 through Freeze 9

One paragraph each, against the contract's own nine conditions.

**Freeze 1 — Residual issues resolved or Backlogged. MET BY MEASUREMENT.** The clause
names three: D-1, D-2, D-5. **D-1** (Core 3 — a failed `take_custody` left the item held
with no custody record) is **resolved** by `work_item_pipeline-aih`; `CCV1-003` is
CONFORMS, its probe asserts all three separable parts of the compensation (the failing arm
routes to it, the compensation releases *and* verifies by its own read-back, and a
compensating release that itself fails stays loud), and its two behavioural fixtures —
`modules/tool-work-tracker/tests/test_custody_atomic.py::test_failed_take_custody_releases_the_claim_back_to_ready`
and `::test_failed_take_custody_then_failed_release_says_the_item_may_still_be_held` — ran
inside today's 127-passed module suite. **D-2** (Core 7 — post-reclaim close unfenced) is **resolved** by
`work_item_pipeline-dn4`; `CCV1-009` is CONFORMS and was measured on both layers today —
`tests/integration/test_post_reclaim_fence.py` (5 tests: the fence after a real reap, the
fence after the bare release that sweep makes, the integrator half, the live-holder half,
the already-landed-close half) inside the 20-passed run, and Fixture 2's three
`test_fixture2_*` tests inside the 127. **D-5** (Core 11 — a landed write reported as a
failure) is **resolved**; `CCV1-014` indexes three named tests in
`test_phantom_conflict_recovery.py`, all three green today. For completeness, the two
residuals Freeze 1 does *not* name: **D-3** (Incident C, `held_stale`) was fixed in PR #63
and is out of this contract's scope by the SEED's own adjudication; **D-4**'s conflict half
was discharged at SEED. **D-6** is Freeze 2's subject, below. **Nothing here is waiting on
a person** — but see Freeze 2 for the one word that is.

**Freeze 2 — D-6 recovery verb designed and implemented. MET BY MEASUREMENT; ONE OWNER
WORD OUTSTANDING.** **The verb is `work_release`** — not `work_reopen`, and not the new
`work_custody_clear` Backlog 3 offered as its other option. Backlog 3's proposal reads
*"`work_custody_clear` **or extended semantics on `work_release`**"*; the second branch is
what shipped. `Beads.release` now reads the item's status **before** any write and returns
`already_closed` having written nothing, and the tool seam's `unclaim` clears the session's
own custody latch in-process — so the D-6 wedge (a session whose close already landed while
it still believes it holds the item) recovers with no restart, no human, and **without
reopening the closed item**, which Backlog 3 itself calls "dangerous". Its tests, all green
today: at the adapter,
`tests/integration/test_phantom_conflict_recovery.py::test_release_on_an_already_resolved_item_writes_nothing_and_reports_already_closed`
(`CCV1-010`'s indexed cite); at the agent seam,
`modules/tool-work-tracker/tests/test_conformance_fixtures.py::test_fixture3_release_of_an_already_closed_held_item_clears_the_latch`,
whose BAD half asserts the item's snapshot is **byte-identical** afterwards (so a write
that happened to land on the same status is caught too) and whose tail proves the session
can claim again immediately; plus
`modules/tool-work-tracker/tests/test_phantom_conflict_recovery.py::test_unclaim_recovers_a_session_wedged_on_an_already_closed_item`.
**Human-only residue:** Backlog 3 still stands in the contract as a Backlogged clause with
an unfired trigger. Whether the shipped `work_release` semantics **discharge** Freeze 2 or
merely **defer** it with approval is a word only the owner can say. The SEED asked this same
question on 2026-09-01 and it has not been answered since.

**Freeze 3 — All four Conformance fixtures implemented, passing, and executable via
`make test`. MET BY MEASUREMENT.** All four exist as discriminating good/bad pairs and all
four ran green today. **Fixture 1** (conflicted-but-landed close):
`tests/integration/test_phantom_conflict_recovery.py`, 4 tests, inside today's 20-passed
run — plus an unnamed-by-the-contract tool-seam twin,
`modules/tool-work-tracker/tests/test_phantom_conflict_recovery.py` (2 tests), inside the
127 (see §C4-6). **Fixture 2** (post-reclaim close fence): three `test_fixture2_*` in
`modules/tool-work-tracker/tests/test_conformance_fixtures.py`, plus the adapter-layer
`tests/integration/test_post_reclaim_fence.py` (5). **Fixture 3** (in-process recovery
after reclaim): three `test_fixture3_*`. **Fixture 4** (single-hold): four
`test_fixture4_*`. **Nothing is quietly disabled** — `test_row_ccv1_023` part 4 walks the
fixture file's AST for any `xfail`/`skip`/`skipif` decorator and found none, and the run
itself reported **0 xfailed, 0 skipped**. **Executable via `make test`**: the `test` target
runs `pytest tests ledger/checks` **and** `pytest modules/tool-work-tracker/tests` as two
deliberately non-fail-fast invocations, and CI runs the same as Tier 2 / Tier 4 / Tier 5.

**Freeze 4 — All check functions implemented and passing. MET ON SUBJECTS; NOT MET ON
NAMES.** This is the one condition whose reading changes the answer, so both are stated.
**On subjects: green.** Each of the five named checks has its subject asserted by machinery
that runs in CI, and every one of those assertions was executed green today —
`check_claim_atomic` → Core 1 → `CCV1-001`'s three `test_directed_claim.py` tests;
`check_custody_fresh_survives` → Core 2 → `CCV1-002`'s five unit tests;
`check_readback_verified` → Core 10 → `CCV1-012` + `CCV1-013` probes and
`test_phantom_conflict_recovery.py`'s three read-back tests; `check_fenced_close` → Core 7
→ `CCV1-009`'s probe, `test_post_reclaim_fence.py` (5) and Fixture 2 (3);
`check_single_hold` → Core 12 → `CCV1-017`'s probe and Fixture 4 (4). **On names: two of
five exist.** `check_claim_atomic` (`src/amplifier_work_tracker/contract.py:158`) and
`check_custody_fresh_survives` (`:644`) are real functions in `doctor`'s registry.
`check_readback_verified`, `check_fenced_close` and `check_single_hold` **do not exist
anywhere in this repository** under those names — `grep -rn` returns hits only in the
contract itself and in this report. And the two that do exist run **only** under
`amplifier-work-tracker doctor`, which **CI does not run at all** (checked:
`.github/workflows/ci.yml` has no `doctor` step). This is pre-lock candidate §C4-2/§C4-3.

**Freeze 5 — Test suite importable and run as part of CI. MET BY MEASUREMENT (as the
ledger reads it).** `CCV1-022` is CONFORMS and its probe asserts all four halves of the
wiring — the editable install (`-e "modules/tool-work-tracker[dev]"` in **both** `make venv`
and CI's setup step), the `test-module` target, `make test`'s aggregation of it, and the CI
"Tier 5 -- tool module tests" step — plus that the suite it wires in still exists. Measured
today rather than inferred: **127 passed, 0 failed, 0 xfailed, 0 skipped** in 629.55s against
real `bd` 1.1.2 and an isolated dolt server. **Literal-text caveat:** the clause's own glob,
`tests/test_*.py`, matches **zero** files in this repository (`ls tests/test_*.py` → *No such
file or directory*); the tests live in `tests/unit/` (44), `tests/integration/` (29),
`tests/cli/` (9) and `modules/tool-work-tracker/tests/` (20). The ledger reads the clause as
being about the tool-module suite, which is the reading that makes it a real Freeze blocker —
but that reading is the ledger's, not the contract's. Pre-lock candidate §C4-4.

**Freeze 6 — Every Core clause verified against actual code. MET BY MEASUREMENT.** Every
Core clause is cited by at least one row (the coverage tripwire
`test_every_core_clause_of_every_contract_is_cited_by_at_least_one_row` enforces this and
passes), and every row's assertion resolves and ran today. Per clause:

| Clause | Row(s) | Assertion that verifies it against code | Ran today |
|---|---|---|---|
| Core 1 | `CCV1-001` | indexed → `tests/integration/test_directed_claim.py` ×3 | ✅ in 20 |
| Core 2 | `CCV1-002` | indexed → `tests/unit/test_custody.py` ×3, `test_custody_dead_holder.py` ×2 | ✅ in 67 |
| Core 3 | `CCV1-003` | probe `test_row_ccv1_003` — 4 source-shape assertions on the compensation | ✅ in 60 |
| Core 4 | `CCV1-004`, `CCV1-005` | probes — the one-strike mechanism's source shape; both agent docs pinned present **and** absent | ✅ in 60 |
| Core 5 | `CCV1-006` | indexed → `tests/unit/test_custody.py` ×3 | ✅ in 67 |
| Core 6 | `CCV1-007`, `CCV1-008` | indexed → `tests/unit/test_supervisor.py` ×4; probe pinning both docs' sweep prose | ✅ in 67 / 60 |
| Core 7 | `CCV1-009` | probe — the identity fence outside the `status == "held"` gate, its `FencedError`, its refusal wording, and the mechanism pin | ✅ in 60 (+ 5 + 3 behavioural) |
| Core 8 | `CCV1-010` | indexed → `tests/integration/test_phantom_conflict_recovery.py` ×1 | ✅ in 20 |
| Core 9 | `CCV1-011` | probe — renew's holder+generation fence, the monotonic increment, `take_custody`'s assignee fence | ✅ in 60 |
| Core 10 | `CCV1-012`, `CCV1-013` | probes — `release`'s verify-before-success; both claim paths returning the read-back, never `Item.from_beads` | ✅ in 60 |
| Core 11 | `CCV1-014`, `CCV1-015`, `CCV1-016` | indexed → `tests/integration/test_phantom_conflict_recovery.py` ×3; probe over the **closed list** of 14 item-level write verbs; probe over both prose surfaces | ✅ in 20 / 60 |
| Core 12 | `CCV1-017` | probe — the single-hold refusal, by name, before any `bd` call | ✅ in 60 (+ 4 behavioural) |
| Core 13 | `CCV1-018` | **NOT-ASSERTABLE**, with justification; the contract declares it so itself | n/a |
| Core 14 | `CCV1-020` | indexed → `tests/integration/test_directed_claim.py` ×4 | ✅ in 20 |
| NOT-ASSERTABLE 1 | `CCV1-019` | **NOT-ASSERTABLE**, self-declaring, with justification | n/a |

**Freeze 7 — Every quote a contiguous, whitespace-collapsed substring. MET BY
MEASUREMENT, AND MECHANIZED.** 23 / 23 quote-carrying rows verify (§C2a), enforced on every
run by `test_every_row_quote_verifies_against_its_own_contract_bytes` and recomputed
independently here. The check is family-resolved: a row is verified against the contract it
*names*, never against whichever contract happens to be first in the file.

**Freeze 8 — PR review by an external reviewer. NOT MET. NOT THIS LANE.** This condition
is human- or agent-**independent** by construction: a reviewer who is not the author. This
lane authored part of what would be reviewed, so it cannot discharge it, and does not try.
The precedent is `operator-surface.v1`'s own Freeze 9: an independent reviewer produced
`.amplifier/converge/operator-surface-freeze9-review.md`, returned **REQUEST CHANGES**, and
three owner-ratified pre-lock fixes (RC-1/2/3) landed before the FROZEN stamp. **§C4 below is
what that reviewer should be pointed at first** — seven candidates found by this re-check,
every one a defect in the contract's own text rather than in the machinery.

**Freeze 9 — Owner ratification and signature. NOT MET. OWNER ONLY.** Downstream of
Freeze 8 by the contract's own ordering, and of the one outstanding word on Freeze 2.

**Stated plainly: everything a machine can check is green.** 60 / 60 ledger probes;
69 / 69 mutations proven with none unproven; 127 module tests; 20 custody integration
tests; 67 custody unit tests; zero red rows; zero `xfail`; zero `skip`; both SYNC hashes
matching; every quote verifying; every Core clause covered. **Nothing mechanical stands
between this contract and FROZEN.** What stands between them is one owner word on Freeze 2,
an external review (Freeze 8), the owner's stamp (Freeze 9), and whatever that review
decides to do with §C4.

---

### C4. Pre-lock candidates — LISTED, NOT FIXED

Seven defects in the contract's **own text**, found by this re-check. The contract is
DRAFT, so an edit is permitted in principle — and is deliberately **not** made here. The
precedent is exact: `operator-surface.v1`'s pre-lock fixes (RC-1/2/3) were the **owner's**
call, taken **after** the external review, not the reconciler's. Each candidate below
carries its measurement and the **smallest** fix that would close it.

**C4-1 — Core 1's machine-check parenthetical is false on this tree, twice, and points at a
section that does not exist.** Current text (`:17`): *"both must pass; skipped under
`--quick` in CI due to Freeze Bar dependencies (see §Freeze Blockers)"*. Measured: (i) CI
never runs `doctor` at all, with or without `--quick` — `.github/workflows/ci.yml` has no
`doctor` step; (ii) `--quick` skips those two checks for **speed**, not for Freeze Bar
dependencies — `contract.py`'s own comment says *"they are the two slowest checks by a wide
margin"*; (iii) there is **no** `§Freeze Blockers` section in this contract — the section is
`## Freeze Bar`. *Smallest fix:* delete the clause from `;` onward, leaving *"both must
pass."*

**C4-2 — Nine of the fourteen machine-check ids the contract names do not exist.** The
contract names 14 ids across its Core clauses. Five are real entries in `doctor`'s registry
(`src/amplifier_work_tracker/contract.py`): `claim.atomic`, `claim.directed_atomic`,
`custody.fresh_survives`, `custody.idle_not_exempt`, `custody.fenced`. **Nine are not
anywhere in the repository:** `claim.custody_indivisible` (Core 3), `custody.one_strike`
(Core 4), `sweep.required_and_scheduled` (Core 6 — the contract itself annotates this one
"(Backlogged: …)"), `fence.close_post_reclaim` (Core 7), `recovery.discoverable` (Core 8),
`write.readback_verified` (Core 10), `write.honest_failure` (Core 11), `session.single_hold`
(Core 12), `claim.error_specificity` (Core 14). Core 7's is the sharpest case, and it is
sharper than a spelling mistake: the registry *does* carry a close fence, `resolve.fenced`,
but reading it shows it stages a **takeover** (holder A releases, holder B claims, A wakes
and closes) — so it never reaches the **released-but-not-yet-re-claimed** state Core 7
explicitly names as the case it covers. Renaming `fence.close_post_reclaim` to
`resolve.fenced` would therefore make the contract point at a check narrower than its own
clause; the assertion that really covers both halves is `CCV1-009`'s probe plus
`tests/integration/test_post_reclaim_fence.py`. *Smallest fix:*
re-label each absent id with the assertion that actually carries the clause (the ledger row
and its probe/cites, as tabulated in Freeze 6 above), or state inline that the id names an
intended check not yet in the registry. Nine unresolvable ids in a locked contract are nine
pointers a future reader will try to run and cannot.

**C4-3 — the Conformance `Checks` list names three functions that do not exist.** Of
`check_claim_atomic()`, `check_custody_fresh_survives()`, `check_readback_verified()`,
`check_fenced_close()` and `check_single_hold()`, only the first two are real; the other
three return no hits outside the contract. The same paragraph also says these are
*"implemented as test functions in `ledger/checks/`"* — the two that exist live in
`src/amplifier_work_tracker/contract.py`, not in `ledger/checks/`. *Smallest fix:* re-point
the list at the real assertions (Freeze 6's table is the mapping) and correct the location
sentence. See also §C4-2 — these two candidates are the same defect at two grains, and one
fix could close both.

**C4-4 — Freeze 5's glob matches nothing.** *"Test suite (`tests/test_*.py`) is importable
and run as part of CI"*. `ls tests/test_*.py` → *No such file or directory*. *Smallest fix:*
name what the clause actually means — `modules/tool-work-tracker/tests/` is the suite whose
absence made this a Freeze blocker, and `CCV1-022` already reads it that way.

**C4-5 — Conformance 1 and 2 still say "Bad behavior (current)".** Both fixtures describe
their bad half as **current** (`:183`, `:197`). Neither is current: Conformance 1's
unread-back conflict was fixed in PR #63 and Conformance 2's status-gated fence by
`work_item_pipeline-dn4`, both measured green today. Conformance 3 and 4 say plainly *"Bad
behavior:"* with no qualifier, so the inconsistency is visible inside one section. This is
also the exact class of statement the **owner-ratified 2026-09-03 amendment struck from every
Core clause** — conformance status lives in the ledger only — and it survived there.
*Smallest fix:* delete the two `(current)` qualifiers, matching Conformance 3 and 4.

**C4-6 — Conformance 1's Verification describes the tool seam; its Test location names only
the adapter.** The Verification reads *"Call `work_resolve(id)` … then call
`work_list(item_id=id)`"* — agent-seam verbs — while the only Test location it names is
`tests/integration/test_phantom_conflict_recovery.py`, which exercises `Beads.resolve` /
`Beads.release` directly. The tool-seam counterpart **does** exist and is unnamed by the
contract: `modules/tool-work-tracker/tests/test_phantom_conflict_recovery.py`. Conformance 2
already names both layers ("(tool seam)" and "(adapter layer)"). *Smallest fix:* give
Conformance 1 the same two-path form Conformance 2 already has.

**C4-7 — one clause id remains unnumbered.** `CCV1-021` cites `Conformance: Checks`, which is
the only clause id in either family with no bare number; the 2026-09-03 amendment numbered
the Conformance *fixtures* and the Freeze Bar but not the `Checks` subsection. This is
already a **reported** deviation, not a silent one — `ledger/checks/_support.py` carries it
as an explicit `unnumbered=frozenset({"Conformance: Checks"})` with a comment naming the
amendment. *Smallest fix (optional):* number it, and drop the exemption in the same change.
Listed for completeness; it costs nothing today.

**Two residuals that are not contract text, and are not fixed here either.** (i) The seven
`indexed` rows' `last_measured` dates still read 2026-09-01 (six of them) and 2026-09-05
(`CCV1-002`) although all 23 cited tests were executed green **today** — refreshing them would be a
`rows.yaml` write beyond this lane's drift-only scope, and it understates rather than
overstates, so it is named rather than done. (ii) `CCV1-009` and `CCV1-022` still carry
`assertion.kind: probe` with a named follow-up to upgrade five rows to `indexed` now that
the behavioural fixtures run in CI; that is a schema change across five rows plus the
mutation harness, still out of scope, and now with the fixtures measured green rather than
assumed.

---

### C5. Honest limits of this re-check

- **This section produces evidence, not a lock.** No contract byte was edited. Nothing here
  is owner ratification and nothing here is an external review.
- **The ledger probes remain in-process source assertions.** They prove the *shape* of the
  code, never its behaviour. What makes this run stronger than a probe-only run is that the
  behavioural fixtures behind the shape assertions were **executed** (§C1), not cited.
- **`make test` was not run end to end.** The tiers this contract's Freeze Bar depends on
  were run individually and are named with their counts; the root tiers unrelated to custody
  (CLI surface, web, observatory, the operator-surface kits) were not re-run, because
  `git diff origin/main -- src tests` is empty and no custody claim rests on them.
- **Two clauses are NOT-ASSERTABLE and stay that way.** Core 13 and NOT-ASSERTABLE 1 are
  about what an *agent* did in a session this repository does not host. No run in §C1
  strengthens them, and none pretends to.
- **`CCV1-023`'s Fixture-1 half is an existence check** (§C2c) — the one place a CONFORMS
  row leans on `.exists()` without a content assertion of its own, mitigated but not closed
  by `CCV1-010`/`CCV1-014` indexing four named tests inside that same file.
- **The seven pre-lock candidates were found by reading, not by a check.** Nothing in the
  ledger would have caught any of them: every one is a statement in the contract's own prose
  that no probe reads. That is exactly why Freeze 8 exists, and why this list is handed to it
  rather than acted on.

---

### C6. Files written by this re-check

| File | What changed |
|---|---|
| `ledger/reconcile-report.md` | this section (`C1`–`C6`) and one Changelog entry |
| `ledger/rows.yaml` | **one row**: `CCV1-009`'s stale title corrected, plus a dated note paragraph recording it (§C2b). No disposition, no assertion, no quote, no other row. |
| `contracts/operator-surface.v3-candidate.md` | a **new sibling proposal** (one change: re-anchor Backlogged 4's under-qualified `` `__init__.py:711` `` citation to its full path). Proposes only; edits nothing. |

**No other file was written.** No byte of `contracts/custody-coordination.v1.md`, of
`contracts/operator-surface.v1.md`, of `ledger/checks/`, of `src/`, of `tests/`, of
`modules/`, of `docs/` or of `.github/`. No item was filed and none closed; no work-tracker
item was claimed or resolved. The live service was never contacted, `:3308` was never
written, and no locked-document guard was invoked — because no locked document was opened.

---

## Amendment 2026-09-06 — operator-surface v3 applied

The mandatory full re-review that a SYNC-hash change triggers, run because the
FROZEN contract moved again: the **one** owner-ratified correction in
`contracts/operator-surface.v3-candidate.md`, plus one dated Changelog entry.

**Run:** 2026-09-06, branch `lane/custody-lock`, branched from `main` @ **`4c37b16`**.
**Trigger:** `contracts/operator-surface.v1.md` changed, so `OSV1-000`'s pin
failed. Under `LEDGER-FORMAT.md` sec.4 that mandates a **full ledger re-review,
never a silent hash bump** — this section is that re-review's record.
**Owner's act, in his own words:** *"Yep, your recommendations are good, go for
all."* — answering four questions at once; the third of them was "ratify
operator-surface.v3-candidate.md". The stamp is on the proposal itself
(`Ratified by owner — 2026-09-06, literal: "your recommendations are good, go
for all".`), which is what let the write through: `hooks-candidate-guard`
refuses an in-place edit of a locked contract unless a sibling
`*.vN-candidate.md` names that contract in its `target:` field AND carries the
ratified stamp. **The guard PERMITTED the edit** — the stamped candidate stood
beside its target and the write went through on the first attempt. The guard was
never bypassed: no `bash`, no `sed -i`, no emergency-unlock token.

**Outcome in one line:** **zero rows re-anchored, zero dispositions changed,
zero drift in either direction** — the amendment repairs one pointer's
*addressing*; the line it points at never moved.

---

### V1. What was actually run (a self-report is not proof)

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed** | every row's quote verifies against the NEW bytes, every assertion ref resolves, the tripwires hold, `OSV1-000`'s pin matches |

The custody family was untouched by this amendment and its pins were recomputed
rather than assumed (see V3).

---

### V2. What changed in the contract — one line, one Changelog entry

**Backlogged 4's trigger citation, re-anchored to its full path.**

Before:

```
**Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `__init__.py:711`)*
```

After:

```
**Trigger:** the owner reports a reclaim they did not see on the web surface. *(Brief A §3, `modules/tool-work-tracker/amplifier_module_tool_work_tracker/__init__.py:711`)*
```

The line number did not move — `711` was measured on this tree and at `4aaee50`
(the commit that authored the citation) and is the same line in both. Only the
*file* is qualified: eleven files in this repository are named `__init__.py`,
and the bare citation had already been resolved to the wrong one, on the record,
by an independent drafter (`operator-surface.v2-candidate.md` §"Not in this
proposal", item 3, which called it a "dead pointer"). That reading was a
mis-resolution, not a real dead pointer, and **the need it returned is answered
here**. The v2 candidate is a ratified historical record and was not edited.

Plus one Changelog entry in the contract, newest-first, recording the amendment
and that Status remains FROZEN.

---

### V3. Hash, old → new

| pinned file | before | after |
|---|---|---|
| `contracts/operator-surface.v1.md` (`OSV1-000`) | `a1f304b11b17e686…` | `b6f9dc58d8807e31…` |
| `contracts/custody-coordination.v1.md` (`OSV1-000`, `CCV1-000`) | `ec4b736f8d6dca4e…` | **unchanged at this amendment** — recomputed byte-for-byte, not assumed |
| `docs/VISION.md` (`CCV1-000`) | `f5eb400c79211d90…` | **unchanged at this amendment** — recomputed byte-for-byte, not assumed |

The custody contract and the vision are opened **later in this same lane**, by
the custody true-up and lock; those moves re-hash `CCV1-000` and `OSV1-000`'s
custody entry again and carry their own record below.

---

### V4. The full re-review — 36 rows walked, 0 re-anchored

Checked on this tree **after** the edit, not taken from the proposal's own
prediction:

1. **No OSV1 row cites a Backlogged clause.** The 36 rows' `contract.clause`
   values distribute Core ×19, Conformance ×7, Freeze ×8, Reserved ×1, SYNC ×1.
   Backlogged: **zero**.
2. **No row's quote overlaps the changed line, in either direction.** Every
   quote-carrying row was whitespace-collapsed and tested for containment
   against the collapsed target line — before-text and after-text both — and the
   target line against each quote. Result: **NONE**.

Tally unchanged. Dispositions unchanged. No probe needed retargeting, so
`ledger/checks/` was not touched by this amendment.

---

### V5. The `OSV1-033` trap, named in advance and avoided

`test_row_osv1_033` asserts the contract's `## Changelog` section cites exactly
one in-repo file — `assert cited == {"webapp.py"}` — where `_SOURCE_CITE` is a
**backticked bare** `` `<file>.py:<line>` ``. Two consequences, both honoured:

- The replacement text lives in Backlogged 4, outside the Changelog, and is a
  *path*: the character before `__init__.py` is `/`, not a backtick, so the
  pattern cannot match it even where it stands.
- The ratifying Changelog entry describes the change in **prose** and writes no
  backticked bare `file.py:NN`. `test_row_osv1_033` is green.

---

### V6. Files written by this amendment

| File | Change |
|---|---|
| `contracts/operator-surface.v3-candidate.md` | the owner's ratified stamp on the file's designated stamp line — then, in the same change, `git mv`'d to `contracts/applied/` |
| `contracts/applied/operator-surface.v3-candidate.applied.md` | the archived proposal: the ARCHIVED note and the `RATIFIED by owner 2026-09-06` status, written as **one** edit (the candidate guard refuses a status stamp that lands without the record of why it landed) |
| `contracts/operator-surface.v1.md` | the one ratified change, byte-exact from the candidate, plus one dated Changelog entry |
| `ledger/rows.yaml` | `OSV1-000` rehashed + full-re-review notes |
| `ledger/reconcile-report.md` | this section (`V1`–`V6`) and a Changelog entry |

**No other file was written by this amendment.** `ledger/checks/` was NOT
touched — no row needed re-anchoring, so no probe needed retargeting. No `src/`
byte, no `tests/` byte, and at this point no `docs/VISION.md` byte and no
`contracts/custody-coordination.v1.md` byte. The live service was never
contacted, `:3308` was never written. No item was filed and none closed; no
work-tracker item was claimed or resolved.

---

## Lock 2026-09-06 — custody-coordination.v1 FROZEN

> Re-issued after Freeze 8 pass 2 (REQUEST CHANGES, one blocker RC-10): the lock branch was rebuilt from the DRAFT true-up commit so the false sentence RC-2 had introduced at §Checks could be corrected while the file still read DRAFT; the lock was then applied again as one write and this hash re-computed. Nothing else in this section changes.

The mandatory full re-review that a SYNC-hash change triggers, run twice in one
lane because the custody contract moved twice: once for the **pre-lock DRAFT
true-up** (the Freeze 8 external review's nine findings and six nits), and once
for the **lock** itself.

**Run:** 2026-09-06, branch `lane/custody-lock`, branched from `main` @ **`4c37b16`**.
**Owner's act, in his own words:** *"Yep, your recommendations are good, go for
all."* — one sentence answering four questions in order: ratify the custody
pre-lock true-up; **discharge** custody Freeze 2; ratify
`operator-surface.v3-candidate.md`; hold `docs/VISION.md` loosely.
**Outcome in one line:** **`contracts/custody-coordination.v1.md` is FROZEN**,
every Freeze Bar condition met, three quotes re-anchored, one probe retargeted,
**zero dispositions changed**.

---

### K1. What was actually run (a self-report is not proof)

| Command | Result | What it proves |
|---|---|---|
| `.venv/bin/python -m pytest ledger/checks -q` | **60 passed** | every row's quote verifies against the FROZEN bytes, every assertion ref resolves, the tripwires hold, both SYNC pins match |
| `make ledger-mutate` | **69 / 69 proven, none unproven** | every probe still discriminates — including the retargeted `CCV1-023` and its rewritten mutation |
| `.venv/bin/python -m pytest modules/tool-work-tracker/tests/test_conformance_fixtures.py -q` | **10 passed** | Freeze 3: all four Conformance fixtures implemented and PASSING, measured today rather than cited from a dated note |
| `make test-conformance-a` | **0 failed / 0 XPASS** | the operator-surface Tier-A kit is unaffected by either write |
| `ruff check ledger` + `ruff format --check ledger` | clean | the two probe-side edits are formatted like the rest |

---

### K2. What changed in the contract — two writes, in this order

**Write 1 — the pre-lock DRAFT true-up** (text only; no `src/`, no `tests/`, no
behaviour). RC-1: the nine **Machine check:** lines naming ids that existed
nowhere in the repository (`claim.custody_indivisible`, `custody.one_strike`,
`sweep.required_and_scheduled`, `fence.close_post_reclaim`,
`recovery.discoverable`, `write.readback_verified`, `write.honest_failure`,
`session.single_hold`, `claim.error_specificity`) now name the ledger row plus
the probe or tests that actually carry the clause; the five lines that DO name a
real `doctor` check say so and gain their row. RC-2: §Checks rewritten to what
exists. RC-3: Freeze 1 maps D-1/-2/-5 to `CCV1-003`/`-009`/`-014` inline. RC-5:
Freeze 2 discharged, naming `work_release`'s `already_closed` branch and its
tests; Conformance 3 and Backlog 3 updated to match. RC-6: Core 1's `--quick`
parenthetical corrected (speed, not a Freeze Bar dependency; §Freeze Bar, not a
§Freeze Blockers that never existed). RC-7: Core 5's "(Backlogged feature)"
struck. RC-8: Core 6 points at `CCV1-007`/`-008` and records that sweep
observability shipped as `doctor`'s `sweeps.alive`. RC-9: TTL defined once with
its value. Six nits: Freeze 5's dead glob; Conformance 1/2 "(current)" →
"(pre-fix)"; Conformance 1's Test location given Conformance 2's two-path form;
`custody.generation` dropped from Reserved; both cadence lines given a standing
trigger; Backlog 1's trigger made observable. Plus three dated Changelog
entries.

**Write 2 — the lock, in ONE edit.** `**Status:** DRAFT` → `**Status:** FROZEN`
and the dated Changelog entry recording the ratification, landed together:
`git diff --stat` for that write is **2 insertions, 1 deletion**. The single
write is not a style preference — `hooks-candidate-guard` refuses a write that
stamps the status without adding, in the same write, the record of why it
landed, because a half-frozen file cannot be repaired afterwards (every later
edit that would add the record is refused, since by then the file reads locked).
Verified by hitting exactly that refusal earlier in this lane on the archived
v3 proposal, and re-issuing the two halves as one write.

---

### K3. Hashes, old → new

| pinned file | before this lane | after true-up | after lock |
|---|---|---|---|
| `contracts/custody-coordination.v1.md` (`CCV1-000`, `OSV1-000`) | `ec4b736f8d…` | `67b903e77f…` | **`afb0d6522e…`** |
| `contracts/operator-surface.v1.md` (`OSV1-000`) | `a1f304b11b…` | `b6f9dc58d8…` (v3 amendment) | unchanged |
| `docs/VISION.md` (`CCV1-000`) | `f5eb400c79…` | unchanged | unchanged at the lock; **`87c02ae26d…`** after the hold-loosely line (§K8) |

Both SYNC rows carry the identical custody hash, as they must — they watch the
same file for different families. Every "unchanged" above was **recomputed**,
never assumed.

---

### K4. Rows re-anchored: 3. Probe retargeted: 1. Dispositions changed: 0.

All 24 CCV1 rows were walked against the new bytes. Three quotes anchored into
text the true-up moved, and each was re-anchored to the SAME clause's surviving
normative text — never to a different clause, and never by softening what the
row reads:

| row | clause | why the quote moved | where it now anchors |
|---|---|---|---|
| `CCV1-006` | Core 5 | the `(Backlogged feature)` parenthetical was struck (RC-7) | the same sentence, minus that parenthetical — the promise is identical word for word |
| `CCV1-021` | Conformance: Checks | the whole subsection was rewritten (RC-2); both halves of the old sentence were false | the new sentence that states what this row's probe actually asserts — which also closes the review's complaint that the check tested LESS than the clause promised |
| `CCV1-022` | Freeze 5 | the glob `tests/test_*.py` matched no file (nit 10) | the clause now names `modules/tool-work-tracker/tests/` outright, so this row's former silent reinterpretation is the contract's own word |

One probe needed retargeting, and it was retargeted **in the same change as the
text that moved**: `CCV1-023` part 5 asserts Conformance 1's Test-location line
verbatim, that line gained its tool-seam path, so `test_row_ccv1_023` and its
paired mutation `_m023_test_location_regresses` were updated together. The
mutation still flips the probe red (`make ledger-mutate`: 69/69).

**Tally unchanged: 22 CONFORMS / 2 NOT-ASSERTABLE / 0 VIOLATION / 0 GAP.** No
disposition was re-decided by the lock — a lock records a state, it does not
grant one. Every CCV1 row carries a dated `TRUE-UP + LOCK 2026-09-06` note
naming what moved in its own clause.

**The OSV1 family, re-reviewed because `OSV1-000` pins the custody file too:**
zero OSV1 rows quote custody bytes at all — the boundary is a one-way citation,
so `operator-surface.v1` cites `custody-coordination.v1.md Core 8` and `Core 14`
by identifier and restates neither. Checked explicitly against the true-up's
changed clauses rather than assumed. 0 re-anchored, 0 dispositions changed.

---

### K5. Freeze Bar 1–9 at the lock

Conditions **1–7 by measurement** on this tree (§K1 above, and the pre-lock
re-check's §C1–C3), **8 by the external PR review** recorded in the contract's
own Changelog (an independent session, not the author; verdict REQUEST CHANGES →
all nine findings and six nits landed), **9 by the owner's word**. §7 above was
re-issued in this same change so the report's Freeze Bar section no longer
contradicts the ledger — the review's finding 4.

---

### K6. Honest limits and residuals of this lock

- **A lock is a record, not evidence.** Nothing in §K1 became more true because
  the status word changed; the run is what it is, and it is dated.
- **The ledger probes remain in-process source assertions.** They prove the
  *shape* of the code, never its behaviour. What makes this run stronger than a
  probe-only run is that the behavioural fixtures behind the shape assertions
  were executed.
- **Two clauses are NOT-ASSERTABLE and stay that way.** Core 13 and
  NOT-ASSERTABLE 1 are about what an *agent* did in a session this repository
  does not host. The lock does not strengthen them and does not pretend to.
- **`CCV1-023`'s Fixture-1 half is still an existence check** — mitigated but
  not closed by `CCV1-010`/`CCV1-014` indexing named tests inside that file.
- **Residuals carried forward, unchanged by this lane** (both named at §C4 and
  deliberately still out of scope): the seven `indexed` rows' `last_measured`
  dates still read 2026-09-01/-05 although their cited tests ran green today;
  and five rows still carry `assertion.kind: probe` with a named follow-up to
  upgrade them to `indexed`. Both understate rather than overstate.
- **`Conformance: Checks` remains the one unnumbered clause id** (§C4-7), still
  a reported deviation in `ledger/checks/_support.py`, not a silent one. The
  true-up rewrote that subsection's body but did not number its heading, which
  would have been a change nobody asked for.

---

### K7. Files written by this lock

| File | Change |
|---|---|
| `contracts/custody-coordination.v1.md` | the pre-lock true-up (write 1), then the lock — Status DRAFT → FROZEN plus its dated Changelog entry — in ONE write (write 2) |
| `ledger/rows.yaml` | `CCV1-000` and `OSV1-000` re-hashed twice with full-re-review notes; three quotes re-anchored (`CCV1-006`, `-021`, `-022`); a dated `TRUE-UP + LOCK 2026-09-06` note on every one of the 24 CCV1 rows |
| `ledger/checks/test_custody_rows.py` | `test_row_ccv1_023` part 5 retargeted to Conformance 1's new two-path Test-location line |
| `ledger/checks/mutation_harness.py` | `_m023_test_location_regresses` rewritten to mutate that same new line, so the probe still has a counterfactual that flips it red |
| `ledger/reconcile-report.md` | §7 re-issued (old reading preserved verbatim as §7a), this section (`K1`–`K7`), and a Changelog entry |

**No other file was written by this lock.** No `src/` byte, no `tests/` byte
outside `ledger/checks/`, no `modules/` byte, no `.github/` byte. No item was
filed and none closed; no work-tracker item was claimed or resolved. The live
service was never contacted and `:3308` was never written. The candidate guard
was never bypassed: no `bash`, no `sed -i`, no emergency-unlock token.

---

### K8. `docs/VISION.md` — held loosely, not locked

The fourth of the owner's four answers. The external reviewer's verdict on the
vision was **HOLD LOOSELY**: it meets the bar — present tense, no dates, no
"will", no roadmap, nothing falsifiable — but its Governing-contracts line
points at contracts that were still moving. The owner's word was to hold it
loosely, so **one line** was added under its Status line and nothing else:

```
**Hold loosely** — owner's word 2026-09-06 ("go for all", on the external reviewer's recommendation): the lock bar is met; left deliberately unlocked while its two governing contracts settle under lock; revisit at each `ledger/reconcile-report.md` re-check.
```

Its **Status stays DRAFT**. "Hold loosely" is a recorded decision *not* to lock;
writing a FROZEN stamp or a freeze Changelog entry here would be a lock under
another name, and would be the one thing the owner did not say. `CCV1-000`'s
vision pin moves `f5eb400c79…` → `87c02ae26d…`, and the mandatory re-review was
run for it too: **no CCV1 row quotes `docs/VISION.md` text at all** — verified
against the single line that changed, which no row cites — so 0 rows
re-anchored, 0 dispositions changed. `OSV1-000` pins the two contracts and not
the vision, so the operator family is not disturbed by a vision change; one repo
vision pinned twice would mean two rows racing to re-hash the same bytes.

---

## Changelog
- **2026-09-06 — VISION HELD LOOSELY (not locked), `docs/VISION.md`.** Owner's
  word, same sentence as the lock: the reviewer's HOLD LOOSELY recommendation
  accepted. One line added under the Status line recording that the lock bar is
  met, that the vision is deliberately left unlocked while its two governing
  contracts settle under lock, and that it is revisited at each re-check.
  Status stays DRAFT on purpose. `CCV1-000` vision pin `f5eb400c79...` →
  `87c02ae26d...`; full re-review performed — no CCV1 row quotes vision text,
  so 0 re-anchored, 0 dispositions changed; `OSV1-000` untouched by it. See §K8.
- **2026-09-06 — LOCKED, `contracts/custody-coordination.v1.md` DRAFT →
  FROZEN.** Owner's literal words: *"Yep, your recommendations are good, go for
  all."* Two writes in one lane: the pre-lock DRAFT true-up (the Freeze 8
  external review's nine findings and six nits, including Freeze 2 **discharged**
  by naming `work_release`'s `already_closed` branch), then the lock itself in
  ONE edit — status stamp and dated Changelog entry together, because the guard
  refuses a half-frozen file. `CCV1-000`/`OSV1-000` custody hash `ec4b736f8d...`
  → `67b903e77f...` → `afb0d6522e...`. **Full re-review both times** (mandatory,
  never a silent bump): 24 CCV1 rows walked, **3 quotes re-anchored** to
  surviving normative text in the same clause (`CCV1-006`, `-021`, `-022`), **1
  probe retargeted with its paired mutation** (`CCV1-023`), **0 dispositions
  changed** (22 CONFORMS / 2 NOT-ASSERTABLE); 36 OSV1 rows walked, 0 re-anchored
  — zero of them quote custody bytes. §7's SEED "BLOCKED" reading re-issued as
  FROZEN with the old text preserved verbatim at §7a (the review's finding 4).
  Gates: `pytest ledger/checks -q` 60 passed · `make ledger-mutate` 69/69 proven,
  none unproven · Conformance fixtures 10 passed · `make test-conformance-a` 0
  failed / 0 XPASS. See §K1–K7.
- **2026-09-06 — AMENDMENT APPLIED, `contracts/operator-surface.v1.md`
  (FROZEN), v3.** One owner-ratified change (owner's literal words *"Yep, your
  recommendations are good, go for all."*): Backlogged 4's trigger citation
  re-anchored from the bare `__init__.py:711` — eleven files in this repository
  carry that basename, and it had already been mis-resolved once on the record —
  to its full path, line number unchanged and re-measured at the authoring
  commit. Applied through the ratified sibling proposal, which was stamped
  first and archived to `contracts/applied/` in the same change; the guard
  PERMITTED the edit and was never bypassed. `OSV1-000` operator hash
  `a1f304b11b...` → `b6f9dc58d8...`; the custody and vision pins were recomputed
  byte-for-byte and were unchanged at this amendment. **Full re-review of all 36
  OSV1 rows performed** (mandatory, never a silent bump): zero rows cite a
  Backlogged clause, zero quotes overlap the changed line in either direction →
  **0 re-anchored, 0 dispositions changed**, tally unchanged, `pytest
  ledger/checks -q` 60 passed. See §V1–V6.
- **2026-09-06 — PRE-LOCK RE-CHECK, `contracts/custody-coordination.v1.md`
  (DRAFT), Freeze Bar read by measurement.** Scheduled re-check, not a
  hash-triggered re-review — no SYNC hash moved and both `CCV1-000` pins were
  recomputed, not assumed. **Everything a machine can check is green:** `pytest
  ledger/checks -q` **60 passed**; `make ledger-mutate` **69/69, none unproven**;
  `pytest modules/tool-work-tracker/tests -q` **127 passed / 0 failed / 0 xfailed
  / 0 skipped** (629s, real `bd` 1.1.2 + isolated dolt); the four custody
  integration files **20 passed**; the three custody unit files **67 passed**;
  ruff clean. Tally unchanged at **22 CONFORMS / 2 NOT-ASSERTABLE / 0 GAP / 0
  VIOLATION**; **0 dispositions changed, 0 quotes re-anchored** (23/23 verify).
  Freeze 1 / 3 / 5 / 6 / 7 read **met by measurement**; Freeze 4 reads **met on
  subjects, not on names** (three of its five named `check_*` functions do not
  exist, and the two that do run only under `doctor`, which CI never runs);
  Freeze 2 reads **met** — the D-6 verb is `work_release`'s extended
  `already_closed` semantics, measured on both layers — with **one owner word
  outstanding** on whether that discharges or defers it; Freeze 8 (external
  review) and Freeze 9 (owner stamp) are the two human conditions and are **not
  this lane's** to discharge. **One drift found, in the ledger and not the
  code:** `CCV1-009`'s title still read *"a post-reclaim close is not fenced"* —
  the VIOLATION it was seeded with — while its disposition, probe and fixtures
  all read green; corrected, with a dated note, and nothing machine-read touched
  (no probe reads `title`). **Seven pre-lock candidates in the contract's own
  text are LISTED, not fixed** (§C4) — a false CI claim and a dangling
  §Freeze Blockers pointer in Core 1, nine invented machine-check ids, three
  non-existent `check_*` functions, a Freeze 5 glob matching zero files, two
  stale "(current)" bad-behaviour labels, a Conformance 1 Test-location that
  names the adapter while its Verification describes the tool seam, and one
  unnumbered clause id — because a DRAFT's pre-lock edits are the owner's call
  **after** the external review, exactly as operator-surface's RC-1/2/3 were.
  Also written: `contracts/operator-surface.v3-candidate.md`, a one-change
  sibling proposal re-anchoring Backlogged 4's under-qualified
  `` `__init__.py:711` `` citation to its full path (it proposes only; the
  FROZEN contract is untouched). No `src/`, no `tests/`, no `ledger/checks/`, no
  contract byte; the live service was never contacted. See
  §"Re-check 2026-09-06 — custody-coordination.v1 Freeze Bar reading".
- **2026-09-06 — Core 10 residual closed (`work_item_pipeline-zhv`).** Dead
  `webapp._oldest_ready_item` deleted; `OSV1-015` stays CONFORMS with its
  exemption paragraph replaced by a dated note and its probe retargeted onto a
  source-wide limit census; Tier-A runs 42 passed / 0 xfailed / 0 XPASS. See
  §"2026-09-06 zhv".
- **2026-09-06 — AMENDMENT, `contracts/operator-surface.v1.md` v2 applied to
  the LOCKED text, mandatory full re-review.** Owner's word, literal:
  *"Ratified"* — the sibling proposal `operator-surface.v2-candidate.md` was
  ratified as written, all six changes, no edits requested. The candidate was
  stamped first (`Ratified by owner — 2026-09-06 …`); that stamp is what let
  `hooks-candidate-guard` pass the edits through, and **the guard was never
  bypassed** — no `bash`, no `sed -i`, no emergency-unlock token. Six
  corrections an independent review of the LOCKED text named (Freeze 9 pass-1
  findings 4/6/7/8/9 and pass-2 note 1): **Core 1**'s "leads" judgment routed
  to Core 12's review cadence, with the machine check now stating it reaches
  presence only; **Core 4** gains the register-GROWTH rule that had lived only
  in `OSV1-006`'s notes; **Core 5**'s machine-check line names its predicate
  inline and the audit's bound (static, module-local, name-matched, depth 4)
  and says plainly it does not reach the clause's second promise; **Core 12/13**
  define "ENCODE gate" once at first use, a term used four times and defined at
  none; **Core 2**'s two drifted evidence pointers re-anchored +42 lines onto
  the same bytes; **Backlogged 2/4/6** triggers made observable, with Brief A's
  out-of-repo quotation preserved byte-for-byte and dated rather than
  overwritten. SYNC (`OSV1-000`) rehashed for the operator contract only
  (`a467be2adc…` → `a1f304b11b…`); the custody contract's bytes are unchanged
  and were re-verified, not assumed. Full re-review performed (never a silent
  bump): 36 rows walked, **0 re-anchored** — measured by collapsing both the old
  and new text and testing all 35 quote-carrying rows against each, not assumed
  from the proposal's prediction — and **0 dispositions changed**. Tally stands
  at **33 CONFORMS / 3 NOT-ASSERTABLE / 0 GAP / 0 VIOLATION**; no clause changed
  tier, so Freeze 5 still reads met (19 Core rows: 17 CONFORMS + 2
  NOT-ASSERTABLE, zero red). Twelve rows' notes walked and dated. `OSV1-033`'s
  named trap avoided: the ratifying Changelog entry carries no backticked
  `file.py:LINE`, so the Changelog's cited set is still exactly `{webapp.py}`.
  Measured here, not transcribed: `pytest ledger/checks -q` **60 passed**;
  `make ledger-mutate` **69/69, none unproven**; `make test-conformance-a`
  **41 passed / 1 named xfail, 0 failed, 0 xpassed**; ruff clean. Tier-B
  deliberately not re-run and the reason stated (§A1): `git diff origin/main --
  src tests` is empty. Residuals returned rather than fixed silently (§A5):
  Backlogged 4's dead `__init__.py:711` pointer, the candidate's `**Status:**`
  line still reading PROPOSED, and two source-side findings. No `src/`, no
  `tests/`, no `ledger/checks/`, no `docs/VISION.md` and no custody-contract
  byte touched; the live service was never contacted.
- **2026-09-05 — LOCK, `contracts/operator-surface.v1.md` FROZEN, mandatory
  full re-review.** Owner ratification and signature (Freeze 10), literal words
  *"Ok, do the freeze"* and *"looked, ratify."* Three owner-ratified pre-lock
  fixes from the Freeze 9 external review (independent reviewer, verdict
  REQUEST CHANGES → approve once landed): **RC-1** Core 5 reworded to what
  `reads.never_write` asserts, naming `GET /auth/logout`'s cookie clear as the
  one exception — the old sentence was literally false on this tree; **RC-2**
  Conformance 1/3/4 halves reworded to the defects the kit MEASURES (a hue
  outside the token set, not "alarm-coloured"; the disclosure plus live-region
  node identity, not "all four"; the element-level border box past
  `clientWidth`, not `scrollWidth`, which `overflow-x: clip` makes satisfiable
  by hiding overflow rather than preventing it — the Good half inherited that
  defect too); **RC-3** Core 12/13 cadences gain a standing trigger, "at each
  `ledger/reconcile-report.md` re-check", because both existing triggers expire
  at this stamp. Plus the **Freeze 8 record** (the owner looked at L0/L1/L2 at
  430/900/1280 in both themes — the eighteen pinned-browser captures as three
  contact sheets — and said *"looked"*) and the FROZEN stamp. SYNC (`OSV1-000`)
  rehashed for the operator contract only (`f4098752…` → `a467be2adc…`); the
  custody contract's bytes are unchanged and were re-verified, not assumed.
  Full re-review performed (never a silent bump): 36 rows walked, **1
  re-anchored** (`OSV1-007`, within the same clause), **1 disposition changed**
  — `OSV1-034` (Freeze 8) GAP → **CONFORMS** by `VIOLATION-MOVEMENT`, its pin
  replaced by a real record check and its mutation flipped to the regression
  direction in the same change. Tally 32/3/1/0 → **33 CONFORMS / 3
  NOT-ASSERTABLE / 0 GAP / 0 VIOLATION**; the family now carries **no red row**.
  Five more rows' notes trued up where the clause text they describe moved
  (`OSV1-018`, `-019`, `-020`, `-022`, `-023`), and two "honest limit"
  paragraphs (`OSV1-007`'s `GET /auth/logout`, `OSV1-023`'s `scrollWidth`) now
  record that the clause and the check AGREE. **Freeze Bar: all ten met** — 1–7
  by measurement, 8 and 10 as owner acts recorded in the Changelog, 9 as the
  external review file (out-of-repo, and reported as such; no row) — §8, with
  the pre-lock reading kept as §8b. Measured here, not transcribed: `pytest
  ledger/checks -q` **60 passed**; `make ledger-mutate` **69/69, none
  unproven**; `make test-conformance-a` **41 passed / 1 named xfail**; ruff
  clean. Tier-B deliberately not re-run and the reason stated (§L1): `git diff
  origin/main -- src tests` is empty, so the committed recording is still a
  recording of this tree. Six lower review findings deferred to post-lock
  proposals. No `src/`, no `tests/`, no `docs/VISION.md` and no custody-contract
  byte touched; the live service was never contacted.
- **2026-09-05 — RE-CHECK, `contracts/operator-surface.v1.md` (`OSV1-###`),
  after highway `hw-operator-surface` waves 1–4** (PRs #82 `aec9991`, #83
  `6c2e9fa`, #84 `065da04`, #85 `7e43e73`). Standing ratchet run against `main`
  @ `7e43e73`. **Zero disposition changes and zero drift in either direction**
  — the tally stands at **32 CONFORMS / 3 NOT-ASSERTABLE / 1 GAP / 0
  VIOLATION**, with **0 red Core-carrying rows** (19 Core rows: 17 CONFORMS + 2
  NOT-ASSERTABLE), so **Freeze 5 is met by measurement**; the ten Core flips
  that took it there are recorded with the measurement behind each (§R3). All
  three SYNC hashes re-computed and matching (`f4098752…`, `ec4b736f…`,
  `f5eb400c…`) — no re-review triggered, and `git diff dfd4b8f..7e43e73 --
  contracts/ docs/VISION.md` is empty, so the four waves moved `src/` and
  `tests/` and never the contract. Measured here, not transcribed: `pytest
  ledger/checks -q` **60 passed**; `make ledger-mutate` **69/69, none
  unproven**; `make test-conformance-a` **41 passed / 1 named xfail**; the
  Tier-B kit **89 passed, twice**, with every asserted field byte-identical to
  the committed recording (the only moving leaves are the four unasserted
  light-theme `--watch` buckets and a session-timing `text_scored` denominator,
  both diagnosed in §R5) — and the ledger re-run **green against the fresh
  recording**, not only the committed one. The censuses were re-run in-session
  too: 0 literal inline sites, 0 `<style>` blocks outside the token module, the
  8-site exemption register set-equal to the live `COMPUTED` census, 30 routes
  with 0 GET-reaching-mutation, 54 text pairs / 9 non-text pairs all clearing
  their floors. **Freeze Bar reading: 1–7 MET, 8/9/10 outstanding and
  human-only** — the contract is READY FOR THE OWNER'S LOOK AND EXTERNAL
  REVIEW, and stays DRAFT (§8, seed reading kept as §8a). Two record defects
  reported rather than absorbed: `OSV1-024`/`OSV1-025` still open their notes
  with stale "PINNING ROW" prose above a CONFORMS disposition (with
  `test_row_osv1_025`'s docstring), filed as `work_item_pipeline-lvn`; and
  `work_item_pipeline-umm` remains open under the now-green `OSV1-031`. Three
  needs returned to the root (§R9). `ledger/rows.yaml` byte-unchanged; no
  contract, no `docs/VISION.md` and no `src/` byte touched; the live service was
  never contacted.

- **2026-09-04 — operator-surface DRAFT true-up #1, mandatory full re-review.**
  Owner-ratified (*"yep, do it all."*) three-part amendment: Core 4 widened to
  reach `<style>` blocks outside the token module (evidence: `webtrust.py`'s
  hardcoded retired palette, which the seed could only record-not-score), Core
  10's machine check aligned to its own clause (*"does not survive a refresh"*),
  and the Changelog's `webapp.py:38-39` quotation made byte-exact — the contract
  had been failing its own Freeze 7. SYNC (`OSV1-000`) rehashed for the operator
  contract only (`7566c75c…` -> `f4098752…`); the custody contract's bytes are
  unchanged and were re-verified, not assumed. Full re-review performed (never a
  silent bump): 36 rows walked, **2 re-anchored** (`OSV1-005`, `OSV1-016`, both
  within the same clause), **1 disposition changed** — `OSV1-033` GAP →
  **CONFORMS** by `VIOLATION-MOVEMENT`, its pin replaced by a real check in the
  same change. Tally 8/5/20/3 -> **9 CONFORMS / 5 VIOLATION / 19 GAP / 3
  NOT-ASSERTABLE**; Freeze 5's Core sub-tally unmoved (10 of 19 still red). New
  `<style>`-block census engine in `_support.py` (one block, 40 literal
  declarations, `webtrust.py:256-302`), pinned separately from the inline half
  in `OSV1-005` and `OSV1-032`. Two of §9's five open needs closed (need 2:
  yes, Core 4 reaches; need 4: no, density conforms). `pytest ledger/checks -q`
  60 passed; `make ledger-mutate` **53/53** (52 -> 53: one mutation added, one
  replaced when `OSV1-033` changed groups). Status stays DRAFT; no `src/` byte,
  no custody-contract byte and no `docs/VISION.md` byte was touched.

- **2026-09-04 — SEED, `contracts/operator-surface.v1.md` (`OSV1-###`).** First
  population of the second row family: 36 rows (8 CONFORMS / 5 VIOLATION / 20
  GAP / 3 NOT-ASSERTABLE) covering Core 1–13, Conformance 1–7, Freeze 1–8 and
  Reserved 1, all measured against `main` @ `4aaee50`. `OSV1-000` pins BOTH
  contracts (ruling Need 3) so a custody amendment re-reviews this family too.
  25 red rows, all carrying pinning probes and a filed work item; 10 items filed
  in `work_tracker`. The ledger machinery became family-aware: tripwires,
  clause-id validation, probe ownership and the mutation harness now resolve
  through `_support.FAMILIES` instead of one hardcoded contract. Measured on
  this branch: `pytest ledger/checks -q` 60 passed in 1.06s;
  `make ledger-mutate` proven 52/52. Five interpretive needs returned to the
  root (report §9); no contract and no `docs/VISION.md` byte was touched.

- **2026-09-04 — VISION.md two-seam extension, mandatory full re-review.**
  Owner-ratified (*"lgtm."*) DRAFT text at the operator-surface ENCODE gate:
  `docs/VISION.md` became the one repo vision over two seams and
  `contracts/operator-surface.v1.md` was added as a new DRAFT contract. SYNC
  (`CCV1-000`) rehashed for the vision only (`b7547519...` -> `f5eb400c...`);
  the custody contract's bytes are unchanged and were re-verified, not assumed.
  Full re-review performed (never a silent bump): 24 rows walked, **0
  re-anchored** — no row quotes vision text, so the changed Scope and
  Governing-contract lines are cited by no row — dispositions unchanged (22
  CONFORMS / 2 NOT-ASSERTABLE / 0 VIOLATION / 0 GAP), `pytest ledger/checks -q`
  26 passed, `make ledger-mutate` 15/15. No `OSV1-###` rows created here; that
  contract is seeded as its own row family in a following step.
- **2026-09-03 — DRAFT amendment, mandatory full re-review.** Owner-ratified
  ("ok, yes, proceed") three-part contract true-up: struck all
  `**Current state:**` annotations (conformance status lives in the ledger
  only), numbered Conformance 1-4 and Freeze 1-9 for bare-id citation, and
  corrected the four stale Test-location lines. SYNC (CCV1-000) rehashed;
  full re-review performed (never a silent bump): quotes re-verified (none
  needed re-anchoring), CCV1-022/-023 retargeted from the unnumbered
  `Freeze Bar` id to `Freeze 5`/`Freeze 3`, CCV1-023's probe flipped from a
  drift-recording pin to a genuine conformance check (its stale-note
  companions in CCV1-009/-022 corrected too), and the mutation harness's
  three now-un-appliable `FIXED:` mutations retired for one honest
  `REGRESSION` mutation (17/17 -> 15/15, denominator shrank honestly). §1
  rewritten with the current tally (22 CONFORMS / 2 NOT-ASSERTABLE / 0
  VIOLATION / 0 GAP), SEED table kept as §1a history. No row's disposition
  changed. Discharges §11.2's Residual 1 and Residual 2.
- **2026-09-02 — Ruling-1 conditions.** Pinning probes made auditable:
  `VIOLATION-MOVEMENT` flip direction defined locally (§11.1), pinning-row
  census recorded — zero `VIOLATION` rows remain, one `GAP` pin (§11.2) —
  and `ledger/checks/mutation_harness.py` + `make ledger-mutate` committed,
  proving **17 / 17** mutations flip their probe red (§11.3). Two tripwires
  added; ledger kit now 26 checks.
- **2026-09-01 — SEED.** First population. 24 rows (12 CONFORMS · 4 VIOLATION ·
  6 GAP · 2 NOT-ASSERTABLE), 10 items filed, tripwires green, SYNC pinned at
  `b5b23ca`. Freeze BLOCKED on 4 conformance blockers + 2 process items. Six
  contract "Current state" annotations found stale in the reverse direction and
  recorded here rather than silently corrected.

## Publication re-check 2026-09-08 — custody-coordination projections

The protocol-authority ruling permits separately named **non-governing public
projections** and an attestation without a new ratification because no
normative clause changes. `CCV2-000` now pins
`contracts/custody-coordination.v3.public.md` and
`contracts/custody-coordination.v2.public.md`. Their approved candidate
identities, privately-held original-document hashes, normative-payload hashes,
and public-projection hashes are explicitly bound by the repo-relative
`contracts/ratification-attestation.json`.

Mandatory full custody re-review completed before the SYNC pins changed. All
24 CCV1 rows remain anchored to their unchanged public historical v1 source.
All three CCV2 rows were walked against the v3 public projection:
`CCV2-001` retains the approved retained-failure-reason, fenced-clear, and
named-stale-refusal fixture cites; `CCV2-002` retains its Core 13 quote and
eleven-tool CONFORMS disposition. No disposition changed: custody remains
**24 CCV1 CONFORMS, 2 CCV1 NOT-ASSERTABLE, 2 CCV2 CONFORMS**, with zero GAP
and zero VIOLATION rows.

This publication run executed source assertions from the public worktree:
`pytest ledger/checks -q` (**61 passed**), the projection-integrity test
(**1 passed**), and the mutation harness (**71 / 71 proven**). The ledger
checks verify the CCV2 quotes against the public projection bytes; the
projection-integrity test verifies the public Core/Conformance byte range
against the attested approved normative-payload hash. Ruff check and format
check passed for the changed Python checks and test.

These are publication-integrity results, not a rerun of runtime validation.
The existing validation summary is retained as prior evidence only; no full
suite, installation, or DTU run was performed for this publication change. No
runtime source or module test file is changed by this ledger update.
