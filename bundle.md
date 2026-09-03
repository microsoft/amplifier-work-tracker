---
bundle:
  name: work-tracker
  version: 0.1.0
  description: >-
    Multi-agent work coordination. Many autonomous agent sessions pull from
    shared, named, per-project queues; exactly one agent ever holds a given item.
    Adds atomic claiming, PID-bound custody that survives arbitrarily long idle
    holds, a feedback loop that carries a resolution back to the person who
    reported it, and an executable contract suite that makes upstream
    storage-layer churn fail loudly. Built on Beads (bd) as a swappable storage layer.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: work-tracker:behaviors/work-tracker
---

# Work Tracker

This bundle coordinates work across **many parallel, autonomous agent sessions**
pulling from the same project queue. It exists because three failure modes show
up the moment more than one agent works a queue at once, and each one is
**silent** — no error, no undo, just corrupted parallel work:

1. **Double-claiming.** The obvious way to claim work — list ready items, pick
   one, then update it — looks safe and isn't. Measured directly: `bd update
   <id> --claim` double-claimed in **2 to 5 of every 6 trials** under
   contention, and every losing agent still got **exit 0**. Claiming here goes
   through a single atomic operation (`bd ready --claim`) exclusively; the
   unsafe two-step path is never exposed above the seam.
2. **Lost custody on long-idle sessions.** A coding agent may work for hours,
   then sit completely idle for hours awaiting a human's review or answer,
   then resume. Beads' own leases are node-local and never replicate, and
   there is no built-in heartbeat. A custody record renewed on a timer, bound
   to the holding process's PID, is what makes an arbitrarily long *idle* hold
   survive while a *dead* hold gets released.
3. **Feedback never reaches the reporter.** Closing the engineering issue
   linked to a user's report does not, on its own, tell the reporter anything
   — measured: the report stayed `open` after its linked issue closed. A
   notifier walks the link and flips it, on a timer.

## What's available in this session

Kept in sync with `mount()`'s tool list in
`modules/tool-work-tracker/amplifier_module_tool_work_tracker/` -- audit
this table whenever that module's tools change.

| Mechanism | Name | Purpose |
|---|---|---|
| Tool | `work_claim` | Atomically claim + start PID-bound custody, in one call |
| Tool | `work_declare` | Report `working` / `awaiting_human` for the held item |
| Tool | `work_resolve` | Fenced close of the currently held item -- refuses (writing nothing) if the item is already closed with DIFFERENT text |
| Tool | `work_reopen` | Return a resolved item to the queue so its published resolution can be corrected; archives the previous record first |
| Tool | `work_erratum` | Append an append-only correction to a resolved item's record when the record is wrong but the work stands -- never rewrites `resolution`, needs no claim |
| Tool | `work_status` | Read-only: projects, queue depths, what this session holds |
| Tool | `work_file` | File newly discovered work, linked `discovered-from` the held item |
| Tool | `work_add` | File a new engineering-lane item directly, no held item required -- the sanctioned way to seed a project's FIRST item(s) |
| Tool | `work_move` | Move one item from one project's queue to another, preserving its id |
| Tool | `work_list` | Read-only per-item listing (or one item's full record via `item_id`) |
| Tool | `work_subscribe` / `work_unsubscribe` / `work_subscriptions` | Opt a project's status IN/OUT of this session's reminders (see the reminder hook below); `work_claim` auto-subscribes to whatever it claims from |
| Tool | `work_tracker_status` | Read-only: is the background service (shared dolt server + reap/notify sweeps) installed and healthy on this machine |
| Tool | `work_tracker_install` | Install and start the background service -- the only tool here that changes system state |
| Hook | `hooks-work-subscribe-reminder` | Compact, cadence-gated status reminder (ready/held/holding/custody-stale) for subscribed projects, injected like the todo/status system-reminders |
| Agent | `work-tracker:work-executor` | Claims and works engineering-lane items to resolution |
| Skill | `claiming-work-safely` | The claim/custody procedure, freshness model, and post-reap recovery |
| Skill | `work-tracker-operations` | Reading `doctor`, the seam, version floor, and scheduling reap/notify |

**No default feedback-triage agent.** `agents/feedback-triage.md` exists in
this repo but is deliberately NOT composed into this bundle by default: its
entire job is processing `lane:intake` reports, and no tool in this
bundle's default composition can read them -- every mounted `work_*` tool
works the engineering lane (`lane:eng`) only, and the agent's own Hard
Rules forbid both raw `bd` and CLI shell-out. Composing it today would give
you an agent with no legal call it could make. Compose
`work-tracker:feedback-triage` yourself once you have (or build) a tool
that exposes intake-lane items -- see `docs/DESIGN.md` section 3 for the
triage design this agent implements.

## Operator CLI surface — not agent tools

`new`, `instances`, `reap`, `notify`, and `doctor` are **operator-facing CLI
commands**, not tools an agent session calls:

```bash
amplifier-work-tracker new <project>          # create a project (once)
amplifier-work-tracker instances               # list projects and queue depth
amplifier-work-tracker reap --project <p>      # releases stale custody back to the queue
amplifier-work-tracker notify --project <p>    # propagates resolutions to reporters
amplifier-work-tracker doctor                  # run after any bd upgrade, and in CI
```

Resolution does **not** propagate to reporters on its own, and stale custody
does **not** release itself — both require `reap` and `notify` to actually
run. **If the background service is installed** (`work_tracker_install`, or
`amplifier-work-tracker service install`), both already run automatically as
in-process sweeps inside it -- see `src/amplifier_work_tracker/supervisor.py`'s
`reap_loop`/`notify_loop`. Only schedule `reap`/`notify` manually (cron,
systemd timer) if you are running `amplifier-work-tracker serve` yourself
without the installed service. Neither belongs in an agent's tool surface
either way: they operate across the whole queue, not on behalf of one
session's held item.

## Configuration

| Environment variable | Default | Meaning |
|---|---|---|
| `AMPLIFIER_WORK_TRACKER_ROOT` | `~/.amplifier-work-tracker` | Workspace root holding all named projects -- **must be the same path for every session sharing a queue**; a session pointed at a different root sees an empty queue and correctly (but silently) reports "no work" |
| `AMPLIFIER_WORK_TRACKER_CUSTODY_TTL_SECONDS` | `900` (15 min) | No renewal within this window → custody goes stale → reclaimable |
| `AMPLIFIER_WORK_TRACKER_ESCALATION_HOURS` | `24` | Ceiling on a *fresh* `awaiting_human` hold before it becomes reclaim-eligible regardless |
| `AMPLIFIER_WORK_TRACKER_RENEW_INTERVAL_SECONDS` | `120` | How often custody renews |

## What this deliberately does not add

- **No dispatcher.** Nothing in this bundle assigns work to agents or decides
  scheduling. Agents pull; nothing pushes. `bd swarm` is a computed report
  (ready-fronts, max parallelism), not a scheduler, and this bundle doesn't add
  one either.
- **No feedback-capture tool.** Untrusted product agents never touch Beads or
  this bundle's tools directly — they speak plain HTTP to the Feedback Gateway
  (`amplifier_work_tracker.gateway`), which is the only thing permitted to
  write a report on a reporter's behalf. If you're building a product agent
  that needs to capture user feedback, that's a `POST /reports` HTTP call, not
  a tool from this bundle.

---

@foundation:context/shared/common-system-base.md
