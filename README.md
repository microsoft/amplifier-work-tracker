# amplifier-work-tracker

Multi-agent work coordination: safe parallel claiming, custody across long autonomous and idle
sessions, and feedback routed back to whoever reported it.

## Built on Beads

amplifier-work-tracker is a coordination layer on top of [Beads](https://github.com/gastownhall/beads)
(`bd`), Steve Yegge's git-native issue tracker built for AI coding agents. Beads does the hard part:
the issue graph, dependency links, the ready-queue, git-native sync with full history, and a
`--json` interface on everything. All of that is Beads' work, and it's excellent work -- go star
the repo.

What amplifier-work-tracker adds is thin, deliberately: a single seam between our vocabulary and
Beads' (so Beads' fast-moving internals never leak upward), a safe atomic-claim wrapper, a custody
system for claims that live across hours of agent idle time, a notifier that closes the loop back
to reporters, and a Feedback Gateway that keeps untrusted product agents off the work graph
entirely. If you're evaluating whether to use Beads directly instead of this project: for a single
human or a single agent, you probably don't need us. This project earns its keep the moment you
have *multiple* agents claiming from the same queue, or sessions that need to survive being idle
for hours at a time.

## Why this exists

Three problems show up the moment more than one agent works a queue at once:

1. **Agents double-claim work.** Read-then-write claiming (`bd ready` -> pick -> `bd update
   --claim`) looks safe and isn't: under contention, multiple agents each get exit 0 and believe
   they hold the same item. No error, no undo -- just silent duplicated (or conflicting) work.
2. **Long-running or long-idle agent sessions lose their claims.** A coding agent might work for
   hours, then sit completely idle awaiting a human's review or answer, then resume. Beads' own
   leases are node-local and expire on a short TTL with nothing renewing them -- exactly the kind
   of hold this workload needs to survive.
3. **User feedback never gets back to the person who reported it.** Closing the engineering issue
   that a report was linked to does not, on its own, tell the reporter anything. Without a
   deliberate return path, the loop never closes and users stop bothering to report things.

## Quick start

```bash
pip install amplifier-work-tracker
# or, from a checkout:
pip install -e ".[dev]"

amplifier-work-tracker new my-project              # create a project
amplifier-work-tracker instances                   # list projects and their queue state
amplifier-work-tracker claim --project my-project --actor agent-1
amplifier-work-tracker custody --project my-project --actor agent-1 --id <id> &
# ... do the work ...
amplifier-work-tracker resolve --project my-project --id <id> --actor agent-1 \
    --reason "Fixed: root-caused and shipped"
amplifier-work-tracker notify --project my-project
amplifier-work-tracker doctor                      # verify the installed bd still behaves as we assume
```

Compose the bundle (`git+https://github.com/microsoft/amplifier-work-tracker@main`) and load the
`claiming-work-safely` skill (or delegate to `work-tracker:work-executor`) for the full agent-facing
claim/custody loop and its hard rules, and see [`docs/DESIGN.md`](docs/DESIGN.md) for the complete
design, including every measured number below.

## How it works

**Reports and issues are two different objects.** A report is a user's raw, sloppy words, captured
automatically with full session context. An issue is a considered engineering spec with acceptance
criteria, written by a triage step -- never by editing the user's words in place. They're linked
with a non-blocking `discovered-from` dependency: the issue can be worked immediately, its source
reports stay open until the fix ships, and a notifier flips them closed with the real resolution
text once it does.

**Untrusted product agents never touch Beads directly.** They speak HTTP to the Feedback Gateway
(`amplifier_work_tracker.gateway`), which authenticates every caller to exactly one reporter
identity via bearer token, redacts PII from free text before it reaches an effectively-permanent
git/Dolt history, and is the only thing permitted to write reports on their behalf.

**Everything Beads-specific lives behind one seam**, `amplifier_work_tracker.adapter`. Nothing else
in the codebase shells out to `bd` or encodes its field names or CLI shape. This is deliberate:
Beads moves fast, and we want its improvements without its churn reaching our domain logic.

**The contract suite (`amplifier-work-tracker doctor`) is our early-warning system.** Every
behaviour we depend on is declared as a named assumption and proven live against the installed
`bd` binary -- run it after any `bd` upgrade or in CI. A failure names exactly which assumption
broke, scoped to `adapter.py`.

## The safe-claim rule

**Claim only through the single atomic operation, `bd ready --claim`. Never the two-step
`bd ready` -> pick -> `bd update --claim` path** -- it is the obvious way to write a claim, and it
double-claims silently under contention. `amplifier_work_tracker.adapter.Beads.claim_next` calls
`bd ready --claim` exclusively; the unsafe primitive is not exposed anywhere above the seam.

This isn't a theoretical concern -- it was measured directly:

| Command | Version | Topology | Trials | Double-claims |
|---|---|---|---|---|
| `bd update <id> --claim` | 1.0.0 | shared-server | 6 | **5** |
| `bd update <id> --claim` | 1.0.0 | dedicated | 6 | **3** |
| `bd update <id> --claim` | 1.1.2 | shared-server | 8 | **2** |
| **`bd ready --claim`** | **1.1.2** | **shared-server** | **6** | **0** |

A "double-claim" is the silent kind: 2-3 agents each get **exit 0** and believe they own the bead,
while only one is actually the assignee. The others proceed to work on an issue they do not hold --
no error, no undo. An earlier, single-trial measurement claimed the claim primitive was
unconditionally atomic; repeated trials retracted that. Full verification log, including the
retraction, in [`docs/DESIGN.md`](docs/DESIGN.md).

## Requirements

- [`bd`](https://github.com/gastownhall/beads) >= 1.1.2 (older builds lack `bd ready --claim` and
  leave only the unsafe claim path available)
- [`dolt`](https://github.com/dolthub/dolt), running as a shared server (`bd init --shared-server`)
- Python 3.11+

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md), which also documents the `main`
branch protection ruleset and why it's configured the way it is.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
