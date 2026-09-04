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

## 1. Rows by disposition

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

## 8. Freeze Bar status — BLOCKED

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

3. **Does a computed *colour* belong on a computed-*geometry* register?**
   (Core 4 / OSV1-006.) Six of the 23 registered sites interpolate a colour, not
   a geometry. They are listed, never hidden. If they do not belong, OSV1-006 is
   not CONFORMS and six sites move to `np3`'s migration list.

4. **Is the density preference "state stored only in the browser"?** (Core 10 /
   OSV1-016.) `localStorage['wt-density']` **satisfies** Core 10's prose (it
   survives a refresh) while being, literally, the thing the machine check's
   wording forbids. This run pinned **theme only** — red under both readings —
   precisely so a later density ruling is not pre-empted by an already-red probe.

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

## Changelog
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
