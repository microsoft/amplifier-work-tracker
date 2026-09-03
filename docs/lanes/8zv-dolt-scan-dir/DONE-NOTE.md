# Lane 8zv — pin the dolt scan directory; stop reporting infrastructure failure as "item not found"

Item: `model_performance-8zv` (project `model_performance`).
Repo: `github.com/microsoft/amplifier-work-tracker`, branch `lane/8zv-dolt-scan-dir`.
Spend: **$0** — no API calls, no DTU, no infrastructure created, nothing registered in
the infra ledger and nothing to tear down. The whole lane is a code change plus rpz's
own $0 harness.

Diagnosis was **not** re-derived: lane `model_performance-rpz` owns it
(`ai-notes` branch `lane/rpz-dolt-error-misreport`, commit `a6c6e03`). This lane fixes,
measures, and fences it.

---

## 1. What was wrong (rpz's diagnosis, restated only to anchor the fix)

The `dolt` CLI enumerates its data directory and `lstat()`s every entry on **every**
invocation — including the pure client mode (`--host/--port` against the already-running
shared server) that every `_dolt_*` helper in `adapter.py` uses, where no local database
is relevant at all. With no `--data-dir` given, that directory is the **inherited current
working directory** — whatever directory the calling agent happened to be in. If an entry
vanishes between `readdir` and `lstat`, dolt aborts the whole query.

`_dolt_sql` / `_dolt_sql_json` passed no `cwd=` to `_run_bounded`, so the failure rate of
a work-tracker read was set by an unrelated process's litter in `/tmp`.

---

## 2. What changed (all in `adapter.py` unless named otherwise)

| # | Change | Why this one |
|---|---|---|
| 1 | `_dolt_scan_dir()` — a stable, empty, memoised directory we own (`$XDG_CACHE_HOME`/`~/.cache/amplifier-work-tracker/dolt-scan`, overridable via `AMPLIFIER_WORK_TRACKER_DOLT_SCAN_DIR`). Applied **two independent ways**: `cwd=` on the two hot helpers, and `--data-dir` in `_dolt_conn_args()` so *every* dolt invocation in the module gets it by construction. | REMOVES the failure rather than tolerating it. Both remedies measured 0/25 under the load that produced 7/25 and 12/25 unpinned. Two, not one, because they are independent — a refactor dropping either must not silently reopen the defect. |
| 2 | `_run_dolt_sql_bounded()` — the same bounded transport retry `Beads._run` already had for `bd`, now on the direct-SQL path; `"failed to load database names"` added to `_RETRYABLE_CONNECTION`. | The retry classification lived **only** in `Beads._run`. The direct dolt-SQL path had none, across 19 call sites. Adding the string alone would have landed in a table this path never read. Putting the loop in one helper is what makes all 19 benefit. |
| 3 | `BeadsUnavailableError(BeadsError)` + one classifier `_sql_failure()` at the six SQL read sites. `claim_item` and `get_readonly` re-raise it untouched; `project_summary` reports `UNAVAILABLE: …` (`STATUS_UNAVAILABLE_PREFIX`, `is_unavailable_status`). | A **type**, not a substring callers must grep. `get_readonly` stops discarding the cause — the specific one-line defect, on the exact path `context/awareness.md` hazard #6 tells agents to trust. |
| 4 | `contract.py`: new assumption `read.unavailable_not_absent`, fencing **both** directions. | A regression now breaks loudly under `doctor`. |
| 5 | CLI/web follow-on: `cli.cmd_instances` prints the new status verbatim (no second copy of the rule); `webapp._dashboard_row` paints an unreachable project amber **Unavailable** rather than crimson **Broken**; `webbrowse` says "unknown, not broken". | `instances` had no vocabulary between `ok` and `ERROR`. |

**`doctor` now measures 35/35** — read off `doctor`, not computed (33+2 arithmetic would
have said 36 last time and been wrong). `AGENTS.md` updated in all three places that
carried the old count.

---

## 3. Deliverables

### 3.1 The failure is REMOVED, and it was measured — **DONE**

rpz's own harness, run verbatim (`git show lane/rpz-dolt-error-misreport:probes/rpz-dolt-error-misreport/repro.sh`,
sha256 `77635c7a…`; copied to the capture root and run there, unmodified). **Two runs**;
raw counts pasted exactly as printed:

```
RUN A — stock installed CLI (0.1.0, unfixed) on PATH
  0. empty cwd  : real 0m0.056s
     /tmp (66292 entries): real 0m8.685s
  2. raw dolt, cwd = churning dir (== today's code path)   failures:  7 / 25
  3. FIX A -- identical load, cwd pinned to a stable dir   failures:  0 / 25
  4. FIX B -- cwd left churning, --data-dir pinned         failures:  0 / 25

RUN B — LANE build (fix applied) shimmed first on PATH
  0. empty cwd  : real 0m0.036s
     /tmp (66292 entries): real 0m0.873s
  2. raw dolt, cwd = churning dir (== today's code path)   failures: 12 / 25
  3. FIX A -- identical load, cwd pinned to a stable dir   failures:  0 / 25
  4. FIX B -- cwd left churning, --data-dir pinned         failures:  0 / 25
```

So: **25/25 succeed with the scan directory pinned, by either remedy, in both runs**,
against 7/25 and 12/25 failures unpinned under the same load in the same run.

**Deviation from the item's wording, stated plainly:** the item predicted "failed 6/25".
Measured today it was **7/25 and 12/25** — the same defect, a *worse* failure rate than
filed (this host's `/tmp` has grown from rpz's 52,281 entries to 66,292). The pinned
counts are the ones the deliverable turns on, and they are 0/25 both times.

Stage 5 is the end-to-end half, on `model_performance-8zv` — an item that exists and that
this session **holds** — read-only, mutating nothing:

```
RUN A (stock CLI):  7 of 8 attempts -> "item 'model_performance-8zv' not found in project 'model_performance'"
                    1 of 8 attempts -> the real record
RUN B (lane build): 8 of 8 attempts -> the real record
```

Run B's stage 2 shows a *harsher* load (12/25 raw failures) than run A's, so the fixed
CLI was not merely luckier.

Raw captures: `.amplifier/evaluation/treatment-validation/2026-09-02-model_performance-8zv/`
(`harness-run-A-stock.txt`, `harness-run-B-fixed.txt`, `repro.sh`, `shim-bin/`).

### 3.2 `claim --id <existing-id>` past the retry budget — **DONE**

Names the transient condition; does **not** say "item not found".
Tests: `tests/cli/test_cli_unavailable_not_absent.py::test_claim_id_on_an_existing_item_does_not_say_item_not_found_when_unreachable`
(real CLI subprocess, real `dolt`, real closed port — genuinely past
`_run_dolt_sql_bounded`'s budget), and
`tests/unit/test_unavailable_not_absent.py::test_claim_item_under_transport_failure_does_not_say_item_not_found`.

### 3.3 `list --id <existing-id>` past the retry budget — **DONE**

Still carries the underlying cause; `get_readonly` no longer discards it.
Tests: `tests/cli/…::test_list_id_on_an_existing_item_does_not_deny_it_when_the_db_is_unreachable`,
`tests/unit/…::test_get_readonly_under_transport_failure_does_not_claim_absence`,
`…::test_get_readonly_transport_failure_is_a_distinct_TYPE`.

### 3.4 `instances` — **DONE**

Retries first, then reports a status distinct from **both** `ok` and `ERROR` naming the
transient cause, with counts left `None` rather than fabricated.
Tests: `tests/cli/…::test_instances_reports_UNAVAILABLE_not_ERROR_when_the_db_is_unreachable`,
`tests/unit/…::test_project_summary_under_transport_failure_is_UNAVAILABLE_not_ERROR`,
`…::test_project_summary_unavailable_is_distinct_from_every_other_status`.

### 3.5 The no-blurring guardrail — **DONE** (treated as load-bearing as the rest)

Genuine absence on a **healthy** database reports absence exactly as it does today, on
all three verbs, with no "maybe transient" hedge anywhere:

- `tests/cli/…::test_list_id_on_a_genuinely_absent_item_is_UNCHANGED`
- `tests/cli/…::test_claim_id_on_a_genuinely_absent_item_is_UNCHANGED`
- `tests/cli/…::test_instances_on_a_healthy_server_is_UNCHANGED`
- `tests/unit/…::test_get_readonly_genuine_absence_is_UNCHANGED` (asserts the message
  **byte for byte**), `…::test_get_readonly_wrong_project_prefix_is_UNCHANGED`,
  `…::test_claim_item_genuine_absence_is_UNCHANGED`,
  `…::test_project_summary_real_read_failure_still_reports_ERROR` (a *reachable* database
  that cannot be read is still an honest `ERROR`, not softened),
  `…::test_project_summary_healthy_is_UNCHANGED`
- `tests/unit/test_dolt_scan_dir.py::test_a_real_domain_failure_is_not_classified_transient`
  and `…::test_direct_sql_does_not_retry_a_real_domain_failure` — the classifier itself.

Note, deliberately: **the three CLI-tier guardrail tests pass on the PARENT commit as well
as on the fix.** That is the point of them — they are the fence that says nothing moved.

### 3.6 `doctor` assumption — **DONE**

`contract.py::check_unavailable_not_absent`, id `read.unavailable_not_absent`, registered
in `CHECKS`. Fences both directions in one check. The transport failure is *injected* at
`_dolt_sql`/`_dolt_sql_json` (restored in a `finally`) rather than provoked by churning a
real directory — this check runs inside `doctor` on operators' machines, and injecting also
places the failure past the retry budget, which is the condition the deliverable names.

`doctor` on this tree: **`All 35 assumptions hold.`**

### 3.7 Fail-before evidence — **DONE**

`docs/lanes/8zv-dolt-scan-dir/evidence/fail-before.txt` — the three new test files run
against the parent commit's source (`src/` + `AGENTS.md` reverted to
`2468a6946ee7e04e82ad9d563af86d48a5d66355`, the new tests kept):

```
unit  : 18 failed, 2 passed
cli   :  3 failed, 3 passed
```

The 3 CLI passes and 2 unit passes are exactly the unchanged-behaviour guardrails
(§3.5) — they must pass before *and* after. Every test describing the defect fails there.

---

## 4. Test tiers — all four, by name, plus the modules tier

| Tier | Command | Result |
|---|---|---|
| unit | `pytest tests/unit` (`make test-unit`) | **810 passed** |
| integration | `pytest -m integration tests/integration` (`make test-integration`) | **322 passed, 3 skipped** (14:00) |
| cli | `pytest -m cli tests/cli` (`make test-cli`) | **86 passed, 1 failed** — the pre-existing `test_doctor_quick_succeeds_against_the_real_installed_bd` |
| ledger | `pytest ledger/checks` (`make test-ledger`) | **24 passed** |
| modules | `pytest modules/tool-work-tracker/tests` (not in `testpaths`) | **100 passed, 1 failed** — the pre-existing `test_explicit_resolve_refusal_after_reap_…` |
| lint/types | `make check` (`ruff check`, `ruff format --check`, `pyright src tests`) | clean, `0 errors` |
| doctor | `amplifier_work_tracker.cli doctor` | **All 35 assumptions hold** |

Both failures are the two named in the item as PRE-EXISTING and NOT this lane's
(`model_performance-jyg`, `model_performance-c0e`). **`jyg` was checked rather than
assumed**: its failure line is `[FAIL] sweeps.alive — no heartbeat ever recorded…`, an
environment/service condition in the isolated test workspace, and the *new*
`read.unavailable_not_absent` check reports `[PASS]` inside that very run. The third named
item (`tests/unit/test_supervisor_web.py`, a port-binding flake) did not fire.

The modules tier needs a separate install the repo's own dev extras do not perform —
`uv pip install -e modules/tool-work-tracker` (plus `amplifier-core` and `pytest-asyncio`
per the item's KNOWN note), or the whole tier fails at **collection** with
`ModuleNotFoundError: No module named 'amplifier_module_tool_work_tracker'` and looks like
a real breakage. Recorded here because it cost real time and the item's KNOWN note names
only two of the three missing packages.

Raw tier output: `docs/lanes/8zv-dolt-scan-dir/evidence/tier-*.txt`.

---

## 5. Decisions made without asking (per the no-waiting-on-humans rule)

1. **Both remedies, not one.** The item ranked `--data-dir` and `cwd=` as alternatives.
   Both are applied: they are independent, both measured 0/25, and the combination
   survives a future refactor that drops either. Cost: ~3 lines.
2. **`--data-dir` lives in `_dolt_conn_args`, not on the two hot helpers.** That covers
   the other four `dolt` call sites (`DROP DATABASE`, `SHOW CREATE`, the copy script)
   by construction. "Remember to pass it at each call site" is exactly the discipline
   that failed here in the first place — the same argument `_bd_env`'s own docstring
   makes about telemetry.
3. **Genuine-absence wording left byte-identical.** The item said `get_readonly` "must
   stop discarding the cause". It does — for the transient case, which is the case that
   was lying. Appending bd's cause to a *real* "not found" would have changed the very
   message the no-blurring deliverable requires to be unchanged, so the cause is carried
   by the exception **type** and its message instead. `from e` already preserved the
   chain; the message did not, and now does, where it matters.
4. **Retry budget reused, not reinvented.** `_MAX_CONNECTION_RETRIES` / the existing
   backoff cap, so there is one answer to "how long do we tolerate a blip", not two.
5. **Scan directory under `~/.cache`, not the workspace root or `~/.beads/…/dolt`.** The
   workspace root grows a directory per project; the dolt data directory churns as dolt
   writes. Both would reintroduce the cost the pin removes. Falls back to one
   process-lifetime temp directory if the cache directory cannot be created — degrading to
   today's behaviour beats breaking every SQL read.
6. **Stage 5 run through a PATH shim, not by installing over the user's tool.** Installing
   the lane build as `amplifier-work-tracker` would have changed behaviour for live
   sessions on this host. The shim is a 2-line script first on `PATH`, and the capture
   records which binary each run used.

## 6. What remains open

- The `--data-dir` flag position is verified against `dolt 2.2.3` only (the version this
  repo pins via `check_version`). An older dolt without the global flag would fail loudly
  at the first SQL call, not silently — but it is untested.
- `_dolt_scan_dir()` is memoised per process. A long-lived process whose cache directory
  is deleted underneath it re-creates the directory on the next call (`is_dir()` guard),
  but this is asserted by construction, not by a test that deletes it mid-run.
- The CLI/web `UNAVAILABLE` rendering is covered by the adapter/CLI tests and by
  `webapp._dashboard_row`'s branch; there is no snapshot test of the rendered HTML row.
