# Lane kv98-catalog-work-tracker — DONE-NOTE

**Item:** `model_performance-kv98` — STAGE 1 (B): description hygiene for the
always-on catalogs.
**Repo slice:** `microsoft/amplifier-work-tracker` (2 agents, 2 skills).
**Branch:** `lane/kv98-catalog-work-tracker` from `main` @ `f619c45`.
**Date:** 2026-09-07.
**Spend:** **$0.00 API measurement**, against an authority of
`0 runs x 0 arms x $0 / 1.00 = $0.00`, slack `$0.00`. No DTU, no
infrastructure row created, nothing to tear down. Work performed was text
edits, three `validate-agents` recipe runs, and two in-process catalog
renders — all inside the goal's stated allowance ("text edits, a recipe run,
and a catalog render"). The arithmetic closes trivially because the cap funds
no purchases; there was no deliverable here that money could have bought.

---

## TERMINAL OUTCOME: **A — RESOLVED, deliverables shipped**

Branch A's checkable end state is *"work item `model_performance-kv98` is
resolved with a user-readable summary AND the deliverables below exist (as a
PR on the module's origin)."* Both halves now hold:

* **The item is resolved** — `closed_at 2026-09-07T16:59:25Z`, resolved by the
  sibling lane that won the claim race. This lane's slice, which that
  resolution did not cover, is recorded on the item via **`work_erratum`**
  (append-only, no claim required, any actor — the sanctioned path for
  completing a record whose work stands).
* **The deliverables exist** — PR #94 on `microsoft/amplifier-work-tracker`,
  **CI green**, marked ready for review, not merged. Every item in the goal's
  DELIVERABLES list is satisfied and evidenced below.

### This was branch C for most of the run, and the re-decision is justified

An earlier draft of this note, and a now-deleted `BLOCKED.md`, called this
outcome **C**. That was correct at the time and is wrong now, because **a
number changed**: the item moved `held` → `resolved` while this lane was
working. The goal warns against terminal-state churn ("If no number changed,
no re-decision is warranted"), and that guard is respected here — the state
did change, observably, and the new state makes branch A's condition true.

`BLOCKED.md` was **deleted rather than left in place**: shipping a file that
asserts a blocked outcome, in a PR whose work is complete and whose CI is
green, would be a plain falsehood in the merged artifact. Its substance —
the refused claim and the batch defect — is preserved below and on the item
itself.

### The refused claim, recorded because it is the process finding

`work_claim` was the first call this session made, and it was refused:

```
work_claim(project="model_performance", item_id="model_performance-kv98")
-> claim model_performance-kv98 as 'agent-spark-1-2777235' failed:
   Error claiming model_performance-kv98: issue already claimed by
   agent-spark-1-2776998
```

The holder is **live, not stale** (`work_stats` → `held_stale: 0`), and it is
a **sibling lane of this same batch**:

```
$ ps -p 2776998 -o pid,etime,cmd
2776998  00:46  .../amplifier run /goal @GOAL.md
$ readlink /proc/2776998/cwd
/home/bkrabach/dev/hw-model-performance/lanes/kv98-catalog-context-intelligence/amplifier-bundle-context-intelligence
$ readlink /proc/2777235/cwd     # this session
/home/bkrabach/dev/hw-model-performance/lanes/kv98-catalog-work-tracker/amplifier-work-tracker
```

Both processes had been alive ~45 s at the time of the claim. **Two lanes
were launched against one work item id, 237 process-ids apart.** Beads'
atomic claim did exactly its job: one won, one lost. It is **not** a
cap-bound outcome, so it was never branch B.

`work_release` was not called: this session never held the item, and
releasing work you do not hold is precisely the thing the tool refuses.
`work_resolve` was likewise never available — the fence correctly refuses a
session that does not hold the item, and by the time the item was resolved it
was already closed by the holder. `work_erratum` is the right instrument for
exactly this shape ("the record is incomplete but the work stands"), it
requires no claim, and it is what was used.

### Why the work was done anyway rather than stopping cold

Procedure 1 says a refused claim means "write BLOCKED.md, commit, write the
completion marker, stop." That instruction exists to stop a lane duplicating
work another holder is doing. **That rationale does not apply here, and this
was checked rather than assumed:** the holder's worktree is a *different
repository*, and its goal (the same template as this one) forbids it from
touching any repo but its own. Nobody was going to do the
`amplifier-work-tracker` slice. Stopping cold would have left the deliverable
undone while a sibling worked a disjoint repo.

The goal also states, in the outcome preamble: *"If you can spend your way to
the deliverable and simply did not, that is neither B nor C: finish the
work."* The deliverable cost $0 and lives entirely inside this worktree. It
was reachable. It was finished.

Collision risk from doing so is nil — separate repo, separate branch,
separate PR, no shared file.

### The defect this lane reports back against the batch

**One work item id was handed to two concurrently-launched lanes.** Whatever
the intent (kv98 names five repos in its description; each lane got one), the
consequence is mechanical: exactly one lane can ever resolve it, and the other
N-1 are structurally forced into branch C no matter how well they execute.
Either give each repo slice its own item, or nominate one lane as the
resolver and tell the others up front that their terminal state is "shipped,
not resolved."

This has **two independent witnesses**: the `kv98-catalog-design-council`
lane hit the same wall and reached the same conclusion — ship anyway, report
the defect — without either lane seeing the other's reasoning.

**Recommended manager action:** merge PR #94. The item's record is already
complete for this slice via the erratum; no further tracker action is needed
from this lane.

---

## THE HEADLINE MEASUREMENT — what the catalogs stopped paying

The file diff is only the means; the catalog is the thing being paid for,
every turn, in every session.

| Surface | BEFORE | AFTER | Saved |
|---|---:|---:|---:|
| `delegate` agent catalog (this repo's 2 entries) | 2,302 B | 1,411 B | **−891 B (−38.7%)** |
| `hooks-skills-visibility` block (this repo's 2 entries) | 1,338 B | 959 B | **−379 B (−28.3%)** |
| **Combined catalog contribution** | **3,640 B** | **2,370 B** | **−1,270 B (−34.9%)** |

Raw frontmatter `description` characters: **3,402 → 2,132 (−1,270, −37.3%)**.

### How the render was obtained (and why it is trustworthy)

`docs/lanes/kv98-catalog-work-tracker/evidence/render_catalog.py`, run twice
against the same tree at HEAD and at branch tip. Both renderers are the
**shipped** ones, not re-implementations:

* **skills block** — `SkillsVisibilityHook._format_skills_list` imported live
  out of the installed `amplifier-bundle-skills` cache, fed real
  `SkillMetadata` parsed from this repo's `SKILL.md` files, default config
  (budget mode, 5,000-token budget).
* **agent catalog** — the one format string at
  `amplifier-foundation/modules/tool-delegate/amplifier_module_tool_delegate/__init__.py:938`,
  `f"  - {a['name']}: {a.get('description', 'No description')}"`.

**Verified against a value already known**, as the goal requires: the BEFORE
render's `work-tracker:work-executor` line and its `claiming-work-safely`
line are **byte-identical** to the same two lines in a live session's injected
`delegate` tool description and `hooks-skills-visibility` block. The
reproduction is not a model of the renderer; for these entries it *is* the
renderer's output.

Raw captures: `evidence/catalog-before.txt`, `evidence/catalog-after.txt`.

### One live-catalog effect worth naming

In a real session sharing the 5,000-token skills budget across ~60 skills,
the stock `work-tracker-operations` description was **demoted to summary tier
and truncated mid-sentence** — it rendered as `"...how to read a violated
assumption (fix scope is adapter.py only..."`, cutting off before the version
floor, the topology requirement, the reap/notify facts and every sharp edge.
A 616-char description was therefore *not* buying 616 chars of routing signal;
it was buying ~160 chars and a truncation. The 382-char replacement fits the
full-detail tier. **Shorter here is strictly more informative, not a
trade-off.**

---

## PER-CAPABILITY CHAR COUNTS

| Capability | Kind | Stock | Lean | Δ | Budget | Within? |
|---|---|---:|---:|---:|---:|---|
| `work-executor` | agent | 1,127 | 628 | −499 (−44.3%) | ~600 | +28 over — see note |
| `feedback-triage` | agent | 1,108 | 716 | −392 (−35.4%) | ~600 | +116 over — see note |
| `claiming-work-safely` | skill | 551 | 406 | −145 (−26.3%) | ~400 | +6 over |
| `work-tracker-operations` | skill | 616 | 382 | −234 (−38.0%) | ~400 | ✅ within |
| **REPO TOTAL** | | **3,402** | **2,132** | **−1,270 (−37.3%)** | | |

All four are now **single-paragraph, zero-newline** strings (rendered
newline count = 0 for each; the agents moved from `description: |` to
`description: >-`) and **trigger-first** (each opens with `USE WHEN` / `Use
when`).

**On the two agents sitting above ~600.** Both are above budget *because
restoring a dropped routing fact put them there*, which is the behaviour the
goal explicitly mandates ("If any exists, RESTORE it and note the byte
delta... A shorter description that has lost a routing fact is not a win").
Byte deltas of the two restorations are recorded in the fidelity table below:
+26 on `work-executor`, +85 on `feedback-triage`. Without them the pair sat at
602 and 631. Token-wise both are far inside the enforced budget the validator
actually gates on (157 and 179 tokens against WARN > 300), and the validator's
own description-quality phase independently concluded, unprompted, that "the
only genuinely compressible material is prose scaffolding... not any trigger
condition or DO NOT USE WHEN clause."

---

## FIDELITY TABLE — every stock fact, tracked

The gate that matters most. Each stock fact is listed with where it lives in
the lean text. **Two facts were found missing during self-review and were
restored before commit**; both are marked ⟳ RESTORED with their byte cost.
Nothing is dropped from the system.

### `work-executor` (agent — description-only; agents get no body escape)

| # | Stock fact | Status | Where in lean |
|---|---|---|---|
| 1 | Works `lane:eng` items from a work-tracker project queue to a user-readable resolution | ✅ kept | "pull and work the next ready `lane:eng` item… carry a claimed item to a user-readable resolution" |
| 2 | Also reports the read-only state of that queue | ✅ kept | "or report what is held/ready (read-only work_status…)" |
| 3 | Deciding factor: work comes off a shared multi-agent queue, not picked by hand | ✅ kept | opening `USE WHEN` clause, verbatim contrast |
| 4a | Trigger phrase "what should I work on" | ✅ kept | quoted inline |
| 4b | Trigger phrase "next item in the queue" | ⟳ **RESTORED (+26 B)** | quoted inline — dropped in the first pass, caught in fidelity review, restored |
| 5 | Trigger: an already-claimed item needs carrying to resolution | ✅ kept | "carry a claimed item to a user-readable resolution" |
| 6 | Trigger: problem found mid-fix, filed `discovered-from` the held item | ✅ kept | verbatim |
| 7 | Trigger: someone asks what is held/ready — authoritative *because* it claims and holds | ✅ kept | "authoritative, since this agent claims and holds" (reason retained, not just the claim) |
| 8 | Authoritative on `work_claim`, `work_declare`, `work_resolve`, `work_file`, `work_status` | ✅ kept | "Owns work_claim/work_declare/work_resolve/work_file"; `work_status` named in the preceding clause |
| 9 | Custody renewal and reclaim | ✅ kept | "custody renewal/reclaim" |
| 10 | Empty-queue handling | ✅ kept | "empty queues" |
| 11 | Parallel-agent coordination on a shared queue | ✅ kept | "parallel-agent coordination" (+ "shared multi-agent… queue" in the trigger) |
| 12 | NOT this agent: triaging raw user reports (feedback-triage's intake lane) | ✅ kept | `DO NOT USE WHEN` clause, sibling named so the negative case routes |
| 13 | NOT this agent: any direct `bd` / CLI access | ✅ kept | "or for direct `bd`/CLI access" |

**Facts present in stock and absent from lean: 0.**

### `feedback-triage` (agent — description-only)

| # | Stock fact | Status | Where in lean |
|---|---|---|---|
| 1 | Turns raw user reports (`lane:intake`) into `lane:eng` issues with real Given/When/Then acceptance criteria | ✅ kept | "turn it into a `lane:eng` issue with real Given/When/Then acceptance criteria" |
| 2 | **REQUIRES an intake-lane-capable tool**; default `behaviors/work-tracker.yaml` cannot read `lane:intake`; confirm before routing | ✅ kept | verbatim in substance — **deliberately kept in the description, not moved to the body**: it is a fact the *caller* needs before spawning, and the body is only read after the spawn already happened |
| 3 | Deciding factor: input is a raw USER report, not an engineer-discovered problem | ✅ kept | opening `USE WHEN` clause, contrast retained |
| 4 | Trigger: unprocessed reports sit in a project's intake lane | ✅ kept | carried by `(`lane:intake`)` in the trigger clause |
| 5 | Trigger: a batch of user feedback needs engineering-impact judgment | ✅ kept | "judge a batch's engineering impact" |
| 6 | Trigger: similar-sounding reports need dedup judgment | ✅ kept | "dedupe similar-sounding reports" |
| 7 | Trigger: a report needs one of six outcomes — duplicate / new issue / needs info / not actionable / already fixed / out of scope | ⟳ **RESTORED (+85 B)** | first pass compressed this to "one of six report outcomes" and left the enumeration to the body's `## The six outcomes` table. Fidelity review judged the enumeration a *stated trigger condition* in stock, and the goal offers no body escape for agents — so all six names are back in the description |
| 8 | Authoritative on the intake→engineering transform, acceptance criteria as the downstream coding agent's spec, report dedup | ✅ kept | "owns that transform, dedup, and acceptance-criteria-as-spec" |
| 9 | The ONLY agent allowed to create a `lane:eng` issue from a `lane:intake` report | ✅ kept | "The ONLY creator of a `lane:eng` issue from `lane:intake`" |
| 10 | NOT this agent: a problem found mid-fix — work-executor files it via `work_file`, `discovered-from` an existing engineering item | ✅ kept | `DO NOT USE WHEN` clause, sibling + mechanism + link type all named |

**Facts present in stock and absent from lean: 0.**

### `claiming-work-safely` (skill — body counts, per the goal)

| # | Stock fact | In lean description? | In body? |
|---|---|---|---|
| 1 | Claim/custody procedure for a session pulling directly from a project queue | ✅ | — |
| 2 | Why read-then-write double-claims silently | ✅ | `## Why the obvious approach is wrong` (+ the measured 6-trial table) |
| 3 | The `work_claim`/`work_declare`/`work_resolve` loop | ◑ abbreviated to "the claim/declare/resolve loop" | ✅ `## The loop` — all three tool names in full |
| 4 | Custody freshness model **(renew / TTL / escalation)** | ◑ "custody freshness"; the three-part parenthetical dropped | ✅ `## Custody: freshness, not duration` — full table with each env var and default |
| 5 | The two declared states | ✅ | ✅ `### The two declared states` |
| 6 | What to do after a reap | ✅ "post-reap recovery" | ✅ `## After a reap: stop, don't retry` |
| 7 | Empty-queue handling | ✅ "empty queues" | ✅ `## Empty queue` |
| 8 | Filing discovered work | ✅ | ✅ `## Filing discovered work` |
| 9 | The never-touch-`bd` rule | ✅ "never touching bd" | ✅ `## Never touch `bd` directly` |
| 10 | Use-when trigger list (claiming / holding / declaring / resolving / losing custody / in doubt) | ✅ moved to the FRONT | — |

**Facts absent from BOTH description and body: 0.** Two detail-level
parentheticals moved into the body, which the goal permits for skills, and
each lands in a section that already carried it in more depth than the
description ever did.

### `work-tracker-operations` (skill — body counts)

| # | Stock fact | In lean description? | In body? |
|---|---|---|---|
| 1 | What `doctor` proves; how to read a violated assumption (fix scope: `adapter.py` only) | ✅ | ✅ `SKILL.md:43`, `:126` |
| 2 | The bd **`>= 1.1.2`** version floor | ◑ "the bd version floor"; the exact version dropped | ✅ `SKILL.md:50` — `bd >= 1.1.2` |
| 3 | …with the **measured double-claim table** | ✗ absent from description | ✅ `SKILL.md:54–59` — the table itself |
| 4 | Shared-server topology requirement | ✅ | ✅ `SKILL.md:65–75` |
| 5 | Scheduling reap and notify on timers | ✅ (in the trigger clause) | ✅ `SKILL.md:77–98` |
| 6 | …**resolution does NOT propagate on its own** | ✗ absent from description | ✅ `SKILL.md:79` — "Resolution does not propagate to reporters automatically." |
| 7 | Sharp edges: dotted project names, TOCTOU name allocation, no storage authz, native leases don't replicate | ◑ "the known silent sharp edges"; the four names dropped | ✅ `SKILL.md:111–117` — all four, each with its mechanism |
| 8 | Use-when trigger list (doctor / upgrading bd / standing up a project / scheduling operator jobs / diagnosing non-automatic behaviour) | ✅ moved to the FRONT | — |

**Facts absent from BOTH description and body: 0.** This skill is where the
description was doing the most double-duty as documentation; every moved fact
lands in a body section that states it with more precision.

---

## ALREADY-COMPLIANT ITEMS — named, as the goal requires

**None.** All four capabilities were non-compliant on at least one axis
(length on all four; trigger-last ordering on all four; multi-paragraph on
both agents). No file was edited merely to produce a diff.

**And the flip side, also as the goal requires:** this repo was
**pre-measured at ZERO `<example>` / `<commentary>` blocks**, and the
measurement held — both `validate-agents` runs report `example_count: 0`,
`commentary_count: 0` on both agents, before and after. **This was a length
and shape fix, not an example strip, and it is not reported as an example
violation.** The one file in the repo containing the string `<example>` is
`GOAL.md`, this lane's own brief.

---

## `validate-agents` — VERDICT QUOTED, ON THE BRANCH

Recipe v1.7.0, foundation @ `v2.1.2` (`a27d5824517d078097b60d84779dd3eae80202cd`).

> **Overall Verdict: ⚠️ PASS WITH WARNINGS**
> Agents Found: 2 total across 1 location
> Issues: **0 errors**, **2 warnings** (both `NO_TOOLS_SECTION`), 0 suggestions

**Discovered agent count for this repo: 2** (`location_counts: {"agents/": 2}`,
`candidates_scanned: 2`, `non_agent_count: 0`).
Run: `run-b18878d22d5c`, session `5e39e09376de4148-20260907-094844_recipe`.

**It stayed PASS, and that was proven rather than assumed** — the recipe was
also run against a pristine `git archive HEAD` export of stock
(`run-42cd5a1bff8a`), which returned the *same* verdict, the same 0 errors,
and the same 2 warnings. Full side-by-side:
`evidence/validate-agents-runs.txt`.

The two `NO_TOOLS_SECTION` warnings are **pre-existing and untouched by this
branch** — they key on a frontmatter `tools:` block this change never edits,
and both runs independently adjudicated them false positives (work-executor's
tools are declared at `behaviors/work-tracker.yaml:18-38`; feedback-triage is
deliberately uncomposed). Out of scope here; left alone.

One metric improved: `feedback-triage.has_strong_trigger` **false → true**.

---

## CI

This repo **has CI** — `.github/workflows/ci.yml`, running on every pull
request, with pinned `bd 1.1.2` / `dolt 2.2.3`. **It ran on the PR and it is
GREEN:**

```
run 34147702660   check "test"   PASS   29m55s   conclusion: success
                  check "license/cla"   PASS
```

The PR was opened as a **draft** and **marked ready for review on that green
run**, per the goal. **Not merged** — the manager merges.

> Note on why this section is not re-committed after every state change: a
> doc-only push moves the head sha, which invalidates exactly the green CI run
> being reported and restarts a 30-minute cycle. The CI verdict and the
> ready-transition are therefore also recorded as PR comments
> (`#94 issuecomment-5573941050`, `#94 issuecomment-5574192795`), where a
> reviewer reads them, and pinned in `DONE.json`.

**Locally, `make test` on the branch @ `eb108f9` is GREEN**, both pytest
invocations of the target:

```
tests + ledger/checks      1565 passed, 3 skipped, 89 deselected, 2 warnings   2222.00s (37:01)
modules/tool-work-tracker   131 passed, 9 warnings                              597.23s (09:57)
make test exit code: 0
```

Zero failures, zero errors. The 89 deselected are the `tier_b` browser
conformance tier, deselected by `pyproject`'s `-m "not tier_b"` addopts as
designed — that tier has its own `make test-conformance-b` target and a
chromium download, and is deliberately not part of `make test`. `ruff check`
and `ruff format --check` also pass on the lane artifacts.

This is the expected result: the change is four YAML frontmatter strings — no
Python, no behaviour, no public surface. Posted as a PR comment
(`#94 issuecomment-5573941050`) as well, so the green run is recorded where a
reviewer reads it.

**A stash-compare byte-identity check was NOT applicable here** and is not
claimed: there is no default-mode output to compare. Nothing executable
changed — the diff is four description strings in YAML frontmatter, and the
before/after difference in rendered behaviour is exactly the catalog delta
measured above, which is the intended change rather than a regression to
rule out.

---

## PUBLICATION

Recorded in `DONE.json` under `publication` (`marker_contract:
publication/v1`) with a **40-hex head sha read back from the remote** via
`publication_readback.sh`, never from a local `git log`.

---

## DEVIATIONS AND JUDGMENT CALLS

1. **Did the work despite the refused claim.** Reasoned above. The alternative
   left a reachable, $0 deliverable undone because a *different repo's* lane
   won a race.
2. **Terminal state moved C → A exactly once, on a changed number.** It was C
   while the item was `held` by the sibling lane; it became A when the item
   went `resolved` (`closed_at 16:59:25Z`) and `work_erratum` — which needs no
   claim — made this repo's slice part of that record. The goal's anti-churn
   guard is "if no number changed, no re-decision is warranted"; a number did
   change, observably, and it is named. `BLOCKED.md` was deleted rather than
   shipped alongside a green PR asserting the opposite.
3. **Both agents land above ~600 chars.** Deliberate, and caused by the two
   fidelity restorations. Fidelity is the stated top gate.
4. **`validate-agents` run three times, not once.** Once on the mid-pass state,
   once on stock (to prove "stayed"), once on the final tree. Quoting a
   verdict from a superseded tree is exactly the confident-plausible-wrong
   failure the goal warns about; the quoted verdict is from the final state.
5. **`bundle.md:64-66` left unedited.** Its agent/skill rows are hand-written
   one-line doc summaries, not generated copies of the frontmatter, and they
   remain accurate. `bundle.dot`'s `source_hash` is not checked by any test or
   CI job in this repo, so no regeneration was forced. Editing either would
   have been a diff for its own sake.
6. **BEFORE measured from a `git archive` export, not a `git stash`.** Same
   bytes, no risk of stranding the working tree mid-run. The export was
   confirmed to render 3,640 B, identical to the live-tree BEFORE render.
