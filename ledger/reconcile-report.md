# Reconcile report — SEED

**Contract:** `contracts/custody-coordination.v1.md` (DRAFT, owner-ratified at the
ENCODE gate 2026-09-01)
**Mode:** SEED (first population of the ledger)
**Run:** 2026-09-01, branch `converge/seed-custody-ledger`, tree `b5b23ca`
(branched from `main` @ `b5b23ca`; the reference fix is PR #63, merge `94f0b46`)
**Ledger:** `ledger/rows.yaml` (24 rows) + `ledger/checks/` (24 executable checks)

---

## 1. Rows by disposition

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

`CCV1-000` pins both governed files by content hash:

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

## 7. Freeze Bar status — BLOCKED

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

---

## Changelog

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
