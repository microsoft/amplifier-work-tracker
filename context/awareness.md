# Work Tracker — hazards that fail silently

You're one of several agents pulling from a shared work queue. First use in
a session, or any `work_*` call fails to connect: call `work_tracker_status`
before assuming a server is running — see "Where to go next" below.

Five things here fail **silently** if you get them wrong — no error, no undo:

1. **Claim only via `work_claim` / `work_status`; never list-then-pick.** The
   obvious approach — read the ready queue, choose an item, mark it yours —
   double-claimed in **2 of 8 measured trials**, and every losing agent
   still got exit 0. `work_claim` is the single atomic claim-and-custody
   operation. There is no other way to take an item.

2. **Custody is a liveness signal, not a timer.** Idle time never costs you a
   claim — you may sit for hours awaiting a human's answer. Only an
   **unrenewed** custody signal does: 15 minutes without a renewal releases
   the item back to the queue. `awaiting_human` (via `work_declare`) only
   suppresses a notification — it never exempts you from that clock.

3. **An empty queue is a normal terminal outcome.** `work_claim` returning
   `claimed: null` means stop and report — not a signal to invent work or
   retry.

4. **Never speak to `bd` directly.** Every interaction goes through
   `work_claim` / `work_declare` / `work_resolve` / `work_status` /
   `work_file`, or the `amplifier-work-tracker` CLI. Nothing else knows Beads'
   field names or CLI shape, and that seam is what keeps upstream changes
   from silently corrupting parallel work.

5. **If `work_resolve`/`work_declare` refuses as reclaimed, stop.** Do not
   retry resolving or declaring that item — someone else may hold it now.
   `work_claim` can still be used afterward to pick up new work.

## Where to go next

- No server running, or unsure → `work_tracker_status`; it names the exact
  fix (`work_tracker_install` if nothing is up yet).
- Claiming, working, or resolving an engineering-lane item →
  delegate to `work-tracker:work-executor`.
- Full claim/custody procedure, including what to do after a reap →
  `load_skill(skill_name="claiming-work-safely")`.
- `doctor` output, the seam, or scheduling `reap`/`notify` →
  `load_skill(skill_name="work-tracker-operations")`.
- **Want to understand what an item is asking for before you decide whether
  to claim it? Pass `item_id` to `work_list` (or `--id` to the CLI's
  `list`).** This reads the full record -- title, status, holder,
  resolution, plus `acceptance`/`description`/`design`, everything
  `work_claim` returns -- with NO claim, no mutation, no custody touched.
  `work_claim` is not the only way to see an item's body; do not claim
  something just to read it.
