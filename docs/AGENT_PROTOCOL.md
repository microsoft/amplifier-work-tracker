# Coding Agent Protocol -- amplifier-work-tracker

You are one of several agents working the same project queue. Others are running right now.

## Setup (once per session)

```bash
export AMPLIFIER_WORK_TRACKER_ROOT=<root>    # given to you
export BD_ACTOR=<your-agent-name>            # unique per session
```

(`amplifier-work-tracker` is installed as a console script, so no PATH setup beyond the
normal package install is required.)

## The loop

```bash
amplifier-work-tracker instances                                    # what projects exist
amplifier-work-tracker claim --project <p> --actor "$BD_ACTOR"       # get ONE unit of work
amplifier-work-tracker custody --project <p> --actor "$BD_ACTOR" --id <id> &   # start in the background
# ... do the work ...
amplifier-work-tracker resolve --project <p> --id <id> --actor "$BD_ACTOR" --reason "<what the USER will read>"
amplifier-work-tracker notify --project <p>                         # tell the reporters
```

`claim` returns the issue plus its `acceptance_criteria`. **That is your spec.** The raw user
report is linked for color only -- never treat a user's words as the specification.

## Custody -- how a claim stays yours across a long, idle hold

Beads' own leases are node-local and never replicate, and `bd heartbeat` / `bd reclaim` do not
exist in this build. Liveness for a held item is entirely ours: `amplifier-work-tracker custody`
runs in the background, bound to the PID you point it at, and renews your custody signal every 2
minutes (default) until that PID exits -- at which point it exits too, on its own.

You may sit **completely idle for hours** awaiting a human's answer or review; that is fine and
expected. Custody eligibility depends **only** on whether the signal is still being renewed, never
on how long you have held the item or what you say you're doing. If you know you're about to go
idle waiting on a person, start (or re-run) custody with `--declared-state awaiting_human` -- it
only suppresses "worth a human's attention" reporting, it never buys you exemption from the
liveness check itself, and after `ESCALATION_HOURS` (24 by default) in that state you become
reclaim-eligible regardless, flagged for a human to look at.

## Hard rules

1. **Never run `bd update <id> --claim`.** It double-claims under contention: 2-3 agents each get
   exit 0 for the same bead, only one is really the assignee, and the losers get no error. Always
   claim through `amplifier-work-tracker claim`, which uses `bd ready --claim` -- measured clean
   under contention.

2. **Never pick work by reading `bd ready` and choosing.** Every agent sorts the list identically,
   so you will all choose the same bead. Let `amplifier-work-tracker claim` hand you one.

3. **Start `amplifier-work-tracker custody` right after claiming, in the background, or lose the
   claim.** `amplifier-work-tracker reap` releases items whose custody signal has gone stale
   (default 15 min without a renewal) back to the queue. A long *idle* hold is fine; a long
   *unrenewed* hold is not -- those are different things and only the second one is reclaimed.

4. **Exit code 3 from `claim` means the queue is empty.** That is a normal outcome, not an error.
   Stop; do not invent work.

5. **File what you find.** A new problem discovered mid-fix gets filed through the `work_file` tool
   (bundle sessions) or the CLI equivalent -- never a raw `bd create --deps discovered-from:<id>`
   invocation, which would breach the one seam (`amplifier_work_tracker.adapter`) everything Beads-
   specific is required to live behind. It links automatically to the item you currently hold and is
   non-blocking, so it will not wedge your current work.

   This is the one place a coding agent creates a `lane:eng` item directly. Triage
   (`docs/DESIGN.md` section 3) owns the transform from a *user report* to a new engineering issue;
   what you're filing here is *discovered* work, linked to the engineering item you're already
   holding, not to a report. The two are distinguishable by what `discovered-from` points at.

6. **Always close through `amplifier-work-tracker resolve`, never `bd close` directly.**
   `resolve` refuses if your claim was reclaimed while you were away (fenced against a non-current
   holder), so a stale agent cannot silently close work it no longer owns. `--reason` is read by
   the person who reported it -- write it for them.
