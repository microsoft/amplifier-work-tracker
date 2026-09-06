# DONE-NOTE — lane `jyg-doctor-sweep-heartbeat`

Item: `model_performance-jyg` — *"tests/cli doctor test fails on any machine
whose sweep heartbeats live outside the test root (pre-existing)."*

Repo: `microsoft/amplifier-work-tracker`, branch `lane/jyg-doctor-sweep-heartbeat`.

**OUTCOME: branch A — RESOLVED.** Every deliverable is DONE. Spend **$0.00**
against a **$0.00** authority (`0 runs x 0 arms x $0 / 1.00 = $0.00`); this was
a pure code/test change and nothing needed buying. No infrastructure created,
so no ledger rows to claim or tear down.

---

## 1. The answer to the question the goal said to settle first

**The goal asked: is `sweeps.alive` a legitimate assumption to evaluate against
an isolated test root at all?**

Neither of the two framings offered is quite right. The assumption is
**correct**; the test is **not wrong** either. What is wrong is a **scope
mismatch inside the check itself**, and it is visible in the source without
running anything:

`cli._check_sweeps_alive` joins two facts of **different scope**:

| fact | scope | source |
|---|---|---|
| "the service is installed and active" | **host** — one singleton `--user` unit | `service.describe_service()` |
| "this root has a fresh sweep heartbeat" | **per workspace root** — one file per root | `heartbeat.heartbeat_path(root)` (`cli.py`, `results.append(_check_sweeps_alive(_ws(a).root))`) |

That join is only sound when the two refer to the **same root**. It never
checked. `doctor` runs against whichever root it was pointed at
(`AMPLIFIER_WORK_TRACKER_ROOT`, `--root`), while the heartbeat is written by
the supervisor under the root **it** was given. Against any other root the
heartbeat file is absent **by construction** — the supervisor was never asked
to write one there — so its absence proves nothing about the loops.

Measured on this host:

```
$ grep ExecStart ~/.config/systemd/user/amplifier-work-tracker.service
ExecStart=/home/bkrabach/.local/bin/amplifier-work-tracker serve \
    --root /home/bkrabach/.amplifier-work-tracker  ...
```

The unit serves `/home/bkrabach/.amplifier-work-tracker`. The suite's
`workspace_root` fixture (`tests/conftest.py:299`) points every `run_cli` call
at a fresh `tmp_path_factory` root. Two different roots, one singleton service,
no check between them.

**So: `sweeps.alive`'s semantics are RIGHT, and the isolated root is not a
legitimate place to *evaluate* them.** The honest report is neither PASS
(claiming proof we do not have) nor FAIL (red-lining a service that is provably
healthy) — it is **`unknown`**, exactly the third option
`sweeps.reclaiming` already established in `model_performance-oy4` (`46d7da4`)
for a heartbeat that cannot answer the question put to it. This lane follows
that precedent rather than inventing a fourth convention.

The goal's second option — "have the TEST provision a heartbeat" — was
rejected deliberately: it would make the test manufacture the evidence it then
asserts on, which proves nothing about the sweep loops and leaves the check
still unable to tell a wrong-root from a dead loop for **every other** caller
of `doctor`. The defect is in the check, not the fixture, so it is fixed in the
check.

### What made this detectable

`_serve_argv_tail` (`service.py:504`) bakes `--root <path>` into the unit as an
**explicit argument**, not an `Environment=` line — a deliberate choice the
unit template's own comment calls out. So the served root is **readable**, and
the mismatch is **decidable** rather than a guess.

---

## 2. What changed

**`service.py`**
- `ServiceInfo` gains `served_root: Path | None` — which root the installed
  unit actually serves, read back out of the unit itself, never guessed.
- `parse_systemd_served_root(unit_text)` / `parse_launchd_served_root(plist_text)`
  — pure readers (text in, `Path` out) for `ExecStart=` and `ProgramArguments`.
  Both return `None` for "cannot tell" (unreadable, no `--root`, unparseable),
  never a guess.
- `_read_served_root(unit_path, platform)` — never raises; an unreadable unit
  reads as `None`.

**`cli.py`**
- `_served_root_mismatch(info, root)` — the shared gate. Returns an explanation
  when the inspected root is not the served root, `None` when they match **or
  the answer is unknowable**.
- `_check_sweeps_alive` and `_check_sweeps_reclaiming` consult it after the
  existing `installed`/`active` gates and report `unknown -- ...` on a mismatch.
  Dependency ordering is unchanged: "not installed" is still reported as such.

**`tests/_util.py` + `tests/cli/test_cli_surface.py`** — the masking, fixed
separately (see §4).

`assert_no_silent_failure` and its announcement predicate are **called
unchanged**. The scope-out was respected: nothing was narrowed, and the test
was neither deleted nor skipped.

---

## 3. The deliverable that a green-everything "fix" would have broken

> *`doctor` still FAILS loudly when a sweep genuinely is not running on a real
> installation.*

The conservative direction is deliberate and is pinned by tests, not by
assertion:

| situation | verdict |
|---|---|
| served root, **no heartbeat at all** | **FAIL** — `no heartbeat ever recorded` |
| served root, **stale** heartbeat | **FAIL** — names the loop |
| served root, heartbeat from a **dead pid** | **FAIL** — `no longer running` |
| served root, sweep **failed on every project** | **FAIL** (`sweeps.reclaiming`) — names them |
| **served root cannot be determined** | **evaluate anyway; can still FAIL** |
| a root the service does **not** serve | `unknown` |

That fifth row is the one that matters most. "Cannot tell" must never become a
way to make a real dead-loop failure disappear: silence about a scope mismatch
is far cheaper than silence about a stopped sweep. It is stated as a test
(`test_when_the_served_root_cannot_be_determined_we_evaluate_anyway_and_can_still_FAIL`)
so it cannot be quietly inverted later.

New test files:
- `tests/unit/test_sweeps_root_scope.py` (11 tests) — both halves of the gate.
- `tests/unit/test_served_root.py` (14 tests) — the pure readers, including two
  **round-trips through the real writers** (`_systemd_unit_content`,
  `_LAUNCHD_PLIST_TEMPLATE`), so a future change to how `--root` is baked in
  cannot silently make the reader answer `None` and quietly restore the old
  false FAIL.
- `tests/unit/test_doctor_surface_failures.py` (6 tests) — the de-masking.

Every pre-existing test in `tests/unit/test_cli_doctor.py` keeps its exact
meaning: its `_Info` fake carries `served_root = None`, which takes the
conservative path.

---

## 4. The masking, and why fixing the FAIL was not enough

`test_doctor_quick_succeeds_against_the_real_installed_bd` was three sequential
asserts with `assert result.returncode == 0` **first**. Any exit-1 — including
a purely environmental one the fixture itself creates — killed the test before
the two assertions after it ever ran.

Removing the environmental exit-1 restores visibility *today*. It does not fix
the **ordering**, which is a defect in its own right: the next environmental
exit-1, from any cause, would hide the next real defect identically. Both are
fixed.

### Demonstration (committed, reproducible)

A `wp6`-shaped defect was injected into `cmd_doctor` — one line printing an
error **announcement** while everything else passes — and the *same* cli test
was run on the *same* box, before and after.

**BEFORE** (`evidence/masking-BEFORE-injected-defect-is-invisible.log`, at
pristine `HEAD` = `46d7da4`):

```
>       assert result.returncode == 0, result.stdout + result.stderr
E       AssertionError:   [PASS] version   bd 1.1.2
        ... (the sweeps.alive FAIL)
```

The injected defect appears **0 times in the entire log**, and the string
`silent-failure guard` appears **0 times** — the guard never ran. The verdict a
reader gets is "sweeps.alive failed," i.e. exactly the *"that one cli failure
is jyg, not mine"* hand-verification the item describes.

**AFTER** (`evidence/masking-AFTER-injected-defect-is-visible.log`):

```
E  AssertionError: `doctor --quick` failed 1 independent check(s)
   (all of them reported, none masked by the first):
     1. silent-failure guard: command printed an error announcement but
        exited 0 ... shape=error-colon matched='Error:'
```

The test now reports **the injected defect itself**. The injection was reverted
before commit; `AWT_JYG_INJECT_ANNOUNCEMENT` appears nowhere in the tree.

The ordering property is additionally pinned permanently and cheaply (no bd, no
subprocess) by `test_an_exit_1_does_not_hide_a_silent_failure_announcement`.

---

## 5. Measurements

### `doctor` — MEASURED, never computed

**38/38, both roots, exit 0.** Unchanged; `AGENTS.md:29` and `:145` need no
edit.

| run | assumption lines | `sweeps.alive` | exit |
|---|---|---|---|
| before, isolated root (`evidence/before-doctor-quick-isolated-root.log`) | 38 | **FAIL** | **1** |
| after, isolated root (`evidence/after-doctor-quick-isolated-root.log`) | 38 | `unknown -- the installed service serves --root /home/bkrabach/.amplifier-work-tracker, not /tmp/...` | **0** |
| after, real served root (`evidence/after-doctor-quick-real-served-root.log`) | 38 | `reap sweep completed 64s ago (threshold 900s); notify sweep completed 261s ago` | **0** |

The third row is the load-bearing one: against the root the service actually
serves, the assumption is still **genuinely evaluated** against a real
heartbeat, not skipped.

### The target test, same box, before and after

| | result |
|---|---|
| before (`evidence/before-test-doctor-quick-fails.log`) | **FAILED** at `assert result.returncode == 0` — `1 failed in 49.67s` |
| after (`evidence/tier-cli.log:89`) | **PASSED** |

### All four documented tiers + the modules suite, by name

| tier | command | result |
|---|---|---|
| 1 — unit | `make test-unit` | **912 passed** in 45.24s |
| 2 — integration | `make test-integration` | **374 passed, 3 skipped** in 1104.29s (18:24) |
| 3 — cli | `make test-cli` | **89 passed** in 317.83s |
| 4 — ledger | `make test-ledger` | **26 passed** in 0.60s |
| 4b — ledger mutation | `make ledger-mutate` | **proven 15 / 15** (ALL mutations) |
| 5 — modules | `make test-module` | **119 passed** in 457.93s |

`ruff check`, `ruff format --check`, `pyright` — all clean (`0 errors, 0
warnings, 0 informations`).

The known port-binding flake in `tests/unit/test_supervisor_web.py` did not
occur in this run.

---

## 6. Deviations and things left open

- **No deviations from the goal.** One objective, no OPTIONAL-IF-CAP-PERMITS
  items, nothing dropped.
- **The cap did not bind.** $0.00 authority, $0.00 spent, $0.00 residue. The
  arithmetic in the goal (`0 x 0 x $0 / 1.00 = $0.00`) closes correctly for a
  pure code change; there was no purchase to price.
- **Open, deliberately not widened into:** `sweeps.reclaiming` on this host
  still reports `unknown -- the running supervisor predates per-sweep outcome
  reporting`. That is `oy4`'s documented behaviour for a supervisor started
  before `46d7da4`, and it clears on the next `service restart`. Not this
  lane's item.
- **Also open:** `_served_root_mismatch` compares resolved paths, so a served
  root reached through a **bind mount or a different mount namespace** would
  read as a mismatch and report `unknown` where FAIL might be warranted. That
  is the conservative direction, it did not arise on any measured host, and
  fixing it would require a device/inode comparison whose failure modes are
  worse than the one it closes. Recorded rather than silently absorbed.
