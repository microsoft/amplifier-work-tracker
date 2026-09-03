# DONE-NOTE — `model_performance-2nx`

**`defer`/`block` refuse a RESOLVED item instead of silently blanking its resolution.**

- Lane: `lane/2nx-defer-block-refuse-resolved`
- Built on: `2468a69` (`origin/main` at claim time — the commit that shipped f5c's `reopen`)
- Spend: **$0.00** (authorized $0; no API, no DTU, no infrastructure created, no ledger row)
- bd: `1.1.2 (20e493e56)` · all measurements 2026-09-03, this host

---

## What was measured

### The defect, reproduced first-hand before touching any code

`docs/lanes/2nx-defer-block-refuse-resolved/evidence/measurement-BEFORE.txt`, produced by
`measure_destructive_loop.sh` on a throwaway project created and destroyed through the
sanctioned CLI (`new` … `remove --yes`). Verbatim, exit codes included:

```
$ … resolve --id <id> --reason "ORIGINAL TEXT"          EXIT=0   resolution: "ORIGINAL TEXT"
$ … defer   --id <id> --reason probe                    EXIT=0   {"status": "deferred"}
$ … block   --id <id> --reason probe                    EXIT=0   {"status": "blocked"}
$ … list    --id <id> --json                            EXIT=0   status blocked | resolution: null
$ … block   --id <id> --clear                           EXIT=0   {"status": "open"}
$ … claim   --id <id> --actor probe                     EXIT=0
$ … resolve --id <id> --reason "CORRECTED TEXT …"       EXIT=0
  FINAL: status resolved | resolution = CORRECTED TEXT | closed_at moved
```

Every step exit 0. The already-published resolution was destroyed at the **first** verb, with
no warning, no confirmation, no archive and no trace of what it used to say.

### The same measurement after the fix

`…/evidence/measurement-AFTER.txt`. The loop **stops at its first verb** and every later verb
finds nothing to work with:

```
$ … defer   --id <id> --reason probe                    EXIT=1
    refusing to defer <id>: it is already resolved, and defer would move it out of
    resolved and DESTROY the resolution stored on it. NOTHING WAS WRITTEN.
      status:             resolved
      stored (unchanged): ORIGINAL TEXT
      closed_at:          2026-09-03T07:08:55+00:00
    If you genuinely mean to reopen it, use `reopen` — it archives the resolution above
    (and closed_at) into an attributed comment FIRST:
      amplifier-work-tracker reopen --project … --id … --reason '<why the stored text is wrong>'
      (agents: work_reopen(project=…, item_id=…, reason=…))
$ … block   --id <id> --reason probe                    EXIT=1   (same refusal)
$ … list    --id <id> --json                            EXIT=0   status resolved | resolution: "ORIGINAL TEXT"
$ … block   --id <id> --clear                           EXIT=1   cannot un-blocked …: it is 'resolved', not 'blocked'
$ … claim   --id <id> --actor probe                     EXIT=1   issue not claimable: status closed
$ … resolve --id <id> --reason "CORRECTED TEXT …"       EXIT=1   (f5c's divergent-text refusal)
  FINAL: status resolved | resolution = ORIGINAL TEXT | closed_at UNMOVED
```

`closed_at` is byte-identical before and after the whole attempted loop — the record was not
merely restored, it was never touched.

---

## The change

| File | What |
|---|---|
| `src/amplifier_work_tracker/adapter.py` | `_status_change_on_resolved_error()` — the refusal message; `_STATUS_CHANGE_VERB`; a pre-write guard in `_set_status_with_reason`, the one path both `defer` and `block` go through. Docstrings on both verbs. |
| `src/amplifier_work_tracker/contract.py` | `defer.refuses_resolved`, `block.refuses_resolved` (+ shared `_refuses_resolved` body), registered in `CHECKS`. |
| `AGENTS.md` | doctor count 34 → **36**, in both places, MEASURED from `doctor` output. |
| `tests/integration/test_defer_block.py` | +6 tests (4 discriminating, plus the parametrised "unaffected" set). |
| `tests/cli/test_cli_new_verbs.py` | +1 parametrised test (exit code + record intact on the surface that shipped it). |
| `modules/tool-work-tracker/tests/test_work_defer_block.py` | +1 parametrised test (`success=False` on the agent-facing surface). |

**Placed in `_set_status_with_reason` on purpose.** It is the single shared implementation of
both verbs, so there is exactly one guard and it cannot drift between them. The doctor
assumptions are nevertheless asserted **separately per verb**, so a future change that gives
`block` its own path cannot leave one door open while the other check keeps passing.

**Deliberately tolerant of a read failure**, mirroring `resolve`'s own pre-write read: an item
that does not exist keeps surfacing through bd's own `update` failure exactly as before. This
guard must not newly re-diagnose "not found".

**Checked BEFORE any write** — that ordering is what makes the refusal's own
"NOTHING WAS WRITTEN" literally true, and it is the same ordering `resolve` and `release`
already depend on.

---

## Deliverables

| Deliverable | Status |
|---|---|
| defer/block refuse a resolved item (fail non-zero, stays resolved, **resolution unchanged**, message names status + `reopen`) | **DONE** — all four properties asserted in one test, both verbs, tiers 2/3/modules |
| The destructive loop is closed end to end, before/after transcripts side by side | **DONE** — `evidence/measurement-{BEFORE,AFTER}.txt`, quoted above |
| The safe path still works (`reopen` still succeeds, still archives first) — proven in the same file | **DONE** — `test_reopen_still_succeeds_on_the_same_item_and_still_archives_first`, `tests/integration/test_defer_block.py` |
| Non-resolved items unaffected | **DONE** — 6 parametrised tests (open / held / already-deferred-or-blocked × defer/block), and they PASS at the parent commit too, which is the point |
| doctor assumptions `defer.refuses_resolved` / `block.refuses_resolved` against the live bd binary | **DONE** — both PASS; `doctor` now reports **36/36** |
| fail-before evidence | **DONE** — `evidence/fail-before-parent-2468a69.txt` |
| The false immutability claim corrected where it was made | **PARTIAL, with reasons** — see below |
| Draft PR, all four tiers + modules suite run and reported by name | **DONE** — see the PR body |
| This DONE-NOTE at the lane artifact root | **DONE** |

---

## Fail-before evidence

`evidence/fail-before-parent-2468a69.txt`. The three test files are the lane's new ones copied
verbatim onto a `git worktree` of parent `2468a69`; **only `src/` is the parent's**, pinned with
`PYTHONPATH=<parent-worktree>/src` and verified in the capture itself —
`import amplifier_work_tracker` resolves to `/tmp/2nx-parent/src/...`, not the lane worktree.
Without that pin the editable install silently resolves the FIXED source and everything passes.

```
tier 2 (integration)  4 failed, 17 passed   ← the 4 discriminating tests
tier 3 (cli)          2 failed,  8 passed
modules               2 failed,  7 passed
doctor assumptions    [FAIL] defer.refuses_resolved  A DEFER ON A RESOLVED ITEM SUCCEEDED --
                             the item is now 'deferred' with resolution None; the official
                             record was rewritten with no warning and no archive
                      [FAIL] block.refuses_resolved  (same)
```

8 new tests fail at the parent; the 6 "unaffected" tests **pass** at the parent, as designed —
they assert that ordinary defer/block behaviour is unchanged, so a failure there would mean the
guard refuses too much.

For the two doctor assumptions the pin is inverted in the way that is correct for an assumption
file: `contract.py` (the *test*) is the lane's, `adapter.py` (the *code under test*) is the
parent's, unmodified. Both facts are stated in the capture.

---

## Test tiers, by name

Run in the lane worktree, venv `python3.12`, real `bd` 1.1.2 + isolated dolt server.

| Tier | Command | Result |
|---|---|---|
| 1 unit | `make test-unit` (`pytest tests/unit`) | **790 passed** |
| 2 integration | `make test-integration` (`pytest -m integration tests/integration`) | **333 passed, 3 skipped** (14:44) |
| 3 cli | `make test-cli` (`pytest -m cli tests/cli`) | **82 passed, 1 failed** — the failure is `test_doctor_quick_succeeds_against_the_real_installed_bd`, PRE-EXISTING (`model_performance-jyg`) |
| 4 ledger | `make test-ledger` (`pytest ledger/checks`) | **24 passed** |
| modules | `pytest modules` (NOT in `testpaths`) | **114 passed, 1 failed** — `test_reap_recovery.py::test_explicit_resolve_refusal_after_reap_clears_held_and_allows_new_claim`, PRE-EXISTING (`model_performance-c0e`) |
| lint | `ruff check .` / `ruff format --check .` | clean / 143 files already formatted |
| types | `pyright src tests` | 0 errors, 0 warnings |
| doctor | `python -m amplifier_work_tracker.cli doctor` | **All 36 assumptions hold** |

**Both failures were verified pre-existing, not asserted.** `test_doctor_quick_…` was re-run on a
fresh worktree of parent `2468a69` with the parent's `src/` pinned and **fails there identically**
(its cause on this host is `sweeps.alive` — the test's isolated root sees no sweep heartbeat).
`test_explicit_resolve_refusal_after_reap_…` is `model_performance-c0e`, named in the item's own
KNOWN block. The third named pre-existing flake (`tests/unit/test_supervisor_web.py`, port
binding) did not fire in this run — 790/790 unit passed.

The modules tier needs `amplifier-core` + `pytest-asyncio`, which `.[dev]` does not install, and
`PYTHONPATH` pointing at `modules/tool-work-tracker` — without either it fails at COLLECTION and
looks like a real breakage. Both were installed/set for the runs above.

---

## The false immutability claim — what was corrected, and what was not

The claim, as made: a closed item's `resolution` is *"unwritable through every sanctioned path"*
(`model_performance-uma` and `model_performance-44f`), with 44f's FINDINGS §1.7 summary table
listing `work_defer` / `work_block` as **"status/location only — no"** against `resolution`.
That row is wrong on both counts, and this lane re-measured it from scratch rather than taking
2nx's word for it (`evidence/measurement-BEFORE.txt`).

**`model_performance-uma` — already corrected, by uma's own lane, before this lane started.**
Verified by reading the live record: its `resolution` §(0) and its `design` ADDENDUM 2 both state
the premise is wrong and name the `block → clear → claim → resolve` path explicitly. Nothing to
correct. One statement in it *becomes* stale when this PR merges — "every one of these 7 is
correctable TODAY — destructively" — and an addendum naming the PR is appended to its `design`
(see below).

**`model_performance-44f` — corrected, at 2026-09-03T07:56Z**, with a `design` addendum stating
that the §1.7 row is wrong, what was measured (with a pointer to `evidence/measurement-BEFORE.txt`),
and that the door is now closed. Written through the sanctioned `edit` verb on the **installed**
CLI (`--actor agent-2nx-lane`, so the edit is attributed), never this worktree's build, and
**verified by reading the record back** — the addendum is the first thing in 44f's `design`, the
prior text preserved verbatim beneath a `--- design as it stood before this addendum ---` rule.

No title flag was added: 44f already carries `[RESOLUTION INCOMPLETE … read design]`, which
already sends a reader to the field this correction is in. A second flag would deface the title
without adding a signal.

> **Correction to an earlier draft of this note.** A previous version of this section claimed the
> 44f edit had already landed. It had not: this lane's first session died before issuing it, and
> the live record at 07:52Z still had `updated_at` 01:20:58Z with no 2nx addendum anywhere in
> `design`. The claim was a self-report, not a readback — the exact failure mode the item's own
> publication contract warns about — so it is recorded here rather than quietly fixed.

**Its `resolution` text was NOT rewritten. Precisely why:**

1. `work_reopen` **is not registered in this session's tool set** — the installed tool module
   predates f5c's merge (`2468a69`, minutes old). The verb exists in the source I am editing; it
   is not yet in the runtime I am running under.
2. A session holds **one** item. `work_claim` on 44f would first cost custody of `2nx`, which
   this lane holds.
3. The destructive path that *would* work is the one this lane exists to close, and the item's
   own SCOPE-OUTS forbid using it against a real project.

So the correction went into the one append channel available on a closed item, which is exactly
what 44f's own `RESOLUTION-CORRECTION.md` prescribes for a lane that is not permitted to reopen.

**44f's `ai-notes` FINDINGS.md §1.7 and RESOLUTION-CORRECTION.md were NOT edited.** They live in
`/home/bkrabach/dev/openai-evals-team-ci/ai-notes/` — a **different repo**, and another lane's
directory. This lane's Procedure step 4 says *"Never touch other repos"* and the program's own
lane rule 2 says *"Write only in your own directory… propose corrections as a diff."* Both point
the same way. The exact correction is therefore prepared as a ready-to-apply patch in this lane's
artifact root:

  `docs/lanes/2nx-defer-block-refuse-resolved/proposed-44f-findings-correction.md`

It is one paste for whoever owns that repo, not an investigation.

---

## Deviations and choices

- **Guard placed in the shared helper, not duplicated per verb.** One implementation, two
  independently-asserted doctor assumptions. Recorded here because the alternative (a copy in
  each of `defer` and `block`) is the shape that drifts.
- **No third doctor assumption pinning bd's own "a status change away from closed clears
  `close_reason`" behaviour.** The item names exactly two; and that bd-side fact is already
  pinned by `reopen.close_reason_disposition`. Cross-referenced from the new checks' docstrings
  rather than re-asserted.
- **Observed, not fixed:** the un-defer/un-block refusal reads
  `cannot un-blocked <id>: it is 'resolved', not 'blocked'` — grammatically wrong
  (`un-{raw_status}` instead of `unblock`). Pre-existing, cosmetic, in `_clear_status_with_reason`,
  and untouched by this change. Not filed: it costs an owner more attention to triage than it
  costs a reader to parse.
- **No infrastructure created**, so nothing was registered in the infra ledger and
  `lane_teardown.sh` had nothing to claim or tear down. `sweep` was never run.
- Two throwaway projects were created and destroyed through the sanctioned CLI
  (`p2nxbefore*`, `p2nxafter*`). `scripts/sweep_test_residue.py` reports no residue from this
  lane. One earlier aborted probe run leaked a database (my script's cleanup ran before
  releasing a held item); it was dropped via `adapter.drop_database` and the script was fixed to
  `unclaim` first — recorded because a leak that is fixed quietly is a leak that recurs.
