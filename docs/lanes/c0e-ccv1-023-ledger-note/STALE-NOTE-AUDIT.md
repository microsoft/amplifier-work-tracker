# Stale mechanism-claim audit — every CCV1 row, 2026-09-05

Lane `c0e-ccv1-023-ledger-note`, work item `model_performance-c0e`.

`model_performance-c0e` asked for one deliverable to be answered explicitly:

> **Say explicitly whether any OTHER ledger row makes a mechanism claim that is now
> stale.** #68, #76 and #77 all landed since these notes were written; a second wrong
> note is likelier than not, and finding it now is cheap.

**Answer: yes — five, not one.** All five are CONFORMS rows whose *disposition* is
correct and whose *notes* describe a world that no longer exists. Four of the five are
the same claim repeated. All five are corrected in `ledger/rows.yaml` in this change;
no disposition and no `assertion.kind` was changed by this lane.

## Method

Not a skim. Three passes over all 24 CCV1 rows:

1. Grep every row's notes for the mechanism vocabulary the three merges touch —
   `reap`, `reclaim`, `TTL`, `liveness`, `sweep`, `heartbeat`, `sweeps.`, `xfail`,
   `runs in no`, `unrun`, `does not exist`, `doctor`.
2. For every hit, read the CURRENT source or CI config that the claim is about, and
   compare. A claim is only stale if the artefact it describes disagrees with it *now*.
3. Where the source itself states the fact in prose (a docstring), quote both sides so
   the disagreement is checkable rather than asserted.

## The five

### 1. CCV1-002 — "exactly two routes" to reclaim-eligible. **STALE. Corrected.**

The note said:

> `custody.reclaim_eligible` reaches "eligible" by exactly two routes -- a stale/absent
> last_seen, or the one-way escalation ceiling.

`src/amplifier_work_tracker/custody.py::reclaim_eligible`'s own docstring says:

> Three paths to eligible, and only three: 1. STALE ... 2. DEAD HOLDER ... 3.
> ESCALATION CEILING

The dead-holder path landed in **PR #76 (`46d7da4`, `model_performance-oy4`)**, after
this note was written. The ledger and the source disagreed on the *count of the very
mechanism the row is about* — the highest-value catch in this audit, and one this lane
would not have looked for without the deliverable that told it to.

**The clause is not weakened.** Core 2 says total hold duration never disqualifies a
claim; path 2 keys on the HOLDER's liveness, never the hold's age, is fenced to only
ACCELERATE path 1 inside a window path 1 would have covered anyway, and every
unknowable case resolves to NOT eligible. Disposition stays CONFORMS.

**Also fixed:** the row's `indexed` refs covered only paths 1 and 3, so it did not
actually cover the mechanism it now describes. Two path-2 cites added from
`tests/unit/test_custody_dead_holder.py`
(`test_a_live_holder_deep_inside_the_ttl_is_left_alone`,
`test_ttl_staleness_still_wins_and_costs_no_pid_probe`), and `last_measured` moved
2026-09-01 → 2026-09-05 because they were run, not assumed.

### 2–4. CCV1-003, CCV1-004, CCV1-010 — "that suite runs in nothing (CCV1-022)". **STALE. Corrected.**

Three rows defer their own indexed upgrade on a blocker that is gone:

| Row | The stale sentence |
|---|---|
| CCV1-003 | "...which still runs in no CI (CCV1-022) ... Upgrade this row to an `indexed` cite when CCV1-022 goes green." |
| CCV1-004 | "...but that suite runs in nothing (CCV1-022), so it cannot be cited as measured." |
| CCV1-010 | "...in the modules suite) runs in nothing -- CCV1-022." |

**CCV1-022 is green**, closed by **PR #68 (`b3fac1e`)**, and its own note says so. The
suite is wired three ways: the venv install (`Makefile:24`), the `test-module` target
inside `make test` (`Makefile:99,108`), and `.github/workflows/ci.yml:125-126`
("Tier 5 -- tool module tests"). Every fixture the three rows cite was measured passing
on this branch 2026-09-05.

This is the *worse* failure mode of the two in this audit, because it is self-sealing: a
row that says "cannot be cited as measured" tells the next reader not to bother
measuring. Corrected to say what is actually true — the fixtures run, and the only thing
left is the citation itself, which stays a named, now-unblocked follow-up.

### 5. CCV1-017 — "Fixture 4 does not exist in ANY suite ... asserted by nothing". **STALE. Corrected.**

The note said the behavioural single-hold fixture "does not exist in ANY suite -- see
CCV1-023 -- so the refusal is enforced and asserted by nothing."

Both halves are false. **CCV1-023 itself flipped CONFORMS on the file that contains it.**
`modules/tool-work-tracker/tests/test_conformance_fixtures.py` carries four Fixture-4
tests (`test_fixture4_a_directed_second_claim_is_refused_while_holding`,
`..._a_queue_second_claim_is_refused_while_holding`,
`..._the_second_claim_succeeds_once_the_first_is_resolved`,
`..._the_second_claim_succeeds_once_the_first_is_released`), measured passing
2026-09-05. Two rows of one ledger disagreed with each other about whether a fixture
exists.

## Checked and NOT stale

* **CCV1-006 / CCV1-007** (`sweeps.alive`, the TTL-enforced-by-sweep prose) — read
  against **PR #77 (`0055cd2`)**, which made `sweeps.alive` report `unknown` rather than
  FAIL for a root the service does not serve. Neither note asserts the failing-vs-unknown
  behaviour; both describe the heartbeat's existence and the "TTL does not enforce
  itself" prose, and both remain true. No change.
* **CCV1-009 / CCV1-022 / CCV1-023's xfail sentences** — already corrected by the
  2026-09-03 re-review; verified, not re-corrected.
* **`ledger/reconcile-report.md`** — carries the same "runs in nothing" claims in four
  places (`:253`, `:271`, `:313`, `:356`). **Deliberately NOT touched.** It is an
  explicitly dated, explicitly superseded snapshot ("### 1a. SEED snapshot (2026-09-01)
  -- history, superseded by the table above"), and it already says of itself that
  rewriting it is the wrong move. A historical report that is edited to agree with the
  present is no longer evidence of anything. Recorded here instead.
* The remaining CCV1 rows carry no mechanism claim touched by #68, #76 or #77.

## OSV1 rows

Out of scope and stated as such: the OSV1 family was seeded 2026-09-04 — *after* all
three merges — by the operator-surface highway that is still actively pushing to this
repo. Its rows cannot be stale with respect to merges that predate them, and auditing a
family another lane is concurrently rewriting would produce conflicts, not truth.
