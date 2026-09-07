# Lane hd-work-tracker — DONE-NOTE

**Item:** `model_performance-b1tw` — lean head: amplifier-work-tracker's OWN
surface (21 tool descriptions + `context/awareness.md`), hazards MOVED to
where they act.
**Repo:** `microsoft/amplifier-work-tracker`.
**Branch:** `lane/hd-work-tracker` from `main` @ `7fcb10e` (merge-base
verified: `git merge-base HEAD origin/main` → `7fcb10e429345983c65435949e3ae3ac5b317105`).
**Date:** 2026-09-07.
**Spend:** **$0.00**, against an authority of `0 runs x 0 arms x $0 / 1.00 =
$0.00`, slack **$0.00**. No API measurement, no DTU, no infrastructure row
created, nothing to tear down. Work performed: text edits, one scratch-home
render measurement, and test runs — all inside the goal's stated allowance
("Text edits, a render measurement, a test run"). The arithmetic closes
trivially because the cap funds no purchases; there was no deliverable here
money could have bought. **Residue: $0.00**; the smallest useful purchase it
could not buy is not applicable — nothing on this item was purchasable.

---

## TERMINAL OUTCOME: **A — RESOLVED, deliverables shipped**

Every deliverable is DONE. Nothing is NOT-POSSIBLE, so branch B does not
apply; nothing was unreachable for a non-cap reason, so branch C does not
apply. Per the goal's LANDING STAGE clause, the deliverables are complete at
the **draft PR** — the merge is the manager's next stage.

---

## FIRST, THE GOAL DEFECT — read this before the rest

**The goal's Procedure step 1 told this lane to claim `model_performance-6f80`
and treat its description as "the authoritative spec". `6f80` is a different
job in a different repo.**

| | |
|---|---|
| What GOAL.md's Task/DELIVERABLES describe | `amplifier-work-tracker`'s own head cost: 21 tool descriptions + `work-tracker-awareness.md` |
| What this lane was provisioned with | worktree `amplifier-work-tracker`, branch `lane/hd-work-tracker`, artifact root `docs/lanes/hd-work-tracker/` |
| What `6f80` actually is | "STAGE 1 (C): tool-delegate must STRIP example/commentary blocks at catalog-render time" — repo `amplifier-module-tool-delegate`, which per `model_performance-j1e6`'s resolution **returns 404** |

`6f80`'s deliverables are unreachable from this worktree **by construction**:
the lane's own SCOPE-OUTS forbid touching another repo, and the goal's own
preamble names that case — *"If the only way to satisfy a deliverable is to
write a file outside your worktree (another repo …), that is a DEFECT IN THIS
GOAL, not a task. Report it against the goal … and resolve."*

**What this lane did, in order:**

1. `work_claim(item_id="model_performance-6f80")` — succeeded, returned the
   tool-delegate spec, mismatch detected on first read.
2. `work_release(id="model_performance-6f80")` — released **untouched, no
   resolution set**, so its proper lane can still take it. Its record is NOT
   contaminated with unrelated resolution text; that exact failure mode is
   already on the books as `model_performance-69y`.
3. `work_add(...)` → **`model_performance-b1tw`**, carrying the work the
   goal's Task section actually describes, linked `relates-to`
   `model_performance-hyid` (the lean-head tracker) and `model_performance-mse0`
   (awareness-file dedupe). Claimed and executed.
4. `work_file(...)` → **`model_performance-z7nk`**, the goal defect, filed
   `discovered-from` b1tw with a proposed authoring rule.

This is the same class already filed as `model_performance-pq7q` ("a goal's
deliverable list must be checkable against the lane's provisioned worktrees at
authoring time"). The one-line fix z7nk asks for: **the goal-authoring step
must cross-check the cited item id against the repo the lane is provisioned
in** — checkable by the lane on first read, exactly like the spend-arithmetic
AUTHORING RULE step 3 already carries.

No fourth outcome branch was invented, no other repo was touched, and the
terminal state was chosen **once**.

---

## DELIVERABLE 1 — 21 tool descriptions, trigger-first, ≤ ~600 chars — **DONE**

Every description now opens with **USE WHEN** (or **USE FIRST**), carries an
explicit **DO NOT USE WHEN**, and keeps the parameter semantics a caller
genuinely needs. Measured in-process against the shipped `description`
properties (`docs/lanes/hd-work-tracker/evidence/measure_tools.py`):

| tool | before | after | delta |
|---|---:|---:|---:|
| `work_claim` | 942 | 591 | -351 |
| `work_declare` | 421 | 579 | +158 |
| `work_resolve` | 337 | 593 | +256 |
| `work_reopen` | 1473 | 598 | -875 |
| `work_erratum` | 837 | 599 | -238 |
| `work_release` | 554 | 530 | -24 |
| `work_status` | 526 | 562 | +36 |
| `work_stats` | 403 | 594 | +191 |
| `work_file` | 293 | 539 | +246 |
| `work_add` | 622 | 589 | -33 |
| `work_move` | 816 | 576 | -240 |
| `work_edit` | 617 | 589 | -28 |
| `work_defer` | 332 | 424 | +92 |
| `work_block` | 415 | 453 | +38 |
| `work_dep` | 375 | 491 | +116 |
| `work_list` | 926 | 596 | -330 |
| `work_subscribe` | 625 | 564 | -61 |
| `work_unsubscribe` | 260 | 304 | +44 |
| `work_subscriptions` | 171 | 243 | +72 |
| `work_tracker_status` | 1242 | 606 | -636 |
| `work_tracker_install` | 571 | 586 | +15 |
| **TOTAL (21)** | **12,758** | **11,206** | **−1,552 (−12.2%)** |

**Read the +/- column honestly.** Eleven descriptions GREW. That is the
change working, not failing: the seven hazards deleted from an always-on file
landed in the tools they are about, so `work_resolve` (+256), `work_file`
(+246) and `work_stats` (+191) each absorbed a rule that used to be billed to
every session whether or not the tool was ever called. The nine bloated ones
(`work_reopen` −875, `work_tracker_status` −636, `work_claim` −351,
`work_list` −330) paid for all of it and 1,552 chars over.

**Descriptions still over ~600, and the contract that forced each:**

| tool | chars | what forced it |
|---|---:|---|
| `work_tracker_status` | **606** | The **three no-fix running states** are named in full on purpose. `running_healthy` / `running_unmanaged` / `running_systemd_unreachable` all mean *the server works* — an agent that reads only two of them stops a healthy dolt server that other lanes are using. That is the tool's own documented hazard (its `fix` field exists precisely because two of those states look broken and are not), and 6 chars over a "~600" bar is not a trade worth making. |

Nothing else exceeds 600. Max = 606, mean = 534.

**Schema bytes were deliberately NOT touched** (9,748 chars, unchanged). The
largest single line item there is `adapter.NAME_RULE` repeated verbatim on
**14 project-name parameters** (~2,464 chars, 25% of the schema surface).
That repetition is a **contract**: `modules/tool-work-tracker/tests/test_project_name_rule.py`
asserts the rule appears *verbatim* on every project-name parameter and that
exactly 14 exist, and commit `4c37b16` put it there because sessions kept
naming projects with dashes, failing, and retrying. Trimming it is a separate,
owner-visible decision, not a byte-reduction side effect. **Recommendation for
the manager:** leave it; the measured cost of the rule living somewhere an
agent does not read before its first call was real.

## DELIVERABLE 2 — `context/awareness.md` → concept + trigger + pointer — **DONE**

**7,529 → 708 bytes (−90.6%).** The whole file is now one concept sentence and
one pointer sentence. Full fidelity table below — **no fact silently dropped**.

## DELIVERABLE 3 — fact-by-fact fidelity table — **DONE** (next section)

## DELIVERABLE 4 — every over-budget description NAMED — **DONE** (table above)

## DELIVERABLE 5 — a pin test — **DONE**

`modules/tool-work-tracker/tests/test_description_pins.py`, 25 tests:

* every mounted tool is measured (21, asserted — a tool added to `mount()`
  and forgotten here fails the count),
* every description is trigger-first,
* every description names when NOT to use it,
* no description exceeds 610 chars ("~600" plus a few chars of tolerance),
* the whole surface stays under 11,600 chars,
* **each of the seven hazards is pinned, by phrase, to the tool it acts at**
  (19 parametrised cases),
* `context/awareness.md` stays ≤1,200 bytes and has not regrown any of the
  five operating rules that moved out.

**FAIL-BEFORE / PASS-AFTER, both quoted:**

```
# at main (product changes stashed, test file present):
20 failed, 5 passed in 0.25s      docs/lanes/hd-work-tracker/evidence/pin-test-fail-before.txt

# on this branch:
25 passed in 0.23s                docs/lanes/hd-work-tracker/evidence/pin-test-pass-after.txt
```

The 5 that passed before are recorded honestly: main's `work_claim` already
said "a normal terminal outcome", `work_add` already said "never fall back to
a raw storage-layer CLI", `work_erratum` already said "APPEND-ONLY",
`work_reopen` already said "CLEARS closed_at", and the 21-tool count already
held. A test that only ever goes green proves nothing; these five were already
true and are now pinned.

## DELIVERABLE 6 — before/after bytes for BOTH surfaces, from a scratch session on the owner's app list — **DONE**

Measured by booting `amplifier tool info <name> --format json` in a scratch
`AMPLIFIER_HOME` seeded from a **copy** of `~/.amplifier/settings.yaml`
(`/tmp/b1tw-amp-home`). **The real `~/.amplifier/` was never written to** —
`zc6t`'s finding F6 (`amplifier source add` ignores `AMPLIFIER_HOME`) was
avoided by never calling `source add`: the after-side was produced by patching
the scratch home's own **copy** of the bundle cache, not the shared one.

| surface | before | after | delta |
|---|---:|---:|---:|
| tool descriptions, this bundle's 21 | 12,758 | 11,206 | **−1,552 (−12.2%)** |
| tool descriptions, whole app list (86 tools) | 120,620 | 119,068 | −1,552 (−1.29%) |
| context file `context/awareness.md` | 7,529 | 708 | **−6,821 (−90.6%)** |
| **combined always-on head, this bundle** | **20,287** | **11,914** | **−8,373 (−41.3%)** |

≈ **−8.4 KB off the head of every turn of every session that mounts this
bundle**, or roughly **−2,100 tokens per request** at 4 chars/token.

**Verified against a value already known** (the goal's own instruction): the
scratch session's BEFORE work_* slice is **12,758 chars — byte-identical to
the in-process measurement** and to `origin/main`, and the live cache this
session itself runs from
(`~/.amplifier/cache/amplifier-work-tracker-226b28f571473a91`) `diff`s clean
against `origin/main` for both the tool module and `context/awareness.md`. So
the "before" is not a reconstruction; it is what the owner's sessions are
paying right now.

**Control:** five tools from other bundles, re-measured on the after side,
moved **exactly 0 bytes** — `read_file` 725→725, `bash` 1,318→1,318,
`load_skill` 968→968, `delegate` 47,877→47,877, `todo` 526→526. The −1,552 is
this bundle's, and only this bundle's.

**Also worth the manager's attention, from the same census:** `delegate`'s
description is **47,877 chars — 39.7% of the entire 120,620-char tool-
description surface on this app list, and 4.3× this whole bundle's 21 tools
combined.** It is the dynamic agent catalog. That is not this lane's repo and
was not touched; it is the single largest remaining item on this surface by a
wide margin, and `model_performance-6f80` (the item this lane's goal
mis-cited) is precisely the work that trims it.

## DELIVERABLE 7 — CI green — **DONE**

## DELIVERABLE 8 — draft PR, manager merges — **DONE**

**PR #95** — <https://github.com/microsoft/amplifier-work-tracker/pull/95>,
`microsoft/amplifier-work-tracker`, branch `lane/hd-work-tracker`. Publication
values read back from the remote with
`publication_readback.sh`, not from local `git log`.

---

## FIDELITY: every fact in the old `context/awareness.md`, accounted for

33 facts. **MOVED** = the fact now lives where it fires, destination named.
**DELETED** = redundant with a catalog line that is already always-on, that
line named. **KEPT** = still in the awareness file.

### Header

| # | fact | disposition |
|---|---|---|
| F0 | "You're one of several agents pulling from a shared work queue" | **KEPT** — the concept sentence |
| F1 | first use in a session / any failed `work_*` connection → `work_tracker_status` | **KEPT** as the trigger, **and MOVED** into `work_tracker_status`'s description ("USE FIRST … and whenever a `work_*` call fails to connect") |

### Hazard 1 — claim only via `work_claim`; never list-then-pick

| # | fact | disposition |
|---|---|---|
| F2 | never list-then-pick; `work_claim` is the single atomic claim-and-custody operation | **MOVED** → `work_claim` description ("The ONLY atomic claim … Never list-then-pick") |
| F3 | "double-claimed in 2 of 8 measured trials, and every losing agent still got exit 0" | **MOVED** → `work_claim` ("double-claims SILENTLY (2 of 8 measured trials, all losers exit 0)"). The full 4-row measured table stays in `claiming-work-safely` §"Why the obvious approach is wrong" |
| F4 | "There is no other way to take an item" | **MOVED** (compressed into "The ONLY atomic claim") |

### Hazard 2 — custody is a liveness signal, not a timer

| # | fact | disposition |
|---|---|---|
| F5 | idle time never costs a claim; only an unrenewed signal does | **DELETED** — verbatim in `claiming-work-safely` §"Custody: freshness, not duration" ("Total hold duration is irrelevant. Only recency of the last renewal matters.") |
| F6 | renewal is one-strike — "a single failed renewal ends renewal permanently — there is no retry on the next tick" | **MOVED** → `work_status` description, **verbatim**; ledger row `CCV1-005` re-anchored to it (see below). Also already in the skill §"Renewal is one-strike" |
| F7 | the only way to find out is `work_status`'s non-null `holding.custody_lost` | **MOVED** → `work_status` description |
| F8 | check it before any long-running step and after any tool error | **MOVED** → `work_status` description |
| F9 | "The TTL does not enforce itself" — unrenewed = reclaim-*eligible*, the out-of-band `reap` sweep is what reclaims | **MOVED** → `work_stats` description; ledger row `CCV1-008` re-anchored to it. Also already in the skill |
| F10 | a reclaim lands up to a sweep interval (300s default) AFTER the TTL | **DELETED** — in `claiming-work-safely` §"Custody: freshness, not duration" ("A reclaim arrives up to a sweep interval late — expect ~15–20 min … not exactly 15") **and** its constants table row `Reap sweep interval / 300s`. Deliberately not put in a tool description: it is a number a caller cannot act on at call time |
| F11 | a dead agent's hold persists indefinitely where no sweep runs — never wait on a stuck held item | **MOVED** → `work_stats` description |
| F12 | `awaiting_human` suppresses a notification only; never exempts from the clock | **MOVED** → `work_declare` description ("buys ZERO exemption from the custody clock") |

### Hazard 3 — an empty queue is a normal terminal outcome

| # | fact | disposition |
|---|---|---|
| F13 | `claimed: null` → stop and report; do not invent work or retry | **DELETED as redundant** with `work_claim`'s own catalog line, which said "a normal terminal outcome, not an error" **before** this change and now says "stop and report, never retry or invent work". Pinned by the new test |

### Hazard 4 — never speak to `bd` directly

| # | fact | disposition |
|---|---|---|
| F14 | every interaction goes through the `work_*` tools or the `amplifier-work-tracker` CLI | **DELETED** — `claiming-work-safely` §"Never touch `bd` directly" already lists exactly those verbs |
| F15 | "Nothing else knows Beads' field names or CLI shape, and that seam is what keeps upstream changes from silently corrupting parallel work" | **MOVED** → into that same skill section, which was missing the clause (and whose closing paragraph was **spliced mid-sentence**; repaired in the same edit). Trigger-moment restatements are in `work_add` ("never fall back to a raw storage-layer CLI") and `work_list` ("never use a raw storage-layer CLI"), both pre-existing, both now pinned |

### Hazard 5 — if `work_resolve`/`work_declare` refuses as reclaimed, stop

| # | fact | disposition |
|---|---|---|
| F16 | do not retry resolving or declaring — someone else may hold it now | **MOVED** → `work_resolve` ("then STOP, do not retry, report what you left behind") and `work_declare` ("STOP — do not retry it and do not re-claim that item to resume"). Full procedure stays in the skill §"After a reap: stop, don't retry" |
| F17 | `work_claim` still works afterward for new work | **MOVED** → `work_declare` ("work_claim still works for new work") |

### Hazard 6 — a reported write failure is UNKNOWN

| # | fact | disposition |
|---|---|---|
| F18 | "A reported write failure does NOT prove the write failed — treat it as UNKNOWN and re-read before you retry" | **MOVED VERBATIM** → `claiming-work-safely` §"A reported write failure is UNKNOWN, not 'didn't happen'"; ledger row `CCV1-016` re-anchored to it |
| F19 | the shared single-writer dolt server, the error signatures ("still conflicting after 8 retries", 1213/1205, …) | **MOVED VERBATIM** → same skill section |
| F20 | `work_resolve`/`work_release` re-read on conflict, so a reported SUCCESS from those two is confirmed | **MOVED VERBATIM** → same skill section, **and** to both tools' descriptions ("a reported success here is confirmed") |
| F21 | every other write verb surfaces the raw conflict unverified — a reported failure means *unknown* | **MOVED VERBATIM** → same skill section, **and** the trigger-moment half to `work_add` ("does NOT prove the write failed") and `work_file` ("does NOT prove nothing was written") |
| F22 | never resubmit a non-idempotent write blind; re-read via a read-only path that cannot itself conflict | **MOVED VERBATIM** → same skill section, **and** "re-read with work_list" into `work_add`/`work_file`; `work_list` now advertises itself as "the safe re-read after a reported write failure" |

### Hazard 7 — correcting a published resolution

| # | fact | disposition |
|---|---|---|
| F23 | never correct by re-resolving; pick by whether the RECORD or the WORK is wrong | **MOVED VERBATIM** → `claiming-work-safely` §"Correcting a published resolution" |
| F24 | `work_resolve` on an already-resolved item is a no-op **only** when byte-identical; different text fails non-zero and writes nothing (7 wrong resolutions shipped before this) | **MOVED VERBATIM** → same skill section, **and** to `work_resolve`'s description ("byte-identical is a no-op, different text fails and writes nothing") |
| F25 | `work_erratum` — append-only, no claim, idempotent, errata travel with the item | **MOVED VERBATIM** → same skill section; already stated in `work_erratum`'s own description |
| F26 | `work_reopen` — not idempotent, clears `closed_at`, moves throughput roll-ups by one | **MOVED VERBATIM** → same skill section; already stated in `work_reopen`'s own description |
| F27 | erratum first if only the record is wrong; reopen only if the work is | **MOVED VERBATIM** → same skill section; both tools' DO NOT USE clauses now point at each other |

### "Naming a project"

| # | fact | disposition |
|---|---|---|
| F28 | underscores not dashes, `^[a-z][a-z0-9_]{1,30}$`, refusal names the underscore form | **DELETED as redundant** with the **14 project-name parameter descriptions** that carry `adapter.NAME_RULE` verbatim — asserted, count and text, by `modules/tool-work-tracker/tests/test_project_name_rule.py` |

### "Where to go next"

| # | fact | disposition |
|---|---|---|
| F29 | no server / unsure → `work_tracker_status` (→ `work_tracker_install`) | **KEPT** |
| F30 | claiming/working/resolving → delegate to `work-tracker:work-executor` | **KEPT** |
| F31 | full claim/custody procedure, post-reap → `claiming-work-safely` | **KEPT** |
| F32 | `doctor`, the seam, `reap`/`notify` scheduling → `work-tracker-operations` | **KEPT** |
| F33 | read an item without claiming: pass `item_id` to `work_list` | **DELETED as redundant** with `work_list`'s own catalog line ("Pass item_id for ONE item's FULL record … never claim an item just to read it") and the skill §"Reading without claiming" |

**Count: 33 facts — 18 MOVED, 6 DELETED-as-redundant (each with the naming
line), 5 KEPT, 4 KEPT-and-MOVED. Zero dropped.**

---

## The part that needed care: three ledger rows PINNED the deleted prose

`context/awareness.md` was not just documentation. Three rows of the
conformance ledger for the **locked** `contracts/custody-coordination.v1.md`
asserted its exact sentences, and the ledger runs in CI (Tier 4):

| row | clause | what it pinned in `awareness.md` | now pinned in |
|---|---|---|---|
| `CCV1-005` | Core 4 — renewal is one-strike | "a single failed renewal ends renewal permanently — there is no retry on the next tick" + `holding.custody_lost` | **`work_status`'s rendered description** (skill leg unchanged) |
| `CCV1-008` | Core 6 — the TTL is not self-enforcing | "The TTL does not enforce itself…" + "persist indefinitely where no sweep runs" | **`work_stats`'s rendered description** (skill leg unchanged) |
| `CCV1-016` | Core 11 — a reported write failure must not contradict the state | the whole hazard-6 block | **`claiming-work-safely/SKILL.md`** (verbatim), **plus** 4 new trigger-moment assertions on `work_resolve`/`work_release`/`work_add`/`work_file`. CLI leg unchanged |

**No contract file was edited.** The clauses say "the agent-facing prose that
states it" and "both prose surfaces" — they never named `context/awareness.md`;
only the ledger's own probes did. Both-directions pinning is preserved
everywhere (the corrected claim must be present AND the wrong phrasing must
stay gone), disposition stays CONFORMS on all three, and each row's `notes`
now records the re-anchor and why — the ledger's own "RE-ANCHORED" precedent.

Two supporting changes were required and are honest about their limits:

1. **`ledger/checks/_support.py` gained `tool_descriptions()` /
   `description_contains()`.** `contains(TOOL_MODULE, …)` **cannot** pin a
   description: a description is written as adjacent string literals, so the
   source carries `" "` boundaries a collapsed snippet never matches, and a
   probe written that way would pass vacuously. These read the **rendered**
   description — what an agent actually sees. Still in-process and hermetic:
   no bd, no dolt, no network, no subprocess; the session's workspace root is
   pinned to a throwaway temp dir.
2. **The mutation harness's `CCV1-008` and `CCV1-016` counterfactuals were
   re-pointed** from `awareness.md` to the skill. `make ledger-mutate`
   patches **files**; it cannot patch a rendered description. **HONEST LIMIT,
   recorded in the row notes:** the description legs of `CCV1-005`/`008`/`016`
   are **not** mutation-covered. Their discriminating check is the new pin
   test, which goes red if the phrase moves — demonstrated by the 20-failure
   fail-before run.

Without this, the change would have been a red build. With it, `make
ledger-mutate` reports every mutation proven and `ledger/checks` is 60 passed.

---

## Verification

| check | result |
|---|---|
| `ruff check .` | **All checks passed!** |
| `ruff format --check .` | **198 files already formatted** |
| `pyright src tests` | **0 errors, 0 warnings, 0 informations** |
| `pytest ledger/checks` (Tier 4 + mutation harness) | **60 passed** |
| `pytest modules/.../test_description_pins.py` | **25 passed** (20 failed at main) |
| `pytest modules/.../test_project_name_rule.py` | passed — the 14-parameter NAME_RULE contract is untouched |
| full suite, root tier (`pytest tests ledger/checks`) | **1,565 passed, 3 skipped, 89 deselected** in 36m55s, rc=0 |
| full suite, module tier (`pytest modules/tool-work-tracker/tests`) | **156 passed** in 10m40s, rc=0 |
| **CI** | **SUCCESS on every commit of this branch** — `1ab580f` run [34162236937](https://github.com/microsoft/amplifier-work-tracker/actions/runs/34162236937) (31m03s), `ce0bf88` run [34164256876](https://github.com/microsoft/amplifier-work-tracker/actions/runs/34164256876), `77a4398` run [34164362689](https://github.com/microsoft/amplifier-work-tracker/actions/runs/34164362689). All `conclusion: success` |

`1ab580f` is the commit carrying every product, ledger and test change; the
later commits are documentation and evidence under this lane's artifact root
only, and each was verified green in its own right rather than assumed. The
commit that adds *this* line is necessarily a fourth; its run id is recorded
in `DONE.json`, which is written after it goes green — this note does not claim
a verdict for a run that had not finished when it was written.

The 89 deselected are the Tier-B browser kit (`-m "not tier_b"` in pyproject's
addopts); CI runs that tier as its own step and the whole run concluded
`success`, so it is covered there. The 3 skips are pre-existing.

**PR state:** opened as a **draft** (PR #95) and **marked ready for review on
the green run**, following this repo's own precedent — PR #94 (kv98) did
exactly that. The goal text says both "DRAFT PR; the manager merges" and
"DRAFT PR, mark ready when green, stop"; that tension is already filed as
`model_performance-41rx` and `model_performance-kn0e` and is not this lane's
to adjudicate. **Not merged. The merge is the manager's stage.**

---

## What remains open

1. **The merge** — manager's stage. Draft PR, marked ready when CI is green.
2. **`model_performance-6f80` is back in the queue, unclaimed and untouched.**
   It is real work (render-time example stripping in tool-delegate) and,
   per the census above, it targets the single largest description on the
   surface (`delegate`, 47,877 chars). It needs a lane provisioned in the
   right repo — and per `j1e6`, that repo currently 404s, which is its own
   blocker.
3. **`model_performance-z7nk`** — the goal-authoring cross-check. One line in
   the template.
4. **The 14× `NAME_RULE` repetition** (~2,464 chars of schema, 25% of this
   bundle's schema surface) is deliberately untouched. It is contract-pinned
   and was added for a measured reason. Raising or trimming it is an
   owner-visible decision; this lane declined to make it as a side effect of a
   byte reduction.
5. **`publication_readback.sh` returns a stale `head_sha` and exits 0** —
   reproduced live by this lane 40 seconds after a push, and root-caused to
   one block: the script reads the authoritative sha from `git ls-remote` and
   then **overwrites it** with `gh pr list`'s `headRefOid`, which lags a push.
   Filed as `model_performance-lsda`, linked `relates-to`
   `model_performance-17oq` (which predicted the symptom) and relevant to
   `model_performance-fr47`. A two-option patch (minimal / fail-loud, with a
   recommendation) is shipped as an artifact at
   `docs/lanes/hd-work-tracker/proposed-publication-readback-patch.md` —
   **not applied**, because the script lives in another repo this lane must
   not edit. **This lane's own `DONE.json` carries the value `git ls-remote`
   and `gh pr view` agree on, re-read after the final push — not the value
   the script printed.**
6. **The skill grew 11,208 → 14,724 bytes (+3,516)** as hazards 6 and 7 landed
   there. That is pay-per-use, not pay-per-turn: it is charged only to a
   session that actually loads `claiming-work-safely`, which is the whole
   point of the move. It does mean the *combined repo prose* fell by less than
   the head did (−8,373 head, −4,857 repo-wide), and both numbers are stated
   here rather than only the flattering one.
