# kxk — a HEALED dirty-schema migration must not leak bd's `Error:` line while exiting 0

Item: `model_performance-kxk` (project `model_performance`), discovered-from `model_performance-wp6`.
Branch: `lane/kxk-healed-migration-stderr`. Repo: `microsoft/amplifier-work-tracker`.
Spend authority: **$0** (pure code change). **Actual API/DTU spend: $0.00.** No infrastructure
created, so no `infra_ledger.sh` row and no teardown.

**Outcome: branch A — RESOLVED.** Every deliverable is DONE. Nothing was dropped, and the cap never
bound (there was nothing to buy: the whole item is a code change, and the reproduction turned out to
need no runs at all — see below).

---

## The finding that changed the fix

The item, and the goal, both describe the leak as bd's stderr being "passed straight through"
underneath our own log line. **That is not what happens, and it matters, because it makes the fix
smaller and the reproduction free.**

The `Error:` line is **inside our own `logger.warning`**. `Workspace.create`'s dirty-schema self-heal
interpolated `blob.strip()[:300]`, and `blob` is bd's **multi-line** stderr — so the second line of
that quoted blob became the second line of *our* stderr, where it reads as this program's own
announcement.

Proof, taken from the committed evidence rather than from reasoning
(`docs/lanes/wp6-error-regex-scope/evidence/pr70-doctor-quick.run1-transient.stderr.txt`, on main):
the quoted text spanning those two lines is **exactly 300 characters** and stops mid-sentence at
`run 'bd dolt commit' to` — the slice boundary, not a line bd chose to end there.

```
$ python3 - <<'PY'
lines = open('.../pr70-doctor-quick.run1-transient.stderr.txt').read().split('\n')
blob = lines[0].split('retrying once: ',1)[1] + '\n' + lines[1]
print(len(blob))          # -> 300
PY
```

Consequence: **the leak never needed a dirty dolt store.** It needed bd to hand `create()` that blob
once. That is scriptable, so the "hard part" the goal flagged — *"observed ONCE and not on the
immediately following run"* — dissolved. The reproduction is deterministic, tier 1, no bd, no dolt,
no network, no spend.

## What changed

`src/amplifier_work_tracker/adapter.py`

* New `_quote_handled_output(blob)` — for quoting **another program's output on a path this module
  handled and recovered from**. Two narrow transformations:
  1. **Flatten to one line.** A multi-line quote puts `Error:` at the start of a line of *our*
     stderr, which is precisely where a reader (or a log scraper) reads it as ours.
  2. **Attribute instead of assert.** `Error:` → `[bd Error]`. The word survives (people grep for
     it), the detail survives (still diagnostic), only the impersonation ends.
  Truncation moves from the bare `[:300]` slice to the existing `truncate_status` — word boundary,
  explicit `...[truncated]` marker — which is the same fragment problem that helper already solved.
* Applied at **both** handled call sites in the file: the dirty-schema self-heal in
  `Workspace.create` (the reported one) and the best-effort cleanup of a partially-moved item in
  `move_item`, which quoted a foreign blob the same way on a path whose caller continues. Same
  defect, same file, one helper. Named here rather than done silently.

**Deliberately not merged with `_clean_bd_error`.** That one builds the text of a real `BeadsError`
on its way to a non-zero exit, which *should* announce loudly. The failure path is untouched, and a
test pins that bd's own announcement still reaches stderr there.

Before / after, on the verbatim recorded blob:

```
BEFORE (two lines of our stderr; line 2 announces):
  project 'contract...rm': bd init hit a dirty schema migration -- dropping and retrying once: [mysql] ... busy buffer
  Error: failed to open Dolt store: failed to initialize schema: ... run 'bd dolt commit' to

AFTER (one line; attributed; word-boundary truncation):
  project 'contract...rm': bd init hit a dirty schema migration -- dropping and retrying once: [mysql] ... busy buffer [bd Error] failed to open Dolt store: failed to initialize schema: ... run 'bd dolt ...[truncated]
```

`tests/unit/test_handled_output_is_not_an_announcement.py` (13 tests) drives the **real**
`Workspace.create` heal path with a scripted `bd init`, and reconstructs what a plain CLI invocation
would put on stderr from `record.getMessage()` — which is literally what Python's handler of last
resort writes, since it has no formatter. Both directions live in that one file, for the reason
wp6's own file gives for the same choice.

## Deliverables

| Deliverable | State | Evidence |
|---|---|---|
| A healed migration leaves no error announcement on stderr; the `dropping and retrying once` line survives | **DONE** | `test_a_healed_dirty_migration_leaves_no_error_announcement` asserts *all four*: heal happened (2 `bd init` calls), recovery line present, bd's detail present, `error_announcement(...) is None`, and `assert_no_silent_failure` passes on the healed stderr beside exit 0 |
| A migration that genuinely FAILS still announces loudly and exits non-zero | **DONE** | `test_a_migration_that_really_fails_still_raises` (raises `BeadsError`, retry still attempted, `error_announcement(...) is not None`, `[bd ` absent) and `test_a_migration_that_really_fails_exits_non_zero_and_announces` (`cmd_new` → `die` → exit 1, announcement present on stderr, `assert_no_silent_failure` correctly does **not** fire) |
| Fail-before: reproduce the leak, flag it on the parent, not flag it after | **DONE — and deterministic** | `evidence/fail-before.txt` (10 failed / 3 passed on the parent), `evidence/fail-after.txt` (36 passed) |
| wp6's guarantee is not weakened | **DONE** | `tests/unit/test_error_announcement_detection.py` — 23 tests, all green, unmodified. `tests/_util.py` untouched (`git diff --stat` shows it is not in the change) |
| All four documented tiers + the modules suite, BY NAME | **DONE (one known-not-mine failure)** | table below |
| DRAFT PR on origin (`lane/kxk-healed-migration-stderr`) | **DONE** | see `publication` in `DONE.json` — values read back from the remote, not from local `git log` |
| DONE-NOTE.md at `docs/lanes/kxk-healed-migration-stderr/` | **DONE** | this file |

### Was the repro deterministic?

**Yes — fully, and with no spend.** This is a stronger answer than the goal expected, and it is
because of the root-cause finding above: reproducing the *leak* never required reproducing the *dirty
store*. Run against the parent commit, the new test fails with:

```
AssertionError: a handled, recovered condition republished an error announcement:
('error-colon', 'Error:') in "project 'kxkheal': bd init hit a dirty schema migration --
dropping and retrying once: [mysql] 2026/09/03 01:25:03 connection.go:214 busy buffer\nError:
failed to open Dolt store: ... labels; run 'bd dolt commit' to"
```

Note the reproduced string ends at `run 'bd dolt commit' to` — the **same 300-character cut** as the
recorded incident. It is the recorded leak, not a lookalike.

What is *not* claimed: no run in this lane produced a genuinely dirty dolt store. The end-to-end
`doctor` run below is green and never entered the heal path, so it corroborates nothing about the
fix and is recorded only for the two things it does prove (below). The guarantee rests on the
deterministic tier-1 test of the real product path.

## Test tiers, by name

| Tier | Command | Result |
|---|---|---|
| 1 — unit | `make test-unit` | **846 passed** (43.6 s) |
| 2 — integration | `make test-integration` | **367 passed, 3 skipped** (15 m 55 s) |
| 3 — cli | `make test-cli` | **88 passed, 1 failed** — the failure is `model_performance-jyg`, see below |
| 4 — ledger | `make test-ledger` | **26 passed**; `make ledger-mutate` → **proven 15 / 15**, none unproven |
| 5 — modules | `make test-module` | **115 passed** (6 m 31 s) |
| lint/types | `make check` | ruff clean (157 files formatted), pyright **0 errors** |

**The tier-3 failure is `model_performance-jyg`, and that was verified rather than asserted.**
`test_doctor_quick_succeeds_against_the_real_installed_bd` dies at
`assert result.returncode == 0` — the *earlier* assertion — because `[FAIL] sweeps.alive` reports
`no heartbeat ever recorded for the reap sweep loop`. It never reaches `assert_no_silent_failure`.
The cause is environmental: the test's isolated root has no sweep heartbeats. Running the same
command on this branch's code against the **real** workspace root
(`evidence/doctor-quick-real-root.txt`):

```
  [PASS] sweeps.alive   reap sweep completed 97s ago (threshold 900s); notify sweep completed 117s ago (threshold 900s)

All 37 assumptions hold. Safe to run parallel agents.
--- exit=0 ---
```

**37/37, measured, not computed** — and `error_announcement()` over that entire captured output
returns `None`. Two things that proves: the tier-3 failure is the environment, not this change; and
this branch's `doctor` emits no announcement on a healthy run. (It proves nothing about the heal
path, which it did not enter.)

`model_performance-c0e` (modules reap-recovery) and the `test_supervisor_web.py` port-binding flake
did **not** fire in these runs. Neither was chased.

## Deviations and choices recorded

1. **Direction (1), as the goal preferred** — re-label bd's stderr on the heal path. Direction (2),
   wp6's parseable-channel redesign, was **not** implemented and is **not** required: the root cause
   is our own interpolation, so there is no channel-separation problem to solve here. That remains an
   open owner-level output-contract question, untouched.
2. **`tests/_util.py` was not widened, narrowed, or edited.** The fix is entirely product-side, as
   the scope-out demanded.
3. **Second call site fixed too** (`move_item`'s best-effort cleanup). Same defect class, same file,
   same helper — declared here rather than slipped in.
4. **The defusal covers all five shapes in `_util._ERROR_ANNOUNCEMENT_RES`, not just the observed
   one.** Product code cannot import a test helper, so the coupling is closed from the test side:
   `test_every_known_announcement_shape_has_a_sample` goes red if a shape is ever added to the
   predicate without a matching defusal sample. Widening the predicate later cannot silently outrun
   the product fix.
5. **The goal's authoring rule on cap arithmetic does not apply** — the authority is `$0` for a pure
   code change with no run-buying deliverable, so there is no `runs × arms × per-run` arithmetic to
   show and none to check. No residue, nothing unspendable, no branch-B condition.
6. Did not widen into `jyg` or `c0e`.
