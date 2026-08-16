# Convention: Authoring Work Items a Cold Session Can Execute

**Status:** proposed, validated against 6 real items in this project's own queue (not on reasoning alone)
**Audience:** anyone filing a `work_item_pipeline` item (or any project's), and any triage/enrichment
agent that touches one before a coding session claims it
**Relates to:** `docs/DESIGN.md` (report/issue split this convention borrows from); `work_item_pipeline-h3a`
(the item this document answers); depends on, but does not require, `work_item_pipeline-cta`
(the live item -> goal-file -> lane trip, still open at time of writing -- see "What remains unproven")

---

## The one idea

**A work item is the only channel to a session that will execute it with zero access to the
conversation that created it.** Nothing today names what that channel must carry, so the
requirement is never checked -- it is discovered, expensively, the first time a cold session
guesses wrong. This document names it.

The central tension is real and not solved by picking a side: capture must be cheap and must not
drag in irrelevant context for a brand-new, unrelated idea; a related item must not lose the value
the originating session already paid to discover. The resolution below is **a floor and a ceiling
on one schema, not a mode switch decided at filing time** -- because the six real items already in
this project's queue prove that richness is written straight into the existing three fields
(`title` / `description` / `acceptance`) with zero schema change, whenever the filer actually has
context worth preserving and bothers to write it down.

---

## Why not the two-mode (COLD/WARM) idea

A COLD/WARM mode switch, decided by the filer at capture time, was sketched and rejected during
this item's own filing (recorded in `work_item_pipeline-h3a`'s PARKED section). Rejected on two
grounds, now confirmed against real evidence rather than asserted:

1. **The filer often cannot correctly classify "related" vs "unrelated" at filing time** -- that
   judgment belongs to whoever later reads the item with fresh eyes, not to someone mid-flow trying
   to get an idea out of their head before it's lost. A mode flag decided under exactly the
   condition it's meant to resist (haste) will default to COLD out of habit even when WARM was
   warranted, silently discarding the very value the mode was invented to protect.
2. **No mode flag was needed to produce the rich items that actually exist.** `work_item_pipeline-h3a`,
   `-cta`, `-gt9`, and `-gp9` are all rich, all written into the same `description` field every thin
   item uses, and none of them required a schema change or a flag. The richness is a *writing
   convention applied to an existing field*, not a structural fork of the schema.

So: one schema, always. The difference between a thin item and a rich one is entirely in how much
of the optional template below got filled in -- never in which fields exist.

---

## The floor -- minimum viable capture (never blocked on this)

`work_add` / `work_file`'s actual write surface is exactly three fields: `title`, `description`,
`acceptance` (confirmed against the tool interface; `work_file` is identical minus `project`, since
it links `discovered-from` the item already held). The floor is deliberately thin enough that
capturing a raw idea costs nothing more than typing it:

| Field | Floor requirement |
|---|---|
| `title` | One line, specific enough to tell items apart in a list. Not "bug" or "improvement". |
| `description` | At minimum, what's actually happening or wanted, in the filer's own words. May be exactly what a person would say out loud. |
| `acceptance` | May be thin or even absent at filing time. A cheap capture that will sit untouched for a while is not required to have a fully-formed spec before it can exist. |

**Nothing above blocks capture.** A one-line idea for a brand-new project is a complete, valid work
item. The floor exists so that "the convention requires too much" is never a reason not to file
something.

---

## The ceiling -- the structured template, proven by real items

When the filer *does* have context worth preserving -- because the item came out of a working
session, not a hallway idea -- the `description` field carries an optional, additive template.
Every block below is drawn from real, working items in this queue, not invented for this document:

| Block | Carries | Seen working in |
|---|---|---|
| **CONTEXT** | Why this matters, who it affects, what's actually happening | `h3a`, `cta`, `gt9`, `gp9` |
| **KNOWN** | Facts already established -- "do not re-derive." Explicitly a speed aid, not a substitute for a real exit condition | `h3a`, `cta`, `gt9`, `gp9` |
| **ANCHORS** | Exact paths to the code/docs/skills a cold session will need -- saves a full-repo exploration pass | `h3a`, `cta` |
| **SCOPE-OUTS** | What is explicitly *not* required -- the single highest-leverage block for preventing runaway scope | all four |
| **PARKED** *(optional)* | Ideas considered and explicitly rejected, so a cold session doesn't re-invent and re-reject them from scratch | `h3a` |
| **DEPENDS ON** *(optional, informal)* | Sibling items whose findings this one needs, since no tool-level dependency link is being used here | `h3a` |
| **PROVENANCE** | Session ID, date, originating repo | `h3a`, `cta`, `gt9`, `gp9` |

This is not a new field and not a new mode -- it's a checklist for what to put in the same
`description` field, applied exactly as much as the filer has context to spend.

### Who pays for enrichment, and when

The report/issue split in `docs/DESIGN.md` already answers this shape of question for user
feedback: *"Do not interrogate the user. They will not answer, and their answers are worse than
your telemetry."* The same principle generalizes here. **The filer is never required to enrich.**
Whoever has the context pays for the template, and that is usually one of:

- **The filer, in the moment**, if the item came directly out of a working session and writing the
  CONTEXT/KNOWN/ANCHORS/SCOPE-OUTS down costs nothing extra -- the session already has everything
  in its own transcript. This is exactly how `h3a`, `cta`, `gt9`, and `gp9` were produced: authored
  as deliberate rich specimens by the session that discovered the need, at zero marginal cost to
  that session.
- **A later triage pass**, deliberately, on a backlog of thin items -- the same role `docs/DESIGN.md`
  assigns to the triage agent that turns a sloppy report into "a real spec." Triage is who should
  enrich `i7f` and `m9v` (see worked examples below) before either is handed to a cold session,
  *not* the person who filed them in five seconds while doing something else.

Either way, enrichment is a distinct, optional, later step -- never a precondition for capture.

---

## The acceptance-vs-goalify vocabulary mismatch

**Position: translate at conversion time. Do not reconcile the two vocabularies, and the mismatch
is not a nothing -- it is real and it is not "neither is needed."**

The work-tracker vocabulary (`acceptance` / `description` / `design`) and the goalify vocabulary
(one-sentence checkable outcome, disjunctive exit, per-item negative terminal, `SCOPE-OUTS`,
optional `KNOWN`) were built for different consumers and share zero terms -- verified by grep
across `goal-batch`, `goalify`, and `claiming-work-safely` (`"acceptance criteria"` and
`"self-contained"` both appear zero times). That is not an oversight to fix by editing either
system: a work item is read by humans, triage agents, and a GitHub Issues export, none of which
need a disjunctive exit clause. A goal file is read by exactly one consumer: an unattended
convergence loop that needs a mechanically checkable stop condition. Forcing the general-purpose
schema to natively speak the one specialized consumer's dialect (a fourth `work_add` field, say)
would warp a shared resource around a single downstream use.

**The mismatch is real, and it matters:** `h3a`'s own KNOWN section names the actual failure mode --
*"a work item converted carelessly into a goal file yields a `/goal` loop that never terminates,
silently burning a whole lane. The failure is silent, not loud."* That is exactly the class of
hazard this whole convention exists to prevent for a different channel (custody, claiming); here it
recurs for conversion.

**Evidence the translation is already happening, successfully, without being written down anywhere
until now:** `gt9` and `gp9`'s `acceptance` fields are not Given/When/Then. They are already
goalify-shaped: *"Complete when EITHER (a) ... OR (b) ..."*, with named, independent
PASS/FAIL/BLOCKED/PENDING-HUMAN terminals per sub-claim. Both items resolved cleanly. Nobody
designed this as a convention -- the authoring session simply reached for goalify's shape because it
was the more precise way to say "when is this actually done." **The fix is not new tooling. It is
writing down, deliberately, a pattern that is already working by unrecorded habit**, so it happens
consistently instead of only when the filer happens to already know goalify.

### The crosswalk

| goalify requires | work-tracker equivalent | Notes |
|---|---|---|
| One-sentence checkable outcome | First line of `acceptance` | State the end state, not an activity |
| Disjunctive exit | `acceptance`, explicit "Complete when EITHER (a) ... OR (b) ..." | Given/When/Then alone does not supply this -- see worked example below |
| Per-item negative terminal | `acceptance`, one PASS/FAIL-\<reason\>/BLOCKED-\<reason\>/PENDING-HUMAN per named sub-claim | Required the moment `acceptance` lists more than one thing |
| `SCOPE-OUTS` | `description`, `SCOPE-OUTS` block | Same word, same meaning -- copy directly |
| `KNOWN` (optional) | `description`, `KNOWN` block | Same word, same meaning -- copy directly |
| *(no equivalent)* | `description`, `PROVENANCE` block | Kept; goalify has nothing to say about session origin, and it costs nothing to carry forward |

**Practical instruction for authors:** if an item might become a goal file, write `acceptance` in
goalify's shape from the start -- disjunctive exit and named terminals -- rather than plain
Given/When/Then. It costs no more to write and removes an entire class of silent non-termination at
conversion time.

---

## The description/design asymmetry

**Finding:** `work_claim` / `work_list` return `design` as a readable field alongside `description`
and `acceptance`. Neither `work_add` nor `work_file` -- the *only* write paths -- accept a `design`
parameter. The read side promises a field the write side cannot populate.

`docs/DESIGN.md`'s own triage guidance (`--description` / `--design` / `--acceptance` as three
separate `bd create` flags) shows that Beads itself supports a design field at creation. That makes
this most likely an omission in the amplifier-work-tracker tool wrapper, not a deliberate
narrowing and not a Beads limitation -- worth naming precisely so nobody "fixes" it by guessing
wrong about which layer is at fault.

**Recommendation, staying within the three fields per this item's scope (modifying `work_add`'s
schema is out of scope here -- this is a finding, not a mandate):** fold design content -- a
hypothesis, a suspected component, a rough sketch -- into a labeled subsection of `description`
(e.g. a `DESIGN:` line) until the wrapper gap is addressed as its own item. Do not attempt to
populate `design` by any path that bypasses the `bd` seam -- that would violate the bundle's own
hard rule to reach a field the tool surface doesn't expose. Filing the wrapper gap as its own
engineering item is the correct next step, distinct from this research item.

---

## Worked examples (read-only, real items in this queue)

Pulled via `work_list(project="work_item_pipeline", item_id=...)` -- no items claimed or mutated to
produce this section, per this lane's scope.

### Good: rich handoff that worked

- **`work_item_pipeline-gt9`** and **`work_item_pipeline-gp9`** -- both resolved cleanly by a cold
  session with zero access to the originating conversation. Both carry CONTEXT / KNOWN / ANCHORS /
  SCOPE-OUTS / PROVENANCE, and both already write `acceptance` in goalify's disjunctive-exit,
  named-terminal shape rather than Given/When/Then. `gp9` additionally shows the "file what you
  find" pattern in its own resolution text -- the executing session filed and closed sibling
  findings inline, exactly as `docs/DESIGN.md` section 4.3 describes.
- **`work_item_pipeline-h3a`** (this item) is itself a specimen: a genuinely cold session (this one)
  executed it correctly on the first attempt with no clarifying question needed, using only CONTEXT
  / KNOWN / PARKED / ANCHORS / DEPENDS ON / SCOPE-OUTS / PROVENANCE. That is direct, live
  proof-by-execution that the template above is sufficient -- not merely plausible.

### Thin: cheap capture, not yet cold-safe

- **`work_item_pipeline-i7f`** ("status breakdown for project stats") and
  **`work_item_pipeline-m9v`** ("project rename support") are both plain Given/When/Then, with no
  KNOWN/ANCHORS/SCOPE-OUTS and no disjunctive exit. Neither is wrong as filed -- both are exactly
  the cheap, low-friction capture the floor is designed to allow. Neither should be handed to a
  goal-batch lane as-is without a triage pass; see the conversion below for why.

---

## A live conversion: `i7f`, careless vs. translated

This is the "carried through to a goal file" check this item's acceptance requires. Both versions
below are inert worked examples embedded in this document -- neither was written to
`.amplifier/goals/` or launched as a lane. Running a real item through a real lane end-to-end is
`work_item_pipeline-cta`'s job, and it is still open at time of writing (see next section).

**Careless conversion** -- `i7f`'s raw `acceptance` text, used verbatim as a goal condition:

```
Given a project with items in every status (open, held, blocked, deferred, resolved)
When `work_status` (or `amplifier-work-tracker instances`) is called
Then the response includes per-project counts for all five statuses, not just total/ready/held

Given a single project name
When a caller requests detailed stats for that project (new op or flag — not full item listing)
Then the response returns the full status-count breakdown for that project in one call, without
paginating through individual item records
```

Self-applying goalify's Phase 3 lint by hand to this text (no linter built or run -- this is a
manual read against the documented rules, within this item's research scope):

| Rule | Result |
|---|---|
| L1-L5 (hard blockers) | None literally fire -- no ordering claim, no "all N" quantifier, no wall-clock requirement, no human-in-the-loop clause, no unbounded enumeration |
| L6 (missing disjunctive exit) | **Fires.** Nothing states "or conclusively demonstrate this cannot be done" |
| W1 (multiple items, not all with a negative terminal) | **Fires.** Two distinct features (cheap summary; detailed per-project view) are bundled with no independent PASS/FAIL/BLOCKED per feature -- the item's own description even suggests "split into separate items during implementation if that's cleaner," which is scope ambiguity left for the executing session to resolve mid-flight |

Neither is a hard L1-L5 blocker, so this would not be rejected outright -- but W1 plus the "new op
or flag" ambiguity is exactly the shape `h3a`'s KNOWN section warns about: a loop that spends its
whole budget debating an implementation choice nobody pinned down, rather than converging. This
matches `cta`'s own stated, still-untested prediction almost exactly -- consistent with, not yet
independently proven by, a live trial.

**Translated conversion**, applying the crosswalk above (splits the bundled features per the
item's own suggestion, adds the disjunctive exit and per-item terminals, and moves the informal
"KNOWN" already implicit in the description into its own block):

```
One-sentence outcome: work_status reports a full open/held/blocked/deferred/resolved breakdown,
both across all projects and for one project in detail.

KNOWN:
- work_status / `instances` today report only total/ready/held per project.
- Getting the missing split today costs N `work_list` calls per project (one per status,
  `limit=1`, reading only `total_count`) -- a workaround, not a fix.

Complete when EACH of the following resolves independently to
PASS / FAIL-<named reason> / BLOCKED-<named reason> / PENDING-HUMAN:

(a) All-projects summary: `work_status` / `instances` includes per-project counts for all five
    statuses (open, held, blocked, deferred, resolved), not just total/ready/held.
(b) Per-project detail: a single call returns the full status-count breakdown for one named
    project, without paginating through individual item records.

A stage ending FAIL or BLOCKED is a residual, not a failure of the whole item.

SCOPE-OUTS:
- Whether (b) is a new operation or a flag on an existing one is an implementation decision for
  the executing session, not a precondition -- it does not block either stage's terminal state.
- No requirement to unify the two call shapes if two feels more natural than one.
```

The translated version resolves L6 and W1 (each stage now independently terminal), and pins the
one ambiguity (op-vs-flag) as an explicit non-blocking implementation choice via SCOPE-OUTS rather
than leaving it live inside the acceptance text for the loop to stall on.

---

## Where this convention should live, and why

**This document lives in `docs/`**, alongside `docs/DESIGN.md` -- it is a design-rationale record
(why the tension resolves this way, what evidence backs it), read by a human or a curious agent
deciding *whether* to trust the convention, not by every session on every claim.

**The operational half -- the crosswalk table and the floor/ceiling checklist, not the rationale --
belongs in `skills/`**, alongside `skills/claiming-work-safely/SKILL.md` and
`skills/work-tracker-operations/SKILL.md`, once this proposal is accepted. Skills are what actually
loads into an agent's context by convention in this ecosystem; a design doc in `docs/` is not
automatically read by a filing session the way a skill is. This document deliberately does **not**
create that skill -- doing so is implementation, out of this item's scope -- but names the correct
target so acceptance of this proposal has an unambiguous next step.

---

## What remains unproven

This convention is validated against real items **retrospectively** -- by reading six items already
in this queue and showing the pattern already works (`gt9`, `gp9`) or already risks stalling
(`i7f`, `m9v` as filed). It has **not** been validated by a live item -> goal-file -> isolated-lane
trip reaching an actual terminal outcome, because `work_item_pipeline-cta` -- the sibling item whose
entire job is that live trip -- is still open at time of writing. Everything in the "live
conversion" section above is a manual, honest simulation of that trip, not a substitute for it.
Treat this document's crosswalk as strongly evidenced, not as proven by execution, until `cta`
resolves.

---

## One-page checklist (for a filer in a hurry)

1. Write `title` + `description` in your own words. That alone is a complete, valid item.
2. Have five extra minutes and real context from a working session? Add CONTEXT / KNOWN / ANCHORS
   / SCOPE-OUTS to `description`. Skip anything you don't have -- partial is fine.
3. Writing `acceptance`? If there's any chance this becomes a goal file, use "Complete when EITHER
   (a)... OR (b)..." with named PASS/FAIL-\<reason\>/BLOCKED-\<reason\>/PENDING-HUMAN terminals
   instead of bare Given/When/Then.
4. Don't have design content clearly separated? Put it in `description` under a `DESIGN:` line --
   `work_add`/`work_file` have no `design` parameter today.
5. Nobody is required to do any of this at filing time. A later triage pass may add it instead.
