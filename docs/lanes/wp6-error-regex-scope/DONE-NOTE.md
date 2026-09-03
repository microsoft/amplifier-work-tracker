# DONE-NOTE — `model_performance-wp6`

**Lane:** `wp6-error-regex-scope`
**Branch:** `lane/wp6-error-regex-scope`, built on `origin/main` = `ea233a76a00f087e1096f7251b60323bd65b84ea`
("highway wave 2: Conformance Fixtures 2/3/4 + Ruling-1 conditions", #71)
**Scope:** option (2) only — tighten `tests/_util.py`'s `assert_no_silent_failure` to real error
ANNOUNCEMENT shapes. Option (1), the parseable-channel redesign of `doctor`'s output, was **not
taken**; see "Why option (1) was NOT taken" below.
**Spend:** **$0.00** of a **$0.00** authority. No API calls, no DTU, no infrastructure created,
nothing to tear down. Everything below is local `git`, `pytest`, `uv`, and the already-installed
`bd`.

---

## Result

**OUTCOME branch A — RESOLVED.** Every deliverable is DONE. No deliverable was recorded
NOT-POSSIBLE, and the cap never bound (there was nothing to buy).

The predicate is now announcement-shaped, the guarantee is proven still standing by tests that
FAIL if it is retired, and the exact bytes that block PR #70 were reproduced locally and shown to
stop tripping the check.

---

## The defect, restated from the evidence

`assert_no_silent_failure` used `re.compile(r"\berror\b", re.IGNORECASE)`. That is not a test for
an error being **emitted**; it is a test for the word appearing. `doctor` prints every
assumption's own DESCRIPTION on a healthy run, so in a catalogue whose entire subject matter is
error handling, one honest sentence turns a green run red.

Reproduced locally against PR #70's own head (`20557bc`), `doctor --quick`, exit code **0**:

```
  [PASS] read.unavailable_not_absent         an infrastructure read failure raises
  BeadsUnavailableError with its cause intact on read/claim and reports UNAVAILABLE
  (not ERROR) per project, while genuine absence on a healthy database still reports
  plain 'not found'
```

`\berror\b` matches `ERROR` at **offset 302** of the combined stdout+stderr (offset 99 within that
row) → `assert_no_silent_failure` raises → `test_doctor_quick_succeeds_against_the_real_installed_bd`
FAILS on a completely healthy system. That is the CI failure blocking #70, reproduced.

---

## The fix

`tests/_util.py` now matches five **announcement** shapes instead of one word. Every shape is
justified by output this repository actually emits — none is a guess:

| shape | pattern | why it is here |
|---|---|---|
| `error-colon` | `\berror\s*:` | `Error: unknown command "reclaim"` (the shipped `reap` bug this tier is named for); `ERROR: <cause>`, `adapter.py`'s own status for an unreadable project, as `instances` renders it in a table column; `ERROR: tokens file not found` (`gateway.py:141`); the argparse/cobra `<prog>: error: <msg>` shape. Deliberately **not** anchored to line start — a real announcement is routinely preceded by a program name, a log prefix, or a column. |
| `json-error-field` | `"error"\s*:\s*(?!null\|""\|[]\|{})\S` | `supervisor.py:177,189` writes `{"error": str(e)}` into payloads the CLI prints. `{"error": "boom"}` beside exit 0 is exactly this tier's invariant. A null/empty value is the "no error" reading of the same field and is deliberately **not** matched. |
| `error-running` | `\berror\s+running\b` | An announcement with no colon; named in the item. |
| `unknown-command` | `\bunknown command\b` | The shipped bug's own words, kept as a shape in its own right so the guard survives the announcement prefix changing. **New coverage** — contains no "error". |
| `python-traceback` | `^Traceback \(most recent call last\):` | A Python crash printed while exiting 0 is the same silent failure in different clothes. **New coverage** — contains no "error". |

`error_announcement()` returns `(shape_name, matched_text)`, and `assert_no_silent_failure` puts
both into the assertion message. That is not decoration: it is what lets a reader of a CI failure
tell a real announcement from a false positive without re-deriving the regex.

**Net direction, stated honestly: this is not purely a loosening.** Two of the five shapes
(`unknown-command`, `python-traceback`) are strictly NEW coverage the parent commit did not have.

---

## Deliverables

| # | Deliverable | State |
|---|---|---|
| 1 | Regex narrowed to announcement shapes; an assumption description containing "error" in prose no longer fails on a healthy system | **DONE** |
| 2 | The guarantee is NOT retired — a test proves `Error: unknown command "reclaim"` + exit 0 STILL fails | **DONE** |
| 3 | Fail-before test: fails on the parent commit, passes on the fix, both outputs pasted | **DONE** |
| 4 | #70's REAL description text is the innocent-case fixture | **DONE** |
| 5 | Report whether #70 would now pass, with evidence | **DONE** — verdict: **it would** |
| 6 | All documented tiers + the modules suite, run and reported BY NAME | **DONE** — 1 pre-existing failure, not this lane's (below) |
| 7 | Fail-before evidence committed under the artifact root and pasted in the PR body | **DONE** |
| 8 | DRAFT PR on `origin`, branch `lane/wp6-error-regex-scope` | **DONE** |
| 9 | DONE-NOTE at `docs/lanes/wp6-error-regex-scope/DONE-NOTE.md` | **DONE** (this file) |

### Deliverable 2 in detail — the one that can be faked

A fix that makes everything pass has deleted the guard, not repaired it. So the regression file
asserts the guilty direction with **ten parametrised rows** plus three assertion-level tests, and
every one of them fails loudly if the shape stops being detected:

```
'Error: unknown command "reclaim"'                                            <- THE shipped bug
'reaping stale holds...\nError: unknown command "reclaim"\n'                  <- as it appeared
'  brokenqueue  TOTAL - READY - HELD -  ERROR: database unreachable'          <- adapter.py status
'ERROR: tokens file not found: /etc/awt/tokens.json'                          <- gateway.py
'amplifier-work-tracker: error: unrecognized arguments: --nope'               <- argparse
'internal error: connection reset by peer'
'{"custody": {"error": "dolt: connection refused"}}'                          <- supervisor.py
'error running bd list --json'
'unknown command "reclaim" for "bd"'                                          <- NEW coverage
'Traceback (most recent call last):\n  File "cli.py", line 1\n'               <- NEW coverage
```

**Eight of those ten pass on the parent commit AND on the fix** (see the fail-before run) — which
is the actual proof that the guarantee survived the narrowing, rather than an assurance that it
did.

Both directions live in **one file** on purpose, per the acceptance criteria. The failure mode
being fenced is not "too strict" or "too loose" — it is the two collapsing into each other. Split
across two files, one half can be deleted without the other noticing.

### Why the regression test is TIER 1, not tier 3

Deliberate, and it is the trap the item warned about. The tier-3 test that surfaced this
(`test_doctor_quick_succeeds_against_the_real_installed_bd`) **cannot reach**
`assert_no_silent_failure` on this machine: `tests/conftest.py:308` repoints
`AMPLIFIER_WORK_TRACKER_ROOT` at a session-scoped tmp root, so `sweeps.alive` FAILs, `doctor`
exits 1, and the test dies at the EARLIER `assert result.returncode == 0`. That is
`model_performance-jyg`. I tried to bypass it by exporting the real root — `run_cli` uses
`setdefault`, so the monkeypatched value already wins; the attempt and why it cannot work are
recorded in `evidence/jyg-cannot-be-bypassed-from-outside.txt` rather than dropped.

A tier-1 test of the predicate itself needs no `bd`, no dolt, and no healthy sweeps, so it cannot
be masked that way. The end-to-end evidence was obtained instead by running `doctor --quick`
directly, outside pytest, against the real root — where it does exit 0.

---

## Fail-before / fail-after

Full output: `evidence/fail-before.txt` (committed).

**Parent commit `ea233a7` — `tests/_util.py` restored to the bare `\berror\b`, this lane's new
test file in place:**

```
$ .venv/bin/python -m pytest tests/unit/test_error_announcement_detection.py -q
...
FAILED tests/unit/test_error_announcement_detection.py::test_pr70_description_is_prose_not_an_announcement
FAILED tests/unit/test_error_announcement_detection.py::test_healthy_doctor_run_carrying_pr70s_description_is_not_a_silent_failure
FAILED tests/unit/test_error_announcement_detection.py::test_mentioning_errors_is_not_announcing_one[reports UNAVAILABLE (not ERROR) per project]
FAILED tests/unit/test_error_announcement_detection.py::test_mentioning_errors_is_not_announcing_one[this command never reports an error it did not observe]
FAILED tests/unit/test_error_announcement_detection.py::test_mentioning_errors_is_not_announcing_one[ERROR and UNAVAILABLE are different readings of the same field]
FAILED tests/unit/test_error_announcement_detection.py::test_mentioning_errors_is_not_announcing_one[{"ok": true, "error": null}]
FAILED tests/unit/test_error_announcement_detection.py::test_mentioning_errors_is_not_announcing_one[{"ok": true, "error": ""}]
FAILED tests/unit/test_error_announcement_detection.py::test_real_error_announcements_are_still_caught[unknown command "reclaim" for "bd"]
FAILED tests/unit/test_error_announcement_detection.py::test_real_error_announcements_are_still_caught[Traceback (most recent call last):\n  File "cli.py", line 1\n]
FAILED tests/unit/test_error_announcement_detection.py::test_the_failure_message_names_which_shape_fired
10 failed, 13 passed in 0.24s
```

Read that list carefully — it is the whole argument:

* the **first seven** failures are the defect: prose classified as an emitted error, including #70's
  real sentence;
* the **next two** are NEW coverage the old predicate never had;
* the **last** is the new shape-naming API;
* and the **13 that pass** include eight of the ten real error announcements — the guarantee,
  already standing on the parent, and still standing after.

The assertions are written against `looks_like_error_text` / `assert_no_silent_failure` — the API
that existed BEFORE this change — precisely so this run reports the real diagnosis instead of an
`AttributeError` on a helper that did not exist yet.

**This branch:**

```
$ .venv/bin/python -m pytest tests/unit/test_error_announcement_detection.py -q
23 passed in 0.22s
```

---

## Would PR #70 now pass?

**Yes, on the evidence available without merging anything.** Full detail:
`evidence/pr70-would-now-pass.txt`, with the raw captures beside it.

Method — a real run, not a synthetic fixture:

1. `git worktree add /tmp/wp6-pr70 origin/pr-70` (head `20557bc5bde2f3983615f30494234bf71510dba1`)
2. its own `uv venv` + `uv pip install -e ".[dev,web]"`
3. `.venv/bin/python -m amplifier_work_tracker.cli doctor --quick` against the **real** workspace
   root, so `sweeps.alive` passes — i.e. the healthy-CI condition, **not** the jyg-masked one
4. exit code **0**, 35 rows, tail `All 35 assumptions hold. Safe to run parallel agents.`
5. both predicates applied to those exact bytes

| predicate | result |
|---|---|
| parent `\berror\b` | **MATCH** — `ERROR` at offset 302 → `assert_no_silent_failure` raises → the test FAILS. **The CI failure that blocks #70, reproduced.** |
| this branch | **no announcement found** → does not raise → the silent-failure check **PASSES** |

**What this does NOT prove**, stated plainly: it does not re-run #70's CI (nothing was merged),
and it does not touch `model_performance-jyg` — on a machine whose sweep heartbeats live outside
the isolated test root, that same test still dies earlier at `assert result.returncode == 0`. The
run above deliberately went around pytest to get past jyg.

---

## Test tiers actually run, honestly

All in `.venv` created by `make venv`, which installs both `.[dev,web]` and
`modules/tool-work-tracker[dev]` — so the modules tier did not silently fail at COLLECTION.
Raw logs under `evidence/`.

| tier | command | result | log |
|---|---|---|---|
| 1 — unit | `make test-unit` | **813 passed** in 45.5s | `evidence/tier-unit.txt` |
| 2 — integration | `make test-integration` | **354 passed, 3 skipped** in 17m52s | `evidence/tier-integration.txt` |
| 3 — cli | `make test-cli` | **80 passed, 1 failed** in 6m56s — the failure is `jyg`, see below | `evidence/tier-cli.txt` |
| 4 — conformance ledger | `make test-ledger` | **26 passed** in 0.6s | `evidence/tier-ledger.txt` |
| 4b — ledger mutation harness | `make ledger-mutate` | **exit 0**, no unproven holes | `evidence/ledger-mutate.txt` |
| 5 — modules (`modules/tool-work-tracker/tests`) | `make test-module` | **113 passed** in 7m32s | `evidence/tier-modules.txt` |
| lint + types | `make check` | ruff check clean, 149 files formatted, **pyright 0 errors** | `evidence/check.txt` |

### The one failure, and why it is not mine

`tests/cli/test_cli_surface.py::test_doctor_quick_succeeds_against_the_real_installed_bd` fails
here — at the **earlier** assertion, before `assert_no_silent_failure` is ever called:

```
>       assert result.returncode == 0, result.stdout + result.stderr
E           [FAIL] sweeps.alive   no heartbeat ever recorded for the reap sweep loop ...
E       assert 1 == 0
```

Proven pre-existing by re-running that single test with `tests/_util.py` restored to the parent
commit (`evidence/jyg-preexisting.txt`): **`1 failed in 46.35s`**, identical signature. This is
`model_performance-jyg` — separately filed, separately owned, explicitly out of scope.

The two other known non-mine failures named in the item did **not** reproduce in these runs:
`model_performance-c0e` (modules reap-recovery) passed, and the `tests/unit/test_supervisor_web.py`
port-binding flake did not fire. Reported as observed; not claimed as fixed.

---

## Why option (1) was NOT taken

Option (1) — have `doctor` emit assumption descriptions on a channel the check can exclude (e.g.
filtering `  [PASS]` / `  [FAIL]` lines, or a `--json` surface the test consumes instead) — is
**not implemented here, and I am not recommending it be bundled into this change.**

Three reasons, in order of weight:

1. **The item pins scope to option (2) and says so twice.** The owner decision dated 2026-09-03 is
   explicit: do option (2) now, file option (1) as a follow-up, do not do it here.
2. **It is a change to `doctor`'s output contract, not to a test helper.** This lane's entire diff
   is two files under `tests/`. Option (1) touches `cli.cmd_doctor`'s printing, and anything
   parsing that output — a materially larger blast radius, on a surface the owner has not ruled on.
3. **It would not have been sufficient on its own.** The evidence run turned up a genuine
   `Error:` announcement arriving on **stderr from `bd` itself**, underneath a `doctor` run that
   healed the condition and exited 0 (filed as `model_performance-kxk`, below). Filtering
   `doctor`'s own `[PASS]` rows would not have excluded that; a shape-aware predicate is needed
   regardless of whether the channel is redesigned. Option (1) and option (2) are complements, not
   alternatives.

**I did not conclude option (1) is necessary**, so there is nothing to stop for: option (2) fully
clears the blockage on #70, as demonstrated above. If option (1) is later built, this predicate
stays useful and can be narrowed further at that point.

---

## Discovered work, filed not absorbed

**`model_performance-kxk`** — *doctor/bd: a HEALED dirty-schema migration still leaks bd's own
`Error:` line to stderr while exiting 0*, filed `discovered-from` wp6.

Observed once (did not reproduce on the immediately following run) during the #70 evidence run:

```
project 'contract1788423815748rm': bd init hit a dirty schema migration -- dropping and
  retrying once: [mysql] 2026/09/03 01:25:03 connection.go:214 busy buffer
Error: failed to open Dolt store: failed to initialize schema: schema migration: pending
  schema migrations alter pre-existing dirty tables: comments, compaction_snapshots, ...
```

…with stdout ending `All 35 assumptions hold` and **exit 0**. The recovery path works; bd's own
announcement is simply passed through underneath it. Both the old predicate and this branch's flag
that — **correctly**, by the letter of the invariant. It is a real intermittent CI-flake source for
any `tests/cli` test funnelling through `assert_no_silent_failure`, it is not caused by #70's
description, and it is a product-side output-contract question rather than a test-regex one. Raw
capture: `evidence/pr70-doctor-quick.run1-transient.stderr.txt`.

---

## Deviations from the spec

1. **The regression test is tier 1, not tier 3.** The acceptance criteria ask for "a regression
   test [that] covers both cases in the same file"; it does not name a tier. Tier 1 was chosen
   because tier 3 is structurally unable to reach the assertion on any machine with jyg present —
   reasoning and the failed bypass attempt are both recorded above. The tier-3 test is left
   untouched.
2. **Two shapes added beyond a pure narrowing** (`unknown command`, `Traceback`). Both are named
   in the item text / owner decision, both strengthen the guard, and neither can produce the #70
   false positive. Called out rather than slipped in.
3. **A JSON `"error": <non-empty>` shape was added** which the item did not name. Justification:
   `supervisor.py` writes `{"error": str(e)}` into printed payloads, so the parent predicate DID
   cover that real shape via `\berror\b`, and a colon-only rule would have dropped it — this
   preserves existing coverage rather than adding new scope. Also called out rather than slipped in.
4. **Nothing was reworded in any assumption description**, per the scope-out. The trap is in the
   predicate, not in #70's prose.

---

## Spend

| item | amount |
|---|---|
| Authority for this item | **$0.00** (pure code change; no runs to buy) |
| API spend | **$0.00** |
| DTU / infrastructure spend | **$0.00** |
| Infrastructure created | **none** — nothing registered in the ledger, nothing to tear down |

The `$0` cap is stated as a bare figure rather than as arithmetic, and the authoring rule in the
goal asks for `runs x arms x per-run estimate / validity rate`. **That is not a defect here**: the
rule governs a *run-buying* deliverable, and this item buys no runs. The arithmetic closes
trivially — `0 runs x $0 = $0` — and every deliverable landed inside it. Recorded for completeness,
not raised as a finding.

Cost incurred that is not dollars: ~35 minutes of wall clock across the integration (17m52s),
modules (7m32s) and cli (6m56s) tiers, plus one throwaway `uv venv` for the #70 worktree.

---

## What remains open

1. **`model_performance-jyg`** — the tier-3 doctor test cannot reach its own silent-failure check
   on any machine whose sweeps live outside the isolated root. Untouched; separately owned. Until
   it is fixed, tier 3 is red locally for everyone, and the wp6 defect would have been invisible
   there.
2. **`model_performance-kxk`** — the healed-but-still-announced `Error:` leak, filed above.
3. **Option (1)** — the parseable-channel redesign of `doctor`'s output. Not filed by this lane
   (the owner decision says to file it as a follow-up; I did not want to duplicate an item the
   owner may already have opened). Recommended, on the evidence, as a **complement** to this
   change rather than a replacement for it.
4. **`panic:`** — a Go panic from `bd` is an announcement shape this predicate still does not
   match. Not added, because neither the item nor the owner decision named it and I would rather
   name the gap than widen scope unasked. Widening this list is cheap and safe; narrowing it is
   what retires a guarantee.
