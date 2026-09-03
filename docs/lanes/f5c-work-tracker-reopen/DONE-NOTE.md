# DONE-NOTE — `model_performance-f5c`

**Item:** IMPLEMENT: `reopen` CLI verb + `work_reopen` tool, and make `resolve` on a closed
item fail loud (spec: uma)
**Lane:** `f5c-work-tracker-reopen` · **Branch:** `lane/f5c-work-tracker-reopen`
**Repo:** `github.com/microsoft/amplifier-work-tracker` · **Parent:** `1621771`
**bd:** 1.1.2 (20e493e56) · **Date:** 2026-09-02

---

## Result

All five parts shipped, with tests. The headline behaviour change: `resolve` on an
already-closed item now compares the resolution **text**, not the item's status, at **both**
places it decides "did my write land?" — so a correction is either an idempotent success
(identical text) or a loud, non-zero refusal that writes nothing (divergent text). `reopen`
is the remedy that refusal names.

The lane also found and fixed **two undocumented bd behaviours** that the spec had flagged as
unknown or had not anticipated at all. Both are recorded below; the second one would have
made `work_reopen(claim=True)` unusable in exactly the scenario it exists for.

---

## What was measured (not assumed)

### 1. `bd reopen` CLEARS `close_reason` — the archive-first ordering is load-bearing

The spec (§2.4) said bd 1.1.2's treatment of `close_reason` across a reopen was undocumented
and unverified, and told the implementer not to build a guarantee on it. **Measured here:
reopen clears it.** The previous resolution text is *gone* from the issue row.

That makes the spec's archive-first ordering not merely prudent but load-bearing: had the
wrapper trusted bd to preserve the text, **every correction would have destroyed the record
it was correcting.** Pinned in two places so a future bd change is loud:
`tests/integration/test_reopen_roundtrip.py::test_measured_close_reason_disposition_across_a_reopen`
and `doctor`'s `reopen.close_reason_disposition`.

### 2. `bd reopen` LEAVES THE OLD ASSIGNEE — an item nobody can take is not correctable

Not in the spec; found because this lane's own tool test failed on its claim leg. After
`bd reopen`, the item is `open` with `closed_at` cleared **but still assigned to whoever
closed it**, so a directed claim by anyone else is refused outright:

```
claim <id> as 'corrector' failed: Error claiming <id>: issue already claimed by <first-pass actor>
```

`work_reopen(claim=True)` could therefore only ever claim what it reopened if the correcting
agent happened to be the agent who closed it — which is the *opposite* of the correction
scenario. `Beads.reopen` now clears the assignee (the same `update --assignee ""` that
`release` already does) and verifies by readback; if it cannot be cleared, it says so loudly
naming the stuck holder rather than handing back an untakeable item. Fenced by
`doctor`'s `reopen.reopens`, which now performs a **directed** claim by a *different* actor
(the weaker `claim_next` form passed even with the stale assignee in place).

### 3. The `reopened` audit trail is TWO event rows, not one

The deliverable expected "a `reopened` row naming the actor and reason". Measured: bd writes
the `reopened` row with `event_type` + `actor` (its `comment` column is **empty** — the reason
is not there) and lands `--reason` as an adjacent attributed `commented` row in the same
transaction. The `reopened` row's `old_value` additionally carries the entire prior issue JSON
including `close_reason` — a third, incidental archive. Both rows are asserted, because a test
that only looked for the reason on the `reopened` row would pass on a bd that stopped recording
the transition at all.

---

## The open question, answered

> *whether one actor may hold two items at once. If not, `work_reopen`'s `claim=True` must
> degrade to `claimed:false` with a clear message rather than drop the caller's existing
> custody.*

**Answered: a SESSION holds at most one item.** The constraint is at the tool layer, not bd's:
`_Held`'s own docstring states it, and `WorkTrackerSession.claim` refuses outright with
`"already holding <id> ... resolve it with work_resolve before claiming another item"`. (bd
itself would happily assign two items to one actor name; the seam is what enforces one.)

So `claim=True` from a session that already holds work **cannot** be honoured, and
`work_reopen` degrades exactly as the spec required: `claimed: false`, `claim_error` carrying
the refusal verbatim, `next_step` telling the caller to claim it themselves — and the existing
hold is untouched, its custody thread still running. The reopen still **stands**; rolling it
back would mean a second close with invented text, which is the disease.

Implemented by *reusing* `session.claim()` wholesale rather than re-implementing the claim leg
— that is the one atomic claim-plus-custody path, and a second implementation of it is how a
double-claim hole gets reopened. Proven by
`modules/tool-work-tracker/tests/test_work_reopen.py::test_claim_leg_degrades_without_dropping_an_existing_hold`.

---

## Deliverables

| Deliverable | Status |
|---|---|
| Draft PR on origin carrying parts 1–5, suite green | **DONE** — see PR body |
| reopen round-trip (corrected text reads back; events row; verbatim comment archive) | **DONE** — `tests/integration/test_reopen_roundtrip.py` |
| divergent-text refusal (non-zero, nothing written, both texts, remedy) | **DONE** — unit + integration + CLI |
| identical-text idempotency (`"idempotent": true`) | **DONE** — unit + integration + CLI |
| contended path — BOTH decision points | **DONE** — `tests/unit/test_resolve_text_compare.py` |
| doctor assumptions (6 new) | **DONE** — `doctor` now 33/33 against live bd |
| fail-before evidence | **DONE** — `evidence/fail-before-*.log`, `evidence/before-defect-demonstration.log` |
| help/contract text updated | **DONE** — `cli.py` module docstring, `context/awareness.md`, `bundle.md`, `AGENTS.md` |
| DONE-NOTE with the open question answered | **DONE** — this file |

### Test tiers actually run, honestly

| Tier | Command | Needed live bd/dolt? | Result |
|---|---|---|---|
| unit | `make test-unit` | no | green (23 new tests) |
| integration | `make test-integration` | **yes — had it** (bd 1.1.2 + isolated dolt server per session) | green (8 new + 6 new contract assumptions) |
| cli | `make test-cli` | **yes — had it** | green (5 new) |
| ledger | `make test-ledger` | no | green (24, incl. 3 reconciled rows) |
| **all four** | `make test` | yes | **1189 passed, 3 skipped, 1 failed — the failure is pre-existing, see below** |
| modules suite | `pytest modules/tool-work-tracker/tests` | **yes — had it** | **93 passed, 1 failed — pre-existing, see below** (all 7 new tests green) — *not run by root CI (AGENTS.md); run directly because this change touches it* |
| `doctor` | `amplifier-work-tracker doctor --quick` | yes | **33/33** |

**Two failures, both pre-existing, both reproduced at parent commit `1621771` with this
change absent.** Neither is caused by this work; both are filed `discovered-from` this item.

1. `tests/cli/test_cli_surface.py::test_doctor_quick_succeeds_against_the_real_installed_bd`
   — the suite repoints `AMPLIFIER_WORK_TRACKER_ROOT` at an isolated tmp root where no sweep
   heartbeat has ever been written, so `sweeps.alive` reports "no heartbeat ever recorded"
   and `doctor` exits 1. Every other assumption in that same run passes, **including all six
   added here**. Evidence: `evidence/parent-commit-doctor-cli-preexisting-failure.log`.
   Filed as **`model_performance-jyg`**.

2. `modules/tool-work-tracker/tests/test_reap_recovery.py::test_explicit_resolve_refusal_after_reap_clears_held_and_allows_new_claim`
   — a post-reclaim `work_resolve` is **not** refused; the close lands at `success=True`.
   This is the ledger's own flagship divergence **CCV1-009** (VIOLATION,
   `work_item_pipeline-dn4`) observed behaviourally: a reap leaves the item `open`, so
   `resolve`'s fence — gated on `status == "held"` — is skipped, and the tool layer's `_held`
   latch lets it through rather than catching it. Evidence:
   `evidence/parent-commit-modules-reap-preexisting-failure.log` (parent) and
   `evidence/modules-suite.log` (with this change). Filed as **`model_performance-c0e`**,
   which also records that ledger row CCV1-023's note ("passes via the session latch") is
   measurably wrong — left untouched here because it is a claim about a different row's
   subject, not drift this change caused.

---

## Deviations from the spec, and why

1. **`resolve()` keeps returning `Item`; the `idempotent` flag lives on a new
   `resolve_outcome()`.** The spec implied a richer return. There are ~30 `bd.resolve(...)`
   call sites across src, contract, and both suites; changing the return type would have
   churned every one of them for a flag two callers need. `resolve()` is now a **one-line
   projection** of `resolve_outcome()` — deliberately pure, so the two entry points cannot
   drift.

2. **`ReopenOutcome.previous_closed_at` is a `datetime`, not a `str`.** The spec's sketch
   said `str`. `Item` parses every bd timestamp into a real `datetime` *at the seam*
   precisely so no caller re-parses one; the JSON surfaces (CLI, tool) `isoformat()` it.

3. **`reopen` clears the stale assignee.** Not in the spec — see measurement 2. Without it
   the deliverable's own round-trip is unreachable for any agent but the original closer.

4. **`defer()`/`block()` refusing a resolved item is NOT in this change.** The spec added it
   late (§1) and filed it as `model_performance-2nx`. It is a *separate destructive path*,
   and the goal named five parts; folding in a sixth would widen a change whose value is
   elsewhere. It remains a real, unfixed hole: both verbs still move a resolved item out of
   `resolved` and blank its resolution at exit 0.

5. **`reopen_count` on read surfaces (spec §2.8's "additionally") is NOT in this change.**
   `reopened_count()` already exists project-wide; surfacing a per-item count on
   `work_list`/the item payload is a read-surface change with its own SQL, and nothing in the
   deliverables asked for it.

6. **The `claiming-work-safely` skill was left alone.** The goal named three doc surfaces
   (`--help`, `cli.py:29`, `context/awareness.md`); all three are updated, and `awareness.md`
   is the always-loaded agent-facing contract. The skill asserts nothing this change makes
   false.

---

## Ledger reconciliation (three rows moved; none absorbed silently)

This change made three probes in `ledger/checks/test_custody_rows.py` fail. All three were
reconciled explicitly, with the reason recorded in each row's `notes`. **No row's disposition
changed**; `contracts/` and `docs/VISION.md` were not touched, so the CCV1-000 SYNC hashes
still hold.

- **CCV1-009** (VIOLATION, post-reclaim close unfenced) — the probe sliced `resolve`'s source
  and matched a literal gate line. The close path grew a pre-write read of its own and the
  fence moved into `resolve_outcome`. Probe re-pointed to follow it and made robust to
  formatting (delimits the pre-write region by the `close` write itself). **Claim re-verified
  and unchanged:** the fence still runs only under `status == "held"`.
- **CCV1-015** (GAP, only resolve/release verify a conflicted write) — count 3 → 4:
  `reopen` adopted the same verify-on-conflict discipline. **Real movement toward the clause,
  recorded rather than absorbed.** Still a GAP: `take_custody`/`renew_custody` remain uncovered.
- **CCV1-023** (GAP, Fixture 4 single-hold asserted nowhere) — now asserted *incidentally* in
  the modules suite, as one branch of `work_reopen`'s claim-degradation path. That suite is
  the one `make test` does not run, so the Freeze Bar clause ("executable via `make test`") is
  still unmet and the row stays GAP. The probe now pins that exact file set, so a real
  dedicated Fixture 4 still flips it.

---

## Spend

**$0.** No API spend, no DTU, no containers, no infrastructure registered or torn down.
Pure code change verified against the already-running local bd/dolt and the suite's own
per-session isolated dolt server. Spend authority for this item was $0 and none was used.

---

## What remains open

- `model_performance-2nx` — `defer()`/`block()` still perform an unaudited, destructive reopen
  of a resolved item at exit 0. This change gives them the safe verb to point at; it does not
  make them use it.
- `model_performance-jyg` (filed by this lane) — the pre-existing `doctor` CLI test failure.
- `model_performance-69y` — the 7-item correction backlog (`dt1`, `ys8`, `xy0`, `1rn`, `df1`,
  `bji`, `44f`) is now **unblocked**: each is one `reopen` → `claim` → `resolve` cycle. Expect
  the 7-day throughput figure to move by up to 7 items as their `closed_at` values are cleared
  — that is the documented, surfaced cost, not a bug.
- Fixture 4 (single-hold) still needs a dedicated, `make test`-runnable fixture; blocked on
  CCV1-022 (the modules suite runs in no CI).
