# Design: A Work-Item Type Taxonomy

**Status:** PROPOSED -- design for owner review. **Not a shipped decision.** See
"Open questions / needs owner sign-off" at the end; several of them are blocking.
**Audience:** the owner deciding whether to accept this, and whoever implements it if so.
**Relates to:** [`docs/VISION.md`](../VISION.md) (anchors A1, A2, A5, A8 all bear on this),
[`docs/DESIGN.md`](../DESIGN.md) (the report/issue split and the lane-label convention),
[`docs/design/cold-startable-authoring.md`](cold-startable-authoring.md) (what a *given type*
of item must carry).

---

## The problem, stated precisely

Every item in this system is handled the same way, and they are not the same kind of thing.
A defect needs a reproduction before a fix. A design item's terminal state is a document and a
human's sign-off, never merged code. An execution item is mechanical and safe to hand to an
isolated cold session. A planning item probably should not be claimable by an autonomous
executor at all. Today none of that is expressible, so the distinction lives only in the prose
of each item's title -- which means it is invisible to every filter, every queue, every
dashboard, and every agent deciding whether it is the right thing to claim.

## The finding that determines the answer

**Beads already has a native type column, we are already writing to it, and we read it back
almost nowhere.** This is not a greenfield decision -- it is a decision about whether to fix
what exists or to build a second thing beside it.

Verified in this repo:

| Fact | Evidence |
|---|---|
| Beads has a native `issue_type` column | `adapter.py` `_FIELD_MAP`: `"issue_type": "kind"` -- it is a first-class column on `issues`, projected by `_LIST_ITEM_SCALAR_COLUMNS` and read straight out of SQL in `_summary_items_via_sql` (`kind=rec["issue_type"] or "task"`) |
| We already set it on every write | `Beads.create` passes `-t <kind>`; default `kind="task"` |
| ...but always hardcoded, never chosen by the caller | `work_add` -> `kind="task"` (`modules/.../__init__.py:593`); `work_file` -> `kind="bug"` (`:563`); CLI `add` -> `kind="task"` (`cli.py:442`); Gateway report -> `kind="chore"` (`gateway.py:353`) |
| It travels for free across a project move | `move_item` copies the `issues` row itself; a native column crosses databases with no extra work |
| It is read back at exactly **one** site in the entire codebase | `webapp.py:2557` -- a `("Kind", ...)` fact row on the item detail page. Nothing else reads `.kind`. |
| It is absent from the shared read shape | `Item.summary()` returns id/title/status/holder/resolution, and (with `full=True`) acceptance/description/design/repos/context/timestamps/created_by. **`kind` is in neither.** So no `work_*` tool and no CLI JSON output ever shows an item's type. |

The situation, in one sentence: **a native, single-valued, SQL-filterable, move-safe column is
already populated on every item with a value nobody chose, and is then discarded on read.**

---

## Recommendation: ride the native `issue_type`. Not labels. Not parsed metadata.

**This is the "no separate/parallel tracking" answer, and it is the right one for reasons that
are specific to this codebase, not generic.**

### Why not a `type:*` label namespace

Labels are not free real estate here -- they are **load-bearing for routing**. `lane:eng` and
`lane:intake` are the only members of the label vocabulary today, and `lane:eng` is what makes
an item claimable at all: `Beads.claim_next(lane=LANE_WORK)` filters on it, and
`project_summary` computes `ready` and `intake` from it (`adapter.py:3704-3706`). Adding a
second, semantically unrelated dimension into that namespace costs real properties:

- **No single-valued guarantee.** The `labels` table is a many-to-one join keyed by `issue_id`.
  Nothing prevents an item carrying `type:bug` *and* `type:feature`. Every consumer would then
  need a tie-break rule, and every consumer would need the *same* tie-break rule. `issue_type`
  is one column: single-valued by construction, no rule needed.
- **No default.** An unlabelled item has no type, so every reader needs an "absent" branch. A
  column has a value on every row.
- **A join per filter.** Lane filtering already costs a subquery against `labels` in
  `Beads.list`'s WHERE construction. Type filtering would cost a second one, on a dimension
  where a plain column comparison would do.
- **Conflation risk in exactly the place it hurts.** A future reader scanning `tags` cannot tell
  a routing decision from a classification without knowing the prefix convention -- and the
  convention would be enforced nowhere.

### Why not parsed metadata (a `TYPE:` line in the description, or a `metadata` JSON key)

There is a real precedent for parsing structure out of an item's prose -- `parse_bootstrap_metadata`
pulls `repos:`/`context:` out of a fenced ` ```yaml ` block in the description, and it works.
But the precedent argues *against* using it here, because of what makes it work there:
bootstrap metadata is **optional, additive, absent on the overwhelming majority of items, and
safely defaults to two empty lists**. A taxonomy is none of those. It is meant to be present on
every item and to be *filtered on*.

And filtering is where parsed-from-prose fails concretely, not theoretically. `Beads.list`
builds a SQL `WHERE` clause and hands it to `_list_rows_via_sql`; a type that lives in a column
becomes one more predicate in that clause, filtered server-side. A type parsed out of markdown
cannot be filtered in SQL at all -- it requires fetching every row and parsing each description
in Python. That is precisely the full-scan cost the read-only-SQL work (PRs #48/#49) just
eliminated, reintroduced through the back door. It also fails **VISION anchor A5** in spirit:
the read stops being cheap the moment the project is large, which is exactly the condition the
whole conflict fix was about.

The `metadata` JSON column is a closer call -- it is native, it round-trips (proven by the
`metadata.roundtrip` contract assumption), and it survives a move. But it is a JSON blob:
filtering means `JSON_EXTRACT` in the WHERE clause, there is no vocabulary constraint, and it
duplicates a column that already exists and already carries a value. Choosing it over
`issue_type` would mean deliberately leaving a native, populated, indexed-by-nature column
holding a *wrong* value forever. That is the parallel-tracking failure mode this design is
explicitly told to avoid.

### The decisive argument

Anything other than `issue_type` leaves the existing column populated with a value that is now
*known to be meaningless*, sitting one join away from the real answer, rendered on the item
detail page as `Kind`. Two sources of type, disagreeing, one of them visible in the UI. The
cheapest correct move is not to add a dimension -- it is to **fix the vocabulary of the one that
already exists, let callers choose it, and surface it on read.**

---

## The taxonomy

Five values, chosen to answer one question: *what does "done" look like, and who is allowed to
decide it?* That is the only distinction worth encoding, because it is the one that changes how
an item is handled.

| Type | The work is | Terminal state is | Safe for an autonomous cold session? |
|---|---|---|---|
| **defect** | Something behaves wrongly | A verified root cause and a fix, or a proven "works as intended" | Yes, *after* reproduction |
| **feature** | Something does not exist yet and should | New capability meeting stated acceptance criteria | Yes, if acceptance is well-formed |
| **execution** | A known, decided change applied | The change applied and verified; no design latitude | Yes -- this is the ideal goal-batch lane candidate |
| **design** | A question answered in writing | A document plus **human sign-off**. Never merged code. | Only to produce the document; the sign-off is not the agent's to give |
| **planning** | Deciding what work should exist | A set of filed items, or an explicit decision not to | **No** -- see per-type protocol below |

The line that matters most is between **execution** and **design**: an execution item has no
open decisions left, and a design item is *entirely* open decisions. Handing a design item to a
convergence loop that can only terminate on "code merged" produces a loop that cannot honestly
stop -- the exact silent-non-termination hazard
[`cold-startable-authoring.md`](cold-startable-authoring.md) is about.

### Mapping onto Beads' accepted values -- **unresolved, and blocking**

We know `task`, `bug`, and `chore` are accepted, because this repo writes all three today. We do
**not** know the full accepted vocabulary of `bd create -t`, whether unknown values are rejected
or silently accepted, or whether that set is stable across `bd` versions. This document does not
guess, and no mapping below should be implemented before the probe below runs.

Proposed mapping **conditional on the probe**:

| Our type | Preferred `issue_type` | Fallback if not accepted |
|---|---|---|
| defect | `bug` | -- (known-good) |
| feature | `feature` | `task` |
| execution | `task` | -- (known-good) |
| design | `design` | `chore` |
| planning | `epic` | `chore` |

**The probe, and where it belongs:** this repo already has the right mechanism for "we depend on
a `bd` behaviour, so prove it live." Add a named assumption -- `type.vocabulary` -- to
`contract.py`'s `CHECKS`, asserting that each value we depend on is accepted by `bd create -t`
and survives a write/read round-trip into `Item.kind`. `AGENTS.md` states `doctor` is the gate,
not a suggestion; a taxonomy built on an unproven vocabulary would be exactly the kind of silent
dependency the contract suite exists to catch. **Anchor A1 applies:** if a Beads upgrade narrows
the accepted set, the failure must surface as one named assumption in one file, not as items
quietly landing with the wrong type.

---

## Classification: who decides, and when

**Type is assigned at write time by the caller, with a per-path default -- never inferred from
prose.** Inference from a title is a guess that looks like a fact, and it would be wrong exactly
where it matters (a "fix the X design" item is a design item, not a defect).

| Write path | Default today | Proposed default | Caller override |
|---|---|---|---|
| `work_add` | `task` (hardcoded) | `execution` | yes -- optional `type` parameter |
| CLI `add` | `task` (hardcoded) | `execution` | yes -- optional `--type` |
| `work_file` | `bug` (hardcoded) | `defect` | yes, but `defect` is the right default: discovered-mid-fix work is a defect by construction |
| Gateway `POST /reports` | `chore` (hardcoded) | unchanged -- reports are not typed | no. A report is not an issue (`docs/DESIGN.md`); triage assigns the type when it creates the issue |

Note the tension with **anchor A2**'s corollary, which the tool module's own docstring states:
*"callers never need to know the label vocabulary."* Adding an optional `type` parameter is a
deliberate, narrow exception -- the caller is not being asked to know Beads' vocabulary, only
*ours*, and the seam still does the translation. The default must remain correct for a caller
who omits it entirely.

**Reclassification is an edit, not a special operation.** `Beads.update` already amends content
fields and verifies the write landed. Type should ride the same method (adding a `kind`
parameter), not acquire a bespoke verb -- it is content, not lifecycle.

## Filtering

Three additions, all mechanical once the column carries a real value:

1. **`Beads.list(type=...)`** -- one more predicate in the WHERE clause it already builds:
   `` `issues`.`issue_type` = '<literal>' ``, through `_sql_literal`. No join, no scan. This is
   the entire reason the native column wins.
2. **`--type` on the CLI `list`, `type` on `work_list`** -- choices drawn from a public
   `TYPES` tuple exported from `adapter.py`, exactly as `STATUSES` is today, so neither surface
   reinvents (or silently disagrees on) the vocabulary.
3. **`kind` in `Item.summary()`'s lean row.**

Point 3 deserves its own argument, because `summary()`'s docstring explicitly justifies keeping
the lean row lean -- it excludes timestamps on the grounds that "adding three ISO strings per row
to a 200+ item default listing would bloat the exact payload this method's docstring already
promises to keep lean." That reasoning does not extend to type: it is **one short enum string,
not three ISO-8601 timestamps**, and unlike a timestamp it is the field a caller needs *in order
to decide whether to look closer at all*. A listing that cannot distinguish a design item from an
execution item forces a second directed read per row to recover the distinction -- strictly more
payload than including it. Include it in the lean row.

## Per-type handling protocol

The point of the taxonomy is that these differ. Otherwise it is decoration.

- **defect** -- Reproduce before fixing. The item is not done because a change was made; it is
  done when the original symptom provably no longer occurs. A defect whose root cause was never
  found does not resolve, it becomes `BLOCKED-<reason>`. (This project has a live cautionary
  case: the serialization-conflict bug's *surfaced message* named a completely different cause;
  a fix aimed at the message would have shipped and changed nothing. **Anchor A3.**)
- **feature** -- Requires acceptance criteria before it is claimable. A feature item with no
  stated acceptance is not ready; it is a planning item wearing the wrong type.
- **execution** -- No design latitude remains. If the executing session finds an open decision,
  that is a signal the item was mistyped: file the decision as a `design` item via `work_file`
  and continue, or stop if it blocks.
- **design** -- Terminal state is a document plus **human sign-off**. An autonomous session may
  produce the document; it may not grant the sign-off. Every design item's acceptance should
  therefore carry an explicit `PENDING-HUMAN` terminal, and the document itself should end with
  an open-questions section (this document does, deliberately -- it is its own specimen).
- **planning** -- **Not claimable by an autonomous executor.** Planning decides what work should
  exist, which is precisely the judgment a queue-consuming agent should not be making
  unsupervised. *How* to enforce that is an open question (below): it could be a type check in
  `claim_next`, or it could ride the existing lane mechanism, which already is the claimability
  gate.

---

## What this does NOT propose

- **No backfill of the 29-odd existing items** as part of this design. Their current types are
  artefacts of a hardcoded default; see open question 4.
- **No new table, no new label namespace, no new metadata key.** That is the whole point.
- **No change to lanes.** Type answers *what kind of work is this*; lane answers *is this
  claimable, and from which queue*. They are orthogonal and must stay so -- an `execution` item
  in `lane:intake` is not yet claimable, and that is correct.
- **No type-based priority or ordering.** Ordering is `priority ASC, created_at DESC, id ASC`
  and this does not touch it.

---

## OPEN QUESTIONS / needs owner sign-off

This document is **PENDING-HUMAN**. Nothing here should be implemented before these are
answered; the first three are blocking.

1. **[BLOCKING] What `issue_type` values does the installed `bd` actually accept, and what
   happens to an unrecognised one -- rejection, or silent acceptance?** The whole mapping table
   above is conditional on this. It must be answered by a live probe and pinned as a
   `type.vocabulary` assumption in `contract.py`, not assumed from the three values this repo
   happens to use today.
2. **[BLOCKING] Do you want the five-value taxonomy at all, or a smaller one?** Three
   (`defect` / `feature` / `design`) covers most of the handling difference. `execution` vs
   `feature` and `planning` vs `design` are each a real distinction, but each also adds a
   classification decision the filer has to get right. Fewer types are more likely to be used
   correctly.
3. **[BLOCKING] Should the write surfaces expose `type` to the caller?** Doing so is a narrow,
   deliberate exception to the tool module's own stated principle that callers never need to
   know the vocabulary (see Classification above). The alternative -- keep it hardcoded per path,
   which at least makes `work_file` -> `defect` correct for free -- is less useful but strictly
   simpler.
4. **Backfill policy for existing items.** Options: (a) leave them, accepting that pre-taxonomy
   items carry a meaningless type; (b) backfill by hand at triage; (c) treat the current default
   `task` as "unclassified" and require reclassification before an item is claimable. Note that
   (c) is a behaviour change to an existing queue and would strand currently-ready items.
5. **Does type gate claimability, or does lane?** If `planning` items must not be claimable by
   autonomous executors, that can be a type check inside `claim_next` (new mechanism) or simply a
   convention that planning items live outside `lane:eng` (existing mechanism, zero new code).
   The existing mechanism is almost certainly right -- confirm.
6. **Should the taxonomy apply to reports as well as issues?** The recommendation above says no
   (a report is not an issue; the Gateway keeps `chore`), but that leaves the Gateway writing a
   value from a vocabulary this design otherwise governs. An explicit `report` type would be
   honest; it would also put an untrusted-origin value into the same column.
7. **Where does the operational half live once accepted?** This document is rationale, in
   `docs/design/`. The "which type do I pick" checklist belongs in `skills/`, alongside
   `claiming-work-safely` -- skills are what actually load into an agent's context, and a design
   doc is not read by a filing session the way a skill is. Confirm the target before implementing.
