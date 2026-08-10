# Work Tracker — hazards that fail silently

You're one of several agents pulling from a shared work queue. First use in
a session, or any `work_*` call fails to connect: call `work_tracker_status`
before assuming a server is running — see "Where to go next" below.

Four things here fail **silently** if you get them wrong — no error, no undo:

1. **Claim only via `work_claim` / `work_status`; never list-then-pick.** The
   obvious approach — read the ready queue, choose an item, mark it yours —
   double-claimed in **2–5 of every 6 measured trials**, and every losing
   agent still got exit 0. `work_claim` is the single atomic claim-and-custody
   operation. There is no other way to take an item.

2. **Custody is a liveness signal, not a timer.** Idle time never costs you a
   claim — you may sit for hours awaiting a human's answer. What costs you a
   claim is an **unrenewed** custody signal: 15 minutes without a renewal and
   the item releases back to the queue, whether or not you were "still
   working" in spirit. `awaiting_human` (via `work_declare`) only suppresses
   a human-attention notification — it never buys exemption from that clock.

3. **An empty queue is a normal terminal outcome.** `work_claim` returning
   `claimed: null` means stop and report — not a signal to invent work or
   retry.

4. **Never speak to `bd` directly.** Every interaction goes through
   `work_claim` / `work_declare` / `work_resolve` / `work_status` /
   `work_file`, or the `amplifier-work-tracker` CLI. Nothing else knows Beads'
   field names or CLI shape, and that seam is what keeps upstream changes
   from silently corrupting parallel work.

## Where to go next

- No server running, or unsure → `work_tracker_status`; it names the exact
  fix (`work_tracker_install` if nothing is up yet). Full decision tree:
  `load_skill(skill_name="work-tracker-setup")`.
- Claiming, working, or resolving an engineering-lane item →
  delegate to `work-tracker:work-executor`.
- Turning a raw user report into a properly-specified issue →
  delegate to `work-tracker:feedback-triage`.
- Full claim/custody procedure, including what to do after a reap →
  `load_skill(skill_name="claiming-work-safely")`.
- `doctor` output, the seam, or scheduling `reap`/`notify` →
  `load_skill(skill_name="work-tracker-operations")`.
