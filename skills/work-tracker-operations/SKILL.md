---
name: work-tracker-operations
description: "Operating and diagnosing amplifier-work-tracker: what `doctor` proves and how to read a violated assumption (fix scope is adapter.py only), the bd >= 1.1.2 version floor with the measured double-claim table, the shared-server topology requirement, scheduling reap and notify on timers (resolution does NOT propagate on its own), and the known silent sharp edges (dotted project names, TOCTOU name allocation, no storage authz, native leases don't replicate). Use when running doctor, upgrading bd, standing up a project, scheduling operator jobs, or diagnosing why something that should be automatic isn't happening."
version: 1.0.0
---

# Work Tracker Operations

This is operator territory: standing up projects, running the contract
suite, scheduling the jobs that make resolution and reclaim actually happen,
and reading what `doctor` tells you when Beads changes underneath the
system.

## What `doctor` proves

`amplifier-work-tracker doctor` is the early-warning system for Beads
changing under us. Every behaviour the system depends on — atomic claim,
non-blocking links, reverse traversal, metadata round-tripping, resolve
fencing, custody fencing, and more — is declared as a named assumption in
`amplifier_work_tracker.adapter.ASSUMPTIONS` and proven live against the
installed `bd` binary, in a disposable probe project. Run it:

- After **any** `bd` upgrade.
- In CI, on a schedule.
- Before trusting a fresh environment to run parallel agents at all.

```bash
amplifier-work-tracker doctor          # full run, including the adversarial concurrency check
amplifier-work-tracker doctor --quick  # skips claim.atomic -- faster, proves less
```

**`--quick` skips the one check that matters most.** `claim.atomic` spawns
real concurrent processes and counts winners — a static/read-only inspection
would have passed on a build that was measured double-claiming 5 times out
of 6. Only use `--quick` for a fast sanity check between full runs, never as
a substitute for one before trusting parallel agents.

### Reading a violation

A failure names the exact assumption id (e.g. `claim.atomic`,
`resolve.fenced`, `custody.fenced`). **The fix scope is
`amplifier_work_tracker/adapter.py` and nothing else.** Every Beads-specific
behaviour lives behind that one seam by design — if a fix requires touching
anything above it (the CLI, the tool module, an agent), the seam has
already been breached somewhere and that breach is the actual bug.

## Version floor

`bd >= 1.1.2` is required, and enforced at startup by every command:

| Command | Version | Topology | Trials | Double-claims |
|---|---|---|---|---|
| `bd update <id> --claim` | 1.0.0 | shared-server | 6 | **5** |
| `bd update <id> --claim` | 1.0.0 | dedicated | 6 | **3** |
| `bd update <id> --claim` | 1.1.2 | shared-server | 8 | **2** |
| `bd ready --claim` | 1.1.2 | shared-server | 6 | **0** |

Below 1.1.2, `bd ready --claim` does not exist at all, leaving only the
unsafe two-step path — the system refuses to run rather than silently fall
back to it. Above the last version the contract suite has passed on, `bd`
still runs but a `NOTE` is printed; re-run `doctor` to actually verify your
assumptions before trusting it in production.

## Shared-server topology, not per-project ports

One `dolt sql-server` process, hosting N named databases, one per project —
`bd init --shared-server`. This is Beads' native multi-project story;
nothing here manages ports or server processes.

**Do not run embedded mode with concurrent agents.** Measured: 20 concurrent
embedded writers produced **1 winner and 19 hard lock failures**
(`another process holds the exclusive lock`). Server mode produces 1 winner
and 19 clean, retryable conflicts instead. Server mode is not optional for
any topology with more than one active writer.

## Schedule `reap` and `notify` — they do not run themselves

**Resolution does not propagate to reporters automatically.** Measured
directly: closing an issue left every linked report untouched. Someone must
run:

```bash
amplifier-work-tracker reap --project <p>     # release stale custody back to the queue
amplifier-work-tracker notify --project <p>   # flip resolved reports, with the real close reason
```

Neither of these is a tool an agent session calls — they operate across
the whole project's queue, not on behalf of one session's held item (see
the bundle's operator CLI surface). Put both on a timer (cron, systemd
timer, or equivalent) per project. Without `reap` running, dead agents wedge
work forever. Without `notify` running, users never learn their report was
fixed, and the entire reason to build this system stops applying.

## Known silent sharp edges

These fail quietly if you don't know to guard against them:

- **Dotted project names produce a database that reports successful
  creation and then fails every later command.** `bd init` prints green
  checkmarks; the database is unusable. `Workspace.create` validates the
  name (`^[a-z][a-z0-9_]{1,30}$`) and proves the database answers before
  reporting success — always create projects through
  `amplifier-work-tracker new`, never `bd init` directly.
- **Project-name creation is TOCTOU.** A lock file guards it, but a race
  between "check if it exists" and "create it" is a real, if narrow, window.
- **No storage-layer authorization.** Beads issues zero SQL GRANTs by
  default — passwordless root, no TLS. Localhost-only until proven
  otherwise; the Feedback Gateway defaults to `127.0.0.1` and warns loudly
  if bound elsewhere.
- **Native Beads leases don't replicate.** They're node-local
  (`dolt_ignored`), which is exactly why custody exists as its own layer,
  carried inside the item's own metadata instead.

## Never touch `bd` directly

Same rule as the agent-facing skill, from the operator side: every
operator action goes through the `amplifier-work-tracker` CLI. If you find
yourself typing `bd ` for anything other than `doctor`'s own internal
probing, the seam is leaking and the fix belongs in `adapter.py`.
