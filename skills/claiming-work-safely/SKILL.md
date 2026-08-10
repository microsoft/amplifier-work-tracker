---
name: claiming-work-safely
description: "The claim/custody procedure for any session that claims work directly from a work-tracker project queue: why the obvious read-then-write approach double-claims silently, the loop through work_claim/work_declare/work_resolve, the custody freshness model (renew/TTL/escalation), the two declared states, what to do after a reap, empty-queue handling, filing discovered work, and the never-touch-bd rule. Use when claiming, holding, declaring state on, resolving, or losing custody of a work-tracker item -- or when in doubt about any of those mechanics."
version: 1.0.0
---

# Claiming Work Safely

More than one agent is pulling from the same project queue, right now. Every
rule below exists because the naive approach fails **silently** — no error,
no undo, just corrupted parallel work discovered much later.

## Why the obvious approach is wrong

The intuitive way to claim work is: list ready items, pick one, mark it
yours. This was measured directly and it double-claims under contention:

| Command | Version | Topology | Trials | Double-claims |
|---|---|---|---|---|
| `bd update <id> --claim` | 1.0.0 | shared-server | 6 | **5** |
| `bd update <id> --claim` | 1.0.0 | dedicated | 6 | **3** |
| `bd update <id> --claim` | 1.1.2 | shared-server | 8 | **2** |
| `bd ready --claim` (what `work_claim` uses) | 1.1.2 | shared-server | 6 | **0** |

A double-claim is silent: 2–3 agents each get a success signal and believe
they hold the same item. Only one actually does. The others proceed to work
on an issue they do not hold — no error, no undo. `work_claim` uses the
single atomic path exclusively; there is no tool, CLI flag, or code path
here that exposes the unsafe two-step alternative.

## The loop

1. `work_claim(project=<name>)` — atomic claim AND custody establishment, in
   one call, bound to this session's own process.
   - Result has `claimed: <id>` → you now hold it. Proceed.
   - Result has `claimed: null` → **the queue is empty. This is a normal
     terminal outcome.** Report it and stop. Do not retry in a loop hoping
     something appears; do not invent work to do instead.
2. Read `acceptance` — that is your spec. `description` / `design` are
   context. A linked user report (if any) is color, never the spec.
3. Work the item. Custody renews automatically in the background for as
   long as your session process stays alive — you do not need to do
   anything to keep it fresh under normal operation.
4. If you're about to go idle waiting on a human, call
   `work_declare(state="awaiting_human")` once before you go idle. Call
   `work_declare(state="working")` again when you resume, if you want the
   distinction to be accurate.
5. `work_file(...)` for anything new and distinct you discover mid-fix —
   see "Filing discovered work" below.
6. `work_resolve(id=<id>, reason=<user-readable text>)` to close. If this
   refuses, see "After a reap" below — do not retry it.

## Custody: freshness, not duration

Two clocks matter, and only one of them can cost you the item:

| Setting | Default | Effect |
|---|---|---|
| Renew interval | 120s (`AMPLIFIER_WORK_TRACKER_RENEW_INTERVAL_SECONDS`) | How often the background renewal fires |
| Custody TTL | 900s / 15 min (`AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS`) | No renewal within this window → stale → reclaimable |
| Escalation ceiling | 24h (`AMPLIFIER_WORK_TRACKER_ESCALATION_HOURS`) | A *fresh* `awaiting_human` hold past this age becomes reclaim-eligible anyway |

**Total hold duration is irrelevant. Only recency of the last renewal
matters.** A healthily-renewed 12-hour hold is never touched. An unrenewed
15-minute hold is released back to the queue.

The two declared states:

- **`working`** — the default. If your custody signal goes stale while
  declaring this, you are reclaimed exactly like anything else.
- **`awaiting_human`** — suppresses the "worth a human's attention"
  notification only. It buys **zero** exemption from the staleness check —
  an agent that declares this and then dies still goes stale on schedule
  and is reclaimed. Its only other effect is the escalation ceiling: a
  *fresh* `awaiting_human` hold that has sat that way past 24 hours becomes
  reclaim-eligible regardless, so one unresponsive human can't immobilize
  an item forever.

## After a reap: stop, don't retry

If `work_declare` or `work_resolve` refuses because your custody was
reclaimed (stale, or a takeover), **you no longer hold the item.** Do not:

- Re-claim the same item hoping to resume — someone else may already hold
  it, or it may still be open and you'd be double-claiming yourself into
  the exact hazard this system exists to prevent.
- Retry the same call expecting a different result.

A silent close here would destroy their work AND tell a real user their
issue was fixed when it was not — that is the actual failure this refusal
exists to prevent, not just a technicality.

Do:

- Stop immediately.
- Report exactly what you had completed and the state you left the work in
  (files changed, tests run, anything not yet committed).
- Let a human or the next claimer decide how to proceed.

> **KNOWN ISSUE (as of 2026-08-10, fixed in this same change):** on the
> refusal path above, `WorkTrackerSession` used to clear its held-item state
> only on success. A reap/takeover refusal left the session believing it
> still held the reclaimed item — so `work_claim`/`work_declare`/`work_resolve`
> for ANY item then refused for the rest of that process's life, with no
> tool call able to clear it. If you are running a build older than this
> fix, the guidance above still applies (stop, report, do not retry) but
> recovery additionally requires a fresh process. This fix (see
> `WorkTrackerSession.resolve`/`.declare`/`._renew_loop`) clears the held
> state on a fenced/reclaimed refusal so the SAME session can claim again
> immediately — verified via a claim → force-reap → claim-again test
> covering both the explicit refusal and the background renewal loop's own
> detection.

## Empty queue

`work_claim` returning `claimed: null` is not an error, a bug, or a signal
to look harder. It means there is currently no ready work in that project's
engineering lane. Report it plainly and stop.

## Filing discovered work

Found a distinct problem while working something else? Call
`work_file(title=..., description=..., acceptance=...)`. It links
automatically via `discovered-from` to the item you currently hold, and is
non-blocking — it will not wedge your current work. You must be holding an
item to call it; there is no way to file work "detached" from what you're
currently doing.

## Never touch `bd` directly

Every interaction with the queue goes through `work_claim`, `work_declare`,
`work_resolve`, `work_status`, `work_file`, or (for CLI/operator use) the
`amplifier-work-tracker` command. Never shell out to `bd` itself. That seam
is the entire reason a Beads upgrade fails loudly (via `doctor`) instead of
silently corrupting parallel work — see the `work-tracker-operations` skill

If no command here expresses what you actually need, that is a finding
worth reporting, not a reason to go around the seam.
for what the seam covers and how to read a violation.
