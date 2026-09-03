# Work Tracker — hazards that fail silently

You're one of several agents pulling from a shared work queue. First use in
a session, or any `work_*` call fails to connect: call `work_tracker_status`
before assuming a server is running — see "Where to go next" below.

Six things here fail **silently** if you get them wrong — no error, no undo:

1. **Claim only via `work_claim` / `work_status`; never list-then-pick.** The
   obvious approach — read the ready queue, choose an item, mark it yours —
   double-claimed in **2 of 8 measured trials**, and every losing agent
   still got exit 0. `work_claim` is the single atomic claim-and-custody
   operation. There is no other way to take an item.

2. **Custody is a liveness signal, not a timer — and neither end of it is
   automatic.** Idle time never costs you a claim; you may sit for hours
   awaiting a human's answer. Only an **unrenewed** custody signal does.
   Two consequences, both silent:
   - **Renewal is one-strike.** It runs in the background while your
     session process lives, but a single failed renewal ends renewal
     permanently — there is no retry on the next tick — and this session
     goes on believing it still holds the item. The only way to find out
     is `work_status`: a non-null `holding.custody_lost` means renewal
     stopped and the hold is on its way to being reclaimed. Check it
     before any long-running step and after any tool error.
   - **The TTL does not enforce itself.** After 15 minutes with no renewal
     a hold is merely *reclaim-eligible*; the out-of-band `reap` sweep is
     what actually reclaims it, and only where an operator has one
     installed and running. Expect a reclaim to land up to a sweep
     interval (300s by default) AFTER the TTL, and expect a dead agent's
     hold to persist indefinitely where no sweep runs — never wait on a
     stuck held item assuming it frees itself.

   `awaiting_human` (via `work_declare`) only suppresses a notification —
   it never exempts you from that clock.

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

6. **A reported write failure does NOT prove the write failed — treat it as
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
