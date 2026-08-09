# Design: User Feedback -> Engineering Work, on Beads

**Status:** proposed, core graph mechanics proven end-to-end on `bd` (server mode) 2026-08-09
**Audience:** engineers integrating amplifier-work-tracker into a product or agent fleet
**Replaces:** per-product ad-hoc file protocols

---

## The one idea

**A user report and an engineering issue are two different objects.** Everything else follows.

Filesystem protocols fail because they conflate them: a file gets dropped, then edited into a spec,
then edited into a status, and it is simultaneously the user's words, the engineer's spec, and the
status board. Three lifecycles in one mutable file, on N machines, with no atomicity.

Split them:

| | Report | Issue |
|---|---|---|
| Authored by | user (sloppy, partial, emotional) | triage agent (considered) |
| Is it a spec? | **never** | yes -- has acceptance criteria |
| Cardinality | many | few (N reports -> 1 issue) |
| Who reads it | triage agent, reporter | coding agent |
| Lifecycle | open -> acknowledged -> answered | open -> in_progress -> closed |

Link them with a `discovered-from` dependency. **Verified:** `discovered-from` is non-blocking --
the issue lands in `bd ready` while its source reports are still open. That's the property the whole
design rests on, and I confirmed it rather than trusting the docs.

---

## Shape

```
  USER                    GATEWAY                BEADS (dolt server)          CODING SESSION
  ----                    -------                -------------------          --------------
  product agent  --POST--> /reports --bd create--> [report] lane:intake
   (untrusted)                                          |
                                                         | triage agent
                                                         | (sloppy -> considered)
                                                         v
                                                    [issue] lane:eng <---bd ready --claim---+
                                                         |  ^ discovered-from                |
                                                         |  +--------------+                 |
                                                         |                        does the work,
                                                         |  bd close              opens PR, gates
                                                         v                                 |
  product agent  <--GET-- /reports?reporter=me <-- notifier flips linked reports <---------+
   "that thing you
    reported? fixed."
```

Three actors, one graph, one write boundary.

---

## 1. Capture -- burden the machine, not the user

The product agent gets one tool: `report_feedback(text)`. That is the entire user-facing surface.

**Do not interrogate the user.** They will not answer, and their answers are worse than your
telemetry. The agent attaches everything else automatically at capture time:

```json
{
  "reporter_id": "alice",       // stable across sessions -- this is what makes the return path work
  "session_id": "s-8891",
  "app_version": "2.3.1",
  "surface": "chat",
  "verbatim": "ugh it forgot my name AGAIN",
  "recent_turns": "...",         // last N turns, redacted
  "last_error": "...",
  "captured_at": "..."
}
```

Goes in `bd create --metadata`. Arbitrary JSON, queryable later. The user typed six words; the bead
carries a case file.

**Return the report ID to the user immediately.** `bd-a1b2`. That is their receipt, and it is what
they'll reference three sessions from now.

## 2. The write boundary -- the single most important structural decision

**Product agents never touch `bd` directly.** They speak HTTP to the Feedback Gateway
(`amplifier_work_tracker.gateway`); the Gateway is the only process that writes reports.

Why this is non-negotiable:

- **Security** -- product agents run in user context. Direct DB access means users write to your work graph.
- **Concurrency** -- I measured this: 20 concurrent `bd` writers in *embedded* mode produce **1 winner and 19 hard failures** (`another process holds the exclusive lock`). Server mode produces 1 winner and 19 clean conflicts. You need server mode, and you do not want to expose `dolt sql-server` to client machines.
- **Quality** -- the boundary is where you rate-limit, redact PII, and reject junk before it pollutes the graph.

The Gateway is small. Three endpoints:

| Endpoint | Does |
|---|---|
| `POST /reports` | validate -> `bd create` (lane:intake) -> return report ID |
| `GET /reports?reporter=X` | reporter-scoped list + resolved status |
| `GET /reports/{id}` | one report + its linked issue's public status |

That's it. If it grows a fourth endpoint, ask why.

## 3. Triage -- the sloppy -> considered transform

A scheduled agent working `bd ready --label lane:intake`. **Triage owns the intake -> engineering
transform**: it is the only thing allowed to create a new `lane:eng` issue linked `discovered-from`
a `lane:intake` report.

This does not mean triage is the only thing that can ever create a `lane:eng` item. A coding agent
already working an engineering item may file a **discovered** problem it finds mid-fix -- see
section 4, item 3. The two are distinguishable by what the `discovered-from` link points at: triage's
issues link back to a user *report*; an executor's discovered work links back to the *engineering
item it was already holding*. (An earlier draft of this document said triage was the only thing
"allowed to create `lane:eng` issues" full stop, which conflicted with the coding-agent protocol's own
"file what you find" rule -- this section and `docs/AGENT_PROTOCOL.md` are now reconciled on this
point.)

For each report, exactly one of six outcomes. Every one produces a reply the reporter can see:

| Outcome | Graph action | Reporter sees |
|---|---|---|
| **Duplicate** | link `discovered-from` to existing issue | "known, tracked, here's status" |
| **New issue** | create issue + link | "filed as X" |
| **Needs info** | park report, queue question | asked in their *next* session |
| **Not actionable** | close with reason | honest "not a bug, here's why" |
| **Already fixed** | link to closed issue | "fixed in 2.4.0, update" |
| **Out of scope** | close, tag for product review | "heard, not planned" |

**The issue it writes must be a real spec.** `bd create` has the fields -- use them:

- `--description` -- what's actually happening, synthesized across reports
- `--design` -- hypothesis, suspected component
- `--acceptance` -- Given/When/Then. **This is the contract the coding agent is held to.**

Raw user text goes in the *report*, linked. The coding agent can read it for color. It is never the spec.

**Dedup is the hard part.** Start dumb: LLM over the ~50 most recent open issues in the same area.
Do not build a vector store on day one. Revisit when a human notices duplicate issues, not before.

## 4. Coding agent protocol

```bash
bd ready --label lane:eng --claim --assignee "$AGENT_ID" --json
```

**Verified:** atomic. 20 concurrent claims -> exactly one winner, the other 19 get
`issue already claimed by agent-3`. This is a real compare-and-swap, not a read-then-write.

(See the **RETRACTION** below -- this single-trial finding did not hold up under repeated testing.
`amplifier-work-tracker claim` uses `bd ready --claim` exclusively, never the two-step path.)

Then:

1. **Heartbeat.** Leases default to a 5-minute TTL and **nothing heartbeats them for you.** No daemon, no reaper. Your harness runs `bd heartbeat` well under 5 min or a live agent silently loses its claim. (In practice: `bd heartbeat` does not exist in the release we run against -- see custody, below.)
2. **Work in a git worktree.** `bd worktree create` -- worktrees share the parent bead DB automatically. This is the best-supported parallel story in the tool.
3. **File what you find.** New problems discovered mid-fix get filed as their own item, linked
   `discovered-from` the issue you're currently holding -- through `amplifier-work-tracker`'s
   `work_file` tool (or the CLI equivalent), never a raw `bd create --deps discovered-from:<id>`
   invocation. Non-blocking, so they don't wedge the current work but the trail survives. (This is
   the one place a coding agent creates a `lane:eng` item directly -- see section 3's reconciliation
   of who creates what.)
4. **Gate on reality, not on intent.** `bd gate` with `gh:pr` -- the dependent issue does not open until the PR actually merges. Not when the agent *says* it's done.
5. **Close with a reason.** `bd close --reason "..."` -- this string reaches the user. Write it for them, not for the changelog.

And a supervisor process runs `amplifier-work-tracker reap` on a timer, or dead agents wedge work forever.

## 5. The return path -- the reason to build any of this

When the issue closes, `amplifier-work-tracker notify` walks `dependents` on every linked report and
flips them to `resolved` with the close reason.

**Verified:** `bd show <report>` returns a `dependents` array containing the full issue -- status,
assignee, acceptance criteria, close reason. The reverse traversal works today.

**Also verified: propagation is NOT automatic.** I closed the issue; the linked report stayed `open`.
The notifier is ours to build. It is maybe 40 lines.

Next time Alice opens a session, her agent says: *"That name-forgetting thing you reported in March --
fixed in 2.4.0."* Nobody else's feedback system does this. It is nearly free once the links exist,
and it is the entire reason users keep giving you signal.

---

## What Beads gives vs. what we build

| Beads gives (free) | We build |
|---|---|
| Graph, deps, ready-queue | Feedback Gateway (~200 lines) |
| **Atomic claim** (proven, with a caveat -- see retraction) | Heartbeat + reclaim supervisor (custody) |
| Git-native sync, full history | Triage agent |
| `--json` on everything | Close-notifier (report status propagation) |
| Arbitrary metadata, labels, acceptance fields | Reporter-scoped read view |

Everything in the right column is small. Everything in the left column is what made the filesystem
version fragile.

---

## Hard rules

1. **Server mode only** (`bd init --shared-server`). Embedded mode + parallel agents = 19 of 20 agents hard-fail. Measured, not assumed.
2. **Product agents never write to `bd`.** Gateway only.
3. **User words are never the spec.** Reports carry them; issues carry acceptance criteria.
4. **Lanes are labels, and the ready query is always filtered.** Unfiltered `bd ready` returns raw intake reports into the coding agent's queue. Always `--label lane:eng`.
5. **Use the `codex` AGENTS.md profile** (~300 tokens). The default profile injects *"do NOT use TodoWrite"* and *"do NOT use MEMORY.md"* -- it will fight your existing conventions. Also note `bd init` silently writes `CLAUDE.md` and `.claude/settings.json`.
6. **Do not lean on `bd merge-slot`.** Read-then-write, no CAS guard, zero test coverage upstream. It won my 15-way race; that is one trial, not a guarantee. Use `--claim` as the coordination primitive.

## Parked (good ideas, not now)

- **Gas Town** (Yegge's orchestration layer on Beads). Real, 17.5k stars -- and DoltHub's field report is ~$100/hr token burn, auto-merged failing tests, force-pushes to recover. Revisit when our own loop is boring.
- **Semantic dedup / vector search.** Dumb LLM dedup first. Build this when duplicates actually hurt.
- **`bd swarm`.** It's a computed report (ready-fronts, max parallelism), not a dispatcher. Useful telemetry later; it schedules nothing.
- **Cross-project federation.** Leases are `dolt_ignored` and never replicate -- dead-agent recovery is per-machine only. One machine, one server, until that hurts.

## Thinnest provable slice

Two days, in this order. Do not build ahead of it.

1. Stand up `bd init --shared-server`. Hand-create a report bead with `--metadata`. Prove `bd ready --label lane:eng --claim` from two terminals gives one winner.
2. Gateway `POST /reports` only. Product agent gets `report_feedback`. Prove a real user sentence lands as a bead with full context attached.
3. Triage by hand for the first week. **Do not automate the transform you haven't done manually yet** -- you will not know what "considered" means until you've done twenty.
4. Coding agent claims, closes with a reason.
5. Notifier + `GET /reports?reporter=X`. Close the loop. Tell one real user their thing got fixed.

Step 5 is the proof. Everything before it is plumbing.

---

## Verification log (2026-08-09, `bd` v1.0.0, dolt 2.2.3, server mode)

| Claim | How verified | Result |
|---|---|---|
| `discovered-from` is non-blocking | created issue with 2 report deps | issue in `bd ready`, `bd blocked` empty [pass] |
| ~~Claim is atomic~~ | ~~20 concurrent `--claim`~~ | **RETRACTED -- see v2 amendments. That was one lucky trial.** |
| Embedded mode breaks under concurrency | same race, embedded | 1 winner, **19 lock failures** [warn] |
| Lane filtering works | `bd ready --label lane:eng` | only the eng issue [pass] |
| Reverse traversal (report -> issue) | `bd show <report> --json` | `dependents[]` w/ status, acceptance, close reason [pass] |
| Status propagates automatically | closed issue, re-read report | **NO** -- report stayed `open` [warn] build notifier |
| `merge-slot` exclusion | 15 concurrent acquire | 1 winner [pass] (1 trial only, no CAS in code) |

**Known sharp edge:** `bd init` in a directory whose name contains a dot produces `invalid database
name` on every subsequent command -- while `bd init` itself reports success with green checkmarks.
Silent-success-then-broken. `amplifier_work_tracker.adapter.Workspace.create` validates the name and
then proves the database is writable immediately after init, and fails loud otherwise.

**Version caveat:** measured on installed `bd` v1.0.0; latest is v1.1.2, which **removed** the
embedded flock. The race table was re-run on v1.1.2 -- see v2 amendments below.

---

# v2 Amendments (2026-08-09) -- multi-project topology + a retracted claim

## Goal, in one sentence

*Turn sloppy live user feedback into properly-specified engineering work that many parallel coding
agents can safely claim, and tell the reporter when it ships.*

## Requirement #6, answered: yes, we were reinventing it

**Do not build a launcher, a port-allocator, or an instance registry.** Beads ships the multi-project
topology natively:

```
bd init --shared-server        # or config: dolt.shared-server / BEADS_DOLT_SHARED_SERVER=1
```

**ONE** `dolt sql-server` on **port 3308** hosting **N named databases**, one per project, under
`~/.beads/shared-server/dolt/<name>/`. Verified: 2 projects -> 1 process -> full isolation.

```
~/.beads/shared-server/dolt/{alpha,bravo}   <- one dir per project
LISTEN 127.0.0.1:3308  users:(("dolt",pid=1002647))   <- one process
```

Sessions get pointed at a project by `BEADS_DIR` (highest precedence), `BEADS_DOLT_SERVER_DATABASE`,
`.beads/redirect`, or cwd walk-up. A cross-project `beads_global` DB exists via `--global`.

Note the tool is actively steering away from per-project ports: `bd serve`'s own help warns that
ephemeral-port serves have *"no way to enumerate them."* Shared-server is the sanctioned path.

### Still ours to build (small, real)

| Gap | Note |
|---|---|
| `amplifier-work-tracker instances` | Doesn't exist in bd. It's `SHOW DATABASES` + filter -- Beads already does this internally 4x. |
| Server supervision | Nothing starts/restarts the shared server at boot. systemd unit. |
| Prefix allocation | Collisions are *detected*, never *prevented*. TOCTOU on create. Ours to police. |
| AuthZ | Beads issues **zero** SQL GRANTs. Default user `root`, empty password, no TLS. |
| Heartbeat + reclaim | Unchanged: nothing runs these for you. This is `amplifier_work_tracker.custody`. |

## RETRACTION: the claim primitive is not unconditionally atomic

**I previously marked "claim is atomic [pass]" on the strength of one 20-way trial. That was luck, and I
was wrong to bank it.** Repeated trials:

| Command | Version | Topology | Trials | Double-claims |
|---|---|---|---|---|
| `bd update <id> --claim` | 1.0.0 | shared-server | 6 | **5** |
| `bd update <id> --claim` | 1.0.0 | dedicated | 6 | **3** |
| `bd update <id> --claim` | 1.1.2 | shared-server | 8 | **2** |
| **`bd ready --claim`** | **1.1.2** | **shared-server** | **6** | **0** [pass] |

A "double-claim" is the silent kind: 2-3 agents each get **exit 0** and believe they own the bead,
while only one is actually the assignee. The others proceed to work on an issue they do not hold.
No error, no undo.

### The rule this produces

> **Claim only via `bd ready --claim` on bd >= 1.1.2. Never `bd ready` -> pick -> `bd update --claim`.**
> The two-step is the unsafe path, and it is the obvious one to write.

Two gotchas found the hard way: `--claim` **cannot be combined with `--assignee`** (identity comes from
`BEADS_ACTOR`), and `bd ready --claim` **does not exist at all** in v1.0.0 -- so v1.0.0 users have only
the unsafe path available. **Pin >= 1.1.2.**

Upstream appears to know: repo HEAD carries `PROPOSAL-cas-conditional-update.md` and an
`[Unreleased]` "Replica-aware leases" entry. Track it upstream; do **not** build our own lock layer.

`amplifier_work_tracker.adapter.Beads.claim_next` calls `bd ready --claim` exclusively and offers no
two-step path at all -- the unsafe primitive is not exposed anywhere above the seam.

## Council findings folded in

Convened the full six-lens council. Unanimous: the report/issue split, Gateway boundary, six-outcome
triage, `discovered-from` link, and notifier concept are **sound -- don't touch them**. The damage is
concentrated at the extension points. Open punch list (now closed in the implementation):

1. **IDOR on `GET /reports?reporter=X`** -- nothing binds the caller to that reporter identity. Any
   product agent can read another user's report history, including `recent_turns` / `last_error`.
   Application-layer authz, separate from TLS. **Blocker.** -- **Closed:** the Gateway resolves identity
   solely from the bearer token; a request that also supplies a reporter/project gets a 403 if it
   disagrees.
2. **PII is permanent** -- `recent_turns` "// redacted" is a *comment, not a mechanism*. It lands in
   Dolt/git immutable history. Specify and test redaction **before** `bd create --metadata`, or write
   an explicit accepted-risk statement. **Blocker.** -- **Closed:** `amplifier_work_tracker.gateway.redact`
   /`_redact_context` run on every free-text field before the write, verified at the storage layer
   in tests (not just the API echo).
3. **Notifier write is unguarded** -- the "flip report to answered" write needs the same CAS-and-verify
   discipline as the claim path, against the same Dolt cell-merge risk. -- **Closed:** `resolve()` reads
   back and verifies status after every write; `notify` re-reads before flipping.
4. **Project-name creation is TOCTOU** -- use a constraint, not error-string matching. -- **Closed:**
   name validation happens before any filesystem/subprocess work, and creation is guarded by an
   exclusive lock file.
5. **Network topology must be decided and written down** -- passwordless root + zero TLS is
   disqualifying the moment it is reachable off-box. Localhost-only until proven otherwise. --
   **Closed:** the Gateway defaults to `127.0.0.1` and prints a loud warning if bound elsewhere.
6. **Reject dotted project names loudly** -- the documented `bd init` landmine, now multiplied by
   "many named projects." -- **Closed:** `NAME_RE` rejects any name that isn't
   `[a-z][a-z0-9_]{1,30}`, before any I/O.

Two words that mean two people in this doc: **"user"** = Alice the reporter, *and* the operator
routing agent sessions. Disambiguate before the next revision.

## Revised gate

Sequencing bar: **evidence, not implementation.** Each punch-list item closes on its own evidence --
fixing the claim path closes exactly one of them and none of the others.
