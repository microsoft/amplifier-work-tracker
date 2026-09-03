# DONE-NOTE — lane `oy4-dead-holder-reclaim`

Item: `model_performance-oy4` — *"Custody hold whose holder PROCESS IS DEAD did
not become reclaim-eligible in 23+ min against a 900s TTL — a dead lane strands
its own item."*

Repo: `microsoft/amplifier-work-tracker`, branch `lane/oy4-dead-holder-reclaim`.

**OUTCOME: branch A — RESOLVED.** Every deliverable is DONE. Spend **$0.00**
against a **$0.00** authority; nothing needed buying, and nothing was bought.

---

## 1. The headline, and it corrects the item's own premise

**The item's three candidates are all falsified.** The reap sweep was running;
staleness *was* computed from last renewal; the TTL *was* the documented 900s.
The stranding was real, but not for any of those reasons — and the "23+ minutes
past death" in the item's title is arithmetic built on a wrong death time.

Forensics, read out of the live `events` table for `model_performance-h6v`
(committed at `evidence/h6v-forensic-timeline.txt`; `events.created_at` is
written in the dolt server's local timezone, +7h to UTC — see `adapter.py`'s
own TIMEZONE GOTCHA block):

| time (UTC) | what the record shows |
|---|---|
| 07:03:16 | `agent-spark-1-563997` claims, takes custody |
| 07:03:17 → **07:41:36** | **20 custody renewals, on a metronome-regular 120s cadence** |
| — | *then nothing. The next renewal (07:43:36) never happened.* |
| 07:47 / 07:50 / 07:51 / 07:56 | successor `work_claim` refused ×4 |
| 07:52 | `work_stats` reports `held_stale: 0`, `oldest: null` |
| 07:57:51 | hand-run `unclaim` (`actor: Amplifier`) releases it |
| 07:59:09 | successor finally claims |

Last renewal **07:41:36Z** + TTL **900s** ⇒ first reclaim-eligible at
**07:56:36Z**. So:

- **All four refusals were CORRECT.** The last one landed **45 seconds inside**
  the TTL. Nothing refused a claim it should have granted.
- **`held_stale: 0` at 07:52Z was CORRECT.** Silence was 623s against a 900s
  TTL.
- The holder actually died between 07:41:36 and 07:43:36 — **~10 minutes later
  than the "~07:33Z" the item records.** The 19- and 23-minute figures are
  measured from that wrong start.
- The manual `unclaim` at 07:57:51Z beat the next sweep by ~3 minutes. The
  machinery would have freed the item on its own, just later.

**So what IS the defect?** The one fact that settled the matter — *the holder's
process was gone* — was sitting unread in the custody record. `Custody` has
carried `pid` and `host` since it was designed
(`src/amplifier_work_tracker/custody.py:89-96`) and **nothing has ever read
them for a decision**. `reclaim_eligible` (`custody.py:139-175` pre-fix) decides
on `last_seen` recency and the escalation ceiling, and nothing else. Liveness is
*inferred from silence*, never *observed from the holder*.

Consequence: a lane whose process dies is stranded for the remainder of its
900s TTL **plus up to a 300s sweep interval — up to 20 minutes** — on a fact
knowable in microseconds on the same host. And during that window a relaunched
successor can do nothing at all: it cannot `work_claim` (held), cannot
`work_release` (it does not hold it), cannot `work_file` (filing requires
holding an item). That dead end is exactly what forced the hand-run `unclaim`,
twice today (`h6v`, `2nx`).

**Mechanism named at file:line** (post-fix line numbers):

| site | what it does / did |
|---|---|
| `custody.py:139-175` (pre-fix `reclaim_eligible`) | two paths only: TTL staleness, escalation ceiling. Neither consults the holder. |
| `custody.py:89-96` (`Custody.pid` / `.host`) | recorded on every `take_custody`, read by nothing |
| `supervisor.py:105-134` (`reap_project`) | correct — it reclaims exactly what `reclaim_eligible` says, and no more |
| `adapter.py:5362-5382` (`_held_stale_count`) | correct — calls the same function verbatim, which is why `held_stale` agreed with the reaper |

---

## 2. Deliverables

### D1 — Mechanism named at file:line, settling the three candidates — **DONE**

Settled above, from the events table rather than from reading code and
guessing. (a) sweep not running: **NO** — the reap heartbeat shows sweeps
completing continuously, and the machinery released `h6v` correctly once asked.
(b) staleness from the wrong field: **NO** — it is computed from `last_seen`,
exactly as documented, and every value measured during the incident was
arithmetically right. (c) a different TTL: **NO** — 900s, as documented and as
`doctor` reports.

### D2 — A dead holder's hold becomes `held_stale` and is RECLAIMED, within the documented TTL, with a fail-before — **DONE**

A **third path** to reclaim-eligible that observes the holder instead of
inferring from its silence, fenced so it can only ever *accelerate* the TTL and
never take work from a live agent:

1. the record's `host` must equal this host (a pid on another machine is
   unknowable — never guessed);
2. `pid` must be a real positive pid;
3. custody must **already** have been silent for `DEAD_HOLDER_MIN_SILENCE_SECONDS`
   (default `2 × RENEW_INTERVAL_SECONDS` = 240s) before any pid probe is
   consulted at all.

Every unknowable case resolves to **not** eligible. Fence 3 is what protects an
agent whose pid is simply not addressable from here (a container with its own
pid namespace reporting the same hostname): such an agent keeps renewing, so it
never enters the window where the probe runs. PID reuse is imprecise only in the
safe direction — a recycled pid answers "alive", which merely falls back to the
TTL.

Reclaim latency for a dead holder: **up to 1200s → up to 540s**, and the reason
string says plainly that the TTL is *not* what fired.

**Fail-before / pass-after** (`evidence/fail-before-pass-after.txt`, identical
probe on both trees via `git stash push -- src/`), reproducing the incident
signature verbatim — dead holder, 400s silence, 900s TTL:

```
BEFORE  work_stats:  held=1  held_stale=0  held_stale_oldest_age_seconds=None
        reap_project(default ttl): reclaimed_count=0
        successor work_claim: REFUSED -- issue already claimed by dead-agent

AFTER   work_stats:  held=1  held_stale=1  held_stale_oldest_age_seconds=401.256
        reap_project(default ttl): reclaimed_count=1
          "holder process is dead -- pid 3824385 on host 'spark-1' is not
           running, and custody has been silent 401s (corroboration window
           240s); ttl 900s not yet reached, but the holder is gone"
        successor work_claim: SUCCESS
```

Tests: `tests/unit/test_custody_dead_holder.py` (19, injected probe — the
acceleration plus all three fences plus the live-holder safety property);
`tests/integration/test_dead_holder_reclaim.py` (7, real `bd`, real dolt, and a
**real** dead pid — a subprocess started and reaped, not a number chosen for
looking implausible).

### D3 — A successor session can `work_claim` after the reclaim, end to end — **DONE**

`modules/tool-work-tracker/tests/test_dead_holder_successor_claim.py` (4), at
the **agent seam** — `WorkTrackerSession.claim/resolve`, the verbs the stranded
lane actually had. Refused by name before the sweep; succeeds after; the
successor can then resolve. Deliberately **not** `ttl_seconds=0`, which is how
every other reap test in that suite forces staleness — with ttl 0 every hold is
stale and a dead-holder bug hides completely. These use the real default TTL and
a real 400s silence, so a reclaim can only have come from the liveness path. A
live session's identically-silent hold survives the same sweep.

### D4 — `doctor` distinguishes "sweeps installed" from "sweeps actually reclaiming" — **DONE**

The gap was real even though it is not what bit `h6v`. `reap_sweep` catches
every per-project exception into its return value (correct — one broken project
must not abort the sweep), and `reap_loop` **discarded that return value** before
stamping a completed heartbeat. A sweep that failed on *every* project recorded
the same heartbeat as a perfectly healthy one, so `sweeps.alive` — and
`work_tracker_status`'s `running_healthy` on top of it — read identically either
way.

Now: the reap heartbeat carries the sweep's **outcome** (`projects`,
`reclaimed`, `failed_projects`), `reap_loop` `logger.error`s any failed
projects by name, and `doctor` gains **`sweeps.reclaiming`** —
`heartbeat.evaluate_reclaiming`, pure and fully unit-tested — which FAILS naming
every project the last sweep failed on.

One honesty note, and it is deliberate: a heartbeat written by a supervisor
older than this change carries no `failed_projects` key, and that case reports
**`unknown`**, never `0 failed`. Claiming "nothing failed" from a record that
never carried the field would invent exactly the reassurance this check exists
to stop being invented. That is what the live box reports right now (see
`evidence/doctor-measured.txt`) and it clears on the next service restart.

Tests: `tests/unit/test_sweeps_reclaiming.py` (17).

### D5 — Verdict on `model_performance-c0e` — **DONE: genuinely distinct, and its primary half is ALREADY FIXED**

Argued from the code, and then measured.

| | `oy4` | `c0e` |
|---|---|---|
| site | `custody.reclaim_eligible` | `Beads.resolve`'s custody fence |
| proxy relied on | last-renewal **timestamp** | item **status** (`if current.status == "held"`) |
| direction | a live successor wrongly **prevented** from acting | a stale holder wrongly **permitted** to act |
| when | reclaim **never happens** | **after** a reclaim happens |

They rhyme — both are "custody state read from a proxy rather than from the
custody record" — but they are different proxies at different call sites failing
in opposite directions, and neither fix touches the other's code. `oy4`'s fix
does not go near the resolve fence; `c0e`'s does not go near reclaim
eligibility. **Two defects. Fixed only `oy4`, as the goal directs.**

And `c0e`'s named failing test **passes on this tree**: the full modules suite
is **119 passed, 0 failed**, including
`test_reap_recovery.py::test_explicit_resolve_refusal_after_reap_clears_held_and_allows_new_claim`,
the exact test `c0e` reports as failing. `c0e` was filed 03:53Z; PR #68 (the
post-reclaim fence, re-keyed on custody **identity** rather than item status)
landed afterwards and closed it. `c0e`'s **second** finding — that ledger row
CCV1-023's note claims the fixture "passes via the session latch" — is a ledger
note, a different subject, and I did **not** verify or touch it. **I have not
resolved `c0e`**: I do not hold it, its second half is unverified by me, and
resolving another lane's item on a partial reading is exactly the kind of quiet
overreach this program keeps paying for. Recommendation for whoever holds it:
re-run the named test, confirm it passes, and close on the ledger-note half
alone.

### D6 — Two further silent misses in the reaper, found while root-causing — **DONE**

Neither caused this incident; both are live silent-miss bugs in the same
function, and both are one-line-shaped fixes with tests.

1. **`reap_project` read bd's DEFAULT list page.** `bd.list(include_resolved=False)`
   with no `limit` applies `LIST_DEFAULT_LIMIT` (50), ordered `priority ASC,
   created_at DESC, id ASC`. **A held item outside that first page was invisible
   to the reaper permanently, with nothing anywhere reporting the skip.** Now
   `bd.list(status="held", limit=0)`. Measured and ruled out as this incident's
   cause: `model_performance` held 20–22 non-closed items across the window and
   `h6v` ranked 2nd–4th. Pinned twice — on the *call shape*
   (`test_supervisor.py`, since the outcome looks identical on any project small
   enough to fit) and end-to-end with a shrunken page size.
2. **One unreleasable item shadowed the whole queue.** The loop had no per-item
   guard, so the first `release` that raised propagated out, `reap_sweep` caught
   it per project, and every remaining stale hold went unreaped — deterministically,
   on every sweep after it, while the sweep still recorded itself completed.
   Now isolated per item and reported in `failed`, which flows into D4's
   heartbeat.

---

## 3. Tiers — reported BY NAME

| tier | command | result |
|---|---|---|
| unit | `pytest tests/unit` | **881 passed, 0 failed** |
| integration | `pytest -m integration tests/integration` | **374 passed, 3 skipped, 0 failed** (`evidence/integration-tier.log`) |
| cli | `pytest -m cli tests/cli` | **88 passed, 1 failed** — `test_doctor_quick_succeeds_against_the_real_installed_bd`, which is `model_performance-jyg`, **not mine** (see below) |
| ledger | `pytest ledger/checks` | **26 passed** |
| ledger mutation | `python -m ledger.checks.mutation_harness` | **proven 15 / 15**, none unproven |
| modules (tier 5) | `pytest modules/tool-work-tracker/tests` | **119 passed, 0 failed** |
| lint | `ruff check .` / `ruff format --check .` | clean, 163 files |
| types | `pyright src tests` | **0 errors, 0 warnings** |
| **doctor** | `python -m amplifier_work_tracker.cli doctor` | **All 38 assumptions hold** — **MEASURED**, not computed (`evidence/doctor-measured.txt`) |

**The one cli failure is `jyg`, and I verified it rather than assuming it.** The
full doctor output inside that failure shows a single `[FAIL]`, on
`sweeps.alive`: *"no heartbeat ever recorded for the reap sweep loop"* — the
isolated test root has no sweep heartbeat, exactly as `jyg` describes. My own new
check appears one line below it as `[PASS] sweeps.reclaiming  skipped -- no reap
heartbeat recorded yet`, correctly declining to pile a second red line on a root
cause already reported. Captured in `evidence/cli-tier-jyg-failure.txt`.

`doctor` **37 → 38**: the count was read off the tool on this branch, never
computed. `AGENTS.md`'s two sites are updated.

## 4. Spend

**$0.00** of a **$0.00** authority. The goal's arithmetic (`0 runs × 0 arms ×
$0 / 1.00 = $0.00`) closes: this is a pure local code change, no API calls, no
DTU, no infrastructure created — so nothing was registered in the infra ledger
and nothing needed tearing down. No residue was left: the reads against the live
`model_performance` database were pure `SELECT`s, and every test project came
from the repo's own isolated-server fixtures.

## 5. Deviations and judgement calls, all deliberate

1. **I corrected the item's premise rather than confirming it.** The item asks
   which of three candidates is true; the honest answer is *none*, and the
   supporting arithmetic is built on a death time ~10 minutes early. Reporting
   any of the three would have been a fabricated root cause.
2. **A corroboration window instead of an instant probe.** A bare "pid gone ⇒
   reclaim" would fire on a container whose pid is unaddressable from here. Two
   independent signals — a missed renewal *and* a dead pid — cost ~4 extra
   minutes of latency and remove the only way this fix could steal live work.
3. **`sweeps.reclaiming` reports `unknown` for an older supervisor's record.**
   Weaker than failing, and named as such above. Failing would red-line every
   box until its service restarts; claiming `0 failed` would be a lie. Reporting
   the gap in the assumption's own text is the honest third option.
4. **I did not resolve `c0e`,** for the reasons in D5.
5. **I did not touch `jyg`** (the goal scopes it out) and did not run
   `reap --project` against `model_performance` at any point — live lanes hold
   items in it right now. Every live-queue interaction in this lane was a
   read-only `SELECT`.

## 6. Evidence in this directory

| file | what it is |
|---|---|
| `evidence/h6v-forensic-timeline.txt` | the `events`-table reconstruction that falsified all three candidates |
| `evidence/fail-before-pass-after.txt` | identical probe, pre-fix vs post-fix, reproducing the incident signature |
| `evidence/failbefore_probe.py` | that probe, runnable |
| `evidence/doctor-measured.txt` | `doctor` 38/38, measured on this branch |
| `evidence/cli-tier-jyg-failure.txt` | proof the one cli failure is `jyg`, with my check passing beside it |
| `evidence/integration-tier.log` | integration tier output |
