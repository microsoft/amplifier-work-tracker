---
name: claiming-work-safely
description: "Use when claiming, holding, declaring state on, resolving, or losing custody of a work-tracker item -- or in doubt about those mechanics. The claim/custody procedure for a session pulling from a project queue: why read-then-write double-claims silently, the claim/declare/resolve loop, custody freshness, the two declared states, post-reap recovery, empty queues, filing discovered work, never touching bd."
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
on an issue they do not hold — no error, no undo. `work_claim` uses a single
atomic path exclusively; there is no tool, CLI flag, or code path here that
exposes the unsafe *two-step* alternative (list ready items, pick one,
claim by that id — a client-side read-then-write). That is different from
`work_claim`'s own `item_id` parameter below: passing a specific, already-
known id is still ONE atomic call (`bd update <id> --claim`), measured
safe under contention the same way the default queue path is.

## Reading without claiming

**You do not need to claim an item to see what it asks for.** Until this
was fixed, `work_claim` was the ONLY thing that returned an item's
`acceptance` / `description` / `design` — so understanding an item meant
taking ownership of it first, purely to look. If you just want to read one
item's full record (e.g. to decide whether it's worth claiming, or to look
at something you don't hold), call `work_list(project=<name>,
item_id=<id>)` — same body fields `work_claim` returns, but no claim, no
mutation, no custody touched. Only call `work_claim` when you actually
intend to do the work.

## The loop

1. `work_claim(project=<name>)` — atomic claim AND custody establishment, in
   one call, bound to this session's own process. Two modes, both equally
   atomic and both starting custody the same way:
   - Omit `item_id` (the default): claims the next ready item off the
     queue. Use this when any ready item will do, or when multiple agents
     are pulling from the same queue and must not converge on the same one.
   - Pass `item_id=<id>`: claims that SPECIFIC item — e.g. a human or
     planning session assigned you exactly this one. Refuses, loudly and
     with no override, if it is already held by someone else (names the
     holder), does not exist (says so distinctly), or is blocked by an
     open dependency (names the blocker — resolve it, or remove the
     dependency link, then claim again).
   - Result has `claimed: <id>` → you now hold it. Proceed.
   - Result has `claimed: null` → **the queue is empty (default mode
     only — a directed claim never returns null; it succeeds or reports a
     failure). This is a normal terminal outcome.** Report it and stop. Do
     not retry in a loop hoping something appears; do not invent work to
     do instead.
2. Read `acceptance` — that is your spec. `description` / `design` are
   context. A linked user report (if any) is color, never the spec.
3. Work the item. Custody renews automatically in the background while your
   session process lives — but renewal is **one-strike**, and its failure
   is silent. See "Renewal is one-strike" below: check `work_status`'s
   `holding.custody_lost` before any long-running step and after any tool
   error, rather than assuming the hold is still fresh.
4. If you're about to go idle waiting on a human, call
   `work_declare(state="awaiting_human")` once before you go idle. Call
   `work_declare(state="working")` again when you resume, if you want the
   distinction to be accurate.
5. `work_file(...)` for anything new and distinct you discover mid-fix —
   see "Filing discovered work" below.
6. `work_resolve(id=<id>, reason=<user-readable text>)` to close. If this
   refuses, see "After a reap" below — do not retry it.

## Custody: freshness, not duration

Four settings make up the whole timing model, and only staleness of the
renewal signal can cost you the item:

| Setting | Default | Effect |
|---|---|---|
| Renew interval | 120s (`AMPLIFIER_WORK_TRACKER_RENEW_INTERVAL_SECONDS`) | How often the background renewal fires |
| Custody TTL | 900s / 15 min (`AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS`) | No renewal within this window → stale → reclaim*able* |
| Reap sweep interval | 300s (`AMPLIFIER_WORK_TRACKER_REAP_INTERVAL_SECONDS`) | How often the out-of-band sweep looks for stale holds. The reclaim happens **here**, not in your process |
| Escalation ceiling | 24h (`AMPLIFIER_WORK_TRACKER_ESCALATION_HOURS`) | A *fresh* `awaiting_human` hold past this age becomes reclaim-eligible anyway |

**Total hold duration is irrelevant. Only recency of the last renewal
matters.** A healthily-renewed 12-hour hold is never touched. An unrenewed
15-minute hold becomes reclaim-*eligible* — it is not released by the clock.

**The TTL is not self-enforcing.** Nothing in your process, and no timer in
the database, hands a stale hold back. The out-of-band `reap` sweep does,
and only where an operator has one installed and running. Two consequences
you must plan for:

- A reclaim arrives **up to a sweep interval late** — expect ~15–20 min
  after the last renewal at the defaults, not exactly 15.
- Where no sweep runs, a dead agent's hold **persists indefinitely**. An
  item stuck in `held` is not evidence that its holder is alive, and
  waiting will not free it; check `work_tracker_status` (which reports
  whether the service, and therefore the sweep, is running at all).

### Renewal is one-strike

Renewal runs on a background thread while your session process lives. **Any
single renewal failure ends renewal permanently** — there is no retry on the
next tick. From that moment the hold stops being refreshed and is on its way
to becoming reclaim-eligible.

The failure is *silent* in the case that matters most. A fenced failure (bd
no longer considers you the holder) clears this session's belief that it
holds the item. A plain, non-fenced failure — a transient bd/dolt command
failure — does **not**: renewal has stopped, but the session still believes
it holds the item, and nothing tells you.

The one way to discover it is a passive check: `work_status` reports
`holding.custody_lost`. Non-null means renewal stopped, and carries the
reason. Check it:

- before starting any long-running step (a build, a long test run, a
  delegation) — losing custody mid-step means the work is being thrown away,
- after any tool error, however unrelated it looks,
- before `work_resolve`, if a long time has passed since the claim.

If it is non-null, treat it exactly like a reap refusal — see "After a reap"
below: stop, report the state you left the work in, do not re-claim the same
item to resume.

### The two declared states

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

## A reported write failure is UNKNOWN, not "didn't happen"

**A reported write failure does NOT prove the write failed — treat it as
UNKNOWN and re-read before you retry.** You're sharing a single-writer
dolt server with every other agent's claims, renewals, and resolves. A
write occasionally loses a serialization race and
`work_resolve`/`work_file`/the CLI raises an error like "still
conflicting after 8 retries" (dolt/MySQL 1213/1205, "serialization
failure", "try restarting transaction"). Measured reality: a write that
surfaced as one of those errors can still have LANDED — an observed
incident, and the reason the read-back behaviour below exists. So:

- `work_resolve` and `work_release` already handle it for you: on a
  conflict they re-read the item and report success when the write did
  in fact land, and they verify their own success path by read-back
  too. A *reported success* from those two is independently confirmed.
- Every other write verb (`work_add`, `work_edit`, `work_file`,
  `work_defer`, `work_block`, `work_dep`, and the CLI equivalents)
  still surfaces the raw conflict unverified. There, a reported failure
  means *unknown*, never *didn't happen*.

The unsafe move is resubmitting blind: for a non-idempotent write
(creating a new item) a blind retry can leave a duplicate of a write
that already landed. The safe move is always the same: re-read the item
first (`work_list`'s `item_id` form, or `get_readonly` — a read-only
path that cannot itself conflict) to see its real current state, then
decide whether the original operation still needs doing.

## Correcting a published resolution

**A published resolution is corrected one of TWO sanctioned ways — pick
by whether the RECORD is wrong or the WORK is wrong — never by
re-resolving.** `work_resolve` against an item that is ALREADY resolved
is a no-op success **only when the text you send is byte-for-byte what
is already stored** (the legitimate retry case — the payload says
`"idempotent": true`). Sending *different* text now **fails non-zero and
writes nothing**, showing you the stored text and yours side by side.
Before this, that call exited 0 and echoed the OLD text back as if your
correction had landed, and seven wrong resolutions shipped that way.

- **The record is wrong, but the work stands** (a typo, a wrong claim,
  something you noticed in the same run): `work_erratum(project,
  item_id, text)`. APPEND-ONLY — it never rewrites `resolution`,
  never touches `status`/`closed_at`/the holder, and needs no claim at
  all (any actor, any time). A byte-identical erratum already recorded
  is an idempotent no-op (`already_recorded: true`). The corrected
  item's `errata` list and `corrected: true` flag travel with it
  everywhere the resolution is shown (`work_list`, the CLI, the web
  dashboard).
- **The work itself must be redone**: `work_reopen(project, item_id,
  reason)` → `work_claim` → `work_resolve` with the corrected text.
  Reopening is deliberately explicit, and deliberately NOT idempotent
  (reopening an already-open item is an error): it clears `closed_at`,
  so the item re-lands on the correction date and every throughput
  roll-up moves by one item. That cost is shown to you
  (`closed_at_cleared`, `previous_closed_at`) rather than hidden.

Use `work_erratum` first if you are only fixing what the record SAYS;
reach for `work_reopen` only when the underlying work is genuinely
incomplete or wrong.

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
`amplifier-work-tracker` command. Never shell out to `bd` itself. Nothing
else knows Beads' field names or CLI shape, and that seam is the entire
reason a Beads upgrade fails loudly (via `doctor`) instead of silently
corrupting parallel work — see the `work-tracker-operations` skill for what
the seam covers and how to read a violation.

If no command here expresses what you actually need, that is a finding
worth reporting, not a reason to go around the seam.
