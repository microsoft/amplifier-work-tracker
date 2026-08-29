# Vision: amplifier-work-tracker

**Status:** direction-setting. Not a spec, not a roadmap, not a promise of features.
**Audience:** anyone about to add, remove, or change something here -- and anyone deciding
whether a proposed change belongs in this project at all.
**Companions:** [`docs/DESIGN.md`](DESIGN.md) (how the report/issue split works and why),
[`AGENTS.md`](../AGENTS.md) (the contributor gates), [`context/awareness.md`](../context/awareness.md)
(the runtime hazards an agent must know).

---

## The desired end state, in one paragraph

**Many autonomous agent sessions share one work queue, for hours at a time, and none of the
ways that can go wrong go wrong *silently*.** An agent takes work and provably holds it. It
sits idle for three hours waiting on a person and still holds it. It dies mid-flight and the
work comes back, once, to exactly one other agent. It finishes and the human who reported the
underlying problem hears about it. Every failure in that chain announces itself, in the
vocabulary of the thing that actually broke -- never as a plausible-sounding message pointing
at something else. That last clause is the whole project in miniature: the hard part was never
making the happy path work, it was making the unhappy path *honest*.

---

## The tensions this project exists to resolve

These are the real forces pulling in opposite directions. Every design decision here is a
resolution of one of them, and naming them is how a future contributor can tell whether a
proposed change is resolving a tension or just adding surface.

**1. Beads moves fast; we need to not.**
Beads (`bd`) is excellent and under active development -- its field names, CLI flags, and
exit-code semantics are not ours to depend on. But a coordination layer that churns with its
dependency is worthless. *Resolved by:* one seam. All `bd` knowledge lives in
`src/amplifier_work_tracker/adapter.py` and nowhere else -- the field mapping is literally one
dict (`_FIELD_MAP`), the status vocabulary is one dict (`_STATUS_MAP`, where an unrecognised
value passes through rather than being coerced into looking like a known one). Everything above
the seam speaks our vocabulary. A Beads upgrade has exactly one file to reckon with.

**2. Correctness under concurrency vs. the obvious way to write it.**
The natural way to claim work -- list the queue, pick one, mark it yours -- is wrong, and it is
wrong *silently*: measured, 2-3 agents each get exit 0 and each believe they own the same item
(see `docs/DESIGN.md`'s retraction table). *Resolved by:* the unsafe primitive is not exposed
anywhere above the seam. `Beads.claim_next` calls `bd ready --claim` and offers no two-step
path at all. You cannot write the bug here, because the API to write it does not exist.

**3. A read must not be able to lose to a write.**
The single-writer shared dolt server serialises writers on purpose -- that is what makes claims
safe. But `bd list` is a read that also *writes* (an interaction-log row per invocation), so a
large listing holds a write transaction open long enough to reliably lose a serialization
conflict (MySQL 1213/1205) against ordinary background traffic. A 465-item project burned the
full 8-retry budget (~23s) and failed; a 17-item project almost never lost. *Resolved by:*
reads that only read go over a pure SQL `SELECT` (`_summary_items_via_sql`, `_list_rows_via_sql`)
with no write set, so they *cannot* conflict at any project size. The conflict window was
eliminated, not widened.

**4. Capture must be cheap; handoff must be rich.**
An idea nobody bothers to file is worth nothing; an item a cold session cannot execute is worth
almost nothing. These pull opposite ways at exactly the moment the filer is busiest. *Resolved
by:* not by lowering either bar -- by separating the two objects. A report is a user's raw words;
an issue is a considered spec with acceptance criteria; they are linked, never merged. See
`docs/DESIGN.md` and [`docs/design/cold-startable-authoring.md`](design/cold-startable-authoring.md).

**5. Trusting what a process reports vs. verifying what actually happened.**
An exit code says a command ran, not that it did what it said. *Resolved by:* read-back
verification as a standing discipline -- `Beads.resolve` and `Beads.update` both re-read the
item and raise if the change did not land ("exit code is not proof"), `Workspace.create` proves
the database is writable immediately after `bd init` reports success with green checkmarks, and
`contract.py`'s `CHECKS` prove every behaviour we depend on live against the installed binary
rather than trusting its documentation.

**6. Human attention is the scarcest resource in the system.**
Agents are cheap and parallel; the person is not. *Resolved by:* the return path (`notify`
walks the `discovered-from` links and flips reports closed with the real resolution text), the
`awaiting_human` declaration (which suppresses a notification without buying exemption from the
custody clock), and a dashboard whose badges are required to show signals that actually vary
with real data rather than constants that carry no information.

---

## What this project IS

- **A coordination layer over Beads.** Safe atomic claiming, custody that survives hours of
  agent idle time, and a return path back to whoever reported the problem.
- **One seam, deliberately thin.** `adapter.py` is the only thing that knows `bd` exists.
- **A trust boundary.** The Feedback Gateway authenticates every caller to exactly one reporter
  identity via bearer token and redacts free text *before* it reaches effectively-permanent
  git/Dolt history. Untrusted product agents never touch the work graph.
- **An operator surface.** `new` / `remove` / `rename` / `move` / `instances` / `service` /
  `doctor` / `web`, plus the supervisor that keeps the shared dolt server and the reap/notify
  sweeps alive across reboots.
- **An agent surface.** `work_claim`, `work_declare`, `work_resolve`, `work_release`,
  `work_status`, `work_stats`, `work_list`, `work_add`, `work_file`, `work_move`, and the
  service pair `work_tracker_status` / `work_tracker_install` -- plus the skills
  (`claiming-work-safely`, `work-tracker-operations`) and agents (`work-executor`,
  `feedback-triage`) that carry the procedure.
- **An early-warning system for its own foundations.** `doctor` runs the contract suite live
  against the installed `bd`; `AGENTS.md` treats it as a gate, not a suggestion.

## What this project is NOT

- **Not an issue tracker.** Beads is. The graph, dependency links, ready-queue, git-native sync
  and `--json` interface are all Beads' work. If you are a single human or a single agent, use
  Beads directly -- this project earns its keep only with *multiple* agents on one queue, or
  sessions that must survive being idle for hours.
- **Not an orchestrator or dispatcher.** Nothing here schedules an agent, allocates a lane, or
  decides what should be worked next beyond "the oldest ready item in this lane." Gas Town is
  explicitly parked (`docs/DESIGN.md`).
- **Not a lock service.** We do not build our own lock layer on top of Beads' claim primitive.
  When upstream ships CAS-conditional update, we adopt it; we do not pre-empt it.
- **Not a multi-machine / federated system.** Leases are `dolt_ignored` and never replicate;
  dead-agent recovery is per-machine. One machine, one shared server, until that hurts.
- **Not a general-purpose project management tool.** No sprints, no burndowns, no estimates.
  The reason a field exists here is that a claim, a custody decision, or a return-path
  notification depends on it.
- **Not a place for speculative capability.** Every verb here exists because someone hit a wall
  without it -- `move` exists because items were filed into the wrong project and there was no
  way to fix it except by hand.

---

## Where this is, right now

Shipped and load-bearing as of this writing:

- **Reads that cannot conflict.** `Beads.list()` and `project_summary` both go over read-only
  SQL rather than `bd list --all`. Every downstream consumer -- the web project page, the reap
  sweep, the gateway, the CLI's `list` -- got the fix at once because they all funnel through
  the one method.
- **Item mobility.** `move_item` / the CLI's `move` / the `work_move` tool relocate one item and
  every row keyed to it (`labels`, `comments`, `events`, `issue_snapshots`, `interactions`,
  `compaction_snapshots`, `dependencies`) between databases, preserving the id verbatim, and
  report honestly -- `MoveReport.dropped_dependency_edges` names every edge that could not
  survive the crossing rather than dropping it quietly.
- **Reading without taking.** `Beads.get_readonly` / `work_list(item_id=...)` / `list --id`
  return an item's full body -- acceptance, description, design, bootstrap metadata -- with no
  claim, no mutation, no custody touched. Understanding an item no longer costs you ownership
  of it.
- **Content editing at the seam.** `Beads.update` amends title/description/acceptance/design and
  verifies the write landed, deliberately holding no lifecycle power (status, holder, claim,
  and resolve each have their own fenced method).

Genuinely in flight and **not yet shipped** at the time of writing -- named here so this
document is not read as claiming them: session subscriptions (a session declaring interest in
items and receiving status back without polling), and the broader mutation/relationship verb
surface (defer/block, dependency creation, integrator-side resolve) that the current verb set
only partially covers.

---

## Decision anchors

Eight tests a proposed change must pass. They are written so that a reviewer can answer each
one with evidence rather than opinion. A change that fails one of these is not necessarily
wrong -- but it is a change to the project's direction, and should be argued as one.

**A1. Nothing above the seam may know `bd` exists.**
*Test:* does the diff add a `bd` field name, CLI flag, or exit-code assumption anywhere outside
`adapter.py`? If yes, it belongs behind the seam or not at all. `AGENTS.md` states the
corollary: when `doctor` reports a violated assumption, the fix scope is exactly one file.

**A2. No agent touches `bd`, `git`, or `dolt` directly -- ever.**
*Test:* can the capability be reached through `work_*` or the CLI? If a user or agent has to
shell out to the underlying tools to accomplish something reasonable, that is a missing verb,
and the missing verb is the bug. (`work_add` exists precisely because seeding a project's first
item otherwise forced a raw `bd create` plus a hand-guessed `bd label add <id> lane:eng`.)

**A3. A reported conflict must be verifiable, not assumed -- and a misleading message is a
defect equal to the failure it describes.**
*Test:* when this fails, does the message name the thing that actually broke? The
serialization-exhaustion bug cost hours because the surfaced error (`beads.role not configured`)
was merely the last line on stderr of the final retry -- it printed on healthy projects too, and
every command exited 0. Truthful diagnosis is a feature with the same standing as the fix.

**A4. Exit code is not proof.**
*Test:* does a write verify itself by reading back? `resolve` and `update` do, and raise if the
change did not land. `Workspace.create` proves the database is writable rather than trusting
`bd init`'s green checkmarks. A new write path without a read-back is incomplete.

**A5. A read that only reads must not be able to conflict with a writer.**
*Test:* does this path have a write set? If it is a listing, a count, a summary, or a render,
it goes over `_dolt_sql`, not through `bd`. Note the direction of the argument: the fix for a
conflicting read is to remove the write set, never to raise the retry budget.

**A6. Silence is the enemy; a partial result must say so in the result.**
*Test:* can this return something that *looks* complete but isn't? `list_bounded` always reports
its cap explicitly. `MoveReport` names dropped edges. `ProjectSummary` sets every field to
`None`/empty (never zero) in any non-`ok` state, so "not healthy" can never be mistaken for
"read as empty." A new surface that can truncate, skip, or drop must carry that fact in its own
return value.

**A7. Custody is a liveness signal, not a timer.**
*Test:* does this make idle time cost an agent its claim? It must not. Only an *unrenewed*
signal releases an item. `awaiting_human` suppresses a notification and buys nothing else --
and `contract.py`'s `custody.idle_not_exempt` check exists to keep that honest.

**A8. New capability earns its place by closing a gap someone actually hit.**
*Test:* name the incident. Not the symmetry ("we have `rename`, so we should have `move`"), not
the hypothetical. `move` earned its place because items were filed into the wrong project and
the only remedy was manual SQL. If the incident cannot be named, prototype it outside the seam
first.

---

## The one-line version

**Make the dangerous thing impossible to write, make the failure impossible to misread, and
keep the center small enough that a Beads upgrade has exactly one file to argue with.**
