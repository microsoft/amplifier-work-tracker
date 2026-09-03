# Work Tracker — hazards that fail silently

You're one of several agents pulling from a shared work queue. First use in
a session, or any `work_*` call fails to connect: call `work_tracker_status`
before assuming a server is running — see "Where to go next" below.

Seven things here fail **silently** if you get them wrong — no error, no undo:

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

6. **A reported write failure means the write did NOT land — but never
   blindly retry the same operation either; re-read first.** You're sharing
   a single-writer dolt server with every other agent's claims, renewals,
   and resolves. A write occasionally loses a serialization race and
   `work_resolve`/`work_file`/the CLI raises an error like "still
   conflicting after 8 retries." That specific error family (dolt/MySQL
   1213/1205/"serialization failure"/"try restarting transaction") means
   the transaction was aborted — by database guarantee, never partially
   committed — so the write genuinely did not happen. The unsafe move is
   resubmitting blind: for a non-idempotent write (creating a new item) a
   blind retry after an ambiguous-looking failure can leave a duplicate.
   The safe move is always the same: re-read the item first (`work_list`'s
   `item_id` form, or `get_readonly` — a read-only path that cannot itself
   conflict) to see its real current state, then decide whether the
   original operation still needs doing. A *reported success*, by contrast,
   is already independently verified — `resolve`/`unclaim` read the item
   back and raise rather than report success if the change didn't actually
   land — so this caution is specifically about what to do after a
   *reported failure*, not a general distrust of success responses.

7. **A published resolution is corrected by `work_reopen`, never by
   re-resolving.** `work_resolve` against an item that is ALREADY resolved
   is a no-op success **only when the text you send is byte-for-byte what
   is already stored** (the legitimate retry case — the payload says
   `"idempotent": true`). Sending *different* text now **fails non-zero and
   writes nothing**, showing you the stored text and yours side by side.
   Before this, that call exited 0 and echoed the OLD text back as if your
   correction had landed, and seven wrong resolutions shipped that way. To
   actually correct the record: `work_reopen(project, item_id, reason)` →
   `work_claim` → `work_resolve` with the corrected text. Reopening is
   deliberately explicit, and deliberately NOT idempotent (reopening an
   already-open item is an error): it clears `closed_at`, so the item
   re-lands on the correction date and every throughput roll-up moves by
   one item. That cost is shown to you (`closed_at_cleared`,
   `previous_closed_at`) rather than hidden.

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
