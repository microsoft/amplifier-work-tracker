# amplifier-work-tracker — Vision

**Status:** DRAFT

**Scope:** This document describes the vision for the **custody and coordination seam** of amplifier-work-tracker. The seam governs how claimed items are held exclusively by one actor while that actor actively maintains its grip. Other concerns — dashboard rendering, dolt-ops internals, project semantics, and work-item filtering — are explicitly out of scope.

**Governing contract:** `contracts/custody-coordination.v1.md` — the contract that backs this vision.

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

## What This Repo Deliberately Resists

- **Self-enforcing TTLs:** The TTL is enforced by a required, scheduled, observable sweep. Without the sweep running, the TTL is aspirational. A dead agent's hold persists indefinitely until the sweep runs.

- **Custody liveness based on process observation:** Custody is renewed by explicit tool calls, not by monitoring process state or PID. Process death is observed indirectly via missed renewal.

- **Multiple independent staleness-decision paths:** Staleness is decided once, by `reclaim_eligible()`. All surfaces must call it; re-deriving the logic in parallel is a bug.

- **Prose-only assertions of custody behavior:** Every major invariant is backed by machine-checkable code. If a behavior is enforced, the code enforces it. Prose-only claims enter the contract as `NOT-ASSERTABLE` and are reviewed at cadence.

---

## Changelog

- **2026-09-01 — DRAFT.** First draft, derived from Phase 0 evidence and ratified decisions. Awaiting owner review at ENCODE gate and Freeze Bar ratification before promotion to FROZEN.

