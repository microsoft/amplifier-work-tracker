# amplifier-work-tracker — Vision

**Status:** DRAFT

**Scope:** This is the vision for amplifier-work-tracker, which governs two seams: the **custody and coordination seam** — how claimed items are held exclusively by one actor while that actor actively maintains its grip — and the **operator surface**, the human web surface one operator watches. Other concerns — dolt-ops internals, project semantics, and work-item filtering — are explicitly out of scope.

**Governing contracts:** `contracts/custody-coordination.v1.md` (custody seam: *The Vision*, Principles 1–7); `contracts/operator-surface.v1.md` (operator surface: *The Operator Surface*, Principles 8–12). This vision points to them; it does not restate them.

---

## The Vision

The system offers a custody and coordination seam for shared work items in a distributed system. When an actor claims an item, it acquires exclusive holding rights for that item. The hold is indivisible from establishing a custody record — a claim either atomically establishes both or fails loudly, naming the specific blocker. Custody is measured as a liveness signal: a fresh renewal keeps the claim valid indefinitely, regardless of total hold duration. Reading an item never mutates or costs ownership; reads are free and cannot disqualify a claim. A close is fenced against a stale holder in every state, including after a reclaim has stripped the custody. An actor that discovers its custody has been reclaimed recovers in-process — the loss is discoverable and actionable without manual intervention or session restart.

---

## Operating Principles

1. **Atomic operations with loud refusal.** A claim establishes custody or fails loudly, naming the blocker: already held, not found, or blocked by an open dependency. There is no middle ground.

2. **Liveness over elapsed time.** A fresh custody renewal keeps a claim valid indefinitely; total hold duration never triggers reclaim. Only an unrenewed signal costs a claim.

3. **Custody freshness from a single source.** All consumers of staleness consult a single `reclaim_eligible()` function on truthful records; staleness is never re-derived in parallel paths.

4. **Fenced against stale holders.** Every close operation is guarded. A holder that no longer holds the item — including the released-but-not-yet-re-claimed state — is refused, loudly.

5. **In-process recovery from reclaim.** An agent that loses custody via reclaim discovers the loss and recovers without manual intervention, session restart, or escalation.

6. **Read paths never touch custody.** Reading an item's full body is a transactional isolation; it cannot claim, mutate, or clear a hold.

7. **No raw-bd capability exposed.** All custody interactions flow through the `work_*` tool seam. A verb absent from the seam is a missing verb — a bug, not a reason to shell out.

---

## The Operator Surface

For the one operator supervising a fleet of coding agents, this is the ambient second-monitor surface that shows what the fleet is doing — velocity, what is in flight, what is blocked, what needs a human — so nothing is stuck and nothing is missed. Calm is reported, never celebrated; the alarm is what the surface exists to make unmissable.

Its hero is fleet velocity with the counts an operator acts on: in flight, blocked, needs attention, open.

### Operating Principles

8. **Observability leads.** Velocity and the counts that decide whether to step in come first.

9. **Calm is reported, never celebrated.** A calm screen paints no alarm colour; an empty widget keeps its slot.

10. **State is never colour-only.** Colour is redundant encoding; the word is the encoding.

11. **One source of visual truth.** Colour, font, and size come from the token set.

12. **Measured, not eyeballed.** Contrast, targets, and layout are numbers a machine takes from the rendered page. A look ratifies; it never certifies.

---

## What This Repo Deliberately Resists

- **Self-enforcing TTLs:** The TTL is enforced by a required, scheduled, observable sweep. Without the sweep running, the TTL is aspirational. A dead agent's hold persists indefinitely until the sweep runs.

- **Custody liveness based on process observation:** Custody is renewed by explicit tool calls, not by monitoring process state or PID. Process death is observed indirectly via missed renewal.

- **Multiple independent staleness-decision paths:** Staleness is decided once, by `reclaim_eligible()`. All surfaces must call it; re-deriving the logic in parallel is a bug.

- **Prose-only assertions of custody behavior:** Every major invariant is backed by machine-checkable code. If a behavior is enforced, the code enforces it. Prose-only claims enter the contract as `NOT-ASSERTABLE` and are reviewed at cadence.

- **A front-end framework, template engine, build step, or plugin loader:** the operator surface is server-rendered HTML.

- **Kanban drag-boards, and client-side state that dies on refresh:** dragging a card to change state fights machine-owned custody.

- **Agents as dashboard users:** they work through the `work_*` tool seam; a machine-readable web surface is an amendment, never a drift.

- **Notifying on calm:** push carries one event class — a custody-TTL breach.

---

## Changelog

- **2026-09-04 — DRAFT amendment, owner-ratified at the ENCODE gate.** Extended from one seam to two: added *The Operator Surface*, Principles 8–12, four anti-goals, and the second contract pointer; the custody text is unchanged. Owner's words: *"Let's make hero the velocity, along w/ other numbers that matter, such as the active/in-flight, blocked, need attention, open, etc. Focus is on observability, etc. The rest looks good to me."* That opening sentence is the owner-ratified purpose. Alternative set aside: a hero that is the age of the oldest unclaimed item, never a count — *"a giant `0` trains a viewer to stop looking"* (`webapp.py:37-44`). One vision per repo, so no sibling UX file.
- **2026-09-01 — DRAFT.** First draft, derived from Phase 0 evidence and ratified decisions. Awaiting owner review at ENCODE gate and Freeze Bar ratification before promotion to FROZEN.

