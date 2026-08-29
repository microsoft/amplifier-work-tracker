# Design: Authoring Work Items a Cold Session Can Actually Finish

**Status:** PROPOSED -- design for owner review. **Not a shipped decision.** The central
recommendation changes an existing tool's default behaviour; see "Open questions / needs owner
sign-off."
**Audience:** the owner deciding whether to accept this; anyone filing an item; any triage pass.
**Supersedes in part:** [`docs/work-item-authoring-convention.md`](../work-item-authoring-convention.md)
-- that document's floor/ceiling template and goalify crosswalk still stand and are not
re-litigated here. This document revises its *conclusion*, and adds the mechanism it was
missing (see "What changed since").
**Relates to:** [`docs/VISION.md`](../VISION.md) (tension 4; anchors A6, A8),
[`docs/DESIGN.md`](../DESIGN.md) (the report/issue split this leans on),
[`docs/design/item-type-taxonomy.md`](item-type-taxonomy.md) (what a *given type* must carry).

---

## What changed since the prior convention

The earlier convention document argued, correctly, that richness is a *writing convention
applied to existing fields* rather than a schema fork. It then landed on: enrichment is optional,
and "whoever has the context pays." Two things have changed that make that conclusion worth
revisiting.

**1. The "ANCHORS" block is no longer prose. It is a parsed contract.**
`parse_bootstrap_metadata` (`adapter.py`) now extracts `repos:` and `context:` lists from the
first fenced ` ```yaml ` block in an item's description, using a stdlib-only parser that handles
both block style (`repos:` then `- item` lines) and inline flow style (`repos: [a, b]`).
`Item.repos` / `Item.context` are populated at the seam by `Item.from_beads`, and
`Item.summary(full=True)` returns them. An item with no such block yields two empty lists and
never raises -- full backward compatibility. The prior convention predates this entirely and
describes ANCHORS as free text a human reads. **It is now the one part of the item the *system*
reads**, and that changes what "cold-startable" means: a cold session can be handed its repos and
context files mechanically, not by hoping a model notices a paragraph.

**2. Reading an item no longer costs you ownership of it.**
`Beads.get_readonly` / `work_list(item_id=...)` / `list --id` return the full body -- acceptance,
description, design, bootstrap metadata -- with no claim, no mutation, no custody touched
(proven by the `read.no_mutation` contract assumption). Previously `work_claim` was the only path
that returned an item's body. The practical effect: **a session can now evaluate whether an item
is cold-startable *before* taking it** -- which makes a readiness standard enforceable in a way it
was not when reading meant claiming.

One thing has **not** changed, and the earlier finding still holds exactly as written:
`Beads.create` accepts `design`, and `Beads.update` can now amend it, but neither `work_add` nor
`work_file` exposes a `design` parameter -- both take `(title, *, description, acceptance)` only.
The read side still promises a field the agent-facing write side cannot populate.

---

## What a work item MUST carry to be cold-startable

"Cold" means: an isolated session, no access to the conversation that created the item, no
ability to ask a follow-up question and get an answer in-flight. The item is the *entire*
channel. Six things are load-bearing; everything else is a nicety.

**1. A stop condition, not a task description.**
One sentence naming a checkable end state. "Improve the summary path" is an activity; "`work_stats`
returns a full per-status breakdown for one project in a single call" is a state you can stand in
front of and test.

**2. A negative terminal for every named sub-claim.**
`FAIL-<reason>` / `BLOCKED-<reason>` / `PENDING-HUMAN`, per claim. This is the one requirement
that is *not* optional, and the argument for it is in the next section.

**3. Scope-outs -- the explicit not-required set.**
The highest-leverage block by a wide margin, because scope creep in a cold session is not
observed by anyone until the budget is gone. Naming what is *not* required is cheaper than
naming everything that is.

**4. Machine-readable anchors: the fenced ` ```yaml ` block with `repos:` and `context:`.**
Not "the code lives around `adapter.py` somewhere." The actual lists, in the actual block, in
the shape `parse_bootstrap_metadata` parses. This is the only part of the item that is read by
code rather than by a model, and it is the difference between a session that starts working and
a session that starts exploring.

**5. Known facts -- "do not re-derive."**
Explicitly a speed aid, never a substitute for a real exit condition. A cold session that has to
rediscover what the filing session already knew spends its budget on archaeology.

**6. Provenance -- session id, date, originating repo.**
Costs one line. It is the only way a human can later find the conversation that produced the
item, and by construction the cold session cannot supply it.

An item missing 1, 2, or 4 is not a thin item. It is an item a cold session cannot finish
honestly, and handing it to one wastes a whole lane.

---

## Position: acceptance criteria must carry a negative terminal. Given/When/Then does not.

**Recommendation: disjunctive-exit with named terminals is the default form for any claimable
item -- not "if there's a chance this becomes a goal file."**

The prior convention recommended this conditionally, on goalify-compatibility grounds. That
undersells it, and the conditional is why it is applied inconsistently. The real argument has
nothing to do with goalify:

**Given/When/Then can only describe success.** There is no clause in it for "and if this turns
out to be impossible, here is what to do." An autonomous session that hits an impossibility --
the dependency does not exist, the premise is false, the fix requires a decision nobody has made
-- is then facing a spec with exactly one terminal state, and only three moves available:
declare success falsely, keep grinding until the budget is gone, or stop and report a failure the
spec never authorised. The first is the worst outcome this whole system is built to prevent, and
it is the one an eager agent reaches for.

The repo's own agent baseline states the principle directly -- *"a fabricated attestation is
worse than an honest gap"* -- and the honest gap needs somewhere to be recorded. `PENDING-HUMAN`
is that place. **An acceptance criterion with no negative terminal is a spec that makes honest
stopping unrepresentable.**

Two supporting observations, both already true in this repo:

- The practice is already working, unrecorded. Items authored as deliberate rich specimens
  reached for "Complete when EITHER (a)... OR (b)..." with named per-claim terminals, and
  resolved cleanly. Nobody designed that; the authoring session simply reached for the more
  precise way to say when something is done.
- It matches how this codebase already models partial outcomes elsewhere. `MoveReport` names the
  edges it had to drop rather than dropping them quietly; `ProjectSummary` distinguishes
  "not healthy" from "read as empty" by using `None` rather than zero; `list_bounded` always
  reports its cap. **VISION anchor A6** -- a partial result must say so in the result -- is a
  code-level rule here. Acceptance criteria are the one place it is not yet applied, and an item
  is just a contract with a session instead of with a caller.

**The cost, stated honestly:** this form is wordier, and for a genuinely trivial item ("fix the
typo in the README") the terminals are ceremony. That is real. It is also bounded -- the fallback
is one extra clause, not a template -- and it is the wrong trade to optimise the trivial case at
the cost of making the hard case unrepresentable.

---

## Position: the cheap-capture / rich-handoff tension is resolved by moving the cost, not lowering the bar

This is the disagreement with the prior convention, and it should be argued rather than glossed.

**The prior position:** one schema, a thin floor that never blocks capture, an optional rich
ceiling, and "whoever has the context pays for enrichment" -- filer in the moment, or a later
triage pass.

**Why that is not enough:** it makes enrichment a politeness that no mechanism is accountable
for, and *its own evidence shows the failure*. That document identified two real items as
"cheap capture, not yet cold-safe," correctly noted neither should go to a lane as-is, and
assigned the enrichment to "a later triage pass." There is no triage pass. Nothing schedules one,
nothing blocks on one, and nothing marks an item as not-yet-ready. So the thin items sat, fully
claimable, indistinguishable in the ready queue from the rich ones -- which is exactly the
outcome the analysis predicted and the convention had no mechanism to prevent.

**The structural cause, and it is specific and fixable:** *the claimability gate is already being
tripped at capture time.* `Beads.claim_next(lane=LANE_WORK)` only returns items labelled
`lane:eng` -- the lane label **is** the readiness gate, and it already exists. But `work_add`
applies `lane:eng` itself, immediately, at file time (`modules/.../__init__.py:593`, mirrored by
`cli.py:443`). Both do so for a good reason -- the docstring says it plainly, callers should
never need to know the label vocabulary -- but the side effect is that **every cheaply-captured
one-liner becomes instantly claimable by an autonomous executor.** There is no state in which an
item exists but is not yet ready, even though the system already has the vocabulary for exactly
that state.

**The proposal: file thin into intake; promote to the work lane deliberately.**

This is not a new mechanism. `docs/DESIGN.md` already defines this exact transform -- a report
enters at `lane:intake`, triage performs the sloppy-to-considered transform, and *"the issue it
writes must be a real spec"* with acceptance criteria. The gap is that the transform is defined
only for the *user feedback* path (Gateway -> `lane:intake` -> triage -> `lane:eng`) and simply
skipped for the agent/operator path, which writes straight into `lane:eng`. The same discipline
should apply to both, for the same reason.

Concretely:

| | Today | Proposed |
|---|---|---|
| `work_add` / CLI `add` default lane | `lane:eng` (instantly claimable) | `lane:intake` (captured, not yet claimable) |
| Cost of filing a raw idea | zero | **still zero** -- the floor is unchanged |
| Promotion to claimable | n/a | explicit: an opt-in at file time, or a later deliberate pass |
| Who can promote | n/a | anyone -- but it is an act, with the cold-start checklist attached to it |

**Capture stays free. What moves is the moment the item claims to be executable.** The filer is
never blocked and never interrogated -- that principle from `docs/DESIGN.md` ("do not interrogate
the user") is preserved exactly. The only thing that changes is that an item does not get to
*assert* it is ready merely by existing.

**The cost, stated honestly -- and it is real.** `work_add`'s stated reason for existing is
seeding the first item(s) in a brand-new project so nobody has to shell out to raw `bd`. Under
this proposal that first item lands unclaimable, which is a worse experience for the exact case
the tool was built for, and it is a behaviour change to a live queue. The mitigation is a
`ready=true` / `--ready` opt-in for the case where the filer *is* authoring a cold-startable item
and knows it -- so the friction lands only where the item is genuinely thin. That mitigation is
also the weak point of the proposal: an opt-in flag decided in haste will be set out of habit,
which is the same critique the prior convention correctly levelled at a COLD/WARM mode switch.
The difference is one of default direction -- a habitually-set `ready` flag is no worse than
today's unconditional `lane:eng`, whereas a habitually-unset richness mode was strictly worse
than nothing. It is still a genuine weakness, and it is why this is open question 1 rather than a
recommendation to implement.

---

## The bootstrap block, and where it should live

The parsed ` ```yaml ` block is the strongest single lever for cold-startability, because it is
the only machine-read part of an item. Two things follow.

**Write it in the shape the parser actually accepts.** `_parse_yaml_list_key` only honours an
**unindented** occurrence of the key, so a nested or indented `repos:` is silently ignored -- and
silently is the operative word: there is no error, the lists just come back empty. Only the
**first** fenced yaml block is consulted. This is a small, fixed, shallow shape by design (a flat
list of repo slugs and context paths, never arbitrary YAML), and it should be documented as such
wherever filers are told to write it.

**But note the fragility, honestly:** this is structured data parsed out of prose that a human or
a model is free to reformat. Re-wrapping a description, moving the block below another fenced
block, or indenting it under a heading all break it without any signal. The alternative --
Beads' native `metadata` JSON column, which round-trips (proven by the `metadata.roundtrip`
contract assumption) and survives a `move_item` as a first-class column -- is structurally
sturdier. The counter-argument is equally real: prose is what a filer actually writes, and a
tool surface that demands a JSON blob will get an empty one. This is a genuine unresolved
trade-off, recorded as open question 3 rather than decided here.

---

## What this proposal does NOT change

- **No new field, no new schema, no mode flag.** The prior convention's core finding stands:
  richness is a writing convention over `title` / `description` / `acceptance`.
- **No validation that rejects a write.** Nothing here proposes refusing to file an item. The
  intake lane is the escape valve precisely so that enforcement never becomes a reason not to
  capture something.
- **No change to the floor.** A one-line idea remains a complete, valid item.
- **No new agent or scheduled job.** Promotion is an act a human or an already-running session
  performs; this does not propose a triage daemon.

---

## OPEN QUESTIONS / needs owner sign-off

This document is **PENDING-HUMAN**. Question 1 is blocking -- it is the proposal's whole load.

1. **[BLOCKING] Should `work_add` / CLI `add` default to `lane:intake` instead of `lane:eng`?**
   This is a behaviour change to a live queue and to the tool's own stated purpose (seeding a new
   project's first item). Accepting it means new items are not instantly claimable; rejecting it
   means the readiness gate stays unenforceable and this document is advice rather than
   mechanism. If accepted: does the `ready=true` opt-in ship with it, and does the change apply
   retroactively to the items already sitting in `lane:eng`?
2. **[BLOCKING] Is the negative-terminal form mandatory for `lane:eng` items, or strongly
   recommended?** Mandatory needs an enforcement point (promotion-time check) and a decision
   about what happens to existing items that lack it. Recommended is what the prior convention
   already said, and it demonstrably did not take.
3. **Should `repos:` / `context:` move from parsed prose to the native `metadata` column?**
   Sturdier (structured, move-safe, round-trip-proven) versus more likely to actually be written
   (prose is what filers write). A middle path -- parse prose, but *also* accept `metadata`, with
   `metadata` winning -- is possible and is more code. No recommendation offered; this needs the
   owner's read on who is really authoring these items.
4. **`design` remains unreachable from the agent write surface.** `Beads.create` and
   `Beads.update` both accept it; `work_add` and `work_file` do not. Fold design content into a
   `DESIGN:` line in `description` (the prior convention's workaround, still in force), or add
   the parameter? The latter is a small change and closes a real read/write asymmetry.
5. **Who owns promotion from intake to the work lane?** A human, a triage pass (an agent already
   exists for the *reports* path: `agents/feedback-triage.md`), or any session that reads an item
   and judges it ready? Anyone-can-promote is simplest and matches this project's low-ceremony
   posture, but it means the standard is enforced only by whoever bothers.
6. **Does this interact with the type taxonomy?** [`item-type-taxonomy.md`](item-type-taxonomy.md)
   proposes that `planning` items should not be claimable by autonomous executors, and notes the
   existing lane mechanism as the likely enforcement point. That is the same mechanism this
   document proposes to use for readiness. If both land, confirm they compose cleanly rather than
   overloading one label with two meanings.
7. **Where does the operational half live once accepted?** Same answer as the prior convention's,
   and it is still the right one: the rationale stays in `docs/design/`; the checklist belongs in
   `skills/`, because a skill is what actually loads into a filing session's context and a design
   doc is not. Confirm before implementing.
