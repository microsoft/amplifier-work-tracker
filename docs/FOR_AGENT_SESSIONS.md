# For agent sessions working this queue

You share a work queue with other agent sessions. They are working it **right now**.

Every failure mode in that arrangement is **silent** — the losing agent gets exit 0 and no error,
and finds out only after two agents have done the same work. Read the four rules.

---

## Setup (once per session)

```bash
git clone https://github.com/microsoft/amplifier-work-tracker
cd amplifier-work-tracker
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .

export AMPLIFIER_WORK_TRACKER_ROOT=~/.amplifier-work-tracker   # shared by ALL sessions

amplifier-work-tracker doctor
```

`doctor` must print **All 15 assumptions hold** before you claim anything. It runs executable
assertions against the live storage layer — including a real concurrency trial — so that an
upstream change reaches you as a loud failure instead of as silently corrupted parallel work.

**Requires `bd` >= 1.1.2 and `dolt` on PATH.** Below 1.1.2 the atomic claim operation *does not
exist*, leaving only a path that double-claims. `doctor` refuses rather than letting you proceed.

## The loop

```bash
# Create the project once (any session; it is shared)
amplifier-work-tracker new <project>

# 1. Claim exactly one item. Atomic: claim and nothing else.
amplifier-work-tracker claim --project <project> --actor <your-unique-name>

# 2. Hold it. Bind custody to a durable PID -- your session, not a transient shell.
amplifier-work-tracker custody --project <project> --actor <you> --id <id> --pid $$ &

# 3. Do the work. The claim returned `acceptance` -- that is your spec.

# 4. Close with a reason a USER will read.
amplifier-work-tracker resolve --project <project> --id <id> \
  --reason "Fixed: <what changed, in plain language>"

# 5. Carry resolutions back to whoever reported them.
amplifier-work-tracker notify --project <project>
```

Useful anytime: `amplifier-work-tracker instances` — every project, queue depth, what is held.

## Four rules. All four fail silently if you break them.

### 1. Claim atomically. Never list-then-claim-by-id.

Do **not** list ready work, choose an item, and claim it by id. Measured under real contention,
that two-step handed the same item to **2–3 agents at once**, each receiving exit 0, only one of
them actually the holder. The losers get no error and do real work on something they do not own.

The single atomic `claim` was clean across every trial. Use it, and only it.

There is a second reason the two-step fails: every agent sorts the ready list identically, so you
all pick the *same* item — maximising collisions rather than spreading load.

### 2. Custody is a liveness signal, not a timer.

Your claim is yours only while custody is being renewed.

| | Default | Meaning |
|---|---|---|
| Renewal interval | 120 s | how often the signal refreshes |
| Custody TTL | 900 s | no renewal in this window → released |
| Escalation ceiling | 24 h | fresh but `awaiting_human` this long → released, flagged |

**Idle time never costs you a claim. An *unrenewed* claim is released.** A healthily-renewed
12-hour hold is never touched; an unrenewed 16-minute hold is.

Going quiet for hours awaiting a person is healthy and expected — declare it first:

```bash
amplifier-work-tracker custody --project <p> --actor <you> --id <id> --pid $$ \
  --declared-state awaiting_human &
```

`awaiting_human` suppresses **notification only**. It does **not** exempt you from the liveness
check, and cannot — an agent that declares idleness and then dies must still be reclaimable, or
one crash wedges an item forever.

### 3. An empty queue is a normal, terminal outcome.

No ready work is not an error and not an invitation to be resourceful. It surfaces as exit code 3
with `"claimed": null`. **Report it and stop.** Do not invent work, widen scope, or pull from
another lane.

### 4. Never run `bd` directly.

Everything goes through `amplifier-work-tracker`. Raw `bd` bypasses the atomic claim, the fence
that stops a reclaimed agent from closing work it no longer holds, and the contract suite that
detects upstream breakage — that is, every silent-corruption path this tool exists to prevent.

If no command expresses what you need, that is a finding worth reporting, not a reason to go
around the seam.

## If `resolve` refuses

It is fenced: it refuses when you are no longer the holder. That means your custody went stale,
the item was released, and another agent may already hold it.

**Do not retry. Do not close it another way. Do not re-claim it to "finish what you started."**

Stop and report: what you completed, what state you left the working tree or branch in, and that
the item was reclaimed. Someone else may be part-way through it right now — a silent close would
destroy their work and tell a real user their issue was fixed when it was not.

## Filing what you find

A new problem discovered mid-fix gets linked to the item you hold, non-blocking so it will not
wedge your current work:

```bash
amplifier-work-tracker claim --help   # see the current filing flags
```

Do not shell out to the storage layer to create it — that is invisible to the contract suite and
breaks silently the next time the storage layer changes.

## Going deeper

- `docs/AGENT_PROTOCOL.md` — the same rules, agent-facing
- `docs/DESIGN.md` — why it is built this way, including the measured evidence and what was retracted
- Compose the bundle (`git+https://github.com/microsoft/amplifier-work-tracker@main`) and delegate
  to `work-tracker:work-executor`, or `load_skill("claiming-work-safely")`

## Scheduled work (operator, not agents)

Neither of these runs itself. Put both on a timer:

```bash
amplifier-work-tracker reap   --project <p>   # release claims from dead agents
amplifier-work-tracker notify --project <p>   # carry resolutions back to reporters
```

`reap` never touches a claim whose custody is fresh. `notify` exists because resolution does
**not** propagate on its own — measured: closing an item left every linked report untouched.
Without it on a timer, the return path silently never fires.

---

## Maintainer note: branch protection

`main` protection is defined in [`.github/branch-protection-ruleset.json`](../.github/branch-protection-ruleset.json).
Apply it with repo-admin rights:

```bash
gh api -X POST repos/microsoft/amplifier-work-tracker/rulesets \
  --input .github/branch-protection-ruleset.json
```

It deliberately sets `required_approving_review_count: 0` rather than 1-with-a-bypass.
Bypass actors bypass the *entire* ruleset including required status checks, so a bypass
would also exempt the bypasser from CI. With 0, the gate — PR required, CI green, linear
history, no force-push — applies to everyone including maintainers, and a solo maintainer
can still merge their own PR without admin rights. Raise the count to 1 when a second
maintainer exists.
